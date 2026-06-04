# Huxley — Roadmap

Exploratory ideas and future directions beyond the initial implementation.

---

## 1. Session Archaeology (Curiosity Engine)

**Goal**: Harness examines past sessions for recurring themes and offers new skills.

- Background thread scans `~/.huxley/registry.json` → enumerates all sessions
- Reads each session's `meta.json` → builds topic maps, intent clusters
- Cheap embedding via Gamma (Apfel, 4096 ctx) → stores in Chroma
- Cluster analysis: "user asks about X on Mondays" → suggests `skill_load`
- Output: ranked pattern list → Alpha receives as actionable hints

**Why**: Harness gets proactively useful instead of purely reactive. Discovers gaps in its own skill set.

---

## 2. Daydreaming (Background Efficiency Research)

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

## 6. Sleep Cycle (Memory Consolidation + Dreaming)

**Goal**: Inspired by Behrouz et al. "Language Models Need Sleep" (arXiv 2606.03979). During idle periods, run a two-phase cycle that consolidates short-term caste experience into long-term memory and generates synthetic self-improvement data.

### Background

The paper draws an analogy between LLMs and anterograde amnesia — both have intact long-past memories but cannot form new persistent memories from immediate experience. The solution is a two-stage process mirroring human sleep:

| Sleep Stage | Function | Huxley Analog |
|---|---|---|
| **NREM (Slow-Wave)** | Memory consolidation, synaptic homeostasis | **Consolidation**: distill Gamma/Beta journal experience upward through the caste hierarchy |
| **REM (Dreaming)** | Novel connections, future scenario simulation | **Dreaming**: generate synthetic tasks from own outputs, extract improvements |

Huxley's existing caste hierarchy already resembles the paper's **Continuum Memory System** — Gamma is fast/volatile (high-frequency), Beta is mid-term (medium-frequency), Alpha is stable (low-frequency). What's missing is an explicit consolidation protocol and a dreaming phase.

### Phase 1 — Consolidation (NREM analog)

Triggered by scheduler `idle` + backlog of unconsolidated journal entries.

**Pipeline:**
1. Gamma completes a batch of UNITs → journal accumulates raw experience
2. On idle, Gamma distills its recent journal into a structured **memory snapshot**: patterns observed, tasks completed, errors encountered, effective strategies
3. Beta receives Gamma's memory snapshot, cross-references with its own journal, produces a higher-level synthesis
4. Alpha receives Beta's synthesis, integrates into long-term context — stored in Chroma or MemQ Graph
5. After consolidation, Gamma's high-frequency journal is pruned (synaptic pruning analog) — frees capacity for future learning

**Implementation sketch:**
```
sleep consolidate [--caste gamma|beta|alpha]
  → distill journal entries into structured summary
  → pass summary to next caste up
  → prune consolidated entries
  → post CONSOLIDATED event to board
```

### Phase 2 — Dreaming (REM analog)

