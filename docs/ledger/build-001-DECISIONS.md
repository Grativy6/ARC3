# ARC3 Build 001 decisions

Append-only record for material Build 001 engineering and evidence decisions. Christopher D. Pang
is the author and steward; AI systems prepare implementation evidence and are not co-authors or
independent authorities.

## D-001-0001 — Base Build 001 on the exact current main

- Recorded: 2026-08-21T15:41:02Z
- Status: accepted
- Decision: Create `build/001-local-public-recovery` from exact current `main`
  `28c7a00732ce48e5c231211b01bc6eba7d0d71b4` and perform no implementation work on `main`.
- Evidence: Git identity and merge ancestry in the Stage 00 receipt/report.
- Boundary: the current main merge was an owner-created PR #4 merge before this run; Codex did not
  merge it and will not merge the Build 001 PR.

## D-001-0002 — Apply the explicit MIT-0 owner decision

- Recorded: 2026-08-21T15:41:02Z
- Status: accepted
- Decision: Install the candidate MIT-0 text as the operative root `LICENSE` for ARC3 first-party
  source and update active first-party metadata while retaining candidate and Build 000 provenance.
- Authority: active owner instruction states, “I approve MIT-0 for ARC3 first-party source.”
- Boundary: third-party licenses remain unchanged; this does not accept terms, submit, merge, or
  publish a release.

## D-001-0003 — Retain frozen executable pins while recording organizer-page drift

- Recorded: 2026-08-22T03:08:38Z
- Status: accepted
- Decision: Keep Build 000's pinned `arc-agi==0.9.9`, `arcengine==0.9.3`, repository commits, and
  static documentation hashes because the Stage 00 refresh found those executable and static
  identities unchanged. Record, but do not silently adopt, drift in both dynamic organizer pages:
  ARC-AGI-3 `06ba7dde…` → `00de5129…` and general 2026 `59061f61…` → `f0bc5b1f…`.
- Evidence: Stage 00 source-identity receipt.
- Reopening condition: a later measured compatibility failure or upstream identity change.

## D-001-0004 — Keep the ten-game public holdout sealed

- Recorded: 2026-08-21T15:41:02Z
- Status: accepted
- Decision: Read only manifest/exposure metadata until the Stage 11 gate is earned; do not acquire,
  open, inspect, or run a holdout game episode.
- Evidence: manifest hash, 330-event exposure-ledger hash, zero holdout events, and zero local
  holdout asset directories in the Stage 00 receipt.

## D-001-0005 — Reproduce one declared development failure before policy repair

- Recorded: 2026-08-22T03:20:48Z
- Status: accepted
- Decision: Add a generic partition-bound evaluation selector and predeclare exactly one Stage 01
  run: FULL/B4 on development game `ar25-0c556536`, seed 7, 80 actions, 8 resets, and a 120-second
  worker limit. The selector is evaluation infrastructure; the production controller, policy
  features, baseline binding, and competition-runtime declaration remain byte-identical to the
  Build 000 Stage 18 source.
- Evidence: `docs/evidence/001-01-reproduction-predeclaration.json` and focused selector tests.
- Boundary: no asset acquisition, no hosted inference, no holdout selection, and no production
  repair before the reproduction receipt is sealed.

## D-001-0006 — Preserve evaluator failure status while classifying the Stage 01 objective

- Recorded: 2026-08-22T03:26:00Z
- Status: accepted
- Decision: Preserve the generic evaluator's `FAILED_INFRASTRUCTURE` aggregate and exit 1 for an
  all-timeout bundle, while marking Workflow 001 Stage 01 `PASS` because the predeclared target was
  to reproduce that exact timeout pathology. Do not relabel the run itself as success.
- Evidence: verified timeout receipt and comparison in
  `docs/evidence/001-01-reproduction-acceptance.json`.
- Boundary: this classification says only that failure reproduction succeeded; local-public
  controller recovery remains open.

