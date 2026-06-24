"""Command-line interface for Agent-N9er."""

from __future__ import annotations

import sys

import click
from rich.console import Console
from rich.markdown import Markdown
from rich.prompt import Prompt

console = Console()


@click.command()
@click.option(
    "--model",
    default="gpt-4o",
    show_default=True,
    help="OpenAI model to use.",
)
@click.option(
    "--max-iterations",
    default=10,
    show_default=True,
    type=click.IntRange(1, 100),
    help="Maximum number of think/act iterations.",
)
@click.argument("prompt", required=False)
def main(model: str, max_iterations: int, prompt: str | None) -> None:
    """Run Agent-N9er.

    If PROMPT is given it is processed once and the program exits.
    Otherwise an interactive REPL is started.
    """
    from agent_n9er.agent import Agent, AgentConfig

    config = AgentConfig(model=model, max_iterations=max_iterations)
    agent = Agent(config=config)

    if prompt:
        _run_once(agent, prompt)
    else:
        _repl(agent)


def _run_once(agent: "Agent", prompt: str) -> None:
    try:
        answer = agent.run(prompt)
        console.print(Markdown(answer))
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]Error:[/red] {exc}", file=sys.stderr)
        sys.exit(1)


def _repl(agent: "Agent") -> None:
    console.print("[bold cyan]Agent-N9er[/bold cyan]  (type [bold]exit[/bold] to quit)")
    while True:
        try:
            user_input = Prompt.ask("[bold green]You[/bold green]")
        except (EOFError, KeyboardInterrupt):
            console.print("\nBye!")
            break

        if user_input.strip().lower() in {"exit", "quit", "bye"}:
            console.print("Bye!")
            break

        try:
            answer = agent.run(user_input)
            console.print(Markdown(answer))
        except Exception as exc:  # noqa: BLE001
            console.print(f"[red]Error:[/red] {exc}")
