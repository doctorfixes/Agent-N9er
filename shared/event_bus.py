"""
Redis-backed Event Bus with Retry + Dead Letter Queue.

Channels:
  agent:registered    — {agent_id, agent_type, capabilities, price_per_hour}
  agent:state_change  — {agent_id, old_state, new_state, current_load}
  agent:deregistered  — {agent_id}
  pipeline:stage      — {task_id, stage, status, detail}
  scan:completed      — {platform, discovered, new, errors}
"""

import json
import os
import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable

logger = logging.getLogger("event_bus")

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
DLQ_TTL = int(os.getenv("DLQ_TTL_SECONDS", "86400"))  # 24h default
EVENT_TTL = int(os.getenv("EVENT_TTL_SECONDS", "3600"))  # 1h default

# ---------------------------------------------------------------------------
# Retry Policy
# ---------------------------------------------------------------------------

@dataclass
class RetryPolicy:
    max_retries: int = 3
    base_delay: float = 0.3
    max_delay: float = 10.0
    jitter: bool = True

    def delays(self) -> list[float]:
        delays = []
        for attempt in range(self.max_retries):
            d = min(self.base_delay * (2 ** attempt), self.max_delay)
            if self.jitter:
                import random
                d = d * (0.5 + random.random())
            delays.append(d)
        return delays


async def process_with_retry(fn: Callable[[Any], Awaitable[Any]], event: Any, policy: RetryPolicy | None = None) -> bool:
    """Run fn(event) with retry. Returns True if succeeded, False if exhausted."""
    if policy is None:
        policy = RetryPolicy()
    delays = policy.delays()
    last_exc = None
    for attempt in range(policy.max_retries):
        try:
            await fn(event)
            return True
        except Exception as e:
            last_exc = e
            if attempt < policy.max_retries - 1:
                logger.warning("Retry %d/%d for handler: %s", attempt + 1, policy.max_retries, e)
                await asyncio.sleep(delays[attempt])
    logger.error("Exhausted %d retries: %s", policy.max_retries, last_exc)
    return False


# ---------------------------------------------------------------------------
# Dead Letter Queue
# ---------------------------------------------------------------------------

class DLQ:
    """Redis-backed dead letter queue. Events that exhaust retries go here."""

    def __init__(self, redis_client=None):
        self._redis_client = redis_client  # lazily resolved
        self._conn = None  # optional sqlite fallback

    async def _get_redis(self):
        if self._redis_client is None:
            try:
                import redis.asyncio as aioredis
                self._redis_client = aioredis.from_url(REDIS_URL, decode_responses=True)
            except Exception:
                logger.warning("Redis unavailable, DLQ falls back to in-memory store")
                self._redis_client = object()  # sentinel
                self._in_memory = []
        return self._redis_client

    async def push(self, channel: str, event: dict, error: str):
        entry = {
            "channel": channel,
            "event": event,
            "error": error,
            "ts": time.time(),
        }
        key = f"dlq:{channel}"
        payload = json.dumps(entry)
        try:
            r = await self._get_redis()
            if hasattr(r, "lpush"):
                await r.lpush(key, payload)
                await r.expire(key, DLQ_TTL)
                return
        except Exception:
            pass
        # In-memory fallback
        if not hasattr(self, "_in_memory"):
            self._in_memory = []
        self._in_memory.append(entry)

    async def pop(self, channel: str = None) -> list[dict]:
        """Pop and return all DLQ entries for a channel (or all channels)."""
        results = []
        try:
            r = await self._get_redis()
            if hasattr(r, "keys"):
                if channel:
                    keys = [f"dlq:{channel}"]
                else:
                    keys = [k async for k in r.scan_iter("dlq:*")]
                for key in keys:
                    while True:
                        entry = await r.rpop(key)
                        if entry is None:
                            break
                        results.append(json.loads(entry))
        except Exception:
            pass
        # Also check in-memory
        if hasattr(self, "_in_memory"):
            results.extend(self._in_memory)
            self._in_memory = []
        return results


# ---------------------------------------------------------------------------
# Event Bus
# ---------------------------------------------------------------------------

