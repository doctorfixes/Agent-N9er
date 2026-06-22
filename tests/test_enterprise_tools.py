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
