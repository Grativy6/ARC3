# ARC3 Build 003 decision ledger

This ledger is append-oriented. Supersede decisions with new entries; do not erase prior authority or failure evidence.

## D-003-0001 - Select `r11l-495a7899` as the external development target

- **Status:** ADOPTED
- **Stage:** 00
- **Date:** 2026-08-24
- **Commit:** pending
- **Decision:** Predeclare the exact cached `r11l-495a7899` development identity for real offline play. Keep the ID only in evaluation configuration and evidence, never in production policy logic.
- **Alternatives:** `ls20-9607627b`; an arbitrary development game; the sealed public holdout.
- **Evidence:** The frozen partition classifies `r11l` as development; its asset matches `sha256:483e583c88e91c2ae58ad1fa7b274d97813993796ce798551a563e1a9a78a7ff`; it is the only prior development identity with a completed level; it has six declared levels.
- **Why:** This is the strongest repository-grounded progress signal while preserving the project holdout boundary. It is a target selection, not a game-specific rule.
- **Consequences:** Final real-play evidence is labeled `local-public-source-preview-exposed`; static scans must prove the ID is absent from production policy.
- **Reopening condition:** Static asset identity or OFFLINE compatibility fails before play, or the owner specifies a different authorized target.

## D-003-0002 - Implement only bounded BLA and CLEF mechanisms

- **Status:** ADOPTED
- **Stage:** 00
- **Date:** 2026-08-24
- **Commit:** pending
- **Decision:** Map BLA v0.9.1 to structured residuals, provisional/versioned mechanic ledgers, earned support, local-first repair, and saturation. Map CLEF v1.0 to explicit layer declarations, independent evidence families, validity gates, residual promotion, readability walls, and scale-relevance stopping.
- **Alternatives:** Terminology-only comments; physical/thermodynamic game laws; CORAL scoring; wholesale replacement of existing hypotheses/world models.
- **Evidence:** Zenodo records 20807530 and 21193511 and their sole PDF artifacts; attached Build 003 workflow.
- **Why:** These are the operationally justified source mechanisms that can be tested at the existing observation/action boundary.
- **Consequences:** No physical surface-tension, curvature, free-energy, thermodynamic, or material-cost analogy becomes a game rule. PAL v2.2 terminology controls conflicts; CORAL remains proposed and non-operational.
- **Reopening condition:** Measured integration evidence shows a narrower mechanism is necessary while preserving the claim and trace boundaries.

## D-003-0003 - Treat official `WIN` as the sole completion authority

- **Status:** ADOPTED
- **Stage:** 00
- **Date:** 2026-08-24
- **Commit:** pending
- **Decision:** Continue while the official state is `NOT_FINISHED`. Treat `GAME_OVER` as failure evidence, preserve the trace, issue only `RESET` when permitted, revise implicated hypotheses, and continue within declared budgets. Stop as complete only on an actually returned `GameState.WIN`.
- **Alternatives:** Stop after a level transition, score increase, synthetic success, confidence threshold, or complete-looking mechanic map.
- **Evidence:** Current official actions/full-play documentation and the owner instruction.
- **Why:** Environment state is the authoritative external completion boundary.
- **Consequences:** Receipts report total submissions, non-reset scored actions, and resets separately because upstream counters differ.
- **Reopening condition:** Only a later official interface revision verified from primary sources.

## D-003-0004 - Reuse Build 002 lifecycle and governor boundaries

- **Status:** ADOPTED
- **Stage:** 01
- **Date:** 2026-08-24
- **Commit:** pending
- **Decision:** Extend existing perception, world-model, exploration, trace, memory, governor, adapter, and packaging surfaces. Do not create a second budget authority or rewrite the competition lifecycle.
- **Alternatives:** Parallel new controller stack; game-specific solver; per-action durable checkpointing; allocator tracing in competition mode.
- **Evidence:** Build 002 freeze and architecture audit.
- **Why:** Existing contracts already provide deterministic receipts, legal-action checks, replay, bounded modes, and packaging; Build 003 gaps are mechanic learning and cross-level reuse.
- **Consequences:** New source should live in already packaged top-level modules unless the package allowlist is explicitly extended and tested.
- **Reopening condition:** A measured integration need cannot be expressed safely through existing contracts.
