"""Tests for Mission Control workflows: recurring task processing,
multi-agent orchestration, and end-to-end autonomous dispatch."""

import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import aiosqlite
from httpx import ASGITransport, AsyncClient
import pytest

from conftest import load_service

_tmpdir = tempfile.mkdtemp()
os.environ.setdefault("ORCHESTRATOR_DB_PATH", os.path.join(_tmpdir, "mc_orch.db"))
os.environ.setdefault("RECURRING_DB_PATH", os.path.join(_tmpdir, "mc_recurring.db"))

orch = load_service("mc_orch", "orchestrator")
orch.DB_PATH = os.path.join(_tmpdir, "mc_orch.db")

recurring = load_service("mc_recurring", "recurring_engine")
recurring.DB_PATH = os.path.join(_tmpdir, "mc_recurring.db")


@pytest.fixture(autouse=True)
async def reset():
    async with orch._agents_lock:
        orch.registered_agents.clear()
    try:
        async with aiosqlite.connect(orch.DB_PATH) as db:
            await db.execute("DELETE FROM agents")
            await db.commit()
    except Exception:
        pass
    async with recurring._rules_lock:
        recurring.rules.clear()
    try:
        async with aiosqlite.connect(recurring.DB_PATH) as db:
            await db.execute("DELETE FROM rules")
            await db.commit()
    except Exception:
        pass
    yield
    async with orch._agents_lock:
        orch.registered_agents.clear()
    async with recurring._rules_lock:
        recurring.rules.clear()


