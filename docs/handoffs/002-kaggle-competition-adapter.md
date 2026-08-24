# ARC3 Build 002 — Owner handoff scaffold

**Status:** `IN_PROGRESS`; this is not the final handoff.
**Branch:** `build/002-kaggle-competition-adapter`
**Base:** `a1931c673b90923e1af78127229667544802a096`
**Draft pull request:** pending
**Build 001:** remains `PARTIAL`
**Build 001 holdout record:** remains `SEALED_UNCONSUMED`
**Build 002 one-shot authority:** `AUTHORIZED_ONCE_NOT_YET_CONSUMED`
**Official RHAE:** none

Christopher D. Pang is author and steward. AI systems are development tools and assistants, not
co-authors, owners, or independent authorities.

## Measured results

Pending. Do not populate this section from synthetic fixtures, projections, or approximate
scorers. If the authorized ten-game run is earned and executed, report its exact `local-public`
toolkit identity, total score, completed games/levels, per-game and per-level results, agent actions
versus human baselines, wall time, peak memory, governor allocation/reserve, failure taxonomy, and
source/config/artifact hashes.

## Implementation and validation

In progress. Final handoff must identify the exact implementation freeze and verify:

- explicit research and bounded competition modes;
- exact `MyAgent.is_done()` / `MyAgent.choose_action()` integration;
- process-global deterministic tournament governor and official lifecycle;
- competition-only tracing/checkpoint policy with research defaults retained;
- official fixed-action grants only at the bounded adapter boundary;
- true offline cold package, dependency/corpus/config/license completeness;
- notebook build and offline execution;
- structurally valid deterministic `submission.parquet`;
- repository tests, Ruff, strict mypy, replay, integrity/secret scans, and clean clone;
- pushed branch and current draft PR.

## Public-run disposition

Not started. All frozen preflight gates are still pending. Build 002 has `0/1` runs started, zero
environment make interactions, and zero gameplay actions. If the run starts, any failure consumes
the authority and must be reported without retry. Build 002 evidence cannot change Build 001's
historical gate or status.

## Unresolved burdens

- Exact private Kaggle wheels, framework input, gateway, scorer, and hidden environments are
  `BLOCKED_EXTERNAL`.
- Local toolkit and current Kaggle score-cap formulas conflict.
- Public toolkit and latest observed staff-sample versions differ.
- Exact private `submission.parquet` acceptance cannot be proven locally.
- Offline cold start, final package, notebook, structural output, and one-shot run remain pending.

See `docs/ledger/build-002-OPEN-BURDENS.md` for the append-only record.

## Owner-only actions

None are requested while implementation remains in progress. Final handoff may prepare—but must
not perform—the following explicit boundaries:

- review/merge the draft PR;
- accept competition terms;
- provide/use Kaggle credentials;
- upload the notebook;
- submit to the competition or spend a daily submission;
- publish a release or DOI;
- authorize paid compute.

The completed handoff must name only the smallest next owner action that is actually required.
