# Workflow 000 — ARC3 autonomous end-to-end build

Status: **READY FOR CODEX**  
Workflow version: **0.1**  
Repository: `Grativy6/ARC3`  
Owner/author/steward: **Christopher D. Pang**  
Execution target: one long-running autonomous Codex turn, resumable after interruption

---

## 0. One-shot launch instruction

Paste this into Codex while this repository is open:

> Read `AGENTS.md`, then execute `docs/workflows/000-arc3-autonomous-end-to-end.md` from beginning to end. You have full routine engineering permission under `AGENTS.md`: inspect public sources, create the implementation branch, install dependencies, modify the repository, run long tests and benchmarks, use available compute, checkpoint persistently, commit and push after every stage, and open/update a final draft PR. Do not stop after planning or scaffolding. Resume from `docs/ledger/run-state.json` if any prior work exists. Use reversible defaults and document them instead of asking routine questions. Stop only at the explicit human gates in `AGENTS.md`; prepare everything up to those boundaries and continue all independent work. Report only measured results.

Recommended Codex setup:

- strongest long-horizon coding model available;
- high or maximum reasoning effort;
- full workspace read/write permission;
- public internet enabled for documentation and dependency acquisition during development;
- GitHub write permission;
- long command/runtime permission;
- no automatic merge to `main`;
- no official Kaggle submission permission.

OpenAI currently documents that an active Codex turn may continue after the usage meter reaches its limit, subject to fair-use limits. This workflow therefore assumes the turn may finish, but persistence must not depend on that behavior.

---

## 1. Mission

Build the strongest honest, reproducible ARC-AGI-3 agent achievable in one autonomous engineering program.

The agent should:

1. enter novel 2D turn-based environments with no instructions;
2. observe exact frames and action availability;
3. preserve an immutable action/consequence trace;
4. infer controllable objects, action semantics, transition rules, and candidate goals;
5. test candidate rules against prior history;
6. choose information-efficient probes when uncertain;
7. plan internally when enough structure is known;
8. preserve failed hypotheses and reopen cleanly on contradiction;
9. carry legitimate knowledge across levels without game-specific scripts;
10. run offline inside the current Kaggle competition envelope;
11. produce measured baselines, ablations, reports, and a submission-ready package.

The run is successful even if the final score is low, provided the mechanism is implemented, honestly evaluated, and left in a strong resumable state. Difficulty is not a stop condition.

---

## 2. Controlling sources

Read primary sources at the start and pin exact identities:

- `https://docs.arcprize.org/`
- `https://arcprize.org/competitions/2026/arc-agi-3`
- `https://github.com/arcprize/ARC-AGI`
- `https://github.com/arcprize/ARC-AGI-3-Agents`
- `https://github.com/arcprize/ARC-AGI-3-Kaggle-Starter`
- the current Kaggle competition/rules page, if accessible without accepting terms

At workflow creation time, relevant public facts included:

- official toolkit package requires Python 3.12;
- grids are up to 64×64 with values 0–15;
- games advertise a variable action subset from reset, simple actions 1–5, coordinate action 6, and undo/action 7;
- only reset is valid after game over;
- official scoring compares completed-level action count with first-time human baselines using a squared ratio;
- internal reasoning does not count as an environment action;
- competition evaluation has no internet access;
- prize-eligible methods must be open sourced under an eligible permissive license;
- actual legal acceptance, licensing, and official submission remain human-gated.

Re-check all mutable rules during Stage 00. Record source URLs, access times, package versions, and commit SHAs in `upstream.lock.json` and `docs/reports/000-source-identity.md`.

---

## 3. Permission envelope

`AGENTS.md` grants broad routine autonomy. In particular, Codex is expected to:

- create code, tests, tooling, reports, and notebooks;
- install public dependencies;
- clone and inspect upstream repositories;
- use public online ARC games when anonymous access or an existing key permits;
- run long local experiments and parallel isolated workers;
- make reversible architectural decisions;
- commit and push stage checkpoints;
- open and maintain a draft PR.

Do not pause for approval over filenames, library choices, refactors, test strategies, or bounded implementation alternatives.

Human gates are limited to legal terms, secrets unavailable to the run, spending, public licensing, official submission, release, external representation, and merging.

---

## 4. Persistence and recovery protocol

The first implementation action is to validate or initialize `docs/ledger/run-state.json`.

### 4.1 Atomic task protocol

For each atomic task:

