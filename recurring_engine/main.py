import os
import sys
import uuid
import logging

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared.security import RequestIDMiddleware, ServiceTokenMiddleware
from shared.task_taxonomy import list_categories, TaskCategory

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("recurring")

CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")

app = FastAPI(title="Verixio Recurring Engine")

app.add_middleware(RequestIDMiddleware)
app.add_middleware(ServiceTokenMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

rules = []


@app.get("/health")
async def health():
    return {"ok": 1, "service": "recurring", "rule_count": len(rules)}


@app.post("/rules")
async def add_rule(rule: dict):
    if "objective" not in rule:
        raise HTTPException(status_code=422, detail="Missing objective")
    rule["rule_id"] = str(uuid.uuid4())
    rule.setdefault("category", "uncategorized")
    rules.append(rule)
    logger.info("Added rule %s [%s]: %s", rule["rule_id"], rule["category"], rule["objective"][:80])
    return {"ok": 1, "rule": rule}


@app.get("/rules")
async def get_rules():
    return rules


@app.get("/tick")
async def tick():
    generated = []
    for rule in rules:
        task = {
            "id": str(uuid.uuid4()),
            "objective": rule["objective"],
            "source": "recurring",
            "rule_id": rule.get("rule_id"),
            "category": rule.get("category", "uncategorized"),
        }
        generated.append(task)
    if generated:
        logger.info("Tick generated %d tasks from %d rules", len(generated), len(rules))
    return generated


@app.get("/categories")
async def categories():
    return list_categories()
