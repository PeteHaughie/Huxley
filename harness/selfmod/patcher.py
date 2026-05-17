from __future__ import annotations
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

PATCH_DIR = Path.home() / ".huxley" / "patches"


class Patcher:
    def __init__(self):
        PATCH_DIR.mkdir(parents=True, exist_ok=True)

    def apply(self, file_path: str, new_content: str, dry_run: bool = True) -> dict:
        target = Path(file_path).resolve()
        if not target.exists():
            return {"ok": False, "error": f"file not found: {file_path}"}

        original = target.read_text()
        if original == new_content:
            return {"ok": True, "changed": False}

        patch_id = _next_patch_id()
        if dry_run:
            return {
                "ok": True,
                "changed": True,
                "patch_id": patch_id,
                "diff": _make_diff(target, original, new_content),
            }

        import shutil
        backup = PATCH_DIR / f"{patch_id}_{target.name}.bak"
        shutil.copy2(target, backup)

        target.write_text(new_content)
        return {
            "ok": True,
            "changed": True,
            "patch_id": patch_id,
            "backup": str(backup),
            "diff": _make_diff(target, original, new_content),
        }

    def rollback(self, patch_id: str):
        for bak in PATCH_DIR.glob(f"{patch_id}_*.bak"):
            target_name = bak.name.split("_", 1)[1].replace(".bak", "")
            targets = list(PATCH_DIR.parent.glob(f"**/{target_name}"))
            for t in targets:
                shutil.copy2(bak, t)
                bak.unlink()
                return True
        return False


def _make_diff(file_path: Path, original: str, new_content: str) -> str:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(original)
        old_path = f.name
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(new_content)
        new_path = f.name
    result = subprocess.run(
        ["diff", "-u", old_path, new_path],
        capture_output=True, text=True,
    )
    os.unlink(old_path)
    os.unlink(new_path)
    return result.stdout


def _next_patch_id() -> str:
    import uuid
    return str(uuid.uuid4())[:12]
