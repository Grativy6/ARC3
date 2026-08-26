# ARC3 Build 003 — Owner handoff

## Disposition

- **Overall:** `BUILD 003: IN_PROGRESS`
- **Branch:** `build/003-bla-clef-mechanical-learner`
- **Implementation freeze:** `83df5520478cc209c06d9ce4e658c90786914544`
- **Implementation tree:** `3d1a45995b004947900de3114449a7e42bd80a87`
- **Final documentation head:** `PENDING_EVIDENCE`
- **Draft pull request:** #7, `OPEN_DRAFT`; exact final pushed head `PENDING_EVIDENCE`
- **Final synthetic matrix:** `FAILED_MECHANISM`
- **Corrected independent audit:** `FAIL`, 534 genuine findings
- **Latest official development state:** `NOT_FINISHED`, 4/6 levels after Campaign 28
- **Official target completion observed:** `false`
- **Campaign 29 receipt:** `PENDING_EVIDENCE`
- **Official ARC3 RHAE:** `NOT_MEASURED`
- **Public holdout consumed:** `0/1`
- **Claim boundary:** `NO_ARC3_GENERALIZATION_CLAIM`

Christopher D. Pang is author and steward. AI systems were development tools and assistants, not
co-authors, owners, or independent authorities.

## What Build 003 delivered

Build 003 preserves Build 001/002 evidence and adds a bounded mechanical-learning route:

- typed CLEF-style layer declarations, readability/noise gates, and auditable
  `PROMOTE`/`PARK`/`STOP` decisions;
- predicted, observed, explained, and residual consequence vectors over ten effect channels;
- replay-linked action receipts with observation references and terminal-state accounting;
- a versioned, hash-linked BLA mechanic ledger with scope, evidence provenance, passive
  confirmation, stress, reopening, revision, and supersession;
- sparse additive, conditional, gating, override, and delayed causal composition;
- local-first repair, bounded candidate explanations, and deeper reopening after implicated local
  failures;
- relevance-ranked exploration and coordinate targeting without whole-grid brute force;
- mechanic retention across levels, level-local reset, same-level failure memory, and cross-game
  quarantine;
- production integration through `agent/my_agent.py`,
  `src/arc3/mechanics/visual_causal.py`, and `src/arc3/mechanics/learner.py`;
- a deterministic hidden synthetic curriculum, exact Build 002 comparator, four-variant ablation,
  literal H1–H3 decisions, independent audit, production-route profile, and official public-run
  completion receipts.

The full BLA/CLEF source-to-implementation mapping is in
`docs/research/ARC3-Build-003-report.md` and machine-readable form in
`docs/evidence/003-final-evidence-index.json`.

No hosted model call, game-ID branch, fixed target coordinate, walkthrough, game-source inspection,
holdout access, credential, terms acceptance, upload, submission, paid compute, release, merge, or
external representation was used.

## Final synthetic experiment

The exact preregistered v0.2 root is
`C:\a\arc3-b003-stage08-v02-final-83df552-01`.

| Field | Result |
|---|---|
| coverage | 30 held-out cases × 10 families × four variants = 1,200 rows |
| sequences | 120 |
| terminal counts | 47 synthetic `WIN`; 43 `ACTION_BUDGET`; 30 `WALL_CLOCK_BUDGET` |
| H1 transfer | `FAIL`; later-level exploration paired median delta 2.0 |
| H2 conservative repair | `NOT_MEASURED`; 545 scoped revisions but required assessment incomplete |
| H3 layer relevance | `FAIL`; redundant-probe median delta 0.0, pressure median delta 8.0 |
| replay determinism | 1.0 |
| action/receipt completeness | 0.615 |
| infrastructure/policy-error rows | 0 / 0 |
| matrix status | `FAILED_MECHANISM` |

Principal hashes:

- matrix receipt:
  `sha256:a01c3dfca5c18d6282e978c07de035932dd28de21491e7a7ea04f8354a0fc8a6`;
- rows:
  `sha256:8195b470bf4287f4d3246ee82ab349b39a20fb26697c6e714ef1e1aed748f8c0`;
- sequence receipts:
  `sha256:d5d7d865a4a4b52c42d01601b274744b3603893d8e07495b61d16fd69a9c2d60`.

This result is immutable. It must not be rerun, subsetted, replaced, or reclassified as a pass.
The 47 synthetic `WIN` sequences are not target-game completion.

## Corrected audit

The first audit remains immutable `FAIL` with 1,692 findings. Of these, 1,158 were auditor schema
or reconstruction defects and 534 were genuine evidence failures. Assurance-only commit
`d3d8eddb85549550ddc6629de4aa32e202ef897a` corrected only the auditor.

