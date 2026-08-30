# ARC3 Build 003 — Owner handoff

## Disposition

- **Overall:** `BUILD 003: PARTIAL`; workflow execution complete
- **Branch:** `build/003-bla-clef-mechanical-learner`
- **Successful-play implementation freeze:** `eab4497a6033bd27102ed99d4d2e43f6ab708ec4`
- **Implementation tree:** `17bb7e126034f6ccf8a5d24becd8163629e33757`
- **Draft pull request:** #7, `OPEN_DRAFT`, unmerged
- **Official development target:** `WIN`, 6/6 levels in Campaign 52
- **Official target completion observed:** `true`
- **Final synthetic matrix:** `FAILED_MECHANISM`
- **Corrected independent audit:** `FAIL`, 534 genuine findings
- **Official ARC3 RHAE:** `NOT_MEASURED`
- **Public holdout consumed:** `0/1`
- **Claim boundary:** `NO_ARC3_GENERALIZATION_CLAIM`

Christopher D. Pang is author and steward. AI systems were development tools and assistants, not
co-authors, owners, or independent authorities.

## Outcome

The primary requested gameplay outcome was genuinely achieved. The official public-development
environment returned `GameState.WIN` for `r11l-495a7899` after the mechanical learner completed all
six levels. The terminal action was `ACTION6 (14,60)`. The raw recording, trace, run receipt,
completion receipt, and pinned local scorecard all agree on `WIN`, `levels_completed=6`, and
`win_levels=6`.

This is one repeatedly exposed public-development game, not a hidden-game transfer result. The
evaluator correctly retains `MECHANISM_NOT_OBSERVED`, and the final synthetic experiment remains a
negative mechanism result.

## What Build 003 delivered

- typed CLEF-style layer declarations, readability/noise gates, and auditable
  `PROMOTE`/`PARK`/`STOP` decisions;
- predicted, observed, explained, and residual consequence vectors over ten effect channels;
- replay-linked action receipts and a versioned hash-linked BLA mechanic ledger;
- scoped support, passive confirmation, stress, reopening, revision, and supersession;
- sparse additive, conditional, gating, override, and delayed causal composition;
- local-first repair and implicated-only deeper reopening;
- relevance-ranked bounded exploration without whole-grid brute force;
- within-game cross-level persistence, level-local reset, same-level failure memory, and cross-game
  quarantine;
- deterministic curriculum, ablation, replay, public evaluation, packaging, integrity, and
  prelaunch audit tooling.

The source-to-implementation mapping is in `docs/research/ARC3-Build-003-report.md`; the final
machine-readable completion receipt is `docs/evidence/003-10-official-development-win.json`.

## Authoritative completion receipt

| Required receipt field | Value |
|---|---|
| game ID | `r11l-495a7899` |
| evaluation ID | `build003-r11l-mechanical-seed7-eab4497-campaign52` |
| final environment state | `WIN` |
| levels completed | 6/6 |
| `win_levels` | 6 |
| submitted actions including resets | 429 |
| non-reset environment actions | 424 |
| submitted resets | 5 |
| final action | official action 429, `ACTION6 (14,60)` |
| recording observations | 430 |
| `NOT_FINISHED` / `GAME_OVER` / `WIN` consequences | 423 / 5 / 1 |
| completion genuinely observed | `true` |

Evidence root:
`C:\a\arc3-b003-play\build003-r11l-mechanical-seed7-eab4497-campaign52`.

Principal hashes:

- recording:
  `sha256:441ca0be8f956b8b07c52c8ba5f24e0b485618f06231248c7e6ce579f7d48fbe`;
- run/result file:
  `sha256:8b7f653e914f44276108b34af1bf37f74ce66c6a6f094e7b6eb3ab0dc723e069`;
- run receipt:
  `sha256:9826969ef86358f9d58d5d66b0bdd09034d8c2a8835ed8eea456ed3fb19260e1`;
- completion receipt:
  `sha256:84030e25bd09e812d7bd15948d9f785a3d9e9468e99d0534f7e6f91e3ad4181c`;
- trace chunk:
  `sha256:3c0338cc43b27740d3a0b91e4cd40a5bb36864c5f72d5ec7b1936d5a1a888436`;
- trace manifest object:
  `sha256:ef4c11fc2c60a12cdb0a3f01f119e0611ae93fbf3de0834ea82ade7cc6517364`;
- trace tail:
  `sha256:91f3e24a39fea6a823139e148b33f5f695b8dc9dd3cd0b666910d2b36dba0f0e`.

The canonical verifier returned `verified=true`, 613 artifacts, one run, and zero errors. The
recording has 430 rows; the trace has 2,575 events. All 429 selected, submitted, returned, and
mechanics-receipt actions reconcile exactly.

