# Swarm Project Execution

Distribute Beta triage and Gamma execution to idle swarm peers using a Project-Leader model. The leader (epic owner) breaks down epics locally, then pushes tasks/units to remote peers for execution, collects results, and compiles the final project.

## User Stories

### US1 — Remote Unit Execution (P1)
As a daemon, I want to push individual Gamma units to idle swarm peers so that unit execution is distributed across available compute.

**Acceptance criteria:**
- `POST /v1/units/execute` endpoint on each daemon accepts `{ "prompt": "..." }`, runs Gamma inference, returns `{ "result": "..." }`
- `GET /v1/load` endpoint returns the number of IN_PROGRESS tasks
- Swarm announcements broadcast real load (not hardcoded `0.0`)
- `_gamma_execute` checks peer table for idle γ-capable peers before executing locally
- Falls back to local execution if no peers available or remote call fails
- Config toggle `swarm.delegation.enabled` (default: true)

### US2 — Remote Task Execution (P2)
As a daemon, I want to push entire tasks (Beta triage + Gamma execution) to idle swarm peers so that both planning and execution run remotely.

**Acceptance criteria:**
- `POST /v1/tasks/execute` endpoint on each daemon accepts `{ "title": "...", "prompt": "..." }`, runs Beta triage → Gamma execution on all units, returns `{ "task_result": "...", "units": [...] }`
- Scheduler prefers β+γ peers before falling back to γ-only or local execution
- Received results are written to the leader's board as DONE tasks/units
- Config `swarm.delegation.max_load` controls peer selection threshold
