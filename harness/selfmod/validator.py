from __future__ import annotations
import py_compile
import tempfile
import ast
from pathlib import Path


def validate_patch(file_path: str, new_content: str) -> dict[str, object]:
    """Run lightweight validators on the proposed patch content.

    Returns a dict with keys: ok(bool), errors(list), warnings(list).
    """
    errors: list[str] = []
    warnings: list[str] = []

    # Syntax check via ast.parse
    syntax_ok = True
    try:
        ast.parse(new_content, filename=file_path)
    except SyntaxError as e:
        errors.append(f"syntax: {e.msg} at line {e.lineno}")
        syntax_ok = False

    # py_compile for bytecode-level checks (skip if syntax already failed)
    if syntax_ok:
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                tmpfile = Path(tmpdir) / "tmp_patch.py"
                tmpfile.write_text(new_content, encoding="utf-8")
                py_compile.compile(str(tmpfile), doraise=True, dfile=file_path)
        except py_compile.PyCompileError as e:
            errors.append(f"compile: {e.msg}")
        except Exception as e:
            warnings.append(f"py_compile: {type(e).__name__}: {e}")

    ok = len(errors) == 0
    return {"ok": ok, "errors": errors, "warnings": warnings}
