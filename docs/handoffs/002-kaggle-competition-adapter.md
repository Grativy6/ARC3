# ARC3 Build 002 — Owner handoff

## Disposition

- **Overall:** `BUILD 002: PARTIAL`
- **External boundary:** `BLOCKED_EXTERNAL`
- **Branch:** `build/002-kaggle-competition-adapter`
- **Implementation freeze:** `753b0e007222a973a2c8a6d7ce14a395135d3c5f`
- **Tree:** `d07e72716a1f918ed04a6892adb1e3f46259e345`
- **Draft pull request:** <https://github.com/Grativy6/ARC3/pull/6>
- **Build 001:** unchanged `PARTIAL`
- **Build 001 holdout:** unchanged historical `SEALED_UNCONSUMED`
- **Build 002 authority:** `AUTHORIZED_ONCE_NOT_YET_CONSUMED`
- **Build 002 runs started:** `0/1`
- **Official or local-public RHAE:** `NOT_MEASURED`

Christopher D. Pang is author and steward. AI systems were development tools and assistants, not
co-authors, owners, or independent authorities.

## What Build 002 delivered

Build 002 preserves ARC3's research system and adds:

- explicit `RESEARCH_UNBOUNDED` and `COMPETITION_BOUNDED` modes;
- official `MyAgent.is_done()` and `MyAgent.choose_action()` entry points;
- a deterministic process-global tournament governor;
- dynamic environment allocation, protected reserve, legal-action enforcement, fallback,
  action-value accounting, and opportunity-cost accounting;
- exact one-scorecard, one-`make`, level-reset-only, no-game-reset lifecycle controls;
- competition-only compact trace and sparse checkpoints while preserving research defaults;
- documented ACTION1–4 and ACTION7 grants only at the bounded adapter boundary;
- evidence-driven ACTION5 and coordinate ACTION6 behavior;
- durable one-shot intent, interruption, failure, and tamper-resistant result receipts;
- an exact clean-source payload, dependency lock, SBOM, notices, notebook, and structural Parquet
  artifact;
- native Linux CPython 3.12 offline cold-start evidence;
- a fail-closed frozen preflight that preserves the authorized public run.

No game-ID-specific policy, hosted model call, credential, terms acceptance, upload, submission,
paid compute, merge, release, DOI, or external representation was used.

## Measured results

There is no public gameplay result.

| Metric | Result |
|---|---|
| total RHAE | `NOT_MEASURED` |
| completed games | `NOT_MEASURED` |
| completed levels | `NOT_MEASURED` |
| per-game/per-level scores | `NOT_MEASURED` |
| actions versus human baselines | `NOT_MEASURED` |
| public-run wall time / peak memory | `NOT_MEASURED` |
| governor allocation / remaining reserve | `NOT_MEASURED` |
| perception/goal/rule/planning/execution/platform/budget failures | `NOT_MEASURED` |

The zero scorecard, `make`, action, and run-start counters are nonconsumption evidence, not a score.

The strongest bounded measurement is synthetic: 80 competition-mode actions completed in
39.6246924 seconds at 321,466,368-byte peak RSS, with deterministic replay, 11 fault cases, and 12
robustness cases passing. Maximum measured production-controller cycle was
3.3508976999946753 seconds. The profile file is
`sha256:ed2d4c336017551cb4b99e3fc2bc71eedf66b87683811d0d4a00056e0f84fb15`,
with producer receipt
`sha256:3f03b17ed639a6e7c6762254a1cba9fdfabb45aaa6ac42f9eb72e7f7b0048714`.
It carries `NO_GENERALIZATION_CLAIM`.

## Package and notebook

- Candidate:
  `sha256:adcd92352f55a0109c0898fe14b531e8780f02dc9b68489af449c1b8b8c16d9a`,
  838,438 bytes.
- Notebook:
  `sha256:adbb75d09806da104a5d3bfbe41e55d809ec2bb91514aafa6176c2469f30c81e`,
  548,193 bytes.
- First-party payload:
  `sha256:726e595523a9b737a3b000b6d4d088a8e9289c1e6fd1da03297b79876311356f`.
- Safe-fixture Parquet:
  `sha256:f601196d5298e525e04c22185acb3668c3a9f74c6f371040164169fcc17279c9`,
  856 bytes.
- Linux wheelhouse: 31 packages, 45,073,152 bytes.
- Package manifest:
  `sha256:29f5b430ff3be418bd8c4922939aa9134f823864983abf320601e1a46ca89388`.
