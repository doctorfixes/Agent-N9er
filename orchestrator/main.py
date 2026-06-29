import os
import sys
import asyncio
import json as _json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
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
    CORS_ORIGINS, BID_REQUIRE_APPROVAL,
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

_service_health = {}
_HEALTH_ENDPOINTS = {
    "prospector": PROSPECTOR_URL,
    "execution": EXECUTION_URL,
    "reputation": REPUTATION_URL,
}
HEALTH_CHECK_TIMEOUT = httpx.Timeout(5.0)


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
        await db.execute("""
            CREATE TABLE IF NOT EXISTS journal (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                event TEXT NOT NULL,
                decision TEXT NOT NULL,
                reasoning TEXT NOT NULL,
                context TEXT DEFAULT '{}',
                outcome TEXT DEFAULT 'pending',
                severity TEXT DEFAULT 'info'
            )
        """)
        await db.commit()


async def _journal(event: str, decision: str, reasoning: str,
                   context: dict | None = None, outcome: str = "pending",
                   severity: str = "info"):
    ts = datetime.now(timezone.utc).isoformat()
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO journal (timestamp, event, decision, reasoning, context, outcome, severity) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (ts, event, decision, reasoning, _json.dumps(context or {}), outcome, severity),
            )
            await db.commit()
    except Exception as e:
        logger.warning("Journal write failed: %s", e)
    logger.info("JOURNAL [%s] %s — %s (%s)", severity, event, decision, reasoning)


async def _check_service_health():
    results = {}
    async with httpx.AsyncClient(timeout=HEALTH_CHECK_TIMEOUT) as client:
        for name, url in _HEALTH_ENDPOINTS.items():
            try:
                resp = await client.get(f"{url}/health")
                up = resp.status_code == 200 and resp.json().get("ok") == 1
                results[name] = {"up": up, "checked_at": datetime.now(timezone.utc).isoformat()}
            except (httpx.RequestError, Exception):
                results[name] = {"up": False, "checked_at": datetime.now(timezone.utc).isoformat()}
    _service_health.update(results)
    return results


def _is_service_up(name: str) -> bool:
    entry = _service_health.get(name)
    return entry is not None and entry.get("up", False)


async def _auto_unstick(client: httpx.AsyncClient, svc: dict) -> int:
    try:
        resp = await client.get(
            f"{PROSPECTOR_URL}/prospects",
            params={"status": "executing", "limit": 100},
            headers=svc,
        )
        resp.raise_for_status()
        stuck = resp.json()
        if not stuck:
            return 0

        reset = 0
        for prospect in stuck:
            if prospect.get("hired_at"):
                continue
            try:
                await client.patch(
                    f"{PROSPECTOR_URL}/prospects/{prospect['id']}",
                    json={"status": "approved"},
                    headers=svc,
                )
                reset += 1
            except (httpx.RequestError, httpx.HTTPStatusError):
                pass

        if reset > 0:
            await _journal(
                "auto_unstick", f"Reset {reset} stuck prospects",
                f"Found {len(stuck)} prospects stuck in 'executing' — execution service was likely down",
                {"prospect_ids": [p["id"] for p in stuck[:10]], "total": len(stuck)},
                outcome="resolved", severity="warn",
            )
        return reset
    except (httpx.RequestError, httpx.HTTPStatusError):
        return 0


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


AUTO_DISPATCH_ENABLED = os.getenv("AUTO_DISPATCH_ENABLED", "false").lower() == "true"
DISPATCH_RATE_DELAY = int(os.getenv("DISPATCH_RATE_DELAY_SECONDS", "3"))
AUTO_EXECUTE_ON_HIRE = os.getenv("AUTO_EXECUTE_ON_HIRE", "true").lower() == "true"
AUTO_SUBMIT_DELIVERABLE = os.getenv("AUTO_SUBMIT_DELIVERABLE", "false").lower() == "true"


