# ARC3 Build 001 Stage 03 — causal throughput diagnosis

- Stage status: **PASS**
- Evidence labels: **synthetic**, **local-public**
- Frozen measurement source: `515177c2b640efbdbfd92eca117aff1e42637e98`
- Holdout: **SEALED_UNCONSUMED**

Two material throughput causes passed the predeclared intervention threshold with exact matched
behavior: global Python allocation tracing and automatic whole-state checkpoint persistence. These
are distinct engineering findings, not a gameplay recovery result. Every development cell used the
same already-exposed game, seed, eight-action budget, source tree, offline asset, and FULL/B4 policy.
Every cell produced the same eight normalized action decisions, the same nine observation outcomes,
zero completed levels, score 0.0, 241 immutable trace events, and verified replay.

| local-public cell | wall seconds | wall/action | action selection | checkpointing |
|---|---:|---:|---:|---:|
| tracing on, checkpoints on | 46.0703 | 5.7588 | 22.4338 s | 8.0074 s |
| tracing off, checkpoints on | 8.8449 | 1.1056 | 3.3181 s | 1.9192 s |
| tracing on, checkpoints off | 37.9904 | 4.7488 | 21.8483 s | 0 s |
| tracing off, checkpoints off | 6.7524 | 0.8441 | 3.2124 s | 0 s |

With checkpoints retained, disabling allocation tracing saved 37.2254 seconds, or 80.80% and
4.6532 seconds per environment action. With tracing retained, suppressing automatic checkpoints
saved 8.0800 seconds, or 17.54% and 1.0100 seconds per action. Both exceed the frozen materiality
rule. The checkpoint effect remained material without tracing: 2.0925 seconds, or 23.66%. The
5.9875-second additive interaction shows why the marginal savings must not be summed: allocation
tracing also amplifies checkpoint serialization.

The balanced 20-trial `synthetic` factorial independently agreed on direction. Median wall time was
0.4481 seconds with both factors off, 0.6820 seconds with checkpoints only, 1.3017 seconds with
tracing only, and 2.1251 seconds with both. The pooled tracing-on/off wall ratio was 3.2829; the
checkpoint-on/off ratio was 1.5970. All exact decisions and outcomes matched.

The broad action-selection envelope also has a concrete internal cause. In a read-only active-model
microbenchmark, each representative 32-call pass executed 256 `ModelCandidate.predict` calls, 128
ensemble prediction calls, and 1,664 canonical `SymbolicState.state_id` computations. Allocation
tracing made the unchanged candidate pass 4.6428 times slower. This supports prediction reuse and
immutable state-ID caching as a repair candidate, but does not yet count as an end-to-end repair.

## Causal bottleneck map

| candidate | measured classification | bounded reason |
|---|---|---|
| Python allocator/object tracing overhead | **SUPPORTED_MATERIAL_CAUSE** | 80.80% matched local-public reduction; 3.2829× synthetic marginal ratio |
| automatic checkpoint frequency | **SUPPORTED_MATERIAL_CAUSE** | 17.54% reduction under tracing and 23.66% without; 18 immutable checkpoints and 2.395 MB written |
| redundant model prediction/state identity | **SUPPORTED_INTERNAL_CANDIDATE** | repeated prediction/hash calls with exact read-only output and state identity |
| repeated full-history retrodiction | **SUPPORTED_SECONDARY_GROWTH; VALUE UNRESOLVED** | 1.1235 s/2.44%; growth observed, direct safe intervention deferred to Stage 07 |
| synchronous trace/blob work | **MEASURED_SECONDARY; UNRESOLVED** | 2.6886 s/5.84% traced, about 0.705 s untraced; replay and receipts remain mandatory |
| repeated frame transformations | **SUPPORTED REPETITION; SAVING UNRESOLVED** | 38/51 repeated inputs and 40 unchanged classifications; no accepted cache intervention yet |
| component correspondence | **CONTRADICTED AS PRIMARY HERE** | 0.1417 s/0.31% on this episode |
| planning expansion explosion | **CONTRADICTED AS PRIMARY HERE** | 0.5271 s/1.14%; seven plan receipts expanded one node each |
| combinatorial hypothesis growth | **CONTRADICTED AS PRIMARY HERE** | four hypotheses and one model after the first transition; hypothesis update below 0.01% |

The contradictions are episode-bounded. They do not establish absence on other games or longer
histories. Goal support did grow—91 support receipts for 14 goals—and remains a later caching target,
but hypothesis-count explosion itself was not the observed failure.

## Repair boundary

Allocation tracing is evaluator instrumentation, so it can default off outside explicit memory
diagnostics while OS RSS and hot-path timing remain available. Checkpointing is different: disabling
all automatic persistence would violate restartability and action-boundary durability. Stage 08 must
therefore retain crash-safe semantics while reducing full-state serialization through cadence,
incremental state, or both. Trace receipts likewise remain immutable; timing alone cannot authorize
their removal.

## Evidence integrity

- Stage receipt: `docs/evidence/001-03-causal-bottlenecks.json`
- Predeclaration: `sha256:b9f81e93fbd76944dcb2ef9382e4d7da756bfd91e68075a4d7f4930d060f96d1`
- Synthetic raw file: `sha256:bc36afbe4c3f8ec19d97a8999e5b79ccc04dfb39294b13a304f78e1a842ec01c`
- Synthetic self-hash: `sha256:f4df520d35424ad873dd83c399cd9e65d0221ea2245e28929b29c341afc6ad1f`
- Local normalized action signature: `sha256:e4f613a9424030efc046654c242270e750746d7ff3bbe5b690603da790511d76`
- Local normalized observation-outcome signature: `sha256:07485eca51e6c03186842a6572a4c118f3ac349d15f24d1e2f9b1d3a6159b706`
- Control receipt: `sha256:fdaf4e25d1576bc4db765edcae2ad4ddfb5567d2f79fd26ff1c8d99af98f6d6a`
- Tracing-off receipt: `sha256:a5c30f5ab414fd48c6e2ba40e574fd1f1a66a44c20b5777de96738b21991f451`
- Checkpoint-off receipt: `sha256:ef608f58ae1ef55cdef1ce2462fd5d891fc0e8368e408cf9b1f9463136291ca6`
- Joint-intervention receipt: `sha256:460d6c723bb36ba815474b181b5b53e23e41d0278791bf8e7ba0d303d8786470`
- Stage 03 exposure ledger: `sha256:e02a9fa71206170a6fe2aeefb6935ae25141e2759937657475cead4389bb17aa`

All four evaluation bundles passed their artifact verifiers: 30, 30, 11, and 11 artifacts,
respectively, each with one run and zero errors. The different artifact counts are expected because
the diagnostic checkpoint-off cells contain no checkpoint files. The Stage 03 exposure ledger has
eight development events and zero holdout events; the ten holdout asset directories remain absent.
The Build 000 exposure ledger remains byte-identical at
`sha256:cd9af42ed3a5ef9fa0dc201ddb10e32d2bcccee9df729aa0c7d53077c04c9ad4`.

Focused verification passed 21 tests plus Ruff, formatting, strict mypy, diff checks, and a backward
verification of the 30-artifact Stage 02 bundle. The default Windows pytest temp-root denial recurred
as seven setup errors after nine passing tests; the identical file passed 16/16 with a fresh explicit
short-path `--basetemp`, and the combined suite then passed 21/21. That infrastructure failure is
preserved rather than relabeled as a test failure.
