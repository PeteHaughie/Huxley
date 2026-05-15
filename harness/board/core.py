from __future__ import annotations
import uuid
import json
from pathlib import Path
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from harness.config import MONSTER_BOARD_DIR


class Level(str, Enum):
    EPIC = "epic"
    TASK = "task"
    UNIT = "unit"


class State(str, Enum):
    BACKLOG = "backlog"
    READY = "ready"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    DONE = "done"
    ARCHIVED = "archived"


_VALID_TRANSITIONS: dict[State, set[State]] = {
    State.BACKLOG: {State.READY, State.BLOCKED, State.ARCHIVED},
    State.READY: {State.IN_PROGRESS, State.BLOCKED, State.ARCHIVED},
    State.IN_PROGRESS: {State.DONE, State.BLOCKED, State.READY, State.BACKLOG},
    State.BLOCKED: {State.READY, State.ARCHIVED, State.IN_PROGRESS},
    State.DONE: {State.BACKLOG, State.READY, State.ARCHIVED},
    State.ARCHIVED: set(),
}

_STATE_COLORS = {
    State.BACKLOG: "dim",
    State.READY: "cyan",
    State.IN_PROGRESS: "yellow",
    State.BLOCKED: "red",
    State.DONE: "green",
    State.ARCHIVED: "dim",
}


class Task:
    def __init__(
        self,
        level: Level,
        title: str,
        prompt: str = "",
        parent_id: Optional[str] = None,
        caste: Optional[str] = None,
        tags: Optional[list[str]] = None,
        task_id: Optional[str] = None,
        state: State = State.BACKLOG,
        result: Optional[str] = None,
        created: Optional[str] = None,
        updated: Optional[str] = None,
    ):
        self.id = task_id or str(uuid.uuid4())
        self.parent_id = parent_id
        self.level = level
        self.state = state
        self.caste = caste
        self.title = title
        self.prompt = prompt
        self.result = result
        self.tags = tags or []
        now = datetime.now(timezone.utc).isoformat()
        self.created = created or now
        self.updated = updated or now

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "parent_id": self.parent_id,
            "level": self.level.value,
            "state": self.state.value,
            "caste": self.caste,
            "title": self.title,
            "prompt": self.prompt,
            "result": self.result,
            "tags": self.tags,
            "created": self.created,
            "updated": self.updated,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Task:
        return cls(
            task_id=d["id"],
            parent_id=d.get("parent_id"),
            level=Level(d["level"]),
            state=State(d["state"]),
            caste=d.get("caste"),
            title=d["title"],
            prompt=d.get("prompt", ""),
            result=d.get("result"),
            tags=d.get("tags", []),
            created=d.get("created"),
            updated=d.get("updated"),
        )

    def transition(self, new_state: State) -> bool:
        allowed = _VALID_TRANSITIONS.get(self.state, set())
        if new_state not in allowed:
            return False
        self.state = new_state
        self.updated = datetime.now(timezone.utc).isoformat()
        return True

    def __repr__(self):
        return f"<{self.level.value[0].upper()}|{self.state.value[0].upper()}|{self.id[:8]}|{self.title[:30]}>"


class JobBoard:
    def __init__(self):
        MONSTER_BOARD_DIR.mkdir(parents=True, exist_ok=True)

    # -- path helpers --

    @staticmethod
    def _task_path(task_id: str) -> Path:
        return MONSTER_BOARD_DIR / f"{task_id}.json"

    # -- CRUD --

    def create(self, task: Task) -> Task:
        path = self._task_path(task.id)
        if path.exists():
            raise ValueError(f"task {task.id[:8]} already exists")
        with open(path, "w") as f:
            json.dump(task.to_dict(), f, indent=2, ensure_ascii=False)
        return task

    def get(self, task_id: str) -> Optional[Task]:
        path = self._task_path(task_id)
        if path.exists():
            with open(path) as f:
                return Task.from_dict(json.load(f))
        for p in MONSTER_BOARD_DIR.glob("*.json"):
            if p.stem.startswith(task_id):
                with open(p) as f:
                    return Task.from_dict(json.load(f))
        return None

    def update(self, task: Task):
        path = self._task_path(task.id)
        with open(path, "w") as f:
            json.dump(task.to_dict(), f, indent=2, ensure_ascii=False)

    def delete(self, task_id: str) -> bool:
        path = self._task_path(task_id)
        if path.exists():
            path.unlink()
            return True
        for p in MONSTER_BOARD_DIR.glob("*.json"):
            if p.stem.startswith(task_id):
                p.unlink()
                return True
        return False

    # -- query --

    def list(self, level: Optional[Level] = None, state: Optional[State] = None) -> list[Task]:
        tasks = []
        for p in sorted(MONSTER_BOARD_DIR.glob("*.json")):
            with open(p) as f:
                t = Task.from_dict(json.load(f))
            if level is not None and t.level != level:
                continue
            if state is not None and t.state != state:
                continue
            tasks.append(t)
        return tasks

    def children_of(self, parent_id: str) -> list[Task]:
        return [t for t in self.list() if t.parent_id == parent_id]

    # -- claim / complete (caste pull model) --

    def claim(self, level: Level, caste_tag: Optional[str] = None) -> Optional[Task]:
        for t in self.list(level=level, state=State.READY):
            if t.transition(State.IN_PROGRESS):
                if caste_tag:
                    t.caste = caste_tag
                self.update(t)
                return t
        for t in self.list(level=level, state=State.BACKLOG):
            t.transition(State.READY)
            self.update(t)
            if t.transition(State.IN_PROGRESS):
                if caste_tag:
                    t.caste = caste_tag
                self.update(t)
                return t
        return None

    def complete(self, task_id: str, result: str) -> Optional[Task]:
        t = self.get(task_id)
        if t is None:
            return None
        if t.state != State.IN_PROGRESS:
            return None
        t.result = result
        t.transition(State.DONE)
        self.update(t)
        return t

    def block(self, task_id: str, reason: str = "") -> Optional[Task]:
        t = self.get(task_id)
        if t is None:
            return None
        t.result = reason or "blocked"
        t.transition(State.BLOCKED)
        self.update(t)
        return t

    def count(self, level: Optional[Level] = None, state: Optional[State] = None) -> dict[str, int]:
        counts: dict[str, int] = {}
        for t in self.list(level=level):
            key = f"{t.level.value}.{t.state.value}"
            counts[key] = counts.get(key, 0) + 1
        return counts
