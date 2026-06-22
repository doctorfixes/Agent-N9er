import os
import pytest
import asyncio
from unittest.mock import patch

os.environ["AUDIT_DB_PATH"] = "/tmp/test_audit.db"

from shared.audit import (
    init_audit_db,
    record_audit_event,
    query_audit_logs,
    _classify_action,
    _extract_resource,
    _audit_log,
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
