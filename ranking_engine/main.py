import os
import sys
import logging

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

AI_SPEED_KEYWORDS = {
    "python": 1.5, "javascript": 1.5, "typescript": 1.5, "react": 1.3,
    "api": 1.5, "script": 1.8, "automation": 2.0, "data": 1.3,
    "scraper": 1.8, "bot": 1.5, "csv": 1.5, "json": 1.5,
    "documentation": 1.5, "test": 1.3, "refactor": 1.5,
    "sql": 1.3, "regex": 1.5, "translate": 1.3, "content": 1.0,
}


@app.get("/health")
async def health():
    return {"ok": 1, "service": "ranking"}


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

    ai_boost = sum(AI_SPEED_KEYWORDS.get(w, 0) for w in words)

    budget_min = task.get("budget_min", 0) or 0
    budget_max = task.get("budget_max", 0) or 0
    budget_boost = 0.0
    if budget_max > 0:
        budget_boost = min(budget_max / 100, 5.0)
        if budget_max >= 500:
            budget_boost += 2.0

    priority_score = round(base_score + keyword_boost + value_boost + tier_boost + ai_boost + budget_boost, 2)

    logger.info("Ranked task %s: score=%.2f (base=%.1f kw=%.1f val=%.1f tier=%.1f ai=%.1f budget=%.1f) category=%s",
                task["id"], priority_score, base_score, keyword_boost, value_boost, tier_boost,
                ai_boost, budget_boost, task.get("category", "unknown"))
    return {
        "id": task["id"],
        "priority_score": priority_score,
        "category": task.get("category"),
        "tier": tier,
        "value_score": round(value_boost, 2),
        "ai_speed_boost": round(ai_boost, 2),
        "budget_boost": round(budget_boost, 2),
    }
