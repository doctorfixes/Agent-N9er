import os
import logging

from fastapi import FastAPI, HTTPException
import httpx

from agent_personalities import (
    SpeedDemon, PrecisionSpecialist, BalancedGeneralist,
    ResearchAnalyst, ContentCreator,
)
from runner import run
from task_generator import gen, TASK_TEMPLATES

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("simulation")

app = FastAPI(title="Agent N9er Simulation Engine")

ORCHESTRATOR_URL = os.getenv("ORCHESTRATOR_URL", "http://localhost:9000")
MARKETPLACE_URL = os.getenv("MARKETPLACE_URL", "http://localhost:8300")
EXECUTION_URL = os.getenv("EXECUTION_URL", "http://localhost:8700")
REPUTATION_URL = os.getenv("REPUTATION_URL", "http://localhost:8500")


def create_agents():
    return [
        SpeedDemon("speed"),
        PrecisionSpecialist("precision"),
        BalancedGeneralist("balanced"),
        ResearchAnalyst("research"),
        ContentCreator("content"),
    ]


@app.get("/health")
async def health():
    return {"ok": 1, "service": "simulation"}


@app.get("/task-categories")
async def task_categories():
    return {cat: len(templates) for cat, templates in TASK_TEMPLATES.items()}


@app.get("/run")
async def run_simulation(n: int = 10, category: str = None):
    agents = create_agents()
    results = run(agents, n=n, category=category)
    agent_stats = [a.stats() for a in agents]
    logger.info("Local simulation complete: %d rounds (category=%s)", n, category)
    return {
        "mode": "local",
        "results": results,
        "agent_stats": agent_stats,
        "rounds": n,
        "category": category,
    }


@app.post("/run/live")
async def run_live_simulation(n: int = 5, category: str = None):
    agents = create_agents()

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            for agent in agents:
                bid_data = agent.bid({"objective": "calibration task"})
                await client.post(f"{ORCHESTRATOR_URL}/agents/register", json={
                    "agent_id": agent.agent_id,
                    "profile": agent.profile,
                    "specialization": agent.specialization,
                    "price": bid_data["price"],
                    "eta_minutes": bid_data["eta_minutes"],
                    "confidence": bid_data["confidence"],
                })
            logger.info("Registered %d agents with orchestrator", len(agents))
    except httpx.RequestError as e:
        raise HTTPException(status_code=503, detail=f"Orchestrator unreachable: {e}")

    results = []
    async with httpx.AsyncClient(timeout=30.0) as client:
        for i in range(n):
            task = gen(category=category)
            try:
                resp = await client.post(
                    f"{ORCHESTRATOR_URL}/pipeline/full", json=task
                )
                resp.raise_for_status()
                result = resp.json()
                result["round"] = i + 1
                results.append(result)
                logger.info("Live round %d: task %s -> %s",
                            i + 1, task["id"][:8], result.get("status"))
            except httpx.HTTPStatusError as e:
                results.append({"round": i + 1, "error": str(e), "task": task})
            except httpx.RequestError as e:
                results.append({"round": i + 1, "error": str(e), "task": task})

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            ledger_resp = await client.get(f"{REPUTATION_URL}/ledger")
            agent_stats = ledger_resp.json()
    except httpx.RequestError:
        agent_stats = {}

    logger.info("Live simulation complete: %d rounds", n)
    return {
        "mode": "live",
        "rounds": n,
        "category": category,
        "results": results,
        "agent_stats": agent_stats,
    }
