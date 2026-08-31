# ARC3 Build 003w open-burden ledger

Do not delete resolved burdens. Append a resolution with its evidence and commit.

## B-003W-0001 — Official local development play availability is not yet verified

- **Status:** OPEN
- **Stage:** 01–03
- **Opened:** 2026-08-30
- **Burden:** The repository-local Python 3.12 environment and pinned official SDK now pass non-playing checks, but the selected official development asset has not yet been opened. The official public acquisition path may still be unavailable.
- **Why it matters:** Synthetic or mocked success cannot satisfy the owner objective.
- **Progress:** `.venv` and `.uv-cache` are checkout-local; the Wise gate, official adapter, integrity, and offline checks pass. Official exposure and environment actions remain zero.
- **Next discriminating action:** From the clean frozen commit, open only the selected development identity through the guarded official acquisition/local adapter path.
- **Resolution condition:** The official environment returns a normalized initial observation, or all safe local/public routes end at a precisely recorded `BLOCKED_EXTERNAL` boundary.
- **Resolution receipt:** none.

## B-003W-0002 — A generic Wise Scientist trajectory may not reach WIN

- **Status:** OPEN
- **Stage:** 03
- **Opened:** 2026-08-30
- **Burden:** The selected public game may require mechanics that the inherited controller does not acquire. The directive forbids a game-ID branch or copied action sequence.
- **Why it matters:** A level transition, plausible model, or `NOT_FINISHED` state is not completion.
- **Next discriminating action:** Use observation-driven, one-action-at-a-time predictions and the smallest distinguishing tests; preserve and recover from every `GAME_OVER` when reset is officially available.
- **Resolution condition:** The official environment reports `GameState.WIN`, or authorized play becomes genuinely unavailable.
- **Resolution receipt:** none.

## B-003W-0003 — One assisted public trajectory is not deployment or generalization evidence

- **Status:** ACCEPTED_LIMIT
- **Stage:** 03–04
- **Opened:** 2026-08-30
- **Burden:** The active Wise Scientist may enter explicit decisions into a local offline runner. This does not show that the packaged autonomous competition policy would reproduce the trajectory, nor that another game would be solved.
- **Why it matters:** Calling the run autonomous hidden-game generalization would overstate its evidence surface.
- **Next discriminating action:** Label the result `local-public`, preserve every action receipt, keep production free of hosted calls and game-ID logic, and make no RHAE/generalization claim.
- **Resolution condition:** Permanent claim boundary for this experiment.
- **Resolution receipt:** none.

## B-003W-0004 — Process interruption requires exact action-history replay

- **Status:** OPEN
- **Stage:** 01–03
- **Opened:** 2026-08-30
- **Burden:** The official environment object is not assumed serializable. A stopped interactive process must reconstruct state without duplicating or omitting an environment action.
- **Why it matters:** An unreplayable session would break resumability and evidence identity.
- **Next discriminating action:** Store immutable observations/actions/consequences and implement replay from the initial reset with exact frame/state verification before accepting another action.
- **Resolution condition:** Focused tests and an official-session resume prove exact prefix reconstruction, or the active uninterrupted session reaches terminal state and the limitation remains explicit.
- **Resolution receipt:** none.

## B-003W-0005 — Legacy Windows path limit broke one inherited wrapper run

- **Status:** RESOLVED
- **Stage:** 02
- **Opened:** 2026-08-30
- **Resolved:** 2026-08-30
- **Burden:** Nine inherited wrapper tests failed after the first controller decision returned a `FileNotFoundError`; the other failures cascaded from the unfinished tournament state.
- **Why it matters:** A source regression and a host filesystem boundary require different responses.
- **Discriminating action:** Re-run the identical inherited test file with a checkout-local extended-length (`\\?\\`) basetemp and no source or test changes.
- **Resolution:** The test file passed 13 tests with 2 Linux-only skips. The failure is classified `FAILED_INFRASTRUCTURE`, resolved for this gate without weakening inherited behavior.
- **Resolution receipt:** `docs/evidence/003w-03-nonplaying-verification.json`.

## B-003W-0006 — Exact terminal recovery exceeds the original physical action ceiling

- **Status:** OPEN
- **Stage:** 03
- **Opened:** 2026-08-31
- **Burden:** The preserved `GAME_OVER` checkpoint is at 991/1,000 physical environment actions. Reproducing its 532 logical environment actions in a fresh official session would reach 1,523 physical actions before mandatory RESET.
- **Why it matters:** Omitting replay actions would make the action-efficiency evidence false; silently raising a frozen budget would break the recovery contract; stopping would violate the owner-mandated continuation to observed `WIN`.
- **Progress:** Commit `5db317cf198beffaa89b7b02dc27a12594538d4a` adds a resume-only monotonic extension gate. Seventy-seven focused Wise Scientist tests, 36 secret/policy tests, Ruff, and strict mypy pass. The explicit 1,000→3,000 extension is recorded in `docs/evidence/003w-04-environment-action-budget-extension-gate.json`.
- **Next discriminating action:** Start a fresh official session with the explicit extension flags and reason; replay all 532 logical actions plus the prior logical reset, abort on any mismatch, verify exact `GAME_OVER`, and only then issue mandatory RESET.
- **Resolution condition:** The immutable `run.resumed` event records the new session, exact equivalence rule, 532 replay actions, replayed reset, 3,000-action ceiling, reason, and verified terminal observation.
- **Resolution receipt:** pending guarded recovery.
