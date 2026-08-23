# ARC3 Build 001 open burdens

Append-only record. Resolved burdens remain present with their resolving evidence; later success
does not erase earlier uncertainty or failed mechanisms.

## B-001-0001 — Local-public controller failure

- Status: RESOLVED_FOR_FUTURE_VALIDATION
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

- Status: RESOLVED_FOR_FUTURE_STAGE_09_CELLS
- Stage: 07, 09
- Opened: 2026-08-22
- Last updated: 2026-08-22
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
- Resolution: future public workers preserve the returned consequence before any derived baseline
  fold, close the policy/session/journal boundary, fold exact action/reset counts from the replayed
  trace, recover a game-bound official score when available, rehash local asset bytes, sample
  wall/CPU/RSS, and seal an explicit failed receipt. Local workers also count and deny five
  process-local Python socket entry points; this is not OS-level egress isolation.
- Resolution condition: an injected post-action policy fault writes a terminal failure receipt with
  exact durable action/consequence counts, trace tail, after-failure asset identity, resources, and
  close outcome; the evaluator remains nonzero/failed and holdout exposure remains zero.
- Resolution receipt: commits `b4b033b4206a2c0044544c992bd02b709d1c59ad` and
  `f5a2bd28f91eab6c3e16e335ec9b6b232f4d1804`; 29 focused public-runner, baseline-boundary,
  and evaluator tests passed with Ruff, format, and strict mypy. The existing Stage 07 development
  exposure ledger remains zero-holdout evidence at SHA-256
  `4f924df44b11decb392022a927b3296e0248a02edac2c87c53899d374045f0c7`.
- Historical boundary: the nine immutable Stage 07 cells remain unrepaired historical failures;
  their lost process-local terminal measurements are not reconstructed or claimed.
- Guard scope: `socket.create_connection`, `socket.getaddrinfo`, `socket.socket.connect`,
  `connect_ex`, and `sendto` during the local worker body. Preconnected descriptors, `send` or
  `sendall`, subprocess/native/ctypes transports, pre-install activity, and alternate socket
  implementations remain outside this metric.

## B-001-0044 — Recovered failure scores share aggregate policy means

- Status: RESOLVED
- Stage: 08, 09
- Opened: 2026-08-22
- Resolved: 2026-08-22
- Burden: the public evaluator correctly preserves a verified scorecard recovered after a derived
  policy failure, but `_aggregate` currently includes that failed run's score and completed levels
  in the policy mean/total alongside successful runs.
- Why it matters: any failure suppresses improvement claims and forces a failed or partial summary,
  so this cannot manufacture a PASS; however, readers could misread the aggregate mean without a
  separate recovered-failure field.
- Current evidence: the injected post-action failure preserves one verified level and aggregates to
  `FAILED_INFRASTRUCTURE` with `MECHANISM_NOT_OBSERVED`; 29 focused tests pass at
  `f5a2bd28f91eab6c3e16e335ec9b6b232f4d1804`.
- Resolution: public summary schema v0.2 gives successful receipts and recovered failed receipts
  separate typed score/level projections. Flat aggregate fields and improvement ranking consume
  only successful receipts; any failed receipt still disables improvement claims. Unverified
  failures are counted separately. The verifier retains an exact v0.1-only reconstruction path so
  immutable historical evidence remains reproducible without rewriting it.
- Resolution condition: aggregate/report schemas label successful and recovered-failure score and
  level totals separately, with regression coverage proving failures cannot enter the successful
  mean or improvement gate.
- Resolution receipt: commit `15eda558a40eea9ecb7f162aabdf6fb05ab64c4b`; 27 focused
  public-contract and public-episode tests, Ruff, format, and strict mypy pass. The frozen Stage 01
  evaluation reverified with 56 artifacts, one run, and zero errors.
- Compatibility boundary: new failed-only policy means are JSON null rather than numeric zero.
  Consumers must branch on summary schema v0.2; built-in verification accepts v0.1 and v0.2.

---

## 2026-08-22 Stage 08 integration updates

### B-001-0002 — Palette and action equivariance failures

- Status update: RESOLVED for the declared Build 001 mechanisms.
- Current evidence: Stage 04 passed 256/256 palette pairs and 16/16 palette checkpoint pairs.
  Stage 05 passed 128/128 action-remap pairs, 528/528 post-calibration inverse requests, 64/64
  causal controls, and 16/16 checkpoint pairs. The historical Build 000 failures remain preserved.
- Resolution receipt: `docs/evidence/001-04-palette-equivariance.json` and
  `docs/evidence/001-05-action-equivariance.json`.

### B-001-0003 — Rule-change exposure is incomplete

- Status update: RESOLVED_FOR_EXPOSURE; the attempted mechanism remains failed.
- Current evidence: Stage 06 guaranteed the intervention and exercised 32/32 action-effect rotation
  and 32/32 traversability-flip cases plus 32/32 stationary-noise controls. Action-effect rotation
  passed, while traversability recognition and the declared noise classification gate each failed;
  Stage 06 is honestly `FAILED_MECHANISM`.
- Remaining burden: the mechanism failures remain under B-001-0022, B-001-0023, and B-001-0024.
- Resolution receipt: `docs/evidence/001-06-rule-change-reopening.json`.

### B-001-0004 — Retrodiction evidence conflicts

- Status update: RESOLVED_AS_KEEP_FULL_FOR_BUILD_001.
- Current evidence: the unique frozen Stage 07 attempt ended `FAILED_INFRASTRUCTURE` after 279/280
  cells, zero microbenchmarks, and nine local-public mechanics-capacity faults. No replacement gate
  was eligible to run, so production correctly retained FULL. The partial evidence does not resolve
  the scientific benefit/cost conflict and cannot be promoted into a replacement claim.
- Resolution receipt: `docs/evidence/001-07-retrodiction-decision.json` and
  `docs/evidence/001-07-failed-infrastructure-attempt-01.json`.

### B-001-0009 — Explicit short pytest parent recurred once

- Status update: RESOLVED recurrence.
- Current evidence: the first three-test Stage 08 command returned three setup errors because
  `C:\a\arc3-b001-28c7a00\t` did not exist. Creating only that declared parent and rerunning the
  unchanged tests produced the expected code-level results; the final 19-test and 76-test suites
  both passed under explicit short base-temp roots.
- Resolution receipt: commit `df0cf75c63c37a784f6ca2df8b87e24d6404a6cb` records the verified
  source; the setup error is infrastructure evidence and makes no policy claim.

### B-001-0014 — Redundant prediction and state hashing lack an end-to-end repair receipt

- Status update: NARROWED; implementation parity passes, measured end-to-end savings remain open.
- Current evidence: Stage 08 now has a bounded evidence/configuration-keyed prediction cache,
  typed cache telemetry, reopening invalidation, exact restore validation, and no-cache parity
  coverage. The 19-test lifecycle suite and 76-test focused suite pass at `df0cf75`.
- Next discriminating action: run the frozen 20-cell A/B/C/D harness and evaluate the predeclared
  paired timing/materiality gates without changing the cache or cadence after observing results.
- Resolution receipt: none until the Stage 08 acceptance artifact is sealed.

### B-001-0042 — Every attempted Stage 07 local-public mode exceeded the mechanics epoch bound

