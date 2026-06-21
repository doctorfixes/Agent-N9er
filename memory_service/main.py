import os
import sys
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import aiosqlite
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared.security import RequestIDMiddleware, ServiceTokenMiddleware, MaxBodySizeMiddleware
from shared.config import CORS_ORIGINS
from shared.logging_config import setup_logging

logger = setup_logging("memory")

DB_PATH = os.getenv("MEMORY_DB_PATH", "/data/memory.db")


class OutcomeRecord(BaseModel):
    task_id: str
    agent_id: str = "agent-n9er-primary"
    platform: str = "unknown"
    category: str = "uncategorized"
    complexity: str = "moderate"
    success: bool = False
    estimated_cost_usd: float = 0
    actual_cost_usd: float = 0
    estimated_tokens: int = 0
    actual_tokens: int = 0
    quoted_price_usd: float = 0
    duration_seconds: float = 0
    tier: str = "standard"
    model: str = ""
    client_rating: int | None = None


class PromptPatternRecord(BaseModel):
    category: str
    complexity: str
    strategy: str
    success: bool = False
    quality_score: float = 0


@asynccontextmanager
async def _get_db():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        yield db


async def _init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA busy_timeout=5000")

        await db.execute("""
            CREATE TABLE IF NOT EXISTS outcomes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                agent_id TEXT NOT NULL,
                platform TEXT DEFAULT 'unknown',
                category TEXT DEFAULT 'uncategorized',
                complexity TEXT DEFAULT 'moderate',
                success INTEGER NOT NULL,
                estimated_cost_usd REAL DEFAULT 0,
                actual_cost_usd REAL DEFAULT 0,
                estimated_tokens INTEGER DEFAULT 0,
                actual_tokens INTEGER DEFAULT 0,
                quoted_price_usd REAL DEFAULT 0,
                duration_seconds REAL DEFAULT 0,
                tier TEXT DEFAULT 'standard',
                model TEXT DEFAULT '',
                client_rating INTEGER,
                recorded_at TEXT NOT NULL
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS skill_profile (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id TEXT NOT NULL,
                category TEXT NOT NULL,
                attempts INTEGER DEFAULT 0,
                successes INTEGER DEFAULT 0,
                success_rate REAL DEFAULT 0,
                avg_duration REAL DEFAULT 0,
                avg_cost_accuracy REAL DEFAULT 0,
                avg_client_rating REAL DEFAULT 0,
                total_revenue REAL DEFAULT 0,
                total_cost REAL DEFAULT 0,
                updated_at TEXT NOT NULL,
                UNIQUE(agent_id, category)
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS platform_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                platform TEXT NOT NULL UNIQUE,
                leads_scanned INTEGER DEFAULT 0,
                leads_evaluated INTEGER DEFAULT 0,
                leads_approved INTEGER DEFAULT 0,
                leads_executed INTEGER DEFAULT 0,
                leads_succeeded INTEGER DEFAULT 0,
                conversion_rate REAL DEFAULT 0,
                avg_profit REAL DEFAULT 0,
                avg_client_rating REAL DEFAULT 0,
                updated_at TEXT NOT NULL
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS pricing_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                complexity TEXT NOT NULL,
                estimated_cost REAL,
                actual_cost REAL,
                quoted_price REAL,
                won_bid INTEGER DEFAULT 1,
                recorded_at TEXT NOT NULL
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS prompt_patterns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                complexity TEXT NOT NULL,
                strategy TEXT NOT NULL,
                attempts INTEGER DEFAULT 0,
                successes INTEGER DEFAULT 0,
                avg_quality REAL DEFAULT 0,
                updated_at TEXT NOT NULL,
                UNIQUE(category, complexity, strategy)
            )
        """)

        await db.execute("CREATE INDEX IF NOT EXISTS idx_outcomes_agent ON outcomes(agent_id)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_outcomes_category ON outcomes(category)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_outcomes_platform ON outcomes(platform)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_outcomes_time ON outcomes(recorded_at)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_skill_agent ON skill_profile(agent_id)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_pricing_cat ON pricing_history(category)")
        await db.commit()
    logger.info("Memory database initialized at %s", DB_PATH)


