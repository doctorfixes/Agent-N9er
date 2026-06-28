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
