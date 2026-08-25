# ARC3 Build 003 open-burden ledger

Do not delete a burden when later evidence resolves it. Append a resolution with the resolving artifact and commit.

## B-003-0001 - Real OFFLINE target playability is not dynamically verified

- **Status:** OPEN
- **Stage:** 00, 10
- **Opened:** 2026-08-24
- **Owner:** shared
- **Burden:** The cached `r11l-495a7899` identity and development authority pass static checks, but Build 003 has not yet opened it through pinned OFFLINE execution.
- **Why it matters:** Static availability cannot establish that the real official environment can run now.
- **Current evidence:** `docs/evidence/003-00-source-and-base-preflight.json`.
- **Next discriminating action:** After synthetic gates and implementation freeze, revalidate the hash and open exactly this identity with `network_enabled=false` and no credentials.
- **Resolution condition:** The official OFFLINE adapter opens and returns a normalized frame, or an exact incompatibility receipt establishes `BLOCKED_EXTERNAL`.

## B-003-0002 - BLA/CLEF mechanism benefit is unmeasured

- **Status:** OPEN
- **Stage:** 02-09
- **Opened:** 2026-08-24
- **Owner:** Codex
- **Burden:** No Build 003 learner, curriculum, or paired ablation result exists yet.
- **Why it matters:** Framework alignment and passing component tests are not evidence of learning benefit.
- **Current evidence:** Source identity and pre-registration only.
- **Next discriminating action:** Implement the mechanism once, run the frozen four-variant matrix on all predeclared held-out seeds, and report paired outcomes including failures.
- **Resolution condition:** Acceptance gates support `MECHANISM_CONFIRMED_SYNTHETIC`, or the result is preserved as `PARTIAL`/`FAILED_MECHANISM`.

## B-003-0003 - No authoritative target-game completion exists

- **Status:** OPEN
- **Stage:** 10-11
- **Opened:** 2026-08-24
- **Owner:** shared
- **Burden:** No official returned `GameState.WIN` exists for the target. One historical random run completed one level but ended without WIN.
- **Why it matters:** A level transition, score, mechanic map, or synthetic pass is not the requested outcome.
- **Current evidence:** Build 000 Stage 15 trace; Build 003 preflight.
- **Next discriminating action:** Use the frozen learner at the official action boundary, preserve every failure/reset, and continue until WIN or an exact external/resource boundary.
- **Resolution condition:** A replay-linked receipt records final official state WIN, or the same exact blocking condition satisfies the persistent blocked-goal rule after independent work is exhausted.

## B-003-0004 - Target-guided development may overfit

- **Status:** OPEN
- **Stage:** 05-11
- **Opened:** 2026-08-24
- **Owner:** Codex
- **Burden:** Iterating from one public development target can accidentally create identity-, coordinate-, color-, layout-, or walkthrough-specific behavior.
- **Why it matters:** Such behavior would violate the workflow and provide no game-agnostic evidence.
- **Current evidence:** Production public-ID scan exists; no Build 003 code exists.
- **Next discriminating action:** Keep the target ID external, run static scans and remapping/metamorphic tests, and require generic causal features for every repair.
- **Resolution condition:** Final source scans and held-out synthetic compositions pass with zero target/public IDs or privileged imports.

## B-003-0005 - Official ARC3 RHAE remains unmeasured

- **Status:** BLOCKED_EXTERNAL
- **Stage:** 10-11
- **Opened:** 2026-08-24
- **Owner:** upstream/human
- **Burden:** Local OFFLINE play has no authoritative online/Kaggle scorecard, and credentials/terms/submission are not authorized.
- **Why it matters:** Local actions and completions must not be labeled official RHAE.
- **Current evidence:** Build 002 handoff; current official local-vs-online documentation.
- **Next discriminating action:** None in Build 003; report `OFFICIAL_ARC3_RHAE = NOT_MEASURED`.
- **Resolution condition:** A separately authorized official evaluator returns a scorecard bound to the frozen package.

## B-003-0006 - Frozen Windows launcher identity test fails on the current uv alias topology

- **Status:** OPEN / inherited `FAILED_INFRASTRUCTURE`
- **Stage:** 01, 10
- **Opened:** 2026-08-24
- **Owner:** host tooling
- **Burden:** `test_windows_direct_base_spawn_preserves_venv_identity_and_pid` reproducibly fails before Build 003 changes because `_runtime_identity` returns `verified=false` only for `direct_process_probe_exact`.
- **Why it matters:** The final regression result must preserve this known failure rather than attribute it to the learner or silently call the full suite clean.
- **Current evidence:** `docs/evidence/003-01-build-002-frozen-baseline.json`; the launcher probe reports the uv base Python through an unversioned lexical alias while direct execution reports its versioned resolved directory.
- **Next discriminating action:** Re-run the exact test at Stage 10 and compare the predicate-level receipt. Do not modify the frozen baseline or weaken runtime identity validation merely to obtain green output.
- **Resolution condition:** The final test passes on an authenticated stable launcher topology, or a separately scoped fix proves both launcher paths equivalent without weakening any identity predicate.

