# ARC3 open-burden ledger

This file preserves unresolved technical, evidential, legal, and external burdens. Do not delete a burden when it is resolved. Change its status in a new entry or append a resolution section that identifies the resolving evidence and commit.

## Burden template

```markdown
## B-YYYYMMDD-NNN — Short title

- **Status:** OPEN | NARROWED | RESOLVED | ACCEPTED_LIMIT | BLOCKED_EXTERNAL
- **Stage:** 00–20
- **Opened:** ISO-8601
- **Last updated:** ISO-8601
- **Owner:** human | Codex | upstream | shared
- **Burden:** What remains unsupported, unknown, or unavailable.
- **Why it matters:** Consequence if ignored.
- **Current evidence:** Paths, test IDs, reports, or source links.
- **Next discriminating action:** Smallest test or decision that would materially update it.
- **Resolution condition:** What would justify changing the status.
- **Resolution receipt:** `none` until resolved.
```

---

## B-20260820-001 — No ARC3 implementation or measured score exists yet

- **Status:** OPEN
- **Stage:** 00–20
- **Opened:** 2026-08-20
- **Last updated:** 2026-08-20
- **Owner:** Codex
- **Burden:** The repository currently contains the autonomous workflow and specifications, not a working agent, benchmark result, or competition submission.
- **Why it matters:** Planning artifacts must not be mistaken for implemented or measured capability.
- **Current evidence:** `docs/workflows/000-arc3-autonomous-end-to-end.md`; `docs/ledger/run-state.json` is `READY` with every stage pending.
- **Next discriminating action:** Launch Codex with `CODEX_START.md` and complete Stage 00 followed by the first executable baseline.
- **Resolution condition:** A working baseline and its reproducible evidence exist in the implementation branch.
- **Resolution receipt:** none.

## B-20260820-002 — Current competition rules and limits are mutable

- **Status:** OPEN
- **Stage:** 00
- **Opened:** 2026-08-20
- **Last updated:** 2026-08-20
- **Owner:** upstream
- **Burden:** Runtime, hardware, packaging, licensing, and scoring requirements may change during the 2026 competition.
- **Why it matters:** Stale assumptions could invalidate the package or reported score.
- **Current evidence:** Workflow bootstrap research used official ARC Prize documentation and repositories but has not yet produced a source-identity lock inside the implementation branch.
- **Next discriminating action:** Stage 00 must fetch official primary sources, record access dates, and pin exact upstream commits/package versions in `upstream.lock.json`.
- **Resolution condition:** This can only be narrowed for a specific build identity; it remains reopenable whenever upstream changes.
- **Resolution receipt:** none.

## B-20260820-003 — ARC and Kaggle credentials may be unavailable

- **Status:** OPEN
- **Stage:** 00, 02, 15, 17
- **Opened:** 2026-08-20
- **Last updated:** 2026-08-20
- **Owner:** shared
- **Burden:** The autonomous environment may not contain an ARC API key or Kaggle credentials.
- **Why it matters:** Some public games, upload checks, and external evaluation surfaces may be inaccessible.
- **Current evidence:** No credential was supplied or inspected during workflow bootstrap.
- **Next discriminating action:** Stage 00 checks presence without printing values; use anonymous/local modes and prepare adapters if absent.
- **Resolution condition:** Required surface executes with a valid owner-provided credential, or the build finishes with a precise `BLOCKED_EXTERNAL` result while all independent work is completed.
- **Resolution receipt:** none.

## B-20260820-004 — Public license is an owner decision

- **Status:** BLOCKED_EXTERNAL
- **Stage:** 00, 17, 19
- **Opened:** 2026-08-20
- **Last updated:** 2026-08-20
- **Owner:** human
- **Burden:** Prize eligibility requires an eligible permissive open-source license, but no final license has been granted for ARC3.
- **Why it matters:** A public license is a consequential legal grant and cannot be inferred from participation intent.
- **Current evidence:** `AGENTS.md`; `docs/ledger/DECISIONS.md` D-20260820-004.
- **Next discriminating action:** Codex prepares a sourced comparison and candidate text; Christopher explicitly selects the license before release/submission.
- **Resolution condition:** Owner gives an explicit license instruction and the resulting commit is recorded.
- **Resolution receipt:** none.

## B-20260820-005 — Kaggle terms and official submission are human-gated

- **Status:** BLOCKED_EXTERNAL
- **Stage:** 17, 20
- **Opened:** 2026-08-20
- **Last updated:** 2026-08-20
- **Owner:** human
- **Burden:** Codex may prepare and validate a package but may not accept legal terms, spend a daily submission, or submit officially.
- **Why it matters:** These actions have legal/account and scarce-quota consequences.
- **Current evidence:** `AGENTS.md`; `docs/ledger/run-state.json`.
- **Next discriminating action:** Complete the offline package and give Christopher one exact owner-only submission step.
- **Resolution condition:** Christopher explicitly authorizes or personally performs the relevant action; returned evaluator evidence is preserved.
- **Resolution receipt:** none.

## B-20260820-006 — Trace-ledger overhead is unmeasured

