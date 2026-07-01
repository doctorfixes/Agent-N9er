import os
import sys
import uuid
import csv
import io
import hashlib
import secrets
import logging
from datetime import datetime, timezone
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
import aiosqlite
import httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared.security import (
    RequestIDMiddleware, RateLimitMiddleware, APIKeyMiddleware,
    get_service_headers,
)
from shared.config import (
    DEFAULT_TIMEOUT, RATE_LIMIT_MAX_REQUESTS, RATE_LIMIT_WINDOW_SECONDS,
    CORS_ORIGINS,
)
from shared.audit import init_audit_db, record_audit_event, query_audit_logs
from shared.rbac import Role, has_permission, get_user_permissions, DEFAULT_USERS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("enterprise_tools")

DB_PATH = os.getenv("ENTERPRISE_DB_PATH", "/data/enterprise.db")

ORCHESTRATOR_URL = os.getenv("ORCHESTRATOR_URL", "http://localhost:9000")
NORMALIZATION_URL = os.getenv("NORMALIZATION_URL", "http://localhost:8100")
RANKING_URL = os.getenv("RANKING_URL", "http://localhost:8200")
MARKETPLACE_URL = os.getenv("MARKETPLACE_URL", "http://localhost:8300")
EXECUTION_URL = os.getenv("EXECUTION_URL", "http://localhost:8700")
REPUTATION_URL = os.getenv("REPUTATION_URL", "http://localhost:8500")
RECURRING_URL = os.getenv("RECURRING_URL", "http://localhost:8600")
EVALUATOR_URL = os.getenv("EVALUATOR_URL", "http://localhost:8800")
PROSPECTOR_URL = os.getenv("PROSPECTOR_URL", "http://localhost:8900")
BILLING_URL = os.getenv("BILLING_URL", "http://localhost:9200")

SERVICE_REGISTRY = {
    "orchestrator": ORCHESTRATOR_URL,
    "normalization": NORMALIZATION_URL,
    "ranking": RANKING_URL,
    "marketplace": MARKETPLACE_URL,
    "execution": EXECUTION_URL,
    "reputation": REPUTATION_URL,
    "recurring": RECURRING_URL,
    "evaluator": EVALUATOR_URL,
    "prospector": PROSPECTOR_URL,
    "billing": BILLING_URL,
}


