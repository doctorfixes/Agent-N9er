import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import aiosqlite
from httpx import ASGITransport, AsyncClient
import pytest

_tmpdir = tempfile.mkdtemp()
os.environ["ORCHESTRATOR_DB_PATH"] = os.path.join(_tmpdir, "test_orchestrator.db")

from conftest import load_service

orch = load_service("orch_main", "orchestrator")


@pytest.fixture(autouse=True)
async def reset_agents():
    async with orch._agents_lock:
        orch.registered_agents.clear()
    try:
        async with aiosqlite.connect(orch.DB_PATH) as db:
            await db.execute("DELETE FROM agents")
            await db.commit()
    except Exception:
        pass
    yield
    async with orch._agents_lock:
        orch.registered_agents.clear()


@pytest.fixture
async def client():
    async with orch.lifespan(orch.app):
        transport = ASGITransport(app=orch.app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


def _make_response(data, status_code=200):
    resp = MagicMock()
    resp.json.return_value = data
    resp.status_code = status_code
    resp.raise_for_status = MagicMock()
    return resp


def _mock_pipeline():
    normalized = {"id": "n1", "objective": "test task", "inputs": {}, "source": "manual", "raw": {}}
    ranked = {"id": "n1", "priority_score": 0.9}

    async def mock_post(url, **kwargs):
        if "normalize" in url:
            return _make_response(normalized)
        elif "rank" in url:
            return _make_response(ranked)
        elif "publish" in url:
            return _make_response({"ok": 1})
        elif "register" in url:
            return _make_response({"ok": 1})
        elif "bid" in url:
            return _make_response({"ok": 1})
        elif "award" in url:
            return _make_response({"ok": 1, "winner": {"agent_id": "a1", "confidence": 0.8}})
        elif "execute" in url:
            return _make_response({"ok": 1, "success": True, "duration": 3.5})
        elif "complete" in url:
            return _make_response({"ok": 1})
        return _make_response({})

    mock_client = AsyncMock()
    mock_client.post = mock_post
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client, normalized, ranked


async def test_pipeline_calls_all_services(client):
    mock_client, normalized, ranked = _mock_pipeline()

    with patch.object(orch.httpx, "AsyncClient", return_value=mock_client):
        resp = await client.post("/pipeline", json={"objective": "test task"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "task_published"
    assert data["normalized"] == normalized
    assert data["ranked"] == ranked


async def test_register_agent(client):
    mock_client, _, _ = _mock_pipeline()
    with patch.object(orch.httpx, "AsyncClient", return_value=mock_client):
        resp = await client.post("/agents/register", json={"agent_id": "a1", "profile": "speed"})
    assert resp.json()["ok"] == 1
    assert "a1" in orch.registered_agents


async def test_full_pipeline(client):
    async with orch._agents_lock:
        orch.registered_agents["a1"] = {
            "agent_id": "a1", "profile": "speed", "specialization": "generalist",
            "price": 0.1, "eta_minutes": 2, "confidence": 0.8,
        }

    mock_client, _, _ = _mock_pipeline()
    with patch.object(orch.httpx, "AsyncClient", return_value=mock_client):
        resp = await client.post("/pipeline/full", json={"objective": "test"})

    data = resp.json()
    assert data["status"] in ("completed", "failed")
    assert "winner" in data
    assert "execution" in data


async def test_full_pipeline_no_agents(client):
    mock_client, _, _ = _mock_pipeline()
    with patch.object(orch.httpx, "AsyncClient", return_value=mock_client):
        resp = await client.post("/pipeline/full", json={"objective": "test"})
    assert resp.json()["status"] == "task_published_no_agents"


async def test_health_endpoint(client):
    resp = await client.get("/health")
    assert resp.json()["ok"] == 1


async def test_list_agents(client):
    async with orch._agents_lock:
        orch.registered_agents["a1"] = {"agent_id": "a1", "profile": "speed"}
    resp = await client.get("/agents")
    assert "a1" in resp.json()


# --- Pydantic validation tests ---

async def test_register_agent_missing_id_returns_422(client):
    resp = await client.post("/agents/register", json={"profile": "speed"})
    assert resp.status_code == 422


async def test_register_agent_uses_defaults(client):
    mock_client, _, _ = _mock_pipeline()
    with patch.object(orch.httpx, "AsyncClient", return_value=mock_client):
        resp = await client.post("/agents/register", json={"agent_id": "def1"})
    data = orch.registered_agents["def1"]
    assert data["profile"] == "unknown"
    assert data["confidence"] == 0.5
