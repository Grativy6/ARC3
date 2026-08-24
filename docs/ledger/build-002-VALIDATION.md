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

The entries below supersede this pending checklist where they provide terminal evidence. Missing
exact argv or hashes are explicitly left unsealed rather than reconstructed.

## V-002-0010 — Correct and freeze controlling public source identities

- Recorded: 2026-08-24T08:37:44Z.
- Result: `PASS` for available public-source identity; exact private Kaggle parity remains
  `BLOCKED_EXTERNAL`.
- Current lock: `upstream.lock.json`, SHA-256
  `fb3acb1e375dddaaa02e38dc39cd3a0cde7fe95045d4dca34d976d29e0f56c68`.
- Current source receipt: `docs/evidence/002-00-official-source-identities.json`, SHA-256
  `7231d2c84c3c589ddf24ede5b3064d1c789c2c2e5d9cdb27a609914061f9827f`.
- Repository pins:
  - `arcprize/ARC-AGI` `f12822c4d550121c35a275008d964afbbed47d2f`;
  - `arcprize/ARCEngine` `b495c6acaf253c9681cd7b75c4299d352e9ce6f8`;
  - `arcprize/ARC-AGI-3-Agents` `4743e7d0aaae0ded0d98a89a7e282e63564cd58b`;
  - `arcprize/ARC-AGI-3-Kaggle-Starter`
    `eeb1535404f321d280a8f9194bbc1d7aca5f05fc`;
  - `arcprize/docs` `a5dfc0b64c625fb4a19cf074af845ebe0bb88ff8`.
- Fresh anonymous Kaggle metadata: raw response size `3,080` bytes, SHA-256
  `ca6253ca8e87ba6e4e5a435ee5f83bc27aaf62aa564860c1e31390349978de4f`,
  captured `2026-08-24T04:28:41.5202644Z`.
- Preserved superseded discrepancy: the first source receipt recorded
  `de323841ab53bc7f0378a632a3176566111c8a4060009e7952b826661896e09e`, while
  the earlier lock recorded
  `de323841e87991d99d3a33fe49b639c53c34037940ef18a3ed5108e8df286c57`
  for the same alleged response without a representation distinction. Neither controls.
- Preserved line-ending correction: the raw Git-blob SHA-256 values for pinned Agents
  `agents/agent.py` and `agents/swarm.py` are respectively
  `49f1a349cd5e2123fceb266aec4a3a758d18ef5520e0212e808f695905d9e073` and
  `d9dc48f710f1b90a6552db0921293c7e89c8a925ed00a3faefa07ae19998ad39`;
  superseded Windows-checkout hashes
  `500a9b9055aa5023a84b2b19bc9a41cb53dff03b3224b8d1ceb00e738709256f` and
  `c1d35066acfccb0b982bc33bb07a732d70da4d938c80ce3cdafd67b1018212cc`
  remain provenance only.
- Public authority consumed: no.

## V-002-0011 — Clean-clone repository verification

- Recorded: 2026-08-24T08:37:44Z.
- Frozen clean-clone commit:
  `9d395d51fd3ae9ca35df90a2ddbccbd0338dade4`.
- Commands:
  - full `pytest` with the repository defaults and a short Windows `--basetemp`;
  - `uv run ruff check .`;
  - `uv run ruff format --check .`;
  - `uv run mypy src agent scripts`.
- Exit: all final invocations `0`.
- Result:
  - local clean clone: `1464 passed, 21 skipped`, `79%` coverage, `2497.97s`;
  - Ruff lint: `PASS`;
  - Ruff format: `330 files already formatted`;
  - mypy: `PASS`, `188` source files.
- Cross-platform CI at the same source:
  - Ubuntu: `1475 passed, 10 skipped`, `79%`, run
    `https://github.com/Grativy6/ARC3/actions/runs/32702015777`;
  - Windows: `1465 passed, 20 skipped`, `79%`, same run.
- Current `0385d238ab85477ce6f995f7182855a7b3473f5d` clean selector:
  `2 passed`; this verifies the final package-only boundary repair locally.
- Final exact-branch CI runs were still pending when this entry was drafted:
  `32706100172`, `32706100187`, `32706714376`, and `32706714371`.
  Their terminal conclusions are appended rather than replacing this observation.
- Public authority consumed: no.

## V-002-0012 — Preserve Windows long-path pytest failure

