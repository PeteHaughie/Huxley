import os
import yaml
from pathlib import Path

MONSTER_HOME = Path.home() / ".monster"
MONSTER_SKILLS_DIR = MONSTER_HOME / "skills"
DEFAULT_CONFIG_PATH = MONSTER_HOME / "config.yaml"
REGISTRY_PATH = MONSTER_HOME / "registry.json"
SESSIONS_DIR = MONSTER_HOME / "sessions"

DEFAULT_CONFIG = {
    "alpha": {
        "engine": "llama.cpp",
        "model": "gemma-4-e4b-Q4_K_M.gguf",
        "draft_model": "gemma-4-e4b-draft.gguf",
        "cache_type_k": "turbo4_0",
        "cache_type_v": "turbo4_0",
        "ctx_size": 32768,
        "ngl": 99,
        "mtp": True,
        "draft_block_size": 3,
        "draft_max": 8,
    },
    "beta": {
        "engine": "mlx",
        "model": "prism-ml/Ternary-Bonsai-8B",
        "ctx_size": 8192,
        "fallback_engine": "llama.cpp",
        "fallback_model": "ternary-bonsai-8b.gguf",
    },
    "gamma": {
        "endpoint": "http://localhost:11434/v1",
        "model": "apple-foundationmodel",
        "ctx_size": 4096,
    },
    "cloud": {
        "enabled": False,
        "endpoint": "",
        "api_key": "",
        "model": "",
    },
    "harness": {
        "context_hint": "caveman",
        "log_level": "INFO",
        "session_timeout": 3600,
    },
}


def ensure_monster_dirs():
    MONSTER_HOME.mkdir(parents=True, exist_ok=True)
    MONSTER_SKILLS_DIR.mkdir(exist_ok=True)
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    if not DEFAULT_CONFIG_PATH.exists():
        with open(DEFAULT_CONFIG_PATH, "w") as f:
            yaml.dump(DEFAULT_CONFIG, f, default_flow_style=False)


def load_config() -> dict:
    ensure_monster_dirs()
    if not DEFAULT_CONFIG_PATH.exists():
        return DEFAULT_CONFIG
    with open(DEFAULT_CONFIG_PATH) as f:
        cfg = yaml.safe_load(f) or {}
    merged = DEFAULT_CONFIG.copy()
    merged.update(cfg)
    return merged


def save_config(cfg: dict):
    ensure_monster_dirs()
    with open(DEFAULT_CONFIG_PATH, "w") as f:
        yaml.dump(cfg, f, default_flow_style=False)
