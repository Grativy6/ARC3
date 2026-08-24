# Build 002 Stage 00 — Source identity and authority preflight

## Current result

**Status:** `PARTIAL` — available public identities, repository ancestry, and the additive project
lock are verified; exact Kaggle and local evaluator surfaces remain unresolved.

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
environment interactions. A run begins—and authority is consumed—when the runner durably records
intent immediately before the first and only upstream scorecard open. This stricter boundary
prevents an ambiguous scorecard-open failure from authorizing a second scorecard. Environment
`make` interactions remain separately counted from zero, and failure after the scorecard boundary
does not authorize a retry.

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
`2026-08-24T04:28:41.5202644Z`; the 3,080-byte raw response SHA-256 is
`ca6253ca8e87ba6e4e5a435ee5f83bc27aaf62aa564860c1e31390349978de4f`. It reports competition id
133468, nine-hour CPU/GPU limits, notebook-only execution without internet, required
`submission.parquet`, one daily submission, two scored submissions, synchronous rerun, and gateway
kernel id 110953907.

The nine-hour competition limit is narrower than the generic twelve-hour notebook ceiling and
therefore controls. The planned governor reserve is 6,000 seconds inside nine hours. No terms were
accepted, credentials used, upload made, or submission consumed.

The earlier source receipt and runtime lock contained different hashes for one alleged response
without a raw-versus-canonical distinction. Neither older hash is controlling. The fresh raw
capture above is cross-bound into both `upstream.lock.json` and the frozen runtime; the prior
inconsistency remains recorded as superseded evidence rather than silently corrected.

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

Exact private wheels, framework input, gateway, scorer, accepted-terms runtime, exact Kaggle
platform cold start, packaged-runner/import attestation, OS-enforced network containment,
independently pinned ten-game asset provenance, and hidden games remain `BLOCKED_EXTERNAL`. In particular, game
IDs plus self-hashes of caller-supplied files are not sufficient evidence that those bytes are the
official public assets. This does not prevent local implementation, packaging, or structural
validation; it does prevent an exact public-run, private-compatibility, or official-score claim.

## Stage 00 disposition

The project lock now carries an additive Build 002 overlay and validates as JSON at SHA-256
`fb3acb1e375dddaaa02e38dc39cd3a0cde7fe95045d4dca34d976d29e0f56c68`; prior-build sections are
preserved. The available-public-source subcheck is therefore `PASS`, while the overall source
receipt remains `PARTIAL`. Exact Kaggle and evaluator surfaces stay `BLOCKED_EXTERNAL`; the adapter
and lifecycle are implemented and locally tested, while the final configuration/package freeze
remains a later preflight.
The one-run authority remains unconsumed.
