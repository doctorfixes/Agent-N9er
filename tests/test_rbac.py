import pytest
from unittest.mock import AsyncMock, MagicMock

from shared.rbac import Role, has_permission, get_user_permissions, ROLE_HIERARCHY, RBACMiddleware, require_permission


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


def _make_request(path, method="GET", user_role=None):
    """Create a mock request for middleware testing."""
    request = MagicMock()
    request.url.path = path
    request.method = method
    request.state = MagicMock()
    if user_role is not None:
        request.state.user_role = user_role
    else:
        # Simulate no role on request
        del request.state.user_role
        type(request.state).user_role = property(lambda self: (_ for _ in ()).throw(AttributeError()))
    return request


class TestRBACMiddleware:
    async def test_open_path_passes_through(self):
        middleware = RBACMiddleware(app=MagicMock())
        request = _make_request("/health", "GET", user_role="viewer")
        expected_response = MagicMock()

        async def call_next(req):
            return expected_response

        result = await middleware.dispatch(request, call_next)
        assert result is expected_response

    async def test_open_path_docs(self):
        middleware = RBACMiddleware(app=MagicMock())
        request = _make_request("/docs", "GET", user_role="viewer")

        async def call_next(req):
            return MagicMock()

        result = await middleware.dispatch(request, call_next)
        # Should pass through without checking permissions
        assert result is not None

    async def test_no_role_passes_through(self):
        middleware = RBACMiddleware(app=MagicMock())
        request = _make_request("/agents", "GET", user_role=None)
        expected_response = MagicMock()

        async def call_next(req):
            return expected_response

        # getattr(request.state, "user_role", None) should return None
        request.state = MagicMock(spec=[])  # no attributes
        result = await middleware.dispatch(request, call_next)
        assert result is expected_response

    async def test_sufficient_permission_passes(self):
        middleware = RBACMiddleware(app=MagicMock())
        request = _make_request("/agents", "GET", user_role="viewer")
        expected_response = MagicMock()

        async def call_next(req):
            return expected_response

        result = await middleware.dispatch(request, call_next)
        assert result is expected_response

    async def test_insufficient_permission_returns_403(self):
        middleware = RBACMiddleware(app=MagicMock())
        request = _make_request("/admin/users", "POST", user_role="viewer")

        async def call_next(req):
            return MagicMock()

        result = await middleware.dispatch(request, call_next)
        assert result.status_code == 403

    async def test_admin_can_access_admin_routes(self):
        middleware = RBACMiddleware(app=MagicMock())
        request = _make_request("/admin/users", "POST", user_role="admin")
        expected_response = MagicMock()

        async def call_next(req):
            return expected_response

        result = await middleware.dispatch(request, call_next)
        assert result is expected_response

    async def test_operator_cannot_access_admin_routes(self):
        middleware = RBACMiddleware(app=MagicMock())
        request = _make_request("/admin/apikeys", "POST", user_role="operator")

        async def call_next(req):
            return MagicMock()

        result = await middleware.dispatch(request, call_next)
        assert result.status_code == 403

    async def test_unmatched_route_passes_through(self):
        middleware = RBACMiddleware(app=MagicMock())
        request = _make_request("/some/random/path", "GET", user_role="viewer")
        expected_response = MagicMock()

        async def call_next(req):
            return expected_response

        result = await middleware.dispatch(request, call_next)
        assert result is expected_response

    async def test_trailing_slash_stripped(self):
        middleware = RBACMiddleware(app=MagicMock())
        # /admin/users/ with trailing slash should match /admin/users
        request = _make_request("/admin/users/", "POST", user_role="viewer")

        async def call_next(req):
            return MagicMock()

        result = await middleware.dispatch(request, call_next)
        assert result.status_code == 403


class TestRequirePermission:
    async def test_allows_sufficient_permissions(self):
        @require_permission("system:read")
        async def handler(request):
            return {"status": "ok"}

        request = MagicMock()
        request.state = MagicMock()
        request.state.user_role = "viewer"

        result = await handler(request)
        assert result == {"status": "ok"}

    async def test_blocks_insufficient_permissions(self):
        @require_permission("system:admin")
        async def handler(request):
            return {"status": "ok"}

        request = MagicMock()
        request.state = MagicMock()
        request.state.user_role = "viewer"

        result = await handler(request)
        assert result.status_code == 403

    async def test_uses_request_from_kwargs(self):
        @require_permission("system:admin")
        async def handler(request=None):
            return {"status": "ok"}

        request = MagicMock()
        request.state = MagicMock()
        request.state.user_role = "admin"

        result = await handler(request=request)
        assert result == {"status": "ok"}

    async def test_defaults_to_viewer_when_no_role(self):
        @require_permission("system:admin")
        async def handler(request):
            return {"status": "ok"}

        request = MagicMock()
        request.state = MagicMock(spec=[])  # no user_role attribute

        result = await handler(request)
        assert result.status_code == 403

    async def test_no_request_passes_through(self):
        @require_permission("system:admin")
        async def handler():
            return {"status": "ok"}

        result = await handler()
        assert result == {"status": "ok"}
