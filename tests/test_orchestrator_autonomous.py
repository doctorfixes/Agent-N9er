import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import aiosqlite
from httpx import ASGITransport, AsyncClient
import pytest

_tmpdir = tempfile.mkdtemp()
os.environ["ORCHESTRATOR_DB_PATH"] = os.path.join(_tmpdir, "test_orch_auto.db")

from conftest import load_service

orch = load_service("orch_auto_main", "orchestrator")


@pytest.fixture(autouse=True)
async def reset_state():
    async with orch._agents_lock:
        orch.registered_agents.clear()
    orch._autonomous_state.update({
        "running": False,
        "cycles_completed": 0,
        "last_cycle_at": None,
        "prospects_applied": 0,
        "prospects_executed": 0,
        "total_revenue_generated": 0.0,
        "daily_applications": 0,
        "daily_applications_date": None,
    })
    orch._pipeline_stats.update({
        "events_relayed": 0,
        "feedback_loops_triggered": 0,
        "auto_rescans_triggered": 0,
        "confidence_recalibrations": 0,
    })
    orch._event_subscribers.clear()
    try:
        async with aiosqlite.connect(orch.DB_PATH) as db:
            await db.execute("DELETE FROM agents")
            await db.commit()
    except Exception:
        pass
    yield


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
    return resp


# ---------------------------------------------------------------------------
# Autonomous endpoints
# ---------------------------------------------------------------------------

async def test_autonomous_status(client):
    resp = await client.get("/autonomous/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "enabled" in data
    assert "interval_seconds" in data
    assert "auto_apply_enabled" in data
    assert "max_parallel_tasks" in data
    assert "running" in data
    assert "cycles_completed" in data


async def test_autonomous_trigger(client):
    async def mock_post(url, **kwargs):
        if "/scan" in url:
            return _make_response({"ok": 1, "discovered": 2, "new": 1})
        if "/proposal" in url:
            return _make_response({"ok": 1, "mode": "ai"})
        if "/execute" in url:
            return _make_response({"ok": 1, "success": True, "cost_usd": 0.01})
        if "/evaluate-output" in url:
            return _make_response({"quality_score": 0.9})
        if "/invoices" in url:
            return _make_response({"ok": 1, "invoice_id": "inv-1"})
        return _make_response({"ok": 1})

    async def mock_get(url, **kwargs):
        if "/prospects" in url:
            return _make_response([])
        return _make_response({})

    async def mock_patch(url, **kwargs):
        return _make_response({"ok": 1})

    mock_client = AsyncMock()
    mock_client.post = mock_post
    mock_client.get = mock_get
    mock_client.patch = mock_patch
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch.object(orch.httpx, "AsyncClient", return_value=mock_client):
        resp = await client.post("/autonomous/trigger")

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] == 1
    assert "cycle_stats" in data
    assert "state" in data


async def test_autonomous_trigger_already_running(client):
    orch._autonomous_state["running"] = True
    try:
        resp = await client.post("/autonomous/trigger")
        data = resp.json()
        assert data["ok"] == 0
    finally:
        orch._autonomous_state["running"] = False


# ---------------------------------------------------------------------------
# Events endpoints
# ---------------------------------------------------------------------------

async def test_events_recent(client):
    resp = await client.get("/events/recent")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_events_stats(client):
    resp = await client.get("/events/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert "events_relayed" in data
    assert "feedback_loops_triggered" in data


async def test_events_subscriptions_empty(client):
    resp = await client.get("/events/subscriptions")
    assert resp.status_code == 200
    assert resp.json() == {}


async def test_events_relay(client):
    resp = await client.post("/events/relay", json={"type": "test.event", "data": {"foo": "bar"}, "source": "test"})
    assert resp.status_code == 200
    assert resp.json()["ok"] == 1


async def test_events_subscribe_and_list(client):
    resp = await client.post("/events/subscribe", json={"event_type": "test.event", "callback_url": "http://example.com/hook"})
    assert resp.status_code == 200
    assert resp.json()["ok"] == 1

    resp = await client.get("/events/subscriptions")
    subs = resp.json()
    assert "test.event" in subs
    assert "http://example.com/hook" in subs["test.event"]


async def test_events_subscribe_missing_url(client):
    resp = await client.post("/events/subscribe", json={"event_type": "test"})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Review workflow endpoints
# ---------------------------------------------------------------------------

async def test_review_pending(client):
    prospects = [{"id": "p1", "title": "Test Task", "status": "review_needed"}]

    async def mock_get(url, **kwargs):
        if "/prospects" in url:
            return _make_response(prospects)
        if "/output" in url:
            return _make_response({"output": "some output"})
        return _make_response({})

    mock_client = AsyncMock()
    mock_client.get = mock_get
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch.object(orch.httpx, "AsyncClient", return_value=mock_client):
        resp = await client.get("/review/pending")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["id"] == "p1"
    assert data[0]["execution_output"] == "some output"


async def test_review_approve(client):
    prospect = {"id": "p1", "title": "Task", "quoted_price": 100, "client_email": "c@test.com", "platform": "upwork", "actual_cost": 0.5}

    async def mock_get(url, **kwargs):
        return _make_response(prospect)

    async def mock_patch(url, **kwargs):
        return _make_response({"ok": 1})

    async def mock_post(url, **kwargs):
        return _make_response({"ok": 1, "invoice_id": "inv-1"})

    mock_client = AsyncMock()
    mock_client.get = mock_get
    mock_client.patch = mock_patch
    mock_client.post = mock_post
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch.object(orch.httpx, "AsyncClient", return_value=mock_client):
        resp = await client.post("/review/p1", json={"action": "approve"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] == 1
    assert data["status"] == "delivered"
    assert data["invoiced"] is True


async def test_review_reject(client):
    async def mock_patch(url, **kwargs):
        return _make_response({"ok": 1})

    mock_client = AsyncMock()
    mock_client.patch = mock_patch
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch.object(orch.httpx, "AsyncClient", return_value=mock_client):
        resp = await client.post("/review/p1", json={"action": "reject", "reason": "bad quality"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] == 1
    assert data["status"] == "rejected_to_approved"
    assert data["reason"] == "bad quality"


async def test_review_invalid_action(client):
    resp = await client.post("/review/p1", json={"action": "invalid"})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Pipeline momentum
# ---------------------------------------------------------------------------

async def test_pipeline_momentum(client):
    async with orch._agents_lock:
        orch.registered_agents["a1"] = {
            "agent_id": "a1", "profile": "speed", "specialization": "generalist",
            "price": 0.1, "eta_minutes": 2, "confidence": 0.8,
        }

    resp = await client.get("/pipeline/momentum")
    assert resp.status_code == 200
    data = resp.json()
    assert data["agent_count"] == 1
    assert data["avg_confidence"] == 0.8
    assert "autonomous" in data
    assert "recent_events" in data


async def test_pipeline_momentum_no_agents(client):
    resp = await client.get("/pipeline/momentum")
    assert resp.status_code == 200
    data = resp.json()
    assert data["agent_count"] == 0
    assert data["avg_confidence"] == 0.0