The source-projected audit at
`C:\a\arc3-b003-stage08-v02-final-83df552-01-audit-v3-d3d8edd-source-projected`
still returned `FAIL` with exactly 534 findings:

- 462 per-level action/receipt count mismatches;
- 72 aggregate incomplete-link attestations.

Thirteen of fourteen checks passed and the matrix remained unchanged. Receipt SHA-256 is
`518cc61bdf981a2c6537bda321c27d46d66deb95974f0bedc922db040e0a0c89`; report SHA-256 is
`86f1a33c0b6ca8cbdb122619d6a9d5554d430651c3c6160865a2d5889994d046`; sealed payload SHA-256 is
`fda2cc01f12746abbb98b44d8d3513161366e0b8b3c4be8876d65eccb564dde3`.

## Official development play receipt

Campaign 28 is the latest authoritative official non-holdout development evidence.

| Required receipt field | Value |
|---|---|
| game ID | `r11l-495a7899` |
| evaluation ID | `build003-r11l-mechanical-seed7-4a9ebb4-campaign28` |
| final environment state | `NOT_FINISHED` |
| levels completed | 4/6 |
| `win_levels` | 6 |
| submitted action count | 115 |
| non-reset environment actions | 115 |
| submitted resets | 0 |
| `GAME_OVER` / `WIN` | 0 / 0 |
| replay/evidence | `C:\a\arc3-b003-play\campaign28-4a9ebb4-154f3e1f-integrity-replay-receipt.json` |
| completion genuinely observed | `false` |

The official recording is
`C:\a\arc3-b003-play\build003-r11l-mechanical-seed7-4a9ebb4-campaign28\official-recordings\c2120ed7e4beb839e4d0\fd7275c9-50b1-43b4-90fa-18c9e1121d30\r11l-495a7899-7685d115-40b6-47d5-9eb8-64296f242331.jsonl`,
SHA-256 `154f3e1f862dfd47c08607fcfa84546bb9f0b23e85841fe4242772ed9d1637fd`.
The integrity replay SHA-256 is
`45da1c1537f734f2ac9b34b131d01ed1df57eec742c3a35a98e09e73cf9a1222`.

The implementation-freeze canonical replay at
`C:\a\arc3-b003-play\campaign28-83df552-154f3e1f-canonical-replay-receipt.json`, SHA-256
`a31eccb229279a965c7a66dc93c80f40b061ee21401591577fe7f6dda2c42bb2`, matched all 115 recorded
selections and consequences. It issued no official action and does not change `NOT_FINISHED`.

Campaign 29 has not started. Its game ID, final state, levels completed, `win_levels`, total and
non-reset action counts, reset count, replay/evidence paths, verification, and genuine-completion
fields remain `PENDING_EVIDENCE`. Do not populate them from Campaign 28 or recorded-frame replay.

## Performance and verification boundary

At the implementation freeze, the matched synthetic `MyAgent` profile reached the mechanical route
in every cycle. Maximum cycle time was 0.0559292 seconds and maximum peak RSS was 77,959,168 bytes.
Build 003 used 26,386,432 more peak RSS bytes than the matched Build 002 route. Profile receipt:
`C:\a\b003-profile-final-83df552.json`, SHA-256
`caa48466570b4c55ac1fe324071cc7be000ea0b9222d6d043510e0033d256596`.
This is synthetic performance evidence only.

The action-semantics scan had zero findings at
`C:\a\b003-action-semantics-final-83df552.json`, SHA-256
`4615ff438676d992f09e6cbbfdda78bf72443806939c1fe31bf6929d3a2c965d`.

The earlier package-only result at `91c5f26` remains a preserved boundary failure despite 1,012
passing tests: a transitive process-backed test produced exactly 725 denied child-RSS reads.
Commit `83df552` narrows the package-only profile without removing that test from ordinary CI.

The exact `83df552` offline package was built twice from `C:\a\s3f83`; both copies were byte
identical. The candidate is `C:\a\o3f83\package-a\arc3-kaggle-candidate.zip`, SHA-256
`d83efdd5c08b082ec8f1402120e75645b15e960fa954e42eb33fd116ee875ee8`. Its first-party payload,
manifest, SBOM, and build-receipt hashes are respectively
`27bfe4fd15459d20fa1750c4e4bbe69cb1873ded13db26b43030f7866def1e16`,
`81a53eb9a26a8d251370b652478493d5fb309610ed5e37f23fad183d7792f94c`,
`45d81bef6a94c987a3e5db078a2cab6f48fbe5aa7762bed84111850507255106`, and
`c2cc69ece59767a0999b1b4c9e3bd03103c41341ca08236943ebb6b7bf322423`.

