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
┌──────────────────────────────────────────────────────────┐
│  monsterd  (background daemon, ~/.monster/monsterd.pid)  │
│                                                          │
│  ┌── tick loop (every 5s) ────────────────────────────┐  │
│  │  scheduler: check registry → fire due entries      │  │
│  │  worker:   claim board tasks → route → complete    │  │
│  │  router:   shared instance (models stay resident)  │  │
│  └────────────────────────────────────────────────────┘  │
│                                                          │
│  User                                                    │
│    │                                                     │
│    ▼                                                     │
│  α (Gemma 4 e4B)      ←──┐                               │
│    │                     │                               │
│    ├── posts EPICs ──────┤                               │
│    │                     │                               │
│    ▼                     │                               │
│  ╔════════════════════╗  │  ← shared pull-queue          │
│  ║   Kanban Board     ║  │                               │
│  ║  ~/.monster/board/ ║  │                               │
│  ╚════════════════════╝  │                               │
│    ▲                     │                               │
│    │                     │                               │
│    ├── β claims EPICs,   │                               │
│    │   decomposes into   │                               │
│    │   UNITS, posts back │                               │
│    │                     │                               │
│    ├── γ claims UNITS,   │                               │
│    │   executes, marks   │                               │
│    │   done              │                               │
│    │                     │                               │
│    └── β sees done,      │                               │
│        assembles, marks ─┘                               │
│        EPIC complete                                     │
│                                                          │
│  Memory (all castes):                                    │
│    ├── Session Journal  (append-only JSONL per caste)    │
│    ├── Chroma          (vector memory)                   │
│    ├── MemQ Graph      (entity-relation memory)          │
│    ├── TurboQuant KV Cache                               │
│    └── Cloud Endpoint  (OpenAI-compatible, optional)     │
└──────────────────────────────────────────────────────────┘
```

### Caste System

| Caste | Model | Engine | Context | Role |
|-------|-------|--------|---------|------|
| γ | Apple Foundation Model | [Apfel](https://github.com/Arthur-Ficial/apfel) | 4K | File I/O, classification, extraction, grep generation. Stateless, disposable. |
| β | [Ternary Bonsai 8B](https://prismml.com/news/ternary-bonsai) | MLX (primary) / llama.cpp (fallback) | 8K | Summarisation, routing, task decomposition. Short-term context only. |
| α | [Gemma 4 e4B](https://ai.google.dev/gemma) 4bit | llama.cpp + MTP + TurboQuant | 32K | Orchestration, HCI, long-term memory, skill dispatch, cloud routing. |

### Job Board

All inter-caste work flows through a shared Kanban board at `~/.monster/board/`. Castes never call each other directly — they pull tasks from the board.

```
Levels:  EPIC  ──β──→  TASK  ──β──→  UNIT
         (α posts)     (optional)    (γ executes)

States:  backlog → ready → in_progress → done
                                    ↘→ blocked → backlog
```

| Level | Who | What |
|-------|-----|------|
| EPIC | α posts, β claims | High-level goal or feature request |
| TASK | β posts, β claims | Decomposition step (optional intermediate) |
| UNIT | β posts, γ claims | Atomic execution unit — file I/O, classify, extract |

State machine enforces valid transitions (e.g. `backlog → ready` before `in_progress`). Tasks track caste ownership, timestamps, parent hierarchy, and result text.

```bash
# View the board
monster board list
monster board list --level epic
monster board list --state in_progress

# Post work
monster board post epic "refactor memory system" --prompt "..."
monster board post unit "implement GET endpoint"

# Claim work (pulls next backlog→ready→in_progress)
monster board claim epic --caste β

# Show details
monster board show <task-id>          # partial UUID prefix ok

# Complete work
monster board complete <task-id> --result "done"

# Launch Kanban web UI as background daemon (Python stdlib, zero deps)
monster board serve start --port 8080
# γ|boardd|started|pid 12345|http://localhost:8080

monster board serve status
# γ|boardd|running|pid 12345|http://localhost:8080

