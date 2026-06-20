from httpx import ASGITransport, AsyncClient
import pytest

from conftest import load_service

browser = load_service("browser_main", "browser_service")


@pytest.fixture
def client():
    transport = ASGITransport(app=browser.app)
    return AsyncClient(transport=transport, base_url="http://test")


async def test_health_returns_ok(client):
    resp = await client.get("/health")
    assert resp.json()["ok"] == 1


async def test_health_status_code(client):
    resp = await client.get("/health")
    assert resp.status_code == 200


async def test_watchers_list(client):
    resp = await client.get("/watchers")
    data = resp.json()
    assert "available" in data
    assert "gmail" in data["available"]
    assert len(data["available"]) == 8
