from __future__ import annotations
import importlib
import importlib.util
import sys
from pathlib import Path
from typing import Callable

from harness.skill.loader import _skill_dirs
from harness.tool.decorator import _TOOL_REGISTRY, clear_registered_tools


class ToolRegistry:
    def __init__(self, builtins_cfg: dict | None = None):
        self._skills_scanned = False
        self._load_builtins(builtins_cfg or {})

    def _load_builtins(self, builtins_cfg: dict):
        _BUILTIN_MODULES = [
            ("filesystem", "harness.tool.builtins.filesystem"),
            ("search", "harness.tool.builtins.search"),
            ("shell", "harness.tool.builtins.shell"),
        ]
        _SHELL_DEFAULT = False

        enabled_mods = []
        disabled_mods = []
        for cfg_key, mod_name in _BUILTIN_MODULES:
            default = cfg_key != "shell"
            if builtins_cfg.get(cfg_key, default):
                enabled_mods.append(mod_name)
            else:
                disabled_mods.append(mod_name)

        for mod_name in enabled_mods:
            if mod_name in sys.modules:
                importlib.reload(sys.modules[mod_name])
            else:
                importlib.import_module(mod_name)

        # Remove tools registered by disabled modules so that ToolRegistry
        # instances created with a builtin disabled don't expose its tools
        # even if the module was already imported by a prior instance.
        for mod_name in disabled_mods:
            tools_to_remove = [
                name
                for name, entry in list(_TOOL_REGISTRY.items())
                if getattr(entry.get("fn"), "__module__", None) == mod_name
            ]
            for name in tools_to_remove:
                del _TOOL_REGISTRY[name]

    def scan_skills(self):
        if self._skills_scanned:
            return
        for skills_dir in _skill_dirs():
            for entry in sorted(skills_dir.iterdir()):
                if not entry.is_dir():
                    continue
                tools_dir = entry / "tools"
                if not tools_dir.is_dir():
                    continue
                self._load_tools_from(tools_dir)
        self._skills_scanned = True

    def _load_tools_from(self, tools_dir: Path):
        for py_file in sorted(tools_dir.glob("*.py")):
            if py_file.name.startswith("_"):
                continue
            mod_name = f"_skill_tools_{tools_dir.parent.name}_{py_file.stem}"
            if mod_name in sys.modules:
                continue
            try:
                spec = importlib.util.spec_from_file_location(mod_name, py_file)
                if spec is None or spec.loader is None:
                    continue
                mod = importlib.util.module_from_spec(spec)
                sys.modules[mod_name] = mod
                spec.loader.exec_module(mod)
            except Exception as e:
                print(f"\u03b3|tool|skill_load_err|{py_file.name}|{e}", flush=True)

    def definitions(self) -> list[dict]:
        return [entry["definition"] for entry in _TOOL_REGISTRY.values()]

    def get_handler(self, name: str) -> Callable | None:
        entry = _TOOL_REGISTRY.get(name)
        if entry is None:
            return None
        return entry["fn"]

    def has_tool(self, name: str) -> bool:
        return name in _TOOL_REGISTRY

    def list_tools(self) -> list[str]:
        return sorted(_TOOL_REGISTRY.keys())

    @staticmethod
    def reset():
        clear_registered_tools()
