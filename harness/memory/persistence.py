from __future__ import annotations
import json
import uuid
import os
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
