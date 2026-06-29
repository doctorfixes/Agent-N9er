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
from shared.events import (
    emit, subscribe, get_recent_events,
    EVENT_TASK_PUBLISHED, EVENT_TASK_AWARDED,
    EVENT_EXECUTION_COMPLETED, EVENT_EXECUTION_FAILED,
    EVENT_REPUTATION_UPDATED, EVENT_PROSPECT_DISCOVERED,
    EVENT_PROSPECT_APPROVED, EVENT_SCAN_COMPLETED,
    EVENT_AGENT_REGISTERED,
)

os.environ.setdefault("SERVICE_NAME", "orchestrator")

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

DB_PATH = os.getenv("ORCHESTRATOR_DB_PATH", "/data/orchestrator.db")

SCAN_INTERVAL = int(os.getenv("SCAN_INTERVAL_SECONDS", "3600"))
SCAN_PLATFORMS = os.getenv("SCAN_PLATFORMS", "upwork,github_bounties,freelancer,algora,topcoder").split(",")
AUTO_SCAN_ENABLED = os.getenv("AUTO_SCAN_ENABLED", "false").lower() == "true"
SCAN_RATE_DELAY = int(os.getenv("SCAN_RATE_DELAY_SECONDS", "5"))

AUTONOMOUS_MODE = os.getenv("AUTONOMOUS_MODE", "false").lower() == "true"
AUTONOMOUS_INTERVAL = int(os.getenv("AUTONOMOUS_INTERVAL_SECONDS", "300"))
AUTO_APPLY_ENABLED = os.getenv("AUTO_APPLY_ENABLED", "true").lower() == "true"
MAX_PARALLEL_TASKS = int(os.getenv("MAX_PARALLEL_TASKS", "5"))

AGENT_CAPABILITIES = set(
    c.strip() for c in os.getenv(
        "AGENT_CAPABILITIES",
        "coding,writing,research,data_analysis,web_development,automation",
    ).split(",") if c.strip()
)
MAX_DAILY_APPLICATIONS = int(os.getenv("MAX_DAILY_APPLICATIONS", "50"))
REQUIRE_QUALITY_REVIEW = os.getenv("REQUIRE_QUALITY_REVIEW", "true").lower() == "true"
MIN_QUALITY_SCORE = float(os.getenv("MIN_QUALITY_SCORE", "0.6"))

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


_autonomous_task: asyncio.Task | None = None
_autonomous_state = {
    "running": False,
    "cycles_completed": 0,
    "last_cycle_at": None,
    "prospects_applied": 0,
    "prospects_executed": 0,
    "total_revenue_generated": 0.0,
    "daily_applications": 0,
    "daily_applications_date": None,
}


async def _autonomous_loop():
    await asyncio.sleep(10)
    while True:
        try:
            await _run_autonomous_cycle()
            await asyncio.sleep(AUTONOMOUS_INTERVAL)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error("Autonomous loop error: %s", e)
            await asyncio.sleep(60)


