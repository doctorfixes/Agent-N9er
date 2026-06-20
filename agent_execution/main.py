import os
import sys
import logging
import random
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import aiosqlite
import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared.security import RequestIDMiddleware, ServiceTokenMiddleware, get_service_headers
from shared.config import QUICK_TIMEOUT, CORS_ORIGINS
from shared.retry import retry_request

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("execution")

REPUTATION_URL = os.getenv("REPUTATION_URL", "http://localhost:8500")
DB_PATH = os.getenv("DB_PATH", "/data/execution.db")


class ExecuteRequest(BaseModel):
    task_id: str
    agent_id: str
    confidence: float = Field(default=0.5, ge=0, le=1)


@asynccontextmanager
async def _get_db():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        yield db


async def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS executions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                agent_id TEXT NOT NULL,
                success BOOLEAN NOT NULL,
                duration REAL NOT NULL,
                executed_at TEXT NOT NULL
            )
        """)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_exec_task ON executions(task_id)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_exec_agent ON executions(agent_id)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_exec_time ON executions(executed_at)")
        await db.commit()
    logger.info("Execution database initialized at %s", DB_PATH)


@asynccontextmanager
async def lifespan(app):
    await init_db()
    yield


app = FastAPI(title="Verixio Agent Execution", lifespan=lifespan)

app.add_middleware(RequestIDMiddleware)
app.add_middleware(ServiceTokenMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute("SELECT COUNT(*) FROM executions")
            count = (await cursor.fetchone())[0]
        return {"ok": 1, "service": "execution", "total_executions": count}
    except Exception:
        return {"ok": 0, "service": "execution", "error": "db_unreachable"}


@app.post("/execute")
async def execute(request: ExecuteRequest):
    success = random.random() < request.confidence
    duration = round(random.uniform(1, 10), 1)
    now = datetime.now(timezone.utc).isoformat()

    async with _get_db() as db:
        await db.execute(
            "INSERT INTO executions (task_id, agent_id, success, duration, executed_at) VALUES (?, ?, ?, ?, ?)",
            (request.task_id, request.agent_id, success, duration, now)
        )
        await db.commit()

    svc = get_service_headers()
    try:
        await retry_request(
            "POST", f"{REPUTATION_URL}/update",
            timeout=QUICK_TIMEOUT, headers=svc,
            json={"agent_id": request.agent_id, "success": success},
        )
    except httpx.RequestError as e:
        logger.warning("Failed to update reputation after retries: %s", e)

    logger.info("Executed task %s by agent %s: success=%s duration=%.1fs",
                request.task_id, request.agent_id, success, duration)
    return {"ok": 1, "task_id": request.task_id, "agent_id": request.agent_id,
            "success": success, "duration": duration}


@app.get("/history")
async def history(
    agent_id: str = None,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    async with _get_db() as db:
        if agent_id:
            cursor = await db.execute(
                "SELECT * FROM executions WHERE agent_id = ? ORDER BY executed_at DESC LIMIT ? OFFSET ?",
                (agent_id, limit, offset)
            )
        else:
            cursor = await db.execute(
                "SELECT * FROM executions ORDER BY executed_at DESC LIMIT ? OFFSET ?",
                (limit, offset)
            )
        rows = await cursor.fetchall()
        return [
            {
                "id": row["id"],
                "task_id": row["task_id"],
                "agent_id": row["agent_id"],
                "success": bool(row["success"]),
                "duration": row["duration"],
                "executed_at": row["executed_at"],
            }
            for row in rows
        ]
