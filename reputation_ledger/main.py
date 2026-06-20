import os
import logging
from contextlib import asynccontextmanager

import aiosqlite
from fastapi import FastAPI, HTTPException

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("reputation")

DB_PATH = os.getenv("DB_PATH", "/data/reputation.db")


async def get_db():
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    return db


async def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS agents (
                agent_id TEXT PRIMARY KEY,
                profile TEXT DEFAULT '',
                success INTEGER DEFAULT 0,
                fail INTEGER DEFAULT 0,
                score REAL DEFAULT 0.5
            )
        """)
        await db.commit()
    logger.info("Reputation database initialized at %s", DB_PATH)


@asynccontextmanager
async def lifespan(app):
    await init_db()
    yield


app = FastAPI(title="Verixio Reputation Ledger", lifespan=lifespan)


@app.get("/health")
async def health():
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT COUNT(*) FROM agents")
        count = (await cursor.fetchone())[0]
    return {"ok": 1, "service": "reputation", "agent_count": count}


@app.post("/register")
async def register(agent: dict):
    agent_id = agent.get("agent_id")
    profile = agent.get("profile", "")
    if not agent_id:
        raise HTTPException(status_code=422, detail="Missing agent_id")

    db = await get_db()
    try:
        await db.execute(
            "INSERT OR IGNORE INTO agents (agent_id, profile) VALUES (?, ?)",
            (agent_id, profile)
        )
        await db.commit()
    finally:
        await db.close()

    logger.info("Registered agent %s (%s)", agent_id, profile)
    return {"ok": 1, "agent_id": agent_id}


@app.post("/update")
async def update(record: dict):
    agent_id = record.get("agent_id")
    if not agent_id:
        raise HTTPException(status_code=422, detail="Missing agent_id")

    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM agents WHERE agent_id = ?", (agent_id,))
        row = await cursor.fetchone()

        if row:
            success = row["success"]
            fail = row["fail"]
            score = row["score"]
        else:
            success, fail, score = 0, 0, 0.5

        if record.get("success"):
            success += 1
            score = min(1.0, score + 0.01)
        else:
            fail += 1
            score = max(0.0, score - 0.02)

        await db.execute(
            "INSERT OR REPLACE INTO agents (agent_id, profile, success, fail, score) VALUES (?, ?, ?, ?, ?)",
            (agent_id, row["profile"] if row else "", success, fail, round(score, 4))
        )
        await db.commit()
    finally:
        await db.close()

    entry = {"success": success, "fail": fail, "score": round(score, 4)}
    logger.info("Agent %s reputation: %.2f (W:%d L:%d)", agent_id, score, success, fail)
    return {"ok": 1, "agent_id": agent_id, "reputation": entry}


@app.get("/ledger")
async def get_ledger():
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM agents ORDER BY score DESC")
        rows = await cursor.fetchall()
        return {
            row["agent_id"]: {
                "profile": row["profile"],
                "success": row["success"],
                "fail": row["fail"],
                "score": row["score"],
            }
            for row in rows
        }
    finally:
        await db.close()


@app.get("/agent/{agent_id}")
async def get_agent(agent_id: str):
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM agents WHERE agent_id = ?", (agent_id,))
        row = await cursor.fetchone()
    finally:
        await db.close()

    if not row:
        raise HTTPException(status_code=404, detail="Agent not found")
    return {
        "agent_id": row["agent_id"],
        "profile": row["profile"],
        "success": row["success"],
        "fail": row["fail"],
        "score": row["score"],
    }