- Recorded: 2026-08-24T08:37:44Z.
- Result: `FAILED_INFRASTRUCTURE`, later resolved.
- Observation: an initial full-suite Windows run used a long AppData pytest temporary root. Deep
  terminal-artifact fixtures exceeded the effective Windows path-length boundary and failed before
  testing their intended semantics.
- Repair: rerun with a short root such as `C:\q8f`; the isolated terminal test and subsequent clean
  full suite passed.
- Receipt boundary: the exact initial argv, failure count, and output hash were not sealed. Do not
  invent them.
- Public authority consumed: no.

## V-002-0013 — Preserve parallel package-build race

- Recorded: 2026-08-24T08:37:44Z.
- Result: `FAILED_INFRASTRUCTURE`, later resolved.
- Observation: two package builds launched in parallel against one shared `.venv`; one completed
  while the other failed with Windows `Access Denied`.
- Diagnosis: shared mutable environment setup was not an isolated A/B build surface.
- Repair: rerun the package builds sequentially. The preserved `44af464` A/B outputs were
  byte-identical:
  - candidate:
    `a45dde0e4490563cb021a91af990d9c049896d75b09cf3143b320857b1efd30b`;
  - notebook:
    `bd65dca6e2de601f5d17a3ce4d3535486ab9c063905d838fb959a30e0529bbb5`;
  - payload:
    `726e595523a9b737a3b000b6d4d088a8e9289c1e6fd1da03297b79876311356f`;
  - Parquet:
    `f601196d5298e525e04c22185acb3668c3a9f74c6f371040164169fcc17279c9`.
- Receipt boundary: no exact parallel-failure argv, path, or failure hash was sealed.
- Public authority consumed: no.

## V-002-0014 — Preserve OneDrive candidate-stability false failure

- Recorded: 2026-08-24T08:37:44Z.
- Result: `FAILED_INFRASTRUCTURE`, later bounded.
- Observation: a package-only integrity pass against the OneDrive-backed checkout reported
  `candidate-mutated-during-scan`. Content hashes remained stable, while OneDrive changed file
  `ctime` metadata during scanning.
- Repair: rerun from a clean non-OneDrive clone. Package-only static, source, supply-chain, archive,
  and secret checks passed with zero findings.
- Boundary: this was filesystem-metadata churn, not evidence that altered bytes were accepted.
- Receipt boundary: the failed OneDrive invocation and receipt hash were not sealed.
- Public authority consumed: no.

## V-002-0015 — Preserve profiler guard failures

- Recorded: 2026-08-24T08:37:44Z.
- First failure: `FAILED_INFRASTRUCTURE`; an exploratory `2s` worker timeout was too small for the
  full frozen profile. The terminal observation was retained, but no exact argv or receipt hash
  was sealed.
- Second failure: `FAILED_INFRASTRUCTURE`; the profiler was given expected commit
  `9d395d57d08ffc0106760597061d746dc384c59a` while the clean checkout was actually
  `9d395d51fd3ae9ca35df90a2ddbccbd0338dade4`.
- Exact failure:
  - error: `Stage 16 profiles require the named clean frozen commit`;
  - schema: `arc3.stage16.profile.v0.1`;
  - producer receipt SHA-256:
    `570bbcb3472999c5f8f8e2e50d079cdf89e8a01461a18e607c583a9ece85e2ff`;
  - preserved path:
    `artifacts/build002/failed-attempts/profile-incorrect-frozen-sha.json`.
- Repair: use the exact clean commit and coherent `1800s` outer worker timeout.
- Public authority consumed: no.

## V-002-0016 — Final frozen competition profile

- Recorded: 2026-08-24T08:37:44Z.
- Source:
  - commit `0385d238ab85477ce6f995f7182855a7b3473f5d`;
  - tree `5b9a5610df4add0f0417f4f73161ff082af7b502`;
  - clean identity verified before worker launch, at worker start, and at worker end.
- Receipt: `artifacts/build002/profile-0385d238/profile.json`.
- Status: `PASS`; evidence label `synthetic`; claim `NO_GENERALIZATION_CLAIM`.
- File SHA-256:
  `31fa5931681dd692865097ea30c9cf019cec8cff8ca2659e733d874639266c38`.
- Producer receipt SHA-256:
  `cfea7341ecd3617978451e0d6e8384d4f9d2cf4566fc72f6fdc55f3aaacad6bd`.
