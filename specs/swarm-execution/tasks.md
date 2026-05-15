# Tasks: Swarm Project Execution

## Phase 1: Setup & Foundation

- [X] T001 Add `swarm.delegation` config section to `harness/config.py` with `enabled` (default: true) and `max_load` (default: 5) fields
- [X] T002 [P] Create `harness/comms/remote.py` with a `post_to_peer(addr, port, path, body, timeout=30)` helper that performs HTTP POST to a peer daemon and returns parsed JSON response, with error handling for connection failures and timeouts

## Phase 2: Worker API — Remote Execution Endpoints

- [X] T003 Add `GET /v1/load` handler to `DaemonHandler` in `harness/daemon/server.py` that returns `{"load": N}` where N is the count of IN_PROGRESS tasks on the local board
- [X] T004 Add `POST /v1/units/execute` handler to `DaemonHandler` in `harness/daemon/server.py` that accepts `{"prompt": "..."}`, runs Gamma inference via `_scheduler.infer()`, returns `{"result": "..."}`
- [X] T005 Add `POST /v1/tasks/execute` handler to `DaemonHandler` in `harness/daemon/server.py` that accepts `{"title": "...", "prompt": "..."}`, runs Beta triage + Gamma execution on all resulting units via `_scheduler.execute_task()`, returns `{"task_result": "...", "units": [{"title": "...", "result": "..."}]}`

## Phase 3: [US1] Remote Unit Execution (P1)

- [X] T006 Compute and announce real load in `harness/swarm/discovery.py:_announce_all` — count IN_PROGRESS tasks from the local board instead of hardcoded `0.0`, with fallback to `0.0` if board access fails
- [X] T007 Modify `_gamma_execute` in `harness/daemon/scheduler.py` to check the peer table for idle γ-capable peers before executing locally:
  - Filter `_peer_table.list_active()` for peers with `γ` in `castes` and `load < config.max_load`
  - If found, `POST /v1/units/execute` to the lowest-load peer
  - On success: `board.complete(task.id, resp["result"])`
  - On failure: fall back to local inference

## Phase 4: [US2] Remote Task Execution (P2)

- [X] T008 Add peer selection helper `_select_peer(required_castes, max_load)` in `harness/daemon/scheduler.py` that filters `_peer_table.list_active()` by caste requirement and load, returns the lowest-load peer key `"addr:port"` or `None`
- [X] T009 Modify the delegation path in `_gamma_execute` to prefer β+γ peers for full task execution:
  - First try `_select_peer("βγ")` and `POST /v1/tasks/execute` on the parent task
  - On success: delete existing children, mark parent DONE with `task_result`, create unit entries for each returned unit as DONE
  - On failure: fall back to γ-only peer path (T007)
- [X] T010 Add delegation metrics logging in `harness/daemon/scheduler.py` — log `γ|worker|delegate|{peer}|{task_id[:8]}|{mode}` (mode = "task" or "unit") and `γ|worker|delegate_fallback|{task_id[:8]}|local` when no peer available

## Dependencies

```
T001 ──→ T003 ──→ T006 ──→ T007 ──→ T009
                              ↑
T002 ──→ T004 ──→ T007       │
      ──→ T005 ──→ T009 ─────┘
                              │
                        T008 ─┘
                              │
                        T010 ─┘
```

## Parallel Execution Examples

```
Wave 1: T001 + T002                    (setup — independent)
Wave 2: T003 + T004 + T005             (worker API — independent)
Wave 3: T006 + T007 + T008             (US1 core + helper)
Wave 4: T009 + T010                    (US2 + polish)
```

## User Story Test Criteria

**US1**: Post a unit prompt to a peer's `POST /v1/units/execute` endpoint, verify result contains `"result"` key with non-empty string. Verify scheduler delegates to a peer when one is available and falls back to local when none exists.

**US2**: Post a task to a peer's `POST /v1/tasks/execute` endpoint, verify response contains both `"task_result"` and `"units"` array. Verify scheduler prefers β+γ peers over γ-only peers.
