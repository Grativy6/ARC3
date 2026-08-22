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
