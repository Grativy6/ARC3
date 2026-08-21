# ARC3 Build 000 — Owner handoff

## Disposition

- **Overall build:** PARTIAL
- **Branch:** `build/000-arc3-end-to-end`
- **Draft pull request:** <https://github.com/Grativy6/ARC3/pull/3>
- **Release-candidate source:** `90ecf7267d5bb23d751d6f7ce3e8aa75f2f1a130`
- **Release-candidate tree:** `0cf6e00b2fcc399e7a99a62c20e91bb84d485f13`
- **Stage 18 evidence checkpoint:** `a72737c923fff23b31b16450c7553a1ab3766f53`
- **Claim boundary:** NO_GENERALIZATION_CLAIM

The final workflow commit is the pushed tip containing the Stage 20 seal. A commit cannot contain
its own SHA without changing that SHA; resolve it with `git rev-parse HEAD` after checkout. The
exact final value is recorded as PR #3's `headRefOid` and in the final autonomous-run response.
The PR must remain draft and unmerged until Christopher D. Pang decides otherwise.

Christopher D. Pang is the project author and steward. AI systems were development tools and
assistants, not co-authors, owners, or independent authorities.

## What exists

Build 000 contains a typed offline ARC-AGI-3 agent with explicit separation between observation,
interpretation, candidate hypothesis, accepted rule, world model, goal hypothesis, plan/probe,
action, returned consequence, and trace update. Raw observation/action/consequence receipts are
immutable. Derived summaries, hypotheses, indices, models, goals, and plans remain revisable and
reopenable.

The repository includes deterministic replay and tamper detection, checkpoint/resume with pending
action reconciliation, geometric perception, typed hypothesis tracking, executable retrodictive
world models, goal evidence, bounded planning/recovery, source-linked persistent memory, one
integrated controller, procedural environments, B0–B4 baselines, paired ablations, runtime and RSS
profiling, public-development evaluation, competition-integrity scans, an exact dependency lock,
an offline Kaggle package candidate, clean-clone verification, and complete research/evidence
reports.

## Strongest measured results

| Surface | Exact bounded result | Status |
|---|---|---|
| `synthetic` | Stage 12 FULL completed 32/32 in 190 actions; deterministic cycle completed 4/32 in 463 under equal 16-action budgets | MECHANISM_OBSERVED |
| `synthetic` | Stage 14 FULL completed 8/14 in 150 actions; no world-model simulation completed 1/14 in 211; no goal inference completed 0/14 in 224 | MECHANISM_OBSERVED for A4/A5; A3 conflicting |
| `synthetic` | Stage 16 completed 80 actions in 116.26474110002164 seconds at 175,210,496-byte peak RSS; all 9 frozen resource checks passed | runtime PASS |
| `local-public` | Stage 15 FULL completed zero levels and returned no official scorecard across 30 timeouts; B0 random produced the sole nonzero score and completed one development level | MECHANISM_NOT_OBSERVED |
| `local-public` | Stage 18 FULL completed zero levels and timed out in all 6 smoke runs; all 18 terminal result artifacts verify | FAILED_MECHANISM |
| `synthetic` | Stage 18 clean-clone release infrastructure passed 423 tests, 13 replay/tamper tests, exact Stage 13 reproduction, two byte-identical package builds, integrity, and secret checks | PASS |

Official RHAE remains unmeasured/null for these local runs. Completion, environment-action counts,
and local scorecard values are reported separately and are not RHAE. There is no `online-public`,
`Kaggle-public`, `semi-private`, or `official-private` result. No game source was read during public
evaluation to infer solutions. The ten-game public holdout remains unconsumed.

## Baseline and ablation comparison

- Stage 13 `synthetic`, seeds 7 and 11: FULL 2/2 in 8 actions; cycle and trace 1/2 in 19;
  random and novelty 0/2 in 32.
- Stage 14 `synthetic`, 154 paired terminal episodes: removing world-model simulation lost seven
  completions; removing goal inference lost eight. Disabling the retrodiction gate kept 8/14 and
  used nine fewer actions, conflicting with the opposite Stage 08 mechanism result.
- Stage 15 `local-public`: simple baselines returned their budgets; only B0 random completed a
  development level. FULL timed out 30/30 and returned no official scorecard.
- Stage 18 `local-public`: random and cycle each returned 480 actions and zero levels; FULL timed
  out 6/6 after 146 total actions and zero levels.

## Exact setup and verification

From a fresh checkout of the branch, use a portable uv 0.12.5 installation. This first bootstrap
may download public locked dependencies:

```powershell
uv sync --frozen --all-extras --dev --python 3.12.14 --link-mode copy
uv lock --check --offline
& .\.venv\Scripts\python.exe -m arc3 doctor --json
& .\.venv\Scripts\python.exe -m ruff check --no-cache .
& .\.venv\Scripts\python.exe -m ruff format --check --no-cache .
& .\.venv\Scripts\python.exe -m mypy --strict src agent scripts
& .\.venv\Scripts\python.exe -m pytest -q
& .\.venv\Scripts\python.exe -m pytest -q --no-cov tests/replay tests/property/test_trace_properties.py
```

The `--offline` lock check requires the bootstrap to have primed uv's local cache. Fully offline
environment creation likewise requires a primed cache or the exact wheel inputs; the measured
machine-specific offline clean-clone command and uv executable identity are preserved in the
Stage 18 report.

