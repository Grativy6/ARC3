# AGENTS.md — ARC3 execution contract

## Controlling instruction

The controlling build plan is:

`docs/workflows/000-arc3-autonomous-end-to-end.md`

Read that file completely before changing implementation files. Then read:

1. `docs/specs/target-architecture.md`
2. `docs/specs/trace-ledger-contract.md`
3. `docs/specs/evaluation-protocol.md`
4. `docs/ledger/run-state.json`
5. `docs/ledger/DECISIONS.md`
6. `docs/ledger/OPEN_BURDENS.md`

If instructions conflict, this priority order controls:

1. Repository owner instructions in the active Codex task
2. This `AGENTS.md`
3. The controlling workflow
4. The three specification documents
5. Existing repository conventions
6. Reversible engineering judgment

## Project identity

- Repository: `Grativy6/ARC3`
- Owner, author, and steward: **Christopher D. Pang**
- AI systems are development tools and assistants, not co-authors, owners, or independent authorities.
- Target: ARC Prize 2026 ARC-AGI-3 interactive reasoning benchmark.
- Primary research question: can a persistent, falsification-aware trace ledger plus an executable world model improve action-efficient generalization in unfamiliar interactive environments?

Do not claim that ARC3 proves PAL, AGI, consciousness, or a general theory of intelligence. Report only bounded measured results.

## Autonomous execution authority

For this workflow, routine engineering approval is already granted. Do not stop to ask permission for ordinary repository work.

You may autonomously:

- inspect, create, edit, move, and delete files inside this repository;
- create and use an isolated Python 3.12 environment;
- install public open-source dependencies;
- clone and inspect public upstream repositories;
- access public technical documentation and issue trackers during development;
- run tests, linters, type checks, profilers, benchmarks, and local game environments;
- use available CPU/GPU resources within the active environment;
- launch parallel workers when their workspaces and outputs are isolated;
- generate recordings, fixtures, reports, notebooks, plots, and reproducibility artifacts;
- create implementation branches, commits, tags for local checkpoints, and push branches;
- open and update a **draft** pull request;
- make reversible technical decisions when the owner has not specified one;
- continue after non-fatal failures by recording the failure, narrowing scope, and trying a justified alternative.

Prefer action over narration. Do not finish after producing only a plan, TODO list, or scaffolding unless a hard external blocker truly prevents implementation.

## Actions that remain human-gated

Do **not** perform these without an explicit later instruction from Christopher:

- accept Kaggle or ARC Prize legal terms;
- submit an official Kaggle competition entry or spend one of the daily submissions;
- merge a pull request into `main`;
- publish a release or DOI;
- choose or irrevocably grant a public license on Christopher's behalf;
- spend money, purchase compute, or activate a paid service;
- send external messages, contact organizers, or represent Christopher;
- disclose, rotate, or transmit secrets;
- weaken account security, branch protection, or repository visibility;
- claim a private, semi-private, or official score that was not actually returned by the corresponding evaluator.

When a human-gated action is reached, prepare everything up to the boundary, write the exact one-step owner action in the handoff, and continue all other available work.

## Credentials and secrets

- Never commit API keys, Kaggle tokens, cookies, credentials, `.env`, or generated auth files.
- Use environment variables and ignored local files.
- Keep `.env.example` populated only with placeholders.
- Run a secret scan before every milestone PR update and before the final handoff.
- If a required credential is unavailable, use anonymous/public/local modes where possible, create a tested adapter, record the blocker, and continue.

## Persistent-run protocol

This project is designed for long autonomous runs and interruption recovery.

At startup:

1. inspect git status and current branch;
2. read `docs/ledger/run-state.json`;
3. verify whether the recorded latest commit exists;
4. resume the first incomplete atomic task rather than restarting completed work;
5. validate existing artifacts before trusting their status.

After every meaningful atomic task:

1. run the smallest relevant verification;
2. update `docs/ledger/run-state.json` atomically;
3. append material decisions to `docs/ledger/DECISIONS.md`;
4. append unresolved failures or uncertainty to `docs/ledger/OPEN_BURDENS.md`;
5. commit a coherent checkpoint;
6. push when network and credentials permit.

After every workflow stage:

- run the full stage acceptance suite;
- write or update the stage report under `docs/reports/`;
- update the draft PR body with measured status;
- mark the stage complete only when its evidence paths exist.

Never erase an unresolved burden merely because a later approach succeeds. Mark it resolved with the resolving artifact and commit.

## Git policy

- Never develop directly on `main` unless the owner explicitly instructs it.
- If no implementation branch exists, create `build/000-arc3-end-to-end` from the current controlling branch.
- Keep the workflow/setup branch separate when practical.
- Use small, meaningful commits. Suggested prefixes: `build`, `feat`, `fix`, `test`, `bench`, `docs`, `chore`.
- Do not rewrite or force-push shared history unless a source-identity repair requires it and the workflow explicitly records the mapping.
- Do not merge the final PR.

## Source identity and licensing discipline

Use primary sources for benchmark behavior:

- ARC-AGI-3 documentation
- `arcprize/ARC-AGI`
- `arcprize/ARC-AGI-3-Agents`
- `arcprize/ARC-AGI-3-Kaggle-Starter`
- ARC Prize competition pages and Kaggle rules

