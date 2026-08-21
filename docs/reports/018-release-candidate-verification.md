# Stage 18 — Clean-clone release-candidate verification

- **Stage status:** FAILED_MECHANISM
- **Release infrastructure:** PASS after repair
- **Measured surfaces:** synthetic; local-public
- **Claim boundary:** NO_GENERALIZATION_CLAIM
- **Candidate source commit:** `90ecf7267d5bb23d751d6f7ce3e8aa75f2f1a130`
- **Candidate source tree:** `0cf6e00b2fcc399e7a99a62c20e91bb84d485f13`
- **CI repair descendant:** `67e4b0ed4be8dbe4e3ea5a0dbc7c20ef9b934c4e`
- **Initial failed-run evidence:** `docs/evidence/018-release-candidate-initial-failure.json`
- **Acceptance evidence:** `docs/evidence/018-release-candidate-acceptance.json`

## Result

A fresh remote clone at the exact candidate commit was bootstrapped with the frozen lock and only
documented repository commands. The repaired verifier passed dependency-lock validation, Ruff
lint and format, strict mypy, the complete 423-test suite, 13 focused replay/tamper tests, exact
synthetic benchmark reproduction, two deterministic offline package builds, competition-integrity
scanning, source identity, artifact sealing, and generated-log secret scanning.

The stage remains `FAILED_MECHANISM`, not PASS, because the available `local-public` smoke
evaluation is `PARTIAL`: the full policy completed no levels and timed out in all six runs. The
release verifier preserves this performance failure independently of the clean-clone
infrastructure result. A partial evaluation is not promoted to success merely because its
artifacts validate.

No online evaluation, Kaggle authentication, terms acceptance, upload, official submission,
private gateway validation, license grant, release, or merge occurred.

## Clean source and isolated state

The authoritative clone was created at `C:\a\arc3-s18-70ed0f3`, then detached at
`90ecf7267d5bb23d751d6f7ce3e8aa75f2f1a130`. Its `.venv` was created from `uv.lock` with uv
0.12.5, CPython 3.12.14, offline resolution, and 61 synchronized packages. `git status` remained
clean before and after verification.

Sealed logs, evaluations, package candidates, integrity receipts, and the final release receipt
remain under the ignored in-clone evidence root. Writable HOME, USERPROFILE, TEMP, coverage,
Hypothesis, Ruff, mypy, uv cache, and pytest basetemp state use a separate fresh short path,
`C:\a\s18-t-90ecf72`. That transient tree is explicitly unsealed. This separation prevents
Windows path expansion and prevents test fixtures from inheriting the evidence root's Git ignore
scope.

Subprocesses receive a strict environment allowlist and isolated homes/caches. Credential-like
values are removed; generated stdout/stderr are redacted before persistence, and any redaction or
remaining secret pattern fails the required log scan. Dependency-lock validation runs offline.

## Verification matrix

| Check | Result | Exact bounded evidence |
|---|---|---|
| Candidate/interpreter source | PASS | exact commit/tree; clone-local `.venv`; isolated import origin |
| Dependency lock | PASS | `uv lock --check --offline` |
| Ruff lint | PASS | complete repository, no cache |
| Ruff format | PASS | complete repository, no cache |
| Strict typing | PASS | `src`, `agent`, and `scripts`; 142 source files |
| Complete tests | PASS | 423 passed in 417.05 seconds; 80% measured coverage |
| Replay/tamper subset | PASS | 13 passed in 7.79 seconds |
| Frozen synthetic benchmark | PASS | 10/10 terminal runs; exact Stage 13 semantic projection |
| Synthetic artifact verification | PASS | complete manifest/hash/replay checks |
| Offline package A/B | PASS | both `PACKAGING_PASS`; byte-identical candidate and receipt |
| Competition integrity | PASS | source, archive, public-ID, hosted-client, secret, and dependency checks |
| Public inventory | PASS | three frozen smoke games available; game source not semantically inspected |
| Public smoke policy | FAILED_MECHANISM | `local-public`; full 0/6 successful runs, six timeouts, zero levels |
| Public artifact verification | PASS | partial result retained and structurally/hash verified |
| Repository clean after | PASS | exact candidate identity unchanged |
| Generated-log secret scan | PASS | zero redactions and zero retained findings |

The acceptance run started at `2026-08-21T13:11:04.771199Z` and completed at
`2026-08-21T13:35:46.189811Z`. Its release receipt has file SHA-256
`sha256:ae571ae99b2746bfe17f3e8ea790707810522f2f462d983a9c2726bb57dcc7a5` and
canonical self SHA-256
`sha256:31ca85d0fa11de07372b740fc73dd3d9976e71808f9c84cb454710eaa92d6e91`.
The curated raw evidence file has SHA-256
`sha256:66e980f95e5505ae166a76d6339dbaa0b9ee9cb4eca693c862e8f4409c7b2aa6`.
The sealed set contains 1,895 files and 208,702,479 bytes with set SHA-256
`sha256:00e343694d460b5a751fd3812ace699825967622d52cd18cf91ba994156969e0`.
Its `complete=false` field records the required public-policy mechanism failure; sealing itself
finished and the partial public artifacts passed independent verification.

