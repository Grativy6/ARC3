# ARC3 Build 002 — Kaggle competition adapter and first honest RHAE boundary

**Overall disposition:** `PARTIAL`
**External evaluation boundary:** `BLOCKED_EXTERNAL`
**Implementation freeze:** `753b0e007222a973a2c8a6d7ce14a395135d3c5f`
**Source tree:** `d07e72716a1f918ed04a6892adb1e3f46259e345`
**Draft pull request:** <https://github.com/Grativy6/ARC3/pull/6>
**Official and local-public RHAE:** `NOT_MEASURED`
**Build 002 public run:** `0/1`, not consumed
**Build 001:** unchanged `PARTIAL`; historical holdout record remains `SEALED_UNCONSUMED`

Christopher D. Pang is author and steward. AI systems were development tools and assistants, not
co-authors, owners, or independent authorities.

## Abstract

Build 002 adds a deterministic bounded competition surface around ARC3's persistent research
controller. It implements the official `MyAgent.is_done()` and `MyAgent.choose_action()` interface,
a process-global tournament governor, exact lifecycle enforcement, competition-only hot-path
controls, an offline package, generated notebook, and locally validated `submission.parquet`.

The strongest result is an engineering result, not a benchmark result. Available local and native
Linux package, replay, lifecycle, fault, and structural-output checks passed. Exact private Kaggle
wheels, framework input, gateway, scorer, accepted-terms runtime, static ten-game provenance, and
OS-enforced platform containment were unavailable. The frozen preflight therefore returned
`BLOCKED_EXTERNAL` before arming a scorecard or opening an environment. No public or official RHAE
exists.

## 1. Source identity and claim boundary

Build 002 was branched from merged `origin/main`
`a1931c673b90923e1af78127229667544802a096`. Build 001 final
`8a42e43c96ac1edada21725746cdedcee24e68f9` was verified ancestral. No Build 001
handoff, ledger, report, or evidence file changed.

Controlling public identities were pinned as follows:

| Source | Commit |
|---|---|
| `arcprize/ARC-AGI` | `f12822c4d550121c35a275008d964afbbed47d2f` |
| `arcprize/ARCEngine` | `b495c6acaf253c9681cd7b75c4299d352e9ce6f8` |
| `arcprize/ARC-AGI-3-Agents` | `4743e7d0aaae0ded0d98a89a7e282e63564cd58b` |
| `arcprize/ARC-AGI-3-Kaggle-Starter` | `eeb1535404f321d280a8f9194bbc1d7aca5f05fc` |
| `arcprize/docs` | `a5dfc0b64c625fb4a19cf074af845ebe0bb88ff8` |

The refreshed anonymous Kaggle metadata response is
`sha256:ca6253ca8e87ba6e4e5a435ee5f83bc27aaf62aa564860c1e31390349978de4f`.
It identifies competition `133468`, a nine-hour CPU/GPU limit, notebook-only execution, disabled
internet, and `submission.parquet`. The project lock is
`sha256:fb3acb1e375dddaaa02e38dc39cd3a0cde7fe95045d4dca34d976d29e0f56c68`.

The pinned public toolkit is ARC-AGI `0.9.9` with ARCEngine `0.9.3`. Local public scoring remains
source-bound because the public toolkit's 1.15 level cap conflicts with the current Kaggle
description's 1.0 cap. No local score may be promoted to official RHAE.

## 2. Implemented competition surface

Build 002 adds:

- explicit `RESEARCH_UNBOUNDED` and `COMPETITION_BOUNDED` execution modes;
- preservation of research-mode allocator tracing, per-action checkpoints, and generic opaque
  action learning;
- competition-only compact in-memory trace, 16-action sparse checkpoints, deterministic replay,
  and failure receipts;
- competition-only grants for `ACTION1` up, `ACTION2` down, `ACTION3` left, `ACTION4` right, and
  `ACTION7` undo;
- evidence-driven treatment of variable `ACTION5` and coordinate-dependent `ACTION6`;
- exact `MyAgent.is_done()` and `MyAgent.choose_action()` integration;
- a process-global governor with legal-action filtering, dynamic per-environment allocation,
  action-value and opportunity-cost accounting, bounded fallback, and deterministic stop reasons;