- Runtime configuration SHA-256:
  `3b56018560e4bde4005da4c7f30bc97a4180179d4a8ce1c0959cc0c76651694a`.
- Measured competition profile:
  - `80/80` actions;
  - total wall time `41.6403431s`;
  - peak RSS `321,601,536` bytes;
  - maximum production controller cycle `3.5639200000077835s` under the `10s` bound;
  - mean total step `0.4258290975001728s`;
  - trace `18,397,528` bytes;
  - checkpoint directory `18,598,709` bytes;
  - `12` robustness cases and `11` fault cases, all required predicates passing;
  - Stage 13 regression comparison `PASS`.
- Competition policy observed: allocator tracing off, automatic per-action checkpoints off,
  compact trace capacity `512`, sparse checkpoint interval `16`.
- Superseded-but-preserved profile: commit `44af4647b7d7b8f28236261bc01051dd78a5c640`
  also passed; file SHA-256
  `90f7909c30204d235c580d9780ff2b4e24a99763e061014ad4db927a89551729`.
- Public authority consumed: no.

## V-002-0017 — Final local package, notebook, and Parquet validation

- Recorded: 2026-08-24T08:37:44Z.
- Source: commit `0385d238ab85477ce6f995f7182855a7b3473f5d`.
- Output: `artifacts/build002/final-0385d238`.
- Status: `PACKAGING_PASS`; evidence label `synthetic`; no upload or official submission.
- Producer build-receipt SHA-256:
  `661d550c6bc0827b44b860eeadbb42bcca8611be5254c15d26461230b8f368a9`.
- Identities:
  - candidate:
    `7b34c6c88f5ee88db823cd7d98409ddd06d0f9e4ebe8f5259bc7afe0104fd7f1`,
    `838,437` bytes;
  - notebook:
    `d3d7e51774c2c2e0f613f0a47b20359190af8d0f31a6b4ff5a0963fe9048e4f0`,
    `548,193` bytes;
  - first-party payload:
    `726e595523a9b737a3b000b6d4d088a8e9289c1e6fd1da03297b79876311356f`,
    `400,650` bytes and `104` exact Git-bound members;
  - package manifest:
    `c17e2e3c3aed1fbc9b0917b17fcf242d72777d59e0405d82d8b47d84fd5cbcf6`;
  - `submission.parquet`:
    `f601196d5298e525e04c22185acb3668c3a9f74c6f371040164169fcc17279c9`,
    `856` bytes, one local fixture row, columns `row_id`, `game_id`, `end_of_game`, `score`.
- Package-only integrity: `PASS` with producer receipt
  `d0d32f777cadc5a5116d12d9096f97e638af7f99857b8f0632f0bca6c177c5b5`.
- Deliberate boundary:
  `full_competition_integrity_status=NOT_EVALUATED_PUBLIC_IDENTIFIERS`; package-only validation did
  not semantically access the protected public manifest.
- The one-row Parquet file proves pinned-public structural handling only. It is not a public score,
  upload-acceptance receipt, official RHAE, or substitute for a complete competition output.
- Public authority consumed: no.

## V-002-0018 — Native Linux offline cold-start rehearsal

- Recorded: 2026-08-24T08:37:44Z.
- CI run:
  `https://github.com/Grativy6/ARC3/actions/runs/32706714450`;
  job `97369252329`.
- Source: commit `0385d238ab85477ce6f995f7182855a7b3473f5d`.
- Status: `PASS`; schema `arc3.build-002-cold-start-command.v0.2`.
- Receipt file SHA-256:
  `e97df685246b87936813eed74cf442b3c516192dad4a4d9fd83e6bfb116b519a`.
- Target: CPython `3.12.14`, Linux x86-64, glibc `2.39`, `manylinux_2_28`.
- Acquisition: `31` exact wheels, `45,073,152` bytes, hash-required/no-index installation.
- Measurements: `12.627258882s` wall time; peak memory `132,145,152` bytes.
- Exact generated notebook cells executed: `4`; production requirement set matched; two startup
  projections were deterministic.
- Notebook output matched the local Parquet SHA-256
  `f601196d5298e525e04c22185acb3668c3a9f74c6f371040164169fcc17279c9`.
- Network observation: zero non-loopback Python socket attempts under the loopback-only guard.
- Limitation: the framework and gateway were deterministic safe loopback fixtures. There was no
  exact Kaggle gateway, private evaluator, or OS network namespace attestation.