@asynccontextmanager
async def lifespan(app):
    await _init_db()
    yield


app = FastAPI(title="Agent N9er Memory & Learning", lifespan=lifespan)

app.add_middleware(RequestIDMiddleware)
app.add_middleware(ServiceTokenMiddleware)
app.add_middleware(MaxBodySizeMiddleware)
app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, allow_methods=["GET", "POST"], allow_headers=["*"])


@app.get("/health")
async def health():
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute("SELECT COUNT(*) FROM outcomes")
            count = (await cursor.fetchone())[0]
        return {"ok": 1, "service": "memory", "total_outcomes": count}
    except Exception:
        return {"ok": 0, "service": "memory", "error": "db_unreachable"}


@app.post("/outcomes")
async def record_outcome(record: OutcomeRecord):
    now = datetime.now(timezone.utc).isoformat()
    async with _get_db() as db:
        await db.execute(
            """INSERT INTO outcomes
               (task_id, agent_id, platform, category, complexity, success,
                estimated_cost_usd, actual_cost_usd, estimated_tokens, actual_tokens,
                quoted_price_usd, duration_seconds, tier, model, client_rating, recorded_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (record.task_id, record.agent_id, record.platform, record.category,
             record.complexity, int(record.success), record.estimated_cost_usd,
             record.actual_cost_usd, record.estimated_tokens, record.actual_tokens,
             record.quoted_price_usd, record.duration_seconds, record.tier,
             record.model, record.client_rating, now),
        )
        await db.commit()

    await _update_skill_profile(record)
    await _update_platform_stats(record)
    await _update_pricing_history(record)

    logger.info("Outcome recorded: task=%s category=%s success=%s", record.task_id, record.category, record.success)
    return {"ok": 1, "task_id": record.task_id}


async def _update_skill_profile(record: OutcomeRecord):
    now = datetime.now(timezone.utc).isoformat()
    async with _get_db() as db:
        cursor = await db.execute(
            "SELECT * FROM skill_profile WHERE agent_id = ? AND category = ?",
            (record.agent_id, record.category),
        )
        row = await cursor.fetchone()

        if row:
            attempts = row["attempts"] + 1
            successes = row["successes"] + (1 if record.success else 0)
            success_rate = round(successes / attempts, 4)

            prev_dur = row["avg_duration"]
            avg_duration = round(prev_dur + (record.duration_seconds - prev_dur) / attempts, 2)

            cost_accuracy = 0.0
            if record.estimated_cost_usd > 0:
                cost_accuracy = 1 - abs(record.actual_cost_usd - record.estimated_cost_usd) / record.estimated_cost_usd
            prev_acc = row["avg_cost_accuracy"]
            avg_cost_accuracy = round(prev_acc + (cost_accuracy - prev_acc) / attempts, 4)

            avg_rating = row["avg_client_rating"]
            if record.client_rating is not None:
                rated_count = row["attempts"]
                avg_rating = round((avg_rating * rated_count + record.client_rating) / (rated_count + 1), 2)

            total_revenue = row["total_revenue"] + (record.quoted_price_usd if record.success else 0)
            total_cost = row["total_cost"] + record.actual_cost_usd

            await db.execute(
                """UPDATE skill_profile SET
                   attempts = ?, successes = ?, success_rate = ?, avg_duration = ?,
                   avg_cost_accuracy = ?, avg_client_rating = ?,
                   total_revenue = ?, total_cost = ?, updated_at = ?
                   WHERE agent_id = ? AND category = ?""",
                (attempts, successes, success_rate, avg_duration, avg_cost_accuracy,
                 avg_rating, round(total_revenue, 4), round(total_cost, 4), now,
                 record.agent_id, record.category),
            )
        else:
            success_rate = 1.0 if record.success else 0.0
            cost_accuracy = 0.0
            if record.estimated_cost_usd > 0:
                cost_accuracy = 1 - abs(record.actual_cost_usd - record.estimated_cost_usd) / record.estimated_cost_usd
            revenue = record.quoted_price_usd if record.success else 0

            await db.execute(
                """INSERT INTO skill_profile
                   (agent_id, category, attempts, successes, success_rate, avg_duration,
                    avg_cost_accuracy, avg_client_rating, total_revenue, total_cost, updated_at)
                   VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (record.agent_id, record.category, int(record.success), success_rate,
                 record.duration_seconds, round(cost_accuracy, 4),
                 float(record.client_rating or 0), round(revenue, 4),
                 round(record.actual_cost_usd, 4), now),
            )
        await db.commit()


