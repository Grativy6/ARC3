# ARC3 Build 003w — Wise Scientist clean-room development play

- **Overall status:** `PASS`
- **Workflow status:** `COMPLETE`
- **Evidence label:** `local-public`
- **Branch:** `experiment/003w-wise-scientist-clean-room`
- **Game:** `ls20-9607627b`
- **Final official state:** `WIN`
- **Official progress:** `7/7`
- **Claim boundary:** `NO_GENERALIZATION_CLAIM`; `NO_OFFICIAL_RHAE_CLAIM`
- **Holdout:** `SEALED_UNCONSUMED`

Christopher D. Pang is author and steward. AI systems were development tools and assistants, not
co-authors, owners, or independent authorities.

## Abstract

Build 003w tested the Wise Scientist directive in a fresh clean-room checkout rather than importing
the earlier Build 003 learner or gameplay state. The run used decision-relevant distinctions,
prediction-before-action receipts, scoped stage priors, localized residual revision, and explicit
recovery from failure. It continued through all seven stages of the selected public development
game until the official environment returned `GameState.WIN`.

The terminal result is genuine but narrow. It is one assisted `local-public` trajectory, not an
autonomous hidden-game generalization result, an official competition score, or evidence that the
same policy will solve another game. The full immutable trace remains repository-local under the
ignored artifact root; tracked evidence records its paths, byte sizes, hashes, terminal observation,
receipt, checkpoint, and verification results.

## Authoritative completion receipt

| Field | Observed value |
|---|---|
| game ID | `ls20-9607627b` |
| final official environment state | `WIN` |
| `levels_completed` | `7` |
| `win_levels` | `7` |
| genuine `GameState.WIN` observed | `true` |
| unique logical environment actions | `1,324` |
| replay environment actions | `991` |
| physical environment actions | `2,315` |
| unique logical resets | `3` |
| replay resets | `2` |
| physical resets | `5` |
| total physical SDK calls | `2,320` |
| terminal resource / lives | `16 / 1` |
| elapsed wall time | `71,244.569304 s` (`19.790158 h`) |
| final receipt hash | `sha256:fd69f3d50d1b03d055db73eb1e8e8c138d73a0ceeb95ad211f42bb13e1c2f6ce` |
| WIN observation hash | `sha256:ef954826914b7ae2a8c92d11e4065e2e5fe909b4de59c64327dd642ba2915a51` |

Primary replay and evidence paths:

- `artifacts/003w/run-003w-20260830T2302Z-bridge/events.jsonl`
- `artifacts/003w/run-003w-20260830T2302Z-bridge/recovery-events.jsonl`
- `artifacts/003w/run-003w-20260830T2302Z-bridge/observation-001327.json`
- `artifacts/003w/run-003w-20260830T2302Z-bridge/final-receipt.json`
- `docs/evidence/003w-05-official-development-win.json`
- `docs/evidence/003w-06-final-verification.json`

The physical action total counts every non-`RESET` call made to an official environment object,
including deterministic recovery replay. Resets are reported separately. The current-session local
ScorecardManager reports 1,327 actions and three resets; this equals 1,324 unique logical
environment actions plus the three unique resets. Its per-level action vector is
`[16, 80, 206, 59, 462, 231, 273]` and sums to 1,327.

The same local ScorecardManager reports `57.27512786469639`. This is a verified score only on the
pinned `arc-agi==0.9.9` `local-public` surface. It is not official RHAE and is not promoted to an
official or private result.

## Clean-room and authority boundary

The Wise branch began from merged Build 002 at
`bea1eac99cb0f1b351526b1dc487d132ba1d40ef`. The frozen play directive is commit
`04cf10a1e45b40e26bb31a0e5e106593e53b5696`, with file SHA-256
`39ec55d9ec92095a1567466e5e137b26a7a81ba7ad7453170954a4f318864f8e`.
The final gameplay source commit is `41d73427468afa7a8d797d93a87efd6e2a7e9403`.

No sibling checkout was inspected, no Build 003 implementation or trace was imported, no sealed
holdout identity or manifest was loaded, and no game source was read during evaluation. A
non-playing delivery helper checked remote branch/default-branch/pull-request metadata during play;
it did not fetch or inspect other ref objects, open gameplay content, or communicate any such
content to the player. That metadata check is disclosed rather than being silently folded into the
clean-room claim.

After the official `WIN`, delivery verification moved disposable pytest basetemp trees from the
repository to the user's local temporary directory so repository-wide scans would not scan their
own generated fixtures. This was a recorded deviation from the stricter repository-only workspace
instruction. It happened after gameplay, opened no environment session, imported no earlier build
or mechanic content, and does not weaken the narrower clean-room gameplay claim.

