# ARC3 Build 001 open burdens

Append-only record. Resolved burdens remain present with their resolving evidence; later success
does not erase earlier uncertainty or failed mechanisms.

## B-001-0001 — Local-public controller failure

- Status: OPEN
- Carried from: Build 000 burdens B-20260821-038 and B-20260821-045
- Burden: FULL completed zero levels and timed out in every measured local-public run; causal hot
  path and generic recovery remain unproved.
- Next evidence: Stages 01–03 reproduction, instrumentation, and interventions.
- Stage 01 update (2026-08-22): **failure reproduced, burden remains open**. The frozen production
  policy timed out after 120.11965939996298 seconds and 21 actions with zero completed levels on the
  one predeclared development run; the 56-artifact bundle and trace replay verify. Stage 02 must now
  measure the hot path, and Stage 03 must establish causal interventions before repair.
- Stage 02 instrumentation update (2026-08-22): **measurement pending**. Opt-in phase, CPU/wall,
  RSS, cache/repeated-input, and per-boundary accounting is implemented and behavior-preserving in
  focused synthetic tests. The measurement thresholds are frozen in
  `docs/evidence/001-02-hot-path-predeclaration.json`; no throughput cause is accepted until those
  clean-source measurements exist.
- Stage 02 measurement update (2026-08-22): **observability PASS; causal burden remains open**.
  Seven alternating synthetic pairs preserved exact decisions/outcomes with 4.62% median wall
  overhead. One bounded `local-public` profile attributed 99.98% of 38.303 seconds and ranked
  action selection (48.06%) and checkpointing (16.97%) first. These are correlations under active
  allocator tracing; Stage 03 intervention evidence is still required.
- Stage 03 update (2026-08-22): **causal diagnosis PASS; gameplay failure remains open**. Exact
  behavior-matched interventions established allocation tracing and whole-state checkpoint
  frequency as material costs, reducing the 46.0703-second control to 8.8449 and 37.9904 seconds,
  respectively. Every cell still completed zero levels and scored 0.0, so throughput diagnosis is
  not recovery. Stages 04–10 must still improve generic behavior and validate it on development.

## B-001-0002 — Palette and action equivariance failures

- Status: OPEN
- Carried from: Build 000 burden B-20260821-040
- Burden: two palette permutations and two action remaps changed a base score of 1.0 to 0.0.
- Next evidence: Stages 04–05 paired metamorphic tests.
- Stage 04 update (2026-08-22): **palette half resolved; action half remains open**. The clean
  Stage 04 source repaired both historical palette cases and passed 256/256 paired procedural
  bijections, 16/16 checkpoint/resume pairs, and all 64 joint plus 64 one-sided color controls.
  Stage 05 must still repair the two action-remap failures and remove fixed action-ID semantics.

## B-001-0003 — Rule-change exposure is incomplete

- Status: OPEN
- Carried from: Build 000 burden B-20260821-041
- Burden: one rule-change case terminated before intervention, so reopening was not exercised.
- Next evidence: Stage 06 guaranteed-exposure families and a noise control.

## B-001-0004 — Retrodiction evidence conflicts

- Status: OPEN
- Carried from: Build 000 burdens B-20260821-035 and B-20260821-036
- Burden: a supplied-plan symbolic test favored retrodiction, while the integrated matrix preserved
  completion and used nine fewer actions without it; causal runtime value is unmeasured.
- Next evidence: Stage 07 paired hot-path interventions.
- Frozen experiment: `docs/evidence/001-07-retrodiction-predeclaration.json`, SHA-256
  `d4eb82f2e0c04e1c94be4d6fbaa8862aa808cc07932042a02d0c5fbcc02dc608`, commits five modes and
  280 paired evaluation cells before implementation or measurement. It includes eight sealed
  false-rule histories whose decisive contradiction lies outside an eight-transition window,
  balanced change/noise controls, and two permitted development seeds.
- Resolution condition: one replacement mode must meet every predeclared truth, completion,
  mechanics, action, cost, replay, checkpoint, offline-integrity, and holdout-isolation gate; if
  none does, retain `FULL` and resolve the decision as `KEEP_FULL` without erasing failed modes.

## B-001-0005 — Holdout and hidden generalization remain unmeasured

- Status: OPEN
- Carried from: Build 000 burdens B-20260821-039, B-20260821-042, and B-20260821-044
- Burden: the ten-game public holdout is sealed, official RHAE is null, and no Kaggle-private or
  official-private surface is available locally.
- Next evidence: Stage 11 gate, optional one-shot Stage 12 only if earned, and owner-only official
  submission after this workflow.

## B-001-0006 — Full competition runtime is estimated

- Status: OPEN
- Carried from: Build 000 burden B-20260821-043
- Burden: the reported 110-game nine-hour envelope cannot be reproduced exactly without the private
  Kaggle input/gateway; local extrapolation is not an official runtime result.
- Next evidence: Stage 13 bounded package/runtime verification and later owner-gated Kaggle run.

## B-001-0007 — Mutable external rules and anonymous-access limits

- Status: OPEN
- Carried from: Build 000 mutable-source and credential burdens
- Burden: ARC Prize/Kaggle rules and services can change; Kaggle legal/competition surfaces and
  private inputs remain human/credential gated. On 2026-08-22 the two dynamic organizer-page body
  hashes differed from the Build 000 lock while repository heads and eight static docs remained
  stable; semantic impact beyond the separately pinned static sources is unresolved.
- Next evidence: current source identities at each release checkpoint; no terms acceptance by Codex.

## B-001-0008 — First-party license owner gate

- Status: RESOLVED
- Carried from: Build 000 burden B-20260820-004
- Resolution: Christopher D. Pang explicitly approved MIT-0 for ARC3 first-party source in the
  active Build 001 handoff. The root `LICENSE`, active metadata, and Stage 00 receipt implement the
  decision. Build 000's historical unresolved entry remains unchanged.

## B-001-0009 — OneDrive environment and default pytest-temp failures

- Status: RESOLVED
- Observed: 2026-08-22
- Failure evidence: the workspace `.venv` refresh failed with Windows access denied while replacing
  `arc3-0.1.0.dist-info`; the first short-path sync failed with incompatible cloud hardlinks; the
  first focused pytest run produced 23 setup errors because the default user temp root was
  ACL-inaccessible.
- Resolution: `uv sync --link-mode copy` passed in `C:\a\arc3-b001-28c7a00`, and the exact focused
  suite passed 35/35 with an explicit isolated `--basetemp` under `C:\a`. These were infrastructure
  failures, not controller or license-mechanism failures.

## B-001-0010 — Stage 02 profile scope and allocator-tracing distortion

