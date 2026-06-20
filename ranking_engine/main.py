import os
import sys
import logging

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared.security import RequestIDMiddleware, ServiceTokenMiddleware

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("ranking")

CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")

app = FastAPI(title="Verixio Ranking Engine")

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


@app.post("/rank")
async def rank(task: dict):
    if "id" not in task:
        raise HTTPException(status_code=422, detail="Missing required field: id")

    objective = task.get("objective", "")
    words = objective.lower().split()

    base_score = min(len(objective) * 0.1, 5.0)
    keyword_boost = sum(KEYWORD_WEIGHTS.get(w, 0) for w in words)
    priority_score = round(base_score + keyword_boost, 2)

    logger.info("Ranked task %s: score=%.2f", task["id"], priority_score)
    return {"id": task["id"], "priority_score": priority_score}