## B-003-0007 - Global composite-preservation guards regressed ordinary affine play

- **Status:** RESOLVED
- **Stage:** 10
- **Opened:** 2026-08-25
- **Owner:** Codex
- **Burden:** Campaign 14 ended after 29 official actions at `NOT_FINISHED`, `levels_completed=2/6`, when a cross-mediator separation guard learned from a composite level was applied to ordinary single-color affine groups. The policy exhausted its bounded same-group action set and raised `PolicyError`.
- **Why it matters:** A repair that preserves later mechanics but removes a valid earlier route is not progress toward authoritative `WIN`.
- **Failure evidence:** `C:\a\arc3-b003-play\build003-r11l-mechanical-seed7-b1a695ec-campaign14`; official recording SHA-256 `993031c8909e386c89a0fb35a9604c32e88260ddba151b082747709de4c43245`.
- **Local resolution evidence:** The guards are now scoped by observed composite-mediator identity. Disabling only the target-box gate did not repair the first divergent action; disabling ordinary inter-mediator separation did. The repaired policy exactly matches all 29 pre-transition actions from Campaign 13 and reaches its returned level-3 `NOT_FINISHED` observation. The visual-policy suite reports 40 passed; Ruff and strict mypy pass.
- **Official resolution evidence:** Campaign 15, rooted at `C:\a\arc3-b003-play\build003-r11l-mechanical-seed7-e87a2762-campaign15`, passed the Campaign 14 failure boundary and officially reached level 3. Its later compound-evidence failures are preserved separately as B-003-0008 rather than back-propagated into this resolved ordinary-affine regression.
- **Next discriminating action:** None for this burden; preserve the Campaign 14 and Campaign 15 traces as paired regression evidence.
- **Resolution condition:** Met by Campaign 15 reaching level 3 through ordinary affine play. Continued preservation of level-3 compound groups is governed by B-003-0008.

## B-003-0008 - Compound evidence loss and false failure memory blocked level-3 continuation

- **Status:** RESOLVED BY CAMPAIGN 17; LATER LEVEL-3 RESIDUAL PRESERVED SEPARATELY
- **Stage:** 10
- **Opened:** 2026-08-25
- **Owner:** Codex
- **Burden:** Campaign 15 reached level 3 but did not reach `WIN`. Observable compound mechanics were erased when a moved endpoint, prospective connector/tether raster, or translated mediator sector crossed a target region or merged with same-color scene structure. Separately, readable marker displacements were classified as unrecognized changes and falsely blacklisted, while an exact predicted local target collapse became unreadable after its expected disappearance and could not drive continuation to another unresolved group.
- **Why it matters:** Cross-level mechanic retention cannot serve progress when an action destroys the learner's own evidence, and false failure memory can exhaust otherwise valid same-group actions after `RESET`. Neither high confidence nor a local collapse is official completion; the controller must preserve bounded local progress and continue until the environment returns `WIN`.
- **Failure evidence:** Campaign root `C:\a\arc3-b003-play\build003-r11l-mechanical-seed7-e87a2762-campaign15`; official recording `C:\a\arc3-b003-play\build003-r11l-mechanical-seed7-e87a2762-campaign15\official-recordings\c2120ed7e4beb839e4d0\d5a89114-d780-4700-9741-1ce5c7a2a91d\r11l-495a7899-8f76d262-4475-4265-9851-5a4184c54c1a.jsonl`; SHA-256 `2a2b3da7fad9e5bb8d4fea3b2f33133bdf2e9076ac66ea49f02dc9c6744b2a14`. The run ended `FAILED_INFRASTRUCTURE` on `PolicyError`; the latest raw environment state was `NOT_FINISHED`, the score boundary reported `GAME_OVER`, and measured progress was 3/6 levels after 112 submissions: 110 non-reset actions and two `RESET` actions.
- **Local resolution evidence:** The bounded repair protects all observable target regions and prospective connector/tether rasters, applies the parser's own component-merge relation to endpoint and mediator-sector placement, recognizes structurally readable marker displacement as a known controllable effect, and carries observation-grounded exact local target contact forward as local continuation state. These changes do not establish a level completion or `WIN`.
- **Campaign 16 recheck:** The fresh campaign frozen at `0b87a923500041757213fc421e5e165530b0c11c` ended before level 3, so it neither resolves nor disproves the compound-preservation repair. It did verify that removing false blacklisting exposes a separate shallow-improvement cycle, preserved as B-003-0009. Campaign root `C:\a\arc3-b003-play\build003-r11l-mechanical-seed7-0b87a923-campaign16`; recording SHA-256 `9531e3137b8b08d7f178c6df0d33f248f6b87740bbb58471b131b992778891a0`.
- **Campaign 17 resolution:** The run frozen at `0ae945257a1f8ed68d9462f6b0f0bf4083b41c5b` reached level 3 through the repaired earlier route, preserved three readable compound groups, continued after one exact local collapse, and then exactly collapsed a second group. It ended on a distinct post-collapse overlay/reacquisition residual rather than the Campaign 15 evidence-loss or false-blacklist mechanisms. Campaign root `C:\a\arc3-b003-play\build003-r11l-mechanical-seed7-0ae94525-campaign17`; recording SHA-256 `2685d5e81cb4b95c5784169a9e9a4a1675c4b3a94cb447fc5dd186c4ac864965`.
- **Next discriminating action:** None for this burden. Preserve Campaign 15 and Campaign 17 as paired failure/resolution evidence; post-collapse continuation is B-003-0010.
- **Resolution condition:** A fresh official campaign does not falsely blacklist readable compound actions, continues after an exact local collapse, and advances beyond the Campaign 15 boundary without erasing an unresolved compound mechanic; authoritative completion still requires returned `GameState.WIN` under B-003-0003.

