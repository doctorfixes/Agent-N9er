import os
import sys
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import aiosqlite
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared.security import RequestIDMiddleware, ServiceTokenMiddleware
from shared.config import CORS_ORIGINS, BID_REQUIRE_APPROVAL

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("marketplace")

DB_PATH = os.getenv("DB_PATH", "/data/marketplace.db")


class PublishRequest(BaseModel):
    id: str
    objective: str = ""
    priority_score: float = 0.0
    inputs: dict = Field(default_factory=dict)
    source: str = "manual"


class BidRequest(BaseModel):
    task_id: str
    agent_id: str
    price: float = Field(default=0.0, ge=0)
    eta_minutes: int = Field(default=0, ge=0)
    confidence: float = Field(default=0.0, ge=0, le=1)
    require_approval: bool | None = None


class CompleteRequest(BaseModel):
    success: bool = False


@asynccontextmanager
async def _get_db():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        yield db


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
                status TEXT DEFAULT 'submitted',
                reviewed_at TEXT,
                FOREIGN KEY (task_id) REFERENCES tasks(id),
                UNIQUE(task_id, agent_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                entity_id TEXT,
                detail TEXT,
                timestamp TEXT NOT NULL
            )
        """)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_tasks_published ON tasks(published_at)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_bids_task ON bids(task_id)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_bids_agent ON bids(agent_id)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_audit_time ON audit_log(timestamp)")
        await db.commit()
    logger.info("Marketplace database initialized at %s", DB_PATH)


async def _audit(db, action: str, entity_type: str, entity_id: str = None, detail: str = None):
    now = datetime.now(timezone.utc).isoformat()
    await db.execute(
        "INSERT INTO audit_log (action, entity_type, entity_id, detail, timestamp) VALUES (?, ?, ?, ?, ?)",
        (action, entity_type, entity_id, detail, now),
    )


@asynccontextmanager
async def lifespan(app):
    await init_db()
    yield


app = FastAPI(title="Agent N9er Bidding Marketplace", lifespan=lifespan)

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
            cursor = await db.execute("SELECT COUNT(*) FROM tasks")
            count = (await cursor.fetchone())[0]
        return {"ok": 1, "service": "marketplace", "task_count": count}
    except Exception:
        return {"ok": 0, "service": "marketplace", "error": "db_unreachable"}


@app.post("/publish")
async def publish(task: PublishRequest):
    now = datetime.now(timezone.utc).isoformat()
    async with _get_db() as db:
        await db.execute(
            "INSERT OR REPLACE INTO tasks (id, objective, priority_score, status, inputs, source, published_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (task.id, task.objective, task.priority_score, "open",
             json.dumps(task.inputs), task.source, now)
        )
        await _audit(db, "publish", "task", task.id, f"source={task.source}")
        await db.commit()

    logger.info("Published task %s", task.id)
    return {"ok": 1, "task_id": task.id}


@app.get("/feed")
async def feed(
    status: str = None,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    async with _get_db() as db:
        if status:
            cursor = await db.execute(
                "SELECT * FROM tasks WHERE status = ? ORDER BY published_at DESC LIMIT ? OFFSET ?",
                (status, limit, offset),
            )
        else:
            cursor = await db.execute(
                "SELECT * FROM tasks ORDER BY published_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            )
        rows = await cursor.fetchall()
        return [_task_from_row(r) for r in rows]


@app.post("/bid")
async def submit_bid(bid: BidRequest):
    needs_approval = bid.require_approval if bid.require_approval is not None else BID_REQUIRE_APPROVAL
    bid_status = "pending_approval" if needs_approval else "submitted"

    async with _get_db() as db:
        cursor = await db.execute("SELECT id FROM tasks WHERE id = ?", (bid.task_id,))
        if not await cursor.fetchone():
            raise HTTPException(status_code=404, detail="Task not found")

        now = datetime.now(timezone.utc).isoformat()
        await db.execute(
            "INSERT OR REPLACE INTO bids (task_id, agent_id, price, eta_minutes, confidence, submitted_at, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (bid.task_id, bid.agent_id, bid.price, bid.eta_minutes, bid.confidence, now, bid_status)
        )
        await _audit(db, "bid", "task", bid.task_id, f"agent={bid.agent_id} confidence={bid.confidence} status={bid_status}")
        await db.commit()

    logger.info("Bid from agent %s on task %s (confidence=%.2f, status=%s)", bid.agent_id, bid.task_id, bid.confidence, bid_status)
    return {"ok": 1, "status": bid_status}


@app.get("/bids/pending")
async def list_pending_bids(
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    async with _get_db() as db:
        cursor = await db.execute(
            "SELECT * FROM bids WHERE status = 'pending_approval' ORDER BY submitted_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )
        rows = await cursor.fetchall()
        return [_bid_from_row(r) for r in rows]


@app.get("/bids/{task_id}")
async def get_bids(task_id: str):
    async with _get_db() as db:
        cursor = await db.execute("SELECT * FROM bids WHERE task_id = ? ORDER BY confidence DESC", (task_id,))
        rows = await cursor.fetchall()
        if not rows:
            cursor2 = await db.execute("SELECT id FROM tasks WHERE id = ?", (task_id,))
            if not await cursor2.fetchone():
                raise HTTPException(status_code=404, detail="Task not found")
        return [_bid_from_row(r) for r in rows]


@app.post("/bids/{bid_id}/approve")
async def approve_bid(bid_id: int):
    async with _get_db() as db:
        cursor = await db.execute("SELECT * FROM bids WHERE id = ?", (bid_id,))
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Bid not found")
        if row["status"] != "pending_approval":
            raise HTTPException(status_code=409, detail=f"Bid is already '{row['status']}', not pending_approval")

        now = datetime.now(timezone.utc).isoformat()
        await db.execute(
            "UPDATE bids SET status = 'submitted', reviewed_at = ? WHERE id = ?",
            (now, bid_id),
        )
        await _audit(db, "approve_bid", "bid", str(bid_id),
                      f"task={row['task_id']} agent={row['agent_id']}")
        await db.commit()

    logger.info("Bid %d approved (task=%s, agent=%s)", bid_id, row["task_id"], row["agent_id"])
    return {"ok": 1, "bid_id": bid_id, "status": "submitted"}


@app.post("/bids/{bid_id}/reject")
async def reject_bid(bid_id: int):
    async with _get_db() as db:
        cursor = await db.execute("SELECT * FROM bids WHERE id = ?", (bid_id,))
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Bid not found")
        if row["status"] != "pending_approval":
            raise HTTPException(status_code=409, detail=f"Bid is already '{row['status']}', not pending_approval")

        now = datetime.now(timezone.utc).isoformat()
        await db.execute(
            "UPDATE bids SET status = 'rejected', reviewed_at = ? WHERE id = ?",
            (now, bid_id),
        )
        await _audit(db, "reject_bid", "bid", str(bid_id),
                      f"task={row['task_id']} agent={row['agent_id']}")
        await db.commit()

    logger.info("Bid %d rejected (task=%s, agent=%s)", bid_id, row["task_id"], row["agent_id"])
    return {"ok": 1, "bid_id": bid_id, "status": "rejected"}


@app.post("/bids/approve-all/{task_id}")
async def approve_all_bids_for_task(task_id: str):
    async with _get_db() as db:
        now = datetime.now(timezone.utc).isoformat()
        cursor = await db.execute(
            "UPDATE bids SET status = 'submitted', reviewed_at = ? WHERE task_id = ? AND status = 'pending_approval'",
            (now, task_id),
        )
        count = cursor.rowcount
        await _audit(db, "approve_all_bids", "task", task_id, f"approved={count}")
        await db.commit()

    logger.info("Approved %d pending bids for task %s", count, task_id)
    return {"ok": 1, "task_id": task_id, "approved_count": count}


@app.post("/award/{task_id}")
async def award_task(task_id: str):
    async with _get_db() as db:
        cursor = await db.execute(
            "SELECT * FROM bids WHERE task_id = ? AND status = 'submitted' ORDER BY confidence DESC LIMIT 1",
            (task_id,)
        )
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="No submitted bids for task")

        winning_bid = _bid_from_row(row)
        await db.execute(
            "UPDATE tasks SET status = 'awarded', awarded_to = ? WHERE id = ?",
            (winning_bid["agent_id"], task_id)
        )
        await _audit(db, "award", "task", task_id, f"winner={winning_bid['agent_id']}")
        await db.commit()

    logger.info("Task %s awarded to agent %s", task_id, winning_bid["agent_id"])
    return {"ok": 1, "winner": winning_bid}


@app.post("/complete/{task_id}")
async def complete_task(task_id: str, result: CompleteRequest):
    status = "completed" if result.success else "failed"
    async with _get_db() as db:
        await db.execute("UPDATE tasks SET status = ? WHERE id = ?", (status, task_id))
        await _audit(db, "complete", "task", task_id, f"status={status}")
        await db.commit()
    logger.info("Task %s marked %s", task_id, status)
    return {"ok": 1}


@app.get("/audit")
async def get_audit_log(
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    async with _get_db() as db:
        cursor = await db.execute(
            "SELECT * FROM audit_log ORDER BY timestamp DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )
        rows = await cursor.fetchall()
        return [
            {
                "id": row["id"],
                "action": row["action"],
                "entity_type": row["entity_type"],
                "entity_id": row["entity_id"],
                "detail": row["detail"],
                "timestamp": row["timestamp"],
            }
            for row in rows
        ]


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
    result = {
        "id": row["id"],
        "task_id": row["task_id"],
        "agent_id": row["agent_id"],
        "price": row["price"],
        "eta_minutes": row["eta_minutes"],
        "confidence": row["confidence"],
        "submitted_at": row["submitted_at"],
    }
    try:
        result["status"] = row["status"]
        result["reviewed_at"] = row["reviewed_at"]
    except (IndexError, KeyError):
        pass
    return result
