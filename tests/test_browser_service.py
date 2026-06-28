import hashlib
import hmac
import json
import time
from unittest.mock import patch, AsyncMock, MagicMock

from httpx import ASGITransport, AsyncClient
import pytest

from conftest import load_service

browser = load_service("browser_main", "browser_service")


@pytest.fixture(autouse=True)
async def reset_watchers():
    async with browser._watchers_lock:
        browser.active_watchers.clear()
    yield
    async with browser._watchers_lock:
        browser.active_watchers.clear()


@pytest.fixture
def client():
    transport = ASGITransport(app=browser.app)
    return AsyncClient(transport=transport, base_url="http://test")


def _mock_orchestrator():
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"status": "task_published", "task_id": "t1"}
    mock_resp.raise_for_status = MagicMock()
    return patch.object(browser, "retry_request", AsyncMock(return_value=mock_resp))


async def test_health_returns_ok(client):
    resp = await client.get("/health")
    assert resp.json()["ok"] == 1


async def test_watchers_list(client):
    resp = await client.get("/watchers")
    data = resp.json()
    assert "github" in data["available"]
    assert len(data["available"]) == 8


async def test_activate_watcher(client):
    resp = await client.post("/watchers/github/activate")
    assert resp.json()["status"] == "active"
    watchers = (await client.get("/watchers")).json()
    assert "github" in watchers["active"]


async def test_deactivate_watcher(client):
    async with browser._watchers_lock:
        browser.active_watchers.add("github")
    resp = await client.post("/watchers/github/deactivate")
    assert resp.json()["status"] == "inactive"


async def test_activate_invalid_watcher(client):
    resp = await client.post("/watchers/invalid/activate")
    assert resp.status_code == 404


# --- GitHub webhook tests ---

async def test_github_issue_opened(client):
    with _mock_orchestrator():
        resp = await client.post(
            "/webhooks/github",
            json={
                "action": "opened",
                "issue": {
                    "title": "Bug in login",
                    "number": 42,
                    "html_url": "https://github.com/test/repo/issues/42",
                    "body": "Login fails on mobile",
                    "labels": [{"name": "bug"}],
                },
                "repository": {"full_name": "test/repo"},
            },
            headers={"X-GitHub-Event": "issues"},
        )
    data = resp.json()
    assert data["ok"] == 1
    assert data["event"] == "issue.opened"


async def test_github_pr_opened(client):
    with _mock_orchestrator():
        resp = await client.post(
            "/webhooks/github",
            json={
                "action": "opened",
                "pull_request": {
                    "title": "Add auth module",
                    "number": 10,
                    "html_url": "https://github.com/test/repo/pull/10",
                    "body": "Implements JWT auth",
                    "draft": False,
                },
                "repository": {"full_name": "test/repo"},
            },
            headers={"X-GitHub-Event": "pull_request"},
        )
    data = resp.json()
    assert data["ok"] == 1
    assert data["event"] == "pr.opened"


async def test_github_push_to_main(client):
    with _mock_orchestrator():
        resp = await client.post(
            "/webhooks/github",
            json={
                "ref": "refs/heads/main",
                "commits": [
                    {"message": "fix typo"},
                    {"message": "update docs"},
                ],
                "repository": {"full_name": "test/repo"},
            },
            headers={"X-GitHub-Event": "push"},
        )
    data = resp.json()
    assert data["ok"] == 1
    assert data["event"] == "push"


async def test_github_ignored_event(client):
    resp = await client.post(
        "/webhooks/github",
        json={"action": "closed", "issue": {"title": "old"}},
        headers={"X-GitHub-Event": "issues"},
    )
    assert resp.json()["action"] == "ignored"


# --- Slack webhook tests ---

async def test_slack_url_verification(client):
    resp = await client.post("/webhooks/slack", json={
        "type": "url_verification",
        "challenge": "test_challenge_123",
    })
    assert resp.json()["challenge"] == "test_challenge_123"


async def test_slack_task_message(client):
    with _mock_orchestrator():
        resp = await client.post("/webhooks/slack", json={
            "event": {
                "type": "message",
                "text": "task: Deploy staging environment",
                "channel": "C123",
                "user": "U456",
            },
        })
    data = resp.json()
    assert data["ok"] == 1
    assert data["event"] == "message.task"


async def test_slack_app_mention(client):
    with _mock_orchestrator():
        resp = await client.post("/webhooks/slack", json={
            "event": {
                "type": "app_mention",
                "text": "<@BOT> review the latest PR",
                "channel": "C123",
                "user": "U456",
            },
        })
    data = resp.json()
    assert data["ok"] == 1
    assert data["event"] == "app_mention"


async def test_slack_regular_message_ignored(client):
    resp = await client.post("/webhooks/slack", json={
        "event": {
            "type": "message",
            "text": "just chatting",
            "channel": "C123",
            "user": "U456",
        },
    })
    assert resp.json()["action"] == "ignored"


# --- Generic webhook tests ---

