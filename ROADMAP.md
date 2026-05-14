# 1BitMonster — Roadmap

Exploratory ideas and future directions beyond the initial implementation.

---

## 1. Monster as Service (monsterd)

**Goal**: Run harness as a persistent background daemon.

- launchd plist at `~/Library/LaunchAgents/com.monster.harness.plist`
- Low idle footprint — Alpha resident, Gammas/Betas spawned on-demand
- API endpoint: Unix domain socket or `localhost:0` dynamic port
- `monsterctl` CLI: `monsterctl ask`, `monsterctl status`, `monsterctl tail`
- Graceful shutdown saves `~/.monster/sessions/` state
- Resource cgroups via launchd (low-priority I/O, CPU throttling when idle)

**Why**: Session persistence works. Next step is making it always-on so you can `monsterctl ask` from any terminal without waiting for model load.

---

## 2. Session Archaeology (Curiosity Engine)

**Goal**: Harness examines past sessions for recurring themes and offers new skills.

- Background thread scans `~/.monster/registry.json` → enumerates all sessions
- Reads each session's `meta.json` → builds topic maps, intent clusters
- Cheap embedding via Gamma (Apfel, 4096 ctx) → stores in Chroma
- Cluster analysis: "user asks about X on Mondays" → suggests `skill_load`
- Output: ranked pattern list → Alpha receives as actionable hints

**Why**: Harness gets proactively useful instead of purely reactive. Discovers gaps in its own skill set.

---

## 3. Daydreaming (Background Efficiency Research)

**Goal**: Harness continuously investigates ways to improve itself — models, quantization, frameworks — all at the edge. As befits the role of the ruling class only Alphas can afford to dream.

### Pipeline

**Discovery** (Gamma — high volume, cheap):
- Scrape: Hacker News, r/LocalLLaMA, Hugging Face papers, GitHub trending ML
- Track: `quantization`, `macOS inference`, `llama.cpp fork`, `new 1.58bit model`, `MTP`, `speculative decoding`
- Filter: deduplicate, coarse relevance scoring

**Evaluation** (Beta — moderate):
- Digest promising finds → structured reports: `{source, claim, evidence, relevance_score}`  
- Cross-ref against current harness config → compute improvement delta
- Classify: `new_model`, `quant_method`, `framework`, `tool`, `skill_pattern`

**Ratification** (Alpha — occasional, deliberate):
- Weekly lightweight "daydream" session: review candidate improvements
- Decision: `ignore` / `file_for_later` / `generate_patch` / `write_skill`
- Approved items → self-mod pipeline (see Phase H)

### Constraints
- Never preempts active work — uses `nice` / low-priority scheduling
- Strict token budget per daydream cycle (e.g., 10K tok/hr max)
- Explicit opt-in flag in config: `harness.daydream: true`

**Why**: Manual model/quant research is tedious. Let the harness do it. It has the context and the incentive.

---

## 4. Monster Collective (Central Skill Registry)

**Goal**: Formally tested skills shared across monster instances.

### Infrastructure

- Git-backed registry repo: `github.com/1bitmonster/registry`
- Manifest format per skill:
  ```yaml
  name: monster-caveman
  version: 1.2.0
  description: Caveman communication protocol for inter-caste messages
  hash: sha256:...
  tests: passed (6/6)
  dependencies: []
  author: monster/hash-abc123
  ```

### Commands

| Command | Action |
|---------|--------|
| `monster skill search <query>` | Semantic search via registry index |
| `monster skill pull <name>` | Download + validate hash + install to `~/.monster/skills/` |
| `monster skill push <name>` | Run test suite, submit from `~/.monster/skills/` |
| `monster skill update` | Pull all outdated skills with passing tests |

### Quality Gate

Before `push`: skill must pass harness test harness (`monster test <skill>`). No passing tests = no submission.

**Why**: Avoid walled-garden. If one monster finds a better way to quant or route or prompt, every monster benefits.

---

## 5. Monster Swarm (Distributed Caste Network)

**Goal**: Monsters on the same LAN discover each other and lend idle β/γ capacity. Idle swarms can confer on problems during quiet time.

### Network Discovery

- **mDNS/Bonjour** — each monster advertises `_monster._tcp` on startup
- Service record contains: `{caste, engine, load, capacity, arch}`
- Poll loop: scan LAN every 30s for new/vanished peers
- No central registry — fully peer-to-peer discovery

```
# monster peers
γ|peers|online|2
γ|peers|m2-mini-32gb|arm64|α+β|idle  ← offered by remote α
γ|peers|m5-wife|arm64|α+γ|busy     ← denied
```

### Distributed Pull Model

When local α has backlogged EPICs and insufficient β/γ:

1. α checks peer table for idle remote β/γ
2. Sends `borrow_request{caste, task_id, token_budget}` via **ZeroMQ** PUB/SUB
3. Remote α evaluates: `load < capacity AND opt_in_help == true`
4. Response: `borrow_accept{endpoint, auth_token}` or `borrow_deny{reason}`
5. Local β/γ connects to remote's board (or receives forwarded tasks)
6. Results flow back through ZMQ pipeline

```
Local α ──borrow_request──→ Remote α
Local α ←──borrow_accept─── Remote α
Local β ─────pull task─────→ Remote Board (via ZMQ)
Local β ←───push result──── Remote Board
Remote α ──task_complete──→ Local α (via ZMQ)
```

### Messaging Layer

| Layer | Protocol | Why |
|-------|----------|-----|
| Discovery | mDNS/Bonjour | Zero-config, built into macOS |
| Control | ZeroMQ PUB/SUB (TCP) | Fast, no broker needed, language-agnostic |
| Task data | ZeroMQ PUSH/PULL or REQ/REP | Binary-safe, streaming-capable |

ZeroMQ over RabbitMQ: simpler deployment (no broker daemon), lower latency for small messages, native pub/sub + pipeline patterns.

### Auth & Trust

- Per-session tokens (UUID4) exchanged on borrow_accept
- Token scoped to one task — revoked on complete or timeout
- All ZMQ traffic over local subnet only (no WAN routing)
- Opt-in config: `swarm.enabled: false`, `swarm.duty_bound: true`
- `duty_bound: true` = α must help when idle unless explicitly denied
- `duty_bound: false` = α decides per-request

### Idle-Time Consensus

When α detects all local EPICs are done and peers are idle:

1. α pings peer α's with `idle_proposal{topic, skill_slot}`
2. If ≥2 peers accept → session forms around the topic
3. Each α runs daydream loops, shares findings via ZMQ
4. Results: new skills, config patches, research summaries
5. On any peer going busy → session disbands gracefully

**Why**: You have an M1 Pro (16GB), M2 Pro (16GB), M2 Mini (32GB), M5 (32GB) all on the same network. That's 96GB of aggregate inference capacity. Idle time on those machines could produce new skills, explore quant methods, or chip away at hard problems — all without touching your main session.

---

## Implementation Priority

1. **monsterd** — unlocks always-on, which makes everything else viable
2. **Daydreaming (Discovery only)** — cheap, passive, feeds curiosity engine
3. **Session Archaeology** — needs data from monsterd running for a while
4. **Monster Swarm** — needs monsterd + ZeroMQ, unlocks remote compute
5. **Daydreaming (Full pipeline)** — needs archaeology + swarm for distributed compute
6. **Monster Collective** — needs at least 2+ monsters and 1 ratified skill
