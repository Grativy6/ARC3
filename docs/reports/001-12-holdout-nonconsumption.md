# Build 001 Stage 12 — Sealed holdout nonconsumption

## Result

**Status:** `PASS`

**Decision:** `HOLDOUT_NOT_EARNED`

**Evidence label:** `synthetic`

Because Stage 11 did not earn the frozen gate, Stage 12 performed no public-holdout evaluation.
The nonconsumption receipt records:

- `gameplay_opened=false`;
- `environment_adapter_loaded=false`;
- `environment_actions=0`;
- `identities_loaded=0`;
- `manifest_parsed=false`;
- opaque partition count `10` and only its pre-existing SHA-256 identity.

The exact receipt is tracked at `docs/evidence/001-12-holdout-nonconsumption.json` and preserved at
`C:/a/arc3-b001/artifacts/stage12/holdout-nonconsumption.json`. Both copies are 827 byte-identical
bytes at file SHA-256 `sha256:52005ea16e7f0413f33ad61fed651ee7d8f79ee7493553a6b1aedff34a69709c`;
its semantic core hash is
`sha256:ec9dfe6ffea40c4ecec42888c3872247392768bdbacfa663b484011d774bb24b`.

The receipt is hash-bound to the Stage 11 decision, and independent verification returned
`verified=true`. No `local-public`, `online-public`, `Kaggle-public`, `semi-private`, or
`official-private` holdout score exists for Build 001.
