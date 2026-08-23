# Build 001 Stage 10 — Robustness and regression

Status: **FAILED_INFRASTRUCTURE**

Evidence label: **synthetic**

Claim boundary: **no robustness, regression, ablation, resource, gameplay, holdout,
private-platform, or hidden-game performance claim**

## Result

The sole predeclared Stage 10 attempt stopped in its first suite. The integrity child was launched,
authorized inside the Windows Job Object, and denied network access successfully, but it returned
exit 2 before producing its declared artifact. Eight later suites were never started. Stage 10 is
therefore `FAILED_INFRASTRUCTURE`, not `FAILED_MECHANISM` and not `PASS`; its one-run allowance is
consumed and the attempt will not be resumed or rerun.

No synthetic regression floor, component ablation, rule-change result, or resource profile was
measured in this attempt. Build 000's synthetic results remain historical comparators, not Build
001 measurements.

## Exact cause

The frozen suite command invoked `scripts/check_competition_integrity.py --package-only` without
the scanner's required `--expected-commit 88720037361822e1202a6b007678726d4e114b72`
argument. The child emitted exactly:

```text
integrity scan refused: --package-only requires --expected-commit
```

It returned 2, so no `integrity.json` or composite receipt was created. This is a frozen plan and
preflight coverage defect. It is not a production-policy integrity finding: the scanner did not
run far enough to inspect the declared candidate. The network receipt recorded zero connection,
DNS, send, or send-to attempts.

The preflight's static predicates established that paths and source identities were well formed,
but did not validate that the integrity child's argument contract matched the current scanner.
That missing cross-check is preserved as a future harness repair; it cannot authorize a rerun.

## Terminal authentication

The result at
`C:/a/arc3-b001/artifacts/stage10/robustness-regression-attempt-01.json` is 50,168 bytes with file
SHA-256 `e6e668c57b88f9c7a5d9efe74050e24cf4746a6875e3f74b10c7929183ed982f` and artifact-core hash
`2ecfd9bd24c2cd1e446384e66b3378c8dc6fb0c0b19ecabc133abf2eb8bd2d3d`.
Its invocation ledger is 3,863 bytes at SHA-256
`9bb13fdddc8c31a2bc81b56102dddb57207ec546fe1c525e7b5947c046a68f07`.

A bounded read-only reconstruction validated the exact preflight, plan, source/runtime identity,
ledger chain, launch and authorization receipts, process-creation token, cleanup, network receipt,
stdout/stderr hashes, parent receipt, and recomputed suite validation. It admitted `null` artifact
and composite receipts only for the two exact declared paths that do not exist; the recomputed
validation had to remain `FAILED_INFRASTRUCTURE`, and the reconstructed result had to equal the
original bytes. The complete nine-file result graph totals 90,692 bytes at canonical manifest
SHA-256 `f79b2567fa2acc6e7d813a5dfd2b3831673032de9f9b118dcccdf443b8b79143`
and was unchanged before and after validation.

The frozen strict resume verifier refused the same graph because it required a file receipt even
when the declared artifact was absent precisely because the suite failed before writing it. That
secondary read-only verifier defect is preserved separately; a future repair must never accept a
missing artifact for `PASS` or `FAILED_MECHANISM`, and cannot rerun or promote this attempt.

## Frozen identities and resources

- Execution source: commit `88720037361822e1202a6b007678726d4e114b72`, tree
  `22ae823cfde9f0f471fde0a16b5b642d569fdd3b`, clean detached checkout
  `C:/a/arc3-stage10-harness-8872003`.
- Source floor: commit `2e78c258cfbee8be62462f61ed08ad04c00a8934`, tree
  `4145356c116944bbd7c0c412771de9179ba22efe`.
- Python 3.12.14; logical launcher SHA-256
  `99bbec125a2d2ce19b6257324a5a5b70539a64c9fd7b9724c6b65dcba8a6d276`; actual interpreter
  SHA-256 `4eb51b7d5963d9e0dc356bd209b1d55360c73db39d8d458ceee084610ca48fd1`.
- Child measured wall: 1,955,847,100 ns. The outer command returned after 9.4018766 seconds.
- CPU, peak RSS, trace volume, and planned suite metrics are unavailable because the resource suite
  was never reached.
- Public environments opened: zero. Gameplay actions: zero. Holdout access: zero.

The exact normalized supervisor argv, plan order, hashes, and boundary receipts are preserved in
`docs/evidence/001-10-robustness-regression.json` and the external attempt root.

## Gate and continuation

Stage 10 cannot satisfy the Stage 11 predicate requiring `PASS`. Stage 09 is also
`FAILED_INFRASTRUCTURE`, so the holdout-opening rule is already false independently. Workflow 001
continues to a mechanically hash-bound `HOLDOUT_NOT_EARNED` decision, a Stage 12 nonconsumption
receipt, package verification, and final reporting. The ten-game public holdout remains
`SEALED_UNCONSUMED`.
