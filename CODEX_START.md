# Start ARC3 in Codex

This repository is prepared for one long, autonomous, resumable Codex build.

## 1. Open the correct branch

Until the workflow PR is merged, open:

```text
workflow/000-autonomous-arc3
```

The autonomous run will create its own implementation branch:

```text
build/000-arc3-end-to-end
```

Do not point the implementation run at `main` unless the workflow files have already been merged there.

## 2. Recommended Codex controls

Use the strongest long-horizon coding configuration available and grant:

- full read/write access to this repository;
- terminal and long-command execution;
- public internet access during development;
- dependency installation;
- Git and GitHub branch/commit/push/PR access;
- available CPU/GPU use;
- parallel isolated worktrees or workers;
- permission to continue without routine confirmations.

Keep these actions disabled or human-confirmed:

- merge to `main`;
- official Kaggle competition submission;
- acceptance of legal terms;
- public license grant;
- spending money or activating paid compute;
- disclosure or creation of credentials;
- external messages sent as Christopher D. Pang.

## 3. Paste this exact launcher

```text
Read AGENTS.md completely, then execute docs/workflows/000-arc3-autonomous-end-to-end.md from beginning to end.

You have full routine engineering permission under AGENTS.md: inspect public primary sources; create and use build/000-arc3-end-to-end; install public dependencies; modify, test, refactor, benchmark, and document the repository; use available CPU/GPU resources; run parallel workers only in isolated worktrees; checkpoint persistently; commit and push after every stage; and open/update the final draft pull request.

Do not stop after analysis, a plan, scaffolding, a partial implementation, one passing toy test, one public-game win, or one failed mechanism. Continue through every achievable stage. Do not ask routine questions. Make reversible decisions, record them in docs/ledger/DECISIONS.md, preserve unresolved burdens in docs/ledger/OPEN_BURDENS.md, and resume from docs/ledger/run-state.json after any interruption.

Use only measured evidence for claims. The final competition agent must run offline and must not contain game-ID-specific solutions or require a hosted model API. Christopher D. Pang is the project author and steward; AI systems are tools and assistants, not co-authors or independent authorities.

Stop only at the explicit human gates in AGENTS.md. At a gate, prepare everything up to the boundary, write the exact smallest owner action in the handoff, and continue all independent work. Do not merge the final PR.
```

## 4. What Codex should do without returning early

The controlling workflow has 21 stages. It is not complete when Codex has merely created a package or agent skeleton.

The run must attempt, in order:

```text
source identity
→ reproducible project foundation
→ official SDK baseline
→ immutable trace/replay/checkpoint
→ perception
→ typed hypotheses
→ procedural environment laboratory
→ information-efficient exploration
→ retrodictive executable world model
→ goal acquisition
→ planning and recovery
→ persistent memory
→ integrated controller
→ evaluation harness
→ ablations
→ official public-game development
→ optimization and integrity checks
→ offline Kaggle package
→ clean-clone verification
→ research report and owner handoff
→ final draft PR
```

A stage may end `PARTIAL`, `FAILED_MECHANISM`, `FAILED_INFRASTRUCTURE`, or `BLOCKED_EXTERNAL`, but its evidence and remaining burden must be preserved. Benchmark difficulty is not itself a reason to stop.

## 5. Persistence check

Within the first few minutes, Codex should:

1. read `AGENTS.md` and every controlling specification;
2. inspect and validate `docs/ledger/run-state.json`;
3. create `build/000-arc3-end-to-end`;
4. update the run state to `IN_PROGRESS`;
5. commit and push the first source-identity checkpoint.

After that, every meaningful task and every stage gets a durable checkpoint. If the Codex turn or machine ends, reopen the repository and paste the same launcher. The run must validate existing evidence and continue from the first incomplete atomic task instead of restarting.

## 6. Expected final response

Codex should return:

- build status;
- final branch and commit;
- draft PR;
- strongest measured result with the correct evaluation label;
- test/type/lint/clean-clone/package status;
- key artifact paths and hashes;
- remaining burdens;
- exactly one smallest owner-only next action.

A low or zero score is acceptable. An unsupported score or hidden gap is not.