- Status: RESOLVED
- Stage: 02–03
- Opened: 2026-08-22
- Burden: The phase ranking comes from one eight-action development episode while Python allocator
  tracing is active. Build 000 already measured substantial traced/untraced distortion on a
  synthetic stress path, so absolute phase costs and ordering may change without it.
- Why it matters: Optimizing a tracer-amplified phase could misallocate engineering effort or remove
  a functionally useful mechanism.
- Current evidence: `docs/evidence/001-02-hot-path-observability.json`; 38.3345 seconds wall, eight
  actions, zero levels, and 99.978% attribution. This is `local-public` diagnostic evidence only.
- Next discriminating action: Stage 03 predeclared one-at-a-time allocator-tracing and checkpoint
  interventions with exact action-signature comparison.
- Resolution condition: paired intervention receipts quantify marginal cost and behavior for at
  least the top two material causes.
- Resolution update (2026-08-22): The same-source four-cell development factorial preserved exact
  normalized action decisions and observation outcomes. Disabling tracing with checkpoints retained
  saved 37.2254 seconds (80.80%), while disabling checkpoints with tracing retained saved 8.0800
  seconds (17.54%). The balanced synthetic factorial agreed on both directions.
- Resolution receipt: `docs/evidence/001-03-causal-bottlenecks.json`.

## B-001-0011 — Resolved Stage 02 verification preconditions remain provenance

- Status: RESOLVED
- Stage: 02
- Opened: 2026-08-22
- Burden: A mistyped focused test path collected zero tests; a dirty-worktree broad run passed 304
  tests but failed two clean-source Stage 16 subprocess assertions; one integration assertion still
  expected profile schema v0.1 after hardening to v0.2.
- Resolution: The corrected focused suite passed 45 tests, the two exact Stage 16 subprocess tests
  passed from clean commit `84854c4`, and the v0.2 integration assertion passed. No mechanism was
  weakened to satisfy these preconditions.
- Resolution receipt: `docs/evidence/001-02-hot-path-observability.json`.

## B-001-0012 — Stage 03 diagnostic interventions are not production repairs

- Status: OPEN
- Stage: 03–08
- Opened: 2026-08-22
- Burden: Turning off Python allocation tracing may remove evaluator-only distortion, while turning
  off every automatic checkpoint would violate restartability and durable action-boundary
  requirements. Neither measured speedup, if present, proves functional value is dispensable.
- Current evidence: the controls and thresholds are frozen in
  `docs/evidence/001-03-causal-predeclaration.json`; production defaults remain enabled.
- Next discriminating action: quantify the two factors in Stage 03, then use Stage 08 to retain
  crash-safe durability with a measured cadence and incremental representation rather than global
  checkpoint deletion.
- Resolution condition: an optimized production path preserves action decisions, immutable trace
  receipts, replay, crash recovery without resubmission, and the declared runtime budget.
- Resolution receipt: none.

## B-001-0013 — Default Windows pytest temp-root denial recurred during Stage 03

- Status: RESOLVED
- Stage: 03
- Opened: 2026-08-22
- Burden: A direct 16-test evaluator-contract invocation produced seven setup errors because pytest
  again attempted to enumerate the ACL-inaccessible default user temp root. No test body failed.
- Resolution: The identical 16-test file passed with an explicit new short-path `--basetemp` under
  `C:\a`; subsequent Stage 03 checks retain an isolated temp root. This is the same infrastructure
  condition preserved in B-001-0009, not a controller failure.
- Resolution receipt: the Stage 03 acceptance artifact will retain both exact commands and results.
- Stage 04 recurrence (2026-08-22): the first harness-focused invocation again received Windows
  `PermissionError [WinError 5]` at the default user pytest temp root. A unique explicit
  `C:\a\arc3-b001\tmp\pytest-stage04-harness-*` root passed the identical tests. All final Stage 04
  test commands used explicit short-path temp roots.

## B-001-0014 — Redundant prediction and state hashing lack an end-to-end repair receipt

- Status: OPEN
- Stage: 03–08
- Opened: 2026-08-22
- Burden: The read-only active-ensemble microbenchmark found repeated model prediction and canonical
  state-ID computation, but no production cache/reuse change has yet proved exact decision,
  prediction-receipt, replay, checkpoint, and recovery parity.
- Current evidence: a representative 32-call pass made 256 model-candidate predictions, 128
  ensemble predictions, and 1,664 `SymbolicState.state_id` calls. Tracing-off/on median call time was
  4.5105/20.9416 milliseconds with identical outputs and policy state.
- Next discriminating action: add collision-safe immutable identity caching and per-state/action/model
  prediction reuse during Stage 08, then rerun paired controller and development evaluations.
- Resolution condition: exact functional parity plus measured end-to-end savings under default
  production diagnostics.
- Resolution receipt: none.

## B-001-0015 — Workflow Stage 04 palette-failure count conflicts with frozen evidence

- Status: RESOLVED
- Stage: 04–05
- Opened: 2026-08-22
- Burden: Workflow 001 says Stage 04 must repair “the four Build 000 palette failures,” while frozen
  Build 000 acceptance evidence records two palette failures and two action-remap failures.
- Resolution: Preserve the frozen evidence taxonomy: Stage 04 owns the two palette cases at seeds 7
  and 11, and Stage 05 owns the two action-remap cases at the same seeds. Do not manufacture two
  additional palette failures or collapse action identity into palette identity.
- Resolution receipt: `docs/evidence/016-competition-profile-acceptance.json` and the Stage 04/05
  predeclarations once committed.

## B-001-0016 — Naive palette-role identity repairs broke controller regressions

- Status: RESOLVED
- Stage: 04
- Opened: 2026-08-22
- Failed approaches: The first structural-role patch ordered opaque role hashes when choosing the
  provisional mover, breaking the seed-23 checkpointed planning regression. The next patch let
  structurally tied colors share spatial-ordinal entity IDs; those IDs could swap after movement,
  reducing the 16-seed integrated completion contract to 15/16 at seed 5.
- Resolution: Use a raw-free structural provisional key, revise controllability from sole tracked
  translation evidence, and separate a shared ambiguous role from a stable anonymous identity token
  derived by first-observation encounter order. The corrected broad subset passed 68/68 and the
  integrated contract returned to 16/16 before the implementation commit.
- Resolution receipt: implementation commit `86134755f3f26a268585b14264946571592cd4a5` and
  `docs/evidence/001-04-palette-equivariance.json`.

## B-001-0017 — Stage 04 seed-11 base efficiency changed

- Status: OPEN
- Stage: 04–10
- Opened: 2026-08-22
- Burden: The frozen Build 000 base seed-11 synthetic case completed in one action. The generic
  palette-equivariant controller now completes both base and paired palette variants in three
  identical actions. This meets the predeclared Stage 04 parity/completion gate but is an observed
  action-efficiency regression, not evidence that the extra actions are free.
