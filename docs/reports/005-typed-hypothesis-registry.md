# Stage 05 — Typed hypothesis registry

- **Stage status:** PASS
- **Measured surface:** synthetic
- **Measured at:** 2026-08-21
- **Repository base during measurement:** `3fe666e300650d870cbfe0ef7c56be52126ff714` with Stage 05 files uncommitted
- **Primary evidence:** `docs/evidence/005-hypothesis-acceptance.json`

## Result

ARC3 now distinguishes a typed candidate explanation from an active, contradicted, narrowed,
rejected, superseded, or reopened rule. Registry state is a deterministic fold of immutable
hypothesis events rather than a mutable belief record. Rebuilding from serialized events
reproduces the same current records and full history.

The registry supports all nine architecture families:

- action semantics;
- controllable-object identity;
- collision/traversability;
- interaction/toggle;
- coordinate-action target;
- state transition;
- progress/terminal;
- candidate goal;
- level invariant.

Each family has a structured statement with explicit fields and strict round-trip validation.
No family type grants accepted status merely by construction.

## Evidence and lineage

Support, contradiction, and unexplained-residual receipts must cite at least one immutable
source event ID. Receipt summaries are bounded convenience text; the event pointers remain the
authority for replay. Status changes preserve their prior state, cause IDs, rank contribution,
scope, and event sequence.

Lineage records parent IDs, narrowed forms, superseding forms, and scope changes without
rewriting the broad or earlier claim. Rejected hypotheses remain directly retrievable, and an
`ever_rejected` view retains that fact after reopening. Reopening emits a deterministic signal
for every registered dependent plan and clears those dependencies only after preserving the
invalidation receipt.

## Synthetic acceptance sequence

The measured sequence created a broad action-semantics candidate, supported it, contradicted
it, created a narrower contact-conditioned child, marked the broad form narrowed, rejected the
child, and later reopened that same child from a residual receipt. The final broad state was
`narrowed`; the child's final state was `candidate`; its parent, contradiction, residual,
rejection history, and invalidated `PLAN-7` dependency all remained present.

The seven lifecycle events were also converted into the Stage 03 immutable trace vocabulary,
verified as a complete hash chain, and rebuilt into a derived trace index with the same final
statuses and parent link.

## Ranking and conflict handling

Weights are signed integers used only for deterministic ordering. Every serialized/reporting
surface calls them `uncalibrated_rank`; they are not probabilities, confidence calibration, or
proof. Conflict relations are symmetric and deterministically resolved by status, rank,
testing recency, creation order, and stable ID. Compatible hypotheses can form ensembles;
incompatible or redundant claims remain explicit.

## Verification

```text
Ruff check / format (Stage 05 paths): PASS
strict mypy (10 Stage 05 source files): PASS
focused pytest: 20 passed in 2.34s
typed family round trips: PASS (9/9)
trace-chain/index lifecycle integration: PASS
```

Tests cover strict serialization, malformed-event rejection, duplicate IDs, illegal status
transitions, support/contradiction/residual receipts, family mismatches, scope and supersession,
parent/narrowed lineage, rejected-history retrieval, reopening and plan invalidation,
deterministic ranking/conflicts/ensembles, reports, event-fold equivalence, and the full
acceptance sequence.

## Commands

```text
python -m uv run ruff check src/arc3/hypotheses tests/unit/test_hypotheses_families.py tests/unit/test_hypotheses_registry.py tests/property/test_hypotheses_properties.py tests/integration/test_hypothesis_lifecycle.py
python -m uv run ruff format --check src/arc3/hypotheses tests/unit/test_hypotheses_families.py tests/unit/test_hypotheses_registry.py tests/property/test_hypotheses_properties.py tests/integration/test_hypothesis_lifecycle.py
python -m uv run mypy src/arc3/hypotheses
python -m uv run pytest -q --basetemp %TEMP%\arc3-stage05-final-pytest tests/unit/test_hypotheses_families.py tests/unit/test_hypotheses_registry.py tests/property/test_hypotheses_properties.py tests/integration/test_hypothesis_lifecycle.py
```

## Preserved limits

- The acceptance sequence validates mechanism behavior, not prediction quality.
- Rank weights are deliberately uncalibrated; Stage 14 must measure downstream usefulness.
- Conflict resolution is a stable generic rule, not evidence that the winning claim is true.
- Reopening preserves and invalidates dependencies but leaves replacement selection to later
  world-model and planning stages.
