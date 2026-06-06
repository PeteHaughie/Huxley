from __future__ import annotations
import hashlib
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
        self._enabled_builtin_modules: set[str] = set()
        self._builtin_modules: set[str] = set()
        self._load_builtins(builtins_cfg or {})

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
        return True

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
        root_key = hashlib.sha1(str(tools_dir.resolve()).encode("utf-8")).hexdigest()[:12]
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
                print(f"\u03b3|tool|skill_load_err|{py_file.name}|{e}", flush=True)

    def definitions(self) -> list[dict]:
        return [
            entry["definition"]
            for entry in _TOOL_REGISTRY.values()
            if self._is_tool_enabled(entry)
        ]

    def get_handler(self, name: str) -> Callable | None:
        entry = _TOOL_REGISTRY.get(name)
        if entry is None:
            return None
        if not self._is_tool_enabled(entry):
            return None
        return entry["fn"]

    def has_tool(self, name: str) -> bool:
        entry = _TOOL_REGISTRY.get(name)
        if entry is None:
            return False
        return self._is_tool_enabled(entry)

    def list_tools(self) -> list[str]:
        return sorted(
            name for name, entry in _TOOL_REGISTRY.items() if self._is_tool_enabled(entry)
        )

    @staticmethod
    def reset():
        clear_registered_tools()
