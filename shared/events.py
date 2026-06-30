import os
import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Callable, Awaitable

import httpx

logger = logging.getLogger("events")

ORCHESTRATOR_URL = os.getenv("ORCHESTRATOR_URL", "http://localhost:9000")

EVENT_TASK_PUBLISHED = "task.published"
EVENT_TASK_AWARDED = "task.awarded"
EVENT_EXECUTION_COMPLETED = "execution.completed"
EVENT_EXECUTION_FAILED = "execution.failed"
EVENT_REPUTATION_UPDATED = "reputation.updated"
EVENT_PROSPECT_DISCOVERED = "prospect.discovered"
EVENT_PROSPECT_APPROVED = "prospect.approved"
EVENT_INVOICE_CREATED = "invoice.created"
EVENT_SCAN_COMPLETED = "scan.completed"
EVENT_AGENT_REGISTERED = "agent.registered"

_local_handlers: dict[str, list[Callable[[dict], Awaitable[None]]]] = {}
_event_log: list[dict] = []
_MAX_LOG = 500


def subscribe(event_type: str, handler: Callable[[dict], Awaitable[None]]):
    _local_handlers.setdefault(event_type, []).append(handler)
    logger.info("Subscribed to %s", event_type)


async def emit(event_type: str, data: dict, *, relay: bool = True):
    event = {
        "type": event_type,
        "data": data,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": os.getenv("SERVICE_NAME", "unknown"),
    }

    _event_log.append(event)
    if len(_event_log) > _MAX_LOG:
        _event_log[:] = _event_log[-_MAX_LOG:]

    for handler in _local_handlers.get(event_type, []):
        try:
            await handler(data)
        except Exception as e:
            logger.error("Event handler error for %s: %s", event_type, e)

    for handler in _local_handlers.get("*", []):
        try:
            await handler(event)
        except Exception as e:
            logger.error("Wildcard handler error: %s", e)

    if relay:
        asyncio.create_task(_relay_to_orchestrator(event))


async def _relay_to_orchestrator(event: dict):
    try:
        from shared.security import get_service_headers
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(
                f"{ORCHESTRATOR_URL}/events/relay",
                json=event,
                headers=get_service_headers(),
            )
    except Exception as e:
        logger.debug("Event relay failed (non-critical): %s", e)


def get_recent_events(limit: int = 50, event_type: str = None) -> list[dict]:
    events = _event_log
    if event_type:
        events = [e for e in events if e["type"] == event_type]
    return events[-limit:]
