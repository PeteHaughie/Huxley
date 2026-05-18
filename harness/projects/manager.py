import json
import re
import shutil
from pathlib import Path, PurePosixPath
from datetime import datetime, timezone
from typing import Optional

from harness.config import HUXLEY_PROJECTS_DIR
from harness.board import JobBoard, Task


PROJECT_SUMMARY_NAME = "summary.md"
PROJECT_EPIC_NAME = "epic.json"
PROJECT_TASKS_DIRNAME = "tasks"
PROJECT_SUGGESTIONS_DIRNAME = "suggestions"
PROJECT_MATERIALIZED_ROOT = "materialized-projects"
PROJECT_MANIFEST_NAME = "materialized.json"


def _slug(text: str, max_len: int = 48) -> str:
    s = text.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = s.strip("-")
    return s[:max_len].rstrip("-")


def archive_epic(epic: Task, board: JobBoard) -> Path:
    HUXLEY_PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    slug = _slug(epic.title)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    proj_dir = HUXLEY_PROJECTS_DIR / f"{ts}-{slug}"
    proj_dir.mkdir(parents=True, exist_ok=True)

    _write_json(proj_dir / "epic.json", epic)
    if epic.result:
        (proj_dir / "summary.md").write_text(epic.result)

    tasks_dir = proj_dir / "tasks"
    task_children = board.children_of(epic.id)
    for task in task_children:
        tslug = _slug(task.title)
        tdir = tasks_dir / f"{task.id[:8]}-{tslug}"
        tdir.mkdir(parents=True, exist_ok=True)
        _write_json(tdir / "task.json", task)
        if task.result:
            (tdir / "result.md").write_text(task.result)

        unit_children = board.children_of(task.id)
        if unit_children:
            units_dir = tdir / "units"
            for unit in unit_children:
                uslug = _slug(unit.title)
                udir = units_dir / f"{unit.id[:8]}-{uslug}"
                udir.mkdir(parents=True, exist_ok=True)
                _write_json(udir / "unit.json", unit)
                if unit.result:
                    (udir / "result.md").write_text(unit.result)

    return proj_dir


def write_compiled_suggestions(proj_dir: Path, result: str) -> list[dict]:
    suggestions = _parse_compiled_suggestions(result)
    if not suggestions:
        return []
    suggestions_root = proj_dir / PROJECT_SUGGESTIONS_DIRNAME
    if suggestions_root.exists():
        shutil.rmtree(suggestions_root)
    suggestions_root.mkdir(parents=True, exist_ok=True)
    manifest = []
    for index, suggestion in enumerate(suggestions, start=1):
        folder = f"{index:02d}-{_slug(suggestion['name'] or f'suggestion-{index}') or f'suggestion-{index}'}"
        suggestion_dir = suggestions_root / folder
        suggestion_dir.mkdir(parents=True, exist_ok=True)
        written = 0
        for rel_path, content in suggestion["files"]:
            fpath = suggestion_dir / rel_path
            fpath.parent.mkdir(parents=True, exist_ok=True)
            fpath.write_text(_clean_generated_content(content))
            written += 1
        manifest.append({
            "name": suggestion["name"],
            "folder": folder,
            "path": str(suggestion_dir),
            "file_count": written,
        })
    return manifest


def list_projects() -> list[dict]:
    HUXLEY_PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    projects = []
    for d in sorted(HUXLEY_PROJECTS_DIR.iterdir(), reverse=True):
        if not d.is_dir():
            continue
        epath = d / "epic.json"
        if not epath.exists():
            continue
        try:
            with open(epath) as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue
        summary = ""
        spath = d / "summary.md"
        if spath.exists():
            try:
                summary = spath.read_text()[:200]
            except OSError:
                pass
        tasks = list(d.glob("tasks/*/task.json"))
        suggestions = _collect_suggestion_views(d)
        projects.append({
            "dir": d.name,
            "path": str(d),
            "title": data.get("title", "?"),
            "created": data.get("created", "?"),
            "result_len": len(data.get("result", "") or ""),
            "task_count": len(tasks),
            "suggestion_count": len(suggestions),
        })
    return projects


