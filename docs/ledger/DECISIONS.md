# ARC3 decision ledger

This file records material decisions made during the autonomous build. It is append-oriented: do not erase an older decision when it changes. Add a superseding entry and link both.

## Entry template

```markdown
## D-YYYYMMDD-NNN — Short title

- **Status:** PROPOSED | ADOPTED | SUPERSEDED | REJECTED
- **Stage:** 00–20
- **Date:** ISO-8601
- **Commit:** SHA or `pending`
- **Decision:** What was chosen.
- **Alternatives:** Serious alternatives considered.
- **Evidence:** Tests, source links, benchmarks, or constraints.
- **Why:** Concise reasoning; no hidden chain-of-thought.
- **Consequences:** What this enables or constrains.
- **Reopening condition:** What evidence should cause reconsideration.
- **Supersedes / superseded by:** IDs or `none`.
```

---

## D-20260820-001 — Use an offline-first competition architecture

- **Status:** ADOPTED
- **Stage:** workflow bootstrap
- **Date:** 2026-08-20
- **Commit:** pending
- **Decision:** The production competition policy must not require a remote model or internet service. Hosted models may be used only as development tools outside the evaluated runtime.
- **Alternatives:** Remote LLM agent; hybrid remote/local policy.
- **Evidence:** ARC Prize 2026 competition materials state that internet is unavailable during Kaggle evaluation.
- **Why:** A remote dependency cannot execute in the target evaluator and would make the research result non-reproducible there.
- **Consequences:** Begin with symbolic/algorithmic mechanisms. Any model component must be local, licensed, packaged, and ablated.
- **Reopening condition:** Official competition rules materially change and the new rule is pinned in source identity.
- **Supersedes / superseded by:** none.

## D-20260820-002 — Separate immutable receipts from derived world models

- **Status:** ADOPTED
- **Stage:** workflow bootstrap
- **Date:** 2026-08-20
- **Commit:** pending
- **Decision:** Raw observation/action/consequence events are append-only and hash-linked; hypotheses, summaries, indices, and world models are derived and replaceable.
- **Alternatives:** Mutable memory state only; prose-only logs; direct overwrite of prior beliefs.
- **Evidence:** The project research question requires persistent trace, falsification, and reopening; reproducible replay also requires stable source events.
- **Why:** Later interpretations must not rewrite what was available at action time.
- **Consequences:** Adds storage and implementation cost but enables replay, ablation, provenance, and contradiction analysis.
- **Reopening condition:** Measured overhead prevents competition compliance and a narrower design preserves the same invariants.
- **Supersedes / superseded by:** none.

## D-20260820-003 — Prefer the official Kaggle starter as deployment substrate

- **Status:** PROPOSED
- **Stage:** 00–01
- **Date:** 2026-08-20
- **Commit:** pending
- **Decision:** Adapt the official `ARC-AGI-3-Kaggle-Starter` for packaging while keeping policy code in `src/arc3` and `agent/my_agent.py` thin.
- **Alternatives:** Build notebook/deployment plumbing from scratch; use the full agents repository as the primary codebase.
- **Evidence:** The official starter already implements local play, notebook construction, Kaggle upload plumbing, and the expected agent interface.
- **Why:** Reduces infrastructure risk and keeps effort focused on reasoning mechanisms.
- **Consequences:** Must pin upstream identity and preserve license/attribution; may require adaptation to a richer package layout.
- **Reopening condition:** Stage 00 finds the starter incompatible with current competition rules or the architecture after a measured integration attempt.
- **Supersedes / superseded by:** none.

## D-20260820-004 — Do not grant a public license autonomously

