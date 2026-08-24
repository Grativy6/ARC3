# Workflow 002 — Kaggle competition adapter and first honest RHAE

**Status:** active; implementation and preflight in progress
**Implementation branch:** `build/002-kaggle-competition-adapter`
**Base:** exact merged `origin/main` at
`a1931c673b90923e1af78127229667544802a096`
**Owner, author, and steward:** Christopher D. Pang

This workflow adds a bounded Kaggle execution surface without deleting or weakening ARC3's
persistent research system. AI systems are development tools and assistants, not co-authors,
owners, or independent authorities.

## Frozen claim and authority boundaries

- Build 001 remains `PARTIAL`. Its ten-game public holdout record remains
  `SEALED_UNCONSUMED`; no Build 002 observation may revise that historical conclusion.
- For Build 002 only, the owner has authorized exactly one run over that ten-game public set,
  and only after every offline, source-identity, packaging, competition-mode, notebook, and
  structural-output preflight below passes.
- Authorization is not consumption. Until the one-shot runner starts its first environment,
  Build 002 records `AUTHORIZED_ONCE_NOT_YET_CONSUMED`.
- Once started, the run is consumed even if it fails, crashes, times out, or returns zero score.
  It must not be retried, resumed as a second run, or silently replaced.
- Any score from the public toolkit/local public games is `local-public`. It is not Kaggle-public,
  semi-private, official-private, or official RHAE unless the corresponding official evaluator
  actually returns it.
- Exact private Kaggle wheels, framework input, gateway, scorer, and accepted-terms execution are
  outside current authority. Their absence is `BLOCKED_EXTERNAL`, not a reason to manufacture a
  compatibility or scoring claim.
- No terms acceptance, Kaggle credential use, upload, submission, paid service, merge, release,
  DOI, external representation, or secret disclosure is authorized.

## Controlling sources

Current official ARC-AGI-3 documentation, `arcprize/ARC-AGI`,
`arcprize/ARC-AGI-3-Agents`, `arcprize/ARC-AGI-3-Kaggle-Starter`, ARCEngine, and the current
competition-specific Kaggle metadata control this workflow. Exact identities and unresolved
discrepancies are recorded in `docs/evidence/002-00-official-source-identities.json`.

When sources disagree:

1. competition-specific current Kaggle constraints control generic Kaggle limits;
2. executable pinned behavior controls local execution, with the conflict retained;
3. a returned official score controls only that official surface;
4. unresolved private-surface compatibility fails closed;
5. no source discrepancy may be erased after a later successful run.

The current competition metadata reports a nine-hour CPU/GPU limit. That narrower limit controls
the generic twelve-hour notebook ceiling. The competition governor must reserve safely below nine
hours; merely remaining below twelve hours is insufficient.

## Atomic stages

### Stage 00 — Repository, source, and authority preflight

Acceptance requires:

- all remotes fetched and pruned;
- Build 001 final commit `8a42e43c96ac1edada21725746cdedcee24e68f9` verified ancestral to the exact current merged
  `origin/main`;
- a clean Build 002 branch from that exact `origin/main`, without rewritten history;
- Build 000/001 evidence treated as immutable;
- official repositories, packages, relevant source files, and current competition metadata bound
  by exact commit/tree/blob/file or response hashes;
- every material source discrepancy and unavailable private surface recorded.

Current state: source discovery is complete on available public surfaces; lock/report integration
and final stage acceptance remain pending.

### Stage 01 — Execution-mode separation

Implement explicit `RESEARCH_UNBOUNDED` and `COMPETITION_BOUNDED` modes. Acceptance requires the
research defaults and generic opaque-action mechanism to remain unchanged, while competition mode
is explicit, receipt-bound, deterministic, and rejected on incompatible environment modes.

### Stage 02 — Official agent adapter and granted interface semantics

Integrate the existing corpus and controller behind exact `MyAgent.is_done()` and
`MyAgent.choose_action()` entry points. In competition mode only, grant the documented meanings of
`ACTION1` through `ACTION4` and `ACTION7`; keep `ACTION5` and coordinate-dependent `ACTION6`
evidence-driven. Prove research mode still learns opaque action handles generically.

### Stage 03 — Global tournament governor and lifecycle

Implement a process-global governor with:

- a protected reserve below the controlling nine-hour competition limit;
- dynamic per-environment allocation from remaining runtime and environments;
- legal-action filtering;
- bounded deterministic fallback;
- action-value and opportunity-cost accounting;
- stable stop reasons and failure receipts;
- sequential lifecycle enforcement.

Acceptance also requires one scorecard, every supplied environment included, exactly one `make`
interaction per environment, level-only resets, no game resets, no illegal post-game action, and
deterministic behavior under a supplied seed.