## D-001-0007 — Keep hot-path instrumentation outside policy semantics

- Recorded: 2026-08-22T03:59:41Z
- Status: accepted
- Decision: Add opt-in derived profiling around the declared runtime phases, keep telemetry outside
  policy-selection spans, reject diagnostic mode on the holdout, validate requested profiles inside
  sealed evaluation receipts, and measure enabled/disabled overhead on alternating fixed synthetic
  episodes before using one bounded development-game profile for ranking.
- Evidence: implementation commit `84854c4ada25684f5248fe7bd8725d3b6301c2d5`, 45 focused
  tests, clean-source Stage 16 regression tests, and
  `docs/evidence/001-02-hot-path-predeclaration.json`.
- Boundary: profiler state is revisable derived evidence, never an observation, hypothesis, plan,
  action input, score, or hidden reasoning record. A parent-killed worker records diagnostic
  unavailability rather than manufacturing a partial timing profile.
- Reopening condition: paired identity tests fail, measured overhead exceeds the declaration, or
  the receipt cannot attribute at least 90 percent of the measured profiler lifetime.

## D-001-0008 — Diagnose action selection and persistence before optimization

- Recorded: 2026-08-22T04:03:00Z
- Status: accepted
- Decision: Treat the Stage 02 exclusive-time ranking as an intervention order, not yet a causal
  conclusion. Stage 03 will first split allocator-tracing effects and checkpoint persistence, then
  test the broad action-selection envelope and growing retrodiction/goal work one factor at a time.
- Evidence: `docs/evidence/001-02-hot-path-observability.json`; the development profile attributes
  48.06% to action selection and 16.97% to checkpointing, while checkpoint time grows from 0.3469
  seconds at action 2 to 1.2397 seconds at action 8. Planning is only 1.10% on this run.
- Boundary: one traced development game cannot establish transfer, functional value, or safe
  deletion. No mechanism is disabled in production solely because it is expensive.
- Reopening condition: Stage 03 intervention evidence contradicts the ranking or shows that an
  apparently expensive phase supplies behaviorally necessary value at the same budget.

## D-001-0009 — Isolate allocator tracing and checkpoint persistence as diagnostic factors

- Recorded: 2026-08-22T04:22:27Z
- Status: accepted
- Decision: Add two default-on, receipt-bound diagnostic controls to the development evaluator:
  Python allocation tracing and FULL automatic checkpoint persistence. Any disabled control
  requires FULL plus hot-path profiling and is rejected on the public holdout. Pair a balanced
  synthetic 2x2 factorial with the same four cells on the one already-exposed Stage 01 development
  game before changing production behavior.
- Evidence: `docs/evidence/001-03-causal-predeclaration.json`, focused evaluator-contract tests,
  and the synthetic causal-diagnosis harness.
- Boundary: disabling `use_memory` is a causal intervention only, not a persistence repair; the
  default evaluation and competition policy remain unchanged. A read-only private-method
  microbenchmark may diagnose candidate-generation cost but cannot bypass action receipts or
  promote a production optimization by itself.
- Reopening condition: intervention receipts change exact decisions/outcomes, fail source binding,
  access the holdout, or disagree materially across synthetic and local-public evidence.

## D-001-0010 — Accept two causal throughput costs without deleting their functions

- Recorded: 2026-08-22T04:33:07Z
- Status: accepted
- Decision: Accept global Python allocation tracing and every-boundary whole-state checkpointing as
  the two Stage 03 material throughput causes. The same-source development interventions saved
  80.80% and 17.54% of control wall time, respectively, with exact normalized decisions and
  observation outcomes. Preserve checkpoint/trace semantics and carry their implementation repair
  into Stage 08; do not treat a diagnostic bypass as the repair.
