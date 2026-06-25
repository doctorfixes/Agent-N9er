"""Shared Upwork GraphQL client — extracted from bid_service for reuse across Agent N9er.

Contains all confirmed GraphQL queries, mutations, Pydantic models, and the
UpworkGraphQLClient wrapper that bid_service, prospector, and other services
can import instead of duplicating the logic.

References:
  https://www.upwork.com/services/api/documentation
  https://github.com/furkankoykiran/upwork-mcp (reference impl)
"""

import os
import json
import logging
from typing import Any

import httpx
from pydantic import BaseModel

logger = logging.getLogger("upwork_client")

# ---------------------------------------------------------------------------
# GraphQL — all mutations and queries confirmed working from upwork-mcp source
# ---------------------------------------------------------------------------

SUBMIT_PROPOSAL_MUTATION = """
mutation SubmitProposal($input: SubmitProposalInput!) {
  submitProposal(input: $input) {
    proposal {
      id
      status
      job {
        id
        title
      }
    }
    connectsUsed
    remainingConnects
  }
}
"""

WITHDRAW_PROPOSAL_MUTATION = """
mutation WithdrawProposal($proposalId: String!, $reason: String!) {
  withdrawProposal(proposalId: $proposalId, reason: $reason) {
    success
    connectsRefunded
    proposal {
      id
      status
    }
  }
}
"""

UPDATE_PROPOSAL_MUTATION = """
mutation UpdateProposal($proposalId: String!, $input: UpdateProposalInput!) {
  updateProposal(proposalId: $proposalId, input: $input) {
    proposal {
      id
      status
      bidAmount
      coverLetter
      estimatedDuration
      updatedAt
    }
  }
}
"""

CONNECTS_BALANCE_QUERY = """
query ConnectsBalance {
  connectsBalance {
    available
    totalEarned
    totalUsed
    nextRefillDate
  }
}
"""

PROPOSAL_STATS_QUERY = """
query ProposalStats {
  proposalStats {
    total
    pending
    accepted
    declined
    withdrawn
    archived
    interviewRate
    hireRate
    avgBidAmount
  }
}
"""

PROPOSAL_SEARCH_QUERY = """
query Proposals($status: String, $limit: Int, $offset: Int) {
  proposals(status: $status, limit: $limit, offset: $offset) {
    totalCount
    edges {
      node {
        id
        jobId
        jobTitle
        coverLetter
        bidAmount
        currency
        bidType
        status
        submittedDate
        client {
          uid
          name
          country
        }
      }
    }
    pageInfo {
      hasNextPage
      endCursor
    }
  }
}
"""

JOB_DETAILS_QUERY = """
query GetJobDetails($jobKey: String!) {
  jobPostingByJobKey(jobKey: $jobKey) {
    id
    title
    description
    jobStatus
    jobType
    workload
    duration
    entryLevel
    url
    createdDate
    client {
      uid
      name
      country
      paymentVerificationStatus
      totalSpent
      totalHires
      rating
    }
    budget {
      amount
      currency
      type
      min
      max
    }
    skills
    connects
    screeningQuestions {
      question
    }
  }
}
"""

SEARCH_JOBS_QUERY = """
query SearchJobs($filter: MarketplaceJobPostingsSearchFilter) {
  marketplaceJobPostingsSearch(marketPlaceJobFilter: $filter) {
    totalCount
    edges {
      node {
        id
        title
        description
        jobStatus
        jobType
        workload
        duration
        entryLevel
        url
        createdDate
        client {
          uid
          name
          country
          paymentVerificationStatus
          totalSpent
        }
        budget {
          amount
          currency
          type
          min
          max
        }
        skills
        connects
      }
    }
    pageInfo {
      hasNextPage
      endCursor
    }
  }
}
"""

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class ScoutingRequest(BaseModel):
    """Search parameters for Upwork job scouting."""
    keyword: str = ""
    category: str = ""
    budget_min: float = 0
    budget_max: float = 0
    limit: int = 10


class BidRequest(BaseModel):
    """Submits a proposal for a job already discovered by the Prospector."""
    prospect_id: str
    bid_amount: float
    bid_type: str = "fixed"
    estimated_duration: str | None = None
    tone: str = "professional"
    answers: list[dict] = []


class RawBidRequest(BaseModel):
    """Submit a raw proposal with pre-written text."""
    job_id: str
    cover_letter: str
    bid_amount: float
    bid_type: str = "fixed"
    estimated_duration: str | None = None
    answers: list[dict] = []


class UserPlanResponse(BaseModel):
    ok: bool = True
    action: str
    proposal_id: str = ""
    proposal_status: str = ""
    connects_used: int = 0
    remaining_connects: int = 0
    cost_usd: float = 0
    mode: str = "live"
    detail: str = ""


# ---------------------------------------------------------------------------
# Upwork GraphQL client
# ---------------------------------------------------------------------------


