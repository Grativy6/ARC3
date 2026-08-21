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

- **Status:** OPEN
- **Stage:** 01, 18
- **Opened:** 2026-08-21
- **Last updated:** 2026-08-21
- **Owner:** Codex
- **Burden:** CI configuration and local bootstrap contracts can pass while a pushed Linux/Windows job or an isolated clone still fails.
- **Why it matters:** Repository-local success is not evidence of cross-platform or clean-clone reproducibility.
- **Current evidence:** Local Windows `scripts/bootstrap.ps1 -Check` passed; CI YAML and bootstrap contents have executable contract tests. No remote Actions result or true clean-clone receipt is claimed yet.
- **Next discriminating action:** Observe the pushed Stage 01 Actions run, then perform the Stage 18 fresh-clone locked bootstrap and artifact verification.
- **Resolution condition:** Linux and Windows CI plus the declared Stage 18 clean-clone checks pass, or failures are preserved with exact outputs.
- **Resolution receipt:** none.
