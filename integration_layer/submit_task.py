import httpx


async def forward_task(task_config: dict):
    async with httpx.AsyncClient() as client:
        await client.post("http://orchestrator:9000/pipeline", json=task_config)