monster board serve stop
# γ|boardd|stopped|pid 12345
```

### Memory System

Three layers, each progressively more persistent:

1. **VK Cache (TurboQuant)** — In-process KV cache at 4.5 bits/element via `--cache-type-k turbo4_0`. Persisted to `~/.monster/<session>/cache/`.
2. **Vector DB (Chroma)** — Semantic memory in `~/.monster/<session>/interlink/`. Queried by Alpha for relevant past context.
3. **MemQ Graph** — Entity-relation graph. Nodes = concepts/files/agents, edges = typed relationships. JSON-backed, queryable by traversal.

### Models

GGUF models are stored in `~/.monster/models/` — a central, harness-managed directory.

| Model | Path | Caste |
|-------|------|-------|
| Gemma 4 e4B (main) | `~/.monster/models/gemma-4-e4b-Q4_K_M.gguf` | α |
| Gemma 4 e4B draft (MTP) | `~/.monster/models/gemma-4-e4b-draft.gguf` | α |
| Ternary Bonsai 8B (llama.cpp fallback) | `~/.monster/models/ternary-bonsai-8b.gguf` | β |

```bash
# List models in the models directory
monster models
# γ|model|gemma-4-e4b-Q4_K_M.gguf|5.2G
```

MLX models (primary Beta engine) are cached by MLX in its own Hugging Face cache — no extra management needed.

Model paths in `~/.monster/config.yaml` use `~` expansion and are resolved at load time.

## Session Lifecycle

```
~/.monster/
  registry.json           # path → session-id mapping
  config.yaml             # global harness configuration
  models/                 # GGUF model files (Gemma 4, Bonsai fallback, etc.)
  board/                  # Kanban job board (one JSON file per task)
  skills/                 # monster-specific skills (shadow ~/.agents/skills/)
  scheduler/
    schedules.json        # persistent schedule registry
    history.json          # last-N firings per schedule
  monsterd.pid            # daemon PID (auto-generated)
  monsterd.port           # daemon control port
  monsterd.log            # daemon log output
  boardd.pid              # board web UI PID
  boardd.port             # board web UI port
  boardd.log              # board web UI log
  apfeld.pid              # Apfel PID (only if monster started it)
  apfeld.log              # Apfel log
  sessions/
    <uuid>/
      meta.json           # session metadata (path, created, last active)
      interlink/          # Chroma vector database
      graph/              # MemQ graph snapshots (nodes.json, edges.json)
      cache/              # TurboQuant KV cache state
      gamma/
        journal.jsonl     # append-only JSONL conversation log
      beta/
        journal.jsonl     # append-only JSONL conversation log
      alpha/
        journal.jsonl     # append-only JSONL conversation log
```

Each project directory can have a `.monster` symlink → `~/.monster/sessions/<uuid>/` for quick reference.

## Daemon (monsterd)

The background daemon runs the scheduler tick loop and autonomous worker loop. It manages caste lifecycles, ports, and process state.

```bash
# Start monsterd (background, PID at ~/.monster/monsterd.pid)
monster daemon start

# Check status
monster daemon status

# Stop gracefully
monster daemon stop
```

The daemon exposes an HTTP control API on `localhost:8083` (`MONSTERD_PORT`) for internal CLI commands. It stays resident so castes don't need to reload models between invocations.

## Scheduler

The scheduler runs inside monsterd — a tick loop (every 5s) that checks the schedule registry and fires due actions. Schedules persist across restarts in `~/.monster/scheduler/`.

### Trigger Types

| Type | Description | Syntax |
|------|-------------|--------|
| `interval` | Fire every N seconds | `--every 3600` |
| `daily_at` | Fire at wall-clock time daily | `--at 02:00` |
| `idle` | Fire after N seconds of empty board | `--idle-after 3600` |
| `backlog` | Fire when backlog exceeds threshold | `--backlog 5` |

### Action Types

| Action | Effect |
|--------|--------|
| `post_to_board` | Creates board entry (default — preserves pull model) |

### Commands

```bash
# List all schedules
monster schedule list

# Add an interval schedule (post a task to the board every hour)
monster schedule add --type interval --every 3600 --action post_to_board --level task --title "hourly scan"

