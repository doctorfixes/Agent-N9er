import logging

from fastapi import FastAPI

from agent_personalities import SpeedDemon, PrecisionSpecialist, BalancedGeneralist
from runner import run

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("simulation")

app = FastAPI(title="Verixio Simulation Engine")


@app.get("/health")
async def health():
    return {"ok": 1, "service": "simulation"}


@app.get("/run")
async def run_simulation(n: int = 10):
    agents = [
        SpeedDemon("speed"),
        PrecisionSpecialist("precision"),
        BalancedGeneralist("balanced"),
    ]
    results = run(agents, n=n)
    agent_stats = [a.stats() for a in agents]
    logger.info("Simulation complete: %d rounds, %d agents", n, len(agents))
    return {
        "results": results,
        "agent_stats": agent_stats,
        "rounds": n,
    }
