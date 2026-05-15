from __future__ import annotations
import json
import uuid
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from harness.config import MONSTER_HOME, SESSIONS_DIR, REGISTRY_PATH


class SessionStore:
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.path = SESSIONS_DIR / session_id
        self.meta_path = self.path / "meta.json"
        self.graph_dir = self.path / "graph"
        self.cache_dir = self.path / "cache"
        self.gamma_dir = self.path / "gamma"
        self.beta_dir = self.path / "beta"
        self.alpha_dir = self.path / "alpha"

    def ensure_dirs(self):
        self.path.mkdir(parents=True, exist_ok=True)
        self.graph_dir.mkdir(exist_ok=True)
        self.cache_dir.mkdir(exist_ok=True)
        self.gamma_dir.mkdir(exist_ok=True)
        self.beta_dir.mkdir(exist_ok=True)
        self.alpha_dir.mkdir(exist_ok=True)

    def save_meta(self, data: dict):
        self.ensure_dirs()
        with open(self.meta_path, "w") as f:
            json.dump(data, f, indent=2, default=str)

    def load_meta(self) -> dict:
        if not self.meta_path.exists():
            return {}
        with open(self.meta_path) as f:
            return json.load(f)

    @staticmethod
    def resolve_session(path_hint: Optional[str] = None) -> tuple[str, Path]:
        work_dir = Path(path_hint or os.getcwd()).resolve()
        registry = _load_registry()

        if str(work_dir) in registry:
            sid = registry[str(work_dir)]
            store = SessionStore(sid)
            if store.path.exists():
                return sid, work_dir

        sid = str(uuid.uuid4())
        registry[str(work_dir)] = sid
        _save_registry(registry)
        store = SessionStore(sid)
        store.ensure_dirs()
        store.save_meta({"path": str(work_dir), "created": sid[:8]})
        return sid, work_dir


def _load_registry() -> dict:
    if not REGISTRY_PATH.exists():
        return {}
    with open(REGISTRY_PATH) as f:
        return json.load(f)


def _save_registry(registry: dict):
    MONSTER_HOME.mkdir(parents=True, exist_ok=True)
    with open(REGISTRY_PATH, "w") as f:
        json.dump(registry, f, indent=2)


def _estimate_tokens(text: str) -> int:
    return int(len(text.split()) * 1.5) + 1


class SessionJournal:
    def __init__(self, session_id: str, caste_tag: str):
        self.path = SESSIONS_DIR / session_id / caste_tag / "journal.jsonl"

    def append(self, role: str, content: str):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a") as f:
            f.write(json.dumps({"role": role, "content": content, "ts": datetime.now(timezone.utc).isoformat()}, ensure_ascii=False) + "\n")

    def read(self, max_tokens: int = 4096) -> list[dict]:
        if not self.path.exists():
            return []
        raw = self.path.read_text()
        if not raw.strip():
            return []
        entries = []
        for line in raw.splitlines():
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                pass
        reserve = 256
        budget = max_tokens - reserve
        selected = []
        used = 0
        for entry in reversed(entries):
            est = _estimate_tokens(entry["content"])
            if used + est > budget:
                break
            selected.insert(0, entry)
            used += est
        return [{"role": e["role"], "content": e["content"]} for e in selected]

    def entry_count(self) -> int:
        if not self.path.exists():
            return 0
        raw = self.path.read_text()
        if not raw.strip():
            return 0
        count = 0
        for line in raw.splitlines():
            try:
                json.loads(line)
                count += 1
            except json.JSONDecodeError:
                pass
        return count

    def needs_compaction(self, threshold: int = 30) -> bool:
        return self.entry_count() > threshold

    def build_compactable_text(self, protected_count: int = 2, max_recent: int = 10) -> str | None:
        if not self.path.exists():
            return None
        raw = self.path.read_text()
        entries = []
        for line in raw.splitlines():
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                pass
        if len(entries) <= protected_count + max_recent + 1:
            return None
        compactable = entries[protected_count:-max_recent] if max_recent > 0 else entries[protected_count:]
        if not compactable:
            return None
        lines = []
        for e in compactable:
            lines.append(f"{e['role']}: {e['content']}")
        return "\n".join(lines)

    def compact(self, summary: str, protected_count: int = 2, max_recent: int = 10):
        if not self.path.exists():
            return
        raw = self.path.read_text()
        entries = []
        for line in raw.splitlines():
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                pass
        protected = entries[:protected_count]
        recent = entries[-max_recent:] if max_recent > 0 else []
        summary_entry = {"role": "system", "content": f"Previous context summary: {summary}", "ts": datetime.now(timezone.utc).isoformat()}
        new_entries = protected + [summary_entry] + recent
        with open(self.path, "w") as f:
            for e in new_entries:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")

    def clear(self):
        if self.path.exists():
            self.path.unlink()
