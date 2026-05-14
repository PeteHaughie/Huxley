from __future__ import annotations
from pathlib import Path
from typing import Optional

from harness.config import MONSTER_SKILLS_DIR

AGENTS_SKILLS_DIR = Path.home() / ".agents" / "skills"


def _skill_dirs() -> list[Path]:
    dirs = []
    if MONSTER_SKILLS_DIR.exists():
        dirs.append(MONSTER_SKILLS_DIR)
    if AGENTS_SKILLS_DIR.exists():
        dirs.append(AGENTS_SKILLS_DIR)
    return dirs


def _scan_dir(dir_path: Path) -> list[dict]:
    skills = []
    for entry in sorted(dir_path.iterdir()):
        if entry.is_dir():
            skill_path = entry / "SKILL.md"
            if skill_path.exists():
                frontmatter = _parse_frontmatter(skill_path)
                skills.append({
                    "name": entry.name,
                    "path": str(skill_path),
                    "description": frontmatter.get("description", ""),
                    "source": "monster" if dir_path == MONSTER_SKILLS_DIR else "agents",
                })
    return skills


def list_skills() -> list[dict]:
    seen: set[str] = set()
    skills = []
    for d in _skill_dirs():
        for s in _scan_dir(d):
            if s["name"] not in seen:
                seen.add(s["name"])
                skills.append(s)
    return skills


def load_skill(name: str) -> Optional[str]:
    for d in _skill_dirs():
        skill_path = d / name / "SKILL.md"
        if skill_path.exists():
            with open(skill_path) as f:
                content = f.read()
            return _strip_frontmatter(content)
    return None


def _parse_frontmatter(path: Path) -> dict:
    content = path.read_text()
    meta = {}
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            for line in parts[1].strip().split("\n"):
                if ":" in line:
                    key, _, val = line.partition(":")
                    meta[key.strip()] = val.strip().strip('"').strip("'")
    return meta


def _strip_frontmatter(content: str) -> str:
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            return parts[2].strip()
    return content.strip()