1. mark task `IN_PROGRESS` in run state;
2. execute it;
3. run its narrow verification;
4. store evidence paths and hashes;
5. record decisions/residuals;
6. mark task `PASS`, `PARTIAL`, or a bounded failure state;
7. commit;
8. push when possible.

### 4.2 Stage checkpoint

Every stage completion requires:

- clean or intentionally documented git state;
- updated run-state file;
- stage report;
- acceptance command output captured or summarized;
- commit SHA;
- draft PR update after the PR exists.

### 4.3 Interruption recovery

On restart:

- never trust `completed` flags without checking evidence;
- verify the recorded commit and artifact hashes;
- resume the first incomplete atomic task;
- preserve partially written data and recover to the last valid trace event;
- do not rerun expensive experiments unless their artifacts are absent or invalid;
- if upstream versions changed, preserve the old locked run and create a new compatibility decision.

### 4.4 Parallel work

Parallelize only independent units, for example:

- synthetic environments;
- trace schema/tests;
- perception primitives;
- packaging research;
- documentation/source review.

Each worker must use an isolated worktree/branch or produce non-overlapping files. The primary runner reviews and integrates all outputs. Never let multiple workers append to the same ledger or mutate the same branch concurrently.

---

## 5. Stage map

| Stage | Name | Required result |
|---:|---|---|
| 00 | Preflight and source identity | pinned upstreams, current rules, run state |
| 01 | Repository foundation | reproducible Python project and CI |
| 02 | Official SDK and baseline loop | random/cycle agents run end-to-end |
| 03 | Immutable trace and replay | sealed hash-linked trace, replay, checkpoint |
| 04 | Perception and frame differencing | tested object/delta primitives |
| 05 | Typed hypothesis registry | evidence, contradiction, lineage, reopening |
| 06 | Synthetic environment laboratory | procedural unseen rule families |
| 07 | Action semantics and exploration | information-efficient generic probes |
| 08 | Retrodictive world model | executable rules explain prior transitions |
| 09 | Goal acquisition | typed goal candidates and progress evidence |
| 10 | Planning and recovery | internal search, one-step execution, replan |
| 11 | Persistent memory | episode/game/generic scopes and resume |
| 12 | Full ARC3 controller | integrated observe→model→act loop |
| 13 | Evaluation harness and baselines | reproducible metrics and partitions |
| 14 | Ablations and mechanism tests | controlled component comparisons |
| 15 | Public-game development | strongest measured local/online public result |
| 16 | Optimization and robustness | bounded runtime, no leakage, adversarial tests |
| 17 | Offline Kaggle package | notebook/package candidate passes offline |
| 18 | Clean-clone release candidate | reproducible verification from scratch |
| 19 | Research report and handoff | full evidence, limitations, owner actions |
| 20 | Draft PR finalization | pushed branch, draft PR, no merge |

Do not skip a stage merely because later work seems more exciting. A stage may be narrowed when blocked, but its burden must remain visible.

---

# STAGE 00 — Preflight and source identity

## Objectives

Establish exact repository, upstream, rules, and environment identity before implementation.

## Tasks

1. Inspect repository metadata, current branch, remotes, and commit graph.
2. Read every controlling file named in `AGENTS.md`.
3. If running on the workflow branch and no implementation branch exists, create `build/000-arc3-end-to-end` from the controlling commit and switch to it.
4. Record host OS, CPU, RAM, available GPU, Python installations, `uv`, git, Docker availability, and network access.
5. Fetch current official docs index and competition page.
6. Clone or query the three official GitHub repositories.
7. Pin:
   - toolkit repository commit;
   - agents repository commit;
   - Kaggle starter commit;
   - `arc-agi` package version and resolved dependencies;
   - relevant license identifiers.
8. Inspect current official action schema, game schema, recording format, scoring, competition mode, and submission constraints.
9. Create:
   - `upstream.lock.json`;
   - `THIRD_PARTY_NOTICES.md`;
   - `docs/reports/000-source-identity.md`;
   - `docs/legal/LICENSE-DECISION.md` recommending eligible options without granting one;
   - `.env.example` placeholders only.
10. Initialize or validate the persistent run ledger.
11. Record all unavailable credentials as external blockers, not implementation failures.

## Acceptance

- source report lists exact commits/versions and URLs;
- no secret appears in git;
- implementation branch exists;
- `run-state.json` points to the branch and current commit;
- mutable competition rules are quoted only with access dates;
- license remains an explicit owner decision.

