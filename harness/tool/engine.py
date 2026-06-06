from __future__ import annotations
import json
from typing import Callable

from harness.tool.registry import ToolRegistry


class ToolService:
    def __init__(
        self, registry: ToolRegistry | None = None, tools_cfg: dict | None = None
    ):
        _cfg = tools_cfg or {}
        self._max_turns = int(_cfg.get("max_turns", 10))
        self._registry = registry or ToolRegistry(builtins_cfg=_cfg.get("builtins", {}))
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

        for turn in range(max_turns):
            resp = model_fn(messages=current, tools=tools)
            choice = resp.get("choices", [{}])[0]
            msg = choice.get("message", {})

            if not msg.get("tool_calls"):
                return resp

            current.append(
                {
                    "role": "assistant",
                    "content": msg.get("content"),
                    "tool_calls": msg["tool_calls"],
                }
            )
            for idx, tc in enumerate(msg["tool_calls"]):
                result = self._execute_tool_call(tc)
                tool_call_id = tc.get("id") or f"tool_call_{turn}_{idx}"
                current.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call_id,
                        "content": result,
                    }
                )

        return resp

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
