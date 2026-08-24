# ARC3 Build 001 Stage 06 — guaranteed rule-change reopening

- Stage status: **FAILED_MECHANISM**
- Evidence label: **synthetic**
- Frozen source: `ec51f7e7d09241f47baa866af897546912d3c611`
- Raw artifact: `sha256:198201b86d6bbbefd01188cdea67bde4297f402a41ca1531a4fb05a527627151`
- Raw self-hash: `sha256:4623ec8b03dbeaa6c4901ca70daaea53747f3918b8a8c49b6d73a80c1d70eb0f`
- Holdout: **SEALED_UNCONSUMED**

The unchanged frozen Stage 06 matrix completed all 112 planned controller executions, but the
mechanism did not meet acceptance. Action-effect rotation passed all 32 cases. Traversability
change reached `WIN` in all 32 cases but passed zero because the trace lacked the candidate-linked
typed successor hypothesis required to match evaluator confirmation. All 32 stationary-noise
episodes also reached `WIN`, recorded `resolved_as_noise`, and opened zero false-positive epochs,
but passed zero because the trace lacked a trigger-sourced candidate with two exact typed recovery
receipts. Four of eight checkpoint pairs passed; all four traversability pairs failed validity.

These are receipt failures, not cosmetic report failures. Terminal completion cannot manufacture
the missing lifecycle evidence. The frozen decision rule therefore requires **FAILED_MECHANISM**,
not `PASS` or `PARTIAL`. Stage 06 is closed as a measured failure and Workflow 001 proceeds to the
independent Stage 07 retrodiction decision without rerunning or weakening this matrix.

## Measured result

| suite | exercised | terminal WIN | accepted | result |
|---|---:|---:|---:|---|
| action-effect rotation | 32/32 | 32/32 | 32/32 | PASS on frozen case predicates |
| traversability flip | 32/32 | 32/32 | 0/32 | FAILED_MECHANISM |
| stationary-noise control | 32/32 | 32/32 | 0/32 | FAILED_MECHANISM |
| checkpoint/resume | 8/8 pairs | n/a | 4/8 | FAILED_MECHANISM |
| trace replay and prefix immutability | 112/112 | n/a | 112/112 | PASS |

Every declared intervention family, timing, seed, palette transform, and action transform was
executed. There were zero dropped cases, shared-prefix preparation failures, controller faults,
invalid requests, resets, or infrastructure failures in Attempt 02. The 112 executions used 2,084
environment actions and produced 53,980 immutable trace events across 1,724 trace files.

## What worked

The action-effect rotation mechanism passed 32/32 identity and transformed cases. Its trace chains
carried ordered contradiction, transition, and discrimination-context support receipts into a
candidate-linked confirmation. The clean preflight 059 independently reproduced the formerly
failing non-lexicographic support case: `WIN` in 18 actions, trigger at action 6, confirmation at
action 7, exact ordered causal closure, and a 24/24-predicate checkpoint pair.

The support-order repair is therefore retained as bounded generic progress. Preflight 058 remains
immutable evidence of the earlier misalignment; the successful repair does not rewrite that failed
trace as having passed.

The bounded content-addressed workspace mapping also worked. Attempt 02 completed all 112
executions without a path failure. Preflight 059 used a runtime root eight characters longer than
Attempt 02, projected a 249-character temporary path, and reported zero filesystem or socket
failures. Official Attempt 01 remains preserved separately as `FAILED_INFRASTRUCTURE`.

## What failed

### Traversability successor closure

All 32 traversability episodes completed within budget, retained predecessor history, excluded
stale plans/models, and re-explored. They still failed the controlling lifecycle predicate. The
independent fold reported a candidate-specific error of the form:

`candidate-linked typed successor hypothesis is absent`

Evaluator confirmation at step 9 did not have a matching controller confirmation or ordered typed
successor chain. The observed `WIN` is therefore evidence only that the environment was completed;
it is not evidence that the frozen contradiction-to-reopening mechanism was established. Both
pre-trigger and post-reopen checkpoint variants for traversability failed `validity`, producing the
four checkpoint misses.

### Stationary-noise closure

The raw aggregate counted 32/32 as `resolved_as_noise`, with zero false-positive reopening events.
That outcome is insufficient under the predeclaration. Every noise case lacked the traceable
candidate-specific closure: no trigger-sourced candidate and no two exact typed causal recovery
receipts linked the outlier to the retained predecessor rule. Consequently all 32 case predicates
failed even though all episodes reached `WIN`.

### Metamorphic acceptance

No intervention metamorphic group (0/16) and no noise group (0/8) met every exact parity predicate.
This does not negate the 32 individually passing action-rotation cases; it is an additional reason
the complete Stage 06 acceptance cannot be promoted.

