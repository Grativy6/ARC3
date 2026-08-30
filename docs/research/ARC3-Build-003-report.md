# ARC3 Build 003 — BLA–CLEF mechanical learner

**Workflow disposition:** `COMPLETE`
**Build disposition:** `PARTIAL`
**Official development target:** `WIN`, 6/6 levels in Campaign 52
**Official target completion observed:** `true`
**Final preregistered synthetic matrix:** `FAILED_MECHANISM`
**Corrected independent audit:** `FAIL` — 534 genuine evidence-completeness findings
**Official ARC3 RHAE:** `NOT_MEASURED`
**Public holdout consumed:** `0/1`
**Claim boundary:** `NO_ARC3_GENERALIZATION_CLAIM`

Christopher D. Pang is author and steward. AI systems were development tools and assistants, not
co-authors, owners, or independent authorities.

## Abstract

Build 003 implements a bounded BLA/CLEF-inspired mechanical learner that predicts before acting,
decomposes returned consequences, records structured residuals, revises versioned scoped mechanics,
uses passive confirmation, and retains reliable mechanics across levels while quarantining game
facts between games. The production route is
`MyAgent -> VisualCausalPolicy -> MechanicalLearner`; the Build 002 lifecycle, legal-action,
resource, and tournament-governor boundaries remain operative.

The primary gameplay outcome was achieved. On authorized public non-holdout development play, the
official environment returned `GameState.WIN` for `r11l-495a7899` after completing all six levels.
Campaign 52 submitted 429 actions including five legal resets: 424 `ACTION6` actions and five
`RESET`s. The terminal action was `ACTION6 (14,60)`. The raw recording, immutable trace, official
scorecard, run receipt, and completion receipt all report `WIN`, `levels_completed=6`, and
`win_levels=6`; the canonical verifier passed all 613 declared artifacts.

This win does not erase the negative research result. The exact one-shot synthetic matrix remains
`FAILED_MECHANISM`: H1 and H3 failed, H2 is `NOT_MEASURED`, and receipt completeness is 0.615. The
public evaluator therefore retains `MECHANISM_NOT_OBSERVED` and `NO_GENERALIZATION_CLAIM` even
though its run status is `PASS`. Repeated development exposure and iterative repairs make Campaign
52 evidence of completion on this public development game, not hidden-game generalization.

## 1. Identity, base, and authority

Build 003 branches from merged main `bea1eac99cb0f1b351526b1dc487d132ba1d40ef`, tree
`700718c09c2a1532cea16526b290f57be0120371`. Build 002 head
`5448c53f3b7e08f606cf292e6068f3f9c9db16d4` is ancestral and merge-equivalent by tree. Build 001
remains `PARTIAL` and `SEALED_UNCONSUMED`; Build 002 remains `PARTIAL`, with its exact private
evaluation boundary preserved as `BLOCKED_EXTERNAL`. No prior result is retroactively revised.

The successful implementation freeze is:

- branch: `build/003-bla-clef-mechanical-learner`;
- commit: `eab4497a6033bd27102ed99d4d2e43f6ab708ec4`;
- tree: `17bb7e126034f6ccf8a5d24becd8163629e33757`;
- first-party source hash:
  `sha256:96fada83990cd7c6a6b08aca151443c1d3ce51d725020bc35361a5cbee3c3902`.

The final evidence commit is documentation-only relative to that freeze. Its exact pushed identity
and current check state are external self-referential facts recorded on draft PR #7.

The controlling source identities are:

| Source | Identity |
|---|---|
| Build 003 workflow | `sha256:f261b0840e023f34bbadd06cece2ab98647d3685afd960fd1f2f3eeb329f8467` |
| BLA v0.9.1 public working draft, Zenodo 20807530 | `sha256:7ec1fbd21a792770a1617b74360b3af1b2ab1fd056d9a81bb7ba1b136008185e` |
| CLEF v1.0, Zenodo 21193511 | `sha256:24589330eda2020145492fc7c3395911e0cf7a17cc67dfe47dad4e7af1280d43` |
| `arcprize/ARC-AGI` | `f12822c4d550121c35a275008d964afbbed47d2f` |
| `arcprize/ARCEngine` | `b495c6acaf253c9681cd7b75c4299d352e9ce6f8` |
| `arcprize/ARC-AGI-3-Agents` | `4743e7d0aaae0ded0d98a89a7e282e63564cd58b` |
| `arcprize/ARC-AGI-3-Kaggle-Starter` | `eeb1535404f321d280a8f9194bbc1d7aca5f05fc` |
| `arcprize/docs` | `a5dfc0b64c625fb4a19cf074af845ebe0bb88ff8` |

