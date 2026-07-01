"""
Agent Registry — Service for agent registration, discovery, and lifecycle.

Endpoints:
  POST   /register       Register a new agent
  POST   /heartbeat      Update agent status + liveness
  POST   /deregister     Remove an agent
  GET    /list           List agents (filter by type, state, capabilities)
  POST   /select         Best-fit agent for a task
  GET    /agents/{id}    Get agent details
  GET    /health         Health check
"""

import os
import sys
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

import aiosqlite
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared.security import RequestIDMiddleware, ServiceTokenMiddleware
from shared.config import CORS_ORIGINS, ENV
from shared.agent_state_machine import AGENT_TYPES, AGENT_STATES, VALID_TRANSITIONS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("agent_registry")

DB_PATH = os.getenv("REGISTRY_DB_PATH", os.path.join(os.path.dirname(__file__), "registry.db"))
HEARTBEAT_TTL_SECONDS = int(os.getenv("HEARTBEAT_TTL_SECONDS", "30"))

# ── Pydantic models ──────────────────────────────────────────────


class RegisterRequest(BaseModel):
    agent_id: str = Field(..., min_length=1, description="Unique agent identifier")
    agent_type: str = Field(..., description=f"One of: {AGENT_TYPES}")
    capabilities: list[str] = Field(default_factory=list)
    price_per_hour: float = Field(default=0.0, ge=0.0)
    max_load: int = Field(default=3, ge=1, le=20)
    metadata: dict = Field(default_factory=dict)


class HeartbeatRequest(BaseModel):
    agent_id: str
    state: str = "idle"
    current_load: int = 0
    current_task_id: Optional[str] = None
    metadata: dict = Field(default_factory=dict)


class DeregisterRequest(BaseModel):
    agent_id: str


class SelectRequest(BaseModel):
    required_capabilities: list[str] = Field(default_factory=list)
    preferred_type: Optional[str] = None
    max_price_per_hour: Optional[float] = None


class AgentRecord(BaseModel):
    agent_id: str
    agent_type: str
    state: str
    capabilities: list[str]
    price_per_hour: float
    current_load: int
    max_load: int
    last_heartbeat: str
    current_task_id: Optional[str] = None
    metadata: dict
    registered_at: str

    class Config:
        from_attributes = True


# ── Database ─────────────────────────────────────────────────────


SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS agents (
        agent_id        TEXT PRIMARY KEY,
        agent_type      TEXT NOT NULL,
        state           TEXT NOT NULL DEFAULT 'idle',
        capabilities    TEXT NOT NULL DEFAULT '[]',
        price_per_hour  REAL NOT NULL DEFAULT 0.0,
        current_load    INTEGER NOT NULL DEFAULT 0,
        max_load        INTEGER NOT NULL DEFAULT 3,
        last_heartbeat  TEXT NOT NULL DEFAULT '',
        current_task_id TEXT,
        metadata        TEXT NOT NULL DEFAULT '{}',
        registered_at   TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_agents_type ON agents(agent_type)",
    "CREATE INDEX IF NOT EXISTS idx_agents_state ON agents(state)",
]


@asynccontextmanager
async def get_db():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        yield db


async def init_db():
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        for stmt in SCHEMA:
            await db.execute(stmt)
        await db.commit()
    logger.info("Agent Registry DB initialized at %s", DB_PATH)


def _row_to_agent(row: aiosqlite.Row) -> AgentRecord:
    return AgentRecord(
        agent_id=row["agent_id"],
        agent_type=row["agent_type"],
        state=row["state"],
        capabilities=json.loads(row["capabilities"]),
        price_per_hour=row["price_per_hour"],
        current_load=row["current_load"],
        max_load=row["max_load"],
        last_heartbeat=row["last_heartbeat"],
        current_task_id=row["current_task_id"],
        metadata=json.loads(row["metadata"]),
        registered_at=row["registered_at"],
    )


# ── App lifecycle ────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(
    title="Agent Registry",
    description="Agent discovery, registration, and lifecycle management",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])
app.add_middleware(RequestIDMiddleware)
app.add_middleware(ServiceTokenMiddleware)


# ── Helpers ──────────────────────────────────────────────────────


async def _stale_heartbeat_cleanup():
    """Mark agents as idle if they haven't heartbeated within TTL."""
    cutoff = datetime.now(timezone.utc).isoformat()
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT agent_id, last_heartbeat FROM agents WHERE state != 'idle'"
        )
        rows = await cursor.fetchall()
        now = datetime.now(timezone.utc)
        for row in rows:
            try:
                hb = datetime.fromisoformat(row["last_heartbeat"])
                if (now - hb).total_seconds() > HEARTBEAT_TTL_SECONDS:
                    logger.warning("Agent %s heartbeat expired, resetting to idle", row["agent_id"])
                    await db.execute(
                        "UPDATE agents SET state='idle', current_load=0, current_task_id=NULL WHERE agent_id=?",
                        (row["agent_id"],),
                    )
            except (ValueError, TypeError):
                pass
        await db.commit()


# ── Routes ───────────────────────────────────────────────────────


@app.get("/health")
async def health():
    return {"status": "ok", "service": "agent-registry", "agents_known": None}


