import os
import sys
import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

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
from shared.ethics import screen_project, screen_deliverable, add_transparency_notice
from shared.config import (
    DEFAULT_TIMEOUT, PIPELINE_TIMEOUT,
    QUICK_TIMEOUT, RATE_LIMIT_MAX_REQUESTS, RATE_LIMIT_WINDOW_SECONDS,
    CORS_ORIGINS,
)
from shared.retry import retry_post
from shared.llm import complete as llm_complete

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
FREELANCER_MAX_BIDS_PER_MONTH = int(os.getenv("FREELANCER_MAX_BIDS_PER_MONTH", "45"))
FREELANCER_MAX_BIDS_PER_HOUR = int(os.getenv("FREELANCER_MAX_BIDS_PER_HOUR", "5"))
FREELANCER_MIN_BUDGET = float(os.getenv("FREELANCER_MIN_BUDGET", "50"))
FREELANCER_MAX_BUDGET = float(os.getenv("FREELANCER_MAX_BUDGET", "15000"))

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
AUTO_REPLY_ENABLED = os.getenv("AUTO_REPLY_ENABLED", "true").lower() == "true"
AUTO_REPLY_DELAY_SECONDS = int(os.getenv("AUTO_REPLY_DELAY_SECONDS", "30"))
AUTO_REPLY_MAX_PER_THREAD_HOUR = int(os.getenv("AUTO_REPLY_MAX_PER_THREAD_HOUR", "3"))
TELEGRAM_COMMAND_ENABLED = os.getenv("TELEGRAM_COMMAND_ENABLED", "true").lower() == "true"

_reply_tracker: dict[int, list[float]] = {}
_pending_replies: dict[int, dict] = {}
_pending_replies_lock = asyncio.Lock()

_activity_log: list[dict] = []
_ACTIVITY_MAX = 200


def _log_activity(event_type: str, summary: str, details: dict | None = None):
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "type": event_type,
        "summary": summary,
        "details": details or {},
    }
    _activity_log.insert(0, entry)
    if len(_activity_log) > _ACTIVITY_MAX:
        del _activity_log[_ACTIVITY_MAX:]
_telegram_poll_task: asyncio.Task | None = None
_last_telegram_update_id = 0


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

    if FREELANCER_AUTO_BID and total_new > 0:
        try:
            bids_placed = await _auto_evaluate_and_bid(svc=svc)
            if bids_placed > 0:
                logger.info("Auto-bid cycle placed %d bids", bids_placed)
        except Exception as e:
            logger.warning("Auto-bid cycle failed: %s", e)

    if FREELANCER_AUTO_BID:
        try:
            await _check_awarded_and_execute(svc=svc)
        except Exception as e:
            logger.warning("Post-bid pipeline failed: %s", e)

        try:
            await _check_freelancer_messages(svc=svc)
        except Exception as e:
            logger.warning("Message check failed: %s", e)

    return results