- **Status:** ADOPTED
- **Stage:** workflow bootstrap
- **Date:** 2026-08-20
- **Commit:** pending
- **Decision:** Codex may prepare an MIT-0/CC0 comparison and candidate text but may not add a final `LICENSE` or represent that Christopher has granted one.
- **Alternatives:** Automatically select MIT-0 because the competition recommends it.
- **Evidence:** Public licensing is a consequential legal grant reserved to the owner.
- **Why:** Engineering can proceed without crossing that authority boundary.
- **Consequences:** Prize eligibility remains an open owner action before official release/evaluation.
- **Reopening condition:** Christopher explicitly chooses a license.
- **Supersedes / superseded by:** none.

## D-20260821-005 — Pin Build 000 to measured Stage 00 identities

- **Status:** ADOPTED
- **Stage:** 00
- **Date:** 2026-08-21
- **Commit:** 9e17c9d20334f8e52be2eafcc8f84a1d2f0973b2
- **Decision:** Pin the three official upstream repository heads, `arc-agi==0.9.9`, its Python 3.12 Windows resolution, and content identities for stable primary documentation in `upstream.lock.json`.
- **Alternatives:** Floating main branches and dependency ranges; relying on prose memory.
- **Evidence:** `docs/reports/000-source-identity.md`; `upstream.lock.json`; successful `git ls-remote`, PyPI metadata, documentation fetches, and `uv pip compile`.
- **Why:** Executable and mutable upstream identities must be distinguishable from project interpretation and later upstream changes.
- **Consequences:** Build 000 can be reproduced against an explicit snapshot; later compatibility work must preserve this lock and record a superseding decision.
- **Reopening condition:** A pinned dependency is unusable, unsafe, or incompatible with the current competition surface, supported by a failing executable test.
- **Supersedes / superseded by:** none.

## D-20260821-006 — Implement an equivalent Kaggle wrapper without copying the starter

- **Status:** ADOPTED
- **Stage:** 00–01, 17
- **Date:** 2026-08-21
- **Commit:** 9e17c9d20334f8e52be2eafcc8f84a1d2f0973b2
- **Decision:** Preserve the official `MyAgent` interface and deployment behavior in first-party ARC3 code, but do not copy source from the pinned Kaggle starter.
- **Alternatives:** Copy/adapt the starter; defer all packaging work; use the hosted-model-oriented Agents repository as the runtime.
- **Evidence:** The GitHub tree and repository metadata for `arcprize/ARC-AGI-3-Kaggle-Starter@eeb1535404f321d280a8f9194bbc1d7aca5f05fc` contained no `LICENSE`, `COPYING`, or `NOTICE` and no detected license. The documented interface is sufficient to implement compatibility independently.
- **Why:** An equivalent wrapper satisfies the deployment contract without assuming a copyright permission that was not found.
- **Consequences:** Packaging code must be first-party and tested against the pinned public interface; the starter remains an inspected source with `NOASSERTION` licensing in notices.
- **Reopening condition:** Upstream adds a compatible license or the owner establishes permission and a measured integration benefit justifies adaptation.
- **Supersedes / superseded by:** supersedes proposed D-20260820-003.

## D-20260821-007 — Use a uv-managed CPython 3.12 toolchain

- **Status:** ADOPTED
- **Stage:** 00–01
- **Date:** 2026-08-21
- **Commit:** 9e17c9d20334f8e52be2eafcc8f84a1d2f0973b2
- **Decision:** Use uv-managed CPython 3.12.14 for Build 000. Until the uv executable is on `PATH`, invoke uv reproducibly as `python -m uv` from the installed Python 3.13 launcher.
- **Alternatives:** Use system Python 3.13; install a machine-wide Python; modify the user's shell profile.
- **Evidence:** `arc-agi==0.9.9` declares Python `>=3.12`; Stage 00 measured only system Python 3.13 initially, then installed uv 0.12.5 and managed CPython 3.12.14 successfully.
- **Why:** This meets the official package requirement without an unnecessary system-wide configuration change.
- **Consequences:** Bootstrap scripts must locate `python -m uv` or the uv-managed interpreter explicitly and remain cross-platform.
- **Reopening condition:** CI or packaging demonstrates incompatibility with this managed runtime.
- **Supersedes / superseded by:** none.

