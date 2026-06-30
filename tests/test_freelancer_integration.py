import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_tmpdir = tempfile.mkdtemp()
os.environ["ORCHESTRATOR_DB_PATH"] = os.path.join(_tmpdir, "test_orch_fl.db")

from conftest import load_service

orch = load_service("orch_fl_main", "orchestrator")


@pytest.fixture(autouse=True)
def reset_rate_state():
    orch._platform_call_log.clear()
    orch._pending_messages.clear()
    yield
    orch._platform_call_log.clear()
    orch._pending_messages.clear()


def test_rate_limit_allows_under_threshold():
    orch.PLATFORM_RATE_LIMITS["freelancer"] = 3
    assert orch._check_platform_rate_limit("freelancer") is True
    assert orch._check_platform_rate_limit("freelancer") is True
    assert orch._check_platform_rate_limit("freelancer") is True


def test_rate_limit_blocks_over_threshold():
    orch.PLATFORM_RATE_LIMITS["freelancer"] = 2
    assert orch._check_platform_rate_limit("freelancer") is True
    assert orch._check_platform_rate_limit("freelancer") is True
    assert orch._check_platform_rate_limit("freelancer") is False


def test_rate_limit_unknown_platform_allowed():
    assert orch._check_platform_rate_limit("some_other_platform") is True


@pytest.mark.asyncio
async def test_place_bid_not_configured_returns_error():
    orch.FREELANCER_LIVE = False
    client = AsyncMock()
    result = await orch._freelancer_place_bid(client, {"id": "p1", "job_id": "123"}, "proposal", 50)
    assert result == {"ok": 0, "error": "freelancer_not_configured"}
    client.post.assert_not_called()


@pytest.mark.asyncio
async def test_place_bid_success():
    orch.FREELANCER_LIVE = True
    orch.FREELANCER_OAUTH_TOKEN = "tok"
    orch.FREELANCER_USER_ID = "999"
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"result": {"id": 555}}
    client = AsyncMock()
    client.post.return_value = mock_resp
    result = await orch._freelancer_place_bid(client, {"id": "p1", "job_id": "123"}, "proposal", 50)
    assert result == {"ok": 1, "bid_id": 555}
    orch.FREELANCER_LIVE = False


@pytest.mark.asyncio
async def test_place_bid_rate_limited():
    orch.FREELANCER_LIVE = True
    orch.FREELANCER_OAUTH_TOKEN = "tok"
    orch.FREELANCER_USER_ID = "999"
    orch.PLATFORM_RATE_LIMITS["freelancer"] = 1
    orch._check_platform_rate_limit("freelancer")
    client = AsyncMock()
    result = await orch._freelancer_place_bid(client, {"id": "p1", "job_id": "123"}, "proposal", 50)
    assert result == {"ok": 0, "error": "rate_limited"}
    client.post.assert_not_called()
    orch.FREELANCER_LIVE = False
    orch.PLATFORM_RATE_LIMITS["freelancer"] = 20


@pytest.mark.asyncio
async def test_check_awarded_true():
    orch.FREELANCER_LIVE = True
    orch.FREELANCER_OAUTH_TOKEN = "tok"
    orch.FREELANCER_USER_ID = "999"
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"result": {"bids": [{"award_status": "awarded"}]}}
    client = AsyncMock()
    client.get.return_value = mock_resp
    result = await orch._freelancer_check_awarded(client, {"id": "p1", "job_id": "123"})
    assert result is True
    orch.FREELANCER_LIVE = False


@pytest.mark.asyncio
async def test_check_awarded_false_when_not_configured():
    orch.FREELANCER_LIVE = False
    client = AsyncMock()
    result = await orch._freelancer_check_awarded(client, {"id": "p1", "job_id": "123"})
    assert result is False
    client.get.assert_not_called()


@pytest.mark.asyncio
async def test_check_messages_filters_own_messages():
    orch.FREELANCER_LIVE = True
    orch.FREELANCER_OAUTH_TOKEN = "tok"
    orch.FREELANCER_USER_ID = "999"
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "result": {
            "threads": [
                {
                    "id": 1,
                    "messages": [
                        {"from_user": 999, "message": "our own reply"},
                        {"from_user": 42, "message": "client question"},
                    ],
                }
            ]
        }
    }
    client = AsyncMock()
    client.get.return_value = mock_resp
    result = await orch._freelancer_check_messages(client, {"id": "p1", "job_id": "123"})
    assert len(result) == 1
    assert result[0]["message"] == "client question"
    orch.FREELANCER_LIVE = False


@pytest.mark.asyncio
async def test_auto_apply_passes_real_proposal_text_with_portfolio():
    """Regression test: agent_execution returns the proposal under the 'proposal'
    key, not 'proposal_text'/'text'. The live bid must receive the real text."""
    orch.FREELANCER_LIVE = True
    orch.FREELANCER_OAUTH_TOKEN = "tok"
    orch.FREELANCER_USER_ID = "999"
    orch.PORTFOLIO_URL = "https://example.com/portfolio"

    proposal_resp = MagicMock()
    proposal_resp.raise_for_status = MagicMock()
    proposal_resp.json.return_value = {"ok": 1, "proposal": "Here is my pitch.", "mode": "live"}

    patch_client = AsyncMock()
    patch_client.post.return_value = proposal_resp
    patch_client.patch = AsyncMock()

    captured = {}

    async def fake_place_bid(client_, prospect, proposal_text, amount):
        captured["proposal_text"] = proposal_text
        return {"ok": 1, "bid_id": 1}

    with patch.object(orch, "_freelancer_place_bid", fake_place_bid):
        prospect = {"id": "p1", "job_id": "123", "platform": "freelancer",
                    "title": "Build a thing", "skills": "coding", "budget_max": 100}
        result = await orch._auto_apply_prospect(patch_client, prospect, {})

    assert result["ok"] == 1
    assert "Here is my pitch." in captured["proposal_text"]
    assert "https://example.com/portfolio" in captured["proposal_text"]

    orch.FREELANCER_LIVE = False
    orch.PORTFOLIO_URL = ""


def test_pending_messages_endpoint():
    from starlette.testclient import TestClient

    orch._pending_messages["prospect-1"] = [{"message": "hello"}]
    with TestClient(orch.app) as ac:
        resp = ac.get("/messages/pending")
        assert resp.status_code == 200
        data = resp.json()
        assert any(d["prospect_id"] == "prospect-1" for d in data)

        ack_resp = ac.post("/messages/prospect-1/ack")
        assert ack_resp.status_code == 200
        assert "prospect-1" not in orch._pending_messages