class EventBus:
    """Redis pubsub event bus with retry + DLQ."""

    def __init__(self, redis_url: str | None = None):
        self._redis_url = redis_url or REDIS_URL
        self._pub_client = None
        self._sub_client = None
        self._running = False
        self._handlers: dict[str, list[Callable]] = {}
        self.dlq = DLQ()
        self.retry_policy = RetryPolicy()

    async def _get_pub(self):
        if self._pub_client is None:
            try:
                import redis.asyncio as aioredis
                self._pub_client = aioredis.from_url(self._redis_url, decode_responses=True)
            except Exception as e:
                logger.warning("Redis pub client failed (%s), using in-memory fallback", e)
                self._pub_client = InMemoryPubSub()
        return self._pub_client

    async def _get_sub(self):
        if self._sub_client is None:
            try:
                import redis.asyncio as aioredis
                self._sub_client = aioredis.from_url(self._redis_url, decode_responses=True)
            except Exception as e:
                logger.warning("Redis sub client failed (%s), using in-memory fallback", e)
                self._sub_client = InMemoryPubSub()
        return self._sub_client

    async def publish(self, channel: str, event: dict):
        """Publish an event to the channel."""
        payload = json.dumps({
            **event,
            "_ts": time.time(),
            "_channel": channel,
        })
        try:
            client = await self._get_pub()
            await client.publish(channel, payload)
            logger.debug("Published event to %s: %s", channel, event.get("event_type", "?"))
        except Exception as e:
            logger.error("Failed to publish to %s: %s", channel, e)

    def subscribe(self, channel: str, handler: Callable[[dict], Awaitable[None]]):
        """Register an async handler for a channel. Multiple handlers per channel."""
        if channel not in self._handlers:
            self._handlers[channel] = []
        self._handlers[channel].append(handler)

    def unsubscribe(self, channel: str, handler: Callable = None):
        """Remove handler(s) from a channel."""
        if handler:
            self._handlers[channel] = [h for h in self._handlers.get(channel, []) if h != handler]
        else:
            self._handlers.pop(channel, None)

    async def _dispatch(self, channel: str, message: dict):
        """Dispatch a parsed message to all handlers for the channel, with retry."""
        if channel not in self._handlers:
            return
        for handler in self._handlers[channel]:
            ok = await process_with_retry(handler, message, self.retry_policy)
            if not ok:
                await self.dlq.push(channel, message, f"Handler {handler.__name__} failed after retries")

    async def start(self):
        """Start listening on subscribed channels."""
        if self._running:
            return
        self._running = True
        try:
            client = await self._get_sub()
            pubsub = client.pubsub()
            channels = list(self._handlers.keys())
            if not channels:
                logger.info("EventBus: no channels to subscribe to")
                return
            await pubsub.subscribe(*channels)
            logger.info("EventBus: subscribed to %s", channels)
            while self._running:
                try:
                    raw = await pubsub.get_message(timeout=1.0)
                    if raw and raw["type"] == "message":
                        channel = raw["channel"]
                        try:
                            data = json.loads(raw["data"])
                        except json.JSONDecodeError:
                            data = {"raw": raw["data"]}
                        asyncio.ensure_future(self._dispatch(channel, data))
                except asyncio.TimeoutError:
                    continue
                except Exception as e:
                    logger.error("EventBus loop error: %s", e)
                    await asyncio.sleep(1)
        except Exception as e:
            logger.error("EventBus start failed: %s", e)
        finally:
            self._running = False

    async def stop(self):
        self._running = False


# ---------------------------------------------------------------------------
# In-memory fallback (no Redis)
# ---------------------------------------------------------------------------

class InMemoryPubSub:
    """Minimal in-memory pubsub for dev/test when Redis is absent."""

    def __init__(self):
        self._subs: dict[str, list] = {}

    async def publish(self, channel: str, message: str):
        if channel in self._subs:
            for queue in self._subs[channel]:
                try:
                    await queue.put({"type": "message", "channel": channel, "data": message})
                except Exception:
                    pass

    def pubsub(self):
        return InMemoryPubSubListener(self._subs)


class InMemoryPubSubListener:
    def __init__(self, subs: dict):
        self._subs = subs
        self._channels = []
        self._queues = {}

    async def subscribe(self, *channels: str):
        for ch in channels:
            if ch not in self._subs:
                self._subs[ch] = []
            q = asyncio.Queue()
            self._subs[ch].append(q)
            self._queues[ch] = q
            self._channels.append(ch)

    async def get_message(self, timeout: float = 1.0):
        for ch in self._channels:
            q = self._queues.get(ch)
            if q and not q.empty():
                return await q.get()
        await asyncio.sleep(timeout)
        return None