The official cached target asset is repository-classified development evidence at
`C:\a\arc3-s15-6a0f6e5\artifacts\stage15\public-environments`, SHA-256
`483e583c88e91c2ae58ad1fa7b274d97813993796ce798551a563e1a9a78a7ff`. Its game source was not
semantically inspected. The target ID is evaluation configuration only and is prohibited from
production policy code.

## 2. Architecture delivered

Build 003 adds:

- typed CLEF-style logical layers, readability/noise gates, independent evidence families, and
  explicit `PROMOTE`/`PARK`/`STOP` decisions;
- predicted, observed, explained, and residual consequence vectors over ten effect channels;
- immutable replay-linked action receipts and a hash-linked versioned BLA mechanic ledger;
- scoped support, passive confirmation, stress, reopening, revision, and supersession;
- sparse additive, conditional, gating, override, and delayed causal composition;
- local-first repair and deeper reopening only after implicated local explanations fail;
- relevance-ranked bounded exploration without a whole-grid coordinate fallback;
- within-game cross-level persistence, level-local reset, same-level failure memory, and cross-game
  quarantine;
- deterministic curriculum, ablation, replay, public evaluation, packaging, and integrity tools.

The learner is deterministic under its declared seed, works without a hosted model, and remains
bounded by the inherited competition governor.

## 3. BLA/CLEF source-to-implementation mapping

The frameworks are bounded software-design inputs. Their use does not validate BLA or CLEF as a
general theory and does not control ARC semantics.

| Source mechanism used | Bounded realization | Principal paths | Evidence limit |
|---|---|---|---|
| CLEF layer declaration and dynamic action window | Typed logical layers, action windows, readable fields, extraction thresholds, and readability walls | `src/arc3/perception/layers.py` | Operational game layers only |
| CLEF independent evidence families | Separate evidence readings and non-averagable validity gates | `src/arc3/perception/layers.py` | Failed validity parks evidence |
| CLEF coupling promotion and relevance stopping | `PROMOTE`, `PARK`, or `STOP` on residual relevance and cost/value | `src/arc3/perception/layers.py`, `src/arc3/exploration/causal_events.py` | Final H3 is `FAIL` |
| BLA residual as bounded question | Typed predicted/observed residual records with provenance | `src/arc3/exploration/causal_events.py`, `src/arc3/mechanics/effects.py` | Unknown values are not invented |
| BLA versioned boundary ledger | Append-only hash-linked mechanic versions, scope, counterevidence, reopen, and supersede | `src/arc3/mechanics/models.py`, `src/arc3/mechanics/ledger.py` | Final matrix linkage remains incomplete |
| BLA support conservation | Distinct-context support, passive confirmation, scoped stress/reopen, and transfer confirmation | `src/arc3/mechanics/ledger.py`, `src/arc3/mechanics/learner.py` | H1 failed; no general transfer claim |
| BLA smallest repair | At most four ranked local candidates and implicated-only reopening | `src/arc3/mechanics/repair.py`, `src/arc3/mechanics/learner.py` | H2 is `NOT_MEASURED` |
| Sparse causal composition | Additive, conditional, gating, override, and delayed contributions | `src/arc3/mechanics/models.py`, `src/arc3/mechanics/effects.py` | Occurrence evidence does not prove magnitude |
| Persistence and authority ceilings | Game/level/region/object/state scope, reset retention, and cross-game quarantine | `src/arc3/mechanics/learner.py`, `src/arc3/mechanics/ledger.py` | No live cross-game generalization evidence |
| Economical causal exploration | Relevance-ranked probes, failed-action memory, bounded coordinates, and fail-closed exhaustion | `src/arc3/exploration/policy.py`, `src/arc3/exploration/coordinates.py`, `src/arc3/mechanics/visual_causal.py` | No whole-grid fallback |
| Action/consequence integration | Predict, select once, receive one consequence, update, and replan | `agent/my_agent.py`, `src/arc3/mechanics/visual_causal.py`, `src/arc3/evaluation/public_runner.py` | Campaign 52 is one public-development win |

## 4. Synthetic curriculum and ablation

Protocol v0.2 froze 30 held-out synthetic cases, ten mechanic families, four variants, and 1,200
required rows. The exact root is `C:\a\arc3-b003-stage08-v02-final-83df552-01`.

| Result | Literal disposition |
|---|---|
| structure | complete: 1,200 rows and 120 sequence receipts |
| terminal counts | 47 synthetic `WIN`, 43 `ACTION_BUDGET`, 30 `WALL_CLOCK_BUDGET` |
| H1 transfer | `FAIL`; paired later-level exploratory-action median delta 2.0 |
| H2 conservative repair | `NOT_MEASURED`; required assessment incomplete |
| H3 CLEF relevance | `FAIL`; redundant-probe delta 0.0 and pressure delta 8.0 |
| replay determinism | 1.0 |
| action/receipt completeness | 0.615 |
| overall | `FAILED_MECHANISM` |