class UpworkGraphQLClient:
    """Thin wrapper around Upwork's GraphQL endpoint.

    Provides async methods for all confirmed operations:
    - Proposal lifecycle (submit, withdraw, update)
    - Connects balance and stats
    - Job search and details
    - Proposal search

    Usage:
        client = UpworkGraphQLClient(access_token="...")
        data = await client.search_jobs(keyword="python", budget_min=500)
    """

    DEFAULT_API_URL = os.getenv("UPWORK_API_URL", "https://api.upwork.com/graphql")

    def __init__(self, access_token: str, base_url: str | None = None):
        self.access_token = access_token
        self.base_url = base_url or self.DEFAULT_API_URL
        self._headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "User-Agent": "AgentN9er/1.0",
        }

    async def execute(self, query: str, variables: dict | None = None) -> dict:
        """Execute a GraphQL query/mutation against Upwork.

        Returns the `data` envelope on success.
        Raises httpx.HTTPStatusError or ValueError with Upwork error details.
        """
        if not self.access_token:
            raise ValueError(
                "Upwork OAuth token not configured. "
                "Set UPWORK_ACCESS_TOKEN or use set_oauth_token endpoint."
            )

        payload: dict[str, Any] = {"query": query}
        if variables:
            payload["variables"] = variables

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(self.base_url, json=payload, headers=self._headers)

        if resp.status_code == 401:
            raise httpx.HTTPStatusError(
                "Upwork token expired. Refresh via /bid/upwork/oauth/refresh",
                request=resp.request,
                response=resp,
            )
        if resp.status_code == 429:
            raise httpx.HTTPStatusError(
                "Upwork rate limit hit. Retry after backoff.",
                request=resp.request,
                response=resp,
            )

        resp.raise_for_status()
        data = resp.json()

        if "errors" in data:
            err_msgs = [e.get("message", "Unknown error") for e in data["errors"]]
            raise ValueError(f"Upwork GraphQL error: {'; '.join(err_msgs)}")

        return data["data"]

    async def submit_proposal(
        self,
        job_id: str,
        cover_letter: str,
        bid_amount: float,
        bid_type: str = "fixed",
        estimated_duration: str | None = None,
        answers: list | None = None,
    ) -> dict:
        """Submit a proposal to an Upwork job posting."""
        variables: dict[str, Any] = {
            "input": {
                "jobId": job_id,
                "coverLetter": cover_letter,
                "bidAmount": bid_amount,
                "bidType": bid_type.upper(),
            }
        }
        if estimated_duration:
            variables["input"]["estimatedDuration"] = estimated_duration
        if answers:
            variables["input"]["answers"] = answers

        data = await self.execute(SUBMIT_PROPOSAL_MUTATION, variables)
        return data.get("submitProposal", {})

    async def withdraw_proposal(self, proposal_id: str, reason: str = "") -> dict:
        """Withdraw a previously submitted proposal."""
        data = await self.execute(WITHDRAW_PROPOSAL_MUTATION, {
            "proposalId": proposal_id,
            "reason": reason or "Withdrawn by Agent N9er",
        })
        return data.get("withdrawProposal", {})

    async def update_proposal(self, proposal_id: str, input_data: dict) -> dict:
        """Update a pending proposal."""
        data = await self.execute(UPDATE_PROPOSAL_MUTATION, {
            "proposalId": proposal_id,
            "input": input_data,
        })
        return data.get("updateProposal", {})

    async def get_connects_balance(self) -> dict:
        """Get current Connects balance and usage stats."""
        return await self.execute(CONNECTS_BALANCE_QUERY)

    async def get_proposal_stats(self) -> dict:
        """Get aggregate proposal stats (interview rate, hire rate, etc.)."""
        return await self.execute(PROPOSAL_STATS_QUERY)

    async def search_proposals(self, status: str | None = None,
                               limit: int = 20, offset: int = 0) -> dict:
        """Search submitted proposals."""
        variables: dict[str, Any] = {"limit": limit, "offset": offset}
        if status:
            variables["status"] = status
        data = await self.execute(PROPOSAL_SEARCH_QUERY, variables)
        return data.get("proposals", {})

    async def get_job_details(self, job_key: str) -> dict:
        """Get detailed job information by job key."""
        data = await self.execute(JOB_DETAILS_QUERY, {"jobKey": job_key})
        return data.get("jobPostingByJobKey", {})

    async def search_jobs(
        self,
        keyword: str | None = None,
        category: str | None = None,
        budget_min: float | None = None,
        budget_max: float | None = None,
        limit: int = 10,
    ) -> dict:
        """Search job postings directly via Upwork GraphQL.

        Filters by keyword, category, and/or budget range.
        Returns the marketplaceJobPostingsSearch envelope with edges + totalCount.
        """
        filt: dict[str, Any] = {}
        if keyword:
            filt["keyword"] = keyword
        if category:
            filt["category2"] = category
        if budget_min:
            filt["fixedPriceAmountMin"] = budget_min
        if budget_max:
            filt["fixedPriceAmountMax"] = budget_max
        data = await self.execute(SEARCH_JOBS_QUERY, {"filter": filt})
        return data.get("marketplaceJobPostingsSearch", {})