- Status update: NARROWED by a generic capacity repair; public resolution remains open.
- Current evidence: mechanics transition capacity now derives from the config-hashed environment
  action budget and restores exactly. Focused lifecycle/controller/retrodiction/replay verification
  passed at commit `5d1a67840bf75a939e25832d8300fa9c835c0e1d`. No Stage 07 artifact was
  rewritten and no new local-public run has yet established that the repaired controller completes.
- Next discriminating action: the frozen Stage 08 public cells and Stage 09 development suite must
  exercise the unchanged generic repair inside their declared action and wall budgets.
- Resolution receipt: none; the nine Stage 07 failures remain immutable.

## B-001-0045 — Legacy cadence migration cannot honestly cross source identity

- Status: RESOLVED
- Stage: 08
- Opened: 2026-08-22
- Burden: a cadence-less checkpoint generated at commit
  `df961c7acd67cbe382e5a56a44d6e1358c61278d` cannot enter the intended migration branch when
  restored under the honest current source identity. Forcing the legacy commit into `RunContext`
  makes compatibility restore succeed but falsely stamps newly emitted cadence receipts with the
  old source identity.
- Why it matters: accepting the compatibility-only path would make a successful restart receipt
  misrepresent the source that actually produced it. Relaxing ordinary commitment validation would
  also weaken checkpoint authority.
- Current evidence: pristine 13-event legacy trace SHA-256
  `b3878c197f25693ab64893a1c2a774dba89264cde8c63d719ca3b94fe33e8aca`; checkpoint file SHA-256
  `f0eb87b174443acb9c805c0e3c4ca4b8c52c65a689769fb9c2c8d462bc67597f`; envelope hash
  `7e96ceddd19c4d078b8a172a45e02987e7bfc3f43107b03ed54cc8308bb654d7`. Honest current restore
  fails with `checkpoint commitment receipt is not exactly bound to its prior trace tail`.
- Resolution: `ARC3Controller.restore` now requires paired exact legacy code/source identities for
  cadence-less migration, validates the untouched checkpoint and commitment under that identity,
  rejects wrong, partial, current-commit, configuration-drifted, or cadence-bearing inputs, and
  writes one activation plus all later checkpoints under the honest current identity. Ordinary
  restore now also validates the current source identity rather than only Git/config identity.
- Resolution condition: pristine legacy bytes remain unchanged; pending action and exact replay are
  preserved without resubmission; wrong/missing legacy identity fails; activation occurs once under
  current source; and later checkpoint/continuation receipts validate under current identity.
- Resolution receipt: commit `7f994fc`; 21 focused legacy/controller checkpoint replay tests,
  Ruff, format, and strict mypy pass. A copied real `df961c7` artifact preserved the known trace,
  checkpoint-file, and envelope hashes while migrating once and then restoring normally; its final
  clean-commit receipt is `docs/evidence/001-08-premeasurement-audit.json`. The first final auditor
  attempt is retained as `FAILED_INFRASTRUCTURE`: its audit code referenced a nonexistent snapshot
  attribute after migration and normal restore had already passed. The second attempt from a fresh
  pristine copy passed under commit `2e78c258cfbee8be62462f61ed08ad04c00a8934`, preserved the
  29,970-byte legacy trace prefix and 14,433-byte checkpoint, emitted exactly one current-identity
  activation, blocked resubmission, applied one consequence, and restored the continued checkpoint.

## B-001-0046 — Stage 08 cadence integration regressed broad checkpoint boundaries

- Status: RESOLVED
- Stage: 08
- Opened: 2026-08-22
- Burden: remote CI at pushed commit `aecde0cb9969270bfe7b7eb24744ef6efbb16fe7`
  reported 19 failures and 863 passes on both Ubuntu and Windows. A reasoning selection begun from
  an observation remained in progress until action construction, so explicit checkpoints after an
  observation, budget-fault checkpoints, close after malformed input, Stage 07 adapter restores,
  and several frozen equivariance restores either refused to checkpoint or lost their current
  commitment. Intentional cadence/config mismatch tests also surfaced low-level commitment-source
  errors before their typed policy rejection.
- Why it matters: Stage 08 cannot be measured from a source that fails established checkpoint,
  replay, malformed-input, and restart contracts. A narrow integration suite passing did not prove
  broad compatibility.
- Current evidence: GitHub Actions runs `32601337309` and `32601335338`; each completed Linux and
  Windows test job reported the same 19 named failures with 863 passes. Lint, formatting, and strict
  mypy passed before the test failures. No public Stage 08 worker was started.
- Next discriminating action: terminalize or safely abort only the current revisable reasoning fold
  before an external checkpoint/fault, without checkpointing mid-deliberation or letting checkpoint
  frequency change cadence counters; preserve raw authority receipts and strict source identity;
  then rerun all 19 regressions plus the focused cadence/replay/checkpoint suites.
- Resolution condition: the exact 19 remote failures pass locally on the repaired source, cadence
  terminal/commitment adjacency and checkpoint/no-checkpoint policy parity are covered, the full
  local suite and new remote Linux/Windows CI pass, and the failure remains preserved here.
- Resolution receipt: none.

- Status update: NARROWED_PENDING_FULL_AND_REMOTE_VERIFICATION at commit
  `7c4ea86fda1fc5900b3c37b204e8c60c476cbab8`. The complete controller/cadence files pass 44/44;
  five adversarial restart cases pass; Ruff, format, and strict mypy pass. The exact 18 local
  regressions pass in 65.11 seconds, and the nineteenth Stage 16 fresh-process profile test passes
  from clean detached source in 52.01 seconds. Review found and repaired two additional precommit
  gaps: replaceable orphan `latest.json` influence and close-before-action cadence advancement. No
  public Stage 08 worker was started.
- Remaining resolution evidence: finish the full local suite and pushed Linux/Windows CI. Preserve
  the original 19-failure receipt even if all pass.

- Remote verification update: the push and draft-PR ARC3 CI runs `32604662810` and `32604664455`
  completed successfully at commit `7c4ea86fda1fc5900b3c37b204e8c60c476cbab8`. The draft-PR run
  passed lint, format, strict mypy, runtime doctor, and 885 tests on both Ubuntu (920.86 seconds)
  and Windows (1,569.18 seconds).
- Local verification infrastructure update: the first detached local full suite reported 863 passes
  and 22 Stage 08 contract-test failures in 1,868.09 seconds. Every failure was a missing
  `submission_ordinal` constructor argument because the pinned virtual environment's editable
  install imported
  `C:/Users/cdpan/OneDrive/Documents/ARC3/src/arc3/evaluation/two_speed_measurement.py` from the
  current dirty workspace while pytest collected tests from clean detached commit `7c4ea86`.
  Setting `PYTHONPATH=C:/a/arc3-ci-7c4ea86/src` changed the imported module path to the exact
  detached source. A second full local suite is running with that explicit source binding. Preserve
  the 22-failure receipt as `FAILED_INFRASTRUCTURE`; it is not evidence of a repaired-source
  mechanism regression.

## 2026-08-22 Stage 08 process-supervisor infrastructure update

### B-001-0009 — Isolated Windows pytest parent recurred under parallel workers

