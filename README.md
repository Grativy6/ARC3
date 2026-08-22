# ARC3

ARC3 is a reproducible, offline-capable research agent for the **ARC Prize 2026 — ARC-AGI-3**
interactive reasoning benchmark. It explores unfamiliar grid environments, preserves immutable
observations and action consequences, tracks revisable hypotheses, compiles executable world
models, infers candidate goals, plans one action at a time, recovers from contradictions, and
checkpoints exact state.

## Measured status

**Build 000: PARTIAL.** The typed agent, deterministic evaluation system, trace/replay/checkpoint
machinery, procedural environments, ablations, runtime profile, integrity checks, and offline
Kaggle package candidate were implemented on `build/000-arc3-end-to-end` and merged by the owner
through [PR #3](https://github.com/Grativy6/ARC3/pull/3). Build 001 local-public recovery is in
progress on `build/001-local-public-recovery`; no release or official submission has occurred.

“PARTIAL” describes the measured agent result, not missing evidence:

| Surface | Strongest relevant result |
|---|---|
| synthetic | Full controller 32/32 in 190 actions vs cycle 4/32 in 463 under equal 16-action budgets |
| synthetic ablation | FULL 8/14 in 150 actions; no world-model simulation 1/14 in 211; no goal inference 0/14 in 224 |
| local-public | Full controller timed out in all 30 Stage 15 smoke/development runs and all 6 Stage 18 release-smoke runs, completing zero levels; random produced the sole nonzero Stage 15 result and completed one development level |
| synthetic runtime | 80 actions in 116.26474110002164 seconds; 175,210,496-byte peak RSS; all 9 runtime checks passed |
| synthetic robustness | 7 passed, 4 palette/action-remap cases failed, 1 rule-change case not exercised |
| synthetic package | Two byte-identical offline candidates passed sandbox, schema, source, wheel, secret, and game-ID checks |
| synthetic release infrastructure | Clean clone passed 423 tests, 13 replay/tamper tests, exact benchmark reproduction, deterministic packaging, integrity, and artifact verification |

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
accept terms, upload, or submit. Exact clean-clone release reproduction is documented in
[`docs/reports/018-release-candidate-verification.md`](docs/reports/018-release-candidate-verification.md).

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

- The measured public result is negative; synthetic completion did not transfer.
- Palette and action remapping break otherwise successful paired synthetic cases.
- The one-shot public holdout remains deliberately unconsumed after its development gate failed.
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