- An earlier Build 002 package workflow for the same commit also passed:
  `https://github.com/Grativy6/ARC3/actions/runs/32706100218`.
- Public authority consumed: no.

## V-002-0019 — Frozen production preflight stops before consumption

- Recorded: 2026-08-24T08:37:44Z.
- Source:
  - commit `0385d238ab85477ce6f995f7182855a7b3473f5d`;
  - tree `5b9a5610df4add0f0417f4f73161ff082af7b502`;
  - runtime configuration SHA-256
    `3b56018560e4bde4005da4c7f30bc97a4180179d4a8ce1c0959cc0c76651694a`.
- Result: `BLOCKED_EXTERNAL`.
- Producer receipt SHA-256:
  `aa9906ca2612f9b9130ed19ac6dbe9b2138139613206bcd0f1891e13b6b77301`.
- Request SHA-256:
  `4a0e541b19f8d26affbb895a23a1139e2b971bfc61bddda2bc4a8127c3a02783`.
- Error: `FileNotFoundError`; message SHA-256
  `ba7ce61033f638929402dad230d898e52fb6ddbdf1471b4951fe49c525e8bd86`.
- Exact missing boundary: independently pinned ten-game static assets and exact external
  framework/gateway/platform attestations were unavailable.
- Measured counters:
  - scorecard-open intents/interactions `0/0`;
  - environment-make intents/interactions `0/0`;
  - actions `0`;
  - resets `0`.
- Authority: authorized runs consumed `0/1`; no canonical one-shot state or consumption marker was
  created.
- Public metrics, including total RHAE, completed games/levels, per-game/per-level scores,
  actions-versus-human baselines, gameplay wall time, gameplay peak memory, budget allocation,
  remaining reserve, and failure distribution are `NOT_MEASURED`.
- Build 001 remains `PARTIAL` and historically `SEALED_UNCONSUMED`.
- Public authority consumed: no.

## V-002-0020 — Preserve Build 001 protected-manifest CI regression

- Recorded: 2026-08-24T08:37:44Z.
- Failed source: `9d395d51fd3ae9ca35df90a2ddbccbd0338dade4`.
- Failed workflow:
  `https://github.com/Grativy6/ARC3/actions/runs/32702015799`.
- Result: Ubuntu and Windows `FAILED_MECHANISM`.
- Cause: Build 001's package-only subprocess verifier collected
  `tests/competition/test_run_build002_holdout.py`. That Build 002 production-preflight test
  intentionally copies the protected public partition manifest into an isolated fixture, which is
  outside Build 001's package-only no-public-semantics boundary. The verifier correctly refused to
  call the result `BLOCKED_EXTERNAL`.
- Windows terminal evidence reported a release-verification receipt with
  `status=FAILED_MECHANISM`; its uploaded artifact digest was
  `e64ca0c71fd4ee2e0ce598d07a2b67becfdd4063294c0c18dec8c373f7fceced`.
- Repair: commit `0385d238ab85477ce6f995f7182855a7b3473f5d` explicitly excludes that exact
  Build 002 production-preflight test from the Build 001 package-only pytest boundary, with the
  reason preserved in `scripts/package_only_pytest.py`.
- Boundary: the repair does not weaken the protected-manifest scanner, authorize Build 001
  manifest access, or revise Build 001 evidence.
- Current focused verification: `2 passed`; final hosted package-only confirmation is appended
  after terminal completion.
- Public authority consumed: no.

## V-002-0021 — Branch, push, and draft pull request identity

- Recorded: 2026-08-24T08:37:44Z.
- Branch: `build/002-kaggle-competition-adapter`.
- Implementation freeze:
  - commit `0385d238ab85477ce6f995f7182855a7b3473f5d`;
  - tree `5b9a5610df4add0f0417f4f73161ff082af7b502`.
- Push: `origin/build/002-kaggle-competition-adapter` reached the exact implementation commit.
- Draft PR: `https://github.com/Grativy6/ARC3/pull/6`.
- No merge, release, upload, terms acceptance, token use, or official competition submission was
  performed.

## V-002-0022 — Second 0385d238 package-only regression

- Recorded: 2026-08-24T09:05:27Z.
- Source:
  - commit `0385d238ab85477ce6f995f7182855a7b3473f5d`;
  - tree `5b9a5610df4add0f0417f4f73161ff082af7b502`.
- Failed Build 001 package-only workflow:
  `https://github.com/Grativy6/ARC3/actions/runs/32706714371`.
