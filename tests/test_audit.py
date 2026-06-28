import os
import time
import pytest
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock

os.environ["AUDIT_DB_PATH"] = "/tmp/test_audit.db"

from shared.audit import (
    init_audit_db,
    record_audit_event,
    query_audit_logs,
    _classify_action,
    _extract_resource,
    _audit_log,
    AuditMiddleware,
    SKIP_PATHS,
)


@pytest.fixture(autouse=True)
async def setup_db():
    if os.path.exists("/tmp/test_audit.db"):
        os.remove("/tmp/test_audit.db")
    await init_audit_db()
    _audit_log.clear()
    yield
    if os.path.exists("/tmp/test_audit.db"):
        os.remove("/tmp/test_audit.db")


class TestClassifyAction:
    def test_get_is_read(self):
        assert _classify_action("GET", "/agents") == "read"

    def test_post_pipeline(self):
        assert _classify_action("POST", "/pipeline/full") == "pipeline.execute"

    def test_post_register(self):
        assert _classify_action("POST", "/agents/register") == "agent.register"

    def test_post_scan(self):
        assert _classify_action("POST", "/scan/trigger") == "scan.trigger"

    def test_delete(self):
        assert _classify_action("DELETE", "/admin/apikeys/123") == "delete"

    def test_generic_post(self):
        assert _classify_action("POST", "/something") == "post.request"


class TestExtractResource:
    def test_two_parts(self):
        rtype, rid = _extract_resource("/agents/abc123")
        assert rtype == "agents"
        assert rid == "abc123"

    def test_one_part(self):
        rtype, rid = _extract_resource("/health")
        assert rtype == "health"
        assert rid is None

    def test_empty(self):
        rtype, rid = _extract_resource("/")
        assert rtype is None
        assert rid is None


@pytest.mark.asyncio
class TestAuditLogging:
    async def test_record_and_query(self):
        await record_audit_event(
            action="test.action",
            user_id="testuser",
            user_role="admin",
            resource_type="test",
            resource_id="123",
            method="POST",
            path="/test",
            status_code=200,
        )

        result = await query_audit_logs(limit=10)
        assert result["total"] >= 1
        entries = result["entries"]
        assert len(entries) >= 1
        assert entries[0]["action"] == "test.action"
        assert entries[0]["user_id"] == "testuser"

    async def test_query_filter_by_user(self):
        await record_audit_event(action="a1", user_id="alice")
        await record_audit_event(action="a2", user_id="bob")

        result = await query_audit_logs(user_id="alice")
        assert all(e["user_id"] == "alice" for e in result["entries"])

    async def test_query_filter_by_action(self):
        await record_audit_event(action="pipeline.execute", user_id="test")
        await record_audit_event(action="read", user_id="test")

        result = await query_audit_logs(action="pipeline")
        assert all("pipeline" in e["action"] for e in result["entries"])

    async def test_in_memory_log(self):
        _audit_log.clear()
        await record_audit_event(action="memory.test", user_id="mem")
        assert len(_audit_log) >= 1
        assert _audit_log[0]["action"] == "memory.test"

    async def test_pagination(self):
        for i in range(5):
            await record_audit_event(action=f"page.{i}", user_id="pager")

        result = await query_audit_logs(limit=2, offset=0, user_id="pager")
        assert len(result["entries"]) == 2
        assert result["total"] >= 5

    async def test_query_filter_by_resource_type(self):
        await record_audit_event(action="test.rt", user_id="u1", resource_type="agents")
        await record_audit_event(action="test.rt", user_id="u1", resource_type="tasks")

        result = await query_audit_logs(resource_type="agents")
        assert all(e["resource_type"] == "agents" for e in result["entries"])

    async def test_query_filter_by_since(self):
        await record_audit_event(action="test.since", user_id="u1")
        # Use a far-future timestamp so nothing matches
        result = await query_audit_logs(since="2099-01-01T00:00:00")
        assert result["total"] == 0

    async def test_query_filter_by_until(self):
        await record_audit_event(action="test.until", user_id="u1")
        # Use a far-past timestamp so nothing matches
        result = await query_audit_logs(until="2000-01-01T00:00:00")
        assert result["total"] == 0

    async def test_query_filter_since_and_until_bracket(self):
        await record_audit_event(action="test.bracket", user_id="u1")
        # Use a wide bracket that includes now
        result = await query_audit_logs(since="2020-01-01T00:00:00", until="2099-12-31T23:59:59")
        assert result["total"] >= 1