- **Status:** OPEN
- **Stage:** 03, 11, 16
- **Opened:** 2026-08-20
- **Last updated:** 2026-08-20
- **Owner:** Codex
- **Burden:** Append-only frames, deltas, hypothesis history, and checkpoints may exceed competition memory or decision-time budgets.
- **Why it matters:** A structurally faithful system that cannot execute within the evaluator is not a viable competition agent.
- **Current evidence:** Design only in `docs/specs/trace-ledger-contract.md`.
- **Next discriminating action:** Benchmark append latency, deduplication, trace growth, retrieval, and checkpoint size on maximum-size synthetic frames and official recordings.
- **Resolution condition:** Measured overhead fits a conservative current competition envelope, or the design is narrowed without violating source-trace invariants.
- **Resolution receipt:** none.

## B-20260820-007 — Public-game performance will not establish hidden generalization

- **Status:** OPEN
- **Stage:** 13–19
- **Opened:** 2026-08-20
- **Last updated:** 2026-08-20
- **Owner:** shared
- **Burden:** Public games can be inspected, tuned against, and overfit. Even excellent public performance is not private-set evidence.
- **Why it matters:** The project must not promote a development result into a general intelligence or hidden-generalization claim.
- **Current evidence:** `docs/specs/evaluation-protocol.md` partitions and claim vocabulary.
- **Next discriminating action:** Preserve deterministic public holdouts, procedural held-out rule families, and any later authorized Kaggle/private result as separate surfaces.
- **Resolution condition:** Never fully closed; narrowed only by independent hidden evaluation with preserved submission identity.
- **Resolution receipt:** none.

## B-20260820-008 — The value of PAL-inspired trace discipline is an empirical question

- **Status:** OPEN
- **Stage:** 03–15
- **Opened:** 2026-08-20
- **Last updated:** 2026-08-20
- **Owner:** Codex
- **Burden:** Persistent receipts, rejected-hypothesis retention, retrodiction, and reopening may or may not improve completion or action efficiency.
- **Why it matters:** Architectural resemblance or conceptual elegance is not evidence of benchmark benefit.
- **Current evidence:** Proposed ablations in `docs/specs/evaluation-protocol.md`; no run yet.
- **Next discriminating action:** Execute paired full-vs-ablation comparisons under identical games, seeds, action budgets, and scorer.
- **Resolution condition:** Report bounded measured effects or `MECHANISM_NOT_OBSERVED`; do not turn either result into proof of PAL as a whole.
- **Resolution receipt:** none.

## B-20260820-009 — A local learned model is not yet justified

- **Status:** OPEN
- **Stage:** 08, 12, 14, 16, 17
- **Opened:** 2026-08-20
- **Last updated:** 2026-08-20
- **Owner:** Codex
- **Burden:** It is unknown whether a packaged local model would improve rule proposal or planning enough to justify its latency, memory, licensing, and deployment costs.
- **Why it matters:** Premature model integration could consume the build while weakening reproducibility and offline compatibility.
- **Current evidence:** The target architecture makes the model path optional and disabled by default.
- **Next discriminating action:** Establish symbolic baselines first; add a local model only behind a typed adapter and only after a controlled resource-compatible ablation.
- **Resolution condition:** Measured improvement under the same action/compute budget with an eligible packageable model, or an accepted decision to remain symbolic.
- **Resolution receipt:** none.

## B-20260820-010 — Final merge remains owner-gated

- **Status:** BLOCKED_EXTERNAL
- **Stage:** 20
- **Opened:** 2026-08-20
- **Last updated:** 2026-08-20
- **Owner:** human
- **Burden:** The autonomous run may push and open/update a draft PR but may not merge it to `main`.
- **Why it matters:** The owner remains responsible for accepting the final repository state.
- **Current evidence:** `AGENTS.md`.
- **Next discriminating action:** Finish the draft PR with evidence and one clear review decision.
- **Resolution condition:** Christopher explicitly directs or performs the merge.
- **Resolution receipt:** none.

---

## 2026-08-21 Stage 00 updates

### B-20260820-002 — Current competition rules and limits are mutable

- **Status update:** NARROWED for Build 000, never permanently closed.
- **Last updated:** 2026-08-21
- **Current evidence:** `upstream.lock.json`; `docs/reports/000-source-identity.md` pin stable documentation bodies, official repository commits, package artifacts, and access times. Kaggle client-rendered HTML is deliberately identified by URL/access time rather than treated as stable content.
- **Remaining burden:** Revalidate immediately before any public holdout, package freeze, or owner-authorized submission.
- **Resolution receipt:** Stage 00 source-identity checkpoint `9e17c9d20334f8e52be2eafcc8f84a1d2f0973b2`.

### B-20260820-003 — ARC and Kaggle credentials may be unavailable

- **Status update:** NARROWED / BLOCKED_EXTERNAL for authenticated surfaces.
- **Last updated:** 2026-08-21
- **Current evidence:** Presence-only checks found no `ARC_API_KEY`, Kaggle token environment variable, Kaggle CLI, or Kaggle credential file. Network, local toolkit, anonymous, synthetic, and offline packaging routes remain available.
- **Remaining burden:** Authenticated online-public scorecards and authenticated Kaggle upload/status checks cannot run without an owner-provided credential; this does not block independent work.
- **Resolution receipt:** `docs/reports/000-source-identity.md`.

