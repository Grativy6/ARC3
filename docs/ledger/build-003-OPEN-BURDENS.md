# ARC3 Build 003 open-burden ledger

Do not delete a burden when later evidence resolves it. Append a resolution with the resolving artifact and commit.

## B-003-0001 - Real OFFLINE target playability is not dynamically verified

- **Status:** OPEN
- **Stage:** 00, 10
- **Opened:** 2026-08-24
- **Owner:** shared
- **Burden:** The cached `r11l-495a7899` identity and development authority pass static checks, but Build 003 has not yet opened it through pinned OFFLINE execution.
- **Why it matters:** Static availability cannot establish that the real official environment can run now.
- **Current evidence:** `docs/evidence/003-00-source-and-base-preflight.json`.
- **Next discriminating action:** After synthetic gates and implementation freeze, revalidate the hash and open exactly this identity with `network_enabled=false` and no credentials.
- **Resolution condition:** The official OFFLINE adapter opens and returns a normalized frame, or an exact incompatibility receipt establishes `BLOCKED_EXTERNAL`.

## B-003-0002 - BLA/CLEF mechanism benefit is unmeasured

- **Status:** OPEN
- **Stage:** 02-09
- **Opened:** 2026-08-24
- **Owner:** Codex
- **Burden:** No Build 003 learner, curriculum, or paired ablation result exists yet.
- **Why it matters:** Framework alignment and passing component tests are not evidence of learning benefit.
- **Current evidence:** Source identity and pre-registration only.
- **Next discriminating action:** Implement the mechanism once, run the frozen four-variant matrix on all predeclared held-out seeds, and report paired outcomes including failures.
- **Resolution condition:** Acceptance gates support `MECHANISM_CONFIRMED_SYNTHETIC`, or the result is preserved as `PARTIAL`/`FAILED_MECHANISM`.

## B-003-0003 - No authoritative target-game completion exists

- **Status:** OPEN
- **Stage:** 10-11
- **Opened:** 2026-08-24
- **Owner:** shared
- **Burden:** No official returned `GameState.WIN` exists for the target. One historical random run completed one level but ended without WIN.
- **Why it matters:** A level transition, score, mechanic map, or synthetic pass is not the requested outcome.
- **Current evidence:** Build 000 Stage 15 trace; Build 003 preflight.
- **Next discriminating action:** Use the frozen learner at the official action boundary, preserve every failure/reset, and continue until WIN or an exact external/resource boundary.
- **Resolution condition:** A replay-linked receipt records final official state WIN, or the same exact blocking condition satisfies the persistent blocked-goal rule after independent work is exhausted.

## B-003-0004 - Target-guided development may overfit

- **Status:** OPEN
- **Stage:** 05-11
- **Opened:** 2026-08-24
- **Owner:** Codex
- **Burden:** Iterating from one public development target can accidentally create identity-, coordinate-, color-, layout-, or walkthrough-specific behavior.
- **Why it matters:** Such behavior would violate the workflow and provide no game-agnostic evidence.
- **Current evidence:** Production public-ID scan exists; no Build 003 code exists.
- **Next discriminating action:** Keep the target ID external, run static scans and remapping/metamorphic tests, and require generic causal features for every repair.
- **Resolution condition:** Final source scans and held-out synthetic compositions pass with zero target/public IDs or privileged imports.

## B-003-0005 - Official ARC3 RHAE remains unmeasured

- **Status:** BLOCKED_EXTERNAL
- **Stage:** 10-11
- **Opened:** 2026-08-24
- **Owner:** upstream/human
- **Burden:** Local OFFLINE play has no authoritative online/Kaggle scorecard, and credentials/terms/submission are not authorized.
- **Why it matters:** Local actions and completions must not be labeled official RHAE.
- **Current evidence:** Build 002 handoff; current official local-vs-online documentation.
- **Next discriminating action:** None in Build 003; report `OFFICIAL_ARC3_RHAE = NOT_MEASURED`.
- **Resolution condition:** A separately authorized official evaluator returns a scorecard bound to the frozen package.

## B-003-0006 - Frozen Windows launcher identity test fails on the current uv alias topology

- **Status:** OPEN / inherited `FAILED_INFRASTRUCTURE`
- **Stage:** 01, 10
- **Opened:** 2026-08-24
- **Owner:** host tooling
- **Burden:** `test_windows_direct_base_spawn_preserves_venv_identity_and_pid` reproducibly fails before Build 003 changes because `_runtime_identity` returns `verified=false` only for `direct_process_probe_exact`.
- **Why it matters:** The final regression result must preserve this known failure rather than attribute it to the learner or silently call the full suite clean.
- **Current evidence:** `docs/evidence/003-01-build-002-frozen-baseline.json`; the launcher probe reports the uv base Python through an unversioned lexical alias while direct execution reports its versioned resolved directory.
- **Next discriminating action:** Re-run the exact test at Stage 10 and compare the predicate-level receipt. Do not modify the frozen baseline or weaken runtime identity validation merely to obtain green output.
- **Resolution condition:** The final test passes on an authenticated stable launcher topology, or a separately scoped fix proves both launcher paths equivalent without weakening any identity predicate.

## B-003-0007 - Global composite-preservation guards regressed ordinary affine play

- **Status:** RESOLVED LOCALLY; OFFICIAL RECHECK PENDING
- **Stage:** 10
- **Opened:** 2026-08-25
- **Owner:** Codex
- **Burden:** Campaign 14 ended after 29 official actions at `NOT_FINISHED`, `levels_completed=2/6`, when a cross-mediator separation guard learned from a composite level was applied to ordinary single-color affine groups. The policy exhausted its bounded same-group action set and raised `PolicyError`.
- **Why it matters:** A repair that preserves later mechanics but removes a valid earlier route is not progress toward authoritative `WIN`.
- **Failure evidence:** `C:\a\arc3-b003-play\build003-r11l-mechanical-seed7-b1a695ec-campaign14`; official recording SHA-256 `993031c8909e386c89a0fb35a9604c32e88260ddba151b082747709de4c43245`.
- **Local resolution evidence:** The guards are now scoped by observed composite-mediator identity. Disabling only the target-box gate did not repair the first divergent action; disabling ordinary inter-mediator separation did. The repaired policy exactly matches all 29 pre-transition actions from Campaign 13 and reaches its returned level-3 `NOT_FINISHED` observation. The visual-policy suite reports 40 passed; Ruff and strict mypy pass.
- **Next discriminating action:** Run a fresh official target campaign from the committed repair and require progress beyond the failed state without losing the level-3 composite preservation behavior.
- **Resolution condition:** The fresh official campaign reaches level 3 through ordinary affine play and retains all unresolved composite groups after each accepted action.
