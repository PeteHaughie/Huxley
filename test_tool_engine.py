import json
import unittest
from pathlib import Path
from harness.tool.engine import ToolService
from harness.tool.registry import ToolRegistry
from harness.tool.decorator import tool, clear_registered_tools


def setup_function():
    clear_registered_tools()


def teardown_function():
    clear_registered_tools()


def _make_model_response(content=None, tool_calls=None, finish="stop"):
    msg = {}
    if content is not None:
        msg["content"] = content
    if tool_calls:
        msg["tool_calls"] = tool_calls
    return {
        "choices": [{"index": 0, "message": msg, "finish_reason": finish}],
    }


def _identity_model_fn(messages, **kw):
    content = messages[-1]["content"] if messages else ""
    return _make_model_response(content=content)


def test_no_tools_passthrough():
    svc = ToolService()
    msgs = [{"role": "user", "content": "hello"}]
    resp = svc.run_loop(_identity_model_fn, msgs, tools=None)
    assert resp["choices"][0]["message"]["content"] == "hello"


def test_no_tool_calls_in_response():
    @tool()
    def ping(x: str) -> str:
        return f"pong: {x}"

    svc = ToolService()
    definitions = svc.registry.definitions()
    assert len(definitions) > 0

    msgs = [{"role": "user", "content": "just say hi"}]
    resp = svc.run_loop(_identity_model_fn, msgs, tools=definitions)
    assert resp["choices"][0]["message"]["content"] == "just say hi"


def test_execute_single_tool_call():
    results = []
    turn = [0]

    @tool()
    def greet(name: str) -> str:
        results.append(name)
        return f"Hello, {name}!"

    def model_fn(messages, **kw):
        turn[0] += 1
        has_tool_result = any(m.get("role") == "tool" for m in messages)
        if has_tool_result:
            return _make_model_response(content="Done greeting")
        tc = {
            "id": "call_1",
            "type": "function",
            "function": {"name": "greet", "arguments": json.dumps({"name": "Alice"})},
        }
        return _make_model_response(tool_calls=[tc])

    svc = ToolService()
    msgs = [{"role": "user", "content": "greet Alice"}]
    resp = svc.run_loop(model_fn, msgs, tools=svc.registry.definitions())
    assert results == ["Alice"], f"expected ['Alice'], got {results}"
    assert turn[0] == 2
    assert resp["choices"][0]["message"]["content"] == "Done greeting"


def test_execute_multiple_tool_calls_in_one_turn():
    results = []
    model_inputs = []

    @tool()
    def add(a: int, b: int) -> int:
        results.append(("add", a, b))
        return str(a + b)

    def model_fn(messages, **kw):
        model_inputs.append(messages)
        if any(m.get("role") == "tool" for m in messages):
            return _make_model_response(content="all done")
        tc1 = {
            "id": "call_1",
            "type": "function",
            "function": {"name": "add", "arguments": json.dumps({"a": 1, "b": 2})},
        }
        tc2 = {
            "id": "call_2",
            "type": "function",
            "function": {"name": "add", "arguments": json.dumps({"a": 3, "b": 4})},
        }
        return _make_model_response(tool_calls=[tc1, tc2])

    svc = ToolService()
    msgs = [{"role": "user", "content": "add some numbers"}]
    resp = svc.run_loop(model_fn, msgs, tools=svc.registry.definitions())
    assert results == [("add", 1, 2), ("add", 3, 4)]
    assert resp["choices"][0]["message"]["content"] == "all done"
    second_turn = model_inputs[1]
    assistant_tool_msgs = [
        m for m in second_turn if m.get("role") == "assistant" and m.get("tool_calls")
    ]
    assert len(assistant_tool_msgs) == 1
    assert len(assistant_tool_msgs[0]["tool_calls"]) == 2


def test_execute_tool_call_without_id_uses_fallback_id():
    model_inputs = []

    @tool()
    def echo(text: str) -> str:
        return text

    def model_fn(messages, **kw):
        model_inputs.append(messages)
        if any(m.get("role") == "tool" for m in messages):
            return _make_model_response(content="done")
        tc = {
            "type": "function",
            "function": {"name": "echo", "arguments": json.dumps({"text": "hi"})},
        }
        return _make_model_response(tool_calls=[tc])

    svc = ToolService()
    msgs = [{"role": "user", "content": "say hi"}]
    resp = svc.run_loop(model_fn, msgs, tools=svc.registry.definitions())
    assert resp["choices"][0]["message"]["content"] == "done"
    second_turn = model_inputs[1]
    tool_msgs = [m for m in second_turn if m.get("role") == "tool"]
    assert len(tool_msgs) == 1
    assert tool_msgs[0]["tool_call_id"] == "tool_call_0_0"


