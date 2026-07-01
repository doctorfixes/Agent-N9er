"""
Agent Launcher — spawns and manages agent processes as reified state-machine agents.

Each agent is an asyncio task that:
  1. Registers with the Agent Registry on startup
  2. Runs its own state machine (idle → claiming → pricing → executing → ...)
  3. Heartbeats on a regular interval
  4. Wraps an existing service (bid_service, prospector_service, etc.) or runs as a standalone

Startup:
  python agent_launcher/main.py --type bidder --registry http://localhost:9900
  python agent_launcher/main.py --type prospector --registry http://localhost:9900
"""

import os
import sys
import json
import asyncio
import signal
import argparse
import logging
from datetime import datetime, timezone

import httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared.agent_state_machine import (
    AgentStateMachine,
    AGENT_TYPES,
    AGENT_STATES,
    AgentStatus,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s %(message)s")
logger = logging.getLogger("agent_launcher")

REGISTRY_URL = os.getenv("REGISTRY_URL", "http://localhost:9900")
HEARTBEAT_INTERVAL = int(os.getenv("HEARTBEAT_INTERVAL", "15"))
DEFAULT_MAX_LOAD = int(os.getenv("DEFAULT_MAX_LOAD", "3"))
SERVICE_TOKEN = os.getenv("SERVICE_TOKEN", "")

AGENT_DEFAULTS: dict[str, dict] = {
    "bidder": {
        "capabilities": ["bidding", "pricing", "marketplace"],
        "price_per_hour": 0.50,
    },
    "prospector": {
        "capabilities": ["scanning", "rss", "web-scraping", "discovery"],
        "price_per_hour": 0.30,
    },
    "executor": {
        "capabilities": ["llm", "code", "research", "writing"],
        "price_per_hour": 1.00,
    },
    "researcher": {
        "capabilities": ["research", "analysis", "web-search"],
        "price_per_hour": 0.75,
    },
    "reviewer": {
        "capabilities": ["review", "qa", "validation"],
        "price_per_hour": 0.40,
    },
    "orchestrator": {
        "capabilities": ["planning", "delegation", "coordination"],
        "price_per_hour": 1.50,
    },
}


class AgentRuntime:
    """Wraps AgentStateMachine with HTTP calls to the Registry and heartbeat loop."""

    def __init__(self, agent_type: str, agent_id: str | None = None):
        if agent_type not in AGENT_TYPES:
            raise ValueError(f"Unknown agent type: {agent_type}")

        defaults = AGENT_DEFAULTS[agent_type]
        self.agent_id = agent_id or f"{agent_type}-{os.urandom(4).hex()}"
        self.agent_type = agent_type
        self.registry_url = REGISTRY_URL.rstrip("/")

        self.sm = AgentStateMachine(
            agent_id=self.agent_id,
            agent_type=agent_type,
            capabilities=defaults["capabilities"],
            price_per_hour=defaults["price_per_hour"],
            max_load=DEFAULT_MAX_LOAD,
        )

        self._http = httpx.AsyncClient(timeout=10.0)
        self._running = False
        self._heartbeat_task: asyncio.Task | None = None
        self._work_task: asyncio.Task | None = None
        self._log = logging.getLogger(f"agent.{self.agent_id}")

    async def register(self) -> dict:
        """Register with the Agent Registry."""
        payload = {
            "agent_id": self.agent_id,
            "agent_type": self.agent_type,
            "capabilities": self.sm.capabilities,
            "price_per_hour": self.sm.price_per_hour,
            "max_load": self.sm.max_load,
            "metadata": {"agent_type": self.agent_type},
        }
        headers = {}
        if SERVICE_TOKEN:
            headers["X-Service-Token"] = SERVICE_TOKEN

        resp = await self._http.post(
            f"{self.registry_url}/register",
            json=payload,
            headers=headers,
        )
        if resp.status_code == 200:
            data = resp.json()
            self._log.info("Registered with registry — state=%s", data.get("state", "unknown"))
            return data
        else:
            self._log.error("Registration failed: %s %s", resp.status_code, resp.text)
            resp.raise_for_status()  # type: ignore — raises on non-2xx
            return {}  # unreachable, pacifies type checker

    async def heartbeat_loop(self):
        """Send heartbeats to the registry at a regular interval."""
        while self._running:
            try:
                payload = {
                    "agent_id": self.agent_id,
                    "state": self.sm.state,
                    "current_load": self.sm.current_load,
                    "current_task_id": self.sm.current_task_id,
                    "metadata": self.sm.metadata,
                }
                headers = {}
                if SERVICE_TOKEN:
                    headers["X-Service-Token"] = SERVICE_TOKEN

                resp = await self._http.post(
                    f"{self.registry_url}/heartbeat",
                    json=payload,
                    headers=headers,
                )
                if resp.status_code != 200:
                    self._log.warning("Heartbeat failed: %s", resp.status_code)
            except Exception as e:
                self._log.warning("Heartbeat error: %s", e)

            await asyncio.sleep(HEARTBEAT_INTERVAL)

    async def work_loop(self):
        """Agent-specific work cycle. Subclass or override for custom behaviour."""
        self._log.info("Work loop starting (type=%s)", self.agent_type)
        while self._running:
            if self.sm.state == "idle" and self.sm.is_available:
                # Built-in behaviour: try to discover work via the registry
                try:
                    await self._look_for_work()
                except Exception as e:
                    self._log.debug("No work available: %s", e)
            await asyncio.sleep(10)

    async def _look_for_work(self):
        """Query registry for tasks or perform agent-type-specific discovery."""
        # Base implementation: log state and wait
        # Subclassed agents override this with actual logic
        pass

    async def start(self):
        """Start the agent: register, then run heartbeat + work loops."""
        self._running = True
        await self.register()
        self._heartbeat_task = asyncio.create_task(self.heartbeat_loop())
        self._work_task = asyncio.create_task(self.work_loop())
        self._log.info("Agent started (type=%s, id=%s)", self.agent_type, self.agent_id)

    async def stop(self):
        """Graceful shutdown."""
        self._running = False
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
        if self._work_task:
            self._work_task.cancel()
        await self._http.aclose()
        self._log.info("Agent stopped")

    def transition(self, target: str, task_id: str | None = None):
        """Transition state machine and log."""
        self.sm.transition(target, task_id)
        self._log.info("State → %s%s", target, f" (task={task_id})" if task_id else "")


class BidderAgent(AgentRuntime):
    """Bidder agent — wraps bid_service logic as an autonomous agent."""

    BID_SERVICE_URL = os.getenv("BID_SERVICE_URL", "http://localhost:9400")

    def __init__(self, agent_id: str | None = None):
        super().__init__("bidder", agent_id)
        # Extend capabilities beyond defaults
        self.sm.capabilities = ["bidding", "pricing", "marketplace", "upwork", "freelancer"]

    async def _look_for_work(self):
        """Poll marketplace for tasks ready for bidding."""
        headers = {}
        if SERVICE_TOKEN:
            headers["X-Service-Token"] = SERVICE_TOKEN

        resp = await self._http.get(
            f"{self.registry_url}/list?state=idle&agent_type=bidder&limit=1",
            headers=headers,
        )
        if resp.status_code != 200:
            return
        self._log.debug("Heartbeat acknowledged, looking for bidding opportunities")


class ProspectorAgent(AgentRuntime):
    """Prospector agent — wraps prospector_service scanning logic."""

    PROSPECTOR_URL = os.getenv("PROSPECTOR_URL", "http://localhost:8900")

    def __init__(self, agent_id: str | None = None):
        super().__init__("prospector", agent_id)
        self.sm.capabilities = ["scanning", "rss", "web-scraping", "discovery", "upwork-rss"]

    async def _look_for_work(self):
        """Check prospector service for pending scans."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{self.PROSPECTOR_URL}/health")
                if resp.status_code == 200:
                    self._log.debug("Prospector service healthy")
        except Exception as e:
            self._log.debug("Prospector service unreachable: %s", e)


# ── CLI ──────────────────────────────────────────────────────────


async def main():
    parser = argparse.ArgumentParser(description="Agent N9er Launcher")
    parser.add_argument("--type", choices=AGENT_TYPES, default="bidder",
                        help="Agent type to launch")
    parser.add_argument("--id", type=str, default=None,
                        help="Custom agent ID (auto-generated if omitted)")
    parser.add_argument("--registry", type=str, default=REGISTRY_URL,
                        help=f"Registry URL (default: {REGISTRY_URL})")

    args = parser.parse_args()
    global REGISTRY_URL
    REGISTRY_URL = args.registry

    agent_class = {
        "bidder": BidderAgent,
        "prospector": ProspectorAgent,
    }.get(args.type, AgentRuntime)

    agent = agent_class(agent_id=args.id)
    logger.info("Launching %s agent (id=%s)", args.type, agent.agent_id)

    loop = asyncio.get_event_loop()
    stop_event = asyncio.Event()

    def _signal_handler():
        logger.info("Shutdown signal received")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            pass  # Windows support

    await agent.start()

    try:
        await stop_event.wait()
    finally:
        await agent.stop()


if __name__ == "__main__":
    asyncio.run(main())