async def _run_autonomous_cycle():
    _autonomous_state["running"] = True
    svc = _svc_headers()
    cycle_stats = {"scanned": 0, "evaluated": 0, "applied": 0, "executed": 0, "invoiced": 0}

    async with httpx.AsyncClient(timeout=PIPELINE_TIMEOUT) as client:
        # Phase 1: Scan all platforms in parallel
        scan_tasks = []
        for platform in SCAN_PLATFORMS:
            scan_tasks.append(_scan_platform(client, platform, svc))
        scan_results = await asyncio.gather(*scan_tasks, return_exceptions=True)
        for r in scan_results:
            if isinstance(r, dict):
                cycle_stats["scanned"] += r.get("new", 0)

        # Phase 2: Evaluate all discovered prospects in parallel
        try:
            resp = await client.get(
                f"{PROSPECTOR_URL}/prospects",
                params={"status": "discovered", "limit": MAX_PARALLEL_TASKS * 2},
                headers=svc,
            )
            resp.raise_for_status()
            discovered = resp.json()

            if discovered:
                eval_tasks = [
                    _evaluate_prospect(client, p["id"], svc)
                    for p in discovered[:MAX_PARALLEL_TASKS]
                ]
                eval_results = await asyncio.gather(*eval_tasks, return_exceptions=True)
                cycle_stats["evaluated"] = sum(
                    1 for r in eval_results if isinstance(r, dict) and r.get("ok")
                )
        except (httpx.RequestError, httpx.HTTPStatusError) as e:
            logger.warning("Autonomous evaluate phase failed: %s", e)

        # Phase 3: Auto-apply to all approved prospects in parallel
        if AUTO_APPLY_ENABLED:
            try:
                resp = await client.get(
                    f"{PROSPECTOR_URL}/prospects",
                    params={"status": "approved", "limit": MAX_PARALLEL_TASKS},
                    headers=svc,
                )
                resp.raise_for_status()
                approved = resp.json()

                if approved:
                    apply_tasks = [
                        _auto_apply_prospect(client, p, svc)
                        for p in approved[:MAX_PARALLEL_TASKS]
                    ]
                    apply_results = await asyncio.gather(*apply_tasks, return_exceptions=True)
                    cycle_stats["applied"] = sum(
                        1 for r in apply_results if isinstance(r, dict) and r.get("ok")
                    )
            except (httpx.RequestError, httpx.HTTPStatusError) as e:
                logger.warning("Autonomous apply phase failed: %s", e)

        # Phase 4: Execute work for hired prospects in parallel
        try:
            resp = await client.get(
                f"{PROSPECTOR_URL}/prospects",
                params={"status": "hired", "limit": MAX_PARALLEL_TASKS},
                headers=svc,
            )
            resp.raise_for_status()
            hired = resp.json()

            if hired:
                exec_tasks = [
                    _execute_prospect(client, p, svc)
                    for p in hired[:MAX_PARALLEL_TASKS]
                ]
                exec_results = await asyncio.gather(*exec_tasks, return_exceptions=True)
                for r in exec_results:
                    if isinstance(r, dict) and r.get("ok"):
                        cycle_stats["executed"] += 1
                        cycle_stats["invoiced"] += 1 if r.get("invoiced") else 0
        except (httpx.RequestError, httpx.HTTPStatusError) as e:
            logger.warning("Autonomous execute phase failed: %s", e)

    _autonomous_state["running"] = False
    _autonomous_state["cycles_completed"] += 1
    _autonomous_state["last_cycle_at"] = datetime.now(timezone.utc).isoformat()
    _autonomous_state["prospects_applied"] += cycle_stats["applied"]
    _autonomous_state["prospects_executed"] += cycle_stats["executed"]

    await emit(EVENT_SCAN_COMPLETED, {
        "autonomous": True, **cycle_stats,
    }, relay=False)

    logger.info(
        "Autonomous cycle #%d: scanned=%d evaluated=%d applied=%d executed=%d invoiced=%d",
        _autonomous_state["cycles_completed"],
        cycle_stats["scanned"], cycle_stats["evaluated"], cycle_stats["applied"],
        cycle_stats["executed"], cycle_stats["invoiced"],
    )
    return cycle_stats


async def _scan_platform(client: httpx.AsyncClient, platform: str, svc: dict) -> dict:
    try:
        resp = await client.post(
            f"{PROSPECTOR_URL}/scan",
            json={"platform": platform, "max_results": 20},
            headers=svc,
        )
        resp.raise_for_status()
        return resp.json()
    except (httpx.RequestError, httpx.HTTPStatusError) as e:
        logger.warning("Scan failed for %s: %s", platform, e)
        return {"error": str(e)}


async def _evaluate_prospect(client: httpx.AsyncClient, prospect_id: str, svc: dict) -> dict:
    try:
        resp = await client.post(
            f"{PROSPECTOR_URL}/prospects/{prospect_id}/evaluate",
            headers=svc,
        )
        resp.raise_for_status()
        return resp.json()
    except (httpx.RequestError, httpx.HTTPStatusError) as e:
        logger.warning("Evaluate failed for %s: %s", prospect_id[:8], e)
        return {"error": str(e)}


