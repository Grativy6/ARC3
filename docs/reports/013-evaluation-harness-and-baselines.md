# Stage 13 — Evaluation harness, partitions, and baselines

- **Stage status:** PASS
- **Measured surface:** synthetic
- **Claim:** NO_GENERALIZATION_CLAIM
- **Measured commit:** `01f7a12e42f50e2899db9d430bcf4d125a81d49f`
- **Primary evidence:** `docs/evidence/013-evaluation-harness-acceptance.json`

## Result

ARC3 now has a spawn-isolated evaluation harness with per-run action, reset, wall-clock, and
memory envelopes; deterministic seeds; crash/timeout recovery; immutable failure retention; and
sealed JSON/JSONL/Markdown artifacts. The CLI implements `evaluate`, `compare`, `report`, and
`verify-artifacts`. A terminal evaluation is immutable: a matching request verifies and reuses
it, a changed identity is rejected, and tampered or interrupted attempts are preserved before a
new run can begin.

Every result binds the Git commit, a first-party source hash, configuration, upstream lock,
partition manifest, threshold declaration, runtime, hardware summary, scorer source, seeds,
budgets, timestamps, and network mode. B3 action/consequence receipts replay through the Stage 03
ledger. B4 constructs the genuine full `ARC3Controller`; it is not an alias for a simpler
baseline. Reproduction uses an executable absolute Python argv and does not depend on `uv` being
available on `PATH`.

## Clean B0–B4 comparison

The final receipt came from a clean detached worktree at the measured commit. It ran two seeds,
16 actions per run, two resets, a 30-second worker budget, and no network:

| Baseline | Policy | Runs | Completed | Actions | Mean synthetic score |
|---|---|---:|---:|---:|---:|
| B0 | random valid | 2/2 | 0 | 32 | 0.0 |
| B1 | deterministic cycle | 2/2 | 1 | 19 | 0.5 |
| B2 | novelty only | 2/2 | 0 | 32 | 0.0 |
| B3 | trace plus local action statistics | 2/2 | 1 | 19 | 0.5 |
| B4 | full ARC3 controller | 2/2 | 2 | 8 | 1.0 |

All 10 workers succeeded. B4 used seven actions on seed 7 and one on seed 11; B1/B3 used 16 and
three; B0/B2 exhausted 16 on both. Official RHAE remains `null`. The sealed manifest is
`sha256:dad6c9a7ff00bb8bb60bbd68b204cf4dfd33032a1122bb1b1439b86a59771f73`.

Executing the generated reproduction argv created a new 10-run evaluation. Both artifact sets
verified, and all five same-policy comparisons had exactly zero score delta and exactly zero
action delta. The reproduced manifest is
`sha256:6d8e9bd535a8c106cbb66943f689ef23623d430506ee4c1048bb4f85a856d30b`.

## Pinned performance gate

The threshold declaration applies only to B0–B3 on seeds 7 and 11 with a 16-action, eight-reset,
30-second envelope. The clean run passed 8/8 receipts and all four policies:

| Metric | Observed maximum | Gate |
|---|---:|---:|
| invalid-action rate | 0.0 | 0.0 |
| Python traced peak bytes | 1,445,249 | 2,097,152 |
| decision p95 seconds | 0.000189000 | 0.01 |
| worker wall seconds | 0.734858 | 2.0 |

The threshold manifest is
`sha256:d4743c22264be7996999fc1af87da3cde69e7331af6a050a42a9ef0a91b83957`.
This gate intentionally excludes process startup, whole-process RSS, and B4. Those are later
profiling burdens, not silently implied by a passing compact-worker threshold.

## Failure and tamper behavior

Focused tests force abnormal exit, timeout escalation, terminal tampering, and interrupted-run
tampering. The harness keeps the original run, trace, checkpoint, and failure receipt; it neither
drops the failure nor launders it through a later pass. Verification recomputes hashes, closed-set
membership, identity, score/metric semantics, threshold status, run IDs, budgets, and
action/consequence pairing.

One root rerun failed 1/26 because a parallel Stage 14 worker changed first-party source while a
test reopened a terminal evaluation. That is the intended identity rejection, not a stable-tree
harness failure. Filesystem writes were paused, the same suite passed 26/26, and final evidence
was generated from a clean detached worktree. Earlier 1 MiB calibration, fresh-worker, and
non-executable reproduction failures remain listed in the evidence rather than relabeled.

## Verification

```text
focused pytest without coverage: 26 passed in 24.04s
Ruff check: PASS
Ruff format: 13 files already formatted
strict mypy: 8 source files clean
controlled evaluation: 10/10 PASS; 0 failures
threshold evaluation: 8/8 PASS; 0 failures
original and reproduction artifact verification: PASS
same-policy reproduction: 5/5 exact score and action matches
```

## Commands

```text
python -m arc3 evaluate --partition smoke --agents random,cycle,novelty,trace,full --seeds 7,11 --max-actions 16 --max-resets 2 --timeout-seconds 30 --output-root C:\a\s13-evidence-01f7a12 --evaluation-id stage13-clean-01f7a12
python -m arc3 verify-artifacts --evaluation stage13-clean-01f7a12 --output-root C:\a\s13-evidence-01f7a12
python -m arc3 report --evaluation stage13-clean-01f7a12 --output-root C:\a\s13-evidence-01f7a12
python -m arc3 compare --evaluation stage13-clean-01f7a12 --evaluation eval-20260821T080648890647Z-d99370f32331 --output-root C:\a\s13-evidence-01f7a12
python -m arc3 evaluate --partition smoke --agents random,cycle,novelty,trace --seeds 7,11 --max-actions 16 --max-resets 8 --timeout-seconds 30 --output-root C:\a\s13-evidence-01f7a12 --evaluation-id stage13-threshold-clean-01f7a12
```

## Preserved limits

- The comparison uses two seeds of one compact first-party synthetic environment.
- No public environment was opened, and no official RHAE was measured.
- Python traced allocation is not whole-process RSS; worker time excludes spawn startup.
- Hash seals detect mutation but do not provide external signatures or independent authenticity.
- These results do not establish PAL, AGI, consciousness, or a general theory of intelligence.
