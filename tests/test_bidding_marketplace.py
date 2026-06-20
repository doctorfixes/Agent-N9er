import os
import tempfile

from httpx import ASGITransport, AsyncClient
import pytest

# Point DB at a temp file before importing the module
_tmpdir = tempfile.mkdtemp()
os.environ["DB_PATH"] = os.path.join(_tmpdir, "test_marketplace.db")

from conftest import load_service

marketplace = load_service("marketplace_main", "bidding_marketplace")


@pytest.fixture
async def client():
    async with marketplace.lifespan(marketplace.app):
        transport = ASGITransport(app=marketplace.app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


async def test_feed_initially_empty(client):
    resp = await client.get("/feed")
    assert resp.json() == []


async def test_publish_adds_task(client):
    task = {"id": "t1", "objective": "test", "priority_score": 0.5}
    resp = await client.post("/publish", json=task)
    assert resp.json()["ok"] == 1


async def test_feed_returns_published_tasks(client):
    await client.post("/publish", json={"id": "t10", "objective": "first"})
    await client.post("/publish", json={"id": "t11", "objective": "second"})
    feed = (await client.get("/feed")).json()
    ids = [t["id"] for t in feed]
    assert "t10" in ids
    assert "t11" in ids


async def test_publish_sets_status_open(client):
    await client.post("/publish", json={"id": "t20", "objective": "x"})
    feed = (await client.get("/feed")).json()
    task = next(t for t in feed if t["id"] == "t20")
    assert task["status"] == "open"


async def test_submit_bid(client):
    await client.post("/publish", json={"id": "t30", "objective": "x"})
    resp = await client.post("/bid", json={"task_id": "t30", "agent_id": "a1", "confidence": 0.8})
    assert resp.json()["ok"] == 1


async def test_get_bids(client):
    await client.post("/publish", json={"id": "t40", "objective": "x"})
    await client.post("/bid", json={"task_id": "t40", "agent_id": "a1", "confidence": 0.8})
    await client.post("/bid", json={"task_id": "t40", "agent_id": "a2", "confidence": 0.9})
    bids = (await client.get("/bids/t40")).json()
    assert len(bids) == 2


async def test_award_task(client):
    await client.post("/publish", json={"id": "t50", "objective": "x"})
    await client.post("/bid", json={"task_id": "t50", "agent_id": "a1", "confidence": 0.6})
    await client.post("/bid", json={"task_id": "t50", "agent_id": "a2", "confidence": 0.9})
    result = (await client.post("/award/t50")).json()
    assert result["winner"]["agent_id"] == "a2"


async def test_complete_task(client):
    await client.post("/publish", json={"id": "t60", "objective": "x"})
    await client.post("/complete/t60", json={"success": True})
    feed = (await client.get("/feed")).json()
    task = next(t for t in feed if t["id"] == "t60")
    assert task["status"] == "completed"


async def test_health_endpoint(client):
    resp = await client.get("/health")
    assert resp.json()["ok"] == 1
