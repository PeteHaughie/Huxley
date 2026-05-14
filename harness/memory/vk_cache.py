from __future__ import annotations
from pathlib import Path


class VKCache:
    def __init__(self, path: Path):
        self.path = path
        self.path.mkdir(parents=True, exist_ok=True)

    def snapshot(self):
        pass

    def restore(self):
        pass

    @property
    def is_persisted(self) -> bool:
        return any(self.path.iterdir())