- one-scorecard, one-`make`-per-environment, level-reset-only, no-game-reset lifecycle enforcement;
- durable scorecard and environment-intent receipts with append-only hash chains;
- exact recomputation and tamper rejection for score, allocation, reserve, failure, and source
  identity artifacts.

The frozen competition configuration is
`sha256:3b56018560e4bde4005da4c7f30bc97a4180179d4a8ce1c0959cc0c76651694a`.
It uses a 32,400-second ceiling, 6,000-second reserve, at most 240 seconds and 80 actions per game,
8,800 total actions over 110 environments, a five-second minimum fallback, and a ten-second
controller-cycle limit.

## 3. Package, notebook, and output evidence

The exact clean source produced:

| Artifact | Size | SHA-256 |
|---|---:|---|
| first-party payload | 400,650 bytes | `726e595523a9b737a3b000b6d4d088a8e9289c1e6fd1da03297b79876311356f` |
| Kaggle candidate | 838,438 bytes | `adcd92352f55a0109c0898fe14b531e8780f02dc9b68489af449c1b8b8c16d9a` |
| notebook | 548,193 bytes | `adbb75d09806da104a5d3bfbe41e55d809ec2bb91514aafa6176c2469f30c81e` |
| safe-fixture `submission.parquet` | 856 bytes | `f601196d5298e525e04c22185acb3668c3a9f74c6f371040164169fcc17279c9` |

The payload contains 104 exact Git-blob-bound members, including first-party runtime,
configuration, licenses, notices, and source locks. ARC3 has no separate learned-model asset. The
Linux artifact bundle contains 31 hash-pinned wheels totaling 45,073,152 bytes.

The package manifest is
`sha256:29f5b430ff3be418bd8c4922939aa9134f823864983abf320601e1a46ca89388` and the SBOM is
`sha256:e1d4836e974f22cf8821ddc46909edc1bce0ed2146a9ad4116550d11a130d0ed`.
The serialized build receipt is
`sha256:be23ee24c614229b2f940c112fb916f12b63cbdc700c8bcafc1569024d008bc5`,
with producer receipt
`sha256:8afaf2f16cf9f4a7c7825718b14427b5afdcb239d877523d22e70f617ed46358`;
the clean integrity-A receipt is
`sha256:9287f22b9a6d63cd8dd3540661f28b2115e9935488d24c38aeb58767c7ad1b3b`,
with producer receipt
`sha256:42aa847bc4443f100be9163b9bb9746ed30dc1e5d79692d20d7d1cfbc43da588`.

Native Linux CPython 3.12.14 cold start passed with no host `.pth` bridge, no foreign site path,
exact production requirements, and zero observed non-loopback Python socket attempts. It completed
in 12.728529202 seconds with 132,288,512-byte peak RSS. The notebook executed its exact four
generated code cells and emitted a readable, unique, one-row safe-fixture Parquet file with columns
`row_id`, `game_id`, `end_of_game`, and `score`.

This proves pinned-public structural validity only. The safe loopback framework and gateway are
fixtures. Kaggle's private gateway, framework, scorer, and OS-level network containment were not
used or proven.

## 4. Synthetic runtime evidence

The frozen synthetic profile file is
`sha256:ed2d4c336017551cb4b99e3fc2bc71eedf66b87683811d0d4a00056e0f84fb15`, with producer receipt
`sha256:3f03b17ed639a6e7c6762254a1cba9fdfabb45aaa6ac42f9eb72e7f7b0048714`.
It completed 80 actions in 39.6246924 seconds at 321,466,368-byte peak RSS. Deterministic replay,
complete action chains, the 11-case fault matrix, the 12-case robustness matrix, and the pinned
regression comparison passed. Maximum measured production controller cycle was
3.3508976999946753 seconds.

These measurements are `synthetic` and carry `NO_GENERALIZATION_CLAIM`. They are neither public
gameplay nor RHAE.

## 5. Public-run disposition

