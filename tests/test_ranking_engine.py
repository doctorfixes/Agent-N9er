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
    assert data["priority_score"] == pytest.approx(0.5)


async def test_rank_preserves_id(client):
    resp = await client.post("/rank", json={"id": "my-id", "objective": "x"})
    assert resp.json()["id"] == "my-id"


async def test_rank_empty_objective_scores_zero(client):
    resp = await client.post("/rank", json={"id": "t1", "objective": ""})
    assert resp.json()["priority_score"] == 0.0


async def test_rank_long_objective_scores_higher(client):
    short = await client.post("/rank", json={"id": "s", "objective": "hi"})
    long = await client.post("/rank", json={"id": "l", "objective": "a" * 100})
    assert long.json()["priority_score"] > short.json()["priority_score"]
