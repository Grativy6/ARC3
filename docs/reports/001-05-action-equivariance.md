# ARC3 Build 001 Stage 05 — action equivariance

- Stage status: **PASS**
- Evidence label: **synthetic**
- Frozen source: `43713f8add4495cb48e15d9edab402564ab8b8da`
- Frozen tree: `c002b634f5536839fc96b64e827e0a03c71e6c02`
- Holdout: **SEALED_UNCONSUMED**

The learned-action repair met every frozen Stage 05 mechanism predicate. Both historical Build 000
action-remap failures now complete, all 128 procedural pairs preserve exact post-calibration
inverse requests and canonical trajectories, all 64 causal controls retain the distinctions the
registry is required to preserve, and all 16 restart pairs resume exactly. Production scanning
found no unjustified cardinal, `ACTION6`, `ACTION7`, public-game, or game-specific action semantics.
This is bounded synthetic mechanism evidence, not local-public recovery or hidden-game
generalization.

## Measured result

| suite | required | observed | result |
|---|---:|---:|---:|
| historical action-remap regressions | 2 | 2 paired completions | PASS |
| procedural action-remap pairs | 128 | 128 exact | PASS |
| post-calibration inverse requests | 100% | 528/528 | PASS |
| causal ambiguity/identity controls | 64 | 64 | PASS |
| checkpoint/resume pairs | 16 | 16 exact | PASS |
| production action-semantics findings | 0 | 0 | PASS |

The procedural suite comprised 96 full four-handle pairs, eight partial two-handle pairs, eight
partial three-handle pairs, and 16 mixed coordinate/point-free pairs. Every pair preserved the
canonical effect trajectory, post-prefix state trajectory, completion, score, terminal phase,
validity, trace chain, and replay. The 16 mixed-coordinate pairs also preserved the exact
post-calibration `ACTION6` coordinate and consequence.

The base and permuted sides each used 1,016 actions and zero resets. Their per-family inverse
counts were 384/384, 32/32, 32/32, and 80/80 respectively, totaling 528/528. Each pair supplied at
least four eligible actions after calibration. The two-, three-, or four-action calibration prefix
was included in every action count and resource measurement; only that unavoidable pre-evidence
prefix was excluded from the inverse-request fraction under the frozen declaration.

## Historical-case and efficiency accounting

| seed | Build 000 base | Build 000 action remap | Build 001 base | Build 001 action remap |
|---:|---:|---:|---:|---:|
| 7 | win, 7 actions | loss, 16 actions | win, 9 actions | win, 9 actions |
| 11 | win, 1 action | loss, 16 actions | win, 3 actions | win, 5 actions |

Both historical failures are repaired, but the action cost is not an improvement. The unpermuted
total rises from eight Build 000 actions to 12 Build 001 actions, a four-action or 50% regression.
The two Build 001 remapped cases require 14 actions, two more than their paired bases. These charged
calibration costs remain visible; no completion result is used to erase or relabel the efficiency
regression. Full-sequence inverse equality is not claimed for the historical cases because their
identical initial observations provide no evidence with which to distinguish opaque permuted
handles before calibration, and one case terminates within that boundary.

## Causal controls and revisable semantics

All four 16-case control families passed:

- multi-object displacements retained two `AMBIGUOUS` translation candidates rather than choosing
  one from raw identity or component order;
- conditioned no-op and movement receipts remained separate candidates for the same opaque handle;
- restore behavior was learned only from receipts for `ACTION2` in six cases, `ACTION5` in five,
  and `ACTION7` in five, while all 16 `ACTION7` negative controls rejected name-derived undo;
- coordinate-local and coordinate-distant changes were distinguished in eight cases each, so the
  `ACTION6` wire shape did not manufacture selection semantics.

The controls preserved 91 raw receipts and passed 64/64 registry serialization roundtrips. Across
the controller-driven suites, 292 episodes issued 2,314 environment actions, wrote 55,707 immutable
trace events across 2,187 trace files, and produced zero invalid requests, controller faults,
action/reset-budget violations, or replay failures. The maximum episode used nine actions.

The level-scoped registry remained below its declared bounds: at most four of seven handles, two of
32 candidates per handle, and five candidates total were observed across 546 projections. Raw
receipts and candidate source identities remain immutable; learned effects, displacement facets,
bindings, plans, and checkpoint projections remain derived and revisable.

## Checkpoint and resume

All 16 uninterrupted and 16 resumed counterparts completed in eight actions each, totaling 128
actions per side. The boundary registry, calibration cursor, next canonical choice, resolved raw
request, final action/effect/state trajectories, result, trace verification, and replay matched.
No resumed controller resubmitted the already returned calibration consequence.

## Preserved failed mechanism

The first implementation made whole-effect identity too coarse: a translation that also restored a
prior digest became a separate semantic identity from the same stable displacement. The paired
smoke at `C:/a/arc3-b001/stage05-smoke-pair-02` achieved only 5/12 inverse requests, and an
integrated compatibility run reached 15/16 seeds because seed 13 exhausted its action budget.

