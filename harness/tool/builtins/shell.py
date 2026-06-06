from __future__ import annotations
import subprocess
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
    description="Run a shell command and return its output. Working directory is restricted to project root and ~/.huxley."
)
def bash(command: str, workdir: str = "", timeout: int = 30) -> str:
    cwd = Path(workdir).expanduser().resolve() if workdir else Path.cwd().resolve()
    if not _is_path_allowed(cwd):
        return f"Error: working directory not allowed: {workdir or '.'}"
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(cwd),
        )
        output = ""
        if result.stdout:
            output += result.stdout.strip()
        if result.stderr:
            if output:
                output += "\n"
            output += f"(stderr) {result.stderr.strip()}"
        if result.returncode != 0:
            return (
                f"exit code {result.returncode}\n{output}"
                if output
                else f"exit code {result.returncode}"
            )
        return output or "(no output)"
    except subprocess.TimeoutExpired:
        return f"Error: command timed out after {timeout}s"
    except FileNotFoundError as e:
        return f"Error: command not found: {e}"
    except Exception as e:
        return f"Error executing command: {e}"
