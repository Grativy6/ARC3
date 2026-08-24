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