- SBOM:
  `sha256:e1d4836e974f22cf8821ddc46909edc1bce0ed2146a9ad4116550d11a130d0ed`.
- Build receipt file / producer:
  `sha256:be23ee24c614229b2f940c112fb916f12b63cbdc700c8bcafc1569024d008bc5` /
  `sha256:8afaf2f16cf9f4a7c7825718b14427b5afdcb239d877523d22e70f617ed46358`.
- Integrity-A file / producer:
  `sha256:9287f22b9a6d63cd8dd3540661f28b2115e9935488d24c38aeb58767c7ad1b3b` /
  `sha256:42aa847bc4443f100be9163b9bb9746ed30dc1e5d79692d20d7d1cfbc43da588`.
- Native Linux cold start: `PASS`, 12.728529202 seconds, 132,288,512-byte peak RSS; receipt file
  `sha256:d04dcef55e36a9ee32a6f4153d89efc6b61560962b9931b031a70632a4ff4ecc`.
- Secret findings: zero.
- Kaggle upload or official submission: none.

The generated Parquet is structurally valid against the pinned public four-column contract.
Private gateway/scorer acceptance remains unverified.

## Public-run disposition

The frozen preflight returned `BLOCKED_EXTERNAL` before arming because exact private Kaggle
surfaces, external attestation, and independently pinned ten-game static assets were unavailable.
Its serialized receipt is
`sha256:15d748c6954705cabdfc37d0f993ec3e5d352558fb0741d7bd7cbd472e24e82e`,
with producer receipt
`sha256:bb37fa65c0bf470ba54b2e6b82c14c01cafc8045d9697b1ac82893b2a241b189`,
request `sha256:b842e2cee086ec2833bdd7c3453482f88c8a889b1e474ca992124e8a33033160`,
and hashed error message
`sha256:ba7ce61033f638929402dad230d898e52fb6ddbdf1471b4951fe49c525e8bd86`.

The holdout remains mechanically unconsumed:

- runs started: `0/1`;
- scorecards opened: `0`;
- environment `make` calls: `0`;
- gameplay actions: `0`;
- authority consumed: `false`.

Build 002 evidence does not revise Build 001. Public-source preview exposure remains recorded, so
any later run must be labeled `local-public-source-preview-exposed`.

## Verification status

The implementation, lifecycle, source locks, package, notebook, structural output, deterministic
replay, synthetic profiling, failure injection, secret scan, and native Linux cold start passed on
their declared surfaces. The final repair makes packaged startup call `configure_tournament`
before agent construction. Exact pinned POSIX framework integration is excluded only from Build
001's protected package-only guard; ordinary CI retains it.

- Build 002 native Linux package/cold-start run
  <https://github.com/Grativy6/ARC3/actions/runs/32708504639>: `PASS`.
- Exact-head ARC3 CI run
  <https://github.com/Grativy6/ARC3/actions/runs/32708504627>: `PASS`; Ubuntu `1476 passed, 10
  skipped`, Windows `1466 passed, 20 skipped`.
- Exact-head Build 001 package-only run
  <https://github.com/Grativy6/ARC3/actions/runs/32708504623>: `PASS`; the deliberate private-surface
  result remained `BLOCKED_EXTERNAL` on both platforms.

Stage 10 is `PASS` at the implementation freeze. The final documentation commit cannot embed its
own SHA or post-commit CI conclusion; verify that final documentation-only head externally on the
draft PR after push.

## Unresolved burdens

- exact private Kaggle wheels, framework input, gateway, scorer, and accepted-terms runtime;
- independently pinned ten-game static assets;
- local-toolkit versus Kaggle score-cap divergence;
- public-toolkit versus staff-sample version divergence;
- exact private `submission.parquet` validation;
- OS/native network and process containment;
- every public performance and gameplay-failure measurement;
- permanent public-source preview provenance.

## Actions requiring explicit owner authorization

The following were not performed and remain owner-gated:

- merge PR #6;
- accept ARC Prize or Kaggle terms;
- authorize any credentialed Kaggle execution;
- upload a notebook;
- click Submit to Competition or spend a daily submission;
- activate paid compute;
- publish a release or DOI;
- communicate externally as Christopher D. Pang.

No Kaggle token is requested.

## Smallest owner-only next action

Review draft PR #6 and decide whether to merge it.
