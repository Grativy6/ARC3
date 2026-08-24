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
