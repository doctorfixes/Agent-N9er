import os
import time
import uuid
import json
import logging
from datetime import datetime, timezone
from collections import deque

import aiosqlite
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger("audit")

_default_audit_db = "/data/audit.db"
try:
    os.makedirs(os.path.dirname(_default_audit_db), exist_ok=True)
    _safe_audit_path = _default_audit_db
except PermissionError:
    _safe_audit_path = os.path.join(os.path.dirname(__file__), "audit.db")
AUDIT_DB_PATH = os.getenv("AUDIT_DB_PATH", _safe_audit_path)
MAX_MEMORY_ENTRIES = 500

_audit_log: deque = deque(maxlen=MAX_MEMORY_ENTRIES)


async def init_audit_db():
    os.makedirs(os.path.dirname(AUDIT_DB_PATH), exist_ok=True)
    async with aiosqlite.connect(AUDIT_DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                user_id TEXT DEFAULT 'system',
                user_role TEXT DEFAULT 'system',
                action TEXT NOT NULL,
                resource_type TEXT,
                resource_id TEXT,
                method TEXT,
                path TEXT,
                status_code INTEGER,
                ip_address TEXT,
                request_id TEXT,
                details TEXT,
                duration_ms REAL
            )
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_log(timestamp)
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_log(user_id)
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_log(action)
        """)
        await db.commit()


async def record_audit_event(
    action: str,
    user_id: str = "system",
    user_role: str = "system",
    resource_type: str = None,
    resource_id: str = None,
    method: str = None,
    path: str = None,
    status_code: int = None,
    ip_address: str = None,
    request_id: str = None,
    details: dict = None,
    duration_ms: float = None,
):
    entry = {
        "id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "user_id": user_id,
        "user_role": user_role,
        "action": action,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "method": method,
        "path": path,
        "status_code": status_code,
        "ip_address": ip_address,
        "request_id": request_id,
        "details": details,
        "duration_ms": duration_ms,
    }

    _audit_log.appendleft(entry)

    try:
        async with aiosqlite.connect(AUDIT_DB_PATH) as db:
            await db.execute(
                """INSERT INTO audit_log
                   (id, timestamp, user_id, user_role, action, resource_type, resource_id,
                    method, path, status_code, ip_address, request_id, details, duration_ms)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    entry["id"], entry["timestamp"], user_id, user_role,
                    action, resource_type, resource_id, method, path,
                    status_code, ip_address, request_id,
                    json.dumps(details) if details else None, duration_ms,
                ),
            )
            await db.commit()
    except Exception as e:
        logger.error("Failed to persist audit log: %s", e)


async def query_audit_logs(
    limit: int = 50,
    offset: int = 0,
    user_id: str = None,
    action: str = None,
    resource_type: str = None,
    since: str = None,
    until: str = None,
):
    conditions = []
    params = []

    if user_id:
        conditions.append("user_id = ?")
        params.append(user_id)
    if action:
        conditions.append("action LIKE ?")
        params.append(f"%{action}%")
    if resource_type:
        conditions.append("resource_type = ?")
        params.append(resource_type)
    if since:
        conditions.append("timestamp >= ?")
        params.append(since)
    if until:
        conditions.append("timestamp <= ?")
        params.append(until)

    where_clause = " AND ".join(conditions) if conditions else "1=1"

    try:
        async with aiosqlite.connect(AUDIT_DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            count_cursor = await db.execute(
                f"SELECT COUNT(*) as total FROM audit_log WHERE {where_clause}", params
            )
            total = (await count_cursor.fetchone())["total"]

            cursor = await db.execute(
                f"SELECT * FROM audit_log WHERE {where_clause} ORDER BY timestamp DESC LIMIT ? OFFSET ?",
                params + [limit, offset],
            )
            rows = await cursor.fetchall()

            entries = []
            for row in rows:
                entry = dict(row)
                if entry.get("details"):
                    try:
                        entry["details"] = json.loads(entry["details"])
                    except (json.JSONDecodeError, TypeError):
                        pass
                entries.append(entry)

            return {"total": total, "limit": limit, "offset": offset, "entries": entries}
    except Exception as e:
        logger.error("Failed to query audit logs: %s", e)
        return {"total": 0, "limit": limit, "offset": offset, "entries": list(_audit_log)[:limit]}


SKIP_PATHS = {"/health", "/docs", "/openapi.json", "/redoc", "/favicon.ico"}
SKIP_PREFIXES = ("/_next", "/static")


def _classify_action(method: str, path: str) -> str:
    if method == "GET":
        return "read"
    if method == "POST" and "pipeline" in path:
        return "pipeline.execute"
    if method == "POST" and "register" in path:
        return "agent.register"
    if method == "POST" and "scan" in path:
        return "scan.trigger"
    if method == "POST" and "bid" in path:
        return "bid.submit"
    if method == "DELETE":
        return "delete"
    return f"{method.lower()}.request"


def _extract_resource(path: str) -> tuple[str | None, str | None]:
    parts = [p for p in path.strip("/").split("/") if p]
    if len(parts) >= 2:
        return parts[0], parts[1] if len(parts) > 1 else None
    if len(parts) == 1:
        return parts[0], None
    return None, None


class AuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path in SKIP_PATHS or any(path.startswith(p) for p in SKIP_PREFIXES):
            return await call_next(request)

        start = time.time()
        response = await call_next(request)
        duration_ms = (time.time() - start) * 1000

        if response.status_code < 400 and request.method == "GET":
            return response

        user_id = getattr(request.state, "user_id", "anonymous") if hasattr(request, "state") else "anonymous"
        user_role = getattr(request.state, "user_role", "unknown") if hasattr(request, "state") else "unknown"
        request_id = getattr(request.state, "request_id", None) if hasattr(request, "state") else None
        client_ip = request.client.host if request.client else "unknown"
        resource_type, resource_id = _extract_resource(path)

        await record_audit_event(
            action=_classify_action(request.method, path),
            user_id=user_id,
            user_role=user_role,
            resource_type=resource_type,
            resource_id=resource_id,
            method=request.method,
            path=path,
            status_code=response.status_code,
            ip_address=client_ip,
            request_id=request_id,
            duration_ms=round(duration_ms, 2),
        )

        return response
