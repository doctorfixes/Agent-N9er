import os
import pytest
from httpx import AsyncClient, ASGITransport

os.environ["ENTERPRISE_DB_PATH"] = "/tmp/test_enterprise.db"
os.environ["AUDIT_DB_PATH"] = "/tmp/test_enterprise_audit.db"

from enterprise_tools.main import app, _init_db, _hash_password
from shared.audit import init_audit_db


def _client():
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest.fixture(autouse=True)
async def setup_db():
    for path in ["/tmp/test_enterprise.db", "/tmp/test_enterprise_audit.db"]:
        if os.path.exists(path):
            os.remove(path)
    await _init_db()
    await init_audit_db()
    yield
    for path in ["/tmp/test_enterprise.db", "/tmp/test_enterprise_audit.db"]:
        if os.path.exists(path):
            os.remove(path)


class TestHealthEndpoint:
    @pytest.mark.asyncio
    async def test_health(self):
        async with _client() as client:
            resp = await client.get("/health")
            assert resp.status_code == 200
            data = resp.json()
            assert data["ok"] == 1
            assert data["service"] == "enterprise_tools"
            assert "users" in data
            assert "active_keys" in data


class TestUserManagement:
    @pytest.mark.asyncio
    async def test_list_users(self):
        async with _client() as client:
            resp = await client.get("/admin/users")
            assert resp.status_code == 200
            users = resp.json()
            assert isinstance(users, list)
            assert len(users) >= 3  # admin, operator, viewer defaults

    @pytest.mark.asyncio
    async def test_create_user(self):
        async with _client() as client:
            resp = await client.post("/admin/users", json={
                "username": "newuser",
                "password": "secret123",
                "role": "operator",
                "display_name": "New User",
            })
            assert resp.status_code == 200
            data = resp.json()
            assert data["ok"] == 1
            assert data["username"] == "newuser"

    @pytest.mark.asyncio
    async def test_create_duplicate_user(self):
        async with _client() as client:
            await client.post("/admin/users", json={
                "username": "dupeuser", "password": "pass", "role": "viewer"
            })
            resp = await client.post("/admin/users", json={
                "username": "dupeuser", "password": "pass2", "role": "viewer"
            })
            assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_create_user_invalid_role(self):
        async with _client() as client:
            resp = await client.post("/admin/users", json={
                "username": "badrole", "password": "pass", "role": "superadmin"
            })
            assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_authenticate_user(self):
        async with _client() as client:
            resp = await client.post("/admin/users/authenticate", json={
                "username": "admin", "password": "admin"
            })
            assert resp.status_code == 200
            data = resp.json()
            assert data["ok"] == 1
            assert data["role"] == "admin"
            assert "permissions" in data

    @pytest.mark.asyncio
    async def test_authenticate_invalid_password(self):
        async with _client() as client:
            resp = await client.post("/admin/users/authenticate", json={
                "username": "admin", "password": "wrong"
            })
            assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_update_user(self):
        async with _client() as client:
            # First create a user
            create_resp = await client.post("/admin/users", json={
                "username": "updateme", "password": "pass", "role": "viewer"
            })
            user_id = create_resp.json()["user_id"]

            # Update role
            resp = await client.put(f"/admin/users/{user_id}", json={"role": "operator"})
            assert resp.status_code == 200

            # Verify
            users_resp = await client.get("/admin/users")
            users = users_resp.json()
            updated = [u for u in users if u["user_id"] == user_id]
            assert len(updated) == 1
            assert updated[0]["role"] == "operator"


class TestAPIKeyManagement:
    @pytest.mark.asyncio
    async def test_create_and_list_key(self):
        async with _client() as client:
            resp = await client.post("/admin/apikeys", json={
                "name": "Test Key",
                "role": "viewer",
                "expires_in_days": 30,
            })
            assert resp.status_code == 200
            data = resp.json()
            assert data["ok"] == 1
            assert data["api_key"].startswith("n9er_")
            assert "expires_at" in data

            list_resp = await client.get("/admin/apikeys")
            keys = list_resp.json()
            assert len(keys) >= 1
            assert any(k["name"] == "Test Key" for k in keys)

    @pytest.mark.asyncio
    async def test_revoke_key(self):
        async with _client() as client:
            create_resp = await client.post("/admin/apikeys", json={
                "name": "Revoke Me", "role": "viewer", "expires_in_days": 30,
            })
            key_id = create_resp.json()["key_id"]

            resp = await client.delete(f"/admin/apikeys/{key_id}")
            assert resp.status_code == 200

            list_resp = await client.get("/admin/apikeys")
            keys = list_resp.json()
            revoked = [k for k in keys if k["key_id"] == key_id]
            assert len(revoked) == 1
            assert revoked[0]["active"] == 0


