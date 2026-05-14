from __future__ import annotations
from harness.skill.loader import list_skills, load_skill


class SkillRegistry:
    def __init__(self):
        self._cache: dict[str, str] = {}

    def refresh(self):
        self._cache.clear()
        for s in list_skills():
            body = load_skill(s["name"])
            if body:
                self._cache[s["name"]] = body

    def get(self, name: str) -> str | None:
        if name not in self._cache:
            body = load_skill(name)
            if body:
                self._cache[name] = body
        return self._cache.get(name)

    def all(self) -> list[dict]:
        return list_skills()

    def has(self, name: str) -> bool:
        return self.get(name) is not None

    def count(self) -> int:
        return len(self._cache) or len(list_skills())
