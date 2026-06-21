import os
import sys
import uuid
import logging
from contextlib import asynccontextmanager
from datetime import datetime

import aiosqlite
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared.security import RequestIDMiddleware, ServiceTokenMiddleware
from shared.config import CORS_ORIGINS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("prospector")

DB_PATH = os.getenv("PROSPECTOR_DB_PATH", "/data/prospector.db")
EVALUATOR_URL = os.getenv("EVALUATOR_URL", "http://localhost:8800")
SERVICE_TOKEN = os.getenv("SERVICE_TOKEN", "")

UPWORK_RSS_BASE = "https://www.upwork.com/ab/feed/jobs/rss"
UPWORK_SEARCH_CATEGORIES = os.getenv(
    "UPWORK_SEARCH_CATEGORIES",
    "web-development,data-science,ai-ml,writing,software-development"
).split(",")

PROSPECT_STATUSES = [
    "discovered", "evaluating", "approved", "applied",
    "hired", "executing", "delivered", "paid", "rated", "rejected",
]


class ScanRequest(BaseModel):
    platform: str = "upwork"
    query: str = ""
    category: str = ""
    max_results: int = 20


class ProspectUpdate(BaseModel):
    status: str
    notes: str = ""


def _svc_headers():
    h = {"Content-Type": "application/json"}
    if SERVICE_TOKEN:
        h["X-Service-Token"] = SERVICE_TOKEN
    return h


async def _init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS prospects (
                id TEXT PRIMARY KEY,
                platform TEXT NOT NULL,
                platform_job_id TEXT,
                title TEXT NOT NULL,
                description TEXT,
                budget_min REAL DEFAULT 0,
                budget_max REAL DEFAULT 0,
                client_rating REAL DEFAULT 0,
                skills TEXT DEFAULT '',
                status TEXT DEFAULT 'discovered',
                evaluation_id TEXT,
                quoted_price REAL DEFAULT 0,
                estimated_cost REAL DEFAULT 0,
                actual_cost REAL DEFAULT 0,
                url TEXT,
                applied_at TIMESTAMP,
                hired_at TIMESTAMP,
                delivered_at TIMESTAMP,
                paid_at TIMESTAMP,
                rating INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.commit()


@asynccontextmanager
async def lifespan(app):
    await _init_db()
    yield


app = FastAPI(title="Agent N9er Prospector", lifespan=lifespan)

app.add_middleware(RequestIDMiddleware)
app.add_middleware(ServiceTokenMiddleware)
app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, allow_methods=["GET", "POST", "PATCH"], allow_headers=["*"])


@app.get("/health")
async def health():
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute("SELECT COUNT(*) FROM prospects")
            count = (await cursor.fetchone())[0]
        return {"ok": 1, "service": "prospector", "prospects": count}
    except Exception:
        return {"ok": 0, "service": "prospector", "error": "db_unreachable"}


@app.post("/scan")
async def scan(req: ScanRequest):
    if req.platform == "upwork":
        prospects = await _scan_upwork(req.query, req.category, req.max_results)
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported platform: {req.platform}")

    saved = 0
    for p in prospects:
        existing = await _get_by_platform_id(p["platform"], p["platform_job_id"])
        if not existing:
            await _save_prospect(p)
            saved += 1

    logger.info("Scan complete: %d discovered, %d new on %s", len(prospects), saved, req.platform)
    return {"ok": 1, "discovered": len(prospects), "new": saved, "platform": req.platform}


async def _scan_upwork(query: str, category: str, max_results: int) -> list[dict]:
    params = {"sort": "recency", "paging": f"0;{max_results}"}
    if query:
        params["q"] = query
    if category:
        params["subcategory2"] = category

    prospects = []
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(UPWORK_RSS_BASE, params=params)
            resp.raise_for_status()
            items = _parse_rss(resp.text)

            for item in items[:max_results]:
                prospects.append({
                    "id": str(uuid.uuid4()),
                    "platform": "upwork",
                    "platform_job_id": item.get("guid", str(uuid.uuid4())),
                    "title": item.get("title", "Untitled"),
                    "description": item.get("description", ""),
                    "budget_min": _extract_budget(item.get("description", ""), "min"),
                    "budget_max": _extract_budget(item.get("description", ""), "max"),
                    "url": item.get("link", ""),
                    "skills": item.get("skills", ""),
                    "status": "discovered",
                })
    except httpx.RequestError as e:
        logger.warning("Upwork RSS fetch failed: %s", e)

    return prospects


def _parse_rss(xml_text: str) -> list[dict]:
    import xml.etree.ElementTree as ET
    items = []
    try:
        root = ET.fromstring(xml_text)
        for item in root.iter("item"):
            entry = {}
            for child in item:
                tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                entry[tag] = child.text or ""
            items.append(entry)
    except ET.ParseError:
        logger.warning("Failed to parse RSS feed")
    return items


def _extract_budget(description: str, which: str) -> float:
    import re
    patterns = [
        r"\$(\d[\d,]*(?:\.\d{2})?)",
        r"Budget:\s*\$(\d[\d,]*(?:\.\d{2})?)\s*-\s*\$(\d[\d,]*(?:\.\d{2})?)",
    ]
    for pattern in patterns:
        match = re.search(pattern, description)
        if match:
            groups = match.groups()
            if len(groups) == 2:
                val = groups[0] if which == "min" else groups[1]
                return float(val.replace(",", ""))
            elif len(groups) == 1:
                return float(groups[0].replace(",", ""))
    return 0


