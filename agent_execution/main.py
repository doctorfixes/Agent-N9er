import os
import sys
import logging
import random
import time
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
from shared.llm import complete, estimate_cost, select_tier, OPENROUTER_API_KEY

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("execution")

REPUTATION_URL = os.getenv("REPUTATION_URL", "http://localhost:8500")
DB_PATH = os.getenv("DB_PATH", "/data/execution.db")


class ExecuteRequest(BaseModel):
    task_id: str
    agent_id: str
    confidence: float = Field(default=0.5, ge=0, le=1)
    objective: str = ""
    description: str = ""
    complexity: str = "moderate"
    tier: str = ""


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
                executed_at TEXT NOT NULL,
                mode TEXT DEFAULT 'simulation',
                model TEXT DEFAULT '',
                input_tokens INTEGER DEFAULT 0,
                output_tokens INTEGER DEFAULT 0,
                cost_usd REAL DEFAULT 0,
                output TEXT DEFAULT ''
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


app = FastAPI(title="Agent N9er Execution Engine", lifespan=lifespan)

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
        return {
            "ok": 1,
            "service": "execution",
            "total_executions": count,
            "mode": "live" if OPENROUTER_API_KEY else "simulation",
        }
    except Exception:
        return {"ok": 0, "service": "execution", "error": "db_unreachable"}


@app.post("/execute")
async def execute(request: ExecuteRequest):
    if OPENROUTER_API_KEY and request.objective:
        result = await _execute_live(request)
    else:
        result = await _execute_simulation(request)

    svc = get_service_headers()
    try:
        await retry_request(
            "POST", f"{REPUTATION_URL}/update",
            timeout=QUICK_TIMEOUT, headers=svc,
            json={"agent_id": request.agent_id, "success": result["success"]},
        )
    except httpx.RequestError as e:
        logger.warning("Failed to update reputation after retries: %s", e)

    return result


async def _execute_live(request: ExecuteRequest) -> dict:
    tier = request.tier or select_tier(request.complexity)
    now = datetime.now(timezone.utc).isoformat()

    messages = [
        {
            "role": "system",
            "content": (
                "You are Agent N9er, an autonomous task execution agent. "
                "Complete the following task thoroughly and professionally. "
                "Provide your full deliverable — code, text, analysis, or whatever the task requires. "
                "Be detailed and production-ready."
            ),
        },
        {
            "role": "user",
            "content": f"Task: {request.objective}\n\n{request.description}" if request.description
            else f"Task: {request.objective}",
        },
    ]

    try:
        llm_result = await complete(messages, tier=tier)

        success = llm_result.finish_reason in ("stop", "end_turn")
        output_preview = llm_result.content[:500]

        async with _get_db() as db:
            await db.execute(
                """INSERT INTO executions
                   (task_id, agent_id, success, duration, executed_at, mode, model,
                    input_tokens, output_tokens, cost_usd, output)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (request.task_id, request.agent_id, success,
                 llm_result.latency_ms / 1000, now, "live", llm_result.model,
                 llm_result.input_tokens, llm_result.output_tokens,
                 llm_result.cost_usd, llm_result.content),
            )
            await db.commit()

        logger.info(
            "Live execution: task=%s agent=%s model=%s tokens=%d+%d cost=$%.4f success=%s",
            request.task_id, request.agent_id, llm_result.model,
            llm_result.input_tokens, llm_result.output_tokens,
            llm_result.cost_usd, success,
        )

        return {
            "ok": 1,
            "task_id": request.task_id,
            "agent_id": request.agent_id,
            "success": success,
            "duration": round(llm_result.latency_ms / 1000, 1),
            "mode": "live",
            "model": llm_result.model,
            "input_tokens": llm_result.input_tokens,
            "output_tokens": llm_result.output_tokens,
            "cost_usd": llm_result.cost_usd,
            "output_preview": output_preview,
        }

    except Exception as e:
        logger.error("Live execution failed for task %s: %s", request.task_id, e)
        async with _get_db() as db:
            await db.execute(
                """INSERT INTO executions
                   (task_id, agent_id, success, duration, executed_at, mode, output)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (request.task_id, request.agent_id, False, 0, now, "live_failed", str(e)),
            )
            await db.commit()

        return {
            "ok": 0,
            "task_id": request.task_id,
            "agent_id": request.agent_id,
            "success": False,
            "duration": 0,
            "mode": "live_failed",
            "error": str(e),
        }


async def _execute_simulation(request: ExecuteRequest) -> dict:
    success = random.random() < request.confidence
    duration = round(random.uniform(1, 10), 1)
    now = datetime.now(timezone.utc).isoformat()

    async with _get_db() as db:
        await db.execute(
            """INSERT INTO executions
               (task_id, agent_id, success, duration, executed_at, mode)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (request.task_id, request.agent_id, success, duration, now, "simulation"),
        )
        await db.commit()

    logger.info("Simulated execution: task=%s agent=%s success=%s duration=%.1fs",
                request.task_id, request.agent_id, success, duration)

    return {
        "ok": 1,
        "task_id": request.task_id,
        "agent_id": request.agent_id,
        "success": success,
        "duration": duration,
        "mode": "simulation",
    }


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
        results = []
        for row in rows:
            entry = {
                "id": row["id"],
                "task_id": row["task_id"],
                "agent_id": row["agent_id"],
                "success": bool(row["success"]),
                "duration": row["duration"],
                "executed_at": row["executed_at"],
            }
            try:
                entry["mode"] = row["mode"]
                entry["model"] = row["model"]
                entry["cost_usd"] = row["cost_usd"]
            except (IndexError, KeyError):
                entry["mode"] = "simulation"
            results.append(entry)
        return results


@app.get("/executions/{task_id}/output")
async def get_execution_output(task_id: str):
    async with _get_db() as db:
        cursor = await db.execute(
            "SELECT * FROM executions WHERE task_id = ? ORDER BY executed_at DESC LIMIT 1",
            (task_id,),
        )
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Execution not found")
        try:
            output = row["output"]
        except (IndexError, KeyError):
            output = ""
        return {
            "task_id": row["task_id"],
            "agent_id": row["agent_id"],
            "success": bool(row["success"]),
            "output": output,
        }