## B-20260821-011 — Pinned Kaggle starter has no detected source license

- **Status:** NARROWED
- **Stage:** 00, 01, 17
- **Opened:** 2026-08-21
- **Last updated:** 2026-08-21
- **Owner:** upstream
- **Burden:** `arcprize/ARC-AGI-3-Kaggle-Starter@eeb1535404f321d280a8f9194bbc1d7aca5f05fc` has no `LICENSE`, `COPYING`, or `NOTICE` file and no GitHub-detected license, so copying/adapting its source would assume permission not established by the repository.
- **Why it matters:** Deployment compatibility does not itself grant copyright permission.
- **Current evidence:** `upstream.lock.json`; `THIRD_PARTY_NOTICES.md`; D-20260821-006.
- **Next discriminating action:** Implement and test an equivalent first-party wrapper from the documented interface; re-check upstream licensing before any later adaptation.
- **Resolution condition:** Packaging passes without copied source, or upstream publishes a compatible license/permission whose exact identity is recorded.
- **Resolution receipt:** none; first-party wrapper not yet implemented.

## B-20260821-012 — Docker is unavailable on the measured host

- **Status:** ACCEPTED_LIMIT
- **Stage:** 00, 17, 18
- **Opened:** 2026-08-21
- **Last updated:** 2026-08-21
- **Owner:** shared
- **Burden:** Docker is not installed, so container-based parity checks are unavailable.
- **Why it matters:** A container could provide an additional Linux/offline packaging check, but it is not required by the controlling workflow.
- **Current evidence:** `docker --version` was unavailable; Python 3.12, uv, Git, local network access, and a Windows clean-clone path are available.
- **Next discriminating action:** Use process-level network denial and a fresh clone for Stage 17/18; rely on Linux CI for the second OS surface.
- **Resolution condition:** Those checks pass, or a container becomes available without paid/system-changing prerequisites.
- **Resolution receipt:** none.

## B-20260821-013 — Official package, docs, and example identities disagree

- **Status:** OPEN
- **Stage:** 00, 02, 03, 13, 15
- **Opened:** 2026-08-21
- **Last updated:** 2026-08-21
- **Owner:** upstream
- **Burden:** The pinned sources contain several contradictions: ARC-AGI declares/tags 0.9.9 while its lock records root 0.9.8; Agents declares 0.1.0 while using v0.9.x tags and toolkit 0.9.1; docs call ACTION7 undo while the engine types it generically; docs' action-count wording differs from the executable non-RESET counter; methodology/toolkit use a 115% level cap while the Kaggle data formula describes a 100% cap; docs say local play has no recordings while toolkit source can save local JSONL; toolkit/Agents surfaces disagree on the default API host; and ARC Prize/Kaggle pages disagree on some milestone prize splits.
- **Why it matters:** Silently choosing whichever statement is convenient would weaken reproducibility and could invalidate scoring, action validation, or replay claims.
- **Current evidence:** `upstream.lock.json` `observed_discrepancies`; `docs/reports/000-source-identity.md`; immutable upstream commits pinned there.
- **Next discriminating action:** Regenerate ARC3's lock, install exact wheels, execute contract probes against the local toolkit, and use the pinned executable behavior for implementation while retaining documentation conflicts.
- **Resolution condition:** Each behavior used by ARC3 has an executable compatibility test and any remaining doc conflict is labeled in reports.
- **Resolution receipt:** none.

## B-20260821-014 — Upstream examples and anonymous logging violate ARC3 production constraints

- **Status:** OPEN
- **Stage:** 02, 12, 16
- **Opened:** 2026-08-21
- **Last updated:** 2026-08-21
- **Owner:** shared
- **Burden:** Pinned sample policy uses wall-clock/Python-hash seeding, can ignore advertised available actions, and contains a public-game-ID conditional. The toolkit's anonymous-key path can log the fetched key at INFO.
- **Why it matters:** Copying these patterns would violate determinism, action validity, competition-integrity, and credential hygiene.
- **Current evidence:** Immutable starter/Agents/toolkit sources identified in `docs/reports/000-source-identity.md`.
- **Next discriminating action:** Implement first-party deterministic baselines, authoritative available-action validation, redacted logging, and static game-ID/secret scans.
- **Resolution condition:** Stage 02/16 tests prove those properties on ARC3 production paths; the upstream observations remain historical evidence.
- **Resolution receipt:** none.

---

## 2026-08-21 Stage 01 updates

### B-20260821-011 — Pinned Kaggle starter has no detected source license

- **Status update:** NARROWED; packaging verification remains open through Stage 17.
- **Last updated:** 2026-08-21
- **Current evidence:** A first-party `agent/my_agent.py` compatibility wrapper and interface tests were implemented without copying starter source. `docs/reports/001-repository-foundation.md` records the boundary.
- **Remaining burden:** Prove the independently implemented wrapper inside the generated offline Kaggle package and re-check upstream licensing before any future source adaptation.
- **Resolution receipt:** Stage 01 implementation checkpoint `311110299444f71d7e0f0ff0e3b1f8d9c174a01b`.

## B-20260821-015 — Remote CI and true clean-clone execution are not yet receipts

