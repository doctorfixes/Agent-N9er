import os
import sys
import asyncio
import logging

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared.security import RequestIDMiddleware, ServiceTokenMiddleware
from shared.task_taxonomy import compute_value_score
from shared.config import CORS_ORIGINS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("ranking")

CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
BILLING_URL = os.getenv("BILLING_URL", "http://localhost:9200")

_profitability_cache: dict = {}
_cache_expires_at: float = 0


app = FastAPI(title="Agent N9er Ranking Engine")

app.add_middleware(RequestIDMiddleware)
app.add_middleware(ServiceTokenMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

KEYWORD_WEIGHTS = {
    "urgent": 2.0,
    "critical": 2.5,
    "important": 1.5,
    "asap": 2.0,
    "bug": 1.8,
    "fix": 1.5,
    "deploy": 1.7,
    "review": 1.0,
}


@app.get("/health")
async def health():
    return {"ok": 1, "service": "ranking"}


async def _get_profitability() -> dict:
    import time
    global _profitability_cache, _cache_expires_at
    now = time.time()
    if _profitability_cache and now < _cache_expires_at:
        return _profitability_cache
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{BILLING_URL}/profitability")
            resp.raise_for_status()
            _profitability_cache = resp.json()
            _cache_expires_at = now + 300
    except Exception as e:
        logger.debug("Profitability fetch failed (using cache): %s", e)
    return _profitability_cache


@app.post("/rank")
async def rank(task: dict):
    if "id" not in task:
        raise HTTPException(status_code=422, detail="Missing required field: id")

    objective = task.get("objective", "")
    words = objective.lower().split()

    base_score = min(len(objective) * 0.1, 5.0)
    keyword_boost = sum(KEYWORD_WEIGHTS.get(w, 0) for w in words)

    leverage_score = task.get("leverage_score", 1.0)
    cost_tier = task.get("cost_tier", "mid")
    value_boost = compute_value_score(leverage_score, cost_tier) * 0.5

    tier = task.get("tier", "")
    tier_boost = {"highest_leverage": 3.0, "high_roi": 2.0, "operational": 1.0, "creative_technical": 0.5}.get(tier, 0)

    # Profitability boost: platforms with higher historical margins get priority
    profit_boost = 0.0
    platform = task.get("platform", task.get("source", ""))
    if platform:
        profitability = await _get_profitability()
        platform_data = profitability.get(platform, {})
        avg_profit = platform_data.get("avg_profit_usd", 0)
        margin = platform_data.get("margin_pct", 0)
        if avg_profit > 0:
            profit_boost = min(avg_profit * 0.05, 5.0)
        if margin > 80:
            profit_boost += 2.0
        elif margin > 50:
            profit_boost += 1.0

    # Budget signal: tasks with known budgets get a boost proportional to value
    budget = task.get("budget_max", 0)
    budget_boost = 0.0
    if budget > 0:
        budget_boost = min(budget * 0.01, 5.0)

    priority_score = round(base_score + keyword_boost + value_boost + tier_boost + profit_boost + budget_boost, 2)

    logger.info("Ranked task %s: score=%.2f (base=%.1f kw=%.1f val=%.1f tier=%.1f profit=%.1f budget=%.1f) category=%s",
                task["id"], priority_score, base_score, keyword_boost, value_boost, tier_boost,
                profit_boost, budget_boost, task.get("category", "unknown"))
    return {
        "id": task["id"],
        "priority_score": priority_score,
        "category": task.get("category"),
        "tier": tier,
        "value_score": round(value_boost, 2),
        "profit_boost": round(profit_boost, 2),
        "budget_boost": round(budget_boost, 2),
    }