async def _auto_evaluate_and_bid(svc=None):
    if svc is None:
        svc = _svc_headers()
    bids_placed = 0
    async with httpx.AsyncClient(timeout=PIPELINE_TIMEOUT) as client:
        prospects_resp = await client.get(
            f"{PROSPECTOR_URL}/prospects",
            params={"status": "approved", "platform": "freelancer", "limit": 20},
            headers=svc,
        )
        prospects_resp.raise_for_status()
        all_prospects = prospects_resp.json()

        now = datetime.now(timezone.utc)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
        applied_resp = await client.get(
            f"{PROSPECTOR_URL}/prospects",
            params={"status": "applied", "platform": "freelancer", "limit": 200},
            headers=svc,
        )
        bids_this_month = 0
        if applied_resp.status_code == 200:
            for p in applied_resp.json():
                if p.get("applied_at", "") >= month_start:
                    bids_this_month += 1

        remaining = FREELANCER_MAX_BIDS_PER_MONTH - bids_this_month
        if remaining <= 0:
            logger.info("Auto-bid: monthly bid limit reached (%d/%d), skipping", bids_this_month, FREELANCER_MAX_BIDS_PER_MONTH)
            await telegram_notify(f"AUTO-BID PAUSED\nMonthly bid limit reached: {bids_this_month}/{FREELANCER_MAX_BIDS_PER_MONTH}")
            return 0

        hour_ago = (now - timedelta(hours=1)).isoformat()
        bids_this_hour = 0
        if applied_resp.status_code == 200:
            for p in applied_resp.json():
                if p.get("applied_at", "") >= hour_ago:
                    bids_this_hour += 1
        hourly_remaining = FREELANCER_MAX_BIDS_PER_HOUR - bids_this_hour
        if hourly_remaining <= 0:
            logger.info("Auto-bid: hourly limit reached (%d/%d), waiting", bids_this_hour, FREELANCER_MAX_BIDS_PER_HOUR)
            return 0

        effective_limit = min(remaining, hourly_remaining)

        def _is_good_roi(p):
            bmin = p.get("budget_min", 0) or 0
            bmax = p.get("budget_max", 0) or 0
            budget = bmax or bmin
            if budget < FREELANCER_MIN_BUDGET:
                return False
            if budget > FREELANCER_MAX_BUDGET:
                return False
            desc = (p.get("description") or "").lower()
            title = (p.get("title") or "").lower()
            low_value_signals = [
                "for free", "no budget", "volunteer", "unpaid",
                "test project", "just testing", "looking for cheapest",
            ]
            for signal in low_value_signals:
                if signal in desc or signal in title:
                    return False
            vague_titles = ["i need", "help me", "do this", "project", "work"]
            if title.strip() in vague_titles:
                return False

            undeliverable_signals = [
                "lead generation", "lead gen", "lead list", "sales navigator",
                "linkedin scraping", "linkedin leads", "email scraping",
                "data scraping", "web scraping", "screen scraping",
                "cold calling", "cold email list", "prospect list",
                "verified emails", "email harvest", "contact list",
                "b2b leads", "b2b list", "mailing list",
                "virtual assistant", "admin assistant", "personal assistant",
                "data entry", "manual data", "copy paste",
                "video editing", "video production", "motion graphics",
                "graphic design", "logo design", "photoshop", "illustrator",
                "3d modeling", "3d rendering", "cad design",
                "translation", "transcription", "voice over", "voiceover",
                "social media management", "social media posting",
                "seo backlinks", "link building", "guest posting",
                "phone calls", "appointment setting", "telemarketing",
            ]
            combined = f"{title} {desc}"
            for signal in undeliverable_signals:
                if signal in combined:
                    return False

            return True

        candidates = [p for p in all_prospects if not p.get("applied_at")]
        qualified = [p for p in candidates if _is_good_roi(p)]
        skipped = len(candidates) - len(qualified)
        if skipped > 0:
            logger.info("Auto-bid: filtered out %d low-ROI prospects", skipped)

        qualified.sort(key=lambda p: (p.get("budget_max", 0) or p.get("budget_min", 0) or 0), reverse=True)
        prospects = qualified[:effective_limit]

        logger.info("Auto-bid: %d approved Freelancer prospects without bids (%d/%d monthly limit)", len(prospects), bids_this_month, FREELANCER_MAX_BIDS_PER_MONTH)
        for prospect in prospects:
            pid = prospect["id"]
            try:
                ethics = screen_project(
                    prospect.get("title", ""),
                    prospect.get("description", ""),
                    prospect.get("skills", ""),
                )
                if not ethics["allowed"]:
                    logger.warning("ETHICS BLOCK: %s -- %s", prospect.get("title", "")[:60], ethics["flags"])
                    await client.patch(
                        f"{PROSPECTOR_URL}/prospects/{pid}",
                        json={"status": "rejected"},
                        headers=svc,
                    )
                    await telegram_notify(
                        f"PROJECT BLOCKED (ethics)\n"
                        f"Title: {prospect.get('title', 'Unknown')}\n"
                        f"Flags: {', '.join(ethics['flags'])}"
                    )
                    continue

                budget_min = prospect.get("budget_min", 0) or 0
                budget_max = prospect.get("budget_max", 0) or 0
                quoted = prospect.get("quoted_price", 0) or 0
                bid_amount = max(quoted, budget_min, 15.0)
                if budget_max > 0:
                    bid_amount = min(bid_amount, budget_max)

                proposal_text = ""
                try:
                    prop_resp = await client.post(
                        f"{EXECUTION_URL}/proposal",
                        json={
                            "title": prospect.get("title", ""),
                            "description": prospect.get("description", ""),
                            "skills": prospect.get("skills", ""),
                            "platform": "freelancer",
                            "budget_max": budget_max,
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
                        "bid_amount": bid_amount,
                        "period": 7,
                        "milestone_percentage": 100.0,
                        "description": proposal_text,
                    },
                    headers=svc,
                )
                if bid_resp.status_code == 200:
                    bid_data = bid_resp.json()
                    bids_placed += 1
                    logger.info("Auto-bid on Freelancer project %s: $%.2f", pid[:8], bid_amount)
                    _log_activity("bid_placed", f"Bid ${bid_amount:.2f} on {prospect.get('title', 'Unknown')[:60]}", {"project": prospect.get("title"), "amount": bid_amount, "bid_id": bid_data.get("bid_id"), "prospect_id": pid})
                    await telegram_notify(
                        f"BID PLACED\n"
                        f"Project: {prospect.get('title', 'Unknown')}\n"
                        f"Amount: ${bid_amount:.2f}\n"
                        f"Bid ID: {bid_data.get('bid_id')}\n"
                        f"URL: {prospect.get('url', '')}"
                    )
                else:
                    logger.warning("Freelancer auto-bid failed for %s: %s", pid[:8], bid_resp.text)
                    await telegram_notify(
                        f"BID FAILED\n"
                        f"Project: {prospect.get('title', 'Unknown')}\n"
                        f"Reason: {bid_resp.text}"
                    )
            except Exception as e:
                logger.warning("Auto-bid error for %s: %s", pid[:8], e)
            await asyncio.sleep(2)
    return bids_placed


