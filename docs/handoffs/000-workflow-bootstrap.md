# ARC3 Workflow 000 bootstrap handoff

Status: **WORKFLOW_READY**  
Repository: `Grativy6/ARC3`  
Workflow branch: `workflow/000-autonomous-arc3`  
Draft PR: `https://github.com/Grativy6/ARC3/pull/1`  
Owner/author/steward: **Christopher D. Pang**

## Result

The repository now contains a complete autonomous, persistent, start-to-finish Codex workflow for building and evaluating an ARC-AGI-3 agent.

This bootstrap contains **the workflow and contracts only**. It does not yet contain an implemented ARC3 agent, a local score, a Kaggle score, or an official submission.

## Controlling files

- `AGENTS.md` — autonomy, safety, evidence, competition-integrity, and human-gate contract.
- `CODEX_START.md` — exact launcher and recommended Codex controls.
- `docs/workflows/000-arc3-autonomous-end-to-end.md` — 21-stage implementation workflow.
- `docs/specs/target-architecture.md` — target reasoning architecture.
- `docs/specs/trace-ledger-contract.md` — append-only receipt, replay, and checkpoint schema.
- `docs/specs/evaluation-protocol.md` — baselines, partitions, metrics, ablations, and result labels.
- `docs/ledger/run-state.json` — interruption/resume state.
- `docs/ledger/DECISIONS.md` — material decision lineage.
- `docs/ledger/OPEN_BURDENS.md` — unresolved burdens and human gates.
- `docs/legal/LICENSE-DECISION.md` — explicit record that no final license has yet been granted.

## Permission shape

Codex has advance routine permission to:

- create the implementation branch;
- modify the repository;
- install public dependencies;
- inspect public primary sources and upstream code;
- use available CPU/GPU resources;
- run long tests, benchmarks, profiling, and isolated parallel workers;
- checkpoint, commit, and push every stage;
- open/update a draft implementation PR;
- continue after bounded failure and preserve the failure evidence.

Codex does not have authority to:

- accept legal terms;
- grant the public license;
- spend money;
- expose credentials;
- submit officially to Kaggle;
- merge to `main`;
- contact third parties as Christopher.

## Exact next action

Open the branch `workflow/000-autonomous-arc3` in Codex and paste:

```text
Read AGENTS.md completely, then execute docs/workflows/000-arc3-autonomous-end-to-end.md from beginning to end.

You have full routine engineering permission under AGENTS.md: inspect public primary sources; create and use build/000-arc3-end-to-end; install public dependencies; modify, test, refactor, benchmark, and document the repository; use available CPU/GPU resources; run parallel workers only in isolated worktrees; checkpoint persistently; commit and push after every stage; and open/update the final draft pull request.

Do not stop after analysis, a plan, scaffolding, a partial implementation, one passing toy test, one public-game win, or one failed mechanism. Continue through every achievable stage. Do not ask routine questions. Make reversible decisions, record them in docs/ledger/DECISIONS.md, preserve unresolved burdens in docs/ledger/OPEN_BURDENS.md, and resume from docs/ledger/run-state.json after any interruption.

Use only measured evidence for claims. The final competition agent must run offline and must not contain game-ID-specific solutions or require a hosted model API. Christopher D. Pang is the project author and steward; AI systems are tools and assistants, not co-authors or independent authorities.

Stop only at the explicit human gates in AGENTS.md. At a gate, prepare everything up to the boundary, write the exact smallest owner action in the handoff, and continue all independent work. Do not merge the final PR.
```

## Expected first checkpoint

Codex should read the contracts, validate `run-state.json`, create `build/000-arc3-end-to-end`, re-check official ARC/Kaggle sources, pin upstream identities, and push the Stage 00 source-identity commit before moving into implementation.

## Expected final state

The workflow directs Codex to leave:

- a typed offline-capable ARC-AGI-3 agent;
- immutable trace/replay/checkpoint infrastructure;
- procedural test environments;
- baselines and controlled ablations;
- public-game measurements with honest labels;
- a Kaggle package candidate without official submission;
- a clean-clone verification report;
- a research report and final owner handoff;
- a pushed implementation branch and draft PR, unmerged.

If a mechanism fails or the score remains zero, the run still completes the evidence path and preserves the residual rather than stopping or manufacturing success.
