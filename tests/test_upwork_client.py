"""Tests for shared/upwork_client.py — UpworkGraphQLClient with mocked httpx."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from shared.upwork_client import UpworkGraphQLClient

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_transport():
    """Return a fully-wired async context manager that yields mock_http."""
    mock_http = AsyncMock(spec=httpx.AsyncClient)

    # async context manager protocol
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=False)

    return mock_http


def _make_success_response(status_code=200, json_data=None):
    """Build a mock httpx.Response that reports success."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json = MagicMock(return_value=json_data or {"data": {"ok": True}})
    resp.raise_for_status = MagicMock()
    return resp


def _make_error_response(status_code, detail=""):
    """Build a mock httpx.Response that raises on raise_for_status."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.text = detail
    resp.json = MagicMock(return_value={"data": {}})

    def raise_it():
        raise httpx.HTTPStatusError(detail, request=MagicMock(), response=resp)

    resp.raise_for_status = raise_it
    return resp


# ---------------------------------------------------------------------------
# Constructor
# ---------------------------------------------------------------------------


class TestConstructor:
    def test_sets_default_api_url(self):
        client = UpworkGraphQLClient(access_token="tok_abc")
        assert client.access_token == "tok_abc"
        assert client.base_url == "https://api.upwork.com/graphql"
        assert client._headers["Authorization"] == "Bearer tok_abc"

    def test_accepts_custom_base_url(self):
        client = UpworkGraphQLClient(
            access_token="tok_abc", base_url="https://custom.upwork.com/gql"
        )
        assert client.base_url == "https://custom.upwork.com/gql"


# ---------------------------------------------------------------------------
# execute() — core method
# ---------------------------------------------------------------------------


class TestExecute:
    async def test_success_returns_data(self, mock_transport):
        payload = {"data": {"connectsBalance": {"available": 50}}}
        mock_transport.post = AsyncMock(return_value=_make_success_response(json_data=payload))

        client = UpworkGraphQLClient("tok_abc")
        with patch("httpx.AsyncClient", return_value=mock_transport):
            result = await client.execute("{ connectsBalance }")

        assert result == {"connectsBalance": {"available": 50}}
        mock_transport.post.assert_called_once()

    async def test_raises_on_empty_token(self, mock_transport):
        client = UpworkGraphQLClient("")
        with pytest.raises(ValueError, match="Upwork OAuth token not configured"):
            await client.execute("{ something }")

    async def test_401_raises_http_error(self, mock_transport):
        mock_transport.post = AsyncMock(
            return_value=_make_error_response(401, "token expired")
        )

        client = UpworkGraphQLClient("tok_expired")
        with patch("httpx.AsyncClient", return_value=mock_transport):
            with pytest.raises(httpx.HTTPStatusError, match="Upwork token expired"):
                await client.execute("{ query }")

    async def test_429_raises_http_error(self, mock_transport):
        mock_transport.post = AsyncMock(
            return_value=_make_error_response(429, "rate limit")
        )

        client = UpworkGraphQLClient("tok_abc")
        with patch("httpx.AsyncClient", return_value=mock_transport):
            with pytest.raises(httpx.HTTPStatusError, match="Upwork rate limit hit"):
                await client.execute("{ query }")

    async def test_graphql_errors_raises_value_error(self, mock_transport):
        payload = {
            "errors": [
                {"message": "Field 'foo' doesn't exist"},
                {"message": "Not authorized"},
            ]
        }
        resp = _make_success_response(json_data=payload)
        # Override: success status but error body — override raise_for_status
        resp.raise_for_status = MagicMock()
        mock_transport.post = AsyncMock(return_value=resp)

        client = UpworkGraphQLClient("tok_abc")
        with patch("httpx.AsyncClient", return_value=mock_transport):
            with pytest.raises(ValueError, match="Upwork GraphQL error"):
                await client.execute("{ badQuery }")

    async def test_sends_variables(self, mock_transport):
        payload = {"data": {"submitProposal": {"proposal": {"id": "p1"}}}}
        resp = _make_success_response(json_data=payload)
        mock_transport.post = AsyncMock(return_value=resp)

        client = UpworkGraphQLClient("tok_abc")
        variables = {"input": {"jobId": "j1", "bidAmount": 500}}
        with patch("httpx.AsyncClient", return_value=mock_transport):
            result = await client.execute("mutation { submitProposal }", variables)

        assert result == {"submitProposal": {"proposal": {"id": "p1"}}}
        _, kwargs = mock_transport.post.call_args
        assert kwargs["json"]["variables"] == variables


# ---------------------------------------------------------------------------
# High-level methods
# ---------------------------------------------------------------------------


class TestSubmitProposal:
    async def test_submits_proposal(self, mock_transport):
        payload = {
            "data": {
                "submitProposal": {
                    "proposal": {"id": "p_123", "status": "active", "job": {"id": "j_456", "title": "Bot"}},
                    "connectsUsed": 8,
                    "remainingConnects": 42,
                }
            }
        }
        mock_transport.post = AsyncMock(return_value=_make_success_response(json_data=payload))

        client = UpworkGraphQLClient("tok_abc")
        with patch("httpx.AsyncClient", return_value=mock_transport):
            result = await client.submit_proposal(
                job_id="j_456",
                cover_letter="I can do this",
                bid_amount=500,
                bid_type="fixed",
            )

        assert result["proposal"]["id"] == "p_123"
        assert result["connectsUsed"] == 8

    async def test_submit_with_duration_and_answers(self, mock_transport):
        payload = {"data": {"submitProposal": {"proposal": {"id": "p_2"}}}}
        mock_transport.post = AsyncMock(return_value=_make_success_response(json_data=payload))

        client = UpworkGraphQLClient("tok_abc")
        with patch("httpx.AsyncClient", return_value=mock_transport):
            result = await client.submit_proposal(
                job_id="j_789",
                cover_letter="Hi",
                bid_amount=250,
                estimated_duration="2 weeks",
                answers=[{"question": "Experience?", "answer": "5 years"}],
            )

        assert result["proposal"]["id"] == "p_2"
        _, kwargs = mock_transport.post.call_args
        sent = kwargs["json"]["variables"]["input"]
        assert "estimatedDuration" in sent
        assert "answers" in sent


class TestWithdrawProposal:
    async def test_withdraws(self, mock_transport):
        payload = {
            "data": {
                "withdrawProposal": {
                    "success": True,
                    "connectsRefunded": 8,
                    "proposal": {"id": "w_1", "status": "withdrawn"},
                }
            }
        }
        mock_transport.post = AsyncMock(return_value=_make_success_response(json_data=payload))

        client = UpworkGraphQLClient("tok_abc")
        with patch("httpx.AsyncClient", return_value=mock_transport):
            result = await client.withdraw_proposal("w_1", "Client went silent")

        assert result["success"] is True
        assert result["connectsRefunded"] == 8

    async def test_withdraw_default_reason(self, mock_transport):
        payload = {"data": {"withdrawProposal": {"success": True}}}
        mock_transport.post = AsyncMock(return_value=_make_success_response(json_data=payload))

        client = UpworkGraphQLClient("tok_abc")
        with patch("httpx.AsyncClient", return_value=mock_transport):
            await client.withdraw_proposal("w_2")

        _, kwargs = mock_transport.post.call_args
        assert "Withdrawn by Agent N9er" in kwargs["json"]["variables"]["reason"]


class TestSearchJobs:
    async def test_search_with_filters(self, mock_transport):
        payload = {
            "data": {
                "marketplaceJobPostingsSearch": {
                    "totalCount": 1,
                    "edges": [
                        {
                            "node": {
                                "id": "job_1",
                                "title": "Python Developer",
                                "budget": {"min": 500, "max": 1000, "type": "fixed"},
                            }
                        }
                    ],
                }
            }
        }
        mock_transport.post = AsyncMock(return_value=_make_success_response(json_data=payload))

        client = UpworkGraphQLClient("tok_abc")
        with patch("httpx.AsyncClient", return_value=mock_transport):
            result = await client.search_jobs(
                keyword="python", category="web-development",
                budget_min=500, budget_max=2000, limit=10,
            )

        assert result["totalCount"] == 1
        assert result["edges"][0]["node"]["title"] == "Python Developer"

    async def test_search_no_filters(self, mock_transport):
        payload = {"data": {"marketplaceJobPostingsSearch": {"totalCount": 0, "edges": []}}}
        mock_transport.post = AsyncMock(return_value=_make_success_response(json_data=payload))

        client = UpworkGraphQLClient("tok_abc")
        with patch("httpx.AsyncClient", return_value=mock_transport):
            result = await client.search_jobs(limit=5)

        assert result["totalCount"] == 0
        _, kwargs = mock_transport.post.call_args
        # When no filters, the filter dict should be empty (no keys passed)
        sent_vars = kwargs["json"]["variables"]["filter"]
        assert sent_vars == {}


class TestGetConnectsBalance:
    async def test_returns_balance(self, mock_transport):
        payload = {
            "data": {
                "connectsBalance": {
                    "available": 60,
                    "totalEarned": 200,
                    "totalUsed": 140,
                    "nextRefillDate": "2026-07-01",
                }
            }
        }
        mock_transport.post = AsyncMock(return_value=_make_success_response(json_data=payload))

        client = UpworkGraphQLClient("tok_abc")
        with patch("httpx.AsyncClient", return_value=mock_transport):
            result = await client.get_connects_balance()

        assert result["connectsBalance"]["available"] == 60