The production preflight returned `BLOCKED_EXTERNAL`. Its serialized file is
`sha256:15d748c6954705cabdfc37d0f993ec3e5d352558fb0741d7bd7cbd472e24e82e`,
with producer receipt
`sha256:bb37fa65c0bf470ba54b2e6b82c14c01cafc8045d9697b1ac82893b2a241b189`, request
`sha256:b842e2cee086ec2833bdd7c3453482f88c8a889b1e474ca992124e8a33033160`,
and hashed error message
`sha256:ba7ce61033f638929402dad230d898e52fb6ddbdf1471b4951fe49c525e8bd86`.
It stopped before arming or any environment interaction because the required exact external
attestation and official surfaces were unavailable.

| Requested public metric | Result |
|---|---|
| total RHAE | `NOT_MEASURED` |
| completed games and levels | `NOT_MEASURED` |
| per-game and per-level scores | `NOT_MEASURED` |
| agent actions versus human baselines | `NOT_MEASURED` |
| public-run wall time and peak memory | `NOT_MEASURED` |
| allocation and remaining reserve | `NOT_MEASURED` |
| gameplay failure taxonomy | `NOT_MEASURED` |

Boundary counters are zero: scorecards opened `0`, environment `make` interactions `0`, gameplay
actions `0`, and runs started `0/1`. These counters must not be misread as a zero score.

The one-run authority remains `AUTHORIZED_ONCE_NOT_YET_CONSUMED` but is not eligible to run until
all exact preflight predicates pass. The earlier public-source preview exposure remains permanent
provenance; any later result must be labeled `local-public-source-preview-exposed`, not pristine or
unseen.

## 6. Failures and unresolved burdens

Preserved failures include the initial missing competition-package projection, a superseded Kaggle
response-hash inconsistency, an undersized profiler deadline, a shared-environment package race,
OneDrive snapshot churn, long Windows temporary-path failures, clean-tree fixture assumptions, and
the package-only boundary regression repaired at `0385d238`. The preflight ledger additionally
preserves one temporary A/B-layout request and one corrected-path retry rejected because its output
directory was not fresh; the final retained-path request used a fresh output directory. The later
`753b0e0` repair makes
package startup call `configure_tournament` before agent construction and excludes exact pinned
POSIX framework integration only from Build 001's protected package-only guard; ordinary CI still
retains and exercises that integration test.

Open burdens remain:

- exact private Kaggle wheels, framework, gateway, scorer, and accepted-terms execution;
- exact static provenance for the ten-game public set;
- public-toolkit versus Kaggle score-cap and package-version divergence;
- exact private `submission.parquet` acceptance;
- OS/native network and process containment;
- every requested public performance and gameplay-failure measurement.

## 7. Stage disposition

| Stage | Status |
|---|---|
| 00 source and authority preflight | `PASS` |
| 01 execution modes | `PASS` |
| 02 official adapter semantics | `PASS` |
| 03 governor and lifecycle | `PASS` |
| 04 competition hot path | `PASS` |
| 05 offline package and cold start | `PASS` on available public/native Linux surfaces |
| 06 notebook and Parquet validation | `PASS` at pinned-public structural scope |
| 07 frozen one-shot preflight | `BLOCKED_EXTERNAL` |
| 08 authorized public run | `BLOCKED_EXTERNAL`; unconsumed |
| 09 blocked-result seal | `PASS`; no public result graph exists |
| 10 final verification and handoff | `PASS`; implementation-freeze ordinary, package-only, and package CI green |

Build 002 is therefore `PARTIAL`, with the scientific public/official result honestly unmeasured.
Build 002 package/cold-start workflow `32708504639`, ARC3 CI run `32708504627`, and Build 001
package-only run `32708504623` all passed at the implementation freeze. ARC3 CI reported `1476
passed, 10 skipped` on Ubuntu and `1466 passed, 20 skipped` on Windows; lint, format, strict typing,
and the runtime doctor also passed. The final documentation commit cannot record its own SHA or
post-commit CI conclusion; those are verified externally on the draft PR after push.

## Smallest owner-only next action

Review draft PR #6 and decide whether to merge it. Any later terms acceptance, credentialed Kaggle
execution, notebook upload, or competition submission requires separate explicit owner action and
authorization.
