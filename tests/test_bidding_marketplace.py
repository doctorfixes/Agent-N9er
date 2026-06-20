from httpx import ASGITransport, AsyncClient
import pytest

from conftest import load_service

marketplace = load_service("marketplace_main", "bidding_marketplace")


@pytest.fixture(autouse=True)
def reset_tasks():
    marketplace.tasks.clear()
    yield
    marketplace.tasks.clear()


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
    t1 = {"id": "t1", "objective": "first"}
    t2 = {"id": "t2", "objective": "second"}
    await client.post("/publish", json=t1)
    await client.post("/publish", json=t2)
    feed = (await client.get("/feed")).json()
    assert len(feed) == 2
    assert feed[0]["id"] == "t1"
    assert feed[1]["id"] == "t2"


async def test_publish_preserves_all_fields(client):
    task = {"id": "t1", "objective": "x", "priority_score": 1.5, "extra": "data"}
    await client.post("/publish", json=task)
    feed = (await client.get("/feed")).json()
    assert feed[0]["extra"] == "data"