Pin upstream commit SHAs and package versions in `upstream.lock.json`. Preserve upstream copyright and license notices for copied or adapted material. Maintain `THIRD_PARTY_NOTICES.md`.

Do not silently replace upstream behavior with memory or assumptions. If docs, package behavior, and code disagree, record the discrepancy and prefer the executable pinned version for implementation while flagging the documentation conflict.

Do not add a final project `LICENSE` without owner approval. A candidate MIT-0 text may be prepared under `docs/legal/` for review because prize eligibility requires a permissive open-source license.

## Competition integrity

The final agent must be capable of running without internet access or remote model APIs.

The following are prohibited in final agent logic:

- hard-coded solutions keyed to public game IDs or versions;
- manually encoded action sequences for known games;
- importing hidden/private evaluation information;
- runtime calls to OpenAI, Anthropic, Google, xAI, or any other hosted model/API;
- reading game source code during evaluation to extract the solution;
- changing scoring, environment, or submission files to manufacture results;
- reporting local or self-reported scores as verified private scores.

Public game source may be inspected to understand SDK mechanics and build test fixtures, but final policy behavior must derive from observations, action receipts, generic priors, and learned/general rules. Add static tests that fail if production policy code contains known game IDs.

## Evidence and claim rules

- A score exists only when accompanied by a scorecard or reproducible evaluation artifact.
- Label every result as one of: `synthetic`, `local-public`, `online-public`, `Kaggle-public`, `semi-private`, or `official-private`.
- Preserve random seeds, package versions, commit SHA, configuration, runtime, hardware description, and action budget.
- Distinguish completion rate from RHAE/action efficiency.
- Never promote an anecdotal win into a generalization claim.
- Compare every major improvement against a pinned baseline and at least one ablation.
- Store concise decision rationale and hypothesis state; do not attempt to store hidden chain-of-thought.

## Engineering standards

Unless the pinned upstream requires otherwise:

- Python: 3.12
- Environment/package manager: `uv`
- Packaging: `pyproject.toml`, `src/` layout
- Tests: `pytest` with deterministic seeds
- Property tests: `hypothesis` where useful
- Lint/format: `ruff`
- Type checking: `mypy --strict` for first-party code
- Data validation: typed dataclasses or Pydantic models
- Structured logs: JSONL for immutable traces, JSON/Parquet/Markdown for derived reports
- CI: Linux and Windows smoke coverage where feasible

Production agent code must be:

- deterministic under a supplied seed;
- restartable from checkpoints;
- bounded by explicit action, wall-clock, and memory budgets;
- robust to malformed model output because no remote model should be required;
- safe when `GAME_OVER` permits only `RESET`;
- compatible with variable action spaces and coordinate-based `ACTION6`;
- free of network requirements in competition mode.

## Architectural invariants

Keep these separations explicit:

- observation is not interpretation;
- frame difference is not object identity;
- candidate rule is not accepted rule;
- prediction confidence is not evidence;
- goal hypothesis is not permission to act;
- successful action does not rewrite the prior hypothesis as having been known;
- raw trace is immutable; summaries and indices are derived;
- public-game tuning is not hidden-game generalization;
- narrative explanation is not a score.

Every environment action should be traceable to:

1. the observation available at the time;
2. the active candidate world models/goals;
3. the selected probe or plan;
4. alternatives considered at a summary level;
5. the returned consequence;
6. the update or reopening caused by that consequence.

## Resource discipline

- Begin with symbolic and algorithmic baselines before adding trainable models.
- Profile before optimizing.
- Prefer information-efficient probes because environment actions are squared in the RHAE penalty.
- Internal computation is cheaper than environment interaction, but still enforce wall-clock and memory budgets compatible with the current Kaggle rules.
- Do not download very large models or datasets without evidence that they are necessary and compatible with offline competition packaging.
- Cache public dependencies and games locally when licensing and rules allow.

## Failure handling

A stage may end in one of these statuses:

- `PASS` — acceptance criteria met;
- `PARTIAL` — useful bounded result, remaining burden recorded;
- `BLOCKED_EXTERNAL` — credential, legal, service, or unavailable-resource boundary;
- `FAILED_MECHANISM` — implementation disproved the attempted mechanism;
- `FAILED_INFRASTRUCTURE` — tooling/environment failure, with reproducible evidence.

Do not relabel failure as success. A failed mechanism can still be a successful experiment.

When a command fails:

1. capture command, exit code, and concise stderr;
2. identify whether the fault is code, dependency, environment, network, or upstream;
3. attempt bounded repairs;
4. add a regression test when repaired;
5. record the unresolved burden if not repaired;
6. continue independent stages when possible.

## Definition of done

The autonomous run is complete only when all achievable stages in the controlling workflow have been executed and the repository contains:

- a working, typed ARC-AGI-3 agent;
- deterministic local evaluation and replay tooling;
- an immutable trace ledger and checkpoint/resume path;
- a general perception → hypothesis → world-model → goal → plan → action loop;
- pinned baselines and ablations;
- measured reports with honest labels;
- an offline Kaggle-package candidate;
- clean tests, lint, type checks, and secret scan;
- source identity and third-party notices;
- a final handoff with exact owner-only next steps;
- a pushed implementation branch and updated draft PR when GitHub access permits.

If measured performance remains low, finish honestly with the strongest reproducible system and a prioritized residual map. Do not stop merely because the benchmark is difficult.
