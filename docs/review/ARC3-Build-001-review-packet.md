# ARC3 Build 001 — Review packet

## Review disposition

- **Overall:** `BUILD 001: PARTIAL`
- **Pull request:** <https://github.com/Grativy6/ARC3/pull/5>
- **State:** draft, open, unmerged
- **Branch:** `build/001-local-public-recovery`
- **Package stage:** `BLOCKED_EXTERNAL`
- **Holdout:** `SEALED_UNCONSUMED`
- **Claim boundary:** `NO_GENERALIZATION_CLAIM`

This packet is a review map, not a replacement for the exact evidence. Christopher D. Pang is
author and steward. AI systems were development tools and assistants, not co-authors, owners, or
independent authorities.

## Recommended review order

1. Read `docs/research/ARC3-Build-001-report.md` for the full bounded result.
2. Check `docs/evidence/001-final-evidence-index.json` for exact paths and hashes.
3. Compare the stage table in `docs/research/data/ARC3-Build-001-stage-results.csv` and the paired
   baseline/ablation table in `docs/research/data/ARC3-Build-001-baseline-ablation.csv` against their
   source evidence; use `docs/research/data/ARC3-Build-001-mechanism-results.csv` for the compact
   controlled-mechanism rows.
4. Inspect `docs/evidence/001-06-rule-change-reopening.json`,
   `docs/evidence/001-09-development-recovery.json`, and
   `docs/evidence/001-10-robustness-regression.json` before evaluating any success claim.
5. Verify the Stage 11/12 denial/nonconsumption receipts before accepting the statement that no
   Build 001 public-holdout result exists.
6. Validate the package receipt and final verification seal.
7. Review every still-open item in `docs/ledger/build-001-OPEN-BURDENS.md`.

## Claims under review

| Claim | Allowed status | Controlling receipt |
|---|---|---|
| `THROUGHPUT_BOTTLENECK_IDENTIFIED` | supported for matched measured prefixes | `001-03-causal-bottlenecks.json` |
| `PALETTE_EQUIVARIANCE_OBSERVED` | supported only on the paired synthetic suite | `001-04-palette-equivariance.json` |
| `ACTION_EQUIVARIANCE_OBSERVED` | supported only on the paired synthetic suite | `001-05-action-equivariance.json` |
| `RULE_CHANGE_REOPENING_OBSERVED` | not supported for the full stage | `001-06-rule-change-reopening.json` |
| `LOCAL_PUBLIC_RECOVERY_OBSERVED` | not measured | `001-09-development-recovery.json` |
| Stage 10 baseline/ablation | unavailable | `001-10-robustness-regression.json` |
| `HOLDOUT_NOT_EARNED` | mechanically supported | `001-11-holdout-gate.json` |
| public-holdout score | no result exists | `001-12-holdout-nonconsumption.json` |
| deterministic offline package | supported on available synthetic/runtime surfaces | `001-13-offline-package.json` |
| private Kaggle compatibility | `BLOCKED_EXTERNAL` | `001-13-offline-package.json` |

Not claimed: hidden-game generalization, official RHAE, AGI, consciousness, PAL validation, or a
general theory of intelligence.

## Exact headline results

### Local-public

Build 001 FULL reproduced the frozen timeout at seed 7: 120.11965939996298 seconds, 21 actions,
zero levels, local score 0.0. The matched Build 000 FULL run used 120.110601900029 seconds, 19
actions, zero levels, local score 0.0. This is a reproduced failure, not a recovery.

The 96-cell Stage 09 recovery matrix never opened an environment. Its sole attempt exposed one
development identity, submitted zero actions, and left 95 cells unstarted after exact launcher/
interpreter identity failed closed.

### Synthetic mechanisms

- Palette: 256/256 procedural pairs, 16/16 checkpoint pairs, 128/128 causal controls, and 2/2
  historical cases passed; the historical unpermuted action cost increased 25%.
- Action handles: 128/128 procedural pairs, 528/528 inverse requests, 64/64 controls, 16/16
  checkpoint pairs, and 2/2 historical cases passed; the historical unpermuted action cost
  increased 50%.
- Rule changes: 112/112 executions completed, but traversability and stationary-noise gates each
  passed 0/32 and checkpoint continuity passed 4/8. Stage status is `FAILED_MECHANISM`.
- Retrodiction and two-speed decisive matrices are `FAILED_INFRASTRUCTURE`; partial receipts do not
  authorize an aggregate winner or recovery claim.

### Historical baseline/ablation

Build 001 Stage 10 did not produce a replacement comparison. The retained Build 000 historical
matrix reports FULL 8/14 in 150 actions, no world-model simulation 1/14 in 211, no goal inference
0/14 in 224, and no retrodiction gate 8/14 in 141. These are frozen inherited comparators only.

## Package review

The accepted local `d9c19558…` A/B archives are byte-identical, 788,071 bytes, SHA-256
`0bd55b93d1652f1d2f09aafb74189d5b6050e4a9fae3df9aa9925359f2a095bd`. The package-safe suite
passed 699 tests with two skips. Startup passed in 1.6057818999979645 seconds at 67,846,144-byte
peak RSS with zero Python-audited network/process attempts. Four hosted Ubuntu/Windows jobs
authenticated deterministic packaging. The final `9f25e13…` source retains the same 100-member
runtime payload projection and produces eight byte-identical hosted A/B archives at 788,070 bytes,
SHA-256 `02326a145d510c017dc04ffd79a61cfe8c46771cbc9e74b7c8f29a9b75756d21`.
Exact final-source job and receipt identities are sealed in the final evidence index.

Review boundaries:

- exact private wheels/input/gateway/scorer unavailable;
- no upload or official submission;
- Python audit guard is not complete OS/native containment;
- static checks are not proof against every possible shortcut;
- package success cannot revise negative or unavailable game results.

## Integrity checklist

- [x] Build 000 evidence preserved and referenced as historical only.
- [x] Stage 00 owner-authorized MIT-0 provenance retained.
- [x] Upstream commits, packages, static docs, lock, and notices pinned.
- [x] Raw failed attempts retained; no failure overwritten by a later repair.
- [x] Production policy contains no known public IDs or obvious solution table.
- [x] Competition mode has no hosted-model runtime dependency.
- [x] Trace replay, checkpoint/resume, and secret checks included in final verification.
- [x] Holdout gate failed mechanically and nonconsumption receipt exists.
- [x] No legal-term acceptance, paid compute, submission, merge, release, DOI, or owner
  impersonation occurred.
- [ ] Exact private-platform compatibility remains externally blocked.
- [ ] Full 110-game runtime remains unmeasured.
- [ ] Complete OS/native containment is not claimed.

## Failed mechanisms and permanent failed-run evidence

- Stage 06 typed rule-change/reopening gate failure;
- Stage 07 incomplete 280-cell retrodiction decision;
- Stage 08 incomplete 20-cell two-speed comparison;
- Stage 09 launcher/interpreter PID authority abort;
- Stage 10 missing frozen-commit argument abort;
- initial Stage 13 long-root Windows path failure;
- earlier package-plan, guard, interpreter-origin, line-ending, and CI-contract failures preserved
  in the burden ledger and external audit roots.

## Publication boundary

`docs/research/ARC3-Build-001-publication-draft.md` is a draft only. It has not been submitted,
released, assigned a DOI, or communicated externally as Christopher D. Pang.

## Exactly one owner action

Review draft PR #5 and decide whether to merge it.