That failure remains preserved in a 45-file, 3,030,753-byte bundle at
`C:/a/arc3-b001/artifacts/stage05/failed-mechanisms/seed13-pre-translation-facet`; its active trace
hash is `sha256:0f14f37dad736d3f279920949b4e2c54911d916a124a00493337efa7cdfc9c76`.
The repair keeps the complete effect revisable while resolving a conditioned displacement facet
only when every live candidate supports the same non-null translation. The follow-up smoke passed
4/4, all six seed-13 permutations passed, focused verification passed 67/67, and the clean official
matrix passed 128/128. The later success does not erase the failed approach or its receipts.

## Runtime and verification

The corrected clean official measurement ran for 238.9817805 wall seconds and 218.109375 CPU
seconds. Median episode wall time was 0.3869605 seconds; the maximum was 0.9526158 seconds. Peak
process RSS was 66,064,384 bytes. These measurements passed the frozen 600-second full-run,
60-second per-episode, and 1 GiB RSS limits on Windows 10, CPython 3.12.14, a 12-logical-CPU AMD64
host, ARC3 0.1.0,
NumPy 2.5.2, and Pydantic 2.13.4.

Before the coordinate-bound correction, focused verification passed 67 tests, the broad Stage
04/05 subset passed 114/114, the post-trace subset passed 30/30, and offline controller integrity
passed 11/11. On the corrected but intentionally dirty worktree, the full suite reported 492 passed
and exactly two source-identity guard failures in 502.18 seconds. After commit, the 17-test changed
mechanism/expectation subset passed in 6.57 seconds and both clean-source guard tests passed in 7.84
seconds. The standalone action-semantics scan on the corrected source returned zero findings with
receipt
`sha256:f050c5208445c9d0fd7679e539437c06338be0335076f7ec8f8a870a11d3098c`.
The earlier competition-integrity secret scan reported zero findings.

Remote CI is green on the corrected source. Push run `32557369468` passed on Ubuntu job
`96993584811` in 4m17s and Windows job `96993584903` in 7m4s. Pull-request run `32557371792`
passed on Ubuntu job `96993590721` in 4m12s and Windows job `96993590806` in 7m21s. Each job
installed the locked environment and passed repository-wide Ruff lint, Ruff format, strict mypy,
the full pytest suite with coverage, and the runtime doctor.

## Preserved superseded official run

The first clean official artifact at commit `291e73e197fb9425465c072923804b2a377fbfb8`
passed the frozen synthetic matrix, but remote CI exposed contradictory repository evidence. The
calibration coordinate was prepended after truncating coordinate candidates, so a configured bound
of two could yield three legal requests. CI also showed that two ablation tests still described
pre-Stage-05 behavior: world models before transition evidence and coordinate candidates before the
charged calibration request.

Commit `43713f8add4495cb48e15d9edab402564ab8b8da` applies the generic bound to the complete candidate
sequence after calibration is prepended and updates only those contradicted test expectations. The
unchanged frozen harness was then rerun from clean source. The superseded artifact remains at
`C:/a/arc3-b001/artifacts/stage05/superseded-291e73e/action-equivariance.json`, with file hash
`sha256:6280fbe932fec3fa23fae6ba430093ca94a10135b052370673a801e38ff56a02` and valid core hash
`sha256:e40b4065765bda7c55d1a08e4f68b25c55fa3d9bb39ffeedf58b3b79d36154f1`.

## Evidence integrity

- Acceptance receipt: `docs/evidence/001-05-action-equivariance.json`
- Predeclaration: `sha256:ec4ed1a8b3b8d4904a38bf4533d9fbd61975cac61aea05d4313d4b6a47119ce2`
- Raw artifact file: `sha256:48141af44742c0955f30086f73b1983e6274362e150195ff88065be2b30ea797`
- Raw artifact self-hash: `sha256:b2ea83ff85f50f005e8630e34857741b70471b232781464fa8e3825d6f33bc07`
- First-party source hash: `sha256:9edc1029698e7f091babcb6252c34adde9613db240ff7aec090ed4a92edaf463`
- Source-identity hash: `sha256:e0b3c8cd67254fd206bc407a87c88cb7ae32cbc6ea29fd403ff825d02a73e8f3`

The public partition manifest remains
`sha256:682d5891c2aface54803d9bd1173c55ed21e89856e13b8a478fb9276ee963f2f`.
The Build 000 exposure ledger remains bound at
`sha256:cd9af42ed3a5ef9fa0dc201ddb10e32d2bcccee9df729aa0c7d53077c04c9ad4`;
the Stage 03 exposure ledger remains bound at
`sha256:e02a9fa71206170a6fe2aeefb6935ae25141e2759937657475cead4389bb17aa`.
The synthetic-only harness used no public-game episode, source, asset, adapter, network, hosted
inference, or holdout. The holdout remains at zero gameplay events and zero locally acquired assets.

## Limits

- This result is `synthetic`; it does not establish `local-public` recovery.
- Calibration is a charged symmetry breaker, not free interaction or inferred gameplay meaning.
- Full-sequence inverse equivalence is not claimed before differing transition evidence.
- Historical base efficiency regresses from eight to 12 actions across the two cases.
- Whole-process peak RSS can include earlier cases in the same process.
- The superseded clean run remains historical evidence and is not used as the final Stage 05 source.
- No public-holdout, hidden-game, Kaggle, semi-private, or official-private claim is made.