- Current evidence: official clean Stage 04 artifact
  `sha256:c76ad6ecf0c956b51579b27d6543734e7368ca48fb0cadfce3134735be895676`.
- Next discriminating action: include the unchanged Build 000 benchmark and action counts in Stage
  10 regression evaluation; do not optimize against this one seed before Stage 05 action semantics
  and Stage 08 controller cadence are measured.
- Resolution condition: matched robustness evidence shows no material aggregate efficiency loss, or
  a generic repair restores the action without weakening palette/action equivariance.

## B-001-0018 — Whole-effect identity fragmented a stable translation facet

- Status: RESOLVED
- Stage: 05
- Opened: 2026-08-22
- Failed approaches: The first action registry treated a translation that happened to restore a
  prior frame as a different mutually exclusive semantic identity from the same ordinary
  translation. One paired smoke reached only 5/12 inverse requests, and the integrated 16-seed
  regression fell to 15/16 because seed 13 oscillated until its action budget expired.
- Preserved failure evidence: `C:/a/arc3-b001/stage05-smoke-pair-02`; and the 45-file, 3,030,753-byte
  seed-13 trace/checkpoint bundle at
  `C:/a/arc3-b001/artifacts/stage05/failed-mechanisms/seed13-pre-translation-facet`, whose
  `trace/active.jsonl` SHA-256 is
  `0f14f37dad736d3f279920949b4e2c54911d916a124a00493337efa7cdfc9c76`.
- Resolution: Add the conservative conditioned displacement projection recorded in D-001-0014.
  The resolving smoke passed 4/4; all six seed-13 permutations passed 4/4; all 16 compatibility
  seeds completed within 3–13 actions; multi-displacement controls remained unresolved.
- Resolution receipt: `C:/a/arc3-b001/stage05-smoke-pair-04`,
  `C:/a/arc3-b001/stage05-seed13-after-translation-facet`, 67/67 focused tests, and the official
  clean Stage 05 artifact
  `sha256:b2ea83ff85f50f005e8630e34857741b70471b232781464fa8e3825d6f33bc07`.
  The failed evidence remains retained after resolution.

## B-001-0019 — Opaque-handle calibration has a measured historical action cost

- Status: OPEN
- Stage: 05–10
- Opened: 2026-08-22
- Burden: The generic calibration prefix repairs both historical action-remap failures, but the
  unpermuted seed-7 case rises from seven Build 000/Stage 04 actions to nine Stage 05 actions, and
  seed 11 remains three actions versus the Build 000 one-action case. Across the two unpermuted
  historical cases, Build 001 uses 12 actions versus Build 000's eight, a 50% increase. Calibration
  actions are fully charged; the equivariance PASS does not make them free.
- Current evidence: clean Stage 05 artifact
  `sha256:b2ea83ff85f50f005e8630e34857741b70471b232781464fa8e3825d6f33bc07`.
  The remapped variants improve from two 16-action non-completions to wins in nine and five actions,
  respectively, so this is an efficiency burden alongside a real robustness repair.
- Next discriminating action: retain the exact calibration policy through Stage 09 development and
  Stage 10 regression evaluation, compare matched completion and action-efficiency metrics against
  Build 000/B0 and ablations, then optimize only with generic measured evidence.
- Resolution condition: a generic discovery/caching strategy preserves the frozen action-
  equivariance and ambiguity controls while reducing matched aggregate actions without lowering
  completion, or Stage 10 evidence shows the overhead is not materially harmful on the declared
  development matrix.

## B-001-0020 — Stage 05 CI exposed stale pre-transition expectations and a candidate-bound defect

- Status: RESOLVED
- Stage: 05
- Opened: 2026-08-22
- Failure evidence: both push run `32556414798` and draft-PR run `32556416756` failed on Linux and
  Windows at source commit `291e73e197fb9425465c072923804b2a377fbfb8`; the shared test result
  was 492 passed and two failed. One ablation test incorrectly expected an accepted world model
  before any transition evidence. A second test exposed that prepending the mandatory coordinate
  calibration request returned three coordinate candidates under a configured limit of two.
- Resolution: require the first real consequence before asserting model-promotion receipts; count
  mandatory coordinate calibration inside the configured candidate maximum; and preserve the
  original Stage 05 artifact under
  `C:/a/arc3-b001/artifacts/stage05/superseded-291e73e/` with raw file SHA-256
  `6280fbe932fec3fa23fae6ba430093ca94a10135b052370673a801e38ff56a02`.
- Resolution receipt: correcting commit `43713f8add4495cb48e15d9edab402564ab8b8da`; focused tests
  7/7; clean Stage 16 source guards 2/2; corrected frozen Stage 05 artifact self-hash
  `sha256:b2ea83ff85f50f005e8630e34857741b70471b232781464fa8e3825d6f33bc07`;
  green push run `32557369468` and draft-PR run `32557371792` on both Linux and Windows.

## B-001-0021 — Integrity CLI does not infer the Build 001 nested manifest identity

- Status: RESOLVED
- Stage: 05–06
- Opened: 2026-08-22
- Failure evidence: on clean commit `916c80174b16b75c03d65b2ff9613116b41fff2a`, invoking
  `scripts.check_competition_integrity` with the Build 001 run-state but without
  `--expected-manifest-sha256` returned exit 1 and the single blocking finding
  `manifest-identity-unbound`. Its receipt is
  `C:/a/arc3-b001/artifacts/stage06/preimplementation-integrity.json`, file SHA-256
  `f7d6028981573d6df232fa3d3ab5d9e6c6ad618b359f50b7a53bcdc6fa5adc0e`; policy,
  supply-chain, and zero-finding secret checks still passed.
- Resolution: supply the already frozen manifest identity explicitly as the CLI contract requires:
  `--expected-manifest-sha256 682d5891c2aface54803d9bd1173c55ed21e89856e13b8a478fb9276ee963f2f`.
- Resolution receipt: `C:/a/arc3-b001/artifacts/stage06/preimplementation-integrity-pinned.json`,
  file SHA-256 `4209570fe577904844577ad5ead0a0d2d984673316b82dd0f1f9f0fd35089b0a`,
  receipt hash `sha256:993bbce75fb055058711949d873ac5c73e6cc0a6cabe2cf4e93cf04fd12923a3`;
  exit 0, zero blocking findings, zero warnings, zero secret findings.

## B-001-0022 — Stage 06 reopening required several failed generic mechanisms

