from httpx import ASGITransport, AsyncClient
import pytest

from conftest import load_service

ranking = load_service("ranking_main", "ranking_engine")


@pytest.fixture
def client():
    transport = ASGITransport(app=ranking.app)
    return AsyncClient(transport=transport, base_url="http://test")


async def test_rank_calculates_score(client):
    resp = await client.post("/rank", json={"id": "abc", "objective": "hello"})
    data = resp.json()
    assert data["priority_score"] > 0


async def test_rank_preserves_id(client):
    resp = await client.post("/rank", json={"id": "my-id", "objective": "x"})
    assert resp.json()["id"] == "my-id"


async def test_rank_empty_objective_scores_low(client):
    resp = await client.post("/rank", json={"id": "t1", "objective": ""})
    assert resp.json()["priority_score"] < 1.0


async def test_rank_long_objective_scores_higher(client):
    short = await client.post("/rank", json={"id": "s", "objective": "hi"})
    long = await client.post("/rank", json={"id": "l", "objective": "a " * 50})
    assert long.json()["priority_score"] > short.json()["priority_score"]


async def test_rank_keyword_boost(client):
    normal = await client.post("/rank", json={"id": "n", "objective": "update readme"})
    urgent = await client.post("/rank", json={"id": "u", "objective": "urgent fix deploy"})
    assert urgent.json()["priority_score"] > normal.json()["priority_score"]


async def test_rank_highest_leverage_tier_boosts_score(client):
    unranked = await client.post("/rank", json={"id": "u", "objective": "hello"})
    ranked = await client.post("/rank", json={
        "id": "r", "objective": "hello",
        "tier": "highest_leverage", "leverage_score": 10.0, "cost_tier": "mid",
    })
    assert ranked.json()["priority_score"] > unranked.json()["priority_score"]


async def test_rank_returns_category(client):
    resp = await client.post("/rank", json={
        "id": "c", "objective": "test", "category": "code_generation", "tier": "highest_leverage",
    })
    assert resp.json()["category"] == "code_generation"


async def test_rank_missing_id_returns_422(client):
    resp = await client.post("/rank", json={"objective": "test"})
    assert resp.status_code == 422


async def test_health_endpoint(client):
    resp = await client.get("/health")
    assert resp.json()["ok"] == 1