- **Status:** NARROWED
- **Stage:** 01, 18
- **Opened:** 2026-08-21
- **Last updated:** 2026-08-21
- **Owner:** Codex
- **Burden:** CI configuration and local bootstrap contracts can pass while a pushed Linux/Windows job or an isolated clone still fails.
- **Why it matters:** Repository-local success is not evidence of cross-platform or clean-clone reproducibility.
- **Current evidence:** Local Windows `scripts/bootstrap.ps1 -Check` passed. Initial Actions runs `32450125300` and `32450125762` passed on Ubuntu but failed Windows formatting because checkout converted LF to CRLF. `.gitattributes` made source line endings invariant; correcting runs `32450257835` and `32450260123` passed both Ubuntu and Windows jobs.
- **Next discriminating action:** Observe the pushed Stage 01 Actions run, then perform the Stage 18 fresh-clone locked bootstrap and artifact verification.
- **Resolution condition:** Linux and Windows CI plus the declared Stage 18 clean-clone checks pass, or failures are preserved with exact outputs.
- **Resolution receipt:** Remote CI portion resolved by Actions runs `32450257835` and `32450260123`; true clean-clone verification remains open for Stage 18.

---

## 2026-08-21 Stage 02 updates

### B-20260821-013 — Official package, docs, and example identities disagree

- **Status update:** NARROWED for the Stage 02 execution path; documentation/scoring and future-version conflicts remain open.
- **Last updated:** 2026-08-21
- **Current evidence:** Exact wheels import; adapter compatibility tests bind frame extraction, automatic reset, action validation, terminal behavior, recording limitations, mode precedence, and scorecard normalization to `arc-agi==0.9.9` / `arcengine==0.9.3`.
- **Remaining burden:** Preserve the 100%/115% score-cap conflict until Stage 13 validates the chosen official-facing scorer; re-run compatibility tests on any upstream change.
- **Resolution receipt:** `docs/reports/002-official-sdk-baselines.md`.

### B-20260821-014 — Upstream examples and anonymous logging violate ARC3 production constraints

- **Status update:** NARROWED for Stage 02 production paths; final static/package scans remain open.
- **Last updated:** 2026-08-21
- **Current evidence:** Deterministic first-party baselines use local seeded PRNG state, advertised-action filtering, no game-ID branches, injected silent SDK loggers, and sanitized exception text. Sentinel tests and a production-ID scan pass.
- **Remaining burden:** Turn these scans into durable Stage 16/17 CI checks and prove the final packaged controller has the same properties.
- **Resolution receipt:** `docs/reports/002-official-sdk-baselines.md`.

## B-20260821-016 — Stage 02 timestamps are incomplete evaluation receipts

- **Status:** OPEN
- **Stage:** 02, 03, 13
- **Opened:** 2026-08-21
- **Last updated:** 2026-08-21
- **Owner:** Codex
- **Burden:** The Stage 02 CLI scorecards preserve configuration, source identities, seeds, budgets, and results, but the combined command did not emit exact evaluation start/end timestamps.
- **Why it matters:** Inferred timestamps would weaken provenance; missing fields must be explicit.
- **Current evidence:** Both fields are `null` with an explanation in `docs/evidence/002-baseline-scorecards.json`.
- **Next discriminating action:** Use the immutable Stage 03 event clock and Stage 13 evaluation manifest to record exact start/completion timestamps.
- **Resolution condition:** The general evaluation harness emits and hashes both timestamps without relying on shell history.
- **Resolution receipt:** none.

## B-20260821-017 — One would-be public holdout was exposed before manifest freeze

- **Status:** ACCEPTED_LIMIT
- **Stage:** 02, 15
- **Opened:** 2026-08-21
- **Last updated:** 2026-08-21
- **Owner:** shared
- **Burden:** `ls20-9607627b` was opened for SDK contract work before deterministic public partitions were committed; its hash rank would otherwise have placed it in public holdout.
- **Why it matters:** Treating it as unseen later would be false even though no game source was inspected and no solution was encoded.
- **Current evidence:** The manifest records original assignment, exposure date/type, and an override to development.
- **Next discriminating action:** Keep it in development/regression only and run Stage 15 public holdout solely on the 10 unexposed manifest entries.
- **Resolution condition:** Permanent process constraint for Build 000; never erase the exposure record.
- **Resolution receipt:** `docs/evaluation/public-game-partitions.v0.1.json`.

### B-20260821-015 — Remote CI and true clean-clone execution are not yet receipts

- **Status update:** RESOLVED for the Stage 02 correction; Stage 18 clean-clone work remains.
- **Last updated:** 2026-08-21
- **Current evidence:** Stage 02 Actions runs `32451110070` and `32451112828` failed one stale Stage 01 assertion after the `evaluate` command became real; all preceding sync/lint/format/type steps passed. The test now targets the still-reserved `compare` command.
- **Remaining burden:** Retain Stage 18 true clean-clone verification as a separate boundary.
- **Resolution receipt:** Correcting Actions runs `32451273583` and `32451275935` passed both Ubuntu and Windows jobs at commit `9ee31a453cfa1b52c1cb99b6cf0a2bc7ac52e61a`.

---

## 2026-08-21 Stage 03 updates