Build and locally exercise the no-submit offline package:

```powershell
.\scripts\prepare_kaggle_submission.ps1 --output artifacts\stage17\candidate --owner-username OWNER_USERNAME
```

`OWNER_USERNAME` is notebook metadata only. The command does not authenticate, accept terms,
upload, or submit. The hermetic Stage 18 command, exact transient/evidence paths, and permitted
nondeterminism are in `docs/reports/018-release-candidate-verification.md`.

## Key artifacts and SHA-256 identities

| Artifact | SHA-256 |
|---|---|
| `docs/evidence/014-ablation-acceptance.json` | `56e7c23bea479cd64fb4433e369bda28177ca76e94e4ba18ee756dab3a8ab82c` |
| `docs/evidence/015-public-development-acceptance.json` | `43d9b116448668626a27874f138f38f22011fb08fe7d38b8e335333cd0063815` |
| `docs/evidence/016-competition-profile-acceptance.json` | `8127acc6441bcba4f4e9b0a02b9950880c3231f7a0b4cef91c95dd089af0f595` |
| `docs/evidence/017-kaggle-package-acceptance.json` | `aac45a86092a7c83bdf26a2e12fbd396381f37257f9e3b5294850f65152583fa` |
| `docs/evidence/018-release-candidate-acceptance.json` | `92d37027c50889a979b1c57487ed490f52e4c7d742c14fe35b63f06af0a0966c` |
| Stage 18 release receipt file | `ae571ae99b2746bfe17f3e8ea790707810522f2f462d983a9c2726bb57dcc7a5` |
| Stage 18 release receipt canonical self-hash | `31ca85d0fa11de07372b740fc73dd3d9976e71808f9c84cb454710eaa92d6e91` |
| Stage 18 sealed artifact set, 1,895 files / 208,702,479 bytes | `00e343694d460b5a751fd3812ace699825967622d52cd18cf91ba994156969e0` |
| Stage 18 550,068-byte offline candidate | `5d64883392f8b1506314e64442702f51ecf0b52e54e190277dad52f07e6cd3f7` |
| `uv.lock` | `3bf42dcbe45720f71b7433584f56a5d5982ec1c687c341ad2626222fa5de285b` |
| `docs/evidence/019-dependency-license-inventory.json` | `7df3e815648e4c1e69f15c2a1f727c5a43dd37276bb1f9a2c5d6016597ce6c7f` |

The ignored Stage 18 raw artifacts remain under
`C:\a\arc3-s18-70ed0f3\artifacts\stage18\rc-90ecf72` on the measured machine. Compact receipts in
the repository bind the relevant identities so the handoff does not depend on that local path.

## Failed mechanisms and unresolved burdens

- FULL timed out in every measured `local-public` run: 30/30 at Stage 15 and 6/6 at Stage 18.
- Both palette-permuted and both action-remapped Stage 16 cases fell from their base score of 1.0
  to 0.0. These four results remain `FAILED_MECHANISM`.
- One rule-change case terminated before the intervention and remains `NOT_EXERCISED`.
- Retrodiction has conflicting evidence: beneficial in Stage 08, nine actions costlier at equal
  completion in Stage 14.
- The public holdout remains intentionally unconsumed after the development gate failed.
- Exact private Kaggle wheels/input framework, gateway, scorer, and a complete 110-game runtime
  remain unavailable or unmeasured. Local schema validation is not private-gateway validation.
- Static checks detect obvious game-ID tables, hosted-client imports, dependency drift, and secret
  patterns; they do not prove the absence of every possible shortcut or trusted-execution issue.

The initial Stage 18 417-pass/five-failure clean-clone run, OneDrive fixture failure, Windows/Linux
line-ending defect, and shallow-history CI failure remain preserved as infrastructure evidence;
later repairs do not erase them.

## Licensing and external gates

There is intentionally no root `LICENSE`. `docs/legal/candidates/MIT-0-CANDIDATE.md` begins with
`CANDIDATE ONLY — NO LICENSE GRANTED` and is nonoperative. `THIRD_PARTY_NOTICES.md` and
`docs/evidence/019-dependency-license-inventory.json` reconcile all 61 `uv.lock` records: one
first-party owner-decision record and 60 third-party records, with no unknown third-party record.

Competition-term acceptance, credential provision, paid compute, official submission, public
release/DOI, external communication as Christopher D. Pang, and merge remain human gates. None was
performed. Optional missing credentials did not block offline development or package rehearsal.

## Prioritized next builds

1. Predeclare a generic palette/action-equivariance mechanism and paired procedural test suite.
2. Profile the public FULL controller's low action throughput without tuning to game identities.
3. Add two guaranteed-exposure rule-change cases and verify post-intervention reopening.
4. Freeze a new generic milestone and rerun public development; do not rewrite Stage 15 or 18.
5. Open the ten-game holdout only after that future milestone produces a passing sealed
   development result.
6. After applicable owner gates, perform a no-submit exact-platform rehearsal with wall, RSS,
   framework, wheel, gateway, and output receipts.

## Smallest owner-only next action

Review docs/legal/candidates/MIT-0-CANDIDATE.md and explicitly approve or reject MIT-0 for ARC3 first-party source. No license is granted until that instruction.
