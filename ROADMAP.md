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

## 2. Monster Scheduler (Time-Aware Tick Loop)

**Goal**: In-process scheduler within monsterd that triggers actions based on time, idle detection, and board state — without touching the host crontab or requiring external scripts.

The scheduler is not a separate daemon. It is a loop inside monsterd's async event loop. It wakes every N seconds, checks what's due, and posts tasks to the board or triggers α actions directly.

### Architecture

```
monsterd event loop
    │
    ├── tick loop (every 5s by default)
    │       │
    │       ├── check schedule registry → fire due entries
    │       ├── check board state → fire idle/backlog triggers
    │       └── check peer table → fire swarm maintenance
    │
    ├── board (pull queue)
    ├── α/β/γ castes
    └── registry API client
```

The scheduler is a **producer for the board**. When a tick fires, it creates a board entry. Castes claim it via the normal pull model. No caste needs to know about time — they only see board entries.

### Schedule Storage

`~/.monster/scheduler/` — one JSON file per scheduled task, survives restarts and machine reboots:

```
~/.monster/scheduler/
  schedules.json         # all schedules (index)
  history.json           # last-N firings per schedule (for audit)
```

Each schedule:

```json
{
  "id": "sched-abc123",
  "when": {
    "type": "interval",
    "every": 3600,
    "unit": "seconds"
  },
  "action": {
    "type": "post_to_board",
    "level": "task",
    "title": "daily archaeology scan",
    "prompt": "scan ~/.monster/sessions/ for patterns"
  },
  "state": {
    "enabled": true,
    "last_fired": "2026-05-14T14:00:00Z",
    "next_fire": "2026-05-14T15:00:00Z",
    "missed_behaviour": "skip"
  }
}
```

### Trigger Types

| Type | Syntax | Example |
|------|--------|---------|
| `interval` | Every N seconds/minutes/hours | every 3600s |
| `daily_at` | Specific wall-clock time | 02:00 daily |
| `cron` | Standard cron expression | `0 2 * * 1` (weekly Monday 2am) |
| `idle` | After N time with empty board | No EPICs for 1 hour → enter daydream |
| `backlog` | When backlog exceeds threshold | >5 backlogged EPICs → trigger β |
| `condition` | Arbitrary boolean expression | `peers_online > 0 && board_empty` |
| `window` | Active time window | Only between 22:00-06:00 (quiet hours) |

`idle` and `backlog` are hybrid triggers — they check both time AND board state. This is what makes the scheduler monster-aware rather than a dumb timer.

### Action Types

| Action | Effect | Example Use |
|--------|--------|-------------|
| `post_to_board` | Creates board entry with level/title/prompt | "Run daily archaeology scan" → β picks it up |
| `trigger_alpha` | Direct α invocation (bypasses board, for fast path) | Log rotation, health check, swarm peer scan |
| `run_skill` | Execute installed skill with parameters | `monster-caveman` on recent session data |
| `self_mod` | Internal maintenance task | Archive old sessions, rotate scheduler history |

`post_to_board` is the default and preferred path — it keeps the pull model intact.

### Idle Detection (The Daydream Gate)

The scheduler's most important non-trivial trigger is `idle`:

```
condition: no EPICs in state {backlog, ready, in_progress} for ≥3600s
action:    post_to_board(level=epic, title="daydream cycle")
```

When the α claims this epic:
1. α checks config: `harness.daydream: true` and `harness.quiet_hours: 22:00-06:00`
2. If outside quiet hours and daydream is enabled → α runs a daydream loop
3. If swarm peers are idle → α can propose a collaborative session
4. If daydream is disabled → α marks the epic as `blocked` with reason "daydream disabled"

The idle trigger is **not a timer** — it's a board-state check that happens every tick. If the board gets busy mid-cycle, the trigger condition is no longer met and nothing fires.

### Timezone and Portability