## Checkpoint and replay

The eight frozen checkpoint pairs split exactly by family:

- action-effect rotation: 4/4 passed, covering both pre-trigger and post-reopen boundaries;
- traversability flip: 0/4 passed, with `validity` false in every pair.

Across the whole matrix, all 112 traces replayed and all 112 pre-trigger prefixes remained byte-
and hash-immutable. All 2,084 environment truth receipts verified. These integrity successes make
the mechanism failure inspectable; they do not change its status.

## Resource and verification evidence

Attempt 02 ran for 849.782134 wall seconds and 717.34375 CPU seconds, within the frozen 900-second
limit. Median execution wall time was 6.57589745 seconds; the maximum was 13.7044736 seconds,
within the 60-second per-execution limit. Peak working-set RSS was 120,565,760 bytes, within the
1 GiB limit. The run used Windows 10, CPython 3.12.14, a 12-logical-CPU AMD64 host, no network, no
hosted inference, and no public assets.

The artifact-embedded checks passed:

- Ruff lint;
- Ruff format over 261 files;
- strict mypy over 154 source files;
- 114 focused unit, integration, and replay tests;
- competition-integrity scan with zero findings;
- action-semantics scan with zero findings;
- socket-deny guard with zero attempts.

Remote CI was green at the frozen source. Push run `32578675235` passed Ubuntu job `97044684125`
and Windows job `97044684065`; pull-request run `32578677426` passed Ubuntu job `97044689987`
and Windows job `97044689898`. Each job installed the locked environment and passed Ruff lint,
Ruff format, strict mypy, the full pytest suite with coverage, and the runtime doctor.

## Preserved failure history

Official Attempt 01 failed before completing its first case because its temporary blob path reached
283 characters on Windows. No result JSON was created. Its ten-file, 16,846,070-byte partial tree
remains preserved with recursive manifest
`sha256:66e31a5df20dbdc5629eae1a063c001cd62e50615519c2c4095422eb77bda080`.

Preflight 058 then proved the bounded path mapping but exposed independent sorting of three causal
support arrays. It reached `WIN` in 18 actions but failed exact support linkage. Its raw file remains
`sha256:b864d5391a45ed12468d8c7a0ec97f6fabe4c5e7cb09ae3b80f140d5e086b91b`
with self-hash
`sha256:9534e8b993f6cda329fc07545bf785b6ab92f91df4c320ef1fef1b436573e23c`.

Preflight 059 passed the repaired case from clean source. Its file hash is
`sha256:13d088883014bc61ae3ad5943e2e87b0c8b8f85b0bd0994263048e0ea37642c0`
and self-hash is
`sha256:4edb729d70ebcd1b5b3cd92de99b8183a7ff198440e51dce2a9201630da2a711`.
This resolves the path-infrastructure and support-order burdens only. The broader Stage 06
traversability, checkpoint, and candidate-specific closure burdens remain open.

## Evidence integrity

- Acceptance receipt: `docs/evidence/001-06-rule-change-reopening.json`
- Predeclaration: `sha256:0bca5f32986c79008cf6ee01a83867262cda591f477239a5b8e9bccd90e37434`
- Raw artifact file: `sha256:198201b86d6bbbefd01188cdea67bde4297f402a41ca1531a4fb05a527627151`
- Raw artifact self-hash: `sha256:4623ec8b03dbeaa6c4901ca70daaea53747f3918b8a8c49b6d73a80c1d70eb0f`
- First-party source hash: `sha256:87b357474403e486f7650169e6269c94bc0f012f0fbb83867b4d7a8fd83a5354`
- Source-identity hash: `sha256:d6e30b0dd2167651953acdb8ad78622f70161d6373667fbac92603ac5140b1c8`

The public partition manifest remains
`sha256:682d5891c2aface54803d9bd1173c55ed21e89856e13b8a478fb9276ee963f2f`.
The Build 000 exposure ledger remains
`sha256:cd9af42ed3a5ef9fa0dc201ddb10e32d2bcccee9df729aa0c7d53077c04c9ad4`;
the Stage 03 exposure ledger remains
`sha256:e02a9fa71206170a6fe2aeefb6935ae25141e2759937657475cead4389bb17aa`.
The holdout remains sealed with zero gameplay events and zero locally acquired assets.

## Limits and next step

- This is `synthetic` mechanism evidence, not `local-public` recovery.
- Completion does not retroactively create missing typed lifecycle receipts.
- No public-holdout, hidden-game, Kaggle, semi-private, or official-private claim is made.
- Stage 07 must freeze its paired retrodiction variants, budgets, measurements, and decision rule
  before execution. Stage 06 is not rerun or weakened.
