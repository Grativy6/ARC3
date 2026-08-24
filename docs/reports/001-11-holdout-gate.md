# Build 001 Stage 11 — Frozen milestone and holdout gate

## Result

**Status:** `PASS` for the gate procedure; decision `HOLDOUT_NOT_EARNED`

**Evidence label:** `synthetic`

**Claim boundary:** gate/nonconsumption evidence only; no public-holdout result exists

The five frozen predicates were evaluated from already-produced evidence at clean detached commit
`262b5f1c443d2df28b61ecab19ada760943f5f67` (tree
`235442ff3f5e2918b31ab84a55740b1ad60c4926`). All five were false:

| Frozen predicate | Result | Exact reason |
|---|---:|---|
| Stage 09 = `PASS` | false | authenticated Stage 09 status is `FAILED_INFRASTRUCTURE` |
| Stage 10 = `PASS` | false | read-only reconstruction of H=`8872003…` returned `FAILED_INFRASTRUCTURE` |
| competition integrity clear | false | the Stage 10 composite was never produced after the first-suite abort |
| production source unchanged | false | the gate/verifier source projection is later than production P=`d6d4bac…` |
| sealed holdout identity matches | false | the receipt preserved only the opaque hash; it parsed no manifest or identities |

The exact gate receipt is tracked at `docs/evidence/001-11-holdout-gate.json` and preserved at
`C:/a/arc3-b001/artifacts/stage11/holdout-gate.json`. Both copies are 5,928 byte-identical bytes at
file SHA-256 `sha256:edf01ae6c69a7ce4f862d68bb5a3660cc1b2ce805725d88edd11e1b372a48dcd`; its semantic core hash is
`sha256:7fc63e47bbc601c98daa5c204c809ac216d92cb848f45f493a89fbfb682988bc`.

## Failed launch preserved

The first invocation failed closed before creating either output because the shared environment's
editable installation imported `arc3` from the live worktree. Exact error:
`Stage 11 first-party module origin is outside the execution source: arc3`. Both output paths were
confirmed absent. `docs/evidence/001-11-source-origin-failure.json` preserves the failure. The
repair explicitly bound `PYTHONPATH` to the detached root and `src`; import origins then resolved
to H=`262b5f1…`. No source or evidence was changed, and no holdout surface was touched.

## Verification

The successful environment-free invocation used the exact Stage 09 and Stage 10 file/core hashes,
historical source roots, dependency/config identities, opaque holdout hash
`sha256:682d5891c2aface54803d9bd1173c55ed21e89856e13b8a478fb9276ee963f2f`, seeds `7,11`, action
budget `80`, reset budget `8`, and timeout `120` seconds. Independent bound verification returned
`verified=true` and `HOLDOUT_NOT_EARNED`.

The receipt records `identities_loaded=0` and `manifest_parsed=false`. It does not inspect, name,
enumerate, or play any holdout game.
