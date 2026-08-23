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

## D-001-0022 — Freeze paired retrodiction replacement gates before implementation

- Recorded: 2026-08-22T15:21:32.8066144Z
- Status: accepted
- Decision: Compare `FULL`, `NONE`, `RECENT_WINDOW_8`, `EVENT_TRIGGERED`, and
  `CACHED_INCREMENTAL` on an exact 280-cell paired matrix: 14 frozen Stage 14 cases, eight
  evaluator-sealed old-contradiction histories, a balanced 32-case Stage 06 intervention/noise
  subset, and two permitted development seeds. Keep `FULL` as the production and competition
  default until a measured candidate passes every truth, completion, mechanics, action, runtime,
  replay, checkpoint, and integrity gate.
- Evidence: `docs/evidence/001-07-retrodiction-predeclaration.json`, SHA-256
  `d4eb82f2e0c04e1c94be4d6fbaa8862aa808cc07932042a02d0c5fbcc02dc608`; clean baseline
  `8e3400cebda87f75b8bb3fd0c8d592d2125a6869`.
- Boundary: `NONE` is an experimental negative control, recent-window artifacts may not claim full
  coverage, event reuse requires an immutable matched prediction receipt, and cached reuse must
  materialize exact FULL semantics. The ten-game public holdout remains sealed. No result may be
  selected on Stage 06 outcomes or promoted from synthetic evidence into hidden generalization.
- Reopening condition: an identity/count audit finds the matrix was not frozen as declared, a
  mode can reuse authority without its required receipts, cache/checkpoint tamper survives restore,
  or an official measurement begins from a source that does not contain this unchanged declaration.

## D-001-0023 — Amend the infeasible B07 construction and bind B seeds before measurement

- Recorded: 2026-08-22T15:42:41.2920389Z
- Status: accepted
- Decision: Preserve the committed Stage 07 declaration at SHA-256
  `d4eb82f2e0c04e1c94be4d6fbaa8862aa808cc07932042a02d0c5fbcc02dc608` unchanged. Bind a
  premeasurement amendment that changes B07 from overlapping contact at beacon x3 to adjacent
  contact after the mover advances x2 to x3 beside beacon x4. Keep exactly one shared movement and
  one candidate-specific rare contact rule; do not add a collision rule or alter production world-
  model semantics to manufacture fixture feasibility. The same amendment binds B01 through B08 to
  seeds 1 through 8 because the base paired-seed rule omitted their concrete values.
- Evidence: `src/arc3/world_model/rules.py` blob
  `751bb35efabd14f028ad2d3b54ee0814dd7176ee` defaults an unmatched overlap to `BLOCK` before
  applying contacts. Amendment
  `docs/evidence/001-07-retrodiction-predeclaration-amendment-01.json`, SHA-256
  `5c8ff0c91602d86ecaadd61197dfb80681f618ad4e6c810c26933ca337fdcc3b`, was written before any
  Stage 07 measurement or public-development attempt.
- Boundary: no mode, case ID, previously declared A/C/D seed, count, budget, rank, decision gate,
  public partition, or holdout rule changes. The B seeds are newly fixed before results rather than
  changed from prior values. The construction and underbinding failures remain preserved; the
  amendment supplies no evidence for a retrodiction mode.
- Reopening condition: B07 cannot execute exactly under the amended adjacent-contact composition,
  its before/after truth differs from the amendment, or any official artifact fails to bind both
  the base and amendment hashes.

## D-001-0024 — Bind retrodiction reuse to reconstructible typed evidence

- Recorded: 2026-08-22T16:02:36.5432466Z
- Status: accepted
- Decision: Implement all five frozen Stage 07 modes in a pure typed runtime whose cache namespace
  includes the complete configuration hash, model semantic fingerprint, mechanics epoch,
  projection, and ordered exclusion identity. Checkpoints retain complete canonical transition
  witnesses and typed outcome folds. Restore must reconstruct model outcomes from immutable
  transitions and compare the exact result before accepting any cached artifact or completion
  receipt; hashes alone do not grant authority.
