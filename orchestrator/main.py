import os
import logging

from fastapi import FastAPI, HTTPException
import httpx

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("orchestrator")

app = FastAPI(title="Verixio Orchestrator")

NORMALIZATION_URL = os.getenv("NORMALIZATION_URL", "http://localhost:8100")
RANKING_URL = os.getenv("RANKING_URL", "http://localhost:8200")
MARKETPLACE_URL = os.getenv("MARKETPLACE_URL", "http://localhost:8300")


@app.get("/health")
async def health():
    return {"ok": 1, "service": "orchestrator"}


@app.post("/pipeline")
async def pipeline(task: dict):
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            norm_resp = await client.post(f"{NORMALIZATION_URL}/normalize", json=task)
            norm_resp.raise_for_status()
            normalized = norm_resp.json()

            rank_resp = await client.post(f"{RANKING_URL}/rank", json=normalized)
            rank_resp.raise_for_status()
            ranked = rank_resp.json()

            publish_payload = {
                "id": ranked["id"],
                "objective": normalized["objective"],
                "priority_score": ranked["priority_score"],
                "inputs": normalized.get("inputs", {}),
            }
            pub_resp = await client.post(f"{MARKETPLACE_URL}/publish", json=publish_payload)
            pub_resp.raise_for_status()

            logger.info("Task %s published with priority %.2f", ranked["id"], ranked["priority_score"])
            return {
                "status": "task_published",
                "normalized": normalized,
                "ranked": ranked,
            }
    except httpx.HTTPStatusError as e:
        logger.error("Downstream service error: %s", e)
        raise HTTPException(status_code=502, detail=f"Downstream service error: {e.response.status_code}")
    except httpx.RequestError as e:
        logger.error("Service unreachable: %s", e)
        raise HTTPException(status_code=503, detail=f"Service unreachable: {e}")
