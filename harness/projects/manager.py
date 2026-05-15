import json
import re
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

from harness.config import MONSTER_PROJECTS_DIR
from harness.board import JobBoard, Task


def _slug(text: str, max_len: int = 48) -> str:
    s = text.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = s.strip("-")
    return s[:max_len].rstrip("-")


def archive_epic(epic: Task, board: JobBoard) -> Path:
    MONSTER_PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    slug = _slug(epic.title)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    proj_dir = MONSTER_PROJECTS_DIR / f"{ts}-{slug}"
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


def list_projects() -> list[dict]:
    MONSTER_PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    projects = []
    for d in sorted(MONSTER_PROJECTS_DIR.iterdir(), reverse=True):
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
        projects.append({
            "dir": d.name,
            "path": str(d),
            "title": data.get("title", "?"),
            "created": data.get("created", "?"),
            "result_len": len(data.get("result", "") or ""),
            "task_count": len(tasks),
        })
    return projects


def get_project(name: str) -> Optional[dict]:
    MONSTER_PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    for d in MONSTER_PROJECTS_DIR.iterdir():
        if not d.is_dir() or name not in d.name:
            continue
        epath = d / "epic.json"
        if not epath.exists():
            continue
        try:
            with open(epath) as f:
                epic = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue
        summary = ""
        spath = d / "summary.md"
        if spath.exists():
            try:
                summary = spath.read_text()
            except OSError:
                pass
        tasks = []
        for tdir in sorted((d / "tasks").glob("*")) if (d / "tasks").exists() else []:
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
        }
    return None


def _write_json(path: Path, task: Task):
    path.write_text(json.dumps(task.to_dict(), indent=2, ensure_ascii=False))
