from __future__ import annotations
import hashlib
import importlib
import importlib.util
import sys
import threading
from pathlib import Path
from typing import Any, Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from harness.tool.mcp_bridge import McpBridge

from harness.skill.loader import _skill_dirs
from harness.tool.decorator import _TOOL_REGISTRY, clear_registered_tools


class ToolRegistry:
    def __init__(
        self,
        builtins_cfg: dict | None = None,
        mcp_bridges_cfg: dict | None = None,
    ):
        self._skills_scanned = False
        self._enabled_builtin_modules: set[str] = set()
        self._builtin_modules: set[str] = set()
        cfg = builtins_cfg or {}
        self._skills_scan_enabled: bool = bool(cfg.get("skills", False))
        self._load_builtins(cfg)

        self._mcp_bridges_cfg: dict = mcp_bridges_cfg or {}
        self._mcp_bridges: dict[str, McpBridge] = {}
        self._mcp_connected = False
        self._mcp_lock = threading.Lock()
        self._mcp_tool_index: dict[str, tuple[str, dict]] = {}

        self._skill_tool_map: dict[str, list[str]] = {}
        self._skills_lock = threading.Lock()

        from harness.tool.builtins.tools import set_registry
        set_registry(self)

    def _load_builtins(self, builtins_cfg: dict):
        _BUILTIN_MODULES = [
            ("filesystem", "harness.tool.builtins.filesystem"),
            ("search", "harness.tool.builtins.search"),
            ("shell", "harness.tool.builtins.shell"),
        ]
        _SHELL_DEFAULT = False
        self._builtin_modules = {mod_name for _, mod_name in _BUILTIN_MODULES}

        enabled_mods = []
        for cfg_key, mod_name in _BUILTIN_MODULES:
            default = _SHELL_DEFAULT if cfg_key == "shell" else True
            if builtins_cfg.get(cfg_key, default):
                enabled_mods.append(mod_name)
        self._enabled_builtin_modules = set(enabled_mods)

        for mod_name in enabled_mods:
            if mod_name in sys.modules:
                has_tools = any(
                    getattr(entry.get("fn"), "__module__", None) == mod_name
                    for entry in _TOOL_REGISTRY.values()
                )
                if not has_tools:
                    importlib.reload(sys.modules[mod_name])
            else:
                importlib.import_module(mod_name)

    def _is_tool_enabled(self, entry: dict) -> bool:
        module_name = getattr(entry.get("fn"), "__module__", None)
        if module_name in self._builtin_modules:
            return module_name in self._enabled_builtin_modules
        if isinstance(module_name, str) and module_name.startswith("_skill_tools_"):
            return self._skills_scan_enabled
        return True

    def _connect_mcp_servers(self):
        if self._mcp_connected:
            return
        with self._mcp_lock:
            if self._mcp_connected:
                return
            from harness.tool.mcp_bridge import McpBridge

            for server_name, server_cfg in self._mcp_bridges_cfg.items():
                if not isinstance(server_cfg, dict):
                    continue
                bridge = McpBridge(server_name, server_cfg)
                try:
                    defs = bridge.definitions()
                    for d in defs:
                        fn_name = d["function"]["name"]
                        self._mcp_tool_index[fn_name] = (server_name, d)
                    self._mcp_bridges[server_name] = bridge
                except Exception as e:
                    bridge.disconnect()
                    print(
                        f"\u03b3|tool|mcp_connect_err|{server_name}|{e}",
                        flush=True,
                    )
            self._mcp_connected = True

    def _get_mcp_handler(self, name: str) -> Callable | None:
        match = self._mcp_tool_index.get(name)
        if match is None:
            return None
        bridge_name, _ = match
        bridge = self._mcp_bridges.get(bridge_name)
        if bridge is None:
            return None

        def _handler(**kwargs: Any) -> str:
            return bridge.call_tool(name, kwargs)

        return _handler

    def scan_skills(self, skill_name: str | None = None):
        if not self._skills_scan_enabled:
            return
        if skill_name is None and self._skills_scanned:
            return
        with self._skills_lock:
            if skill_name is None and self._skills_scanned:
                return
            for skills_dir in _skill_dirs():
                for entry in sorted(skills_dir.iterdir()):
                    if not entry.is_dir():
                        continue
                    if skill_name and entry.name != skill_name:
                        continue
                    tools_dir = entry / "tools"
                    if not tools_dir.is_dir():
                        continue
                    self._load_tools_from(tools_dir, skill_name=entry.name)
            if skill_name is None:
                self._skills_scanned = True

    def _load_tools_from(self, tools_dir: Path, skill_name: str | None = None):
        root_key = hashlib.sha1(str(tools_dir.resolve()).encode("utf-8")).hexdigest()[:12]
        before = set(_TOOL_REGISTRY.keys())
        for py_file in sorted(tools_dir.glob("*.py")):
            if py_file.name.startswith("_"):
                continue
            mod_name = (
                f"_skill_tools_{root_key}_{tools_dir.parent.name}_{py_file.stem}"
            )
            if mod_name in sys.modules:
                has_tools = any(
                    getattr(entry.get("fn"), "__module__", None) == mod_name
                    for entry in _TOOL_REGISTRY.values()
                )
                if has_tools:
                    continue
                try:
                    importlib.reload(sys.modules[mod_name])
                except Exception as e:
                    print(f"\u03b3|tool|skill_load_err|{py_file.name}|{e}", flush=True)
                continue
            try:
                spec = importlib.util.spec_from_file_location(mod_name, py_file)
                if spec is None or spec.loader is None:
                    continue
                mod = importlib.util.module_from_spec(spec)
                sys.modules[mod_name] = mod
                spec.loader.exec_module(mod)
            except Exception as e:
                sys.modules.pop(mod_name, None)
                print(f"\u03b3|tool|skill_load_err|{py_file.name}|{e}", flush=True)
        if skill_name:
            after = set(_TOOL_REGISTRY.keys())
            self._skill_tool_map.setdefault(skill_name, [])
            for name in sorted(after - before):
                self._skill_tool_map[skill_name].append(name)

    def definitions(self, skill_name: str | None = None) -> list[dict]:
        self._connect_mcp_servers()
        builtin_defs = []
        for entry in _TOOL_REGISTRY.values():
            if not self._is_tool_enabled(entry):
                continue
            try:
                builtin_defs.append(entry["definition"])
            except Exception as e:
                fn_name = getattr(entry.get("fn"), "__name__", "?")
                print(f"\u03b3|tool|schema_warn|builtin|{fn_name}|{e}", flush=True)
        mcp_defs = [info[1] for info in self._mcp_tool_index.values()] if self._mcp_connected else []
        if skill_name:
            skill_tool_names = set(self._skill_tool_map.get(skill_name, []))
            all_skill_tool_names = {
                n for names in self._skill_tool_map.values() for n in names
            }
            return [
                d for d in builtin_defs + mcp_defs
                if d["function"]["name"] not in all_skill_tool_names
                or d["function"]["name"] in skill_tool_names
            ]
        return builtin_defs + mcp_defs

    def get_handler(self, name: str) -> Callable | None:
        entry = _TOOL_REGISTRY.get(name)
        if entry is not None and self._is_tool_enabled(entry):
            return entry["fn"]
        self._connect_mcp_servers()
        return self._get_mcp_handler(name)

    def has_tool(self, name: str) -> bool:
        entry = _TOOL_REGISTRY.get(name)
        if entry is not None:
            return self._is_tool_enabled(entry)
        self._connect_mcp_servers()
        return name in self._mcp_tool_index

    def list_tools(self) -> list[str]:
        builtin_names = sorted(
            name for name, entry in _TOOL_REGISTRY.items() if self._is_tool_enabled(entry)
        )
        self._connect_mcp_servers()
        mcp_names = sorted(self._mcp_tool_index.keys())
        return builtin_names + mcp_names

    def list_mcp_sources(self) -> list[dict]:
        self._connect_mcp_servers()
        sources = []
        for bridge_name, bridge in self._mcp_bridges.items():
            tools = [
                name for name, info in self._mcp_tool_index.items()
                if info[0] == bridge_name
            ]
            sources.append({
                "name": bridge_name,
                "connected": bridge.connected,
                "tools": sorted(tools),
            })
        return sources

    def disconnect_mcp_servers(self):
        with self._mcp_lock:
            for bridge in self._mcp_bridges.values():
                try:
                    bridge.disconnect()
                except Exception:
                    pass
            self._mcp_bridges.clear()
            self._mcp_tool_index.clear()
            self._mcp_connected = False

    @staticmethod
    def reset():
        clear_registered_tools()
