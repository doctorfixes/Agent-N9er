from unittest.mock import patch, AsyncMock, MagicMock

from httpx import ASGITransport, AsyncClient
import pytest

from conftest import load_service

execution = load_service("execution_main", "agent_execution")


@pytest.fixture(autouse=True)
def reset_executions():
    execution.executions.clear()
    yield
    execution.executions.clear()


@pytest.fixture
def client():
    transport = ASGITransport(app=execution.app)
    return AsyncClient(transport=transport, base_url="http://test")


def _mock_reputation():
    mock_client = AsyncMock()
    mock_client.post = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return patch.object(execution.httpx, "AsyncClient", return_value=mock_client)


async def test_execute_returns_result(client):
    with _mock_reputation():
        resp = await client.post("/execute", json={"task_id": "t1", "agent_id": "a1", "confidence": 0.9})
    data = resp.json()
    assert data["ok"] == 1
    assert "success" in data
    assert "duration" in data


async def test_execute_missing_fields_returns_422(client):
    resp = await client.post("/execute", json={"task_id": "t1"})
    assert resp.status_code == 422


async def test_history_endpoint(client):
    with _mock_reputation():
        await client.post("/execute", json={"task_id": "t1", "agent_id": "a1", "confidence": 0.9})
    history = (await client.get("/history")).json()
    assert len(history) == 1


async def test_history_filter_by_agent(client):
    with _mock_reputation():
        await client.post("/execute", json={"task_id": "t1", "agent_id": "a1", "confidence": 0.9})
        await client.post("/execute", json={"task_id": "t2", "agent_id": "a2", "confidence": 0.8})
    history = (await client.get("/history", params={"agent_id": "a1"})).json()
    assert len(history) == 1
    assert history[0]["agent_id"] == "a1"


async def test_health_endpoint(client):
    resp = await client.get("/health")
    assert resp.json()["ok"] == 1
