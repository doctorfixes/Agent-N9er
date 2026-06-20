from fastapi import FastAPI
import httpx

app = FastAPI()


@app.post("/pipeline")
async def pipeline(task: dict):
    async with httpx.AsyncClient() as client:
        normalized = (
            await client.post(
                "http://normalization-service:8100/normalize",
                json=task,
            )
        ).json()
        ranked = (
            await client.post(
                "http://ranking-engine:8200/rank",
                json=normalized,
            )
        ).json()
        await client.post(
            "http://bidding-marketplace:8300/publish",
            json={
                "id": ranked["id"],
                "objective": normalized["objective"],
                "priority_score": ranked["priority_score"],
            },
        )
        return {
            "status": "task_published",
            "normalized": normalized,
            "ranked": ranked,
        }