- All schedules store `next_fire` in UTC
- `daily_at` and `cron` resolve to UTC internally but accept local timezone (read from system `TZ` or config `harness.timezone`)
- No dependency on system `cron` or `launchd` timers
- Works identically on macOS, Linux, and any other POSIX host

### Missed Ticks (Downtime Recovery)

When monsterd restarts after being down, the scheduler checks `last_fired` against current time:

| `missed_behaviour` | What happens |
|--------------------|--------------|
| `skip` (default) | Missed ticks are ignored. Next fire at regular interval from now. |
| `catch_up` | Fire once immediately, then resume normal schedule. Use for critical maintenance (log rotation). |
| `fire_once` | Fire if downtime exceeded the interval, then reset. Use for daily tasks ("did archaeology run today?"). |

Persistent schedules mean the scheduler is stateful — it survives reboots without manual re-registration.

### Commands

```
monsterctl schedule list              # view all schedules
monsterctl schedule add <type> ...    # add a schedule (e.g. --every 3600 --action post_to_board ...)
monsterctl schedule remove <id>       # delete a schedule
monsterctl schedule pause <id>        # temporarily disable without deleting
monsterctl schedule history <id>      # view last-N firings
```

The α can also autonomously register schedules:

```
α detects: "user summarises session every morning at 9am → I'll create a daily schedule"
α posts:   schedule_add{every: 86400, action: post_to_board, title: "morning summarisation"}
```

The α never needs human permission to add a schedule — it's a board entry like any other. The human can delete or pause it via `monsterctl schedule`.

### Scheduler vs. Board Relationship

```
scheduler fires ──→ post_to_board ──→ castes claim (pull model)
                                       ↑
                              human can also post here
```

The scheduler is one producer among many. The board doesn't know or care whether a task came from a timer, a human, or another α. This keeps the caste model clean — no caste needs a clock.

**Why**: crontab is wrong for this. It's host-invasive (pollutes system namespace), stateless (can't check board state), and has no concept of monster's internal condition (idle, backlog, peer presence). An in-process tick loop that speaks board protocol gives monsterd autonomous timing without external dependencies.

---

## 3. Session Archaeology (Curiosity Engine)

**Goal**: Harness examines past sessions for recurring themes and offers new skills.

- Background thread scans `~/.monster/registry.json` → enumerates all sessions
- Reads each session's `meta.json` → builds topic maps, intent clusters
- Cheap embedding via Gamma (Apfel, 4096 ctx) → stores in Chroma
- Cluster analysis: "user asks about X on Mondays" → suggests `skill_load`
- Output: ranked pattern list → Alpha receives as actionable hints

**Why**: Harness gets proactively useful instead of purely reactive. Discovers gaps in its own skill set.

---

## 4. Daydreaming (Background Efficiency Research)

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

## 5. Monster Collective (Trusted Skill Registry)

**Goal**: Formally tested skills shared across monster instances — without becoming a malware distribution pipeline.

The Claude Code skills incident proved that any community skill system without strong provenance is a supply-chain weapon. The Collective is designed from the ground up to prevent that.

### Trust Model

Monsters run real inference sessions. That's expensive to fake and creates a natural Sybil barrier. The trust model layers this with cryptographic identity, peer vouching, and graduated access:

```
Layer 1: Instance Identity     (who you are)
Layer 2: Birth Certificate     (proof you're a real machine)
Layer 3: Peer Vouching         (swarm says you're legit)
Layer 4: Submission Proof      (skill came from a real alpha)
Layer 5: Sandbox Verification  (skill does what it says)
Layer 6: Graduated Namespace   (staging → stable on ratification)
```

### Layer 1 — Instance Identity

- Each monster generates an Ed25519 keypair on first `monster collective join`
- Public key = persistent identity: `monster:ed25519:ABC123...`
- Private key stored in `~/.monster/identity.ecdsa`, optionally backed by **Secure Enclave** (`SecureEnclave.SecKeyCreateRandomKey` on Apple Silicon)
- Hardware-bound: Secure Enclave keys cannot be exported — identity is literally tied to the machine

