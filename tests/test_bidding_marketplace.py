from httpx import ASGITransport, AsyncClient
import pytest

from conftest import load_service

marketplace = load_service("marketplace_main", "bidding_marketplace")


@pytest.fixture(autouse=True)
def reset_state():
    marketplace.tasks.clear()
    marketplace.bids.clear()
    yield
    marketplace.tasks.clear()
    marketplace.bids.clear()


@pytest.fixture
def client():
    transport = ASGITransport(app=marketplace.app)
    return AsyncClient(transport=transport, base_url="http://test")


async def test_feed_initially_empty(client):
    resp = await client.get("/feed")
    assert resp.json() == []


async def test_publish_adds_task(client):
    task = {"id": "t1", "objective": "test", "priority_score": 0.5}
    resp = await client.post("/publish", json=task)
    assert resp.json()["ok"] == 1


async def test_feed_returns_published_tasks(client):
    await client.post("/publish", json={"id": "t1", "objective": "first"})
    await client.post("/publish", json={"id": "t2", "objective": "second"})
    feed = (await client.get("/feed")).json()
    assert len(feed) == 2


async def test_publish_sets_status_open(client):
    await client.post("/publish", json={"id": "t1", "objective": "x"})
    feed = (await client.get("/feed")).json()
    assert feed[0]["status"] == "open"


async def test_submit_bid(client):
    await client.post("/publish", json={"id": "t1", "objective": "x"})
    resp = await client.post("/bid", json={"task_id": "t1", "agent_id": "a1", "confidence": 0.8})
    assert resp.json()["ok"] == 1


async def test_get_bids(client):
    await client.post("/publish", json={"id": "t1", "objective": "x"})
    await client.post("/bid", json={"task_id": "t1", "agent_id": "a1", "confidence": 0.8})
    await client.post("/bid", json={"task_id": "t1", "agent_id": "a2", "confidence": 0.9})
    bids = (await client.get("/bids/t1")).json()
    assert len(bids) == 2


async def test_award_task(client):
    await client.post("/publish", json={"id": "t1", "objective": "x"})
    await client.post("/bid", json={"task_id": "t1", "agent_id": "a1", "confidence": 0.6})
    await client.post("/bid", json={"task_id": "t1", "agent_id": "a2", "confidence": 0.9})
    result = (await client.post("/award/t1")).json()
    assert result["winner"]["agent_id"] == "a2"


async def test_health_endpoint(client):
    resp = await client.get("/health")
    assert resp.json()["ok"] == 1