async def _scan_loop():
    first_run = True
    while True:
        try:
            if first_run:
                first_run = False
                await asyncio.sleep(5)
            else:
                await asyncio.sleep(SCAN_INTERVAL)

            health = await _check_service_health()
            up_count = sum(1 for v in health.values() if v.get("up"))
            total = len(health)
            await _journal(
                "health_check", f"{up_count}/{total} services online",
                "; ".join(f"{k}={'UP' if v.get('up') else 'DOWN'}" for k, v in health.items()),
                health, outcome="ok" if up_count == total else "degraded",
                severity="info" if up_count == total else "warn",
            )

            if _is_service_up("prospector"):
                svc = _svc_headers()
                async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
                    unstuck = await _auto_unstick(client, svc)
                    if unstuck:
                        logger.info("Auto-unstick: reset %d prospects", unstuck)
            else:
                await _journal(
                    "scan_skipped", "Skipped scan — prospector is down",
                    "Health check shows prospector service unreachable",
                    severity="warn", outcome="skipped",
                )
                continue

            results = await _run_scan_cycle()

            if AUTO_DISPATCH_ENABLED:
                if _is_service_up("prospector"):
                    await _dispatch_cycle()
                else:
                    await _journal(
                        "dispatch_skipped", "Skipped dispatch — prospector is down",
                        "Post-scan dispatch deferred until services recover",
                        severity="warn", outcome="skipped",
                    )

            if _is_service_up("prospector"):
                await _posthire_cycle()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error("Scan loop error: %s", e)
            await _journal("scan_loop_error", "Scan loop crashed",
                           str(e), severity="error", outcome="error")
            await asyncio.sleep(60)


async def _get_scan_platforms(client: httpx.AsyncClient, svc: dict) -> list[str]:
    """Get platforms to scan — intersect SCAN_PLATFORMS with configured platforms from prospector."""
    try:
        resp = await client.get(f"{PROSPECTOR_URL}/platforms/configured", headers=svc)
        resp.raise_for_status()
        data = resp.json()
        configured = set(data.get("configured", []))
        active = [p for p in SCAN_PLATFORMS if p in configured]
        skipped = [p for p in SCAN_PLATFORMS if p not in configured]
        if skipped:
            await _journal(
                "platforms_skipped",
                f"Skipped {len(skipped)} unconfigured platforms: {', '.join(skipped)}",
                "Missing required credentials — configure tokens to enable",
                {"skipped": skipped, "active": active},
                outcome="info",
            )
        return active
    except (httpx.RequestError, httpx.HTTPStatusError):
        return list(SCAN_PLATFORMS)


async def _run_scan_cycle():
    _scan_state["running"] = True
    svc = _svc_headers()
    results = {}
    total_new = 0

    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        active_platforms = await _get_scan_platforms(client, svc)
        _scan_state["platforms"] = active_platforms

        for platform in active_platforms:
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

    scanned_count = len(active_platforms)
    failed_platforms = [p for p, r in results.items() if "error" in r]
    await _journal(
        "scan_complete", f"Scanned {scanned_count} platforms, {total_new} new prospects",
        f"Successful: {scanned_count - len(failed_platforms)}, "
        f"Failed: {failed_platforms if failed_platforms else 'none'}",
        {"results": results, "total_new": total_new},
        outcome="ok" if not failed_platforms else "partial",
    )
    logger.info("Scan cycle complete: %d platforms, %d new prospects", scanned_count, total_new)
    return results


