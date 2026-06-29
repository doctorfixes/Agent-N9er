"""Tests for the evaluator service — project viability and cost estimation."""

import os
import tempfile

from httpx import ASGITransport, AsyncClient
import pytest

from conftest import load_service

_tmpdir = tempfile.mkdtemp()
os.environ.setdefault("EVALUATOR_DB_PATH", os.path.join(_tmpdir, "test_evaluator.db"))

evaluator = load_service("eval_main", "evaluator_service")


@pytest.fixture
async def client():
    async with evaluator.lifespan(evaluator.app):
        transport = ASGITransport(app=evaluator.app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


class TestEvaluate:
    async def test_simple_task_viable(self, client):
        resp = await client.post("/evaluate", json={
            "title": "Fix a bug in login page",
            "description": "The login button doesn't work on mobile",
            "platform": "upwork",
        })
        data = resp.json()
        assert data["viable"] is True
        assert data["complexity"] == "simple"
        assert data["quoted_price_usd"] > 0
        assert data["estimated_profit_usd"] > 0
        assert data["markup_multiplier"] == 8.0

    async def test_complex_task_viable(self, client):
        resp = await client.post("/evaluate", json={
            "title": "Build REST API with authentication and payment integration",
            "description": "Full-stack web application with database, OAuth, Stripe payments",
            "platform": "upwork",
        })
        data = resp.json()
        assert data["viable"] is True
        assert data["complexity"] in ("complex", "expert")

    async def test_non_digital_rejected(self, client):
        resp = await client.post("/evaluate", json={
            "title": "Need someone for a phone call",
            "description": "30-minute phone call to discuss project",
            "platform": "upwork",
        })
        data = resp.json()
        assert data["viable"] is False
        assert "phone call" in data["rejection_reason"]

    async def test_budget_exceeded_rejected(self, client):
        resp = await client.post("/evaluate", json={
            "title": "Build complex distributed system architecture",
            "description": "Design and implement a microservices architecture with Kubernetes",
            "platform": "upwork",
            "budget_max": 0.001,
        })
        data = resp.json()
        assert data["viable"] is False

    async def test_minimum_quote_applied(self, client):
        resp = await client.post("/evaluate", json={
            "title": "Fix typo",
            "description": "Change one word",
            "platform": "upwork",
        })
        data = resp.json()
        assert data["quoted_price_usd"] >= 5.00

    async def test_evaluation_persisted(self, client):
        await client.post("/evaluate", json={
            "title": "Test persistence",
            "description": "Testing",
            "platform": "test",
        })
        history = (await client.get("/history")).json()
        assert any(e["title"] == "Test persistence" for e in history)


class TestHealth:
    async def test_health_ok(self, client):
        resp = await client.get("/health")
        assert resp.json()["ok"] == 1
        assert resp.json()["service"] == "evaluator"


class TestPricing:
    async def test_pricing_endpoint(self, client):
        resp = await client.get("/pricing")
        data = resp.json()
        assert data["markup_multiplier"] == 8.0
        assert data["minimum_quote_usd"] == 5.0
        assert "standard" in data["model_tiers"]
        assert "budget" in data["model_tiers"]


class TestFeedbackLoop:
    async def test_update_feedback(self, client):
        payload = {
            "by_platform": {"freelancer": {"total": 10, "wins": 5, "win_rate": 0.5}},
            "by_budget": {"small": {"total": 5, "wins": 3, "avg_rating": 4.0}},
        }
        resp = await client.post("/feedback/update", json=payload)
        data = resp.json()
        assert data["ok"] == 1
        assert data["platforms"] == 1
        assert data["budget_buckets"] == 1

    async def test_current_feedback_empty(self, client):
        evaluator._feedback_data = {}
        resp = await client.get("/feedback/current")
        data = resp.json()
        assert data["has_feedback"] is False

    async def test_current_feedback_populated(self, client):
        await client.post("/feedback/update", json={
            "by_platform": {"freelancer": {"total": 5, "wins": 3, "win_rate": 0.6}},
        })
        resp = await client.get("/feedback/current")
        data = resp.json()
        assert data["has_feedback"] is True
        assert "freelancer" in data["data"]["by_platform"]

    async def test_low_win_rate_rejects_viable_project(self, client):
        await client.post("/feedback/update", json={
            "by_platform": {"badplatform": {"total": 20, "wins": 0, "win_rate": 0.01}},
            "by_budget": {},
        })
        resp = await client.post("/evaluate", json={
            "title": "Fix a bug",
            "description": "Simple bug fix",
            "platform": "badplatform",
        })
        data = resp.json()
        assert data["viable"] is False
        assert "win rate" in data["rejection_reason"].lower()
        evaluator._feedback_data = {}

    async def test_low_budget_rating_rejects(self, client):
        await client.post("/feedback/update", json={
            "by_platform": {},
            "by_budget": {"micro": {"total": 10, "wins": 2, "avg_rating": 1.5}},
        })
        resp = await client.post("/evaluate", json={
            "title": "Fix a bug",
            "description": "Simple",
            "platform": "upwork",
            "budget_max": 50,
        })
        data = resp.json()
        assert data["viable"] is False
        assert "rating" in data["rejection_reason"].lower()
        evaluator._feedback_data = {}
