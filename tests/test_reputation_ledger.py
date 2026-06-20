from httpx import ASGITransport, AsyncClient
import pytest

from conftest import load_service

ledger_mod = load_service("ledger_main", "reputation_ledger")


@pytest.fixture(autouse=True)
def reset_ledger():
    ledger_mod.ledger.clear()
    yield
    ledger_mod.ledger.clear()


@pytest.fixture
def client():
    transport = ASGITransport(app=ledger_mod.app)
    return AsyncClient(transport=transport, base_url="http://test")


async def test_ledger_initially_empty(client):
    resp = await client.get("/ledger")
    assert resp.json() == {}


async def test_update_creates_agent_entry(client):
    await client.post("/update", json={"agent_id": "a1", "success": True})
    ledger = (await client.get("/ledger")).json()
    assert "a1" in ledger


async def test_update_success_increments(client):
    await client.post("/update", json={"agent_id": "a1", "success": True})
    ledger = (await client.get("/ledger")).json()
    assert ledger["a1"]["success"] == 1
    assert ledger["a1"]["fail"] == 0


async def test_update_failure_increments(client):
    await client.post("/update", json={"agent_id": "a1", "success": False})
    ledger = (await client.get("/ledger")).json()
    assert ledger["a1"]["success"] == 0
    assert ledger["a1"]["fail"] == 1


async def test_multiple_updates_accumulate(client):
    for _ in range(3):
        await client.post("/update", json={"agent_id": "a1", "success": True})
    await client.post("/update", json={"agent_id": "a1", "success": False})
    ledger = (await client.get("/ledger")).json()
    assert ledger["a1"]["success"] == 3
    assert ledger["a1"]["fail"] == 1


async def test_separate_agents_tracked_independently(client):
    await client.post("/update", json={"agent_id": "a1", "success": True})
    await client.post("/update", json={"agent_id": "a2", "success": False})
    ledger = (await client.get("/ledger")).json()
    assert ledger["a1"]["success"] == 1
    assert ledger["a2"]["fail"] == 1
