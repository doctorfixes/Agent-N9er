"""Core Agent class that orchestrates a tool-use loop."""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import BaseModel, Field

from agent_n9er.memory import Memory
from agent_n9er.tools import Tool, ToolResult

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover
    OpenAI = None  # type: ignore[assignment,misc]

logger = logging.getLogger(__name__)


class Message(BaseModel):
    """A single conversation turn."""

    role: str
    content: str | None = None
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None
    name: str | None = None


class AgentConfig(BaseModel):
    """Runtime configuration for an Agent."""

    model: str = "gpt-4o"
    max_iterations: int = Field(default=10, ge=1, le=100)
    system_prompt: str = (
        "You are Agent N9er, an elite autonomous freelance agent. You win contracts "
        "by writing precise, technically excellent proposals and delivering production-ready "
        "work that exceeds client expectations.\n\n"
        "CORE DIRECTIVES:\n"
        "1. UNDERSTAND before you act — restate the client's actual problem, not just their words.\n"
        "2. SCOPE precisely — break work into concrete deliverables with time estimates.\n"
        "3. EXECUTE with quality — write clean, tested, documented code. No placeholders.\n"
        "4. COMMUNICATE proactively — flag risks early, provide progress updates, deliver ahead of schedule.\n"
        "5. OPTIMIZE for profit — prioritize high-leverage tasks where AI has a structural advantage.\n\n"
        "ETHICAL BOUNDARIES:\n"
        "- Never misrepresent capabilities or fabricate experience.\n"
        "- Decline tasks requiring deception, legal violations, or harm.\n"
        "- Be transparent that you are an AI agent when platform rules require disclosure.\n"
        "- Protect client data and never leak project details across engagements.\n\n"
        "COMPETITIVE EDGE:\n"
        "- You deliver 10x faster than human freelancers on code, data, and content tasks.\n"
        "- You provide working code, not pseudocode. Tests, not promises.\n"
        "- Your proposals address the client's specific pain point in the first sentence.\n"
        "- You underpromise on timeline and overdeliver on scope."
    )
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)


class Agent:
    """A tool-using AI agent that runs a ReAct-style think/act loop.

    Example::

        from agent_n9er import Agent, tool

        @tool
        def add(a: int, b: int) -> int:
            \"\"\"Return the sum of two integers.\"\"\"
            return a + b

        agent = Agent(tools=[add])
        result = agent.run("What is 7 + 35?")
        print(result)
    """

    def __init__(
        self,
        tools: list[Tool] | None = None,
        config: AgentConfig | None = None,
        memory: Memory | None = None,
    ) -> None:
        self.config = config or AgentConfig()
        self.tools: dict[str, Tool] = {t.name: t for t in (tools or [])}
        self.memory = memory if memory is not None else Memory()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self, user_message: str) -> str:
        """Run the agent on a user message and return the final answer.

        This method drives the think/act loop synchronously using the
        OpenAI Chat Completions API.  The loop continues until the model
        returns a plain text response (no more tool calls) or the
        maximum number of iterations is reached.
        """
        if OpenAI is None:
            raise RuntimeError(
                "openai package is required to run the agent. "
                "Install it with: pip install openai"
            )

        client = OpenAI()
        messages = self._build_messages(user_message)
        tool_schemas = [t.schema() for t in self.tools.values()]

        for iteration in range(self.config.max_iterations):
            logger.debug("Iteration %d", iteration + 1)

            kwargs: dict[str, Any] = dict(
                model=self.config.model,
                temperature=self.config.temperature,
                messages=[m.model_dump(exclude_none=True) for m in messages],
            )
            if tool_schemas:
                kwargs["tools"] = tool_schemas
                kwargs["tool_choice"] = "auto"

            response = client.chat.completions.create(**kwargs)
            choice = response.choices[0]
            assistant_msg = choice.message

            # Store the assistant turn
            messages.append(
                Message(
                    role="assistant",
                    content=assistant_msg.content,
                    tool_calls=(
                        [tc.model_dump() for tc in assistant_msg.tool_calls]
                        if assistant_msg.tool_calls
                        else None
                    ),
                )
            )

            if choice.finish_reason == "stop" or not assistant_msg.tool_calls:
                answer = assistant_msg.content or ""
                self.memory.add_exchange(user_message, answer)
                return answer

            # Execute all requested tool calls
            for tc in assistant_msg.tool_calls:
                result = self._call_tool(tc.function.name, tc.function.arguments)
                messages.append(
                    Message(
                        role="tool",
                        tool_call_id=tc.id,
                        name=tc.function.name,
                        content=result.to_content(),
                    )
                )

        raise RuntimeError(
            f"Agent did not finish within {self.config.max_iterations} iterations."
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_messages(self, user_message: str) -> list[Message]:
        messages: list[Message] = [
            Message(role="system", content=self.config.system_prompt)
        ]
        for exchange in self.memory.exchanges:
            messages.append(Message(role="user", content=exchange["user"]))
            messages.append(Message(role="assistant", content=exchange["assistant"]))
        messages.append(Message(role="user", content=user_message))
        return messages

    def _call_tool(self, name: str, arguments_json: str) -> ToolResult:
        if name not in self.tools:
            return ToolResult(error=f"Unknown tool: {name!r}")
        try:
            args: dict[str, Any] = json.loads(arguments_json)
        except json.JSONDecodeError as exc:
            return ToolResult(error=f"Invalid tool arguments: {exc}")
        return self.tools[name].call(args)
