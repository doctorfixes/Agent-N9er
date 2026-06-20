import os
import logging
import random
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import aiosqlite
import httpx
from fastapi import FastAPI, HTTPException

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("execution")

REPUTATION_URL = os.getenv("REPUTATION_URL", "http://localhost:8500")
DB_PATH = os.getenv("DB_PATH", "/data/execution.db")


async def get_db():
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    return db


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
        await db.commit()
    logger.info("Execution database initialized at %s", DB_PATH)


@asynccontextmanager
async def lifespan(app):
    await init_db()
    yield


app = FastAPI(title="Verixio Agent Execution", lifespan=lifespan)


@app.get("/health")
async def health():
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT COUNT(*) FROM executions")
        count = (await cursor.fetchone())[0]
    return {"ok": 1, "service": "execution", "total_executions": count}


@app.post("/execute")
async def execute(request: dict):
    agent_id = request.get("agent_id")
    task_id = request.get("task_id")
    confidence = request.get("confidence", 0.5)

    if not agent_id or not task_id:
        raise HTTPException(status_code=422, detail="Missing agent_id or task_id")

    success = random.random() < confidence
    duration = round(random.uniform(1, 10), 1)
    now = datetime.now(timezone.utc).isoformat()

    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO executions (task_id, agent_id, success, duration, executed_at) VALUES (?, ?, ?, ?, ?)",
            (task_id, agent_id, success, duration, now)
        )
        await db.commit()
    finally:
        await db.close()

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(f"{REPUTATION_URL}/update", json={
                "agent_id": agent_id,
                "success": success,
            })
    except httpx.RequestError as e:
        logger.warning("Failed to update reputation: %s", e)

    logger.info("Executed task %s by agent %s: success=%s duration=%.1fs",
                task_id, agent_id, success, duration)
    return {"ok": 1, "task_id": task_id, "agent_id": agent_id,
            "success": success, "duration": duration}


@app.get("/history")
async def history(agent_id: str = None, limit: int = 100):
    db = await get_db()
    try:
        if agent_id:
            cursor = await db.execute(
                "SELECT * FROM executions WHERE agent_id = ? ORDER BY executed_at DESC LIMIT ?",
                (agent_id, limit)
            )
        else:
            cursor = await db.execute(
                "SELECT * FROM executions ORDER BY executed_at DESC LIMIT ?", (limit,)
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
    finally:
        await db.close()
