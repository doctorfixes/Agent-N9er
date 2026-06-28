import os
import sys
import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

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
    DEFAULT_TIMEOUT, PIPELINE_TIMEOUT,
    QUICK_TIMEOUT, RATE_LIMIT_MAX_REQUESTS, RATE_LIMIT_WINDOW_SECONDS,
    CORS_ORIGINS,
)
from shared.retry import retry_post

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("orchestrator")

NORMALIZATION_URL = os.getenv("NORMALIZATION_URL", "http://localhost:8100")
RANKING_URL = os.getenv("RANKING_URL", "http://localhost:8200")
MARKETPLACE_URL = os.getenv("MARKETPLACE_URL", "http://localhost:8300")
EXECUTION_URL = os.getenv("EXECUTION_URL", "http://localhost:8400")
REPUTATION_URL = os.getenv("REPUTATION_URL", "http://localhost:8500")
RECURRING_URL = os.getenv("RECURRING_URL", "http://localhost:8600")
PROSPECTOR_URL = os.getenv("PROSPECTOR_URL", "http://localhost:8900")
EVALUATOR_URL = os.getenv("EVALUATOR_URL", "http://localhost:8800")
BILLING_URL = os.getenv("BILLING_URL", "http://localhost:9200")

FREELANCER_AUTO_BID = os.getenv("FREELANCER_AUTO_BID", "true").lower() == "true"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")


async def telegram_notify(message: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json={"chat_id": TELEGRAM_CHAT_ID, "text": message},
            )
            if resp.status_code != 200:
                logger.warning("Telegram send failed (%d): %s", resp.status_code, resp.text)
    except Exception as e:
        logger.warning("Telegram notification failed: %s", e)

DB_PATH = os.getenv("ORCHESTRATOR_DB_PATH", "/data/orchestrator.db")

SCAN_INTERVAL = int(os.getenv("SCAN_INTERVAL_SECONDS", "3600"))
SCAN_PLATFORMS = os.getenv("SCAN_PLATFORMS", "upwork,github_bounties,freelancer,algora,topcoder").split(",")
AUTO_SCAN_ENABLED = os.getenv("AUTO_SCAN_ENABLED", "false").lower() == "true"
SCAN_RATE_DELAY = int(os.getenv("SCAN_RATE_DELAY_SECONDS", "5"))

app = FastAPI(title="Agent N9er Orchestrator")