def get_project(name: str) -> Optional[dict]:
    HUXLEY_PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    d = resolve_project_dir(name)
    if d is None:
        return None
    epath = d / PROJECT_EPIC_NAME
    try:
        with open(epath) as f:
            epic = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None
    summary = ""
    spath = d / PROJECT_SUMMARY_NAME
    if spath.exists():
        try:
            summary = spath.read_text()
        except OSError:
            pass
    tasks = []
    for tdir in sorted((d / PROJECT_TASKS_DIRNAME).glob("*")) if (d / PROJECT_TASKS_DIRNAME).exists() else []:
        tpath = tdir / "task.json"
        if not tpath.exists():
            continue
        try:
            with open(tpath) as f:
                tdata = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue
        tres = ""
        rpath = tdir / "result.md"
        if rpath.exists():
            try:
                tres = rpath.read_text()[:500]
            except OSError:
                pass
        units = []
        for udir in sorted(tdir.glob("units/*")) if (tdir / "units").exists() else []:
            upath = udir / "unit.json"
            if not upath.exists():
                continue
            try:
                with open(upath) as f:
                    udata = json.load(f)
            except (json.JSONDecodeError, OSError):
                continue
            ures = ""
            urp = udir / "result.md"
            if urp.exists():
                try:
                    ures = urp.read_text()[:300]
                except OSError:
                    pass
            units.append({
                "id": udata.get("id", "?")[:8],
                "title": udata.get("title", "?")[:60],
                "result_preview": ures,
            })
        tasks.append({
            "id": tdata.get("id", "?")[:8],
            "title": tdata.get("title", "?")[:80],
            "result_preview": tres,
            "unit_count": len(units),
            "units": units,
        })
    return {
        "dir": d.name,
        "path": str(d),
        "title": epic.get("title", "?"),
        "prompt": epic.get("prompt", ""),
        "summary": summary,
        "result_len": len(epic.get("result", "") or ""),
        "tasks": tasks,
        "suggestions": _collect_suggestion_views(d),
    }


def resolve_project_dir(name: str) -> Optional[Path]:
    HUXLEY_PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    for d in HUXLEY_PROJECTS_DIR.iterdir():
        if not d.is_dir() or name not in d.name:
            continue
        if (d / PROJECT_EPIC_NAME).exists():
            return d
    return None