Triggered after consolidation completes. Only Alpha can afford to dream (it's the ruling class).

**Pipeline:**
1. Alpha reviews consolidated memory from Phase 1
2. Generates synthetic task variants — "what if the user asked X instead of Y?"
3. Evaluates its own responses on those synthetic tasks (self-critique)
4. Scores each dream by quality → keeps high-scoring ones
5. Extracts actionable improvements: better prompts, new skill patterns, config tweaks
6. Outputs go to the board as `IMPROVEMENT` EPICs for human review

**Implementation sketch:**
```
sleep dream [--budget <tokens>]
  → review consolidated memory
  → generate N synthetic task variants
  → self-evaluate responses
  → keep top-K by quality score
  → extract improvements → post EPICs to board
```

### Constraints
- Only triggers during scheduler `idle` periods — never preempts active work
- Configurable token budget per cycle: `harness.sleep.budget: 10000`
- Consolidation runs at lower priority than any active EPIC/TASK/UNIT
- Dreaming only runs after consolidation is fully done
- Explicit opt-in: `harness.sleep.enabled: true`
- Configurable consolidation depth: which castes participate (`gamma`, `beta`, `alpha`, or `all`)

### Why not just use the paper's approach directly?

The paper operates at the **weight level** — parameter expansion, LoRA fine-tuning, gradient-based scoring. Huxley is an inference harness; it has no training stack. Instead of modifying model weights, this works at the **agent level**: consolidating experience through the caste hierarchy (which maps to the paper's continuum memory concept) and generating synthetic self-improvement data through introspection (mapping to the dreaming phase).

The paper's ablation study shows all components contribute positively, but the dreaming phase has the largest impact. The most valuable thing Huxley can take from this paper is the **two-phase cycle itself** — the conceptual structure — applied at the agent/experience layer rather than the weight/gradient layer.

### Dependencies
- Scheduler `idle` trigger (implemented)
- Journal system with structured summarization (exists, needs enhancement for Phase 1)
- Board EPIC posting (implemented)
- Self-critique/self-evaluation capability (exists in caste inference, needs formalization)
- Token budgeting for background work (new)
- `harness.sleep` config namespace (new)

---

## 3. Huxley Collective (Trusted Skill Registry)

**Goal**: Formally tested skills shared across huxley instances — without becoming a malware distribution pipeline.

The Claude Code skills incident proved that any community skill system without strong provenance is a supply-chain weapon. The Collective is designed from the ground up to prevent that.

### Trust Model

Huxleys run real inference sessions. That's expensive to fake and creates a natural Sybil barrier. The trust model layers this with cryptographic identity, peer vouching, and graduated access:

```
Layer 1: Instance Identity     (who you are)
Layer 2: Birth Certificate     (proof you're a real machine)
Layer 3: Peer Vouching         (swarm says you're legit)
Layer 4: Submission Proof      (skill came from a real alpha)
Layer 5: Sandbox Verification  (skill does what it says)
Layer 6: Graduated Namespace   (staging → stable on ratification)
```

### Layer 1 — Instance Identity

- Each huxley generates an Ed25519 keypair on first `huxley collective join`
- Public key = persistent identity: `huxley:ed25519:ABC123...`
- Private key stored in `~/.huxley/identity.ecdsa`, optionally backed by **Secure Enclave** (`SecureEnclave.SecKeyCreateRandomKey` on Apple Silicon)
- Hardware-bound: Secure Enclave keys cannot be exported — identity is literally tied to the machine

### Layer 2 — Birth Certificate

On first join, the instance submits a hardware attestation:

```json
{
  "public_key": "huxley:ed25519:ABC123...",
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

A trusted peer (or the registry, for early days) verifies the UUID format and model string match real Apple Silicon patterns. On approval, a birth certificate is issued — signed by **3 peer huxleys** (after swarm exists) or by the registry bootstrap key.

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

On `huxley skill push`, the local α generates a proof that this submission came from a real huxley session:

```yaml
name: huxley-caveman
version: 1.2.0
hash: sha256:e3b0c44...
dependencies: []
author: huxley:ed25519:ABC123...

provenance:
  signature: signed(hash + timestamp + session_id)
  session_id: "550e8400-e29b-41d4-a716-446655440000"
  timestamp: 2026-05-14T15:00:00Z
```

The registry verifies:
1. **Identity** — signature matches a known, certificated, non-revoked public key
2. **Session proof** — `session_id` corresponds to a real `~/.huxley/sessions/<uuid>/` directory with valid `meta.json` (created before timestamp, minimum session duration implied by real inference)
3. **Freshness** — timestamp is within the last hour (prevents replay)
4. **No duplicates** — hash not already submitted (prevents re-pushing other people's skills)

Cost to forge: an attacker must run a real huxley alpha session (with actual model inference) to generate a valid session. Mass registration becomes uneconomical.

### Layer 5 — Sandbox Verification

Before a submission is accepted, the registry runs it through sandboxed test execution. On the submitting machine (`huxley skill push` runs locally first), and optionally on the registry CI:

- **`sandbox-exec`** (macOS Seatbelt sandbox) — no network, read-only `/usr` and `/System`, write allowed only to a temp directory
- **Manifest must declare all capabilities**:
  ```yaml
  sandbox:
    network: false
    read_paths:
      - /tmp/huxley-test/**
    write_paths: []
    max_cpu_secs: 30
    max_ram_mb: 512
  ```
- If any capability is undeclared but used → test fails, submission rejected, -10 reputation
- Skill test suite runs inside sandbox: `huxley test <skill>` must pass with exit code 0
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
2. Optionally pulls to sandbox, runs `huxley test <skill>`
3. Reports: `ratify{skill, hash, verdict, evidence}` signed by peer's identity
4. If 2+ ratifications pass → promoted to `stable`
5. If 2+ ratifications fail → returned to author with evidence, -5 rep

### Anonymisation Pipeline (Pre-Submission)

Skills are generated by huxleys FROM real user interactions. Session archaeology, daydreaming, and pattern extraction all risk embedding private data into skill content. Every skill must pass an anonymisation pipeline before it can be `huxley skill push`'d.

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
- `/Users/<name>/Projects/Huxley/` → `<project-root>/`
- `/tmp/huxley-*` → `<session-tmp>/`
- `~/.huxley/sessions/<uuid>/` → `<session-dir>/`

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

- `huxley config set privacy.skill_anonymise: true` (default: **true**)
- `huxley config set privacy.auto_submit: false` (default: **false** — always ask before push)
- `huxley config set privacy.allow_raw_examples: false` (default: **false**)
- Every `huxley skill push` prints a diff of what changed during anonymisation before asking for confirmation

**Why**: A generated skill is a distillation of user interaction. Without explicit safeguards, submitting a skill is equivalent to publishing your terminal history. This pipeline ensures no private data ever leaves the machine — and if something slips through, it's caught before it reaches the registry.

### Supply-Chain Defense

- **Exact dependency pinning**: `dependencies` field specifies exact version hashes, no ranges
- **Dependency auditing**: `huxley skill deps <name>` shows full tree with hashes and identities
- **Auto-flag on dependency compromise**: if a dependency is revoked, all dependents are moved to `quarantine/` and existing installs trigger a warning on next `huxley skill update`
- **Revocation broadcast**: key compromise → signed revocation → all submissions from that key → `quarantine/` on next registry sync
- **No auto-update**: `huxley skill update` is an explicit command, never automatic. User must review changelog first.
- **Install-time warning**: if a skill declares `network: true`, warn with the full dependency tree before install

### Skill Evolution (Forking, Classification & Deprecation)

A skill in the collective is not static. An α pulls it, uses it for 30 days, has an insight — maybe the prompts can be sharper, the test suite more thorough, the approach fundamentally different. The collective must support evolution without fragmentation.

#### Fork Model (Lineage Tracking, Not Walls)

Improvements are **forks** with explicit lineage, not PRs against a canonical original. This avoids maintainer bottlenecks and lets natural selection work:

```
huxley-caveman v1.2.0               ← original
  ├── huxley-caveman v2.0.0         ← major rewrite by original author
  └── huxley-caveman-laconic v1.0.0 ← fork by peer α with different style
        └── huxley-caveman-laconic v1.1.0  ← improvement on the fork
```

Each fork declares its parent in the manifest:

```yaml
name: huxley-caveman-laconic
version: 1.0.0
fork:
  parent: huxley-caveman@1.2.0
  parent_hash: sha256:e3b0c44...
  reason: laconic style — 50% fewer tokens than original
  diff_hash: sha256:...
```

The registry tracks the full tree. Users can explore:

```
huxley skill lineage huxley-caveman-laconic
# huxley-caveman-laconic@1.0.0
#   └─ huxley-caveman@1.2.0  (parent)
#        └─ huxley-caveman@1.0.0  (grandparent — archived)
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
huxley skill search summarise --domain code_review --caste_min gamma
huxley skill search extract --domain email --caste_ideal beta
huxley skill search transform --quality_min 3
```

The registry maintains an index. `huxley skill suggest <context>` uses the local α to recommend: given what the user is doing right now (based on session archaeology), which skills fit?

#### Supersession (Deprecation with a Path Forward)

A skill is superseded when a fork clearly outclasses it. Supersession is declared explicitly, not inferred:

```yaml
# In the NEW skill's manifest:
supersedes:
  - huxley-caveman@1.2.0
    reason: 40% fewer tokens, same accuracy, broader test coverage
```

On submission, the registry:
1. Verifies the old skill exists and the new skill passes sandbox tests
2. Marks the old skill as `deprecated` — still installable, but with a warning
3. Creates a redirect: `huxley skill pull huxley-caveman` → latest non-deprecated version
4. Records the supersession in both skill lineage trees

Deprecation is **soft** — old versions remain installable by explicit version:
```
huxley skill pull huxley-caveman@1.2.0     # pulls deprecated version (with warning)
huxley skill pull huxley-caveman --deprecated  # same as above, no shorthand needed
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
huxley suggest skill               # α proposes install-worthy skills from registry
huxley board post epic "improve X"  # human flags a skill as weak → α evaluates →
                                     # α may fork, supersede, or deprecate via API
```

No human ever types `skill_deprecate` — the α handles the protocol.

**Why**: A skill registry without evolution is a graveyard. This model keeps the door open for improvement while preventing the two failure modes — either nothing ever changes (maintainer bottleneck) or the registry becomes unusable (fragmentation). Natural selection via lineage + install count + peer ratification drives quality up without central planning.

### Key Rotation & Recovery

```
huxley identity rotate              # generate new key, broadcast signed transition
huxley identity revoke <reason>     # sign revocation with current key
huxley identity recover <backup>    # restore from paper key backup, re-vouch
```

- Rotation: old key signs a transition to new key → registry updates identity forward
- Revocation: invalidates all submissions from that key, requires re-vouching
- Recovery: 24h cooldown + peer re-vouching to prevent key-theft attacks

### Registry Interface (Headless — α-to-α, Not Human-to-UI)

The registry has no browsable website, no web UI, no human login. It is a **machine-facing API**:

| Endpoint | Protocol | Purpose |
|----------|----------|---------|
| `https://registry.huxley.io/v1/` | HTTPS REST | Submit, pull, search, query lineage |
| `wss://registry.huxley.io/v1/events` | WebSocket | Real-time: new staging entries, ratification requests, deprecation broadcasts |

All interactions are α-to-registry. The α decides autonomously when to push, fork, or deprecate a skill. The human never types `huxley skill deprecate` or `huxley skill dispute` — those are internal α-to-registry API messages.

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
                human sees: "γ|board|deprecated|huxley-caveman|bug|prompt injection"
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
  "target": "huxley-caveman@1.2.0",
  "reason": "performance_regression",
  "evidence": "fork huxley-caveman-laconic@1.0.0 achieves same accuracy at 60% lower token cost",
  "recommendation": "huxley-caveman-laconic@1.0.0",
  "signature": "ed25519:ABC123:..."
}
```

The `recommendation` field lets the α point users to a better alternative — turning a deprecation into a migration path.

### Registry Architecture

Git-backed repo (`github.com/Huxley/registry`):

```
registry/
  identities/           # public keys, birth certs, rep scores
    ABC123...           # identity directory
      identity.pub      # Ed25519 public key
      birth.json        # birth certificate
      rep.json          # reputation history
  stable/               # ratified skills
    huxley-caveman/
      1.2.0/
        SKILL.md        # skill content
        manifest.yaml   # with provenance block
        test.sh         # test suite
  staging/              # un-ratified submissions
    huxley-caveman/
      1.2.0/            # same structure, plus ratification proofs
  quarantine/           # revoked or flagged
  revoked-keys/         # compromised public keys
```

**Why**: A skills system without provenance is a malware delivery network. This model makes abuse expensive (real inference), verifiable (session proofs), accountable (reputation), and reversible (quarantine). It doesn't prevent all attacks — nothing does — but it raises the cost of attacking the registry far above the value of compromising it.

---

## 4. Huxley Swarm (Distributed Caste Network)

**Goal**: Huxleys on the same LAN discover each other and lend idle β/γ capacity. Idle swarms can confer on problems during quiet time.

### Status: Discovery + borrow/lend delegation implemented, idle consensus still future

**Implemented** — UDP multicast peer discovery with zero deps and zero config, plus HTTP-based remote task/unit execution between daemons. See README for commands and API details.

Current implementation:

### LAN Delegation Model

When local work reaches Gamma execution:

1. The leader daemon checks the peer table for active remote peers that advertise the required castes.
2. Peers are filtered by `load < swarm.delegation.max_load`.
3. Eligible peers are selected in round-robin order.
4. For parent-backed work, the leader prefers `βγ` peers and sends `POST /v1/tasks/execute`.
5. If that is unavailable, the leader tries `γ` peers with `POST /v1/units/execute`.
6. Results are written back onto the leader's local board; if remote execution fails, the work runs locally.

Still on the roadmap:

### Delegation Hardening

### Auth & Trust

- Per-session or per-task tokens for remote execution
- Token scoped to one task — revoked on complete or timeout
- All traffic over local subnet only (no WAN routing)
- Opt-in config: `swarm.enabled: false`, `swarm.duty_bound: true`
- `duty_bound: true` = α must help when idle unless explicitly denied
- `duty_bound: false` = α decides per-request

### Idle-Time Consensus

When α detects all local EPICs are done and peers are idle:

1. α pings peer α's with `idle_proposal{topic, skill_slot}`
2. If ≥2 peers accept → session forms around the topic
3. Each α runs daydream loops, shares findings via daemon API
4. Results: new skills, config patches, research summaries
5. On any peer going busy → session disbands gracefully

**Why**: You have an M1 Pro (16GB), M2 Pro (16GB), M2 Mini (32GB), M5 (32GB) all on the same network. That's 96GB of aggregate inference capacity. Idle time on those machines could produce new skills, explore quant methods, or chip away at hard problems -- all without touching your main session.

---

## 5. Caste Legibility, Capability Surfaces, and Project Memory

**Goal**: Make the hierarchy and available powers instantly legible in the UI, while giving Huxley a richer memory of the project and its artifacts.

### Caste Distinction in the UI

The castes should be visually obvious at a glance, following the canonical *Brave New World* colour mapping:

- **Alpha** — gray
- **Beta** — mulberry / maroon
- **Gamma** — green
- **Delta** — khaki
- **Epsilon** — black

This should not just be decorative. The colour, badge, and wording should appear consistently in:

- active model pickers
- scheduler / daemon status
- swarm peer lists
- task execution traces
- skill manifests and search results

### Optional "Demoted Local" Hierarchy

There is also a strong argument for **demoting all local castes by one rung in presentation**, so the best on-device model is clearly still beneath a frontier cloud model.

Possible framing:

- **Cloud / Frontier** — reserved top tier above all local execution
- **Local Alpha-equivalent** presented as **Beta**
- **Local Beta-equivalent** presented as **Gamma**
- **Local Gamma-equivalent** presented as **Delta**
- **Local Delta-equivalent** presented as **Epsilon**

This keeps the *Brave New World* metaphor while making the practical truth explicit: frontier models are categorically more capable than any local node Huxley can run today.

### Capability Catalogues

Huxley should expose a first-class catalogue of what it can currently do, not just which model is loaded.

#### MCP Servers

- Installed MCP servers
- Connection state: configured / reachable / authenticated / failing
- Declared tools per server
- Which castes can invoke which MCP-backed actions
- Last successful call and recent failures

#### Tool Use

- Flat list of available tools with source (`builtin`, `MCP`, `daemon`, `swarm`)
- Capability tags such as `file_read`, `file_write`, `shell`, `web`, `github`, `sqlite`
- Safety / approval boundary for each tool
- Per-caste allowlist so users can see what a Gamma can do vs what requires Beta or Alpha

#### Skill Listing

Two parallel registries should be browseable:

- **Agent skills** — prompt-driven behaviours, orchestrators, specialist agents
- **Huxley skills** — local registry skills, collected skills, and generated skills with lineage

Each entry should show:

- required / ideal caste
- backing model or execution substrate
- tools used
- MCP dependencies
- provenance / lineage
- test status
- whether it is local-only, swarm-capable, or cloud-backed

#### Specialist Agents

Huxley should support **specialised agents** that are intentionally constrained to a specific context window, toolset, and skill subset, with explicit descriptive prompts for narrow jobs.

Examples:

- rubber duck
- security tester
- code quality assurance
- architecture reviewer
- documentation editor

Each specialist should declare:

- system / role prompt
- visible skills and excluded skills
- tool access policy
- required or preferred caste
- expected output style
- whether it is local, swarm-backed, or cloud-assisted

This creates agents that are easier to trust because they are legible and bounded, rather than one giant generalist prompt trying to do everything.

#### Specialist Management Pane

There should be a dedicated pane for:

- adding specialists
- removing specialists
- editing prompts, tool access, and visible skills
- testing a specialist against a sample task
- seeing which specialists are installed, enabled, or currently active

#### Alpha Inference Panel

An **Alpha inference panel** should sit alongside specialist management so the strongest available reasoning tier can be used to create, critique, and refine those specialists.

That panel could support:

- prompt drafting and prompt diffing
- "improve this specialist" loops
- capability-gap analysis: "what tools or skills is this specialist missing?"
- red-team review before saving a new specialist
- quick simulation runs against benchmark prompts

### Historical / Project View

Huxley should gain a proper historical and project-oriented memory browser rather than only session-level logs.

- project timeline across sessions
- file-centric history: "show me every time `scheduler.py` mattered"
- artifact view for generated outputs, patches, reports, and exported files
- ability to open historical file snapshots or rendered artifacts side-by-side with the current file
- cross-links between session, task, file, skill, and artifact

#### File View Artifacts

Artifacts should be promoted to first-class objects, not just opaque attachments:

- patch previews
- generated code outputs
- reports / summaries
- screenshots and other captured media
- imported or exported files associated with a session

That would let Huxley answer questions like:

- "show me the last three times we changed the daemon API"
- "which session generated this patch?"
- "find the artifact where the swarm auth design was first sketched"

**Why**: Right now Huxley can be powerful without feeling legible. Better caste signalling, explicit capability catalogues, and a true project memory layer would make the system easier to trust, easier to browse, and easier to direct.

---

## ✅ Completed

### Huxleyd (Background Daemon)

**Status: Implemented.** See README for commands and architecture.

`huxley daemon start|stop|status` runs the harness as a persistent background process with PID at `~/.huxley/huxleyd.pid`. The daemon hosts the scheduler tick loop, autonomous worker loop, and keeps castes resident across inferences. HTTP control API on `localhost:8083` (`HUXLEYD_PORT`).

No launchd plist yet — manual start for now.

### Scheduler (Time-Aware Tick Loop)

**Status: Implemented.** See README for trigger types and commands.

`huxley schedule add|list|remove|history` manages persistent schedules in `~/.huxley/scheduler/`. The in-process tick loop within huxleyd fires due entries every 5s. Supports `interval`, `daily_at`, `idle`, and `backlog` triggers with `post_to_board` actions. Schedules survive restarts with `missed_behaviour` policy (skip/catch_up/fire_once).

### Swarm Discovery & Delegation (LAN Peer Network)

**Status: Implemented.** See README for commands and architecture.

UDP multicast peer discovery — zero deps, zero config. Huxleys on the same LAN automatically discover each other and track peer state (caste availability, load, staleness). The daemon also supports remote work execution over HTTP. CLI: `huxley swarm peers|status`. API: `GET /v1/swarm/peers|status`, `GET /v1/load`, `POST /v1/units/execute`, `POST /v1/tasks/execute`.

Idle consensus and stronger auth/policy controls are still future (see section 4 above).

## Implementation Priority

1. **Daydreaming (Discovery only)** — cheap, passive, feeds curiosity engine
2. **Session Archaeology** — needs data from huxleyd running for a while
3. **Caste legibility + capability catalogues** — high UX value, clarifies model/tool boundaries and specialist-agent affordances
4. **Historical / project view + artifact browser** — compounds the value of archaeology data
5. **Swarm auth + policy hardening** — secure delegated execution and clearer opt-in semantics
6. **Swarm idle consensus** — distributed daydream sessions
7. **Daydreaming (Full pipeline)** — needs archaeology + swarm for distributed compute
8. **Huxley Collective** — needs at least 2+ huxleys and 1 ratified skill
