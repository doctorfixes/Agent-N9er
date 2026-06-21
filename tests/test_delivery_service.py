"""Tests for the delivery service — sending completed work to clients."""

import os
import tempfile
from unittest.mock import patch, MagicMock, AsyncMock

from httpx import ASGITransport, AsyncClient
import pytest

from conftest import load_service

_tmpdir = tempfile.mkdtemp()
os.environ.setdefault("DELIVERY_DB_PATH", os.path.join(_tmpdir, "test_delivery.db"))

delivery = load_service("delivery_main", "delivery_service")


@pytest.fixture
async def client():
    async with delivery.lifespan(delivery.app):
        transport = ASGITransport(app=delivery.app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


def _mock_response(data, status_code=200):
    resp = MagicMock()
    resp.json.return_value = data
    resp.status_code = status_code
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        import httpx
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=resp,
        )
    return resp


class TestHealth:
    async def test_health(self, client):
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] == 1
        assert data["service"] == "delivery"


class TestDeliver:
    async def test_deliver_queues_without_smtp(self, client):
        mock_exec_resp = _mock_response({
            "task_id": "task-001",
            "agent_id": "agent-1",
            "success": True,
            "output": "Here is the completed REST API code with tests...",
        })

        mock_http = AsyncMock()
        mock_http.get = AsyncMock(return_value=mock_exec_resp)
        mock_http.post = AsyncMock(return_value=_mock_response({"content": "formatted"}))
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)

        with patch.object(delivery.httpx, "AsyncClient", return_value=mock_http):
            resp = await client.post("/deliver", json={
                "task_id": "task-001",
                "client_email": "client@example.com",
                "client_name": "Test Client",
            })

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] == 1
        assert data["status"] == "queued"
        assert data["delivery_id"]
        assert data["client_email"] == "client@example.com"

    async def test_deliver_with_smtp_sends_email(self, client):
        mock_exec_resp = _mock_response({
            "task_id": "task-002",
            "agent_id": "agent-1",
            "success": True,
            "output": "Dashboard implementation with charts...",
        })

        mock_http = AsyncMock()
        mock_http.get = AsyncMock(return_value=mock_exec_resp)
        mock_http.post = AsyncMock(return_value=_mock_response({"content": "formatted"}))
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)

        with patch.object(delivery.httpx, "AsyncClient", return_value=mock_http), \
             patch.object(delivery, "SMTP_HOST", "smtp.test.com"), \
             patch.object(delivery, "SMTP_USER", "user@test.com"), \
             patch.object(delivery, "_send_email") as mock_send:
            resp = await client.post("/deliver", json={
                "task_id": "task-002",
                "client_email": "client2@example.com",
                "subject": "Your work is ready",
            })

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "delivered"
        mock_send.assert_called_once()

    async def test_deliver_handles_email_failure(self, client):
        mock_exec_resp = _mock_response({
            "task_id": "task-003",
            "output": "Some output",
        })

        mock_http = AsyncMock()
        mock_http.get = AsyncMock(return_value=mock_exec_resp)
        mock_http.post = AsyncMock(return_value=_mock_response({"content": "formatted"}))
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)

        with patch.object(delivery.httpx, "AsyncClient", return_value=mock_http), \
             patch.object(delivery, "SMTP_HOST", "smtp.test.com"), \
             patch.object(delivery, "SMTP_USER", "user@test.com"), \
             patch.object(delivery, "_send_email", side_effect=Exception("SMTP connection refused")):
            resp = await client.post("/deliver", json={
                "task_id": "task-003",
                "client_email": "client3@example.com",
            })

        data = resp.json()
        assert data["status"] == "failed"
        assert "SMTP" in data["error"]

    async def test_deliver_no_output_returns_404(self, client):
        mock_exec_resp = _mock_response({"task_id": "task-missing", "output": ""})

        mock_http = AsyncMock()
        mock_http.get = AsyncMock(return_value=mock_exec_resp)
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)

        with patch.object(delivery.httpx, "AsyncClient", return_value=mock_http):
            resp = await client.post("/deliver", json={
                "task_id": "task-missing",
                "client_email": "client@example.com",
            })
        assert resp.status_code == 404


class TestListDeliveries:
    async def test_list_deliveries_empty(self, client):
        resp = await client.get("/deliveries")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_list_with_filters(self, client):
        resp = await client.get("/deliveries", params={"status": "delivered", "limit": 10})
        assert resp.status_code == 200


class TestAnalytics:
    async def test_analytics(self, client):
        resp = await client.get("/analytics")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_deliveries" in data
        assert "by_status" in data
        assert "unique_clients" in data
