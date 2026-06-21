import os
import sys
import uuid
import asyncio
import logging
from contextlib import asynccontextmanager

import aiosqlite
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared.security import RequestIDMiddleware, ServiceTokenMiddleware
from shared.task_taxonomy import list_categories, TaskCategory
from shared.config import CORS_ORIGINS
from shared.logging_config import setup_logging

logger = setup_logging("recurring")

DB_PATH = os.getenv("RECURRING_DB_PATH", "/data/recurring.db")

rules = []
_rules_lock = asyncio.Lock()


async def _init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA busy_timeout=5000")
        await db.execute("""
            CREATE TABLE IF NOT EXISTS rules (
                rule_id TEXT PRIMARY KEY,
                objective TEXT NOT NULL,
                category TEXT DEFAULT 'uncategorized'
            )
        """)
        await db.commit()


async def _load_rules():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM rules")
        rows = await cursor.fetchall()
        for row in rows:
            rules.append({
                "rule_id": row["rule_id"],
                "objective": row["objective"],
                "category": row["category"],
            })
    logger.info("Loaded %d rules from database", len(rules))


async def _persist_rule(rule: dict):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO rules (rule_id, objective, category) VALUES (?, ?, ?)",
            (rule["rule_id"], rule["objective"], rule.get("category", "uncategorized")),
        )
        await db.commit()


@asynccontextmanager
async def lifespan(app):
    await _init_db()
    await _load_rules()
    yield


app = FastAPI(title="Agent N9er Recurring Engine", lifespan=lifespan)

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
    async with _rules_lock:
        count = len(rules)
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute("SELECT COUNT(*) FROM rules")
            db_count = (await cursor.fetchone())[0]
        return {"ok": 1, "service": "recurring", "rule_count": count, "db_rules": db_count}
    except Exception:
        return {"ok": 0, "service": "recurring", "error": "db_unreachable"}


@app.post("/rules")
async def add_rule(rule: dict):
    if "objective" not in rule:
        raise HTTPException(status_code=422, detail="Missing objective")
    rule["rule_id"] = str(uuid.uuid4())
    rule.setdefault("category", "uncategorized")
    async with _rules_lock:
        rules.append(rule)
    await _persist_rule(rule)
    logger.info("Added rule %s [%s]: %s", rule["rule_id"], rule["category"], rule["objective"][:80])
    return {"ok": 1, "rule": rule}


@app.get("/rules")
async def get_rules():
    async with _rules_lock:
        return list(rules)


@app.get("/tick")
async def tick():
    async with _rules_lock:
        snapshot = list(rules)
    generated = []
    for rule in snapshot:
        task = {
            "id": str(uuid.uuid4()),
            "objective": rule["objective"],
            "source": "recurring",
            "rule_id": rule.get("rule_id"),
            "category": rule.get("category", "uncategorized"),
        }
        generated.append(task)
    if generated:
        logger.info("Tick generated %d tasks from %d rules", len(generated), len(snapshot))
    return generated


@app.get("/categories")
async def categories():
    return list_categories()
