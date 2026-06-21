import os
import sys
import uuid
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared.security import RequestIDMiddleware, ServiceTokenMiddleware
from shared.task_taxonomy import classify_task, list_categories
from shared.config import CORS_ORIGINS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("normalization")

CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")


app = FastAPI(title="Agent N9er Normalization Service")

app.add_middleware(RequestIDMiddleware)
app.add_middleware(ServiceTokenMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


class NormalizeRequest(BaseModel):
    objective: str = ""
    inputs: dict = {}
    source: str = "manual"


@app.get("/health")
async def health():
    return {"ok": 1, "service": "normalization"}


@app.post("/normalize")
async def normalize(task: dict):
    task_id = str(uuid.uuid4())
    objective = str(task.get("objective", ""))
    inputs = task.get("inputs", {})
    source = task.get("source", "manual")

    classification = classify_task(objective, inputs)

    normalized = {
        "id": task_id,
        "objective": objective,
        "inputs": inputs,
        "source": source,
        "category": classification["category"],
        "tier": classification["tier"],
        "leverage_score": classification["leverage_score"],
        "cost_tier": classification["cost_tier"],
        "classification": classification,
        "raw": task,
    }
    logger.info("Normalized task %s [%s/%s]: %s",
                task_id, classification["category"], classification["tier"], objective[:80])
    return normalized


@app.get("/categories")
async def get_categories(tier: str = None):
    return list_categories(tier)
