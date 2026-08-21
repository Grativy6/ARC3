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
