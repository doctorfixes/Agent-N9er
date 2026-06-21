import uuid

from httpx import ASGITransport, AsyncClient
import pytest

from conftest import load_service

norm = load_service("norm_main", "normalization_service")


@pytest.fixture
def client():
    transport = ASGITransport(app=norm.app)
    return AsyncClient(transport=transport, base_url="http://test")


async def test_normalize_returns_id(client):
    resp = await client.post("/normalize", json={"objective": "do stuff"})
    data = resp.json()
    uuid.UUID(data["id"])


async def test_normalize_extracts_objective(client):
    resp = await client.post("/normalize", json={"objective": "build widget"})
    assert resp.json()["objective"] == "build widget"


async def test_normalize_extracts_inputs(client):
    resp = await client.post("/normalize", json={"objective": "x", "inputs": {"a": 1}})
    assert resp.json()["inputs"] == {"a": 1}


async def test_normalize_defaults_missing_objective(client):
    resp = await client.post("/normalize", json={})
    assert resp.json()["objective"] == ""


async def test_normalize_defaults_missing_inputs(client):
    resp = await client.post("/normalize", json={"objective": "x"})
    assert resp.json()["inputs"] == {}


async def test_normalize_preserves_raw(client):
    payload = {"objective": "x"}
    resp = await client.post("/normalize", json=payload)
    raw = resp.json()["raw"]
    assert raw["objective"] == "x"
    assert "inputs" in raw
    assert "source" in raw


async def test_normalize_includes_source(client):
    resp = await client.post("/normalize", json={"objective": "x", "source": "github"})
    assert resp.json()["source"] == "github"


async def test_normalize_classifies_code_task(client):
    resp = await client.post("/normalize", json={"objective": "Implement a new API endpoint"})
    data = resp.json()
    assert data["category"] == "code_generation"
    assert data["tier"] == "highest_leverage"
    assert "classification" in data


async def test_normalize_classifies_research_task(client):
    resp = await client.post("/normalize", json={"objective": "Research and summarize best practices"})
    data = resp.json()
    assert data["category"] == "research_synthesis"


async def test_normalize_returns_leverage_score(client):
    resp = await client.post("/normalize", json={"objective": "Build a REST API function"})
    data = resp.json()
    assert data["leverage_score"] > 0
    assert data["cost_tier"] in ("low", "mid", "high")


async def test_categories_endpoint(client):
    resp = await client.get("/categories")
    cats = resp.json()
    assert len(cats) == 20


async def test_categories_filter_by_tier(client):
    resp = await client.get("/categories?tier=highest_leverage")
    cats = resp.json()
    assert len(cats) == 5
    assert all(c["tier"] == "highest_leverage" for c in cats)


async def test_health_endpoint(client):
    resp = await client.get("/health")
    assert resp.json()["ok"] == 1