- Status update: RESOLVED recurrence.
- Current evidence: the first Stage 08 parent-supervisor test command passed four tests and raised
  eight setup errors when concurrent workers collided with the shared Windows pytest temporary
  parent (`WinError 5`). No assertion failed. The unchanged 12-test suite passed under explicit
  isolated `--basetemp=C:\a\arc3-b001\pytest-stage08-parent-agent-20260822-02 --no-cov`, and an
  independent rerun passed 12/12 under a second isolated short base-temp path.
- Resolution receipt: the Stage 08 parent-supervisor checkpoint retains the isolated commands and
  passing verification; this is infrastructure evidence, not policy evidence.

- Second recurrence: a clean detached full-suite command used the pinned environment's editable
  installation from the dirty primary workspace. The exact import-path probes above reproduced the
  mismatch and proved that explicit detached `PYTHONPATH` selects the intended source. The first
  863-pass/22-failure run is retained; a correctly source-bound rerun uses a distinct short
  `--basetemp` and does not overwrite it.

- Resolution receipt: commit `7c4ea86fda1fc5900b3c37b204e8c60c476cbab8`; remote push/PR
  runs `32604662810` and `32604664455` passed lint, format, strict mypy, doctor, and 885 tests on
  both Ubuntu and Windows. The correctly source-bound clean detached local suite passed 885/885 in
  2,139.82 seconds with `PYTHONPATH=C:/a/arc3-ci-7c4ea86/src` and isolated base-temp
  `C:/a/arc3-b001-28c7a00/t/full-7c-clean2`. The original 19 remote failures and the later
  863-pass/22-failure mixed-source run remain preserved; neither was relabeled as a mechanism result.

## B-001-0047 — Stage 08 supervisor used a Windows-only subprocess attribute directly

- Status: RESOLVED
- Stage: 08
- Opened: 2026-08-23
- Burden: the first push of the sealed process harness passed Ruff but failed strict mypy on both
  Ubuntu jobs before tests because Linux's typed `subprocess` module has no
  `CREATE_NEW_PROCESS_GROUP` attribute. The Windows-only execution branch had passed strict mypy
  locally on Windows, so the platform-specific type defect escaped the focused checkpoint.
- Why it matters: Stage 08 cannot open the public matrix from a source whose cross-platform strict
  type gate fails, even though the affected flag is only evaluated on Windows.
- Current evidence: GitHub Actions runs `32607075312` and `32607073797`; Ubuntu job IDs
  `97113626818` and `97113622798` failed at
  `scripts/measure_two_speed_controller.py:1089` with `[attr-defined]`. Ruff lint and format passed;
  the test and doctor steps were correctly skipped after the type failure. No Stage 08 public cell
  was exposed or launched.
- Repair under verification: resolve the platform constant through typed `getattr` at module load,
  preserving the exact Windows flag when present and zero only on platforms where the Windows
  launch branch is unreachable.
- Resolution condition: strict mypy passes under both Windows and an explicit Linux target; focused
  process-tree tests still pass on Windows; pushed Ubuntu and Windows CI pass from the repaired
  source; the original failed jobs remain cited here.
- Resolution receipt: the supervisor resolves the flag through typed `getattr`; strict mypy passed
  over 161 source files on Windows and under an explicit Linux target, and 111/111 focused Stage 08
  tests passed. Exact-source push run `32607264914` and draft-PR run `32607267169` passed lint,
  format, strict mypy, 959 tests, and runtime doctor on both Ubuntu and Windows at commit
  `2e78c258cfbee8be62462f61ed08ad04c00a8934`. The original two Ubuntu type failures remain
  preserved above and in the premeasurement audit.

## B-001-0048 — Stage 08 validators conflated close state and frame-hash namespaces

- Status: RESOLVED
- Stage: 08
- Opened: 2026-08-23
- Owner: Codex
- Burden: the unique Stage 08 attempt stopped after one development cell because two integration
  validators rejected valid frozen Build 000 evidence. Terminal restore compared the correct
  pre-`CLOSED` checkpoint phase with the post-close in-memory phase. Boundary validation required
  the domain-separated semantic `GridFrame.digest` to equal the trace descriptor/blob hash over
  canonical JSON, even though both identities were independently valid and intentionally differ.
- Why it matters: unit fixtures reused one fake hash for both namespaces and mocked restore success,
  so 111 focused tests and full cross-platform CI did not exercise the real frozen comparator's
  close or hashing contracts. The resulting fail-closed behavior protected claims but consumed the
  only permitted exposure of cell 00 and made the 20-cell timing gate unavailable.
- Last updated: 2026-08-23
- Current evidence: raw attempt SHA-256
  `7c39fa77de24bd1925d9dbd489d583118f96d4b7fe860678607f485506ad39d4`;
  worker result SHA-256 `523f0a6fbc8b34d9ea739e17d507597a3f94d506ed8521b19335644c776e1465`;
  replay-verified trace semantic frame digest `b0c134f1cbe1bac078337e72000916d047f34742d2202561fdb65c63ccfd6e37`
  versus trace frame/blob hash `dcb73927160522c26e2655d31ead221e6da6aab818037d20388bbf46e9afa1b0`.
  A read-only eight-boundary audit found the remaining decision, action, link, ordering, returned
  consequence, semantic receipt, and trace-adjacency predicates valid. See
  `docs/evidence/001-08-two-speed-controller.json` and D-001-0038.
- Next discriminating action: none for the generic validator repair. Do not rerun or resume the
  Stage 08 matrix.
- Resolution condition: the generic validator independently proves both hash namespaces and their
  causal link, accepts the correct pre-close checkpoint phase while still rejecting actual state
  drift, and regression tests fail under either original conflation. This can resolve the harness
  burden for future work but cannot change Stage 08 Attempt 01 from `FAILED_INFRASTRUCTURE`.
- Resolution receipt: commit `fa24a4326ed191a3dd97b36903a2032bb481c524` independently verifies
  trace blob/canonical-frame hashes and semantic `GridFrame.digest` values, retains their causal
  link, and compares restored state with the checkpoint-recorded phase. Real `BlobStore`/`GridFrame`
  and real close/checkpoint/restore regressions fail under the two original conflations. Integrated
  verification passed 113 focused tests, Ruff lint/format, and strict mypy over both repaired source
  and regression tests. Worker SHA-256 is
  `31cdea4060013d2a80358b2249d62bf556064f7e1ae87b729a84cb5715f61f03`; regression-test SHA-256 is
  `8cb7f6b12c4da65f23354187da6c9fb3f0ac303f6228b41154aaf1316b2851de`. The repair resolves only
  future validation infrastructure: immutable Attempt 01 remains `FAILED_INFRASTRUCTURE`, retains
  one development exposure, and remains non-rerunnable.

## B-001-0049 — A lock-only Stage 09 integrity scan could not authorize production policy

- Status: RESOLVED
- Stage: 09
- Opened: 2026-08-23
- Burden: the first Stage 09 integrity receipt scanned only `uv.lock`. It reported 60 non-blocking
  supply-chain warnings and no blocking finding, but it did not cover the full production policy,
  offline/runtime, game-ID, source-reading, or secret surfaces required by the decisive gate.
- Why it matters: absence of a blocking finding in a narrow scan cannot be promoted into full
  competition-integrity authority.
