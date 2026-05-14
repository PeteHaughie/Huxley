from __future__ import annotations
import ast
import inspect
import pkgutil
import harness
from pathlib import Path
from typing import Any


def module_map() -> dict[str, dict[str, Any]]:
    result = {}
    pkg_path = Path(harness.__file__).parent
    for importer, modname, ispkg in pkgutil.walk_packages(
        path=[str(pkg_path)],
        prefix="harness.",
    ):
        try:
            mod = importer.find_module(modname).load_module(modname)
            result[modname] = {
                "is_package": ispkg,
                "file": str(getattr(mod, "__file__", "")),
                "classes": [c for c in dir(mod) if isinstance(getattr(mod, c, None), type)],
                "functions": [
                    f for f in dir(mod)
                    if callable(getattr(mod, f, None)) and not f.startswith("_")
                ],
            }
        except Exception as e:
            result[modname] = {"error": str(e)}
    return result


def source_of(module_path: str) -> str | None:
    try:
        import importlib
        mod = importlib.import_module(module_path)
        return inspect.getsource(mod)
    except Exception:
        return None


def api_surface() -> list[dict]:
    apis = []
    for modname, info in module_map().items():
        src = source_of(modname)
        if src is None:
            continue
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                apis.append({
                    "module": modname,
                    "name": node.name,
                    "kind": "function",
                    "lineno": node.lineno,
                })
            elif isinstance(node, ast.ClassDef):
                apis.append({
                    "module": modname,
                    "name": node.name,
                    "kind": "class",
                    "lineno": node.lineno,
                })
    return apis