async def _check_awarded_and_execute(svc=None):
    """Check for awarded bids, execute work, deliver, and track payments."""
    if svc is None:
        svc = _svc_headers()

    async with httpx.AsyncClient(timeout=PIPELINE_TIMEOUT) as client:
        # 1. Check for newly awarded bids
        try:
            awarded_resp = await client.get(
                f"{PROSPECTOR_URL}/freelancer/check-awarded",
                headers=svc,
            )
            if awarded_resp.status_code == 200:
                awarded = awarded_resp.json().get("awarded", [])
                for award in awarded:
                    logger.info("BID AWARDED: %s", award.get("title", ""))
                    _log_activity("bid_accepted", f"Hired for {award.get('title', 'Unknown')[:60]} — ${award.get('bid_amount', 0):.2f}", {"project": award.get("title"), "amount": award.get("bid_amount", 0), "client": award.get("client_username", "")})
                    await telegram_notify(
                        f"BID ACCEPTED!\n"
                        f"Project: {award.get('title', 'Unknown')}\n"
                        f"Amount: ${award.get('bid_amount', 0):.2f}\n"
                        f"Starting execution..."
                    )
        except Exception as e:
            logger.warning("Awarded check failed: %s", e)

        # 2. Execute work for hired prospects
        try:
            hired_resp = await client.get(
                f"{PROSPECTOR_URL}/prospects",
                params={"status": "hired", "platform": "freelancer", "limit": 10},
                headers=svc,
            )
            if hired_resp.status_code == 200:
                for prospect in hired_resp.json():
                    pid = prospect["id"]
                    title = prospect.get("title", "Unknown")

                    ethics = screen_project(title, "", "")
                    if not ethics["allowed"]:
                        logger.warning("ETHICS SOFT-FLAG on hired project (title-only): %s -- %s", title[:60], ethics["flags"])
                        await telegram_notify(
                            f"ETHICS WARNING (hired project)\n"
                            f"Project: {title}\n"
                            f"Flags: {', '.join(ethics['flags'])}\n"
                            f"Proceeding — project already passed pre-bid screening."
                        )

                    await client.patch(
                        f"{PROSPECTOR_URL}/prospects/{pid}",
                        json={"status": "executing"},
                        headers=svc,
                    )

                    try:
                        exec_resp = await client.post(
                            f"{EXECUTION_URL}/execute",
                            json={
                                "task_id": pid,
                                "agent_id": "agent-n9er-primary",
                                "objective": prospect.get("title", ""),
                                "description": prospect.get("description", ""),
                                "complexity": prospect.get("complexity", "moderate"),
                                "confidence": 0.8,
                                "tier": prospect.get("tier", "standard"),
                                "platform": prospect.get("platform", "freelancer"),
                                "budget": prospect.get("quoted_price", 0),
                                "client": prospect.get("client_username", ""),
                            },
                            headers=svc,
                            timeout=120.0,
                        )

                        if exec_resp.status_code == 200 and exec_resp.json().get("success"):
                            output_resp = await client.get(
                                f"{EXECUTION_URL}/executions/{pid}/output",
                                headers=svc,
                            )
                            deliverable = ""
                            if output_resp.status_code == 200:
                                deliverable = output_resp.json().get("output", "")

                            deliverable_check = screen_deliverable(deliverable)
                            if not deliverable_check["allowed"]:
                                logger.warning("DELIVERABLE BLOCKED: %s -- %s", title[:60], deliverable_check["flags"])
                                await telegram_notify(
                                    f"DELIVERABLE BLOCKED (safety)\n"
                                    f"Project: {title}\n"
                                    f"Reason: {deliverable_check['reasons'][0] if deliverable_check['reasons'] else 'Unknown'}\n"
                                    f"Manual review required."
                                )
                                continue

                            deliverable = add_transparency_notice(deliverable, "markdown")

                            try:
                                deliver_resp = await client.post(
                                    f"{PROSPECTOR_URL}/freelancer/deliver-milestone",
                                    json={"prospect_id": pid, "deliverable": deliverable},
                                    headers=svc,
                                    timeout=30.0,
                                )
                                if deliver_resp.status_code == 200:
                                    _log_activity("delivered", f"Delivered: {title[:60]}", {"project": title, "prospect_id": pid})
                                    await telegram_notify(
                                        f"WORK DELIVERED\n"
                                        f"Project: {title}\n"
                                        f"Awaiting payment release."
                                    )
                                    logger.info("Executed and delivered: %s", title[:60])
                                else:
                                    logger.error("Delivery API returned %s for %s", deliver_resp.status_code, pid[:8])
                                    _log_activity("delivery_failed", f"Delivery failed: {title[:60]} — will retry", {"project": title, "prospect_id": pid})
                                    await client.patch(
                                        f"{PROSPECTOR_URL}/prospects/{pid}",
                                        json={"status": "hired"},
                                        headers=svc,
                                    )
                                    await telegram_notify(
                                        f"DELIVERY FAILED\n"
                                        f"Project: {title}\n"
                                        f"Will retry next cycle."
                                    )
                            except Exception as de:
                                logger.warning("Milestone delivery failed for %s: %s", pid[:8], de)
                                _log_activity("delivery_failed", f"Delivery error: {title[:60]} — {str(de)[:60]}", {"project": title, "prospect_id": pid})
                                await client.patch(
                                    f"{PROSPECTOR_URL}/prospects/{pid}",
                                    json={"status": "hired"},
                                    headers=svc,
                                )
                                await telegram_notify(
                                    f"DELIVERY ERROR\n"
                                    f"Project: {title}\n"
                                    f"Error: {str(de)[:100]}\n"
                                    f"Will retry next cycle."
                                )
                        else:
                            logger.warning("Execution failed for %s", pid[:8])
                            _log_activity("execution_failed", f"Execution failed: {title[:60]}", {"project": title, "prospect_id": pid})
                            await telegram_notify(
                                f"EXECUTION FAILED\n"
                                f"Project: {title}\n"
                                f"Manual intervention may be needed."
                            )
                    except Exception as ee:
                        logger.warning("Execution error for %s: %s", pid[:8], ee)
        except Exception as e:
            logger.warning("Hired prospect processing failed: %s", e)

        # 3. Check for payments on delivered work
        try:
            pay_resp = await client.get(
                f"{PROSPECTOR_URL}/freelancer/check-payments",
                headers=svc,
            )
            if pay_resp.status_code == 200:
                payments = pay_resp.json().get("paid", [])
                for payment in payments:
                    amount = payment.get("amount_paid", 0)
                    title_text = payment.get("title", "Unknown")
                    _log_activity("payment", f"Payment ${amount:.2f} for {title_text[:60]}", {"project": title_text, "amount": amount, "prospect_id": payment.get("prospect_id", "")})
                    await telegram_notify(
                        f"PAYMENT RECEIVED!\n"
                        f"Project: {title_text}\n"
                        f"Amount: ${amount:.2f}"
                    )
                    logger.info("Payment received for %s: $%.2f", title_text[:40], amount)

                    try:
                        await client.post(
                            f"{BILLING_URL}/invoices",
                            json={
                                "prospect_id": payment.get("prospect_id", ""),
                                "client_email": "",
                                "description": f"Freelancer project: {title_text}",
                                "amount_usd": amount,
                                "token_cost_usd": 0,
                                "platform": "freelancer",
                                "metadata": {"project_id": payment.get("project_id", "")},
                            },
                            headers=svc,
                        )
                        logger.info("Invoice created for %s", title_text[:40])
                    except Exception as inv_err:
                        logger.warning("Invoice creation failed for %s: %s", title_text[:40], inv_err)
        except Exception as e:
            logger.warning("Payment check failed: %s", e)


