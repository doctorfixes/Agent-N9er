import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import ASGITransport, AsyncClient
import pytest

from conftest import load_service

_tmpdir = tempfile.mkdtemp()
os.environ.setdefault("ORCHESTRATOR_DB_PATH", os.path.join(_tmpdir, "test_val_orch.db"))

norm = load_service("val_norm", "normalization_service")
ranking = load_service("val_ranking", "ranking_engine")

_mp_db = os.path.join(_tmpdir, "test_val_marketplace.db")
os.environ["DB_PATH"] = _mp_db
marketplace = load_service("val_marketplace", "bidding_marketplace")
marketplace.DB_PATH = _mp_db

orch = load_service("val_orch", "orchestrator")
orch.DB_PATH = os.path.join(_tmpdir, "test_val_orch.db")


@pytest.fixture
def norm_client():
    transport = ASGITransport(app=norm.app)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest.fixture
def ranking_client():
    transport = ASGITransport(app=ranking.app)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest.fixture
async def mp_client():
    async with marketplace.lifespan(marketplace.app):
        transport = ASGITransport(app=marketplace.app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


@pytest.fixture
async def orch_client():
    async with orch.lifespan(orch.app):
        transport = ASGITransport(app=orch.app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


@pytest.fixture(autouse=True)
async def reset_orch():
    async with orch._agents_lock:
        orch.registered_agents.clear()
    yield
    async with orch._agents_lock:
        orch.registered_agents.clear()


# --- Unicode and special characters ---

class TestUnicodeHandling:
    async def test_normalize_unicode_objective(self, norm_client):
        resp = await norm_client.post("/normalize", json={"objective": "翻译这个文档到英语"})
        data = resp.json()
        assert data["objective"] == "翻译这个文档到英语"
        assert data["id"]

    async def test_normalize_emoji_objective(self, norm_client):
        resp = await norm_client.post("/normalize", json={"objective": "Fix 🐛 in login 🔐"})
        data = resp.json()
        assert data["objective"] == "Fix 🐛 in login 🔐"

    async def test_normalize_mixed_scripts(self, norm_client):
        resp = await norm_client.post("/normalize", json={
            "objective": "Résumé for café naïve señor"
        })
        assert resp.status_code == 200
        assert resp.json()["objective"] == "Résumé for café naïve señor"

    async def test_ranking_unicode_objective(self, ranking_client):
        resp = await ranking_client.post("/rank", json={
            "id": "u1", "objective": "urgent: デプロイメントを修正する"
        })
        assert resp.status_code == 200
        assert resp.json()["priority_score"] > 0

    async def test_marketplace_unicode_objective(self, mp_client):
        resp = await mp_client.post("/publish", json={
            "id": "u1", "objective": "建立新的API端点"
        })
        assert resp.json()["ok"] == 1
        feed = (await mp_client.get("/feed")).json()
        assert any(t["objective"] == "建立新的API端点" for t in feed)

    async def test_agent_register_unicode_profile(self, orch_client):
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=MagicMock(raise_for_status=MagicMock()))
        with patch.object(orch.httpx, "AsyncClient", return_value=mock_client):
            resp = await orch_client.post("/agents/register", json={
                "agent_id": "ünïcödë-ägent", "profile": "速度型"
            })
        assert resp.json()["ok"] == 1


# --- Very long strings ---

class TestLongInputs:
    async def test_normalize_very_long_objective(self, norm_client):
        long_obj = "a" * 10000
        resp = await norm_client.post("/normalize", json={"objective": long_obj})
        assert resp.status_code == 200
        assert len(resp.json()["objective"]) == 10000

    async def test_ranking_long_objective(self, ranking_client):
        long_obj = "urgent " * 1000
        resp = await ranking_client.post("/rank", json={"id": "long1", "objective": long_obj})
        assert resp.status_code == 200
        assert resp.json()["priority_score"] > 0

    async def test_marketplace_long_objective(self, mp_client):
        long_obj = "x" * 5000
        resp = await mp_client.post("/publish", json={"id": "long1", "objective": long_obj})
        assert resp.json()["ok"] == 1

    async def test_normalize_deeply_nested_inputs(self, norm_client):
        nested = {"level": 1}
        current = nested
        for i in range(2, 20):
            current["child"] = {"level": i}
            current = current["child"]
        resp = await norm_client.post("/normalize", json={
            "objective": "nested test", "inputs": nested
        })
        assert resp.status_code == 200
        assert resp.json()["inputs"]["child"]["child"]["level"] == 3

    async def test_normalize_large_inputs_dict(self, norm_client):
        big_inputs = {f"key_{i}": f"value_{i}" for i in range(200)}
        resp = await norm_client.post("/normalize", json={
            "objective": "big inputs", "inputs": big_inputs
        })
        assert resp.status_code == 200
        assert len(resp.json()["inputs"]) == 200


# --- Empty and boundary values ---

class TestBoundaryValues:
    async def test_normalize_empty_everything(self, norm_client):
        resp = await norm_client.post("/normalize", json={})
        data = resp.json()
        assert data["objective"] == ""
        assert data["inputs"] == {}
        assert data["source"] == "manual"

    async def test_ranking_min_score(self, ranking_client):
        resp = await ranking_client.post("/rank", json={"id": "min1", "objective": ""})
        data = resp.json()
        assert data["priority_score"] >= 0

    async def test_marketplace_zero_priority(self, mp_client):
        resp = await mp_client.post("/publish", json={
            "id": "z1", "objective": "zero", "priority_score": 0.0
        })
        assert resp.json()["ok"] == 1

    async def test_marketplace_bid_boundary_confidence(self, mp_client):
        await mp_client.post("/publish", json={"id": "bc1", "objective": "test"})
        resp_zero = await mp_client.post("/bid", json={
            "task_id": "bc1", "agent_id": "a1", "confidence": 0.0
        })
        assert resp_zero.json()["ok"] == 1

        resp_one = await mp_client.post("/bid", json={
            "task_id": "bc1", "agent_id": "a2", "confidence": 1.0
        })
        assert resp_one.json()["ok"] == 1

    async def test_marketplace_bid_above_one_rejected(self, mp_client):
        await mp_client.post("/publish", json={"id": "bv1", "objective": "test"})
        resp = await mp_client.post("/bid", json={
            "task_id": "bv1", "agent_id": "a1", "confidence": 1.001
        })
        assert resp.status_code == 422

    async def test_marketplace_bid_below_zero_rejected(self, mp_client):
        await mp_client.post("/publish", json={"id": "bv2", "objective": "test"})
        resp = await mp_client.post("/bid", json={
            "task_id": "bv2", "agent_id": "a1", "confidence": -0.001
        })
        assert resp.status_code == 422

    async def test_marketplace_bid_zero_price(self, mp_client):
        await mp_client.post("/publish", json={"id": "zp1", "objective": "test"})
        resp = await mp_client.post("/bid", json={
            "task_id": "zp1", "agent_id": "a1", "price": 0.0
        })
        assert resp.json()["ok"] == 1

    async def test_marketplace_bid_zero_eta(self, mp_client):
        await mp_client.post("/publish", json={"id": "ze1", "objective": "test"})
        resp = await mp_client.post("/bid", json={
            "task_id": "ze1", "agent_id": "a1", "eta_minutes": 0
        })
        assert resp.json()["ok"] == 1

    async def test_agent_register_boundary_confidence(self, orch_client):
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=MagicMock(raise_for_status=MagicMock()))
        with patch.object(orch.httpx, "AsyncClient", return_value=mock_client):
            resp = await orch_client.post("/agents/register", json={
                "agent_id": "bound1", "confidence": 0.0
            })
        assert resp.json()["ok"] == 1
        with patch.object(orch.httpx, "AsyncClient", return_value=mock_client):
            resp = await orch_client.post("/agents/register", json={
                "agent_id": "bound2", "confidence": 1.0
            })
        assert resp.json()["ok"] == 1

    async def test_feed_limit_boundary(self, mp_client):
        resp = await mp_client.get("/feed", params={"limit": 1})
        assert resp.status_code == 200
        resp = await mp_client.get("/feed", params={"limit": 1000})
        assert resp.status_code == 200

    async def test_feed_limit_too_high_rejected(self, mp_client):
        resp = await mp_client.get("/feed", params={"limit": 1001})
        assert resp.status_code == 422

    async def test_feed_limit_zero_rejected(self, mp_client):
        resp = await mp_client.get("/feed", params={"limit": 0})
        assert resp.status_code == 422


