from unittest.mock import patch, AsyncMock, MagicMock

from httpx import ASGITransport, AsyncClient
import pytest

from conftest import load_service

browser = load_service("browser_main", "browser_service")


@pytest.fixture(autouse=True)
def reset_watchers():
    browser.active_watchers.clear()
    yield
    browser.active_watchers.clear()


@pytest.fixture
def client():
    transport = ASGITransport(app=browser.app)
    return AsyncClient(transport=transport, base_url="http://test")


def _mock_orchestrator():
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"status": "task_published", "task_id": "t1"}
    mock_resp.raise_for_status = MagicMock()
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return patch.object(browser.httpx, "AsyncClient", return_value=mock_client)


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