class TestSystemConfig:
    @pytest.mark.asyncio
    async def test_set_and_get_config(self):
        async with _client() as client:
            resp = await client.post("/admin/config", json={
                "markup_multiplier": "3.5",
                "auto_scan_enabled": "true",
            })
            assert resp.status_code == 200
            assert "markup_multiplier" in resp.json()["updated"]

            get_resp = await client.get("/admin/config")
            config = get_resp.json()
            assert "markup_multiplier" in config
            assert config["markup_multiplier"]["value"] == "3.5"


class TestAuditEndpoint:
    @pytest.mark.asyncio
    async def test_audit_logs_returned(self):
        async with _client() as client:
            # Create a user to generate an audit event
            await client.post("/admin/users", json={
                "username": "audituser", "password": "pass", "role": "viewer"
            })

            resp = await client.get("/audit/logs", params={"limit": 10})
            assert resp.status_code == 200
            data = resp.json()
            assert "entries" in data
            assert "total" in data


class TestPasswordHashing:
    def test_deterministic(self):
        h1 = _hash_password("test")
        h2 = _hash_password("test")
        assert h1 == h2

    def test_different_passwords(self):
        h1 = _hash_password("pass1")
        h2 = _hash_password("pass2")
        assert h1 != h2


class TestSystemHealth:
    @pytest.mark.asyncio
    async def test_system_health_all_unreachable(self):
        """Test /system/health when all services are unreachable."""
        async with _client() as client:
            resp = await client.get("/system/health")
            assert resp.status_code == 200
            data = resp.json()
            assert "overall" in data
            assert "healthy_count" in data
            assert "total_count" in data
            assert "services" in data
            assert "checked_at" in data
            # All services should be unreachable since nothing is running
            assert data["overall"] in ("down", "degraded")
            for name, info in data["services"].items():
                assert info["status"] in ("unreachable", "healthy", "degraded")


class TestAuthenticateUser:
    @pytest.mark.asyncio
    async def test_authenticate_nonexistent_user(self):
        async with _client() as client:
            resp = await client.post("/admin/users/authenticate", json={
                "username": "nonexistent", "password": "anything"
            })
            assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_authenticate_returns_permissions(self):
        async with _client() as client:
            resp = await client.post("/admin/users/authenticate", json={
                "username": "admin", "password": "admin"
            })
            assert resp.status_code == 200
            data = resp.json()
            assert isinstance(data["permissions"], list)
            assert len(data["permissions"]) > 0


class TestAPIKeyCreateAndRevoke:
    @pytest.mark.asyncio
    async def test_create_key_with_custom_role(self):
        async with _client() as client:
            resp = await client.post("/admin/apikeys", json={
                "name": "Operator Key",
                "role": "operator",
                "expires_in_days": 60,
            })
            assert resp.status_code == 200
            data = resp.json()
            assert data["ok"] == 1
            assert data["api_key"].startswith("n9er_")

    @pytest.mark.asyncio
    async def test_revoke_nonexistent_key(self):
        async with _client() as client:
            resp = await client.delete("/admin/apikeys/nonexistent-key-id")
            assert resp.status_code == 404


class TestGetConfig:
    @pytest.mark.asyncio
    async def test_get_config_empty(self):
        async with _client() as client:
            resp = await client.get("/admin/config")
            assert resp.status_code == 200
            assert isinstance(resp.json(), dict)

    @pytest.mark.asyncio
    async def test_update_config_skips_underscore_keys(self):
        async with _client() as client:
            resp = await client.post("/admin/config", json={
                "_internal": "hidden",
                "visible_key": "value",
            })
            assert resp.status_code == 200
            data = resp.json()
            assert "visible_key" in data["updated"]
            assert "_internal" not in data["updated"]