async def _dispatch_cycle():
    """Post-scan dispatch: evaluate discovered → generate proposals for approved → queue bids."""
    svc = _svc_headers()
    stats = {"evaluated": 0, "approved": 0, "proposals": 0, "bids_queued": 0, "errors": 0}

    try:
        async with httpx.AsyncClient(timeout=PIPELINE_TIMEOUT) as client:
            # 1. Fetch all discovered prospects
            resp = await client.get(
                f"{PROSPECTOR_URL}/prospects",
                params={"status": "discovered", "limit": 50},
                headers=svc,
            )
            resp.raise_for_status()
            discovered = resp.json()

            if not discovered:
                logger.info("Dispatch: no discovered prospects to process")
                await _journal("dispatch_idle", "No prospects to process",
                               "Zero discovered prospects in queue", outcome="ok")
                return stats

            logger.info("Dispatch: processing %d discovered prospects", len(discovered))

            # 2. Evaluate each
            for prospect in discovered:
                pid = prospect["id"]
                try:
                    eval_resp = await client.post(
                        f"{PROSPECTOR_URL}/prospects/{pid}/evaluate",
                        headers=svc,
                    )
                    eval_resp.raise_for_status()
                    eval_data = eval_resp.json()
                    stats["evaluated"] += 1

                    if eval_data.get("status") != "approved":
                        reason = eval_data.get("evaluation", {}).get("rejection_reason", "not viable")
                        logger.info("Dispatch: %s rejected (%s)", prospect["title"][:40], reason)
                        await _journal(
                            "prospect_rejected", f"Rejected: {prospect['title'][:60]}",
                            reason,
                            {"prospect_id": pid, "platform": prospect.get("platform", "")},
                            outcome="rejected",
                        )
                        continue

                    stats["approved"] += 1
                    evaluation = eval_data.get("evaluation", {})
                    quoted_price = evaluation.get("quoted_price_usd", 0)

                    # 2b. Get adaptive pricing
                    try:
                        price_resp = await client.get(
                            f"{PROSPECTOR_URL}/bids/optimal-price",
                            params={"platform": prospect.get("platform", ""),
                                    "budget_max": prospect.get("budget_max", 0)},
                            headers=svc,
                        )
                        price_resp.raise_for_status()
                        price_data = price_resp.json()
                        adaptive_price = price_data.get("amount", 0)
                        if adaptive_price > 0 and price_data.get("source") != "default":
                            await _journal(
                                "adaptive_pricing",
                                f"Using learned price ${adaptive_price:.2f} (ratio {price_data.get('ratio', '?')}) instead of ${quoted_price:.2f}",
                                f"Source: {price_data.get('source')}, Win rate: {price_data.get('win_rate', '?')}, Samples: {price_data.get('samples', 0)}",
                                price_data, outcome="ok",
                            )
                            quoted_price = adaptive_price
                    except (httpx.RequestError, httpx.HTTPStatusError):
                        pass

                    # 3. Generate proposal
                    proposal_text = ""
                    try:
                        prop_resp = await client.post(
                            f"{EXECUTION_URL}/proposal",
                            json={
                                "prospect_id": pid,
                                "title": prospect["title"],
                                "description": prospect.get("description", ""),
                                "platform": prospect.get("platform", ""),
                                "budget_min": prospect.get("budget_min", 0),
                                "budget_max": prospect.get("budget_max", 0),
                                "skills": prospect.get("skills", ""),
                            },
                            headers=svc,
                        )
                        prop_resp.raise_for_status()
                        prop_data = prop_resp.json()
                        proposal_text = prop_data.get("proposal", "")
                        stats["proposals"] += 1
                    except (httpx.RequestError, httpx.HTTPStatusError) as e:
                        logger.warning("Dispatch: proposal generation failed for %s: %s", pid[:8], e)
                        proposal_text = f"Interested in \"{prospect['title']}\". Ready to deliver quality work within the specified timeline."

                    # 4. Submit bid (goes through approval gate)
                    bid_platforms = {"freelancer", "github_bounties"}
                    platform = prospect.get("platform", "")
                    if platform in bid_platforms and prospect.get("platform_job_id"):
                        try:
                            bid_resp = await client.post(
                                f"{PROSPECTOR_URL}/prospects/{pid}/bid",
                                json={
                                    "prospect_id": pid,
                                    "amount": quoted_price if quoted_price > 0 else prospect.get("budget_min", 50),
                                    "period": 7,
                                    "description": proposal_text,
                                },
                                headers=svc,
                            )
                            bid_resp.raise_for_status()
                            bid_data = bid_resp.json()
                            stats["bids_queued"] += 1
                            await _journal(
                                "bid_queued", f"Bid queued: {prospect['title'][:60]}",
                                f"${quoted_price:.2f} on {platform} — {bid_data.get('status', 'unknown')}",
                                {"prospect_id": pid, "platform": platform, "amount": quoted_price},
                                outcome="queued",
                            )
                            logger.info("Dispatch: bid queued for %s ($%.2f) [%s] — %s",
                                        prospect["title"][:40], quoted_price, platform,
                                        bid_data.get("status", "unknown"))
                        except (httpx.RequestError, httpx.HTTPStatusError) as e:
                            logger.warning("Dispatch: bid submission failed for %s: %s", pid[:8], e)
                            stats["errors"] += 1
                    else:
                        logger.info("Dispatch: %s approved with proposal (%s, no auto-bid)",
                                    prospect["title"][:40], platform)

                except (httpx.RequestError, httpx.HTTPStatusError) as e:
                    logger.warning("Dispatch: evaluation failed for %s: %s", pid[:8], e)
                    stats["errors"] += 1

                await asyncio.sleep(DISPATCH_RATE_DELAY)

    except Exception as e:
        logger.error("Dispatch cycle error: %s", e)
        stats["errors"] += 1
        await _journal("dispatch_error", "Dispatch cycle failed",
                       str(e), stats, outcome="error", severity="error")

    await _journal(
        "dispatch_complete",
        f"Dispatch: {stats['evaluated']} evaluated, {stats['approved']} approved, {stats['bids_queued']} bids",
        f"Proposals: {stats['proposals']}, Errors: {stats['errors']}",
        stats, outcome="ok" if stats["errors"] == 0 else "partial",
    )
    logger.info("Dispatch complete: %s", stats)
    _scan_state["last_dispatch"] = stats
    return stats


