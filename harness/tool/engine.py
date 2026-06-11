from __future__ import annotations
import json
import re
from typing import Callable

from harness.tool.registry import ToolRegistry

_TEXT_TOOL_RE = re.compile(
    r'"action"\s*:\s*"([\w.]+)"',
    re.DOTALL,
)
_TEXT_TOOL_INPUT_RE = re.compile(
    r'"action_input"\s*:\s*("(?:\\.|[^"\\])*"|\{(?:\\.|[^{}])*\})',
    re.DOTALL,
)


def _parse_text_tool(content: str) -> dict | None:
    m = _TEXT_TOOL_RE.search(content)
    if not m:
        return None
    name = m.group(1)

    input_m = _TEXT_TOOL_INPUT_RE.search(content)
    raw_input = input_m.group(1).strip() if input_m else "{}"

    try:
        parsed = json.loads(raw_input)
    except (json.JSONDecodeError, TypeError):
        parsed = raw_input.strip("\"'")

    if isinstance(parsed, dict):
        args = parsed
    elif isinstance(parsed, str):
        try:
            import ast
            args = ast.literal_eval(parsed)
        except Exception:
            args = {"prompt": parsed}
    else:
        args = {"prompt": str(parsed)}
    return {"name": name, "arguments": args}


class ToolService:
    def __init__(
        self, registry: ToolRegistry | None = None, tools_cfg: dict | None = None
    ):
        _cfg = tools_cfg or {}
        self._max_turns = int(_cfg.get("max_turns", 10))
        self._registry = registry or ToolRegistry(
            builtins_cfg=_cfg.get("builtins", {}),
            mcp_bridges_cfg=_cfg.get("mcp_servers", {}),
        )
        allow_path_fns = []
        if self._registry.has_tool("read_file"):
            from harness.tool.builtins import filesystem

            allow_path_fns.append(filesystem.allow_path)
        if self._registry.has_tool("grep"):
            from harness.tool.builtins import search

            allow_path_fns.append(search.allow_path)
        if self._registry.has_tool("bash"):
            from harness.tool.builtins import shell

            allow_path_fns.append(shell.allow_path)

        for p in _cfg.get("path_whitelist", []):
            for allow_path_fn in allow_path_fns:
                allow_path_fn(p)

    @property
    def registry(self) -> ToolRegistry:
        return self._registry

    def run_loop(
        self,
        model_fn: Callable,
        messages: list[dict],
        tools: list[dict] | None = None,
        max_turns: int | None = None,
    ) -> dict:
        if not tools:
            return model_fn(messages=messages)

        current = list(messages)
        max_turns = max_turns if max_turns is not None else self._max_turns
        if max_turns <= 0:
            return model_fn(messages=current, tools=tools)

        for turn in range(max_turns):
            resp = model_fn(messages=current, tools=tools)
            choice = resp.get("choices", [{}])[0]
            msg = choice.get("message", {})

            if not msg.get("tool_calls"):
                text_tool = _parse_text_tool(msg.get("content", ""))
                if text_tool and turn < max_turns - 1:
                    msg["tool_calls"] = [
                        {
                            "id": f"tool_call_{turn}_0",
                            "type": "function",
                            "function": {
                                "name": text_tool["name"],
                                "arguments": json.dumps(text_tool["arguments"]),
                            },
                        }
                    ]
                else:
                    return resp

            normalized_tool_calls = []
            for idx, tc in enumerate(msg["tool_calls"]):
                normalized_tc = dict(tc)
                normalized_tc["id"] = normalized_tc.get("id") or f"tool_call_{turn}_{idx}"
                normalized_tool_calls.append(normalized_tc)

            current.append(
                {
                    "role": "assistant",
                    "content": msg.get("content"),
                    "tool_calls": normalized_tool_calls,
                }
            )
            for tc in normalized_tool_calls:
                result = self._execute_tool_call(tc)
                current.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": result,
                    }
                )

        # max_turns exhausted while model still requesting tool calls; make one
        # final call without tools so the model can produce a text completion
        # based on the accumulated tool results.
        return model_fn(messages=current)

    def _execute_tool_call(self, tool_call: dict) -> str:
        try:
            fn_info = tool_call.get("function", {})
            name = fn_info.get("name", "")
            raw_args = fn_info.get("arguments", "{}")
            if isinstance(raw_args, str):
                args = json.loads(raw_args)
            else:
                args = raw_args
        except (json.JSONDecodeError, KeyError) as e:
            return f"Error: invalid tool call payload: {e}"
        if not isinstance(args, dict):
            return "Error: invalid tool call payload: arguments must be an object"

        handler = self._registry.get_handler(name)
        if handler is None:
            return f"Error: unknown tool '{name}'"

        try:
            result = handler(**args)
            if result is None:
                return "ok"
            return str(result)
        except Exception as e:
            return f"Error calling {name}: {e}"
