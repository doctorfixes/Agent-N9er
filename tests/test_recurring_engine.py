import os
import tempfile
import uuid

import aiosqlite
from httpx import ASGITransport, AsyncClient
import pytest

_tmpdir = tempfile.mkdtemp()
os.environ["RECURRING_DB_PATH"] = os.path.join(_tmpdir, "test_recurring.db")

from conftest import load_service

recurring = load_service("recurring_main", "recurring_engine")


@pytest.fixture(autouse=True)
async def reset_rules():
    async with recurring._rules_lock:
        recurring.rules.clear()
    try:
        async with aiosqlite.connect(recurring.DB_PATH) as db:
            await db.execute("DELETE FROM rules")
            await db.commit()
    except Exception:
        pass
    yield
    async with recurring._rules_lock:
        recurring.rules.clear()


@pytest.fixture
async def client():
    async with recurring.lifespan(recurring.app):
        transport = ASGITransport(app=recurring.app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


async def test_rules_initially_empty(client):
    resp = await client.get("/rules")
    assert resp.json() == []


async def test_add_rule(client):
    resp = await client.post("/rules", json={"objective": "daily standup"})
    assert resp.json()["ok"] == 1
    assert resp.json()["rule"]["objective"] == "daily standup"


async def test_add_rule_missing_objective(client):
    resp = await client.post("/rules", json={"schedule": "daily"})
    assert resp.status_code == 422


async def test_tick_with_no_rules_returns_empty(client):
    resp = await client.get("/tick")
    assert resp.json() == []


async def test_tick_generates_tasks_from_rules(client):
    async with recurring._rules_lock:
        recurring.rules.append({"objective": "daily report", "rule_id": "r1"})
        recurring.rules.append({"objective": "sync data", "rule_id": "r2"})
    resp = await client.get("/tick")
    tasks = resp.json()
    assert len(tasks) == 2
    assert tasks[0]["objective"] == "daily report"
    assert tasks[1]["objective"] == "sync data"


async def test_tick_generates_valid_uuids(client):
    async with recurring._rules_lock:
        recurring.rules.append({"objective": "test", "rule_id": "r1"})
    resp = await client.get("/tick")
    uuid.UUID(resp.json()[0]["id"])


async def test_tick_generates_unique_ids_each_call(client):
    async with recurring._rules_lock:
        recurring.rules.append({"objective": "test", "rule_id": "r1"})
    id1 = (await client.get("/tick")).json()[0]["id"]
    id2 = (await client.get("/tick")).json()[0]["id"]
    assert id1 != id2


async def test_health_endpoint(client):
    resp = await client.get("/health")
    assert resp.json()["ok"] == 1
