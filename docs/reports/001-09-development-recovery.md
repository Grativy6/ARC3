# Build 001 Stage 09 — Local-public development recovery

Status: **FAILED_INFRASTRUCTURE**

Evidence label: **local-public**

Claim boundary: **no development-recovery, action-efficiency, holdout, private-platform, or hidden-game performance claim**

## Result

The sole predeclared 96-cell Stage 09 attempt stopped after its first development-cell exposure.
The isolated worker returned exit 73 and the parent produced an authenticated
`terminal-cell-infrastructure-failure` receipt. The environment was never opened, no action was
submitted, 95 cells were never started, and the development recovery gate was not evaluated.

Stage 09 is therefore `FAILED_INFRASTRUCTURE`, not `FAILED_MECHANISM` and not `PASS`. The attempt
has consumed its one-run allowance and will not be resumed or rerun in Build 001.

## Exact cause

The parent launch receipt and authorization bound PID `21056`. The isolated interpreter that
executed the worker reported PID `23936`. A direct audit of all 19 authorization predicates found
exactly two false predicates:

- `launch_pid_matches_worker`;
- `authorization_pid_matches_worker`.

All schemas, self-hashes, command values, tokens, paths, process-creation tokens, worker-spec
hashes, and cross-receipt links passed. The Windows virtual-environment launcher created the
isolated interpreter as a distinct child process, so a parent receipt bound to the launcher PID
could not equal the worker's own PID. The invoked virtual-environment executable's PE metadata
identifies it as original filename `py.exe`, internal name `Python Launcher`. The worker failed
closed after its ten-second authorization
wait and wrote `launch-authorization-unavailable-or-invalid` before importing or opening the game
environment.

The Windows Job Object was assigned before resume, cleanup passed, and zero active assigned
processes remained. No stdout or stderr was emitted. This is a process-launch authorization defect
in the Stage 09 harness, not evidence about the production policy or any environment mechanic.

## Terminal authentication

The aggregate at
`C:/a/arc3-b001/artifacts/stage09/development-recovery-attempt-01.json` is 262,390 bytes with file
SHA-256 `5bb20928afe32e60449ae3ff6af3538e1a1b2c2722664f1f2dcfe8c1c77136a4` and artifact-core hash
`9c6eb08c33721b1b611a562e16bed57a8b7f7f5d654e18a7564e8e0efa71a6bd`.

The harness's strict `verify_complete_terminal` path correctly refused the aggregate because
`execution_complete` is false; that function authorizes only completed PASS or
FAILED_MECHANISM matrices. The same frozen harness's official terminal reconstruction loader then
recomputed the live preflight, every surviving receipt/finalization, the exposure prefix, resource
accounting, source/runtime/authority boundaries, and the complete fail-closed aggregate. It passed
exact reconstruction. A before/after hash inventory of all 16 evidence files was identical, so
validation changed no evidence bytes.

The durable terminal finalization is 4,114 bytes with file SHA-256
`6d50afa64110a8ccb350edafcaf5172ea5d4de61442ae2ea7085b26f82e84b4f`, internal hash
`4b44eae5243e58de170152144f0625acc6d335930ddbd449fd2bf1e54b5372c6`, and passing terminal
authority and overall-wall predicates. The complete 16-file evidence manifest is 671,876 bytes
with canonical manifest SHA-256
`3f709f3a376511025078aa6c89c3be9c6df0e6bb6fb5fab366759f2e89c7f39d`.

## Frozen identities and resources

- Production policy `P`: commit `d6d4bac1e33c9837856c08abcee61bcb14afd34e`, tree
  `dd8e82e4b34337a208110929e3f5f8079d1e0a18`, source SHA-256
  `8f0de1a9c2c88761951ba2bcd69f2612bedfa0cc4226f44f1ed272b54b9023a8`.
- Harness `H`: commit `10c2c7878a0a13ee6c7eb3c0c9aa36fc98fedefb`, tree
  `18a44bfb068f98fcfb9c0b674cc9c8824fc240cd`, clean detached checkout
  `C:/a/arc3-stage09-harness-10c2c78`.
- Frozen Build 000 comparator: commit `90ecf7267d5bb23d751d6f7ce3e8aa75f2f1a130`, tree
  `0cf6e00b2fcc399e7a99a62c20e91bb84d485f13`.
- Python 3.12.14 on Windows; AMD64 Family 23 Model 8; 12 logical CPUs; 17,124,503,552 bytes RAM;
  NVIDIA GeForce GTX 1660, 6,144 MiB, driver 560.94.
- Measured active wall: 43,763,174,300 ns; pre-receipt active wall: 43,714,027,800 ns; worker
  supervision wall: 10,219,918,300 ns; conservative cell admission charge: 150,000,000,000 ns.
- Child CPU and peak RSS are unavailable because the worker failed before the measured workload;
  resource measurement is explicitly incomplete.

The normalized effective bootstrap argv and the exact worker command are preserved in
`docs/evidence/001-09-development-recovery.json`. The outer shell did not produce a distinct
process-self receipt; the effective arguments remain independently bound by the embedded bootstrap
authority, terminal preflight, source mapping, and runtime receipt.

## Gate and continuation

No Stage 09 baseline or ablation comparison exists because no environment opened. Local-public
recovery is not observed. Stage 09 cannot satisfy the Stage 11 predicate requiring `PASS`.

The ten-game public holdout remains `SEALED_UNCONSUMED`: zero identities loaded, no manifest use as
gameplay metadata, zero gameplay events, and zero locally acquired assets. The failed development
launch does not weaken or reopen that gate.

Workflow 001 continues with every independent Stage 10 regression task that its frozen authority
permits. The Stage 09 launcher defect will be retained as a future repair burden, but no repair can
retroactively change or rerun this attempt.