## Commit

`chore(build-000): pin ARC3 source identity and initialize run ledger`

---

# STAGE 01 — Repository foundation

## Objectives

Create a clean, cross-platform, reproducible development substrate.

## Tasks

1. Choose the official Kaggle starter as the deployment substrate or document a measured reason to build an equivalent wrapper.
2. Use Python 3.12 and `uv`.
3. Create a `src/arc3` package and preserve `agent/my_agent.py` compatibility for the starter.
4. Add:
   - `pyproject.toml`;
   - `.python-version`;
   - `.gitignore` covering credentials, environments, large recordings, generated notebooks, caches, and artifacts;
   - Ruff, strict mypy, pytest, Hypothesis, and coverage configuration;
   - pre-commit configuration;
   - Windows PowerShell and POSIX bootstrap scripts;
   - a cross-platform `arc3 doctor` command;
   - GitHub Actions smoke CI for Linux and Windows where practical;
   - test directory skeleton matching the architecture spec.
5. Copy/adapt upstream scaffold only with attribution and notices.
6. Add a deterministic config system with explicit environment modes:
   - `synthetic`;
   - `local`;
   - `online`;
   - `competition`.
7. Ensure competition mode defaults to networking disabled.
8. Add typed core IDs, enums, and error hierarchy.
9. Add a lightweight structured logger with redaction.
10. Write a clean-clone bootstrap test.

## Acceptance commands

```bash
uv sync --all-extras --dev
uv run ruff check .
uv run ruff format --check .
uv run mypy src agent scripts
uv run pytest -q
uv run arc3 doctor
```

On Windows, run the PowerShell bootstrap/smoke equivalent if the host supports it. CI configuration itself must be validated even if remote Actions have not run yet.

## Commit

`build(000): establish reproducible ARC3 project foundation`

---

# STAGE 02 — Official SDK and baseline loop

## Objectives

Prove the complete observation/action/evaluation path before adding intelligence.

## Tasks

1. Implement a narrow adapter around the pinned `arc-agi` toolkit.
2. Never leak SDK-specific objects through core architecture boundaries; normalize them into first-party types.
3. Implement game discovery and action-space inspection.
4. Implement mandatory game-over reset handling.
5. Add baseline policies:
   - random valid action;
   - deterministic action cycle;
   - deterministic coarse coordinate sweep for `ACTION6`.
6. Add CLI commands such as:

```bash
arc3 games list
arc3 play --agent random --game ls20 --seed 7 --max-actions 100
arc3 evaluate --agent cycle --partition smoke
```

7. Use anonymous access if available. If a preexisting `ARC_API_KEY` is present, use it without printing it. Never request or fabricate one.
8. Capture exact upstream failures and continue with local/synthetic paths if service access fails.
9. Produce a baseline report even when score is zero.

## Acceptance

- at least one synthetic loop runs;
- official SDK imports and lists/creates an environment when available;
- invalid actions are prevented by validation;
- baseline behavior is deterministic under seed;
- zero is reported honestly;
- no game-specific strategy exists.

## Commit

`feat(baseline): integrate ARC-AGI toolkit and deterministic baseline agents`

---

# STAGE 03 — Immutable trace, replay, and checkpoint

## Objectives

Implement `docs/specs/trace-ledger-contract.md` before relying on memory.

## Tasks

1. Define and validate event schemas.
2. Implement canonical JSON serialization and SHA-256 hash chaining.
3. Store large frames/deltas by content hash with deduplication.
4. Implement append, flush, recovery from partial line, chunk sealing, manifest verification, and optional compression.
5. Implement derived indices and rebuild.
6. Implement checkpoint write/validate/restore with RNG state and code/config identity.
7. Instrument baseline agents so every observation, candidate selection, action, and consequence receives receipts.
8. Implement offline replay that can:
   - render frames;
   - rebuild deltas;
   - reproduce concise decision inputs;
   - verify chain integrity;
   - detect event tampering.
9. Add migration harness even if no migration is yet needed.
10. Do not record hidden chain-of-thought; use typed rationale categories and concise summaries.

## Fault injections

- terminate during append;
- corrupt one byte in a sealed event;
- remove a blob;
- restore with wrong config hash;
- duplicate an event ID;
- break previous-event hash.

## Acceptance

All required unit/property/integration tests in the trace contract pass. A synthetic episode survives forced interruption and resumes from the last valid event.

## Commit

