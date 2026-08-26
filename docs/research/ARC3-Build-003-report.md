# ARC3 Build 003 — BLA–CLEF mechanical learner

**Current build disposition:** `IN_PROGRESS`
**Final preregistered synthetic matrix:** `FAILED_MECHANISM`
**Corrected independent audit:** `FAIL` — 534 genuine evidence-completeness findings
**Official development target:** `NOT_FINISHED`, 4/6 levels after Campaign 28
**Official target completion observed:** `false`
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
`MyAgent -> VisualCausalPolicy -> MechanicalLearner`; action selection remains subject to the
Build 002 lifecycle, legal-action, resource, and tournament-governor boundaries.

The final preregistered synthetic result is negative. The exact one-shot v0.2 matrix contains all
1,200 required rows and 120 sequence receipts, but H1 and H3 failed their literal rules, H2 was not
measured, and action/receipt completeness was only 0.615. The corrected independent audit removed
only 1,158 auditor-generated schema/reconstruction findings and still returned `FAIL` with 462
per-level action/receipt count mismatches and 72 aggregate incomplete-link attestations. This is
not `MECHANISM_CONFIRMED_SYNTHETIC`.

Authorized official non-holdout development play made real progress but did not complete the
target. Campaign 28 ended with the official environment returning `NOT_FINISHED` at 4/6 levels
after 115 `ACTION6` submissions, with zero submitted resets, zero `GAME_OVER`, and zero `WIN`.
Campaign 29 has not started. Only an official returned `GameState.WIN` can change the completion
field.

## 1. Identity, base, and authority

Build 003 branches from merged main `bea1eac99cb0f1b351526b1dc487d132ba1d40ef`, tree
`700718c09c2a1532cea16526b290f57be0120371`. Build 002 head
`5448c53f3b7e08f606cf292e6068f3f9c9db16d4` is ancestral and merge-equivalent by tree. Build 001
remains `PARTIAL` and `SEALED_UNCONSUMED`; Build 002 remains `PARTIAL` with exact evaluation
`BLOCKED_EXTERNAL`. No prior result is retroactively revised.

The Build 003 implementation freeze is:

- branch: `build/003-bla-clef-mechanical-learner`;
- commit: `83df5520478cc209c06d9ce4e658c90786914544`;
- tree: `3d1a45995b004947900de3114449a7e42bd80a87`.

Later commits are evidence, assurance, or documentation only unless a ledgered defect explicitly
reopens the implementation. The exact-freeze package, cold-start, package-only integrity, and
generated-log secret evidence are now recorded below. Draft PR #7 is open; the final documentation
head, exact pushed PR head, current-head CI, and Campaign 29 receipt remain `PENDING_EVIDENCE`.

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
`C:\a\arc3-s15-6a0f6e5\artifacts\stage15\public-environments`, asset SHA-256
`483e583c88e91c2ae58ad1fa7b274d97813993796ce798551a563e1a9a78a7ff`. Its game source was not
semantically inspected. The target ID is evaluation configuration only and is prohibited from
production policy code.

## 2. Architecture delivered

Build 003 adds these bounded mechanisms:

- CLEF-style layer declarations, noise thresholds, readability walls, independent evidence
  families, validity gates, and explicit `PROMOTE`/`PARK`/`STOP` decisions;
- factored predicted and observed consequence vectors covering displacement, object changes,
  resources, inventory, legal actions, topology/reachability, status/animation, score/progress,
  terminal/reset, and delayed/unresolved effects;
- immutable, replay-linked causal action receipts and structured mixed-type residuals;
- a hash-linked versioned mechanic ledger with scope ceilings, evidence provenance, calibrated
  statuses, counterevidence, reopening, supersession, passive confirmation, and bounded active
  state;
- sparse additive, conditional, gating, override, and delayed effect composition;
- local-first repair candidates and deeper reopening only after implicated local explanations fail;
- broad-map exploration with consequence relevance, progress, information value, action savings,
  resource/failure risk, redundancy, bounded candidate counts, and non-grid-search coordinate
  targeting;
- within-game cross-level persistence, level-local reset, same-level failure retention, and
  cross-game quarantine;
- deterministic synthetic curriculum, four-variant ablation, exact frozen comparator, literal
  H1–H3 result gates, production-route profiling, public-evaluation receipts, and read-only
  recording replay.