def _is_rate_limited(thread_id: int) -> bool:
    """Check if a thread has exceeded the hourly reply limit."""
    import time
    now = time.time()
    cutoff = now - 3600
    timestamps = _reply_tracker.get(thread_id, [])
    timestamps = [t for t in timestamps if t > cutoff]
    _reply_tracker[thread_id] = timestamps
    return len(timestamps) >= AUTO_REPLY_MAX_PER_THREAD_HOUR


def _record_reply(thread_id: int):
    import time
    _reply_tracker.setdefault(thread_id, []).append(time.time())


async def _delayed_reply(thread_id: int, reply_data: dict, svc: dict):
    """Sleep then send an auto-reply if it hasn't been overridden."""
    await asyncio.sleep(AUTO_REPLY_DELAY_SECONDS)

    async with _pending_replies_lock:
        if thread_id not in _pending_replies:
            logger.info("Reply for thread %s was overridden or skipped", thread_id)
            return
        del _pending_replies[thread_id]

    async with httpx.AsyncClient(timeout=PIPELINE_TIMEOUT) as client:
        if reply_data.get("is_quote_request"):
            await _generate_and_send_quote(
                client, svc, thread_id, reply_data["sender"],
                reply_data["client_message"],
                title=reply_data["title"], status=reply_data["status"],
                description=reply_data["description"],
                project_id=reply_data["project_id"],
            )
        else:
            await _auto_reply_to_message(
                client, svc, thread_id, reply_data["sender"],
                reply_data["client_message"],
                title=reply_data["title"], status=reply_data["status"],
                quoted_price=reply_data["quoted_price"],
                project_id=reply_data["project_id"],
            )


