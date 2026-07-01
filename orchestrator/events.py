"""
Event handlers for the orchestrator.
Subscribes to agent and pipeline events via the EventBus.
"""

import os
import logging
from typing import Any

import httpx

logger = logging.getLogger("orchestrator.events")

# ---------------------------------------------------------------------------
# Agent event handlers
# ---------------------------------------------------------------------------

async def on_agent_registered(event: dict):
    """React to agent registration — log it, downstream could trigger eval."""
    agent_id = event.get("agent_id", "?")
    agent_type = event.get("agent_type", "unknown")
    caps = event.get("capabilities", [])
    logger.info("[EVENT] Agent registered: %s (type=%s, %d capabilities)", agent_id, agent_type, len(caps))


async def on_agent_state_change(event: dict):
    """When an agent changes state, log and potentially rebalance workloads."""
    agent_id = event.get("agent_id", "?")
    old_state = event.get("old_state", "?")
    new_state = event.get("new_state", "?")
    load = event.get("current_load", 0)
    logger.info("[EVENT] Agent %s: %s → %s (load=%d)", agent_id, old_state, new_state, load)


async def on_agent_deregistered(event: dict):
    """Agent left the pool."""
    agent_id = event.get("agent_id", "?")
    logger.info("[EVENT] Agent deregistered: %s", agent_id)


# ---------------------------------------------------------------------------
# Pipeline event handlers
# ---------------------------------------------------------------------------

async def on_pipeline_stage(event: dict):
    """Log pipeline stage transitions."""
    task_id = event.get("task_id", "?")
    stage = event.get("stage", "?")
    status = event.get("status", "?")
    detail = event.get("detail", "")
    logger.info("[PIPELINE] task=%s stage=%s status=%s %s", task_id, stage, status, detail)


# ---------------------------------------------------------------------------
# Scan event handlers
# ---------------------------------------------------------------------------

async def on_scan_completed(event: dict):
    """Log scan results and trigger follow-up if new prospects found."""
    platform = event.get("platform", "?")
    discovered = event.get("discovered", 0)
    new_prospects = event.get("new", 0)
    errors = event.get("errors", [])
    logger.info("[SCAN] %s: %d discovered, %d new", platform, discovered, new_prospects)
    if errors:
        logger.warning("[SCAN] %s errors: %s", platform, errors[:3])


# ---------------------------------------------------------------------------
# Register all handlers with the event bus
# ---------------------------------------------------------------------------

def register_handlers(bus):
    """Attach all event handlers to the bus."""
    bus.subscribe("agent:registered", on_agent_registered)
    bus.subscribe("agent:state_change", on_agent_state_change)
    bus.subscribe("agent:deregistered", on_agent_deregistered)
    bus.subscribe("pipeline:stage", on_pipeline_stage)
    bus.subscribe("scan:completed", on_scan_completed)
    logger.info("Registered %d event handlers", 5)
    return bus