import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from httpx import ASGITransport, AsyncClient
import pytest

_tmpdir = tempfile.mkdtemp()
os.environ.setdefault("ORCHESTRATOR_DB_PATH", os.path.join(_tmpdir, "test_err_orch.db"))

from conftest import load_service

orch = load_service("err_orch", "orchestrator")
orch.DB_PATH = os.path.join(_tmpdir, "test_err_orch.db")


@pytest.fixture(autouse=True)
async def reset():
    async with orch._agents_lock:
        orch.registered_agents.clear()
    yield
    async with orch._agents_lock:
        orch.registered_agents.clear()


@pytest.fixture
async def client():
    async with orch.lifespan(orch.app):
        transport = ASGITransport(app=orch.app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


def _make_response(data, status_code=200):
    resp = MagicMock()
    resp.json.return_value = data
    resp.status_code = status_code
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        http_resp = httpx.Response(status_code, request=httpx.Request("POST", "http://test"))
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=http_resp.request, response=http_resp
        )
    return resp


# --- Network failure tests ---

class TestPipelineNetworkFailures:
    async def test_normalize_service_unreachable(self, client):
        async def mock_post(url, **kwargs):
            raise httpx.ConnectError("Connection refused")

        mock_client = AsyncMock()
        mock_client.post = mock_post
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch.object(orch.httpx, "AsyncClient", return_value=mock_client):
            resp = await client.post("/pipeline", json={"objective": "test"})

        assert resp.status_code == 503
        assert "unreachable" in resp.json()["detail"].lower()

    async def test_ranking_service_unreachable(self, client):
        normalized = {"id": "n1", "objective": "test", "inputs": {}, "source": "manual", "raw": {}}
        call_count = 0

        async def mock_post(url, **kwargs):
            nonlocal call_count
            call_count += 1
            if "normalize" in url:
                return _make_response(normalized)
            raise httpx.ConnectError("Connection refused")

        mock_client = AsyncMock()
        mock_client.post = mock_post
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch.object(orch.httpx, "AsyncClient", return_value=mock_client):
            resp = await client.post("/pipeline", json={"objective": "test"})

        assert resp.status_code == 503

    async def test_marketplace_publish_unreachable(self, client):
        normalized = {"id": "n1", "objective": "test", "inputs": {}, "source": "manual", "raw": {}}
        ranked = {"id": "n1", "priority_score": 0.9}

        async def mock_post(url, **kwargs):
            if "normalize" in url:
                return _make_response(normalized)
            if "rank" in url:
                return _make_response(ranked)
            raise httpx.ConnectError("Connection refused")

        mock_client = AsyncMock()
        mock_client.post = mock_post
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch.object(orch.httpx, "AsyncClient", return_value=mock_client):
            resp = await client.post("/pipeline", json={"objective": "test"})

        assert resp.status_code == 503


class TestPipelineHTTPErrors:
    async def test_normalize_returns_500(self, client):
        async def mock_post(url, **kwargs):
            return _make_response({"detail": "Internal error"}, 500)

        mock_client = AsyncMock()
        mock_client.post = mock_post
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch.object(orch.httpx, "AsyncClient", return_value=mock_client):
            resp = await client.post("/pipeline", json={"objective": "test"})

        assert resp.status_code == 502
        assert "500" in resp.json()["detail"]

    async def test_ranking_returns_422(self, client):
        normalized = {"id": "n1", "objective": "test", "inputs": {}, "source": "manual", "raw": {}}

        async def mock_post(url, **kwargs):
            if "normalize" in url:
                return _make_response(normalized)
            return _make_response({"detail": "Missing id"}, 422)

        mock_client = AsyncMock()
        mock_client.post = mock_post
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch.object(orch.httpx, "AsyncClient", return_value=mock_client):
            resp = await client.post("/pipeline", json={"objective": "test"})

        assert resp.status_code == 502


class TestFullPipelineErrors:
    async def test_award_fails_returns_502(self, client):
        async with orch._agents_lock:
            orch.registered_agents["a1"] = {
                "agent_id": "a1", "profile": "test", "specialization": "generalist",
                "price": 0.1, "eta_minutes": 5, "confidence": 0.8,
            }

        normalized = {"id": "n1", "objective": "test", "inputs": {}, "source": "manual", "raw": {}}
        ranked = {"id": "n1", "priority_score": 0.9}

        async def mock_post(url, **kwargs):
            if "normalize" in url:
                return _make_response(normalized)
            if "rank" in url:
                return _make_response(ranked)
            if "publish" in url:
                return _make_response({"ok": 1})
            if "bid" in url:
                return _make_response({"ok": 1})
            if "award" in url:
                return _make_response({"detail": "No bids"}, 404)
            return _make_response({})

        mock_client = AsyncMock()
        mock_client.post = mock_post
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch.object(orch.httpx, "AsyncClient", return_value=mock_client):
            resp = await client.post("/pipeline/full", json={"objective": "test"})

        assert resp.status_code == 502

    async def test_execution_service_timeout(self, client):
        async with orch._agents_lock:
            orch.registered_agents["a1"] = {
                "agent_id": "a1", "profile": "test", "specialization": "generalist",
                "price": 0.1, "eta_minutes": 5, "confidence": 0.8,
            }

        normalized = {"id": "n1", "objective": "test", "inputs": {}, "source": "manual", "raw": {}}
        ranked = {"id": "n1", "priority_score": 0.9}

        async def mock_post(url, **kwargs):
            if "normalize" in url:
                return _make_response(normalized)
            if "rank" in url:
                return _make_response(ranked)
            if "publish" in url:
                return _make_response({"ok": 1})
            if "bid" in url:
                return _make_response({"ok": 1})
            if "award" in url:
                return _make_response({"ok": 1, "winner": {"agent_id": "a1", "confidence": 0.8}})
            if "execute" in url:
                raise httpx.ReadTimeout("Execution timed out")
            return _make_response({})

        mock_client = AsyncMock()
        mock_client.post = mock_post
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch.object(orch.httpx, "AsyncClient", return_value=mock_client):
            resp = await client.post("/pipeline/full", json={"objective": "test"})

        assert resp.status_code == 503


