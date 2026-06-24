"""Simple in-process conversation memory."""

from __future__ import annotations

from typing import Any


class Memory:
    """Stores a list of past user/assistant exchange pairs.

    The agent injects prior exchanges as few-shot context so it can
    maintain continuity across multiple :meth:`Agent.run` calls within
    the same session.

    Parameters
    ----------
    max_exchanges:
        Maximum number of exchanges to keep.  Older exchanges are
        dropped when the limit is exceeded (FIFO).
    """

    def __init__(self, max_exchanges: int = 20) -> None:
        if max_exchanges < 1:
            raise ValueError("max_exchanges must be at least 1")
        self.max_exchanges = max_exchanges
        self._exchanges: list[dict[str, str]] = []

    @property
    def exchanges(self) -> list[dict[str, str]]:
        return list(self._exchanges)

    def add_exchange(self, user: str, assistant: str) -> None:
        """Append a completed exchange and evict the oldest if necessary."""
        self._exchanges.append({"user": user, "assistant": assistant})
        if len(self._exchanges) > self.max_exchanges:
            self._exchanges.pop(0)

    def clear(self) -> None:
        """Remove all stored exchanges."""
        self._exchanges.clear()

    def __len__(self) -> int:
        return len(self._exchanges)

    def __repr__(self) -> str:  # pragma: no cover
        return f"Memory(exchanges={len(self)}, max={self.max_exchanges})"
