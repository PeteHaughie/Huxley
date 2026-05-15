# Swarm Project Execution Plan

## Tech Stack
- Python 3.13 stdlib: `http.server` (daemon HTTP), `json`, `threading`, `urllib.request`
- Existing Router from `harness.comms.router` for inference dispatch
- Existing `PeerTable` from `harness.swarm.peer` for peer selection
- Existing `JobBoard` for local task state
- No new dependencies

## Architecture

The Project-Leader model: the daemon that owns an epic acts as leader. It distributes units of work to swarm peers and collects results back onto its local board.

### New daemon HTTP endpoints (`server.py`)

| Method | Path | Request Body | Response | Purpose |
|---|---|---|---|---|
| `POST` | `/v1/units/execute` | `{"prompt": "..."}` | `{"result": "..."}` | Run Gamma inference for a single unit |
| `POST` | `/v1/tasks/execute` | `{"title": "...", "prompt": "..."}` | `{"task_result": "...", "units": [{"title": "...", "result": "..."}]}` | Run Beta triage + Gamma for all units |
| `GET` | `/v1/load` | — | `{"load": 3}` | Current IN_PROGRESS task count |

### Peer selection flow (`scheduler.py`)

```
_gamma_execute(task, board):
    1. Query peer_table.list_active()
    2. Filter by caste capability (β+γ first, then γ-only)
    3. Sort by load, pick lowest
    4. POST to peer endpoint
    5. On success: write results to local board as DONE
    6. On failure: fall back to local execution
```

### Load tracking (`discovery.py`)

Replace hardcoded `load=0.0` in `_build_announce` with a real computation:
- Count of `board.list(state=State.IN_PROGRESS)` across all levels
- If board access fails, use `0.0` as fallback

### Files changed

| File | Change |
|---|---|
| `harness/daemon/server.py` | Add 3 new endpoint handlers |
| `harness/daemon/scheduler.py` | Add delegation logic, remote inference helper |
| `harness/swarm/discovery.py` | Compute and announce real load |
| `harness/config.py` | Add `swarm.delegation` config section |
| `harness/comms/remote.py` | New — `post_to_peer()` HTTP helper for daemon-to-daemon calls |

### Data flow

```
Leader                              Worker
  │                                    │
  ├── Alpha breakdown (local)          │
  ├── For each TASK:                   │
  │   ├── query peer table             │
  │   ├── POST /v1/tasks/execute ─────→│
  │   │                                 ├── Beta triage (local infer)
  │   │                                 ├── For each UNIT:
  │   │                                 │   └── Gamma execute (local infer)
  │   │                                 ├── Compile results
  │   │◀── { task_result, units } ─────┤
  │   ├── Write board entries (DONE)    │
  │   └── Beta review (local)          │
  ├── Escalation check (local)          │
  ├── Archive project (local)           │
  └── Compile project files (local)     │
```