Cold start passed in 3.0803145 seconds with 73,826,304 sampled peak RSS and zero network or process
attempts. Package-only integrity reports `package_only_passed=true`; its top-level `passed=false`
only because public-identifier semantics are intentionally `NOT_EVALUATED` in that mode. The
generated-log scan covered 22 persisted redacted stdout/stderr logs with zero findings or
redactions; it is not a claim about every raw sealed byte. The full static lock-only receipt also
has top-level `passed=false`: source, policy, archive, and secret sub-checks pass, while supply chain
is explicitly `NOT_EVALUATED` by scope with 60 nonblocking warnings.

Two failures remain preserved. The integrated verifier receipt at
`C:\a\o3f83\release-verification-receipt.json`, SHA-256
`35e84860f5c167677cfaa1de45fa903e099fff895a73e0ff81de0e366fd72ddb`, is
`FAILED_INFRASTRUCTURE` because its guarded tests exceeded the fixed 2,400-second limit. The
receipt's 45 declared artifact hashes currently match with no missing or mismatched file, but its
sealed artifact set remains explicitly incomplete. The
no-deadline recovery receipt at `C:\a\o3f83\package-only-test-guard-recovery.json`, SHA-256
`a2b21eeb5c4a7ac7448ecfd9abdaf77902cf8ceaba12d0dde462c68d23d31a1a`, is classified
`FAILED_MECHANISM`: one unsolvable procedural synthetic-lab case failed, 1,018 tests inferred
passed, three skipped, and zero guard attempts occurred. Post-freeze commit
`48bd18d09ec82c06150dbcba7b72370781eb21de` repaired distinct supplemental anchors and added the
exact regression. Its focused 3-test property run and 17-test combined lab suite passed, as did
Ruff, formatting, and strict mypy. The synthetic lab contributes zero of 114 members in the frozen
competition payload, so the production/Campaign 29 freeze remains `83df552`.

These terminal gates remain deliberately `PENDING_EVIDENCE`:

- current documentation-head package-only CI;
- current documentation-head ordinary Ubuntu/Windows CI and exact totals;
- final documentation commit/tree;
- draft PR URL and exact pushed head;
- all Campaign 29 official completion fields.

## Preserved failures and unresolved burdens

- The final synthetic matrix is `FAILED_MECHANISM`; H1 and H3 failed, H2 is `NOT_MEASURED`, and
  receipt completeness is 0.615.
- The corrected audit remains `FAIL` with 534 genuine linkage findings.
- Campaign 28 remains `NOT_FINISHED` at 4/6; no `WIN` was observed.
- The integrated exact-freeze verifier remains `FAILED_INFRASTRUCTURE`; its standalone recovery
  remains `FAILED_MECHANISM` despite the narrow post-freeze synthetic assurance repair.
- The Campaign 28 independent integrity receipt reports
  `trace_manifest_object_hash_verified=false` while the authoritative verifier and replay pass.
- Exact-context override support is occurrence-only and does not establish magnitude certainty.
- Pixel-only inventory, topology without behavioral evidence, and one-off delayed consequences
  remain bounded limitations.
- Official ARC3 RHAE and exact private Kaggle compatibility remain `NOT_MEASURED`.
- Passing tests, synthetic `WIN`, replay, a level transition, or a complete-looking mechanic map
  cannot substitute for official `GameState.WIN`.

## Human gates

These actions were not taken and remain explicitly owner-gated:

- accept ARC Prize or Kaggle terms;
- use credentials or request a Kaggle token;
- access the sealed public holdout or spend the `0/1` authority;
- upload a notebook, open an online scorecard, or submit to a competition;
- purchase compute or spend money;
- publish a release or DOI;
- merge the draft PR;
- send an external message or represent Christopher D. Pang.

Current values remain: terms `false`, credentials `false`, holdout accessed `false`, upload
`false`, submission `false`, money spent `false`, release `false`, PR merged `false`, and external
message sent as owner `false`.

## Next actions

1. Push the documentation-only head and obtain exact current-head Ubuntu/Windows and package-only
   CI receipts.
2. Replace only the explicit `PENDING_EVIDENCE` fields with returned evidence and hashes.
3. Start Campaign 29 from a fresh authorized `development` session using the frozen learner.
4. Continue action by action while the official environment returns `NOT_FINISHED`; preserve
   `GAME_OVER`, issue only legal `RESET`, revise the implicated scope, and continue.
5. Terminate successfully only when the official environment itself returns `GameState.WIN`.
6. Open or update the draft PR. Do not merge it.

The smallest owner-only action remains review of the eventual draft PR. Any merge or other
human-gated action requires separate explicit authorization.

Draft PR: `https://github.com/Grativy6/ARC3/pull/7`. Do not merge it.