`feat(trace): add immutable receipt ledger replay and persistent checkpoints`

---

# STAGE 04 — Perception and frame differencing

## Objectives

Convert raw frames into measurements without importing premature semantics.

## Tasks

1. Implement normalized grids and stable frame hashes.
2. Implement changed-cell masks and metadata deltas.
3. Implement connected components for each color and configurable background candidates.
4. Implement shape signatures invariant to translation and optionally rotation/reflection.
5. Implement component correspondence across frames with explicit ambiguity.
6. Extract:
   - additions/removals;
   - recolors;
   - translations;
   - resize/shape changes;
   - containment, adjacency, overlap;
   - global shifts or repeated patterns.
7. Track candidate controllable objects based on action-correlated change, without promoting identity after one sample.
8. Create visual/debug renderers and concise textual summaries.
9. Build synthetic fixtures with palette/position permutations.
10. Measure runtime and memory on maximum-size frames.

## Acceptance

- exact delta tests pass;
- object identity alternatives remain visible in ambiguous cases;
- palette permutations do not break structural detection;
- no semantic labels such as player/goal are stored in the observation layer;
- performance fits the decision budget.

## Commit

`feat(perception): measure grid deltas components and temporal correspondences`

---

# STAGE 05 — Typed hypothesis registry

## Objectives

Create the mechanism that distinguishes candidate explanations from earned active rules.

## Tasks

1. Implement typed hypothesis records and event-sourced status transitions.
2. Support families named in the target architecture.
3. Add evidence receipts with support, contradiction, and unexplained residuals.
4. Add lineage:
   - parent;
   - narrowed form;
   - superseding form;
   - scope changes.
5. Implement weighted ranking without falsely calling uncalibrated weights probabilities.
6. Preserve rejected hypotheses for retrieval.
7. Implement dependent-plan invalidation when a hypothesis reopens.
8. Add deterministic conflict resolution and ensemble compatibility checks.
9. Add human-readable hypothesis reports generated from structured state.

## Acceptance

A synthetic sequence must demonstrate:

- plausible hypothesis creation;
- support;
- contradiction;
- narrowing or rejection;
- later reopening;
- preservation of the complete historical lineage.

## Commit

`feat(hypotheses): add typed evidence lineage contradiction and reopening`

---

# STAGE 06 — Synthetic environment laboratory

## Objectives

Create a large generalization testbed that does not depend on memorizing public games.

## Tasks

1. Implement a small ARC-compatible synthetic adapter.
2. Create procedural rule families from the evaluation protocol.
3. Randomize:
   - palette;
   - object shapes;
   - positions;
   - action mappings;
   - distractors;
   - level layouts;
   - reversible/irreversible consequences.
4. Separate training/development parameter ranges from held-out combinations and held-out rule families.
5. Generate first-time episodes with no textual instructions.
6. Provide exact ground-truth transition and goal annotations only to the evaluator, never the production controller.
7. Include deliberate false-leading evidence and later contradictions.
8. Add fast batch execution and recording.
9. Add environment self-tests to ensure puzzles are solvable and goal signals are not accidentally leaked.

## Acceptance

- at least 10 rule families exist;
- held-out generation is deterministic under seed;
- baseline scores are measured;
- production controller receives only the same class of observation/action information as official games;
- synthetic ground truth stays evaluator-side.

## Commit

`test(lab): add procedural ARC3 environment and unseen-rule suite`

---

# STAGE 07 — Action semantics and information-efficient exploration

## Objectives

Learn what actions do while minimizing expensive environment interactions.

## Tasks

1. Build action-effect statistics conditioned on state features.
2. Seed directional mappings as weak generic priors only; evidence may override them.
3. Detect no-op, movement, selection, interaction, undo, terminal, and metadata-only effects.
4. Implement candidate coordinate generation for `ACTION6`:
   - component centers;
   - changed cells;
   - empty slots;
   - corners/boundaries;
   - disagreement regions;
   - coarse-to-fine unexplored samples.
5. Implement probe utility with configurable terms for information gain, progress, reversibility, novelty, failure risk, repeated action, and budget pressure.
6. Prefer actions that discriminate active world-model alternatives.
7. Detect and suppress repeated ineffective actions unless they test a changed condition.
8. Exploit undo only when its semantics are supported and the action is available.
9. Add action-budget-aware fallback.
10. Compare exploration policies against random and deterministic cycle baselines.

## Acceptance

