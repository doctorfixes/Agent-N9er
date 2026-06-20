from httpx import ASGITransport, AsyncClient
import pytest

from conftest import load_service

execution = load_service("execution_main", "agent_execution")


@pytest.fixture
def client():
    transport = ASGITransport(app=execution.app)
    return AsyncClient(transport=transport, base_url="http://test")


async def test_execute_returns_ok(client):
    resp = await client.post("/execute", json={"task_id": "t1", "agent_id": "a1"})
    assert resp.json()["ok"] == 1


async def test_execute_accepts_any_payload(client):
    resp = await client.post("/execute", json={"arbitrary": "data"})
    assert resp.status_code == 200