- Resolution receipt: fresh full-repository receipts from the exact frozen policy checkouts passed
  every one of the five integrity checks with zero findings. Build 001 receipt
  `C:/a/arc3-b001/artifacts/stage09/policy-integrity-2e78c258-full.json` has file SHA-256
  `9fd255b3a32549fd09c12247863319e8662805ed43f874b46e52eb3cb675834f`; Build 000 receipt
  `C:/a/arc3-b001/artifacts/stage09/policy-integrity-build000-90ecf726-full.json` has file SHA-256
  `b63ea29913a042930b01ace640c283dd0febce3597b637c3d8433fc981579349`.
- Boundary: the failed narrow receipt remains preserved and supplies no authority. These scans are
  non-playing static evidence and do not create a performance result.

## B-001-0050 — Stage 09 initially validated integrity receipts in the wrong hash namespace

- Status: RESOLVED
- Stage: 09
- Opened: 2026-08-23
- Burden: the first clean detached Stage 09 preflight used the evaluation artifact validator's
  newline-terminated canonical JSON contract for the integrity scanner's newline-free canonical
  receipt. Both valid full receipts therefore failed closed at the prior-authority boundary.
- Why it matters: two independently correct hash namespaces were conflated, making the decisive
  supervisor unavailable and tempting an unsafe bypass.
- Resolution receipt: commit `2a069f3ef0596cea3ec229ca550285286e7268b5` validates through
  `IntegrityReceipt.from_bytes` and adds a real-receipt regression. A clean detached non-playing
  preflight then returned `READY_NOT_EXECUTED`; receipt SHA-256
  `d8995e91466d9396a85097f1b44f7a641bdce3bcec3fe2cf3418443f814f71b7`; all thirteen predicates
  were true and no attempt, output, or exposure path was created.
- Boundary: this resolves only the receipt validator. Later independent audit findings remain
  separately open under B-001-0051.

## B-001-0051 — Independent audit found unsafe Stage 09 restart and evidence promotion paths

- Status: OPEN
- Stage: 09
- Opened: 2026-08-23
- Owner: Codex
- Burden: an independent static audit of the ready supervisor found that failed raw receipts could
  influence decisive completion/normal-termination/B0 metrics; exception class could promote an
  invariant failure into mechanism evidence; after-boundary reconstruction substituted current
  preflight values; terminal reconstruction did not live-replay every success/failure trace; an
  authorized live orphan could coexist with a terminal projection; partial terminals were not
  reconstructed canonically; and parent admission/finalization time was not fully bound.
- Why it matters: a self-consistent but malformed restart graph could manufacture or corrupt the
  Stage 09 gate even while individual receipt hashes verify.
- Current evidence: no Stage 09 gameplay has begun. The attempt, work, and exposure-ledger paths
  are absent. An isolated repair is in progress from commit `2a069f3`; decisive execution remains
  blocked until adversarial regressions, strict typing, lint, exact-source preflight, and a second
  independent audit all pass. The second audit additionally found that controller wall timeouts
  vanished from the frozen 80-action efficiency charge and that a supervisor crash after a durable
  cell receipt but before finalization left resume unable to seal or reconstruct the terminal cell.
  Continued audit found four further launch-blocking windows: a durable exposure without a launch
  or worker-abort receipt could not produce a typed terminal; a durable terminal output without its
  finalization could still be promoted as PASS; parent work before exposure had no durable open
  active-segment marker and could vanish across interruption; and pre-kill process snapshots did
  not prove that a racing descendant could not escape termination. All findings remain preserved
  until exact crash-injection, reboot, and process-tree regressions pass.
- Resolution condition: only raw `SUCCESS` cells may affect decisive metrics; all raw failures are
  infrastructure unless a separately sealed typed mechanism producer exists; every trace and
  action/reset budget is replayed; persisted observations reconstruct exactly; live launch tokens
  cannot be terminalized; partial/terminal graphs are canonical; full runtime and parent-time
  authority remain immutable through finalization; every timed cell has a durable open/closed
  segment; recovered terminal-finalization gaps cannot authorize PASS; and process-tree cleanup is
  verified against a race-safe OS supervision boundary or reported as failed infrastructure.

## B-001-0052 — Stage 10 and holdout authorization crossed sealed semantic boundaries

- Status: OPEN
- Stage: 10–12
- Opened: 2026-08-23
- Owner: Codex
- Burden: independent audit of commit `d300570` found that a Stage 10 rule child still invoked the
  default integrity scan that parses the public partition manifest; Stage 10 did not revalidate
  source at every suite or reject a pre-existing terminal before child launch; malformed typed
  metrics could be downgraded to mechanism failure; the `HOLDOUT_NOT_EARNED` path imported the ARC
  adapter and directly hashed/parsed the manifest; and earned action workers received no gate
  authority to revalidate immediately before environment action.
- Why it matters: sealed identifiers or assets must not enter a denied path, structural evidence
  failure must not become performance evidence, and parent-only authorization cannot survive
  source/evidence drift at the action boundary.
- Current evidence: Stage 10 has not executed and no holdout environment has been opened. Static
  exploit regressions and isolated repairs are in progress. The ten-game holdout remains
  `SEALED_UNCONSUMED` with zero gameplay events and zero locally acquired assets. Continued audit
  also found a mixed-tree path where a Stage 10 supervisor imported from tree A could validate and
  execute tree B with tree A's validator logic; explicit supervisor/import-closure origin binding
  is now required before any decisive launch. A further audit found that Stage 11 checked only two
  loaded module origins even though scanner/artifact helpers participate in authority, and that a
  Stage 10 `STARTED` record carried no process creation identity or verified orphan cleanup path.
- Resolution condition: package/production-only integrity never opens semantic public surfaces;
  exact source is bound from preflight through every suite; terminal graphs are canonical and
  non-rerunnable; malformed child evidence is infrastructure; denied paths import no adapter and
  read zero manifest bytes, identities, paths, or assets; earned workers carry and freshly validate
  exact evidence authority immediately before action; all participating first-party authority
  modules originate in the frozen execution tree; and interrupted synthetic children are either
  proven gone by immutable process-tree evidence or force a non-promotable infrastructure terminal.

## B-001-0053 — Holdout-gate integration fixtures drifted behind frozen evidence schemas

- Status: RESOLVED
- Stage: 11
- Opened: 2026-08-23
- Burden: after integrating Stage 09 aggregate schema v0.3 and Stage 10 result schema v0.2, the
  isolated holdout-gate fixtures still emitted older literal schema strings. Eleven of thirteen
  integration tests failed before any environment or manifest selection.
- Why it matters: a gate test that proves only stale fixture contracts cannot authorize the actual
  frozen evidence artifacts.
- Resolution receipt: commit `d300570868a84b092241a9d06002382cd574a825` imports the production
  schema constants into the fixtures; the focused suite passed 13/13 and Ruff passed. The original
  eleven failures remain preserved as integration evidence.
- Boundary: this resolves only schema alignment. The independent authority blockers under
  B-001-0052 still prevent Stage 10 execution and any holdout decision.

## B-001-0054 — Package-only verification could falsely pass crossed boundaries

- Status: OPEN
- Stage: 13
- Opened: 2026-08-23
- Owner: Codex
- Burden: exact-commit audit of `96de932` demonstrated four false-PASS paths: a `python -I`
  child bypassed inherited `sitecustomize` and read a protected synthetic file; `os.remove`
  deleted protected evidence without an attempt; a Windows junction bypassed lexical path
  checks; and a packaged synthetic agent sent UDP while startup reported zero network attempts.
  The first Linux package workflow also failed because isolated mode could not import the editable
  candidate source, and the workflow initially treated the verifier's exit code incorrectly.
