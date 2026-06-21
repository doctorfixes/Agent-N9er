"""Tests for the memory & learning service — outcome tracking, skill profiles, and adaptive intelligence."""

import os
import tempfile

from httpx import ASGITransport, AsyncClient
import pytest

from conftest import load_service

_tmpdir = tempfile.mkdtemp()
os.environ.setdefault("MEMORY_DB_PATH", os.path.join(_tmpdir, "test_memory.db"))

memory = load_service("memory_main", "memory_service")


@pytest.fixture
async def client():
    async with memory.lifespan(memory.app):
        transport = ASGITransport(app=memory.app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


class TestHealth:
    async def test_health(self, client):
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] == 1
        assert data["service"] == "memory"


class TestOutcomes:
    async def test_record_outcome(self, client):
        resp = await client.post("/outcomes", json={
            "task_id": "task-001",
            "agent_id": "agent-alpha",
            "platform": "upwork",
            "category": "code_generation",
            "complexity": "moderate",
            "success": True,
            "estimated_cost_usd": 0.05,
            "actual_cost_usd": 0.04,
            "estimated_tokens": 3000,
            "actual_tokens": 2800,
            "quoted_price_usd": 15.0,
            "duration_seconds": 12.5,
            "tier": "standard",
            "model": "anthropic/claude-sonnet-4-6",
        })
        assert resp.status_code == 200
        assert resp.json()["ok"] == 1

    async def test_record_failure_outcome(self, client):
        resp = await client.post("/outcomes", json={
            "task_id": "task-002",
            "agent_id": "agent-alpha",
            "platform": "github_bounties",
            "category": "code_generation",
            "complexity": "complex",
            "success": False,
            "estimated_cost_usd": 0.10,
            "actual_cost_usd": 0.08,
            "quoted_price_usd": 25.0,
            "duration_seconds": 30.0,
        })
        assert resp.status_code == 200


class TestSkillProfile:
    async def test_skill_profile_builds_from_outcomes(self, client):
        for i in range(5):
            await client.post("/outcomes", json={
                "task_id": f"skill-task-{i}",
                "agent_id": "agent-beta",
                "category": "data_analysis",
                "success": i < 4,
                "actual_cost_usd": 0.05,
                "quoted_price_usd": 10.0,
                "duration_seconds": 15.0,
            })

        resp = await client.get("/skills/agent-beta")
        assert resp.status_code == 200
        data = resp.json()
        assert data["agent_id"] == "agent-beta"
        assert data["total_tasks"] == 5
        assert len(data["skills"]) >= 1

        da_skill = next(s for s in data["skills"] if s["category"] == "data_analysis")
        assert da_skill["attempts"] == 5
        assert da_skill["successes"] == 4
        assert da_skill["success_rate"] == pytest.approx(0.8, abs=0.01)

    async def test_identifies_strengths_and_weaknesses(self, client):
        for i in range(5):
            await client.post("/outcomes", json={
                "task_id": f"strong-{i}",
                "agent_id": "agent-gamma",
                "category": "content_generation",
                "success": True,
                "actual_cost_usd": 0.02,
                "quoted_price_usd": 8.0,
                "duration_seconds": 5.0,
            })
        for i in range(5):
            await client.post("/outcomes", json={
                "task_id": f"weak-{i}",
                "agent_id": "agent-gamma",
                "category": "complex_reasoning",
                "success": i == 0,
                "actual_cost_usd": 0.10,
                "quoted_price_usd": 20.0,
                "duration_seconds": 45.0,
            })

        resp = await client.get("/skills/agent-gamma")
        data = resp.json()
        assert "content_generation" in data["strengths"]
        assert "complex_reasoning" in data["weaknesses"]

    async def test_no_history_returns_empty(self, client):
        resp = await client.get("/skills/nonexistent-agent")
        assert resp.status_code == 200
        data = resp.json()
        assert data["skills"] == []


