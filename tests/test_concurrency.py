import asyncio
import os
import tempfile
from unittest.mock import patch, AsyncMock, MagicMock

import aiosqlite
from httpx import ASGITransport, AsyncClient
import pytest

_tmpdir = tempfile.mkdtemp()

_orch_db = os.path.join(_tmpdir, "conc_orch.db")
_recurring_db = os.path.join(_tmpdir, "conc_recurring.db")
_marketplace_db = os.path.join(_tmpdir, "conc_marketplace.db")

os.environ["ORCHESTRATOR_DB_PATH"] = _orch_db
os.environ["RECURRING_DB_PATH"] = _recurring_db

from conftest import load_service

orch = load_service("conc_orch", "orchestrator")
orch.DB_PATH = _orch_db

recurring = load_service("conc_recurring", "recurring_engine")
recurring.DB_PATH = _recurring_db

marketplace = load_service("conc_marketplace", "bidding_marketplace")
marketplace.DB_PATH = _marketplace_db


def _mock_reputation():
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"ok": 1}
    mock_resp.raise_for_status = MagicMock()
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


# --- Orchestrator concurrency ---

class TestOrchestratorConcurrency:
    @pytest.fixture(autouse=True)
    async def setup(self):
        async with orch._agents_lock:
            orch.registered_agents.clear()
        try:
            async with aiosqlite.connect(orch.DB_PATH) as db:
                await db.execute("DELETE FROM agents")
                await db.commit()
        except Exception:
            pass
        yield
        async with orch._agents_lock:
            orch.registered_agents.clear()

    @pytest.fixture
    async def client(self):
        async with orch.lifespan(orch.app):
            transport = ASGITransport(app=orch.app)
            async with AsyncClient(transport=transport, base_url="http://test") as c:
                yield c

    async def test_concurrent_agent_registration(self, client):
        mock_client = _mock_reputation()

        async def register(agent_id):
            with patch.object(orch.httpx, "AsyncClient", return_value=mock_client):
                return await client.post(
                    "/agents/register",
                    json={"agent_id": agent_id, "profile": "test"},
                )

        results = await asyncio.gather(*[register(f"agent_{i}") for i in range(20)])

        assert all(r.status_code == 200 for r in results)
        async with orch._agents_lock:
            assert len(orch.registered_agents) == 20

    async def test_concurrent_read_and_write(self, client):
        mock_client = _mock_reputation()

        async def register(agent_id):
            with patch.object(orch.httpx, "AsyncClient", return_value=mock_client):
                return await client.post(
                    "/agents/register",
                    json={"agent_id": agent_id, "profile": "test"},
                )

        async def list_agents():
            return await client.get("/agents")

        tasks = []
        for i in range(10):
            tasks.append(register(f"rw_agent_{i}"))
            tasks.append(list_agents())

        results = await asyncio.gather(*tasks)
        assert all(r.status_code == 200 for r in results)


# --- Recurring engine concurrency ---

class TestRecurringConcurrency:
    @pytest.fixture(autouse=True)
    async def setup(self):
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
    async def client(self):
        async with recurring.lifespan(recurring.app):
            transport = ASGITransport(app=recurring.app)
            async with AsyncClient(transport=transport, base_url="http://test") as c:
                yield c

    async def test_concurrent_rule_addition(self, client):
        async def add_rule(i):
            return await client.post("/rules", json={"objective": f"rule {i}"})

        results = await asyncio.gather(*[add_rule(i) for i in range(20)])
        assert all(r.status_code == 200 for r in results)

        async with recurring._rules_lock:
            assert len(recurring.rules) == 20

    async def test_concurrent_tick_and_add(self, client):
        async with recurring._rules_lock:
            recurring.rules.append({"objective": "existing", "rule_id": "r0"})

        async def add_rule(i):
            return await client.post("/rules", json={"objective": f"new rule {i}"})

        async def tick():
            return await client.get("/tick")

        tasks = []
        for i in range(5):
            tasks.append(add_rule(i))
            tasks.append(tick())

        results = await asyncio.gather(*tasks)
        assert all(r.status_code == 200 for r in results)


# --- Marketplace concurrency ---

class TestMarketplaceConcurrency:
    @pytest.fixture
    async def client(self):
        async with marketplace.lifespan(marketplace.app):
            transport = ASGITransport(app=marketplace.app)
            async with AsyncClient(transport=transport, base_url="http://test") as c:
                yield c

    async def test_concurrent_bids_on_same_task(self, client):
        await client.post("/publish", json={"id": "conc_t1", "objective": "test"})

        async def bid(agent_id, confidence):
            return await client.post("/bid", json={
                "task_id": "conc_t1",
                "agent_id": agent_id,
                "confidence": confidence,
            })

        results = await asyncio.gather(*[
            bid(f"agent_{i}", round(0.1 + i * 0.05, 2)) for i in range(10)
        ])
        assert all(r.status_code == 200 for r in results)

        bids = (await client.get("/bids/conc_t1")).json()
        assert len(bids) == 10

    async def test_concurrent_publish(self, client):
        async def publish(i):
            return await client.post("/publish", json={
                "id": f"cpar_t{i}", "objective": f"task {i}",
            })

        results = await asyncio.gather(*[publish(i) for i in range(15)])
        assert all(r.status_code == 200 for r in results)

        feed = (await client.get("/feed")).json()
        published_ids = {t["id"] for t in feed}
        expected_ids = {f"cpar_t{i}" for i in range(15)}
        assert expected_ids.issubset(published_ids)