async def _posthire_cycle():
    """Post-hire lifecycle: check awards, auto-execute hired work, check payments, check reviews."""
    svc = _svc_headers()
    stats = {"awards_checked": 0, "newly_hired": 0, "executed": 0, "payments": 0, "reviews": 0, "errors": 0}

    try:
        async with httpx.AsyncClient(timeout=PIPELINE_TIMEOUT) as client:
            # 1. Check for awarded bids (applied → hired)
            try:
                resp = await client.post(f"{PROSPECTOR_URL}/prospects/check-awards", headers=svc)
                resp.raise_for_status()
                awards = resp.json()
                stats["awards_checked"] = awards.get("checked", 0)
                stats["newly_hired"] = awards.get("hired", 0)

                if stats["newly_hired"] > 0:
                    await _journal(
                        "bids_awarded", f"{stats['newly_hired']} bids awarded",
                        f"Checked {stats['awards_checked']} applied bids, {stats['newly_hired']} hired",
                        awards.get("details", []), outcome="ok",
                    )
            except (httpx.RequestError, httpx.HTTPStatusError) as e:
                stats["errors"] += 1
                logger.warning("Award check failed: %s", e)

            # 2. Auto-execute work for hired prospects
            if AUTO_EXECUTE_ON_HIRE and _is_service_up("execution"):
                try:
                    hired_resp = await client.get(
                        f"{PROSPECTOR_URL}/prospects",
                        params={"status": "hired", "limit": 10},
                        headers=svc,
                    )
                    hired_resp.raise_for_status()
                    hired = hired_resp.json()

                    for prospect in hired:
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
                                    "objective": prospect["title"],
                                    "description": prospect.get("description", ""),
                                    "complexity": "moderate",
                                },
                                headers=svc,
                            )
                            exec_resp.raise_for_status()
                            exec_data = exec_resp.json()

                            if exec_data.get("success"):
                                await client.patch(
                                    f"{PROSPECTOR_URL}/prospects/{pid}",
                                    json={"status": "delivered"},
                                    headers=svc,
                                )
                                stats["executed"] += 1

                                if AUTO_SUBMIT_DELIVERABLE:
                                    try:
                                        await client.post(
                                            f"{PROSPECTOR_URL}/prospects/{pid}/submit-deliverable",
                                            headers=svc,
                                        )
                                    except (httpx.RequestError, httpx.HTTPStatusError):
                                        pass

                                await _journal(
                                    "work_completed", f"Delivered: {prospect['title'][:60]}",
                                    f"Mode: {exec_data.get('mode', '?')}, Cost: ${exec_data.get('cost_usd', 0):.4f}",
                                    {"prospect_id": pid, "mode": exec_data.get("mode"), "cost": exec_data.get("cost_usd", 0)},
                                    outcome="ok",
                                )
                            else:
                                await client.patch(
                                    f"{PROSPECTOR_URL}/prospects/{pid}",
                                    json={"status": "hired"},
                                    headers=svc,
                                )
                        except (httpx.RequestError, httpx.HTTPStatusError) as e:
                            stats["errors"] += 1
                            try:
                                await client.patch(
                                    f"{PROSPECTOR_URL}/prospects/{pid}",
                                    json={"status": "hired"},
                                    headers=svc,
                                )
                            except httpx.RequestError:
                                pass
                            logger.warning("Execution failed for hired prospect %s: %s", pid[:8], e)
                except (httpx.RequestError, httpx.HTTPStatusError) as e:
                    stats["errors"] += 1
                    logger.warning("Hired prospect fetch failed: %s", e)

            # 3. Check for payments (delivered → paid)
            try:
                resp = await client.post(f"{PROSPECTOR_URL}/prospects/check-payments", headers=svc)
                resp.raise_for_status()
                payments = resp.json()
                stats["payments"] = payments.get("paid", 0)

                if stats["payments"] > 0:
                    await _journal(
                        "payments_received", f"{stats['payments']} payments received",
                        f"Total earned: ${payments.get('total_earned', 0):.2f}",
                        outcome="ok",
                    )
            except (httpx.RequestError, httpx.HTTPStatusError) as e:
                stats["errors"] += 1
                logger.warning("Payment check failed: %s", e)

            # 4. Check for reviews (paid → rated)
            try:
                resp = await client.post(f"{PROSPECTOR_URL}/prospects/check-reviews", headers=svc)
                resp.raise_for_status()
                reviews = resp.json()
                stats["reviews"] = reviews.get("rated", 0)
            except (httpx.RequestError, httpx.HTTPStatusError) as e:
                stats["errors"] += 1
                logger.warning("Review check failed: %s", e)

            # 5. Update feedback loop (feed learning stats to evaluator)
            if stats.get("reviews", 0) > 0 or stats.get("newly_hired", 0) > 0:
                try:
                    fb_resp = await client.get(f"{PROSPECTOR_URL}/feedback/stats", headers=svc)
                    fb_resp.raise_for_status()
                    feedback = fb_resp.json()
                    try:
                        await client.post(
                            f"{EVALUATOR_URL}/feedback/update",
                            json=feedback, headers=svc,
                        )
                        await _journal(
                            "feedback_updated", "Evaluator feedback updated",
                            f"Platforms: {len(feedback.get('by_platform', {}))}, "
                            f"Budget buckets: {len(feedback.get('by_budget', {}))}",
                            outcome="ok",
                        )
                    except (httpx.RequestError, httpx.HTTPStatusError):
                        pass
                except (httpx.RequestError, httpx.HTTPStatusError) as e:
                    logger.warning("Feedback stats fetch failed: %s", e)

            # 6. Check client messages and auto-respond
            try:
                msg_resp = await client.post(f"{PROSPECTOR_URL}/prospects/check-messages", headers=svc)
                msg_resp.raise_for_status()
                msg_data = msg_resp.json()
                stats["messages_found"] = msg_data.get("new_messages", 0)

                for pm in msg_data.get("prospects_with_messages", []):
                    if pm.get("message_type") in ("revision", "question") and _is_service_up("execution"):
                        try:
                            respond_resp = await client.post(
                                f"{EXECUTION_URL}/respond",
                                json={
                                    "prospect_id": pm["prospect_id"],
                                    "client_message": pm.get("preview", ""),
                                    "project_title": pm.get("title", ""),
                                },
                                headers=svc,
                            )
                            respond_resp.raise_for_status()
                            response_text = respond_resp.json().get("response", "")

                            if response_text:
                                await client.post(
                                    f"{PROSPECTOR_URL}/prospects/{pm['prospect_id']}/reply",
                                    json={"message": response_text, "thread_id": pm.get("thread_id", "")},
                                    headers=svc,
                                )
                                stats["auto_replies"] = stats.get("auto_replies", 0) + 1
                                await _journal(
                                    "auto_reply", f"Auto-replied to client: {pm['title'][:50]}",
                                    f"Type: {pm['message_type']}, Preview: {pm.get('preview', '')[:80]}",
                                    outcome="ok",
                                )
                        except (httpx.RequestError, httpx.HTTPStatusError) as e:
                            logger.warning("Auto-reply failed for %s: %s", pm["prospect_id"][:8], e)

            except (httpx.RequestError, httpx.HTTPStatusError) as e:
                logger.warning("Message check failed: %s", e)

    except Exception as e:
        stats["errors"] += 1
        await _journal("posthire_error", "Post-hire cycle failed",
                       str(e), severity="error", outcome="error")

    if any(stats[k] > 0 for k in ("newly_hired", "executed", "payments", "reviews", "messages_found")):
        await _journal(
            "posthire_complete",
            f"Post-hire: {stats['newly_hired']} hired, {stats['executed']} executed, {stats['payments']} paid",
            f"Awards checked: {stats['awards_checked']}, Reviews: {stats['reviews']}",
            stats, outcome="ok" if stats["errors"] == 0 else "partial",
        )

    _scan_state["last_posthire"] = stats
    return stats


