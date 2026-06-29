import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import aiosqlite
from httpx import ASGITransport, AsyncClient
import pytest

_tmpdir = tempfile.mkdtemp()
os.environ["ORCHESTRATOR_DB_PATH"] = os.path.join(_tmpdir, "test_orchestrator.db")

from conftest import load_service

orch = load_service("orch_main", "orchestrator")


@pytest.fixture(autouse=True)
async def reset_agents():
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


def _mock_pipeline():
    normalized = {"id": "n1", "objective": "test task", "inputs": {}, "source": "manual", "raw": {}}
    ranked = {"id": "n1", "priority_score": 0.9}

    async def mock_post(url, **kwargs):
        if "normalize" in url:
            return _make_response(normalized)
        elif "rank" in url:
            return _make_response(ranked)
        elif "publish" in url:
            return _make_response({"ok": 1})
        elif "register" in url:
            return _make_response({"ok": 1})
        elif "bid" in url:
            return _make_response({"ok": 1})
        elif "award" in url:
            return _make_response({"ok": 1, "winner": {"agent_id": "a1", "confidence": 0.8}})
        elif "execute" in url:
            return _make_response({"ok": 1, "success": True, "duration": 3.5})
        elif "complete" in url:
            return _make_response({"ok": 1})
        return _make_response({})

    mock_client = AsyncMock()
    mock_client.post = mock_post
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client, normalized, ranked