- Evidence: `docs/evidence/001-03-causal-bottlenecks.json` and four verified local-public bundles.
  The balanced synthetic factorial agrees on both factor directions. The action-selection
  microbenchmark additionally identifies redundant prediction and state-ID work, but only as a
  production optimization candidate until an end-to-end parity intervention exists.
- Boundary: all four development cells still completed zero levels and scored 0.0. This decision is
  throughput diagnosis only and makes no recovery, holdout, benchmark, or generalization claim.
- Reopening condition: later clean evaluation reverses the measured direction, or crash/replay tests
  show that a proposed optimization weakens immutable receipts, action durability, or restartability.

## D-001-0011 — Canonicalize palette classes only in derived interpretation

- Recorded: 2026-08-22T04:40:21Z
- Status: accepted
- Decision: Repair palette equivariance with a bounded, level-scoped derived registry whose stable
  class identities come from first-observed structural/background evidence, never numeric color.
  Preserve raw frame cells, raw component colors, hashes, deltas, recolor evidence, and executable
  color-sensitive mechanics. Freeze 256 procedural pairs, 16 checkpoint/resume pairs, 64 causal
  color controls, and the two actual Build 000 palette regressions before implementation.
- Evidence: `docs/evidence/001-04-palette-equivariance-predeclaration.json` and the frozen Build 000
  Stage 16 acceptance artifact.
- Boundary: a joint bijective relabeling should preserve policy behavior; a one-sided recolor may be
  causally meaningful and must remain distinguishable. Structurally tied colors remain explicitly
  ambiguous rather than being ordered by their raw numeric labels.
- Reopening condition: any raw receipt changes, registry cardinality exceeds 16, checkpoint restore
  rewrites a class, or a color-causal control becomes indistinguishable.

## D-001-0012 — Separate shared palette role from anonymous persistent identity

- Recorded: 2026-08-22T05:15:22Z
- Status: accepted
- Decision: Keep structurally indistinguishable colors in one explicitly ambiguous semantic role,
  while assigning each observed color a stable anonymous identity token from its shared structural
  role and first-observation encounter ordinal. Use that token for derived entity continuity, never
  the raw numeric color or a semantic priority. Revise the provisional controllable entity only
  after a sole tracked component supplies nonzero translation evidence.
- Evidence: implementation commit `86134755f3f26a268585b14264946571592cd4a5`; official clean
  Stage 04 artifact `sha256:c76ad6ecf0c956b51579b27d6543734e7368ca48fb0cadfce3134735be895676`;
  256/256 procedural pairs, 16/16 checkpoint/resume pairs, 64/64 joint relabeling controls,
  64/64 one-sided recolor controls, and both historical cases passed.
- Boundary: the anonymous token is a revisable derived identity handle, not a color meaning. Raw
  cells, component colors, frame hashes, deltas, and recolor evidence remain exact and immutable.
  One-sided recoloring remains distinguishable.
- Reopening condition: a paired palette mapping changes a derived action, identity tokens depend on
  numeric color order, an ambiguous role is falsely promoted to a unique semantic role, or a
  checkpoint changes the token-to-raw-color association.

## D-001-0013 — Calibrate opaque action handles before claiming inverse equivariance

- Recorded: 2026-08-22T05:29:04Z
- Status: accepted
- Decision: Begin every Stage 05 procedural episode by probing each initially advertised non-reset
  handle exactly once in stable wire order, count every probe against the action and efficiency
  budgets, and exclude only that complete prefix from the inverse-request numerator. After the
  prefix, require exact inverse-mapped requests and canonical effect/state parity. Learn movement,
  restore, conditional, and coordinate-related effects only from immutable transition receipts.
- Evidence: `docs/evidence/001-05-action-equivariance-predeclaration.json`; its frozen matrix contains
  128 paired procedural cases, 64 causal ambiguity controls, 16 checkpoint/resume pairs, and the two
  historical Build 000 action-remap failures.
