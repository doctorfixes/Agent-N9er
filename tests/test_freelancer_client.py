"""Tests for shared/freelancer_client.py and bid_service freelancer endpoints."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from shared.freelancer_client import (
    FreelancerClient,
    build_authorize_url,
    exchange_code_for_token,
    refresh_access_token,
    FREELANCER_API_BASE,
    FREELANCER_OAUTH_URL,
    FREELANCER_AUTH_URL,
)

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_transport():
    """Fully-wired async context manager that yields a mock httpx.AsyncClient."""
    mock_http = AsyncMock(spec=httpx.AsyncClient)
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=False)
    return mock_http


def _make_success_response(status_code=200, json_data=None):
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json = MagicMock(return_value=json_data or {"status": "success", "result": {}})
    resp.raise_for_status = MagicMock()
    return resp


def _make_freelancer_success(result_data: dict):
    """Build a successful Freelancer-envelope response."""
    return _make_success_response(json_data={"status": "success", "result": result_data})


def _make_error_response(status_code, detail=""):
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.text = detail
    resp.json = MagicMock(return_value={"status": "error", "error_message": detail})

    def raise_it():
        raise httpx.HTTPStatusError(detail, request=MagicMock(), response=resp)

    resp.raise_for_status = raise_it
    return resp


# ============================================================================
# FreelancerClient — constructor
# ============================================================================


class TestFreelancerClientConstructor:
    def test_sets_default_api_url(self):
        client = FreelancerClient(access_token="tok_abc")
        assert client.access_token == "tok_abc"
        assert client.base_url == FREELANCER_API_BASE
        assert "Freelancer-OAuth-V1" in client._headers()
        assert client._headers()["Freelancer-OAuth-V1"] == "tok_abc"

    def test_accepts_custom_base_url(self):
        client = FreelancerClient(access_token="tok_abc", base_url="https://custom.api.com/")
        assert client.base_url == "https://custom.api.com/"

    def test_headers_include_content_type(self):
        client = FreelancerClient(access_token="tok_abc")
        h = client._headers()
        assert h["Content-Type"] == "application/json"
        assert h["User-Agent"] == "AgentN9er/1.0"


# ============================================================================
# FreelancerClient — submit_proposal
# ============================================================================


class TestSubmitProposal:
    async def test_submit_fixed_bid(self, mock_transport):
        result_data = {"id": 12345, "project_id": 67890, "amount": 500.0, "period": 14}
        mock_transport.request = AsyncMock(return_value=_make_freelancer_success({"bid": result_data}))

        client = FreelancerClient("tok_abc")
        with patch("httpx.AsyncClient", return_value=mock_transport):
            result = await client.submit_proposal(
                job_id="67890",
                cover_letter="I am experienced in this.",
                bid_amount=500.0,
                bid_type="fixed",
                estimated_duration="2 weeks",
            )

        assert result["id"] == 12345
        assert result["amount"] == 500.0
        # Verify payload
        call_args = mock_transport.request.call_args
        assert call_args[0][0] == "POST"
        assert "bids/" in call_args[0][1]
        body = call_args[1]["json"]["bid"]
        assert body["project_id"] == 67890
        assert body["amount"] == 500.0
        assert body["milestone_percentage"] == 100
        assert body["period"] == 14

    async def test_submit_hourly_bid(self, mock_transport):
        mock_transport.request = AsyncMock(
            return_value=_make_freelancer_success({"bid": {"id": 999, "amount": 25.0}})
        )
        client = FreelancerClient("tok_abc")
        with patch("httpx.AsyncClient", return_value=mock_transport):
            result = await client.submit_proposal(
                job_id="123", cover_letter="test", bid_amount=25.0, bid_type="hourly"
            )
        assert result["id"] == 999
        body = mock_transport.request.call_args[1]["json"]["bid"]
        assert body["milestone_percentage"] == 0

    async def test_submit_parses_days_duration(self, mock_transport):
        mock_transport.request = AsyncMock(
            return_value=_make_freelancer_success({"bid": {"id": 1}})
        )
        client = FreelancerClient("tok_abc")
        with patch("httpx.AsyncClient", return_value=mock_transport):
            await client.submit_proposal(
                job_id="1", cover_letter="test", bid_amount=100.0, estimated_duration="7 days"
            )
        body = mock_transport.request.call_args[1]["json"]["bid"]
        assert body["period"] == 7

    async def test_submit_parses_weeks_duration(self, mock_transport):
        mock_transport.request = AsyncMock(
            return_value=_make_freelancer_success({"bid": {"id": 1}})
        )
        client = FreelancerClient("tok_abc")
        with patch("httpx.AsyncClient", return_value=mock_transport):
            await client.submit_proposal(
                job_id="1", cover_letter="test", bid_amount=100.0, estimated_duration="3 weeks"
            )
        body = mock_transport.request.call_args[1]["json"]["bid"]
        assert body["period"] == 21

    async def test_submit_defaults_period(self, mock_transport):
        mock_transport.request = AsyncMock(
            return_value=_make_freelancer_success({"bid": {"id": 1}})
        )
        client = FreelancerClient("tok_abc")
        with patch("httpx.AsyncClient", return_value=mock_transport):
            await client.submit_proposal(
                job_id="1", cover_letter="test", bid_amount=100.0
            )
        body = mock_transport.request.call_args[1]["json"]["bid"]
        assert body["period"] == 14

    async def test_submit_raises_on_401(self, mock_transport):
        mock_transport.request = AsyncMock(
            return_value=_make_error_response(401, "Invalid token")
        )
        client = FreelancerClient("tok_bad")
        with patch("httpx.AsyncClient", return_value=mock_transport), pytest.raises(
            httpx.HTTPStatusError, match="Freelancer token expired"
        ):
            await client.submit_proposal(job_id="1", cover_letter="test", bid_amount=100.0)

    async def test_submit_raises_on_429(self, mock_transport):
        mock_transport.request = AsyncMock(
            return_value=_make_error_response(429, "Rate limited")
        )
        client = FreelancerClient("tok_abc")
        with patch("httpx.AsyncClient", return_value=mock_transport), pytest.raises(
            httpx.HTTPStatusError, match="Freelancer rate limit"
        ):
            await client.submit_proposal(job_id="1", cover_letter="test", bid_amount=100.0)


# ============================================================================
# FreelancerClient — withdraw / update
# ============================================================================


class TestWithdrawProposal:
    async def test_withdraw_success(self, mock_transport):
        mock_transport.request = AsyncMock(return_value=_make_freelancer_success({}))
        client = FreelancerClient("tok_abc")
        with patch("httpx.AsyncClient", return_value=mock_transport):
            result = await client.withdraw_proposal("bid_456", "Not a fit")
        assert result["status"] == "withdrawn"
        assert result["bid_id"] == "bid_456"
        # Verify DELETE endpoint
        call_args = mock_transport.request.call_args
        assert call_args[0][0] == "DELETE"
        assert "bids/bid_456" in call_args[0][1]


class TestUpdateProposal:
    async def test_update_success(self, mock_transport):
        mock_transport.request = AsyncMock(
            return_value=_make_freelancer_success({"bid": {"id": "bid_456", "amount": 600.0}})
        )
        client = FreelancerClient("tok_abc")
        with patch("httpx.AsyncClient", return_value=mock_transport):
            result = await client.update_proposal("bid_456", {"amount": 600.0})
        assert result["amount"] == 600.0
        call_args = mock_transport.request.call_args
        assert call_args[0][0] == "PUT"
        assert "bids/bid_456" in call_args[0][1]


# ============================================================================
# FreelancerClient — balance & stats
# ============================================================================


class TestGetBalance:
    async def test_returns_balance(self, mock_transport):
        mock_transport.request = AsyncMock(
            return_value=_make_freelancer_success({
                "profile": {"balance": 150.50, "currency": {"code": "USD"}}
            })
        )
        client = FreelancerClient("tok_abc")
        with patch("httpx.AsyncClient", return_value=mock_transport):
            result = await client.get_balance()
        assert result["available"] == 150.50
        assert result["currency"] == "USD"

    async def test_handles_missing_currency(self, mock_transport):
        mock_transport.request = AsyncMock(
            return_value=_make_freelancer_success({
                "profile": {"balance": 50.0}
            })
        )
        client = FreelancerClient("tok_abc")
        with patch("httpx.AsyncClient", return_value=mock_transport):
            result = await client.get_balance()
        assert result["available"] == 50.0
        assert result["currency"] == "USD"  # default


class TestGetStats:
    async def test_returns_stats(self, mock_transport):
        mock_transport.request = AsyncMock(
            return_value=_make_freelancer_success({
                "profile": {
                    "id": 12345,
                    "username": "dev_agent",
                    "jobs_completed": 42,
                    "jobs_in_progress": 3,
                    "avg_bid_amount": 250.0,
                    "registration_date": "2024-01-15",
                    "reputation": {"overall": 4.8},
                }
            })
        )
        client = FreelancerClient("tok_abc")
        with patch("httpx.AsyncClient", return_value=mock_transport):
            result = await client.get_stats()
        assert result["user_id"] == 12345
        assert result["username"] == "dev_agent"
        assert result["jobs_completed"] == 42
        assert result["reputation"]["overall"] == 4.8

    async def test_handles_missing_reputation(self, mock_transport):
        mock_transport.request = AsyncMock(
            return_value=_make_freelancer_success({
                "profile": {"id": 1, "username": "test"}
            })
        )
        client = FreelancerClient("tok_abc")
        with patch("httpx.AsyncClient", return_value=mock_transport):
            result = await client.get_stats()
        assert result["reputation"] == {}
        assert result["user_id"] == 1


# ============================================================================
# FreelancerClient — search_jobs
# ============================================================================


class TestSearchJobs:
    async def test_search_with_keyword(self, mock_transport):
        mock_transport.request = AsyncMock(
            return_value=_make_freelancer_success({
                "projects": [{"id": 1, "title": "Python API"}],
                "total_count": 1,
            })
        )
        client = FreelancerClient("tok_abc")
        with patch("httpx.AsyncClient", return_value=mock_transport):
            result = await client.search_jobs(keyword="python")
        # Verify query params
        call_args = mock_transport.request.call_args
        assert call_args[1]["params"]["q"] == "python"
        assert result["total_count"] == 1

    async def test_search_with_budget_filter(self, mock_transport):
        mock_transport.request = AsyncMock(
            return_value=_make_freelancer_success({"projects": []})
        )
        client = FreelancerClient("tok_abc")
        with patch("httpx.AsyncClient", return_value=mock_transport):
            await client.search_jobs(budget_min=100, budget_max=1000)
        params = mock_transport.request.call_args[1]["params"]
        assert params["min_price"] == 100
        assert params["max_price"] == 1000

    async def test_search_respects_limit_cap(self, mock_transport):
        mock_transport.request = AsyncMock(
            return_value=_make_freelancer_success({"projects": []})
        )
        client = FreelancerClient("tok_abc")
        with patch("httpx.AsyncClient", return_value=mock_transport):
            await client.search_jobs(keyword="test", limit=100)
        assert mock_transport.request.call_args[1]["params"]["limit"] == 50

    async def test_get_project_details(self, mock_transport):
        mock_transport.request = AsyncMock(
            return_value=_make_freelancer_success({
                "project": {"id": 42, "title": "Web Scraper"}
            })
        )
        client = FreelancerClient("tok_abc")
        with patch("httpx.AsyncClient", return_value=mock_transport):
            result = await client.get_project_details("42")
        assert result["title"] == "Web Scraper"
        assert "projects/42" in mock_transport.request.call_args[0][1]

    async def test_get_my_bids(self, mock_transport):
        mock_transport.request = AsyncMock(
            return_value=_make_freelancer_success({"bids": []})
        )
        client = FreelancerClient("tok_abc")
        with patch("httpx.AsyncClient", return_value=mock_transport):
            result = await client.get_my_bids(limit=10, offset=0)
        assert "bids/" in mock_transport.request.call_args[0][1]


# ============================================================================
# OAuth helper functions
# ============================================================================


class TestBuildAuthorizeUrl:
    def test_builds_url_with_params(self):
        url = build_authorize_url(
            client_id="cli_abc",
            redirect_uri="https://app.example.com/callback",
            scope="basic,projects,bids",
        )
        assert FREELANCER_AUTH_URL in url
        assert "client_id=cli_abc" in url
        assert "response_type=code" in url
        assert "scope=basic%2Cprojects%2Cbids" in url or "scope=basic,projects,bids" in url
        assert "redirect_uri=https%3A%2F%2Fapp.example.com%2Fcallback" in url or \
               "redirect_uri=https://app.example.com/callback" in url


class TestExchangeCodeForToken:
    async def test_exchanges_code(self, mock_transport):
        token_data = {"access_token": "acc_new", "refresh_token": "ref_new", "expires_in": 3600}
        mock_transport.post = AsyncMock(
            return_value=_make_success_response(json_data=token_data)
        )
        mock_transport.post.return_value.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient", return_value=mock_transport):
            result = await exchange_code_for_token(
                client_id="cli_abc",
                client_secret="sec_123",
                code="auth_code_xyz",
                redirect_uri="https://app.example.com/callback",
            )
        assert result["access_token"] == "acc_new"
        assert result["refresh_token"] == "ref_new"
        # Verify POST data
        call_kwargs = mock_transport.post.call_args[1]
        assert call_kwargs["data"]["grant_type"] == "authorization_code"
        assert call_kwargs["data"]["code"] == "auth_code_xyz"


class TestRefreshAccessToken:
    async def test_refreshes_token(self, mock_transport):
        token_data = {"access_token": "acc_refreshed", "expires_in": 3600}
        mock_transport.post = AsyncMock(
            return_value=_make_success_response(json_data=token_data)
        )
        mock_transport.post.return_value.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient", return_value=mock_transport):
            result = await refresh_access_token(
                client_id="cli_abc",
                client_secret="sec_123",
                refresh_token="ref_old",
            )
        assert result["access_token"] == "acc_refreshed"
        call_kwargs = mock_transport.post.call_args[1]
        assert call_kwargs["data"]["grant_type"] == "refresh_token"


# ============================================================================
# Freelancer API envelope handling
# ============================================================================


class TestEnvelopeHandling:
    async def test_raises_on_api_error_envelope(self, mock_transport):
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 200
        resp.json = MagicMock(return_value={
            "status": "error",
            "error_message": "Project not found",
            "error_code": "INVALID_PROJECT",
        })
        resp.raise_for_status = MagicMock()
        mock_transport.request = AsyncMock(return_value=resp)

        client = FreelancerClient("tok_abc")
        with patch("httpx.AsyncClient", return_value=mock_transport), pytest.raises(
            ValueError, match="Freelancer API error: Project not found"
        ):
            await client.submit_proposal(job_id="1", cover_letter="test", bid_amount=100.0)

    async def test_extracts_bid_from_envelope(self, mock_transport):
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 200
        resp.json = MagicMock(return_value={
            "status": "success",
            "result": {"bid": {"id": 777, "amount": 300}},
        })
        resp.raise_for_status = MagicMock()
        mock_transport.request = AsyncMock(return_value=resp)

        client = FreelancerClient("tok_abc")
        with patch("httpx.AsyncClient", return_value=mock_transport):
            result = await client.submit_proposal(job_id="1", cover_letter="t", bid_amount=300)
        assert result["id"] == 777