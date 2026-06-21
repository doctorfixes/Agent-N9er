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
from shared.logging_config import setup_logging

logger = setup_logging("reputation")

DB_PATH = os.getenv("DB_PATH", "/data/reputation.db")


class RegisterRequest(BaseModel):
    agent_id: str
    profile: str = ""
    nickname: str = ""


class UpdateRequest(BaseModel):
    agent_id: str
    success: bool


class RatingRequest(BaseModel):
    agent_id: str
    prospect_id: str = ""
    rating: int
    client_email: str = ""
    comment: str = ""


class NicknameRequest(BaseModel):
    nickname: str


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
                nickname TEXT DEFAULT '',
                success INTEGER DEFAULT 0,
                fail INTEGER DEFAULT 0,
                score REAL DEFAULT 0.5,
                total_ratings INTEGER DEFAULT 0,
                avg_rating REAL DEFAULT 0.0,
                jobs_completed INTEGER DEFAULT 0
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS ratings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id TEXT,
                prospect_id TEXT,
                rating INTEGER,
                client_email TEXT DEFAULT '',
                comment TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (agent_id) REFERENCES agents(agent_id)
            )
        """)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_agents_score ON agents(score)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_ratings_agent ON ratings(agent_id)")
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
    allow_methods=["GET", "POST", "PATCH"],
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
            "INSERT OR IGNORE INTO agents (agent_id, profile, nickname) VALUES (?, ?, ?)",
            (agent.agent_id, agent.profile, agent.nickname)
        )
        await db.commit()

    logger.info("Registered agent %s (%s) nickname=%s", agent.agent_id, agent.profile, agent.nickname or "(none)")
    return {"ok": 1, "agent_id": agent.agent_id, "nickname": agent.nickname}


@app.patch("/agent/{agent_id}/nickname")
async def set_nickname(agent_id: str, req: NicknameRequest):
    nickname = req.nickname.strip()
    if len(nickname) > 32:
        raise HTTPException(status_code=422, detail="Nickname must be 32 characters or fewer")

    async with _get_db() as db:
        cursor = await db.execute("SELECT agent_id FROM agents WHERE agent_id = ?", (agent_id,))
        if not await cursor.fetchone():
            raise HTTPException(status_code=404, detail="Agent not found")

        await db.execute("UPDATE agents SET nickname = ? WHERE agent_id = ?", (nickname, agent_id))
        await db.commit()

    logger.info("Agent %s nickname set to '%s'", agent_id, nickname)
    return {"ok": 1, "agent_id": agent_id, "nickname": nickname}


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
            """INSERT INTO agents (agent_id, success, fail, score)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(agent_id) DO UPDATE SET
                   success = excluded.success,
                   fail = excluded.fail,
                   score = excluded.score""",
            (record.agent_id, success, fail, round(score, 4))
        )
        await db.commit()

    entry = {"success": success, "fail": fail, "score": round(score, 4)}
    logger.info("Agent %s reputation: %.2f (W:%d L:%d)", record.agent_id, score, success, fail)
    return {"ok": 1, "agent_id": record.agent_id, "reputation": entry}


@app.post("/rate")
async def rate_agent(req: RatingRequest):
    if req.rating < 1 or req.rating > 5:
        raise HTTPException(status_code=422, detail="Rating must be 1-5")

    async with _get_db() as db:
        cursor = await db.execute("SELECT * FROM agents WHERE agent_id = ?", (req.agent_id,))
        row = await cursor.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Agent not found")

        await db.execute(
            "INSERT INTO ratings (agent_id, prospect_id, rating, client_email, comment) VALUES (?, ?, ?, ?, ?)",
            (req.agent_id, req.prospect_id, req.rating, req.client_email, req.comment),
        )

        total_ratings = row["total_ratings"] + 1
        avg_rating = round(((row["avg_rating"] * row["total_ratings"]) + req.rating) / total_ratings, 2)
        jobs_completed = row["jobs_completed"] + 1

        score_delta = (req.rating - 3) * 0.01
        new_score = max(0.0, min(1.0, row["score"] + score_delta))

        await db.execute(
            "UPDATE agents SET total_ratings = ?, avg_rating = ?, jobs_completed = ?, score = ? WHERE agent_id = ?",
            (total_ratings, avg_rating, jobs_completed, round(new_score, 4), req.agent_id),
        )
        await db.commit()

    logger.info("Agent %s rated %d/5 (avg %.2f over %d)", req.agent_id, req.rating, avg_rating, total_ratings)
    return {
        "ok": 1,
        "agent_id": req.agent_id,
        "rating": req.rating,
        "avg_rating": avg_rating,
        "total_ratings": total_ratings,
        "score": round(new_score, 4),
    }


@app.get("/agent/{agent_id}/ratings")
async def get_agent_ratings(agent_id: str, limit: int = 50):
    async with _get_db() as db:
        cursor = await db.execute("SELECT agent_id FROM agents WHERE agent_id = ?", (agent_id,))
        if not await cursor.fetchone():
            raise HTTPException(status_code=404, detail="Agent not found")

        cursor = await db.execute(
            "SELECT * FROM ratings WHERE agent_id = ? ORDER BY created_at DESC LIMIT ?",
            (agent_id, limit),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


def _agent_to_dict(row):
    d = {
        "agent_id": row["agent_id"],
        "profile": row["profile"],
        "success": row["success"],
        "fail": row["fail"],
        "score": row["score"],
    }
    for key, default in [("nickname", ""), ("total_ratings", 0), ("avg_rating", 0.0), ("jobs_completed", 0)]:
        try:
            d[key] = row[key]
        except (IndexError, KeyError):
            d[key] = default
    return d


@app.get("/ledger")
async def get_ledger():
    async with _get_db() as db:
        cursor = await db.execute("SELECT * FROM agents ORDER BY score DESC")
        rows = await cursor.fetchall()
        return {row["agent_id"]: _agent_to_dict(row) for row in rows}


@app.get("/agent/{agent_id}")
async def get_agent(agent_id: str):
    async with _get_db() as db:
        cursor = await db.execute("SELECT * FROM agents WHERE agent_id = ?", (agent_id,))
        row = await cursor.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Agent not found")
    return _agent_to_dict(row)