async def test_pipeline_calls_all_services(client):
    mock_client, normalized, ranked = _mock_pipeline()

    with patch.object(orch.httpx, "AsyncClient", return_value=mock_client):
        resp = await client.post("/pipeline", json={"objective": "test task"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "task_published"
    assert data["normalized"] == normalized
    assert data["ranked"] == ranked


async def test_register_agent(client):
    mock_client, _, _ = _mock_pipeline()
    with patch.object(orch.httpx, "AsyncClient", return_value=mock_client):
        resp = await client.post("/agents/register", json={"agent_id": "a1", "profile": "speed"})
    assert resp.json()["ok"] == 1
    assert "a1" in orch.registered_agents


async def test_full_pipeline(client):
    async with orch._agents_lock:
        orch.registered_agents["a1"] = {
            "agent_id": "a1", "profile": "speed", "specialization": "generalist",
            "price": 0.1, "eta_minutes": 2, "confidence": 0.8,
        }

    mock_client, _, _ = _mock_pipeline()
    with patch.object(orch.httpx, "AsyncClient", return_value=mock_client):
        with patch.object(orch, "BID_REQUIRE_APPROVAL", False):
            resp = await client.post("/pipeline/full", json={"objective": "test"})

    data = resp.json()
    assert data["status"] in ("completed", "failed")
    assert "winner" in data
    assert "execution" in data


async def test_full_pipeline_pending_approval(client):
    async with orch._agents_lock:
        orch.registered_agents["a1"] = {
            "agent_id": "a1", "profile": "speed", "specialization": "generalist",
            "price": 0.1, "eta_minutes": 2, "confidence": 0.8,
        }

    mock_client, _, _ = _mock_pipeline()
    with patch.object(orch.httpx, "AsyncClient", return_value=mock_client):
        with patch.object(orch, "BID_REQUIRE_APPROVAL", True):
            resp = await client.post("/pipeline/full", json={"objective": "test"})

    data = resp.json()
    assert data["status"] == "pending_approval"
    assert data["pending_bids"] == 1
    assert "task_id" in data


async def test_full_pipeline_no_agents(client):
    mock_client, _, _ = _mock_pipeline()
    with patch.object(orch.httpx, "AsyncClient", return_value=mock_client):
        resp = await client.post("/pipeline/full", json={"objective": "test"})
    assert resp.json()["status"] == "task_published_no_agents"


async def test_health_endpoint(client):
    resp = await client.get("/health")
    assert resp.json()["ok"] == 1


async def test_list_agents(client):
    async with orch._agents_lock:
        orch.registered_agents["a1"] = {"agent_id": "a1", "profile": "speed"}
    resp = await client.get("/agents")
    assert "a1" in resp.json()


# --- Pydantic validation tests ---

async def test_register_agent_missing_id_returns_422(client):
    resp = await client.post("/agents/register", json={"profile": "speed"})
    assert resp.status_code == 422


async def test_register_agent_uses_defaults(client):
    mock_client, _, _ = _mock_pipeline()
    with patch.object(orch.httpx, "AsyncClient", return_value=mock_client):
        resp = await client.post("/agents/register", json={"agent_id": "def1"})
    data = orch.registered_agents["def1"]
    assert data["profile"] == "unknown"
    assert data["confidence"] == 0.5


# --- Scan scheduler tests ---

async def test_scan_status_endpoint(client):
    resp = await client.get("/scan/status")
    data = resp.json()
    assert "auto_scan_enabled" in data
    assert "platforms" in data
    assert "total_scans" in data
    assert data["running"] is False


async def test_trigger_scan_calls_prospector(client):
    scan_resp = _make_response({"ok": 1, "discovered": 3, "new": 2, "platform": "upwork"})

    async def mock_post(url, **kwargs):
        return scan_resp

    mock_client = AsyncMock()
    mock_client.post = mock_post
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch.object(orch.httpx, "AsyncClient", return_value=mock_client):
        resp = await client.post("/scan/trigger")

    data = resp.json()
    assert data["ok"] == 1
    assert "results" in data
    assert data["scan_state"]["total_scans"] >= 1


async def test_trigger_scan_while_running(client):
    orch._scan_state["running"] = True
    try:
        resp = await client.post("/scan/trigger")
        assert resp.json()["ok"] == 0
    finally:
        orch._scan_state["running"] = False


# --- Pipeline approval tests ---

async def test_approve_pipeline_bids(client):
    async with orch._agents_lock:
        orch.registered_agents["a1"] = {
            "agent_id": "a1", "profile": "speed", "specialization": "generalist",
            "price": 0.1, "eta_minutes": 2, "confidence": 0.8,
        }

    mock_client, _, _ = _mock_pipeline()

    async def mock_post_with_approve(url, **kwargs):
        if "approve-all" in url:
            return _make_response({"ok": 1, "approved_count": 1})
        return await mock_client.post(url, **kwargs)

    approve_mock = AsyncMock()
    approve_mock.post = mock_post_with_approve
    approve_mock.__aenter__ = AsyncMock(return_value=approve_mock)
    approve_mock.__aexit__ = AsyncMock(return_value=False)

    with patch.object(orch.httpx, "AsyncClient", return_value=approve_mock):
        resp = await client.post("/pipeline/task-123/approve")

    data = resp.json()
    assert data["status"] in ("completed", "failed")
    assert data["approved_bids"] == 1
    assert "winner" in data


async def test_approve_pipeline_no_pending_bids(client):
    async def mock_post(url, **kwargs):
        if "approve-all" in url:
            return _make_response({"ok": 1, "approved_count": 0})
        return _make_response({})

    mock_client = AsyncMock()
    mock_client.post = mock_post
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch.object(orch.httpx, "AsyncClient", return_value=mock_client):
        resp = await client.post("/pipeline/no-such-task/approve")

    assert resp.status_code == 404


async def test_approve_pipeline_downstream_error(client):
    from httpx import HTTPStatusError, Response, Request

    async def mock_post(url, **kwargs):
        if "approve-all" in url:
            resp = _make_response({"detail": "error"}, 500)
            resp.raise_for_status = MagicMock(side_effect=HTTPStatusError(
                "Server error", request=Request("POST", url), response=Response(500)))
            return resp
        return _make_response({})

    mock_client = AsyncMock()
    mock_client.post = mock_post
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch.object(orch.httpx, "AsyncClient", return_value=mock_client):
        resp = await client.post("/pipeline/err-task/approve")

    assert resp.status_code == 502


async def test_approve_pipeline_service_unreachable(client):
    import httpx as httpx_lib

    async def mock_post(url, **kwargs):
        raise httpx_lib.ConnectError("Connection refused")

    mock_client = AsyncMock()
    mock_client.post = mock_post
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch.object(orch.httpx, "AsyncClient", return_value=mock_client):
        resp = await client.post("/pipeline/unreach-task/approve")

    assert resp.status_code == 503


# --- Revenue pipeline tests ---

async def test_revenue_pipeline_pending_approval(client):
    scan_resp = _make_response({"ok": 1, "discovered": 1, "new": 1})
    prospects_resp = _make_response([{"id": "p1", "title": "Test project", "description": "desc"}])
    eval_resp = _make_response({
        "status": "approved",
        "evaluation": {
            "quoted_price_usd": 50.0,
            "estimated_cost_usd": 5.0,
            "complexity": "moderate",
            "recommended_tier": "standard",
        },
    })

    async def mock_post(url, **kwargs):
        if "scan" in url:
            return scan_resp
        if "evaluate" in url:
            return eval_resp
        return _make_response({"ok": 1})

    async def mock_get(url, **kwargs):
        if "prospects" in url:
            return prospects_resp
        return _make_response({})

    mock_client = AsyncMock()
    mock_client.post = mock_post
    mock_client.get = mock_get
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch.object(orch.httpx, "AsyncClient", return_value=mock_client):
        with patch.object(orch, "BID_REQUIRE_APPROVAL", True):
            resp = await client.post("/revenue-pipeline", json={
                "platform": "upwork", "max_results": 5,
            })

    data = resp.json()
    assert data["approved"] == 1
    assert data["executed"] == 0
    prospects = data["prospects"]
    pending = [p for p in prospects if p["status"] == "pending_approval"]
    assert len(pending) == 1
    assert "detail" in pending[0]


async def test_revenue_pipeline_auto_execute(client):
    scan_resp = _make_response({"ok": 1, "discovered": 1, "new": 1})
    prospects_resp = _make_response([{"id": "p2", "title": "Auto exec project"}])
    eval_resp = _make_response({
        "status": "approved",
        "evaluation": {
            "quoted_price_usd": 100.0,
            "estimated_cost_usd": 10.0,
            "complexity": "moderate",
            "recommended_tier": "standard",
        },
    })
    exec_resp = _make_response({"ok": 1, "success": True, "mode": "simulation", "cost_usd": 0.01, "duration": 2.5})
    patch_resp = _make_response({"ok": 1})

    async def mock_post(url, **kwargs):
        if "scan" in url:
            return scan_resp
        if "evaluate" in url:
            return eval_resp
        if "execute" in url:
            return exec_resp
        return _make_response({"ok": 1})

    async def mock_get(url, **kwargs):
        if "prospects" in url:
            return prospects_resp
        return _make_response({})

    async def mock_patch(url, **kwargs):
        return patch_resp

    mock_client = AsyncMock()
    mock_client.post = mock_post
    mock_client.get = mock_get
    mock_client.patch = mock_patch
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch.object(orch.httpx, "AsyncClient", return_value=mock_client):
        with patch.object(orch, "BID_REQUIRE_APPROVAL", False):
            resp = await client.post("/revenue-pipeline", json={
                "platform": "upwork", "max_results": 5, "auto_execute": True,
            })

    data = resp.json()
    assert data["executed"] == 1
    assert data["estimated_profit"] > 0


async def test_revenue_pipeline_rejected_prospect(client):
    scan_resp = _make_response({"ok": 1, "discovered": 1, "new": 1})
    prospects_resp = _make_response([{"id": "p3", "title": "Non-digital task"}])
    eval_resp = _make_response({
        "status": "rejected",
        "evaluation": {"rejection_reason": "non-digital task"},
    })

    async def mock_post(url, **kwargs):
        if "scan" in url:
            return scan_resp
        if "evaluate" in url:
            return eval_resp
        return _make_response({"ok": 1})

    async def mock_get(url, **kwargs):
        if "prospects" in url:
            return prospects_resp
        return _make_response({})

    mock_client = AsyncMock()
    mock_client.post = mock_post
    mock_client.get = mock_get
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch.object(orch.httpx, "AsyncClient", return_value=mock_client):
        with patch.object(orch, "BID_REQUIRE_APPROVAL", False):
            resp = await client.post("/revenue-pipeline", json={"platform": "upwork"})

    data = resp.json()
    assert data["evaluated"] == 1
    assert data["approved"] == 0
    rejected = [p for p in data["prospects"] if p["status"] == "rejected"]
    assert len(rejected) == 1


async def test_revenue_pipeline_auto_execute_disabled(client):
    scan_resp = _make_response({"ok": 1, "discovered": 1, "new": 1})
    prospects_resp = _make_response([{"id": "p4", "title": "Hold project"}])
    eval_resp = _make_response({
        "status": "approved",
        "evaluation": {
            "quoted_price_usd": 25.0,
            "estimated_cost_usd": 2.5,
            "complexity": "simple",
        },
    })

    async def mock_post(url, **kwargs):
        if "scan" in url:
            return scan_resp
        if "evaluate" in url:
            return eval_resp
        return _make_response({"ok": 1})

    async def mock_get(url, **kwargs):
        if "prospects" in url:
            return prospects_resp
        return _make_response({})

    mock_client = AsyncMock()
    mock_client.post = mock_post
    mock_client.get = mock_get
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch.object(orch.httpx, "AsyncClient", return_value=mock_client):
        with patch.object(orch, "BID_REQUIRE_APPROVAL", False):
            resp = await client.post("/revenue-pipeline", json={
                "platform": "upwork", "auto_execute": False,
            })

    data = resp.json()
    assert data["approved"] == 1
    assert data["executed"] == 0
    approved = [p for p in data["prospects"] if p["status"] == "approved"]
    assert len(approved) == 1


async def test_revenue_pipeline_execution_failure(client):
    scan_resp = _make_response({"ok": 1, "discovered": 1, "new": 1})
    prospects_resp = _make_response([{"id": "p5", "title": "Failing project"}])
    eval_resp = _make_response({
        "status": "approved",
        "evaluation": {
            "quoted_price_usd": 50.0,
            "estimated_cost_usd": 5.0,
            "complexity": "moderate",
        },
    })
    exec_resp = _make_response({"ok": 1, "success": False, "mode": "simulation"})

    async def mock_post(url, **kwargs):
        if "scan" in url:
            return scan_resp
        if "evaluate" in url:
            return eval_resp
        if "execute" in url:
            return exec_resp
        return _make_response({"ok": 1})

    async def mock_get(url, **kwargs):
        if "prospects" in url:
            return prospects_resp
        return _make_response({})

    mock_client = AsyncMock()
    mock_client.post = mock_post
    mock_client.get = mock_get
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch.object(orch.httpx, "AsyncClient", return_value=mock_client):
        with patch.object(orch, "BID_REQUIRE_APPROVAL", False):
            resp = await client.post("/revenue-pipeline", json={
                "platform": "upwork", "auto_execute": True,
            })

    data = resp.json()
    assert data["executed"] == 0
    failed = [p for p in data["prospects"] if p["status"] == "execution_failed"]
    assert len(failed) == 1


async def test_revenue_pipeline_service_unreachable(client):
    import httpx as httpx_lib

    async def mock_post(url, **kwargs):
        raise httpx_lib.ConnectError("Connection refused")

    mock_client = AsyncMock()
    mock_client.post = mock_post
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch.object(orch.httpx, "AsyncClient", return_value=mock_client):
        resp = await client.post("/revenue-pipeline", json={"platform": "upwork"})

    assert resp.status_code == 503


async def test_revenue_pipeline_with_invoicing(client):
    scan_resp = _make_response({"ok": 1, "discovered": 1, "new": 1})
    prospects_resp = _make_response([{"id": "p6", "title": "Invoice project", "client_email": "client@test.com"}])
    eval_resp = _make_response({
        "status": "approved",
        "evaluation": {
            "quoted_price_usd": 200.0,
            "estimated_cost_usd": 20.0,
            "complexity": "complex",
            "recommended_tier": "premium",
        },
    })
    exec_resp = _make_response({"ok": 1, "success": True, "mode": "live", "cost_usd": 0.05, "duration": 5.0})
    invoice_resp = _make_response({"ok": 1, "invoice_id": "inv-001"})
    patch_resp = _make_response({"ok": 1})

    async def mock_post(url, **kwargs):
        if "scan" in url:
            return scan_resp
        if "evaluate" in url:
            return eval_resp
        if "execute" in url:
            return exec_resp
        if "invoices" in url:
            return invoice_resp
        return _make_response({"ok": 1})

    async def mock_get(url, **kwargs):
        if "prospects" in url:
            return prospects_resp
        return _make_response({})

    async def mock_patch(url, **kwargs):
        return patch_resp

    mock_client = AsyncMock()
    mock_client.post = mock_post
    mock_client.get = mock_get
    mock_client.patch = mock_patch
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch.object(orch.httpx, "AsyncClient", return_value=mock_client):
        with patch.object(orch, "BID_REQUIRE_APPROVAL", False):
            resp = await client.post("/revenue-pipeline", json={
                "platform": "upwork", "auto_execute": True,
            })

    data = resp.json()
    assert data["executed"] == 1
    assert data["invoiced"] == 1
    executed = [p for p in data["prospects"] if p["status"] == "executed"]
    assert executed[0]["invoice_id"] == "inv-001"


async def test_revenue_pipeline_require_approval_override(client):
    """Test that per-request require_approval overrides the global config."""
    scan_resp = _make_response({"ok": 1, "discovered": 1, "new": 1})
    prospects_resp = _make_response([{"id": "p7", "title": "Override test"}])
    eval_resp = _make_response({
        "status": "approved",
        "evaluation": {
            "quoted_price_usd": 30.0,
            "estimated_cost_usd": 3.0,
            "complexity": "simple",
        },
    })
    exec_resp = _make_response({"ok": 1, "success": True, "mode": "simulation", "cost_usd": 0.01, "duration": 1.0})
    patch_resp = _make_response({"ok": 1})

    async def mock_post(url, **kwargs):
        if "scan" in url:
            return scan_resp
        if "evaluate" in url:
            return eval_resp
        if "execute" in url:
            return exec_resp
        return _make_response({"ok": 1})

    async def mock_get(url, **kwargs):
        if "prospects" in url:
            return prospects_resp
        return _make_response({})

    async def mock_patch(url, **kwargs):
        return patch_resp

    mock_client = AsyncMock()
    mock_client.post = mock_post
    mock_client.get = mock_get
    mock_client.patch = mock_patch
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch.object(orch.httpx, "AsyncClient", return_value=mock_client):
        with patch.object(orch, "BID_REQUIRE_APPROVAL", True):
            resp = await client.post("/revenue-pipeline", json={
                "platform": "upwork", "auto_execute": True,
                "require_approval": False,
            })

    data = resp.json()
    assert data["executed"] == 1


async def test_revenue_pipeline_prospect_eval_error(client):
    """Test that evaluation network errors are handled per-prospect."""
    import httpx as httpx_lib

    scan_resp = _make_response({"ok": 1, "discovered": 1, "new": 1})
    prospects_resp = _make_response([{"id": "p8", "title": "Error prospect"}])

    call_count = 0

    async def mock_post(url, **kwargs):
        nonlocal call_count
        if "scan" in url:
            return scan_resp
        if "evaluate" in url:
            raise httpx_lib.ReadTimeout("timed out")
        return _make_response({"ok": 1})

    async def mock_get(url, **kwargs):
        if "prospects" in url:
            return prospects_resp
        return _make_response({})

    mock_client = AsyncMock()
    mock_client.post = mock_post
    mock_client.get = mock_get
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch.object(orch.httpx, "AsyncClient", return_value=mock_client):
        with patch.object(orch, "BID_REQUIRE_APPROVAL", False):
            resp = await client.post("/revenue-pipeline", json={"platform": "upwork"})

    data = resp.json()
    error_prospects = [p for p in data["prospects"] if p["status"] == "error"]
    assert len(error_prospects) == 1


async def test_full_pipeline_bid_submission_error(client):
    """Test that bid submission failure for an agent is handled gracefully."""
    import httpx as httpx_lib

    async with orch._agents_lock:
        orch.registered_agents["a1"] = {
            "agent_id": "a1", "profile": "speed", "specialization": "generalist",
            "price": 0.1, "eta_minutes": 2, "confidence": 0.8,
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
        if "/bid" in url:
            raise httpx_lib.ConnectError("bid service down")
        if "award" in url:
            return _make_response({"ok": 1, "winner": {"agent_id": "a1", "confidence": 0.8}})
        if "execute" in url:
            return _make_response({"ok": 1, "success": True, "duration": 1.0})
        if "complete" in url:
            return _make_response({"ok": 1})
        return _make_response({})

    mock_client = AsyncMock()
    mock_client.post = mock_post
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch.object(orch.httpx, "AsyncClient", return_value=mock_client):
        with patch.object(orch, "BID_REQUIRE_APPROVAL", False):
            resp = await client.post("/pipeline/full", json={"objective": "test"})

    assert resp.status_code in (200, 502)


# --- Dispatch tests ---

async def test_dispatch_status_endpoint(client):
    resp = await client.get("/dispatch/status")
    data = resp.json()
    assert "auto_dispatch_enabled" in data
    assert "auto_scan_enabled" in data


async def test_dispatch_trigger_with_no_prospects(client):
    """Dispatch with no discovered prospects returns zero stats."""
    prospects_resp = _make_response([])

    async def mock_get(url, **kwargs):
        return prospects_resp

    mock_client = AsyncMock()
    mock_client.get = mock_get
    mock_client.post = AsyncMock(return_value=_make_response({"ok": 1}))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch.object(orch.httpx, "AsyncClient", return_value=mock_client):
        resp = await client.post("/dispatch")

    data = resp.json()
    assert data["ok"] == 1
    assert data["dispatch"]["evaluated"] == 0
    assert data["dispatch"]["approved"] == 0


async def test_dispatch_evaluates_and_queues_bids(client):
    """Dispatch evaluates prospects, generates proposals, and queues bids."""
    prospects_data = [
        {"id": "dp1", "title": "Test Project", "description": "Build something",
         "platform": "freelancer", "budget_min": 50, "budget_max": 200, "skills": "python"},
    ]

    eval_data = {
        "ok": 1, "status": "approved",
        "evaluation": {"quoted_price_usd": 150, "estimated_cost_usd": 20,
                       "complexity": "moderate", "recommended_tier": "standard"},
    }

    proposal_data = {"ok": 1, "proposal": "I can do this.", "mode": "simulation"}

    bid_data = {"ok": 1, "status": "pending_approval", "bid_id": "b1"}

    async def mock_get(url, **kwargs):
        if "prospects" in url:
            return _make_response(prospects_data)
        return _make_response({})

    async def mock_post(url, **kwargs):
        if "evaluate" in url:
            return _make_response(eval_data)
        if "proposal" in url:
            return _make_response(proposal_data)
        if "bid" in url:
            return _make_response(bid_data)
        return _make_response({"ok": 1})

    mock_client = AsyncMock()
    mock_client.get = mock_get
    mock_client.post = mock_post
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch.object(orch.httpx, "AsyncClient", return_value=mock_client):
        resp = await client.post("/dispatch")

    data = resp.json()
    assert data["ok"] == 1
    dispatch = data["dispatch"]
    assert dispatch["evaluated"] == 1
    assert dispatch["approved"] == 1


async def test_dispatch_handles_rejected_prospects(client):
    """Dispatch skips rejected prospects without queuing bids."""
    prospects_data = [
        {"id": "dp2", "title": "Bad project", "description": "Not viable",
         "platform": "upwork", "budget_min": 0, "budget_max": 5, "skills": ""},
    ]

    eval_data = {
        "ok": 1, "status": "rejected",
        "evaluation": {"rejection_reason": "too cheap"},
    }

    async def mock_get(url, **kwargs):
        if "prospects" in url:
            return _make_response(prospects_data)
        return _make_response({})

    async def mock_post(url, **kwargs):
        if "evaluate" in url:
            return _make_response(eval_data)
        return _make_response({"ok": 1})

    mock_client = AsyncMock()
    mock_client.get = mock_get
    mock_client.post = mock_post
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch.object(orch.httpx, "AsyncClient", return_value=mock_client):
        resp = await client.post("/dispatch")

    data = resp.json()
    dispatch = data["dispatch"]
    assert dispatch["evaluated"] == 1
    assert dispatch["approved"] == 0
    assert dispatch["bids_queued"] == 0


async def test_dispatch_handles_service_error(client):
    """Dispatch handles network errors gracefully."""
    import httpx as httpx_lib

    async def mock_get(url, **kwargs):
        raise httpx_lib.ConnectError("Connection refused")

    mock_client = AsyncMock()
    mock_client.get = mock_get
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch.object(orch.httpx, "AsyncClient", return_value=mock_client):
        resp = await client.post("/dispatch")

    data = resp.json()
    assert data["ok"] == 1
    assert data["dispatch"]["errors"] >= 1


# --- Unstick tests ---

async def test_unstick_resets_stuck_prospects(client):
    """Unstick endpoint resets 'executing' prospects back to 'approved'."""
    stuck = [
        {"id": "stuck1", "title": "Stuck A", "status": "executing"},
        {"id": "stuck2", "title": "Stuck B", "status": "executing"},
    ]
    patch_calls = []

    async def mock_get(url, **kwargs):
        if "prospects" in url:
            return _make_response(stuck)
        return _make_response({})

    async def mock_patch(url, **kwargs):
        patch_calls.append(url)
        return _make_response({"ok": 1})

    mock_client = AsyncMock()
    mock_client.get = mock_get
    mock_client.patch = mock_patch
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch.object(orch.httpx, "AsyncClient", return_value=mock_client):
        resp = await client.post("/prospects/unstick", json={})

    data = resp.json()
    assert data["ok"] == 1
    assert data["found"] == 2
    assert data["reset"] == 2
    assert data["target_status"] == "approved"
    assert len(patch_calls) == 2


async def test_unstick_no_stuck_prospects(client):
    """Unstick returns zeros when nothing is stuck."""
    async def mock_get(url, **kwargs):
        return _make_response([])

    mock_client = AsyncMock()
    mock_client.get = mock_get
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch.object(orch.httpx, "AsyncClient", return_value=mock_client):
        resp = await client.post("/prospects/unstick", json={})

    data = resp.json()
    assert data["ok"] == 1
    assert data["found"] == 0
    assert data["reset"] == 0


def _mock_service_up():
    """Mock _check_service_health so execute-work doesn't hit real services."""
    health = {"execution": {"up": True}, "prospector": {"up": True}, "reputation": {"up": True}}
    return patch.object(orch, "_service_health", health)


async def test_execute_work_rolls_back_on_failure(client):
    """Execute-work resets prospect to 'approved' when execution fails."""
    prospects = [{"id": "rb1", "title": "Rollback test", "status": "executing"}]
    exec_resp = _make_response({"ok": 1, "success": False, "mode": "simulation"})
    patch_calls = []

    async def mock_get(url, **kwargs):
        return _make_response(prospects)

    async def mock_post(url, **kwargs):
        return exec_resp

    async def mock_patch(url, **kwargs):
        patch_calls.append(kwargs.get("json", {}))
        return _make_response({"ok": 1})

    mock_client = AsyncMock()
    mock_client.get = mock_get
    mock_client.post = mock_post
    mock_client.patch = mock_patch
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with _mock_service_up(), \
            patch.object(orch, "_check_service_health", AsyncMock(return_value={})), \
            patch.object(orch.httpx, "AsyncClient", return_value=mock_client):
        resp = await client.post("/prospects/execute-work", json={"status_filter": "executing"})

    data = resp.json()
    assert data["failed"] == 1
    assert any(p.get("status") == "approved" for p in patch_calls)


async def test_execute_work_rolls_back_on_service_error(client):
    """Execute-work resets prospect to 'approved' when execution service is unreachable."""
    import httpx as httpx_lib

    prospects = [{"id": "rb2", "title": "Unreachable test", "status": "executing"}]
    patch_calls = []

    async def mock_get(url, **kwargs):
        return _make_response(prospects)

    async def mock_post(url, **kwargs):
        raise httpx_lib.ConnectError("Connection refused")

    async def mock_patch(url, **kwargs):
        patch_calls.append(kwargs.get("json", {}))
        return _make_response({"ok": 1})

    mock_client = AsyncMock()
    mock_client.get = mock_get
    mock_client.post = mock_post
    mock_client.patch = mock_patch
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with _mock_service_up(), \
            patch.object(orch, "_check_service_health", AsyncMock(return_value={})), \
            patch.object(orch.httpx, "AsyncClient", return_value=mock_client):
        resp = await client.post("/prospects/execute-work", json={"status_filter": "executing"})

    data = resp.json()
    assert data["failed"] == 1
    assert any(p.get("status") == "approved" for p in patch_calls)


async def test_execute_work_blocked_when_service_down(client):
    """Execute-work returns 503 when execution service is down."""
    health = {"execution": {"up": False}, "prospector": {"up": True}, "reputation": {"up": True}}
    with patch.object(orch, "_service_health", health), \
            patch.object(orch, "_check_service_health", AsyncMock(return_value=health)):
        resp = await client.post("/prospects/execute-work", json={"status_filter": "executing"})
    assert resp.status_code == 503


async def test_journal_endpoint(client):
    """Journal API returns entries."""
    await orch._journal("test_event", "test decision", "test reasoning", outcome="ok")
    resp = await client.get("/journal")
    data = resp.json()
    assert "entries" in data
    assert "total" in data
    assert data["total"] >= 1
    assert any(e["event"] == "test_event" for e in data["entries"])


async def test_journal_severity_filter(client):
    """Journal API filters by severity."""
    await orch._journal("warn_event", "warning decision", "test", severity="warn")
    resp = await client.get("/journal", params={"severity": "warn"})
    data = resp.json()
    assert all(e["severity"] == "warn" for e in data["entries"])


async def test_services_health_endpoint(client):
    """Services health endpoint returns status."""
    health = {"execution": {"up": True}, "prospector": {"up": False}, "reputation": {"up": True}}
    with patch.object(orch, "_service_health", health), \
            patch.object(orch, "_check_service_health", AsyncMock(return_value=health)):
        resp = await client.get("/services/health")
    data = resp.json()
    assert data["online"] == 2
    assert data["total"] == 3
    assert data["status"] == "degraded"


async def test_self_awareness_endpoint(client):
    """Self-awareness endpoint returns full assessment."""
    health = {"execution": {"up": True}, "prospector": {"up": True}, "reputation": {"up": True}}
    with patch.object(orch, "_service_health", health), \
            patch.object(orch, "_check_service_health", AsyncMock(return_value=health)):
        resp = await client.get("/self-awareness")
    data = resp.json()
    assert "health" in data
    assert "activity" in data
    assert "stability" in data
    assert "recommendations" in data
    assert data["health"]["status"] == "healthy"


async def test_self_awareness_degraded(client):
    """Self-awareness flags issues when services are down."""
    health = {"execution": {"up": False}, "prospector": {"up": True}, "reputation": {"up": True}}
    with patch.object(orch, "_service_health", health), \
            patch.object(orch, "_check_service_health", AsyncMock(return_value=health)):
        resp = await client.get("/self-awareness")
    data = resp.json()
    assert data["health"]["status"] == "degraded"
    assert len(data["issues"]) > 0
    assert any("execution" in r.lower() for r in data["recommendations"])
