from __future__ import annotations
import inspect
import typing
from typing import Any, Callable, get_type_hints

_TOOL_REGISTRY: dict[str, dict] = {}


def _py_type_to_json(tp: type) -> str:
    if tp is str:
        return "string"
    if tp is int:
        return "integer"
    if tp is float:
        return "number"
    if tp is bool:
        return "boolean"
    origin = getattr(tp, "__origin__", None)
    if origin is list:
        return "array"
    if origin is dict:
        return "object"
    if origin is typing.Union:
        args = tp.__args__
        non_none = [a for a in args if a is not type(None)]
        if non_none:
            return _py_type_to_json(non_none[0])
    return "string"


def tool(name: str | None = None, description: str | None = None):
    def wrapper(fn: Callable) -> Callable:
        tool_name = name or fn.__name__
        hints = get_type_hints(fn)
        sig = inspect.signature(fn)

        properties: dict[str, dict] = {}
        required: list[str] = []

        for param_name, param in sig.parameters.items():
            if param_name == "return":
                continue
            param_type = hints.get(param_name, str)
            prop: dict[str, Any] = {"type": _py_type_to_json(param_type)}
            if param.default is not inspect.Parameter.empty:
                if param.default is not None:
                    prop["default"] = param.default
            else:
                required.append(param_name)
            if param.annotation is not inspect.Parameter.empty:
                origin = getattr(param_type, "__origin__", None)
                if origin is list:
                    args = getattr(param_type, "__args__", None)
                    if args:
                        prop["items"] = {"type": _py_type_to_json(args[0])}
                elif origin is typing.Union:
                    args = getattr(param_type, "__args__", None)
                    if args:
                        non_none = [a for a in args if a is not type(None)]
                        if non_none:
                            prop["type"] = _py_type_to_json(non_none[0])

            properties[param_name] = prop

        definition = {
            "type": "function",
            "function": {
                "name": tool_name,
                "description": description or fn.__doc__ or "",
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        }

        _TOOL_REGISTRY[tool_name] = {
            "fn": fn,
            "definition": definition,
        }

        return fn

    return wrapper


def get_registered_tools() -> dict[str, dict]:
    return dict(_TOOL_REGISTRY)


def clear_registered_tools():
    _TOOL_REGISTRY.clear()