- Evidence: source checkpoint `586e8ba2c9c414b4bf2cc426ad5c1bbd357d5258`; 33 focused unit,
  property, and legacy-parity tests passed with Ruff, format, and strict mypy. The tests include
  rehashed configuration, identity, exclusion, witness, artifact, and residual-content tamper
  attempts.
- Boundary: cached and event-triggered modes may reduce computation only. They do not change FULL
  semantics, make a recent-window artifact complete, authorize `NONE` for competition, or promote
  derived checkpoint state over trace receipts. Production remains `FULL` until the frozen decision
  artifact is complete and independently verified.
- Reopening condition: any altered typed outcome, residual, identity, omission, prefix, receipt, or
  configuration survives reconstruction; eviction changes policy behavior; or legacy FULL/NONE
  artifacts drift.

## D-001-0025 — Trace the exact evidence authorizing event-triggered reuse

- Recorded: 2026-08-22T16:09:50.7346730Z
- Status: accepted
- Decision: An EVENT_TRIGGERED reuse receipt must carry the exact ordered matched-prediction
  evidence for the reused suffix and no unrelated evidence. Each item binds transition and model
  identity to the pre-action prediction event and receipt, returned consequence event, assessment
  receipt, match scope, match result, and source order. First-use, full-audit, and non-reuse paths
  emit an empty authorization vector.
- Evidence: source checkpoint `44fc3666522db4787f4349c4a5cb5ee085f787d9`; 35 focused
  retrodiction tests pass, including omitted,
  extra, reordered, wrong-model, invalid-scope, exact-hit, and full-audit authorization cases.
- Boundary: a cache hit is not authority by itself. Controller restore must still validate every
  referenced event type, source order, model, transition, and receipt against the immutable trace.
- Reopening condition: a reuse passes without the exact suffix receipts, unrelated evidence is
  accepted, trace references are not independently folded, or the authorization vector can be
  changed and rehashed without rejection.

## D-001-0026 — Make the one official Stage 07 attempt fail closed

- Recorded: 2026-08-22T17:26:50.7566939Z
- Status: accepted
- Decision: Bind the official result, work, exposure, development-asset, and recording paths;
  require a clean Build 001 branch descending from the frozen baseline; measure every complete
  cell including terminal restore; suppress every replacement decision unless the exact 280-cell
  matrix, 60 microbenchmarks, verification suite, resource gates, trace replay, checkpoint restore,
  source stability, network denial, and sealed-holdout checks all pass. Use one terminal
  content-addressed checkpoint for reused Stage 06 cells rather than enabling policy memory or
  per-action checkpointing merely to satisfy an evaluator predicate.
- Evidence: source checkpoint `1cf1945c42bb7da42e63b423c4a986d72fd24ead`;
  `docs/evidence/001-07-premeasurement-audit.json`; synthetic verification passed 69 harness tests,
  139 expanded Stage 07 tests, Ruff, format, and strict mypy. The official output, work, exposure,
  and recording targets were absent at the checkpoint.
- Boundary: this prepares but does not execute the one official Stage 07 attempt. The terminal
  checkpoint changes evidence persistence only and preserves the frozen `use_memory=False` policy
  semantics for Group C. A `PARTIAL` artifact must keep `FULL` and exit nonzero.
- Reopening condition: any alternate path can evade the frozen attempt, a source or asset mutation
  survives, a resource/verification failure can retain a candidate decision, or a terminal
  checkpoint does not restore exactly from its immutable commitment.

## D-001-0027 — Reconstruct typed artifacts and bind the opaque development bytes

