"""Tests for the simulation service main module."""

import importlib
import random
import sys
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

# The simulation package uses a mix of relative and absolute imports internally.
# main.py does `from runner import run` (absolute, relying on sys.path containing
# the simulation/ dir), while runner.py uses relative imports
# (`from .task_generator import gen`).
#
# To make this work, we pre-import the submodules as package members and also
# alias them as bare names so both import styles resolve.
root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))
sim_dir = str(root / "simulation")
if sim_dir not in sys.path:
    sys.path.insert(0, sim_dir)

# Import submodules through the package so relative imports work
from simulation import task_generator as _tg  # noqa: E402
from simulation import market as _mkt  # noqa: E402
from simulation import runner as _runner  # noqa: E402

# Register bare-name aliases so `from runner import run` in main.py resolves
sys.modules.setdefault("runner", _runner)
sys.modules.setdefault("task_generator", _tg)
sys.modules.setdefault("market", _mkt)

import simulation.main as sim  # noqa: E402


@pytest.fixture
def client():
    transport = ASGITransport(app=sim.app)
    return AsyncClient(transport=transport, base_url="http://test")


class TestHealth:
    async def test_health_returns_ok(self, client):
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] == 1
        assert data["service"] == "simulation"


class TestTaskCategories:
    async def test_task_categories_returns_dict(self, client):
        resp = await client.get("/task-categories")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)
        assert len(data) > 0
        for cat, count in data.items():
            assert isinstance(count, int)
            assert count > 0

    async def test_task_categories_includes_known_categories(self, client):
        resp = await client.get("/task-categories")
        data = resp.json()
        assert "code_generation" in data
        assert "complex_reasoning" in data


class TestCreateAgents:
    def test_create_agents_returns_five(self):
        agents = sim.create_agents()
        assert len(agents) == 5

    def test_create_agents_profiles(self):
        agents = sim.create_agents()
        profiles = [a.profile for a in agents]
        assert "speed" in profiles
        assert "precision" in profiles
        assert "balanced" in profiles
        assert "research" in profiles
        assert "content" in profiles

    def test_create_agents_unique_ids(self):
        agents = sim.create_agents()
        ids = [a.agent_id for a in agents]
        assert len(set(ids)) == 5