- Why it matters: neither a zero-attempt receipt nor an offline startup PASS is evidence when the
  boundary can be escaped. Such receipts cannot authorize Stage 13, Stage 10, or holdout work.
- Current evidence: commits `903f9f5e137cdc1c699bc164173e21b3e6d8c3a7` and
  `24450526ca3c36e9b34fd6f3bc9116555aa37b6f` explicitly bind isolated imports, canonicalize
  junctions, default-deny external paths, protect the receipt/log, deny child processes and
  destructive operations, and deny all Python socket audit events during startup. Fourteen
  focused adversarial tests passed. Commits `af65b4058bea714c00040f3ebf87f3e6f8806981` and
  `129b76b720cefc42f8dca2710b54e90e34eb4a1b` additionally reject cross-platform unsafe archive
  members, protected explicit candidates before normalization/output exclusion, and UDP/DNS
  sandbox bypasses. Integrated verification passed 58 focused tests with one Windows privilege
  skip, 15 integrity tests with the same bounded privilege skip, Ruff, and strict Windows/Linux
  mypy over 175 files. Exact-source package workflow run `32616456163` then failed on both systems:
  Linux rejected an isolated interpreter-origin mismatch immediately; Windows ran for about 1,149
  seconds and returned `FAILED_MECHANISM` instead of the expected private-surface
  `BLOCKED_EXTERNAL`. The failure path skipped artifact upload, so the Windows internal check
  receipt is unavailable. The companion full CI Windows jobs later reported the exact platform
  regression: 10 `test_package_only_path_guard.py` assertions failed after bootstrap filesystem
  events were redacted as `protected-external-path`, while 1,074 tests passed; Linux passed the full
  suite. Exact-source repair verification, cross-platform guard-harness isolation, failure-artifact
  preservation, and the remaining descendant-process audit remain pending.
- Resolution condition: exact-source CI passes the guarded package subset and startup checks on
  both Windows and Linux; every audit exploit has a failing regression under the vulnerable code
  and a passing denial under the repair; package receipts preserve the scoped claim below; and
  package archive/integrity safety findings are closed or separately reported.

### B-001-0054 — Complete local repair is verified; hosted exact-source execution remains open

- Status update: NARROWED, not resolved.
- Last updated: 2026-08-23T04:45:18.5941520Z
- Current evidence: commit `d6d4bac1e33c9837856c08abcee61bcb14afd34e` isolates pytest
  framework state under the guarded root, preserves verifier evidence on failure, launches the
  lexical clone-local virtual-environment interpreter, and fails closed on process-tree accounting
  and Windows handle-close errors. The integrated Windows run passed 176 relevant tests with four
  bounded platform skips, including all 12 package-only path-guard tests; strict typing and Ruff
  passed. The isolated audit reported Linux-target type PASS and 86 reachable policy files with
  zero package-only static findings.
- Remaining burden: the fresh exact-source package receipt and hosted Linux/Windows workflow have
  not yet confirmed the repair. The prior failures remain evidence and are not relabeled.
- Resolution receipt: pending exact-source receipt and CI artifacts.

## B-001-0055 — Python audit guards are not OS process-tree containment

- Status: OPEN
- Stage: 13
- Opened: 2026-08-23
- Owner: Codex
- Burden: the repaired package-only test guard proves only that selected in-process tests made no
  Python-audited disallowed access and spawned no Python-audited child. It does not mount or ACL an
  allowlisted filesystem, create a network namespace/firewall boundary, prevent native-extension
  escape, or supervise aggregate descendant RSS and orphan termination. The verifier's current
  resource measurement is direct-process only.
- Why it matters: a Python audit receipt must not be promoted into a claim that the entire process
  tree was OS-contained or physically incapable of reaching every host resource.
- Current evidence: the v0.2 guard receipt states verbatim that it is not OS containment; the
  package startup receipt separately names Python audit-hook socket/process enforcement. Fresh
  hosted CI runners and filtered scopes reduce exposure but do not erase this architectural limit.
  A final isolated audit is testing descendant RSS and timeout termination; until measured repair
  evidence exists, no receipt or report may promote the direct-process measurements.
- Resolution condition: either add measured cross-platform OS filesystem/network/process-tree
  containment with adversarial orphan/native tests, or finish Stage 13 honestly as bounded/partial
  and keep the narrower Python-level claim in every receipt, report, and PR summary.

### B-001-0055 — Descendant supervision is measured but the OS-containment limit remains

- Status update: NARROWED, not resolved.
- Last updated: 2026-08-23T04:45:18.5941520Z
- Current evidence: commit `d6d4bac1e33c9837856c08abcee61bcb14afd34e` adds Windows
  suspended launch followed by kill-on-close Job assignment, POSIX inherited process groups,
  aggregate sampled RSS, bounded pipe drain, verified teardown, checked full-width Windows HANDLE
  closure, and adversarial descendant tests. Cleanup/accounting failure now forces
  `FAILED_INFRASTRUCTURE`.
- Remaining burden: Python audit hooks still are not OS filesystem/network containment; POSIX
  `setsid`/double-fork escape remains explicitly outside the claim; RSS is sampled rather than a
  hard memory limit; dynamic imports and native extensions are not proven contained.
- Resolution receipt: pending final Stage 13 bounded acceptance and cross-platform execution.

## B-001-0056 — Complete policy reachability invalidated the frozen wrapper integrity PASS

- Status: OPEN
- Stage: 09, 11, 13
- Opened: 2026-08-23
- Owner: Codex
- Burden: the repaired static import closure now includes the base module executed by
  `from arc3.adapters.arc_agi import normalize_frame_data`. On the frozen `2e78c25` production
  source this exposes `src/arc3/adapters/arc_agi.py: forbidden-dynamic-import`; the prior full-policy
  receipt omitted that executed base module and therefore cannot authorize Stage 09, Stage 11, or
  a package integrity PASS.
- Why it matters: preserving a source freeze cannot preserve authority from an incomplete scanner.
  Stage 09 has not begun, so the honest repair is a before-results generic policy refactor and an
  explicit predeclaration amendment, not reliance on the incomplete historical receipt.
- Current evidence: the ten-game holdout is still sealed, Stage 09 attempt/work/exposure paths are
  absent, and no development result exists under either source. An isolated repair is extracting
  frame normalization into a pure module while retaining adapter compatibility; behavioral and
  static-closure regressions are required before a new policy commit is frozen.
- Resolution condition: commit the generic refactor; prove wrapper normalization behavior remains
  equivalent; generate a fresh complete full-policy integrity receipt; preserve the original Stage
  09 predeclaration and add a hash-bound amendment naming the new exact commit/tree/source hash;
  repin Stage 09 and Stage 10/11 authority before any decisive gameplay; and independently verify
  that the amended source has no forbidden production reachability finding.

### B-001-0056 — Generic source repair is committed; authority repinning remains open

- Status update: NARROWED, not resolved.
- Last updated: 2026-08-23T04:45:18.5941520Z
- Current evidence: commit `d6d4bac1e33c9837856c08abcee61bcb14afd34e` moves pure frame
  normalization out of the live environment adapter while retaining its public import, and the
  complete package-only closure now reaches 86 scanned/hashed production files with zero local
  findings. Adapter compatibility, release/integrity/package tests, strict typing, and Ruff pass.