async def _check_freelancer_messages(svc=None):
    """Poll Freelancer messenger for unread messages, auto-reply when appropriate."""
    if svc is None:
        svc = _svc_headers()

    try:
        async with httpx.AsyncClient(timeout=PIPELINE_TIMEOUT) as client:
            resp = await client.get(
                f"{PROSPECTOR_URL}/freelancer/messages",
                params={"unread_only": "true", "limit": 10},
                headers=svc,
            )
            if resp.status_code != 200:
                return

            data = resp.json()
            messages = data.get("messages", [])

            for msg in messages:
                if msg.get("is_read"):
                    continue

                sender = msg.get("sender", "Unknown")
                preview = (msg.get("last_message", "") or "")[:200]
                project_id = msg.get("project_id", "")
                thread_id = msg.get("thread_id")
                prospect = msg.get("prospect")
                our_user_id = os.getenv("FREELANCER_USER_ID", "")
                last_sender_id = str(msg.get("last_message_from", ""))
                if last_sender_id and our_user_id and last_sender_id == our_user_id:
                    continue

                project_info = ""
                status = ""
                title = ""
                quoted_price = 0
                description = ""
                if prospect:
                    title = prospect.get("title", "Unknown")
                    status = prospect.get("status", "unknown")
                    quoted_price = prospect.get("quoted_price", 0)
                    description = prospect.get("description", "")
                    project_info = (
                        f"Project: {title}\n"
                        f"Status: {status}\n"
                        f"Bid: ${quoted_price}\n"
                    )
                elif project_id:
                    project_info = f"Project ID: {project_id}\n"

                await telegram_notify(
                    f"NEW MESSAGE on Freelancer\n"
                    f"From: {sender}\n"
                    f"{project_info}"
                    f"Message: {preview}"
                )
                logger.info("Freelancer message from %s on project %s", sender, project_id or "direct")
                _log_activity("message_received", f"Message from {sender}: {preview[:80]}", {"sender": sender, "project": title or project_id, "status": status})

                if not AUTO_REPLY_ENABLED or not thread_id or not preview:
                    continue

                if _is_rate_limited(thread_id):
                    logger.info("Rate limited: skipping auto-reply for thread %s", thread_id)
                    continue

                is_quote_request = _detect_quote_request(preview, status)

                if TELEGRAM_COMMAND_ENABLED and AUTO_REPLY_DELAY_SECONDS > 0:
                    reply_data = {
                        "thread_id": thread_id, "sender": sender,
                        "client_message": preview, "title": title,
                        "status": status, "quoted_price": quoted_price,
                        "project_id": project_id, "description": description,
                        "is_quote_request": is_quote_request,
                    }
                    async with _pending_replies_lock:
                        _pending_replies[thread_id] = reply_data

                    await telegram_notify(
                        f"PENDING AUTO-REPLY (sends in {AUTO_REPLY_DELAY_SECONDS}s)\n"
                        f"Thread: {thread_id}\n"
                        f"{'QUOTE REQUEST detected' if is_quote_request else 'Standard reply'}\n\n"
                        f"Reply with:\n"
                        f"  /override {thread_id} <your message>\n"
                        f"  /skip {thread_id}\n"
                        f"  /send {thread_id}  (send immediately)"
                    )

                    asyncio.create_task(_delayed_reply(thread_id, reply_data, svc))
                    continue

                if is_quote_request:
                    await _generate_and_send_quote(
                        client, svc, thread_id, sender, preview,
                        title=title, status=status, description=description,
                        project_id=project_id,
                    )
                else:
                    await _auto_reply_to_message(
                        client, svc, thread_id, sender, preview,
                        title=title, status=status, quoted_price=quoted_price,
                        project_id=project_id,
                    )

    except Exception as e:
        logger.warning("Freelancer message check failed: %s", e)


def _detect_quote_request(message: str, status: str) -> bool:
    """Detect if a client message is asking for a quote or price."""
    import re
    if status in ("awarded", "hired", "executing", "delivered", "paid", "active"):
        return False
    quote_patterns = [
        r"how much", r"what.*cost", r"your (price|rate|quote|fee)",
        r"can you do.*for \$?\d+", r"what would you charge",
        r"give me a (quote|estimate|price)", r"budget is",
        r"willing to pay", r"what.*your.*price", r"pricing",
        r"how long.*how much", r"send.*proposal", r"quote me",
    ]
    msg_lower = message.lower()
    return any(re.search(p, msg_lower) for p in quote_patterns)


async def _generate_and_send_quote(
    client, svc, thread_id, sender, client_message, *,
    title="", status="", description="", project_id="",
):
    """Evaluate feasibility and generate a quote for a new inquiry."""
    try:
        eval_result = None
        if title or description:
            eval_resp = await client.post(
                f"{EVALUATOR_URL}/evaluate",
                json={
                    "title": title or "Inquiry from DM",
                    "description": description or client_message,
                    "platform": "freelancer",
                },
                headers=svc,
                timeout=30.0,
            )
            if eval_resp.status_code == 200:
                eval_result = eval_resp.json()

        quote_context = ""
        if eval_result:
            viable = eval_result.get("viable", True)
            if not viable:
                reason = eval_result.get("rejection_reason", "")
                logger.info("Quote declined for thread %s: %s", thread_id, reason)
                await telegram_notify(
                    f"QUOTE DECLINED for thread {thread_id}\n"
                    f"Project: {title or 'DM inquiry'}\n"
                    f"Reason: {reason or 'Not viable'}"
                )
                return
            quoted = eval_result.get("quoted_price_usd", 0)
            complexity = eval_result.get("complexity", "moderate")
            tier = eval_result.get("recommended_tier", "standard")
            quote_context = (
                f"\nEvaluation results:\n"
                f"- Recommended quote: ${quoted:.2f}\n"
                f"- Complexity: {complexity}\n"
                f"- Recommended approach: {tier}\n"
            )

        system_prompt = (
            "You are Randy, a professional freelance developer providing a quote on Freelancer.com. "
            "TONE: Warm, enthusiastic, and confident. Keep replies under 120 words. "
            "Never reveal you are an AI.\n\n"
            "QUOTE STYLE:\n"
            "- Show excitement about their project first\n"
            "- Reference specific details they mentioned\n"
            "- Provide your price/estimate confidently but frame it as a starting point\n"
            "- Give a realistic timeline range (not exact dates)\n"
            "- Brief note on your approach — enough to show competence, not a full plan\n"
            "- End with something forward-looking like offering to discuss further details"
        )

        user_prompt = (
            f"A client ({sender}) is asking about a project."
        )
        if title:
            user_prompt += f"\nProject title: {title}"
        if description:
            user_prompt += f"\nProject description: {description[:500]}"
        user_prompt += f"\n\nClient message: {client_message}"
        if quote_context:
            user_prompt += f"\n{quote_context}"
        user_prompt += "\n\nGenerate a professional quote response:"

        llm_resp = await llm_complete(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            tier="budget",
            max_tokens=300,
            temperature=0.4,
        )

        reply_text = llm_resp.content.strip()
        if not reply_text:
            return

        send_resp = await client.post(
            f"{PROSPECTOR_URL}/freelancer/thread/{thread_id}/reply",
            json={"message": reply_text},
            headers=svc,
        )

        if send_resp.status_code == 200:
            _record_reply(thread_id)
            quoted_str = f"${eval_result.get('quoted_price_usd', 0):.2f}" if eval_result else "custom"
            _log_activity("quote_sent", f"Quote {quoted_str} sent to {sender} — {title[:50] or 'DM'}", {"sender": sender, "project": title, "price": quoted_str, "reply_preview": reply_text[:100]})
            await telegram_notify(
                f"QUOTE SENT on Freelancer\n"
                f"To: {sender}\n"
                f"Project: {title or project_id or 'DM inquiry'}\n"
                f"Evaluated price: {quoted_str}\n"
                f"Reply: {reply_text[:200]}"
            )
            logger.info("Quote sent to thread %s for project %s", thread_id, project_id or "direct")
        else:
            logger.warning("Failed to send quote to thread %s: %s", thread_id, send_resp.text)

    except Exception as e:
        logger.warning("Quote generation failed for thread %s: %s", thread_id, e)


