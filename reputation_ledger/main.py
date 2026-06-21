import os
import sys
import logging
from contextlib import asynccontextmanager

import aiosqlite
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared.security import RequestIDMiddleware, ServiceTokenMiddleware
from shared.config import CORS_ORIGINS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("reputation")

DB_PATH = os.getenv("DB_PATH", "/data/reputation.db")


class RegisterRequest(BaseModel):
    agent_id: str
    profile: str = ""


class UpdateRequest(BaseModel):
    agent_id: str
    success: bool


@asynccontextmanager
async def _get_db():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        yield db


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
        await db.execute("CREATE INDEX IF NOT EXISTS idx_agents_score ON agents(score)")
        await db.commit()
    logger.info("Reputation database initialized at %s", DB_PATH)


@asynccontextmanager
async def lifespan(app):
    await init_db()
    yield


app = FastAPI(title="Agent N9er Reputation Ledger", lifespan=lifespan)

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
            cursor = await db.execute("SELECT COUNT(*) FROM agents")
            count = (await cursor.fetchone())[0]
        return {"ok": 1, "service": "reputation", "agent_count": count}
    except Exception:
        return {"ok": 0, "service": "reputation", "error": "db_unreachable"}


@app.post("/register")
async def register(agent: RegisterRequest):
    async with _get_db() as db:
        await db.execute(
            "INSERT OR IGNORE INTO agents (agent_id, profile) VALUES (?, ?)",
            (agent.agent_id, agent.profile)
        )
        await db.commit()

    logger.info("Registered agent %s (%s)", agent.agent_id, agent.profile)
    return {"ok": 1, "agent_id": agent.agent_id}


@app.post("/update")
async def update(record: UpdateRequest):
    async with _get_db() as db:
        cursor = await db.execute("SELECT * FROM agents WHERE agent_id = ?", (record.agent_id,))
        row = await cursor.fetchone()

        if row:
            success = row["success"]
            fail = row["fail"]
            score = row["score"]
        else:
            success, fail, score = 0, 0, 0.5

        if record.success:
            success += 1
            score = min(1.0, score + 0.01)
        else:
            fail += 1
            score = max(0.0, score - 0.02)

        await db.execute(
            "INSERT OR REPLACE INTO agents (agent_id, profile, success, fail, score) VALUES (?, ?, ?, ?, ?)",
            (record.agent_id, row["profile"] if row else "", success, fail, round(score, 4))
        )
        await db.commit()

    entry = {"success": success, "fail": fail, "score": round(score, 4)}
    logger.info("Agent %s reputation: %.2f (W:%d L:%d)", record.agent_id, score, success, fail)
    return {"ok": 1, "agent_id": record.agent_id, "reputation": entry}


@app.get("/ledger")
async def get_ledger():
    async with _get_db() as db:
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


@app.get("/agent/{agent_id}")
async def get_agent(agent_id: str):
    async with _get_db() as db:
        cursor = await db.execute("SELECT * FROM agents WHERE agent_id = ?", (agent_id,))
        row = await cursor.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Agent not found")
    return {
        "agent_id": row["agent_id"],
        "profile": row["profile"],
        "success": row["success"],
        "fail": row["fail"],
        "score": row["score"],
    }
