import os
import asyncio
import logging

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("orchestrator")

NORMALIZATION_URL = os.getenv("NORMALIZATION_URL", "http://localhost:8100")
RANKING_URL = os.getenv("RANKING_URL", "http://localhost:8200")
MARKETPLACE_URL = os.getenv("MARKETPLACE_URL", "http://localhost:8300")
EXECUTION_URL = os.getenv("EXECUTION_URL", "http://localhost:8400")
REPUTATION_URL = os.getenv("REPUTATION_URL", "http://localhost:8500")
RECURRING_URL = os.getenv("RECURRING_URL", "http://localhost:8600")

MAX_RETRIES = 3
RETRY_BACKOFF = 0.3

app = FastAPI(title="Verixio Orchestrator")

registered_agents = {}


class AgentRegisterRequest(BaseModel):
    agent_id: str
    profile: str = "unknown"
    price: float = 0.1
    eta_minutes: int = 5
    confidence: float = 0.5


class PipelineRequest(BaseModel):
    objective: str = ""
    source: str = "manual"
    inputs: dict = {}


async def _retry_post(client: httpx.AsyncClient, url: str, **kwargs):
    last_exc = None
    for attempt in range(MAX_RETRIES):
        try:
            resp = await client.post(url, **kwargs)
            resp.raise_for_status()
            return resp
        except httpx.RequestError as e:
            last_exc = e
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(RETRY_BACKOFF * (2 ** attempt))
                logger.warning("Retry %d for %s: %s", attempt + 1, url, e)
    raise last_exc


@app.get("/health")
async def health():
    return {"ok": 1, "service": "orchestrator", "registered_agents": len(registered_agents)}


@app.post("/agents/register")
async def register_agent(agent: AgentRegisterRequest):
    registered_agents[agent.agent_id] = agent.model_dump()
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(f"{REPUTATION_URL}/register", json={
                "agent_id": agent.agent_id, "profile": agent.profile,
            })
    except httpx.RequestError:
        pass
    logger.info("Registered agent %s (%s)", agent.agent_id, agent.profile)
    return {"ok": 1, "agent_id": agent.agent_id}


@app.get("/agents")
async def list_agents():
    return registered_agents


@app.post("/pipeline")
async def pipeline(task: dict):
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            norm_resp = await _retry_post(client, f"{NORMALIZATION_URL}/normalize", json=task)
            normalized = norm_resp.json()

            rank_resp = await _retry_post(client, f"{RANKING_URL}/rank", json=normalized)
            ranked = rank_resp.json()

            publish_payload = {
                "id": ranked["id"],
                "objective": normalized["objective"],
                "priority_score": ranked["priority_score"],
                "inputs": normalized.get("inputs", {}),
                "source": normalized.get("source", "manual"),
            }
            await _retry_post(client, f"{MARKETPLACE_URL}/publish", json=publish_payload)

            logger.info("Task %s published with priority %.2f", ranked["id"], ranked["priority_score"])
            return {
                "status": "task_published",
                "task_id": ranked["id"],
                "normalized": normalized,
                "ranked": ranked,
            }
    except httpx.HTTPStatusError as e:
        logger.error("Downstream service error: %s", e)
        raise HTTPException(status_code=502, detail=f"Downstream service error: {e.response.status_code}")
    except httpx.RequestError as e:
        logger.error("Service unreachable: %s", e)
        raise HTTPException(status_code=503, detail=f"Service unreachable: {e}")


@app.post("/pipeline/full")
async def full_pipeline(task: dict):
    pub_result = await pipeline(task)
    task_id = pub_result["task_id"]

    if not registered_agents:
        return {**pub_result, "status": "task_published_no_agents",
                "detail": "No agents registered to bid"}

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            async def _submit_bid(agent_id, agent_info):
                bid_payload = {
                    "task_id": task_id,
                    "agent_id": agent_id,
                    "price": agent_info.get("price", 0.1),
                    "eta_minutes": agent_info.get("eta_minutes", 5),
                    "confidence": agent_info.get("confidence", 0.5),
                }
                try:
                    await client.post(f"{MARKETPLACE_URL}/bid", json=bid_payload)
                except httpx.RequestError:
                    logger.warning("Failed to submit bid for agent %s", agent_id)

            await asyncio.gather(*[
                _submit_bid(aid, ainfo) for aid, ainfo in registered_agents.items()
            ])

            award_resp = await _retry_post(client, f"{MARKETPLACE_URL}/award/{task_id}")
            award_data = award_resp.json()
            winner = award_data["winner"]

            exec_resp = await _retry_post(client, f"{EXECUTION_URL}/execute", json={
                "task_id": task_id,
                "agent_id": winner["agent_id"],
                "confidence": winner.get("confidence", 0.5),
            })
            exec_data = exec_resp.json()

            status = "completed" if exec_data.get("success") else "failed"
            await client.post(f"{MARKETPLACE_URL}/complete/{task_id}",
                              json={"success": exec_data.get("success", False)})

            logger.info("Full pipeline complete for task %s: %s (agent %s)",
                        task_id, status, winner["agent_id"])
            return {
                "status": status,
                "task_id": task_id,
                "winner": winner,
                "execution": exec_data,
            }

    except httpx.HTTPStatusError as e:
        logger.error("Pipeline stage failed: %s", e)
        raise HTTPException(status_code=502, detail=str(e))
    except httpx.RequestError as e:
        logger.error("Service unreachable during pipeline: %s", e)
        raise HTTPException(status_code=503, detail=str(e))


@app.post("/process-recurring")
async def process_recurring():
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            tick_resp = await client.get(f"{RECURRING_URL}/tick")
            tick_resp.raise_for_status()
            generated_tasks = tick_resp.json()

        results = []
        for task in generated_tasks:
            try:
                result = await full_pipeline(task)
                results.append(result)
            except HTTPException as e:
                results.append({"task_id": task.get("id"), "error": e.detail})

        logger.info("Processed %d recurring tasks", len(results))
        return {"ok": 1, "processed": len(results), "results": results}

    except httpx.RequestError as e:
        raise HTTPException(status_code=503, detail=f"Recurring engine unreachable: {e}")