## D-20260821-008 — Keep the official SDK optional at the typed core boundary

- **Status:** ADOPTED
- **Stage:** 01–02
- **Date:** 2026-08-21
- **Commit:** 311110299444f71d7e0f0ff0e3b1f8d9c174a01b
- **Decision:** Keep deterministic configuration, trace vocabulary, logging, and the thin starter-compatible agent importable without the official SDK, while locking `arc-agi==0.9.9` as the `official` project extra and in the committed all-extras resolution.
- **Alternatives:** Import the SDK from every core module; omit it from the lock; vendor upstream source.
- **Evidence:** The Stage 01 suite imports and exercises the first-party core with optional dependencies absent; `uv sync --all-extras --dev` installs the pinned official package; `arc3 doctor` reports optional dependency presence without making network calls.
- **Why:** This preserves an offline, testable core and prevents SDK objects or import-time behavior from crossing architectural boundaries, without weakening reproducibility of official integration.
- **Consequences:** Adapters must translate explicitly between SDK and first-party values; missing optional dependencies produce typed boundary errors rather than import failures.
- **Reopening condition:** A measured packaging constraint requires the official wheel in the minimal competition runtime, while retaining the same typed boundary and offline behavior.
- **Supersedes / superseded by:** none.

## D-20260821-009 — Enforce stricter first-party SDK semantics

- **Status:** ADOPTED
- **Stage:** 02
- **Date:** 2026-08-21
- **Commit:** 63ee8a6069d7af4fe39d92277b6702ff253d7aa1
- **Decision:** Treat the pinned SDK as an environment transport/scorer boundary, but validate exact coordinates, advertised-action membership, terminal lifecycle, mode precedence, and credential-safe logging in first-party code before any upstream call.
- **Alternatives:** Trust upstream Pydantic coercion and wrapper lifecycle; fork or vendor the SDK.
- **Evidence:** `docs/reports/002-official-sdk-baselines.md`; 27 focused tests; executable probes preserved in `docs/evidence/002-baseline-scorecards.json` and the Stage 00 discrepancy ledger.
- **Why:** Measured upstream behavior is intentionally permissive in several places and the inherited competition operation mode is networked. ARC3's offline/integrity contract is stricter.
- **Consequences:** Invalid or ambiguous upstream values become typed adapter failures; production paths suppress upstream details that may contain credentials; official scoring behavior remains untouched.
- **Reopening condition:** A pinned upstream release supplies equivalent strict semantics and passes the same first-party compatibility tests.
- **Supersedes / superseded by:** none.

## D-20260821-010 — Freeze public partitions by deterministic hash with visible exposure overrides

- **Status:** ADOPTED
- **Stage:** 02, 13, 15
- **Date:** 2026-08-21
- **Commit:** 63ee8a6069d7af4fe39d92277b6702ff253d7aa1
- **Decision:** Assign current public names by sorted `SHA-256(salt + NUL + stable_name)` into fixed-size smoke/development/holdout partitions. Move any already-opened game to development without erasing its original assignment.
- **Alternatives:** Curate favorable partitions; treat every public game as development; claim a previously opened game remains held out.
- **Evidence:** `docs/evaluation/public-game-partitions.v0.1.json`; the pre-manifest `ls20` SDK probe.
- **Why:** Deterministic assignment reduces selection bias, while an explicit exposure override preserves honest provenance.
- **Consequences:** `ls20` is permanently development for Build 000 even though its original hash rank was holdout; 10 public holdout games remain unopened at the gameplay level.
- **Reopening condition:** A versioned upstream game-set change requires a new manifest and salt while preserving this manifest and all opened-game receipts.
- **Supersedes / superseded by:** none.

## D-20260821-011 — Bind immutable receipts with canonical event hashes

