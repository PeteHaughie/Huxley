import os
import yaml
from pathlib import Path

HUXLEY_HOME = Path.home() / ".huxley"
HUXLEY_SKILLS_DIR = HUXLEY_HOME / "skills"
HUXLEY_MODELS_DIR = HUXLEY_HOME / "models"
HUXLEY_BOARD_DIR = HUXLEY_HOME / "board"
HUXLEY_SCHEDULER_DIR = HUXLEY_HOME / "scheduler"
HUXLEY_PROJECTS_DIR = HUXLEY_HOME / "projects"
DEFAULT_CONFIG_PATH = HUXLEY_HOME / "config.yaml"
REGISTRY_PATH = HUXLEY_HOME / "registry.json"
SESSIONS_DIR = HUXLEY_HOME / "sessions"

DEFAULT_CONFIG = {
    "alpha": {
        "engine": "llama.cpp",
        "model": "~/.huxley/models/gemma-4-E4B-it-Q4_K_M.gguf",
        "draft_model": "~/.huxley/models/gemma-4-E4B-it-assistant-Q4_K_M.gguf",
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
        "model": "~/.huxley/models/Bonsai-8B.gguf",
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
        "log_file": "~/.huxley/huxleyd.log",
    },
    "scheduler": {
        "enabled": True,
        "tick_interval": 5,
    },
    "swarm": {
        "enabled": True,
        "multicast_group": "239.255.43.21",
        "multicast_port": 43210,
        "announce_interval": 30,
        "stale_timeout": 90,
        "delegation": {
            "enabled": True,
            "max_load": 5,
            "selection": "round_robin",
        },
    },
    "harness": {
        "context_hint": "caveman",
        "models_dir": "~/.huxley/models",
        "log_level": "INFO",
        "session_timeout": 3600,
    },
}


def resolve_path(p: str) -> str:
    return str(Path(p).expanduser().resolve())


def ensure_huxley_dirs():
    HUXLEY_HOME.mkdir(parents=True, exist_ok=True)
    HUXLEY_SKILLS_DIR.mkdir(exist_ok=True)
    HUXLEY_MODELS_DIR.mkdir(exist_ok=True)
    HUXLEY_BOARD_DIR.mkdir(exist_ok=True)
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    if not DEFAULT_CONFIG_PATH.exists():
        with open(DEFAULT_CONFIG_PATH, "w") as f:
            yaml.dump(DEFAULT_CONFIG, f, default_flow_style=False)


def load_config() -> dict:
    ensure_huxley_dirs()
    if not DEFAULT_CONFIG_PATH.exists():
        with open(DEFAULT_CONFIG_PATH, "w") as f:
            yaml.dump(DEFAULT_CONFIG, f, default_flow_style=False)
        return DEFAULT_CONFIG
    with open(DEFAULT_CONFIG_PATH) as f:
        cfg = yaml.safe_load(f) or {}
    if _repair_legacy_model_aliases(cfg):
        save_config(cfg)
    merged = _deep_merge_dicts(DEFAULT_CONFIG, cfg)
    _resolve_model_paths(merged)
    return merged


def _deep_merge_dicts(base: dict, overrides: dict) -> dict:
    merged = {}
    for key, value in base.items():
        if isinstance(value, dict):
            merged[key] = _deep_merge_dicts(value, {})
        else:
            merged[key] = value
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge_dicts(merged[key], value)
        else:
            merged[key] = value
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


def _repair_legacy_model_aliases(cfg: dict) -> bool:
    repaired = False
    for section, keys in {
        "alpha": ("model", "draft_model"),
        "beta": ("model", "fallback_model"),
    }.items():
        section_cfg = cfg.get(section)
        if not isinstance(section_cfg, dict):
            continue
        for key in keys:
            if section_cfg.get(key) == "apple-foundationmodel":
                section_cfg[key] = DEFAULT_CONFIG[section][key]
                repaired = True
    return repaired


def save_config(cfg: dict):
    ensure_huxley_dirs()
    with open(DEFAULT_CONFIG_PATH, "w") as f:
        yaml.dump(cfg, f, default_flow_style=False)