## B-003-0009 - Uncertified relocation geometry produced a shallow-improvement cycle

- **Status:** RESOLVED BY CAMPAIGN 17
- **Stage:** 10
- **Opened:** 2026-08-25
- **Owner:** Codex
- **Burden:** Campaign 16 completed two levels, then the repaired failure memory exposed a shallow-improvement cycle. The bounded policy ranked apparent relocations whose coordinates remained inside the current endpoint hitbox and did not separate an endpoint center that had merged into sparse-target evidence. It exhausted its same-group action set and raised `PolicyError` while the official state remained `NOT_FINISHED`.
- **Why it matters:** Retaining or looking ahead through more candidate actions is not useful when the candidate geometry itself does not certify relocation or preserve parser identity. The repair must remove the unsupported action and restore the exact observable target boundary before ranking further progress.
- **Failure evidence:** Frozen commit `0b87a923500041757213fc421e5e165530b0c11c`; campaign root `C:\a\arc3-b003-play\build003-r11l-mechanical-seed7-0b87a923-campaign16`; official recording `C:\a\arc3-b003-play\build003-r11l-mechanical-seed7-0b87a923-campaign16\official-recordings\c2120ed7e4beb839e4d0\3e7aa61a-60a6-4f13-919c-9cfbea353d9b\r11l-495a7899-12ce06a5-763d-4190-aebd-d28bf8e702c2.jsonl`; SHA-256 `9531e3137b8b08d7f178c6df0d33f248f6b87740bbb58471b131b992778891a0`. The recording contains 34 events for 33 non-reset action submissions and zero resets; `levels_completed=2/6`; raw and official final states were `NOT_FINISHED`.
- **Disproved first repair:** The broad D-003-0007 follow-up ranking regressed a preserved official replay route and was rejected before fresh official play. This narrows the burden: no evidence earned broader lookahead.
- **Refined diagnosis:** Official actions at the painted edge `(41,16)` and an unpainted bounding-box corner `(41,15)` both left the active endpoint center and mediator unchanged, so treating either coordinate as a new center invented improvement without relocation evidence. Separately, an endpoint center was joined to a sparse target; removing that center reconstructed the exact symmetric target ring, identifying a parser-level contaminant rather than a new target geometry.
- **Smallest local repair:** Reject relocation coordinates inside the current active endpoint's observed bounding box. For exactly certified endpoint-center/sparse-target contamination, select the smallest readable separation whose prospective center no longer merges with the residual target under the parser's exact small-component relation, then reobserve before continuing. Accept a consequence only when the predicted endpoint-center replacement or outer-color role transfer is visible; retain exact target restoration even when an ordinary improvement produced it.
- **Local verification evidence:** The visual-policy suite reports 50 passed; Ruff and strict mypy are clean. Historical replay preserves the full known official Level 1 route and replaces the failed Level 2 tail with the certified sequence `(59,49)`, `(59,46)`, `(39,16)`, `(49,48)` into the recorded Level 3 frame. No-op role transfers are now rejected, while actual role transfers and both dedicated and incidental target-identity restoration are covered. These results verify only the local repair and do not establish fresh official progress or `WIN`.
- **Official resolution evidence:** Campaign 17 preserved the earlier two-level route, executed the certified separation sequence, reached level 3, and continued for seventeen level-3 actions before a distinct residual. Campaign root `C:\a\arc3-b003-play\build003-r11l-mechanical-seed7-0ae94525-campaign17`; recording SHA-256 `2685d5e81cb4b95c5784169a9e9a4a1675c4b3a94cb447fc5dd186c4ac864965`.
- **Next discriminating action:** None for this burden; the distinct Campaign 17 residual is B-003-0010.
- **Resolution condition:** A fresh official campaign passes the Campaign 16 failure boundary without regressing the earlier two-level route; authoritative completion remains governed by B-003-0003.

