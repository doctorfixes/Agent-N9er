"""Tool definition and registration helpers."""

from __future__ import annotations

import inspect
import traceback
from typing import Any, Callable, get_type_hints

from pydantic import BaseModel


class ToolResult(BaseModel):
    """The outcome of a tool invocation."""

    output: Any = None
    error: str | None = None

    def to_content(self) -> str:
        """Serialise the result for inclusion in a tool response message."""
        if self.error is not None:
            return f"ERROR: {self.error}"
        return str(self.output)

    @property
    def ok(self) -> bool:
        return self.error is None


class Tool:
    """Wraps a Python callable so it can be called by the agent.

    Parameters
    ----------
    fn:
        The underlying Python function.  Its docstring becomes the tool
        description; parameter names and type annotations drive the
        generated JSON schema.
    name:
        Override the tool name (defaults to ``fn.__name__``).
    description:
        Override the tool description (defaults to ``fn.__doc__``).
    """

    def __init__(
        self,
        fn: Callable[..., Any],
        *,
        name: str | None = None,
        description: str | None = None,
    ) -> None:
        self._fn = fn
        self.name = name or fn.__name__
        self.description = description or (inspect.getdoc(fn) or "")

    # ------------------------------------------------------------------
    # Schema generation (OpenAI function-calling format)
    # ------------------------------------------------------------------

    def schema(self) -> dict[str, Any]:
        """Return the OpenAI-compatible tool schema."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self._parameters_schema(),
            },
        }

    def _parameters_schema(self) -> dict[str, Any]:
        sig = inspect.signature(self._fn)
        try:
            hints = get_type_hints(self._fn)
        except Exception:
            hints = {}

        properties: dict[str, Any] = {}
        required: list[str] = []

        for param_name, param in sig.parameters.items():
            if param_name in ("self", "cls"):
                continue
            prop: dict[str, Any] = {
                "type": _python_type_to_json(hints.get(param_name, str))
            }
            properties[param_name] = prop
            if param.default is inspect.Parameter.empty:
                required.append(param_name)

        return {
            "type": "object",
            "properties": properties,
            "required": required,
        }

    # ------------------------------------------------------------------
    # Invocation
    # ------------------------------------------------------------------

    def call(self, arguments: dict[str, Any]) -> ToolResult:
        """Invoke the tool with the given arguments dict."""
        try:
            output = self._fn(**arguments)
            return ToolResult(output=output)
        except Exception:
            return ToolResult(error=traceback.format_exc())


def tool(
    fn: Callable[..., Any] | None = None,
    *,
    name: str | None = None,
    description: str | None = None,
) -> Tool | Callable[[Callable[..., Any]], Tool]:
    """Decorator that converts a function into a :class:`Tool`.

    Can be used with or without arguments::

        @tool
        def greet(name: str) -> str:
            \"\"\"Return a greeting.\"\"\"
            return f"Hello, {name}!"

        @tool(name="add_numbers")
        def add(a: int, b: int) -> int:
            \"\"\"Add two numbers.\"\"\"
            return a + b
    """
    if fn is not None:
        # Used as bare @tool
        return Tool(fn, name=name, description=description)

    # Used as @tool(...) factory
    def decorator(f: Callable[..., Any]) -> Tool:
        return Tool(f, name=name, description=description)

    return decorator


# ------------------------------------------------------------------
# Type mapping helpers
# ------------------------------------------------------------------

_TYPE_MAP: dict[type, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
}


def _python_type_to_json(py_type: Any) -> str:
    """Map a Python type annotation to a JSON Schema type string."""
    origin = getattr(py_type, "__origin__", None)
    if origin is list:
        return "array"
    if origin is dict:
        return "object"
    return _TYPE_MAP.get(py_type, "string")
