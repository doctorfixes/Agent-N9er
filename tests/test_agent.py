"""Tests for agent_n9er.agent (no real OpenAI calls)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agent_n9er.agent import Agent, AgentConfig, Message
from agent_n9er.memory import Memory
from agent_n9er.tools import tool


# ---------------------------------------------------------------------------
# AgentConfig
# ---------------------------------------------------------------------------


def test_agent_config_defaults():
    cfg = AgentConfig()
    assert cfg.model == "gpt-4o"
    assert cfg.max_iterations == 10
    assert cfg.temperature == 0.2


def test_agent_config_max_iterations_bounds():
    with pytest.raises(Exception):
        AgentConfig(max_iterations=0)
    with pytest.raises(Exception):
        AgentConfig(max_iterations=101)


def test_agent_config_temperature_bounds():
    with pytest.raises(Exception):
        AgentConfig(temperature=-0.1)
    with pytest.raises(Exception):
        AgentConfig(temperature=2.1)


# ---------------------------------------------------------------------------
# Agent initialisation
# ---------------------------------------------------------------------------


def test_agent_registers_tools():
    @tool
    def ping(x: str) -> str:
        """Return pong."""
        return "pong"

    agent = Agent(tools=[ping])
    assert "ping" in agent.tools


def test_agent_default_memory():
    agent = Agent()
    assert isinstance(agent.memory, Memory)


def test_agent_custom_memory():
    mem = Memory(max_exchanges=5)
    agent = Agent(memory=mem)
    assert agent.memory is mem


# ---------------------------------------------------------------------------
# _build_messages
# ---------------------------------------------------------------------------


def test_build_messages_includes_system_and_user():
    agent = Agent()
    msgs = agent._build_messages("Hello!")
    roles = [m.role for m in msgs]
    assert roles[0] == "system"
    assert roles[-1] == "user"
    assert msgs[-1].content == "Hello!"


def test_build_messages_includes_history():
    agent = Agent()
    agent.memory.add_exchange("prev question", "prev answer")
    msgs = agent._build_messages("new question")
    contents = [m.content for m in msgs]
    assert "prev question" in contents
    assert "prev answer" in contents


# ---------------------------------------------------------------------------
# _call_tool
# ---------------------------------------------------------------------------


def test_call_tool_success():
    @tool
    def double(n: int) -> int:
        """Double a number."""
        return n * 2

    agent = Agent(tools=[double])
    result = agent._call_tool("double", '{"n": 5}')
    assert result.ok
    assert result.output == 10


def test_call_tool_unknown():
    agent = Agent()
    result = agent._call_tool("nonexistent", "{}")
    assert not result.ok
    assert "Unknown tool" in result.error


def test_call_tool_bad_json():
    @tool
    def noop(x: str) -> str:
        """Do nothing."""
        return x

    agent = Agent(tools=[noop])
    result = agent._call_tool("noop", "not json!")
    assert not result.ok
    assert "Invalid tool arguments" in result.error


# ---------------------------------------------------------------------------
# agent.run – mocked OpenAI
# ---------------------------------------------------------------------------


def _make_choice(content: str, finish_reason: str = "stop") -> MagicMock:
    choice = MagicMock()
    choice.finish_reason = finish_reason
    choice.message.content = content
    choice.message.tool_calls = None
    return choice


def _make_tool_call_choice(
    tool_call_id: str, fn_name: str, fn_args: str
) -> MagicMock:
    tc = MagicMock()
    tc.id = tool_call_id
    tc.function.name = fn_name
    tc.function.arguments = fn_args
    tc.model_dump.return_value = {
        "id": tool_call_id,
        "type": "function",
        "function": {"name": fn_name, "arguments": fn_args},
    }

    choice = MagicMock()
    choice.finish_reason = "tool_calls"
    choice.message.content = None
    choice.message.tool_calls = [tc]
    return choice


def _make_response(choice: MagicMock) -> MagicMock:
    resp = MagicMock()
    resp.choices = [choice]
    return resp


@patch("agent_n9er.agent.OpenAI")
def test_run_simple_answer(mock_openai_cls):
    client = MagicMock()
    mock_openai_cls.return_value = client
    client.chat.completions.create.return_value = _make_response(
        _make_choice("The answer is 42.")
    )

    agent = Agent()
    answer = agent.run("What is the answer?")
    assert answer == "The answer is 42."


@patch("agent_n9er.agent.OpenAI")
def test_run_stores_exchange_in_memory(mock_openai_cls):
    client = MagicMock()
    mock_openai_cls.return_value = client
    client.chat.completions.create.return_value = _make_response(
        _make_choice("pong")
    )

    agent = Agent()
    agent.run("ping")
    assert len(agent.memory) == 1
    assert agent.memory.exchanges[0]["user"] == "ping"
    assert agent.memory.exchanges[0]["assistant"] == "pong"


@patch("agent_n9er.agent.OpenAI")
def test_run_with_tool_call(mock_openai_cls):
    client = MagicMock()
    mock_openai_cls.return_value = client

    @tool
    def add(a: int, b: int) -> int:
        """Add two numbers."""
        return a + b

    client.chat.completions.create.side_effect = [
        _make_response(
            _make_tool_call_choice("call_1", "add", '{"a": 3, "b": 4}')
        ),
        _make_response(_make_choice("The result is 7.")),
    ]

    agent = Agent(tools=[add])
    answer = agent.run("What is 3 + 4?")
    assert answer == "The result is 7."
    assert client.chat.completions.create.call_count == 2


@patch("agent_n9er.agent.OpenAI")
def test_run_raises_after_max_iterations(mock_openai_cls):
    client = MagicMock()
    mock_openai_cls.return_value = client

    @tool
    def loop_tool(x: int) -> int:
        """Always loops."""
        return x

    # Always return a tool_call so the loop never exits naturally
    client.chat.completions.create.return_value = _make_response(
        _make_tool_call_choice("call_x", "loop_tool", '{"x": 1}')
    )

    cfg = AgentConfig(max_iterations=2)
    agent = Agent(tools=[loop_tool], config=cfg)
    with pytest.raises(RuntimeError, match="did not finish"):
        agent.run("go forever")


@patch("agent_n9er.agent.OpenAI", None)
def test_run_missing_openai_raises():
    agent = Agent()
    with pytest.raises(RuntimeError, match="openai package is required"):
        agent.run("hello")