- Remaining burden: generate and independently validate the fresh canonical receipt at the exact
  clean commit; add the before-results Stage 09 amendment without changing the frozen matrix,
  seeds, budgets, pass rule, or holdout gate; then repin Stage 09/10/11 authority before gameplay.
- Resolution receipt: pending amended freeze and fresh exact-source authority artifacts.

### B-001-0054 — Cross-platform failure evidence narrowed the remaining package repair

- Status update: NARROWED, not resolved.
- Last updated: 2026-08-23T05:11:04.1107215Z
- Current evidence: package-only workflow run `32618693323` completed on both systems and uploaded
  failure artifacts. It evaluated GitHub's pull-request merge commit
  `396f53bd545276faaeb3f1b872ad45b6a1336e4a`, rather than literal branch head `44d9f83`.
  Ubuntu preserved receipt file
  `sha256:681eac22b411ebd3bd80593d52e4f8508c2e6101b5f4c452296016a7dd5e29e6`
  after 754 tests passed and 10 failed; Windows preserved receipt file
  `sha256:63b635cdb9ac3f60e1569f8a5f2de355806f1e7e2f82c80e4b794c8bc7c5fd69`
  after 756 passed and 8 failed. Both static checks rejected the generated archive because it was
  outside the checkout. The remaining guarded failures attempted a correctly denied public
  manifest read or child process; two Ubuntu-only runtime-profile failures depended on correctly
  denied external OS telemetry. The local repair gives explicit external archives portable labels,
  retains all archive safety checks, excludes the four boundary-requiring files only from the
  Python-audited subset, and binds pull-request package runs to the literal head SHA.
- Remaining burden: commit the repair, execute the literal exact-head workflow on Linux and
  Windows, validate both uploaded receipts and ordinary-CI coverage, and preserve any contradiction.
- Resolution receipt: pending exact-head cross-platform run.

### B-001-0054 — Literal-head CI exposed transitive selection and nested-payload gaps

- Status update: REOPENED and NARROWED, not resolved.
- Last updated: 2026-08-23T05:48:14.9077086Z
- Current evidence: exact-head package workflow run `32620135768` evaluated literal commit
  `a959bdfdcf0d9af08f713d450b5c8712956f25ba` on both hosted systems. The Ubuntu receipt is
  `sha256:e7728990385b9eb85c4f8f9941197f9ffd20d71c68c9e02a3b3dcbcbc38de09c`; its
  verifier ran 711 passing selected tests but correctly returned `FAILED_MECHANISM` after the
  Python audit guard recorded 78 disallowed attempts. The Windows receipt is
  `sha256:ad0776072f972345522bd5996c2afc2fda36dd2cd997ba4f93d8e21b36dabfff`;
  it likewise ran 711 passing tests but recorded 34 transitive child-process attempts. Ubuntu also
  preserved six strict-mypy `ctypes.windll` errors; commit
  `f4e00ccfbcc5bfccf8765cae96e3c089973df7c3` repairs and Linux-types that boundary without
  changing the predeclared gameplay policy, matrix, seeds, budgets, or gate. Independent package
  audit additionally proved that scanning the outer `arc3-kaggle-candidate.zip` did not recurse
  into its executable `arc3-first-party.zip`, allowing a synthetic hosted import in the shipped
  payload to produce zero findings.
- Remaining burden: integrate recursive bounded nested-ZIP inspection, bind the exact effective
  package-safe test set and its exclusions in the receipt, retain complete ordinary-CI coverage,
  rerun literal-head Linux and Windows package workflows, and independently validate the uploaded
  evidence. Static Python/AST evidence remains narrower than OS or native containment.
- Resolution receipt: pending the audited repair commit and clean exact-head cross-platform PASS at
  the declared `BLOCKED_EXTERNAL` private-surface boundary.

### B-001-0051 — Accounting repair is integrated; exact frozen-harness validation remains

- Status update: NARROWED, not resolved.
- Last updated: 2026-08-23T05:56:01.5753579Z
- Current evidence: integrated commit `da6ba4ca4846e16867b6b2dbf9ad7c950ffc5629` retains the
  Stage 09 v0.2 complete-terminal verifier and the earlier charged timeout/recovery repairs while
  adding Linux-portable Windows containment typing from
  `f4e00ccfbcc5bfccf8765cae96e3c089973df7c3`. The combined root suite passed 221 tests with
  three bounded host-symlink skips; Ruff check/format and strict mypy passed on both host and Linux
  targets. Independent review found no remaining Stage 09/10 launch blocker in the repaired hash
  and terminal graph.
- Remaining burden: bind the final harness commit/tree/file hashes after the package repair lands,
  run a fresh clean detached non-playing preflight with zero attempt/work/exposure paths, and
  independently validate every preflight predicate before the one authorized Stage 09 launch.
- Resolution receipt: pending exact final-harness `READY_NOT_EXECUTED` evidence.

### B-001-0052 — Authority chain is integrated; final composite preflight remains

- Status update: NARROWED, not resolved.
- Last updated: 2026-08-23T05:56:01.5753579Z
- Current evidence: commit `da6ba4ca4846e16867b6b2dbf9ad7c950ffc5629` closes the exact
  frozen-suite -> live integrity-input -> parent measurement -> child-authority top/nested ->
  launch-authorization -> child pre-import -> projected-receipt equality chain. Negative
  reseal/substitution tests are present, source-root Git commands strip inherited `GIT_*`
  redirection, and denied holdout paths consume only opaque hashes and strict zero/nonconsumption
  projections. The integrated focused result is 221 passed with three bounded host-symlink skips;
  strict typing and Ruff pass on Windows and Linux targets.
- Remaining burden: generate the fresh exact-harness package-only receipt, run Stage 09 to an
  independently verified terminal, then run the one-shot Stage 10 supervisor and mechanically
  evaluate Stage 11. No holdout gate predicate is yet earned.
- Resolution receipt: pending the exact Stage 10 terminal and Stage 11 decision receipts.

## B-001-0057 — Stage 09 Git identity initially trusted caller state and the mutable index

- Status: RESOLVED for the Stage 09 decisive harness.
- Stage: 09
- Opened: 2026-08-23
- Resolved: 2026-08-23
- Owner: Codex
- Burden: the prefreeze bootstrap, supervisor, and worker Git commands initially inherited caller
  `GIT_*` redirection, and the package-integrity candidate enumerator used `git ls-files`. A
  redirected index or index-only/skip-worktree state could therefore undermine a clean-source or
  exact-candidate claim even though the named critical files were separately hashed.
- Resolving evidence: commit `79fb54bb1f7598786fc4a6af76099f25cbf231bf` strips Git
  redirection, sets `GIT_NO_REPLACE_OBJECTS=1`, strips Git state from the worker environment, and
  enumerates exact `HEAD` tree members. The focused suite passed 96 tests with one bounded host-
  symlink skip; redirect, child-environment, and mutable-index regressions pass; Ruff and strict
  typing pass.
- Residual: Git and Python executable provenance remains bounded by the frozen runtime/environment
  receipt and local host trust; these controls are evidence-integrity checks, not an adversarial OS
  containment claim. Final exact detached preflight is still required under B-001-0051.