class TestBulkDispatchTasks:
    @pytest.mark.asyncio
    async def test_bulk_dispatch_all_fail(self):
        """Test bulk task dispatch when orchestrator is unreachable."""
        from unittest.mock import patch, AsyncMock
        import httpx as _httpx

        mock_client = AsyncMock()
        mock_client.post.side_effect = _httpx.ConnectError("connection refused")

        with patch("enterprise_tools.main.httpx.AsyncClient") as MockClass:
            MockClass.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClass.return_value.__aexit__ = AsyncMock(return_value=False)
            async with _client() as client:
                resp = await client.post("/bulk/tasks", json={
                    "objectives": ["task 1", "task 2"],
                    "mode": "publish",
                    "source": "test",
                })
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert data["failed"] == 2
        assert data["dispatched"] == 0

    @pytest.mark.asyncio
    async def test_bulk_dispatch_full_mode(self):
        """Test bulk task dispatch in full pipeline mode."""
        from unittest.mock import patch, AsyncMock, MagicMock
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"status": "completed", "task_id": "t1"}

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp

        with patch("enterprise_tools.main.httpx.AsyncClient") as MockClass:
            MockClass.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClass.return_value.__aexit__ = AsyncMock(return_value=False)
            async with _client() as client:
                resp = await client.post("/bulk/tasks", json={
                    "objectives": ["task 1"],
                    "mode": "full",
                    "source": "test",
                })
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["dispatched"] == 1


class TestBulkRegisterAgents:
    @pytest.mark.asyncio
    async def test_bulk_register_all_fail(self):
        """Test bulk agent registration when orchestrator is unreachable."""
        from unittest.mock import patch, AsyncMock
        import httpx as _httpx

        mock_client = AsyncMock()
        mock_client.post.side_effect = _httpx.ConnectError("connection refused")

        with patch("enterprise_tools.main.httpx.AsyncClient") as MockClass:
            MockClass.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClass.return_value.__aexit__ = AsyncMock(return_value=False)
            async with _client() as client:
                resp = await client.post("/bulk/agents", json={
                    "agents": [
                        {"agent_id": "a1", "profile": "speed"},
                        {"agent_id": "a2", "profile": "precision"},
                    ],
                })
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert data["failed"] == 2
        assert data["registered"] == 0


class TestExportAuditCSV:
    @pytest.mark.asyncio
    async def test_export_audit_csv(self):
        async with _client() as client:
            # Generate some audit events first
            await client.post("/admin/users", json={
                "username": "exportuser", "password": "pass", "role": "viewer"
            })

            resp = await client.get("/export/audit")
            assert resp.status_code == 200
            assert "text/csv" in resp.headers["content-type"]
            content = resp.text
            # Should have CSV header
            assert "id" in content
            assert "timestamp" in content
            assert "action" in content

    @pytest.mark.asyncio
    async def test_export_audit_csv_with_params(self):
        async with _client() as client:
            resp = await client.get("/export/audit", params={
                "limit": 10,
                "since": "2020-01-01",
            })
            assert resp.status_code == 200
            assert "text/csv" in resp.headers["content-type"]


class TestExportAgentsCSV:
    @pytest.mark.asyncio
    async def test_export_agents_csv_unreachable(self):
        """Test agent export when orchestrator is unreachable."""
        from unittest.mock import patch, AsyncMock
        import httpx as _httpx

        mock_client = AsyncMock()
        mock_client.get.side_effect = _httpx.ConnectError("connection refused")

        with patch("enterprise_tools.main.httpx.AsyncClient") as MockClass:
            MockClass.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClass.return_value.__aexit__ = AsyncMock(return_value=False)
            async with _client() as client:
                resp = await client.get("/export/agents")
        assert resp.status_code == 503


class TestSystemOverview:
    @pytest.mark.asyncio
    async def test_system_overview(self):
        """Test the system overview endpoint."""
        async with _client() as client:
            resp = await client.get("/system/overview")
            assert resp.status_code == 200
            data = resp.json()
            assert "timestamp" in data
            assert "services" in data
            assert "agents" in data
            assert "tasks" in data
            assert "users" in data
            assert "api_keys" in data
            # Users should be > 0 due to default seeding
            assert data["users"] >= 3