@asynccontextmanager
async def lifespan(app):
    global _scan_task
    await _init_db()
    await _load_agents()
    await _journal(
        "system_boot", "Agent N9er starting up",
        f"Auto-scan={'ON' if AUTO_SCAN_ENABLED else 'OFF'}, "
        f"Auto-dispatch={'ON' if AUTO_DISPATCH_ENABLED else 'OFF'}, "
        f"Scan interval={SCAN_INTERVAL}s, Platforms={SCAN_PLATFORMS}",
        outcome="ok",
    )
    if AUTO_SCAN_ENABLED:
        _scan_task = asyncio.create_task(_scan_loop())
        logger.info("Auto-scan enabled: interval=%ds, platforms=%s, auto_dispatch=%s",
                     SCAN_INTERVAL, SCAN_PLATFORMS, AUTO_DISPATCH_ENABLED)
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
    if AUTO_DISPATCH_ENABLED:
        dispatch_stats = await _dispatch_cycle()
        return {"ok": 1, "results": results, "dispatch": dispatch_stats, "scan_state": _scan_state}
    return {"ok": 1, "results": results, "scan_state": _scan_state}


@app.post("/dispatch")
async def trigger_dispatch():
    """Manually trigger dispatch: evaluate discovered prospects, generate proposals, queue bids."""
    stats = await _dispatch_cycle()
    return {"ok": 1, "dispatch": stats, "scan_state": _scan_state}