- Boundary: deterministic paired policies cannot produce inverse raw requests before a permuted
  opaque handle has supplied differentiating evidence. The calibration prefix is therefore an
  explicit symmetry breaker, not free interaction and not an action-ID semantic prior. `ACTION6`
  coordinate arity and reset-only-after-`GAME_OVER` remain API facts; selection and undo do not.
- Reopening condition: any calibration action is omitted from action/efficiency accounting, a raw
  identifier supplies gameplay meaning before evidence, ambiguity is broken by numeric identity,
  or the post-prefix inverse-request rate is less than the frozen exact threshold.

## D-001-0014 — Resolve displacement as an evidence facet without erasing whole-effect ambiguity

- Recorded: 2026-08-22T06:12:17Z
- Status: accepted
- Decision: Keep each complete observed effect revisable, including restore digest, terminal state,
  coordinate relation, and condition, while permitting a handle's displacement facet to resolve
  only when every live conditioned candidate carries the same non-null translation and at least one
  has net support. A live no-op, transform, missing displacement, or conflicting vector keeps that
  facet unresolved. Use the facet for semantic ordering, planning, contact probes, and hypothesis
  projection without rewriting or merging the underlying candidates.
- Evidence: the preserved pre-fix seed-13 trace at
  `C:/a/arc3-b001/artifacts/stage05/failed-mechanisms/seed13-pre-translation-facet/trace/active.jsonl`
  (`sha256:0f14f37dad736d3f279920949b4e2c54911d916a124a00493337efa7cdfc9c76`),
  the failed 5/12 inverse smoke at `C:/a/arc3-b001/stage05-smoke-pair-02`, the resolving
  4/4 smoke at `C:/a/arc3-b001/stage05-smoke-pair-04`, and focused registry/controller tests.
- Boundary: a displacement facet is a derived conditional projection, not proof that the complete
  effect is stationary or globally understood. Restore provenance and every contradictory source
  event remain visible; raw action identity never supplies the vector.
- Reopening condition: any conflicting live displacement is silently discarded, a no-op/transform
  alternative still resolves as movement, checkpoint roundtrip changes the facet, or inverse paired
  behavior depends on raw handle ordering rather than learned semantics.

## D-001-0015 — Accept exact synthetic action equivariance with run-local receipt canonicalization

- Recorded: 2026-08-22T06:21:11Z
- Status: accepted
- Decision: Accept the Stage 05 mechanism on its frozen synthetic surface: both historical remap
  cases completed; all 128 procedural pairs achieved exact post-calibration inverse requests and
  canonical trajectory parity; all 64 causal controls and 16 restart pairs passed; the production
  scan found zero identifier semantics. For cross-run checkpoint comparisons only, replace each
  independently generated source event ID by its stable ordinal within that run before comparing
  registry projections. The actual checkpoint restore within a run retains exact event IDs and
  projections.
- Evidence: corrected clean source commit `43713f8add4495cb48e15d9edab402564ab8b8da`; raw
  artifact file `sha256:48141af44742c0955f30086f73b1983e6274362e150195ff88065be2b30ea797`;
  self-hash `sha256:b2ea83ff85f50f005e8630e34857741b70471b232781464fa8e3825d6f33bc07`.
  The superseded `291e73e` run remains preserved under
  `C:/a/arc3-b001/artifacts/stage05/superseded-291e73e/`.
- Boundary: event UUID/timestamp material is intentionally run-local and is not a policy semantic.
  Canonicalization may not drop, merge, reorder, or change candidate support, contradiction,
  status, handle, effect, or evidence cardinality. This is `synthetic` mechanism evidence only and
  does not establish local-public recovery or hidden-game generalization.
- Reopening condition: any semantic field differs across checkpoint counterparts, any actual restore
  changes an evidence ID, any procedural inverse request misses, or later public-development evidence
  shows that calibration/action discovery harms completion or action efficiency materially.

## D-001-0016 — Count mandatory coordinate calibration inside the candidate bound

