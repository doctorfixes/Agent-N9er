"""Tests for agent_n9er.memory."""

import pytest

from agent_n9er.memory import Memory


def test_memory_starts_empty():
    m = Memory()
    assert len(m) == 0
    assert m.exchanges == []


def test_add_exchange():
    m = Memory()
    m.add_exchange("What is 2+2?", "It is 4.")
    assert len(m) == 1
    assert m.exchanges[0] == {"user": "What is 2+2?", "assistant": "It is 4."}


def test_exchanges_returns_copy():
    m = Memory()
    m.add_exchange("hi", "hello")
    copy = m.exchanges
    copy.append({"user": "x", "assistant": "y"})
    assert len(m) == 1  # internal list untouched


def test_memory_evicts_oldest_when_full():
    m = Memory(max_exchanges=3)
    for i in range(4):
        m.add_exchange(f"q{i}", f"a{i}")
    assert len(m) == 3
    users = [e["user"] for e in m.exchanges]
    assert users == ["q1", "q2", "q3"]


def test_clear():
    m = Memory()
    m.add_exchange("hi", "hello")
    m.clear()
    assert len(m) == 0


def test_max_exchanges_validation():
    with pytest.raises(ValueError):
        Memory(max_exchanges=0)
