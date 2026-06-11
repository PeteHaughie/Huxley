from __future__ import annotations
from harness.tool.decorator import tool

_REGISTRY = None


def set_registry(registry):
    global _REGISTRY
    _REGISTRY = registry


@tool(
    description="List all available tools that can be used. Returns tool names one per line, each prefixed with its source (builtin or mcp)."
)
def list_tools() -> str:
    global _REGISTRY
    if _REGISTRY is not None:
        return "\n".join(_REGISTRY.list_tools())
    from harness.tool.decorator import _TOOL_REGISTRY
    return "\n".join(sorted(_TOOL_REGISTRY.keys()))


@tool(
    description="Get the description and JSON schema for a specific tool. Pass the exact tool name as shown by list_tools."
)
def tool_info(tool_name: str) -> str:
    from harness.tool.registry import ToolRegistry
    reg = ToolRegistry()
    defs = reg.definitions()
    for d in defs:
        if d["function"]["name"] == tool_name:
            import json
            return json.dumps(d, indent=2)
    return f"Tool '{tool_name}' not found"
