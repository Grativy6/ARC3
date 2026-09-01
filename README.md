# ARC3

## Strongwiz clean-room playground

This branch is an isolated sibling experiment rooted at the Build 002 merge
`bea1eac99cb0f1b351526b1dc487d132ba1d40ef`. It uses the same comparison base as
the earlier 003w clean-room experiment and must not inherit implementation,
receipts, traces, replays, action sequences, or game-specific discoveries from
Build 003 or 003w.

The intended experimental aperture is the frozen ARC3 comparison base, a
separately pinned public Strongwiz source commit, and explicitly authorized
official public ARC-AGI-3 interfaces. Hearthline and `hearthline-workshop` are
outside the aperture. No Strongwiz source or environment interaction is
consumed by this setup commit; those require a later owner run directive and a
recorded source pin.

Merely reading this checkout does not authorize changes. If an owner instruction explicitly
directs a system to build or run ARC3 **in this checkout**, that system must treat this repository
root as its complete project workspace:

- do not create, edit, delete, or use task-generated project files outside this repository;
- do not inspect or import another ARC3 checkout, prior-run branch, Hearthline repository, trace,
  replay, or artifact;
- keep virtual environments, caches, temporary files, logs, traces, recordings, checkpoints, and
  generated evidence inside this repository;
- use [`playground/`](playground/) for disposable scratch work and task-local tool state;
- stop and report the boundary if a required build step cannot be completed without crossing the
  declared source or workspace aperture.

Read-only systems may inspect this checkout when authorized to do so. The build restrictions become
active only for a system instructed to build or run work here; they do not manufacture write,
gameplay, submission, or legal authority. See [`playground/README.md`](playground/README.md) for the
full boundary.

ARC3 is a reproducible, offline-capable research agent for the **ARC Prize 2026 — ARC-AGI-3**
interactive reasoning benchmark. It explores unfamiliar grid environments, preserves immutable
observations and action consequences, tracks revisable hypotheses, compiles executable world
models, infers candidate goals, plans one action at a time, recovers from contradictions, and
checkpoints exact state.

## Measured status