- Recorded: 2026-08-22T17:26:50.7566939Z
- Status: accepted
- Decision: Every new controller retrodiction completion carries its full normalized typed artifact
  projection. Restore recomputes every completion from preserved typed transitions, including
  FULL, NONE, RECENT, and evicted cache/event receipts, and hard integrity requires that semantic
  reconstruction. Separately, bind the permitted `ar25-0c556536` development asset to its already
  measured aggregate and two-file byte identity before open, after open, and after each episode;
  require all ten D cells to carry the same three receipts.
- Evidence: source checkpoint `1cf1945c42bb7da42e63b423c4a986d72fd24ead`; current opaque
  aggregate SHA-256
  `e796e615d2e10c93b849f9bf150308fbf84d624725deaf995d7ec2d1c2f86b22` matches the Stage 01–03
  frozen identity. Focused synthetic/no-game tests passed 87/87, the all-mode adapter suite passed
  48/48, and independent read-only re-audits closed both P1 findings.
- Boundary: the asset check hashes bytes only and does not inspect game semantics or open a holdout.
  It supports paired source identity, not hidden-game generalization. Legacy receipts without the
  new projection remain readable outside this official harness, but cannot satisfy Stage 07 hard
  integrity.
- Reopening condition: a completion can pass without an exact typed projection and restore, any D
  cell can omit or alter one of the three byte snapshots, or current asset bytes differ from the
  frozen prior identity.

## D-001-0028 — Preserve the unique Stage 07 attempt and keep FULL

- Recorded: 2026-08-22T18:38:27.5753539Z
- Status: accepted
- Decision: Treat the execution from clean commit
  `f683dbc672213e804ddc6120b0be2762e6c66a08` as the one and only frozen official Stage 07
  attempt. Do not rerun, resume, complete, or overwrite it. Because it created only 279/280 matrix
  cell directories, ran 0/60 microbenchmarks, raised during final aggregation, and never evaluated
  the replacement gates, retain production mode `FULL`. Repair only the fail-closed partial-result
  serialization path for future protocols and continue Workflow 001 with the negative result.
- Evidence: `docs/evidence/001-07-failed-infrastructure-attempt-01.json`; preserved work inventory
  `sha256:fa79526cc91c096fa38868fe4aa11e52cad6c8f0fe8c804ebe00806ee6f4f62e`; nine D-cell
  failure receipts report `WorldModelError: mechanics transition bound exceeded for epoch`; the
  final `CACHED_INCREMENTAL` seed-23 D cell was not started. The post-loop verification receipts
  all pass, but they cannot supply the missing matrix or microbenchmark evidence.
- Boundary: the 270 synthetic cell directories and nine `local-public` failure receipts remain
  partial evidence. Lost process-local wall/CPU/RSS measurements are not reconstructed or claimed.
  The ten-game holdout remains sealed with zero events/assets. A harness defect does not erase the
  D-cell mechanism failure, and the mechanism failure does not convert the harness into a PASS.
- Reopening condition: none within Build 001. A future separately predeclared workflow may execute
  a new comparison under a new attempt identity, but it cannot revise or supersede this attempt's
  immutable status.

## D-001-0029 — Freeze evidence-preserving two-speed reasoning before implementation

- Recorded: 2026-08-22T19:00:22.4554283Z
- Status: accepted
- Decision: Keep the raw consequence/observation boundary, prediction assessment, local action
  effects, immutable transition membership, contradiction/reopening, goal progress, plan/cache
  invalidation, and both exactly-once checkpoints always on. Defer only expensive model
  compilation, retrodiction, goal revision, candidate-wide simulation, and new-plan search behind
  typed deterministic triggers. Use no elapsed-time value as a policy input. Derive the mechanics
  transition capacity from the already config-hashed `max_actions`, persist and verify it at
  restore, and never invent an epoch rollover to escape storage pressure.