The learner remains deterministic under its declared seed and bounded by the inherited governor.
No hosted model or remote inference API is required.

## 3. BLA/CLEF source-to-implementation mapping

The source frameworks are used only as bounded software design inputs. They do not control ARC
semantics and their implementation does not validate either framework as a general theory.

| Source mechanism actually used | Bounded software realization | Principal paths | Evidence and limit |
|---|---|---|---|
| CLEF layer declaration `(X, r, N_L, A_L, W_L)` and dynamic action window | Typed logical layers, action windows, readable fields, thresholds, extraction method, and readability wall | `src/arc3/perception/layers.py` | Unit layer tests; operational game layers only, no physical/thermodynamic import |
| CLEF independent evidence families and non-averagable validity gates | Separate evidence readings plus required gates inside `LayerAssessment` | `src/arc3/perception/layers.py` | Failed validity parks evidence rather than being averaged into support |
| CLEF coupling promotion and scale-relevance stopping | `assess_residual` returns `PROMOTE`, `PARK`, or `STOP` for noise, explanation, wall, decision effect, and cost/value reasons | `src/arc3/perception/layers.py`, `src/arc3/exploration/causal_events.py` | Stage 09 adversarial coverage; final H3 still `FAIL` |
| CLEF active-layer pressure and BLA-only comparison | Measured promoted/parked/stopped residuals and active-ledger pressure; ablation can disable CLEF relevance | `evaluation_only/arc3_build003_curriculum/variant_policy.py`, `src/arc3/evaluation/build003_results.py` | H3 pressure median delta was 8.0 and redundant-probe delta 0.0; no benefit claim |
| BLA residual opens a bounded question, not an answer | Predicted/observed consequence comparison emits typed residual records with evidence references and dispositions | `src/arc3/exploration/causal_events.py`, `src/arc3/mechanics/effects.py` | Ten consequence channels remain explicit; unknown/unreadable values are not invented |
| BLA versioned boundary ledger and reopening handle | Append-only hash-linked events, immutable mechanic versions, scoped statuses, evidence/counterevidence, reopen and supersede transitions | `src/arc3/mechanics/models.py`, `src/arc3/mechanics/ledger.py` | Ledger serialization/replay tests; final matrix receipt linkage is incomplete |
| BLA earned support and conservation of still-correct consequences | Distinct-context evidence, passive confirmation, channel-local support, scoped stress/reopen, and transfer confirmation | `src/arc3/mechanics/ledger.py`, `src/arc3/mechanics/learner.py` | Development evidence is positive; H1 final transfer rule failed |
| BLA smallest sufficient repair | At most four ranked local candidates per residual, tracked failures, and deeper reopening after implicated local failures | `src/arc3/mechanics/repair.py`, `src/arc3/mechanics/learner.py` | Stage 09 cases pass; H2 final decision is `NOT_MEASURED` |
| BLA sparse causal composition | Base, additive, conditional, gating, override, and delayed contributions with unresolved ambiguity retained | `src/arc3/mechanics/models.py`, `src/arc3/mechanics/effects.py` | Exact-context override support is occurrence-only; magnitude certainty is not claimed |
| BLA persistence and authority ceilings | Game/level/region/object/state scopes, cross-level retention, same-level failure memory, level-local archival, and cross-game quarantine | `src/arc3/mechanics/learner.py`, `src/arc3/mechanics/ledger.py` | Quarantine is enforced at ledger admission; no two-live-game generalization claim |
| BLA/CLEF economical causal exploration | Relevance-ranked probes, ineffective-action memory, bounded coordinate candidates, readable objects/regions/frontiers, and no whole-grid fallback | `src/arc3/exploration/policy.py`, `src/arc3/exploration/coordinates.py`, `src/arc3/mechanics/visual_causal.py` | Coordinate exhaustion fails closed rather than inventing a target |
| Action-by-action integration and consequence return path | `MyAgent` delegates to `VisualCausalPolicy`, which predicts, selects once, accepts one returned observation, updates the learner, and replans | `agent/my_agent.py`, `src/arc3/mechanics/visual_causal.py`, `src/arc3/evaluation/public_runner.py` | Canonical Campaign 28 replay matched 115 actions/consequences; official state remained `NOT_FINISHED` |

## 4. Synthetic curriculum and ablation

