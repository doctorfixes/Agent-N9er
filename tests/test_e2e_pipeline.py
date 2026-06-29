"""End-to-end tests that exercise multiple services in sequence,
verifying data flows correctly through the pipeline without mocking
the downstream services (only the inter-service HTTP calls are mocked)."""

import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import aiosqlite
from httpx import ASGITransport, AsyncClient
import pytest

from conftest import load_service

_tmpdir = tempfile.mkdtemp()

os.environ.setdefault("ORCHESTRATOR_DB_PATH", os.path.join(_tmpdir, "e2e_orch.db"))

norm = load_service("e2e_norm", "normalization_service")
ranking = load_service("e2e_ranking", "ranking_engine")
orch = load_service("e2e_orch", "orchestrator")
orch.DB_PATH = os.path.join(_tmpdir, "e2e_orch.db")

_mp_db = os.path.join(_tmpdir, "e2e_marketplace.db")
marketplace = load_service("e2e_marketplace", "bidding_marketplace")
marketplace.DB_PATH = _mp_db

_exec_db = os.path.join(_tmpdir, "e2e_execution.db")
execution = load_service("e2e_execution", "agent_execution")
execution.DB_PATH = _exec_db

_rep_db = os.path.join(_tmpdir, "e2e_reputation.db")
reputation = load_service("e2e_reputation", "reputation_ledger")
reputation.DB_PATH = _rep_db


