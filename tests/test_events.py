"""Tests for shared/events.py — event bus with subscribe, emit, and log."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from shared.events import (
    emit,
    subscribe,
    get_recent_events,
    _event_log,
    _local_handlers,
    _MAX_LOG,
)


@pytest.fixture(autouse=True)
def _clear_global_state():
    _event_log.clear()
    _local_handlers.clear()
    yield
    _event_log.clear()
    _local_handlers.clear()


class TestEmit:
    async def test_emit_stores_event(self):
        await emit("task.published", {"id": 1}, relay=False)
        assert len(_event_log) == 1
        assert _event_log[0]["type"] == "task.published"
        assert _event_log[0]["data"] == {"id": 1}

    async def test_emit_multiple_events(self):
        await emit("a", {}, relay=False)
        await emit("b", {}, relay=False)
        assert len(_event_log) == 2

    async def test_event_has_timestamp_and_source(self):
        await emit("x", {}, relay=False)
        assert "timestamp" in _event_log[0]
        assert "source" in _event_log[0]

    async def test_log_caps_at_500(self):
        for i in range(510):
            await emit("flood", {"i": i}, relay=False)
        assert len(_event_log) == _MAX_LOG

    async def test_relay_false_no_http(self):
        with patch("shared.events._relay_to_orchestrator", new_callable=AsyncMock) as mock_relay:
            await emit("x", {}, relay=False)
            mock_relay.assert_not_called()

    async def test_relay_true_creates_task(self):
        with patch("shared.events._relay_to_orchestrator", new_callable=AsyncMock) as mock_relay:
            await emit("x", {}, relay=True)
            # Give the created task a chance to run
            await asyncio.sleep(0.05)
            mock_relay.assert_called_once()


class TestSubscribe:
    async def test_handler_called_on_emit(self):
        handler = AsyncMock()
        subscribe("task.published", handler)
        await emit("task.published", {"id": 1}, relay=False)
        handler.assert_called_once_with({"id": 1})

    async def test_handler_not_called_for_other_type(self):
        handler = AsyncMock()
        subscribe("task.published", handler)
        await emit("task.awarded", {}, relay=False)
        handler.assert_not_called()

    async def test_wildcard_receives_all(self):
        handler = AsyncMock()
        subscribe("*", handler)
        await emit("task.published", {"a": 1}, relay=False)
        await emit("task.awarded", {"b": 2}, relay=False)
        assert handler.call_count == 2
        # Wildcard receives the full event dict (not just data)
        assert handler.call_args_list[0][0][0]["type"] == "task.published"

    async def test_handler_error_does_not_crash(self):
        bad = AsyncMock(side_effect=RuntimeError("boom"))
        subscribe("x", bad)
        # Should not raise
        await emit("x", {}, relay=False)
        assert len(_event_log) == 1

    async def test_wildcard_handler_error_does_not_crash(self):
        bad = AsyncMock(side_effect=RuntimeError("boom"))
        subscribe("*", bad)
        await emit("x", {}, relay=False)
        assert len(_event_log) == 1


class TestGetRecentEvents:
    async def test_returns_events(self):
        await emit("a", {}, relay=False)
        await emit("b", {}, relay=False)
        events = get_recent_events()
        assert len(events) == 2

    async def test_respects_limit(self):
        for i in range(10):
            await emit("a", {"i": i}, relay=False)
        events = get_recent_events(limit=3)
        assert len(events) == 3
        # Returns the most recent
        assert events[-1]["data"]["i"] == 9

    async def test_filters_by_type(self):
        await emit("a", {}, relay=False)
        await emit("b", {}, relay=False)
        await emit("a", {}, relay=False)
        events = get_recent_events(event_type="a")
        assert len(events) == 2
        assert all(e["type"] == "a" for e in events)

    async def test_filter_and_limit_combined(self):
        for i in range(5):
            await emit("a", {"i": i}, relay=False)
            await emit("b", {}, relay=False)
        events = get_recent_events(limit=2, event_type="a")
        assert len(events) == 2
        assert all(e["type"] == "a" for e in events)
