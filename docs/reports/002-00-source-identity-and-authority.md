# Build 002 Stage 00 — Source identity and authority preflight

## Current result

**Status:** `PARTIAL` — available public identities and repository ancestry verified; final lock
integration and exact private Kaggle surfaces remain unresolved.

**Evidence label:** `source-identity`

**Claim boundary:** no gameplay, public score, Kaggle compatibility result, or official RHAE.

Build 002 starts from exact merged `origin/main`
`a1931c673b90923e1af78127229667544802a096`, tree
`7ddc02a03908e43caeda31edaf09bea9bd426cfd`. Build 001 final commit
`8a42e43c96ac1edada21725746cdedcee24e68f9` is the merge commit's second parent and passed the
ancestor check. No Build 000/001 evidence is changed.

## Holdout boundary

Build 001 remains `PARTIAL`, and its ten-game holdout remains `SEALED_UNCONSUMED` historical
evidence. Build 002 has a distinct owner authorization for exactly one run after every frozen
preflight passes. The current state is `AUTHORIZED_ONCE_NOT_YET_CONSUMED`, with zero runs and zero
environment interactions. A run begins—and authority is consumed—at the first attempted
environment open/make interaction after the launch receipt. Failure after that boundary does not
authorize a retry.

The machine-readable transition is
`docs/evidence/002-00-holdout-authority-transition.json`.

## Public source identities

The following current official public repository heads were fetched and inspected:

| Source | Commit | Tree |
|---|---|---|
| `arcprize/ARC-AGI` | `f12822c4d550121c35a275008d964afbbed47d2f` | `9ee140e4183df0df109cec50b7cd0d2531c47168` |
| `arcprize/ARCEngine` | `b495c6acaf253c9681cd7b75c4299d352e9ce6f8` | `6677025cc6afbb74b5da332f6808015b903d73ee` |
| `arcprize/ARC-AGI-3-Agents` | `4743e7d0aaae0ded0d98a89a7e282e63564cd58b` | `6878fdfdd0156059323b541fc229b6329ad4fd28` |
| `arcprize/ARC-AGI-3-Kaggle-Starter` | `eeb1535404f321d280a8f9194bbc1d7aca5f05fc` | `332ff438d9b092c95e58a07eace6194379de06b4` |
| `arcprize/docs` | `a5dfc0b64c625fb4a19cf074af845ebe0bb88ff8` | `87ca00ac975faaad8884db70150856e6673c2ade` |

The controlling file blobs and SHA-256 identities are in
`docs/evidence/002-00-official-source-identities.json`. The competition adapter may use the
documented directional/undo grants only in bounded mode. ACTION5 and coordinate-dependent ACTION6
remain evidence-driven; the generic research action mechanism remains intact.

## Current competition metadata

An anonymous official competition metadata request returned HTTP 200 at
`2026-08-24T03:10:13.3556365Z`; response SHA-256 is
`de323841ab53bc7f0378a632a3176566111c8a4060009e7952b826661896e09e`. It reports competition id
133468, nine-hour CPU/GPU limits, notebook-only execution without internet, required
`submission.parquet`, one daily submission, two scored submissions, synchronous rerun, and gateway
kernel id 110953907.

The nine-hour competition limit is narrower than the generic twelve-hour notebook ceiling and
therefore controls. The planned governor reserve is 6,000 seconds inside nine hours. No terms were
accepted, credentials used, upload made, or submission consumed.

## Discrepancies and fail-closed policy

- ARC-AGI 0.9.9 local methodology/code cap per-level action efficiency at 1.15; the current Kaggle
  data-page formula describes a 1.0 cap. Local scores must name the exact scorer and cannot be
  called official.
- Current public ARC-AGI is 0.9.9; the latest observed official staff sample used 0.9.6. Private
  runtime parity is unproved.
- The pinned starter's submission-limit text is stale against current competition metadata.
- The pinned Agents action loop has an inclusive counter edge; `MyAgent`/the governor must stop at
  the exact configured budget.
- Documentation names ACTION7 as undo while ARCEngine types expose a generic simple action. Build
  002 grants undo only at the bounded adapter boundary.

Exact private wheels, framework input, gateway, scorer, accepted-terms runtime, and hidden games
remain `BLOCKED_EXTERNAL`. This does not prevent local implementation, packaging, or structural
validation; it does prevent an exact private-compatibility or official-score claim.

## Stage 00 disposition

The project lock now carries an additive Build 002 overlay and validates as JSON at SHA-256
`b5474a8f36bda80bb629f204591610325045411bd5aac65f6765261b7fab6b0b`; prior-build sections are
preserved. Available public source identity is therefore `PASS`. Exact private Kaggle surfaces stay
`BLOCKED_EXTERNAL`, and the implementation/configuration/package freeze remains a later preflight.
The one-run authority remains unconsumed.