async def _auto_apply_prospect(client: httpx.AsyncClient, prospect: dict, svc: dict) -> dict:
    pid = prospect["id"]

    # Daily application limit check
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if _autonomous_state.get("daily_applications_date") != today:
        _autonomous_state["daily_applications"] = 0
        _autonomous_state["daily_applications_date"] = today
    if _autonomous_state["daily_applications"] >= MAX_DAILY_APPLICATIONS:
        logger.info("Skipped prospect %s: daily application limit reached (%d)", pid[:8], MAX_DAILY_APPLICATIONS)
        return {"ok": 0, "prospect_id": pid, "reason": "daily_limit_reached"}

    # Skill-matching gate
    prospect_skills_raw = prospect.get("skills", "")
    if prospect_skills_raw:
        prospect_skills = set(s.strip().lower() for s in prospect_skills_raw.split(",") if s.strip())
        agent_caps_lower = set(c.lower() for c in AGENT_CAPABILITIES)
        if not prospect_skills & agent_caps_lower:
            logger.info("Skipped prospect %s: no matching skills", pid[:8])
            return {"ok": 0, "prospect_id": pid, "reason": "no_skill_match"}

    try:
        proposal_resp = await client.post(
            f"{EXECUTION_URL}/proposal",
            json={
                "prospect_id": pid,
                "title": prospect.get("title", ""),
                "description": prospect.get("description", ""),
                "platform": prospect.get("platform", "unknown"),
                "budget_max": prospect.get("budget_max", 0) or prospect.get("quoted_price", 0),
                "skills": prospect.get("skills", ""),
                "tone": "professional",
            },
            headers=svc,
        )
        proposal_resp.raise_for_status()
        proposal_data = proposal_resp.json()

        await client.patch(
            f"{PROSPECTOR_URL}/prospects/{pid}",
            json={"status": "applied"},
            headers=svc,
        )

        _autonomous_state["daily_applications"] += 1

        logger.info("Auto-applied to prospect %s: %s [%s]",
                     pid[:8], prospect.get("title", "?")[:50], proposal_data.get("mode"))
        return {"ok": 1, "prospect_id": pid, "proposal_mode": proposal_data.get("mode")}

    except (httpx.RequestError, httpx.HTTPStatusError) as e:
        logger.warning("Auto-apply failed for %s: %s", pid[:8], e)
        return {"error": str(e)}


async def _execute_prospect(client: httpx.AsyncClient, prospect: dict, svc: dict) -> dict:
    pid = prospect["id"]
    try:
        await client.patch(
            f"{PROSPECTOR_URL}/prospects/{pid}",
            json={"status": "executing"},
            headers=svc,
        )

        exec_resp = await client.post(
            f"{EXECUTION_URL}/execute",
            json={
                "task_id": pid,
                "agent_id": "agent-n9er-primary",
                "confidence": 0.85,
                "objective": prospect.get("title", ""),
                "description": prospect.get("description", ""),
            },
            headers=svc,
            timeout=120.0,
        )
        exec_resp.raise_for_status()
        exec_data = exec_resp.json()

        invoiced = False
        if exec_data.get("success"):
            # Quality verification gate
            if REQUIRE_QUALITY_REVIEW:
                try:
                    quality_resp = await client.post(
                        f"{EVALUATOR_URL}/evaluate-output",
                        json={
                            "task_id": pid,
                            "title": prospect.get("title", ""),
                            "description": prospect.get("description", ""),
                            "output_preview": exec_data.get("output_preview", ""),
                        },
                        headers=svc,
                        timeout=30.0,
                    )
                    quality_data = quality_resp.json()
                    quality_score = quality_data.get("quality_score", 0)
                except Exception:
                    logger.warning("Quality check unreachable for %s, marking review_needed", pid[:8])
                    quality_score = 0

                if quality_score < MIN_QUALITY_SCORE:
                    await client.patch(
                        f"{PROSPECTOR_URL}/prospects/{pid}",
                        json={"status": "review_needed"},
                        headers=svc,
                    )
                    return {"ok": 1, "prospect_id": pid, "invoiced": False,
                            "quality_score": quality_score, "needs_review": True}

            await client.patch(
                f"{PROSPECTOR_URL}/prospects/{pid}",
                json={"status": "delivered"},
                headers=svc,
            )

            quoted = prospect.get("quoted_price", 0) or prospect.get("budget_max", 0)
            if quoted > 0:
                try:
                    await client.post(
                        f"{BILLING_URL}/invoices",
                        json={
                            "prospect_id": pid,
                            "client_email": prospect.get("client_email", ""),
                            "description": prospect.get("title", ""),
                            "amount_usd": quoted,
                            "token_cost_usd": exec_data.get("cost_usd", 0),
                            "platform": prospect.get("platform", ""),
                        },
                        headers=svc,
                    )
                    invoiced = True
                except (httpx.RequestError, httpx.HTTPStatusError):
                    logger.warning("Invoice creation failed for %s", pid[:8])

            return {"ok": 1, "prospect_id": pid, "invoiced": invoiced}
        else:
            await client.patch(
                f"{PROSPECTOR_URL}/prospects/{pid}",
                json={"status": "approved"},
                headers=svc,
            )
            return {"ok": 0, "prospect_id": pid, "reason": "execution_failed"}

    except (httpx.RequestError, httpx.HTTPStatusError) as e:
        logger.warning("Execute failed for %s: %s", pid[:8], e)
        return {"error": str(e)}


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
    return results


