import os
import logging
import hashlib
import hmac

from fastapi import FastAPI, HTTPException, Request, Header
import httpx

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("browser_service")

app = FastAPI(title="Verixio Browser Service")

ORCHESTRATOR_URL = os.getenv("ORCHESTRATOR_URL", "http://localhost:9000")
GITHUB_WEBHOOK_SECRET = os.getenv("GITHUB_WEBHOOK_SECRET", "")
SLACK_SIGNING_SECRET = os.getenv("SLACK_SIGNING_SECRET", "")

active_watchers = set()


@app.get("/health")
async def health():
    return {"ok": 1, "service": "browser", "active_watchers": list(active_watchers)}


@app.get("/watchers")
async def list_watchers():
    return {
        "available": [
            "gmail", "drive", "slack", "notion",
            "airtable", "asana", "trello", "github",
        ],
        "active": list(active_watchers),
    }


@app.post("/watchers/{name}/activate")
async def activate_watcher(name: str):
    valid = {"gmail", "drive", "slack", "notion", "airtable", "asana", "trello", "github"}
    if name not in valid:
        raise HTTPException(status_code=404, detail=f"Unknown watcher: {name}")
    active_watchers.add(name)
    logger.info("Activated watcher: %s", name)
    return {"ok": 1, "watcher": name, "status": "active"}


@app.post("/watchers/{name}/deactivate")
async def deactivate_watcher(name: str):
    active_watchers.discard(name)
    logger.info("Deactivated watcher: %s", name)
    return {"ok": 1, "watcher": name, "status": "inactive"}


async def _forward_to_pipeline(task: dict):
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(f"{ORCHESTRATOR_URL}/pipeline", json=task)
            resp.raise_for_status()
            result = resp.json()
            logger.info("Forwarded task to pipeline: %s", result.get("task_id", "unknown"))
            return result
    except httpx.RequestError as e:
        logger.error("Failed to forward to pipeline: %s", e)
        raise HTTPException(status_code=503, detail="Orchestrator unreachable")


# --- GitHub Webhook ---

@app.post("/webhooks/github")
async def github_webhook(
    request: Request,
    x_github_event: str = Header(None, alias="X-GitHub-Event"),
    x_hub_signature_256: str = Header(None, alias="X-Hub-Signature-256"),
):
    body = await request.body()

    if GITHUB_WEBHOOK_SECRET and x_hub_signature_256:
        expected = "sha256=" + hmac.new(
            GITHUB_WEBHOOK_SECRET.encode(), body, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected, x_hub_signature_256):
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
            result = await _forward_to_pipeline(task)
            return {"ok": 1, "event": "push", "pipeline": result}

    logger.info("GitHub event %s (action=%s) — no task created",
                event_type, payload.get("action"))
    return {"ok": 1, "event": event_type, "action": "ignored"}


# --- Slack Webhook ---

@app.post("/webhooks/slack")
async def slack_webhook(request: Request):
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
    result = await _forward_to_pipeline(task)
    return {"ok": 1, "event": "generic", "pipeline": result}