class TestRunSimulation:
    async def test_run_default(self, client):
        random.seed(42)
        resp = await client.get("/run")
        assert resp.status_code == 200
        data = resp.json()
        assert data["mode"] == "local"
        assert data["rounds"] == 10
        assert data["category"] is None
        assert len(data["results"]) == 10
        assert len(data["agent_stats"]) == 5

    async def test_run_with_n(self, client):
        random.seed(42)
        resp = await client.get("/run", params={"n": 3})
        assert resp.status_code == 200
        data = resp.json()
        assert data["rounds"] == 3
        assert len(data["results"]) == 3

    async def test_run_with_category(self, client):
        random.seed(42)
        resp = await client.get("/run", params={"n": 2, "category": "code_generation"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["category"] == "code_generation"
        assert len(data["results"]) == 2

    async def test_run_results_structure(self, client):
        random.seed(42)
        resp = await client.get("/run", params={"n": 1})
        data = resp.json()
        result = data["results"][0]
        assert "round" in result
        assert "task" in result
        assert "bids" in result
        assert "winner" in result
        assert "success" in result
        assert "duration" in result

    async def test_agent_stats_structure(self, client):
        random.seed(42)
        resp = await client.get("/run", params={"n": 1})
        data = resp.json()
        stat = data["agent_stats"][0]
        assert "agent_id" in stat
        assert "profile" in stat
        assert "reputation" in stat


class TestRunLiveSimulation:
    async def test_live_success(self, client):
        """Test the /run/live endpoint when all services are reachable."""
        mock_register_resp = MagicMock()
        mock_register_resp.raise_for_status = MagicMock()

        mock_pipeline_resp = MagicMock()
        mock_pipeline_resp.raise_for_status = MagicMock()
        mock_pipeline_resp.json.return_value = {"status": "completed", "task_id": "t1"}

        mock_ledger_resp = MagicMock()
        mock_ledger_resp.json.return_value = {"agent1": {"score": 0.9}}

        async def mock_post(url, **kwargs):
            if "/agents/register" in url:
                return mock_register_resp
            return mock_pipeline_resp

        async def mock_get(url, **kwargs):
            return mock_ledger_resp

        mock_client = AsyncMock()
        mock_client.post = mock_post
        mock_client.get = mock_get
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            resp = await client.post("/run/live", params={"n": 2})

        assert resp.status_code == 200
        data = resp.json()
        assert data["mode"] == "live"
        assert data["rounds"] == 2
        assert len(data["results"]) == 2
        assert data["results"][0]["status"] == "completed"

    async def test_live_orchestrator_unreachable(self, client):
        """Test /run/live when orchestrator cannot be reached during registration."""
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=httpx.RequestError("Connection refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            resp = await client.post("/run/live", params={"n": 1})

        assert resp.status_code == 503
        assert "Orchestrator unreachable" in resp.json()["detail"]

    async def test_live_pipeline_http_error(self, client):
        """Test /run/live when pipeline returns HTTP errors."""
        mock_register_resp = MagicMock()
        mock_register_resp.raise_for_status = MagicMock()

        async def mock_post(url, **kwargs):
            if "/agents/register" in url:
                return mock_register_resp
            raise httpx.HTTPStatusError(
                "Server Error",
                request=MagicMock(),
                response=MagicMock(status_code=500),
            )

        mock_ledger_resp = MagicMock()
        mock_ledger_resp.json.return_value = {}

        mock_client = AsyncMock()
        mock_client.post = mock_post
        mock_client.get = AsyncMock(return_value=mock_ledger_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            resp = await client.post("/run/live", params={"n": 2})

        assert resp.status_code == 200
        data = resp.json()
        assert data["mode"] == "live"
        for result in data["results"]:
            assert "error" in result

    async def test_live_pipeline_request_error(self, client):
        """Test /run/live when pipeline has connection errors."""
        mock_register_resp = MagicMock()
        mock_register_resp.raise_for_status = MagicMock()

        async def mock_post(url, **kwargs):
            if "/agents/register" in url:
                return mock_register_resp
            raise httpx.RequestError("Connection reset")

        mock_ledger_resp = MagicMock()
        mock_ledger_resp.json.return_value = {}

        mock_client = AsyncMock()
        mock_client.post = mock_post
        mock_client.get = AsyncMock(return_value=mock_ledger_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            resp = await client.post("/run/live", params={"n": 1})

        assert resp.status_code == 200
        data = resp.json()
        assert data["results"][0]["error"] is not None

    async def test_live_ledger_unreachable(self, client):
        """Test /run/live when reputation ledger is unreachable."""
        mock_register_resp = MagicMock()
        mock_register_resp.raise_for_status = MagicMock()

        mock_pipeline_resp = MagicMock()
        mock_pipeline_resp.raise_for_status = MagicMock()
        mock_pipeline_resp.json.return_value = {"status": "ok", "task_id": "t1"}

        async def mock_post(url, **kwargs):
            if "/agents/register" in url:
                return mock_register_resp
            return mock_pipeline_resp

        async def mock_get(url, **kwargs):
            raise httpx.RequestError("Connection refused")

        mock_client = AsyncMock()
        mock_client.post = mock_post
        mock_client.get = mock_get
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            resp = await client.post("/run/live", params={"n": 1})

        assert resp.status_code == 200
        data = resp.json()
        assert data["agent_stats"] == {}

    async def test_live_with_category(self, client):
        """Test /run/live with a specific task category."""
        mock_register_resp = MagicMock()
        mock_register_resp.raise_for_status = MagicMock()

        mock_pipeline_resp = MagicMock()
        mock_pipeline_resp.raise_for_status = MagicMock()
        mock_pipeline_resp.json.return_value = {"status": "ok", "task_id": "t1"}

        mock_ledger_resp = MagicMock()
        mock_ledger_resp.json.return_value = {}

        async def mock_post(url, **kwargs):
            if "/agents/register" in url:
                return mock_register_resp
            return mock_pipeline_resp

        mock_client = AsyncMock()
        mock_client.post = mock_post
        mock_client.get = AsyncMock(return_value=mock_ledger_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            resp = await client.post("/run/live", params={"n": 1, "category": "code_generation"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["category"] == "code_generation"