async def test_generic_webhook(client):
    with _mock_orchestrator():
        resp = await client.post("/webhooks/generic", json={
            "objective": "Run database migration",
            "source": "custom",
        })
    assert resp.json()["ok"] == 1


async def test_generic_webhook_missing_objective(client):
    resp = await client.post("/webhooks/generic", json={"data": "nothing"})
    assert resp.status_code == 422


# --- Slack signature verification tests ---

async def test_slack_rejects_invalid_signature(client):
    original_secret = browser.SLACK_SIGNING_SECRET
    try:
        browser.SLACK_SIGNING_SECRET = "test_secret_123"
        resp = await client.post(
            "/webhooks/slack",
            content=json.dumps({"event": {"type": "message", "text": "task: test"}}),
            headers={
                "Content-Type": "application/json",
                "X-Slack-Request-Timestamp": str(int(time.time())),
                "X-Slack-Signature": "v0=invalid_signature",
            },
        )
        assert resp.status_code == 401
    finally:
        browser.SLACK_SIGNING_SECRET = original_secret


async def test_slack_accepts_valid_signature(client):
    original_secret = browser.SLACK_SIGNING_SECRET
    try:
        secret = "test_secret_456"
        browser.SLACK_SIGNING_SECRET = secret
        body = json.dumps({"type": "url_verification", "challenge": "abc"})
        timestamp = str(int(time.time()))
        sig_basestring = f"v0:{timestamp}:{body}"
        signature = "v0=" + hmac.new(
            secret.encode(), sig_basestring.encode(), hashlib.sha256
        ).hexdigest()

        with _mock_orchestrator():
            resp = await client.post(
                "/webhooks/slack",
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Slack-Request-Timestamp": timestamp,
                    "X-Slack-Signature": signature,
                },
            )
        assert resp.status_code == 200
        assert resp.json()["challenge"] == "abc"
    finally:
        browser.SLACK_SIGNING_SECRET = original_secret


async def test_slack_rejects_missing_signature_when_secret_configured(client):
    original_secret = browser.SLACK_SIGNING_SECRET
    try:
        browser.SLACK_SIGNING_SECRET = "configured_secret"
        resp = await client.post(
            "/webhooks/slack",
            json={"event": {"type": "message", "text": "task: test"}},
        )
        assert resp.status_code == 401
    finally:
        browser.SLACK_SIGNING_SECRET = original_secret


# --- GitHub signature verification tests ---

async def test_github_rejects_invalid_signature(client):
    original_secret = browser.GITHUB_WEBHOOK_SECRET
    try:
        browser.GITHUB_WEBHOOK_SECRET = "gh_secret_123"
        body = json.dumps({"action": "opened", "issue": {"title": "test"}})
        resp = await client.post(
            "/webhooks/github",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-GitHub-Event": "issues",
                "X-Hub-Signature-256": "sha256=invalid",
            },
        )
        assert resp.status_code == 401
    finally:
        browser.GITHUB_WEBHOOK_SECRET = original_secret


async def test_github_rejects_missing_signature_when_secret_configured(client):
    original_secret = browser.GITHUB_WEBHOOK_SECRET
    try:
        browser.GITHUB_WEBHOOK_SECRET = "gh_secret_456"
        resp = await client.post(
            "/webhooks/github",
            json={"action": "opened", "issue": {"title": "test"}},
            headers={"X-GitHub-Event": "issues"},
        )
        assert resp.status_code == 401
    finally:
        browser.GITHUB_WEBHOOK_SECRET = original_secret


async def test_github_accepts_valid_signature(client):
    original_secret = browser.GITHUB_WEBHOOK_SECRET
    try:
        secret = "gh_valid_secret"
        browser.GITHUB_WEBHOOK_SECRET = secret
        body = json.dumps({"action": "closed", "issue": {"title": "old"}})
        signature = "sha256=" + hmac.new(
            secret.encode(), body.encode(), hashlib.sha256
        ).hexdigest()

        resp = await client.post(
            "/webhooks/github",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-GitHub-Event": "issues",
                "X-Hub-Signature-256": signature,
            },
        )
        assert resp.status_code == 200
        assert resp.json()["action"] == "ignored"
    finally:
        browser.GITHUB_WEBHOOK_SECRET = original_secret


# --- Signal log tests ---

async def test_signals_endpoint(client):
    """Test the /signals endpoint returns logged signals."""
    browser.signal_log.clear()
    resp = await client.get("/signals")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_signals_populated_after_webhook(client):
    """Test that signals get logged after webhook processing."""
    browser.signal_log.clear()
    with _mock_orchestrator():
        await client.post(
            "/webhooks/github",
            json={
                "action": "opened",
                "issue": {
                    "title": "Bug fix needed",
                    "number": 99,
                    "html_url": "https://github.com/test/repo/issues/99",
                    "body": "Fix this",
                    "labels": [],
                },
                "repository": {"full_name": "test/repo"},
            },
            headers={"X-GitHub-Event": "issues"},
        )
    resp = await client.get("/signals")
    data = resp.json()
    assert len(data) >= 1
    assert data[0]["source"] == "github"
    assert data[0]["event_type"] == "issue.opened"