class TestPlatformIntelligence:
    async def test_platform_stats_accumulate(self, client):
        for i in range(4):
            await client.post("/outcomes", json={
                "task_id": f"plat-{i}",
                "platform": "upwork",
                "category": "code_generation",
                "success": i < 3,
                "actual_cost_usd": 0.05,
                "quoted_price_usd": 15.0,
                "duration_seconds": 10.0,
            })

        resp = await client.get("/platforms")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["platforms"]) >= 1
        upwork = next(p for p in data["platforms"] if p["platform"] == "upwork")
        assert upwork["leads_executed"] >= 4
        assert upwork["leads_succeeded"] >= 3


class TestPricingRecommendation:
    async def test_insufficient_data(self, client):
        resp = await client.get("/pricing/recommend", params={
            "category": "obscure_category",
            "complexity": "trivial",
        })
        assert resp.status_code == 200
        assert resp.json()["recommendation"] == "insufficient_data"

    async def test_pricing_recommendation_with_history(self, client):
        for i in range(5):
            await client.post("/outcomes", json={
                "task_id": f"price-{i}",
                "category": "translation",
                "complexity": "simple",
                "success": True,
                "estimated_cost_usd": 0.03,
                "actual_cost_usd": 0.03,
                "quoted_price_usd": 10.0,
                "duration_seconds": 8.0,
            })

        resp = await client.get("/pricing/recommend", params={
            "category": "translation",
            "complexity": "simple",
        })
        data = resp.json()
        assert data["recommendation"] != "insufficient_data"
        assert data["suggested_quote_usd"] > 0
        assert data["data_points"] >= 5


class TestConfidenceAdjustment:
    async def test_no_history_returns_base(self, client):
        resp = await client.get("/confidence/new-agent", params={
            "category": "code_generation",
            "base_confidence": 0.5,
        })
        data = resp.json()
        assert data["adjusted_confidence"] == 0.5
        assert data["adjustment_source"] == "no_history"

    async def test_adjusts_with_history(self, client):
        for i in range(5):
            await client.post("/outcomes", json={
                "task_id": f"conf-{i}",
                "agent_id": "agent-delta",
                "category": "workflow_automation",
                "success": True,
                "actual_cost_usd": 0.02,
                "quoted_price_usd": 8.0,
                "duration_seconds": 5.0,
            })

        resp = await client.get("/confidence/agent-delta", params={
            "category": "workflow_automation",
            "base_confidence": 0.5,
        })
        data = resp.json()
        assert data["adjusted_confidence"] > 0.5
        assert data["adjustment_source"] == "skill_history"


class TestPromptPatterns:
    async def test_record_and_retrieve_patterns(self, client):
        await client.post("/prompt-patterns", json={
            "category": "code_generation",
            "complexity": "moderate",
            "strategy": "step_by_step",
            "success": True,
            "quality_score": 0.9,
        })
        await client.post("/prompt-patterns", json={
            "category": "code_generation",
            "complexity": "moderate",
            "strategy": "step_by_step",
            "success": True,
            "quality_score": 0.85,
        })
        await client.post("/prompt-patterns", json={
            "category": "code_generation",
            "complexity": "moderate",
            "strategy": "direct_answer",
            "success": False,
            "quality_score": 0.4,
        })

        resp = await client.get("/prompt-patterns/best", params={
            "category": "code_generation",
            "complexity": "moderate",
        })
        data = resp.json()
        assert data["recommendation"] == "step_by_step"


class TestInsights:
    async def test_insights_with_data(self, client):
        for i in range(5):
            await client.post("/outcomes", json={
                "task_id": f"insight-{i}",
                "agent_id": "agent-insight",
                "category": "data_analysis",
                "success": i < 4,
                "estimated_cost_usd": 0.05,
                "actual_cost_usd": 0.04 + (i * 0.005),
                "estimated_tokens": 3000,
                "actual_tokens": 2800 + (i * 100),
                "quoted_price_usd": 15.0,
                "duration_seconds": 10.0 + i,
            })

        resp = await client.get("/insights", params={"agent_id": "agent-insight"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["summary"]["total_tasks"] == 5
        assert data["summary"]["successes"] == 4
        assert len(data["by_category"]) >= 1

    async def test_insights_empty_agent(self, client):
        resp = await client.get("/insights", params={"agent_id": "nobody"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["summary"]["total_tasks"] == 0
