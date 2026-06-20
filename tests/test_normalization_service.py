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
    payload = {"objective": "x", "extra": "data"}
    resp = await client.post("/normalize", json=payload)
    assert resp.json()["raw"] == payload
