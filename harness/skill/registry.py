from __future__ import annotations
from harness.skill.loader import list_skills, load_skill, load_skill_with_frontmatter


class SkillRegistry:
    def __init__(self):
        self._cache: dict[str, str] = {}
        self._frontmatter_cache: dict[str, dict] = {}

    def refresh(self):
        self._cache.clear()
        self._frontmatter_cache.clear()
        for s in list_skills():
            body = load_skill(s["name"])
            if body:
                self._cache[s["name"]] = body
            fm = load_skill_with_frontmatter(s["name"])
            if fm:
                self._frontmatter_cache[s["name"]] = fm["frontmatter"]

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

    def load_skill_body(self, name: str) -> str | None:
        return load_skill(name)

    def all_with_triggers(self) -> list[dict]:
        seen: set[str] = set()
        result = []
        for d in list_skills():
            name = d["name"]
            if name in seen:
                continue
            seen.add(name)
            triggers = d.get("triggers", [])
            result.append({
                "name": name,
                "description": d.get("description", ""),
                "source": d.get("source", ""),
                "triggers": triggers if isinstance(triggers, list) else [],
                "requires_tools": bool(d.get("requires_tools", False)),
            })
        return result
