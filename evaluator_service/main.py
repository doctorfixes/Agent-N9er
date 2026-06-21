import os
import sys
import uuid
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import aiosqlite
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared.security import RequestIDMiddleware, ServiceTokenMiddleware
from shared.config import CORS_ORIGINS
from shared.llm import estimate_cost, select_tier, MODEL_TIERS, MARKUP_MULTIPLIER
from shared.guardrails import check_task_content, check_spending_limits
from shared.logging_config import setup_logging

logger = setup_logging("evaluator")

DB_PATH = os.getenv("EVALUATOR_DB_PATH", "/data/evaluator.db")
MINIMUM_QUOTE_USD = float(os.getenv("MINIMUM_QUOTE_USD", "5.00"))

COMPLEXITY_SIGNALS = {
    "expert": ["architecture", "system design", "distributed", "migration", "security audit",
               "machine learning", "ml pipeline", "infrastructure", "scalability"],
    "complex": ["api", "database", "integration", "full-stack", "deployment", "testing",
                "refactor", "optimization", "authentication", "payment"],
    "moderate": ["web app", "script", "automation", "dashboard", "crud", "form",
                 "landing page", "email", "report", "data"],
    "simple": ["fix", "bug", "typo", "update", "change", "edit", "small", "quick",
               "readme", "docs", "comment"],
    "trivial": ["hello world", "rename", "formatting", "lint"],
}


class EvaluateRequest(BaseModel):
    title: str = ""
    description: str = ""
    platform: str = "unknown"
    budget_min: float = 0
    budget_max: float = 0
    skills_required: list[str] = Field(default_factory=list)
    deadline: str | None = None


class EvaluationResult(BaseModel):
    evaluation_id: str
    viable: bool
    complexity: str
    recommended_tier: str
    recommended_model: str
    estimated_input_tokens: int
    estimated_output_tokens: int
    estimated_cost_usd: float
    quoted_price_usd: float
    markup_multiplier: float
    estimated_profit_usd: float
    rush_multiplier: float = 1.0
    rejection_reason: str | None = None


def assess_complexity(title: str, description: str, skills: list[str]) -> str:
    text = f"{title} {description} {' '.join(skills)}".lower()
    for level in ["expert", "complex", "moderate", "simple", "trivial"]:
        if any(signal in text for signal in COMPLEXITY_SIGNALS[level]):
            return level
    return "moderate"


def estimate_output_tokens(complexity: str, description: str) -> int:
    base = {"trivial": 500, "simple": 1000, "moderate": 3000, "complex": 6000, "expert": 12000}
    desc_factor = min(2.0, max(1.0, len(description) / 500))
    return int(base.get(complexity, 3000) * desc_factor)


NON_VIABLE_SIGNALS = [
    "phone call", "video call", "in-person", "on-site", "physical",
    "hardware", "soldering", "printing", "shipping",
]


def compute_rush_multiplier(deadline: str | None) -> float:
    if not deadline:
        return 1.0
    try:
        dl = datetime.fromisoformat(deadline)
        if dl.tzinfo is None:
            dl = dl.replace(tzinfo=timezone.utc)
        hours_left = (dl - datetime.now(timezone.utc)).total_seconds() / 3600
        if hours_left <= 0:
            return 2.0
        elif hours_left <= 4:
            return 1.75
        elif hours_left <= 24:
            return 1.5
        elif hours_left <= 72:
            return 1.25
        return 1.0
    except (ValueError, TypeError):
        return 1.0


def check_viability(title: str, description: str) -> str | None:
    text = f"{title} {description}".lower()
    for signal in NON_VIABLE_SIGNALS:
        if signal in text:
            return f"Task requires non-digital capability: {signal}"
    return None