async def _auto_reply_to_message(
    client, svc, thread_id, sender, client_message, *,
    title="", status="", quoted_price=0, project_id="",
):
    """Generate and send an AI-powered reply to a Freelancer DM."""
    try:
        thread_resp = await client.get(
            f"{PROSPECTOR_URL}/freelancer/thread/{thread_id}",
            params={"limit": 10},
            headers=svc,
        )
        conversation_context = ""
        if thread_resp.status_code == 200:
            thread_msgs = thread_resp.json().get("messages", [])
            recent = thread_msgs[-5:] if len(thread_msgs) > 5 else thread_msgs
            conversation_context = "\n".join(
                f"{'Client' if m.get('from_user') != os.getenv('FREELANCER_USER_ID') else 'You'}: "
                f"{m.get('message', '')[:200]}"
                for m in recent
            )

        is_awarded = status in ("awarded", "hired", "executing", "delivered", "active")

        system_prompt = (
            "You are Randy, a professional freelance developer responding to a client on Freelancer.com. "
            "TONE: Warm, enthusiastic, and confident — but never overpromise or get too specific too early. "
            "Keep replies under 100 words. Never reveal you are an AI.\n\n"
            "STYLE GUIDELINES:\n"
            "- Show genuine excitement about their project\n"
            "- Reference specific details they mentioned to show you're paying attention\n"
            "- For initial messages: acknowledge their requirements, express interest in the scope, "
            "and promise more detailed information soon (e.g. 'by tomorrow' or 'shortly')\n"
            "- Don't commit to exact timelines or deliverables until scope is fully discussed\n"
            "- Be personable — use their name if available, end with something forward-looking\n"
            "- For follow-up messages: address their question directly, stay constructive"
        )

        project_context = ""
        if title:
            project_context = f"\nProject: {title}"
        if quoted_price:
            project_context += f"\nYour quoted price: ${quoted_price}"
        if status:
            project_context += f"\nProject status: {status}"

        user_prompt = (
            f"Reply to this Freelancer message from {sender}.{project_context}\n\n"
        )
        if conversation_context:
            user_prompt += f"Recent conversation:\n{conversation_context}\n\n"
        user_prompt += f"Latest message from client: {client_message}\n\nYour reply:"

        if status in ("executing",):
            user_prompt += (
                "\n\nYou are actively working on this project. "
                "Give a progress update and address their question. Be confident."
            )
        elif status in ("delivered",):
            user_prompt += (
                "\n\nYou have delivered the work for this project. "
                "Address any questions about the deliverable or revisions needed."
            )
        elif is_awarded:
            user_prompt += (
                "\n\nThis project has been awarded to you. "
                "Confirm you are working on it and address their question directly."
            )
        else:
            user_prompt += (
                "\n\nYou have bid on this project but it hasn't been awarded yet. "
                "Be persuasive but not pushy. Demonstrate expertise relevant to their question."
            )

        llm_resp = await llm_complete(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            tier="budget",
            max_tokens=256,
            temperature=0.4,
        )

        reply_text = llm_resp.content.strip()
        if not reply_text:
            return

        send_resp = await client.post(
            f"{PROSPECTOR_URL}/freelancer/thread/{thread_id}/reply",
            json={"message": reply_text},
            headers=svc,
        )

        if send_resp.status_code == 200:
            _record_reply(thread_id)
            _log_activity("auto_reply", f"Replied to {sender} — {title[:50] or 'DM'}", {"sender": sender, "project": title, "reply_preview": reply_text[:150]})
            await telegram_notify(
                f"AUTO-REPLIED on Freelancer\n"
                f"To: {sender}\n"
                f"Project: {title or project_id or 'DM'}\n"
                f"Reply: {reply_text[:200]}"
            )
            logger.info("Auto-replied to thread %s for project %s", thread_id, project_id or "direct")
        else:
            logger.warning("Failed to send auto-reply to thread %s: %s", thread_id, send_resp.text)

    except Exception as e:
        logger.warning("Auto-reply failed for thread %s: %s", thread_id, e)