def test_max_turns_exhausted():
    turn_count = [0]

    def model_fn(messages, **kw):
        turn_count[0] += 1
        tc = {
            "id": f"call_{turn_count[0]}",
            "type": "function",
            "function": {"name": "nonexistent_tool", "arguments": "{}"},
        }
        return _make_model_response(tool_calls=[tc])

    svc = ToolService()
    msgs = [{"role": "user", "content": "loop"}]
    resp = svc.run_loop(model_fn, msgs, tools=[{"type": "function"}], max_turns=3)
    assert turn_count[0] == 3


def test_unknown_tool_returns_error():
    def model_fn(messages, **kw):
        tc = {
            "id": "call_1",
            "type": "function",
            "function": {"name": "does_not_exist", "arguments": "{}"},
        }
        return _make_model_response(tool_calls=[tc])

    svc = ToolService()
    msgs = [{"role": "user", "content": "run tool"}]
    resp = svc.run_loop(model_fn, msgs, tools=[{"type": "function"}], max_turns=1)
    assert "Error: unknown tool" in svc._execute_tool_call(
        {"function": {"name": "does_not_exist", "arguments": "{}"}}
    )


def test_tool_error_returns_error_message():
    @tool()
    def failing_tool() -> str:
        raise ValueError("something broke")

    err = ToolService()._execute_tool_call(
        {
            "id": "call_1",
            "function": {"name": "failing_tool", "arguments": "{}"},
        }
    )
    assert "Error calling failing_tool" in err
    assert "something broke" in err


def test_tool_invalid_json_arguments():
    service = ToolService()
    err = service._execute_tool_call(
        {
            "id": "call_1",
            "function": {"name": "test", "arguments": "not valid json"},
        }
    )
    assert "Error: invalid tool call payload" in err


def test_tool_rejects_non_object_arguments():
    service = ToolService()
    for raw_args in ("null", "[]", ["x"], None):
        err = service._execute_tool_call(
            {
                "id": "call_1",
                "function": {"name": "test", "arguments": raw_args},
            }
        )
        assert "Error: invalid tool call payload" in err


def test_tool_service_with_tools_kwarg():
    @tool()
    def hello(name: str) -> str:
        return f"hi {name}"

    def model_fn(messages, **kw):
        if "tools" in kw:
            return _make_model_response(content=f"got {len(kw['tools'])} tools")
        return _make_model_response(content="no tools")

    svc = ToolService()
    tool_count = len(svc.registry.definitions())
    msgs = [{"role": "user", "content": "test tools kwarg"}]
    resp = svc.run_loop(model_fn, msgs, tools=svc.registry.definitions())
    assert f"got {tool_count} tools" in resp["choices"][0]["message"]["content"]


def test_path_whitelist_does_not_enable_disabled_shell_tool(tmp_path: Path):
    registry = ToolRegistry(builtins_cfg={"shell": False})
    assert registry.has_tool("bash") is False
    svc = ToolService(registry=registry, tools_cfg={"path_whitelist": [str(tmp_path)]})
    assert svc.registry.has_tool("bash") is False


class ToolEngineTests(unittest.TestCase):
    def setUp(self):
        clear_registered_tools()

    def tearDown(self):
        clear_registered_tools()

    def test_no_tools_passthrough(self):
        test_no_tools_passthrough()

    def test_no_tool_calls_in_response(self):
        test_no_tool_calls_in_response()

    def test_execute_single_tool_call(self):
        test_execute_single_tool_call()

    def test_execute_multiple_tool_calls_in_one_turn(self):
        test_execute_multiple_tool_calls_in_one_turn()

    def test_execute_tool_call_without_id_uses_fallback_id(self):
        test_execute_tool_call_without_id_uses_fallback_id()

    def test_max_turns_exhausted(self):
        test_max_turns_exhausted()

    def test_unknown_tool_returns_error(self):
        test_unknown_tool_returns_error()

    def test_tool_error_returns_error_message(self):
        test_tool_error_returns_error_message()

    def test_tool_invalid_json_arguments(self):
        test_tool_invalid_json_arguments()

    def test_tool_rejects_non_object_arguments(self):
        test_tool_rejects_non_object_arguments()

    def test_tool_service_with_tools_kwarg(self):
        test_tool_service_with_tools_kwarg()

    def test_path_whitelist_does_not_enable_disabled_shell_tool(self):
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            test_path_whitelist_does_not_enable_disabled_shell_tool(Path(d))
