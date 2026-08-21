# Stage 03 — Immutable trace, replay, and checkpoint

- **Stage status:** PASS
- **Measured surface:** synthetic
- **Measured at:** 2026-08-21
- **Repository base during measurement:** `9ee31a453cfa1b52c1cb99b6cf0a2bc7ac52e61a` with Stage 03 files uncommitted
- **Primary evidence:** `docs/evidence/003-trace-acceptance.json`

## Result

ARC3 now records raw observations, candidate-action summaries, selected actions, submitted
actions, and returned consequences as validated append-only events. Each event has a canonical
JSON representation, content hash, previous-event hash, source identity, code/config identity,
UTC timestamp, and stable step scope. Raw frame bodies live in a write-once content-addressed
blob store; the journal retains their hashes and dimensions.

The baseline runner accepts a narrow receipt sink rather than importing trace implementation
types. Its trace integration records exactly what existed before acting, the generic candidates
and selection rationale, the submitted action, and the returned consequence. Concise rationale
categories are validated; free-form hidden chain-of-thought is neither required nor stored.

## Immutable and revisable boundaries

Immutable sources are:

- raw observation-frame blobs;
- submitted actions and returned consequences;
- event payloads, ordering, timestamps, and source/code/config identities;
- sealed chunk hashes and manifests.

Replaceable derived products are:

- episode and hypothesis indices;
- summaries and rendered frame deltas;
- checkpoints and current controller state;
- schema-migrated copies.

Migration is non-destructive: a new journal is created with a manifest tying every destination
event to its source event hash. The original trace is not rewritten.

## Replay and interruption recovery

Replay validates the manifest and complete event chain before reconstructing frames. It can
render raw frames, compute/apply deltas, recover decision inputs visible at a chosen action, and
build source-cited summaries. A summary claim without supporting event IDs is rejected.

Checkpoints preserve the Python RNG state, exact trace-tail event/hash, run and episode IDs,
repository commit, configuration hash, and replaceable state. Resume rejects mismatched code,
configuration, run, episode, or trace position. The tested interruption path restores the RNG
and derived state, resumes from the same trace tail, and produces the same subsequent receipts
as uninterrupted execution.

## Fault-injection acceptance

All required faults were injected and detected:

- a partial final JSONL append is truncated while prior complete events survive;
- a changed byte in a sealed chunk fails content verification;
- a missing frame blob fails replay rather than inventing a frame;
- wrong code/config/trace checkpoint identities fail resume and can emit a rejection receipt;
- duplicate event IDs are rejected;
- a broken previous-event hash is rejected.

Optional gzip copies are hash-verified and indexed alongside the authoritative uncompressed
chunk. Derived indices can be deleted and deterministically rebuilt from verified events.

## Verification

```text
Ruff check / format (Stage 03 paths): PASS
strict mypy (11 Stage 03 source files): PASS
focused pytest: 29 passed in 9.14s
baseline trace integration: PASS
fault-injection suite: PASS
```

The focused suite covers schema validation, canonicalization, hash continuity, blob
deduplication, append/flush/seal/compress/recovery, manifests, index rebuilding, replay,
summary provenance, migration, checkpoint identity/RNG restoration, long-episode behavior,
property tests, interruption equivalence, and the instrumented baseline episode.

## Measured overhead

One local synthetic benchmark on the recorded Windows/Python host appended 500 concise events
in 0.3117981 seconds (0.623596 ms/event), verified/retrieved them in 0.0877939 seconds, and
used 77,106 peak Python-traced bytes while appending. The active trace occupied 381,211 bytes.
A canonical 64×64 frame occupied 8,321 bytes; 100 repeated writes created zero duplicate blobs
and took 0.285372 seconds. A representative RNG/state checkpoint occupied 7,259 bytes.

These values satisfy the test's conservative local thresholds of 20 ms/event, 2 seconds for
500-event retrieval, and 32 MiB peak traced allocation. They are **synthetic** measurements on
one host, not proof of Kaggle runtime fit. Stage 16 must re-profile the integrated controller,
and Stage 14 must test whether this trace machinery improves any measured outcome.

## Commands

The acceptance run used the locked environment:

```text
python -m uv run ruff check src/arc3/baseline_runner.py src/arc3/trace scripts/benchmark_trace.py tests/unit/test_trace_schema.py tests/unit/test_trace_journal.py tests/unit/test_trace_checkpoint.py tests/unit/test_trace_performance.py tests/property/test_trace_properties.py tests/replay/test_trace_replay.py tests/integration/test_trace_episode.py tests/integration/test_traced_baseline.py
python -m uv run ruff format --check src/arc3/baseline_runner.py src/arc3/trace scripts/benchmark_trace.py tests/unit/test_trace_schema.py tests/unit/test_trace_journal.py tests/unit/test_trace_checkpoint.py tests/unit/test_trace_performance.py tests/property/test_trace_properties.py tests/replay/test_trace_replay.py tests/integration/test_trace_episode.py tests/integration/test_traced_baseline.py
python -m uv run mypy src/arc3/baseline_runner.py src/arc3/trace
python -m uv run pytest -q --basetemp %TEMP%\arc3-root-stage03-pytest tests/unit/test_trace_schema.py tests/unit/test_trace_journal.py tests/unit/test_trace_checkpoint.py tests/unit/test_trace_performance.py tests/property/test_trace_properties.py tests/replay/test_trace_replay.py tests/integration/test_trace_episode.py tests/integration/test_traced_baseline.py
python -m uv run python scripts/benchmark_trace.py --git-commit 9ee31a453cfa1b52c1cb99b6cf0a2bc7ac52e61a --events 500 --frame-repeats 100
```

The complete numeric output, runtime identity, fault matrix, and exact commands are preserved
in the primary JSON evidence and git history.

## Preserved limits

- The current measured trace is synthetic and short relative to a full competition campaign.
- Raw receipts are immutable, but filesystem access controls and external archival durability
  remain deployment concerns.
- Successful replay proves reproducibility of recorded inputs and transitions, not that the
  chosen action or hypothesis was correct.
- No score benefit is claimed. The full-vs-trace-ablation test remains open for Stage 14.