Principal hashes are matrix receipt
`a01c3dfca5c18d6282e978c07de035932dd28de21491e7a7ea04f8354a0fc8a6`, rows
`8195b470bf4287f4d3246ee82ab349b39a20fb26697c6e714ef1e1aed748f8c0`, and sequence receipts
`d5d7d865a4a4b52c42d01601b274744b3603893d8e07495b61d16fd69a9c2d60`.

The corrected independent audit remains `FAIL` with 534 genuine findings: 462 per-level
action/receipt count mismatches and 72 aggregate incomplete-link attestations. The matrix was not
rerun, subsetted, rewritten, or reclassified.

## 5. Official non-holdout development completion

The target was `r11l-495a7899`, partition `development`, surface
`local-public-source-preview-exposed`, with six declared levels. Public development play was
authorized. It was not the sealed holdout.

Campaign 52 is the authoritative completion receipt:

| Required receipt field | Value |
|---|---|
| evaluation ID | `build003-r11l-mechanical-seed7-eab4497-campaign52` |
| game ID | `r11l-495a7899` |
| final environment state | `WIN` |
| levels completed | 6/6 |
| `win_levels` | 6 |
| submitted actions including resets | 429 |
| non-reset environment actions | 424 |
| submitted resets | 5 |
| final action | official action 429, `ACTION6 (14,60)` |
| `GAME_OVER` / `WIN` consequences | 5 / 1 |
| completion genuinely observed | `true` |
| repository receipt | `docs/evidence/003-10-official-development-win.json` |

The official scorecard reports level action counts `[3,10,13,35,335,33]`, verified state `WIN`,
and score `76.79913906815948`. That score is not relabeled RHAE; the scorer exposes no standalone
official RHAE field.

The recording contains 430 rows: one opening SDK observation plus 429 submitted actions. The trace
contains 2,575 events: 430 observations and 429 each of candidate, selection, submission,
consequence, and durable mechanics receipt. All four action streams match. The final raw observation
event is `E-01788064208554893700-00000a0e-a8495476bf5941f5b66973273aa640fe` and reports
`WIN`, 6/6, with upstream session `730d1515-d732-4f70-9b7b-8796119c3e21`.

Principal evidence:

- root:
  `C:\a\arc3-b003-play\build003-r11l-mechanical-seed7-eab4497-campaign52`;
- recording SHA-256:
  `441ca0be8f956b8b07c52c8ba5f24e0b485618f06231248c7e6ce579f7d48fbe`;
- run/result file SHA-256:
  `8b7f653e914f44276108b34af1bf37f74ce66c6a6f094e7b6eb3ab0dc723e069`;
- run receipt object hash:
  `sha256:9826969ef86358f9d58d5d66b0bdd09034d8c2a8835ed8eea456ed3fb19260e1`;
- completion receipt hash:
  `sha256:84030e25bd09e812d7bd15948d9f785a3d9e9468e99d0534f7e6f91e3ad4181c`;
- trace chunk SHA-256:
  `3c0338cc43b27740d3a0b91e4cd40a5bb36864c5f72d5ec7b1936d5a1a888436`;
- trace manifest object hash:
  `sha256:ef4c11fc2c60a12cdb0a3f01f119e0611ae93fbf3de0834ea82ade7cc6517364`;
- trace tail:
  `sha256:91f3e24a39fea6a823139e148b33f5f695b8dc9dd3cd0b666910d2b36dba0f0e`.

The canonical verifier returned `verified=true`, 613 declared artifacts, one run, and zero errors.
The exposure ledger contains 101 development events, zero holdout events, final sequence 100, tail
`sha256:157773149e8dfa20c2f624ffc2a811635786aaf29ed12912b3a7d53e2630af40`, and file SHA-256
`1dbfe3e9b29dae81083fddc1e69ba7dca35e67b3f030d633cf90b56342fcb000`.

Campaigns 1–51 remain immutable development evidence. In particular, Campaign 50 and Campaign 51
remain `FAILED_MECHANISM` at 5/6. Their two distinct overlay residuals motivated the generic
per-source layer repair in `eab4497`; their failures are not rewritten as prior knowledge or
success.

## 6. Verification, package, and CI

At exact successful freeze `eab4497`:

- Campaign 51 replay matched all 424 submissions, consequences, and mechanics receipts, then
  staged/cancelled only the related continuation with zero environment actions;
- clean-source selection: 119 passed, three expected platform skips;
- replay/CLI/audit selection: 82 passed;
- full visual-policy module: 155 passed in 4,165.07 seconds;
- Ruff lint/format, strict MyPy, manifest integrity, package-only integrity, action semantics, and
  sanitized development prelaunch audit passed;