The public-exposure ledger has 101 development events, zero holdout events, final sequence 100,
tail `sha256:157773149e8dfa20c2f624ffc2a811635786aaf29ed12912b3a7d53e2630af40`,
and file SHA-256 `1dbfe3e9b29dae81083fddc1e69ba7dca35e67b3f030d633cf90b56342fcb000`.

## Synthetic result retained

The exact v0.2 matrix at `C:\a\arc3-b003-stage08-v02-final-83df552-01` remains immutable:

| Field | Result |
|---|---|
| coverage | 1,200 rows, 120 sequences, 30 cases, four variants |
| terminal counts | 47 synthetic `WIN`, 43 `ACTION_BUDGET`, 30 `WALL_CLOCK_BUDGET` |
| H1 transfer | `FAIL` |
| H2 conservative repair | `NOT_MEASURED` |
| H3 layer relevance | `FAIL` |
| replay determinism | 1.0 |
| action/receipt completeness | 0.615 |
| matrix status | `FAILED_MECHANISM` |

The corrected audit retains 462 per-level action/receipt count mismatches and 72 aggregate
incomplete-link attestations. No row was rerun, replaced, omitted, or reclassified.

## Verification and package

Exact `eab4497` prelaunch evidence passed before Campaign 52:

- Campaign 51 full replay: 424 matching action/consequence/receipt cycles, zero environment actions;
- clean-source selection: 119 passed, three expected skips;
- replay/CLI/audit selection: 82 passed;
- full visual-policy module: 155 passed;
- Ruff lint/format, strict MyPy, manifest integrity, package-only integrity, action semantics, and
  sanitized prelaunch audit: pass;
- hosted CI: five of five workflows and nine of nine jobs passed.

Ordinary exact-freeze CI totals were 1,881 passed / 10 skipped on each Ubuntu PR/push job and 1,871
passed / 20 skipped on each Windows PR/push job. Ruff passed and strict MyPy checked 207 source
files without findings.

The exact-freeze package artifact from hosted run `33288733132` is preserved at
`C:\a\arc3-c52-package-artifact-eab4497-push`:

| Field | Value |
|---|---|
| candidate SHA-256 | `432bdf0ae61f5c960f7372c6b07c1e1393fa52f764f1997ab0d450b2f3459639` |
| payload SHA-256 | `95394d1722ec9590980e51444542ad0f9755f52e98b0f6274af773bafde2d0a5` |
| package manifest SHA-256 | `acf091dd0ae701a9bc8c80d3770bb05b0165b971c07f72798349b0712edab377` |
| SBOM SHA-256 | `05ec473913d86194ae56582dd8cfbf2e0c7dccc7fcfdb87ca19e7da657e3f97c` |
| deterministic A/B | `true` |
| package-safe suite | 1,130 passed, three skipped, zero guard attempts |
| cold start | 1.2002791 seconds; 84,910,080 sampled peak RSS bytes |
| network/process attempts | 0 / 0 |

The release wrapper remains `BLOCKED_EXTERNAL` only at the exact private Kaggle surface; all scoped
non-private checks pass. No private wheels, gateway, scorer, or Agents input were acquired or used.

## Preserved failures and remaining burdens

- Stage 08 remains `FAILED_MECHANISM`; H1/H3 failed and H2 is `NOT_MEASURED`.
- The corrected audit remains `FAIL` with 534 genuine linkage findings.
- Campaigns 1–51 remain immutable failure or interruption evidence; Campaign 52 does not rewrite
  them. Campaigns 50 and 51 remain official `NOT_FINISHED` failures at 5/6.
- Repeated public-game iteration creates material overfit risk; one win is not ARC3 generalization.
- Official ARC3 RHAE and exact private Kaggle compatibility remain `NOT_MEASURED` /
  `BLOCKED_EXTERNAL`.
- Historical infrastructure and incomplete-recording failures remain in the open-burdens ledger.

Required literals:

```text
OFFICIAL_ARC3_RHAE = NOT_MEASURED
PUBLIC_HOLDOUT_CONSUMED = 0/1
NO_ARC3_GENERALIZATION_CLAIM
```

## Human gates

No ARC Prize or Kaggle terms were accepted; no benchmark credentials were used; no holdout was
opened; no notebook was uploaded; no online/Kaggle scorecard or official submission was created;
no money was spent; no release or DOI was published; no PR was merged; and no external message was
sent as Christopher D. Pang. The pinned local `ScorecardManager` did produce the verified local
public-development scorecard cited above; it is not an online or competition scorecard.

## Owner action

Review draft PR #7 at `https://github.com/Grativy6/ARC3/pull/7`. It remains draft and unmerged.
Merging or any other human-gated action requires separate explicit authorization.