async def _init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS api_keys (
                key_id TEXT PRIMARY KEY,
                key_hash TEXT NOT NULL,
                key_prefix TEXT NOT NULL,
                name TEXT NOT NULL,
                role TEXT DEFAULT 'viewer',
                created_by TEXT,
                created_at TEXT NOT NULL,
                last_used_at TEXT,
                expires_at TEXT,
                active INTEGER DEFAULT 1,
                scopes TEXT DEFAULT '*'
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS enterprise_users (
                user_id TEXT PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT DEFAULT 'viewer',
                display_name TEXT,
                email TEXT,
                created_at TEXT NOT NULL,
                last_login_at TEXT,
                active INTEGER DEFAULT 1
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS system_config (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                updated_by TEXT DEFAULT 'system'
            )
        """)
        await db.commit()

    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT COUNT(*) FROM enterprise_users")
        count = (await cursor.fetchone())[0]
        if count == 0:
            now = datetime.now(timezone.utc).isoformat()
            for username, info in DEFAULT_USERS.items():
                await db.execute(
                    "INSERT OR IGNORE INTO enterprise_users (user_id, username, password_hash, role, display_name, created_at, active) VALUES (?, ?, ?, ?, ?, ?, 1)",
                    (str(uuid.uuid4()), username, _hash_password(info["password_hash"]),
                     info["role"].value, info["display_name"], now),
                )
            await db.commit()
            logger.info("Seeded default enterprise users")


def _hash_password(password: str) -> str:
    salt = os.getenv("PASSWORD_SALT", "n9er-enterprise-salt")
    return hashlib.sha256(f"{salt}:{password}".encode()).hexdigest()


def _svc_headers():
    return get_service_headers()


@asynccontextmanager
async def lifespan(app):
    await _init_db()
    await init_audit_db()
    yield


app = FastAPI(title="Agent N9er Enterprise Tools", lifespan=lifespan)

app.add_middleware(RequestIDMiddleware)
app.add_middleware(RateLimitMiddleware, max_requests=RATE_LIMIT_MAX_REQUESTS, window_seconds=RATE_LIMIT_WINDOW_SECONDS)
app.add_middleware(APIKeyMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute("SELECT COUNT(*) FROM enterprise_users")
            user_count = (await cursor.fetchone())[0]
            cursor = await db.execute("SELECT COUNT(*) FROM api_keys WHERE active = 1")
            key_count = (await cursor.fetchone())[0]
        return {"ok": 1, "service": "enterprise_tools", "users": user_count, "active_keys": key_count}
    except Exception:
        return {"ok": 0, "service": "enterprise_tools", "error": "db_unreachable"}


# ──────────────────────────────────────────────
# Health Aggregation
# ──────────────────────────────────────────────

@app.get("/system/health")
async def system_health():
    results = {}
    async with httpx.AsyncClient(timeout=5.0) as client:
        for name, url in SERVICE_REGISTRY.items():
            try:
                resp = await client.get(f"{url}/health", headers=_svc_headers())
                data = resp.json()
                results[name] = {
                    "status": "healthy" if data.get("ok") == 1 else "degraded",
                    "url": url,
                    "details": data,
                }
            except Exception as e:
                results[name] = {"status": "unreachable", "url": url, "error": str(e)}

    total = len(results)
    healthy = sum(1 for v in results.values() if v["status"] == "healthy")
    return {
        "overall": "healthy" if healthy == total else "degraded" if healthy > 0 else "down",
        "healthy_count": healthy,
        "total_count": total,
        "services": results,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


# ──────────────────────────────────────────────
# Audit Logs
# ──────────────────────────────────────────────

@app.get("/audit/logs")
async def get_audit_logs(
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    user_id: str = None,
    action: str = None,
    resource_type: str = None,
    since: str = None,
    until: str = None,
):
    return await query_audit_logs(
        limit=limit, offset=offset, user_id=user_id,
        action=action, resource_type=resource_type,
        since=since, until=until,
    )


# ──────────────────────────────────────────────
# User Management
# ──────────────────────────────────────────────

class CreateUserRequest(BaseModel):
    username: str
    password: str
    role: str = "viewer"
    display_name: str = ""
    email: str = ""


class UpdateUserRequest(BaseModel):
    role: str = None
    display_name: str = None
    email: str = None
    active: bool = None


@app.get("/admin/users")
async def list_users():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT user_id, username, role, display_name, email, created_at, last_login_at, active FROM enterprise_users ORDER BY created_at"
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


@app.post("/admin/users")
async def create_user(req: CreateUserRequest):
    if req.role not in [r.value for r in Role]:
        raise HTTPException(status_code=400, detail=f"Invalid role: {req.role}")

    user_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO enterprise_users (user_id, username, password_hash, role, display_name, email, created_at, active) VALUES (?, ?, ?, ?, ?, ?, ?, 1)",
                (user_id, req.username, _hash_password(req.password), req.role,
                 req.display_name or req.username, req.email, now),
            )
            await db.commit()
    except aiosqlite.IntegrityError:
        raise HTTPException(status_code=409, detail="Username already exists")

    await record_audit_event(
        action="user.create", resource_type="user", resource_id=user_id,
        details={"username": req.username, "role": req.role},
    )
    return {"ok": 1, "user_id": user_id, "username": req.username}


@app.put("/admin/users/{user_id}")
async def update_user(user_id: str, req: UpdateUserRequest):
    updates = []
    params = []
    if req.role is not None:
        if req.role not in [r.value for r in Role]:
            raise HTTPException(status_code=400, detail=f"Invalid role: {req.role}")
        updates.append("role = ?")
        params.append(req.role)
    if req.display_name is not None:
        updates.append("display_name = ?")
        params.append(req.display_name)
    if req.email is not None:
        updates.append("email = ?")
        params.append(req.email)
    if req.active is not None:
        updates.append("active = ?")
        params.append(1 if req.active else 0)

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    params.append(user_id)
    async with aiosqlite.connect(DB_PATH) as db:
        result = await db.execute(
            f"UPDATE enterprise_users SET {', '.join(updates)} WHERE user_id = ?", params
        )
        await db.commit()
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="User not found")

    await record_audit_event(
        action="user.update", resource_type="user", resource_id=user_id,
        details={k: v for k, v in req.model_dump().items() if v is not None},
    )
    return {"ok": 1, "user_id": user_id}


@app.post("/admin/users/authenticate")
async def authenticate_user(credentials: dict):
    username = credentials.get("username", "")
    password = credentials.get("password", "")

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT user_id, username, password_hash, role, display_name, active FROM enterprise_users WHERE username = ?",
            (username,),
        )
        user = await cursor.fetchone()

    if not user or not user["active"]:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if user["password_hash"] != _hash_password(password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE enterprise_users SET last_login_at = ? WHERE user_id = ?", (now, user["user_id"]))
        await db.commit()

    await record_audit_event(
        action="user.login", resource_type="user", resource_id=user["user_id"],
        user_id=user["username"], user_role=user["role"],
    )

    return {
        "ok": 1,
        "user_id": user["user_id"],
        "username": user["username"],
        "role": user["role"],
        "display_name": user["display_name"],
        "permissions": get_user_permissions(user["role"]),
    }


# ──────────────────────────────────────────────
# API Key Management
# ──────────────────────────────────────────────

class CreateAPIKeyRequest(BaseModel):
    name: str
    role: str = "viewer"
    scopes: str = "*"
    expires_in_days: int = Field(default=90, ge=1, le=365)


@app.get("/admin/apikeys")
async def list_api_keys():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT key_id, key_prefix, name, role, created_by, created_at, last_used_at, expires_at, active, scopes FROM api_keys ORDER BY created_at DESC"
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


@app.post("/admin/apikeys")
async def create_api_key(req: CreateAPIKeyRequest):
    raw_key = f"n9er_{secrets.token_urlsafe(32)}"
    key_id = str(uuid.uuid4())
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    key_prefix = raw_key[:12] + "..."
    now = datetime.now(timezone.utc)
    expires_at = datetime(
        now.year, now.month, now.day, tzinfo=timezone.utc
    ).__class__(
        now.year + (now.month + (req.expires_in_days // 30)) // 12,
        ((now.month + (req.expires_in_days // 30) - 1) % 12) + 1,
        min(now.day, 28),
        tzinfo=timezone.utc,
    )

    from datetime import timedelta
    expires_at = now + timedelta(days=req.expires_in_days)

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO api_keys (key_id, key_hash, key_prefix, name, role, created_at, expires_at, active, scopes) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)",
            (key_id, key_hash, key_prefix, req.name, req.role,
             now.isoformat(), expires_at.isoformat(), req.scopes),
        )
        await db.commit()

    await record_audit_event(
        action="apikey.create", resource_type="apikey", resource_id=key_id,
        details={"name": req.name, "role": req.role},
    )

    return {"ok": 1, "key_id": key_id, "api_key": raw_key, "prefix": key_prefix, "expires_at": expires_at.isoformat()}


@app.delete("/admin/apikeys/{key_id}")
async def revoke_api_key(key_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        result = await db.execute("UPDATE api_keys SET active = 0 WHERE key_id = ?", (key_id,))
        await db.commit()
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="API key not found")

    await record_audit_event(action="apikey.revoke", resource_type="apikey", resource_id=key_id)
    return {"ok": 1, "key_id": key_id}


# ──────────────────────────────────────────────
# System Configuration
# ──────────────────────────────────────────────

@app.get("/admin/config")
async def get_config():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM system_config ORDER BY key")
        rows = await cursor.fetchall()
        return {row["key"]: {"value": row["value"], "updated_at": row["updated_at"], "updated_by": row["updated_by"]} for row in rows}


@app.post("/admin/config")
async def update_config(config: dict):
    now = datetime.now(timezone.utc).isoformat()
    updated = []
    async with aiosqlite.connect(DB_PATH) as db:
        for key, value in config.items():
            if key.startswith("_"):
                continue
            await db.execute(
                "INSERT OR REPLACE INTO system_config (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                (key, str(value), now, "admin"),
            )
            updated.append(key)
        await db.commit()

    await record_audit_event(
        action="config.update", resource_type="config",
        details={"keys": updated},
    )
    return {"ok": 1, "updated": updated}


# ──────────────────────────────────────────────
# Bulk Operations
# ──────────────────────────────────────────────

class BulkTaskDispatch(BaseModel):
    objectives: list[str]
    mode: str = "publish"
    source: str = "bulk"


@app.post("/bulk/tasks")
async def bulk_dispatch_tasks(req: BulkTaskDispatch):
    results = []
    svc = _svc_headers()

    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        for objective in req.objectives[:50]:
            try:
                endpoint = f"{ORCHESTRATOR_URL}/pipeline"
                if req.mode == "full":
                    endpoint = f"{ORCHESTRATOR_URL}/pipeline/full"

                resp = await client.post(
                    endpoint,
                    json={"objective": objective, "source": req.source},
                    headers=svc,
                )
                resp.raise_for_status()
                data = resp.json()
                results.append({"objective": objective[:80], "status": data.get("status"), "task_id": data.get("task_id")})
            except Exception as e:
                results.append({"objective": objective[:80], "status": "error", "error": str(e)})

    await record_audit_event(
        action="bulk.dispatch", resource_type="tasks",
        details={"count": len(req.objectives), "mode": req.mode, "success": sum(1 for r in results if r.get("status") != "error")},
    )

    return {
        "total": len(req.objectives),
        "dispatched": sum(1 for r in results if r.get("status") != "error"),
        "failed": sum(1 for r in results if r.get("status") == "error"),
        "results": results,
    }


class BulkAgentRegister(BaseModel):
    agents: list[dict]


@app.post("/bulk/agents")
async def bulk_register_agents(req: BulkAgentRegister):
    results = []
    svc = _svc_headers()

    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        for agent in req.agents[:100]:
            try:
                resp = await client.post(
                    f"{ORCHESTRATOR_URL}/agents/register",
                    json=agent,
                    headers=svc,
                )
                resp.raise_for_status()
                results.append({"agent_id": agent.get("agent_id"), "status": "registered"})
            except Exception as e:
                results.append({"agent_id": agent.get("agent_id"), "status": "error", "error": str(e)})

    await record_audit_event(
        action="bulk.register_agents", resource_type="agents",
        details={"count": len(req.agents), "success": sum(1 for r in results if r["status"] == "registered")},
    )

    return {
        "total": len(req.agents),
        "registered": sum(1 for r in results if r["status"] == "registered"),
        "failed": sum(1 for r in results if r["status"] == "error"),
        "results": results,
    }


# ──────────────────────────────────────────────
# Data Export
# ──────────────────────────────────────────────

@app.get("/export/audit")
async def export_audit_csv(
    since: str = None,
    until: str = None,
    limit: int = Query(1000, le=10000),
):
    logs = await query_audit_logs(limit=limit, since=since, until=until)
    entries = logs["entries"]

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=[
        "id", "timestamp", "user_id", "user_role", "action",
        "resource_type", "resource_id", "method", "path",
        "status_code", "ip_address", "duration_ms",
    ])
    writer.writeheader()
    for entry in entries:
        writer.writerow({k: entry.get(k, "") for k in writer.fieldnames})

    output.seek(0)
    await record_audit_event(action="export.audit", details={"count": len(entries)})

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=audit_export_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv"},
    )


@app.get("/export/agents")
async def export_agents_csv():
    svc = _svc_headers()
    try:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            resp = await client.get(f"{ORCHESTRATOR_URL}/agents", headers=svc)
            resp.raise_for_status()
            agents = resp.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Orchestrator unreachable: {e}")

    output = io.StringIO()
    fieldnames = ["agent_id", "profile", "specialization", "price", "eta_minutes", "confidence"]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for agent_id, info in agents.items():
        row = {k: info.get(k, "") for k in fieldnames}
        row["agent_id"] = agent_id
        writer.writerow(row)

    output.seek(0)
    await record_audit_event(action="export.agents", details={"count": len(agents)})

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=agents_export_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv"},
    )


# ──────────────────────────────────────────────
# System Overview (Enterprise Dashboard Data)
# ──────────────────────────────────────────────

@app.get("/system/overview")
async def system_overview():
    svc = _svc_headers()
    overview = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "services": {},
        "agents": 0,
        "tasks": {"total": 0},
        "users": 0,
        "api_keys": 0,
    }

    async with httpx.AsyncClient(timeout=5.0) as client:
        for name, url in SERVICE_REGISTRY.items():
            try:
                resp = await client.get(f"{url}/health", headers=svc)
                data = resp.json()
                overview["services"][name] = "healthy" if data.get("ok") == 1 else "degraded"
            except Exception:
                overview["services"][name] = "unreachable"

        try:
            resp = await client.get(f"{ORCHESTRATOR_URL}/agents", headers=svc)
            agents = resp.json()
            overview["agents"] = len(agents) if isinstance(agents, dict) else 0
        except Exception:
            pass

        try:
            resp = await client.get(f"{MARKETPLACE_URL}/tasks", headers=svc)
            tasks = resp.json()
            if isinstance(tasks, list):
                overview["tasks"]["total"] = len(tasks)
                overview["tasks"]["open"] = sum(1 for t in tasks if t.get("status") == "open")
                overview["tasks"]["completed"] = sum(1 for t in tasks if t.get("status") == "completed")
                overview["tasks"]["failed"] = sum(1 for t in tasks if t.get("status") == "failed")
        except Exception:
            pass

    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute("SELECT COUNT(*) FROM enterprise_users WHERE active = 1")
            overview["users"] = (await cursor.fetchone())[0]
            cursor = await db.execute("SELECT COUNT(*) FROM api_keys WHERE active = 1")
            overview["api_keys"] = (await cursor.fetchone())[0]
    except Exception:
        pass

    return overview