### B-20260820-006 — Trace-ledger overhead is unmeasured

- **Status update:** NARROWED for the isolated Stage 03 implementation; integrated competition-scale profiling remains open.
- **Last updated:** 2026-08-21
- **Current evidence:** `docs/evidence/003-trace-acceptance.json` records 500-event append/retrieval, 64×64 frame deduplication, storage, checkpoint size, and peak traced allocation on the pinned Windows/Python host. Append measured 0.623596 ms/event and retrieval 0.0877939 seconds for 500 events.
- **Remaining burden:** Profile trace growth, compaction, and decision latency with the Stage 12 controller across long procedural and public-game runs under the Stage 16 envelope.
- **Resolution receipt:** Stage 03 report `docs/reports/003-immutable-trace-replay-checkpoint.md`; implementation checkpoint `8fd5a056a71ae52fa37f83f3c3614ae1f0a4f7c3`.

### B-20260820-008 — The value of PAL-inspired trace discipline is an empirical question

- **Status update:** OPEN; implementation is now ablatable but no performance value is inferred.
- **Last updated:** 2026-08-21
- **Current evidence:** Immutable receipts, replay, rejected-state preservation, and checkpoint/reopen mechanics pass their focused suites. Stage 11 additionally measures one source-linked cross-level rule at one validation probe versus three without memory; this remains isolated synthetic mechanism evidence.
- **Remaining burden:** Stage 14 must compare the integrated controller with and without trace-derived memory and rejected-hypothesis retention under identical seeds, budgets, and scorers.
- **Resolution receipt:** none.

### B-20260821-016 — Stage 02 timestamps are incomplete evaluation receipts

- **Status update:** NARROWED; the trace event clock is implemented, while the general evaluation envelope remains Stage 13 work.
- **Last updated:** 2026-08-21
- **Current evidence:** Every Stage 03 event validates an explicit UTC timestamp and the benchmark preserves exact start/completion times in `docs/evidence/003-trace-acceptance.json`.
- **Remaining burden:** Stage 13 must emit start/completion timestamps for every scorecard and tie them to an immutable run manifest.
- **Resolution receipt:** Stage 03 trace schema and acceptance suite; not fully resolved.

## B-20260821-018 — Perception correspondence is heuristic and uncalibrated

- **Status:** OPEN
- **Stage:** 04, 08, 14, 16
- **Opened:** 2026-08-21
- **Last updated:** 2026-08-21
- **Owner:** Codex
- **Burden:** Component extraction depends on background/connectivity choices, and cross-frame correspondence uses generic hand-weighted geometry scores rather than calibrated probabilities or globally optimal multi-object assignments.
- **Why it matters:** A plausible but wrong match could contaminate later mechanics, world models, and plans if downstream code treats it as accepted identity.
- **Current evidence:** `docs/reports/004-perception-and-frame-differencing.md`; ambiguity retention and palette/position permutation tests pass, but only on synthetic fixtures.
- **Next discriminating action:** Carry alternative segmentations/matches into Stage 08 retrodiction, measure contradiction/recovery behavior in Stage 14, and profile any stronger assignment method in Stage 16.
- **Resolution condition:** Held-out procedural and public evidence demonstrates calibrated/robust matching or downstream recovery makes the remaining error rate an accepted bounded limit.
- **Resolution receipt:** none.

## B-20260821-019 — Hypothesis ranks have no predictive calibration evidence

- **Status:** OPEN
- **Stage:** 05, 08, 13, 14
- **Opened:** 2026-08-21
- **Last updated:** 2026-08-21
- **Owner:** Codex
- **Burden:** Deterministic integer ranks and conflict tie-breaks order typed hypotheses, but their scale has not been calibrated and lifecycle fixture success does not establish predictive accuracy or planning value.
- **Why it matters:** Treating an ordering aid as probability, truth, or expected utility could overstate evidence and bias probes or plans.
- **Current evidence:** Every Stage 05 serialization/report labels weights `uncalibrated_rank`; 20 mechanism tests pass on synthetic lifecycle fixtures.
- **Next discriminating action:** Measure retrodictive accuracy, contradiction rate, rule survival, and downstream score/action effects on held-out procedural episodes in Stages 08, 13, and 14.
- **Resolution condition:** Calibration evidence supports a revised meaning, or the final system retains rank-only semantics with measured limits.
- **Resolution receipt:** none.

## B-20260821-020 — Procedural laboratory fidelity is bounded

- **Status:** OPEN
- **Stage:** 06, 13, 14, 19
- **Opened:** 2026-08-21
- **Last updated:** 2026-08-21
- **Owner:** shared
- **Burden:** The 15 executable procedural families exercise declared mechanics but remain compact first-party abstractions; their distribution and difficulty are not evidence that they represent the current public or private ARC-AGI-3 game distribution.
- **Why it matters:** A controller can overfit the laboratory generator or improve synthetic completion without improving official gameplay.
- **Current evidence:** `docs/evidence/006-lab-acceptance.json` records deterministic splits, 630 solvable episodes, and random baselines; no official score is inferred.
- **Next discriminating action:** Keep generator ground truth away from production code, evaluate mechanisms on frozen held-out combinations/families in Stage 14, and separately measure the untouched public partition in Stage 15.
- **Resolution condition:** Never fully closed by synthetic results; narrow only with independent public/official receipts while preserving surface labels.
- **Resolution receipt:** none.

