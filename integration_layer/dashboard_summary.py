import httpx


async def summary():
    async with httpx.AsyncClient() as client:
        tasks = (await client.get("http://bidding-marketplace:8300/feed")).json()
        agents = (await client.get("http://reputation-ledger:8500/ledger")).json()
        return {"tasks": tasks, "agents": agents}
