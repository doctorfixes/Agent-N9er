import uuid
import logging

from fastapi import FastAPI
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("normalization")

app = FastAPI(title="Verixio Normalization Service")


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
    objective = task.get("objective", "")
    inputs = task.get("inputs", {})
    source = task.get("source", "manual")

    normalized = {
        "id": task_id,
        "objective": objective,
        "inputs": inputs,
        "source": source,
        "raw": task,
    }
    logger.info("Normalized task %s: %s", task_id, objective[:80])
    return normalized
