import os
import sys
import time
from unittest.mock import patch

import pytest

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, root)

from shared.circuit_breaker import (
    CircuitBreaker, CircuitOpenError,
    STATE_CLOSED, STATE_OPEN, STATE_HALF_OPEN,
)


@pytest.fixture
def breaker():
    return CircuitBreaker("test", failure_threshold=3, recovery_timeout=0.1)


class TestCircuitBreakerBasic:
    async def test_starts_closed(self, breaker):
        assert breaker.state == STATE_CLOSED

    async def test_success_stays_closed(self, breaker):
        async def ok():
            return "result"

        result = await breaker.call(ok)
        assert result == "result"
        assert breaker.state == STATE_CLOSED

    async def test_single_failure_stays_closed(self, breaker):
        async def fail():
            raise ValueError("boom")

        with pytest.raises(ValueError):
            await breaker.call(fail)
        assert breaker.state == STATE_CLOSED

    async def test_opens_after_threshold_failures(self, breaker):
        async def fail():
            raise ValueError("boom")

        for _ in range(3):
            with pytest.raises(ValueError):
                await breaker.call(fail)

        assert breaker.state == STATE_OPEN

    async def test_open_circuit_rejects_calls(self, breaker):
        async def fail():
            raise ValueError("boom")

        for _ in range(3):
            with pytest.raises(ValueError):
                await breaker.call(fail)

        with pytest.raises(CircuitOpenError):
            await breaker.call(fail)

    async def test_success_resets_failure_count(self, breaker):
        async def fail():
            raise ValueError("boom")

        async def ok():
            return "ok"

        with pytest.raises(ValueError):
            await breaker.call(fail)
        with pytest.raises(ValueError):
            await breaker.call(fail)

        await breaker.call(ok)
        assert breaker._failure_count == 0
        assert breaker.state == STATE_CLOSED


class TestCircuitBreakerRecovery:
    async def test_transitions_to_half_open_after_timeout(self, breaker):
        async def fail():
            raise ValueError("boom")

        for _ in range(3):
            with pytest.raises(ValueError):
                await breaker.call(fail)

        assert breaker.state == STATE_OPEN

        import asyncio
        await asyncio.sleep(0.15)

        assert breaker.state == STATE_HALF_OPEN

    async def test_half_open_success_closes(self, breaker):
        async def fail():
            raise ValueError("boom")

        async def ok():
            return "recovered"

        for _ in range(3):
            with pytest.raises(ValueError):
                await breaker.call(fail)

        import asyncio
        await asyncio.sleep(0.15)

        result = await breaker.call(ok)
        assert result == "recovered"
        assert breaker.state == STATE_CLOSED

    async def test_half_open_failure_reopens(self, breaker):
        async def fail():
            raise ValueError("boom")

        for _ in range(3):
            with pytest.raises(ValueError):
                await breaker.call(fail)

        import asyncio
        await asyncio.sleep(0.15)

        with pytest.raises(ValueError):
            await breaker.call(fail)

        assert breaker._state == STATE_OPEN


class TestCircuitBreakerReset:
    async def test_manual_reset(self, breaker):
        async def fail():
            raise ValueError("boom")

        for _ in range(3):
            with pytest.raises(ValueError):
                await breaker.call(fail)

        assert breaker.state == STATE_OPEN

        await breaker.reset()
        assert breaker.state == STATE_CLOSED
        assert breaker._failure_count == 0


class TestCircuitBreakerConfig:
    async def test_custom_threshold(self):
        cb = CircuitBreaker("custom", failure_threshold=1)

        async def fail():
            raise ValueError("boom")

        with pytest.raises(ValueError):
            await cb.call(fail)
        assert cb.state == STATE_OPEN

    async def test_high_threshold(self):
        cb = CircuitBreaker("high", failure_threshold=10)

        async def fail():
            raise ValueError("boom")

        for _ in range(9):
            with pytest.raises(ValueError):
                await cb.call(fail)
        assert cb.state == STATE_CLOSED

        with pytest.raises(ValueError):
            await cb.call(fail)
        assert cb.state == STATE_OPEN