- Status: OPEN
- Stage: 06
- Opened: 2026-08-22
- Burden: Pre-official Stage 06 smoke runs exposed distinct generic failures before the frozen
  112-execution matrix was permitted to run. Early controllers did not reach the predeclared
  readiness/trigger boundary; later controllers reopened correctly but failed to retarget and
  complete; early harness folds did not independently reconstruct the lifecycle from trace.
- Preserved failure evidence:
  - trigger/readiness failures:
    `smoke-001-action-rotation` (`sha256:46b9ce2c0f670d8bff693d1419b0995b06d88d32b21af41e1afcba1f70678cb5`),
    `smoke-002-action-rotation-no-markers` (`sha256:38c5f135466954df2826c4d3e8a61b70014e4e93d785b7e792aa6fbc46d38702`),
    `smoke-008-harness-traversability-transformed` (`sha256:cc122a843b97a89524910f4c9f024019a83823ba1987ee57fae73a9b87ff001d`),
    `smoke-009-harness-noise-transformed` (`sha256:23dba247004c841364318ae3280ade030be5c2c7c08140171d21429c5bec2cc4`),
    and `smoke-012-noise-diagonal-stale-goal` (`sha256:a718773f5f4b7e0d9d92f14f130a93cc1986348511b5c7632ae0ec5695876d14`);
  - lifecycle API failure: `smoke-004-noise-static-lane`
    (`sha256:05cb2ef0cd4535a514b01f7a94218d4048c78a2c82155019df6dbc49f082f4df`);
  - post-reopening completion failures:
    `smoke-003-action-rotation-static-goal` (`sha256:4ca86b6e6485244cfdbb81ee92c89e0de6f9a38a7f8b45aafbabf4075d7c947d`),
    `smoke-017-action-transformed-latest-core` (`sha256:b028f7b231f56e529eabc4ae437af8ed59822fde1d5317fe8f65d22e4553d763`),
    and `smoke-019-traversability-transformed-latest-core`
    (`sha256:d9b7692dfbc212df5fdb6373ca2fc6b6e6225e7cbe3fc69c345dd6a5d67f1abb`),
    plus the later fully audited transformed failures
    `smoke-027-transformed-traversability`
    (`sha256:68f7e6c88d1820ca3c0e42b66c158176745c06b456ea37463bde4fe677cc7e6b`)
    and `smoke-028-transformed-action-global`
    (`sha256:5b136f91da6b54cb75a32b7e07842a923898e0bfea160b1236d5c782a32d3cda`);
  - trace/lifecycle-fold failures:
    `smoke-005-harness-action` (`sha256:6fc61a058f2855ef88a59ab1615bbc1f9b24ec45f57281f8354433e3c70b154f`),
    `smoke-006-harness-action` (`sha256:bea3030a60639bf46ced337c669f60cd851845382c376e2447f9adbd9c4552e6`),
    `smoke-020-action-identity-audit` (`sha256:4ba0ef11c4968bac4fc87e19671f6cadf13c2f5c2e061565e9b30246312dc767`),
    `smoke-024-noise-domain-readiness` (`sha256:81000471da76dbb2d25c6114b3b89ef664410ce6bb27d4ae8bc4a791b5fb11aa`),
    and `smoke-025-noise-lifecycle-fold` (`sha256:22db0a9e2488d35d31b739f82827e02ea2306da6883f1f74ce7c29efe997f4fd`).
  All paths are beneath
  `C:/a/arc3-b001/artifacts/stage06/failed-mechanisms/` and remain outside the official result path.
- Current evidence: the later identity action smoke passed in 18 actions with trigger 6 and terminal
  `WIN` at `smoke-021-action-identity-audit/result.json`
  (`sha256:bb9563cebddb939982b9562b1cfba1d11f6aae64b5d020c2b92b04f82d837d0f`),
  A stationary-noise replay smoke also passed with trigger 8 and `WIN` in 17 actions at
  `smoke-026-noise-replay-pass/result.json`
  (`sha256:9b296b52d6618356328eada992cb7155dfa30fece591ef46b173753787da7fb1`).
  The generic repairs then resolved both transformed mechanism failures without changing the
  evaluator gate: `smoke-031-transformed-action-global/result.json` passed with trigger 6,
  confirmation 7, and `WIN` in 18 actions
  (`sha256:10823549bc8d8f2ffb48ca8fb02ff43862ebf84f5d16913b2175872becd78980`),
  while `smoke-032-transformed-traversability/result.json` passed with trigger 8, confirmation 9,
  and `WIN` in 21 actions
  (`sha256:4dda57c6d4d4bec4f7c3c029c19a747bc029cdf1d27551c2adcffdbd09b2108e`).
  These passing smokes do not resolve the frozen matrix or checkpoint obligations.
- Next discriminating action: finish cross-transform and checkpoint preflight, freeze a clean source
  commit, then execute the unchanged official 112-execution harness once all P0 gates pass.
- Resolution condition: the official Stage 06 artifact either meets the frozen decision rule or
  records an honest bounded mechanism result, with every earlier failed receipt retained.
- Resolution receipt: none.
- Stage 06 closeout: official Attempt 02 completed 112/112 executions and is durably classified
  `FAILED_MECHANISM`. Action-effect rotation passed 32/32, but traversability passed 0/32 and the
  stationary-noise control passed 0/32 because candidate-linked typed closure was absent despite
  terminal `WIN`. The historical smoke failures remain preserved. This burden remains open as the
  unresolved generic reopening mechanism; Stage 07 proceeds independently rather than rerunning or
  weakening Stage 06.
- Current receipt: `docs/evidence/001-06-rule-change-reopening.json`; raw artifact file
  `sha256:198201b86d6bbbefd01188cdea67bde4297f402a41ca1531a4fb05a527627151`.

## B-001-0023 — Rehashed Stage 06 checkpoint exposed self-authored restore authority

- Status: OPEN
- Stage: 06
- Opened: 2026-08-22
- Burden: The first expanded restore suite rejected a valid historical observation because restore
  rebuilt earlier symbolic states with the final palette registry. A subsequent read-only audit
  found additional derived action, mechanics, hypothesis, plan, counter, and pending-action fields
  that were structurally checked but not yet reconstructed or exactly bound to immutable trace
  receipts. A checkpoint whose outer hash is recomputed must not manufacture policy authority.