- **Status:** ADOPTED
- **Stage:** 03
- **Date:** 2026-08-21
- **Commit:** 8fd5a056a71ae52fa37f83f3c3614ae1f0a4f7c3
- **Decision:** Store raw environment receipts as canonical JSON events in a SHA-256 previous-event chain, keep frame bodies in a content-addressed write-once blob store, and make summaries, indices, checkpoints, and migrations explicitly derived artifacts.
- **Alternatives:** Mutable controller logs; a database without exportable canonical identities; full frame duplication in every event; storing unrestricted policy reasoning.
- **Evidence:** `docs/reports/003-immutable-trace-replay-checkpoint.md`; 29 focused tests; the benchmark and fault matrix in `docs/evidence/003-trace-acceptance.json`.
- **Why:** Stable source identities allow deterministic replay, contradiction audit, and non-destructive reinterpretation while avoiding duplicate large frames and hidden chain-of-thought storage.
- **Consequences:** Every integrated action path must emit validated concise receipts; replacement derived state must cite immutable event IDs; runtime/storage cost remains measurable and reopenable.
- **Reopening condition:** Integrated profiling exceeds a current evaluator bound, or a fault test demonstrates that the same source-trace invariants require a narrower representation.
- **Supersedes / superseded by:** implements D-20260820-002; superseded by none.

## D-20260821-012 — Keep perception geometric and correspondence explicitly plural

- **Status:** ADOPTED
- **Stage:** 04
- **Date:** 2026-08-21
- **Commit:** ed49b841f3e9f6f5c9a4a6a965e2a60f1c4c3fa5
- **Decision:** Restrict the observation-derived perception layer to grid, color, geometry, delta, relation, and action-correlation measurements; represent close temporal matches as multiple correspondence alternatives and defer role, causal-rule, and goal promotion to typed hypothesis machinery.
- **Alternatives:** Label a player/goal directly from visual heuristics; greedily choose one best temporal identity; make palette values semantic by default.
- **Evidence:** `docs/reports/004-perception-and-frame-differencing.md`; 30 focused tests; deterministic 64×64 benchmark and permutation properties in `docs/evidence/004-perception-acceptance.json`.
- **Why:** A measurement layer must not turn a plausible interpretation into an observation or hide equally supported identity assignments.
- **Consequences:** Downstream world models consume explicit alternatives and generic structural features; they must supply evidence before promoting identity or goal claims.
- **Reopening condition:** Measured downstream failures show that additional generic measurements are needed while preserving the same observation/interpretation boundary.
- **Supersedes / superseded by:** none.

## D-20260821-013 — Derive hypothesis state from immutable typed lifecycle events

- **Status:** ADOPTED
- **Stage:** 05
- **Date:** 2026-08-21
- **Commit:** 5ee32263b5345bcbcb2b5a2f490b08c7f602b1e2
- **Decision:** Represent each candidate rule as one of nine typed families and derive its current status, evidence, lineage, rank, conflicts, and plan dependencies by folding immutable lifecycle events. Keep every rejected form retrievable and make reopening emit explicit dependent-plan invalidation.
- **Alternatives:** Mutable best-guess dictionaries; delete rejected explanations; treat numeric ranks as probabilities; silently repair dependent plans after belief changes.
- **Evidence:** `docs/reports/005-typed-hypothesis-registry.md`; 20 focused tests and the complete synthetic lifecycle in `docs/evidence/005-hypothesis-acceptance.json`.
- **Why:** Later success must not rewrite what a prior hypothesis claimed, what evidence existed, or when dependent plans became unsupported.
- **Consequences:** World-model and planning stages can consume typed, rebuildable candidates and must respond to reopening signals; rank values remain explicitly uncalibrated.
- **Reopening condition:** Held-out evidence demonstrates that the vocabulary cannot express a needed generic rule or that a deterministic transition loses source lineage.
- **Supersedes / superseded by:** none.

## D-20260821-014 — Separate procedural production observations from evaluator truth