- Result: Ubuntu and Windows `FAILED_MECHANISM`.
- Cross-platform cause: the packaged startup probe constructed `MyAgent` without configuring its
  tournament governor. The exact terminal error was
  `arc3.errors.ConfigurationError: MyAgent tournament governor was not configured`.
- Linux-only additional cause: the protected package-only selector collected
  `tests/integration/test_pinned_agents_framework.py`, whose exact pinned Agents integration
  transitively exercises POSIX subprocess behavior outside that guard.
- Failed producer receipts:
  - Ubuntu:
    `18541349e45d99de28c0f30db5edcf1b15c03c993e940eefde739f0950f596c8`;
  - Windows:
    `dd9800dc390fb107f5b15bafa2b948971df9b826c12ec38283b254244f5e9b4f`.
- The associated ARC3 workflow `32706714376` ended canceled overall: Ubuntu succeeded and Windows
  was canceled. It is not treated as a clean exact-head conclusion.
- Package-only receipts still reported no semantic public-manifest access, gameplay, or game-source
  use. Public authority consumed: no.

## V-002-0023 — 753b0e0 package-probe and selector repair

- Recorded: 2026-08-24T09:05:27Z.
- Source:
  - commit `753b0e007222a973a2c8a6d7ce14a395135d3c5f`;
  - tree `d07e72716a1f918ed04a6892adb1e3f46259e345`.
- Repair 1: the packaged startup probe conditionally configures the tournament governor before
  constructing `MyAgent`.
- Repair 2: Build 001's protected package-only selector excludes only the exact POSIX pinned
  Agents integration test, with its reason. Ordinary ARC3 CI retains that test.
- Local verification: targeted selection `30 passed`; packaged startup passes. The exact local
  invocation and standalone transcript hash were not sealed.
- Hosted conclusions at this evidence freeze:
  - Build 002 package and native Linux cold-start workflow
    `https://github.com/Grativy6/ARC3/actions/runs/32708504639`: `PASS`;
  - exact-head ARC3 CI
    `https://github.com/Grativy6/ARC3/actions/runs/32708504627`: `PENDING`;
  - exact-head Build 001 package-only CI
    `https://github.com/Grativy6/ARC3/actions/runs/32708504623`: `PENDING`.
- Pending checks are not represented as green. Public authority consumed: no.

## V-002-0024 — Current frozen profile, package, cold start, and preflight

- Recorded: 2026-08-24T09:20:26Z.
- Frozen source:
  - branch `build/002-kaggle-competition-adapter`;
  - commit `753b0e007222a973a2c8a6d7ce14a395135d3c5f`;
  - tree `d07e72716a1f918ed04a6892adb1e3f46259e345`.
- Synthetic profile `artifacts/build002/profile-753b0e0/profile.json`: `PASS`.
  - serialized file SHA-256:
    `ed2d4c336017551cb4b99e3fc2bc71eedf66b87683811d0d4a00056e0f84fb15`;
  - producer receipt SHA-256:
    `3f03b17ed639a6e7c6762254a1cba9fdfabb45aaa6ac42f9eb72e7f7b0048714`;
  - 80 actions; wall time `39.6246924s`; peak RSS `321,466,368` bytes;
  - maximum production controller cycle `3.3508976999946753s`.
- Package `artifacts/build002/final-753b0e0`: `PACKAGING_PASS`.
  - candidate:
    `adcd92352f55a0109c0898fe14b531e8780f02dc9b68489af449c1b8b8c16d9a`,
    `838,438` bytes;
  - notebook:
    `adbb75d09806da104a5d3bfbe41e55d809ec2bb91514aafa6176c2469f30c81e`,
    `548,193` bytes;
  - first-party payload:
    `726e595523a9b737a3b000b6d4d088a8e9289c1e6fd1da03297b79876311356f`,
    `400,650` bytes and `104` members;
  - package manifest:
    `29f5b430ff3be418bd8c4922939aa9134f823864983abf320601e1a46ca89388`;
  - SBOM:
    `e1d4836e974f22cf8821ddc46909edc1bce0ed2146a9ad4116550d11a130d0ed`;
  - serialized build receipt:
    `be23ee24c614229b2f940c112fb916f12b63cbdc700c8bcafc1569024d008bc5`;
  - build producer receipt:
    `8afaf2f16cf9f4a7c7825718b14427b5afdcb239d877523d22e70f617ed46358`;
  - serialized integrity receipt:
    `9287f22b9a6d63cd8dd3540661f28b2115e9935488d24c38aeb58767c7ad1b3b`;
  - integrity producer receipt:
    `42aa847bc4443f100be9163b9bb9746ed30dc1e5d79692d20d7d1cfbc43da588`;
  - `package_only_passed=true`;
    `full_competition_integrity_status=NOT_EVALUATED_PUBLIC_IDENTIFIERS`.