- Failure evidence: `C:/a/arc3-b001/artifacts/stage06/failed-mechanisms/restore-final-palette-registry/junit.xml`,
  3,823 bytes, SHA-256
  `b241e7b472d56c7e821e3cebf91c2f96a244cbe9b8855ef1b44c00ffb476631d`;
  the expanded run reported 43 passed and one failed before repair. The first frozen PRE_TRIGGER
  checkpoint pair then produced two individually successful `WIN` branches but failed the exact
  next-action gate because the checkpoint boundary was not reached before `choose_action`:
  `smoke-033-checkpoint-pre-trigger/result.json`
  (`sha256:abff536c01f0d8cbc71c16ecde2bbcb6c7bdd03e9f3e2ab6270d649e092f1951`).
  Its diagnostic receipt proves the exact-support pre-action state had an affected model but no
  registered dependent plan/prediction:
  `smoke-035-pretrigger-boundary-diagnostic/result.json`
  (`sha256:87046fe66ca846cea7d2ddb3445637fc3821f11e3d16ededa380dfcd6502e249`).
  The first POST_REOPEN pair failed before branch continuation because chronological reconstruction
  rejected the transformed successor-epoch action registry:
  `smoke-034-checkpoint-post-reopen/result.json`
  (`sha256:b2863c4be4de41a93225a33006e3fb68448731d24a28b5ba7937b8af20a760cb`).
  All three smoke paths are beneath the same retained `failed-mechanisms` root.
- Current bounded verification: the combined changed Stage 06 core, harness, integration, replay,
  and fixture subset passed 83/83 tests, but this does not resolve the two checkpoint-boundary
  failures.
- Next discriminating action: reconstruct palette/symbolic observations chronologically; bind every
  preserved transition to its immediate selected/submitted/consequence/returned-observation
  quartet; validate lifecycle terminal payloads and epoch lineage from trace; and add rehashed
  tamper tests for pending actions and every action-authoritative restored field.
- Resolution condition: valid historical and successor-epoch checkpoints restore exactly, while
  each rehashed authority mutation fails before action selection; the expanded replay suite, Ruff,
  and strict mypy all pass.
- Resolution receipt: none.
- Stage 06 closeout: the frozen matrix passed all four action-effect rotation checkpoint pairs but
  failed all four traversability pairs at the `validity` predicate, for 4/8 overall. All 112 traces
  replayed and prefix immutability passed, but those aggregate checks cannot replace the missing
  family-specific restore validity. The burden remains open.

## B-001-0024 — Same-handle repetition cannot prove the frozen global action rotation

- Status: OPEN
- Stage: 06
- Opened: 2026-08-22
- Burden: The first fixture/controller implementation could confirm the action-effect intervention
  from two consequences of one opaque handle. The frozen predeclaration instead changes every
  latent translation and requires the second qualifying consequence to support the same global
  clockwise successor mapping. Repetition establishes persistence for one handle, not the declared
  cross-handle relation.
- Current evidence: source review against
  `docs/evidence/001-06-rule-change-predeclaration.json`; no official Stage 06 matrix has run.
- Bounded resolving evidence: the controller now requires two distinct raw handles and transition
  receipts for the typed global action-mapping candidate; the repeated-handle negative regression
  passes, and transformed global smoke `smoke-031-transformed-action-global/result.json` passed with
  trigger 6, cross-handle confirmation 7, and `WIN` in 18 actions
  (`sha256:10823549bc8d8f2ffb48ca8fb02ff43862ebf84f5d16913b2175872becd78980`).
  The burden remains open until the frozen matrix exercises every declared transform.
- Next discriminating action: require two distinct affected handles/effects with one coherent typed
  global transformation, and add an adversarial regression proving repeated same-handle evidence
  cannot confirm the global change.
- Resolution condition: typed cross-handle confirmation and the adversarial test pass throughout
  identity/transformed smoke cases and the frozen official matrix.
- Resolution receipt: none.
- Stage 06 closeout: the official action-effect rotation family passed all 32 identity/transformed
  cases and all four of its checkpoint pairs, providing bounded support for the cross-handle repair.
  The broader Stage 06 acceptance still failed its second intervention family and every noise
  control, so this burden remains open pending a later generic closure review rather than being
  erased by the successful action-rotation subset.

## B-001-0025 — First official Stage 06 attempt exceeded the Windows path boundary

- Status: RESOLVED
- Stage: 06
- Opened: 2026-08-22
- Burden: The first clean-source official harness attempt stopped before its first intervention
  case completed. The full frozen case ID was reused as a filesystem directory component, making
  an immutable temporary blob path 283 characters long. `Path.open(mode='xb')` returned
  `FileNotFoundError` on Windows. This is `FAILED_INFRASTRUCTURE`, not evidence for or against the
  reopening mechanism.
- Preserved evidence: `docs/evidence/001-06-failed-infrastructure-attempt-01.json`; the ten-file,
  16,846,070-byte partial work tree was moved intact to
  `C:/a/arc3-b001/artifacts/stage06/failed-infrastructure/official-attempt-01-d1866e0` and has
  recursive manifest hash
  `sha256:66e31a5df20dbdc5629eae1a063c001cd62e50615519c2c4095422eb77bda080`.
  No official result JSON was created and zero mechanism cases completed.
- Next discriminating action: map execution directories to deterministic bounded
  content-addressed components, verify uniqueness across the frozen intervention, noise, and
  checkpoint schedules, then rerun the unchanged matrix from a new clean source and new artifact
  paths.
- Resolution condition: the path mapping tests, repository verification, and superseding frozen
  matrix complete without path failure; Attempt 01 remains preserved and separately labeled.
- Resolution: clean preflight 059 exercised a runtime root eight characters longer than Attempt 02,
  projected a 249-character temporary path, and reported zero path failures. The superseding frozen
  matrix then completed all 112 executions with zero infrastructure failures. Attempt 01 and its
  archived partial tree remain preserved and separately labeled.
- Resolution receipts: `C:/a/arc3-b001/artifacts/stage06/preflight/s059-ordered-support-ec51f7e/result.json`,
  file SHA-256
  `13d088883014bc61ae3ad5943e2e87b0c8b8f85b0bd0994263048e0ea37642c0`;
  `docs/evidence/001-06-rule-change-reopening.json`; Attempt 02 raw artifact file SHA-256
  `198201b86d6bbbefd01188cdea67bde4297f402a41ca1531a4fb05a527627151`.

## B-001-0026 — Independent sorting broke causal support-tuple alignment

- Status: RESOLVED
- Stage: 06
- Opened: 2026-08-22
- Burden: Nonpromotable runtime path preflight 058 proved the Windows path repair but stopped on a
  separate source-honesty failure. The candidate received support in `ACTION4`, then `ACTION1`
  order. Its contradiction and transition arrays retained arrival order, while the context array
  was independently sorted to `ACTION1`, `ACTION4`. Positional causal linkage therefore failed.
  The terminal `WIN` in 18 actions does not override `case_passed=false`.