class TestProcessRecurring:
    async def test_recurring_engine_unreachable(self, client):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch.object(orch.httpx, "AsyncClient", return_value=mock_client):
            resp = await client.post("/process-recurring")

        assert resp.status_code == 503
        assert "recurring" in resp.json()["detail"].lower()

    async def test_recurring_returns_empty_tick(self, client):
        tick_resp = MagicMock()
        tick_resp.json.return_value = []
        tick_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=tick_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch.object(orch.httpx, "AsyncClient", return_value=mock_client):
            resp = await client.post("/process-recurring")

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] == 1
        assert data["processed"] == 0

    async def test_recurring_processes_tasks(self, client):
        async with orch._agents_lock:
            orch.registered_agents["a1"] = {
                "agent_id": "a1", "profile": "test", "specialization": "generalist",
                "price": 0.1, "eta_minutes": 5, "confidence": 0.8,
            }

        tick_resp = MagicMock()
        tick_resp.json.return_value = [
            {"id": "rt1", "objective": "recurring task 1"},
            {"id": "rt2", "objective": "recurring task 2"},
        ]
        tick_resp.raise_for_status = MagicMock()

        normalized = {"id": "rt1", "objective": "recurring task 1", "inputs": {}, "source": "recurring", "raw": {}}
        ranked = {"id": "rt1", "priority_score": 0.5}

        async def mock_post(url, **kwargs):
            if "normalize" in url:
                return _make_response(normalized)
            if "rank" in url:
                return _make_response(ranked)
            if "publish" in url:
                return _make_response({"ok": 1})
            if "bid" in url:
                return _make_response({"ok": 1})
            if "award" in url:
                return _make_response({"ok": 1, "winner": {"agent_id": "a1", "confidence": 0.8}})
            if "execute" in url:
                return _make_response({"ok": 1, "success": True, "duration": 2.0})
            if "complete" in url:
                return _make_response({"ok": 1})
            return _make_response({})

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=tick_resp)
        mock_client.post = mock_post
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch.object(orch.httpx, "AsyncClient", return_value=mock_client):
            resp = await client.post("/process-recurring")

        assert resp.status_code == 200
        data = resp.json()
        assert data["processed"] == 2

    async def test_recurring_partial_failure(self, client):
        async with orch._agents_lock:
            orch.registered_agents["a1"] = {
                "agent_id": "a1", "profile": "test", "specialization": "generalist",
                "price": 0.1, "eta_minutes": 5, "confidence": 0.8,
            }

        tick_resp = MagicMock()
        tick_resp.json.return_value = [
            {"id": "rt1", "objective": "will succeed"},
            {"id": "rt2", "objective": "will fail"},
        ]
        tick_resp.raise_for_status = MagicMock()

        call_count = 0

        async def mock_post(url, **kwargs):
            nonlocal call_count
            call_count += 1
            if "normalize" in url:
                payload = kwargs.get("json", {})
                if payload.get("objective") == "will fail":
                    return _make_response({"detail": "error"}, 500)
                return _make_response({
                    "id": "rt1", "objective": "will succeed",
                    "inputs": {}, "source": "recurring", "raw": {},
                })
            if "rank" in url:
                return _make_response({"id": "rt1", "priority_score": 0.5})
            if "publish" in url:
                return _make_response({"ok": 1})
            if "bid" in url:
                return _make_response({"ok": 1})
            if "award" in url:
                return _make_response({"ok": 1, "winner": {"agent_id": "a1", "confidence": 0.8}})
            if "execute" in url:
                return _make_response({"ok": 1, "success": True, "duration": 2.0})
            if "complete" in url:
                return _make_response({"ok": 1})
            return _make_response({})

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=tick_resp)
        mock_client.post = mock_post
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch.object(orch.httpx, "AsyncClient", return_value=mock_client):
            resp = await client.post("/process-recurring")

        assert resp.status_code == 200
        data = resp.json()
        assert data["processed"] == 2
        errors = [r for r in data["results"] if "error" in r]
        assert len(errors) >= 1