- Evidence: `docs/evidence/001-08-two-speed-predeclaration.json`, SHA-256
  `3342b6e2635c0606391c9aea02b2fec0cf4c5642a3d38b95768a1b77b4520878`; Stage 07's nine
  65-action local-public prefixes; Stage 02/03 hot-path profiles; frozen Build 000 Stage 13/14 and
  Build 001 Stage 04/05/06 mechanism receipts.
- Measurement: compare frozen Build 000 FULL, contemporary always-deep, production two-speed, and
  two-speed without prediction cache in five matched balanced repetitions on only the already
  exposed `ar25-0c556536` seed-7 eight-action surface. Require at least 25% median paired
  per-action wall reduction against both controls and at least 70% non-regressing pairs, while
  reporting behavior, censoring, and failures separately. Freeze the Stage 10 mechanism floors in
  the same declaration before observing Stage 08 results.
- Boundary: cache entries are revisable pure computation, never receipts or authority. A timing
  win cannot override action/score/fault differences, regression failure, incomplete deep
  receipts, resource failure, or holdout exposure. The unique Stage 07 attempt remains immutable.
- Reopening condition: implementation evidence shows that an always-on fold is itself the material
  bottleneck, a declared trigger is not deterministically trace-derived, a cache affects semantics
  or restart behavior, or a stronger predeclared generic design preserves every authority and
  regression boundary at lower measured cost.

## D-001-0030 — Preserve exceptional public outcomes as failed evidence

- Recorded: 2026-08-22T19:30:11.3606991Z
- Status: accepted
- Decision: on every future public-worker exit, preserve any durable returned consequence before
  derived policy processing; close all opened policy, session, and trace ownership boundaries;
  recover but never promote a verified game-bound score; rehash local assets; record wall, CPU,
  RSS, and intercepted Python socket-entry attempts; and accept an explicitly integrity-marked
  changed or unavailable asset only as failed evidence. A failed receipt remains ineligible for a
  public improvement claim.
- Evidence: commits `b4b033b4206a2c0044544c992bd02b709d1c59ad` and
  `f5a2bd28f91eab6c3e16e335ec9b6b232f4d1804`; 29 focused tests prove full-policy and baseline
  post-action faults preserve replayable consequence counts, score, asset, resource, close, and
  failed aggregate boundaries; Ruff, format, and strict mypy pass.
- Boundary: the socket guard is process-local Python interception of `create_connection`,
  `getaddrinfo`, `connect`, `connect_ex`, and `sendto`, not an OS network namespace. The nine
  immutable Stage 07 failure cells remain historically unrepaired, and their missing terminal
  process measurements are not recreated. The holdout remains sealed.
- Reopening condition: a future exception can escape without a sealed failed receipt, a verified
  score is accepted for a different game, asset drift can enter a success, any opened trace owner
  lacks an explicit close outcome, or a guarded socket entry point is neither denied nor counted.

## D-001-0031 — Separate successful aggregates from recovered failure evidence

- Recorded: 2026-08-22T19:41:19.9544637Z
- Status: accepted
- Decision: publish new public evaluation summaries as schema v0.2. Successful-receipt score and
  level aggregates remain the only inputs to flat policy means and improvement ranking. Verified
  scorecards recovered from failed receipts remain visible in a separate failed-evidence
  projection; unverified failures remain separately counted. Any failure still disables an
  improvement claim.
- Evidence: commit `15eda558a40eea9ecb7f162aabdf6fb05ab64c4b`; 27 focused tests,
  Ruff, format, and strict mypy pass. The immutable Stage 01 v0.1 evaluation reverified exactly:
  56 artifacts, one run, zero errors.
- Boundary: v0.1 reconstruction exists only for verification of historical immutable artifacts.
  New failed-only policy means are null, not zero; downstream consumers must use the schema.
- Reopening condition: a failed receipt can enter a successful aggregate or improvement rank, a
  recovered verified score disappears from failure evidence, or a sealed v0.1 artifact no longer
  verifies exactly.

