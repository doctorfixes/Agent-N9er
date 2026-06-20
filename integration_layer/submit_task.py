import os

import httpx

ORCHESTRATOR_URL = os.getenv("ORCHESTRATOR_URL", "http://localhost:9000")


async def forward_task(task_config: dict):
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(f"{ORCHESTRATOR_URL}/pipeline", json=task_config)
        resp.raise_for_status()
        return resp.json()