@app.get("/dispatch/status")
async def dispatch_status():
    return {
        "auto_dispatch_enabled": AUTO_DISPATCH_ENABLED,
        "auto_scan_enabled": AUTO_SCAN_ENABLED,
        "last_dispatch": _scan_state.get("last_dispatch"),
        **_scan_state,
    }


@app.post("/posthire")
async def trigger_posthire():
    """Manually trigger post-hire cycle: check awards, execute hired work, check payments."""
    stats = await _posthire_cycle()
    return {"ok": 1, "posthire": stats}


@app.get("/posthire/status")
async def posthire_status():
    return {
        "auto_execute_on_hire": AUTO_EXECUTE_ON_HIRE,
        "auto_submit_deliverable": AUTO_SUBMIT_DELIVERABLE,
        "last_posthire": _scan_state.get("last_posthire"),
    }


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
                adjusted_confidence = min(1.0, base_confidence + boost)

                bid_payload = {
                    "task_id": task_id,
                    "agent_id": agent_id,
                    "price": agent_info.get("price", 0.1),
                    "eta_minutes": agent_info.get("eta_minutes", 5),
                    "confidence": round(adjusted_confidence, 3),
                    "require_approval": BID_REQUIRE_APPROVAL,
                }
                try:
                    await client.post(f"{MARKETPLACE_URL}/bid", json=bid_payload, headers=svc)
                except httpx.RequestError:
                    logger.warning("Failed to submit bid for agent %s", agent_id)

            await asyncio.gather(*[
                _submit_bid(aid, ainfo) for aid, ainfo in agents_snapshot.items()
            ])

            if BID_REQUIRE_APPROVAL:
                logger.info("Task %s [%s]: bids pending approval from %d agents",
                            task_id, category, len(agents_snapshot))
                return {
                    "status": "pending_approval",
                    "task_id": task_id,
                    "category": category,
                    "pending_bids": len(agents_snapshot),
                    "detail": "Bids require human approval. Use POST /pipeline/{task_id}/approve to approve and continue.",
                }

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


@app.post("/pipeline/{task_id}/approve")
async def approve_pipeline_bids(task_id: str):
    """Approve pending bids for a task and continue the pipeline (award + execute)."""
    try:
        svc = _svc_headers()
        async with httpx.AsyncClient(timeout=PIPELINE_TIMEOUT) as client:
            approve_resp = await retry_post(
                client, f"{MARKETPLACE_URL}/bids/approve-all/{task_id}", headers=svc,
            )
            approve_data = approve_resp.json()

            if approve_data.get("approved_count", 0) == 0:
                raise HTTPException(status_code=404, detail="No pending bids to approve for this task")

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

            logger.info("Approved pipeline for task %s: %s (agent %s)",
                        task_id, status, winner["agent_id"])
            return {
                "status": status,
                "task_id": task_id,
                "approved_bids": approve_data.get("approved_count", 0),
                "winner": winner,
                "execution": exec_data,
            }

    except httpx.HTTPStatusError as e:
        logger.error("Approve pipeline failed: %s", e)
        raise HTTPException(status_code=502, detail=str(e))
    except httpx.RequestError as e:
        logger.error("Service unreachable during approval: %s", e)
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
    require_approval: bool | None = None
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

                    # 3. Execute if auto_execute and approval not required
                    needs_approval = req.require_approval if req.require_approval is not None else BID_REQUIRE_APPROVAL
                    if needs_approval:
                        prospect_result["status"] = "pending_approval"
                        prospect_result["detail"] = "Human approval required before execution"
                    elif req.auto_execute:
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


class ExecuteWorkRequest(BaseModel):
    status_filter: str = "executing"
    prospect_id: str = ""
    client_email: str = ""