## D-001-0032 — Make the Stage 08 paired gate executable before the harness

- Recorded: 2026-08-22T20:07:00.1068965Z
- Status: accepted
- Decision: Encode the frozen A/B/C/D identity, balanced 20-cell schedule, canonical plan hashes,
  typed per-boundary work and score receipts, and paired materiality gates in a pure module before
  writing the environment worker. Build 000 work telemetry is unavailable and must remain null;
  a zero placeholder is rejected. Only normally returned contiguous action/consequence boundaries
  enter paired timing medians, while any missing, censored, failed, networked, integrity-invalid,
  or holdout-contacting cell blocks a Stage 08 PASS.
- Evidence: commit `bd9b8a06ad1acde3d13815ef6921da72ecb15058`; 22 focused tests in the
  pinned Python 3.12 environment; Ruff, format, and strict mypy pass; frozen measurement matrix
  hash `sha256:ca507ee6e539e0544647aac792417b276806a848e656f2b7b4f1a368ba6b63a1`.
- Boundary: the contract parses only the exact already exposed development identity and performs
  no asset discovery or environment interaction. Recovered failed scores remain separate evidence,
  Build 000 unavailable counters are not inferred, and timing cannot override semantic divergence.
- Reopening condition: the harness can omit a declared cell or counter without failing closed,
  unavailable Build 000 work is coerced to zero, a failed score enters successful metrics, or the
  executable matrix differs from the frozen predeclaration.

## D-001-0033 — Bind two-speed policy authority to immutable cadence receipts

- Recorded: 2026-08-22T21:37:59.6950190Z
- Status: accepted
- Decision: Integrate the frozen typed cadence as an explicit policy layer. Every action selection
  retains observation, interpretation, hypothesis, world-model, goal, plan/probe, alternative,
  submission, consequence, and update receipts. FAST may reuse only evidence/configuration-keyed
  pure predictions and known plans; DEEP requires an ordered typed trigger and a terminal cadence
  receipt. A crash may abandon only the closed allowlist of revisable derived events after the last
  committed boundary. Action, consequence, observation, checkpoint, run, migration, and evaluation
  receipts can never be discarded as interrupted deliberation.
- Evidence: commit `df0cf75c63c37a784f6ca2df8b87e24d6404a6cb`, tree
  `4eb163c09b5ac80513dfdacfdf18f318b79813c4`; 19/19 rule-change and reopening tests passed in
  577.12 seconds; 76/76 cadence, replay, checkpoint, planning, trace-authority, and cache tests
  passed in 151.65 seconds; Ruff check, Ruff format check, and strict mypy across nine changed
  source modules passed.
- Boundary: this is implementation and `synthetic` verification, not a throughput result or a
  public-game recovery claim. The predeclared 20-cell Stage 08 measurement has not run. The
  ten-game public holdout remains sealed and unconsumed.
- Reopening condition: any FAST/DEEP transition cannot replay exactly; cache reuse changes an
  environment action; a reopening leaves stale cache authority; a non-revisable receipt enters the
  abandoned suffix; or the measured harness violates behavior, resource, or receipt parity.

## D-001-0034 — Cross cadence-less checkpoints through two explicit identities

- Recorded: 2026-08-22T21:58:38.4359590Z
- Status: accepted
- Decision: Keep normal checkpoint restore strict to the current code and source identities. Permit
  cadence-less migration only when the caller supplies both exact legacy identities, the legacy
  commitment validates under them, the configuration identity is unchanged, and the Git commit is
  different. Preserve the legacy bytes and pending action, then emit exactly one cadence activation
  and every new commitment under the current identities.