## Deterministic benchmark and package

The Stage 18 synthetic command reran the frozen Stage 13 `smoke` configuration with agents
`random,cycle,trace,novelty,full`, seeds 7 and 11, 16 actions, two resets, and 60 seconds per run.
All ten runs completed, and the semantic projection matched the committed expectation exactly.
Timestamps, host paths, process durations, and coverage percentages were excluded only where the
plan declared them nondeterministic.

Two candidate builds from the clean source returned `PACKAGING_PASS`. Their build receipts were
byte-identical with file SHA-256
`sha256:c092a647b894e0f640db0bf9d3517641adf830fca883becb56d2de1d7be163f6`.
Both 550,068-byte candidate archives have SHA-256
`sha256:5d64883392f8b1506314e64442702f51ecf0b52e54e190277dad52f07e6cd3f7`.
The production package remained CPU-only and offline; the sandbox observed no non-loopback
network attempt and created a pinned-public-schema Parquet output.

## Local-public smoke

The smoke used the three predeclared local public assets, policies B0 random, B1 cycle, and B4
full, seeds 7 and 11, an 80-action/8-reset budget, and a 120-second per-run wall limit. There were
18 expected terminal results. Random and cycle each completed all six harness runs but no level;
full timed out in all six, completed no level, and preserved its partial traces. Mean score was
0.0 for every policy. The public holdout was not acquired, opened, or consumed.

Official RHAE remains unmeasured/null for these local runs; completion, environment-action
counts, and local scorecard values are reported separately and are not RHAE. The verifier used
only asset metadata and content identities for availability and did not inspect game source to
infer solutions.

This is `local-public` evidence labeled `MECHANISM_NOT_OBSERVED`. It is consistent with, but does
not replace, Stage 15's larger negative public development result. It is not evidence about hidden
games or official scoring.

## Preserved failed runs and repairs

The first sealed verifier run at `468d102ac609e99d85d333ffc642ae2a87463672` is retained as a
failed result. It passed lock, lint, formatting, typing, replay, synthetic reproduction, package
builds, and integrity, but the complete suite ended 417 passed / five failed. Two generated paths
were 261 and 263 characters; two integrity fixtures inherited `artifacts/**` ignore scope; and one
nested test assumed ambient uv discovery. Its public smoke independently remained partial.

Commit `70ed0f3` introduced a required fresh out-of-tree transient root and a hermetic uv contract
test. Commit `90ecf72` allowed partial public artifacts to be verified without treating the policy
failure as a successful result. Remote CI then exposed a separate shallow-clone ancestry failure:
the exact frozen benchmark assertion correctly refused to verify absent history. Commit `67e4b0e`
set `actions/checkout` to full history rather than weakening or auto-fetching inside the verifier.

Both push and PR Actions runs at `67e4b0e` passed Ubuntu and Windows, including lock, lint,
format, strict typing, the complete suite with coverage, and runtime doctor:

- push run `32485636282`;
- PR run `32485640575`.

The earlier failed/cancelled runs remain visible and are not relabeled.

## Reproduction commands

```text
git clone --branch build/000-arc3-end-to-end --single-branch https://github.com/Grativy6/ARC3.git C:\a\arc3-s18-70ed0f3
git -C C:\a\arc3-s18-70ed0f3 checkout 90ecf7267d5bb23d751d6f7ce3e8aa75f2f1a130
C:\Users\cdpan\AppData\Roaming\Python\Python313\Scripts\uv.exe sync --directory C:\a\arc3-s18-70ed0f3 --frozen --all-extras --dev --python 3.12.14 --offline --link-mode copy
C:\a\arc3-s18-70ed0f3\.venv\Scripts\python.exe C:\a\arc3-s18-70ed0f3\scripts\release_candidate_verifier.py --root C:\a\arc3-s18-70ed0f3 --output-root artifacts\stage18\rc-90ecf72 --transient-root C:\a\s18-t-90ecf72 --expected-commit 90ecf7267d5bb23d751d6f7ce3e8aa75f2f1a130 --official-environments-dir C:\a\arc3-s15-6a0f6e5\artifacts\stage15\public-environments --uv-executable C:\Users\cdpan\AppData\Roaming\Python\Python313\Scripts\uv.exe
```

The exact local public assets are separately hash-bound in the Stage 15 manifest. A reviewer who
does not possess those already acquired public assets can omit `--official-environments-dir`; the
verifier will record the optional public smoke as `BLOCKED_EXTERNAL` without acquiring or opening
games. The synthetic, package, and integrity checks remain independently reproducible.

## Boundaries carried forward

- Stage 18 proves repository-contained reproducibility for the checks that passed; it does not
  turn failed public gameplay into a release success.
- Palette/action-remap robustness remains failed, and one rule-change case remains unexercised.
- The one-shot public holdout remains sealed.
- Exact private Kaggle inputs, gateway, scorer, and full 110-game runtime remain unavailable.
- The complete package remains a no-submit offline candidate.
- Nothing in this stage proves hidden-game generalization, PAL, AGI, consciousness, or a general
  theory of intelligence.

Christopher D. Pang remains the project author and steward. AI systems were used as engineering
tools and assistants, not as co-authors, owners, or independent authorities.