@app.post("/register", response_model=AgentRecord)
async def register(req: RegisterRequest):
    """Register a new agent. If agent_id already exists, updates the registration."""
    if req.agent_type not in AGENT_TYPES:
        raise HTTPException(400, f"Invalid agent_type. Valid: {AGENT_TYPES}")

    now = datetime.now(timezone.utc).isoformat()
    async with get_db() as db:
        existing = await db.execute(
            "SELECT * FROM agents WHERE agent_id=?", (req.agent_id,)
        )
        row = await existing.fetchone()

        if row:
            await db.execute(
                """UPDATE agents SET agent_type=?, capabilities=?, price_per_hour=?,
                   max_load=?, metadata=?, state='idle', current_load=0 WHERE agent_id=?""",
                (
                    req.agent_type,
                    json.dumps(req.capabilities),
                    req.price_per_hour,
                    req.max_load,
                    json.dumps(req.metadata),
                    req.agent_id,
                ),
            )
        else:
            await db.execute(
                """INSERT INTO agents (agent_id, agent_type, state, capabilities,
                   price_per_hour, max_load, last_heartbeat, metadata, registered_at)
                   VALUES (?, ?, 'idle', ?, ?, ?, ?, ?, ?)""",
                (
                    req.agent_id,
                    req.agent_type,
                    json.dumps(req.capabilities),
                    req.price_per_hour,
                    req.max_load,
                    now,
                    json.dumps(req.metadata),
                    now,
                ),
            )
        await db.commit()

        cursor = await db.execute("SELECT * FROM agents WHERE agent_id=?", (req.agent_id,))
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(500, "Agent was not persisted")
        return _row_to_agent(row)


@app.post("/heartbeat")
async def heartbeat(req: HeartbeatRequest):
    """Update agent state and liveness timestamp."""
    if req.state not in AGENT_STATES:
        raise HTTPException(400, f"Invalid state. Valid: {AGENT_STATES}")

    now = datetime.now(timezone.utc).isoformat()
    async with get_db() as db:
        cursor = await db.execute("SELECT 1 FROM agents WHERE agent_id=?", (req.agent_id,))
        if not await cursor.fetchone():
            raise HTTPException(404, f"Agent '{req.agent_id}' not registered")

        await db.execute(
            """UPDATE agents SET state=?, current_load=?, current_task_id=?,
               last_heartbeat=?, metadata=? WHERE agent_id=?""",
            (
                req.state,
                req.current_load,
                req.current_task_id,
                now,
                json.dumps(req.metadata),
                req.agent_id,
            ),
        )
        await db.commit()
    return {"status": "ok", "agent_id": req.agent_id, "state": req.state, "timestamp": now}


@app.post("/deregister")
async def deregister(req: DeregisterRequest):
    """Remove an agent from the registry."""
    async with get_db() as db:
        cursor = await db.execute("SELECT 1 FROM agents WHERE agent_id=?", (req.agent_id,))
        if not await cursor.fetchone():
            raise HTTPException(404, f"Agent '{req.agent_id}' not found")
        await db.execute("DELETE FROM agents WHERE agent_id=?", (req.agent_id,))
        await db.commit()
    return {"status": "ok", "agent_id": req.agent_id, "action": "deregistered"}


@app.get("/list", response_model=list[AgentRecord])
async def list_agents(
    agent_type: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    available: bool = Query(False, description="Only agents with current_load < max_load"),
    limit: int = Query(100, ge=1, le=500),
):
    """List registered agents with optional filters."""
    await _stale_heartbeat_cleanup()

    conditions: list[str] = []
    params: list = []

    if agent_type:
        if agent_type not in AGENT_TYPES:
            raise HTTPException(400, f"Invalid agent_type. Valid: {AGENT_TYPES}")
        conditions.append("agent_type = ?")
        params.append(agent_type)

    if state:
        if state not in AGENT_STATES:
            raise HTTPException(400, f"Invalid state. Valid: {AGENT_STATES}")
        conditions.append("state = ?")
        params.append(state)

    if available:
        conditions.append("current_load < max_load")

    where = ""
    if conditions:
        where = " WHERE " + " AND ".join(conditions)

    async with get_db() as db:
        cursor = await db.execute(f"SELECT * FROM agents{where} ORDER BY registered_at DESC LIMIT ?",
                                   params + [limit])
        rows = await cursor.fetchall()
    return [_row_to_agent(r) for r in rows]


@app.post("/select")
async def select_agent(req: SelectRequest):
    """Pick the best-fit agent for a task based on capabilities, load, and price."""
    await _stale_heartbeat_cleanup()

    async with get_db() as db:
        conditions = ["state = 'idle'", "current_load < max_load"]
        params: list = []

        if req.preferred_type:
            conditions.append("agent_type = ?")
            params.append(req.preferred_type)

        if req.max_price_per_hour is not None:
            conditions.append("price_per_hour <= ?")
            params.append(req.max_price_per_hour)

        cursor = await db.execute(
            f"SELECT * FROM agents WHERE {' AND '.join(conditions)} ORDER BY current_load ASC, price_per_hour ASC",
            params,
        )
        rows = await cursor.fetchall()

    candidates = [_row_to_agent(r) for r in rows]

    if req.required_capabilities:
        candidates = [
            a for a in candidates
            if all(cap in a.capabilities for cap in req.required_capabilities)
        ]

    if not candidates:
        raise HTTPException(404, "No available agent matches the requirements")

    best = candidates[0]
    logger.info("Selected agent %s (type=%s, load=%d, price=%.2f)",
                best.agent_id, best.agent_type, best.current_load, best.price_per_hour)
    return best


@app.get("/agents/{agent_id}", response_model=AgentRecord)
async def get_agent(agent_id: str):
    """Get details for a specific agent."""
    async with get_db() as db:
        cursor = await db.execute("SELECT * FROM agents WHERE agent_id=?", (agent_id,))
        row = await cursor.fetchone()
    if not row:
        raise HTTPException(404, f"Agent '{agent_id}' not found")
    return _row_to_agent(row)


# ── Main ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "9900"))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=(ENV == "development"))