# --- Special characters and injection attempts ---

class TestSpecialCharacters:
    async def test_normalize_html_in_objective(self, norm_client):
        resp = await norm_client.post("/normalize", json={
            "objective": '<script>alert("xss")</script>'
        })
        assert resp.status_code == 200
        assert resp.json()["objective"] == '<script>alert("xss")</script>'

    async def test_ranking_sql_injection_in_objective(self, ranking_client):
        resp = await ranking_client.post("/rank", json={
            "id": "sql1", "objective": "'; DROP TABLE tasks; --"
        })
        assert resp.status_code == 200

    async def test_marketplace_sql_injection_in_id(self, mp_client):
        resp = await mp_client.post("/publish", json={
            "id": "'; DROP TABLE tasks; --", "objective": "test"
        })
        assert resp.json()["ok"] == 1
        feed = (await mp_client.get("/feed")).json()
        assert any(t["id"] == "'; DROP TABLE tasks; --" for t in feed)

    async def test_marketplace_bid_nonexistent_task(self, mp_client):
        resp = await mp_client.post("/bid", json={
            "task_id": "nonexistent", "agent_id": "a1", "confidence": 0.5
        })
        assert resp.status_code == 404

    async def test_marketplace_award_no_bids(self, mp_client):
        await mp_client.post("/publish", json={"id": "nb1", "objective": "test"})
        resp = await mp_client.post("/award/nb1")
        assert resp.status_code == 404

    async def test_normalize_null_bytes_in_objective(self, norm_client):
        resp = await norm_client.post("/normalize", json={
            "objective": "test\x00embedded\x00nulls"
        })
        assert resp.status_code == 200

    async def test_ranking_newlines_in_objective(self, ranking_client):
        resp = await ranking_client.post("/rank", json={
            "id": "nl1", "objective": "line1\nline2\nurgent line3"
        })
        assert resp.status_code == 200
        assert resp.json()["priority_score"] > 0


