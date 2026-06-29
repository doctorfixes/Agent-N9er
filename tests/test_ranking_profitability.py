"""Tests for profitability boost and budget boost in ranking engine."""

from unittest.mock import AsyncMock, patch
import time

from httpx import ASGITransport, AsyncClient
import pytest

from conftest import load_service

ranking = load_service("ranking_main", "ranking_engine")


@pytest.fixture(autouse=True)
def clear_profitability_cache():
    """Reset the profitability cache before each test."""
    ranking._profitability_cache.clear()
    ranking._cache_expires_at = 0
    yield
    ranking._profitability_cache.clear()
    ranking._cache_expires_at = 0


@pytest.fixture
def client():
    transport = ASGITransport(app=ranking.app)
    return AsyncClient(transport=transport, base_url="http://test")


class TestBudgetBoost:
    async def test_budget_500_capped_at_5(self, client):
        resp = await client.post("/rank", json={
            "id": "t1", "objective": "test", "budget_max": 500,
        })
        assert resp.json()["budget_boost"] == 5.0

    async def test_budget_100_gives_1(self, client):
        resp = await client.post("/rank", json={
            "id": "t2", "objective": "test", "budget_max": 100,
        })
        assert resp.json()["budget_boost"] == 1.0

    async def test_budget_0_gives_0(self, client):
        resp = await client.post("/rank", json={
            "id": "t3", "objective": "test", "budget_max": 0,
        })
        assert resp.json()["budget_boost"] == 0.0


class TestProfitBoostAndBudgetBoostFields:
    async def test_response_includes_boost_fields(self, client):
        resp = await client.post("/rank", json={
            "id": "t4", "objective": "test",
        })
        data = resp.json()
        assert "profit_boost" in data
        assert "budget_boost" in data


class TestProfitabilityCache:
    async def test_cache_prevents_duplicate_http_calls(self, client):
        profitability_data = {
            "upwork": {
                "jobs": 5,
                "revenue_usd": 500,
                "cost_usd": 100,
                "profit_usd": 400,
                "avg_profit_usd": 80,
                "margin_pct": 85,
            }
        }

        call_count = 0

        async def mock_get_profitability():
            nonlocal call_count
            # Only increment on actual "fetch" (first call sets cache)
            if not ranking._profitability_cache:
                call_count += 1
                ranking._profitability_cache = profitability_data
                ranking._cache_expires_at = time.time() + 300
            return ranking._profitability_cache

        with patch.object(ranking, "_get_profitability", side_effect=mock_get_profitability):
            resp1 = await client.post("/rank", json={
                "id": "c1", "objective": "test", "platform": "upwork",
            })
            resp2 = await client.post("/rank", json={
                "id": "c2", "objective": "test", "platform": "upwork",
            })

        assert resp1.json()["profit_boost"] > 0
        assert resp2.json()["profit_boost"] > 0
        assert call_count == 1
