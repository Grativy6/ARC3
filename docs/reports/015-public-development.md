# Stage 15 — Public-game development

- **Stage status:** PASS
- **Evaluation status:** PARTIAL
- **Measured surface:** local-public
- **Acceptance outcome:** MECHANISM_NOT_OBSERVED
- **Claim boundary:** NO_GENERALIZATION_CLAIM
- **Measured commit:** `6a0f6e5b9cf076f7d755675ece0fa46379202161`
- **Primary evidence:** `docs/evidence/015-public-development-acceptance.json`

## Result

The frozen FULL/COMPETITION policy did not improve over the pinned baselines on the official
public smoke or development partitions. All 30 FULL runs reached the 120-second worker limit:
six smoke runs after 116 total environment actions and 24 development runs after 344 total
environment actions. FULL completed no levels and returned no official scorecard before those
timeouts. The honest acceptance outcome is `MECHANISM_NOT_OBSERVED`.

The Stage 15 workflow itself is PASS because the declared smoke and development matrices are
complete as terminal evidence, their manifests and 13,927 hash-bound artifacts verify, the
negative result is preserved, and the one-shot public holdout gate remained closed. The two
evaluation manifests remain PARTIAL because timeout is a failed run outcome, not a success.

## Frozen protocol

The evaluation used a clean detached worktree at the measured commit, Python 3.12.14,
`arc-agi==0.9.9`, `arcengine==0.9.3`, spawned worker isolation, and the pinned local official
`ScorecardManager`. Each policy received 80 environment actions, eight resets, 120 wall-clock
seconds per run, and seeds 7 and 11. Policy execution was offline. No game source was read to
infer solutions, no game-specific rule or action sequence was added, and public gameplay did not
change the frozen policy.

The host reported 12 logical CPUs and `AMD64 Family 23 Model 8 Stepping 2, AuthenticAMD` on
`win32`. The scorer exposes no standalone official RHAE field for these local runs, so official
RHAE remains null.

Online metadata revalidation discovered the same 25 public identities as the committed manifest:
three smoke, 12 development, and ten public-holdout games, with no missing, extra, or renamed
identity. Revalidation opened no gameplay. Only the 15 smoke/development assets were acquired;
the ten holdout assets remain absent.

## Smoke partition

| Policy | Runs | Terminal success | Timeout/fault | Actions | Levels | Mean score |
|---|---:|---:|---:|---:|---:|---:|
| B0 random | 6 | 6 | 0 | 480 | 0 | 0.0 |
| B1 cycle | 6 | 6 | 0 | 480 | 0 | 0.0 |
| B2 novelty | 6 | 6 | 0 | 480 | 0 | 0.0 |
| B3 trace | 6 | 6 | 0 | 480 | 0 | 0.0 |
| B4 FULL | 6 | 0 | 6 | 116 | 0 | 0.0 |

Here, “terminal success” means the worker returned a valid terminal run receipt; it does not mean
that the game was completed. None of the 30 smoke runs completed a level. The sealed evaluation
contains 30 run receipts and 2,579 verified artifacts.

## Development partition

| Policy | Runs | Terminal success | Timeout/fault | Actions | Levels | Mean score |
|---|---:|---:|---:|---:|---:|---:|
| B0 random | 24 | 24 | 0 | 1,920 | 1 | 0.016196954972465177 |
| B1 cycle | 24 | 24 | 0 | 1,920 | 0 | 0.0 |
| B2 novelty | 24 | 24 | 0 | 1,920 | 0 | 0.0 |
| B3 trace | 24 | 24 | 0 | 1,920 | 0 | 0.0 |
| B4 FULL | 24 | 0 | 24 | 344 | 0 | 0.0 |

The sole nonzero result was B0 random run `r11l-495a7899-B0-random-seed-7`, which completed
one level in 80 budgeted environment actions and received score `0.38872691933916426` from the
pinned local official scorecard. Averaged across B0's 24 development runs, that is
`0.016196954972465177`. This isolated baseline event is not a benchmark win or evidence of
generalization. No policy completed a public game.

The development seal verifies 120 run receipts and 11,348 hash-bound artifacts. FULL's 24
timeouts occurred after 8–20 environment actions each. Its mean throughput was therefore about
14.3 actions per 120-second worker envelope, substantially below the simple baselines, which each
returned all 80 actions. This identifies runtime as a measured competition blocker rather than an
adapter or action-validity failure.

## Representative traces

The scoring B0 receipt is
`sha256:3e3e06967309828df54279a357acdb3eb023641ed04aa9953871e0dbb2309961`;
its replay-verified trace manifest is
`sha256:6b53c6eece17a55b9d049741ab734c8db9ec4028189c11fcf57ccdafda458846`.

A representative FULL failure, `ar25-0c556536-B4-full-seed-7`, timed out after 19 actions and
120.110601900029 seconds. It retained 759 immutable trace events in 1,679,940 bytes, replayed
successfully, and ended at trace-manifest hash
`sha256:be7f3ac2fceab90248b8dbb507a4a4dd172e58623cfb3a18df1e5bece7907dbd`.
The trace contains observation, candidate, selected-action, returned-consequence, retrodiction,
goal, model-promotion, and simulation receipts. The failure therefore points to excessive
integrated computation and persistence cost, not missing trace provenance.