## B-001-0058 — Stage 10 initially allowed repository replacement-object semantics

- Status: RESOLVED for the Stage 10 decisive harness.
- Stage: 10
- Opened: 2026-08-23
- Resolved: 2026-08-23
- Owner: Codex
- Burden: Stage 10 stripped inherited Git redirection but did not disable repository-local replace
  refs, and its checkpoint worker trusted the child Git environment. A replacement could make a
  literal frozen commit resolve through different object content while preserving the commit name.
- Resolving evidence: commit `971dcc81e6642335e111c69cd8ab84511c05050e` disables replacement
  objects in parent and worker Git commands and in the child environment. The focused suite passed
  18 tests with one platform skip; Ruff and strict typing pass. Direct host audit found no active
  replace refs or hidden Build 001/Build 000 index flags, so this is a prefreeze repair rather than
  evidence of prior contamination.
- Residual: exact detached preflight and terminal source-identity equality remain required; this is
  not an adversarial Git-binary or OS containment proof.

### B-001-0058 — Same-process composite and gate helper gap is closed

- Status update: RESOLVED for every currently reachable Stage 10/11 Git helper.
- Last updated: 2026-08-23T06:21:59.2272232Z
- Current evidence: audit after `971dcc81e6642335e111c69cd8ab84511c05050e` found that
  `integrity_authority` and `holdout_gate` rebuilt environments by stripping all `GIT_*` variables,
  inadvertently removing the parent's no-replacement setting. Commit
  `c1fd1bcfeb1d5b420fd3f6975ff243cf3ea9166b` re-adds the setting inside each helper. Thirty-seven
  focused tests pass, including a real replacement-ref denial; Ruff and strict typing pass.
- Remaining boundary: exact detached preflight/terminal equality and the broader local-host trust
  boundary remain. The package verifier has its own separately tracked Git-authority repair.

## B-001-0059 — Named-file hashing did not close the complete Stage 09 harness source

- Status: RESOLVED before decisive execution.
- Stage: 09
- Opened: 2026-08-23
- Resolved: 2026-08-23
- Owner: Codex
- Burden: the earlier bootstrap named four critical files but imported additional first-party
  modules. Git cleanliness alone could miss assume-unchanged/skip-worktree changes, and accepting a
  clean-filter-normalized worktree could allow executable bytes to differ from the committed blob.
- Resolving evidence: commit `bfdf914b7ad50cc2ac39c3c3b2a0dbfc581255e0` binds every regular
  committed file under all executable first-party roots to the exact Git blob and canonical
  SHA-256, verifies exact live bytes plus ordinary index tags at every authority boundary, and
  rejects extra or symlinked source. The root suite passed 120 tests with one bounded host skip;
  Ruff and strict mypy pass.
- Residual: final H is not frozen until the independent package repair lands. The exact clean
  detached preflight, one-shot Stage 09 terminal, and local-host trust boundary remain under
  B-001-0051; this repair is not gameplay evidence or OS containment.

## B-001-0060 — Manual guard attempts and OneDrive metadata churn produced no package PASS

- Status: RESOLVED as a Stage 09 source-freeze blocker; prior failures remain evidence.
- Stage: 09, 13
- Opened: 2026-08-23
- Resolved: 2026-08-23
- Owner: Codex
- Burden: the first manual package guard attempt was invalid infrastructure because its declared
  basetemp parent did not exist. Receipt
  `C:\a\arc3-guard-out-ddf03ebe35314febb5f9bfadc7e950b6\package-only-test-guard.json`
  is `FAILED_BOUNDARY`, pytest exit 1, attempt count 0, file SHA-256
  `5b465f2ac23b7f209eedb074cc4a1eef8a3836249c5a63bdcdfdacf7279965b6`, receipt SHA-256
  `2a3bd0104e008211a09a073ceb0d1d4c2dcf2ed0e9020ffefe33649103605759`. The corrected
  manual attempt was interrupted after ordinary test failures and produced no receipt or PASS. In
  the OneDrive checkout, the full package suite twice returned `1 failed, 211 passed, 15 skipped`
  from `candidate-mutated-during-scan`; integrity-only and standalone scans passed.
- Resolving evidence: the identical source and suite in clean detached
  `C:\a\arc3-stage09-harness-c318f8f` returned `212 passed, 15 skipped`, exit 0, in 144.10
  seconds. The OneDrive result is therefore retained as `FAILED_INFRASTRUCTURE`, consistent with
  descriptor-metadata churn, and the detached exact-source checkout is the accepted execution path.
- Residual: the detached pass does not retroactively validate either manual attempt, prove which
  external actor changed metadata, establish OS containment, or replace fresh hosted Linux/Windows
  Stage 13 evidence. Those limits remain under B-001-0054 and B-001-0055.

## B-001-0061 — The first frozen H could not authorize its immutable Build 000 comparator

- Status: RESOLVED before decisive execution; failed preflight remains evidence.
- Stage: 09
- Opened: 2026-08-23
- Resolved: 2026-08-23
- Owner: Codex
- Burden: at `H=c318f8f`, the non-playing prior-authority graph failed solely because the complete
  current scanner reported three official ARC SDK adapter findings in immutable Build 000. All
  other seven prior-authority predicates passed; all four Stage 09 mutable paths were absent; no
  gameplay or holdout semantic access occurred. Launching despite that contradiction was forbidden.
- Resolving evidence: commit `10c2c7878a0a13ee6c7eb3c0c9aa36fc98fedefb` binds those three
  findings to the exact Build 000 source identity and complete typed signatures as historical
  limitations, partitions every other finding as blocking, and retains zero findings for `P`.
  Adversarial hosted-client, moved-signature, duplicate, wrong-source, and production-reuse tests
  pass. The exact detached v0.5 preflight now passes all 14 predicates with hash
  `sha256:442b9a1f7d2d751bb3d72f7e9367550fcac2fc90b866ad5bbeb3a8270db1ef5f`.
- Residual: the comparator's three static findings remain explicit limitations and do not prove
  runtime dynamic-import or native-extension containment. They cannot be generalized into a
  production exception or an offline/private-platform result.

## B-001-0062 — Rendered package plans rejected their own exact candidate commit

- Status: RESOLVED locally; hosted terminal evidence pending.
- Stage: 13
- Opened: 2026-08-23
- Resolved locally: 2026-08-23
- Owner: Codex
- Burden: exact-head hosted package-only runs at `c318f8f` and `bb8f5ea` stopped before producing a
  receipt because the static plan validator accepted only the pre-render placeholder, then rejected
  the literal candidate SHA it had just rendered. The verifier exited 2 with
  `package-only package-integrity argv shape is not the frozen static gate`; this was not a package
  PASS or a private-surface boundary result.
- Resolving evidence: commit `6f38ea19e0b253826d487b3c359cfa07503a4dcc` accepts either the
  exact placeholder or a lowercase forty-hex literal in that one position and requires the guarded
  tests and integrity scan to bind the same literal. A clean detached suite passed 16 tests plus
  Ruff and strict mypy; mismatch and extra-argument regressions remain fail-closed.
- Residual: exact-head hosted Linux and Windows runs must reach authenticated terminal receipts.
  Until then B-001-0054 remains open and no cross-platform package result is claimed.

