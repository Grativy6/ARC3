# ARC3 Build 003w decision ledger

This ledger is append-oriented. Later evidence may supersede a decision but must not erase it.

## D-003W-0001 — Enforce the clean-room checkout as the complete project boundary

- **Status:** ADOPTED
- **Stage:** 00
- **Date:** 2026-08-30
- **Commit:** `1702c40d159bb1b3fe994aa1998a330d9bcf603c`
- **Decision:** Read and write only within the current checkout, use only the checked-out history, keep every generated environment/cache/trace under the repository root, and import no Build 003 implementation or gameplay state.
- **Evidence:** `AGENTS.md`, `README.md`, `playground/README.md`, and `docs/evidence/003w-00-clean-room-preflight.json`.
- **Consequences:** No sibling checkout, other ref, inherited gameplay trace, or out-of-root task state may be used. Public dependencies and the official environment may execute only with repository-local state.
- **Reopening condition:** None during this experiment.

## D-003W-0002 — Select one already-exposed development identity without opening the holdout manifest

- **Status:** ADOPTED
- **Stage:** 00
- **Date:** 2026-08-30
- **Commit:** `1702c40d159bb1b3fe994aa1998a330d9bcf603c`
- **Decision:** Supply `ls20-9607627b` as the experiment's runtime game argument because inherited required ledgers already record it as exposed development material. Do not parse the sealed holdout manifest to choose a game.
- **Alternatives:** Enumerate all public identities; open the partition manifest; choose a game by apparent ease.
- **Evidence:** `docs/ledger/DECISIONS.md` D-20260821-010 and `docs/ledger/OPEN_BURDENS.md` B-20260821-017.
- **Consequences:** The runner and production policy must remain game-ID-agnostic; the ID may appear only in experiment configuration, receipts, and tests. The result cannot be called unseen or hidden generalization.
- **Reopening condition:** The exact development asset is unavailable or the official SDK rejects its identity, in which case select another already-recorded non-holdout development identity and preserve this failed attempt.

## D-003W-0003 — Treat the directive as a typed action-decision contract

- **Status:** ADOPTED
- **Stage:** 01
- **Date:** 2026-08-30
- **Commit:** `fd147318019ca497a920c5726ad42a239b105290`
- **Decision:** Before every environment action, require a current observation identity, one governing objective, decision-relevant distinctions with competing predictions and relevance chains, parent-linked subgoals with lifecycle conditions, a predicted consequence, concise alternatives, and a localized post-consequence update. Stop successfully only on an observed official `GameState.WIN`.
- **Alternatives:** Reuse the inherited FULL controller unchanged; record prose after acting; treat level completion or `NOT_FINISHED` as success.
- **Evidence:** `docs/workflows/003w-wise-scientist-play-directive.md`.
- **Consequences:** The development runner may accept explicit offline decisions from the active Wise Scientist, but production code may not call a hosted model or branch on the game ID. The resulting single-game trajectory is evidence of that run only.
- **Reopening condition:** An official SDK constraint requires a narrower transport representation while preserving all directive fields and the WIN-only completion rule.

## D-003W-0004 — Freeze a guarded interactive offline runner before exposure

- **Status:** ADOPTED
- **Stage:** 01–02
- **Date:** 2026-08-30
- **Commit:** `fd147318019ca497a920c5726ad42a239b105290`
- **Decision:** Use a typed scan → act → assess gate around the official local adapter. Require a signed development authorization, an exact clean commit, checkout-local artifacts, bounded actions/resets/time, and refusal of `ARC_API_KEY`. Permit the pinned public acquisition helper only before the local offline session.
- **Alternatives:** Drive the adapter from an ad hoc shell; reuse the full inherited controller; allow uncommitted source changes during play.
- **Evidence:** `docs/evidence/003w-01-development-play-authorization.json`, `docs/evidence/003w-02-wise-scientist-implementation.json`, and `docs/evidence/003w-03-nonplaying-verification.json`.
- **Consequences:** Every environment action requires durable pre-action evidence and a post-consequence assessment. No source edit is allowed after the official session is opened unless the run is closed and the resulting evidence boundary is preserved.
- **Reopening condition:** A verified official SDK mismatch blocks the frozen adapter path.

## D-003W-0005 — Treat the inherited wrapper failure as Windows path infrastructure

- **Status:** RESOLVED
- **Stage:** 02
- **Date:** 2026-08-30
- **Commit:** `5c5c7666d9c08cd8c633231939f88495c2f6bbfc`
- **Decision:** Preserve the initial 9-failure inherited wrapper run as `FAILED_INFRASTRUCTURE`; do not alter inherited controller code or weaken tests. Use a checkout-local extended-length Windows basetemp for the resolving run.
- **Evidence:** The failed wrapper receipt reported `boundary=controller-decision` and `error_type=FileNotFoundError`; the identical test file then passed 13 tests with 2 Linux-only skips under the extended-length path. See `docs/evidence/003w-03-nonplaying-verification.json`.
- **Consequences:** The source gate is not blocked by the host path limit. The failed attempt remains part of the experiment record.
- **Reopening condition:** The same test fails under an extended-length path or a non-path-related regression appears.
