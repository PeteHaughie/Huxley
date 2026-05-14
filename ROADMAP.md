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

**Goal**: Harness continuously investigates ways to improve itself — models, quantization, frameworks — all at the edge.

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

## Implementation Priority

1. **monsterd** — unlocks always-on, which makes everything else viable
2. **Daydreaming (Discovery only)** — cheap, passive, feeds curiosity engine
3. **Session Archaeology** — needs data from monsterd running for a while
4. **Daydreaming (Full pipeline)** — needs archaeology to close the loop
5. **Monster Collective** — needs at least 2+ monsters and 1 ratified skill
