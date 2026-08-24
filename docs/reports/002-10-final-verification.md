# Build 002 Stage 10 — Final verification and blocked-result seal

## Result

Build 002 is `PARTIAL`. The exact competition adapter and achievable local package, profile,
lifecycle, replay, integrity, and structural-output work are complete. Exact-head hosted terminal
checks remain pending, and exact public and official evaluation remains `BLOCKED_EXTERNAL`.

No scorecard was opened, no environment was made, no gameplay action occurred, no Kaggle
credential was used, and no upload or submission was performed.

## Frozen source

- Branch: `build/002-kaggle-competition-adapter`
- Implementation commit: `753b0e007222a973a2c8a6d7ce14a395135d3c5f`
- Implementation tree: `d07e72716a1f918ed04a6892adb1e3f46259e345`
- Base: `a1931c673b90923e1af78127229667544802a096`
- Build 001 final: `8a42e43c96ac1edada21725746cdedcee24e68f9`
- Build 001 ancestry: `PASS`
- Build 001 tracked evidence diff from `origin/main`: empty
- Runtime configuration:
  `sha256:3b56018560e4bde4005da4c7f30bc97a4180179d4a8ce1c0959cc0c76651694a`
- Upstream lock:
  `sha256:fb3acb1e375dddaaa02e38dc39cd3a0cde7fe95045d4dca34d976d29e0f56c68`

The later documentation commit records and reports this frozen implementation; it does not
silently change the packaged source identity.

## Verification matrix

| Surface | Result |
|---|---|
| explicit research/competition modes | `PASS` |
| official `MyAgent` interface | `PASS` |
| fixed-action grant boundary | `PASS` |
| governor, legal actions, reserve, fallback, opportunity cost | `PASS` |
| one scorecard / one make / level resets / no game resets | `PASS` |
| deterministic stop and replay | `PASS` |
| failure and interruption receipts | `PASS` |
| static game-ID prohibition | `PASS` |
| secret scan | `PASS`, zero findings |
| synthetic profile | `PASS` |
| package manifest and SBOM | `PASS` |
| native Linux exact-requirement cold start | `PASS` |
| generated notebook execution | `PASS` on safe fixture |
| pinned-public Parquet structure | `PASS` |
| exact Kaggle framework/gateway/scorer parity | `BLOCKED_EXTERNAL` |
| authorized ten-game public run | `BLOCKED_EXTERNAL`, unconsumed |
| official or local-public RHAE | `NOT_MEASURED` |

## Repository checks

- Clean-clone full suite at `9d395d51fd3ae9ca35df90a2ddbccbd0338dade4`:
  `1464 passed, 21 skipped`, 79 percent coverage, 2,497.97 seconds.
- The `0385d238` repair narrows Build 001's package-only projection by excluding the Build 002
  holdout runner's protected manifest; ordinary CI still tests that runner.
- The later `753b0e0` repair makes packaged startup call `configure_tournament` before agent
  construction. It excludes the exact pinned POSIX framework integration test only from Build
  001's protected package-only guard; ordinary CI retains and exercises that integration test.
- Ruff lint: `PASS`.
- Ruff format check: `PASS`, 330 files.
- strict mypy: `PASS`, 188 source files.
- Clean-clone focused regression for the `0385d238` repair: `2 passed`.
- Final exact-head hosted CI conclusions are bound in the validation ledger and draft PR checks.

## Package evidence

The clean-source package producer receipt is
`sha256:8afaf2f16cf9f4a7c7825718b14427b5afdcb239d877523d22e70f617ed46358`;
its serialized file hash is
`sha256:be23ee24c614229b2f940c112fb916f12b63cbdc700c8bcafc1569024d008bc5`.
The package manifest is
`sha256:29f5b430ff3be418bd8c4922939aa9134f823864983abf320601e1a46ca89388`,
the SBOM is
`sha256:e1d4836e974f22cf8821ddc46909edc1bce0ed2146a9ad4116550d11a130d0ed`,
and clean integrity-A is serialized as
`sha256:9287f22b9a6d63cd8dd3540661f28b2115e9935488d24c38aeb58767c7ad1b3b`
with producer receipt
`sha256:42aa847bc4443f100be9163b9bb9746ed30dc1e5d79692d20d7d1cfbc43da588`.
The candidate, notebook, payload, and Parquet hashes match between local packaging and the native
Linux CI artifact.

- candidate:
  `sha256:adcd92352f55a0109c0898fe14b531e8780f02dc9b68489af449c1b8b8c16d9a`,
  838,438 bytes;