- Recorded: 2026-08-22T06:35:21Z
- Status: accepted
- Decision: The mandatory evidence-gathering `ACTION6(3,3)` calibration request is the first
  coordinate candidate and consumes one slot in `max_coordinate_candidates`. Prepending it may not
  increase the configured maximum. The remaining salient or seeded-uniform candidates are
  deduplicated and truncated to the residual capacity.
- Evidence: CI on source commit `291e73e197fb9425465c072923804b2a377fbfb8` exposed three
  candidates under a configured limit of two. Correcting commit
  `43713f8add4495cb48e15d9edab402564ab8b8da` passed the focused seven-test regression, the clean
  Stage 16 source guards, and all four Linux/Windows push/PR CI jobs. The corrected frozen Stage 05
  rerun passed with self-hash
  `sha256:b2ea83ff85f50f005e8630e34857741b70471b232781464fa8e3825d6f33bc07`.
- Boundary: calibration remains fully charged as an environment action and a generated candidate;
  this repair changes no action meaning and does not authorize a public-holdout run.
- Reopening condition: any decision returns more coordinate requests than the configured bound,
  excludes the calibration action from accounting, or loses seeded determinism/equivariance.

## D-001-0017 — Freeze guaranteed rule-change exposure before Stage 06 implementation

- Recorded: 2026-08-22T06:47:30Z
- Status: accepted
- Decision: Freeze a synthetic-only Stage 06 matrix before implementation: 64 intervention cases
  spanning action-effect rotation and traversability change, early/late support thresholds, four
  seeds, two palette variants, and two opaque-action variants; 32 matched stationary-noise controls;
  and eight checkpoint/resume pairs, for 112 controller executions. Require an ordered immutable
  consequence-to-contradiction-to-demotion-to-reopening-to-adaptation chain and zero false-positive
  reopening in noise controls under the exact predeclared decision rule.
- Evidence: `docs/evidence/001-06-rule-change-predeclaration.json`, SHA-256
  `0bca5f32986c79008cf6ee01a83867262cda591f477239a5b8e9bccd90e37434`.
- Boundary: the environment's intervention truth remains evaluator-only; production receives only
  ordinary observations and consequences. The declaration uses no public assets, permits zero
  public-holdout gameplay events, and may not be weakened after results are observed.
- Reopening condition: implementation cannot guarantee every declared trigger, the frozen suite is
  infeasible within the 900-second/declared resource envelope, or executable trace ordering shows
  that a required lifecycle transition is not source-honest.

## D-001-0018 — Bound Stage 06 filesystem names without changing the frozen matrix

- Recorded: 2026-08-22T13:20:00Z
- Status: accepted
- Decision: Preserve official Attempt 01 as `FAILED_INFRASTRUCTURE`. Replace only the harness's
  filesystem directory components for intervention, stationary-noise, and checkpoint executions
  with deterministic bounded content-addressed names. Keep complete case IDs in typed receipts.
  Freeze the superseding output at
  `C:/a/arc3-b001/artifacts/stage06/rule-change-reopening-attempt-02.json` and its work root at
  `C:/a/arc3-b001/artifacts/stage06/rule-change-reopening-work-attempt-02` before the rerun.
- Evidence: `docs/evidence/001-06-failed-infrastructure-attempt-01.json`; Attempt 01 created no
  result file and completed zero mechanism cases before the 283-character path failed.
- Boundary: this decision changes no schedule member, ordering, seed, environment truth, action or
  reset budget, lifecycle predicate, acceptance threshold, production policy, or holdout state.
  Attempt 02 remains bound to the unchanged Stage 06 predeclaration.
- Reopening condition: any content-addressed component collides across the frozen schedule, any
  receipt loses its full case identity, or any frozen matrix field changes.

## D-001-0019 — Preserve mechanics support as an ordered causal vector