@asynccontextmanager
async def lifespan(app):
    global _scan_task, _autonomous_task
    await _init_db()
    await _load_agents()
    if AUTO_SCAN_ENABLED:
        _scan_task = asyncio.create_task(_scan_loop())
        logger.info("Auto-scan enabled: interval=%ds, platforms=%s", SCAN_INTERVAL, SCAN_PLATFORMS)
    if AUTONOMOUS_MODE:
        _autonomous_task = asyncio.create_task(_autonomous_loop())
        logger.info("Autonomous mode enabled: interval=%ds, parallel=%d, auto_apply=%s",
                     AUTONOMOUS_INTERVAL, MAX_PARALLEL_TASKS, AUTO_APPLY_ENABLED)
    yield
    for task in [_scan_task, _autonomous_task]:
        if task:
            task.cancel()
            try:
                await task
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

    await emit(EVENT_AGENT_REGISTERED, {
        "agent_id": agent.agent_id,
        "specialization": agent.specialization,
        "profile": agent.profile,
    }, relay=False)

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

            await emit(EVENT_TASK_PUBLISHED, {
                "task_id": ranked["id"],
                "priority_score": ranked["priority_score"],
                "category": normalized.get("category", ""),
                "source": normalized.get("source", "manual"),
            }, relay=False)

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

    await emit(EVENT_SCAN_COMPLETED, {
        "platform": req.platform,
        "scanned": results["scanned"],
        "approved": results["approved"],
        "executed": results["executed"],
        "profit": results["estimated_profit"],
    }, relay=False)

    return results


# ---------------------------------------------------------------------------
# Event relay and feedback loops
# ---------------------------------------------------------------------------

_event_subscribers: dict[str, list[str]] = {}
_pipeline_stats = {
    "events_relayed": 0,
    "feedback_loops_triggered": 0,
    "auto_rescans_triggered": 0,
    "confidence_recalibrations": 0,
}


@app.post("/events/relay")
async def relay_event(event: dict):
    event_type = event.get("type", "")
    _pipeline_stats["events_relayed"] += 1

    for handler in _local_event_handlers.get(event_type, []):
        try:
            await handler(event.get("data", {}))
        except Exception as e:
            logger.error("Relay handler error for %s: %s", event_type, e)

    subscriber_urls = _event_subscribers.get(event_type, []) + _event_subscribers.get("*", [])
    for url in subscriber_urls:
        asyncio.create_task(_forward_event(url, event))

    logger.info("Relayed event %s from %s", event_type, event.get("source", "?"))
    return {"ok": 1}


async def _forward_event(url: str, event: dict):
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(url, json=event, headers=_svc_headers())
    except Exception as e:
        logger.debug("Event forward failed to %s: %s", url, e)


@app.post("/events/subscribe")
async def subscribe_events(payload: dict):
    event_type = payload.get("event_type", "*")
    callback_url = payload.get("callback_url", "")
    if not callback_url:
        raise HTTPException(status_code=422, detail="callback_url required")
    _event_subscribers.setdefault(event_type, [])
    if callback_url not in _event_subscribers[event_type]:
        _event_subscribers[event_type].append(callback_url)
    return {"ok": 1, "subscribed": event_type, "callback_url": callback_url}


@app.get("/events/subscriptions")
async def list_subscriptions():
    return _event_subscribers


@app.get("/events/recent")
async def recent_events(limit: int = 50, event_type: str = None):
    return get_recent_events(limit=limit, event_type=event_type)


@app.get("/events/stats")
async def event_stats():
    return _pipeline_stats