- Evidence: commit `7f994fc`; 21 focused migration and controller-checkpoint tests, Ruff, format,
  and strict mypy pass. The copied real `df961c7` artifact retained trace SHA-256
  `b3878c197f25693ab64893a1c2a774dba89264cde8c63d719ca3b94fe33e8aca` and checkpoint-file
  SHA-256 `f0eb87b174443acb9c805c0e3c4ca4b8c52c65a689769fb9c2c8d462bc67597f`.
  Final clean-source validation at commit `2e78c258cfbee8be62462f61ed08ad04c00a8934`
  preserved both byte sequences, emitted exactly one current-identity cadence activation, blocked
  pending-action resubmission, applied the returned consequence once, and restored the continued
  checkpoint. Its 44-event trace SHA-256 is
  `f6b8be2e8116d88551032e681631ec186c84425c3a3f5596a7786b5ee2985351`.
- Boundary: migration never resubmits a pending action and never rewrites or relabels the legacy
  prefix. It does not relax cadence-bearing or ordinary restore.
- Reopening condition: any caller can migrate with a partial or wrong identity, legacy bytes change,
  a pending action can cross twice, or a new receipt carries the legacy identity.

## D-001-0035 — Make Stage 08 timing, behavior, resource, and cadence gates jointly fail closed

- Recorded: 2026-08-22T21:58:38.4359590Z
- Status: accepted
- Decision: Define whole-controller time as choose plus consequence plus both measured checkpoint
  boundaries; compare all four variants by exact ordered environment actions, resets, terminal
  state, verified score/levels/completion, and ordered canonical controller faults; enforce the
  frozen RSS, trace-size, and decision-time limits; and require typed selected-to-terminal cadence
  receipts with priority-ordered trigger source IDs. Keep Build 000 work/cadence telemetry null.
- Evidence: commit `2646cd3`; 37 focused contract tests, Ruff, format, and strict mypy pass while the
  frozen 20-cell matrix and plan hashes remain unchanged.
- Boundary: these are executable premeasurement gates, not observed performance. A faster cell
  cannot pass with semantic divergence, missing receipts, a resource violation, or inferred Build
  000 telemetry.
- Reopening condition: the process harness can serialize an invalid cell into a passing typed result,
  whole-controller accounting excludes an authority checkpoint, or exact paired behavior can drift
  without blocking materiality.

## D-001-0036 — Supervise every Stage 08 public cell as an immutable process boundary

- Recorded: 2026-08-22T22:43:59.8449697Z
- Status: accepted
- Decision: Run the frozen Stage 08 matrix only through a serial parent supervisor whose default
  mode is non-playing preflight and whose playing mode requires an explicit `--execute`. Append an
  exact cell/spec exposure event before launch, preserve exact stdout and stderr bytes, cap each
  worker at the lesser of 120 seconds and the remaining 2,700-second attempt envelope, and never
  rerun an exposed cell. A durable raw result without its parent supervisor receipt remains
  preserved but is classified as interrupted `FAILED_INFRASTRUCTURE`; if the orchestrator crash
  makes elapsed wall time incomplete, stop the attempt and report only an observed lower bound.
- Evidence: 111/111 Stage 08 contract, worker, and parent-supervisor tests passed under an isolated
  short Windows base-temp path in 15.75 seconds; Ruff check, Ruff format check, and strict mypy
  across all 161 first-party source files under both Windows and an explicit Linux target passed.
  The tests cover timeout termination, byte-exact
  streams, exposure binding, interruption refusal, exact action/consequence/trace/score binding,
  nullable resource evidence, fixed paths, source/package/adapter preflight, parent-classification
  recomputation, full surviving-cell resume revalidation, stop-after-infrastructure behavior, and
  incomplete wall accounting. Adversarial review further required exact prefix-wide exposure and
  receipt validation before launch; exact isolated imports from both measured source roots; an
  executing-checkout/source-identity match; raw-result precedence over supervisor timeout claims;
  whole-process-tree termination; exact exposure persistence immediately before supervision; and
  independent live-controller recomputation of cadence budget, cache, registry, work, and artifact
  identities. Binding instrumentation is excluded from candidate/control timings; failed tree
  termination is infrastructure evidence that stops the matrix; and the parent independently
  recomputes worker failure domains from their sealed phase and exception kind. The final targeted
  adversarial review confirmed that false or missing interim asset, holdout, or source-integrity
  evidence stops all later launches, and that initial and returned immutable observation receipts
  bind frame, game, state, action-space, returned action, full-reset, completed-level, and won-level
  consequences. The measured source
  hashes are
  `d3ee67c9238dbda905045edef91de1a59d764169f4eb85dec19aa89a147b7300`,
  `2bc77bdf3280dd8c216094f7363f4ef1e2106342150969f182461b0b80a94dcb`, and
  `903d6ab2f6e86fcdd33b353ee30c8d7692c35846e464538e8236c0a51b7fad00` for the
  typed contract, worker, and supervisor respectively. No public environment was opened by these
  tests.
