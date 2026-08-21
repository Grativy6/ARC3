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
