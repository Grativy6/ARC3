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
