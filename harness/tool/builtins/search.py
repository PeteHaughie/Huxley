from __future__ import annotations
import re
from pathlib import Path

from harness.config import HUXLEY_HOME
from harness.tool.decorator import tool

_PROJECT_ROOTS: list[Path] = []


def _init_project_roots():
    if _PROJECT_ROOTS:
        return
    _PROJECT_ROOTS.append(Path.cwd().resolve())
    _PROJECT_ROOTS.append(HUXLEY_HOME.resolve())


def allow_path(path: str):
    _init_project_roots()
    p = Path(path).expanduser().resolve()
    if p not in _PROJECT_ROOTS:
        _PROJECT_ROOTS.append(p)

def _is_path_allowed(path: Path) -> bool:
    _init_project_roots()
    resolved = path.resolve()
    for root in _PROJECT_ROOTS:
        try:
            resolved.relative_to(root)
            return True
        except ValueError:
            continue
    return False


@tool(
    description="Search file contents using a regular expression. Returns matching files and line numbers."
)
def grep(pattern: str, include: str = "", path: str = "") -> str:
    base = Path(path).expanduser().resolve() if path else Path.cwd().resolve()
    if not _is_path_allowed(base):
        return f"Error: path not allowed: {path or '.'}"
    if not base.is_dir():
        return f"Error: not a directory: {path or '.'}"
    try:
        import subprocess

        cmd = ["rg", "--no-heading", "--line-number", pattern, str(base)]
        if include:
            cmd.extend(["--glob", include])
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if result.returncode == 0:
            output = result.stdout.strip()
            if not output:
                return f"No matches for /{pattern}/ in {base}"
            lines = output.splitlines()
            return f"[{len(lines)} matches for /{pattern}/ in {base}]\n{output}"
        if result.returncode == 1:
            return f"No matches for /{pattern}/ in {base}"
        return f"grep error: {result.stderr.strip()}"
    except FileNotFoundError:
        pass
    except subprocess.TimeoutExpired:
        return f"grep timed out for pattern: {pattern}"

    try:
        compiled = re.compile(pattern)
    except re.error as exc:
        return f"Invalid regex pattern: {exc}"

    matches: list[str] = []
    for f in base.rglob("*"):
        if include and not glob_match(f.name, include):
            continue
        if not f.is_file():
            continue
        try:
            rel_parts = f.relative_to(base).parts
            if any(part.startswith(".") for part in rel_parts[:-1]):
                continue
            text = f.read_text(encoding="utf-8", errors="replace")
            for i, line in enumerate(text.splitlines(), 1):
                if compiled.search(line):
                    rel = f.relative_to(base)
                    matches.append(f"{rel}:{i}:{line.rstrip()}")
        except Exception:
            continue
    if not matches:
        return f"No matches for /{pattern}/ in {base}"
    return f"[{len(matches)} matches for /{pattern}/ in {base}]\n" + "\n".join(
        matches[:200]
    )


def glob_match(name: str, pattern: str) -> bool:
    parts = pattern.split(".")
    if len(parts) == 1:
        return name == pattern
    if len(parts) == 2:
        if parts[0] == "*":
            return name.endswith("." + parts[1])
        if parts[1] == "*":
            return name.startswith(parts[0] + ".")
    return name == pattern
