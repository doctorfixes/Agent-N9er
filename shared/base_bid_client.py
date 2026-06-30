"""Abstract base class for platform-specific bid clients.

Defines the interface that all marketplace bid clients
(Upwork, Freelancer, etc.) must implement.
"""

from abc import ABC, abstractmethod
from typing import Any


class BaseBidClient(ABC):
    """Abstract marketplace bid client.

    Each platform client implements these methods to provide a uniform
    interface for the bid_service endpoints.
    """

    @abstractmethod
    async def submit_proposal(
        self,
        job_id: str,
        cover_letter: str,
        bid_amount: float,
        bid_type: str = "fixed",
        estimated_duration: str | None = None,
        answers: list | None = None,
    ) -> dict[str, Any]:
        """Submit a proposal/bid to a job posting."""
        ...

    @abstractmethod
    async def withdraw_proposal(
        self, proposal_id: str, reason: str = ""
    ) -> dict[str, Any]:
        """Withdraw a previously submitted proposal/bid."""
        ...

    @abstractmethod
    async def update_proposal(
        self, proposal_id: str, input_data: dict
    ) -> dict[str, Any]:
        """Update a pending proposal/bid."""
        ...

    @abstractmethod
    async def get_balance(self) -> dict[str, Any]:
        """Get current account balance / available credits."""
        ...

    @abstractmethod
    async def get_stats(self) -> dict[str, Any]:
        """Get aggregate bid/proposal statistics."""
        ...

    @abstractmethod
    async def search_jobs(
        self,
        keyword: str | None = None,
        category: str | None = None,
        budget_min: float | None = None,
        budget_max: float | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        """Search for available jobs/projects to bid on."""
        ...