# ---------------------------------------------------------------------------
# Feedback loop handlers — these create the self-reinforcing cycle
# ---------------------------------------------------------------------------

_local_event_handlers: dict[str, list] = {}


def _on_event(event_type: str):
    def decorator(fn):
        _local_event_handlers.setdefault(event_type, []).append(fn)
        return fn
    return decorator


@_on_event(EVENT_EXECUTION_COMPLETED)
async def _on_execution_success(data: dict):
    """When execution succeeds, bump agent confidence in local registry
    so future bids are stronger — a positive feedback loop."""
    agent_id = data.get("agent_id")
    if not agent_id:
        return
    async with _agents_lock:
        agent = registered_agents.get(agent_id)
        if agent:
            old = agent["confidence"]
            agent["confidence"] = min(1.0, old + 0.005)
            _pipeline_stats["confidence_recalibrations"] += 1
            logger.info("Confidence bump: %s %.3f → %.3f (execution success)",
                        agent_id, old, agent["confidence"])


@_on_event(EVENT_EXECUTION_FAILED)
async def _on_execution_failure(data: dict):
    """When execution fails, reduce agent confidence so the marketplace
    naturally routes future work to more reliable agents."""
    agent_id = data.get("agent_id")
    if not agent_id:
        return
    async with _agents_lock:
        agent = registered_agents.get(agent_id)
        if agent:
            old = agent["confidence"]
            agent["confidence"] = max(0.1, old - 0.01)
            _pipeline_stats["confidence_recalibrations"] += 1
            logger.info("Confidence drop: %s %.3f → %.3f (execution failure)",
                        agent_id, old, agent["confidence"])


@_on_event(EVENT_REPUTATION_UPDATED)
async def _on_reputation_change(data: dict):
    """When reputation changes, sync the score back into the local agent
    registry. High-reputation agents win more bids → more executions →
    more reputation data. This is the core momentum cycle."""
    agent_id = data.get("agent_id")
    score = data.get("score")
    if not agent_id or score is None:
        return
    async with _agents_lock:
        agent = registered_agents.get(agent_id)
        if agent:
            agent["confidence"] = round((agent["confidence"] + score) / 2, 4)
            _pipeline_stats["feedback_loops_triggered"] += 1
            logger.info("Reputation sync: %s confidence=%.3f (score=%.3f)",
                        agent_id, agent["confidence"], score)


@_on_event(EVENT_SCAN_COMPLETED)
async def _on_scan_completed(data: dict):
    approved = data.get("approved", 0)
    if approved > 0:
        _pipeline_stats["auto_rescans_triggered"] += 1
        logger.info("Scan momentum: %d approved prospects ready for pipeline", approved)


@_on_event(EVENT_PROSPECT_APPROVED)
async def _on_prospect_approved(data: dict):
    """When a prospect is approved, auto-generate a proposal and apply.
    This closes the gap between evaluation and action."""
    if not AUTO_APPLY_ENABLED:
        return
    prospect_id = data.get("prospect_id")
    if not prospect_id:
        return

    svc = _svc_headers()
    async with httpx.AsyncClient(timeout=PIPELINE_TIMEOUT) as client:
        try:
            resp = await client.get(f"{PROSPECTOR_URL}/prospects/{prospect_id}", headers=svc)
            resp.raise_for_status()
            prospect = resp.json()
            result = await _auto_apply_prospect(client, prospect, svc)
            if result.get("ok"):
                _pipeline_stats["feedback_loops_triggered"] += 1
        except Exception as e:
            logger.warning("Auto-apply on event failed for %s: %s", prospect_id[:8], e)


# ---------------------------------------------------------------------------
# Autonomous mode control endpoints
# ---------------------------------------------------------------------------

@app.get("/autonomous/status")
async def autonomous_status():
    return {
        "enabled": AUTONOMOUS_MODE,
        "interval_seconds": AUTONOMOUS_INTERVAL,
        "auto_apply_enabled": AUTO_APPLY_ENABLED,
        "max_parallel_tasks": MAX_PARALLEL_TASKS,
        **_autonomous_state,
    }


@app.post("/autonomous/trigger")
async def trigger_autonomous_cycle():
    if _autonomous_state["running"]:
        return {"ok": 0, "detail": "Cycle already in progress"}
    stats = await _run_autonomous_cycle()
    return {"ok": 1, "cycle_stats": stats, "state": _autonomous_state}