app.add_middleware(RequestIDMiddleware)
app.add_middleware(RateLimitMiddleware, max_requests=200, window_seconds=60)
app.add_middleware(APIKeyMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

registered_agents = {}
_agents_lock = asyncio.Lock()
_scan_task: asyncio.Task | None = None
_scan_state = {
    "running": False,
    "last_scan_at": None,
    "total_scans": 0,
    "total_discovered": 0,
    "last_results": {},
}


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


async def _scan_loop():
    while True:
        try:
            await asyncio.sleep(SCAN_INTERVAL)
            await _run_scan_cycle()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error("Scan loop error: %s", e)
            await asyncio.sleep(60)


async def _run_scan_cycle():
    _scan_state["running"] = True
    svc = _svc_headers()
    results = {}
    total_new = 0

    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        for platform in SCAN_PLATFORMS:
            try:
                resp = await client.post(
                    f"{PROSPECTOR_URL}/scan",
                    json={"platform": platform, "max_results": 20},
                    headers=svc,
                )
                resp.raise_for_status()
                data = resp.json()
                results[platform] = {"discovered": data.get("discovered", 0), "new": data.get("new", 0)}
                total_new += data.get("new", 0)
            except (httpx.RequestError, httpx.HTTPStatusError) as e:
                results[platform] = {"error": str(e)}
                logger.warning("Scan failed for %s: %s", platform, e)
            await asyncio.sleep(SCAN_RATE_DELAY)

    _scan_state["running"] = False
    _scan_state["last_scan_at"] = datetime.now(timezone.utc).isoformat()
    _scan_state["total_scans"] += 1
    _scan_state["total_discovered"] += total_new
    _scan_state["last_results"] = results

    logger.info("Scan cycle complete: %d platforms, %d new prospects", len(SCAN_PLATFORMS), total_new)
    if total_new > 0:
        await telegram_notify(
            f"SCAN COMPLETE\n"
            f"New prospects: {total_new}\n"
            f"Platforms: {', '.join(SCAN_PLATFORMS)}"
        )
    return results


@asynccontextmanager
async def lifespan(app):
    global _scan_task
    await _init_db()
    await _load_agents()
    if AUTO_SCAN_ENABLED:
        _scan_task = asyncio.create_task(_scan_loop())
        logger.info("Auto-scan enabled: interval=%ds, platforms=%s", SCAN_INTERVAL, SCAN_PLATFORMS)
    yield
    if _scan_task:
        _scan_task.cancel()
        try:
            await _scan_task
        except asyncio.CancelledError:
            pass


def _svc_headers(request=None):
    headers = get_service_headers()
    if request and hasattr(request, "state") and hasattr(request.state, "request_id"):
        headers["X-Request-ID"] = request.state.request_id
    return headers


app = FastAPI(title="Agent N9er Orchestrator", lifespan=lifespan)

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
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute("SELECT COUNT(*) FROM agents")
            db_count = (await cursor.fetchone())[0]
        return {"ok": 1, "service": "orchestrator", "registered_agents": count, "db_agents": db_count}
    except Exception:
        return {"ok": 0, "service": "orchestrator", "error": "db_unreachable"}


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


@app.get("/scan/status")
async def scan_status():
    return {
        "auto_scan_enabled": AUTO_SCAN_ENABLED,
        "scan_interval_seconds": SCAN_INTERVAL,
        "platforms": SCAN_PLATFORMS,
        **_scan_state,
    }


@app.post("/scan/trigger")
async def trigger_scan():
    if _scan_state["running"]:
        return {"ok": 0, "detail": "Scan already in progress"}
    results = await _run_scan_cycle()
    return {"ok": 1, "results": results, "scan_state": _scan_state}


@app.post("/pipeline")
async def pipeline(task: dict):
    try:
        svc = _svc_headers()
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            norm_resp = await retry_post(client, f"{NORMALIZATION_URL}/normalize", json=task, headers=svc)
            normalized = norm_resp.json()

            rank_resp = await retry_post(client, f"{RANKING_URL}/rank", json=normalized, headers=svc)
            ranked = rank_resp.json()

            publish_payload = {
                "id": ranked["id"],
                "objective": normalized["objective"],
                "priority_score": ranked["priority_score"],
                "inputs": normalized.get("inputs", {}),
                "source": normalized.get("source", "manual"),
            }
            await retry_post(client, f"{MARKETPLACE_URL}/publish", json=publish_payload, headers=svc)

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

                priority = pub_result.get("ranked", {}).get("priority_score", 0)
                priority_boost = min(0.1, priority / 100)

                adjusted_confidence = min(0.95, base_confidence + boost + priority_boost)

                base_price = agent_info.get("price", 0.1)
                if adjusted_confidence > 0.8:
                    price = base_price * 0.9
                else:
                    price = base_price

                bid_payload = {
                    "task_id": task_id,
                    "agent_id": agent_id,
                    "price": round(price, 4),
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

            award_resp = await retry_post(client, f"{MARKETPLACE_URL}/award/{task_id}", headers=svc)
            award_data = award_resp.json()
            winner = award_data["winner"]

            exec_resp = await retry_post(client, f"{EXECUTION_URL}/execute", json={
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


class RevenuePipelineRequest(BaseModel):
    platform: str = "upwork"
    query: str = ""
    category: str = ""
    max_results: int = 10
    auto_execute: bool = True
    client_email: str = ""


@app.post("/revenue-pipeline")
async def revenue_pipeline(req: RevenuePipelineRequest):
    """End-to-end: scan → evaluate → execute → invoice."""
    svc = _svc_headers()
    results = {
        "platform": req.platform,
        "scanned": 0,
        "evaluated": 0,
        "approved": 0,
        "executed": 0,
        "invoiced": 0,
        "total_quoted": 0,
        "total_cost": 0,
        "prospects": [],
    }

    try:
        async with httpx.AsyncClient(timeout=PIPELINE_TIMEOUT) as client:
            # 1. Scan for prospects
            scan_resp = await client.post(
                f"{PROSPECTOR_URL}/scan",
                json={"platform": req.platform, "query": req.query,
                      "category": req.category, "max_results": req.max_results},
                headers=svc,
            )
            scan_resp.raise_for_status()
            scan_data = scan_resp.json()
            results["scanned"] = scan_data.get("discovered", 0)

            # 2. Fetch new prospects and evaluate each
            prospects_resp = await client.get(
                f"{PROSPECTOR_URL}/prospects",
                params={"status": "discovered", "platform": req.platform, "limit": req.max_results},
                headers=svc,
            )
            prospects_resp.raise_for_status()
            prospects = prospects_resp.json()

            for prospect in prospects:
                pid = prospect["id"]
                prospect_result = {"id": pid, "title": prospect["title"], "status": "discovered"}

                # Evaluate
                try:
                    eval_resp = await client.post(
                        f"{PROSPECTOR_URL}/prospects/{pid}/evaluate",
                        headers=svc,
                    )
                    eval_resp.raise_for_status()
                    eval_data = eval_resp.json()
                    results["evaluated"] += 1

                    if eval_data.get("status") != "approved":
                        prospect_result["status"] = "rejected"
                        prospect_result["reason"] = eval_data.get("evaluation", {}).get("rejection_reason", "")
                        results["prospects"].append(prospect_result)
                        continue

                    results["approved"] += 1
                    evaluation = eval_data.get("evaluation", {})
                    quoted = evaluation.get("quoted_price_usd", 0)
                    cost = evaluation.get("estimated_cost_usd", 0)
                    results["total_quoted"] += quoted
                    results["total_cost"] += cost
                    prospect_result["quoted_price"] = quoted
                    prospect_result["estimated_cost"] = cost
                    prospect_result["complexity"] = evaluation.get("complexity", "")

                    # 2b. Auto-bid on Freelancer prospects
                    if prospect["platform"] == "freelancer" and FREELANCER_AUTO_BID and quoted > 0:
                        try:
                            proposal_text = ""
                            try:
                                prop_resp = await client.post(
                                    f"{EXECUTION_URL}/proposal",
                                    json={
                                        "title": prospect.get("title", ""),
                                        "description": prospect.get("description", ""),
                                        "skills": prospect.get("skills", ""),
                                        "platform": "freelancer",
                                        "budget_max": prospect.get("budget_max", 0),
                                    },
                                    headers=svc,
                                    timeout=30.0,
                                )
                                if prop_resp.status_code == 200:
                                    prop_data = prop_resp.json()
                                    if prop_data.get("ok"):
                                        proposal_text = prop_data.get("proposal", "")
                            except Exception as pe:
                                logger.warning("Proposal generation failed for %s: %s", pid[:8], pe)

                            bid_resp = await client.post(
                                f"{PROSPECTOR_URL}/freelancer/bid",
                                json={
                                    "prospect_id": pid,
                                    "bid_amount": quoted,
                                    "period": 7 if evaluation.get("complexity") in ("simple", "trivial", "moderate") else 14,
                                    "milestone_percentage": 100.0,
                                    "description": proposal_text,
                                },
                                headers=svc,
                            )
                            if bid_resp.status_code == 200:
                                bid_data = bid_resp.json()
                                prospect_result["freelancer_bid_id"] = bid_data.get("bid_id")
                                prospect_result["status"] = "applied"
                                logger.info("Auto-bid on Freelancer project %s: $%.2f", pid[:8], quoted)
                                await telegram_notify(
                                    f"BID PLACED\n"
                                    f"Project: {prospect.get('title', 'Unknown')}\n"
                                    f"Amount: ${quoted:.2f}\n"
                                    f"Bid ID: {bid_data.get('bid_id')}\n"
                                    f"URL: {prospect.get('url', '')}"
                                )
                            else:
                                logger.warning("Freelancer auto-bid failed for %s: %s", pid[:8], bid_resp.text)
                        except httpx.RequestError as e:
                            logger.warning("Freelancer auto-bid request failed for %s: %s", pid[:8], e)

                    # 3. Execute if auto_execute
                    if req.auto_execute:
                        exec_resp = await client.post(
                            f"{EXECUTION_URL}/execute",
                            json={
                                "task_id": pid,
                                "agent_id": "agent-n9er-primary",
                                "confidence": 0.85,
                                "objective": prospect["title"],
                                "description": prospect.get("description", ""),
                                "complexity": evaluation.get("complexity", "moderate"),
                                "tier": evaluation.get("recommended_tier", ""),
                            },
                            headers=svc,
                        )
                        exec_resp.raise_for_status()
                        exec_data = exec_resp.json()

                        if exec_data.get("success"):
                            results["executed"] += 1
                            prospect_result["status"] = "executed"
                            prospect_result["execution"] = {
                                "mode": exec_data.get("mode"),
                                "cost_usd": exec_data.get("cost_usd", 0),
                                "duration": exec_data.get("duration"),
                            }

                            # Update prospect status
                            await client.patch(
                                f"{PROSPECTOR_URL}/prospects/{pid}",
                                json={"status": "delivered"},
                                headers=svc,
                            )

                            # 4. Create invoice
                            if req.client_email or prospect.get("client_email"):
                                inv_resp = await client.post(
                                    f"{BILLING_URL}/invoices",
                                    json={
                                        "prospect_id": pid,
                                        "client_email": req.client_email or prospect.get("client_email", ""),
                                        "description": prospect["title"],
                                        "amount_usd": quoted,
                                        "token_cost_usd": exec_data.get("cost_usd", cost),
                                        "platform": req.platform,
                                    },
                                    headers=svc,
                                )
                                if inv_resp.status_code == 200:
                                    results["invoiced"] += 1
                                    prospect_result["invoice_id"] = inv_resp.json().get("invoice_id")
                        else:
                            prospect_result["status"] = "execution_failed"
                    else:
                        prospect_result["status"] = "approved"

                except httpx.RequestError as e:
                    prospect_result["status"] = "error"
                    prospect_result["error"] = str(e)

                results["prospects"].append(prospect_result)

    except httpx.RequestError as e:
        raise HTTPException(status_code=503, detail=f"Pipeline service unreachable: {e}")

    results["total_quoted"] = round(results["total_quoted"], 2)
    results["total_cost"] = round(results["total_cost"], 4)
    results["estimated_profit"] = round(results["total_quoted"] - results["total_cost"], 2)

    logger.info(
        "Revenue pipeline: scanned=%d evaluated=%d approved=%d executed=%d invoiced=%d profit=$%.2f",
        results["scanned"], results["evaluated"], results["approved"],
        results["executed"], results["invoiced"], results["estimated_profit"],
    )
    return results