- Preserved evidence: `docs/evidence/001-06-preflight-058-failed-mechanism.json`; external receipt
  `C:/a/arc3-b001/artifacts/stage06/failed-mechanisms/s058-path-preflight-7b6133d/result.json`,
  file SHA-256 `b864d5391a45ed12468d8c7a0ec97f6fabe4c5e7cb09ae3b80f140d5e086b91b`,
  self-hash `sha256:9534e8b993f6cda329fc07545bf785b6ab92f91df4c320ef1fef1b436573e23c`;
  immutable trace SHA-256
  `57077d0301dafef5502d38c70f2d40862dd005aa322535d3b43f9b74191ef350`.
- Contradictory evidence preserved: the clean 592-test suite at `7b6133d` passed in 356.84 seconds,
  showing this ordering case was absent from prior coverage. Green tests are not promoted over the
  failed trace predicate.
- Next discriminating action: preserve the three support dimensions as one arrival-ordered typed
  receipt vector, strengthen restore to compare that order directly, reject partial duplicate
  aliasing, and add non-lexicographic, repeated-context, transformed-handle, checkpoint, and tamper
  regressions without weakening the harness.
- Independent-audit expansion: the lifecycle summary fold also ignored the support events and
  trusted terminal arrays, so it could false-pass a terminal-only invented confirmation. The
  repair must reconstruct from contiguous support indices and compare the terminal payload
  exactly. Predecessor-recovery event IDs are likewise trace-ordered and must not be lexically
  normalized. Derived candidate mutation must remain downstream of its immutable support append.
- Resolution condition: the exact failed case and adversarial regressions pass from clean source;
  preflight 058 remains immutable and a new path preflight receipt is created rather than replacing
  it.
- Resolution: clean preflight 059 passed the exact transformed action-rotation case with ordered
  candidate support closure, trigger 6, confirmation 7, `WIN` in 18 actions, and a 24/24-predicate
  checkpoint pair. The official action-rotation matrix then passed 32/32 while all 112 traces
  replayed and retained immutable prefixes. Preflight 058 remains unchanged at its original path.
- Resolution receipts: `C:/a/arc3-b001/artifacts/stage06/preflight/s059-ordered-support-ec51f7e/result.json`,
  file SHA-256
  `13d088883014bc61ae3ad5943e2e87b0c8b8f85b0bd0994263048e0ea37642c0`,
  self-hash
  `sha256:4edb729d70ebcd1b5b3cd92de99b8183a7ff198440e51dce2a9201630da2a711`;
  `docs/evidence/001-06-rule-change-reopening.json`.

## B-001-0027 — Frozen Stage 07 B07 overlap-contact construction was infeasible

- Status: RESOLVED
- Stage: 07
- Opened: 2026-08-22
- Burden: the committed B07 false-rule case required a mover to overlap a beacon using only one
  movement rule and one contact rule, while explicitly prohibiting a collision rule. The pinned
  executor defaults every unmatched overlap to `BLOCK`, so neither rare contact rule could execute.
  Running the case unchanged would structurally predetermine a false-rule gate failure.
- Preserved failure: base declaration
  `docs/evidence/001-07-retrodiction-predeclaration.json`, SHA-256
  `d4eb82f2e0c04e1c94be4d6fbaa8862aa808cc07932042a02d0c5fbcc02dc608`; rule-engine blob
  `751bb35efabd14f028ad2d3b54ee0814dd7176ee`; no Stage 07 measurement had begun.
- Resolution: amendment 01 changes only B07 to an adjacent contact after mover x2 advances to x3
  beside beacon x4. It adds no production rule and changes no mode, count, seed, budget, rank, or
  decision gate.
- Resolution receipt: `docs/evidence/001-07-retrodiction-predeclaration-amendment-01.json`, SHA-256
  `5c8ff0c91602d86ecaadd61197dfb80681f618ad4e6c810c26933ca337fdcc3b`.

## B-001-0028 — Frozen Stage 07 false-rule cases omitted concrete paired seeds

- Status: RESOLVED
- Stage: 07
- Opened: 2026-08-22
- Burden: the base declaration required controller seed equals case seed but did not assign B01
  through B08 concrete seeds. A harness could therefore choose them after observing results.
- Resolution: before implementation measurement, amendment 01 binds B01 through B08 to seeds 1
  through 8 respectively and requires the sealed case manifest to repeat and validate them.
- Resolution receipt: `docs/evidence/001-07-retrodiction-predeclaration-amendment-01.json`, SHA-256
  `5c8ff0c91602d86ecaadd61197dfb80681f618ad4e6c810c26933ca337fdcc3b`.

## B-001-0029 — Initial cache restore validation trusted stored residual contents

- Status: RESOLVED
- Stage: 07
- Opened: 2026-08-22
- Burden: the first typed `RetrodictionCacheEntry.validate_against` implementation reconstructed
  the artifact from checkpoint-stored outcomes. Because the legacy artifact identity summarizes
  match/contradiction counts rather than every residual field, an attacker could alter residual
  content, recompute surrounding checkpoint hashes, and potentially pass that local validation.
  No official Stage 07 measurement or public-development attempt had begun.
- Resolution: restore validation now recomputes every transition outcome and residual from the
  reconstructed model plus immutable transition evidence, requires exact tuple equality with the
  stored fold, and materializes the compared artifact from the recomputed outcomes.
- Resolution receipt: source checkpoint `586e8ba2c9c414b4bf2cc426ad5c1bbd357d5258`;
  `tests/unit/test_retrodiction_modes.py` includes residual-content tamper coverage; the combined
  retrodiction suite passed 33/33 with strict lint, format, and type checks.

## B-001-0030 — Initial event-triggered reuse payload omitted its causal receipts

- Status: RESOLVED
- Stage: 07
- Opened: 2026-08-22
- Burden: the first EVENT_TRIGGERED runtime could require matched prediction evidence in memory,
  but its immutable started/reused/completed payloads omitted those causal identities. A restore
  could therefore see that reuse occurred without independently proving which pre-action prediction
  and returned consequence authorized it. No official Stage 07 measurement or public-development
  attempt had begun.
- Resolution: the plan now derives an exact ordered suffix-only authorization vector, emits it on
  every related trace payload, emits an empty vector on non-reuse paths, and rejects missing,
  injected, reordered, wrong-model, or invalid-scope items before execution.
- Resolution receipt: source checkpoint `44fc3666522db4787f4349c4a5cb5ee085f787d9`; the 35-test
  focused runtime suite and strict
  lint, format, and type checks passed. Controller-level immutable-trace fold validation remains a
  required premeasurement integration check rather than being inferred from this pure-runtime fix.

## B-001-0031 — Prediction restore initially omitted three action-authority fields

- Status: RESOLVED
- Stage: 07
- Opened: 2026-08-22
- Burden: checkpoint restore validated a pending prediction receipt without binding its action,
  action-decision identity, and mechanics epoch. A rehashed trace/checkpoint mutation could retain
  prediction-shaped data outside the exact pre-action authority boundary.