@app.post("/prospects/execute-work")
async def execute_prospect_work(req: ExecuteWorkRequest):
    """Generate deliverables for prospects in 'executing' (or other) status."""
    await _check_service_health()
    if not _is_service_up("execution"):
        await _journal(
            "execute_blocked", "Execution blocked — service is down",
            "Refusing to attempt execution while execution service is unreachable",
            severity="warn", outcome="blocked",
        )
        raise HTTPException(status_code=503, detail="Execution service is down — refusing to create stuck prospects")

    svc = _svc_headers()
    results = {
        "total": 0,
        "completed": 0,
        "failed": 0,
        "skipped": 0,
        "total_cost_usd": 0,
        "deliverables": [],
    }

    try:
        async with httpx.AsyncClient(timeout=PIPELINE_TIMEOUT) as client:
            if req.prospect_id:
                prospect_resp = await client.get(
                    f"{PROSPECTOR_URL}/prospects/{req.prospect_id}",
                    headers=svc,
                )
                prospect_resp.raise_for_status()
                prospects = [prospect_resp.json()]
            else:
                prospects_resp = await client.get(
                    f"{PROSPECTOR_URL}/prospects",
                    params={"status": req.status_filter, "limit": 50},
                    headers=svc,
                )
                prospects_resp.raise_for_status()
                prospects = prospects_resp.json()
            results["total"] = len(prospects)

            if not prospects:
                return {**results, "detail": f"No prospects with status '{req.status_filter}'"}

            for prospect in prospects:
                pid = prospect["id"]
                entry = {
                    "prospect_id": pid,
                    "title": prospect["title"],
                    "platform": prospect.get("platform", "unknown"),
                }

                try:
                    exec_resp = await client.post(
                        f"{EXECUTION_URL}/execute",
                        json={
                            "task_id": pid,
                            "agent_id": "agent-n9er-primary",
                            "confidence": 0.85,
                            "objective": prospect["title"],
                            "description": prospect.get("description", ""),
                            "complexity": "moderate",
                        },
                        headers=svc,
                    )
                    exec_resp.raise_for_status()
                    exec_data = exec_resp.json()

                    if exec_data.get("success"):
                        results["completed"] += 1
                        cost = exec_data.get("cost_usd", 0)
                        results["total_cost_usd"] += cost

                        await client.patch(
                            f"{PROSPECTOR_URL}/prospects/{pid}",
                            json={"status": "delivered"},
                            headers=svc,
                        )

                        entry["status"] = "delivered"
                        entry["mode"] = exec_data.get("mode", "unknown")
                        entry["model"] = exec_data.get("model", "")
                        entry["cost_usd"] = cost
                        entry["duration"] = exec_data.get("duration", 0)
                        entry["output_preview"] = exec_data.get("output_preview", "")[:200]

                        quoted = prospect.get("quoted_price", 0) or prospect.get("budget_min", 0)
                        if req.client_email and quoted > 0:
                            try:
                                await client.post(
                                    f"{BILLING_URL}/invoices",
                                    json={
                                        "prospect_id": pid,
                                        "client_email": req.client_email,
                                        "description": prospect["title"],
                                        "amount_usd": quoted,
                                        "token_cost_usd": cost,
                                        "platform": prospect.get("platform", ""),
                                    },
                                    headers=svc,
                                )
                                entry["invoiced"] = True
                            except httpx.RequestError:
                                entry["invoiced"] = False
                    else:
                        results["failed"] += 1
                        entry["status"] = "execution_failed"
                        entry["error"] = exec_data.get("error", "LLM returned incomplete response")
                        try:
                            await client.patch(
                                f"{PROSPECTOR_URL}/prospects/{pid}",
                                json={"status": "approved"},
                                headers=svc,
                            )
                        except httpx.RequestError:
                            pass

                except (httpx.RequestError, httpx.HTTPStatusError) as e:
                    results["failed"] += 1
                    entry["status"] = "error"
                    entry["error"] = str(e)
                    try:
                        await client.patch(
                            f"{PROSPECTOR_URL}/prospects/{pid}",
                            json={"status": "approved"},
                            headers=svc,
                        )
                    except httpx.RequestError:
                        pass

                results["deliverables"].append(entry)

    except httpx.RequestError as e:
        raise HTTPException(status_code=503, detail=f"Service unreachable: {e}")

    results["total_cost_usd"] = round(results["total_cost_usd"], 4)
    logger.info(
        "Execute work: total=%d completed=%d failed=%d cost=$%.4f",
        results["total"], results["completed"], results["failed"], results["total_cost_usd"],
    )
    return results


class UnstickRequest(BaseModel):
    target_status: str = "approved"


@app.post("/prospects/unstick")
async def unstick_prospects(req: UnstickRequest):
    """Reset stuck 'executing' prospects back to a recoverable status."""
    svc = _svc_headers()
    try:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            resp = await client.get(
                f"{PROSPECTOR_URL}/prospects",
                params={"status": "executing", "limit": 100},
                headers=svc,
            )
            resp.raise_for_status()
            stuck = resp.json()

            reset_count = 0
            for prospect in stuck:
                pid = prospect["id"]
                try:
                    await client.patch(
                        f"{PROSPECTOR_URL}/prospects/{pid}",
                        json={"status": req.target_status},
                        headers=svc,
                    )
                    reset_count += 1
                except (httpx.RequestError, httpx.HTTPStatusError):
                    pass

            return {
                "ok": 1,
                "found": len(stuck),
                "reset": reset_count,
                "target_status": req.target_status,
            }
    except httpx.RequestError as e:
        raise HTTPException(status_code=503, detail=f"Service unreachable: {e}")


