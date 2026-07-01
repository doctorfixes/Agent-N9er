"""
Agent State Machine — shared library for all agent processes.

States:
  idle       — registered but not working
  claiming   — picked a task, preparing to bid/execute
  pricing    — calculating bid price
  executing  — performing the task (LLM calls, tool use, etc.)
  delivering — finalizing output, submitting
  rating     — post-task review & reputation update
  error      — unrecoverable failure

Transitions:
  idle → claiming (on task pick)
  claiming → pricing (on capability match)
  claiming → idle (on task reject)
  pricing → executing (on bid win)
  pricing → idle (on bid loss)
  executing → delivering (on task complete)
  executing → error (on unrecoverable failure)
  delivering → rating (on submission)
  rating → idle (on cycle complete)
  error → idle (on manual reset)
"""

import logging
from enum import Enum
from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel

logger = logging.getLogger("agent_sm")

AGENT_STATES = [
    "idle",
    "claiming",
    "pricing",
    "executing",
    "delivering",
    "rating",
    "error",
]

AGENT_CAPABILITIES_T = list[str]

VALID_TRANSITIONS: dict[str, list[str]] = {
    "idle": ["claiming", "error"],
    "claiming": ["pricing", "idle", "error"],
    "pricing": ["executing", "idle", "error"],
    "executing": ["delivering", "error"],
    "delivering": ["rating", "error"],
    "rating": ["idle", "error"],
    "error": ["idle"],
}

AGENT_TYPES = [
    "bidder",
    "executor",
    "researcher",
    "reviewer",
    "prospector",
    "orchestrator",
]


class AgentStatus(BaseModel):
    """Full status payload sent to the Agent Registry on heartbeat."""

    agent_id: str
    agent_type: str
    state: str = "idle"
    capabilities: list[str] = []
    price_per_hour: float = 0.0
    current_load: int = 0
    max_load: int = 3
    last_heartbeat: str = ""
    current_task_id: Optional[str] = None
    metadata: dict = {}

    class Config:
        from_attributes = True


class StateTransitionError(ValueError):
    """Raised on invalid state transition."""

    pass


def validate_transition(current: str, target: str) -> None:
    """Raise if current → target is not a valid transition."""
    allowed = VALID_TRANSITIONS.get(current, [])
    if target not in allowed:
        raise StateTransitionError(
            f"Invalid transition: {current} → {target}. "
            f"Allowed from {current}: {allowed}"
        )


class AgentStateMachine:
    """Lightweight state machine for a single agent process.

    Usage:
        sm = AgentStateMachine("agent-1", "bidder")
        sm.transition("claiming")   # idle → claiming
        sm.transition("pricing")    # claiming → pricing
    """

    def __init__(
        self,
        agent_id: str,
        agent_type: str,
        capabilities: list[str] | None = None,
        price_per_hour: float = 0.0,
        max_load: int = 3,
    ):
        if agent_type not in AGENT_TYPES:
            raise ValueError(f"Unknown agent type: {agent_type}. Valid: {AGENT_TYPES}")

        self.agent_id = agent_id
        self.agent_type = agent_type
        self.state = "idle"
        self.capabilities = capabilities or []
        self.price_per_hour = price_per_hour
        self.current_load = 0
        self.max_load = max_load
        self.current_task_id: Optional[str] = None
        self.state_started_at: Optional[datetime] = None
        self.metadata: dict = {}
        self._logger = logging.getLogger(f"agent_sm.{agent_id}")

    def transition(self, target: str, task_id: str | None = None) -> None:
        """Attempt to transition to *target* state."""
        validate_transition(self.state, target)
        old = self.state
        self.state = target
        self.state_started_at = datetime.now(timezone.utc)
        if task_id:
            self.current_task_id = task_id
        if target == "idle":
            self.current_task_id = None
        if target in ("claiming", "executing"):
            self.current_load += 1
        if target == "idle" and old in ("rating", "delivering", "error"):
            self.current_load = max(0, self.current_load - 1)
        self._logger.info(
            "State: %s → %s%s",
            old,
            target,
            f" [task={task_id}]" if task_id else "",
        )

    def reset(self) -> None:
        """Force reset to idle (error recovery)."""
        self.state = "idle"
        self.state_started_at = datetime.now(timezone.utc)
        self.current_task_id = None
        self.current_load = 0
        self._logger.info("State reset to idle")

    def status_payload(self) -> AgentStatus:
        """Build the AgentStatus for registry heartbeat."""
        return AgentStatus(
            agent_id=self.agent_id,
            agent_type=self.agent_type,
            state=self.state,
            capabilities=self.capabilities,
            price_per_hour=self.price_per_hour,
            current_load=self.current_load,
            max_load=self.max_load,
            last_heartbeat=datetime.now(timezone.utc).isoformat(),
            current_task_id=self.current_task_id,
            metadata=self.metadata,
        )

    @property
    def is_available(self) -> bool:
        """Agent can accept new work when idle and under max load."""
        return self.state == "idle" and self.current_load < self.max_load

    def can_handle(self, required_capabilities: list[str]) -> bool:
        """Check if agent capabilities cover all required capabilities."""
        if not required_capabilities:
            return True
        return all(cap in self.capabilities for cap in required_capabilities)
