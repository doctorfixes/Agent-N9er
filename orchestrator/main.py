import os
import asyncio
import logging

from fastapi import FastAPI, HTTPException
import httpx

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("orchestrator")

NORMALIZATION_URL = os.getenv("NORMALIZATION_URL", "http://localhost:8100")
RANKING_URL = os.getenv("RANKING_URL", "http://localhost:8200")
MARKETPLACE_URL = os.getenv("MARKETPLACE_URL", "http://localhost:8300")
EXECUTION_URL = os.getenv("EXECUTION_URL", "http://localhost:8400")
REPUTATION_URL = os.getenv("REPUTATION_URL", "http://localhost:8500")
RECURRING_URL = os.getenv("RECURRING_URL", "http://localhost:8600")

app = FastAPI(title="Verixio Orchestrator")

registered_agents = {}


@app.get("/health")
async def health():
    return {"ok": 1, "service": "orchestrator", "registered_agents": len(registered_agents)}


@app.post("/agents/register")
async def register_agent(agent: dict):
    agent_id = agent.get("agent_id")
    profile = agent.get("profile", "unknown")
    if not agent_id:
        raise HTTPException(status_code=422, detail="Missing agent_id")
    registered_agents[agent_id] = agent
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(f"{REPUTATION_URL}/register", json={
                "agent_id": agent_id, "profile": profile,
            })
    except httpx.RequestError:
        pass
    logger.info("Registered agent %s (%s)", agent_id, profile)
    return {"ok": 1, "agent_id": agent_id}


@app.get("/agents")
async def list_agents():
    return registered_agents


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
                "source": normalized.get("source", "manual"),
            }
            pub_resp = await client.post(f"{MARKETPLACE_URL}/publish", json=publish_payload)
            pub_resp.raise_for_status()

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
            for agent_id, agent_info in registered_agents.items():
                bid_payload = {
                    "task_id": task_id,
                    "agent_id": agent_id,
                    "price": agent_info.get("price", 0.1),
                    "eta_minutes": agent_info.get("eta_minutes", 5),
                    "confidence": agent_info.get("confidence", 0.5),
                    "profile": agent_info.get("profile", "unknown"),
                }
                try:
                    await client.post(f"{MARKETPLACE_URL}/bid", json=bid_payload)
                except httpx.RequestError:
                    logger.warning("Failed to submit bid for agent %s", agent_id)

            award_resp = await client.post(f"{MARKETPLACE_URL}/award/{task_id}")
            award_resp.raise_for_status()
            award_data = award_resp.json()
            winner = award_data["winner"]

            exec_resp = await client.post(f"{EXECUTION_URL}/execute", json={
                "task_id": task_id,
                "agent_id": winner["agent_id"],
                "confidence": winner.get("confidence", 0.5),
            })
            exec_resp.raise_for_status()
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