## B-20260821-021 — Exploration improvement is isolated from game completion

- **Status:** OPEN
- **Stage:** 07, 12, 14, 15
- **Opened:** 2026-08-21
- **Last updated:** 2026-08-21
- **Owner:** Codex
- **Burden:** Information-directed probes reduced median actions in a held-out typed semantic-identification fixture, but the fixture isolates one discriminating action and does not measure complete procedural or official games.
- **Why it matters:** A probe policy can identify a local mapping efficiently yet spend too many actions, misclassify effects, or fail to translate knowledge into a successful plan.
- **Current evidence:** `docs/evidence/007-exploration-acceptance.json` records median 1 versus random 4 and cycle 3 over 101 synthetic cases; all claims are limited to that surface.
- **Next discriminating action:** Integrate exploration with retrodictive models, goals, and planning in Stage 12, then run equal-budget full-game ablations in Stage 14 and untouched public evaluation in Stage 15.
- **Resolution condition:** Full-game evidence shows action/completion benefit, or the mechanism is retained only as an isolated capability with an honest negative integrated result.
- **Resolution receipt:** none.

## B-20260821-022 — World-model comparison supplies symbolic states and plans

- **Status:** OPEN
- **Stage:** 08, 10, 12, 14
- **Opened:** 2026-08-21
- **Last updated:** 2026-08-21
- **Owner:** Codex
- **Burden:** Retrodiction selected the correct model on four unseen symbolic parameter combinations, but symbolic states and right-action plans were supplied by the fixture rather than acquired from raw observations and controller search.
- **Why it matters:** Model-selection success can fail to survive perception ambiguity, incomplete hypothesis compilation, goal uncertainty, or planning errors in live episodes.
- **Current evidence:** `docs/evidence/008-world-model-acceptance.json` records 4/4 gated versus 0/4 ungated simulated final states under the same 16 supplied actions. `docs/evidence/010-planning-acceptance.json` adds 24/24 bounded-planning versus 0/24 cycle completions, but still starts from evaluator-supplied symbolic states, models, and targets.
- **Next discriminating action:** Build perception-to-symbolic-state controller integration in Stage 12, then run equal-budget full-game ablations in Stage 14.
- **Resolution condition:** Integrated traces demonstrate successful state construction, pre-action prediction, live consequence matching, and completion benefit; otherwise retain the isolated result only.
- **Resolution receipt:** none.

## B-20260821-023 — Goal comparison begins from supplied evidence and action estimates

- **Status:** OPEN
- **Stage:** 09, 10, 12, 14, 15
- **Opened:** 2026-08-21
- **Last updated:** 2026-08-21
- **Owner:** Codex
- **Burden:** The delayed/proxy comparison supplies strong external-progress evidence and per-action goal-advance estimates before selection; it does not measure whether raw observations yield the right goal, reachability estimate, or multi-step plan.
- **Why it matters:** A selector can reject a novelty trap when given correct estimates yet still fail in an integrated episode because the candidate goal, model, or plan is wrong.
- **Current evidence:** `docs/evidence/009-goal-acceptance.json` records 64/64 goal-aware versus 0/64 novelty-only synthetic completions under equal five-action budgets; the claim is limited to isolated selection.
- **Next discriminating action:** Connect goal candidates to bounded search and live consequence receipts in Stages 10–12, then compare equal-budget integrated variants in Stage 14 and preserve a separately labeled public result in Stage 15.
- **Resolution condition:** Integrated traces show that acquired goals improve completion or action efficiency without hidden fixture estimates, or the mechanism is retained only as an isolated capability with the negative integrated result preserved.
- **Resolution receipt:** none.

## B-20260821-024 — Planning comparison is compact and evaluator specified

- **Status:** OPEN
- **Stage:** 10, 12, 14, 15, 16
- **Opened:** 2026-08-21
- **Last updated:** 2026-08-21
- **Owner:** Codex
- **Burden:** The planning comparison uses obstacle-free symbolic navigation, evaluator-supplied targets and deterministic models, a simple cyclic exploration baseline, and one injected first-action no-op for recovery.
- **Why it matters:** A bounded search implementation can dominate this fixture yet fail when perception is ambiguous, models branch, goals are wrong, obstacles change mechanics, or search cost approaches the competition envelope.
- **Current evidence:** `docs/evidence/010-planning-acceptance.json` records 24/24 planning versus 0/24 exploration-only and 24/24 recovery versus 0/24 no-recovery under equal 24-action budgets; the task manifest is hashed.
- **Next discriminating action:** Integrate raw-observation state construction and persisted model/goal state in Stage 12, compare component ablations on full procedural episodes in Stage 14, and profile expansions/latency/memory in Stage 16.
- **Resolution condition:** Integrated held-out and separately labeled public receipts demonstrate bounded planning value or preserve an honest negative result with the isolated mechanism claim unchanged.
- **Resolution receipt:** none.

## B-20260821-025 — Trace round-trip property generated schema-forbidden keys