@pytest.fixture(autouse=True)
async def reset():
    async with orch._agents_lock:
        orch.registered_agents.clear()
    yield
    async with orch._agents_lock:
        orch.registered_agents.clear()


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
async def exec_client():
    async with execution.lifespan(execution.app):
        transport = ASGITransport(app=execution.app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


@pytest.fixture
async def rep_client():
    async with reputation.lifespan(reputation.app):
        transport = ASGITransport(app=reputation.app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


class TestNormToRankFlow:
    """Verify data flows correctly from normalization to ranking."""

    async def test_normalized_output_valid_for_ranking(self, norm_client, ranking_client):
        norm_resp = await norm_client.post("/normalize", json={
            "objective": "Deploy critical hotfix to production servers"
        })
        normalized = norm_resp.json()

        assert "id" in normalized
        assert "objective" in normalized
        assert "category" in normalized
        assert "tier" in normalized

        rank_resp = await ranking_client.post("/rank", json=normalized)
        ranked = rank_resp.json()

        assert ranked["id"] == normalized["id"]
        assert ranked["priority_score"] > 0
        assert ranked["category"] == normalized["category"]

    async def test_urgent_task_gets_high_priority(self, norm_client, ranking_client):
        norm_resp = await norm_client.post("/normalize", json={
            "objective": "urgent critical bug fix deploy ASAP"
        })
        normalized = norm_resp.json()

        rank_resp = await ranking_client.post("/rank", json=normalized)
        ranked = rank_resp.json()

        assert ranked["priority_score"] > 5.0

    async def test_vague_task_gets_low_priority(self, norm_client, ranking_client):
        norm_resp = await norm_client.post("/normalize", json={
            "objective": "stuff"
        })
        normalized = norm_resp.json()

        rank_resp = await ranking_client.post("/rank", json=normalized)
        ranked = rank_resp.json()

        assert ranked["priority_score"] < 3.0


class TestMarketplaceFlow:
    """Verify publish → bid → award flow in the marketplace."""

    async def test_full_marketplace_cycle(self, mp_client):
        pub_resp = await mp_client.post("/publish", json={
            "id": "e2e-t1", "objective": "Test task", "priority_score": 5.0
        })
        assert pub_resp.json()["ok"] == 1

        feed = (await mp_client.get("/feed")).json()
        assert any(t["id"] == "e2e-t1" for t in feed)

        for agent_id, conf in [("fast-agent", 0.7), ("smart-agent", 0.95), ("cheap-agent", 0.5)]:
            await mp_client.post("/bid", json={
                "task_id": "e2e-t1", "agent_id": agent_id, "confidence": conf,
                "require_approval": False,
            })

        bids = (await mp_client.get("/bids/e2e-t1")).json()
        assert len(bids) == 3

        award = (await mp_client.post("/award/e2e-t1")).json()
        assert award["winner"]["agent_id"] == "smart-agent"
        assert award["winner"]["confidence"] == 0.95

        await mp_client.post("/complete/e2e-t1", json={"success": True})

        feed = (await mp_client.get("/feed")).json()
        task = next(t for t in feed if t["id"] == "e2e-t1")
        assert task["status"] == "completed"

    async def test_audit_trail_complete(self, mp_client):
        await mp_client.post("/publish", json={
            "id": "e2e-aud", "objective": "Audit trail test"
        })
        await mp_client.post("/bid", json={
            "task_id": "e2e-aud", "agent_id": "a1", "confidence": 0.8,
            "require_approval": False,
        })
        await mp_client.post("/award/e2e-aud")
        await mp_client.post("/complete/e2e-aud", json={"success": True})

        audit = (await mp_client.get("/audit")).json()
        task_entries = [e for e in audit if e["entity_id"] == "e2e-aud"]

        actions = {e["action"] for e in task_entries}
        assert "publish" in actions
        assert "bid" in actions
        assert "award" in actions
        assert "complete" in actions


class TestExecutionAndReputation:
    """Verify execution results feed into reputation updates."""

    async def test_execution_records_in_history(self, exec_client):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        with patch.object(execution, "retry_request", AsyncMock(return_value=mock_resp)):
            resp = await exec_client.post("/execute", json={
                "task_id": "e2e-exec1", "agent_id": "agent-alpha", "confidence": 0.9
            })

        data = resp.json()
        assert data["ok"] == 1
        assert data["task_id"] == "e2e-exec1"
        assert data["agent_id"] == "agent-alpha"

        history = (await exec_client.get("/history", params={"agent_id": "agent-alpha"})).json()
        assert len(history) >= 1
        assert history[0]["task_id"] == "e2e-exec1"

    async def test_reputation_tracks_wins_and_losses(self, rep_client):
        await rep_client.post("/register", json={"agent_id": "e2e-rep", "profile": "tester"})

        for _ in range(5):
            await rep_client.post("/update", json={"agent_id": "e2e-rep", "success": True})
        for _ in range(2):
            await rep_client.post("/update", json={"agent_id": "e2e-rep", "success": False})

        agent = (await rep_client.get("/agent/e2e-rep")).json()
        assert agent["success"] == 5
        assert agent["fail"] == 2
        assert agent["score"] > 0.5

        ledger = (await rep_client.get("/ledger")).json()
        assert "e2e-rep" in ledger


class TestCrossCuttingConcerns:
    """Verify shared infrastructure works across services."""

    async def test_all_services_respond_to_health(
        self, norm_client, ranking_client, mp_client, exec_client, rep_client
    ):
        for name, client in [
            ("normalization", norm_client),
            ("ranking", ranking_client),
            ("marketplace", mp_client),
            ("execution", exec_client),
            ("reputation", rep_client),
        ]:
            resp = await client.get("/health")
            data = resp.json()
            assert data["ok"] == 1, f"{name} health check failed"

    async def test_classification_influences_ranking(self, norm_client, ranking_client):
        code_resp = await norm_client.post("/normalize", json={
            "objective": "Implement REST API endpoint for user authentication"
        })
        code_norm = code_resp.json()
        assert code_norm["category"] == "code_generation"
        assert code_norm["tier"] == "highest_leverage"

        code_rank = (await ranking_client.post("/rank", json=code_norm)).json()

        generic_resp = await norm_client.post("/normalize", json={
            "objective": "misc"
        })
        generic_norm = generic_resp.json()
        generic_rank = (await ranking_client.post("/rank", json=generic_norm)).json()

        assert code_rank["priority_score"] > generic_rank["priority_score"]