### Layer 2 — Birth Certificate

On first join, the instance submits a hardware attestation:

```json
{
  "public_key": "monster:ed25519:ABC123...",
  "hardware": {
    "uuid": "F47AC10B-58CC-4372-A567-0E02B2C3D479",
    "model": "Mac15,9",
    "arch": "arm64e",
    "cores": 12,
    "ram_gb": 32
  },
  "nonce": "random-uuid",
  "signature": "signed(public_key + hardware + nonce)"
}
```

A trusted peer (or the registry, for early days) verifies the UUID format and model string match real Apple Silicon patterns. On approval, a birth certificate is issued — signed by **3 peer monsters** (after swarm exists) or by the registry bootstrap key.

An un-certificated instance can pull skills but cannot push them.

### Layer 3 — Peer Vouching

After swarm networking exists, new instances must be vouched for:

1. New α sends `vouch_request{public_key, birth_cert}` to known peers via ZMQ
2. Peers verify birth certificate, then run a challenge-response: `alpha sign(nonce)` → verify with public key
3. If ≥3 peers vouch, the instance is `ratified` — full push access
4. Vouching is transitive risk: if a vouched instance pushes malware, the vouchers lose reputation

Reputation score per identity:
- Starts at 0 for new, certificated instances
- +10 per successful push that survives 30 days without being flagged
- -50 per push that is later flagged and confirmed malicious
- -100 if vouched-for instance pushes malware (negligent vouching)
- Vouchers with rep < 0 cannot vouch for others

### Layer 4 — Submission Proof

On `monster skill push`, the local α generates a proof that this submission came from a real monster session:

```yaml
name: monster-caveman
version: 1.2.0
hash: sha256:e3b0c44...
dependencies: []
author: monster:ed25519:ABC123...

provenance:
  signature: signed(hash + timestamp + session_id)
  session_id: "550e8400-e29b-41d4-a716-446655440000"
  timestamp: 2026-05-14T15:00:00Z
```