- Native Linux cold start from workflow `32708504639`: `PASS`.
  - receipt file SHA-256:
    `d04dcef55e36a9ee32a6f4153d89efc6b61560962b9931b031a70632a4ff4ecc`;
  - 31 exact wheels; wall time `12.728529202s`; peak memory `132,288,512` bytes;
  - zero public-environment interactions; Kaggle was not accessed.
- Frozen production preflight: `BLOCKED_EXTERNAL` before arming or interaction.
  - serialized source artifact SHA-256:
    `15d748c6954705cabdfc37d0f993ec3e5d352558fb0741d7bd7cbd472e24e82e`;
  - producer receipt SHA-256:
    `bb37fa65c0bf470ba54b2e6b82c14c01cafc8045d9697b1ac82893b2a241b189`;
  - request SHA-256:
    `b842e2cee086ec2833bdd7c3453482f88c8a889b1e474ca992124e8a33033160`;
  - `FileNotFoundError` message SHA-256:
    `ba7ce61033f638929402dad230d898e52fb6ddbdf1471b4951fe49c525e8bd86`;
  - holdout authority consumed `false`; scorecard intents, makes, resets, and actions all zero.
- Public-run disposition: `0/1` consumed. Total RHAE, completions, per-game/per-level scores,
  human comparisons, gameplay wall time/peak memory, governor allocation/reserve, and gameplay
  failure taxonomy remain `NOT_MEASURED`.
- Supersession rule: V-002-0016 through V-002-0019 remain historical evidence for `0385d238`;
  this entry binds the current implementation artifacts without overwriting them.
- Build 002 remains `PARTIAL` with exact evaluation `BLOCKED_EXTERNAL`. Build 001 remains unchanged
  `PARTIAL` and historically `SEALED_UNCONSUMED`.

## V-002-0025 — Preserve preflight path-layout and non-fresh-output attempts

- Recorded: 2026-08-24T09:12:27Z.
- Superseded request 1 used the clean worktree's temporary `final-753b0e0-a` A/B package path.
  That path existed during the run and produced a valid pre-consumption `BLOCKED_EXTERNAL` stop,
  but it did not match the retained main-worktree artifact layout. Preserved identities:
  - request SHA-256:
    `71cfd4e150b7b600d7af01e8f6c5003f83bbb73e4ee8c0b479d7d168263646f8`;
  - serialized receipt SHA-256:
    `607bcd215120524a5a88c0ec086da81f38346377f70751643f7052ebf9774845`;
  - producer receipt SHA-256:
    `dc28361fde479112820a3f62f1e7edf3e47ec1d7a0e907a66ac37e995da41d8d`.
- Failed attempt 2 corrected the retained package paths but reused an existing output directory.
  The preflight failed closed with `EvaluationError: Build 002 preflight output directory must be
  fresh`. Preserved identities:
  - status `FAILED_PREFLIGHT`, exit `2`;
  - request SHA-256:
    `1a04da9d372478b5dd91fb83837139fb615493a98703ab66eeb9c80f0212286d`;
  - serialized failure SHA-256:
    `252a42fae72b2683d5651a1fd3febe2199628e9397971e47b050cae00611f507`;
  - producer receipt SHA-256:
    `e16c44ff00798d354b1a6f6026aa56d7915337d64eec16304f25020667bd82e4`;
  - error-message SHA-256:
    `4e35b9a5b583cf5dba62dd81d1a8cfbed017a69c9e9b7d9714628b0436fcacda`.
- Repair: retain the delivered package and flat cold-start receipt paths, use a fresh final output
  directory, and rerun launch-free from clean commit `753b0e0`.
- Final result: `BLOCKED_EXTERNAL`, exit `3`, before arming or interaction.
  - request SHA-256:
    `b842e2cee086ec2833bdd7c3453482f88c8a889b1e474ca992124e8a33033160`;
  - serialized source artifact SHA-256:
    `15d748c6954705cabdfc37d0f993ec3e5d352558fb0741d7bd7cbd472e24e82e`;
  - producer receipt SHA-256:
    `bb37fa65c0bf470ba54b2e6b82c14c01cafc8045d9697b1ac82893b2a241b189`.
