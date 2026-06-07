# Huxley

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
│  huxleyd  (background daemon, ~/.huxley/huxleyd.pid)     │
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
│  ║  ~/.huxley/board/  ║  │                               │
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
| β | [Ternary Bonsai 8B](https://prismml.com/news/ternary-bonsai) | llama.cpp | 8K | Summarisation, routing, task decomposition. Short-term context only. |
| α | [Gemma 4 e4B](https://ai.google.dev/gemma) 4bit | llama.cpp + MTP + TurboQuant | 32K | Orchestration, HCI, long-term memory, skill dispatch, cloud routing. |

### Job Board

All inter-caste work flows through a shared Kanban board at `~/.huxley/board/`. Castes never call each other directly — they pull tasks from the board.

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
huxley board list
huxley board list --level epic
huxley board list --state in_progress

# Post work
huxley board post epic "refactor memory system" --prompt "..."
huxley board post unit "implement GET endpoint"
huxley board post epic "build auth system" --tools      # tool-enabled, propagates to children
huxley board post unit "refactor parser" --tools        # single unit with tool access

# Claim work (pulls next backlog→ready→in_progress)
huxley board claim epic --caste β

# Show details
huxley board show <task-id>          # partial UUID prefix ok

# Complete work
huxley board complete <task-id> --result "done"

# Launch Kanban web UI as background daemon (Python stdlib, zero deps)
huxley board serve start --port 8080
# γ|boardd|started|pid 12345|http://localhost:8080

# From the web UI, use "clear board" to remove all tasks at once.
# API: DELETE /api/tasks  -> {"status":"cleared","removed":N}

huxley board serve status
# γ|boardd|running|pid 12345|http://localhost:8080

huxley board serve stop
# γ|boardd|stopped|pid 12345
```

### Memory System

Three layers, each progressively more persistent:

1. **VK Cache (TurboQuant)** — In-process KV cache at 4.5 bits/element via `--cache-type-k turbo4_0`. Persisted to `~/.huxley/<session>/cache/`.
2. **Vector DB (Chroma)** — Semantic memory in `~/.huxley/<session>/interlink/`. Queried by Alpha for relevant past context.
3. **MemQ Graph** — Entity-relation graph. Nodes = concepts/files/agents, edges = typed relationships. JSON-backed, queryable by traversal.

### Models

GGUF models are stored in `~/.huxley/models/` — a central, harness-managed directory.

| Model | Path | Caste |
|-------|------|-------|
| Gemma 4 e4B (main) | `~/.huxley/models/gemma-4-e4b-Q4_K_M.gguf` | α |
| Gemma 4 e4B draft (MTP) | `~/.huxley/models/gemma-4-e4b-draft.gguf` | α |
| Ternary Bonsai 8B | `~/.huxley/models/ternary-bonsai-8b.gguf` | β |

```bash
# List models in the models directory
huxley models
# γ|model|gemma-4-e4b-Q4_K_M.gguf|5.2G
```

Model paths in `~/.huxley/config.yaml` use `~` expansion and are resolved at load time.

## Session Lifecycle

```
~/.huxley/
  registry.json           # path → session-id mapping
  config.yaml             # global harness configuration
  models/                 # GGUF model files (Gemma 4, Bonsai fallback, etc.)
  board/                  # Kanban job board (one JSON file per task)
  skills/                 # huxley-specific skills (shadow ~/.agents/skills/)
  scheduler/
    schedules.json        # persistent schedule registry
    history.json          # last-N firings per schedule
  huxleyd.pid             # daemon PID (auto-generated)
  huxleyd.port            # daemon control port
  huxleyd.log             # daemon log output
  boardd.pid              # board web UI PID
  boardd.port             # board web UI port
  boardd.log              # board web UI log
  apfeld.pid              # Apfel PID (only if huxley started it)
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

Each project directory can have a `.huxley` symlink → `~/.huxley/sessions/<uuid>/` for quick reference.

## Daemon (huxleyd)

The background daemon runs the scheduler tick loop and autonomous worker loop. It manages caste lifecycles, ports, and process state.

```bash
# Start huxleyd (background, PID at ~/.huxley/huxleyd.pid)
huxley daemon start

# Check status
huxley daemon status

# Stop gracefully
huxley daemon stop
```

The daemon exposes an HTTP control API on `localhost:8083` by default (`HUXLEYD_PORT`) for internal CLI commands. It stays resident so castes don't need to reload models between invocations.

### OpenAI-Compatible Inference API

When `huxleyd` is running, it also exposes an OpenAI-style inference surface at `http://127.0.0.1:8083/v1` by default (`HUXLEYD_PORT` and `api.localhost_only` are configurable).

```bash
# Start the daemon
huxley daemon start

# Check the API endpoint and exposed models
huxley daemon status
# γ|huxleyd|running|...|openai=http://127.0.0.1:8083/v1|models=gemma-4-e4b,alpha,ternary-bonsai-8b,beta

# List exposed models
curl http://127.0.0.1:8083/v1/models

# Chat with beta
curl http://127.0.0.1:8083/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"beta","messages":[{"role":"user","content":"Summarise this repo in one line."}]}'

# Chat with alpha
curl http://127.0.0.1:8083/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"alpha","messages":[{"role":"user","content":"Plan a refactor for the scheduler."}]}'

# Stream chat chunks from beta
curl -N http://127.0.0.1:8083/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"beta","stream":true,"messages":[{"role":"user","content":"Reply in one short line."}]}'

# Stream chat chunks from alpha
curl -N http://127.0.0.1:8083/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"alpha","stream":true,"messages":[{"role":"user","content":"Reply in one short line."}]}'
```

Current compatibility scope:

- `GET /v1/models`
- `POST /v1/chat/completions`
- both JSON and `stream=true` SSE responses
- exposed model IDs: backend IDs (`gemma-4-e4b`, `ternary-bonsai-8b`) plus aliases such as `alpha` and `beta`
- terminal streaming marker: `data: [DONE]`

Live smoke test against a running daemon:

```bash
# one-shot plus streaming smoke tests
HUXLEY_LIVE_API_TEST=1 python -m unittest test_openai_api_live.py -v
```

## Scheduler

The scheduler runs inside huxleyd — a tick loop (every 5s) that checks the schedule registry and fires due actions. Schedules persist across restarts in `~/.huxley/scheduler/`.

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
huxley schedule list

# Add an interval schedule (post a task to the board every hour)
huxley schedule add --type interval --every 3600 --action post_to_board --level task --title "hourly scan"

# Add a daily schedule
huxley schedule add --type daily_at --at 02:00 --action post_to_board --level epic --title "morning summary"

# View firing history
huxley schedule history

# Remove a schedule
huxley schedule remove <id>
```

## Autonomous Worker Loop

Every tick, the daemon claims pending board tasks and routes them to the correct caste:

- **UNITS** → Gamma (cheap, stateless Apfel inference)
- **TASKS** → Beta (mid-weight Bonsai inference)
- **EPICs** → Alpha (full Gemma 4 orchestration)

The Router is shared across ticks — models stay resident, no reload overhead between inferences.

## Tool Execution

Units posted with the `--tools` flag execute inside a multi-turn tool-calling loop — the model can read, write, edit, and search files during inference to produce better results. The `"tools"` tag propagates through decomposition: EPIC → TASK → UNIT.

```bash
# Post a unit with tool access
huxley board post unit "refactor parser" --tools

# Post an epic that propagates tools to all children
huxley board post epic "build auth system" --tools
```

### Available Tools

| Tool | Description |
|------|-------------|
| `read_file` | Read file contents with optional offset/limit |
| `write_file` | Write content to a file (creates parent dirs) |
| `edit_file` | Find and replace text in an existing file |
| `delete_file` | Delete a file |
| `glob_files` | Match file paths by glob pattern |
| `create_directory` | Create a directory (and parents) |
| `list_directory` | List entries in a directory |
| `grep` | Search file contents by regex |
| `bash` | Run shell commands (disabled by default) |

Filesystem and search tools restrict access to a set of allowed roots: the project root, `~/.huxley/`, and any paths listed under `tools.path_whitelist`. The `bash` tool only restricts the **working directory** to these allowed roots — shell commands can still access arbitrary absolute paths inside the process. To minimise that exposure, keep `shell` disabled unless you explicitly need it.

Skill tool loading (`tools.builtins.skills`) is disabled by default; enable it only for explicitly trusted skill directories.

```yaml
tools:
  enabled: true
  max_turns: 10
  builtins:
    shell: false    # set to true to enable bash (working-dir restricted only)
    skills: false   # set to true to auto-load skill tools from ~/.agents and ~/.huxley
  path_whitelist:
    - /Users/me/my-project
    - /Users/me/.huxley
```

### Tool Flow

```
prompt + tools: True
  → ToolService.run_loop()
    → model responds (text or tool_call)
    → if tool_call: execute handler → append result → loop
    → if max_turns exhausted or text response: return
```

Tool support is currently available for Alpha (Gemma 4 / llama.cpp with `--tool-call`), Beta (llama.cpp), and Gamma (Apfel v1.3.4+ OpenAI-compatible tool mode).

## Apfel Auto-Start

Gamma auto-starts Apfel lazily on the first `infer()` call via `ensure_apfel()`. A PID file at `~/.huxley/apfeld.pid` tracks ownership: if huxley started Apfel, `huxley daemon stop` also kills it. If you started Apfel yourself, it is never touched.

## Swarm (LAN Discovery + Delegation)

Huxleys on the same LAN automatically discover each other via **UDP multicast**. Each running `huxleyd` broadcasts a heartbeat every 30s to `239.255.43.21:43210` and listens for heartbeats from peers. Peers are marked as lost after 90s of silence.

```
┌──────────────────┐        UDP multicast          ┌─────────────────┐
│ huxleyd (M2 Pro) │ ◄───── 239.255.43.21 ───────► │ huxleyd (M5)    │
│ port 8083        │                               │ port 8083       │
│ castes: αβγ      │                               │ castes: αγ      │
└──────────────────┘                               └─────────────────┘
```

Discovery is **zero-config** — no registry, no configuration, no external dependencies. If two daemons are on the same LAN, they find each other automatically.

```bash
# List known LAN peers (requires huxleyd running)
huxley swarm peers
# γ|swarm|peer|●|m2-mini-32gb         |:8083|castes=αβγ|load=0.0|age=12s

# Show swarm status
huxley swarm status
# γ|swarm|status|total=1|active=1
```

The peer table and delegation endpoints are accessible via the daemon control API:

| Endpoint | Description |
|----------|-------------|
| `GET /v1/swarm/peers` | List known LAN peers |
| `GET /v1/swarm/peers/all` | List active and stale peers |
| `GET /v1/swarm/status` | Swarm status (enabled, peer count) |
| `GET /v1/load` | Current in-progress task count for this daemon |
| `POST /v1/units/execute` | Execute a single Gamma unit remotely |
| `POST /v1/tasks/execute` | Execute Beta triage + Gamma units remotely |

### Debugging Connections

When a swarm node can see peers but is not visible to them, break the problem into three layers: daemon health, discovery packets, and host networking.

```bash
# 1. Make sure the daemon is really up
huxley daemon status
huxley swarm status
huxley swarm peers

# 2. Check whether multicast/broadcast works on this host at all
huxley swarm test
# γ|swarm|test|send=True|recv=True|loopback=True

# 3. Force an immediate heartbeat instead of waiting 30s
huxley swarm announce

# 4. Inspect the daemon API locally or from another host
curl http://127.0.0.1:8083/v1/swarm/status
curl http://127.0.0.1:8083/v1/swarm/peers/all
curl http://<peer-ip>:8083/v1/swarm/peers/all
```

What to look for:

1. If `huxley swarm test` shows `loopback=False`, the machine is not receiving its own multicast/broadcast. On macOS this usually means firewall, NECP, VPN, or network-extension interference.
2. If `GET /v1/swarm/status` is healthy but `peers/all` only shows stale entries, the daemon is running but not hearing fresh announcements.
3. If a peer appears immediately after `huxley swarm announce`, the receive path is good and the problem is on the sender's periodic announce path or daemon lifecycle.
4. If other machines can see a node but that node cannot see them, the receive path on that node is the problem. If the node can see others but others never see it, the outbound multicast/broadcast path on that node is the problem.

Common fixes:

1. **Restart the daemon that owns the bad peer table.** Discovery sockets are created by `huxleyd`; if the daemon was started before an interface change, restart it.
2. **Check for stale daemon processes.** If `huxley daemon start` says `ok` but the new code does not seem to be running, verify which process owns port `8083` and UDP port `43210`:

   ```bash
   lsof -nP -iTCP:8083 -sTCP:LISTEN
   lsof -nP -iUDP:43210
   ps -Ao pid=,command= | grep '[h]arness.daemon'
   ```

3. **Watch for extra interfaces.** Tailscale (`utun*`), VM bridges, and other virtual NICs can confuse discovery. Check `ifconfig` and confirm the machine is actually using the LAN address you expect.
4. **Confirm packets leave the real LAN interface.** On macOS, if unicast works but multicast/broadcast does not, capture on `en0` while announcing:

   ```bash
   sudo tcpdump -ni en0 'udp port 43210'
   ```

   If packets do not appear, the host is suppressing outbound discovery. If they appear on `en0` but peers still do not see them, the AP or upstream network is filtering multicast/broadcast.

### Delegation Model

Borrow/lend is implemented today through the daemon HTTP API. A daemon that owns the local board acts as the **leader** and keeps final ownership of the result, but it can push work to idle peers on the LAN.

1. **Peer discovery** populates the active peer table with caste availability and real load.
2. **Task-first delegation**: when Gamma is executing a unit that belongs to a parent task, the scheduler first looks for a `βγ` peer and calls `POST /v1/tasks/execute`.
3. **Unit fallback delegation**: if no suitable `βγ` peer accepts work, the scheduler tries `γ` peers with `POST /v1/units/execute`.
4. **Selection policy**: peers must satisfy the required castes and `load < swarm.delegation.max_load`; eligible peers are selected in `round_robin` order.
5. **Result handling**: remote task execution returns `{task_result, units[]}` and those results are written back onto the leader's local board as completed work.
6. **Local fallback**: if no eligible peer is available, or remote execution fails, execution continues locally.

The current implementation is deliberately simple: LAN-only, no registry, no task-scoped auth tokens, and no remote board claiming. Delegation is request/response over the daemon API rather than a separate borrow contract.

#### Remote execution payloads

`POST /v1/units/execute`

```json
{"prompt":"Summarise the parser edge cases"}
```

Response:

```json
{"result":"..."}
```

`POST /v1/tasks/execute`

```json
{"title":"Implement parser fixes","prompt":"Fix the parser and explain the changes"}
```

Response:

```json
{
  "task_result":"## Step 1\n...\n\n## Step 2\n...",
  "units":[
    {"title":"Step 1","result":"..."},
    {"title":"Step 2","result":"..."}
  ]
}
```

### Config

```yaml
swarm:
  enabled: true
  multicast_group: 239.255.43.21
  multicast_port: 43210
  announce_interval: 30
  stale_timeout: 90
  delegation:
    enabled: true
    max_load: 5
    selection: round_robin
```

### Roadmap (future)

- **Delegation hardening**: Add auth, trust, and policy controls around remote execution
- **Idle consensus**: When all local EPICs are done and peers are idle, form distributed daydream sessions
- **Auth tokens**: Per-task authentication for remote board access

## Session Journal & Compaction

Every caste writes an append-only JSONL journal per session at `~/.huxley/sessions/<sid>/<caste>/journal.jsonl`. Journals survive crashes (corrupt trailing lines are skipped on read).

When a journal exceeds 30 entries, the caste auto-compacts: it self-summarises the middle portion into a system message, preserving the first 2 turns and the last 10 verbatim. The rewrite reduces token waste while retaining conversational context.

```bash
# Manual compaction (uses Beta by default)
huxley compact --caste b
```

## Requirements

- **macOS 26+** (Tahoe) for Apfel / Apple Foundation Model
- **Apple Silicon** (M1+)
- **Python 3.11+**
- **Apfel** — `brew install apfel` (for Gamma caste)
- **llama-cpp-python** for Beta caste
- **Optional**: llama.cpp with Gemma 4 GGUF + TurboQuant for Alpha caste

## Installation

```bash
# Clone the repository
git clone git@github.com:PeteHaughie/Huxley.git
cd Huxley

# Install the package and all dependencies
pip install -e .

# (Optional) Start Apfel for Gamma caste
apfel --serve

# Initialise the harness
huxley init
```

## Uninstall

```bash
# Stop background services first
huxley daemon stop
huxley board serve stop

# Remove the Python package
pip uninstall huxley

# Remove the project session symlink
rm -f .huxley

# (Optional) Remove all Huxley runtime data
rm -rf ~/.huxley

# (Optional) Remove the source checkout
cd ..
rm -rf Huxley
```

## Quick Start

```bash
# Show version
huxley --version

# Initialise a session in the current directory
huxley init

# Show current session info
huxley session

# List available skills (from ~/.agents/skills/ + ~/.huxley/skills/)
huxley skills

# List all harness modules
huxley modules

# Discover harness API surface
huxley api

# Route a prompt through Gamma caste (requires apfel --serve)
huxley infer γ "extract all email addresses from this text"

# Route a prompt through Beta caste (requires llama-cpp-python)
huxley infer β "summarise the key points"

# Route a prompt through Alpha caste (requires llama.cpp + Gemma 4)
huxley infer α "what should I work on next?"

# Route through cloud endpoint (requires cloud config)
huxley cloud "explain quantum computing"

# Dry-run a self-mod patch (pipe new content via stdin)
echo "..." | huxley patch harness/cli.py

# Apply a self-mod patch (pipe new content via stdin)
echo "..." | huxley patch --apply harness/config.py

# Post a patch diff + validator report to the board for review
echo "..." | huxley patch --review harness/daemon/scheduler.py

# List existing patches
huxley patch --list

# Rollback a patch by ID
huxley patch --rollback <patch_id>
```

## Adversarial Dev Mode

`huxley adev` runs a multi-round adversarial development loop — a **Programmer** implements a task, a **Roaster** reviews the code, and an **Adjudicator** breaks ties when the review budget is exhausted.

```
Round 1: Programmer implements → Roaster reviews (DENIED → issues)
Round 2: Programmer revises   → Roaster reviews (APPROVED → done)
         ─ or ─
Round N: Adjudicator breaks tie after max rounds
```

```bash
# Basic adev session
huxley adev "add user authentication to the API"

# Control review rounds
huxley adev "fix the memory leak" --rounds 10

# Point at a specific directory
huxley adev "refactor the scheduler" --workdir /path/to/project

# Assign higher-tier castes for more nuanced reviews
huxley adev "design the data model" \
  --programmer-caste gamma \
  --roaster-caste alpha \
  --adjudicator-caste alpha
```

### Roles

| Role | Default Caste | Tools | What it does |
|------|---------------|-------|-------------|
| Programmer | Gamma (γ) | ✅ | Reads codebase, implements the task, writes files |
| Roaster | Gamma (γ) | ✅ | Reviews code, inspects files, denies with issues |
| Adjudicator | Alpha (α) | ❌ | Final decision after round budget is exhausted |

Any caste can be assigned to any role via `--*-caste` flags. Using Alpha as the roaster produces deeper, more critical reviews at higher token cost.

### Loop

```
  Programmer ──write──→ Roaster ──approve──→ done
                  ↑                  │
                  │                  ↓
                  └──── revise ── deny ──→ max rounds → Adjudicator
```

The engine accepts a pluggable `delegate` callable for swarm-aware execution — adev rounds can run across LAN peers instead of locally.

## Commands

### General

| Command | Description |
|---------|-------------|
| `huxley --version` | Print version |
| `huxley init` | Initialise .huxley session in directory |
| `huxley session` | Show current session info |
| `huxley skills` | List available skills from both skill directories |
| `huxley infer <caste> <prompt>` | Route prompt through a caste (α, β, or γ) |
| `huxley api` | List all functions and classes across harness modules |
| `huxley modules` | List all harness modules |
| `huxley models` | List GGUF models in `~/.huxley/models/` |
| `huxley cloud <prompt>` | Route prompt via cloud endpoint |
| `huxley patch --list` | List known patches/backups |
| `huxley patch --rollback <id>` | Roll back a patch by ID |
| `echo "..." \| huxley patch [--apply\|--review] <file>` | Create, apply, or review a self-mod patch using stdin content |
| `huxley compact [--caste]` | Compact session journal via summarisation |
| `huxley daemon start\|stop\|status` | Manage huxley background daemon |
| `huxley schedule list\|add\|remove\|history` | Manage scheduled tasks |
| `huxley swarm peers\|status\|test\|announce` | LAN peer discovery, diagnostics, and manual announce |
| `huxley adev <task> [--rounds] [--workdir] [--*-caste]` | Run adversarial dev loop |

### Board (Kanban Job Queue)

| Command | Description |
|---------|-------------|
| `huxley board list [--level] [--state]` | List tasks, optionally filtered |
| `huxley board post <level> <title> [--tools]` | Post a new task (epic/task/unit) with optional tool access |
| `huxley board show <task-id>` | Show full task details |
| `huxley board claim <level> --caste <caste>` | Pull next available task into in_progress |
| `huxley board complete <task-id> [--result]` | Mark task as done with result |
| `huxley board delete <task-id>` | Delete a task from the board |
| `huxley board serve start [--port]` | Start Kanban web UI daemon (default 8080) |
| `huxley board serve stop` | Stop board daemon |
| `huxley board serve status` | Check board daemon status |

### Daemon (huxleyd)

| Command | Description |
|---------|-------------|
| `huxley daemon start` | Start huxleyd in background |
| `huxley daemon stop` | Stop huxleyd |
| `huxley daemon status` | Check if huxleyd is running |

### Scheduler

| Command | Description |
|---------|-------------|
| `huxley schedule list` | List all schedules |
| `huxley schedule add <type> <interval/daily_at>` | Add a schedule |
| `huxley schedule remove <id>` | Remove a schedule |
| `huxley schedule history [<id>]` | View firing history |

### Compaction

| Command | Description |
|---------|-------------|
| `huxley compact [--caste]` | Compact session journal via summarisation |

## Configuration

`~/.huxley/config.yaml` is auto-generated on first `huxley init`:

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
  model: ~/.huxley/models/Bonsai-8B.gguf
  ctx_size: 65536

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

1. **`~/.huxley/skills/`** — Huxley-specific skills (highest priority)
2. **`~/.agents/skills/`** — Generic shared skills (compatible with other agent frameworks)

If the same skill name exists in both, the huxley version wins. This prevents huxley-specific skills (which may depend on harness architecture) from polluting the shared `~/.agents/` namespace.

Optional local planning scratchpads can live at `~/.huxley/ISSUES.md` and `~/.huxley/IDEAS.md` (see the repo-root `ISSUES.md` and `IDEAS.md` templates). They capture current pain points and future ideas that an agent can consult when choosing or planning follow-up work, without requiring personal notes to be committed in the repository.

### Skill Format

```
~/.huxley/skills/<skill-name>/SKILL.md
```

Each skill is a markdown file with YAML frontmatter:

```markdown
---
name: my-huxley-skill
description: What this skill does
---

Skill instructions and system prompts...
```

## Self-Modification

The harness can read, patch, and hot-reload its own source code:

- **Introspection** (`harness/selfmod/introspect.py`): AST-based API surface discovery. Maps all modules, classes, functions with line numbers.
- **Patcher** (`harness/selfmod/patcher.py`): Diff generation, dry-run, apply with backup, rollback. Patches stored in `~/.huxley/patches/`.
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
Huxley/
├── harness/
│   ├── __init__.py          # Package version
│   ├── __main__.py          # python -m harness
│   ├── cli.py               # Entry point with 16+ commands
│   ├── config.py            # YAML config, ~/.huxley/ bootstrap
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
│   │   ├── beta.py          # Bonsai Ternary / llama.cpp integration
│   │   └── alpha.py         # Gemma 4 / llama.cpp integration
│   ├── comms/
│   │   ├── __init__.py
│   │   ├── message.py       # Structured JSON protocol (Message, Caste, Action, ContextHint)
│   │   └── router.py        # Caste message dispatcher (shared across ticks)
│   ├── daemon/
│   │   ├── __init__.py
│   │   ├── lifecycle.py     # huxleyd start/stop/status
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
│   │   ├── loader.py        # Dual-path skill loader (huxley + agents)
│   │   └── registry.py      # Cached skill registry
│   ├── cloud/
│   │   ├── __init__.py
│   │   ├── endpoint.py      # OpenAI-compatible cloud client
│   │   └── router.py        # Cloud routing
│   ├── swarm/
│   │   ├── __init__.py
│   │   ├── peer.py          # Peer table with TTL-based staleness
│   │   └── discovery.py     # UDP multicast discovery service
│   ├── tool/
│   │   ├── __init__.py
│   │   ├── decorator.py     # @tool() decorator, JSON Schema generation
│   │   ├── registry.py      # Built-in + skill tool loading
│   │   ├── engine.py        # ToolService run_loop (multi-turn tool calling)
│   │   └── builtins/
│   │       ├── __init__.py
│   │       ├── filesystem.py # read/write/edit/delete/glob/listdir/create
│   │       ├── search.py     # grep
│   │       └── shell.py      # bash (disabled by default)
│   ├── adev/
│   │   ├── __init__.py
│   │   └── engine.py        # AdversarialDevEngine (Programmer/Roaster/Adjudicator loop)
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