async def _update_platform_stats(record: OutcomeRecord):
    now = datetime.now(timezone.utc).isoformat()
    async with _get_db() as db:
        cursor = await db.execute(
            "SELECT * FROM platform_stats WHERE platform = ?", (record.platform,)
        )
        row = await cursor.fetchone()

        if row:
            executed = row["leads_executed"] + 1
            succeeded = row["leads_succeeded"] + (1 if record.success else 0)
            conv = round(succeeded / executed, 4) if executed else 0
            profit = record.quoted_price_usd - record.actual_cost_usd if record.success else 0
            prev_profit = row["avg_profit"]
            avg_profit = round(prev_profit + (profit - prev_profit) / executed, 4)

            avg_rating = row["avg_client_rating"]
            if record.client_rating is not None:
                avg_rating = round((avg_rating * row["leads_executed"] + record.client_rating) / executed, 2)

            await db.execute(
                """UPDATE platform_stats SET
                   leads_executed = ?, leads_succeeded = ?, conversion_rate = ?,
                   avg_profit = ?, avg_client_rating = ?, updated_at = ?
                   WHERE platform = ?""",
                (executed, succeeded, conv, avg_profit, avg_rating, now, record.platform),
            )
        else:
            profit = record.quoted_price_usd - record.actual_cost_usd if record.success else 0
            await db.execute(
                """INSERT INTO platform_stats
                   (platform, leads_executed, leads_succeeded, conversion_rate,
                    avg_profit, avg_client_rating, updated_at)
                   VALUES (?, 1, ?, ?, ?, ?, ?)""",
                (record.platform, int(record.success),
                 1.0 if record.success else 0.0, round(profit, 4),
                 float(record.client_rating or 0), now),
            )
        await db.commit()


