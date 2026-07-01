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
from shared.llm import complete, estimate_cost, has_available_provider, select_tier

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


class ProposalRequest(BaseModel):
    prospect_id: str = ""
    title: str
    description: str = ""
    platform: str = "unknown"
    budget_max: float = 0
    skills: str = ""
    tone: str = "professional"


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


MAX_RETRIES = int(os.getenv("EXECUTION_MAX_RETRIES", "2"))


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
            "mode": "live" if has_available_provider() else "simulation",
        }
    except Exception:
        return {"ok": 0, "service": "execution", "error": "db_unreachable"}


@app.post("/execute")
async def execute(request: ExecuteRequest):
    if has_available_provider() and request.objective:
        result = await _execute_with_retry(request)
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


async def _execute_with_retry(request: ExecuteRequest) -> dict:
    last_result = None
    for attempt in range(MAX_RETRIES + 1):
        result = await _execute_live(request)
        if result.get("success"):
            if attempt > 0:
                result["retries"] = attempt
            return result
        last_result = result
        if attempt < MAX_RETRIES:
            logger.warning("Execution failed for task %s, retry %d/%d",
                          request.task_id, attempt + 1, MAX_RETRIES)
    last_result["retries"] = MAX_RETRIES
    return last_result


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


@app.get("/analytics")
async def analytics(days: int = Query(default=30, ge=1, le=365)):
    async with _get_db() as db:
        cursor = await db.execute(
            "SELECT COUNT(*) as total, SUM(CASE WHEN success THEN 1 ELSE 0 END) as successes, "
            "AVG(duration) as avg_duration, SUM(cost_usd) as total_cost, "
            "SUM(CASE WHEN mode='live' THEN 1 ELSE 0 END) as live_count, "
            "SUM(CASE WHEN mode='simulation' THEN 1 ELSE 0 END) as sim_count "
            "FROM executions WHERE executed_at >= datetime('now', ?)",
            (f"-{days} days",),
        )
        row = await cursor.fetchone()
        total = row[0] or 0
        successes = row[1] or 0

        cursor2 = await db.execute(
            "SELECT agent_id, COUNT(*) as tasks, SUM(CASE WHEN success THEN 1 ELSE 0 END) as wins, "
            "AVG(duration) as avg_dur, SUM(cost_usd) as cost "
            "FROM executions WHERE executed_at >= datetime('now', ?) "
            "GROUP BY agent_id ORDER BY tasks DESC LIMIT 20",
            (f"-{days} days",),
        )
        agents = []
        for r in await cursor2.fetchall():
            agents.append({
                "agent_id": r[0], "tasks": r[1], "wins": r[2],
                "success_rate": round(r[2] / r[1], 3) if r[1] else 0,
                "avg_duration": round(r[3], 1) if r[3] else 0,
                "total_cost": round(r[4], 4) if r[4] else 0,
            })

        cursor3 = await db.execute(
            "SELECT model, COUNT(*) as uses, SUM(cost_usd) as cost, AVG(duration) as avg_dur "
            "FROM executions WHERE executed_at >= datetime('now', ?) AND model != '' "
            "GROUP BY model ORDER BY uses DESC",
            (f"-{days} days",),
        )
        models = []
        for r in await cursor3.fetchall():
            models.append({
                "model": r[0], "uses": r[1],
                "total_cost": round(r[2], 4) if r[2] else 0,
                "avg_duration": round(r[3], 1) if r[3] else 0,
            })

    return {
        "period_days": days,
        "total_executions": total,
        "successes": successes,
        "failures": total - successes,
        "success_rate": round(successes / total, 3) if total else 0,
        "avg_duration": round(row[2], 1) if row[2] else 0,
        "total_cost_usd": round(row[3], 4) if row[3] else 0,
        "live_executions": row[4] or 0,
        "simulated_executions": row[5] or 0,
        "by_agent": agents,
        "by_model": models,
    }


