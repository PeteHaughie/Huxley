# 1BitMonster

Hyper-efficient local-first AI agent harness with a three-tier caste system.

```
γ — Gammas:  disposable workers (menial, high-volume, cheap)
β — Betas:   middle management (summarisation, routing, light reasoning)
α — Alphas:  orchestrators (pure cognition, all HCI, no heavy lifting)
```

All communication within the harness is curt and perfunctionary (caveman style) to keep context windows to a bare minimum.

## Architecture

```
User ←→ α (Gemma 4 e4B 4bit + MTP + TurboQuant)
           │
           ├──→ β (Bonsai Ternary 8B / MLX)
           │         │
           │         └──→ Chroma (vector memory)
           │
           ├──→ MemQ Graph (entity-relation memory)
           │
           ├──→ γ (Apfel — Apple Foundation Model)
           │
           └──→ Cloud Endpoint (OpenAI-compatible, optional)
```

### Caste System

| Caste | Model | Engine | Context | Role |
|-------|-------|--------|---------|------|
| γ | Apple Foundation Model | [Apfel](https://github.com/Arthur-Ficial/apfel) | 4K | File I/O, classification, extraction, grep generation. Stateless, disposable. |
| β | [Ternary Bonsai 8B](https://prismml.com/news/ternary-bonsai) | MLX (primary) / llama.cpp (fallback) | 8K | Summarisation, routing, task decomposition. Short-term context only. |
| α | [Gemma 4 e4B](https://ai.google.dev/gemma) 4bit | llama.cpp + MTP + TurboQuant | 32K | Orchestration, HCI, long-term memory, skill dispatch, cloud routing. |

### Memory System

Three layers, each progressively more persistent:

1. **VK Cache (TurboQuant)** — In-process KV cache at 4.5 bits/element via `--cache-type-k turbo4_0`. Persisted to `~/.monster/<session>/cache/`.
2. **Vector DB (Chroma)** — Semantic memory in `~/.monster/<session>/interlink/`. Queried by Alpha for relevant past context.
3. **MemQ Graph** — Entity-relation graph. Nodes = concepts/files/agents, edges = typed relationships. JSON-backed, queryable by traversal.

### Session Lifecycle

```
~/.monster/
  registry.json       # path → session-id mapping
  config.yaml         # global harness configuration
  skills/             # monster-specific skills (shadow ~/.agents/skills/)
  sessions/
    <uuid>/
      meta.json       # session metadata (path, created, last active)
      interlink/      # Chroma vector database
      graph/          # MemQ graph snapshots (nodes.json, edges.json)
      cache/          # TurboQuant KV cache state
      gamma/          # Apfel session scratch
      beta/           # Bonsai session scratch
      alpha/          # Alpha session scratch
```

Each project directory can have a `.monster` symlink → `~/.monster/sessions/<uuid>/` for quick reference.

## Requirements

- **macOS 26+** (Tahoe) for Apfel / Apple Foundation Model
- **Apple Silicon** (M1+)
- **Python 3.11+**
- **Apfel** — `brew install apfel` (for Gamma caste)
- **Optional**: MLX (`pip install mlx-lm`) for Beta caste
- **Optional**: llama.cpp with Gemma 4 GGUF + TurboQuant for Alpha caste

## Installation

```bash
# Clone the repository
git clone git@github.com:PeteHaughie/monster.git
cd monster

# Install core dependencies
pip install pyyaml httpx uuid7

# Install optional dependencies for additional features
pip install chromadb          # vector memory
pip install mlx-lm            # Beta caste (Bonsai Ternary)
pip install llama-cpp-python  # Alpha caste (Gemma 4)

# (Optional) Start Apfel for Gamma caste
apfel --serve

# Initialise the harness
python -m harness init
```

## Quick Start

```bash
# Show version
monster --version

# Initialise a session in the current directory
monster init

# Show current session info
monster session

# List available skills (from ~/.agents/skills/ + ~/.monster/skills/)
monster skills

# List all harness modules
monster modules

# Discover harness API surface
monster api

# Route a prompt through Gamma caste (requires apfel --serve)
monster infer γ "extract all email addresses from this text"

# Route a prompt through Beta caste (requires mlx-lm)
monster infer β "summarise the key points"

# Route a prompt through Alpha caste (requires llama.cpp + Gemma 4)
monster infer α "what should I work on next?"

# Route through cloud endpoint (requires cloud config)
monster cloud "explain quantum computing"

# Dry-run a self-mod patch
monster patch harness/cli.py

# Apply a self-mod patch
monster patch --apply harness/config.py
```

## Commands

| Command | Description |
|---------|-------------|
| `monster --version` | Print version |
| `monster init` | Initialise .monster session in directory |
| `monster session` | Show current session info |
| `monster skills` | List available skills from both skill directories |
| `monster infer <caste> <prompt>` | Route prompt through a caste (α, β, or γ) |
| `monster api` | List all functions and classes across harness modules |
| `monster modules` | List all harness modules |
| `monster cloud <prompt>` | Route prompt via cloud endpoint |
| `monster patch [--apply] <file>` | Dry-run or apply a self-mod patch |

## Configuration

`~/.monster/config.yaml` is auto-generated on first `monster init`:

```yaml
alpha:
  engine: llama.cpp
  model: gemma-4-e4b-Q4_K_M.gguf
  draft_model: gemma-4-e4b-draft.gguf
  cache_type_k: turbo4_0
  cache_type_v: turbo4_0
  ctx_size: 32768
  ngl: 99
  mtp: true
  draft_block_size: 3
  draft_max: 8

beta:
  engine: mlx
  model: prism-ml/Ternary-Bonsai-8B
  ctx_size: 8192
  fallback_engine: llama.cpp
  fallback_model: ternary-bonsai-8b.gguf

gamma:
  endpoint: http://localhost:11434/v1
  model: apple-foundationmodel
  ctx_size: 4096

cloud:
  enabled: false
  endpoint: ""
  api_key: ""
  model: ""

harness:
  context_hint: caveman
  log_level: INFO
  session_timeout: 3600
```

## Skills System

The harness loads skills from two directories, checked in order:

1. **`~/.monster/skills/`** — Monster-specific skills (highest priority)
2. **`~/.agents/skills/`** — Generic shared skills (compatible with other agent frameworks)

If the same skill name exists in both, the monster version wins. This prevents monster-specific skills (which may depend on harness architecture) from polluting the shared `~/.agents/` namespace.

### Skill Format

```
~/.monster/skills/<skill-name>/SKILL.md
```

Each skill is a markdown file with YAML frontmatter:

```markdown
---
name: my-monster-skill
description: What this skill does
---

Skill instructions and system prompts...
```

## Self-Modification

The harness can read, patch, and hot-reload its own source code:

- **Introspection** (`harness/selfmod/introspect.py`): AST-based API surface discovery. Maps all modules, classes, functions with line numbers.
- **Patcher** (`harness/selfmod/patcher.py`): Diff generation, dry-run, apply with backup, rollback. Patches stored in `~/.monster/patches/`.
- **Hot-Reload** (`harness/selfmod/restart.py`): SIGHUP-triggered `os.execv` restart. Register with `register_reload_handler()`.

All self-mods are non-destructive by default (`dry_run=True`). Rollback available by patch ID.

## Cloud Support

Configurable OpenAI-compatible cloud endpoint. When enabled, Alpha can route sub-tasks to the cloud alongside local inference:

```yaml
cloud:
  enabled: true
  endpoint: https://api.openai.com/v1
  api_key: sk-...
  model: gpt-4o
```

Cloud responses masquerade as Beta-caste messages in the harness message protocol.

## Project Structure

```
monster/
├── harness/
│   ├── __init__.py          # Package version
│   ├── __main__.py          # python -m harness
│   ├── cli.py               # Entry point with 9 commands
│   ├── config.py            # YAML config, ~/.monster/ bootstrap
│   ├── caste/
│   │   ├── _base.py         # CasteBase ABC
│   │   ├── gamma.py         # Apfel integration
│   │   ├── beta.py          # Bonsai Ternary / MLX integration
│   │   └── alpha.py         # Gemma 4 / llama.cpp integration
│   ├── comms/
│   │   ├── message.py       # Structured JSON protocol
│   │   └── router.py        # Caste message dispatcher
│   ├── memory/
│   │   ├── persistence.py   # Session store, path↔session registry
│   │   ├── vector_db.py     # Chroma semantic memory
│   │   ├── memq_graph.py    # Entity-relation graph memory
│   │   └── vk_cache.py      # TurboQuant KV cache lifecycle
│   ├── skill/
│   │   ├── loader.py        # Dual-path skill loader (monster + agents)
│   │   └── registry.py      # Cached skill registry
│   ├── cloud/
│   │   ├── endpoint.py      # OpenAI-compatible cloud client
│   │   └── router.py        # Cloud routing
│   ├── selfmod/
│   │   ├── introspect.py    # AST-based API surface discovery
│   │   ├── patcher.py       # Dry-run/apply/rollback patches
│   │   └── restart.py       # SIGHUP hot-reload
│   └── server/
│       └── inference.py     # Shared OpenAICompatibleClient
├── PLAN.md                  # Architecture and implementation plan
├── ROADMAP.md               # Future directions
├── pyproject.toml           # Python package configuration
└── README.md                # This file
```

## License

MIT
