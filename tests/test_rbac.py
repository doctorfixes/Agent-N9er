import pytest
from shared.rbac import Role, has_permission, get_user_permissions, ROLE_HIERARCHY


class TestRoleHierarchy:
    def test_admin_highest(self):
        assert ROLE_HIERARCHY[Role.ADMIN] > ROLE_HIERARCHY[Role.OPERATOR]
        assert ROLE_HIERARCHY[Role.ADMIN] > ROLE_HIERARCHY[Role.VIEWER]

    def test_operator_mid(self):
        assert ROLE_HIERARCHY[Role.OPERATOR] > ROLE_HIERARCHY[Role.VIEWER]
        assert ROLE_HIERARCHY[Role.OPERATOR] < ROLE_HIERARCHY[Role.ADMIN]

    def test_viewer_lowest(self):
        assert ROLE_HIERARCHY[Role.VIEWER] < ROLE_HIERARCHY[Role.OPERATOR]


class TestHasPermission:
    def test_admin_has_all_permissions(self):
        assert has_permission("admin", "system:admin")
        assert has_permission("admin", "users:write")
        assert has_permission("admin", "apikeys:write")
        assert has_permission("admin", "system:read")
        assert has_permission("admin", "agents:read")

    def test_operator_has_mid_permissions(self):
        assert has_permission("operator", "system:read")
        assert has_permission("operator", "agents:read")
        assert has_permission("operator", "tasks:write")
        assert has_permission("operator", "pipeline:execute")
        assert has_permission("operator", "audit:read")
        assert has_permission("operator", "export:read")

    def test_operator_cannot_admin(self):
        assert not has_permission("operator", "system:admin")
        assert not has_permission("operator", "users:write")
        assert not has_permission("operator", "apikeys:write")
        assert not has_permission("operator", "billing:write")

    def test_viewer_readonly(self):
        assert has_permission("viewer", "system:read")
        assert has_permission("viewer", "agents:read")
        assert has_permission("viewer", "tasks:read")
        assert has_permission("viewer", "pipeline:read")

    def test_viewer_cannot_write(self):
        assert not has_permission("viewer", "system:write")
        assert not has_permission("viewer", "tasks:write")
        assert not has_permission("viewer", "pipeline:execute")
        assert not has_permission("viewer", "users:read")

    def test_unknown_role_gets_viewer(self):
        assert has_permission("unknown_role", "system:read")
        assert not has_permission("unknown_role", "system:write")

    def test_unknown_permission_requires_admin(self):
        assert has_permission("admin", "nonexistent:perm")
        assert not has_permission("operator", "nonexistent:perm")


class TestGetUserPermissions:
    def test_admin_gets_all(self):
        perms = get_user_permissions("admin")
        assert "system:admin" in perms
        assert "users:write" in perms
        assert "system:read" in perms

    def test_viewer_gets_read_only(self):
        perms = get_user_permissions("viewer")
        assert "system:read" in perms
        assert "agents:read" in perms
        assert "system:admin" not in perms
        assert "users:write" not in perms

    def test_operator_subset(self):
        admin_perms = set(get_user_permissions("admin"))
        operator_perms = set(get_user_permissions("operator"))
        viewer_perms = set(get_user_permissions("viewer"))
        assert viewer_perms.issubset(operator_perms)
        assert operator_perms.issubset(admin_perms)
