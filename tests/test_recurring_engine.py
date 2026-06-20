import uuid

from httpx import ASGITransport, AsyncClient
import pytest

from conftest import load_service

recurring = load_service("recurring_main", "recurring_engine")


@pytest.fixture(autouse=True)
def reset_rules():
    recurring.rules.clear()
    yield
    recurring.rules.clear()


@pytest.fixture
def client():
    transport = ASGITransport(app=recurring.app)
    return AsyncClient(transport=transport, base_url="http://test")


async def test_rules_initially_empty(client):
    resp = await client.get("/rules")
    assert resp.json() == []


async def test_tick_with_no_rules_returns_empty(client):
    resp = await client.get("/tick")
    assert resp.json() == []


async def test_tick_generates_tasks_from_rules(client):
    recurring.rules.append({"objective": "daily report"})
    recurring.rules.append({"objective": "sync data"})
    resp = await client.get("/tick")
    tasks = resp.json()
    assert len(tasks) == 2
    assert tasks[0]["objective"] == "daily report"
    assert tasks[1]["objective"] == "sync data"


async def test_tick_generates_valid_uuids(client):
    recurring.rules.append({"objective": "test"})
    resp = await client.get("/tick")
    uuid.UUID(resp.json()[0]["id"])


async def test_tick_generates_unique_ids_each_call(client):
    recurring.rules.append({"objective": "test"})
    id1 = (await client.get("/tick")).json()[0]["id"]
    id2 = (await client.get("/tick")).json()[0]["id"]
    assert id1 != id2
