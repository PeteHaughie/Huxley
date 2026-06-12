from __future__ import annotations
from pathlib import Path
from typing import Optional

from harness.config import HUXLEY_SKILLS_DIR

AGENTS_SKILLS_DIR = Path.home() / ".agents" / "skills"


def _skill_dirs() -> list[Path]:
    dirs = []
    if HUXLEY_SKILLS_DIR.exists():
        dirs.append(HUXLEY_SKILLS_DIR)
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
                    "triggers": frontmatter.get("triggers", []),
                    "requires_tools": frontmatter.get("requires_tools", False),
                    "source": "huxley" if dir_path == HUXLEY_SKILLS_DIR else "agents",
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


def load_skill_with_frontmatter(name: str) -> Optional[dict]:
    for d in _skill_dirs():
        skill_path = d / name / "SKILL.md"
        if skill_path.exists():
            frontmatter = _parse_frontmatter(skill_path)
            body = _strip_frontmatter(skill_path.read_text())
            return {"name": name, "frontmatter": frontmatter, "body": body}
    return None


def _normalize_frontmatter(meta: dict) -> dict:
    out = {}
    for k, v in meta.items():
        if isinstance(v, str) and v.lower() in ("true", "false"):
            out[k] = v.lower() == "true"
        else:
            out[k] = v
    return out


def _parse_frontmatter(path: Path) -> dict:
    content = path.read_text()
    meta: dict = {}
    if not content.startswith("---"):
        return meta
    parts = content.split("---", 2)
    if len(parts) < 3:
        return meta
    current_key = None
    for line in parts[1].strip().split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("- "):
            val = stripped[2:].strip().strip('"').strip("'")
            if current_key is not None:
                if current_key not in meta:
                    meta[current_key] = []
                meta[current_key].append(val)
        elif ":" in stripped:
            key, _, val = stripped.partition(":")
            current_key = key.strip()
            val = val.strip()
            if val:
                meta[current_key] = val.strip('"').strip("'")
            else:
                meta[current_key] = []
    return _normalize_frontmatter(meta)


def _strip_frontmatter(content: str) -> str:
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            return parts[2].strip()
    return content.strip()