On held-out synthetic tasks, exploration must either reduce median actions to identify action semantics versus baselines or yield an honest `MECHANISM_NOT_OBSERVED` report with traces showing why.

## Commit

`feat(exploration): infer action semantics with discriminating low-cost probes`

---

# STAGE 08 — Retrodictive executable world model

## Objectives

Build candidate rules that predict and explain transitions rather than merely narrate them.

## Tasks

1. Define interpretable rule primitives for movement, collision, toggles, transformations, counters, contact, selection, attachment, and coordinate effects.
2. Compile compatible hypotheses into world-model candidates.
3. Implement prediction over candidate actions with alternative outcomes and weights.
4. Implement the retrodiction gate over every compatible prior transition.
5. Score models by fit, complexity, contradictions, and residual coverage.
6. Keep an ensemble when evidence underdetermines the rule.
7. Implement a local simulator for short action sequences.
8. Emit prediction receipts before live actions.
9. Match consequences and reopen dependent models/plans on mismatch.
10. Add property tests preventing a model from being promoted when it contradicts a preserved transition without an explicit narrowed condition.

## Acceptance

- model promotion requires a retrodiction artifact;
- contradictions remain visible;
- an executable model solves or materially improves at least one held-out synthetic family;
- removing retrodiction is available as an ablation;
- simulator predictions are deterministic under state/model identity.

## Commit

`feat(world-model): add retrodiction-gated executable transition models`

---

# STAGE 09 — Goal acquisition

## Objectives

Infer what states are worth pursuing without confusing novelty, progress, and terminal goals.

## Tasks

1. Implement typed goal candidates with source evidence and scope.
2. Detect explicit score/progress/level/win changes from metadata.
3. Infer structural candidates such as exits, matching slots, completion patterns, target contact, and stable discrepancy reduction.
4. Separate:
   - external progress evidence;
   - intrinsic exploration utility;
   - intermediate subgoals;
   - terminal goal hypotheses.
5. Compare candidate goals against prior transitions and level structure.
6. Retire or reopen goals on contradiction.
7. Avoid infinite novelty-seeking after external progress evidence becomes strong.
8. Add synthetic tasks where novelty is a trap.
9. Add reports showing why a goal was selected, without anthropomorphic language.

## Acceptance

The controller distinguishes exploration utility from goal desirability and solves or improves on delayed/proxy-goal synthetic tasks versus novelty-only baseline.

## Commit

`feat(goals): infer typed progress and terminal goal candidates`

---

# STAGE 10 — Planning and recovery

## Objectives

Use internal computation to save environment actions.

## Tasks

1. Build symbolic state representations from the world model.
2. Implement bounded BFS/A*/uniform-cost search for deterministic models.
3. Add bounded belief-state or Monte Carlo search only where uncertainty requires it.
4. Score plans by completion likelihood, action count, risk, and information value.
5. Execute one action at a time.
6. Validate each received consequence against the predicted next state.
7. Invalidate stale plans after model/goal change.
8. Implement recovery modes:
   - replan under same model;
   - choose a discriminating probe;
   - reopen model;
   - use undo when supported;
   - mandatory reset after game over.
9. Add search/time/node budgets and deterministic tie-breaking.
10. Compare with exploration-only and no-recovery ablations.

## Acceptance

On held-out synthetic tasks with multi-step solutions, planning reduces environment actions or materially improves completion under equal budgets. Failed predictions trigger a traceable recovery rather than blind continuation.

## Commit

`feat(planning): add bounded internal search and mismatch recovery`

---

# STAGE 11 — Persistent memory and restart continuity

## Objectives

Carry useful trace across steps and levels while preserving scope and source identity.

## Tasks

1. Implement episode, game, and generic memory stores.
2. Add retrieval by exact event, abstract state, active contradiction, and analogous rule structure.
3. Create source-linked summaries that cannot exist without event ranges/hashes.
4. Implement checkpoint/resume for full controller state.
5. Preserve RNG state and ensure resumed action selection is deterministic.
6. Test process death between action receipt and consequence receipt.
7. Keep game-specific knowledge inside game scope.
8. Prevent production policy from retrieving a solution by game ID.
9. Add bounded-memory policies and trace chunking.
10. Compare with no-memory and no-rejected-hypothesis-retention ablations.

## Acceptance

- resumed synthetic episodes match uninterrupted execution from the checkpoint boundary;
- cross-level knowledge helps at least one procedural family or produces an honest negative result;
- source links survive summary/retrieval;
- memory stays within budget over long runs.

