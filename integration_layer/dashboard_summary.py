import os

import httpx

MARKETPLACE_URL = os.getenv("MARKETPLACE_URL", "http://localhost:8300")
REPUTATION_URL = os.getenv("REPUTATION_URL", "http://localhost:8500")


async def summary():
    async with httpx.AsyncClient(timeout=10.0) as client:
        tasks = (await client.get(f"{MARKETPLACE_URL}/feed")).json()
        agents = (await client.get(f"{REPUTATION_URL}/ledger")).json()
        return {"tasks": tasks, "agents": agents}