class TestClassifyActionBid:
    def test_post_bid(self):
        assert _classify_action("POST", "/bid/submit") == "bid.submit"

    def test_post_bid_nested(self):
        assert _classify_action("POST", "/api/bid") == "bid.submit"


class TestAuditMiddleware:
    async def test_skip_paths_pass_through(self):
        middleware = AuditMiddleware(app=MagicMock())
        for path in ["/health", "/docs", "/openapi.json", "/redoc", "/favicon.ico"]:
            request = MagicMock()
            request.url.path = path
            expected_response = MagicMock()

            async def call_next(req):
                return expected_response

            result = await middleware.dispatch(request, call_next)
            assert result is expected_response

    async def test_skip_prefixes_pass_through(self):
        middleware = AuditMiddleware(app=MagicMock())
        for path in ["/_next/data/something", "/static/css/style.css"]:
            request = MagicMock()
            request.url.path = path
            expected_response = MagicMock()

            async def call_next(req):
                return expected_response

            result = await middleware.dispatch(request, call_next)
            assert result is expected_response

    async def test_successful_get_not_audited(self):
        middleware = AuditMiddleware(app=MagicMock())
        request = MagicMock()
        request.url.path = "/agents"
        request.method = "GET"
        request.state = MagicMock()
        request.state.user_id = "testuser"
        request.state.user_role = "viewer"
        request.state.request_id = "req-123"
        request.client.host = "127.0.0.1"

        response = MagicMock()
        response.status_code = 200

        async def call_next(req):
            return response

        _audit_log.clear()
        result = await middleware.dispatch(request, call_next)
        assert result is response

    async def test_post_request_is_audited(self):
        middleware = AuditMiddleware(app=MagicMock())
        request = MagicMock()
        request.url.path = "/pipeline/full"
        request.method = "POST"
        request.state = MagicMock()
        request.state.user_id = "testuser"
        request.state.user_role = "operator"
        request.state.request_id = "req-456"
        request.client.host = "10.0.0.1"

        response = MagicMock()
        response.status_code = 200

        async def call_next(req):
            return response

        _audit_log.clear()
        result = await middleware.dispatch(request, call_next)
        assert result is response
        assert len(_audit_log) >= 1
        assert _audit_log[0]["action"] == "pipeline.execute"

    async def test_error_response_is_audited(self):
        middleware = AuditMiddleware(app=MagicMock())
        request = MagicMock()
        request.url.path = "/agents"
        request.method = "GET"
        request.state = MagicMock()
        request.state.user_id = "failuser"
        request.state.user_role = "viewer"
        request.state.request_id = None
        request.client.host = "127.0.0.1"

        response = MagicMock()
        response.status_code = 500

        async def call_next(req):
            return response

        _audit_log.clear()
        result = await middleware.dispatch(request, call_next)
        assert result is response
        assert len(_audit_log) >= 1
        assert _audit_log[0]["action"] == "read"

    async def test_no_client_uses_unknown_ip(self):
        middleware = AuditMiddleware(app=MagicMock())
        request = MagicMock()
        request.url.path = "/pipeline"
        request.method = "POST"
        request.state = MagicMock()
        request.state.user_id = "testuser"
        request.state.user_role = "operator"
        request.state.request_id = None
        request.client = None

        response = MagicMock()
        response.status_code = 200

        async def call_next(req):
            return response

        _audit_log.clear()
        result = await middleware.dispatch(request, call_next)
        assert _audit_log[0]["ip_address"] == "unknown"
