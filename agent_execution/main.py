import os
import logging
import random
import asyncio

from fastapi import FastAPI, HTTPException
import httpx

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("execution")

app = FastAPI(title="Verixio Agent Execution")

REPUTATION_URL = os.getenv("REPUTATION_URL", "http://localhost:8500")

executions = []


@app.get("/health")
async def health():
    return {"ok": 1, "service": "execution", "total_executions": len(executions)}


@app.post("/execute")
async def execute(request: dict):
    agent_id = request.get("agent_id")
    task_id = request.get("task_id")
    confidence = request.get("confidence", 0.5)

    if not agent_id or not task_id:
        raise HTTPException(status_code=422, detail="Missing agent_id or task_id")

    success = random.random() < confidence
    duration = round(random.uniform(1, 10), 1)

    record = {
        "task_id": task_id,
        "agent_id": agent_id,
        "success": success,
        "duration": duration,
    }
    executions.append(record)

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(f"{REPUTATION_URL}/update", json={
                "agent_id": agent_id,
                "success": success,
            })
    except httpx.RequestError as e:
        logger.warning("Failed to update reputation: %s", e)

    logger.info("Executed task %s by agent %s: success=%s duration=%.1fs",
                task_id, agent_id, success, duration)
    return {"ok": 1, **record}


@app.get("/history")
async def history(agent_id: str = None):
    if agent_id:
        return [e for e in executions if e["agent_id"] == agent_id]
    return executions
