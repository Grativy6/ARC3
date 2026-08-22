# ARC3 Build 001 Stage 04 — palette equivariance

- Stage status: **PASS**
- Evidence label: **synthetic**
- Frozen source: `86134755f3f26a268585b14264946571592cd4a5`
- Frozen tree: `df3204136e44d66b30bff455815a10c5ba9efa84`
- Holdout: **SEALED_UNCONSUMED**

The generic palette-role repair met every frozen Stage 04 predicate. Both actual Build 000 palette
failures now complete, all 256 full-domain paired bijections preserve exact requested actions and
outcomes, all 16 restart pairs preserve the registry and continuation, and all 64 color-causal
controls distinguish one-sided recoloring while accepting joint relabeling. This is bounded
synthetic mechanism evidence, not local-public recovery or hidden-game generalization.

## Measured result

| suite | required | observed | result |
|---|---:|---:|---:|
| historical palette regressions | 2 | 2 exact paired completions | PASS |
| procedural pairs | 256 | 256 exact | PASS |
| checkpoint/resume pairs | 16 | 16 exact | PASS |
| joint palette controls | 64 | 64 equivalent | PASS |
| one-sided color controls | 64 | 64 distinguishable | PASS |

The procedural suite used 32 seeds and eight deterministic bijections per seed over all 16 ARC
colors, including mappings where the measured background is not zero. Each of the 256 cases had an
initial raw-frame hash different from its base while preserving the canonical role projection,
terminal phase, score, completion status, exact action-request sequence, trace integrity, and replay.
All 32 base episodes completed in 192 actions; the 256 transformed counterparts completed in 1,536
actions, exactly eight times the reused base total.

The checkpoint suite completed all 16 uninterrupted and all 16 resumed episodes in 96 actions per
side. Registry serialization, restored symbolic projection, next action, terminal result, replay,
and the no-resubmission invariant matched in every case. The registry's configured bound was 16;
the maximum observed registry size was three entries.

The color-causal controls did not erase color. Applying the same bijection to both sides of a
transition preserved the canonical transition in 64/64 cases. Applying it to only one side remained
distinguishable in 64/64 cases and retained 33–34 raw `RECOLOR` measurements per case.

## Historical-case accounting

The workflow's inherited phrase “four Build 000 palette failures” is broader than the frozen
evidence: two cases are palette permutations and two are action remaps. Stage 04 owns and repairs the
two palette cases; the action-remap obligation remains in Stage 05.

| seed | Build 000 base | Build 000 palette | Build 001 base | Build 001 palette |
|---:|---:|---:|---:|---:|
| 7 | win, 7 actions | loss, 16 actions | win, 7 actions | win, 7 actions |
| 11 | win, 1 action | loss, 16 actions | win, 3 actions | win, 3 actions |

The repair restores exact base/permutation behavior, but it does not improve every base trajectory.
Seed 7 remains at seven actions; seed 11 changes from one to three. Across the two unpermuted cases,
the total rises from eight to ten actions, a 25% increase. That bounded efficiency regression is
preserved rather than hidden behind the successful equivariance result.

## Representation and raw provenance

Raw `GridFrame` cells, frame hashes, palette receipts, component colors, deltas, and immutable trace
events remain exact. A separate level-scoped registry assigns structural palette roles from observed
background, geometry, occupancy, and history. Its raw-color-free projection is used for paired
comparison; its derived state can be revised or restored without rewriting raw observations.
Structurally indistinguishable colors may remain explicitly ambiguous instead of acquiring semantic
meaning from their numeric labels.

Every procedural pair verified its trace chain and replay. Across the 324 measured episodes, 48,598
trace events in 2,521 files replayed, with zero controller faults. All checkpoint cases verified the
serialized registry and trace continuation. All 256 nonidentity mappings changed the initial raw
hash, which demonstrates that equivalence was not manufactured by reusing identical observations.

## Runtime and verification

The clean official measurement ran for 225.4006992 wall seconds and 189.125 CPU seconds. Median bulk
episode wall time was 0.3599957 seconds; the maximum process peak RSS recorded across cases was
54,927,360 bytes. This passed the frozen 600-second limit on Windows 10, CPython 3.12.14, a 12-logical-
CPU AMD64 host, ARC3 0.1.0, NumPy 2.5.2, and Pydantic 2.13.4.

Focused verification passed 13 tests; the broader controller/perception/replay/profiling subset
passed 68/68, and offline integrity checks passed 11/11. Ruff checking, Ruff formatting for the six
Stage 04 files, strict mypy across 148 source files, diff checking, raw-artifact self-hash
verification, trace verification, and replay all passed. Pytest used a fresh explicit short-path
`--basetemp` because the default Windows user temp root is ACL-inaccessible in this environment.

## Evidence integrity

- Acceptance receipt: `docs/evidence/001-04-palette-equivariance.json`
- Predeclaration: `sha256:9df1df67641a642234cde2494b1ac53a55524778284f8af2c0aa0a9d727c6d32`
- Raw artifact file: `sha256:cad09761d4f361e2b072a54a3525a90b0c8f10961dc8fd041da8b08abc6b3108`
- Raw artifact self-hash: `sha256:c76ad6ecf0c956b51579b27d6543734e7368ca48fb0cadfce3134735be895676`
- First-party source hash: `sha256:86d67d1de5ae94394aa193dc649485e6a65d2fafc68fd969c3c6af6747055865`
- Source-identity hash: `sha256:210508d0bd9195fb5505cbeb89d2431b415024ce261516aecf0b18f12854c563`

The public partition manifest remains
`sha256:682d5891c2aface54803d9bd1173c55ed21e89856e13b8a478fb9276ee963f2f`.
The Stage 04 measurement harness was synthetic-only and accessed no public-game asset, adapter,
source, or episode. The post-measurement integrity check read only the already-sealed partition
manifest and exposure-ledger metadata.
The Build 000 exposure ledger remains bound at
`sha256:cd9af42ed3a5ef9fa0dc201ddb10e32d2bcccee9df729aa0c7d53077c04c9ad4`;
the Stage 03 ledger remains bound at
`sha256:e02a9fa71206170a6fe2aeefb6935ae25141e2759937657475cead4389bb17aa`.
The public holdout remains at zero gameplay events and zero locally acquired assets.

## Limits

- This result is `synthetic`; it does not establish `local-public` recovery.
- The 32 verified base episodes are reused across eight paired bijections per seed.
- Whole-process peak RSS can include earlier cases in the same process.
- The seed-11 base efficiency regression remains open for later controller evaluation.
- Action-ID equivariance remains an independent Stage 05 obligation.
- No public-holdout, hidden-game, Kaggle, semi-private, or official-private claim is made.
