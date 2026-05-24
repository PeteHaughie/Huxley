from __future__ import annotations
import difflib
import json
from pathlib import Path
import shutil

PATCH_DIR = Path.home() / ".huxley" / "patches"


class Patcher:
    def __init__(self):
        PATCH_DIR.mkdir(parents=True, exist_ok=True)

    def apply(self, file_path: str, new_content: str, dry_run: bool = True) -> dict:
        target = Path(file_path).expanduser().resolve()
        if not target.is_file():
            return {"ok": False, "error": f"file not found or not a regular file: {file_path}"}
        if not self._path_allowed(target):
            return {"ok": False, "error": f"target not allowed: {target}"}

        try:
            original = target.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError) as e:
            return {"ok": False, "error": f"read error: {e}"}
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

        try:
            backup = PATCH_DIR / f"{patch_id}_{target.name}.bak"
            shutil.copy2(target, backup)

            meta = PATCH_DIR / f"{patch_id}.meta"
            meta.write_text(json.dumps({"original_path": str(target)}), encoding="utf-8")

            target.write_text(new_content, encoding="utf-8")
        except OSError as e:
            bak = PATCH_DIR / f"{patch_id}_{target.name}.bak"
            if bak.exists():
                try:
                    shutil.copy2(bak, target)
                    bak.unlink()
                except OSError:
                    pass
            meta = PATCH_DIR / f"{patch_id}.meta"
            try:
                meta.unlink()
            except OSError:
                pass
            return {"ok": False, "error": f"write error: {e}"}
        return {
            "ok": True,
            "changed": True,
            "patch_id": patch_id,
            "backup": str(backup),
            "diff": _make_diff(target, original, new_content),
        }

    @staticmethod
    def _project_root() -> Path:
        return Path(__file__).resolve().parents[2]

    @staticmethod
    def _path_allowed(p: Path) -> bool:
        return any(
            p.is_relative_to(root.resolve())
            for root in (Patcher._project_root(), Path.home() / ".huxley")
        )

    def rollback(self, patch_id: str):
        if "/" in patch_id or "\\" in patch_id or ".." in patch_id or "\0" in patch_id or any(c in patch_id for c in "*?["):
            return False
        meta = PATCH_DIR / f"{patch_id}.meta"
        if meta.exists():
            try:
                data = json.loads(meta.read_text(encoding="utf-8"))
                orig = Path(data["original_path"]).expanduser().resolve()
                if not orig.is_file() or not self._path_allowed(orig):
                    return False
                bak = PATCH_DIR / f"{patch_id}_{orig.name}.bak"
                if bak.exists():
                    shutil.copy2(bak, orig)
                    bak.unlink()
                    meta.unlink()
                    return True
            except (KeyError, ValueError, OSError, UnicodeDecodeError):
                pass
            return False
        # Legacy fallback: no .meta file — search known roots by filename
        baks = list(PATCH_DIR.glob(f"{patch_id}_*.bak"))
        if baks:
            bak = baks[0]
            target_name = bak.name.split("_", 1)[1]
            if target_name.endswith(".bak"):
                target_name = target_name[:-4]
            matches = []
            for d in (self._project_root(), Path.home() / ".huxley"):
                matches.extend(d.rglob(target_name))
            if len(matches) == 1:
                target = matches[0].resolve()
                if not target.is_file() or not self._path_allowed(target):
                    return False
                shutil.copy2(bak, target)
                bak.unlink()
                return True
        return False


def _make_diff(file_path: Path, original: str, new_content: str) -> str:
    original_lines = original.splitlines(keepends=True)
    new_lines = new_content.splitlines(keepends=True)
    diff = difflib.unified_diff(
        original_lines,
        new_lines,
        fromfile=str(file_path),
        tofile=str(file_path),
    )
    return "".join(diff)


def _next_patch_id() -> str:
    import uuid
    return uuid.uuid4().hex[:12]
