import uuid
import logging

from fastapi import FastAPI, HTTPException

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("recurring")

app = FastAPI(title="Verixio Recurring Engine")

rules = []


@app.get("/health")
async def health():
    return {"ok": 1, "service": "recurring", "rule_count": len(rules)}


@app.post("/rules")
async def add_rule(rule: dict):
    if "objective" not in rule:
        raise HTTPException(status_code=422, detail="Missing objective")
    rule["rule_id"] = str(uuid.uuid4())
    rules.append(rule)
    logger.info("Added rule %s: %s", rule["rule_id"], rule["objective"][:80])
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
        }
        generated.append(task)
    if generated:
        logger.info("Tick generated %d tasks from %d rules", len(generated), len(rules))
    return generated
