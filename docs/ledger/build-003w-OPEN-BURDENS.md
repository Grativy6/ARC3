# ARC3 Build 003w open-burden ledger

Do not delete resolved burdens. Append a resolution with its evidence and commit.

## B-003W-0001 — Official local development play availability is not yet verified

- **Status:** RESOLVED
- **Stage:** 01–03
- **Opened:** 2026-08-30
- **Burden:** The repository-local Python 3.12 environment and pinned official SDK now pass non-playing checks, but the selected official development asset has not yet been opened. The official public acquisition path may still be unavailable.
- **Why it matters:** Synthetic or mocked success cannot satisfy the owner objective.
- **Progress:** `.venv` and `.uv-cache` are checkout-local; the Wise gate, official adapter, integrity, and offline checks pass. The selected development identity opened through the guarded local adapter and the official environment remained available through terminal play.
- **Resolution:** The official environment returned a normalized initial observation and ultimately `GameState.WIN` with `levels_completed=7` and `win_levels=7`.
- **Resolution condition:** The official environment returns a normalized initial observation, or all safe local/public routes end at a precisely recorded `BLOCKED_EXTERNAL` boundary.
- **Resolution receipt:** `docs/evidence/003w-05-official-development-win.json`.

## B-003W-0002 — A generic Wise Scientist trajectory may not reach WIN

- **Status:** RESOLVED_FOR_SELECTED_TRAJECTORY
- **Stage:** 03
- **Opened:** 2026-08-30
- **Burden:** The selected public game may require mechanics that the inherited controller does not acquire. The directive forbids a game-ID branch or copied action sequence.
- **Why it matters:** A level transition, plausible model, or `NOT_FINISHED` state is not completion.
- **Resolution:** The run preserved three `GAME_OVER` events, localized the implicated hypotheses, recovered through official resets and exact replay, and then directly observed `WIN` at 7/7. This resolution applies only to the selected assisted trajectory; B-003W-0003 remains the permanent generalization boundary.
- **Resolution condition:** The official environment reports `GameState.WIN`, or authorized play becomes genuinely unavailable.
- **Resolution receipt:** `docs/evidence/003w-05-official-development-win.json`.

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

- **Status:** RESOLVED
- **Stage:** 01–03
- **Opened:** 2026-08-30
- **Burden:** The official environment object is not assumed serializable. A stopped interactive process must reconstruct state without duplicating or omitting an environment action.
- **Why it matters:** An unreplayable session would break resumability and evidence identity.
- **Resolution:** Three official-session recoveries replayed exact normalized observations, counted every replay action/reset physically, recorded `logical_actions_duplicated=false`, and continued to the terminal WIN. The recovery ledger and journal hash chains verify the boundary.
- **Resolution condition:** Focused tests and an official-session resume prove exact prefix reconstruction, or the active uninterrupted session reaches terminal state and the limitation remains explicit.
- **Resolution receipt:** `docs/evidence/003w-05-official-development-win.json` and `docs/evidence/003w-06-final-verification.json`.

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

- **Status:** RESOLVED
- **Stage:** 03
- **Opened:** 2026-08-31
- **Burden:** The preserved `GAME_OVER` checkpoint is at 991/1,000 physical environment actions. Reproducing its 532 logical environment actions in a fresh official session would reach 1,523 physical actions before mandatory RESET.
- **Why it matters:** Omitting replay actions would make the action-efficiency evidence false; silently raising a frozen budget would break the recovery contract; stopping would violate the owner-mandated continuation to observed `WIN`.
- **Progress:** Commit `5db317cf198beffaa89b7b02dc27a12594538d4a` adds a resume-only monotonic extension gate. Seventy-seven focused Wise Scientist tests, 36 secret/policy tests, Ruff, and strict mypy pass. The explicit 1,000→3,000 extension is recorded in `docs/evidence/003w-04-environment-action-budget-extension-gate.json`.
- **Resolution:** The fresh official session replayed all 532 required logical actions plus the prior reset with exact semantic equality, recorded the 1,000→3,000 extension in `run.resumed`, reproduced the terminal checkpoint, and continued without exceeding the new ceiling. The full run ended at 2,315 physical environment actions and official `WIN`.
- **Resolution condition:** The immutable `run.resumed` event records the new session, exact equivalence rule, 532 replay actions, replayed reset, 3,000-action ceiling, reason, and verified terminal observation.
- **Resolution receipt:** `docs/evidence/003w-04-environment-action-budget-extension-gate.json`, `docs/evidence/003w-05-official-development-win.json`, and `docs/evidence/003w-06-final-verification.json`.

## B-003W-0007 — Raw official-play artifacts are local rather than Git-tracked

- **Status:** ACCEPTED_LIMIT
- **Stage:** 04
- **Opened:** 2026-08-31
- **Burden:** The complete multi-thousand-file observation/journal artifact tree is intentionally ignored and is not force-added to the branch.
- **Why it matters:** A remote reviewer cannot reconstruct every frame using only the Git branch.
- **Mitigation:** The retained checkout-local artifact tree includes the immutable journal, recovery ledger, all normalized observations and frames, checkpoint, and terminal receipts. Tracked evidence records exact repository-relative paths, byte sizes, SHA-256 values, terminal hashes, and the verification result.
- **Reopening condition:** A later owner-authorized publication workflow chooses a bounded archival format and destination without exposing secrets, holdout data, or prohibited material.
- **Resolution receipt:** Permanent scope limit recorded in `docs/evidence/003w-06-final-verification.json` and `docs/handoffs/003w-wise-scientist.md`.

## B-003W-0008 — The broad historical suite did not complete on the deep Windows checkout

- **Status:** ACCEPTED_LIMIT
- **Stage:** 04
- **Opened:** 2026-08-31
- **Burden:** A bounded full-repository run stopped at its sixth failure after 202 passes and 3 skips. Four failures involved Git/path projection under an extended-length basetemp; two involved atomic replace/path resolution under the deep OneDrive checkout.
- **Why it matters:** Passing focused gates cannot honestly be reported as completion of every inherited historical test.
- **Discriminating action:** Rerun every implicated test using the shortest compatible paths still inside the clean-room repository and without changing source or tests.
- **Result:** The complete 28-test package-candidate file passed on a normal short basetemp, the controller end-to-end case passed on a normal short basetemp, and the paired ablation case passed from repository-root `f`. The six source implications are resolved as host path infrastructure; the end-to-end broad-suite completion claim remains unearned.
- **Reopening condition:** Complete the entire inherited suite from a supported short checkout path on the delivered source.
- **Resolution receipt:** `docs/evidence/003w-06-final-verification.json`.