Protocol v0.2 froze 30 held-out cases, ten mechanic families, four variants, and 1,200 required
rows. It binds the exact Build 002 comparator commit/tree, uses 192 actions per sequence, 48 actions
per level attempt, ten resets, ten wall-clock seconds, 1 GiB peak memory, and no row replacement.
The learner process receives only normalized observations and returned consequences, not generator
configuration, seed, family, transition truth, or oracle plan.

Development selection evidence was directionally positive but non-final:

| Variant | Synthetic sequences won | Levels completed | Actions |
|---|---:|---:|---:|
| full BLA+CLEF | 5/5 | 50 | 721 |
| BLA-only persistent | 3/5 | 35 | 797 |
| BLA+CLEF per-level reset | 0/5 | 7 | 960 |
| exact Build 002 | 0/5 | 1 | bounded by five wall-clock exits |

These development seeds selected and debugged the implementation. They are not the final paired
result and do not establish ARC gameplay performance.

### Final one-shot v0.2 matrix

Root: `C:\a\arc3-b003-stage08-v02-final-83df552-01`
Matrix receipt SHA-256: `a01c3dfca5c18d6282e978c07de035932dd28de21491e7a7ea04f8354a0fc8a6`
Rows SHA-256: `8195b470bf4287f4d3246ee82ab349b39a20fb26697c6e714ef1e1aed748f8c0`
Sequence receipts SHA-256: `d5d7d865a4a4b52c42d01601b274744b3603893d8e07495b61d16fd69a9c2d60`

| Result | Literal disposition |
|---|---|
| structure | complete: 1,200 rows, 120 sequences, 30 cases, four variants |
| terminal counts | 47 synthetic `WIN`, 43 `ACTION_BUDGET`, 30 `WALL_CLOCK_BUDGET` |
| H1 transfer | `FAIL`: later-level exploratory-action paired median delta 2.0, not strictly lower; treatment completions 250 versus 64 reference |
| H2 conservative repair | `NOT_MEASURED`: incomplete modifier assessment/retention and unmeasured erroneous global reopenings; 545 scoped revisions |
| H3 CLEF relevance | `FAIL`: redundant-probe median delta 0.0; active-ledger-pressure median delta 8.0; action medians both 14, ratio 1.0 |
| evidence quality | `FAILED`: replay determinism 1.0; receipt completeness 0.615; zero infrastructure rows; zero policy-error rows |
| wall time | 133.42792640000698 seconds |
| overall | `FAILED_MECHANISM` |

The result is an immutable synthetic anti-result. No row may be rerun, replaced, omitted, or
post-selected.

### Independent audit

The first audit at `C:\a\arc3-b003-stage08-v02-final-83df552-01-audit` remains immutable `FAIL`
with 1,692 findings. Independent diagnosis separated 1,158 auditor defects from 534 genuine matrix
evidence failures. Assurance-only commit `d3d8eddb85549550ddc6629de4aa32e202ef897a` fixed only the
auditor schema and per-level reconstruction defects.

The corrected source-projected audit at
`C:\a\arc3-b003-stage08-v02-final-83df552-01-audit-v3-d3d8edd-source-projected` returned `FAIL`
with exactly:

- 462 per-level action/receipt count mismatches;
- 72 truthful aggregate incomplete-link attestations;
- zero schema, row-cascade, source-mutation, infrastructure, or policy errors.

Thirteen of fourteen checks passed; only sequence replay links and counters failed. Audit receipt
SHA-256 is `518cc61bdf981a2c6537bda321c27d46d66deb95974f0bedc922db040e0a0c89`,
report SHA-256 is `86f1a33c0b6ca8cbdb122619d6a9d5554d430651c3c6160865a2d5889994d046`,
sealed payload SHA-256 is `fda2cc01f12746abbb98b44d8d3513161366e0b8b3c4be8876d65eccb564dde3`,
and the matrix-root manifest remained
`747e4c35b13f68714548b8af196ced026e555f8c33491dff5d942b5baab88389` before and after.

## 5. Required adversarial cases

All sixteen named Stage 09 obligations have bounded observation-grounded tests or development
comparison evidence, including provisional movement/resource inference, distinct-context support,
failure/reset linkage, localized restoration, additive-versus-override discrimination, cross-level
transfer, visual remapping, decorative-change parking, consequence relevance, deeper reopening,
bounded coordinate behavior, failed-root avoidance, cross-game quarantine, evaluator isolation,
and measured ablation loss.

