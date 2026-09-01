# Experiment 003s — Strongwiz clean-room ARC-AGI-3 result

Terminal disposition: **FAILED_INFRASTRUCTURE**

The single authorized measured session did not test Strongwiz's gameplay ability. The
context-isolated Codex operator selected a reversible `ACTION1` startup probe, but its 2,168-character
JSON response was truncated by the PTY input boundary before the bridge could parse it. No official
environment step occurred, no action was charged, and `GameState.WIN` was not observed. The one-shot
is consumed and was not rerun.

## Completion receipt

| Field | Observed value |
| --- | --- |
| Game ID | `ls20-9607627b` |
| Surface | `local-public`, development |
| Final environment state | `NOT_FINISHED` |
| `levels_completed` | 0 |
| `win_levels` | 7 |
| Environment actions | 0 |
| Resets | 0 |
| Score | 0.0 |
| Official RHAE | null; not returned by the authoritative scorecard |
| Measured wall time | 81.25 seconds |
| `GameState.WIN` observed | No |
| Completion genuinely observed | No |
| Raw evidence path | `artifacts/strongwiz-clean-room/runs/strongwiz-ls20-seed0-20260901T100522Z` |
| Raw replay path | `artifacts/strongwiz-clean-room/runs/strongwiz-ls20-seed0-20260901T100522Z/official-recordings/d30053b2-103a-4c4d-8584-e062ea865230/ls20-9607627b-f7c50f91-b2fb-49da-9b31-4ec405c798c5.jsonl` |
| Tracked receipt | `docs/evidence/strongwiz-clean-room-result.v0.1.json` |

The local pinned `arc-agi==0.9.9` ScorecardManager verified its own zero-action scorecard. The
overall result remains community-style and self-reported because the hosted Codex model/runtime is
not artifact-hash-bound. This is not a Kaggle, official, hidden-game, autonomous-offline-agent, or
Strongwiz performance result.

## What ran

- Exact comparison base: Build 002 merge `bea1eac99cb0f1b351526b1dc487d132ba1d40ef`.
- Frozen pre-play implementation: `54048a89fc935a2764b643398ce8c46d23e232e8`.
- Strongwiz pin: `6944642da7f4f3e6428a597587038c3b365074a5`, tree
  `f9097631fa5c6fb1dcce7756baaa290d76d22d92`.
- Strongwiz slice: typed contracts and identities, router and two-speed cadence policies,
  PEA/PECAN lab evaluation, and the serial SQLite receipt ledger.
- Not exercised: the full `ReasoningSession`, `GrantRegistry`, `ExecutionCoordinator`, `FactStore`,
  `MechanicLedger`, or `GoalGraph` runtime.
- No Hearthline repository, Hearthline runtime, prior gameplay trace, game source, or holdout was
  used. Codex was the declared external action-choice provider.

One anonymous acquisition session materialized the official public asset without exposing its frame
to the operator. Exactly one measured session then ran the environment locally with Python socket
entry points denied; the guard recorded zero attempts. The inherited ten-game public holdout stayed
sealed and unconsumed.

## Failure localization

The measured operator made exactly one stdin write:

- JSON body: 2,168 ASCII characters;
- transmitted input: 2,169 bytes, including exactly one trailing LF;
- chunk: `642efd`;
- the process closed with exit code 1 after `PolicyError: operator response is not valid JSON`;
- the retained PTY echo stopped inside a `competing_predictions` string;
- bridge receipt: `environment_actions=0`, `unknown_environment_effect=false`.

After closing the measurement, a no-ARC synthetic test exercised the same PTY plus `write_stdin`
path. A dummy `readline()` consumer received only 511 characters, including a newline, from an exact
2,170-byte ASCII line. Its received-prefix SHA-256 was
`485ccd0e2eed21a4b1efcf30895a1e6d18789946a0dda924cf4eca14b37b4c0e`.

That reproduces the failure at the transport boundary: the bridge assumed one multi-kilobyte JSON
response could cross a line-oriented PTY atomically. The response never reached Strongwiz proposal
validation, authorization, action-submission marking, or the single environment writer. Therefore
the appropriate result is `FAILED_INFRASTRUCTURE`, not `FAILED_MECHANISM`, `PARTIAL`, or a measured
Strongwiz score.

The smallest reopening handle is to replace this path with a length-prefixed, chunked, or
file-backed authenticated response channel and prove inputs above 511 bytes before authorizing a new
experiment. This run itself remains frozen.

## Evidence identities

- Protocol SHA-256:
  `9a75b29a73d4b0cf4549c2d083838c27cf7a7b90cc532a376a55f6bcb3d8df56`
- Result internal SHA-256:
  `3f25e959ef5f7d54fa486f6022f78311e80bcfc825ee1c551f4f5a182a4ec68c`
- Result file SHA-256:
  `3e86e5ae2c7b897f3662613a5e2fc38c62ea4e98d92bbdcc933ae81f0a31c678`
- Operator receipt internal SHA-256:
  `22e160921178766848627a6b20dd1c2fe7bcea8d8fd3782e5cb97afdb898be88`
- Strongwiz ledger: 4 receipts; head
  `13bdafcd785f3e122ef3c464938de23d437c8734937907aa2eca8ff5f5f7b650`
- ARC trace: 2 events; file SHA-256
  `83e34b387f2c0e075268b00fc8621efdec00a1799d2f302391fcbe663476867a`
- Referenced frame blob SHA-256:
  `f530cf6adb4a6d0fe87baa072ecf62be621169f9ef3b0baf09539904c5f4220f`
- Official recording SHA-256:
  `25c36d8e0e750a49e39ef9e7bd9aee2bd412d78b1b5510c7c3bd13a8cd4ad770`
- Exposure ledger: exactly four events; file SHA-256
  `966ff4141155292f94479c78a95abde2c61c5bf91a413a8b1e477682d9a9b4ba`

Raw frames and replay data remain ignored repository-local artifacts. The tracked receipt publishes
their paths and content hashes without turning a public-development observation into an input for a
later clean-room run.

## Verification before play

- 118 Strongwiz upstream tests passed.
- 63 affected adapter/bridge tests passed.
- 9 secret-scanner tests passed.
- Ruff lint and formatting passed.
- Strict mypy passed over the eight changed first-party files.
- Protocol, YAML, JSON, exact-source pin, archive, license, and source-snapshot checks passed.
- The independent pre-play bridge audit found no remaining P0/P1 issue in the declared boundary.

A broader inherited Build 002 wrapper suite was not clean before play; the Strongwiz branch did not
modify the implicated `agent/` or `src/arc3/policy` paths relative to its Build 002 base. That
pre-existing residual is not promoted into or hidden by this experiment's affected-suite result.
