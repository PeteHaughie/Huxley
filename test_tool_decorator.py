from harness.tool.decorator import tool, get_registered_tools, clear_registered_tools


def setup_function():
    clear_registered_tools()


def teardown_function():
    clear_registered_tools()


def test_tool_decorator_registers_function():
    @tool()
    def my_tool(x: str) -> str:
        return x.upper()

    reg = get_registered_tools()
    assert "my_tool" in reg
    assert reg["my_tool"]["fn"] is my_tool


def test_tool_decorator_custom_name():
    @tool(name="custom_name")
    def my_tool(x: str) -> str:
        return x

    reg = get_registered_tools()
    assert "custom_name" in reg
    assert "my_tool" not in reg


def test_tool_decorator_custom_description():
    @tool(description="Does a thing")
    def my_tool(x: str) -> str:
        return x

    definition = get_registered_tools()["my_tool"]["definition"]
    assert definition["function"]["description"] == "Does a thing"


def test_tool_definition_uses_docstring():
    @tool()
    def my_tool(x: str) -> str:
        """This is the docstring description"""
        return x

    definition = get_registered_tools()["my_tool"]["definition"]
    assert definition["function"]["description"] == "This is the docstring description"


def test_tool_definition_json_schema():
    @tool()
    def my_tool(name: str, count: int, active: bool = True) -> str:
        return f"{name}: {count}"

    definition = get_registered_tools()["my_tool"]["definition"]
    params = definition["function"]["parameters"]
    assert params["type"] == "object"
    assert params["required"] == ["name", "count"]
    assert params["properties"]["name"]["type"] == "string"
    assert params["properties"]["count"]["type"] == "integer"
    assert params["properties"]["active"]["type"] == "boolean"
    assert "default" not in params["properties"]["name"]
    assert params["properties"]["active"].get("default") is True


def test_tool_definition_json_schema_pep604_optional():
    @tool()
    def my_tool(count: int | None = None) -> str:
        return f"{count}"

    definition = get_registered_tools()["my_tool"]["definition"]
    params = definition["function"]["parameters"]
    assert params["properties"]["count"]["type"] == "integer"


def test_tool_handler_execution():
    @tool()
    def add(a: int, b: int = 0) -> int:
        return a + b

    handler = get_registered_tools()["add"]["fn"]
    assert handler(2, 3) == 5
    assert handler(5) == 5


def test_get_registered_tools_returns_copy():
    @tool()
    def my_tool(x: str) -> str:
        return x

    reg1 = get_registered_tools()
    reg2 = get_registered_tools()
    assert reg1 == reg2
    assert reg1 is not reg2


def test_clear_registered_tools_clears():
    @tool()
    def my_tool(x: str) -> str:
        return x

    assert "my_tool" in get_registered_tools()
    clear_registered_tools()
    assert "my_tool" not in get_registered_tools()


import unittest


class ToolDecoratorTests(unittest.TestCase):
    def setUp(self):
        clear_registered_tools()

    def tearDown(self):
        clear_registered_tools()

    def test_tool_decorator_registers_function(self):
        test_tool_decorator_registers_function()

    def test_tool_decorator_custom_name(self):
        test_tool_decorator_custom_name()

    def test_tool_decorator_custom_description(self):
        test_tool_decorator_custom_description()

    def test_tool_definition_uses_docstring(self):
        test_tool_definition_uses_docstring()

    def test_tool_definition_json_schema(self):
        test_tool_definition_json_schema()

    def test_tool_handler_execution(self):
        test_tool_handler_execution()

    def test_tool_definition_json_schema_pep604_optional(self):
        test_tool_definition_json_schema_pep604_optional()

    def test_get_registered_tools_returns_copy(self):
        test_get_registered_tools_returns_copy()

    def test_clear_registered_tools_clears(self):
        test_clear_registered_tools_clears()