Public non-holdout development play was the only authorized evaluation surface. No contest terms
were accepted, no Kaggle or game credential was used, no paid service was activated, no submission
was uploaded, and no pull request was merged.

## Wise Scientist behavior observed

The journal contains 1,327 complete action decision cycles:

- 1,231 consequences classified `MATCHED`;
- 73 classified `MISMATCHED`;
- 23 classified `PARTIAL`;
- 10 no-action distinction scans;
- 9 explicit attentional stage closures; and
- 3 preserved `GAME_OVER` events.

The three `GAME_OVER` observations occurred once at 2/7 and twice at 4/7. Each remained failure
evidence. The run preserved the implicated trace, used an officially available reset, replayed the
required prefix with exact semantic observation checks, and resumed from the smallest implicated
model boundary. No failure was relabeled as completion.

Across stages, the learner provisionally carried cardinal movement, resource cost, one-use
recharges, keyed endpoint equality, palette conversion, shape editing, rotation, and transport
semantics. New surfaces triggered fresh scans rather than exhaustive completion of old maps.
Residuals reopened only the affected route, life-state, editor, or transport hypothesis. The final
stage is the clearest example: an initially plausible topology-only exit was disproved, after which
the learner recovered palette, editor, recharge, moving-control phase, and access distinctions
needed for the actual endpoint.

On the final life, the run:

1. converted the HUD to color 8;
2. applied a measured editor sequence while preserving enough resource to recharge;
3. collected two additional one-use recharges through known transport routes;
4. aligned two moving-control contacts to produce exact shape `101/110/011`;
5. selected the safer, better-supported exit rather than the shorter untested edge; and
6. contacted the target at `(31,52)` with resource 16 and one life.

The two previously unobserved final floor edges matched their predictions. Target contact then
returned the only authoritative completion signal: `WIN`, with `levels_completed=7` and
`win_levels=7`.

## Recovery and budget accounting

The run spans four official local session IDs. Three `run.resumed` receipts verified exact
normalized observation replay, excluded only upstream session metadata from equality, and recorded
that no logical action was duplicated. Across those recoveries, 991 environment actions and two
resets were physically replayed.

The original 1,000-action ceiling could not reconstruct a checkpoint already reached at 991
physical actions. A committed resume-only gate monotonically extended the ceiling to 3,000 while
preserving all prior calls and requiring abort on any replay mismatch. The wall-clock ceiling was
similarly extended from 14,400 to 86,400 seconds through an immutable recovery receipt. The run
finished at 2,315 physical environment actions, five physical resets, and 71,244.569304 seconds,
inside all final ceilings.

## Verification

The terminal `assess` wrote exactly one `run.completed` event, a self-hashed final receipt, a final
journal receipt, and a `COMPLETE` checkpoint. Independent verification recomputed the final receipt
hash, verified the full journal and recovery hash chains, matched terminal counts and identities,
confirmed a single observed `WIN`, checked the final checkpoint, and hashed every retained terminal
artifact. Source policy, secret, repository-integrity, focused Wise Scientist, lint, format, and
strict typing gates passed and are recorded in `docs/evidence/003w-06-final-verification.json`.

A bounded broad historical-suite attempt reached 202 passed, 3 skipped, and 6 failed tests before
its `--maxfail=6` stop. All six failures were attributable to deep/extended Windows path handling:
the four implicated package-projection tests then passed as part of a 28-test short-path run, the
controller end-to-end test passed on a normal short in-repository path, and the slow paired
ablation test passed from the shortest repository-root basetemp. No source or test change was
needed. This resolves the implicated regression question, but the broad suite was not rerun to
completion and is not claimed as a full-suite pass.

## Interpretation and limits

This run supports the bounded claim that the Wise Scientist process, with active human-directed AI
reasoning entering explicit decisions into an offline guarded runner, completed this one exposed
development game. It also shows the intended mechanics of attentional closure, scoped transfer,
small residual repair, and failure-preserving recovery operating in a long real trajectory.

It does not establish:

- autonomous reproduction by the packaged competition policy;
- performance on a second, unseen, holdout, semi-private, or private game;
- a causal advantage over Little Scientist without a controlled comparison;
- action optimality or efficient RHAE;
- robustness to another seed or game version;
- a completed pass of every inherited historical repository test on this Windows/OneDrive host;
- any general claim about intelligence beyond this bounded experiment.

The 122 parked distinctions in the terminal receipt are retained as reopening handles. They do not
invalidate the observed `WIN`; they limit how broadly the learned mechanic map may be interpreted.

## Disposition

Build 003w is `PASS` and workflow-complete because the official environment itself returned
`GameState.WIN` and the terminal evidence verified. The branch is delivered through draft pull
request [#8](https://github.com/Grativy6/ARC3/pull/8) and must remain unmerged unless Christopher
D. Pang explicitly authorizes a merge.