# ---------------------------------------------------------------------------
# Review workflow endpoints
# ---------------------------------------------------------------------------

@app.get("/review/pending")
async def pending_reviews():
    """List prospects awaiting human review before delivery."""
    try:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            resp = await client.get(
                f"{PROSPECTOR_URL}/prospects",
                params={"status": "review_needed", "limit": 50},
                headers=_svc_headers(),
            )
            resp.raise_for_status()
            prospects = resp.json()

            # Enrich with execution output
            enriched = []
            for p in prospects:
                entry = dict(p)
                try:
                    out_resp = await client.get(
                        f"{EXECUTION_URL}/executions/{p['id']}/output",
                        headers=_svc_headers(),
                    )
                    if out_resp.status_code == 200:
                        entry["execution_output"] = out_resp.json().get("output", "")
                except Exception:
                    entry["execution_output"] = ""
                enriched.append(entry)
            return enriched
    except (httpx.RequestError, httpx.HTTPStatusError) as e:
        logger.warning("Failed to fetch pending reviews: %s", e)
        return []


@app.post("/review/{prospect_id}")
async def review_prospect(prospect_id: str, decision: dict):
    """Approve or reject a prospect's completed work.
    Body: {"action": "approve"} or {"action": "reject", "reason": "..."}
    """
    action = decision.get("action", "")
    if action not in ("approve", "reject"):
        raise HTTPException(status_code=422, detail="action must be 'approve' or 'reject'")

    try:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            svc = _svc_headers()
            if action == "approve":
                # Mark as delivered
                await client.patch(
                    f"{PROSPECTOR_URL}/prospects/{prospect_id}",
                    json={"status": "delivered"},
                    headers=svc,
                )

                # Get prospect details for invoicing
                p_resp = await client.get(
                    f"{PROSPECTOR_URL}/prospects/{prospect_id}",
                    headers=svc,
                )
                prospect = p_resp.json() if p_resp.status_code == 200 else {}

                # Auto-invoice
                invoiced = False
                quoted = prospect.get("quoted_price", 0) or prospect.get("budget_max", 0)
                if quoted > 0:
                    try:
                        await client.post(
                            f"{BILLING_URL}/invoices",
                            json={
                                "prospect_id": prospect_id,
                                "client_email": prospect.get("client_email", ""),
                                "description": prospect.get("title", ""),
                                "amount_usd": quoted,
                                "token_cost_usd": prospect.get("actual_cost", 0),
                                "platform": prospect.get("platform", ""),
                            },
                            headers=svc,
                        )
                        invoiced = True
                    except Exception:
                        pass

                return {"ok": 1, "prospect_id": prospect_id, "status": "delivered", "invoiced": invoiced}

            else:  # reject
                reason = decision.get("reason", "quality_insufficient")
                await client.patch(
                    f"{PROSPECTOR_URL}/prospects/{prospect_id}",
                    json={"status": "approved"},
                    headers=svc,
                )
                logger.info("Rejected delivery for %s: %s", prospect_id[:8], reason)
                return {"ok": 1, "prospect_id": prospect_id, "status": "rejected_to_approved", "reason": reason}

    except (httpx.RequestError, httpx.HTTPStatusError) as e:
        raise HTTPException(status_code=502, detail=f"Service error: {e}")


@app.get("/pipeline/momentum")
async def pipeline_momentum():
    """Dashboard endpoint showing the health of the feedback cycle."""
    async with _agents_lock:
        agents_snapshot = dict(registered_agents)

    avg_confidence = 0.0
    if agents_snapshot:
        avg_confidence = round(
            sum(a.get("confidence", 0.5) for a in agents_snapshot.values()) / len(agents_snapshot), 3
        )

    return {
        "agent_count": len(agents_snapshot),
        "avg_confidence": avg_confidence,
        "events_relayed": _pipeline_stats["events_relayed"],
        "feedback_loops_triggered": _pipeline_stats["feedback_loops_triggered"],
        "confidence_recalibrations": _pipeline_stats["confidence_recalibrations"],
        "auto_rescans_triggered": _pipeline_stats["auto_rescans_triggered"],
        "autonomous": _autonomous_state,
        "recent_events": get_recent_events(limit=10),
    }