## Holdout protocol

The public-holdout command was invoked once at the frozen milestone with the sealed development
manifest. It rejected the request before acquisition or gameplay because the development
evidence was not passing. The CLI returned exit 1 with message `sealed development evidence is
not a passing development run`; no holdout directory was created, the exposure ledger contains
zero holdout events, and the ten holdout games remain unconsumed. There is no public-holdout
result to report.

## Identities and artifact seals

```text
public partition manifest:     sha256:682d5891c2aface54803d9bd1173c55ed21e89856e13b8a478fb9276ee963f2f
first-party source:            sha256:19a02698148e935197326842b91472db0098c37289e3196994e72f08ffc31eba
smoke semantic manifest:       sha256:84cbc4da9dbc4ba58d883ac336e4eef37cc9a5be63d2c0e343fae8f3c5de7747
smoke manifest file:           sha256:41e347e2146f37046d9e608ace8d768a70d74e2b03ca276832e1238ca17cb8d7
development semantic manifest: sha256:de4a67ed3be6e7c929ec719f1ae1c6d27571e6dfa8f246d040501208350fa45c
development manifest file:     sha256:156b1f1bbd185d336068d5dc3b3c6b2241ff651c60107e9694df995eac85a592
exposure ledger after Stage 15: sha256:cd9af42ed3a5ef9fa0dc201ddb10e32d2bcccee9df729aa0c7d53077c04c9ad4
exposure ledger tail event:     sha256:c8c1f9cc5aa1c6e099e7c81abc0ef2848936f3411a77a870d1fe940c2d1060d4
```

The exposure ledger contains 330 hash-linked events ending at sequence 329.

High-volume raw traces, checkpoints, local official assets, manifests, scorecards, and failure
outputs remain under `C:\a\arc3-s15-6a0f6e5\artifacts\stage15`. They total 943,392,258 bytes
across the two sealed evaluation directories alone. They are intentionally not committed; the
compact acceptance evidence records their independently verified counts, identities, and hashes.

## Commands

```text
.venv\Scripts\python.exe -m scripts.evaluate_public --partition smoke --agents random,cycle,novelty,trace,full --seeds 7,11 --max-actions 80 --max-resets 8 --timeout-seconds 120 --frozen-commit 6a0f6e5b9cf076f7d755675ece0fa46379202161 --evaluation-id stage15-smoke-6a0f6e5b9cf0 --milestone-id build-000-stage15-v0.1 --acquire-missing
.venv\Scripts\python.exe -m scripts.evaluate_public --verify artifacts\stage15\evaluations\stage15-smoke-6a0f6e5b9cf0
.venv\Scripts\python.exe -m scripts.evaluate_public --partition development --agents random,cycle,novelty,trace,full --seeds 7,11 --max-actions 80 --max-resets 8 --timeout-seconds 120 --frozen-commit 6a0f6e5b9cf076f7d755675ece0fa46379202161 --evaluation-id stage15-development-6a0f6e5b9cf0 --milestone-id build-000-stage15-v0.1 --acquire-missing
.venv\Scripts\python.exe -m scripts.evaluate_public --verify artifacts\stage15\evaluations\stage15-development-6a0f6e5b9cf0
.venv\Scripts\python.exe -m scripts.evaluate_public --inventory-only --revalidate-online-metadata
.venv\Scripts\python.exe -m scripts.evaluate_public --partition public-holdout --agents random,cycle,novelty,trace,full --seeds 7,11 --max-actions 80 --max-resets 8 --timeout-seconds 120 --frozen-commit 6a0f6e5b9cf076f7d755675ece0fa46379202161 --evaluation-id stage15-public-holdout-6a0f6e5b9cf0 --milestone-id build-000-stage15-v0.1 --allow-public-holdout --sealed-development-manifest artifacts\stage15\evaluations\stage15-development-6a0f6e5b9cf0\manifest.json
```

The commands ran from `C:\a\arc3-s15-6a0f6e5` with `PYTHONPATH` bound to that clean worktree and
the absolute Python interpreter from the repository environment.

## Verification

```text
smoke seal: PASS, 30 runs, 2,579 artifacts, 0 verification errors
development seal: PASS, 120 runs, 11,348 artifacts, 0 verification errors
online metadata identity: PASS, 25/25, gameplay not opened
holdout nonconsumption: PASS, 0 ledger events, 0 acquired holdout games
frozen-commit CI: PASS, Ubuntu and Windows, runs 32471135774 and 32471131148
production public-ID scan: PASS at frozen commit
```

## Preserved limits

- FULL timed out in every public run. Stage 16 must measure and bound perception, hypothesis,
  simulation, checkpoint, and trace costs before this can be considered competition-viable.
- Successful local runs were scored by the pinned official local scorer. Timed-out FULL runs
  returned no official scorecard and are not called verified scores.
- The public holdout was not opened, so there is no `PUBLIC_HOLDOUT_IMPROVEMENT` claim.
- No `online-public`, `Kaggle-public`, `semi-private`, or `official-private` result exists.
- This result does not establish hidden-game generalization, PAL, AGI, consciousness, or a
  general theory of intelligence.
