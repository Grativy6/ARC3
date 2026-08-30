# ARC3 Build 003w decision ledger

This ledger is append-oriented. Later evidence may supersede a decision but must not erase it.

## D-003W-0001 — Enforce the clean-room checkout as the complete project boundary

- **Status:** ADOPTED
- **Stage:** 00
- **Date:** 2026-08-30
- **Commit:** pending
- **Decision:** Read and write only within the current checkout, use only the checked-out history, keep every generated environment/cache/trace under the repository root, and import no Build 003 implementation or gameplay state.
- **Evidence:** `AGENTS.md`, `README.md`, `playground/README.md`, and `docs/evidence/003w-00-clean-room-preflight.json`.
- **Consequences:** No sibling checkout, other ref, inherited gameplay trace, or out-of-root task state may be used. Public dependencies and the official environment may execute only with repository-local state.
- **Reopening condition:** None during this experiment.

## D-003W-0002 — Select one already-exposed development identity without opening the holdout manifest

- **Status:** ADOPTED
- **Stage:** 00
- **Date:** 2026-08-30
- **Commit:** pending
- **Decision:** Supply `ls20-9607627b` as the experiment's runtime game argument because inherited required ledgers already record it as exposed development material. Do not parse the sealed holdout manifest to choose a game.
- **Alternatives:** Enumerate all public identities; open the partition manifest; choose a game by apparent ease.
- **Evidence:** `docs/ledger/DECISIONS.md` D-20260821-010 and `docs/ledger/OPEN_BURDENS.md` B-20260821-017.
- **Consequences:** The runner and production policy must remain game-ID-agnostic; the ID may appear only in experiment configuration, receipts, and tests. The result cannot be called unseen or hidden generalization.
- **Reopening condition:** The exact development asset is unavailable or the official SDK rejects its identity, in which case select another already-recorded non-holdout development identity and preserve this failed attempt.

## D-003W-0003 — Treat the directive as a typed action-decision contract

- **Status:** ADOPTED
- **Stage:** 01
- **Date:** 2026-08-30
- **Commit:** pending
- **Decision:** Before every environment action, require a current observation identity, one governing objective, decision-relevant distinctions with competing predictions and relevance chains, parent-linked subgoals with lifecycle conditions, a predicted consequence, concise alternatives, and a localized post-consequence update. Stop successfully only on an observed official `GameState.WIN`.
- **Alternatives:** Reuse the inherited FULL controller unchanged; record prose after acting; treat level completion or `NOT_FINISHED` as success.
- **Evidence:** `docs/workflows/003w-wise-scientist-play-directive.md`.
- **Consequences:** The development runner may accept explicit offline decisions from the active Wise Scientist, but production code may not call a hosted model or branch on the game ID. The resulting single-game trajectory is evidence of that run only.
- **Reopening condition:** An official SDK constraint requires a narrower transport representation while preserving all directive fields and the WIN-only completion rule.