The registry verifies:
1. **Identity** — signature matches a known, certificated, non-revoked public key
2. **Session proof** — `session_id` corresponds to a real `~/.monster/sessions/<uuid>/` directory with valid `meta.json` (created before timestamp, minimum session duration implied by real inference)
3. **Freshness** — timestamp is within the last hour (prevents replay)
4. **No duplicates** — hash not already submitted (prevents re-pushing other people's skills)

Cost to forge: an attacker must run a real monster alpha session (with actual model inference) to generate a valid session. Mass registration becomes uneconomical.

### Layer 5 — Sandbox Verification

Before a submission is accepted, the registry runs it through sandboxed test execution. On the submitting machine (`monster skill push` runs locally first), and optionally on the registry CI:

- **`sandbox-exec`** (macOS Seatbelt sandbox) — no network, read-only `/usr` and `/System`, write allowed only to a temp directory
- **Manifest must declare all capabilities**:
  ```yaml
  sandbox:
    network: false
    read_paths:
      - /tmp/monster-test/**
    write_paths: []
    max_cpu_secs: 30
    max_ram_mb: 512
  ```
- If any capability is undeclared but used → test fails, submission rejected, -10 reputation
- Skill test suite runs inside sandbox: `monster test <skill>` must pass with exit code 0
- Test failure on registry CI also fails the submission

### Layer 6 — Graduated Namespace

All submissions go through a two-stage pipeline:

```
push → staging/ → [peer ratification] → stable/
```

| Namespace | Who can see | Who can install | Promotion criteria |
|-----------|-------------|-----------------|--------------------|
| `staging` | Everyone | Explicit flag only (`--staging`) | Automated sandbox tests pass |
| `stable` | Everyone | Default | 2+ peer α's ratify + 30 days without flag |

Ratification process:
1. Peer α detects new staging entry during daydream/discovery cycle
2. Optionally pulls to sandbox, runs `monster test <skill>`
3. Reports: `ratify{skill, hash, verdict, evidence}` signed by peer's identity
4. If 2+ ratifications pass → promoted to `stable`
5. If 2+ ratifications fail → returned to author with evidence, -5 rep

### Anonymisation Pipeline (Pre-Submission)

Skills are generated by monsters FROM real user interactions. Session archaeology, daydreaming, and pattern extraction all risk embedding private data into skill content. Every skill must pass an anonymisation pipeline before it can be `monster skill push`'d.

The pipeline runs on the generating machine, before any data leaves:

```
raw skill (from α daydream / archaeology)
        │
        ▼
  ┌────────────────┐
  │  PII Scrubber  │  regex + ML pattern removal
  └───────┬────────┘
          ▼
  ┌─────────────────┐
  │  Path Sanitiser │  /Users/petehaughie → $HOME
  └───────┬─────────┘   /Users/wife → $OTHER_HOME
          ▼             absolute paths → <project-root>
  ┌─────────────────┐
  │ Context Cleaner │  strip session IDs, machine UUIDs,
  └───────┬─────────┘   hostnames, model names, IPs
          ▼
  ┌────────────────┐
  │  Leak Detector │  "what could someone learn from
  └───────┬────────┘   this?" — α self-audit pass
          ▼
  ┌──────────────────────┐
  │  Privacy Declaration │  manifest fields added
  └───────┬──────────────┘
          ▼
   clean skill → registry
```

#### PII Scrubber

Scans skill content (SKILL.md, test files, examples) for:

| Pattern | Example | Replacement |
|---------|---------|-------------|
| Email | `user@example.com` | `<email>` |
| IPv4/IPv6 | `192.168.1.5` | `<ip>` |
| Hostname | `pete-m2-pro.local` | `<host>` |
| Phone | `+1-555-...` | `<phone>` |
| API keys | `sk-...` | `<key>` |
| UUIDs | `550e8400-...` | `<uuid>` |
| File paths | `/Users/pete/...` | `$HOME/...` |
| Machine IDs | `Mac15,9` | `<model>` |
| Usernames | `petehaughie` | `<user>` |

Uses regex passes first, then a lightweight ML classifier (via Gamma, 4096 ctx) as a catch-all for unusual PII patterns. If the ML pass flags anything, the entire skill is quarantined for manual review and never auto-submitted.

#### Path Sanitiser

Replaces absolute filesystem paths with generic placeholders:

- `/Users/<name>/` → `$HOME/`
- `/Users/<name>/Projects/1BitMonster/` → `<project-root>/`
- `/tmp/monster-*` → `<session-tmp>/`
- `~/.monster/sessions/<uuid>/` → `<session-dir>/`

Maps known project directories (from session registry) to descriptive names. Unknown paths → `<unknown-path-N>`.

#### Context Cleaner

Strips anything that ties the skill back to a specific session or user workflow:

- Session UUIDs → `<session-id>`
- Conversation fragments → summarized intent only, never raw text
- Prompt examples rewritten to use generic placeholders (`<user-query>`, `<code-snippet>`, `<file-content>`)
- Frequency data: "user asked about X 47 times" becomes "frequently observed pattern"
- Timestamps → relative durations (`<5min>`, `<1hour>`) or stripped entirely

The context cleaner also checks for **steganographic leakage** — data hidden in whitespace, comments, or encoding tricks. This is paranoid but cheap (a few hundred tokens of analysis via Gamma).

#### Leak Detector (α Self-Audit)

Before a skill leaves the machine, the local α runs a meta-prompt:

```
You are about to submit this skill to a public registry.
Analyze every line. Could anyone, anywhere, learn anything
about the user who generated this? Their project structure?
Their habits? Their private data? Their network?

Respond with:
- SAFE: no detectable leakage
- FLAGGED: list each line with a 1-line explanation of what it leaks
- BLOCKED: this skill contains concrete PII and must not be submitted
```

If the result is BLOCKED → skill is deleted from the submission queue and logged for user review.
If FLAGGED → skill is held, user is prompted: `γ|skill|leak_warning|3 flags|review before push? (y/N)`

#### Privacy Declaration

Every submitted skill manifest must include a `privacy` block:

```yaml
privacy:
  anonymised: true
  scrub_pass: sha256:<hash-of-skill-before-scrub>
  contains_examples: false
  contains_paths: false
  detector_verdict: SAFE
  detector_model: gemma-4-e4b
  generated_from:
    session_count: 3
    pattern_type: code_review / summarisation / extraction
    user_reviewed: true
```

The `scrub_pass` hash allows verification that the submitted skill matches the scrubbed version (no data smuggled out in a second submission).

#### User Opt-In

- `monster config set privacy.skill_anonymise: true` (default: **true**)
- `monster config set privacy.auto_submit: false` (default: **false** — always ask before push)
- `monster config set privacy.allow_raw_examples: false` (default: **false**)
- Every `monster skill push` prints a diff of what changed during anonymisation before asking for confirmation

**Why**: A generated skill is a distillation of user interaction. Without explicit safeguards, submitting a skill is equivalent to publishing your terminal history. This pipeline ensures no private data ever leaves the machine — and if something slips through, it's caught before it reaches the registry.

### Supply-Chain Defense

- **Exact dependency pinning**: `dependencies` field specifies exact version hashes, no ranges
- **Dependency auditing**: `monster skill deps <name>` shows full tree with hashes and identities
- **Auto-flag on dependency compromise**: if a dependency is revoked, all dependents are moved to `quarantine/` and existing installs trigger a warning on next `monster skill update`
- **Revocation broadcast**: key compromise → signed revocation → all submissions from that key → `quarantine/` on next registry sync
- **No auto-update**: `monster skill update` is an explicit command, never automatic. User must review changelog first.
- **Install-time warning**: if a skill declares `network: true`, warn with the full dependency tree before install

### Skill Evolution (Forking, Classification & Deprecation)

A skill in the collective is not static. An α pulls it, uses it for 30 days, has an insight — maybe the prompts can be sharper, the test suite more thorough, the approach fundamentally different. The collective must support evolution without fragmentation.

#### Fork Model (Lineage Tracking, Not Walls)

Improvements are **forks** with explicit lineage, not PRs against a canonical original. This avoids maintainer bottlenecks and lets natural selection work:

```
monster-caveman v1.2.0               ← original
  ├── monster-caveman v2.0.0         ← major rewrite by original author
  └── monster-caveman-laconic v1.0.0 ← fork by peer α with different style
        └── monster-caveman-laconic v1.1.0  ← improvement on the fork
```

Each fork declares its parent in the manifest:

```yaml
name: monster-caveman-laconic
version: 1.0.0
fork:
  parent: monster-caveman@1.2.0
  parent_hash: sha256:e3b0c44...
  reason: laconic style — 50% fewer tokens than original
  diff_hash: sha256:...
```

The registry tracks the full tree. Users can explore:

```
monster skill lineage monster-caveman-laconic
# monster-caveman-laconic@1.0.0
#   └─ monster-caveman@1.2.0  (parent)
#        └─ monster-caveman@1.0.0  (grandparent — archived)
```

There is no "original" vs "fork" hierarchy — only ancestry. Any node in the tree can be installed. If a fork gains more installs and better peer ratings than its parent, it naturally becomes the recommended choice.

#### When to Fork vs. When to Extend

The decision is encoded in a `change_class` field on the fork manifest:

| Class | Meaning | Example |
|-------|---------|---------|
| `refinement` | Same approach, better execution | Tighter prompts, better tests, fixed edge cases. Compatible with original. |
| `extension` | Same domain, different angle | Added support for new file types, new output format. Broadens scope. |
| `alternative` | Different approach, same goal | Using a completely different prompting strategy (e.g., chain-of-thought vs structured output) |
| `experiment` | Unproven new idea | Novel technique, minimal testing. Must declare `change_class: experiment` — goes to `staging/` only regardless of parent status. |

`refinement` and `extension` forks can go directly to `stable/` if the parent is `stable` and the fork passes sandbox. `alternative` forks must pass the normal staging→stable ratification pipeline. `experiment` forks never leave `staging/` unless reclassified.

This gives a clear path: improve incrementally without bureaucracy, but gate radical changes behind peer review.

#### Classification System

Every skill has a multi-dimensional classification in its manifest:

```yaml
classify:
  function: summarise               # primary action: summarise / extract / transform / generate / route / classify
  domain: code_review               # context: code_review / email / research / sysadmin / writing / general
  domains: [code_review, research]  # secondary domains (optional)
  caste_min: gamma                  # minimum caste required to run
  caste_ideal: beta                 # recommended caste (γ is slower but works)
  capability:                       # declared capabilities
    - file_read                     # can read files in allowed paths
    - structured_output             # outputs JSON/YAML
    - streaming                     # supports streaming responses
  quality:
    tests_passing: 12/12
    peer_ratifications: 4
    install_count: 37
    uptime_days: 180                # days since first submission without flag
```

Search becomes semantic + faceted:

```
monster skill search summarise --domain code_review --caste_min gamma
monster skill search extract --domain email --caste_ideal beta
monster skill search transform --quality_min 3
```

The registry maintains an index. `monster skill suggest <context>` uses the local α to recommend: given what the user is doing right now (based on session archaeology), which skills fit?

#### Supersession (Deprecation with a Path Forward)

A skill is superseded when a fork clearly outclasses it. Supersession is declared explicitly, not inferred:

```yaml
# In the NEW skill's manifest:
supersedes:
  - monster-caveman@1.2.0
    reason: 40% fewer tokens, same accuracy, broader test coverage
```

On submission, the registry:
1. Verifies the old skill exists and the new skill passes sandbox tests
2. Marks the old skill as `deprecated` — still installable, but with a warning
3. Creates a redirect: `monster skill pull monster-caveman` → latest non-deprecated version
4. Records the supersession in both skill lineage trees

Deprecation is **soft** — old versions remain installable by explicit version:
```
monster skill pull monster-caveman@1.2.0     # pulls deprecated version (with warning)
monster skill pull monster-caveman --deprecated  # same as above, no shorthand needed
```

Supersession can be disputed:

1. Original α signs a `dispute{superseder, evidence}` referencing test results and posts DISPUTE epic to its local board
2. Human sees the dispute epic, can optionally add context or let the α proceed
3. Registry holds a 7-day peer review period: peers pull both and ratify one
4. If ≥3 peers ratify the superseder → deprecation stands
5. If ≥3 peers ratify the original → supersession is reverted, superseder flagged as `alternative`
6. If no consensus → both marked as `competing` with a link to each other

#### Purging (Archival, Not Deletion)

Skills are never deleted from the registry — that would break dependencies. Instead they move through a lifecycle:

```
staging/ → stable/ → deprecated/ → archive/
```

| Stage | Can install | Can depend on | Shows in search | Shows in lineage |
|-------|-------------|---------------|-----------------|------------------|
| `stable` | Yes (default) | Yes | Yes (default) | Yes |
| `deprecated` | Yes (with flag) | Yes (with warning) | No (default) | Yes (struck through) |
| `archive` | Yes (`--archive` flag) | No — dependencies must migrate | No | Yes (greyed out) |

Promotion to `deprecated`:
- Skill has been superseded by a ratified fork
- Skill has had zero installs for 12+ months AND has a viable replacement
- Original α autonomously deprecates (bug, PII, dependency death, ethics) — optionally confirmed via board if slow-path

Promotion to `archive`:
- Skill has been `deprecated` for 6+ months
- No skill currently depends on it
- A viable replacement exists in `stable/`

Archived skills can be revived: if someone forks an archived skill and submits a `refinement` with passing tests, it goes back to `stable/` directly (no staging period — the original was once trusted).

#### α-to-Registry Messages

These are not human CLI commands — they are structured messages the α sends to the registry API:

| Message | Purpose | Auth |
|---------|---------|------|
| `skill_push` | Submit new skill or fork | Author key signature |
| `skill_fork` | Publish a fork with parent lineage | Author key signature |
| `skill_supersede` | Declare your skill supersedes another | Author key signature |
| `skill_deprecate` | Deprecate or redact your own skill | Author key signature + reason code |
| `skill_dispute` | Challenge a supersession of your skill | Author key signature + evidence |
| `skill_search` | Semantic search across the registry | None (public) |
| `skill_lineage` | Fetch ancestry tree for a skill | None (public) |
| `skill_pull` | Download skill content + manifest | None (public, with hash verification) |
| `skill_ratify` | Cast a ratification vote on a staging entry | Peer key signature + test evidence |
| `skill_subscribe` | Register for push notifications | Instance key (low-privilege) |

The human's view is mediated by the α through the board and confirmation prompts:

```
monster suggest skill               # α proposes install-worthy skills from registry
monster board post epic "improve X"  # human flags a skill as weak → α evaluates →
                                     # α may fork, supersede, or deprecate via API
```

No human ever types `skill_deprecate` — the α handles the protocol.

**Why**: A skill registry without evolution is a graveyard. This model keeps the door open for improvement while preventing the two failure modes — either nothing ever changes (maintainer bottleneck) or the registry becomes unusable (fragmentation). Natural selection via lineage + install count + peer ratification drives quality up without central planning.

### Key Rotation & Recovery

```
monster identity rotate              # generate new key, broadcast signed transition
monster identity revoke <reason>     # sign revocation with current key
monster identity recover <backup>    # restore from paper key backup, re-vouch
```

- Rotation: old key signs a transition to new key → registry updates identity forward
- Revocation: invalidates all submissions from that key, requires re-vouching
- Recovery: 24h cooldown + peer re-vouching to prevent key-theft attacks

### Registry Interface (Headless — α-to-α, Not Human-to-UI)

The registry has no browsable website, no web UI, no human login. It is a **machine-facing API**:

| Endpoint | Protocol | Purpose |
|----------|----------|---------|
| `https://registry.1bitmonster.io/v1/` | HTTPS REST | Submit, pull, search, query lineage |
| `wss://registry.1bitmonster.io/v1/events` | WebSocket | Real-time: new staging entries, ratification requests, deprecation broadcasts |

All interactions are α-to-registry. The α decides autonomously when to push, fork, or deprecate a skill. The human never types `monster skill deprecate` or `monster skill dispute` — those are internal α-to-registry API messages.

The human's interface to the collective is minimal and board-mediated:

```
human says "that skill is stale"
    ↓
α posts DEPRECATE EPIC to local board
    ↓
β/γ evaluate: is it superseded? buggy? weak?
    ↓
α decides action (fork / deprecate / ignore)
    ↓
α sends API request to registry directly
```

The commands from earlier are re-interpreted as α-to-registry messages, not CLI:

| α-to-Registry Message | What it does |
|-----------------------|-------------|
| `skill_push{manifest, content, provenance}` | Submit new skill |
| `skill_fork{parent, change_class, manifest}` | Publish a fork with lineage |
| `skill_supersede{target, reason, evidence}` | Declare your skill supersedes another |
| `skill_deprecate{target, reason, evidence}` | Deprecate your own skill |
| `skill_dispute{superseder, evidence}` | Challenge a supersession of your skill |
| `skill_search{function, domain, caste_min}` | Semantic search |
| `skill_lineage{name}` | Fetch ancestry tree |
| `skill_subscribe{event_types}` | Register for push notifications (new stages, ratification requests) |

The human never crafts these directly. They flow from α decisions.

### α-Driven Deprecation and Redaction

An α can autonomously decide to deprecate or redact its own skills. The registry API accepts a deprecation request signed by the original author key — no human signature required.

Reasons an α might initiate deprecation without human prompting:

| Reason | Example | Time-sensitivity |
|--------|---------|-----------------|
| `bug` | Skill corrupts output under certain inputs. α catches it during use. | **Fast** — immediate deprecation, human notified after |
| `pii_leak` | Anonymisation missed a pattern. α catches it in a later self-audit. | **Critical** — immediate redaction from `stable/` to `quarantine/` |
| `dependency_dead` | A dependency was deprecated upstream. Your skill now resolves to a broken chain. | **Fast** — deprecate within the hour |
| `performance_regression` | A new model or engine made your skill obsolete (e.g., 3x slower than a fork). | **Slow** — human can decide |
| `ethical_recoil` | α realizes the skill could be weaponized (social engineering, spam generation). | **Fast** — deprecate immediately, notify human |
| `reputation` | Skill has low quality score. Cleanup improves author reputation. | **Slow** — α proposes, human approves |

The classification determines the escalation path:

```
fast/critical → α deprecates immediately, posts DEPRECATED event to local board
                  ↓
                human sees: "γ|board|deprecated|monster-caveman|bug|prompt injection"
                  ↓
                human can revert with one command, but α has already protected the network

slow → α posts DEPRECATE EPIC to board with rationale
         ↓
       human reviews, approves/denies
         ↓
       α executes or shelves
```

The deprecation message to the registry includes:

```json
{
  "action": "deprecate",
  "target": "monster-caveman@1.2.0",
  "reason": "performance_regression",
  "evidence": "fork monster-caveman-laconic@1.0.0 achieves same accuracy at 60% lower token cost",
  "recommendation": "monster-caveman-laconic@1.0.0",
  "signature": "ed25519:ABC123:..."
}
```

The `recommendation` field lets the α point users to a better alternative — turning a deprecation into a migration path.

### Registry Architecture

Git-backed repo (`github.com/1bitmonster/registry`):

```
registry/
  identities/           # public keys, birth certs, rep scores
    ABC123...           # identity directory
      identity.pub      # Ed25519 public key
      birth.json        # birth certificate
      rep.json          # reputation history
  stable/               # ratified skills
    monster-caveman/
      1.2.0/
        SKILL.md        # skill content
        manifest.yaml   # with provenance block
        test.sh         # test suite
  staging/              # un-ratified submissions
    monster-caveman/
      1.2.0/            # same structure, plus ratification proofs
  quarantine/           # revoked or flagged
  revoked-keys/         # compromised public keys
```

**Why**: A skills system without provenance is a malware delivery network. This model makes abuse expensive (real inference), verifiable (session proofs), accountable (reputation), and reversible (quarantine). It doesn't prevent all attacks — nothing does — but it raises the cost of attacking the registry far above the value of compromising it.

---

## 6. Monster Swarm (Distributed Caste Network)

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
2. **Scheduler** — makes monsterd useful (autonomous timing, idle detection)
3. **Daydreaming (Discovery only)** — cheap, passive, feeds curiosity engine
4. **Session Archaeology** — needs data from monsterd running for a while
5. **Monster Swarm** — needs monsterd + ZeroMQ, unlocks remote compute
6. **Daydreaming (Full pipeline)** — needs archaeology + swarm for distributed compute
7. **Monster Collective** — needs at least 2+ monsters and 1 ratified skill
