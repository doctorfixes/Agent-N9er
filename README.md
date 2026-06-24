# Agent-N9er

A lightweight, tool-using AI agent framework built on the OpenAI Chat Completions API.

## Features

- **ReAct-style think/act loop** – the agent reasons, calls tools, observes results, and repeats until it has an answer.
- **Simple `@tool` decorator** – turn any Python function into a tool with one line.
- **Conversation memory** – optional rolling memory keeps prior exchanges in context.
- **Rich CLI** – interactive REPL or single-shot mode, powered by [Rich](https://github.com/Textualize/rich).
- **Pydantic-validated config** – safe defaults with sensible bounds.

## Installation

```bash
pip install -e ".[dev]"   # development install with test dependencies
```

An `OPENAI_API_KEY` environment variable is required at runtime.

## Quick start

```python
from agent_n9er import Agent, tool

@tool
def get_weather(city: str) -> str:
    """Return the current weather for a city."""
    return f"It is sunny and 22 °C in {city}."

agent = Agent(tools=[get_weather])
print(agent.run("What's the weather like in Paris?"))
```

## CLI

```bash
# Interactive REPL
n9er

# Single-shot
n9er "Summarise the Zen of Python in three bullet points"

# Choose model / iteration cap
n9er --model gpt-4o-mini --max-iterations 5 "What is 123 * 456?"
```

## Project layout

```
src/
  agent_n9er/
    __init__.py   – public API
    agent.py      – Agent class and AgentConfig
    tools.py      – Tool, ToolResult, @tool decorator
    memory.py     – Memory (rolling conversation history)
    cli.py        – Click-based CLI entry point
tests/
  test_agent.py
  test_memory.py
  test_tools.py
```

## Running tests

```bash
pytest
```

## License

MIT
