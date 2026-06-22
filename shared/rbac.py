import os
import enum
from functools import wraps

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware


class Role(str, enum.Enum):
    ADMIN = "admin"
    OPERATOR = "operator"
    VIEWER = "viewer"


ROLE_HIERARCHY = {Role.ADMIN: 3, Role.OPERATOR: 2, Role.VIEWER: 1}

PERMISSIONS = {
    "system:read": Role.VIEWER,
    "system:write": Role.OPERATOR,
    "system:admin": Role.ADMIN,
    "agents:read": Role.VIEWER,
    "agents:write": Role.OPERATOR,
    "agents:delete": Role.ADMIN,
    "tasks:read": Role.VIEWER,
    "tasks:write": Role.OPERATOR,
    "tasks:delete": Role.ADMIN,
    "pipeline:read": Role.VIEWER,
    "pipeline:execute": Role.OPERATOR,
    "pipeline:admin": Role.ADMIN,
    "prospects:read": Role.VIEWER,
    "prospects:write": Role.OPERATOR,
    "billing:read": Role.OPERATOR,
    "billing:write": Role.ADMIN,
    "audit:read": Role.OPERATOR,
    "audit:admin": Role.ADMIN,
    "apikeys:read": Role.ADMIN,
    "apikeys:write": Role.ADMIN,
    "users:read": Role.ADMIN,
    "users:write": Role.ADMIN,
    "export:read": Role.OPERATOR,
    "config:read": Role.OPERATOR,
    "config:write": Role.ADMIN,
}


def has_permission(user_role: str, permission: str) -> bool:
    role = Role(user_role) if user_role in Role.__members__.values() else Role.VIEWER
    required_role = PERMISSIONS.get(permission, Role.ADMIN)
    return ROLE_HIERARCHY.get(role, 0) >= ROLE_HIERARCHY.get(required_role, 3)


def get_user_permissions(user_role: str) -> list[str]:
    return [perm for perm in PERMISSIONS if has_permission(user_role, perm)]


DEFAULT_USERS = {
    "admin": {"password_hash": "admin", "role": Role.ADMIN, "display_name": "System Admin"},
    "operator": {"password_hash": "operator", "role": Role.OPERATOR, "display_name": "Operator"},
    "viewer": {"password_hash": "viewer", "role": Role.VIEWER, "display_name": "Read-Only"},
}


class RBACMiddleware(BaseHTTPMiddleware):
    OPEN_PATHS = {"/health", "/docs", "/openapi.json", "/redoc"}

    ROUTE_PERMISSIONS = {
        ("GET", "/agents"): "agents:read",
        ("POST", "/agents/register"): "agents:write",
        ("GET", "/task-categories"): "system:read",
        ("GET", "/scan/status"): "system:read",
        ("POST", "/scan/trigger"): "pipeline:execute",
        ("POST", "/pipeline"): "pipeline:execute",
        ("POST", "/pipeline/full"): "pipeline:execute",
        ("POST", "/process-recurring"): "pipeline:execute",
        ("POST", "/revenue-pipeline"): "pipeline:admin",
        ("GET", "/audit/logs"): "audit:read",
        ("GET", "/admin/config"): "config:read",
        ("POST", "/admin/config"): "config:write",
        ("GET", "/admin/apikeys"): "apikeys:read",
        ("POST", "/admin/apikeys"): "apikeys:write",
        ("DELETE", "/admin/apikeys"): "apikeys:write",
        ("GET", "/admin/users"): "users:read",
        ("POST", "/admin/users"): "users:write",
        ("GET", "/export"): "export:read",
        ("POST", "/bulk"): "pipeline:execute",
    }

    async def dispatch(self, request: Request, call_next):
        if request.url.path in self.OPEN_PATHS:
            return await call_next(request)

        role = getattr(request.state, "user_role", None)
        if not role:
            return await call_next(request)

        path = request.url.path.rstrip("/")
        method = request.method
        required_perm = self.ROUTE_PERMISSIONS.get((method, path))

        if required_perm and not has_permission(role, required_perm):
            return JSONResponse(
                status_code=403,
                content={"detail": f"Insufficient permissions. Required: {required_perm}"},
            )

        return await call_next(request)


def require_permission(permission: str):
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            request = kwargs.get("request") or (args[0] if args else None)
            if request and hasattr(request, "state"):
                role = getattr(request.state, "user_role", "viewer")
                if not has_permission(role, permission):
                    return JSONResponse(
                        status_code=403,
                        content={"detail": f"Permission denied: {permission}"},
                    )
            return await func(*args, **kwargs)
        return wrapper
    return decorator