- **Status:** RESOLVED
- **Stage:** 03, 07, corrective checkpoint after 10
- **Opened:** 2026-08-21
- **Last updated:** 2026-08-21
- **Owner:** Codex
- **Burden:** Windows CI runs `32453259223` and `32453261970` minimized the purportedly valid arbitrary receipt payload to `{"CREDENTIALS": null}`; the schema correctly rejected it, so the generator's domain contradicted the test name.
- **Why it matters:** Unseeded platform/example variation made CI flaky and a later pass without a strategy correction could mask the invalid property domain.
- **Current evidence:** `docs/evidence/007-trace-property-ci-failure.json`; both Ubuntu jobs passed and both Windows jobs failed at commit `64408e35bea561f3959791adc94d11885270eca4`. The corrected strategy plus explicit schema rejection suite passed four seeds locally, then push run `32454918883` and pull-request run `32454922333` passed on both Ubuntu and Windows.
- **Next discriminating action:** None for this failure; retain the explicit schema rejection tests and the preserved failure receipt.
- **Resolution condition:** Corrective commit passes the full CI matrix while explicit nested credential/reasoning rejection tests remain enabled.
- **Resolution receipt:** corrective commit `686f13ae2601b1215571db921f60335f1153c576`; Actions runs `32454918883` and `32454922333`.

## B-20260821-026 — Live typed checkpoint reconstruction and consequence reconciliation remain open

- **Status:** OPEN
- **Stage:** 11, 12, 16
- **Opened:** 2026-08-21
- **Last updated:** 2026-08-21
- **Owner:** Codex
- **Burden:** Stage 11 validates canonical snapshots for every declared derived subsystem and safely restores a pending action, but it does not itself reconstruct all Stage 12 live typed objects or prove that each official adapter can redeliver/reconcile an already-submitted consequence.
- **Why it matters:** Correct JSON and RNG restoration can still leave a live controller unable to continue, or an adapter might make action outcome state ambiguous after process death.
- **Current evidence:** The child-process exit-23 test restored every canonical field, returned `AWAIT_CONSEQUENCE`, refused resubmission, and matched 20/20 later RNG choices. The cross-level comparison is only a supplied abstract-rule fixture.
- **Next discriminating action:** Implement typed Stage 12 reconstruction and adapter-level pending-consequence tests; exercise partial checkpoint recovery and long-run restart behavior again in Stage 16.
- **Resolution condition:** Synthetic and official-shaped adapter tests resume the same controller state/action stream across process death without duplicated actions; incompatible checkpoints remain preserved for diagnosis.
- **Resolution receipt:** none.

---

## 2026-08-21 Stage 12 updates

### B-20260821-021 — Exploration improvement is isolated from game completion

- **Status update:** NARROWED on one integrated synthetic grid family; public and broader procedural value remain open.
- **Last updated:** 2026-08-21
- **Current evidence:** The full controller completed 32/32 `synthetic-grid-v1` episodes in 190 actions versus 4/32 in 463 actions for the equal-budget cycle baseline. Action alternatives, selection, prediction, and consequence were all receipt-linked.
- **Remaining burden:** Stage 14 must isolate exploration from planning/model/goal interactions on frozen procedural holdouts; Stage 15 must keep the zero-score public smoke separate.
- **Resolution receipt:** `docs/evidence/012-controller-acceptance.json`; controller commit `3fee19d9f82210ba5010af94feac170164a30f3c`.

### B-20260821-022 — World-model comparison supplies symbolic states and plans

- **Status update:** NARROWED for raw synthetic observation integration; model value remains entangled and public behavior unmeasured.
- **Last updated:** 2026-08-21
- **Current evidence:** The Stage 12 controller now derives perception, candidate models, predictions, and plans from raw synthetic frames and records every prediction/consequence chain. The full bundle completed 32/32 versus 4/32 for cycle.
- **Remaining burden:** Stage 14 must compare model/retrodiction removal under identical seeds and budgets. Compact first-party grid behavior cannot establish official-game fidelity.
- **Resolution receipt:** `docs/evidence/012-controller-acceptance.json`.

### B-20260821-023 — Goal comparison begins from supplied evidence and action estimates

- **Status update:** NARROWED for integrated candidate acquisition; independent goal contribution remains open.
- **Last updated:** 2026-08-21
- **Current evidence:** Stage 12 creates, ranks, retires, and reopens source-linked goal candidates from controller observations, including level transitions and revisits. The full integrated bundle succeeds on the synthetic grid comparison.
- **Remaining burden:** Stage 14 must isolate goal scoring/acquisition; Stage 15 must preserve the public zero and avoid treating synthetic goal success as public evidence.
- **Resolution receipt:** `docs/evidence/012-controller-acceptance.json`.

### B-20260821-024 — Planning comparison is compact and evaluator specified

- **Status update:** NARROWED for live one-action-at-a-time synthetic integration; complexity and official-game benefit remain open.
- **Last updated:** 2026-08-21
- **Current evidence:** Plans are now derived inside the integrated controller, only one action is emitted before validating its returned consequence, and 190/190 actions have complete chains. The full bundle completed 32/32 synthetic episodes.
- **Remaining burden:** Stage 14 must isolate planning and recovery effects on procedural holdouts; Stage 16 must profile search latency/memory; Stage 15 must measure official public behavior without game-specific changes.
- **Resolution receipt:** `docs/evidence/012-controller-acceptance.json`.