## Commit

`feat(memory): add scoped persistent trace retrieval and deterministic resume`

---

# STAGE 12 — Full ARC3 controller integration

## Objectives

Unify all components behind the official agent interface.

## Tasks

1. Implement the controller contract from the architecture spec.
2. Integrate with `agent/my_agent.py` without duplicating policy logic.
3. Controller step order:
   - validate/normalize observation;
   - append observation receipt;
   - compute measurements;
   - update hypotheses;
   - retrodict models;
   - update goals;
   - generate probe/plan candidates;
   - select and validate action;
   - emit predictions;
   - submit action;
   - apply consequence on next callback;
   - checkpoint according to policy.
4. Add explicit state-machine phases and fault handling.
5. Add deterministic configuration presets:
   - `baseline`;
   - `trace`;
   - `world-model`;
   - `full`;
   - `competition`.
6. Ensure production policy does not require a hosted LLM.
7. Add optional local-model proposal interface only as a disabled experimental plugin.
8. Run end-to-end synthetic and official smoke tests.

## Acceptance

The same controller code runs through synthetic, official local/API, and Kaggle wrapper adapters. All actions have receipt chains. Competition preset makes no network call.

## Commit

`feat(agent): integrate persistent ARC3 observe-model-plan-act controller`

---

# STAGE 13 — Evaluation harness, partitions, and baselines

## Objectives

Implement `docs/specs/evaluation-protocol.md` completely enough to compare mechanisms.

## Tasks

1. Discover public games and create deterministic partition manifest.
2. Mark any game already manually inspected as development, not holdout.
3. Build batch runner with process isolation, timeouts, seeds, budgets, and crash recovery.
4. Use the official scorer/scorecards where available.
5. Generate reproducibility envelopes and compact Markdown/JSON reports.
6. Implement B0–B4 baselines.
7. Add diagnostic metrics from the protocol.
8. Add code/config/upstream identity to every result.
9. Add performance regression thresholds after the first stable run.
10. Add commands:

```bash
arc3 evaluate --partition smoke --agents random,cycle,full --seeds 7,11
arc3 compare --evaluation <id-a> --evaluation <id-b>
arc3 report --evaluation <id>
arc3 verify-artifacts --evaluation <id>
```

## Acceptance

A clean deterministic synthetic comparison runs at least two policies, emits all artifacts, and reports failures instead of dropping them.

## Commit

`bench(harness): add reproducible partitions baselines and evaluation reports`

---

# STAGE 14 — Ablations and mechanism tests

## Objectives

Determine which components actually help.

## Tasks

1. Implement all feasible ablations A1–A10.
2. Predeclare seed sets and synthetic holdouts before running.
3. Run paired comparisons under equal action/compute budgets.
4. Report raw values and effect sizes.
5. Inspect representative success and failure traces.
6. Identify:
   - components with clear benefit;
   - components with context-dependent benefit;
   - components that add cost without measured gain;
   - interactions that cannot be isolated yet.
7. Remove or disable unjustified complexity from the competition preset while preserving experimental code/configuration.
8. Update architecture decisions and open burdens.

## Acceptance

At least one full-vs-ablation mechanism comparison is complete. If no mechanism improves results, preserve the negative result and select the simplest strongest measured policy.

## Commit

`bench(ablations): measure trace retrodiction memory and planning contributions`

---

# STAGE 15 — Public-game development

## Objectives

Run the strongest current system on official public environments without manufacturing a generalization claim.

## Tasks

1. Revalidate public game versions and partition manifest.
2. Run smoke partition first.
3. Debug adapter/infrastructure faults without adding per-game production rules.
4. Run development partition across predeclared seeds and budgets.
5. Profile low-scoring traces and fix only generic mechanisms.
6. Keep a ledger of manual inspections and consumed environments.
7. Re-run pinned baselines after material changes.
8. When the system is frozen for a milestone, commit and open the public holdout exactly once under the protocol.
9. If API access is unavailable, use local official games or record `BLOCKED_EXTERNAL` and continue packaging.
10. Produce `docs/reports/015-public-development.md`.

## Acceptance

One of the following honest outcomes exists:

- `LOCAL_PUBLIC_IMPROVEMENT` over pinned baselines;
- `PUBLIC_HOLDOUT_IMPROVEMENT` under the declared holdout procedure;
- `MECHANISM_NOT_OBSERVED` with complete results;
- `BLOCKED_EXTERNAL` with synthetic/local infrastructure still passing.