This Stage 09 `PASS` is narrower than the final matrix. Limits remain explicit: override evidence
is occurrence-only and exact-resource-context localized; failed-root and level-boundary memory are
bounded; coordinate-only exhaustion fails closed; and cross-game evidence covers ledger admission,
not a claim of live multi-game generalization.

## 6. Official non-holdout development play

The target is `r11l-495a7899`, repository partition `development`, evidence surface
`local-public-source-preview-exposed`, with six declared levels. Public development play was
explicitly authorized. It is not the sealed public holdout and does not produce official RHAE.

Campaign 28 is the latest authoritative receipt:

| Receipt field | Value |
|---|---|
| evaluation ID | `build003-r11l-mechanical-seed7-4a9ebb4-campaign28` |
| frozen policy commit | `4a9ebb4798003c5c1d3d6eedae352fc414a998fe` |
| final environment state | `NOT_FINISHED` |
| levels completed | 4/6 |
| `win_levels` | 6 |
| observations | 116 |
| submitted actions | 115 |
| non-reset actions | 115 |
| submitted resets | 0 |
| initial SDK reset returns | 1, not a submitted action |
| `GAME_OVER` events | 0 |
| `WIN` events | 0 |
| completion genuinely observed | `false` |

Both observed child strata, equal-weight composition, and endpoint-arity-weighted composition were
officially tested, returned `NOT_FINISHED`, and were exactly recovered without target damage or
hierarchy-lineage loss. The evaluator then failed closed after the 115th consequence because every
parser-safe continuation in those families was exhausted. No action 116 was submitted.

The sealed recording is
`C:\a\arc3-b003-play\build003-r11l-mechanical-seed7-4a9ebb4-campaign28\official-recordings\c2120ed7e4beb839e4d0\fd7275c9-50b1-43b4-90fa-18c9e1121d30\r11l-495a7899-7685d115-40b6-47d5-9eb8-64296f242331.jsonl`,
SHA-256 `154f3e1f862dfd47c08607fcfa84546bb9f0b23e85841fe4242772ed9d1637fd`.
The integrity replay receipt is
`C:\a\arc3-b003-play\campaign28-4a9ebb4-154f3e1f-integrity-replay-receipt.json`, SHA-256
`45da1c1537f734f2ac9b34b131d01ed1df57eec742c3a35a98e09e73cf9a1222`.

The implementation-freeze canonical replay matched all 115 recorded selections and consequences,
then derived and cancelled an unsubmitted observation-only candidate. Its receipt is
`C:\a\arc3-b003-play\campaign28-83df552-154f3e1f-canonical-replay-receipt.json`, SHA-256
`a31eccb229279a965c7a66dc93c80f40b061ee21401591577fe7f6dda2c42bb2`. Replay is readiness
evidence only; it is not official progress.

The shared public-exposure ledger contains 53 development events, zero holdout events, last
sequence 52, tail hash
`sha256:3c3e851f18a81451079beebe7b2233690b4011495a9fb2b876f14909400c5695`, and file SHA-256
`b3feda3d24756cb279ac7a9fbbeed1b301fd19c6953ea997a20535d20c20233a`.

Campaign 29 has not started. Its final state, levels completed, `win_levels`, action counts,
reset count, replay/evidence path, verification status, and genuinely-observed completion field are
all `PENDING_EVIDENCE`. They must not be inherited from Campaign 28 or populated from replay.

## 7. Performance, package, and verification

The matched synthetic production-route profile passed at the implementation freeze. Every Build
003 cycle reached the mechanical route; maximum cycle time was 0.0559292 seconds and maximum peak
RSS was 77,959,168 bytes. Relative to the matched Build 002 route, Build 003 was faster but used
26,386,432 more peak RSS bytes. Receipt:
`C:\a\b003-profile-final-83df552.json`, SHA-256
`caa48466570b4c55ac1fe324071cc7be000ea0b9222d6d043510e0033d256596`.
This is synthetic runtime evidence, not gameplay or RHAE.

The production action-semantics scan had zero findings. Receipt:
`C:\a\b003-action-semantics-final-83df552.json`, SHA-256
`4615ff438676d992f09e6cbbfdda78bf72443806939c1fe31bf6929d3a2c965d`.