- Resolution: restore now reconstructs and compares the action, decision, mechanics epoch, model,
  state, and dependency boundary; adversarial rehashed mutations fail before action selection.
- Resolution receipt: source checkpoint `2a78ba0f873a6f2c0e2b214a953f4b303057139e`; focused 42/42
  and broad 112/112 synthetic/replay tests passed with Ruff and strict mypy.

## B-001-0032 — Cache order and trigger generation were initially checkpoint-trusted

- Status: RESOLVED
- Stage: 07
- Opened: 2026-08-22
- Burden: cache access ordinals and event-trigger generations could be changed with surrounding
  hashes because restore did not derive them exactly from immutable completion order.
- Resolution: access ordinals and generations are now folded from receipt order, with rehashed
  swap and generation mutations rejected.
- Resolution receipt: source checkpoint `2a78ba0f873a6f2c0e2b214a953f4b303057139e` and
  `tests/replay/test_retrodiction_checkpoint.py`.

## B-001-0033 — Initial profiling and NONE/RECENT audit receipts omitted real work

- Status: RESOLVED
- Stage: 07
- Opened: 2026-08-22
- Burden: the first integration profiled only part of retrodiction rather than plan, execute, and
  commit, while NONE and RECENT could inherit a misleading full-audit generation receipt.
- Resolution: the complete typed runtime path is profiled under the retrodiction phase; NONE and
  RECENT are explicitly non-full generation-zero modes.
- Resolution receipt: source checkpoint `2a78ba0f873a6f2c0e2b214a953f4b303057139e`; phase-scoped
  cache-hit and mode-receipt tests pass.

## B-001-0034 — Integrity scanner initially ignored the active Build 001 holdout binding

- Status: RESOLVED
- Stage: 07
- Opened: 2026-08-22
- Burden: the competition-integrity scanner recognized the Build 000 run-state shape but not the
  active Build 001 `holdout.manifest` and `holdout.manifest_sha256` fields, producing a false
  manifest-binding failure for the controlling ledger.
- Resolution: the scanner accepts both typed shapes and still requires the exact current manifest
  hash; seven focused tests and a live Build 001 scan returned zero findings.
- Resolution receipt: source checkpoint `7f03b7a`; `tests/integrity/test_receipt.py`.

## B-001-0035 — First Stage 07 checkpoint strategy changed policy cost and still failed restore

- Status: RESOLVED
- Stage: 07
- Opened: 2026-08-22
- Burden: an exploratory Group C adapter enabled PRE_TRIGGER checkpointing with production memory
  solely to satisfy evaluator persistence. It produced 39 checkpoint files totaling 3,448,862
  bytes in the preserved run and still returned `checkpoint_valid=false`; it was not an official
  measurement and opened no public game.
- Preserved limitation: the exploratory worker did not retain its exact original stdout/command
  receipt, so its approximate 50.26-second narrative is not promoted into benchmark evidence.
- Resolution: a harness-only controller emits one truthful terminal content-addressed checkpoint
  while retaining the frozen `use_memory=False` policy semantics, then restores the exact closed
  state and validates its trace commitment.
- Resolution receipt: `docs/evidence/001-07-premeasurement-audit.json`; preserved directory
  `C:/a/arc3-b001/pytest-stage07-audit-20260822c`, 57 files, 5,074,716 bytes, recursive inventory
  hash `sha256:7166ea6c9d0be44530bd50d15aea28cddbaf3f68b4ca1aec001331bbf6054631`;
  source checkpoint `1cf1945c42bb7da42e63b423c4a986d72fd24ead`.

## B-001-0036 — Initial decision harness contained multiple fail-open eligibility paths

- Status: RESOLVED
- Stage: 07
- Opened: 2026-08-22
- Burden: the initial harness made Group C rows ineligible through its checkpoint implementation,
  attributed global rather than phase cache hits, compared cached B artifacts only to themselves,
  allowed caller-selected official paths, incompletely bound source ancestry, excluded terminal
  validation from cell time, treated a non-null prefix receipt as replay truth, and could retain a
  replacement decision after partial verification or resource failure.
- Resolution: official paths/source/asset identities are fixed; FULL pairing is exact; all cell
  work is measured; replay predicates must be true; memory is fail-closed; every resource,
  verification, source, trace, checkpoint, network, holdout, and matrix condition is an explicit
  final gate; `PARTIAL` forces `KEEP_FULL` and exit 1.
- Resolution receipt: source checkpoint `1cf1945c42bb7da42e63b423c4a986d72fd24ead`;
  `docs/evidence/001-07-premeasurement-audit.json`; 69/69 focused harness and 139/139 expanded
  Stage 07 tests passed.

## B-001-0037 — Artifact validity was initially asserted for non-retained completions

- Status: RESOLVED
- Stage: 07
- Opened: 2026-08-22
- Burden: the harness wrote `artifact_receipts_verified=true` after structural trace validation,
  while restore reconstructed only retained cache entries. FULL, NONE, RECENT, and evicted
  cache/event completions could therefore carry a hash-linked but semantically wrong artifact
  receipt and still satisfy that field.
- Resolution: every new completion contains a full normalized typed projection. Restore iterates
  every completion, replays its candidate against preserved typed transitions and mechanics epoch,
  and exact-compares the nested projection plus artifact ID, coverage vectors, completion, score,
  status, and weight. Stage 07 hard integrity now requires the independently restored receipt flag.
- Resolution receipt: source checkpoint `1cf1945c42bb7da42e63b423c4a986d72fd24ead`; all five
  controller modes restore in the focused adapter suite, and rehashed summary/nested-projection
  mutations fail.

## B-001-0038 — D-cell environment bytes were recorded but not enforced

- Status: RESOLVED
- Stage: 07
- Opened: 2026-08-22
- Burden: a local-public cell recorded its asset identity but did not compare it to a frozen
  expected digest or require paired cells to share identical bytes. Mutation at the fixed path
  could therefore survive source-integrity gating.
- Resolution: the harness binds the already measured `ar25-0c556536` aggregate and exact two-file
  tuple before open, after open, and after each episode; all ten D cells and both holdout boundary
  checks require exact equality. Stubbed no-game mutation tests cover after-open, after-episode,
  missing-cell, file-name, size, file-hash, and aggregate drift.
- Resolution receipt: source checkpoint `1cf1945c42bb7da42e63b423c4a986d72fd24ead`;
  aggregate SHA-256 `e796e615d2e10c93b849f9bf150308fbf84d624725deaf995d7ec2d1c2f86b22`.

## B-001-0039 — In-process non-return can outlive post-hoc wall gates

