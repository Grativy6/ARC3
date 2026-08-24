# ARC3 Build 002 validation command ledger

Append-only command and verification record. A later passing command does not erase an earlier
failure. Times are UTC. Commands are shown in reproducible PowerShell form unless noted.

## V-002-0001 — Fetch remote identities

- Recorded: 2026-08-24T03:10:13Z.
- Command: `git fetch --all --prune`.
- Exit: `0`.
- Result: `PASS`; remote references refreshed before branch/base selection.
- Public authority consumed: no.

## V-002-0002 — Verify Build 001 ancestry

- Recorded: 2026-08-24T03:10:13Z.
- Command:
  `git merge-base --is-ancestor 8a42e43c96ac1edada21725746cdedcee24e68f9 origin/main`.
- Exit: `0`.
- Result: `PASS`; Build 001 final is ancestral to current merged `origin/main`.
- Evidence: `origin/main` is `a1931c673b90923e1af78127229667544802a096`, tree
  `7ddc02a03908e43caeda31edaf09bea9bd426cfd`, with Build 001 final as second parent.
- Public authority consumed: no.

## V-002-0003 — Verify exact implementation branch base

- Recorded: 2026-08-24T03:10:13Z.
- Commands: `git rev-parse HEAD`; `git rev-parse origin/main`; `git status --short --branch`.
- Exit: `0`.
- Result: `PASS`; `HEAD` and `origin/main` both resolved to
  `a1931c673b90923e1af78127229667544802a096` when the branch was created, and the implementation
  branch was `build/002-kaggle-competition-adapter`.
- Boundary: later uncommitted implementation edits are expected and do not alter the recorded base.
- Public authority consumed: no.

## V-002-0004 — Verify current public upstream repository identities

- Recorded: 2026-08-24T03:10:13Z.
- Commands: fetch/clone each official public repository, then run `git rev-parse HEAD` and
  `git rev-parse HEAD^{tree}` in its isolated checkout.
- Exit: `0`.
- Result: `PASS` for all five public repository identities listed in
  `docs/evidence/002-00-official-source-identities.json`.
- Public authority consumed: no.

## V-002-0005 — Read current anonymous Kaggle competition metadata

- Recorded: 2026-08-24T03:10:13.3556365Z.
- Request: `GET https://www.kaggle.com/api/i/competitions.CompetitionService/GetCompetition?competitionName=arc-prize-2026-arc-agi-3`.
- HTTP status: `200`.
- Response SHA-256:
  `de323841ab53bc7f0378a632a3176566111c8a4060009e7952b826661896e09e`.
- Result: `PASS` for metadata observation; competition id `133468`, CPU/GPU limit `540` minutes,
  required `submission.parquet`, notebook-only, internet disabled, daily limit `1`, scored limit
  `2`, synchronous rerun, gateway kernel id `110953907`.
- Boundary: anonymous metadata access did not accept terms, use credentials, upload, or submit.
- Public authority consumed: no.

## V-002-0006 — Inherited focused package/release/integrity baseline

- Recorded: 2026-08-24T03:10:13Z.
- Command: exact invocation retained in the active run terminal; append it here with its receipt
  path before final freeze.
- Exit: `0`.
- Result: `PASS:237-passed+15-skipped` on the clean Build 002 base using an isolated short pytest
  temporary root.
- Boundary: this verifies inherited focused surfaces only. It does not validate the new adapter,
  a cold package, notebook execution, Parquet output, or public gameplay.
- Public authority consumed: no.

## V-002-0007 — Bind the Build 002 public-source overlay

- Recorded: 2026-08-24T03:42:52Z.
- Commands: parse `upstream.lock.json` with Python 3.12; assert the exact Build 002 base; compute
  `Get-FileHash -Algorithm SHA256 upstream.lock.json`; run `git diff --check`.
- Exit: `0`.
- Result: `PASS`; additive overlay schema `arc3.upstream-lock.build-002.v0.1`, nine controlling
  source-file identities, lock SHA-256
  `b5474a8f36bda80bb629f204591610325045411bd5aac65f6765261b7fab6b0b`.
- Boundary: this validates available public source identity. Private Kaggle runtime/scorer parity
  remains `BLOCKED_EXTERNAL`.
- Public authority consumed: no.

## V-002-0008 — Static holdout-asset availability audit

- Recorded: 2026-08-24T03:38:01Z through 2026-08-24T03:55:35Z.
- Commands: enumerate filenames under the isolated `C:\a` cache for each exact manifest-bound
  holdout ID; issue an unauthenticated `HEAD` to Kaggle's competition archive endpoint; inspect
  public search metadata for a terms-free static-file surface.
- Exit: local enumeration `0`; archive `HEAD` returned HTTP `404`; no exact static asset was
  acquired.
- Result: `BLOCKED_EXTERNAL`; all ten IDs had zero local filename hits and no validated
  anonymous static archive was available. Do not substitute ARC API gameplay acquisition because
  that opens an environment and crosses the run boundary.
- Superseding caveat: the search metadata unexpectedly emitted third-party source-derived public
  game snippets. Exact exposure and its permanent non-pristine reporting consequence are retained
  in `docs/evidence/002-00-public-source-preview-contamination.json` and B-002-0009.
- Public authority consumed: no under the explicit mechanical boundary; environment `make`,
  resets, actions, scorecards, asset acquisitions, and source-file opens all remained zero.

## V-002-0009 — One-shot harness, partial-write, and lifecycle checks

- Recorded: 2026-08-24T03:58:28Z.
- Commands:
  - `.\.venv\Scripts\python.exe -m ruff check src/arc3/evaluation/build002_holdout.py tests/competition/test_build002_holdout.py`
  - `.\.venv\Scripts\python.exe -m mypy --strict src/arc3/evaluation/build002_holdout.py tests/competition/test_build002_holdout.py`
  - `.\.venv\Scripts\python.exe -m pytest -q tests/competition/test_build002_holdout.py tests/competition/test_competition_lifecycle.py --no-cov --basetemp C:\a\b002-holdout-tests7`
- Exit: all `0`.
- Result: `PASS`; Ruff clean, strict mypy clean, pytest `33 passed, 1 skipped`. The single skip is
  the declared POSIX-only `SIGALRM` interruption check on Windows.
- Covered boundaries: exact ten-game static inventory, frozen clean-commit preflight, canonical
  one-shot state root, marker-before-make ordering, callback-before-upstream enforcement, rerun
  rejection, zero-intent consumed failure after marker/ledger-write interruption, append-only
  hash chain, score/failure/allocation/reserve/hash result recomputation, one scorecard, exactly
  one make per environment, no in-flight scorecard read, and deterministic sequential lifecycle.
- Public authority consumed: no; tests use isolated synthetic files/framework fixtures and never
  call an ARC holdout environment.

## Pending mandatory entries

Append exact commands and receipts for:

- Build 002 focused and full test suites;
- Ruff lint and format checks;
- strict mypy;
- deterministic replay/property checks;
- competition lifecycle/integrity and static game-ID scans;
- package A/B identity and complete payload/license manifests;
- true isolated offline cold installation and startup;
- notebook build, size, offline execution, and deterministic regeneration;
- `submission.parquet` structural and content validation;
- secret scan and no-network audit;
- frozen one-shot preflight receipt;
- the single public-run launch/result seal, if earned;
- clean-clone final verification, Git integrity, push, and draft-PR identity.
