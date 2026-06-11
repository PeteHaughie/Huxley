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
        mcp_tool_names: set[str] = set()
        for source in _REGISTRY.list_mcp_sources():
            mcp_tool_names.update(source["tools"])
        lines = []
        for name in _REGISTRY.list_tools():
            prefix = "mcp" if name in mcp_tool_names else "builtin"
            lines.append(f"{prefix}:{name}")
        return "\n".join(lines)
    from harness.tool.decorator import _TOOL_REGISTRY
    return "\n".join(f"builtin:{name}" for name in sorted(_TOOL_REGISTRY.keys()))


@tool(
    description="Get the description and JSON schema for a specific tool. Pass the exact tool name as shown by list_tools."
)
def tool_info(tool_name: str) -> str:
    global _REGISTRY
    normalized_name = tool_name
    if ":" in normalized_name:
        prefix, candidate = normalized_name.split(":", 1)
        if prefix in {"builtin", "mcp"} and candidate:
            normalized_name = candidate
    if _REGISTRY is not None:
        defs = _REGISTRY.definitions()
    else:
        from harness.tool.registry import ToolRegistry
        reg = ToolRegistry()
        defs = reg.definitions()
    for d in defs:
        if d["function"]["name"] == normalized_name:
            import json
            return json.dumps(d, indent=2)
    return f"Tool '{tool_name}' not found"