@app.get("/prospects")
async def list_prospects(status: str = "", platform: str = "", limit: int = 50):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        query = "SELECT * FROM prospects WHERE 1=1"
        params = []
        if status:
            query += " AND status = ?"
            params.append(status)
        if platform:
            query += " AND platform = ?"
            params.append(platform)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        cursor = await db.execute(query, params)
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


@app.get("/prospects/{prospect_id}")
async def get_prospect(prospect_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM prospects WHERE id = ?", (prospect_id,))
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Prospect not found")
        return dict(row)


@app.post("/prospects/{prospect_id}/evaluate")
async def evaluate_prospect(prospect_id: str):
    prospect = await _get_prospect(prospect_id)
    if not prospect:
        raise HTTPException(status_code=404, detail="Prospect not found")

    await _update_status(prospect_id, "evaluating")

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{EVALUATOR_URL}/evaluate",
                json={
                    "title": prospect["title"],
                    "description": prospect["description"],
                    "platform": prospect["platform"],
                    "budget_min": prospect["budget_min"],
                    "budget_max": prospect["budget_max"],
                    "skills_required": prospect["skills"].split(",") if prospect["skills"] else [],
                },
                headers=_svc_headers(),
            )
            resp.raise_for_status()
            evaluation = resp.json()

        new_status = "approved" if evaluation.get("viable") else "rejected"
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE prospects SET status = ?, evaluation_id = ?, quoted_price = ?, estimated_cost = ? WHERE id = ?",
                (new_status, evaluation["evaluation_id"], evaluation.get("quoted_price_usd", 0),
                 evaluation.get("estimated_cost_usd", 0), prospect_id),
            )
            await db.commit()

        logger.info("Prospect %s evaluated: %s (quote=$%.2f)",
                     prospect_id[:8], new_status, evaluation.get("quoted_price_usd", 0))
        return {"ok": 1, "status": new_status, "evaluation": evaluation}

    except httpx.RequestError as e:
        await _update_status(prospect_id, "discovered")
        raise HTTPException(status_code=503, detail=f"Evaluator unreachable: {e}")


@app.patch("/prospects/{prospect_id}")
async def update_prospect(prospect_id: str, update: ProspectUpdate):
    if update.status not in PROSPECT_STATUSES:
        raise HTTPException(status_code=422, detail=f"Invalid status: {update.status}")

    prospect = await _get_prospect(prospect_id)
    if not prospect:
        raise HTTPException(status_code=404, detail="Prospect not found")

    timestamp_field = {
        "applied": "applied_at",
        "hired": "hired_at",
        "delivered": "delivered_at",
        "paid": "paid_at",
    }.get(update.status)

    async with aiosqlite.connect(DB_PATH) as db:
        if timestamp_field:
            await db.execute(
                f"UPDATE prospects SET status = ?, {timestamp_field} = ? WHERE id = ?",
                (update.status, datetime.utcnow().isoformat(), prospect_id),
            )
        else:
            await db.execute(
                "UPDATE prospects SET status = ? WHERE id = ?",
                (update.status, prospect_id),
            )
        await db.commit()

    logger.info("Prospect %s → %s", prospect_id[:8], update.status)
    return {"ok": 1, "prospect_id": prospect_id, "status": update.status}


@app.get("/stats")
async def stats():
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT status, COUNT(*) as count FROM prospects GROUP BY status"
        )
        rows = await cursor.fetchall()
        by_status = {row[0]: row[1] for row in rows}

        cursor = await db.execute(
            "SELECT SUM(quoted_price), SUM(estimated_cost), SUM(actual_cost) FROM prospects WHERE status = 'paid'"
        )
        row = await cursor.fetchone()
        revenue = row[0] or 0
        costs = row[1] or 0
        actual_costs = row[2] or 0

    return {
        "by_status": by_status,
        "total_prospects": sum(by_status.values()),
        "revenue": round(revenue, 2),
        "estimated_costs": round(costs, 2),
        "actual_costs": round(actual_costs, 2),
        "estimated_profit": round(revenue - costs, 2),
    }


@app.get("/platforms")
async def platforms():
    return [
        {"name": "upwork", "status": "active", "type": "rss"},
        {"name": "github_bounties", "status": "planned", "type": "api"},
    ]


async def _get_prospect(prospect_id: str) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM prospects WHERE id = ?", (prospect_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None


async def _get_by_platform_id(platform: str, platform_job_id: str) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM prospects WHERE platform = ? AND platform_job_id = ?",
            (platform, platform_job_id),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def _save_prospect(p: dict):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO prospects (id, platform, platform_job_id, title, description, budget_min, budget_max, skills, status, url) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (p["id"], p["platform"], p["platform_job_id"], p["title"], p["description"],
             p["budget_min"], p["budget_max"], p.get("skills", ""), p["status"], p.get("url", "")),
        )
        await db.commit()


async def _update_status(prospect_id: str, status: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE prospects SET status = ? WHERE id = ?", (status, prospect_id))
        await db.commit()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8900)