Do not call a self-reported public score verified unless the official verification surface returned it.

## Commit

`bench(public): evaluate general ARC3 policy on official public games`

---

# STAGE 16 — Optimization, robustness, and integrity

## Objectives

Make the best measured policy efficient, stable, and hard to fool accidentally.

## Tasks

1. Profile decision latency, memory, trace size, and planner expansion.
2. Optimize measured bottlenecks only.
3. Add caches keyed by immutable identities.
4. Bound coordinate candidates and search nodes.
5. Add malformed frame/metadata/action-space tests.
6. Add game-over, reset, timeout, upstream error, and partial checkpoint recovery tests.
7. Run palette, translation, distractor, action-remap, and rule-change synthetic robustness tests.
8. Add static production-code scan for public game IDs and forbidden network clients in competition paths.
9. Add dependency/secret/license scans.
10. Test on CPU and any available accelerator without making GPU mandatory unless measured benefit justifies it.
11. Freeze the competition configuration.

## Acceptance

- runtime fits conservative current competition budgets;
- peak RAM is measured;
- competition policy has no reachable network dependency;
- game-ID leakage scan passes;
- fault recovery tests pass;
- performance does not regress materially against the pinned milestone.

## Commit

`perf(competition): bound ARC3 runtime memory and failure recovery`

---

# STAGE 17 — Offline Kaggle package

## Objectives

Produce a submission candidate without crossing the human submission boundary.

## Tasks

1. Integrate/adapt the official Kaggle starter at the pinned commit.
2. Keep `agent/my_agent.py` as a thin adapter to first-party policy.
3. Package all required first-party code, dependencies, data, and optional weights.
4. Disable internet in the generated notebook metadata and runtime.
5. Do not bundle secrets or an owner's Kaggle token.
6. Configure CPU by default for a symbolic agent; choose an accelerator only if required by the measured competition preset.
7. Build notebook/package locally.
8. Run it in an offline/sandbox simulation as close to Kaggle as available.
9. Validate output file schema with the official framework.
10. Add `scripts/prepare_kaggle_submission.*` and a human-readable one-command owner path.
11. If Kaggle credentials already exist, they may be used only to validate authentication/status with no submission or rule acceptance; otherwise skip.
12. Produce package hash and software bill of materials.

## Acceptance

- `PACKAGING_PASS` report exists;
- generated candidate runs without internet;
- no secrets scan clean;
- output artifact exists and validates;
- official upload and competition submission are left as explicit owner steps.

## Commit

`build(kaggle): produce offline ARC3 competition package candidate`

---

# STAGE 18 — Clean-clone release candidate verification

## Objectives

Prove that the repository, not the current machine's accumulated state, contains the work.

## Tasks

1. Create a fresh temporary clone/worktree at the candidate commit.
2. Follow only documented bootstrap instructions.
3. Run:
   - dependency lock verification;
   - lint/format;
   - strict type check;
   - unit/property/integration tests;
   - synthetic evaluation smoke;
   - official smoke when available;
   - trace tamper/replay test;
   - offline package build/run;
   - secret and game-ID leakage scans.
4. Reproduce at least one committed benchmark from exact config/seed.
5. Compare artifact hashes or explain permitted nondeterminism.
6. Fix documentation/setup gaps and repeat until clean or externally blocked.
7. Create `docs/reports/018-release-candidate-verification.md`.

## Acceptance

A reviewer can copy exact commands from the report and reproduce the candidate without relying on untracked local files.

## Commit

`test(rc): verify ARC3 from a clean clone and sealed artifacts`

---

# STAGE 19 — Research report and owner handoff

## Objectives

Leave a complete, honest account of what was built and what remains open.

## Tasks

1. Write `docs/research/ARC3-Build-000-report.md` containing:
   - benchmark problem;
   - architecture;
   - trace/world-model hypothesis;
   - implementation;
   - evaluation protocol;
   - measured results;
   - ablations;
   - representative failures;
   - limitations;
   - no-generalization boundaries;
   - future experiments;
   - upstream attribution.
