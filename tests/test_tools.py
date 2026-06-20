"""Tests for agent_n9er.tools."""

import pytest

from agent_n9er.tools import Tool, ToolResult, _python_type_to_json, tool


# ---------------------------------------------------------------------------
# ToolResult
# ---------------------------------------------------------------------------


def test_tool_result_ok_with_output():
    r = ToolResult(output=42)
    assert r.ok
    assert r.to_content() == "42"


def test_tool_result_error():
    r = ToolResult(error="something went wrong")
    assert not r.ok
    assert r.to_content() == "ERROR: something went wrong"


# ---------------------------------------------------------------------------
# Tool schema generation
# ---------------------------------------------------------------------------


def add(a: int, b: int) -> int:
    """Add two integers."""
    return a + b


def test_tool_schema_structure():
    t = Tool(add)
    schema = t.schema()
    assert schema["type"] == "function"
    fn = schema["function"]
    assert fn["name"] == "add"
    assert fn["description"] == "Add two integers."
    params = fn["parameters"]
    assert params["type"] == "object"
    assert set(params["required"]) == {"a", "b"}
    assert params["properties"]["a"]["type"] == "integer"
    assert params["properties"]["b"]["type"] == "integer"


def test_tool_schema_custom_name_and_description():
    t = Tool(add, name="sum_two", description="Sum two numbers.")
    schema = t.schema()
    assert schema["function"]["name"] == "sum_two"
    assert schema["function"]["description"] == "Sum two numbers."


def test_tool_schema_optional_param_not_required():
    def greet(name: str, greeting: str = "Hello") -> str:
        """Greet someone."""
        return f"{greeting}, {name}!"

    t = Tool(greet)
    schema = t.schema()
    required = schema["function"]["parameters"]["required"]
    assert "name" in required
    assert "greeting" not in required


# ---------------------------------------------------------------------------
# Tool.call
# ---------------------------------------------------------------------------


def test_tool_call_success():
    t = Tool(add)
    result = t.call({"a": 3, "b": 4})
    assert result.ok
    assert result.output == 7


def test_tool_call_error_propagation():
    def boom(x: int) -> int:
        """Always raises."""
        raise ValueError("boom!")

    t = Tool(boom)
    result = t.call({"x": 1})
    assert not result.ok
    assert "ValueError" in result.error
    assert "boom!" in result.error


# ---------------------------------------------------------------------------
# @tool decorator
# ---------------------------------------------------------------------------


def test_tool_decorator_bare():
    @tool
    def multiply(a: int, b: int) -> int:
        """Multiply two integers."""
        return a * b

    assert isinstance(multiply, Tool)
    result = multiply.call({"a": 6, "b": 7})
    assert result.output == 42


def test_tool_decorator_with_args():
    @tool(name="sub", description="Subtract b from a.")
    def subtract(a: int, b: int) -> int:
        return a - b

    assert isinstance(subtract, Tool)
    assert subtract.name == "sub"
    assert subtract.description == "Subtract b from a."
    result = subtract.call({"a": 10, "b": 3})
    assert result.output == 7


# ---------------------------------------------------------------------------
# Type mapping
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "py_type,expected",
    [
        (str, "string"),
        (int, "integer"),
        (float, "number"),
        (bool, "boolean"),
        (list, "array"),
        (dict, "object"),
    ],
)
def test_python_type_to_json(py_type, expected):
    assert _python_type_to_json(py_type) == expected


def test_python_type_to_json_generic_list():
    from typing import List

    assert _python_type_to_json(List[str]) == "array"


def test_python_type_to_json_unknown_falls_back_to_string():
    class Custom:
        pass

    assert _python_type_to_json(Custom) == "string"
