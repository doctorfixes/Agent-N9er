import os
import sys
import tempfile
import time
from unittest.mock import patch

from httpx import ASGITransport, AsyncClient
import pytest

_tmpdir = tempfile.mkdtemp()
os.environ["DB_PATH"] = os.path.join(_tmpdir, "test_security.db")

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, root)

from shared.security import (
    RequestIDMiddleware,
    RateLimitMiddleware,
    APIKeyMiddleware,
    ServiceTokenMiddleware,
    get_service_headers,
)

from conftest import load_service

marketplace = load_service("security_marketplace_main", "bidding_marketplace")


@pytest.fixture
async def client():
    async with marketplace.lifespan(marketplace.app):
        transport = ASGITransport(app=marketplace.app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


# --- Request ID tests ---

async def test_request_id_generated_when_absent(client):
    resp = await client.get("/health")
    assert "X-Request-ID" in resp.headers
    assert len(resp.headers["X-Request-ID"]) > 0


async def test_request_id_preserved_when_provided(client):
    custom_id = "custom-req-12345"
    resp = await client.get("/health", headers={"X-Request-ID": custom_id})
    assert resp.headers["X-Request-ID"] == custom_id


# --- Rate limit tests ---

async def test_rate_limit_headers_present():
    from fastapi import FastAPI

    test_app = FastAPI()

    @test_app.get("/data")
    async def data():
        return {"ok": 1}

    test_app.add_middleware(RateLimitMiddleware, max_requests=100, window_seconds=60)
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.get("/data")
        assert "X-RateLimit-Remaining" in resp.headers
        assert "X-RateLimit-Limit" in resp.headers
        assert resp.headers["X-RateLimit-Limit"] == "100"


async def test_health_bypasses_rate_limit():
    from fastapi import FastAPI

    test_app = FastAPI()

    @test_app.get("/health")
    async def health():
        return {"ok": 1}

    test_app.add_middleware(RateLimitMiddleware, max_requests=1, window_seconds=60)
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        for _ in range(5):
            resp = await c.get("/health")
            assert resp.status_code == 200
        assert "X-RateLimit-Remaining" not in resp.headers


# --- Audit log tests ---

async def test_audit_log_initially_empty(client):
    resp = await client.get("/audit")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_audit_log_records_publish(client):
    await client.post("/publish", json={"id": "audit-t1", "objective": "audit test"})
    resp = await client.get("/audit")
    logs = resp.json()
    assert len(logs) >= 1
    assert logs[0]["action"] == "publish"
    assert logs[0]["entity_type"] == "task"
    assert logs[0]["entity_id"] == "audit-t1"


async def test_audit_log_records_bid(client):
    await client.post("/publish", json={"id": "audit-t2", "objective": "bid audit"})
    await client.post("/bid", json={
        "task_id": "audit-t2", "agent_id": "a1", "confidence": 0.9
    })
    resp = await client.get("/audit")
    logs = resp.json()
    bid_logs = [l for l in logs if l["action"] == "bid"]
    assert len(bid_logs) >= 1
    assert "agent=a1" in bid_logs[0]["detail"]


async def test_audit_log_records_award(client):
    await client.post("/publish", json={"id": "audit-t3", "objective": "award audit"})
    await client.post("/bid", json={
        "task_id": "audit-t3", "agent_id": "a1", "confidence": 0.8,
        "require_approval": False,
    })
    await client.post("/award/audit-t3")
    resp = await client.get("/audit")
    logs = resp.json()
    award_logs = [l for l in logs if l["action"] == "award"]
    assert len(award_logs) >= 1
    assert "winner=a1" in award_logs[0]["detail"]


async def test_audit_log_records_complete(client):
    await client.post("/publish", json={"id": "audit-t4", "objective": "complete audit"})
    await client.post("/bid", json={
        "task_id": "audit-t4", "agent_id": "a1", "confidence": 0.7,
        "require_approval": False,
    })
    await client.post("/award/audit-t4")
    await client.post("/complete/audit-t4", json={"success": True})
    resp = await client.get("/audit")
    logs = resp.json()
    complete_logs = [l for l in logs if l["action"] == "complete"]
    assert len(complete_logs) >= 1
    assert "status=completed" in complete_logs[0]["detail"]


async def test_audit_log_pagination(client):
    for i in range(5):
        await client.post("/publish", json={"id": f"pag-{i}", "objective": f"pag test {i}"})
    resp = await client.get("/audit?limit=2&offset=0")
    assert len(resp.json()) == 2
    resp2 = await client.get("/audit?limit=2&offset=2")
    assert len(resp2.json()) == 2


# --- API key middleware tests (unit-level with patching) ---

async def test_api_key_rejects_when_configured():
    from fastapi import FastAPI

    test_app = FastAPI()

    @test_app.get("/health")
    async def health():
        return {"ok": 1}

    @test_app.get("/data")
    async def data():
        return {"data": "secret"}

    with patch("shared.security.API_KEY", "test-key-123"), \
         patch("shared.security.SERVICE_TOKEN", ""):
        test_app.add_middleware(APIKeyMiddleware)
        transport = ASGITransport(app=test_app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.get("/data")
            assert resp.status_code == 401

            resp = await c.get("/data", headers={"X-API-Key": "wrong-key"})
            assert resp.status_code == 401

            resp = await c.get("/data", headers={"X-API-Key": "test-key-123"})
            assert resp.status_code == 200

            resp = await c.get("/health")
            assert resp.status_code == 200


async def test_api_key_allows_service_token_bypass():
    from fastapi import FastAPI

    test_app = FastAPI()

    @test_app.get("/data")
    async def data():
        return {"data": "ok"}

    with patch("shared.security.API_KEY", "api-key"), \
         patch("shared.security.SERVICE_TOKEN", "svc-token"):
        test_app.add_middleware(APIKeyMiddleware)
        transport = ASGITransport(app=test_app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.get("/data", headers={"X-Service-Token": "svc-token"})
            assert resp.status_code == 200


async def test_service_token_rejects_when_configured():
    from fastapi import FastAPI

    test_app = FastAPI()

    @test_app.get("/health")
    async def health():
        return {"ok": 1}

    @test_app.get("/data")
    async def data():
        return {"data": "internal"}

    with patch("shared.security.SERVICE_TOKEN", "svc-secret"):
        test_app.add_middleware(ServiceTokenMiddleware)
        transport = ASGITransport(app=test_app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.get("/data")
            assert resp.status_code == 403

            resp = await c.get("/data", headers={"X-Service-Token": "wrong"})
            assert resp.status_code == 403

            resp = await c.get("/data", headers={"X-Service-Token": "svc-secret"})
            assert resp.status_code == 200

            resp = await c.get("/health")
            assert resp.status_code == 200


# --- get_service_headers tests ---

def test_get_service_headers_empty_when_no_token():
    with patch("shared.security.SERVICE_TOKEN", ""):
        headers = get_service_headers()
        assert headers == {}


def test_get_service_headers_includes_token():
    with patch("shared.security.SERVICE_TOKEN", "my-token"):
        headers = get_service_headers()
        assert headers == {"X-Service-Token": "my-token"}


# --- Rate limit enforcement test ---

async def test_rate_limit_enforced():
    from fastapi import FastAPI

    test_app = FastAPI()

    @test_app.get("/data")
    async def data():
        return {"ok": 1}

    test_app.add_middleware(RateLimitMiddleware, max_requests=3, window_seconds=60)
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        for _ in range(3):
            resp = await c.get("/data")
            assert resp.status_code == 200

        resp = await c.get("/data")
        assert resp.status_code == 429
