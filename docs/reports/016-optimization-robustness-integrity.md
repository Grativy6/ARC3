# Stage 16 — Optimization, robustness, and integrity

- **Stage status:** FAILED_MECHANISM
- **Runtime-profile status:** PASS
- **Robustness status:** FAILED_MECHANISM
- **Measured surface:** synthetic
- **Claim boundary:** NO_GENERALIZATION_CLAIM
- **Measured commit:** `cd3e3aa9cc2c2fa8fbe514b7950862dfe1188783`
- **Measured tree:** `11e2c1ba93a3801dc894cc9c0895c636a31f4b63`
- **Primary evidence:** `docs/evidence/016-competition-profile-acceptance.json`

## Result

The optimized FULL/COMPETITION controller completed the declared 80-action stress workload in
116.26474110002164 seconds and passed all nine frozen runtime-budget checks. Peak whole-process
RSS was 175,210,496 bytes, the immutable trace was 6,837,834 bytes, and the checkpoint directory
was 149,129,938 bytes. The same clean-commit run passed all 11 malformed-input and recovery cases,
all static integrity checks, and the pinned Stage 13 performance regression.

Stage 16 is nevertheless `FAILED_MECHANISM`, not PASS. Four of 12 robustness cases failed their
behavioral predicate: both palette permutations and both action remappings scored 0.0 where their
same-seed base cases scored 1.0. A fifth case, rule-change seed 11, completed after one action
before the changed rule could be exercised and is `NOT_EXERCISED`. The receipt therefore has
`verified=false`, and the wrapper's exit code 1 is the expected fail-closed result.

This is synthetic evidence only. It does not revise the negative Stage 15 `local-public` result,
open the public holdout, or support hidden-game generalization.

## Frozen competition envelope

The configuration hash is
`sha256:512d9e399cba76d6d798620f9090b31cc6e0b648db38dd5caf4eaa575e2d020c`.
It fixes 80 actions, eight resets, 240 seconds per game, 2,048 MiB RAM, 256 MiB each for trace and
checkpoints, 24 coordinate candidates, 10,000 search nodes, depth 32, and two seconds per decision.
Across the documented 110-game, nine-hour competition envelope, 240 seconds per game reserves
6,000 seconds for startup, framework, scoring, and packaging overhead. The controller remained
CPU-only.

The timed fixture was a deterministic 32×32 component-stress environment with 64 components,
seed 25, forced to 80 actions and restarted from sealed checkpoints every eight actions. The
profile ran in a fresh process from clean worktree `C:\a\arc3-s16-cd3e3aa`; imports resolved to
that worktree, not the development checkout.

## Measured runtime

| Measure | Observed | Declared limit | Result |
|---|---:|---:|---:|
| Total workload wall time | 116.26474110002164 s | 240 s | PASS |
| Whole-process peak RSS | 175,210,496 B | 2,147,483,648 B | PASS |
| Trace size | 6,837,834 B / 1,614 events | 268,435,456 B | PASS |
| Checkpoint directory | 149,129,938 B / 162 immutable files | 268,435,456 B | PASS |
| Largest checkpoint | 1,792,247 B | included above | PASS |
| Decision maximum | 0.9290693999500945 s | 2 s | PASS |
| Consequence maximum | 1.3039952999679372 s | 2 s | PASS |
| Explicit checkpoint maximum | 0.8572151999687776 s | 2 s | PASS |
| Restart maximum | 2.6158064999617636 s | recorded, no separate frozen cap | MEASURED |
| Total-step arithmetic mean | 1.4115309074899414 s | 2.727272727272727 s | PASS |
| Total-step maximum | 5.6917618999723345 s | retained, average governs envelope | MEASURED |
| Planner expansion | 2 evaluations; max 3 nodes | 10,000 nodes | PASS |

The total-step acceptance is an aggregate-envelope check: `240 / (80 + 8) =
2.727272727272727` seconds on average. The 5.69-second maximum remains visible and was not
misrepresented as satisfying a per-step maximum. Individual decision, consequence, and explicit
checkpoint maxima each passed their two-second checks. All 80 observation-to-action-to-returned-
consequence chains were complete, replay reconstructed 81 frames and 80 deltas, and no duplicate
event ID or controller fault occurred.

Fresh import through controller-ready took 1.082496999995783 seconds; full fresh-process launch
through clean exit took 1.292819800088182 seconds. Ready-state RSS was 32,460,800 bytes.

## Measured optimization

The Stage 15 representative FULL run had retained 1,679,940 trace bytes and 759 events after only
19 actions, and every public FULL run exceeded 120 seconds. Profiling isolated durable receipt and
checkpoint I/O as a generic bottleneck. The accepted changes:

- keep raw observation, submitted-action, and returned-consequence receipts durable at their
  authority boundaries;
- buffer derived journal events in batches of 128 and flush them before any authority boundary;
- keep a verified live event/tail index so checkpoints bind the current ledger tail without
  reparsing the full journal;
- batch component measurements into one derived perception event;
- avoid a duplicate close-time checkpoint when the latest sealed checkpoint already binds the
  current tail.

