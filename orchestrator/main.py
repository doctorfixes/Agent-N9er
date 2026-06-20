import os
import sys
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import aiosqlite
import httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared.security import (
    RequestIDMiddleware, RateLimitMiddleware, APIKeyMiddleware,
    get_service_headers,
)
from shared.task_taxonomy import get_specialization_boost, list_categories
from shared.config import (
    MAX_RETRIES, RETRY_BACKOFF, DEFAULT_TIMEOUT, PIPELINE_TIMEOUT,
    QUICK_TIMEOUT, RATE_LIMIT_MAX_REQUESTS, RATE_LIMIT_WINDOW_SECONDS,
    CORS_ORIGINS,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("orchestrator")

NORMALIZATION_URL = os.getenv("NORMALIZATION_URL", "http://localhost:8100")
RANKING_URL = os.getenv("RANKING_URL", "http://localhost:8200")
MARKETPLACE_URL = os.getenv("MARKETPLACE_URL", "http://localhost:8300")
EXECUTION_URL = os.getenv("EXECUTION_URL", "http://localhost:8400")
REPUTATION_URL = os.getenv("REPUTATION_URL", "http://localhost:8500")
RECURRING_URL = os.getenv("RECURRING_URL", "http://localhost:8600")

DB_PATH = os.getenv("ORCHESTRATOR_DB_PATH", "/data/orchestrator.db")

registered_agents = {}
_agents_lock = asyncio.Lock()


class AgentRegisterRequest(BaseModel):
    agent_id: str
    profile: str = "unknown"
    specialization: str = "generalist"
    price: float = 0.1
    eta_minutes: int = 5
    confidence: float = 0.5


class PipelineRequest(BaseModel):
    objective: str = ""
    source: str = "manual"
    inputs: dict = {}


async def _init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS agents (
                agent_id TEXT PRIMARY KEY,
                profile TEXT DEFAULT 'unknown',
                specialization TEXT DEFAULT 'generalist',
                price REAL DEFAULT 0.1,
                eta_minutes INTEGER DEFAULT 5,
                confidence REAL DEFAULT 0.5
            )
        """)
        await db.commit()


async def _load_agents():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM agents")
        rows = await cursor.fetchall()
        for row in rows:
            registered_agents[row["agent_id"]] = {
                "agent_id": row["agent_id"],
                "profile": row["profile"],
                "specialization": row["specialization"],
                "price": row["price"],
                "eta_minutes": row["eta_minutes"],
                "confidence": row["confidence"],
            }
    logger.info("Loaded %d agents from database", len(registered_agents))


async def _persist_agent(agent_data: dict):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO agents (agent_id, profile, specialization, price, eta_minutes, confidence) VALUES (?, ?, ?, ?, ?, ?)",
            (agent_data["agent_id"], agent_data["profile"], agent_data["specialization"],
             agent_data["price"], agent_data["eta_minutes"], agent_data["confidence"]),
        )
        await db.commit()


@asynccontextmanager
async def lifespan(app):
    await _init_db()
    await _load_agents()
    yield


def _svc_headers(request=None):
    headers = get_service_headers()
    if request and hasattr(request, "state") and hasattr(request.state, "request_id"):
        headers["X-Request-ID"] = request.state.request_id
    return headers


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


app = FastAPI(title="Verixio Orchestrator", lifespan=lifespan)

app.add_middleware(RequestIDMiddleware)
app.add_middleware(RateLimitMiddleware, max_requests=RATE_LIMIT_MAX_REQUESTS, window_seconds=RATE_LIMIT_WINDOW_SECONDS)
app.add_middleware(APIKeyMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    async with _agents_lock:
        count = len(registered_agents)
    return {"ok": 1, "service": "orchestrator", "registered_agents": count}


@app.post("/agents/register")
async def register_agent(agent: AgentRegisterRequest):
    agent_data = agent.model_dump()
    async with _agents_lock:
        registered_agents[agent.agent_id] = agent_data
    await _persist_agent(agent_data)
    try:
        async with httpx.AsyncClient(timeout=QUICK_TIMEOUT) as client:
            await client.post(
                f"{REPUTATION_URL}/register",
                json={"agent_id": agent.agent_id, "profile": agent.profile},
                headers=_svc_headers(),
            )
    except httpx.RequestError:
        pass
    logger.info("Registered agent %s (%s, specialization=%s)",
                agent.agent_id, agent.profile, agent.specialization)
    return {"ok": 1, "agent_id": agent.agent_id}


@app.get("/agents")
async def list_agents():
    async with _agents_lock:
        return dict(registered_agents)


@app.get("/task-categories")
async def task_categories(tier: str = None):
    return list_categories(tier)


@app.post("/pipeline")
async def pipeline(task: dict):
    try:
        svc = _svc_headers()
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            norm_resp = await _retry_post(client, f"{NORMALIZATION_URL}/normalize", json=task, headers=svc)
            normalized = norm_resp.json()

            rank_resp = await _retry_post(client, f"{RANKING_URL}/rank", json=normalized, headers=svc)
            ranked = rank_resp.json()

            publish_payload = {
                "id": ranked["id"],
                "objective": normalized["objective"],
                "priority_score": ranked["priority_score"],
                "inputs": normalized.get("inputs", {}),
                "source": normalized.get("source", "manual"),
            }
            await _retry_post(client, f"{MARKETPLACE_URL}/publish", json=publish_payload, headers=svc)

            logger.info("Task %s published with priority %.2f [%s/%s]",
                        ranked["id"], ranked["priority_score"],
                        normalized.get("category", "?"), normalized.get("tier", "?"))
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
    category = pub_result.get("normalized", {}).get("category", "uncategorized")

    async with _agents_lock:
        agents_snapshot = dict(registered_agents)

    if not agents_snapshot:
        return {**pub_result, "status": "task_published_no_agents",
                "detail": "No agents registered to bid"}

    try:
        svc = _svc_headers()
        async with httpx.AsyncClient(timeout=PIPELINE_TIMEOUT) as client:
            async def _submit_bid(agent_id, agent_info):
                base_confidence = agent_info.get("confidence", 0.5)
                specialization = agent_info.get("specialization", "generalist")
                boost = get_specialization_boost(specialization, category)
                adjusted_confidence = min(1.0, base_confidence + boost)

                bid_payload = {
                    "task_id": task_id,
                    "agent_id": agent_id,
                    "price": agent_info.get("price", 0.1),
                    "eta_minutes": agent_info.get("eta_minutes", 5),
                    "confidence": round(adjusted_confidence, 3),
                }
                try:
                    await client.post(f"{MARKETPLACE_URL}/bid", json=bid_payload, headers=svc)
                except httpx.RequestError:
                    logger.warning("Failed to submit bid for agent %s", agent_id)

            await asyncio.gather(*[
                _submit_bid(aid, ainfo) for aid, ainfo in agents_snapshot.items()
            ])

            award_resp = await _retry_post(client, f"{MARKETPLACE_URL}/award/{task_id}", headers=svc)
            award_data = award_resp.json()
            winner = award_data["winner"]

            exec_resp = await _retry_post(client, f"{EXECUTION_URL}/execute", json={
                "task_id": task_id,
                "agent_id": winner["agent_id"],
                "confidence": winner.get("confidence", 0.5),
            }, headers=svc)
            exec_data = exec_resp.json()

            status = "completed" if exec_data.get("success") else "failed"
            await client.post(
                f"{MARKETPLACE_URL}/complete/{task_id}",
                json={"success": exec_data.get("success", False)},
                headers=svc,
            )

            logger.info("Full pipeline complete for task %s [%s]: %s (agent %s)",
                        task_id, category, status, winner["agent_id"])
            return {
                "status": status,
                "task_id": task_id,
                "category": category,
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
        svc = _svc_headers()
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            tick_resp = await client.get(f"{RECURRING_URL}/tick", headers=svc)
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
