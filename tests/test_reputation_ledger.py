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


# --- Client rating tests ---

async def test_rate_agent_5_stars(client):
    await client.post("/register", json={"agent_id": "rated1", "profile": "test"})
    resp = await client.post("/rate", json={"agent_id": "rated1", "rating": 5, "prospect_id": "p1"})
    data = resp.json()
    assert data["ok"] == 1
    assert data["rating"] == 5
    assert data["avg_rating"] == 5.0
    assert data["total_ratings"] == 1


async def test_rate_agent_avg_calculation(client):
    await client.post("/register", json={"agent_id": "rated2", "profile": "test"})
    await client.post("/rate", json={"agent_id": "rated2", "rating": 5})
    await client.post("/rate", json={"agent_id": "rated2", "rating": 3})
    resp = await client.post("/rate", json={"agent_id": "rated2", "rating": 1})
    data = resp.json()
    assert data["total_ratings"] == 3
    assert data["avg_rating"] == 3.0


async def test_rate_invalid_rating_rejected(client):
    await client.post("/register", json={"agent_id": "rated3", "profile": "test"})
    resp = await client.post("/rate", json={"agent_id": "rated3", "rating": 6})
    assert resp.status_code == 422
    resp = await client.post("/rate", json={"agent_id": "rated3", "rating": 0})
    assert resp.status_code == 422


async def test_rate_nonexistent_agent_404(client):
    resp = await client.post("/rate", json={"agent_id": "ghost", "rating": 5})
    assert resp.status_code == 404


async def test_rate_adjusts_score_up(client):
    await client.post("/register", json={"agent_id": "rated4", "profile": "test"})
    resp = await client.post("/rate", json={"agent_id": "rated4", "rating": 5})
    assert resp.json()["score"] > 0.5


async def test_rate_adjusts_score_down(client):
    await client.post("/register", json={"agent_id": "rated5", "profile": "test"})
    resp = await client.post("/rate", json={"agent_id": "rated5", "rating": 1})
    assert resp.json()["score"] < 0.5


async def test_get_agent_ratings(client):
    await client.post("/register", json={"agent_id": "rated6", "profile": "test"})
    await client.post("/rate", json={"agent_id": "rated6", "rating": 4, "comment": "Good work"})
    resp = await client.get("/agent/rated6/ratings")
    data = resp.json()
    assert len(data) == 1
    assert data[0]["rating"] == 4
    assert data[0]["comment"] == "Good work"


async def test_agent_includes_rating_fields(client):
    await client.post("/register", json={"agent_id": "rated7", "profile": "test"})
    await client.post("/rate", json={"agent_id": "rated7", "rating": 4})
    agent = (await client.get("/agent/rated7")).json()
    assert agent["total_ratings"] == 1
    assert agent["avg_rating"] == 4.0
    assert agent["jobs_completed"] == 1


# --- Nickname tests ---

async def test_register_with_nickname(client):
    resp = await client.post("/register", json={"agent_id": "nick1", "profile": "test", "nickname": "ShadowRunner"})
    assert resp.json()["ok"] == 1
    assert resp.json()["nickname"] == "ShadowRunner"
    agent = (await client.get("/agent/nick1")).json()
    assert agent["nickname"] == "ShadowRunner"


async def test_set_nickname(client):
    await client.post("/register", json={"agent_id": "nick2", "profile": "test"})
    resp = await client.patch("/agent/nick2/nickname", json={"nickname": "ByteWolf"})
    assert resp.json()["ok"] == 1
    assert resp.json()["nickname"] == "ByteWolf"
    agent = (await client.get("/agent/nick2")).json()
    assert agent["nickname"] == "ByteWolf"


async def test_update_nickname(client):
    await client.post("/register", json={"agent_id": "nick3", "profile": "test", "nickname": "OldName"})
    await client.patch("/agent/nick3/nickname", json={"nickname": "NewName"})
    agent = (await client.get("/agent/nick3")).json()
    assert agent["nickname"] == "NewName"


async def test_nickname_too_long_rejected(client):
    await client.post("/register", json={"agent_id": "nick4", "profile": "test"})
    resp = await client.patch("/agent/nick4/nickname", json={"nickname": "A" * 33})
    assert resp.status_code == 422


async def test_nickname_nonexistent_agent(client):
    resp = await client.patch("/agent/ghost/nickname", json={"nickname": "Phantom"})
    assert resp.status_code == 404


async def test_nickname_preserved_after_update(client):
    await client.post("/register", json={"agent_id": "nick5", "profile": "test", "nickname": "Keeper"})
    await client.post("/update", json={"agent_id": "nick5", "success": True})
    agent = (await client.get("/agent/nick5")).json()
    assert agent["nickname"] == "Keeper"
    assert agent["success"] == 1


async def test_nickname_in_ledger(client):
    await client.post("/register", json={"agent_id": "nick6", "profile": "test", "nickname": "TopDog"})
    ledger = (await client.get("/ledger")).json()
    assert ledger["nick6"]["nickname"] == "TopDog"


async def test_empty_nickname_allowed(client):
    await client.post("/register", json={"agent_id": "nick7", "profile": "test"})
    agent = (await client.get("/agent/nick7")).json()
    assert agent["nickname"] == ""
