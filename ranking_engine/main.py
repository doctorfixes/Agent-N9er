import logging

from fastapi import FastAPI, HTTPException

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ranking")

app = FastAPI(title="Verixio Ranking Engine")

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