@app.get("/journal")
async def get_journal(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    severity: Optional[str] = None,
    event: Optional[str] = None,
):
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            where_parts = []
            params = []
            if severity:
                where_parts.append("severity = ?")
                params.append(severity)
            if event:
                where_parts.append("event LIKE ?")
                params.append(f"%{event}%")
            where = "WHERE " + " AND ".join(where_parts) if where_parts else ""
            cursor = await db.execute(
                f"SELECT * FROM journal {where} ORDER BY id DESC LIMIT ? OFFSET ?",
                params + [limit, offset],
            )
            rows = await cursor.fetchall()
            count_cursor = await db.execute(f"SELECT COUNT(*) FROM journal {where}", params)
            total = (await count_cursor.fetchone())[0]
            entries = []
            for row in rows:
                entry = dict(row)
                try:
                    entry["context"] = _json.loads(entry.get("context", "{}"))
                except (ValueError, TypeError):
                    pass
                entries.append(entry)
            return {"entries": entries, "total": total, "limit": limit, "offset": offset}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Journal read error: {e}")


@app.get("/services/health")
async def services_health(refresh: bool = False):
    if refresh or not _service_health:
        await _check_service_health()
    up_count = sum(1 for v in _service_health.values() if v.get("up"))
    return {
        "services": _service_health,
        "total": len(_service_health),
        "online": up_count,
        "status": "healthy" if up_count == len(_service_health) else (
            "degraded" if up_count > 0 else "down"
        ),
    }


@app.get("/self-awareness")
async def self_awareness():
    """Agent N9er's self-assessment: what it knows about its own state."""
    await _check_service_health()
    up_count = sum(1 for v in _service_health.values() if v.get("up"))
    total_svc = len(_service_health)

    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute(
                "SELECT COUNT(*) FROM journal WHERE severity = 'error' AND timestamp > datetime('now', '-24 hours')"
            )
            errors_24h = (await cursor.fetchone())[0]

            cursor = await db.execute(
                "SELECT COUNT(*) FROM journal WHERE severity = 'warn' AND timestamp > datetime('now', '-24 hours')"
            )
            warnings_24h = (await cursor.fetchone())[0]

            cursor = await db.execute(
                "SELECT event, COUNT(*) as cnt FROM journal WHERE timestamp > datetime('now', '-24 hours') GROUP BY event ORDER BY cnt DESC LIMIT 10"
            )
            event_freq = [{"event": r[0], "count": r[1]} for r in await cursor.fetchall()]

            cursor = await db.execute(
                "SELECT * FROM journal WHERE severity IN ('error', 'warn') ORDER BY id DESC LIMIT 5"
            )
            recent_issues = []
            for row in await cursor.fetchall():
                recent_issues.append({"timestamp": row[1], "event": row[2], "decision": row[3], "reasoning": row[4], "severity": row[7]})
    except Exception:
        errors_24h = warnings_24h = 0
        event_freq = []
        recent_issues = []

    issues = []
    recommendations = []

    if up_count < total_svc:
        down = [k for k, v in _service_health.items() if not v.get("up")]
        issues.append(f"Services down: {', '.join(down)}")
        recommendations.append(f"Restart {', '.join(down)} — execution and dispatch are blocked")

    if errors_24h > 5:
        issues.append(f"{errors_24h} errors in the last 24h — system is unstable")
        recommendations.append("Review journal errors before continuing autonomous operations")

    if _scan_state["total_scans"] > 0 and _scan_state["total_discovered"] == 0:
        issues.append("Scans running but zero prospects discovered — check platform credentials")
        recommendations.append("Verify API keys and platform configuration")

    if not issues:
        recommendations.append("All systems nominal — autonomous operations safe to continue")

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "health": {
            "services_online": f"{up_count}/{total_svc}",
            "status": "healthy" if up_count == total_svc else "degraded",
            "services": _service_health,
        },
        "activity": {
            "total_scans": _scan_state["total_scans"],
            "total_discovered": _scan_state["total_discovered"],
            "last_scan": _scan_state.get("last_scan_at"),
            "auto_scan": AUTO_SCAN_ENABLED,
            "auto_dispatch": AUTO_DISPATCH_ENABLED,
        },
        "stability": {
            "errors_24h": errors_24h,
            "warnings_24h": warnings_24h,
            "event_frequency": event_freq,
        },
        "recent_issues": recent_issues,
        "issues": issues,
        "recommendations": recommendations,
    }