# --- Type coercion and wrong types ---

class TestWrongTypes:
    async def test_normalize_number_as_objective(self, norm_client):
        resp = await norm_client.post("/normalize", json={"objective": 12345})
        assert resp.status_code == 422

    async def test_normalize_boolean_as_objective(self, norm_client):
        resp = await norm_client.post("/normalize", json={"objective": True})
        assert resp.status_code == 422

    async def test_normalize_list_as_inputs(self, norm_client):
        resp = await norm_client.post("/normalize", json={
            "objective": "test", "inputs": [1, 2, 3]
        })
        assert resp.status_code == 422

    async def test_ranking_missing_objective(self, ranking_client):
        resp = await ranking_client.post("/rank", json={"id": "mo1"})
        assert resp.status_code == 200
        assert resp.json()["priority_score"] >= 0

    async def test_marketplace_publish_empty_id(self, mp_client):
        resp = await mp_client.post("/publish", json={"id": "", "objective": "test"})
        assert resp.status_code == 200

    async def test_marketplace_publish_whitespace_id(self, mp_client):
        resp = await mp_client.post("/publish", json={"id": "   ", "objective": "test"})
        assert resp.status_code == 200


# --- Audit log integrity ---

class TestAuditLog:
    async def test_publish_creates_audit_entry(self, mp_client):
        await mp_client.post("/publish", json={"id": "aud1", "objective": "audit test"})
        log = (await mp_client.get("/audit")).json()
        publish_entries = [e for e in log if e["entity_id"] == "aud1" and e["action"] == "publish"]
        assert len(publish_entries) == 1

    async def test_bid_creates_audit_entry(self, mp_client):
        await mp_client.post("/publish", json={"id": "aud2", "objective": "test"})
        await mp_client.post("/bid", json={"task_id": "aud2", "agent_id": "a1", "confidence": 0.5})
        log = (await mp_client.get("/audit")).json()
        bid_entries = [e for e in log if e["entity_id"] == "aud2" and e["action"] == "bid"]
        assert len(bid_entries) == 1
        assert "agent=a1" in bid_entries[0]["detail"]

    async def test_award_creates_audit_entry(self, mp_client):
        await mp_client.post("/publish", json={"id": "aud3", "objective": "test"})
        await mp_client.post("/bid", json={"task_id": "aud3", "agent_id": "a1", "confidence": 0.8})
        await mp_client.post("/award/aud3")
        log = (await mp_client.get("/audit")).json()
        award_entries = [e for e in log if e["entity_id"] == "aud3" and e["action"] == "award"]
        assert len(award_entries) == 1

    async def test_audit_pagination(self, mp_client):
        for i in range(5):
            await mp_client.post("/publish", json={"id": f"apg{i}", "objective": f"task {i}"})
        log = (await mp_client.get("/audit", params={"limit": 2})).json()
        assert len(log) == 2
        log2 = (await mp_client.get("/audit", params={"limit": 2, "offset": 2})).json()
        assert len(log2) == 2
        assert log[0]["id"] != log2[0]["id"]