- all five required hosted workflows and all nine jobs passed before Campaign 52.

Ordinary exact-freeze CI totals were 1,881 passed and 10 skipped on Ubuntu for both
the PR and push runs, and 1,871 passed and 20 skipped on Windows for both runs. Ruff
passed, and strict MyPy checked 207 first-party source files.

The exact-freeze Windows package artifact was downloaded read-only from hosted run
`33288733132` to `C:\a\arc3-c52-package-artifact-eab4497-push`. Its scoped non-private checks pass;
the release wrapper remains correctly `BLOCKED_EXTERNAL` only for unavailable exact private Kaggle
surfaces, which were not accessed.

| Package field | Value |
|---|---|
| candidate | `C:\a\arc3-c52-package-artifact-eab4497-push\package-a\arc3-kaggle-candidate.zip` |
| candidate SHA-256 | `432bdf0ae61f5c960f7372c6b07c1e1393fa52f764f1997ab0d450b2f3459639` |
| A/B deterministic | `true` |
| first-party payload SHA-256 | `95394d1722ec9590980e51444542ad0f9755f52e98b0f6274af773bafde2d0a5` |
| manifest SHA-256 | `acf091dd0ae701a9bc8c80d3770bb05b0165b971c07f72798349b0712edab377` |
| SBOM SHA-256 | `05ec473913d86194ae56582dd8cfbf2e0c7dccc7fcfdb87ca19e7da657e3f97c` |
| package-safe suite | 1,130 passed, three platform skips, zero guard attempts |
| cold start | 1.2002791 seconds, 84,910,080 sampled peak RSS bytes, zero network/process attempts |
| generated-log scan | 22 persisted redacted logs, zero findings/redactions |

Hosted exact-freeze runs were CI push `33288733127`, package push `33288733132`, CI PR
`33288734446`, package PR `33288734449`, and cold-start PR `33288734468`. All nine jobs succeeded.

## 7. Stage disposition

| Stage | Status | Bounded result |
|---:|---|---|
| 00 | `PASS` | source/base/authority and development target identity verified |
| 01 | `PASS` | Build 002 baseline frozen; historical infrastructure failures retained |
| 02–07 | `PASS` | state, ledger, relevance, planning, persistence, and curriculum delivered |
| 08 | `FAILED_MECHANISM` | exact final H1/H3 fail, H2 not measured, completeness 0.615 |
| 09 | `PASS` | required adversarial obligations covered within declared limits |
| 10 | `PASS` | official `WIN` observed; exact package/local/hosted gates passed |
| 11 | `PASS_WITH_EXTERNAL_SELF_IDENTITY_RECEIPT` | final receipt, report, handoff, index, evidence freeze, push, and draft PR handoff; final commit/tree/index hash live in the PR receipt because the files cannot embed their own identities |

The overall build remains `PARTIAL` because the synthetic mechanism claim failed and generalization
was not measured. `PARTIAL` does not negate the separately observed target-game `WIN`.

## 8. Open burdens and claim boundary

Build 003 cannot report `MECHANISM_CONFIRMED_SYNTHETIC`, ARC3 generalization, official RHAE,
private Kaggle compatibility, validation of BLA/CLEF as general theories, AGI, consciousness, or a
general theory of intelligence.

Material residuals remain:

- the 534 genuine final-matrix linkage findings remain immutable;
- H1 and H3 failed and H2 is `NOT_MEASURED`;
- one repeatedly exposed public development game cannot establish hidden-game transfer;
- exact private Kaggle wheels, gateway, Agents input, scorer, and acceptance surface remain
  `BLOCKED_EXTERNAL` and unaccessed;
- pixel-only inventory interpretation, topology without behavioral evidence, one-off delayed
  consequences, and exact-resource-context override magnitude remain bounded limitations;
- all earlier failed and interrupted campaigns remain preserved in the decisions/open-burdens
  ledgers rather than being absorbed into the final success.

Required literals:

```text
OFFICIAL_ARC3_RHAE = NOT_MEASURED
PUBLIC_HOLDOUT_CONSUMED = 0/1
NO_ARC3_GENERALIZATION_CLAIM
```

## 9. Human-gated actions not taken

No ARC Prize or Kaggle terms were accepted; no benchmark credentials were used; no public holdout
was opened; no notebook was uploaded; no competition scorecard or submission was created; no money
was spent; no release or DOI was published; no PR was merged; and no external message was sent as
Christopher D. Pang.

Draft PR: `https://github.com/Grativy6/ARC3/pull/7`. It remains draft and must not be merged without
separate owner authorization.
