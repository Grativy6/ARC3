# Stage 00 — source identity and preflight

Status: **PASS**
Evidence surface: repository/source identity, not a benchmark result
Audit window: **2026-08-21T04:43:00Z–2026-08-21T04:50:00Z**
Owner/author/steward: **Christopher D. Pang**

## Result

The active repository state, controlling contracts, public upstreams, mutable rules pages, package resolution, and host runtime were verified before implementation. The implementation branch is `build/000-arc3-end-to-end`, created from `main@b1948e9d02ad7b1321cbc57f3538047813e01e98`.

The initial `docs/ledger/run-state.json` parsed successfully and accurately described a not-yet-started run: no completed stages, no checkpoint commit, and no evidence artifacts. Those empty fields were not promoted into evidence. Bootstrap PR [#1](https://github.com/Grativy6/ARC3/pull/1) was independently verified as merged at `df88ed44bbd8d1604e3003e22169f50d198356c3`; its referenced head `5d08e97a21290ba24e3b0282a2aefd6a32784330` and the current main commit all exist in the local object database. `git fsck --full` passed.

The frozen bootstrap reference exists at `docs/reference/AGENTS.arc3-bootstrap.v0.1.md` with SHA-256 `927b41db195e79d0f83fe807ed491e7217c2a2ca28e5362a0475161557649079`. It was identity-checked as provenance, not treated as a competing active contract.

## Controlling identities

| File | SHA-256 |
|---|---|
| `AGENTS.md` | `5949d5db179016cf161d504f64a6b1f2c3d4c4e839394de604f2086fc3df1292` |
| `docs/workflows/000-arc3-autonomous-end-to-end.md` | `fc205f770198a63386fe3505dbb7735e51842d15cfdd1d5623a646cb8a86183a` |
| `docs/specs/target-architecture.md` | `f10f4a335efda4f2a41b228f57b67b15583da4337ef4cd0cdc7cb945dffbea1e` |
| `docs/specs/trace-ledger-contract.md` | `82ec2d6cb0dedcaee1793d8c74151ff5a30ef0a71ab864f0575e2c102b7d5a4f` |
| `docs/specs/evaluation-protocol.md` | `cd7703d3b9f729c1a7a3c359509ae088fa805996d22c79f7ba38d428b82ba797` |

## Pinned upstream repositories

The identities below were read from each public repository's `refs/heads/main` and verified through GitHub commit metadata.

| Repository | Commit | Commit time | License identity |
|---|---|---|---|
| [`arcprize/ARC-AGI`](https://github.com/arcprize/ARC-AGI) | `f12822c4d550121c35a275008d964afbbed47d2f` | 2026-06-10T21:29:53Z | MIT |
| [`arcprize/ARCEngine`](https://github.com/arcprize/ARCEngine) | `b495c6acaf253c9681cd7b75c4299d352e9ce6f8` | 2026-01-29T03:34:01Z | MIT |
| [`arcprize/ARC-AGI-3-Agents`](https://github.com/arcprize/ARC-AGI-3-Agents) | `4743e7d0aaae0ded0d98a89a7e282e63564cd58b` | 2026-08-03T20:35:02Z | MIT |
| [`arcprize/ARC-AGI-3-Kaggle-Starter`](https://github.com/arcprize/ARC-AGI-3-Kaggle-Starter) | `eeb1535404f321d280a8f9194bbc1d7aca5f05fc` | 2026-05-27T16:50:53Z | `NOASSERTION`; no license file/detection at this commit |
| [`arcprize/docs`](https://github.com/arcprize/docs) | `a5dfc0b64c625fb4a19cf074af845ebe0bb88ff8` | source identity queried 2026-08-21 | `NOASSERTION`; no detected repository license |

The starter's interface and build route were inspected, but its code is not copied because no source-license grant was found at the pinned identity. ARC3 will build an equivalent thin first-party wrapper and preserve the expected `MyAgent` surface. This supersedes the earlier proposed copy/adapt route; the decision is recorded in `docs/ledger/DECISIONS.md`.

## Package identity

PyPI returned `arc-agi==0.9.9`, requiring Python `>=3.12` and declaring `arcengine>=0.9.3`, Flask, Matplotlib, Pydantic, python-dotenv, Pillow, and Requests. The wheel SHA-256 is `a0536df47b5ab93af16ba708083f74261cd1b7801bb2e0802824623c04d59e50`; the source archive SHA-256 is `ee822d83f4ea4ccb96377ecbc81ffe1e9e7ded15300aedf88150b7f4743a2bc8`.

A non-installing `uv` resolution for Windows/Python 3.12 produced 32 exact packages. The complete list and command are in `upstream.lock.json`. A managed CPython `3.12.14` runtime and `uv 0.12.5` are available; `uv` is invoked as `python -m uv` because its standalone directory is not on `PATH`.

## Current public contract

These facts are observations from primary sources accessed during the audit. They are mutable and apply only to this lock identity.

- [Game schema](https://docs.arcprize.org/game-schema.md): observations contain one or more frames; grids are at most 64×64; cells are integers 0–15; coordinates use top-left `(0,0)` and `(x,y)` ordering; game versions may change while names remain stable.
- [Actions](https://docs.arcprize.org/actions.md): games advertise a subset of `ACTION1`–`ACTION7`; `ACTION6` requires coordinates in 0–63; the page calls `ACTION7` undo; after `GAME_OVER`, only `RESET` is valid. Pinned `arcengine==0.9.3` types `ACTION7` only as a generic simple action, so undo and directional meanings remain defeasible observation-derived semantics rather than unconditional rules.
- [Recordings](https://docs.arcprize.org/recordings.md): online/API play can produce scorecard replays; local toolkit play does not itself generate official recordings; swarm recordings use JSONL. ARC3 therefore keeps its own first-party immutable trace independently of upstream replay availability.
- [Scoring methodology](https://docs.arcprize.org/methodology.md): a completed level uses `(human_baseline_actions / agent_actions)^2`, capped at 1.15; game aggregation weights levels by their 1-indexed level number; the total is the average of game scores. Internal computation that does not alter the environment is not an environment action.
- [Competition mode](https://docs.arcprize.org/toolkit/competition_mode.md): Kaggle forces competition mode; it evaluates all available environments, restricts environment creation/scorecards, and changes reset behavior. The adapter must preserve the pinned executable toolkit behavior where documentation and code disagree.
- [ARC Prize 2026 ARC-AGI-3 page](https://arcprize.org/competitions/2026/arc-agi-3): submissions use the designated Kaggle competition, evaluation has no internet, and prize eligibility requires open sourcing.
- [ARC Prize 2026 general rules](https://arcprize.org/competitions/2026): submitter-authored code/methods must use an eligible permissive public-domain-style license, with CC0 and MIT-0 given as examples; a license grant remains an owner action.
- [Kaggle competition](https://www.kaggle.com/competitions/arc-prize-2026-arc-agi-3/overview/timeline): the publicly rendered current page reports notebook-only submissions, internet disabled, CPU/GPU runtime no more than 9 hours, 110 evaluation games split evenly between public/private surfaces, entry/team deadline 2026-10-26, and final submission deadline 2026-11-02 at 23:59 UTC. The starter describes `submission.parquet` and a two-phase notebook/run then owner-submit flow. Kaggle's anonymous JSON list endpoint returned HTTP 401 and its raw HTML is dynamic, so URL/access time—not a transient client-shell hash—is the identity used here. No terms were accepted.

Exact documentation body hashes are preserved in `upstream.lock.json` for the stable Markdown surfaces.

## Contradictory or stale upstream evidence

These discrepancies are preserved rather than silently reconciled:

1. `ARC-AGI@f12822c...` declares/tags `0.9.9` and matches PyPI `0.9.9`, but its committed `uv.lock` records the root `arc-agi` package as `0.9.8`. ARC3 will generate and test its own lock.
2. `ARC-AGI-3-Agents` declares project version `0.1.0`, has `v0.9.x` tags, and its lock pins the older `arc-agi==0.9.1`. ARC3 uses only the pinned interface and explicitly pins toolkit `0.9.9`.
3. Documentation describes state-affecting interactions as counted actions, while pinned executable engine/scorer behavior counts every submitted non-`RESET` action, including a no-op. Local scoring will follow the executable pin and label any approximation.
4. Methodology and toolkit code cap a completed level at 115%, while the current Kaggle data-page formula describes a 100% ratio cap before squaring. Every score must therefore name its exact scorer/surface; a returned Kaggle score outranks local approximation for Kaggle.
5. Toolkit code still defaults to `https://three.arcprize.org`, while current Agents/docs surfaces direct registration/gateway use through `arcprize.org`. The adapter will probe safely and report live behavior without printing an anonymous or owner key.
6. The toolkit's anonymous-key path can log a fetched key at INFO. ARC3 will suppress/redact that logger and never preserve such output as evidence.
7. Upstream Agents/starter sample policy is not an ARC3 production baseline: it uses wall-clock/Python-hash seeding, can ignore advertised action availability, and includes a public-game-ID conditional. None of those behaviors will be copied.
8. Documentation's recording table says local toolkit play has no recordings, while pinned toolkit source supports local JSONL when recording is enabled. Upstream JSONL is not hash-linked/sealed, and the Agents conversion/playback path appears not to preserve `action_input` consistently. ARC3's own ledger remains authoritative.
9. ARC Prize and Kaggle pages give different second/third-place milestone prize splits even though their milestone totals agree. Prize allocation is not used by the agent, but the discrepancy remains a reason to re-read the owner-facing legal/rules surface before submission.

Each item is carried in `docs/ledger/OPEN_BURDENS.md` or a design decision until an executable test narrows it.

## Host and tools

| Surface | Measured identity |
|---|---|
| OS | Microsoft Windows 10 Home 10.0.19045, build 19045, x64 |
| CPU | AMD Ryzen 5 2600, 6 physical / 12 logical cores |
| RAM | 17,124,503,552 bytes total |
| GPU | NVIDIA GeForce GTX 1660, 6144 MiB, driver 560.94 |
| PowerShell | 7.6.4 |
| Python default | CPython 3.13.14 |
| Python selected | uv-managed CPython 3.12.14 x64 |
| uv | 0.12.5 |
| Git | 2.54.0.windows.1 |
| Docker | unavailable; not required for the Python-first route |

Network/DNS checks succeeded for ARC documentation, ARC Prize, GitHub, PyPI, and Kaggle hosts.

## Credentials and human gates

Presence-only checks found no `ARC_API_KEY`, Kaggle token environment variable, or Kaggle credential file. No value was printed or created.

- Authenticated online ARC scorecards are currently `BLOCKED_EXTERNAL`; anonymous/local modes remain available.
- Authenticated Kaggle status/upload validation is currently `BLOCKED_EXTERNAL`; offline packaging remains available.
- Accepting Kaggle rules, granting a public license, making an official submission, and merging remain owner-only actions.

## Exact principal commands

```powershell
git status --short --branch
git remote -v
git rev-parse HEAD
git log --all --decorate --oneline
git fsck --full
git ls-remote origin refs/heads/main
git ls-remote https://github.com/arcprize/ARC-AGI.git HEAD refs/heads/main
git ls-remote https://github.com/arcprize/ARC-AGI-3-Agents.git HEAD refs/heads/main
git ls-remote https://github.com/arcprize/ARC-AGI-3-Kaggle-Starter.git HEAD refs/heads/main
Get-FileHash -Algorithm SHA256 <controlling-file>
Get-CimInstance Win32_OperatingSystem
Get-CimInstance Win32_ComputerSystem
Get-CimInstance Win32_Processor
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader
python --version
python -m uv --version
python -m uv python install 3.12
'arc-agi==0.9.9' | python -m uv pip compile - --python 3.12 --resolution highest --no-header
Invoke-RestMethod https://pypi.org/pypi/arc-agi/json
Invoke-WebRequest <primary-source-url>
```

## Acceptance

- Repository and prior bootstrap identities: **PASS**
- Active/frozen authority distinction: **PASS**
- Implementation branch: **PASS**
- Upstream repository/package/docs lock: **PASS**
- Current action/game/recording/scoring/competition contract inspected: **PASS**
- Secrets committed or printed: **none observed**
- License automatically granted: **no**
- External credentials: **absent; bounded blockers recorded**

This report establishes source identity only. It is not evidence that an ARC3 agent works or scores.