@app.post("/proposal")
async def generate_proposal(req: ProposalRequest):
    if not has_available_provider():
        return _simulated_proposal(req)

    tone_map = {
        "professional": "formal and professional, emphasizing reliability and expertise",
        "friendly": "warm and approachable, showing genuine interest",
        "technical": "technically detailed, demonstrating deep domain knowledge",
        "concise": "brief and direct, focusing only on key qualifications",
    }
    tone_desc = tone_map.get(req.tone, tone_map["professional"])

    messages = [
        {
            "role": "system",
            "content": (
                "You are Agent N9er, an AI-powered freelance agent. Write a compelling "
                f"proposal/cover letter that is {tone_desc}. "
                "Include: 1) A hook addressing the client's need, "
                "2) Relevant capabilities and approach, "
                "3) Estimated timeline, "
                "4) A clear call to action. "
                "Keep it under 300 words. Do NOT include pricing — that's handled separately."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Platform: {req.platform}\n"
                f"Job Title: {req.title}\n"
                f"Description: {req.description}\n"
                f"Required Skills: {req.skills}\n"
                f"Client Budget: ${req.budget_max}" if req.budget_max else
                f"Platform: {req.platform}\n"
                f"Job Title: {req.title}\n"
                f"Description: {req.description}\n"
                f"Required Skills: {req.skills}"
            ),
        },
    ]

    try:
        result = await complete(messages, tier="budget", max_tokens=1024, temperature=0.5)
        return {
            "ok": 1,
            "prospect_id": req.prospect_id,
            "proposal": result.content,
            "mode": "live",
            "model": result.model,
            "cost_usd": result.cost_usd,
            "tokens": result.input_tokens + result.output_tokens,
        }
    except Exception as e:
        logger.error("Proposal generation failed: %s", e)
        return _simulated_proposal(req)


def _simulated_proposal(req: ProposalRequest) -> dict:
    proposal = (
        f"Thank you for posting \"{req.title}\". "
        "I have extensive experience with the skills required for this project "
        "and am confident I can deliver high-quality results. "
        "My approach would be to first thoroughly analyze the requirements, "
        "then implement a clean, well-tested solution. "
        "I typically deliver projects like this within 3-5 business days. "
        "I'd love to discuss the details further."
    )
    return {
        "ok": 1,
        "prospect_id": req.prospect_id,
        "proposal": proposal,
        "mode": "simulation",
        "model": "none",
        "cost_usd": 0,
        "tokens": 0,
    }


@app.post("/format-deliverable")
async def format_deliverable(payload: dict):
    task_id = payload.get("task_id", "")
    format_type = payload.get("format", "markdown")

    async with _get_db() as db:
        cursor = await db.execute(
            "SELECT * FROM executions WHERE task_id = ? ORDER BY executed_at DESC LIMIT 1",
            (task_id,),
        )
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Execution not found")

        try:
            raw_output = row["output"] or ""
        except (IndexError, KeyError):
            raw_output = ""

    if not raw_output:
        return {"ok": 0, "detail": "No output to format"}

    if format_type == "markdown":
        formatted = _format_markdown(raw_output, task_id, row)
    elif format_type == "html":
        formatted = _format_html(raw_output, task_id, row)
    elif format_type == "plain":
        formatted = raw_output
    else:
        formatted = _format_markdown(raw_output, task_id, row)

    return {
        "ok": 1,
        "task_id": task_id,
        "format": format_type,
        "content": formatted,
        "word_count": len(formatted.split()),
    }


def _format_markdown(output: str, task_id: str, row) -> str:
    try:
        model = row["model"] or "unknown"
        cost = row["cost_usd"] or 0
    except (IndexError, KeyError):
        model = "unknown"
        cost = 0

    header = (
        f"# Deliverable: {task_id}\n\n"
        f"**Agent:** {row['agent_id']}  \n"
        f"**Model:** {model}  \n"
        f"**Generated:** {row['executed_at']}  \n"
        f"**Cost:** ${cost:.4f}  \n\n"
        "---\n\n"
    )
    return header + output


def _format_html(output: str, task_id: str, row) -> str:
    try:
        model = row["model"] or "unknown"
        cost = row["cost_usd"] or 0
    except (IndexError, KeyError):
        model = "unknown"
        cost = 0

    lines = output.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return (
        f"<div class='deliverable'>"
        f"<h1>Deliverable: {task_id}</h1>"
        f"<div class='meta'>"
        f"<span>Agent: {row['agent_id']}</span> | "
        f"<span>Model: {model}</span> | "
        f"<span>Cost: ${cost:.4f}</span>"
        f"</div><hr/>"
        f"<div class='content'><pre>{lines}</pre></div>"
        f"</div>"
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8700"))
    uvicorn.run("main:app", host="0.0.0.0", port=port, log_level="info")
