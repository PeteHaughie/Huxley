import os
import yaml
from pathlib import Path

MONSTER_HOME = Path.home() / ".monster"
MONSTER_SKILLS_DIR = MONSTER_HOME / "skills"
MONSTER_MODELS_DIR = MONSTER_HOME / "models"
MONSTER_BOARD_DIR = MONSTER_HOME / "board"
MONSTER_SCHEDULER_DIR = MONSTER_HOME / "scheduler"
DEFAULT_CONFIG_PATH = MONSTER_HOME / "config.yaml"
REGISTRY_PATH = MONSTER_HOME / "registry.json"
SESSIONS_DIR = MONSTER_HOME / "sessions"

DEFAULT_CONFIG = {
    "alpha": {
        "engine": "llama.cpp",
        "model": "~/.monster/models/gemma-4-E4B-it-Q4_K_M.gguf",
        "draft_model": "~/.monster/models/gemma-4-E4B-it-assistant-Q4_K_M.gguf",
        "cache_type_k": "q4_0",
        "cache_type_v": "q4_0",
        "ctx_size": 32768,
        "ngl": 99,
        "mtp": False,
        "draft_block_size": 3,
        "draft_max": 8,
    },
    "beta": {
        "engine": "llama.cpp",
        "model": "~/.monster/models/Bonsai-8B.gguf",
        "ctx_size": 8192,
        "fallback_engine": "mlx",
        "fallback_model": "prism-ml/Ternary-Bonsai-8B",
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
    "daemon": {
        "enabled": False,
        "port": 8083,
        "log_file": "~/.monster/monsterd.log",
    },
    "scheduler": {
        "enabled": True,
        "tick_interval": 5,
    },
    "harness": {
        "context_hint": "caveman",
        "models_dir": "~/.monster/models",
        "log_level": "INFO",
        "session_timeout": 3600,
    },
}


def resolve_path(p: str) -> str:
    return str(Path(p).expanduser().resolve())


def ensure_monster_dirs():
    MONSTER_HOME.mkdir(parents=True, exist_ok=True)
    MONSTER_SKILLS_DIR.mkdir(exist_ok=True)
    MONSTER_MODELS_DIR.mkdir(exist_ok=True)
    MONSTER_BOARD_DIR.mkdir(exist_ok=True)
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    if not DEFAULT_CONFIG_PATH.exists():
        with open(DEFAULT_CONFIG_PATH, "w") as f:
            yaml.dump(DEFAULT_CONFIG, f, default_flow_style=False)


def load_config() -> dict:
    ensure_monster_dirs()
    if not DEFAULT_CONFIG_PATH.exists():
        with open(DEFAULT_CONFIG_PATH, "w") as f:
            yaml.dump(DEFAULT_CONFIG, f, default_flow_style=False)
        return DEFAULT_CONFIG
    with open(DEFAULT_CONFIG_PATH) as f:
        cfg = yaml.safe_load(f) or {}
    merged = DEFAULT_CONFIG.copy()
    for section, values in cfg.items():
        if section in merged and isinstance(merged[section], dict):
            merged[section].update(values)
        else:
            merged[section] = values
    _resolve_model_paths(merged)
    return merged


_model_path_keys = [
    ("alpha", "model"),
    ("alpha", "draft_model"),
    ("beta", "model"),
    ("beta", "fallback_model"),
    ("cloud", "model"),
]


def _resolve_model_paths(cfg: dict):
    for section, key in _model_path_keys:
        val = cfg.get(section, {}).get(key)
        if val and val.startswith("~"):
            cfg[section][key] = resolve_path(val)


def save_config(cfg: dict):
    ensure_monster_dirs()
    with open(DEFAULT_CONFIG_PATH, "w") as f:
        yaml.dump(cfg, f, default_flow_style=False)