- Every attempt recorded zero environment actions and makes. The canonical one-shot directory was
  absent before and after; public authority remains `0/1` consumed.

## V-002-0026 — Corrected focused competition and package verification

- Recorded: 2026-08-24T09:12:27Z.
- Initial command named nonexistent file `tests/release/test_package_only_pytest.py`; pytest exited
  `1` with `no tests ran`. This command typo changed no source or evidence and consumed no public
  authority.
- Corrected command:
  `.venv\Scripts\python.exe -m pytest -q tests\competition
  tests\release\test_package_startup_probe.py
  tests\release\test_package_only_release_candidate_verifier.py --basetemp C:\q10t`.
- Result: `219 passed, 3 skipped in 234.79s`, exit `0`.
- The three skips are declared POSIX-only signal/RSS checks on Windows. Hosted Linux coverage
  remains in ordinary and package workflows.
- Coverage emitted four benign warnings for already-removed temporary extracted package source
  paths. Test status remained `PASS`; no public environment was touched.

## V-002-0027 — Terminal hosted verification at the implementation freeze

- Recorded: 2026-08-24T09:20:26Z.
- Frozen branch head: `753b0e007222a973a2c8a6d7ce14a395135d3c5f`; tree
  `d07e72716a1f918ed04a6892adb1e3f46259e345`.
- GitHub PR merge object: `e316089172c35c1fd2d2276ce093874b3c9cff81`; its tree is exactly
  `d07e72716a1f918ed04a6892adb1e3f46259e345`. The merge-name difference therefore introduced no
  source-tree drift.
- ARC3 CI `https://github.com/Grativy6/ARC3/actions/runs/32708504627`: `PASS`.
  - Ubuntu job `97374728423`: `1476 passed, 10 skipped`; lint, format, strict mypy, and runtime
    doctor passed.
  - Windows job `97374728560`: `1466 passed, 20 skipped`; lint, format, strict mypy, and runtime
    doctor passed.
- Build 001 protected package-only CI
  `https://github.com/Grativy6/ARC3/actions/runs/32708504623`: `PASS` on Ubuntu and Windows while
  preserving the deliberate `BLOCKED_EXTERNAL` private-surface result.
  - Ubuntu receipt file SHA-256:
    `56e7cb6a4e9b882cb7fe8eb0310ac9a75fb968352b807655dcc7671766611813`.
  - Windows receipt file SHA-256:
    `c053e798a9c368cf8607b9a8953e1369b76f855d532dd8e3f3d7d7114207e054`.
- Build 002 package/native cold-start CI
  `https://github.com/Grativy6/ARC3/actions/runs/32708504639`: `PASS`.
- Non-fatal runner warning: current `actions/checkout@v4` and `astral-sh/setup-uv@v6` advertise a
  deprecated Node.js 20 action runtime and were forced onto Node.js 24 by the runner. This is
  tracked as maintenance provenance, not a test failure.
- Stage 10 is `PASS` at the implementation freeze. The later documentation-only commit cannot
  contain its own SHA or post-commit CI conclusion; the draft PR supplies that external receipt.
- Public authority consumed: no.

## V-002-0028 — Stable-mirror final repository secret scan

- Recorded: 2026-08-24T09:28:40Z.
- Initial current-worktree scan: `FAILED_INFRASTRUCTURE`. The scanner enumerated all `499`
  tracked and unignored untracked candidates with `git ls-files -co --exclude-standard`, then
  reported four `candidate-mutated-during-scan` findings while OneDrive was changing file
  metadata. It reported no secret-pattern rule findings. The failure remains evidence and was not
  relabeled as a clean scan.
- Repair: copy the exact eleven-file documentation overlay onto detached implementation commit
  `753b0e007222a973a2c8a6d7ce14a395135d3c5f` in non-OneDrive worktree `C:\q11`, then rerun the
  same bounded scanner over the same Git candidate enumeration.
- Stable-mirror result: `PASS`, exit `0`; candidate count `499`; finding count `0`.
- Scope: repository candidate bytes only. Package payload and candidate secret scans remain
  independently bound by the final package manifest and cold-start receipts.
- Public authority consumed: no.