- Exact-source verification closure: push run `32607264914` and draft-PR run `32607267169` passed
  lint, format, strict mypy over 161 files, 959 tests, and runtime doctor on both Ubuntu and Windows
  at commit `2e78c258cfbee8be62462f61ed08ad04c00a8934`. Ubuntu test durations were 840.80
  and 946.92 seconds; Windows durations were 1,558.74 and 1,555.66 seconds.
- Boundary: a valid controller worker timeout is resource/mechanism evidence; launch, missing-result,
  interrupted, parser, source, asset, exposure, or receipt faults are infrastructure failures. The
  Python socket guard is not an OS network namespace. The frozen 20-cell matrix has not yet run,
  and this decision makes no throughput or public-performance claim.
- Reopening condition: any cell can run without a prior matching exposure event, an exposed cell can
  be rerun, exact stream/result bytes can disappear, incomplete wall accounting can claim a passing
  limit, a malformed raw result can enter the typed gate, or a holdout identity can reach a worker.

## D-001-0037 — Abort unacted cadence work without changing policy authority

- Recorded: 2026-08-22T23:15:54.0238006Z
- Status: accepted
- Decision: Treat budget exhaustion, explicit TRACE/BASELINE checkpoints, controller close, and
  other pre-action terminal boundaries as aborted deliberations that preserve their immutable
  terminal receipts but do not advance FAST streaks or other cadence inputs. FULL may return the
  exact prior automatic fold checkpoint only when its content-addressed hash reloads, it has no
  pending action, and every later receipt is on the closed revisable-interruption allowlist.
  Restore diagnostics must select the content-addressed envelope named by the immutable commitment,
  never the replaceable `latest.json` pointer; strict source and commitment validation remains the
  final restore authority.
- Evidence: commit `7c4ea86fda1fc5900b3c37b204e8c60c476cbab8`; 44/44 complete
  controller/cadence contract tests; 5/5 adversarial automatic-fold, TRACE abort, pending-FAST close,
  malformed-latest, and runtime-mismatched orphan-latest tests; Ruff, format, and strict mypy pass.
  The exact 18 non-subprocess regressions from the failed remote suite passed in 65.11 seconds, and
  the nineteenth Stage 16 fresh-process profile test passed from the clean detached checkout
  `C:/a/arc3-ci-7c4ea86` in 52.01 seconds.
- Boundary: the remote Linux/Windows full suites for this repair remain pending. This is restart
  and authority evidence, not a Stage 08 performance result, and no public environment was opened.
- Verification closure: GitHub Actions runs `32604662810` and `32604664455` passed 885 tests on
  Ubuntu and Windows. A correctly source-bound clean detached Windows rerun passed 885/885 in
  2,139.82 seconds with `PYTHONPATH=C:/a/arc3-ci-7c4ea86/src`. The earlier mixed-source 22-failure
  run remains preserved as infrastructure evidence.
- Reopening condition: checkpoint frequency changes a selected path or trigger; an unacted terminal
  advances cadence; a raw/external receipt enters an abandoned suffix; an orphan latest pointer
  influences restore; or strict source/commitment validation can be bypassed.