### B-001-0056 — Repaired policy authority is exact and preflight-validated

- Status update: RESOLVED before decisive execution.
- Last updated: 2026-08-23T08:41:29.6191207Z
- Resolving evidence: `P=d6d4bac` remains exact at tree `dd8e82e` and first-party source hash
  `sha256:8f0de1a9c2c88761951ba2bcd69f2612bedfa0cc4226f44f1ed272b54b9023a8`;
  its package-only receipt and before-results amendment verify. The detached `H=10c2c78` v0.5
  preflight independently recomputed `P` as 111 policy files with zero findings, validated the
  package receipt, and passed all 14 predicates with hash
  `sha256:442b9a1f7d2d751bb3d72f7e9367550fcac2fc90b866ad5bbeb3a8270db1ef5f`.
- Residual: package-only authority still does not evaluate public identifiers or prove native/OS
  containment. Decisive Stage 09 and Stage 10 terminals remain under B-001-0051/B-001-0052.

### B-001-0051 — Exact final-harness preflight is complete

- Status update: NARROWED, not resolved.
- Last updated: 2026-08-23T08:41:29.6191207Z
- Current evidence: `H=10c2c78`, tree `18a44bfb`, is detached and clean; its complete executable
  source mapping, runtime binding, comparator and production authority, assets, predecessor,
  inherited exposures, environment cache, and opaque holdout projection passed. All four official
  Stage 09 mutable paths remained absent and exposure/gameplay counts were zero.
- Remaining burden: execute the one authorized 96-cell matrix exactly once, preserve every exposed
  cell and interruption, and authenticate the complete terminal graph before assigning PASS,
  FAILED_MECHANISM, or FAILED_INFRASTRUCTURE.

### B-001-0051 — The unique Stage 09 attempt is terminal and authenticated

- Status update: RESOLVED as an execution requirement; the failed infrastructure remains under
  B-001-0063.
- Last updated: 2026-08-23T08:52:15.5157754Z
- Resolving evidence: the sole launch produced a canonical `FAILED_INFRASTRUCTURE` aggregate after
  one exposed cell. The frozen harness reconstructed every surviving receipt, finalization,
  exposure, resource, source, runtime, and authority projection exactly; a 16-file before/after
  inventory was byte-identical. The raw aggregate is
  `sha256:5bb20928afe32e60449ae3ff6af3538e1a1b2c2722664f1f2dcfe8c1c77136a4`; the terminal
  finalization is
  `sha256:6d50afa64110a8ccb350edafcaf5172ea5d4de61442ae2ea7085b26f82e84b4f`.
- Residual: `execution_complete=false`, so the strict complete-terminal verifier correctly refuses
  authority and Stage 09 cannot PASS. This is final for Build 001 and cannot be rerun.

### B-001-0052 — Stage 09 is terminal; Stage 10 remains

- Status update: NARROWED, not resolved.
- Last updated: 2026-08-23T08:52:15.5157754Z
- Current evidence: Stage 09 ended `FAILED_INFRASTRUCTURE` with an exact reconstructed terminal,
  zero environment opens, and zero gameplay actions. Stage 10 may consume this only through its
  predeclared exact terminal-authority boundary; no complete-matrix or mechanism result may be
  inferred.
- Remaining burden: validate the final Stage 10 authority against this exact terminal, execute
  every permitted frozen synthetic/regression suite once, preserve its terminal, and mechanically
  deny any Stage 11 predicate that requires Stage 09 `PASS`.
- Resolution receipt: pending Stage 10 acceptance and Stage 11 gate receipts.

## B-001-0063 — Windows launcher PID binding prevented Stage 09 worker authorization

- Status: OPEN for future harness repair; terminal for the Build 001 Stage 09 experiment.
- Stage: 09, 13
- Opened: 2026-08-23
- Owner: Codex
- Burden: the Windows supervisor bound both process-launch and worker authorization receipts to
  PID `21056`, the virtual-environment Python launcher. The isolated interpreter executed as PID
  `23936`; its self-check therefore rejected exactly `launch_pid_matches_worker` and
  `authorization_pid_matches_worker`. It wrote
  `launch-authorization-unavailable-or-invalid`, returned 73, and opened no environment.
- Why it matters: launcher process identity and interpreter process identity are not equivalent on
  this host. Any later launcher that assumes `Popen.pid == worker os.getpid()` can fail before its
  workload. Relaxing PID equality without a descendant/containment-bound handshake would weaken
  evidence authority, so the repair requires a typed child-identity protocol and adversarial tests.
- Current evidence: `docs/evidence/001-09-development-recovery.json`; process-launch SHA-256
  `519b43013da356061be47ab15b7f396d00241a5c01114b51969389d98fb9c064`; authorization
  SHA-256 `951f14a354a700915b9f979fea4ab65b00cb9c2e0e7a12041f7a512b896d992b`; worker-abort
  SHA-256 `2856aef677139f69dc7b5b80587643c38f84a0e79c4c594d7dd1b2f24776c57d`.
- Next discriminating action: after preserving the Stage 09 checkpoint, audit Stage 10 and package
  launchers for the same assumption; implement a generic parent-verified descendant handshake or
  exact-interpreter launch where needed, with no Stage 09 rerun and no holdout access.
- Resolution condition: future launch tests reproduce the launcher/child PID split and prove that
  the actual contained interpreter, exact command/spec, source, and launch token are authorized
  without accepting an unrelated process. This cannot change Stage 09's status.

## B-001-0064 — Literal-head hosted package checks exposed two evidence-producer defects

- Status: NARROWED locally; hosted revalidation remains open.
- Stage: 09, 13
- Opened: 2026-08-23
- Last updated: 2026-08-23T09:44:26.4091652Z
- Owner: Codex
- Burden: at exact source `16f69d7d4ccbdb4dc72f298762b7025022990d20`, both Ubuntu
  package-only jobs returned `FAILED_MECHANISM` after the guard recorded one denied child process,
  while both Windows jobs returned `FAILED_INFRASTRUCTURE` because the receipt recorded zero
  collected tests despite 697 passes and two skips. The workflows then correctly refused to
  relabel either terminal as the expected missing-private-surface `BLOCKED_EXTERNAL` result.
- Why it matters: a passing test body is not a valid package receipt when a boundary guard records
  a process attempt or the evidence producer cannot prove which tests were collected.
- Current evidence: Ubuntu's causal path was `doctor._filesystem_check` through
  `platform.platform()` to CPython's `uname -p` fallback. Windows read
  `session.testscollected` before pytest finalized it. Commit
  `54322de9262096f0c71bc691773d9403e7ed3fe1` makes the doctor identity subprocess-free and
  records `len(session.items)`. Twenty-two focused tests, Ruff check/format, strict mypy, and a
  real guarded five-test doctor run pass locally with zero process attempts. All four failed hosted
  receipts and archive hashes remain preserved in `C:/a/arc3-stage13-ci-audit-32629723259`.
- Next discriminating action: require the push and draft-PR package workflows at a descendant of
  `54322de` to produce authenticated Linux and Windows terminals, and diagnose any new failure
  without weakening the guard or expected private-surface boundary.
- Resolution condition: both hosted platforms reach the exact expected authenticated package
  terminal from the same literal candidate commit; local evidence alone does not resolve this.
- Resolution receipt: pending hosted runs.