- notebook:
  `sha256:adbb75d09806da104a5d3bfbe41e55d809ec2bb91514aafa6176c2469f30c81e`,
  548,193 bytes;
- first-party payload:
  `sha256:726e595523a9b737a3b000b6d4d088a8e9289c1e6fd1da03297b79876311356f`.

Native Linux cold-start receipt:

- file SHA-256:
  `d04dcef55e36a9ee32a6f4153d89efc6b61560962b9931b031a70632a4ff4ecc`;
- CPython `3.12.14`, Linux x86_64;
- 31 wheels, 45,073,152 bytes;
- isolated `pip --no-index --no-deps --require-hashes`;
- no host `.pth` bridge or foreign site paths;
- 12.728529202-second wall time;
- 132,288,512-byte peak memory;
- exact four generated notebook code cells executed;
- zero observed non-loopback Python socket attempts.

The fixture does not prove Kaggle's private gateway, framework, evaluator, or OS-level network
containment.

## Profile evidence

The synthetic competition profile is `PASS`:

- producer receipt:
  `sha256:3f03b17ed639a6e7c6762254a1cba9fdfabb45aaa6ac42f9eb72e7f7b0048714`;
- serialized file:
  `sha256:ed2d4c336017551cb4b99e3fc2bc71eedf66b87683811d0d4a00056e0f84fb15`;
- 80 actions;
- 39.6246924-second wall time;
- 321,466,368-byte peak RSS;
- 3.3508976999946753-second maximum production controller cycle;
- 11/11 fault cases verified;
- 12/12 robustness cases verified;
- deterministic replay and pinned regression verified;
- claim boundary: `NO_GENERALIZATION_CLAIM`.

## Frozen preflight

The exact production preflight stopped before arming:

- status: `BLOCKED_EXTERNAL`;
- producer receipt:
  `sha256:bb37fa65c0bf470ba54b2e6b82c14c01cafc8045d9697b1ac82893b2a241b189`;
- serialized file:
  `sha256:15d748c6954705cabdfc37d0f993ec3e5d352558fb0741d7bd7cbd472e24e82e`;
- request:
  `sha256:b842e2cee086ec2833bdd7c3453482f88c8a889b1e474ca992124e8a33033160`;
- hashed error message:
  `sha256:ba7ce61033f638929402dad230d898e52fb6ddbdf1471b4951fe49c525e8bd86`;
- source commit/tree matched;
- scorecards opened: `0`;
- environment makes: `0`;
- gameplay actions: `0`;
- holdout runs started: `0/1`;
- authority consumed: `false`.

No public-run metric or gameplay-failure classification exists. The pre-run blocker is classified
as `platform`; that is not a per-environment gameplay failure.

The ledger preserves a superseded temporary A/B-layout request and a corrected-path
`FAILED_PREFLIGHT` caused by reusing a non-fresh output directory. The final retained-path request
used a fresh output directory and is the receipt cited above. All three attempts remained
launch-free, with zero public interaction and no canonical one-shot state.

## Hosted verification and PR

- Build 002 native Linux package/cold-start run:
  <https://github.com/Grativy6/ARC3/actions/runs/32708504639> — `PASS`.
- Exact-head ARC3 CI:
  <https://github.com/Grativy6/ARC3/actions/runs/32708504627> — `PASS`; Ubuntu `1476 passed, 10
  skipped`, Windows `1466 passed, 20 skipped`, plus lint, format, strict typing, and runtime doctor.
- Exact-head Build 001 package-only CI:
  <https://github.com/Grativy6/ARC3/actions/runs/32708504623> — `PASS`; both platforms retained the
  deliberate `BLOCKED_EXTERNAL` private-surface boundary. Receipt file SHA-256 values were
  `56e7cb6a4e9b882cb7fe8eb0310ac9a75fb968352b807655dcc7671766611813` on Ubuntu and
  `c053e798a9c368cf8607b9a8953e1369b76f855d532dd8e3f3d7d7114207e054` on Windows.
- Draft PR: <https://github.com/Grativy6/ARC3/pull/6>.
- PR state: draft, open, unmerged.

Stage 10 is `PASS` on the implementation freeze. The final documentation commit cannot contain
its own SHA or later CI conclusion; the pushed draft PR is the external receipt for that final
documentation-only head.

## Claim boundary

Build 002 does not prove gameplay recovery, public-set generalization, Kaggle compatibility,
official scoring, AGI, consciousness, or PAL. Build 001 remains unchanged `PARTIAL`.
