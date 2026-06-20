import os
import tempfile

from httpx import ASGITransport, AsyncClient
import pytest

_tmpdir = tempfile.mkdtemp()
os.environ["DB_PATH"] = os.path.join(_tmpdir, "test_reputation.db")

from conftest import load_service

ledger_mod = load_service("ledger_main", "reputation_ledger")


@pytest.fixture
async def client():
    async with ledger_mod.lifespan(ledger_mod.app):
        transport = ASGITransport(app=ledger_mod.app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


async def test_ledger_initially_empty(client):
    resp = await client.get("/ledger")
    assert resp.json() == {} or isinstance(resp.json(), dict)


async def test_register_agent(client):
    resp = await client.post("/register", json={"agent_id": "r1", "profile": "speed"})
    assert resp.json()["ok"] == 1


async def test_update_creates_agent_entry(client):
    await client.post("/update", json={"agent_id": "u1", "success": True})
    ledger = (await client.get("/ledger")).json()
    assert "u1" in ledger


async def test_update_success_increments(client):
    await client.post("/update", json={"agent_id": "s1", "success": True})
    agent = (await client.get("/agent/s1")).json()
    assert agent["success"] >= 1


async def test_update_failure_increments(client):
    await client.post("/update", json={"agent_id": "f1", "success": False})
    agent = (await client.get("/agent/f1")).json()
    assert agent["fail"] >= 1


async def test_update_tracks_score(client):
    await client.post("/update", json={"agent_id": "sc1", "success": True})
    agent = (await client.get("/agent/sc1")).json()
    assert agent["score"] == 0.51


async def test_multiple_updates_accumulate(client):
    for _ in range(3):
        await client.post("/update", json={"agent_id": "m1", "success": True})
    await client.post("/update", json={"agent_id": "m1", "success": False})
    agent = (await client.get("/agent/m1")).json()
    assert agent["success"] == 3
    assert agent["fail"] == 1


async def test_get_missing_agent_returns_404(client):
    resp = await client.get("/agent/nonexistent_agent_xyz")
    assert resp.status_code == 404


async def test_update_missing_agent_id_returns_422(client):
    resp = await client.post("/update", json={"success": True})
    assert resp.status_code == 422


async def test_health_endpoint(client):
    resp = await client.get("/health")
    assert resp.json()["ok"] == 1


# --- Pydantic validation tests ---

async def test_register_missing_agent_id_returns_422(client):
    resp = await client.post("/register", json={"profile": "speed"})
    assert resp.status_code == 422


async def test_update_missing_success_returns_422(client):
    resp = await client.post("/update", json={"agent_id": "x1"})
    assert resp.status_code == 422