## B-003-0010 - Compound-target sector overlay blocked post-collapse reacquisition

- **Status:** LOCAL REPAIR VERIFIED; OFFICIAL RECHECK PENDING
- **Stage:** 10
- **Opened:** 2026-08-25
- **Owner:** Codex
- **Burden:** Campaign 17 locally solved two of three level-3 compound groups but did not reach level 4 or `WIN`. One remaining endpoint center was parser-joined to exactly one same-color sector of its complete compound target. The old contaminant certificate missed that relation, post-collapse reacquisition required an immediate direct relocation, and a subsequent open-space bootstrap recovered a marked endpoint from an already-solved group that the bootstrap reader rejected because no complete group contained it.
- **Why it matters:** Exact local completion must lead to the smallest readable continuation while the official state remains `NOT_FINISHED`. Treating a target-sector overlay as an independent target exhausts safe actions, while discarding a unique returned bootstrap endpoint erases valid causal evidence.
- **Failure evidence:** Frozen commit `0ae945257a1f8ed68d9462f6b0f0bf4083b41c5b`; campaign root `C:\a\arc3-b003-play\build003-r11l-mechanical-seed7-0ae94525-campaign17`; official recording `C:\a\arc3-b003-play\build003-r11l-mechanical-seed7-0ae94525-campaign17\official-recordings\c2120ed7e4beb839e4d0\8872dd93-7263-4c7c-8a2f-2d15e26f8f62\r11l-495a7899-9169ebee-d745-4730-b5f6-cb97a69dd8ed.jsonl`; SHA-256 `2685d5e81cb4b95c5784169a9e9a4a1675c4b3a94cb447fc5dd186c4ac864965`. The recording has 44 events: one initial reset observation and 43 non-reset submissions. Raw and official final state were `NOT_FINISHED`, `levels_completed=3/6`, with no reset and no observed `WIN`.
- **Exact diagnosis:** The remaining marker-14 group had endpoints `(58,32)`, `(44,12)`, `(27,52)`, mediator `(43,32)`, target `(50,12)`, and potential `3805`. A parsed seven-cell marker-14 target component was exactly the endpoint center `(44,12)` plus the six marker-14 cells of the complete twelve-cell compound target. The smallest projected parser-readable separation is `(41,12)`. Raw action 43 returned a unique marked endpoint at the submitted `(6,43)`, but `_marker_bootstrap_active_color` searched only endpoints inside complete groups.
- **Smallest local repair:** Certify only exact endpoint-center plus target-sector equality; bridge both post-collapse reacquisition and visible role transfer to a certified separation when direct improvement is absent; evaluate target rejoining against the same-color target sector; retain the resulting identity constraint only after exact target colors and raw component boundaries are observed; and accept one unique marked endpoint at the exact bootstrap coordinate even when its solved group is no longer complete.
- **Local verification evidence:** Focused replay matches Campaign 17 official actions 1-40 and first diverges at action 41 to `marker:14:separate:41,12`. The exact final official frame now localizes bootstrap active color 0, plans `marker:14:activate:44,12`, and projects separation `(41,12)`. The visual-policy suite reports 56 passed. Negative tests reject near-target similarity, retained marker bridges, and swapped target-sector colors. Ruff, format, strict mypy, JSON, and diff checks pass; independent final review found no remaining actionable issue.
- **Next discriminating action:** Freeze Campaign 18 from the verified repair. Require official observation of the separation and continued level-3 progress; any later distinct horizon remains a new burden rather than retroactively broadening this repair.
- **Resolution condition:** A fresh official campaign preserves the prior route, observes the exact target-sector separation, and continues without repeating the Campaign 17 reacquisition/bootstrap failure. Authoritative completion remains returned `GameState.WIN` under B-003-0003.