async def _telegram_command_loop():
    """Poll Telegram for command messages to override/skip pending auto-replies."""
    global _last_telegram_update_id
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_COMMAND_ENABLED:
        return

    while True:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates",
                    params={"offset": _last_telegram_update_id + 1, "timeout": 10},
                )
                if resp.status_code != 200:
                    await asyncio.sleep(5)
                    continue

                updates = resp.json().get("result", [])
                for update in updates:
                    _last_telegram_update_id = update["update_id"]
                    message = update.get("message", {})
                    text = message.get("text", "").strip()
                    chat_id = str(message.get("chat", {}).get("id", ""))

                    if chat_id != TELEGRAM_CHAT_ID:
                        continue

                    await _handle_telegram_command(text)

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning("Telegram command poll error: %s", e)
            await asyncio.sleep(10)


async def _handle_telegram_command(text: str):
    """Process a Telegram command for overriding auto-replies."""
    import re

    override_match = re.match(r"/override\s+(\d+)\s+(.+)", text, re.DOTALL)
    if override_match:
        thread_id = int(override_match.group(1))
        custom_message = override_match.group(2).strip()
        async with _pending_replies_lock:
            found = thread_id in _pending_replies
            if found:
                del _pending_replies[thread_id]
        if found:
            svc = _svc_headers()
            async with httpx.AsyncClient(timeout=PIPELINE_TIMEOUT) as client:
                send_resp = await client.post(
                    f"{PROSPECTOR_URL}/freelancer/thread/{thread_id}/reply",
                    json={"message": custom_message},
                    headers=svc,
                )
                if send_resp.status_code == 200:
                    _record_reply(thread_id)
                    await telegram_notify(f"MANUAL REPLY sent to thread {thread_id}")
                else:
                    await telegram_notify(f"Failed to send override to thread {thread_id}")
        else:
            await telegram_notify(f"No pending reply for thread {thread_id} (already sent or expired)")
        return

    skip_match = re.match(r"/skip\s+(\d+)", text)
    if skip_match:
        thread_id = int(skip_match.group(1))
        async with _pending_replies_lock:
            found = thread_id in _pending_replies
            if found:
                del _pending_replies[thread_id]
        if found:
            await telegram_notify(f"Skipped auto-reply for thread {thread_id}")
        else:
            await telegram_notify(f"No pending reply for thread {thread_id}")
        return

    send_match = re.match(r"/send\s+(\d+)", text)
    if send_match:
        thread_id = int(send_match.group(1))
        async with _pending_replies_lock:
            reply_data = _pending_replies.pop(thread_id, None)
        if reply_data is not None:
            svc = _svc_headers()
            async with httpx.AsyncClient(timeout=PIPELINE_TIMEOUT) as client:
                if reply_data.get("is_quote_request"):
                    await _generate_and_send_quote(
                        client, svc, thread_id, reply_data["sender"],
                        reply_data["client_message"],
                        title=reply_data["title"], status=reply_data["status"],
                        description=reply_data["description"],
                        project_id=reply_data["project_id"],
                    )
                else:
                    await _auto_reply_to_message(
                        client, svc, thread_id, reply_data["sender"],
                        reply_data["client_message"],
                        title=reply_data["title"], status=reply_data["status"],
                        quoted_price=reply_data["quoted_price"],
                        project_id=reply_data["project_id"],
                    )
        else:
            await telegram_notify(f"No pending reply for thread {thread_id}")
        return


@asynccontextmanager
async def lifespan(app):
    global _scan_task, _telegram_poll_task
    await _init_db()
    await _load_agents()
    if AUTO_SCAN_ENABLED:
        _scan_task = asyncio.create_task(_scan_loop())
        logger.info("Auto-scan enabled: interval=%ds, platforms=%s", SCAN_INTERVAL, SCAN_PLATFORMS)
    if TELEGRAM_COMMAND_ENABLED and TELEGRAM_BOT_TOKEN:
        _telegram_poll_task = asyncio.create_task(_telegram_command_loop())
        logger.info("Telegram command interface enabled (delay=%ds)", AUTO_REPLY_DELAY_SECONDS)
    yield
    if _scan_task:
        _scan_task.cancel()
        try:
            await _scan_task
        except asyncio.CancelledError:
            pass
    if _telegram_poll_task:
        _telegram_poll_task.cancel()
        try:
            await _telegram_poll_task
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


