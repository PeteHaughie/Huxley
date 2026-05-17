# Huxley — AI Agent Harness

## Concept

Hyper-efficient local-first AI framework with a three-tier caste system inspired by Brave New World:

- **Gammas** (`γ`): Disposable worker drones — menial, brainless, high-volume
- **Betas** (`β`): Middle management — summarization, routing, light reasoning
- **Alphas** (`α`): Orchestrators — pure cognition, no heavy lifting, all HCI

All communication curt + perfunctionary (caveman style). Context windows minimised.

## Components

| Caste | Model | Engine | Role |
|-------|-------|--------|------|
| γ | Apple Foundation Model | Apfel (`apfel --serve`) | File I/O, classification, extraction, grep generation |
| β | Bonsai Ternary 8B (1.58-bit) | MLX (primary), llama.cpp fork (fallback) | Summarisation, routing, task decomposition, mid-level reasoning |
| α | Gemma 4 e4B (4-bit quant) | llama.cpp + MTP + TurboQuant | Orchestration, HCI, long-term memory, skill dispatch, cloud routing |

## Architecture

```
User ←→ α (Gemma 4 + MTP + TurboQuant)
           │
           ├──→ β (Bonsai Ternary 8B / MLX) ──→ γ (Apfel)
           │         │
           │         └──→ Chroma (vector memory)
           │
           ├──→ MemQ Graph (entity-relation memory)
           │
           └──→ Cloud Endpoint (OpenAI-compatible, optional)
```

### Memory System

1. **VK Cache (TurboQuant)**: In-process KV cache at 4.5 bits/element. Persisted to `~/.huxley/<session>/cache/`.
2. **Vector DB (Chroma)**: Semantic memory in `~/.huxley/<session>/interlink/`.
3. **MemQ Graph**: Entity-relation graph. Nodes = concepts/files/agents, edges = relationships.

### Session Lifecycle

```
~/.huxley/
  registry.json          # path → session-id mapping
  config.yaml            # global harness config
  sessions/
    <uuid>/
      meta.json          # session metadata
      interlink/         # Chroma vector DB
      graph/             # MemQ graph snapshots
      cache/             # TurboQuant KV cache state
      gamma/             # Apfel session scratch
      beta/              # Bonsai session scratch
      alpha/             # Alpha session scratch
```

Each project directory gets a `.huxley` symlink → `~/.huxley/sessions/<uuid>/`.

## Structured Message Protocol

```json
{
  "caste": "α" | "β" | "γ",
  "msg_id": "uuid",
  "session": "session-uuid",
  "action": "infer" | "route" | "store" | "recall" | "fork" | "skill_load",
  "payload": {},
  "token_budget": {"input": 4096, "output": 512},
  "context_hint": "caveman" | "normal" | "full",
  "timestamp": "ISO8601"
}
```

## Implementation Phases

### Phase A — Skeleton
- Config, CLI entry point, message protocol, session persistence

### Phase B — Gamma (Apfel)
- OpenAI-compatible client for `apfel --serve`, Gamma dispatch

### Phase C — Beta (Bonsai)
- MLX integration for Bonsai Ternary, Beta dispatch, fallback engine

### Phase D — Alpha (Gemma 4)
- llama.cpp bindings, MTP speculative decoding, TurboQuant KV cache, orchestration loop

### Phase E — Memory
- Chroma vector DB, MemQ graph, TurboQuant cache persistence

### Phase F — Skills
- `~/.agents/skills/<name>/SKILL.md` loader, skill dispatch protocol

### Phase G — Cloud
- Custom OpenAI-compatible endpoint, dual-mode routing (local + cloud)

### Phase H — Self-modification
- Introspection engine (AST parsing), code patcher, hot-reload (SIGHUP)

### Phase I — Polish
- Error recovery, Gamma/Beta respawn, performance tuning

## Key Risks

- **Bonsai llama.cpp fork stale**: Mintplex-Labs/prism-ml-llama.cpp not merged upstream. Betas may rely solely on MLX.
- **TurboQuant Metal support**: `TurboFlash` Metal backend may have gaps. Test `--cache-type-k turbo4_0` on Apple Silicon.
- **Apfel requires macOS 26+**: Not available on earlier OS versions.
- **Self-mod sandboxing**: Full code modification needs guardrails (dry-run, diff review, rollback).