async def _init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA busy_timeout=5000")
        await db.execute("""
            CREATE TABLE IF NOT EXISTS evaluations (
                evaluation_id TEXT PRIMARY KEY,
                platform TEXT,
                title TEXT,
                complexity TEXT,
                tier TEXT,
                model TEXT,
                estimated_cost REAL,
                quoted_price REAL,
                viable INTEGER,
                rejection_reason TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_evals_platform ON evaluations(platform)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_evals_viable ON evaluations(viable)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_evals_created ON evaluations(created_at)")
        await db.commit()


@asynccontextmanager
async def lifespan(app):
    await _init_db()
    yield


app = FastAPI(title="Agent N9er Evaluator", lifespan=lifespan)

app.add_middleware(RequestIDMiddleware)
app.add_middleware(ServiceTokenMiddleware)
app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, allow_methods=["GET", "POST"], allow_headers=["*"])


@app.get("/health")
async def health():
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute("SELECT COUNT(*) FROM evaluations")
            count = (await cursor.fetchone())[0]
        return {"ok": 1, "service": "evaluator", "evaluations": count}
    except Exception:
        return {"ok": 0, "service": "evaluator", "error": "db_unreachable"}


@app.post("/evaluate")
async def evaluate(req: EvaluateRequest) -> EvaluationResult:
    evaluation_id = str(uuid.uuid4())

    content_violations = check_task_content(req.title, req.description, " ".join(req.skills_required))
    blocked = [v for v in content_violations if v.severity == "blocked"]
    if blocked:
        rejection = f"Policy violation: {blocked[0].reason}"
        result = EvaluationResult(
            evaluation_id=evaluation_id, viable=False, complexity="unknown",
            recommended_tier="none", recommended_model="none",
            estimated_input_tokens=0, estimated_output_tokens=0,
            estimated_cost_usd=0, quoted_price_usd=0,
            markup_multiplier=MARKUP_MULTIPLIER, estimated_profit_usd=0,
            rejection_reason=rejection,
        )
        await _persist_evaluation(result, req.platform, req.title)
        logger.warning("Task rejected by guardrails: %s — %s", req.title[:50], rejection)
        return result

    rejection = check_viability(req.title, req.description)
    if rejection:
        result = EvaluationResult(
            evaluation_id=evaluation_id, viable=False, complexity="unknown",
            recommended_tier="none", recommended_model="none",
            estimated_input_tokens=0, estimated_output_tokens=0,
            estimated_cost_usd=0, quoted_price_usd=0,
            markup_multiplier=MARKUP_MULTIPLIER, estimated_profit_usd=0,
            rejection_reason=rejection,
        )
        await _persist_evaluation(result, req.platform, req.title)
        return result

    complexity = assess_complexity(req.title, req.description, req.skills_required)
    tier = select_tier(complexity)
    output_tokens = estimate_output_tokens(complexity, req.description)

    prompt_text = f"{req.title}\n{req.description}"
    cost_est = estimate_cost(prompt_text, tier=tier, expected_output_tokens=output_tokens)

    rush = compute_rush_multiplier(req.deadline)
    quoted = max(cost_est.quoted_price_usd * rush, MINIMUM_QUOTE_USD)

    if req.budget_max > 0 and quoted > req.budget_max * 1.5:
        rejection = f"Quoted ${quoted:.2f} exceeds client budget ${req.budget_max:.2f} by too much"
        viable = False
    elif req.budget_max > 0 and cost_est.estimated_cost_usd > req.budget_max:
        rejection = f"Token cost ${cost_est.estimated_cost_usd:.2f} alone exceeds budget ${req.budget_max:.2f}"
        viable = False
    else:
        viable = True

    profit = quoted - cost_est.estimated_cost_usd if viable else 0

    result = EvaluationResult(
        evaluation_id=evaluation_id, viable=viable, complexity=complexity,
        recommended_tier=tier, recommended_model=cost_est.model,
        estimated_input_tokens=cost_est.estimated_input_tokens,
        estimated_output_tokens=cost_est.estimated_output_tokens,
        estimated_cost_usd=cost_est.estimated_cost_usd,
        quoted_price_usd=quoted if viable else 0,
        markup_multiplier=MARKUP_MULTIPLIER,
        estimated_profit_usd=round(profit, 4),
        rush_multiplier=rush,
        rejection_reason=rejection,
    )
    await _persist_evaluation(result, req.platform, req.title)

    logger.info(
        "Evaluation %s: %s complexity=%s tier=%s cost=$%.4f quote=$%.2f viable=%s",
        evaluation_id, req.title[:50], complexity, tier,
        cost_est.estimated_cost_usd, quoted, viable,
    )
    return result


async def _persist_evaluation(result: EvaluationResult, platform: str, title: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO evaluations (evaluation_id, platform, title, complexity, tier, model, estimated_cost, quoted_price, viable, rejection_reason) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (result.evaluation_id, platform, title, result.complexity, result.recommended_tier,
             result.recommended_model, result.estimated_cost_usd, result.quoted_price_usd,
             1 if result.viable else 0, result.rejection_reason),
        )
        await db.commit()


@app.get("/history")
async def history(limit: int = 50):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM evaluations ORDER BY created_at DESC LIMIT ?", (limit,)
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


@app.get("/pricing")
async def pricing():
    return {
        "markup_multiplier": MARKUP_MULTIPLIER,
        "minimum_quote_usd": MINIMUM_QUOTE_USD,
        "model_tiers": {k: {"model": v["model"], "label": v["label"],
                            "input_cost_per_m": v["input_cost_per_m"],
                            "output_cost_per_m": v["output_cost_per_m"]}
                        for k, v in MODEL_TIERS.items()},
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8800)