async def _update_pricing_history(record: OutcomeRecord):
    now = datetime.now(timezone.utc).isoformat()
    async with _get_db() as db:
        await db.execute(
            """INSERT INTO pricing_history
               (category, complexity, estimated_cost, actual_cost, quoted_price, won_bid, recorded_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (record.category, record.complexity, record.estimated_cost_usd,
             record.actual_cost_usd, record.quoted_price_usd, int(record.success), now),
        )
        await db.commit()


@app.post("/prompt-patterns")
async def record_prompt_pattern(record: PromptPatternRecord):
    now = datetime.now(timezone.utc).isoformat()
    async with _get_db() as db:
        cursor = await db.execute(
            "SELECT * FROM prompt_patterns WHERE category = ? AND complexity = ? AND strategy = ?",
            (record.category, record.complexity, record.strategy),
        )
        row = await cursor.fetchone()

        if row:
            attempts = row["attempts"] + 1
            successes = row["successes"] + (1 if record.success else 0)
            prev_qual = row["avg_quality"]
            avg_quality = round(prev_qual + (record.quality_score - prev_qual) / attempts, 4)
            await db.execute(
                """UPDATE prompt_patterns SET attempts = ?, successes = ?, avg_quality = ?, updated_at = ?
                   WHERE category = ? AND complexity = ? AND strategy = ?""",
                (attempts, successes, avg_quality, now, record.category, record.complexity, record.strategy),
            )
        else:
            await db.execute(
                """INSERT INTO prompt_patterns
                   (category, complexity, strategy, attempts, successes, avg_quality, updated_at)
                   VALUES (?, ?, ?, 1, ?, ?, ?)""",
                (record.category, record.complexity, record.strategy,
                 int(record.success), record.quality_score, now),
            )
        await db.commit()

    return {"ok": 1}


@app.get("/skills/{agent_id}")
async def get_skill_profile(agent_id: str):
    async with _get_db() as db:
        cursor = await db.execute(
            "SELECT * FROM skill_profile WHERE agent_id = ? ORDER BY success_rate DESC",
            (agent_id,),
        )
        rows = await cursor.fetchall()
        if not rows:
            return {"agent_id": agent_id, "skills": [], "strengths": [], "weaknesses": []}

        skills = [dict(r) for r in rows]
        strengths = [s for s in skills if s["attempts"] >= 3 and s["success_rate"] >= 0.7]
        weaknesses = [s for s in skills if s["attempts"] >= 3 and s["success_rate"] < 0.5]

        return {
            "agent_id": agent_id,
            "skills": skills,
            "strengths": [s["category"] for s in strengths],
            "weaknesses": [s["category"] for s in weaknesses],
            "total_tasks": sum(s["attempts"] for s in skills),
            "overall_success_rate": round(
                sum(s["successes"] for s in skills) / max(1, sum(s["attempts"] for s in skills)), 4
            ),
        }


@app.get("/platforms")
async def get_platform_intelligence():
    async with _get_db() as db:
        cursor = await db.execute(
            "SELECT * FROM platform_stats ORDER BY conversion_rate DESC"
        )
        rows = await cursor.fetchall()
        platforms = [dict(r) for r in rows]

        return {
            "platforms": platforms,
            "recommended": [p["platform"] for p in platforms if p["conversion_rate"] >= 0.5] or
                           [p["platform"] for p in platforms[:3]] if platforms else [],
        }


@app.get("/pricing/recommend")
async def recommend_pricing(category: str, complexity: str = "moderate"):
    async with _get_db() as db:
        cursor = await db.execute(
            """SELECT AVG(actual_cost) as avg_cost, AVG(quoted_price) as avg_quote,
                      AVG(CASE WHEN won_bid THEN quoted_price END) as avg_winning_quote,
                      COUNT(*) as total, SUM(won_bid) as wins
               FROM pricing_history WHERE category = ? AND complexity = ?""",
            (category, complexity),
        )
        row = await cursor.fetchone()

        total = row["total"] or 0
        if total < 2:
            return {
                "category": category,
                "complexity": complexity,
                "recommendation": "insufficient_data",
                "data_points": total,
            }

        avg_cost = row["avg_cost"] or 0
        avg_quote = row["avg_quote"] or 0
        avg_winning = row["avg_winning_quote"] or avg_quote
        wins = row["wins"] or 0
        win_rate = wins / total if total else 0

        if win_rate > 0.8:
            suggested_quote = round(avg_winning * 1.1, 2)
            advice = "high_win_rate_raise_price"
        elif win_rate < 0.3:
            suggested_quote = round(avg_winning * 0.9, 2)
            advice = "low_win_rate_lower_price"
        else:
            suggested_quote = round(avg_winning, 2)
            advice = "competitive_pricing"

        return {
            "category": category,
            "complexity": complexity,
            "recommendation": advice,
            "suggested_quote_usd": suggested_quote,
            "avg_cost_usd": round(avg_cost, 4),
            "avg_winning_quote_usd": round(avg_winning, 2),
            "win_rate": round(win_rate, 4),
            "data_points": total,
        }


@app.get("/prompt-patterns/best")
async def best_prompt_pattern(category: str, complexity: str = "moderate"):
    async with _get_db() as db:
        cursor = await db.execute(
            """SELECT * FROM prompt_patterns
               WHERE category = ? AND complexity = ? AND attempts >= 2
               ORDER BY avg_quality DESC, successes DESC LIMIT 3""",
            (category, complexity),
        )
        rows = await cursor.fetchall()
        patterns = [dict(r) for r in rows]

        if not patterns:
            return {"category": category, "complexity": complexity, "patterns": [], "recommendation": "default"}

        return {
            "category": category,
            "complexity": complexity,
            "patterns": patterns,
            "recommendation": patterns[0]["strategy"],
        }


@app.get("/insights")
async def get_insights(agent_id: str = "agent-n9er-primary", days: int = Query(default=30, ge=1, le=365)):
    async with _get_db() as db:
        cursor = await db.execute(
            """SELECT COUNT(*) as total,
                      SUM(CASE WHEN success THEN 1 ELSE 0 END) as successes,
                      AVG(actual_cost_usd) as avg_cost,
                      SUM(quoted_price_usd) as total_revenue,
                      SUM(actual_cost_usd) as total_cost,
                      AVG(duration_seconds) as avg_duration
               FROM outcomes
               WHERE agent_id = ? AND recorded_at >= datetime('now', ?)""",
            (agent_id, f"-{days} days"),
        )
        summary = await cursor.fetchone()

        cursor2 = await db.execute(
            """SELECT category, COUNT(*) as tasks,
                      SUM(CASE WHEN success THEN 1 ELSE 0 END) as wins,
                      AVG(actual_cost_usd) as avg_cost,
                      SUM(quoted_price_usd) as revenue
               FROM outcomes
               WHERE agent_id = ? AND recorded_at >= datetime('now', ?)
               GROUP BY category ORDER BY tasks DESC""",
            (agent_id, f"-{days} days"),
        )
        by_category = [dict(r) for r in await cursor2.fetchall()]

        cursor3 = await db.execute(
            """SELECT complexity,
                      AVG(actual_cost_usd - estimated_cost_usd) as avg_cost_delta,
                      AVG(actual_tokens - estimated_tokens) as avg_token_delta,
                      COUNT(*) as samples
               FROM outcomes
               WHERE agent_id = ? AND estimated_cost_usd > 0
                     AND recorded_at >= datetime('now', ?)
               GROUP BY complexity""",
            (agent_id, f"-{days} days"),
        )
        estimation_accuracy = [dict(r) for r in await cursor3.fetchall()]

        total = summary["total"] or 0
        successes = summary["successes"] or 0
        total_revenue = summary["total_revenue"] or 0
        total_cost = summary["total_cost"] or 0

        recommendations = []
        for cat in by_category:
            if cat["tasks"] >= 3:
                rate = cat["wins"] / cat["tasks"]
                if rate >= 0.8:
                    recommendations.append(f"Strong in {cat['category']} ({rate:.0%} success) — prioritize these")
                elif rate < 0.4:
                    recommendations.append(f"Weak in {cat['category']} ({rate:.0%} success) — consider avoiding or improving")

        for est in estimation_accuracy:
            if est["samples"] >= 3 and est["avg_cost_delta"] and abs(est["avg_cost_delta"]) > 0.01:
                direction = "under" if est["avg_cost_delta"] > 0 else "over"
                recommendations.append(
                    f"Consistently {direction}-estimating costs for {est['complexity']} tasks "
                    f"(avg delta: ${est['avg_cost_delta']:+.4f})"
                )

        return {
            "agent_id": agent_id,
            "period_days": days,
            "summary": {
                "total_tasks": total,
                "successes": successes,
                "success_rate": round(successes / total, 4) if total else 0,
                "total_revenue": round(total_revenue, 2),
                "total_cost": round(total_cost, 4),
                "profit": round(total_revenue - total_cost, 2),
                "avg_duration_seconds": round(summary["avg_duration"], 1) if summary["avg_duration"] else 0,
            },
            "by_category": by_category,
            "estimation_accuracy": estimation_accuracy,
            "recommendations": recommendations,
        }


@app.get("/confidence/{agent_id}")
async def get_adjusted_confidence(agent_id: str, category: str, base_confidence: float = 0.5):
    async with _get_db() as db:
        cursor = await db.execute(
            "SELECT success_rate, attempts FROM skill_profile WHERE agent_id = ? AND category = ?",
            (agent_id, category),
        )
        row = await cursor.fetchone()

        if not row or row["attempts"] < 3:
            return {
                "agent_id": agent_id,
                "category": category,
                "base_confidence": base_confidence,
                "adjusted_confidence": base_confidence,
                "adjustment_source": "no_history",
            }

        historical_rate = row["success_rate"]
        weight = min(row["attempts"] / 20, 0.8)
        adjusted = round(base_confidence * (1 - weight) + historical_rate * weight, 4)
        adjusted = max(0.1, min(1.0, adjusted))

        return {
            "agent_id": agent_id,
            "category": category,
            "base_confidence": base_confidence,
            "adjusted_confidence": adjusted,
            "historical_success_rate": historical_rate,
            "data_points": row["attempts"],
            "weight": round(weight, 2),
            "adjustment_source": "skill_history",
        }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=9300)