# Add a daily schedule
monster schedule add --type daily_at --at 02:00 --action post_to_board --level epic --title "morning summary"

# View firing history
monster schedule history

# Remove a schedule
monster schedule remove <id>
```

## Autonomous Worker Loop

Every tick, the daemon claims pending board tasks and routes them to the correct caste:

- **UNITS** → Gamma (cheap, stateless Apfel inference)
- **TASKS** → Beta (mid-weight Bonsai inference)
- **EPICs** → Alpha (full Gemma 4 orchestration)

The Router is shared across ticks — models stay resident, no reload overhead between inferences.

## Apfel Auto-Start

Gamma auto-starts Apfel lazily on the first `infer()` call via `ensure_apfel()`. A PID file at `~/.monster/apfeld.pid` tracks ownership: if monster started Apfel, `monster daemon stop` also kills it. If you started Apfel yourself, it is never touched.

## Swarm (LAN Peer Discovery)

Monsters on the same LAN automatically discover each other via **UDP multicast**. Each running `monsterd` broadcasts a heartbeat every 30s to `239.255.43.21:43210` and listens for heartbeats from peers. Peers are marked as lost after 90s of silence.

```
┌──────────────────┐        UDP multicast          ┌─────────────────┐
│ monsterd (M2 Pro)│ ◄───── 239.255.43.21 ───────► │ monsterd (M5)   │
│ port 8083        │                               │ port 8083       │
│ castes: αβγ      │                               │ castes: αγ      │
└──────────────────┘                               └─────────────────┘
```

Discovery is **zero-config** — no registry, no configuration, no external dependencies. If two daemons are on the same LAN, they find each other automatically.

```bash
# List known LAN peers (requires monsterd running)
monster swarm peers
# γ|swarm|peer|●|m2-mini-32gb         |:8083|castes=αβγ|load=0.0|age=12s

# Show swarm status
monster swarm status
# γ|swarm|status|total=1|active=1
```

The peer table is accessible via the daemon control API:

| Endpoint | Description |
|----------|-------------|
| `GET /v1/swarm/peers` | List known LAN peers |
| `GET /v1/swarm/status` | Swarm status (enabled, peer count) |

### Config

```yaml
swarm:
  enabled: true
  multicast_group: 239.255.43.21
  multicast_port: 43210
  announce_interval: 30
  stale_timeout: 90