- **Status:** ADOPTED
- **Stage:** 06
- **Date:** 2026-08-21
- **Commit:** 7282c99286aa48bad310d22f138766d117d3e367
- **Decision:** Generate deterministic procedural episodes through an official-shaped production session while keeping exact rules, goals, transition annotations, contradictions, and oracle plans on an evaluator-only object. Freeze development, held-out-combination, and wholly held-out-family generator domains.
- **Alternatives:** Put rule labels in observations; test only curated public games; expose oracle annotations to simplify controller development; draw every parameter from one shared range.
- **Evidence:** `docs/reports/006-synthetic-environment-laboratory.md`; 16 focused tests; 630 solvable/leakage-checked episodes and pinned random baselines in `docs/evidence/006-lab-acceptance.json`.
- **Why:** General mechanisms need repeatable unseen-rule tests whose answers cannot leak through the production interface and whose held-out status is explicit.
- **Consequences:** Controller code may consume only `LabSession` observations; evaluator ground truth is limited to scoring, diagnostics, and test assertions; synthetic results remain separately labeled.
- **Reopening condition:** A leakage test fails, a seeded episode is unsolvable, or measured public transition structure demonstrates a missing generic laboratory axis.
- **Supersedes / superseded by:** none.

## D-20260821-015 — Spend probes on model disagreement under an explicit budget

- **Status:** ADOPTED
- **Stage:** 07
- **Date:** 2026-08-21
- **Commit:** a699ef8edb0befac5fadc9906e6b1fb10d86ac1b
- **Decision:** Rank legal probes using explicit alternative-discrimination, progress, reversibility, novelty, failure-risk, repetition, and budget-pressure terms; scope ineffective-action suppression to structural conditions; enable undo only after a receipt establishes restoration semantics.
- **Alternatives:** Fixed action cycling; novelty-only probing; assume conventional directional/undo names are authoritative; permanently blacklist a no-op action across changed states.
- **Evidence:** `docs/reports/007-action-semantics-and-exploration.md`; 14 focused tests; the 101-case comparison in `docs/evidence/007-exploration-acceptance.json`.
- **Why:** Environment actions are costly, while internal comparison of active alternatives is cheap; evidence-gated semantics and condition-specific suppression reduce avoidable actions without turning generic priors into rules.
- **Consequences:** The controller must preserve predicted disagreements and budget state before probe selection; near budget it falls back to progress/risk, and game over mandates reset.
- **Reopening condition:** Integrated held-out or public results fail to improve action efficiency, or calibrated risk/progress evidence supports revised utility terms.
- **Supersedes / superseded by:** none.

## D-20260821-016 — Require full-history retrodiction before model promotion

- **Status:** ADOPTED
- **Stage:** 08
- **Date:** 2026-08-21
- **Commit:** pending
- **Decision:** Compile compatible typed hypotheses into deterministic executable candidates, but promote a model only through an artifact that retrodicts every preserved compatible transition or records a declared condition-based exclusion. Preserve contradictory candidates/residuals and provide retrodiction-off only as an explicit ablation.
- **Alternatives:** Select the highest current hypothesis rank; test only the latest transition; silently ignore unsupported rule syntax; collapse disagreeing models to one outcome.
- **Evidence:** `docs/reports/008-retrodictive-executable-world-model.md`; 12 focused tests; four-combination model-selection comparison in `docs/evidence/008-world-model-acceptance.json`.
- **Why:** A rule that narrates the latest consequence but contradicts preserved history has not earned executable promotion.
- **Consequences:** Every promoted model carries a test/exclusion/contradiction receipt; prediction mismatch reopens models and invalidates dependent plans; ensembles preserve underdetermination.
- **Reopening condition:** Integrated evidence shows the gate is too strict or too permissive, supported by preserved transition artifacts and an alternative that retains contradiction visibility.
- **Supersedes / superseded by:** none.