2. Make clear that Christopher D. Pang is author/steward and AI systems were tools.
3. Do not claim PAL proof. A bounded section may state that the implementation tests PAL-inspired trace/reopening ideas if source identity is explicit.
4. Complete `THIRD_PARTY_NOTICES.md` and license inventory.
5. Prepare, but do not activate, an eligible license candidate under `docs/legal/`.
6. Write final handoff `docs/handoffs/000-autonomous-arc3.md` with:
   - final branch/commit;
   - PR;
   - exact setup/run commands;
   - strongest score labels;
   - artifact paths and hashes;
   - external blockers;
   - owner-only actions;
   - prioritized next builds.
7. Update root README with project description, measured status, quickstart, and honest limitations.
8. Close run-state as complete only after evidence paths validate.

## Acceptance

The handoff tells the owner exactly what exists, what worked, what failed, what was not attempted, and the smallest next action for official submission or further research.

## Commit

`docs(build-000): publish ARC3 methods results limitations and handoff`

---

# STAGE 20 — Draft PR finalization

## Objectives

Push a reviewable end state without merging.

## Tasks

1. Rebase or merge the controlling workflow branch only if necessary and safe; never erase provenance.
2. Ensure git status is clean.
3. Push implementation branch.
4. Open a draft PR to `main` if none exists.
5. PR title:

`Build 000: persistent trace-ledger ARC-AGI-3 agent`

6. PR body must include:
   - build status;
   - architecture summary;
   - exact tests;
   - measured result table;
   - packaging status;
   - limitations/open burdens;
   - human-gated actions;
   - final commit SHA.
7. Do not mark ready or merge.
8. Verify the PR diff contains no credentials, giant accidental artifacts, game-specific cheats, or generated notebook noise that should be ignored.
9. Update run-state and handoff with the PR URL/number.
10. Push the final checkpoint.

## Acceptance

- branch and draft PR exist;
- PR points to all reports/evidence;
- no merge performed;
- owner can review with one clear next decision.

## Final commit

`chore(build-000): seal autonomous ARC3 workflow result`

---

## 6. Global implementation rules

These rules apply throughout all stages.

### 6.1 Prefer falsification over narrative completion

When multiple rules explain a transition, preserve the alternatives and choose probes that distinguish them. Do not select the nicest story.

### 6.2 Preserve raw evidence

Never mutate raw observations or action/consequence events. Fix parsers and derived views instead.

### 6.3 Keep public-game logic general

Do not add a game-name conditional to make a test pass. Convert the observed need into a generic operation and test it on procedural variants.

### 6.4 Make expensive actions deliberate

The official score squares action inefficiency. Prefer internal search, retrodiction, and simulation over broad live trial-and-error.

### 6.5 Maintain authority boundaries

Upstream metadata is observation; project interpretation is not upstream truth. A model prediction does not authorize an invalid action. A fluent report does not strengthen the score.

### 6.6 Keep failure useful

A mechanism that fails under a controlled test receives a `FAILED_MECHANISM` artifact and remains available for analysis. Do not delete the failed branch of reasoning.

### 6.7 No hidden dependency on this Codex run

All useful state must end up in repository code, committed data contracts, reports, or ignored-but-manifested artifacts. The next Codex run should not need private conversational memory.

---

## 7. Escalation policy

Codex should not ask routine questions. Use these rules:

### Proceed autonomously

- library choice among compatible permissive dependencies;
- internal data structures;
- test architecture;
- filenames;
- bounded refactors;
- performance optimizations with measured evidence;
- reversible configuration defaults;
- public documentation research;
- local benchmark execution.

### Record and continue

- one public service is temporarily unavailable;
- anonymous API access fails;
- one optional dependency is incompatible;
- GPU is unavailable;
- a model-based path is too heavy;
- a game crashes due upstream fault;
- one stage yields a negative mechanism result.

### Stop only at the exact boundary

- accepting legal terms;
- committing a real secret;
- spending money;
- granting a public license;
- official competition submission;
- merging to main;
- external representation of the owner.

At a hard boundary, write the exact owner action and continue all independent tasks.

---

## 8. End-of-run response contract

The final Codex response should begin with the result, not a diary.

Required format:

```text
BUILD 000: <PASS/PARTIAL/BLOCKED_EXTERNAL>

Final branch: ...
Final commit: ...
Draft PR: ...

Strongest measured result:
- surface: ...
- games/levels: ...
- score/completion/actions: ...
- comparison: ...

Verification:
- tests: ...
- type/lint: ...
- clean-clone: ...
- offline package: ...

Key artifacts:
- ...

Open burdens:
- ...

Owner-only next action:
- exactly one smallest consequential step
```

Do not say the build is complete merely because code was written. Tie completion to evidence.
