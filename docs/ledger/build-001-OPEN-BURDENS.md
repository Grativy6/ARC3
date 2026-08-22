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

## B-001-0002 — Palette and action equivariance failures

- Status: OPEN
- Carried from: Build 000 burden B-20260821-040
- Burden: two palette permutations and two action remaps changed a base score of 1.0 to 0.0.
- Next evidence: Stages 04–05 paired metamorphic tests.

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

- Status: OPEN
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
- Resolution receipt: none.

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