## D-001-0038 — Preserve the unique Stage 08 infrastructure failure without rerunning it

- Recorded: 2026-08-23T00:51:15.3565958Z
- Status: accepted
- Decision: Classify the one predeclared Stage 08 execution as `FAILED_INFRASTRUCTURE`, preserve
  every surviving receipt, expose no later matrix cell, and never rerun the exposed cell within
  Build 001. Report no paired timing, material-reduction, mechanism, or public-recovery result.
  Continue only independent later workflow work. A read-only audit may diagnose the harness, but a
  successful later repair cannot retroactively change this attempt's status.
- Evidence: `docs/evidence/001-08-two-speed-controller.json`; raw attempt
  `C:/a/arc3-b001/artifacts/stage08/two-speed-controller-attempt-01.json`, file SHA-256
  `7c39fa77de24bd1925d9dbd489d583118f96d4b7fe860678607f485506ad39d4`; one-event exposure
  ledger SHA-256 `be73b837805a66ed172b20573aa31c41fe6ba16ced4d471929b6018e22a5d52e`.
  The first worker submitted and received eight actions, replayed 241 trace events, then failed
  terminal snapshot and boundary-chain validation. Nineteen cells were never opened.
- Diagnosis: the checkpoint validator compared frozen Build 000's intentionally pre-`CLOSED`
  checkpoint phase with its post-close in-memory phase. The boundary validator separately equated
  the domain-separated semantic `GridFrame.digest` with the trace blob's canonical-JSON hash. Both
  are evidence-validation harness incompatibilities; neither establishes a controller defect.
- Boundary: the worker's raw failed-evidence scorecard (0.0, zero levels, `NOT_FINISHED`) is not an
  accepted typed Stage 08 score. Frozen source, development assets, and holdout state remained
  stable; the ten-game holdout has zero gameplay events and remains sealed.
- Reopening condition: none for this attempt. A future separately predeclared measurement may use
  a repaired generic validator but cannot overwrite, resume, or supersede Attempt 01.

## D-001-0039 — Freeze Stage 10 floors and supervise valid negative child evidence

- Recorded: 2026-08-23T00:57:24.3930952Z
- Status: accepted
- Decision: Freeze the Workflow 001 Stage 10 qualitative and exact regression floors before any
  decisive execution. Run nine synthetic suites serially under one exact clean source identity.
  Accept child exit 1 only when a self-hashed artifact proves a bounded measured
  `FAILED_MECHANISM`; preserve that negative evidence and continue independent suites. Give any
  missing, interrupted, malformed, source-drifted, or hash-invalid child infrastructure precedence.
- Evidence: `docs/evidence/001-10-robustness-regression-predeclaration.json`, SHA-256
  `02ad73f25cd6c21459cf425a29de0b830fa27bd660c58777b272ac57116d26e3`; integration commit
  `670e57b7077a94b9c5087b4a9827a00681f26d4b`; 47 integrated supervisor, checkpoint, cadence, and
  integrity tests passed in 24.09 seconds; Ruff, format, and strict mypy over six files passed. Its
  clean non-playing preflight froze nine collision-free suites with plan hash
  `3e4a4bff3cc7b4d36c516e1666deacb93a487c07f3753d786d92cf5ba913b12a` and created neither an
  attempt root nor result.
- Boundary: this is `synthetic` premeasurement infrastructure, not a Stage 10 result. It opens no
  public environment and reads no holdout identity or asset. The eventual decisive source commit
  must contain source floor `2e78c258` and be frozen explicitly at launch.
- Reopening condition: a valid negative child is relabeled as infrastructure from exit code alone;
  an interrupted child can be silently rerun; source, stream, child, parent, or invocation hashes
  can drift on resume; or any frozen floor changes after observing a decisive result.