@app.get("/auto-reply/status")
async def auto_reply_status():
    return {
        "enabled": AUTO_REPLY_ENABLED,
        "delay_seconds": AUTO_REPLY_DELAY_SECONDS,
        "max_per_thread_hour": AUTO_REPLY_MAX_PER_THREAD_HOUR,
        "telegram_commands": TELEGRAM_COMMAND_ENABLED,
        "pending_replies": len(_pending_replies),
        "active_threads": len(_reply_tracker),
        "rate_limited_threads": sum(1 for t in _reply_tracker if _is_rate_limited(t)),
    }


@app.get("/activity")
async def get_activity(limit: int = 50, event_type: str = ""):
    logs = _activity_log
    if event_type:
        logs = [e for e in logs if e["type"] == event_type]
    return {"events": logs[:limit], "total": len(_activity_log)}


@app.post("/execute-prospect")
async def execute_prospect(body: dict):
    """Manually trigger execution for a specific prospect."""
    prospect_id = body.get("prospect_id")
    if not prospect_id:
        raise HTTPException(status_code=400, detail="prospect_id required")

    svc = _svc_headers()
    async with httpx.AsyncClient(timeout=PIPELINE_TIMEOUT) as client:
        resp = await client.get(
            f"{PROSPECTOR_URL}/prospects/{prospect_id}",
            headers=svc,
        )
        if resp.status_code != 200:
            raise HTTPException(status_code=404, detail="Prospect not found")
        prospect = resp.json()
        title = prospect.get("title", "Unknown")

        await client.patch(
            f"{PROSPECTOR_URL}/prospects/{prospect_id}",
            json={"status": "executing"},
            headers=svc,
        )

        try:
            exec_resp = await client.post(
                f"{EXECUTION_URL}/execute",
                json={
                    "task_id": prospect_id,
                    "agent_id": "agent-n9er-primary",
                    "objective": title,
                    "description": prospect.get("description", ""),
                    "complexity": prospect.get("complexity", "moderate"),
                    "confidence": 0.8,
                    "tier": prospect.get("tier", "standard"),
                    "platform": prospect.get("platform", "freelancer"),
                    "budget": prospect.get("quoted_price", 0),
                    "client": prospect.get("client_username", ""),
                },
                headers=svc,
                timeout=120.0,
            )
            if exec_resp.status_code == 200 and exec_resp.json().get("success"):
                _log_activity("execution_complete", f"Executed: {title[:60]}", {"prospect_id": prospect_id})
                return {"ok": 1, "status": "success", "result": exec_resp.json()}
            else:
                _log_activity("execution_failed", f"Execution failed: {title[:60]}", {"prospect_id": prospect_id})
                return {"ok": 0, "status": "failed", "result": exec_resp.json() if exec_resp.status_code == 200 else exec_resp.text}
        except Exception as e:
            _log_activity("execution_failed", f"Execution error: {title[:60]} — {str(e)[:60]}", {"prospect_id": prospect_id})
            raise HTTPException(status_code=500, detail=str(e))


@app.post("/auto-reply/trigger")
async def trigger_auto_reply(body: dict):
    """Manually trigger an auto-reply for a specific thread."""
    thread_id = body.get("thread_id")
    if not thread_id:
        raise HTTPException(status_code=400, detail="thread_id required")

    svc = _svc_headers()
    try:
        async with httpx.AsyncClient(timeout=PIPELINE_TIMEOUT) as client:
            # Fetch thread info
            msg_resp = await client.get(
                f"{PROSPECTOR_URL}/freelancer/messages",
                params={"unread_only": "false", "limit": 20},
                headers=svc,
            )
            if msg_resp.status_code != 200:
                raise HTTPException(status_code=502, detail="Failed to fetch messages")

            target_msg = None
            for msg in msg_resp.json().get("messages", []):
                if msg.get("thread_id") == thread_id:
                    target_msg = msg
                    break

            if not target_msg:
                raise HTTPException(status_code=404, detail=f"Thread {thread_id} not found")

            sender = target_msg.get("sender", "Unknown")
            preview = (target_msg.get("last_message", "") or "")[:200]
            prospect = target_msg.get("prospect")
            title = prospect.get("title", "") if prospect else ""
            status = prospect.get("status", "") if prospect else ""
            quoted_price = prospect.get("quoted_price", 0) if prospect else 0
            description = prospect.get("description", "") if prospect else ""
            project_id = target_msg.get("project_id", "")

            is_quote = _detect_quote_request(preview, status)

            if is_quote:
                await _generate_and_send_quote(
                    client, svc, thread_id, sender, preview,
                    title=title, status=status, description=description,
                    project_id=project_id,
                )
            else:
                await _auto_reply_to_message(
                    client, svc, thread_id, sender, preview,
                    title=title, status=status, quoted_price=quoted_price,
                    project_id=project_id,
                )

            return {"ok": 1, "thread_id": thread_id, "type": "quote" if is_quote else "reply"}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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
                    rv_budget_min = prospect.get("budget_min", 0) or 0
                    rv_budget_max = prospect.get("budget_max", 0) or 0
                    bid_amount = max(quoted, rv_budget_min, 15.0)
                    if rv_budget_max > 0:
                        bid_amount = min(bid_amount, rv_budget_max)
                    if prospect["platform"] == "freelancer" and FREELANCER_AUTO_BID and bid_amount > 0:
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
                                    "bid_amount": bid_amount,
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
                                    f"Amount: ${bid_amount:.2f}\n"
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