- Recorded: 2026-08-22T13:46:20Z
- Status: accepted
- Decision: Treat the three mechanics successor-support dimensions as one arrival-ordered vector
  of `(contradiction_event_id, transition_id, discrimination_context_id)` triples, indexed by the
  immutable one-based `mechanics.successor_evidence_supported.support_index`. Preserve that order
  in candidate state, confirmation payloads, checkpoint serialization, restore, and trace folds.
- Evidence: `docs/evidence/001-06-preflight-058-failed-mechanism.json`; support arrived as
  `ACTION4`, `ACTION1`, but the confirmed context projection was independently sorted as
  `ACTION1`, `ACTION4` and failed exact linkage despite terminal `WIN`.
- Boundary: keep set/sorted normalization for genuinely unordered fields. Do not weaken the
  harness, change the frozen matrix, or infer causal association from lexical action order. Contexts
  may repeat while a candidate is provisional; distinct-context gates count unique contexts.
- Reopening condition: any support dimension loses index alignment, a partial duplicate is
  silently deduplicated, restore accepts an independently permuted dimension, or receipt order is
  confused with raw/canonical action order.

## D-001-0020 — Reconstruct lifecycle folds from support receipts, not terminal narrative

- Recorded: 2026-08-22T13:53:00Z
- Status: accepted
- Decision: Strengthen the independent Stage 06 lifecycle fold so it consumes
  `mechanics.successor_evidence_supported` events in immutable trace arrival order, requires
  contiguous one-based support indices, reconstructs the aligned support vector, and compares the
  terminal confirmation arrays exactly. A terminal `mechanics.change_confirmed` payload cannot
  invent or replace absent support receipts. Preserve predecessor-recovery receipt IDs in arrival
  order for the same reason.
- Evidence: the independent audit of preflight 058 found that the existing summary fold ignored
  support events and could accept a terminal-only confirmation, even though the stricter linked
  causal predicate later rejected the real misalignment.
- Boundary: this strengthens evidence reconstruction only. It does not change the frozen schedule,
  decision threshold, policy truth access, or terminal outcome. Derived candidate mutation follows
  the immutable support append; pure duplicate validation must occur first so partial aliases fail
  without emitting or mutating evidence.
- Reopening condition: a fold passes with missing, duplicated, noncontiguous, reordered, or
  terminal-invented support; recovery order is normalized lexically; or derived state can advance
  when its immutable support append fails.

## D-001-0021 — Accept the frozen Stage 06 failure and continue to Stage 07

- Recorded: 2026-08-22T15:15:09Z
- Status: accepted
- Decision: Close Stage 06 as `FAILED_MECHANISM` under the unchanged predeclared rule and continue
  immediately to the independent Stage 07 retrodiction predeclaration. Do not rerun Stage 06 or
  weaken its lifecycle predicates. Retain the 32/32 action-effect rotation result as bounded
  synthetic progress, but do not promote traversability or stationary-noise terminal `WIN` outcomes
  over their missing candidate-linked typed receipt closures.
- Evidence: clean source commit `ec51f7e7d09241f47baa866af897546912d3c611`; Attempt 02 raw
  artifact file
  `sha256:198201b86d6bbbefd01188cdea67bde4297f402a41ca1531a4fb05a527627151`;
  valid self-hash
  `sha256:4623ec8b03dbeaa6c4901ca70daaea53747f3918b8a8c49b6d73a80c1d70eb0f`.
  All 112 executions completed and replayed, but traversability passed 0/32, stationary noise passed
  0/32, and checkpoint/resume passed 4/8.
- Boundary: this decision is `synthetic` only. It makes no local-public, holdout, hidden-game,
  Kaggle, semi-private, or official-private claim. The ten-game public holdout remains sealed and
  Stage 07 must be frozen before its measurements are observed.
- Reopening condition: an audit shows that the frozen raw artifact was misread, its self-hash or
  source identity fails validation, or any reported count differs from the immutable case records.
