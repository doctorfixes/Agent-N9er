import os
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import aiosqlite
from fastapi import FastAPI, HTTPException

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("marketplace")

DB_PATH = os.getenv("DB_PATH", "/data/marketplace.db")


async def get_db():
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    return db


async def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                objective TEXT NOT NULL,
                priority_score REAL DEFAULT 0,
                status TEXT DEFAULT 'open',
                inputs TEXT DEFAULT '{}',
                source TEXT DEFAULT 'manual',
                published_at TEXT,
                awarded_to TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS bids (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                agent_id TEXT NOT NULL,
                price REAL,
                eta_minutes INTEGER,
                confidence REAL,
                submitted_at TEXT,
                FOREIGN KEY (task_id) REFERENCES tasks(id)
            )
        """)
        await db.commit()
    logger.info("Marketplace database initialized at %s", DB_PATH)


@asynccontextmanager
async def lifespan(app):
    await init_db()
    yield


app = FastAPI(title="Verixio Bidding Marketplace", lifespan=lifespan)


@app.get("/health")
async def health():
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT COUNT(*) FROM tasks")
        count = (await cursor.fetchone())[0]
    return {"ok": 1, "service": "marketplace", "task_count": count}


@app.post("/publish")
async def publish(task: dict):
    task_id = task.get("id")
    if not task_id:
        raise HTTPException(status_code=422, detail="Missing task id")

    now = datetime.now(timezone.utc).isoformat()
    db = await get_db()
    try:
        await db.execute(
            "INSERT OR REPLACE INTO tasks (id, objective, priority_score, status, inputs, source, published_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (task_id, task.get("objective", ""), task.get("priority_score", 0),
             "open", json.dumps(task.get("inputs", {})), task.get("source", "manual"), now)
        )
        await db.commit()
    finally:
        await db.close()

    logger.info("Published task %s", task_id)
    return {"ok": 1, "task_id": task_id}


@app.get("/feed")
async def feed(status: str = None):
    db = await get_db()
    try:
        if status:
            cursor = await db.execute("SELECT * FROM tasks WHERE status = ? ORDER BY published_at DESC", (status,))
        else:
            cursor = await db.execute("SELECT * FROM tasks ORDER BY published_at DESC")
        rows = await cursor.fetchall()
        return [_task_from_row(r) for r in rows]
    finally:
        await db.close()


@app.post("/bid")
async def submit_bid(bid: dict):
    task_id = bid.get("task_id")
    agent_id = bid.get("agent_id")
    if not task_id or not agent_id:
        raise HTTPException(status_code=422, detail="Missing task_id or agent_id")

    db = await get_db()
    try:
        cursor = await db.execute("SELECT id FROM tasks WHERE id = ?", (task_id,))
        if not await cursor.fetchone():
            raise HTTPException(status_code=404, detail="Task not found")

        now = datetime.now(timezone.utc).isoformat()
        await db.execute(
            "INSERT INTO bids (task_id, agent_id, price, eta_minutes, confidence, submitted_at) VALUES (?, ?, ?, ?, ?, ?)",
            (task_id, agent_id, bid.get("price", 0), bid.get("eta_minutes", 0),
             bid.get("confidence", 0), now)
        )
        await db.commit()
    finally:
        await db.close()

    logger.info("Bid from agent %s on task %s (confidence=%.2f)",
                agent_id, task_id, bid.get("confidence", 0))
    return {"ok": 1}


@app.get("/bids/{task_id}")
async def get_bids(task_id: str):
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM bids WHERE task_id = ? ORDER BY confidence DESC", (task_id,))
        rows = await cursor.fetchall()
        if not rows:
            cursor2 = await db.execute("SELECT id FROM tasks WHERE id = ?", (task_id,))
            if not await cursor2.fetchone():
                raise HTTPException(status_code=404, detail="Task not found")
        return [_bid_from_row(r) for r in rows]
    finally:
        await db.close()


@app.post("/award/{task_id}")
async def award_task(task_id: str):
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM bids WHERE task_id = ? ORDER BY confidence DESC LIMIT 1",
            (task_id,)
        )
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="No bids for task")

        winning_bid = _bid_from_row(row)
        await db.execute(
            "UPDATE tasks SET status = 'awarded', awarded_to = ? WHERE id = ?",
            (winning_bid["agent_id"], task_id)
        )
        await db.commit()
    finally:
        await db.close()

    logger.info("Task %s awarded to agent %s", task_id, winning_bid["agent_id"])
    return {"ok": 1, "winner": winning_bid}


@app.post("/complete/{task_id}")
async def complete_task(task_id: str, result: dict):
    status = "completed" if result.get("success") else "failed"
    db = await get_db()
    try:
        await db.execute("UPDATE tasks SET status = ? WHERE id = ?", (status, task_id))
        await db.commit()
    finally:
        await db.close()
    logger.info("Task %s marked %s", task_id, status)
    return {"ok": 1}


def _task_from_row(row):
    return {
        "id": row["id"],
        "objective": row["objective"],
        "priority_score": row["priority_score"],
        "status": row["status"],
        "inputs": json.loads(row["inputs"]) if row["inputs"] else {},
        "source": row["source"],
        "published_at": row["published_at"],
        "awarded_to": row["awarded_to"],
    }


def _bid_from_row(row):
    return {
        "id": row["id"],
        "task_id": row["task_id"],
        "agent_id": row["agent_id"],
        "price": row["price"],
        "eta_minutes": row["eta_minutes"],
        "confidence": row["confidence"],
        "submitted_at": row["submitted_at"],
    }
