import asyncio
import logging
import time

logger = logging.getLogger("circuit_breaker")

STATE_CLOSED = "closed"
STATE_OPEN = "open"
STATE_HALF_OPEN = "half_open"


class CircuitBreaker:
    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        half_open_max: int = 1,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max = half_open_max

        self._state = STATE_CLOSED
        self._failure_count = 0
        self._last_failure_time = 0.0
        self._half_open_calls = 0
        self._lock = asyncio.Lock()

    @property
    def state(self):
        if self._state == STATE_OPEN:
            if time.monotonic() - self._last_failure_time >= self.recovery_timeout:
                return STATE_HALF_OPEN
        return self._state

    async def call(self, func, *args, **kwargs):
        async with self._lock:
            current_state = self.state

            if current_state == STATE_OPEN:
                raise CircuitOpenError(
                    f"Circuit '{self.name}' is open after {self._failure_count} failures"
                )

            if current_state == STATE_HALF_OPEN and self._half_open_calls >= self.half_open_max:
                raise CircuitOpenError(
                    f"Circuit '{self.name}' is half-open, max probe calls reached"
                )

            if current_state == STATE_HALF_OPEN:
                self._half_open_calls += 1

        try:
            result = await func(*args, **kwargs)
            await self._on_success()
            return result
        except Exception as e:
            await self._on_failure()
            raise

    async def _on_success(self):
        async with self._lock:
            if self._state in (STATE_HALF_OPEN, STATE_OPEN):
                logger.info("Circuit '%s' recovered, closing", self.name)
            self._state = STATE_CLOSED
            self._failure_count = 0
            self._half_open_calls = 0

    async def _on_failure(self):
        async with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.monotonic()

            if self._state == STATE_HALF_OPEN:
                self._state = STATE_OPEN
                logger.warning("Circuit '%s' probe failed, reopening", self.name)
            elif self._failure_count >= self.failure_threshold:
                self._state = STATE_OPEN
                logger.warning(
                    "Circuit '%s' opened after %d failures",
                    self.name, self._failure_count,
                )

    async def reset(self):
        async with self._lock:
            self._state = STATE_CLOSED
            self._failure_count = 0
            self._half_open_calls = 0


class CircuitOpenError(Exception):
    pass
