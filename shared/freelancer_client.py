"""Freelancer.com REST API client — platform adapter for Agent N9er bid_service.

Freelancer.com uses a REST API (not GraphQL) with OAuth 2.0 authentication.
The token is passed via the Freelancer-OAuth-V1 header.

API base: https://www.freelancer.com/api/projects/0.1/
Docs:     https://developers.freelancer.com
"""

import os
import json
import logging
from typing import Any

import httpx

from .base_bid_client import BaseBidClient

logger = logging.getLogger("freelancer_client")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

FREELANCER_API_BASE = os.getenv(
    "FREELANCER_API_BASE",
    "https://www.freelancer.com/api/projects/0.1/",
)
FREELANCER_OAUTH_URL = os.getenv(
    "FREELANCER_OAUTH_URL",
    "https://accounts.freelancer.com/oauth/token",
)
FREELANCER_AUTH_URL = os.getenv(
    "FREELANCER_AUTH_URL",
    "https://accounts.freelancer.com/oauth/authorize",
)

# ---------------------------------------------------------------------------
# Freelancer REST API client
# ---------------------------------------------------------------------------


class FreelancerClient(BaseBidClient):
    """REST client for Freelancer.com marketplace.

    Uses the `Freelancer-OAuth-V1` header for authentication.
    All API responses are wrapped in a JSON envelope with ``status``,
    ``result``, and optionally ``error_code`` / ``error_message``.
    """

    def __init__(self, access_token: str, base_url: str | None = None):
        self.access_token = access_token
        self.base_url = (base_url or FREELANCER_API_BASE).rstrip("/") + "/"
        self.users_base_url = "https://www.freelancer.com/api/users/0.1/"

    def _headers(self) -> dict[str, str]:
        return {
            "Freelancer-OAuth-V1": self.access_token,
            "Content-Type": "application/json",
            "User-Agent": "AgentN9er/1.0",
        }

    async def _request(
        self, method: str, path: str, base_url: str | None = None, **kwargs
    ) -> dict[str, Any]:
        """Make an authenticated request, unwrap the Freelancer envelope."""
        url = (base_url or self.base_url) + path.lstrip("/")
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.request(
                method, url, headers=self._headers(), **kwargs
            )

        # Check auth / errors
        if resp.status_code == 401:
            raise httpx.HTTPStatusError(
                "Freelancer token expired or invalid. "
                "Regenerate via /bid/freelancer/oauth/setup",
                request=resp.request,
                response=resp,
            )
        if resp.status_code == 429:
            raise httpx.HTTPStatusError(
                "Freelancer rate limit hit. Retry after backoff.",
                request=resp.request,
                response=resp,
            )

        resp.raise_for_status()
        data = resp.json()

        # Freelancer wraps responses in {"status": "success", "result": ...}
        status = data.get("status", "")
        if status != "success":
            err_msg = data.get("error_message", data.get("error_code", "Unknown error"))
            raise ValueError(f"Freelancer API error: {err_msg}")

        return data.get("result", data)

    # ------------------------------------------------------------------
    # Bid/Proposal lifecycle
    # ------------------------------------------------------------------

    async def submit_proposal(
        self,
        job_id: str,
        cover_letter: str,
        bid_amount: float,
        bid_type: str = "fixed",
        estimated_duration: str | None = None,
        answers: list | None = None,
    ) -> dict[str, Any]:
        """Place a bid on a Freelancer project.

        POST /api/projects/0.1/bids/

        Parameters
        ----------
        job_id : str
            Freelancer project ID.
        cover_letter : str
            Bid description / cover letter.
        bid_amount : float
            Bid amount in USD.
        bid_type : str
            "fixed" (default) or "hourly". Freelancer calls these
            "fixed" and "hourly" project types.
        estimated_duration : str or None
            E.g. "1 week", "2 weeks". Maps to Freelancer's ``period`` field.
        answers : list or None
            Not used by Freelancer's REST API — ignored.

        Returns
        -------
        dict with keys like ``id``, ``project_id``, ``amount``, ``period``.
        """
        period = None
        if estimated_duration:
            # Normalise to Freelancer period format (days as int)
            import re
            m = re.match(r"(\d+)\s*(day|days|d)", estimated_duration, re.IGNORECASE)
            if m:
                period = int(m.group(1))
            else:
                m = re.match(r"(\d+)\s*(week|weeks|w)", estimated_duration, re.IGNORECASE)
                if m:
                    period = int(m.group(1)) * 7
                else:
                    period = 14  # default 2 weeks

        bid_type_upper = bid_type.upper()
        payload: dict[str, Any] = {
            "project_id": int(job_id),
            "amount": bid_amount,
            "description": cover_letter,
            "period": period or 14,
            # Freelancer bids are either fixed-price or hourly
            "milestone_percentage": 100 if bid_type_upper == "FIXED" else 0,
        }

        result = await self._request("POST", "bids/", json={"bid": payload})
        # Freelancer returns {"status": "success", "result": {"id": ..., ...}}
        # but sometimes the bid is at result.bid or just result
        if isinstance(result, dict) and "bid" in result:
            return result["bid"]
        return result

    async def withdraw_proposal(
        self, proposal_id: str, reason: str = ""
    ) -> dict[str, Any]:
        """Withdraw/retract a bid.

        DELETE /api/projects/0.1/bids/{id}
        """
        result = await self._request("DELETE", f"bids/{proposal_id}")
        return {"status": "withdrawn", "bid_id": proposal_id, "result": result}

    async def update_proposal(
        self, proposal_id: str, input_data: dict
    ) -> dict[str, Any]:
        """Update an existing bid.

        PUT /api/projects/0.1/bids/{id}
        """
        result = await self._request(
            "PUT", f"bids/{proposal_id}", json={"bid": input_data}
        )
        if isinstance(result, dict) and "bid" in result:
            return result["bid"]
        return result

    # ------------------------------------------------------------------
    # Account / Stats
    # ------------------------------------------------------------------

    async def get_balance(self) -> dict[str, Any]:
        """Get account balance from the authenticated user's profile.

        GET /api/users/0.1/self/  — note: uses users API, not projects API
        """
        result = await self._request(
            "GET", "self/", base_url=self.users_base_url
        )
        # The users API returns result directly, sometimes wrapped
        user = result.get("profile", result) if isinstance(result, dict) else result
        return {
            "available": user.get("balance", 0),
            "currency": user.get("currency", {}).get("code", "USD") if isinstance(user.get("currency"), dict) else "USD",
            "details": user,
        }

    async def get_stats(self) -> dict[str, Any]:
        """Get basic stats from self user profile.

        Freelancer doesn't have a dedicated proposal stats endpoint
        like Upwork — we infer from the user profile.
        """
        result = await self._request(
            "GET", "self/", base_url=self.users_base_url
        )
        user = result.get("profile", result) if isinstance(result, dict) else result
        # Flatten available reputation data
        reputation = user.get("reputation", {}) if isinstance(user, dict) else {}
        return {
            "user_id": user.get("id", ""),
            "username": user.get("username", ""),
            "reputation": reputation,
            "jobs_completed": user.get("jobs_completed", 0),
            "jobs_in_progress": user.get("jobs_in_progress", 0),
            "avg_bid_amount": user.get("avg_bid_amount", 0),
            "registration_date": user.get("registration_date", ""),
        }

    # ------------------------------------------------------------------
    # Job search
    # ------------------------------------------------------------------

    async def search_jobs(
        self,
        keyword: str | None = None,
        category: str | None = None,
        budget_min: float | None = None,
        budget_max: float | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        """Search active project listings.

        GET /api/projects/0.1/projects/active

        Parameters are passed as query params where supported.
        Returns the ``projects`` envelope with ``total_count`` and ``projects``.
        """
        params: dict[str, Any] = {"limit": min(limit, 50), "offset": 0}
        if keyword:
            # Freelancer uses ``q`` for keyword search on projects or ``jobs[]``
            params["q"] = keyword
        if category:
            params["category"] = category  # This might be a category ID
        if budget_min is not None:
            params["min_price"] = budget_min
        if budget_max is not None:
            params["max_price"] = budget_max

        result = await self._request("GET", "projects/active", params=params)
        return result

    async def get_project_details(self, project_id: str) -> dict[str, Any]:
        """Get full details for a specific project.

        GET /api/projects/0.1/projects/{id}
        """
        result = await self._request("GET", f"projects/{project_id}")
        if isinstance(result, dict) and "project" in result:
            return result["project"]
        return result

    async def get_my_bids(
        self, limit: int = 20, offset: int = 0
    ) -> dict[str, Any]:
        """List bids placed by the authenticated user.

        GET /api/projects/0.1/bids/?user_id=self
        """
        result = await self._request(
            "GET", "bids/", params={"limit": limit, "offset": offset}
        )
        return result


# ---------------------------------------------------------------------------
# OAuth helpers
# ---------------------------------------------------------------------------


def build_authorize_url(client_id: str, redirect_uri: str, scope: str) -> str:
    """Build the Freelancer OAuth authorize URL for the user's browser."""
    return (
        f"{FREELANCER_AUTH_URL}?client_id={client_id}"
        f"&response_type=code"
        f"&scope={scope}"
        f"&redirect_uri={redirect_uri}"
    )


async def exchange_code_for_token(
    client_id: str,
    client_secret: str,
    code: str,
    redirect_uri: str,
) -> dict[str, Any]:
    """Exchange an authorization code for an access token.

    POST to Freelancer's OAuth token endpoint.
    Returns the token response dict with ``access_token``, ``refresh_token``, etc.
    """
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            FREELANCER_OAUTH_URL,
            data={
                "grant_type": "authorization_code",
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "redirect_uri": redirect_uri,
            },
        )
    resp.raise_for_status()
    return resp.json()


async def refresh_access_token(
    client_id: str, client_secret: str, refresh_token: str
) -> dict[str, Any]:
    """Refresh an expired access token."""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            FREELANCER_OAUTH_URL,
            data={
                "grant_type": "refresh_token",
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
            },
        )
    resp.raise_for_status()
    return resp.json()