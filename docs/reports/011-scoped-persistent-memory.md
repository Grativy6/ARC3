# Stage 11 — Scoped persistent memory and restart continuity

- **Stage status:** PASS
- **Measured surface:** synthetic
- **Mechanism result:** MECHANISM_OBSERVED
- **Measured at:** 2026-08-21
- **Repository base during measurement:** `686f13ae2601b1215571db921f60335f1153c576` with Stage 11 files uncommitted
- **Primary evidence:** `docs/evidence/011-memory-acceptance.json`

## Result

ARC3 now stores revisable derived memory at episode, opaque game, and generic scopes without
turning environment identity into a solution key. Retrieval supports exact source event,
palette/position-independent abstract state, active contradiction, and analogous generic rule
structure. Generic retrieval requires analogous-rule evidence from the current game before a
cross-game record becomes visible.

Every record points to a source-linked trace summary with a contiguous event range, each event
hash, sealed chunk hashes, supporting and contradicting event IDs, generator code/config
identity, and unresolved residuals. Loading or replay rebinding rejects changed source hashes,
invalid summary claims, or budget measurements. Solution-shaped lookup fields are rejected in
payloads and summaries, and production memory code contains no frozen public identifier.

Deterministic record/byte budgets govern every scope and the combined store. Eviction retains
source trace and removes only derived records. Snapshots preserve exact access sequence and
validate their declared record/byte totals before restoration. Named switches provide no-memory
and no-rejected-hypothesis-retention ablations.

## Checkpoint and process death

The controller checkpoint wrapper carries the Stage 03 journal identity, Python RNG state,
phase, normalized state hash, perception state, action semantics, hypothesis registry, world
model ensemble, goal registry, explored graph, planner state, scoped memory, pending action, and
unresolved residuals.

An actual child process exited with code 23 after `action.submitted` and before
`consequence.received`. Restoration recovered every derived field, preserved the pending action,
returned `AWAIT_CONSEQUENCE`, and did not permit resubmission. After the consequence was
reconciled, 20/20 subsequent seeded choices matched uninterrupted execution. At this stage the
subsystem snapshots are validated canonical JSON; live typed reconstruction belongs to the Stage
12 controller adapters.

## Cross-level and bounded-memory measurements

One synthetic prior-level trace established that a generic action produced upward translation.
The next level changed palette/position while retaining the same abstract rule:

| Variant | Validation probes |
|---|---:|
| source-linked game memory | 1 |
| ordered identification without memory | 3 |

The two-probe, 66.7% reduction is `MECHANISM_OBSERVED` under
`arc3.memory.direction-validation-probes.v0.1`. It isolates one procedural-family mapping and is
not evidence of full-game completion.

A separate long-run measurement inserted 5,000 derived records in 4.040912 seconds. Deterministic
eviction retained 128/128 allowed records; encoded store size was 179,180 bytes within a 524,288
byte limit; traced current/peak allocations were 178,195/185,190 bytes. Snapshot identity was
`sha256:aab4cd55cdb2e3cf278d08137b950758eb21868bc67165cd2ce92c22ed59d1c7`.

## Verification

```text
Ruff check / format (Stage 11 paths): PASS
strict mypy (10 Stage 11 source/script files): PASS
focused pytest without coverage: 12 passed in 2.85s
production public-ID/network/hosted scan: 0 matches
```

Tests cover scope isolation, generic-evidence gating, solution-key rejection, every retrieval
mode, source replay/tamper rejection, deterministic eviction, trace chunk boundaries, snapshot
round trip, process-death resume, pending-action reconciliation, RNG continuity, and the
cross-level comparison.

## Commands

```text
python -m uv run ruff check --no-cache src/arc3/memory scripts/measure_memory.py tests/unit/test_memory_integrity.py tests/unit/test_memory_scopes.py tests/property/test_memory_bounds.py tests/integration/test_memory_checkpoint_resume.py tests/integration/test_memory_cross_level.py tests/replay/test_memory_source_replay.py
python -m uv run ruff format --check --no-cache src/arc3/memory scripts/measure_memory.py tests/unit/test_memory_integrity.py tests/unit/test_memory_scopes.py tests/property/test_memory_bounds.py tests/integration/test_memory_checkpoint_resume.py tests/integration/test_memory_cross_level.py tests/replay/test_memory_source_replay.py
python -m uv run mypy --cache-dir %TEMP%\arc3-stage11-final-mypy src/arc3/memory scripts/measure_memory.py
python -m uv run pytest -q --no-cov --basetemp %TEMP%\arc3-stage11-final-pytest-2 tests/unit/test_memory_integrity.py tests/unit/test_memory_scopes.py tests/property/test_memory_bounds.py tests/integration/test_memory_checkpoint_resume.py tests/integration/test_memory_cross_level.py tests/replay/test_memory_source_replay.py
python -m uv run python scripts/measure_memory.py
rg -ni "https?://|\b(requests|urllib|socket|httpx|openai|anthropic|google\.generativeai)\b|ls20-|ft09-|vc33-" src/arc3/memory
```

## Preserved limits

- The measured reuse fixture supplies the abstract state/rule signature and does not test their
  acquisition from raw frames.
- The long-run measurement bounds derived memory only; raw immutable trace has a separate Stage
  03 budget and still needs integrated Stage 16 profiling.
- Adapter-specific consequence reconciliation after process death remains Stage 12 work.
- Project-authored synthetic results do not establish official environment fidelity.