Allocator tracing was removed from the authoritative timed pass because a development probe showed
that its instrumentation materially distorted this persistence-heavy workload. Windows kernel
working-set/high-water measurements are the authoritative memory evidence; no unmeasured Python
allocator number was substituted. A dirty development probe with allocator tracing reached only
51/80 actions in 251.3 seconds, while a subsequent no-tracing development probe reached 80/80 in
124.6 seconds. Those probes guided instrumentation design only; neither is promoted as clean-commit
acceptance evidence. The final clean run is the 116.26474110002164-second receipt above.

The frozen budgets and production feature preset were not loosened to obtain the pass. No GPU path,
game identifier, public-game action sequence, or hosted model was added.

## Robustness matrix

| Variant | Seed 7 | Seed 11 | Interpretation |
|---|---|---|---|
| base | PASS; score 1.0; 7 actions | PASS; score 1.0; 1 action | Reference |
| palette | FAILED_MECHANISM; score 0.0 | FAILED_MECHANISM; score 0.0 | Operational trace passed; behavior did not preserve base parity |
| translation | PASS; score 1.0 | PASS; score 1.0 | Terminal phase and score matched base |
| distractor | PASS; score 1.0 | PASS; score 1.0 | Terminal phase and score matched base |
| action-remap | FAILED_MECHANISM; score 0.0 | FAILED_MECHANISM; score 0.0 | Remap boundary was reached; behavior did not preserve score parity |
| rule-change | PASS; 14 change signals | NOT_EXERCISED; base completed first | Seed 7 exposed contradiction/mismatch evidence; seed 11 did not reach the changed rule |

Every case remained operational: each retained complete action chains, zero duplicate event IDs,
and zero controller faults. Operational trace integrity does not convert a behavioral failure into a
pass. Seven of 12 cases pass, four fail the mechanism, and one is not exercised.

## Fault recovery and integrity

All 11 predeclared fault cases passed: malformed observation type, empty frame batch,
non-canonical metadata, out-of-range frame cell, duplicate action space, returned-action mismatch,
action-budget exhaustion, game-over/reset-only behavior, partial checkpoint recovery,
incompatible checkpoint refusal, and an upstream error before consequence. Rejected inputs and
partial artifacts remained preserved where applicable; the previous valid checkpoint remained
loadable.

Static policy, archive, source-identity, dependency/supply-chain, and secret scans all passed with
zero findings. The inventory covered 57 dependencies with no installed-version mismatch and no
unknown or missing license metadata. First-party licensing remains
`OWNER_DECISION_REQUIRED`. This is explicitly static-only assurance: runtime socket denial is
`OUT_OF_SCOPE`, and no OS-level network-denial claim is made.

The pinned Stage 13 evidence still hashes to
`sha256:ab354deec3ef4f7a84d285a8e7603dbe357afcf6c6bbff7862fe94979b94780e`.
The new eight-run compact regression manifest is
`sha256:5f1d68221f99fc9487a6a26d75a64db64c50737a6a3502f909877653f90175eb`;
its regression status is PASS.

An NVIDIA GeForce GTX 1660 with 6,144 MiB was visible through `nvidia-smi`. The production system
is symbolic and CPU-bound, and no measured accelerator mechanism justified a GPU dependency, so
the authoritative run used CPU.

## Evidence and commands

```text
C:\a\arc3-s16-cd3e3aa\.venv\Scripts\python.exe scripts\profile_competition.py --root C:\a\arc3-s16-cd3e3aa --output C:\a\s16-evidence-cd3e3aa\profile.json --work-root C:\a\s16-data-cd3e3aa --frozen-commit cd3e3aa9cc2c2fa8fbe514b7950862dfe1188783
Get-FileHash -Algorithm SHA256 C:\a\s16-evidence-cd3e3aa\profile.json
```

The first command returned 1 because robustness failed, while preserving a complete sealed receipt.
The receipt's canonical self-hash is
`sha256:3c7d407f2b0f1c9705648ac8c5e06adba951567c755e1bbca6ea194a1e668758`;
the receipt file hash is
`sha256:125290f571860cdc2a66a99f8e0bea0f421af1c7d891c488908ebe85cef91bc2`.
Its raw work tree is 173,560,198 bytes across 600 files under `C:\a\s16-data-cd3e3aa`.
High-volume traces and checkpoints remain local and uncommitted; the compact evidence preserves
their identities, metrics, and hashes.

Superseded negative/development receipts remain available at
`C:\a\s16-evidence-30267e2\profile.json`, `C:\a\s16-evidence-f244a63\profile.json`,
`C:\a\s16-opt-probe1`, and `C:\a\s16-opt-probe2`. They were not deleted or substituted for the
authoritative result.

## Boundaries carried forward

- Palette and action-remap robustness are unresolved failed mechanisms.
- Rule-change seed 11 is not evidence about adaptation because it ended before the change.
- The public development policy was not rerun after optimization; Stage 15 remains the only
  measured `local-public` result and remains negative.
- The public holdout remains deliberately unconsumed.
- No `online-public`, `Kaggle-public`, `semi-private`, or `official-private` result exists.
- Static reachability checks do not prove OS-level network denial.
- This stage does not establish hidden-game generalization, PAL, AGI, consciousness, or a general
  theory of intelligence.