The earlier Linux package-only wrapper at `91c5f26` remains a preserved failure: 1,012 tests passed,
but the no-child-process guard correctly rejected 725 child-RSS reads caused by a transitive
process-backed development-performance test. The freeze excludes that test only from the
no-child-process package-only profile; ordinary CI retains it.

The exact `83df552` source was independently cloned at `C:\a\s3f83`. Two offline package builds
completed successfully and produced byte-identical candidates. The frozen package at
`C:\a\o3f83\package-a\arc3-kaggle-candidate.zip` has SHA-256
`d83efdd5c08b082ec8f1402120e75645b15e960fa954e42eb33fd116ee875ee8`; its first-party payload is
`sha256:27bfe4fd15459d20fa1750c4e4bbe69cb1873ded13db26b43030f7866def1e16`, package manifest
`sha256:81a53eb9a26a8d251370b652478493d5fb309610ed5e37f23fad183d7792f94c`, SBOM
`sha256:45d81bef6a94c987a3e5db078a2cab6f48fbe5aa7762bed84111850507255106`, and build receipt
`sha256:c2cc69ece59767a0999b1b4c9e3bd03103c41341ca08236943ebb6b7bf322423`. The two builds took
25.5815 and 22.2563 seconds, with sampled peak RSS of 165,130,240 and 153,407,488 bytes. The payload
contains 31 pinned Linux CPython 3.12 wheels.

The package cold-start check passed in 3.0803145 seconds with 73,826,304 sampled peak RSS. Its
embedded startup path took 2.8182920 seconds, including a 2.5552326-second import and a
0.0001277-second agent instantiation, with zero network and zero process attempts. The package-only
integrity receipt at `C:\a\o3f83\integrity-receipt.json`, SHA-256
`5ff2932b4cd5de6868652ec4b4d87f668207a53f8be4aaa12cb0ba4d513effd2`, reports
`package_only_passed=true`; its top-level `passed=false` only because public-identifier semantics
are intentionally `NOT_EVALUATED` in package-only mode. The generated-log scan covered the 22
persisted redacted stdout/stderr logs and returned zero findings or redactions; it does not claim
every raw sealed byte was scanned. The additional full static lock-only scan at `C:\a\i3f83.json`,
SHA-256 `6d83a04b1a2e652f60ad8dbb8cf401c6baa24f3bfb12b961a848cd39d5c33ffa`, passed source identity,
policy, archive, and secret sub-checks but has top-level `passed=false`: supply-chain evaluation is
explicitly `NOT_EVALUATED` under that lock-only scope, with 60 nonblocking
`dependency-license-not-evaluated` warnings.

The integrated exact-freeze verifier is nevertheless preserved as `FAILED_INFRASTRUCTURE`: its
guarded test phase exceeded the fixed 2,400-second limit at 84 percent. Receipt:
`C:\a\o3f83\release-verification-receipt.json`, SHA-256
`35e84860f5c167677cfaa1de45fa903e099fff895a73e0ff81de0e366fd72ddb`. All 45 hashes declared by
that receipt still match with zero missing or mismatched files, but the historical sealed artifact
set remains explicitly incomplete because the verifier failed. A separate no-deadline
exact-source recovery collected 1,022 tests and found one genuine synthetic-lab generator defect,
with 1,018 inferred passes, three skips, and zero guard attempts. Its raw wrapper disposition is
`FAILED_BOUNDARY`, classified here as `FAILED_MECHANISM` because the failure was an unsolvable
synthetic case rather than a path-boundary crossing. Receipt:
`C:\a\o3f83\package-only-test-guard-recovery.json`, SHA-256
`a2b21eeb5c4a7ac7448ecfd9abdaf77902cf8ceaba12d0dde462c68d23d31a1a`.

Post-freeze assurance commit `48bd18d09ec82c06150dbcba7b72370781eb21de` prevents supplemental
synthetic anchors from aliasing and pins the failing Hypothesis seed. The exact property regression
passed 3 tests; the combined synthetic-lab suite passed 17 tests; Ruff, formatting, and strict mypy
passed. `src/arc3/lab` contributes zero of the frozen first-party archive's 114 members, so this
repair does not alter the competition executable payload or reopen the `83df552` production and
Campaign 29 policy freeze.

Current terminal verification status is:

| Gate | Status |
|---|---|
| exact `83df552` offline package candidate and hashes | `PASS`; deterministic A/B package |
| exact-freeze cold start | `PASS`; zero network/process attempts |
| exact-freeze package-only integrity | `package_only_passed=true`; top-level `passed=false` because public identifiers are `NOT_EVALUATED` by scope |
| exact-freeze generated-log secret scan | `PASS` for 22 persisted redacted logs; zero findings/redactions |
| exact-freeze full static lock-only scan | top-level `passed=false`; four sub-checks `PASS`, supply chain `NOT_EVALUATED` by scope |
| integrated exact-freeze verifier | `FAILED_INFRASTRUCTURE`; test timeout preserved |
| standalone exact-freeze guarded test recovery | `FAILED_MECHANISM`; synthetic generator defect preserved and repaired post-freeze |
| current documentation-head Linux package-only CI | `PENDING_EVIDENCE` |
| current documentation-head ordinary Ubuntu/Windows CI | `PENDING_EVIDENCE` |
| final documentation commit/tree | `PENDING_EVIDENCE` |
| draft pull request | `OPEN_DRAFT`: #7; exact final pushed head `PENDING_EVIDENCE` |

No CI or documentation value may be copied from Build 002 or an earlier Build 003 commit to fill
the remaining fields. The exact-freeze package evidence is bound only to `83df552`.

Draft PR: `https://github.com/Grativy6/ARC3/pull/7`. It must remain unmerged.

## 8. Stage disposition

| Stage | Current status | Bounded result |
|---:|---|---|
| 00 | `PASS` | source/base/authority and non-holdout target identity verified |
| 01 | `PASS` | Build 002 baseline frozen; one reproducible Windows host-topology failure retained |
| 02 | `PASS` | readable state, ten consequence channels, prediction/action links, production reachability |
| 03 | `PASS` | BLA residual lifecycle, passive confirmation, scoped repair and reopening |
| 04 | `PASS` | CLEF promote/park/stop and behaviorally distinct BLA-only path |
| 05 | `PASS` | bounded exploration/planning integrated with the existing governor |
| 06 | `PASS` | cross-level persistence, composition, reset retention, cross-game quarantine |
| 07 | `PASS` | hidden procedural curriculum and privilege boundary |
| 08 | `FAILED_MECHANISM` | exact final v0.2 H1/H3 fail, H2 not measured, receipt completeness 0.615 |
| 09 | `PASS` | all sixteen required adversarial obligations covered within declared limits |
| 10 | `IN_PROGRESS` | Campaign 28 `NOT_FINISHED`; package evidence complete, current-head CI and Campaign 29 remain |
| 11 | `IN_PROGRESS` | report, handoff, and index drafted; final hashes/PR/CI remain pending |

## 9. Claim boundary and open burdens

Build 003 cannot report `MECHANISM_CONFIRMED_SYNTHETIC`. It cannot claim official target
completion, ARC3 generalization, official RHAE, validation of BLA/CLEF as general theories, AGI,
consciousness, or a general theory of intelligence.

The material open burdens are:

- Campaign 29 and later authorized non-holdout development play must continue until the official
  environment returns `GameState.WIN` or an exact external boundary prevents real play;
- the final matrix's 534 genuine action/receipt linkage findings remain unresolved and immutable;
- H1 and H3 failed, and H2 remains `NOT_MEASURED`;
- the integrated exact-freeze verifier timed out and the standalone recovery exposed one synthetic
  generator defect; both failures remain preserved even though package, cold-start, integrity, and
  secret sub-gates passed and the defect was repaired post-freeze;
- current-head CI remains `PENDING_EVIDENCE`;
- the independent Campaign 28 integrity receipt reports
  `trace_manifest_object_hash_verified=false` even though the authoritative evaluator and exact
  replay passed; that discrepancy is not relabeled true;
- pixel-only inventory interpretation, topology without behavioral evidence, one-off delayed
  consequences, and exact-resource-context override magnitude remain bounded limitations;
- official ARC3 RHAE and private Kaggle compatibility remain `NOT_MEASURED`.

## 10. Human-gated actions not taken

No ARC Prize or Kaggle terms were accepted; no credentials were used; no public holdout was opened;
no notebook was uploaded; no scorecard or submission was created; no money was spent; no release or
DOI was published; no PR was merged; and no external message was sent as Christopher D. Pang.

The next autonomous step is to seal and push the documentation-only head, obtain current-head CI,
then start a fresh Campaign 29 official development session from the exact `83df552` learner. The
draft PR must remain unmerged.
