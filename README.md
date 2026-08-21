# ARC3

Autonomous research and engineering workspace for the **ARC Prize 2026 — ARC-AGI-3** interactive reasoning benchmark.

ARC3's initial target is a reproducible, offline-capable agent that can explore unfamiliar grid environments, infer mechanics and candidate goals, test rules against preserved history, plan efficiently, recover from failed predictions, and package cleanly for Kaggle evaluation.

## Current status

**`WORKFLOW_READY`** — the complete autonomous Codex workflow is prepared. Agent implementation and measured scoring have not started.

## Start the autonomous build

1. Open the branch `workflow/000-autonomous-arc3` in Codex.
2. Read [`CODEX_START.md`](CODEX_START.md).
3. Paste its launcher exactly once.

The short form is:

> Read `AGENTS.md`, then execute `docs/workflows/000-arc3-autonomous-end-to-end.md` from beginning to end. Use all routine permissions granted there, persist after every meaningful task, resume from `docs/ledger/run-state.json` after interruption, and stop only at its explicit human gates. Do not merge the final PR.

The implementation run creates and works on:

```text
build/000-arc3-end-to-end
```

## What is already prepared

| Surface | Purpose |
|---|---|
| [`AGENTS.md`](AGENTS.md) | Repository-wide autonomy, integrity, evidence, and human-gate contract |
| [`CODEX_START.md`](CODEX_START.md) | One-paste launcher and recommended Codex permissions |
| [`docs/workflows/000-arc3-autonomous-end-to-end.md`](docs/workflows/000-arc3-autonomous-end-to-end.md) | Twenty-one-stage build from source identity through offline Kaggle package, clean-clone verification, research report, and draft PR |
| [`docs/specs/target-architecture.md`](docs/specs/target-architecture.md) | Observation → trace → hypothesis → world model → goal → plan/probe → action → consequence/reopening architecture |
| [`docs/specs/trace-ledger-contract.md`](docs/specs/trace-ledger-contract.md) | Append-only, hash-linked receipts, replay, summaries, and checkpoint contract |
| [`docs/specs/evaluation-protocol.md`](docs/specs/evaluation-protocol.md) | Baselines, partitions, ablations, reproducibility envelope, and claim limits |
| [`docs/ledger/run-state.json`](docs/ledger/run-state.json) | Machine-readable persistent stage/task state for interruption recovery |
| [`docs/ledger/DECISIONS.md`](docs/ledger/DECISIONS.md) | Append-oriented material decision ledger |
| [`docs/ledger/OPEN_BURDENS.md`](docs/ledger/OPEN_BURDENS.md) | Unresolved technical, evidential, external, and owner-gated burdens |
| [`docs/legal/LICENSE-DECISION.md`](docs/legal/LICENSE-DECISION.md) | Explicit owner gate for the eventual open-source license |

## Build route

```text
source identity
→ reproducible project foundation
→ official SDK and baselines
→ immutable trace / replay / checkpoint
→ perception and object correspondence
→ typed hypotheses and reopening
→ procedural unseen-rule laboratory
→ information-efficient exploration
→ retrodictive executable world model
→ goal acquisition
→ planning and recovery
→ scoped persistent memory
→ integrated ARC3 controller
→ evaluation harness and ablations
→ public-game development
→ runtime and integrity hardening
→ offline Kaggle package
→ clean-clone verification
→ methods/results report and owner handoff
→ final draft PR
```

The final competition policy must work without internet or a hosted model API. Public game IDs may appear in manifests and reports, but production policy may not contain game-specific solutions.

## Human gates

The autonomous run may build, test, benchmark, push branches, and open/update a draft PR. It may not independently:

- accept ARC Prize or Kaggle legal terms;
- grant a public software license;
- spend money or activate paid compute;
- expose or create credentials;
- submit an official competition entry;
- merge into `main`;
- communicate externally as Christopher D. Pang.

At a gate, Codex must prepare everything up to the boundary, record the exact smallest owner action, and continue all independent work.

## Result discipline

ARC3 will distinguish synthetic, local-public, online-public, Kaggle-public, semi-private, and official-private results. A public-game win is not a hidden-generalization result. A clean package is not an official submission. A trace-inspired architecture is not proof of PAL.

Low or zero scores remain valid results when the run is reproducible and honestly reported.

## Authorship

**Christopher D. Pang** is the project author and steward. AI systems are development tools and assistants, not co-authors, owners, or independent authorities.