### Stage 04 — Competition-only hot-path policy

In `COMPETITION_BOUNDED` only, disable allocator tracing and automatic per-action whole-state
checkpoint serialization. Retain compact in-memory trace, sparse recovery checkpoints,
deterministic replay, and failure receipts. This change is grounded only in Build 001's matched
performance evidence: allocator tracing off reduced wall time by 80.801 percent and automatic
checkpointing off reduced wall time by 17.538 percent while preserving exact actions and outcomes.
No research default changes.

### Stage 05 — Offline package and cold start

Build a self-contained candidate containing every required first-party module, dependency, model,
corpus asset, configuration, and applicable license notice. Verify at minimum:

- Python and official toolkit version compatibility;
- exact dependency and payload manifests;
- offline installation/import from the packaged wheelhouse or equivalent sealed payload;
- deterministic cold startup through the same entry point used by the notebook;
- runtime and peak-memory bounds;
- notebook/archive size;
- zero bundled credentials or secrets;
- zero evaluation-time internet requirement;
- complete source, configuration, package, and artifact hashes.

A host-site-packages injection, canned output, approximate framework fixture, or static import
scan alone cannot satisfy the cold-start gate.

### Stage 06 — Notebook and `submission.parquet` validation

Generate the Kaggle notebook from the frozen package, execute its local offline entry point, and
validate its generated `submission.parquet` structurally. Validate schema, columns, row identity,
types, uniqueness, completeness, readable Parquet encoding, deterministic regeneration, and
absence of credential/network requirements. No upload or submission is permitted.

Structural validity is not exact private scorer parity. Any unavailable private schema behavior
remains `BLOCKED_EXTERNAL`.

### Stage 07 — Frozen one-shot preflight

Freeze the exact source commit/tree, runtime configuration, dependency lock, package, notebook,
corpus, public partition, seeds, action/runtime/memory budgets, environment ordering, and output
roots. Re-run all source-identity, offline, packaging, competition-integrity, lifecycle, replay,
secret, and output-structure checks against that freeze.

The holdout gate is `OPEN_ONCE` only if every available predicate passes and every exact identity
matches the freeze. Any failure leaves the authorization unspent. The exact private surface may
remain separately `BLOCKED_EXTERNAL`, but no result may be labeled official.

### Stage 08 — Authorized ten-game public run

Execute the frozen public set exactly once. The consumption boundary is the first attempted
environment open/make interaction. Persist an append-only launch receipt before that boundary.
From then on, interruption is a consumed failed attempt, not authority for a rerun.

The result must include every environment, including zero/failure rows for environments that
receive only bounded fallback. Capture total local-toolkit RHAE, completed games and levels,
per-game/per-level scores, agent actions and human baselines, wall time, peak memory, budget
allocation, reserve, stop reasons, failures by required taxonomy, and exact hashes.

### Stage 09 — Result seal and failure analysis

Independently verify the complete scorecard/trace/artifact graph. Classify each failure as exactly
one primary category among perception, goal inference, rule learning, planning, execution,
platform, or budget exhaustion, while retaining any secondary evidence. Preserve failed attempts
and superseded evidence. Do not turn local-public output into an official claim.

### Stage 10 — Final verification and handoff

Run repository tests, Ruff, formatting, strict mypy, replay/property checks, lifecycle and package
checks, offline cold start, secret and competition-integrity scans, artifact/hash verification,
Git integrity, and clean-clone validation. Commit and push the Build 002 branch, open or update a
draft PR, and prepare the final report and owner handoff. Do not merge or submit.

## Persistent-run protocol

After each atomic task:

1. run the smallest relevant verification;
2. append the exact invocation and result to `docs/ledger/build-002-VALIDATION.md`;
3. update `docs/ledger/build-002-run-state.json` atomically;
4. append material decisions to `docs/ledger/build-002-DECISIONS.md`;
5. append unresolved failures, source conflicts, and superseded evidence to
   `docs/ledger/build-002-OPEN-BURDENS.md`;
6. commit a coherent checkpoint and push when credentials/network permit.

No unresolved burden is deleted. A later repair marks it resolved and points to the repair while
retaining the original observation.

## Completion states

Each stage ends as `PASS`, `PARTIAL`, `BLOCKED_EXTERNAL`, `FAILED_MECHANISM`, or
`FAILED_INFRASTRUCTURE`. `PENDING` and `IN_PROGRESS` are run-state markers, not terminal evidence
claims.

Build 002 is complete only after all achievable stages are terminal, the implementation and exact
adapter are pushed, the draft PR is current, the one-shot run is sealed or honestly blocked, the
notebook and `submission.parquet` validate locally, and the handoff separates measured results,
open burdens, and owner-only actions.
