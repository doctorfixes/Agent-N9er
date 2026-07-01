import os
import sys
import time
import asyncio
import logging
import hashlib
import hmac
import datetime
from collections import deque

from fastapi import FastAPI, HTTPException, Request, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared.security import (
    RequestIDMiddleware, RateLimitMiddleware, APIKeyMiddleware,
    get_service_headers,
)
from shared.config import (
    DEFAULT_TIMEOUT, RATE_LIMIT_MAX_REQUESTS,
    RATE_LIMIT_WINDOW_SECONDS, CORS_ORIGINS,
)
from shared.retry import retry_request

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("browser_service")

ORCHESTRATOR_URL = os.getenv("ORCHESTRATOR_URL", "http://localhost:9000")
GITHUB_WEBHOOK_SECRET = os.getenv("GITHUB_WEBHOOK_SECRET", "")
SLACK_SIGNING_SECRET = os.getenv("SLACK_SIGNING_SECRET", "")

app = FastAPI(title="Agent N9er Browser Service")

app.add_middleware(RequestIDMiddleware)
app.add_middleware(RateLimitMiddleware, max_requests=RATE_LIMIT_MAX_REQUESTS, window_seconds=RATE_LIMIT_WINDOW_SECONDS)
app.add_middleware(APIKeyMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

active_watchers = set()
signal_log: deque = deque(maxlen=100)


def _log_signal(source: str, event_type: str, objective: str) -> None:
    signal_log.appendleft({
        "ts": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
        "source": source,
        "event_type": event_type,
        "objective": objective,
    })

_watchers_lock = asyncio.Lock()

VALID_WATCHERS = {"gmail", "drive", "slack", "notion", "airtable", "asana", "trello", "github"}


class GenericWebhookRequest(BaseModel):
    objective: str = None
    title: str = None
    message: str = None
    source: str = "webhook"
    inputs: dict = {}


@app.get("/health")
async def health():
    async with _watchers_lock:
        watchers = list(active_watchers)
    return {"ok": 1, "service": "browser", "active_watchers": watchers}


@app.get("/watchers")
async def list_watchers():
    async with _watchers_lock:
        active = list(active_watchers)
    return {
        "available": sorted(VALID_WATCHERS),
        "active": active,
    }


@app.post("/watchers/{name}/activate")
async def activate_watcher(name: str):
    if name not in VALID_WATCHERS:
        raise HTTPException(status_code=404, detail=f"Unknown watcher: {name}")
    async with _watchers_lock:
        active_watchers.add(name)
    logger.info("Activated watcher: %s", name)
    return {"ok": 1, "watcher": name, "status": "active"}


@app.post("/watchers/{name}/deactivate")
async def deactivate_watcher(name: str):
    async with _watchers_lock:
        active_watchers.discard(name)
    logger.info("Deactivated watcher: %s", name)
    return {"ok": 1, "watcher": name, "status": "inactive"}


@app.get("/signals")
async def list_signals():
    return list(signal_log)


async def _forward_to_pipeline(task: dict):
    svc = get_service_headers()
    try:
        resp = await retry_request(
            "POST", f"{ORCHESTRATOR_URL}/pipeline",
            timeout=DEFAULT_TIMEOUT, headers=svc, json=task,
        )
        result = resp.json()
        logger.info("Forwarded task to pipeline: %s", result.get("task_id", "unknown"))
        return result
    except httpx.RequestError as e:
        logger.error("Failed to forward to pipeline after retries: %s", e)
        raise HTTPException(status_code=503, detail="Orchestrator unreachable")


def _verify_slack_signature(body: bytes, timestamp: str, signature: str) -> bool:
    if not SLACK_SIGNING_SECRET:
        return False
    if abs(time.time() - int(timestamp)) > 300:
        return False
    sig_basestring = f"v0:{timestamp}:{body.decode('utf-8')}"
    expected = "v0=" + hmac.new(
        SLACK_SIGNING_SECRET.encode(), sig_basestring.encode(), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def _verify_github_signature(body: bytes, signature: str) -> bool:
    if not GITHUB_WEBHOOK_SECRET:
        return False
    expected = "sha256=" + hmac.new(
        GITHUB_WEBHOOK_SECRET.encode(), body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


# --- GitHub Webhook ---

@app.post("/webhooks/github")
async def github_webhook(
    request: Request,
    x_github_event: str = Header(None, alias="X-GitHub-Event"),
    x_hub_signature_256: str = Header(None, alias="X-Hub-Signature-256"),
):
    body = await request.body()

    if GITHUB_WEBHOOK_SECRET:
        if not x_hub_signature_256 or not _verify_github_signature(body, x_hub_signature_256):
            raise HTTPException(status_code=401, detail="Invalid signature")

    payload = await request.json()
    event_type = x_github_event or "unknown"

    if event_type == "issues":
        action = payload.get("action")
        issue = payload.get("issue", {})
        if action == "opened":
            task = {
                "objective": f"[GitHub Issue] {issue.get('title', 'Untitled')}",
                "source": "github",
                "inputs": {
                    "issue_number": issue.get("number"),
                    "repo": payload.get("repository", {}).get("full_name"),
                    "url": issue.get("html_url"),
                    "body": (issue.get("body") or "")[:500],
                    "labels": [l["name"] for l in issue.get("labels", [])],
                },
            }
            _log_signal("github", "issue.opened", task["objective"])
            result = await _forward_to_pipeline(task)
            return {"ok": 1, "event": "issue.opened", "pipeline": result}

    elif event_type == "pull_request":
        action = payload.get("action")
        pr = payload.get("pull_request", {})
        if action in ("opened", "ready_for_review"):
            task = {
                "objective": f"[GitHub PR] Review: {pr.get('title', 'Untitled')}",
                "source": "github",
                "inputs": {
                    "pr_number": pr.get("number"),
                    "repo": payload.get("repository", {}).get("full_name"),
                    "url": pr.get("html_url"),
                    "body": (pr.get("body") or "")[:500],
                    "draft": pr.get("draft", False),
                },
            }
            _log_signal("github", f"pr.{action}", task["objective"])
            result = await _forward_to_pipeline(task)
            return {"ok": 1, "event": f"pr.{action}", "pipeline": result}

    elif event_type == "push":
        commits = payload.get("commits", [])
        ref = payload.get("ref", "")
        if commits and "main" in ref:
            task = {
                "objective": f"[GitHub Push] {len(commits)} commit(s) to {ref}",
                "source": "github",
                "inputs": {
                    "repo": payload.get("repository", {}).get("full_name"),
                    "ref": ref,
                    "commit_count": len(commits),
                    "head_message": commits[-1].get("message", "")[:200],
                },
            }
            _log_signal("github", "push", task["objective"])
            result = await _forward_to_pipeline(task)
            return {"ok": 1, "event": "push", "pipeline": result}

    logger.info("GitHub event %s (action=%s) — no task created",
                event_type, payload.get("action"))
    return {"ok": 1, "event": event_type, "action": "ignored"}


# --- Slack Webhook ---

@app.post("/webhooks/slack")
async def slack_webhook(
    request: Request,
    x_slack_request_timestamp: str = Header(None, alias="X-Slack-Request-Timestamp"),
    x_slack_signature: str = Header(None, alias="X-Slack-Signature"),
):
    body = await request.body()

    if SLACK_SIGNING_SECRET:
        if not x_slack_request_timestamp or not x_slack_signature:
            raise HTTPException(status_code=401, detail="Missing Slack signature headers")
        if not _verify_slack_signature(body, x_slack_request_timestamp, x_slack_signature):
            raise HTTPException(status_code=401, detail="Invalid Slack signature")

    payload = await request.json()

    if payload.get("type") == "url_verification":
        return {"challenge": payload.get("challenge")}

    event = payload.get("event", {})
    event_type = event.get("type")

    if event_type == "message" and not event.get("bot_id"):
        text = event.get("text", "")
        channel = event.get("channel", "")
        user = event.get("user", "")

        if text.lower().startswith("task:") or text.lower().startswith("/task"):
            objective = text.split(":", 1)[-1].strip() if ":" in text else text[5:].strip()
            task = {
                "objective": f"[Slack] {objective}",
                "source": "slack",
                "inputs": {
                    "channel": channel,
                    "user": user,
                    "raw_text": text[:500],
                },
            }
            _log_signal("slack", "message.task", task["objective"])
            result = await _forward_to_pipeline(task)
            return {"ok": 1, "event": "message.task", "pipeline": result}

    elif event_type == "app_mention":
        text = event.get("text", "")
        task = {
            "objective": f"[Slack Mention] {text[:200]}",
            "source": "slack",
            "inputs": {
                "channel": event.get("channel", ""),
                "user": event.get("user", ""),
                "raw_text": text[:500],
            },
        }
        _log_signal("slack", "app_mention", task["objective"])
        result = await _forward_to_pipeline(task)
        return {"ok": 1, "event": "app_mention", "pipeline": result}

    return {"ok": 1, "event": event_type, "action": "ignored"}


# --- Generic Webhook ---

@app.post("/webhooks/generic")
async def generic_webhook(payload: dict):
    objective = payload.get("objective") or payload.get("title") or payload.get("message")
    if not objective:
        raise HTTPException(status_code=422, detail="Payload must include 'objective', 'title', or 'message'")

    source = payload.get("source", "webhook")
    task = {
        "objective": objective,
        "source": source,
        "inputs": payload.get("inputs", payload),
    }
    _log_signal(source, "generic", objective)
    result = await _forward_to_pipeline(task)
    return {"ok": 1, "event": "generic", "pipeline": result}


if __name__ == "__main__":
    port = int(os.getenv("BROWSER_SERVICE_PORT", "8000"))
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=port)