- Status: OPEN
- Stage: 07
- Opened: 2026-08-22
- Burden: per-cell and overall wall limits are checked between synchronous calls and fail a
  returned overrun, but an in-process third-party adapter or dependency that never returns cannot
  be preempted by the harness. It cannot create a false PASS, yet it can prevent the attempt from
  producing its defined partial artifact and exit code.
- Next discriminating action: add a process-supervised cell worker with receipt-preserving timeout
  termination, or demonstrate that every pinned call path supplies an independently enforced
  timeout without changing paired source identity.
- Resolution condition: a deliberately non-returning worker is terminated at the frozen boundary,
  a sealed failure receipt is written, and independent cells remain recoverable.
- Resolution receipt: none.

## B-001-0040 — Historical candidate rank lacks a prefix-derived authority fold

- Status: OPEN
- Stage: 07
- Opened: 2026-08-22
- Burden: restore recompiles a no-longer-current historical candidate's rules, hypothesis IDs, and
  compile residuals, but accepts its historical rank from the completion receipt. A coherent
  adversary able to rewrite and rehash trace plus checkpoint could forge rank-dependent score,
  semantic-fingerprint, namespace, and related identities consistently. Outcomes, residuals,
  coverage, status, rules, and honest official evidence are still recomputed.
- Next discriminating action: fold the hypothesis registry at each retrodiction start from only
  prefix-valid hypothesis events, derive historical rank from that state, and recompute the full
  plan/runtime namespace before accepting the receipt.
- Resolution condition: a coherent rehashed historical-rank mutation fails for retained and
  evicted completions while clean legacy/current checkpoints still restore.
- Resolution receipt: none.

## B-001-0041 — Stage 07 partial aggregation raised instead of serializing failure

- Status: RESOLVED
- Stage: 07, 08, 14
- Opened: 2026-08-22
- Burden: the unique official Stage 07 attempt exceeded its frozen overall wall limit after 279
  matrix measurements. `_apply_global_integrity` then indexed the absent ordinal-279 measurement
  and raised `KeyError` before the harness could serialize its declared `PARTIAL` result. Exact
  process-local wall, CPU, RSS, raw measurement, and microbenchmark arrays were lost with the
  process; they must not be reconstructed as measured values.
- Why it matters: a fail-closed experiment must preserve a machine-readable terminal artifact even
  when a resource boundary interrupts the declared matrix. Hash-linked raw receipts remain, but
  they are weaker and more expensive to recover than the intended terminal result.
- Current evidence: `docs/evidence/001-07-failed-infrastructure-attempt-01.json`; 279 cell
  directories, 6,615 files, 1,854,364,170 bytes, inventory SHA-256
  `fa79526cc91c096fa38868fe4aa11e52cad6c8f0fe8c804ebe00806ee6f4f62e`; no official output file;
  exit 1 at `_apply_global_integrity`; all five post-loop verification commands passed.
- Resolution: global integrity is now total over the completed prefix. Exact-count gates remain
  unchanged, and a CLI regression verifies that an explicitly incomplete result serializes as
  `PARTIAL`, retains `KEEP_FULL`, and exits nonzero. The unique attempt was not rerun.
- Resolution condition: a synthetic unit/integration fixture with a deliberately incomplete matrix
  writes a structurally valid `PARTIAL` artifact, selects `KEEP_FULL`, exits nonzero, and retains the
  missing-cell/resource failure without a `KeyError`.
- Resolution receipt: commit `85a0782e77e0549814363cbeefd50bb5eec6ca3c`;
  `docs/evidence/001-07-retrodiction-decision.json`; 150 focused Stage 07 tests passed.

## B-001-0042 — Every attempted Stage 07 local-public mode exceeded the mechanics epoch bound

- Status: OPEN
- Stage: 07, 08, 09
- Opened: 2026-08-22
- Burden: all nine attempted `local-public` D cells—five modes at seed 7 and four modes at seed
  23—raised `WorldModelError: mechanics transition bound exceeded for epoch`. The frozen overall
  limit was reached before seed-23 `CACHED_INCREMENTAL` started. No mode completed a permitted
  development episode, so Stage 07 provides no public benefit/cost comparison.
- Why it matters: retrodiction-mode selection cannot repair a shared bounded-world-model failure,
  and the same failure would prevent the two-speed or Stage 09 policy from interacting effectively
  unless the lifecycle/storage bound is addressed generically.
- Current evidence: the nine immutable failure receipts listed in
  `docs/evidence/001-07-failed-infrastructure-attempt-01.json`; development exposure ledger SHA-256
  `4f924df44b11decb392022a927b3296e0248a02edac2c87c53899d374045f0c7`; zero holdout events.
- Next discriminating action: isolate the transition-growth cause from the raw traces and implement
  a generic epoch rollover or bounded-history policy only if it preserves immutable receipts,
  accepted-rule authority, replay, checkpoint restore, and the Stage 06 negative evidence.
- Resolution condition: a predeclared generic development run completes within the same action and
  wall budgets without exceeding the epoch bound, while synthetic replay and contradiction tests
  remain within their frozen floors.
- Resolution receipt: none.

## B-001-0043 — Exceptional public-cell exit loses terminal measurement receipts

- Status: OPEN
- Stage: 07, 09
- Opened: 2026-08-22
- Burden: `_run_public_cell` rethrows an episode exception before its after-episode asset snapshot,
  scorecard sealing, normal measurement projection, and explicit adapter close. The Stage 07
  fallback measurement therefore reports zeros and omits the durable trace tail even though each
  of nine trace prefixes independently proves 65 submitted actions and returned consequences.
- Why it matters: failure preservation must distinguish "no action occurred" from "65 actions
  occurred before a controller fault." Missing terminal asset, network-attempt, resource, and
  scorecard receipts prevent the failed D rows from satisfying hard integrity or entering paired
  retrodiction gates.
- Current evidence: `docs/evidence/001-07-failed-infrastructure-attempt-01.json`; nine valid
  1,702-event trace prefixes with projection SHA-256
  `95ec8fddc04499f8f68411d5ba112670f219d87a74b5a8511cd6fdab2be364e6`; each reaches 65
  `action.submitted` and 65 `consequence.received` events, zero levels, and no terminal outcome.
- Next discriminating action: before Stage 09's decisive public run, make exceptional episode exit
  close the adapter and seal recoverable trace/action/resource/asset snapshots without converting
  the policy failure into PASS. Add a fault-injection regression test.
- Resolution condition: an injected post-action policy fault writes a terminal failure receipt with
  exact durable action/consequence counts, trace tail, after-failure asset identity, resources, and
  close outcome; the evaluator remains nonzero/failed and holdout exposure remains zero.
- Resolution receipt: none.