**Build 001: PARTIAL.** Build 001 is complete on `build/001-local-public-recovery` and remains an
unmerged [draft PR #5](https://github.com/Grativy6/ARC3/pull/5). It reproduced and diagnosed the
local-public timeout, added bounded palette/action equivariance mechanisms, preserved a failed
rule-change mechanism, mechanically refused the public holdout, and produced a deterministic
offline package candidate. The decisive public-recovery and regression matrices ended at
authenticated infrastructure boundaries, so recovery was not measured. No release or official
submission has occurred.

“PARTIAL” describes the measured agent result, not missing evidence:

| Surface | Strongest relevant result |
|---|---|
| local-public | Build 001 FULL reproduced the frozen timeout: 120.11965939996298 seconds, 21 actions, 0 levels, local score 0.0; the matched Build 000 run used 19 actions and 120.110601900029 seconds |
| local-public diagnosis | Matched-action control 46.070333300042 seconds; allocation tracing off 8.84490280004684; checkpoints off 37.9903721000301; both off 6.75240610004403 |
| synthetic palette | 256/256 paired cases, 16/16 checkpoint pairs, and 128/128 causal controls passed |
| synthetic action | 128/128 paired cases, 528/528 inverse requests, 64/64 causal controls, and 16/16 checkpoint pairs passed |
| synthetic rule change | 112/112 executions completed; action rotation 32/32, traversability gate 0/32, stationary-noise gate 0/32, checkpoint continuity 4/8 — `FAILED_MECHANISM` |
| development recovery | 96-cell matrix stopped before environment open: 0 gameplay actions, 95 cells unstarted — `FAILED_INFRASTRUCTURE` |
| synthetic package | Final 788,070-byte archive reproduced across eight hosted Ubuntu/Windows A/B builds at SHA-256 `02326a145d510c017dc04ffd79a61cfe8c46771cbc9e74b7c8f29a9b75756d21`; exact private surface remains `BLOCKED_EXTERNAL` |

These results do not establish hidden-game generalization. There is no `online-public`,
`Kaggle-public`, `semi-private`, or `official-private` result. Official RHAE is unmeasured/null for
the local runs; completion, environment-action counts, and local scorecard values are not RHAE.

## Quickstart

Requirements: Git, uv 0.12.5, and a uv-managed CPython 3.12.14 runtime.

```powershell
git clone https://github.com/Grativy6/ARC3.git
Set-Location ARC3
git switch build/001-local-public-recovery
uv sync --frozen --all-extras --dev --python 3.12.14
uv run arc3 doctor
uv run pytest -q
```

Quality and integrity checks:

```powershell
uv run ruff check .
uv run ruff format --check .
uv run mypy --strict src agent scripts
uv run python -m scripts.check_competition_integrity --root .
```

Build the no-submit offline candidate:

```powershell
.\scripts\prepare_kaggle_submission.ps1 --output artifacts\stage17\candidate --owner-username OWNER_USERNAME
```

The package command uses `OWNER_USERNAME` only as notebook metadata. It does not authenticate,
accept terms, upload, or submit. Exact Build 001 package verification is documented in
[`docs/reports/001-13-offline-package.md`](docs/reports/001-13-offline-package.md).

## Architecture

```text
observation
  -> interpretation
  -> candidate hypothesis
  -> accepted rule
  -> executable world model
  -> goal hypothesis
  -> probe or plan
  -> action
  -> returned consequence
  -> trace update and possible reopening
```

Raw environment receipts are immutable and hash-linked. Derived summaries, hypotheses, indices,
world models, goals, and plans remain revisable. Every action is bound to its pre-action evidence,
active models and goals, selected plan/probe, concise alternatives, returned consequence, and
resulting confirmation or contradiction. The controller emits one action, waits for its actual
consequence, then validates or recovers.

Production policy is offline and CPU-default. It contains no hosted model API, public-game ID
conditionals, manually encoded public-game action sequences, or game-specific solution table.
Static source and archive checks fail on obvious violations of those restrictions; they are not a
proof that every possible shortcut is absent.

## Evidence map

| Artifact | Purpose |
|---|---|
| [`docs/research/ARC3-Build-001-report.md`](docs/research/ARC3-Build-001-report.md) | Build 001 methods, results, failures, and limitations |
| [`docs/research/ARC3-Build-001-publication-draft.md`](docs/research/ARC3-Build-001-publication-draft.md) | Publication draft; not submitted or released |
| [`docs/review/ARC3-Build-001-review-packet.md`](docs/review/ARC3-Build-001-review-packet.md) | Reviewer evidence map and checklist |
| [`docs/handoffs/001-local-public-recovery.md`](docs/handoffs/001-local-public-recovery.md) | Build 001 owner handoff |
| [`docs/evidence/001-final-evidence-index.json`](docs/evidence/001-final-evidence-index.json) | Build 001 machine-readable result/evidence index |
| [`docs/ledger/build-001-run-state.json`](docs/ledger/build-001-run-state.json) | Build 001 persistent machine-readable stage state |
| [`docs/ledger/build-001-DECISIONS.md`](docs/ledger/build-001-DECISIONS.md) | Build 001 material technical decisions |
| [`docs/ledger/build-001-OPEN-BURDENS.md`](docs/ledger/build-001-OPEN-BURDENS.md) | Build 001 failures, contradictions, and residual work |
| [`docs/research/ARC3-Build-000-report.md`](docs/research/ARC3-Build-000-report.md) | Methods, results, ablations, failures, and limitations |
| [`docs/handoffs/000-autonomous-arc3.md`](docs/handoffs/000-autonomous-arc3.md) | Owner handoff and exact next boundary |
| [`docs/ledger/run-state.json`](docs/ledger/run-state.json) | Persistent machine-readable stage state |
| [`docs/ledger/DECISIONS.md`](docs/ledger/DECISIONS.md) | Material technical decisions |
| [`docs/ledger/OPEN_BURDENS.md`](docs/ledger/OPEN_BURDENS.md) | Unresolved mechanisms, evidence gaps, and external gates |
| [`docs/evidence/`](docs/evidence/) | Compact measured acceptance receipts |
| [`docs/reports/`](docs/reports/) | Stage methods and reproduction commands |
| [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) | Complete locked dependency/license inventory |
| [`LICENSE`](LICENSE) | Operative MIT-0 grant for ARC3 first-party source |
| [`docs/legal/candidates/MIT-0-CANDIDATE.md`](docs/legal/candidates/MIT-0-CANDIDATE.md) | Preserved nonoperative pre-decision candidate |

The repository-wide execution and integrity contract remains [`AGENTS.md`](AGENTS.md). The frozen
bootstrap copy under `docs/reference/` is provenance, not a competing instruction set.

## Known limitations

- The only valid Build 001 public result reproduces the timeout; the decisive recovery matrix did
  not reach gameplay.
- Palette/action mechanisms pass bounded paired synthetic suites but add measured calibration cost.
- Typed traversability/noise reopening and checkpoint continuity failed in Stage 06.
- The one-shot public holdout remains deliberately unconsumed after its frozen gate was not earned.
- The private Kaggle wheel inventory, gateway, scorer, and complete 110-game runtime were not
  available locally.
- The complete sequential competition runtime is estimated, not measured end to end.
- Hash seals are tamper-evident identities, not signatures or proof of trusted execution.
- No official submission or hidden/private evaluation has occurred.

Low or zero scores remain evidence when their budgets, source identity, failures, and artifacts are
preserved. Packaging success does not revise gameplay results.

## Human gates

Christopher D. Pang explicitly approved MIT-0 for ARC3 first-party source on 2026-08-21. Only
Christopher may accept competition terms, supply or disclose credentials, spend money, make an
official submission, publish a release/DOI, communicate externally as the owner, or merge the
draft PR.

## Authorship and claim boundary

**Christopher D. Pang** is the project author and steward. AI systems are development tools and
assistants, not co-authors, owners, or independent authorities.

ARC3 is a bounded engineering experiment. It does not prove PAL, AGI, consciousness, hidden-game
generalization, or a general theory of intelligence.
