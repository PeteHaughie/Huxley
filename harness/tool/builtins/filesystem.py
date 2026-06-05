from __future__ import annotations
from pathlib import Path

from harness.config import HUXLEY_HOME
from harness.tool.decorator import tool

_PROJECT_ROOTS: list[Path] = []
_INIT_PROJECT_ROOTS_DONE = False


def _init_project_roots():
    global _INIT_PROJECT_ROOTS_DONE
    if _INIT_PROJECT_ROOTS_DONE:
        return
    _INIT_PROJECT_ROOTS_DONE = True
    cwd = Path.cwd().resolve()
    _PROJECT_ROOTS.append(cwd)
    _PROJECT_ROOTS.append(HUXLEY_HOME.resolve())


def allow_path(path: str):
    p = Path(path).resolve()
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


@tool(description="Read the contents of a file at the given path")
def read_file(path: str, offset: int = 0, limit: int = 0) -> str:
    resolved = Path(path).expanduser().resolve()
    if not _is_path_allowed(resolved):
        return (
            f"Error: path not allowed (must be under project root or ~/.huxley): {path}"
        )
    if not resolved.exists():
        return f"Error: file not found: {path}"
    if not resolved.is_file():
        return f"Error: not a file: {path}"
    try:
        content = resolved.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return f"Error reading file: {e}"

    lines = content.splitlines(keepends=True)
    total = len(lines)

    if offset > 0:
        lines = lines[offset:]
    if limit > 0:
        lines = lines[:limit]

    result = "".join(lines)
    meta = f"[read {len(lines)}/{total} lines from {resolved}]"
    return f"{meta}\n{result}"


@tool(
    description="Write content to a file. Creates parent directories if needed. Overwrites existing content."
)
def write_file(path: str, content: str) -> str:
    resolved = Path(path).expanduser().resolve()
    if not _is_path_allowed(resolved):
        return (
            f"Error: path not allowed (must be under project root or ~/.huxley): {path}"
        )
    try:
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(content, encoding="utf-8")
        return f"Wrote {len(content)} bytes to {resolved}"
    except Exception as e:
        return f"Error writing file: {e}"


@tool(
    description="Replace the first occurrence of old_string with new_string in a file. Use for targeted edits."
)
def edit_file(path: str, old_string: str, new_string: str) -> str:
    resolved = Path(path).expanduser().resolve()
    if not _is_path_allowed(resolved):
        return (
            f"Error: path not allowed (must be under project root or ~/.huxley): {path}"
        )
    if not resolved.exists():
        return f"Error: file not found: {path}"
    try:
        content = resolved.read_text(encoding="utf-8")
    except Exception as e:
        return f"Error reading file: {e}"

    if old_string not in content:
        return f"Error: old_string not found in {resolved}"

    new_content = content.replace(old_string, new_string, 1)
    try:
        resolved.write_text(new_content, encoding="utf-8")
        return f"Edited {resolved} ({len(old_string)} chars replaced)"
    except Exception as e:
        return f"Error writing file: {e}"


@tool(description="Delete a file or empty directory")
def delete_file(path: str) -> str:
    resolved = Path(path).expanduser().resolve()
    if not _is_path_allowed(resolved):
        return (
            f"Error: path not allowed (must be under project root or ~/.huxley): {path}"
        )
    if not resolved.exists():
        return f"Error: path not found: {path}"
    try:
        if resolved.is_dir():
            resolved.rmdir()
            return f"Removed empty directory: {resolved}"
        resolved.unlink()
        return f"Deleted file: {resolved}"
    except Exception as e:
        return f"Error deleting {path}: {e}"


@tool(description="List files matching a glob pattern. Use ** for recursive matching.")
def glob_files(pattern: str, path: str = "") -> str:
    base = Path(path).expanduser().resolve() if path else Path.cwd().resolve()
    if not _is_path_allowed(base):
        return f"Error: path not allowed: {path}"
    if not base.is_dir():
        return f"Error: not a directory: {path or '.'}"
    try:
        matches = sorted(base.glob(pattern))
        if not matches:
            return f"No files matching {pattern} in {base}"
        result = "\n".join(str(m.relative_to(base)) for m in matches)
        return f"[{len(matches)} matches in {base}]\n{result}"
    except Exception as e:
        return f"Error globbing: {e}"


@tool(description="Create a directory. Creates parent directories if needed.")
def create_directory(path: str) -> str:
    resolved = Path(path).expanduser().resolve()
    if not _is_path_allowed(resolved):
        return f"Error: path not allowed: {path}"
    try:
        resolved.mkdir(parents=True, exist_ok=True)
        return f"Created directory: {resolved}"
    except Exception as e:
        return f"Error creating directory: {e}"


@tool(description="List entries in a directory")
def list_directory(path: str = "") -> str:
    base = Path(path).expanduser().resolve() if path else Path.cwd().resolve()
    if not _is_path_allowed(base):
        return f"Error: path not allowed: {path}"
    if not base.is_dir():
        return f"Error: not a directory: {path or '.'}"
    try:
        entries = sorted(base.iterdir())
        if not entries:
            return f"(empty directory: {base})"
        lines = []
        for e in entries:
            suffix = "/" if e.is_dir() else ""
            lines.append(f"{e.name}{suffix}")
        return f"[{len(entries)} entries in {base}]\n" + "\n".join(lines)
    except Exception as e:
        return f"Error listing directory: {e}"
