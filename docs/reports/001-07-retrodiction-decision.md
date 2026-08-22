# Build 001 Stage 07 — Retrodiction decision

Status: **FAILED_INFRASTRUCTURE**

Evidence labels: **synthetic**, **local-public**

Production decision: **KEEP_FULL by fail-closed rule; no measured winner**

## Result

The one frozen Stage 07 attempt did not complete its declared comparison. From clean source commit
`f683dbc672213e804ddc6120b0be2762e6c66a08`, it created 279 of 280 matrix cell directories,
executed no microbenchmarks, then raised `KeyError` while final integrity processing indexed the
absent last cell. No official result JSON was written and none will be retroactively synthesized.
The attempt is immutable and will not be rerun in Build 001.

The failure occurred after the explicit 3,600-second loop guard broke execution following ordinal
278. Exact process-local wall, CPU, RSS, and raw `CellMeasurement` values were lost when the process
raised before serialization, so this report makes no numeric resource claim beyond the executable
control-flow boundary and filesystem timestamps.

## What the partial receipts do establish

The individually sealed Group B receipts recover a bounded `synthetic` mechanism result:

| Mode | True candidate | False candidate | Checkpoint roundtrips |
|---|---:|---:|---:|
| `FULL` | promoted 8/8 | rejected 8/8 | 16/16 |
| `NONE` | ungated 8/8 | ungated 8/8 | 16/16 |
| `RECENT_WINDOW_8` | promoted 8/8 | incorrectly promoted 8/8 | 16/16 |
| `EVENT_TRIGGERED` | promoted 8/8 | rejected 8/8 | 16/16 |
| `CACHED_INCREMENTAL` | promoted 8/8 | rejected 8/8 | 16/16 |

The 40 receipt files total 850,188 bytes and have canonical inventory SHA-256
`7c7f2f36f7ad0b17df85007f0c4e64c5865481c92cc4f7f34f818a089c00a533`.
This shows that the bounded recent window missed the deliberately rare contradiction in all eight
histories. It does not recover the paired cost measurements or satisfy a replacement gate.

All nine attempted Group D rows—five modes at seed 7 and four at seed 23—failed identically with
`WorldModelError: mechanics transition bound exceeded for epoch`. Each immutable trace prefix has
1,702 valid hash-linked events, including 65 submitted actions and 65 returned consequences. Each
remained `NOT_FINISHED`, completed zero levels, and had no terminal scorecard before the fault.
Their canonical trace-summary projection is
`95ec8fddc04499f8f68411d5ba112670f219d87a74b5a8511cd6fdab2be364e6`.
Across the nine prefixes this is 15,318 events and 585 action/consequence pairs. No model,
mechanics, hypothesis, planning, simulation, or retrodiction event occurred before the fault, so
this is `local-public` evidence for a shared fixed lifecycle-bound failure—not evidence that one
retrodiction mode outperformed another. Hash-chain validation is not reported as completed replay.

No aggregate A/C result is claimed because those cell measurements existed only in process memory.
No D terminal scorecard, after-episode asset snapshot, or exact resource receipt is claimed.

## Failure chain

The exact command was:

```text
C:/a/arc3-b001-28c7a00/Scripts/python.exe scripts/measure_retrodiction_decision.py --execute --output C:/a/arc3-b001/artifacts/stage07/retrodiction-decision-attempt-01.json --work-root C:/a/arc3-b001/artifacts/stage07/retrodiction-decision-work-attempt-01 --exposure-ledger C:/a/arc3-b001/artifacts/stage07/public-exposure.jsonl --environments-dir C:/a/arc3-s15-6a0f6e5/artifacts/stage15/public-environments --recordings-dir C:/a/arc3-b001/artifacts/stage07/development-recordings
```

It returned exit 1 at:

```text
scripts/measure_retrodiction_decision.py:2084:_apply_global_integrity
KeyError: 'stage07-cell-279-D-3ded77000d47d823'
```

The partial work tree contains 6,615 files and 1,854,364,170 bytes, with canonical recursive
inventory SHA-256 `fa79526cc91c096fa38868fe4aa11e52cad6c8f0fe8c804ebe00806ee6f4f62e`.
Five post-loop verification commands passed before aggregation raised: focused pytest, Ruff lint,
Ruff format, strict mypy, and the competition-integrity scan. The development exposure ledger has
nine events and SHA-256 `4f924df44b11decb392022a927b3296e0248a02edac2c87c53899d374045f0c7`.

## Repair and verification

Commit `85a0782e77e0549814363cbeefd50bb5eec6ca3c` makes global integrity total over an actually
completed measurement prefix. Existing exact-count and resource gates still force an incomplete
run to `PARTIAL`, `KEEP_FULL`, and exit 1. It does not resume or alter the official attempt.

Verification:

- 150 Stage 07 unit, property, integration, replay, offline-integrity, and secret tests passed in
  57.95 seconds;
- the 279-measurement regression preserves exact cell order without indexing the absent cell;
- the CLI regression writes a partial artifact and returns exit 1;
- Ruff lint/format and strict mypy passed;
- competition integrity and action-semantics scans passed with zero findings.

The first version of the prefix regression incorrectly required all recomputed measurements to be
value-identical. It failed because global integrity legitimately recalculates cache parity. The
test was narrowed to the actual invariant—same measured IDs and order, absent cell omitted—and
then passed. This test-development failure is not experiment evidence.

## Decision and burdens

`FULL` remains production default because no candidate passed the frozen gates. This is a
fail-closed retention decision, not evidence that FULL won on cost or completion.

`B-001-0041` is resolved by the partial-serialization regression. Open burdens remain:

- `B-001-0039`: in-process non-return lacks worker supervision;
- `B-001-0040`: historical rank lacks a prefix-derived authority fold;
- `B-001-0042`: the 64-transition epoch bound stops every attempted public row;
- `B-001-0043`: exceptional public-cell exit loses terminal asset/resource/scorecard receipts.

The ten-game public holdout remains sealed and unconsumed: zero gameplay events and zero local
holdout assets.

Primary machine receipt: `docs/evidence/001-07-retrodiction-decision.json`.
Failed-attempt receipt: `docs/evidence/001-07-failed-infrastructure-attempt-01.json`.