# --- Forward to pipeline failure tests ---

async def test_forward_to_pipeline_unreachable(client):
    """Test that 503 is returned when the orchestrator is unreachable."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"status": "error"}
    mock_resp.raise_for_status = MagicMock()
    with patch.object(
        browser, "retry_request",
        AsyncMock(side_effect=browser.httpx.RequestError("Connection refused")),
    ):
        resp = await client.post(
            "/webhooks/generic",
            json={"objective": "Run task", "source": "test"},
        )
    assert resp.status_code == 503


# --- GitHub PR ready_for_review event ---

async def test_github_pr_ready_for_review(client):
    """Test handling of pull_request ready_for_review event."""
    with _mock_orchestrator():
        resp = await client.post(
            "/webhooks/github",
            json={
                "action": "ready_for_review",
                "pull_request": {
                    "title": "Feature ready",
                    "number": 20,
                    "html_url": "https://github.com/test/repo/pull/20",
                    "body": "Ready to review",
                    "draft": False,
                },
                "repository": {"full_name": "test/repo"},
            },
            headers={"X-GitHub-Event": "pull_request"},
        )
    data = resp.json()
    assert data["ok"] == 1
    assert data["event"] == "pr.ready_for_review"


# --- GitHub push to non-main branch (ignored) ---

async def test_github_push_non_main_branch(client):
    """Test that pushes to non-main branches are ignored."""
    resp = await client.post(
        "/webhooks/github",
        json={
            "ref": "refs/heads/feature-branch",
            "commits": [{"message": "wip"}],
            "repository": {"full_name": "test/repo"},
        },
        headers={"X-GitHub-Event": "push"},
    )
    data = resp.json()
    assert data["action"] == "ignored"


# --- GitHub push with no commits ---

async def test_github_push_no_commits(client):
    """Test that pushes with no commits are ignored."""
    resp = await client.post(
        "/webhooks/github",
        json={
            "ref": "refs/heads/main",
            "commits": [],
            "repository": {"full_name": "test/repo"},
        },
        headers={"X-GitHub-Event": "push"},
    )
    data = resp.json()
    assert data["action"] == "ignored"


# --- GitHub unknown event type ---

async def test_github_unknown_event_type(client):
    """Test that unknown GitHub event types are ignored."""
    resp = await client.post(
        "/webhooks/github",
        json={"action": "completed", "check_run": {}},
        headers={"X-GitHub-Event": "check_run"},
    )
    data = resp.json()
    assert data["action"] == "ignored"


# --- Slack message with /task prefix ---

async def test_slack_task_with_slash_prefix(client):
    """Test Slack message starting with /task prefix."""
    with _mock_orchestrator():
        resp = await client.post("/webhooks/slack", json={
            "event": {
                "type": "message",
                "text": "/task Deploy to production",
                "channel": "C789",
                "user": "U111",
            },
        })
    data = resp.json()
    assert data["ok"] == 1
    assert data["event"] == "message.task"


# --- Slack bot message ignored ---

async def test_slack_bot_message_ignored(client):
    """Test that messages from bots are ignored."""
    resp = await client.post("/webhooks/slack", json={
        "event": {
            "type": "message",
            "text": "task: do something",
            "channel": "C123",
            "user": "U456",
            "bot_id": "B999",
        },
    })
    data = resp.json()
    assert data["action"] == "ignored"


# --- Generic webhook with title ---

async def test_generic_webhook_with_title(client):
    """Test generic webhook using 'title' field instead of 'objective'."""
    with _mock_orchestrator():
        resp = await client.post("/webhooks/generic", json={
            "title": "Run database backup",
            "source": "cron",
        })
    assert resp.json()["ok"] == 1


# --- Generic webhook with message ---

async def test_generic_webhook_with_message(client):
    """Test generic webhook using 'message' field."""
    with _mock_orchestrator():
        resp = await client.post("/webhooks/generic", json={
            "message": "Trigger cleanup job",
            "source": "scheduler",
        })
    assert resp.json()["ok"] == 1


# --- Slack timestamp-expired signature ---

async def test_slack_signature_expired_timestamp(client):
    """Test that Slack requests with timestamps older than 5 minutes are rejected."""
    original_secret = browser.SLACK_SIGNING_SECRET
    try:
        secret = "test_expire_secret"
        browser.SLACK_SIGNING_SECRET = secret
        body = json.dumps({"event": {"type": "message", "text": "task: test"}})
        # Timestamp from 10 minutes ago
        old_timestamp = str(int(time.time()) - 600)
        sig_basestring = f"v0:{old_timestamp}:{body}"
        signature = "v0=" + hmac.new(
            secret.encode(), sig_basestring.encode(), hashlib.sha256
        ).hexdigest()

        resp = await client.post(
            "/webhooks/slack",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Slack-Request-Timestamp": old_timestamp,
                "X-Slack-Signature": signature,
            },
        )
        assert resp.status_code == 401
    finally:
        browser.SLACK_SIGNING_SECRET = original_secret