@pytest.fixture
async def orch_client():
    async with orch.lifespan(orch.app):
        transport = ASGITransport(app=orch.app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


@pytest.fixture
async def rec_client():
    async with recurring.lifespan(recurring.app):
        transport = ASGITransport(app=recurring.app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


def _make_response(data, status_code=200):
    resp = MagicMock()
    resp.json.return_value = data
    resp.status_code = status_code
    resp.raise_for_status = MagicMock()
    return resp


def _mock_full_pipeline():
    async def mock_post(url, **kwargs):
        if "normalize" in url:
            return _make_response({"id": "mc1", "objective": "test", "inputs": {}, "source": "recurring", "raw": {}, "category": "uncategorized", "tier": "general"})
        if "rank" in url:
            return _make_response({"id": "mc1", "priority_score": 5.0, "category": "uncategorized"})
        if "publish" in url:
            return _make_response({"ok": 1})
        if "bid" in url:
            return _make_response({"ok": 1})
        if "award" in url:
            return _make_response({"ok": 1, "winner": {"agent_id": "a1", "confidence": 0.8}})
        if "execute" in url:
            return _make_response({"ok": 1, "success": True, "duration": 1.5})
        if "complete" in url:
            return _make_response({"ok": 1})
        return _make_response({})

    async def mock_get(url, **kwargs):
        if "tick" in url:
            return _make_response([{"id": "gen-1", "objective": "recurring task", "source": "recurring"}])
        if "/confidence/" in url:
            return _make_response({"adjusted_confidence": 0.5, "adjustment_source": "no_history"})
        return _make_response([])

    mock_client = AsyncMock()
    mock_client.post = mock_post
    mock_client.get = mock_get
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


class TestRecurringEngine:
    async def test_add_rule(self, rec_client):
        resp = await rec_client.post("/rules", json={"objective": "Daily health scan", "category": "monitoring"})
        data = resp.json()
        assert data["ok"] == 1
        assert data["rule"]["objective"] == "Daily health scan"
        assert data["rule"]["category"] == "monitoring"
        assert "rule_id" in data["rule"]

    async def test_list_rules(self, rec_client):
        await rec_client.post("/rules", json={"objective": "Rule 1"})
        await rec_client.post("/rules", json={"objective": "Rule 2"})
        rules = (await rec_client.get("/rules")).json()
        assert len(rules) == 2

    async def test_tick_generates_tasks(self, rec_client):
        await rec_client.post("/rules", json={"objective": "Scan endpoints"})
        await rec_client.post("/rules", json={"objective": "Check SSL certs"})
        tasks = (await rec_client.get("/tick")).json()
        assert len(tasks) == 2
        assert all(t["source"] == "recurring" for t in tasks)
        assert {t["objective"] for t in tasks} == {"Scan endpoints", "Check SSL certs"}

    async def test_tick_empty_when_no_rules(self, rec_client):
        tasks = (await rec_client.get("/tick")).json()
        assert tasks == []

    async def test_rule_missing_objective_returns_422(self, rec_client):
        resp = await rec_client.post("/rules", json={"category": "test"})
        assert resp.status_code == 422

    async def test_rule_defaults_category(self, rec_client):
        resp = await rec_client.post("/rules", json={"objective": "No category"})
        assert resp.json()["rule"]["category"] == "uncategorized"

    async def test_health_includes_db_stats(self, rec_client):
        await rec_client.post("/rules", json={"objective": "Rule 1"})
        health = (await rec_client.get("/health")).json()
        assert health["ok"] == 1
        assert health["db_rules"] >= 1


class TestProcessRecurring:
    async def test_process_recurring_with_agents(self, orch_client):
        async with orch._agents_lock:
            orch.registered_agents["a1"] = {
                "agent_id": "a1", "profile": "speed", "specialization": "generalist",
                "price": 0.1, "eta_minutes": 2, "confidence": 0.8,
            }

        mock_client = _mock_full_pipeline()
        with patch.object(orch.httpx, "AsyncClient", return_value=mock_client):
            resp = await orch_client.post("/process-recurring")

        data = resp.json()
        assert data["ok"] == 1
        assert data["processed"] >= 1

    async def test_process_recurring_no_agents(self, orch_client):
        mock_client = _mock_full_pipeline()
        with patch.object(orch.httpx, "AsyncClient", return_value=mock_client):
            resp = await orch_client.post("/process-recurring")

        data = resp.json()
        assert data["ok"] == 1
        for result in data.get("results", []):
            assert "no_agents" in result.get("status", "") or "error" in result

    async def test_process_recurring_empty_tick(self, orch_client):
        async def mock_get(url, **kwargs):
            return _make_response([])

        mock_client = AsyncMock()
        mock_client.get = mock_get
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch.object(orch.httpx, "AsyncClient", return_value=mock_client):
            resp = await orch_client.post("/process-recurring")

        data = resp.json()
        assert data["ok"] == 1
        assert data["processed"] == 0


class TestMultiAgentBidding:
    async def test_multiple_agents_bid_on_same_task(self, orch_client):
        for i in range(3):
            async with orch._agents_lock:
                orch.registered_agents[f"agent-{i}"] = {
                    "agent_id": f"agent-{i}", "profile": "speed",
                    "specialization": "generalist", "price": 0.1,
                    "eta_minutes": 5, "confidence": 0.5 + (i * 0.1),
                }

        bid_calls = []

        async def mock_post(url, **kwargs):
            if "normalize" in url:
                return _make_response({"id": "multi-1", "objective": "test", "inputs": {}, "source": "manual", "raw": {}, "category": "uncategorized", "tier": "general"})
            if "rank" in url:
                return _make_response({"id": "multi-1", "priority_score": 5.0})
            if "publish" in url:
                return _make_response({"ok": 1})
            if "bid" in url:
                bid_calls.append(kwargs.get("json", {}))
                return _make_response({"ok": 1})
            if "award" in url:
                return _make_response({"ok": 1, "winner": {"agent_id": "agent-2", "confidence": 0.7}})
            if "execute" in url:
                return _make_response({"ok": 1, "success": True, "duration": 2.0})
            if "complete" in url:
                return _make_response({"ok": 1})
            return _make_response({})

        mock_client = AsyncMock()
        mock_client.post = mock_post
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch.object(orch.httpx, "AsyncClient", return_value=mock_client):
            resp = await orch_client.post("/pipeline/full", json={"objective": "test multi"})

        data = resp.json()
        assert data["status"] == "completed"
        assert data["winner"]["agent_id"] == "agent-2"
        assert len(bid_calls) == 3

    async def test_specialization_boost_applied(self, orch_client):
        async with orch._agents_lock:
            orch.registered_agents["code-agent"] = {
                "agent_id": "code-agent", "profile": "coder",
                "specialization": "code_specialist", "price": 0.1,
                "eta_minutes": 5, "confidence": 0.5,
            }

        bid_payloads = []

        async def mock_post(url, **kwargs):
            if "normalize" in url:
                return _make_response({"id": "spec-1", "objective": "write code", "inputs": {}, "source": "manual", "raw": {}, "category": "code_generation", "tier": "highest_leverage"})
            if "rank" in url:
                return _make_response({"id": "spec-1", "priority_score": 7.0})
            if "publish" in url:
                return _make_response({"ok": 1})
            if "bid" in url:
                bid_payloads.append(kwargs.get("json", {}))
                return _make_response({"ok": 1})
            if "award" in url:
                return _make_response({"ok": 1, "winner": {"agent_id": "code-agent", "confidence": 0.7}})
            if "execute" in url:
                return _make_response({"ok": 1, "success": True})
            if "complete" in url:
                return _make_response({"ok": 1})
            return _make_response({})

        mock_client = AsyncMock()
        mock_client.post = mock_post
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch.object(orch.httpx, "AsyncClient", return_value=mock_client):
            await orch_client.post("/pipeline/full", json={"objective": "write code"})

        assert len(bid_payloads) == 1
        assert bid_payloads[0]["confidence"] > 0.5

    async def test_agent_persistence_across_requests(self, orch_client):
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=_make_response({"ok": 1}))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch.object(orch.httpx, "AsyncClient", return_value=mock_client):
            await orch_client.post("/agents/register", json={"agent_id": "persist-1", "profile": "speed"})

        agents = (await orch_client.get("/agents")).json()
        assert "persist-1" in agents


class TestTaskCategories:
    async def test_categories_endpoint(self, orch_client):
        resp = await orch_client.get("/task-categories")
        data = resp.json()
        assert len(data) > 0
        assert any(c["category"] == "code_generation" for c in data)

    async def test_categories_filter_by_tier(self, orch_client):
        resp = await orch_client.get("/task-categories", params={"tier": "highest_leverage"})
        data = resp.json()
        assert len(data) > 0
        assert all(c["tier"] == "highest_leverage" for c in data)