### B-20260821-026 — Live typed checkpoint reconstruction and consequence reconciliation remain open

- **Status update:** RESOLVED for Stage 12 typed reconstruction and official-shaped consequence reconciliation; Stage 16 long-run robustness remains a separate burden.
- **Last updated:** 2026-08-21
- **Current evidence:** All 32 synthetic checkpoint artifacts restored exactly with zero event duplication. Focused tests restore complete and faulted phases, pending plan/prediction state, counters, explored coordinates, hypotheses, models, goals, and memory; pending submissions cannot be resent, and mismatched returned actions preserve the actual consequence before faulting.
- **Remaining burden:** Profile repeated restart and partial-checkpoint behavior under the Stage 16 long-run envelope.
- **Resolution receipt:** `docs/evidence/012-controller-acceptance.json`; controller commit `3fee19d9f82210ba5010af94feac170164a30f3c`.

## B-20260821-027 — Integrated controller success is synthetic while the public smoke scored zero

- **Status:** OPEN
- **Stage:** 12, 14, 15, 19
- **Opened:** 2026-08-21
- **Last updated:** 2026-08-21
- **Owner:** shared
- **Burden:** The full controller completed 32/32 compact synthetic grid episodes, but its only Stage 12 official local smoke used an exposed development game for eight actions and returned score 0.0 with zero levels completed.
- **Why it matters:** Promoting a strong first-party mechanism result into a public or hidden-game claim would erase the measured distribution boundary.
- **Current evidence:** `docs/evidence/012-controller-acceptance.json` preserves both results under separate exact labels.
- **Next discriminating action:** Run Stage 14 on frozen synthetic holdouts, then Stage 15 smoke/development and one frozen public holdout under the declared manifest without adding game-specific rules.
- **Resolution condition:** Never resolved by synthetic evidence alone; narrow only with separately labeled official public receipts.
- **Resolution receipt:** none.

## B-20260821-028 — Pinned official FrameData may expose a default RESET-shaped action input

- **Status:** ACCEPTED_LIMIT
- **Stage:** 12, 15, 16
- **Opened:** 2026-08-21
- **Last updated:** 2026-08-21
- **Owner:** Codex
- **Burden:** The pinned toolkit can materialize `FrameData.action_input` as `RESET` even where no action acknowledgement is semantically present.
- **Why it matters:** Treating that default as the returned consequence action can falsely fault a correct controller; ignoring real mismatches would weaken receipt integrity.
- **Current evidence:** The official wrapper alone normalizes the absent/default case to no acknowledgement. Direct adapters retain exact mismatch validation, and the pinned wrapper regression passes.
- **Next discriminating action:** Revalidate this boundary against any pinned SDK upgrade and preserve real returned-action mismatch tests.
- **Resolution condition:** Upstream provides an unambiguous presence contract or the compatibility rule remains pinned and covered.
- **Resolution receipt:** `tests/competition/test_controller_offline_integrity.py`; commit `3fee19d9f82210ba5010af94feac170164a30f3c`.

## B-20260821-029 — Stage 12 preacceptance exposed restart, seed, and revisit defects

- **Status:** RESOLVED
- **Stage:** 12
- **Opened:** 2026-08-21
- **Last updated:** 2026-08-21
- **Owner:** Codex
- **Burden:** Fresh workers initially failed an enum import and one reconstruction field; wrapper-derived seeds could exceed the signed 64-bit contract; audit tests mishandled a closed journal; revisiting a level could collide derived identities; and decreasing level indices could emit a false completion event.
- **Why it matters:** In-process happy paths would have hidden restart and lifecycle defects at exactly the boundaries the controller is meant to preserve.
- **Current evidence:** The final 21-test focused suite passes in fresh processes; strict mypy and Ruff pass; the final 32-seed measurement completes with 32 verified restores, zero duplicate events, and zero faults.
- **Next discriminating action:** Retain regressions and repeat them in clean-clone and long-run Stage 16/18 verification.
- **Resolution condition:** Named defects are corrected and covered without erasing their failure history.
- **Resolution receipt:** commits `fb383c0` and `3fee19d`; `docs/evidence/012-controller-acceptance.json`.

## B-20260821-030 — Official online API controller execution lacks credentials

- **Status:** BLOCKED_EXTERNAL
- **Stage:** 12, 15
- **Opened:** 2026-08-21
- **Last updated:** 2026-08-21
- **Owner:** Christopher D. Pang
- **Burden:** No official online ARC3 credential was available, so the final Stage 12 controller was not measured through the online API surface.
- **Why it matters:** Offline adapter contracts and local public execution do not prove authentication, transport, quota, or server behavior.
- **Current evidence:** Synthetic, pinned official-shaped wrapper, and official local execution are available; no hosted inference or optional credential was used.
- **Next discriminating action:** Continue all offline work. If an online run is later desired, the smallest owner-only action is to make an already-authorized competition credential available through the documented local secret mechanism; do not transmit it in chat.
- **Resolution condition:** A separately labeled `online-public` receipt passes with credential provenance kept out of repository artifacts.
- **Resolution receipt:** none.
