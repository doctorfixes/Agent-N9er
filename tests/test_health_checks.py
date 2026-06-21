import os
import tempfile
from unittest.mock import patch

from httpx import ASGITransport, AsyncClient
import pytest

from conftest import load_service

_tmpdir = tempfile.mkdtemp()

os.environ.setdefault("ORCHESTRATOR_DB_PATH", os.path.join(_tmpdir, "test_hc_orch.db"))
os.environ.setdefault("RECURRING_DB_PATH", os.path.join(_tmpdir, "test_hc_recurring.db"))

_mp_db = os.path.join(_tmpdir, "test_hc_marketplace.db")
_exec_db = os.path.join(_tmpdir, "test_hc_execution.db")
_rep_db = os.path.join(_tmpdir, "test_hc_reputation.db")

marketplace = load_service("hc_marketplace", "bidding_marketplace")
marketplace.DB_PATH = _mp_db

execution = load_service("hc_execution", "agent_execution")
execution.DB_PATH = _exec_db

reputation = load_service("hc_reputation", "reputation_ledger")
reputation.DB_PATH = _rep_db

orch = load_service("hc_orch", "orchestrator")
orch.DB_PATH = os.path.join(_tmpdir, "test_hc_orch.db")

recurring = load_service("hc_recurring", "recurring_engine")
recurring.DB_PATH = os.path.join(_tmpdir, "test_hc_recurring.db")

norm = load_service("hc_norm", "normalization_service")
ranking = load_service("hc_ranking", "ranking_engine")
browser = load_service("hc_browser", "browser_service")


# --- DB-backed services: healthy state ---

class TestHealthyState:
    async def test_marketplace_health_shows_db(self):
        async with marketplace.lifespan(marketplace.app):
            transport = ASGITransport(app=marketplace.app)
            async with AsyncClient(transport=transport, base_url="http://test") as c:
                resp = await c.get("/health")
        data = resp.json()
        assert data["ok"] == 1
        assert "task_count" in data

    async def test_execution_health_shows_db(self):
        async with execution.lifespan(execution.app):
            transport = ASGITransport(app=execution.app)
            async with AsyncClient(transport=transport, base_url="http://test") as c:
                resp = await c.get("/health")
        data = resp.json()
        assert data["ok"] == 1
        assert "total_executions" in data

    async def test_reputation_health_shows_db(self):
        async with reputation.lifespan(reputation.app):
            transport = ASGITransport(app=reputation.app)
            async with AsyncClient(transport=transport, base_url="http://test") as c:
                resp = await c.get("/health")
        data = resp.json()
        assert data["ok"] == 1
        assert "agent_count" in data

    async def test_orchestrator_health_shows_db(self):
        async with orch.lifespan(orch.app):
            transport = ASGITransport(app=orch.app)
            async with AsyncClient(transport=transport, base_url="http://test") as c:
                resp = await c.get("/health")
        data = resp.json()
        assert data["ok"] == 1
        assert "db_agents" in data

    async def test_recurring_health_shows_db(self):
        async with recurring.lifespan(recurring.app):
            transport = ASGITransport(app=recurring.app)
            async with AsyncClient(transport=transport, base_url="http://test") as c:
                resp = await c.get("/health")
        data = resp.json()
        assert data["ok"] == 1
        assert "db_rules" in data


# --- DB-backed services: degraded state ---

class TestDegradedState:
    async def test_marketplace_health_db_unreachable(self):
        async with marketplace.lifespan(marketplace.app):
            transport = ASGITransport(app=marketplace.app)
            async with AsyncClient(transport=transport, base_url="http://test") as c:
                with patch.object(marketplace, "DB_PATH", "/nonexistent/path/db.sqlite"):
                    resp = await c.get("/health")
        data = resp.json()
        assert data["ok"] == 0
        assert "error" in data

    async def test_execution_health_db_unreachable(self):
        async with execution.lifespan(execution.app):
            transport = ASGITransport(app=execution.app)
            async with AsyncClient(transport=transport, base_url="http://test") as c:
                with patch.object(execution, "DB_PATH", "/nonexistent/path/db.sqlite"):
                    resp = await c.get("/health")
        data = resp.json()
        assert data["ok"] == 0
        assert "error" in data

    async def test_reputation_health_db_unreachable(self):
        async with reputation.lifespan(reputation.app):
            transport = ASGITransport(app=reputation.app)
            async with AsyncClient(transport=transport, base_url="http://test") as c:
                with patch.object(reputation, "DB_PATH", "/nonexistent/path/db.sqlite"):
                    resp = await c.get("/health")
        data = resp.json()
        assert data["ok"] == 0
        assert "error" in data

    async def test_orchestrator_health_db_unreachable(self):
        async with orch.lifespan(orch.app):
            transport = ASGITransport(app=orch.app)
            async with AsyncClient(transport=transport, base_url="http://test") as c:
                with patch.object(orch, "DB_PATH", "/nonexistent/path/db.sqlite"):
                    resp = await c.get("/health")
        data = resp.json()
        assert data["ok"] == 0
        assert "error" in data

    async def test_recurring_health_db_unreachable(self):
        async with recurring.lifespan(recurring.app):
            transport = ASGITransport(app=recurring.app)
            async with AsyncClient(transport=transport, base_url="http://test") as c:
                with patch.object(recurring, "DB_PATH", "/nonexistent/path/db.sqlite"):
                    resp = await c.get("/health")
        data = resp.json()
        assert data["ok"] == 0
        assert "error" in data


# --- Stateless services: always healthy ---

class TestStatelessHealth:
    async def test_normalization_health(self):
        transport = ASGITransport(app=norm.app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.get("/health")
        data = resp.json()
        assert data["ok"] == 1
        assert data["service"] == "normalization"

    async def test_ranking_health(self):
        transport = ASGITransport(app=ranking.app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.get("/health")
        data = resp.json()
        assert data["ok"] == 1
        assert data["service"] == "ranking"

    async def test_browser_health(self):
        transport = ASGITransport(app=browser.app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.get("/health")
        data = resp.json()
        assert data["ok"] == 1
        assert data["service"] == "browser"