def materialize_project(name: str, destination: str | Path | None = None, overwrite: bool = False) -> Optional[dict]:
    proj_dir = resolve_project_dir(name)
    if proj_dir is None:
        return None
    suggestions = _collect_suggestion_specs(proj_dir)
    if not suggestions:
        raise ValueError(f"project {proj_dir.name} has no generated suggestions")
    root = (
        Path(destination).expanduser().resolve()
        if destination is not None
        else (Path.cwd() / PROJECT_MATERIALIZED_ROOT / proj_dir.name).resolve()
    )
    root.mkdir(parents=True, exist_ok=True)
    materialized = []
    for suggestion in suggestions:
        target_dir = root / suggestion["folder"]
        if target_dir.exists():
            if not overwrite:
                raise FileExistsError(f"{target_dir} already exists (use --force to replace it)")
            shutil.rmtree(target_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        copied = _copy_suggestion(suggestion, target_dir)
        materialized.append({
            "name": suggestion["name"],
            "folder": suggestion["folder"],
            "path": str(target_dir),
            "file_count": copied,
        })
    manifest = {
        "project": proj_dir.name,
        "source": str(proj_dir),
        "materialized_at": datetime.now(timezone.utc).isoformat(),
        "suggestions": materialized,
    }
    (root / PROJECT_MANIFEST_NAME).write_text(json.dumps(manifest, indent=2))
    return {
        "project": proj_dir.name,
        "source": str(proj_dir),
        "root": str(root),
        "suggestions": materialized,
    }


def _write_json(path: Path, task: Task):
    path.write_text(json.dumps(task.to_dict(), indent=2, ensure_ascii=False))


def _clean_generated_content(content: str) -> str:
    clean = content.strip()
    clean = re.sub(r"^```\w*\n", "", clean)
    clean = re.sub(r"\n```\s*$", "", clean)
    return clean


def _parse_compiled_suggestions(result: str) -> list[dict]:
    option_header = re.compile(r"^---\s*(?:OPTION|SUGGESTION|VARIANT):\s*(.+?)\s*$")
    file_header = re.compile(r"^---\s*FILE:\s*(.+?)\s*$")
    end_header = re.compile(r"^---\s*(?:END(?:\s+(?:OPTION|SUGGESTION|VARIANT))?)?\s*$")
    suggestions: list[dict] = []
    current_option: Optional[dict] = None
    current_file: Optional[str] = None
    file_lines: list[str] = []

    def ensure_option(name: Optional[str] = None):
        nonlocal current_option
        if current_option is None:
            current_option = {"name": (name or "primary").strip() or "primary", "files": []}

    def flush_file():
        nonlocal current_file, file_lines
        if current_file is None:
            return
        ensure_option()
        rel_path = _safe_relative_path(current_file)
        content = "\n".join(file_lines).strip()
        if rel_path is not None and content:
            current_option["files"].append((rel_path, content))
        current_file = None
        file_lines = []

    def flush_option():
        nonlocal current_option
        if current_option and current_option["files"]:
            suggestions.append(current_option)
        current_option = None

    for line in result.splitlines():
        option_match = option_header.match(line)
        file_match = file_header.match(line)
        if option_match:
            flush_file()
            flush_option()
            ensure_option(option_match.group(1))
            continue
        if file_match:
            flush_file()
            ensure_option()
            current_file = file_match.group(1)
            continue
        if end_header.match(line):
            flush_file()
            continue
        if current_file is not None:
            file_lines.append(line)
    flush_file()
    flush_option()
    return suggestions


def _safe_relative_path(raw_path: str) -> Optional[Path]:
    cleaned = raw_path.strip()
    if not cleaned:
        return None
    pure = PurePosixPath(cleaned)
    if pure.is_absolute() or ".." in pure.parts:
        return None
    if pure.parts and pure.parts[0] == ".":
        pure = PurePosixPath(*pure.parts[1:])
    if not pure.parts:
        return None
    return Path(*pure.parts)


def _collect_suggestion_views(proj_dir: Path) -> list[dict]:
    suggestions = []
    for spec in _collect_suggestion_specs(proj_dir):
        suggestions.append({
            "name": spec["name"],
            "folder": spec["folder"],
            "path": str(spec["source"]),
            "file_count": spec["file_count"],
        })
    return suggestions


def _collect_suggestion_specs(proj_dir: Path) -> list[dict]:
    suggestions_root = proj_dir / PROJECT_SUGGESTIONS_DIRNAME
    specs = []
    if suggestions_root.exists():
        for suggestion_dir in sorted(p for p in suggestions_root.iterdir() if p.is_dir()):
            file_count = sum(1 for p in suggestion_dir.rglob("*") if p.is_file())
            folder = suggestion_dir.name
            name = folder.split("-", 1)[1].replace("-", " ") if "-" in folder else folder
            specs.append({
                "name": name,
                "folder": folder,
                "source": suggestion_dir,
                "file_count": file_count,
                "legacy_entries": None,
            })
    legacy_entries = _legacy_generated_entries(proj_dir)
    if not specs and legacy_entries:
        specs.append({
            "name": "primary",
            "folder": "01-primary",
            "source": proj_dir,
            "file_count": sum(1 for entry in legacy_entries for p in ([entry] if entry.is_file() else entry.rglob("*")) if p.is_file()),
            "legacy_entries": legacy_entries,
        })
    return specs


def _legacy_generated_entries(proj_dir: Path) -> list[Path]:
    ignored = {
        PROJECT_EPIC_NAME,
        PROJECT_SUMMARY_NAME,
        PROJECT_TASKS_DIRNAME,
        PROJECT_SUGGESTIONS_DIRNAME,
        PROJECT_MANIFEST_NAME,
    }
    return [entry for entry in sorted(proj_dir.iterdir()) if entry.name not in ignored]


def _copy_suggestion(spec: dict, target_dir: Path) -> int:
    copied = 0
    legacy_entries = spec.get("legacy_entries")
    if legacy_entries is not None:
        for entry in legacy_entries:
            if entry.is_dir():
                for src in entry.rglob("*"):
                    if not src.is_file():
                        continue
                    rel = src.relative_to(spec["source"])
                    dest = target_dir / rel
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dest)
                    copied += 1
            else:
                dest = target_dir / entry.name
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(entry, dest)
                copied += 1
        return copied
    for src in spec["source"].rglob("*"):
        if not src.is_file():
            continue
        rel = src.relative_to(spec["source"])
        dest = target_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        copied += 1
    return copied