```

### Roadmap (future)

- **Borrow/lend model**: Request idle β/γ capacity from peers via the daemon HTTP API
- **Idle consensus**: When all local EPICs are done and peers are idle, form distributed daydream sessions
- **Auth tokens**: Per-task authentication for remote board access

## Session Journal & Compaction

Every caste writes an append-only JSONL journal per session at `~/.monster/sessions/<sid>/<caste>/journal.jsonl`. Journals survive crashes (corrupt trailing lines are skipped on read).

When a journal exceeds 30 entries, the caste auto-compacts: it self-summarises the middle portion into a system message, preserving the first 2 turns and the last 10 verbatim. The rewrite reduces token waste while retaining conversational context.

```bash
# Manual compaction (uses Beta by default)
monster compact --caste b
```

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

### General

| Command | Description |
|---------|-------------|
| `monster --version` | Print version |
| `monster init` | Initialise .monster session in directory |
| `monster session` | Show current session info |
| `monster skills` | List available skills from both skill directories |
| `monster infer <caste> <prompt>` | Route prompt through a caste (α, β, or γ) |
| `monster api` | List all functions and classes across harness modules |
| `monster modules` | List all harness modules |
| `monster models` | List GGUF models in `~/.monster/models/` |
| `monster cloud <prompt>` | Route prompt via cloud endpoint |
| `monster patch [--apply] <file>` | Dry-run or apply a self-mod patch |
| `monster compact [--caste]` | Compact session journal via summarisation |
| `monster daemon start\|stop\|status` | Manage monster background daemon |
| `monster schedule list\|add\|remove\|history` | Manage scheduled tasks |
| `monster swarm peers\|status` | LAN peer discovery and swarm status |

### Board (Kanban Job Queue)

| Command | Description |
|---------|-------------|
| `monster board list [--level] [--state]` | List tasks, optionally filtered |
| `monster board post <level> <title>` | Post a new task (epic/task/unit) |
| `monster board show <task-id>` | Show full task details |
| `monster board claim <level> --caste <caste>` | Pull next available task into in_progress |
| `monster board complete <task-id> [--result]` | Mark task as done with result |
| `monster board delete <task-id>` | Delete a task from the board |
| `monster board serve start [--port]` | Start Kanban web UI daemon (default 8080) |
| `monster board serve stop` | Stop board daemon |
| `monster board serve status` | Check board daemon status |

### Daemon (monsterd)

| Command | Description |
|---------|-------------|
| `monster daemon start` | Start monsterd in background |
| `monster daemon stop` | Stop monsterd |
| `monster daemon status` | Check if monsterd is running |

### Scheduler

| Command | Description |
|---------|-------------|
| `monster schedule list` | List all schedules |
| `monster schedule add <type> <interval/daily_at>` | Add a schedule |
| `monster schedule remove <id>` | Remove a schedule |
| `monster schedule history [<id>]` | View firing history |

### Compaction

| Command | Description |
|---------|-------------|
| `monster compact [--caste]` | Compact session journal via summarisation |

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
│   ├── cli.py               # Entry point with 15+ commands
│   ├── config.py            # YAML config, ~/.monster/ bootstrap
│   ├── board/
│   │   ├── __init__.py
│   │   ├── __main__.py      # Board daemon subprocess entry point
│   │   ├── core.py          # JobBoard, Task, Level, State, transitions
│   │   ├── lifecycle.py     # Board daemon start/stop/status
│   │   └── serve.py         # Kanban web UI + REST API server
│   ├── caste/
│   │   ├── __init__.py
│   │   ├── _base.py         # CasteBase ABC
│   │   ├── apfeld.py        # Apfel lifecycle (auto-start, PID tracking)
│   │   ├── gamma.py         # Apfel integration
│   │   ├── beta.py          # Bonsai Ternary / MLX / llama.cpp integration
│   │   └── alpha.py         # Gemma 4 / llama.cpp integration
│   ├── comms/
│   │   ├── __init__.py
│   │   ├── message.py       # Structured JSON protocol (Message, Caste, Action, ContextHint)
│   │   └── router.py        # Caste message dispatcher (shared across ticks)
│   ├── daemon/
│   │   ├── __init__.py
│   │   ├── lifecycle.py     # monsterd start/stop/status
│   │   ├── server.py        # HTTP control API server
│   │   └── scheduler.py     # Tick loop, schedule registry, autonomous worker
│   ├── memory/
│   │   ├── __init__.py
│   │   ├── persistence.py   # SessionJournal (JSONL), SessionStore (registry)
│   │   ├── vector_db.py     # Chroma semantic memory
│   │   ├── memq_graph.py    # Entity-relation graph memory
│   │   └── vk_cache.py      # TurboQuant KV cache lifecycle
│   ├── skill/
│   │   ├── __init__.py
│   │   ├── loader.py        # Dual-path skill loader (monster + agents)
│   │   └── registry.py      # Cached skill registry
│   ├── cloud/
│   │   ├── __init__.py
│   │   ├── endpoint.py      # OpenAI-compatible cloud client
│   │   └── router.py        # Cloud routing
│       ├── swarm/
│   │   ├── __init__.py
│   │   ├── peer.py          # Peer table with TTL-based staleness
│   │   └── discovery.py     # UDP multicast discovery service
│   ├── selfmod/
│   │   ├── __init__.py
│   │   ├── introspect.py    # AST-based API surface discovery
│   │   ├── patcher.py       # Dry-run/apply/rollback patches
│   │   └── restart.py       # SIGHUP hot-reload
│   └── server/
│       ├── __init__.py
│       └── inference.py     # Shared OpenAICompatibleClient
├── PLAN.md                  # Architecture and implementation plan
├── ROADMAP.md               # Future directions
├── pyproject.toml           # Python package configuration
└── README.md                # This file
```

## License

MIT
