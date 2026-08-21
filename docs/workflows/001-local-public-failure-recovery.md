# Workflow 001 — ARC3 local-public failure recovery

Status: **READY FOR CODEX**  
Workflow version: **0.1**  
Repository: `Grativy6/ARC3`  
Owner/author/steward: **Christopher D. Pang**  
Execution target: one long-running autonomous Codex turn, persistently checkpointed and resumable

---

## 0. One-shot launch instruction

Paste this into Codex while `Grativy6/ARC3` is open:

> Read `AGENTS.md`, then execute `docs/workflows/001-local-public-failure-recovery.md` from beginning to end. Build 000 is evidence, not a target to defend. Start from current `main`, preserve every Build 000 artifact and failure, create `build/001-local-public-recovery`, and autonomously implement, test, profile, benchmark, package, commit, push, and maintain a draft PR. You have all routine engineering permissions granted by `AGENTS.md`. Do not ask routine implementation questions. Persist state after every atomic task and resume from the Build 001 ledger after interruption. Keep the ten-game public holdout sealed until the explicit Stage 11 opening gate is earned. Never spend money, accept competition terms, submit to Kaggle, merge, publish a release/DOI, send external messages as Christopher, or grant a license unless the owner has explicitly crossed that human gate. Report only measured results; preserve failed mechanisms and conflicting evidence.

Recommended Codex setup:

- strongest long-horizon coding model available;
- high or maximum reasoning effort;
- full workspace read/write permission;
- public internet enabled for documentation/dependency acquisition during development;
- GitHub write permission;
- long command/runtime permission;
- parallel workers allowed only in isolated worktrees/processes;
- no automatic merge to `main`;
- no official Kaggle submission permission.

The run must remain resumable even if model usage, machine uptime, network access, or a long command ends unexpectedly.

---

## 1. Mission

Build 000 demonstrated a strong bounded mechanism on synthetic tasks and a complete failure of the integrated controller on `local-public`. Build 001 exists to explain and repair that gap **without consuming the sealed public holdout or tuning to game identities**.

The primary questions are:

1. Why did FULL complete 32/32 synthetic episodes in 190 actions but time out in every measured `local-public` FULL run?
2. Which costs dominate wall time and action throughput?
3. Why did palette permutation and action remapping destroy performance despite lower-layer structural tests passing?
4. Can rule changes be detected and reopened after guaranteed exposure?
5. Does the retrodiction gate improve action efficiency enough to justify its runtime/action cost, or should it be narrowed, deferred, or removed from the hot path?
6. Can a generic controller achieve reliable nonzero `local-public` development completion under a predeclared wall-clock/action envelope before any holdout is opened?

Build 001 is successful if it produces a reproducible causal diagnosis and a materially stronger generic controller, even if it still does not earn the holdout-opening gate.

---

## 2. Frozen Build 000 evidence

Treat these as immutable historical observations, not values to rewrite:

- Build 000 branch: `build/000-arc3-end-to-end`
- Build 000 final seal: `ee4938b4fdba8bcea9fa3660d32d7b9597644896`
- Build 000 merged `main` identity at workflow preparation: `cf321c3e0e1aa782076491ee84015d24d0fe28ce`
- synthetic Stage 12: FULL 32/32, 190 actions; deterministic cycle 4/32, 463 actions under equal 16-action budgets;
- synthetic Stage 14: FULL 8/14 in 150 actions; no world-model simulation 1/14 in 211; no goal inference 0/14 in 224;
- Stage 14 retrodiction conflict: disabling retrodiction preserved 8/14 completion and used nine fewer actions;
- `local-public` Stage 15: FULL 0 levels across 30/30 timeouts; B0 random produced the sole nonzero completion;
- `local-public` Stage 18: FULL 0/6 and six timeouts;
- Stage 16 robustness: two palette-permuted and two action-remapped cases failed from base score 1.0 to 0.0;
- one rule-change case was `NOT_EXERCISED`;
- official RHAE remains unmeasured/null;
- the ten-game public holdout remains unconsumed.

Do not alter Build 000 reports to make Build 001 look better. New evidence goes in new Build 001 artifacts.

---

## 3. Human gates and permission envelope

Routine engineering authority is already granted by `AGENTS.md`. Codex should act without asking permission for normal implementation decisions.

### Human-gated actions that remain prohibited without a later explicit owner instruction

- accepting Kaggle or ARC Prize legal terms;
- spending money or enabling paid compute/services;
- official Kaggle/ARC submission or spending a daily submission;
- merging any PR;
- publishing a release or DOI;
- sending external communications as Christopher D. Pang;
- disclosing or transmitting secrets;
- changing repository visibility/security;
- granting a public license unless the owner has explicitly approved the exact license.

### MIT-0 owner gate

`docs/legal/candidates/MIT-0-CANDIDATE.md` is nonoperative until Christopher explicitly approves it. A statement equivalent to **“I approve MIT-0 for ARC3 first-party source”** is sufficient authorization. Merely reading, liking, discussing, or saying the candidate “sounds fine” is not to be interpreted by Codex as a license grant.

If explicit approval is present in the active owner instruction:

1. record the owner decision and timestamp in `docs/legal/LICENSE-DECISION.md`;
2. create the operative root `LICENSE` from the candidate MIT-0 text, excluding all candidate-only boundary text;
3. update notices/metadata consistently;
4. verify no third-party license is overwritten or misrepresented;
5. preserve the original candidate and decision provenance.

If approval is absent, leave licensing untouched and continue all independent Build 001 work.

---

## 4. Competition-integrity constraints

Build 001 must not improve by memorizing public game identities.

Production policy may use only:

- observations and frame deltas available to the agent;
- advertised action spaces and returned consequences;
- generic structural priors;
- persistent receipts and learned world-model state;
- generic algorithms developed on synthetic/procedural and permitted development surfaces.

Prohibited:

- hard-coded public game IDs/versions;
- manually encoded solution sequences;
- reading game source during evaluation to infer solutions;
- hidden/private evaluation information;
- remote hosted-model calls in the final competition agent;
- score fabrication or label promotion.

Static and runtime leakage checks remain mandatory.

---

## 5. Persistence protocol

Create a fresh Build 001 state surface rather than overwriting Build 000 history:

- `docs/ledger/build-001-run-state.json`
- `docs/ledger/build-001-DECISIONS.md`
- `docs/ledger/build-001-OPEN-BURDENS.md`

For every atomic task:

1. mark `IN_PROGRESS` atomically;
2. execute;
3. run the narrowest useful verification;
4. record commands, seeds, environment identity, artifact paths, hashes, runtime, and result;
5. record new decisions and residuals;
6. mark a bounded status (`PASS`, `PARTIAL`, `FAILED_MECHANISM`, `FAILED_INFRASTRUCTURE`, `BLOCKED_EXTERNAL`);
7. commit;
8. push when possible.

On restart, verify evidence/hashes before trusting completion flags. Never rerun an expensive experiment solely because the previous turn ended if valid artifacts already exist.

---

## 6. Stage map

| Stage | Name | Required result |
|---:|---|---|
| 00 | Preflight, Build 000 identity, owner gates | exact base, fresh ledger, license decision handled only if explicit |
| 01 | Failure reproduction | reproduce local-public timeout/failure on frozen Build 000 policy |
| 02 | Hot-path observability | phase-level wall/CPU/RSS/action instrumentation |
| 03 | Throughput diagnosis | causal runtime bottleneck map with bounded microbenchmarks |
| 04 | Palette equivariance | generic palette-invariant representation + metamorphic tests |
| 05 | Action equivariance | action-semantic normalization + remap-invariant controller behavior |
| 06 | Guaranteed rule-change reopening | intervention cases reach the intervention and reopen correctly |
| 07 | Retrodiction decision | paired causal evidence; keep/narrow/defer/remove hot-path gate |
| 08 | Two-speed controller | cheap hot path + bounded deliberative path with explicit budgets |
| 09 | Development recovery | reliable nonzero completion on predeclared local-public development set |
| 10 | Robustness and regression | synthetic strengths retained; permutations/remaps/rule changes pass target |
| 11 | Frozen milestone and holdout gate | earn or refuse holdout opening from predeclared criteria |
| 12 | Holdout evaluation if earned | exactly one sealed holdout evaluation; otherwise explicit non-consumption |
| 13 | Offline package and clean-clone verification | deterministic package, full CI, integrity/secret scans |
| 14 | Research report, handoff, draft PR | bounded claims, exact residuals, pushed draft PR, no merge |

Do not skip failed stages. A failed mechanism is preserved as evidence.

---

# STAGE 00 — Preflight, identity, and owner gates

## Tasks

1. Fetch/pull current `main`; verify Build 000 merge ancestry and exact HEAD.
2. Verify Build 000 handoff/evidence hashes that Build 001 relies upon.
3. Create `build/001-local-public-recovery` from current `main` and switch to it.
4. Record host OS, CPU, RAM, GPU, Python/uv/git identities, network state, and wall-clock source.
5. Re-check mutable ARC-AGI-3 docs/toolkit identities and record any drift without silently upgrading.
6. Initialize fresh Build 001 ledger files.
7. Process MIT-0 only if the active owner instruction explicitly approves it as described in §3.
8. Verify the public holdout manifest remains sealed/unconsumed and record its identity without opening game episodes.
9. Run secret scan and git integrity check.

## Acceptance

- branch exists and is based on exact current `main`;
- Build 000 evidence remains unchanged;
- Build 001 ledger is independent;
- license state accurately reflects explicit owner authority;
- holdout remains unconsumed;
- source and machine identities recorded.

## Commit

`chore(build-001): initialize local-public recovery ledger and source identity`

---

# STAGE 01 — Reproduce the failure before changing it

## Objective

Prove Build 001 can reproduce the Build 000 local-public pathology under the frozen policy before attempting repairs.

## Tasks

1. Identify the exact production FULL controller/config used for Stage 18.
2. Run a small predeclared reproduction subset from the existing **development** partition only.
3. Preserve action budget, wall limit, seed, package identity, game version, and environment mode.
4. Capture complete terminal outcomes and concise execution traces.
5. Compare reproduction to Build 000 timing/action shape, not merely completion count.
6. If exact reproduction is impossible due to upstream/environment drift, preserve that as `FAILED_INFRASTRUCTURE` or compatibility drift and construct the closest identity-preserving reproduction without rewriting historical evidence.

## Acceptance

Either:

- the timeout/zero-completion pathology reproduces; or
- a precise environmental/source reason explains why it no longer reproduces.

No optimization changes are allowed before this checkpoint.

## Commit

`bench(build-001): reproduce frozen local-public failure`

---

# STAGE 02 — Hot-path observability

## Objective

Make every expensive decision phase measurable without materially changing policy.

## Instrument these phases separately

- SDK/frame normalization;
- frame hashing/delta extraction;
- connected components/correspondence;
- trace append/blob work;
- hypothesis generation/ranking;
- retrodiction/model fitting;
- goal inference;
- candidate probe generation;
- internal simulation/search;
- action selection;
- checkpoint/memory persistence;
- rendering/log/report overhead;
- environment `step()` latency itself.

## Requirements

- monotonic high-resolution timers;
- per-action and per-episode aggregate timings;
- CPU time vs wall time where available;
- peak/periodic RSS;
- counts of hypotheses/models/simulations/candidate plans;
- cache hit/miss counters;
- explicit timeout origin;
- instrumentation can be disabled and its overhead measured.

Do not record hidden chain-of-thought. Record typed phase/decision summaries only.

## Acceptance

A failed development episode must produce a machine-readable profile explaining where wall time went to a useful accounting tolerance. Instrumentation overhead must be measured and bounded.

## Commit

`feat(build-001): instrument controller hot path and timeout provenance`

---

# STAGE 03 — Throughput diagnosis

## Objective

Turn profiling into causal evidence rather than immediately optimizing whichever function looks expensive.

## Tasks

1. Rank phases by wall-time contribution and multiplicity.
2. Create isolated microbenchmarks using captured development observations where allowed.
3. Test bounded interventions one at a time, such as:
   - disable rendering/report generation;
   - defer durable checkpoint flushes while preserving crash safety guarantees;
   - cache unchanged perception structure;
   - incrementalize frame differences;
   - cap redundant hypothesis regeneration;
   - cap retrodiction candidate expansion;
   - cap simulation/search branching;
   - separate one-time level initialization from per-action work.
4. Measure action-throughput gain and any change in policy output.
5. Identify at least the top two causal bottlenecks or explicitly show no dominant bottleneck exists.

## Guardrail

Do not accept an optimization that silently drops provenance, uncertainty, contradiction receipts, or action validity. Derived computation may be deferred/cached; raw action/consequence receipts may not be omitted.

## Acceptance

Produce `docs/reports/103-throughput-diagnosis.md` and structured evidence with before/after phase costs and a prioritized causal repair list.

## Commit

`bench(build-001): isolate local-public throughput bottlenecks`

---

# STAGE 04 — Palette equivariance

## Objective

Repair the contradiction between lower-level palette-invariant perception tests and controller-level failure under palette permutation.

## Tasks

1. Trace every path where raw color IDs affect semantics, hypothesis ranking, goal inference, memory reuse, or action choice.
2. Build an episode-local canonical palette representation based on structural/behavioral roles, while preserving original raw values in observation receipts.
3. Do not presume a fixed background/player/goal color.
4. Maintain ambiguity when multiple role mappings remain compatible.
5. Add metamorphic paired tests: original episode and one or more bijective palette permutations must induce equivalent structural state and action decisions modulo representation.
6. Include permutations not seen while implementing the mechanism.
7. Verify persistent memory does not carry raw palette identity as generic knowledge across unrelated games.

## Acceptance

- Build 000's four palette-related failures become explainable;
- predeclared new palette metamorphic cases pass at the controller level or remain bounded failed evidence;
- raw receipts remain lossless;
- no public game IDs or color-specific solution tables exist.

## Commit

`fix(build-001): make controller semantics palette equivariant`

---

# STAGE 05 — Action equivariance

## Objective

Treat action labels as arbitrary interface symbols until their effects are earned from interaction.

## Tasks

1. Audit for assumptions that ACTION1..ACTION7 have fixed directional/semantic meaning beyond official schema guarantees.
2. Separate raw SDK action identity from learned episode-local action effect.
3. Infer action-effect hypotheses from observed deltas with explicit uncertainty and reversibility.
4. Canonicalize learned action roles where possible without erasing raw action receipts.
5. Build synthetic and official-shaped action-remap metamorphic tests.
6. Ensure coordinate action semantics are inferred/validated at the correct layer and malformed coordinates remain rejected.
7. Ensure memory transfer carries generic effect concepts, not raw action numbers.

## Acceptance

Previously failing action-remapped cases are repaired or precisely diagnosed. New hidden-from-implementation permutations must be equivalent under the learned role mapping within predeclared probe budgets.

## Commit

`fix(build-001): infer action semantics under arbitrary remapping`

---

# STAGE 06 — Guaranteed rule-change reopening

## Objective

Actually exercise the reopening mechanism instead of allowing an intervention episode to terminate before the intervention.

## Tasks

1. Create at least two deterministic procedural cases where:
   - a rule is learnable before intervention;
   - the agent must encounter the intervention before termination;
   - the old rule becomes measurably wrong;
   - success requires reopening/relearning rather than continuing stale behavior.
2. Add one action-remap intervention and one transition/goal-rule intervention where practical.
3. Preserve pre-change evidence; mark the old rule scoped/superseded rather than retroactively false from inception.
4. Measure detection delay, wasted actions after contradiction, reopening latency, and recovery completion.
5. Compare against a no-reopening/sticky-model ablation.

## Acceptance

Both guaranteed-exposure cases reach intervention. FULL must either demonstrate bounded reopening advantage or the mechanism is recorded `FAILED_MECHANISM` without reinterpretation.

## Commit

`test(build-001): guarantee and measure post-change reopening`

---

# STAGE 07 — Retrodiction decision

## Objective

Resolve Build 000's conflicting evidence about retrodiction enough to choose an efficient Build 001 hot-path policy.

## Variants

Predeclare and compare at least:

- `R0`: retrodiction disabled;
- `R1`: current Build 000 gate;
- `R2`: cheap incremental retrodiction limited to changed/contested rules;
- optional `R3`: deferred retrodiction invoked only on contradiction, low confidence, or before a high-cost plan.

## Metrics

- completions;
- environment actions;
- wall time;
- model violations caught before action;
- stale/wrong rules prevented;
- contradiction recovery;
- action-efficiency proxy (never label local proxy RHAE unless official scorer returns it).

Use paired seeds/episodes and report uncertainty where sample size permits.

## Decision rule

Keep full retrodiction in the hot path only if it earns a reproducible benefit commensurate with cost. Otherwise narrow or defer it. Do not protect the mechanism because it matches the original architectural intuition.

## Acceptance

One variant is selected for the Build 001 milestone from explicit evidence, with rejected alternatives and residual uncertainty preserved.

## Commit

`bench(build-001): resolve retrodiction hot-path policy`

---

# STAGE 08 — Two-speed controller

## Objective

Separate cheap reactive bookkeeping from expensive deliberation so environment interaction remains informed without timing out.

## Architecture

### Fast path — every environment action

Must remain bounded and cheap:

1. normalize observation;
2. compute incremental delta;
3. append raw receipt;
4. update direct action-effect evidence;
5. detect contradictions/salient novelty;
6. execute already-supported plan step when still valid;
7. otherwise request deliberation.

### Deliberative path — triggered, not unconditional

May perform:

- broader hypothesis generation;
- model fitting/retrodiction under Stage 07 policy;
- goal re-evaluation;
- multi-step internal simulation/search;
- memory retrieval/generalization;
- plan construction.

## Required budgets

Explicit configuration for:

- maximum per-action wall time;
- maximum deliberation wall time;
- maximum model candidates;
- maximum simulation nodes/depth;
- maximum memory retrieval volume;
- maximum trace/checkpoint flush latency;
- environment action budget.

A timeout must degrade gracefully to a valid bounded probe/action, not freeze the episode indefinitely.

## Acceptance

On frozen development episodes, median and tail action throughput improve materially over Stage 01 while preserving trace integrity and action validity. Any policy-quality regression must be measured.

## Commit

`feat(build-001): add budgeted two-speed ARC3 controller`

---

# STAGE 09 — Local-public development recovery

## Objective

Demonstrate that the repaired controller can actually finish development levels rather than merely benchmark faster.

## Protocol

1. Freeze implementation and config before this stage's primary measurement.
2. Use only the existing declared `local-public` development partition; do not open the holdout.
3. Run enough seeds/repetitions to distinguish an anecdotal completion from a reliable nonzero result within available compute.
4. Compare against:
   - frozen Build 000 FULL;
   - B0 random;
   - deterministic cycle;
   - strongest appropriate Build 001 ablation.
5. Capture completion, environment actions, wall time, timeout count, failures, and local scorecard fields separately.
6. Do not call any local action-efficiency proxy official RHAE.

## Minimum recovery target

Before Stage 11 may consider opening the holdout, the frozen Build 001 controller must satisfy **all** of:

- nonzero completed development levels;
- no universal timeout pathology;
- at least two distinct development games/versions completed if the declared development surface contains enough solvable instances;
- improvement over frozen Build 000 FULL on completion and timeout rate;
- no evidence of game-ID-specific policy behavior;
- trace/replay validation passes for measured runs.

This is a minimum gate, not a success claim. Stronger evidence is preferred.

## Commit

`bench(build-001): demonstrate local-public development recovery`

---

# STAGE 10 — Robustness and regression

## Objective

Verify the repair did not simply trade away Build 000's synthetic strengths.

## Required suites

1. exact/compatible Build 000 synthetic benchmark reproduction;
2. fresh procedural seeds not used during implementation;
3. palette metamorphic suite;
4. action-remap metamorphic suite;
5. guaranteed rule-change suite;
6. interruption/replay/tamper tests;
7. resource/wall-time/RSS checks;
8. production game-ID/static leakage scan;
9. deterministic repeatability under seed;
10. key ablations for world-model simulation, goal inference, and chosen retrodiction policy.

## Acceptance

Publish a regression matrix. Any lost Build 000 capability remains visible. A repair that only improves public development while collapsing broad synthetic generality is not an overall PASS.

## Commit

`test(build-001): seal robustness regression and mechanism matrix`

---

# STAGE 11 — Frozen milestone and holdout-opening gate

## Objective

Decide mechanically whether the ten-game public holdout has been earned.

Before evaluating the gate:

1. freeze source commit and config;
2. seal all development evidence and hashes;
3. run full tests/lint/type/integrity/secret scans;
4. verify holdout game episodes/recordings have not been opened or consumed;
5. document all implementation decisions made using development results.

### OPEN_HOLDOUT only if all are true

- Stage 09 minimum recovery target passes;
- Stage 10 has no unresolved integrity/leakage failure;
- controller source/config is frozen before seeing holdout results;
- no planned post-hoc tuning on holdout identities/results;
- the evaluation can run without external hosted models or internet-dependent policy calls.

Otherwise emit `HOLDOUT_NOT_EARNED`, preserve the holdout, skip Stage 12 evaluation, and continue packaging/reporting.

Opening the public holdout under this predeclared gate is routine benchmark evaluation, not an official Kaggle submission and not a human legal gate, provided existing repository rules already designate it as locally available public data. If access would require accepting new terms, credentials not already available, or another human-gated act, stop at that boundary and mark `BLOCKED_EXTERNAL` instead.

## Commit

`chore(build-001): freeze milestone and evaluate holdout gate`

---

# STAGE 12 — One-shot public holdout evaluation, only if earned

## Objective

Obtain one clean generalization measurement without turning the holdout into another development set.

## Protocol

- exact frozen Stage 11 commit/config;
- exactly one primary pass over the ten-game holdout;
- no source/code/config modification after observing partial results;
- record per-game completion, actions, wall time, failure mode, and available scorecard fields;
- preserve complete receipts and environment/package identity;
- compare against pinned baselines if the protocol allows them without consuming a different interpretation of the holdout;
- do not fit/tune based on results in Build 001.

After evaluation, the holdout becomes consumed and must be labeled as such forever. Future development must use new partitions or a new externally defined evaluation surface.

If Stage 11 did not earn this stage, write a short evidence artifact saying it was intentionally skipped and why.

## Commit

`bench(build-001): record sealed public holdout result`

---

# STAGE 13 — Offline package and clean-clone verification

## Objective

Produce a deterministic candidate that reflects the actual Build 001 policy.

## Tasks

1. Rebuild offline package from clean checkout using pinned dependencies.
2. Verify no internet/hosted-model requirement in competition mode.
3. Run Linux and Windows CI where available.
4. Run full pytest, replay/tamper/property suites, Ruff, formatting, strict mypy, doctor, dependency/license inventory, secret scan, large-file scan, game-ID scan, and git integrity.
5. Build package twice in independent clean workspaces and compare permitted nondeterminism/byte identity as appropriate.
6. Record package size and SHA-256.
7. Perform no official submission.

## Acceptance

Package and source identities are reproducible and all failures are explicitly bounded.

## Commit

`build(build-001): seal deterministic offline candidate`

---

# STAGE 14 — Research report, owner handoff, and draft PR

## Required artifacts

- `docs/research/ARC3-Build-001-report.md`
- `docs/handoffs/001-local-public-recovery.md`
- final structured acceptance evidence under `docs/evidence/`
- updated Build 001 decisions/open burdens/run state
- draft PR from `build/001-local-public-recovery` to `main`

## Report structure

1. exact source/environment identity;
2. Build 000 frozen starting evidence;
3. failure reproduction;
4. throughput diagnosis;
5. palette/action equivariance results;
6. rule-change reopening result;
7. retrodiction decision and evidence;
8. two-speed runtime evidence;
9. local-public development result;
10. robustness/regression matrix;
11. holdout gate decision and result if opened;
12. packaging/reproducibility;
13. limitations and unresolved burdens;
14. prioritized Build 002 candidates;
15. exact owner-only next actions.

## Claim boundary

Do not claim:

- PAL validation;
- AGI/general intelligence;
- hidden/private generalization;
- official RHAE unless actually returned by an official evaluator;
- competition success before official submission;
- causation beyond controlled paired evidence.

Christopher D. Pang remains author and steward. AI systems are development tools and assistants.

## Final status

Use one of:

- `BUILD 001: PASS` — only if all Build 001 acceptance surfaces pass, including the holdout gate/evaluation if it was earned and required for the stated claim;
- `BUILD 001: PARTIAL` — useful repairs/results with open burdens;
- bounded failure state where appropriate.

A `HOLDOUT_NOT_EARNED` outcome may still coexist with a useful `PARTIAL`; it must never be disguised as successful generalization.

The PR must remain draft and unmerged unless Christopher later instructs otherwise.

## Commit

`docs(build-001): finalize local-public recovery evidence and handoff`

---

## 7. Build 002 seeds — do not automatically execute

Build 001 may recommend, but must not automatically start, a Build 002. Candidate directions include:

- representation learning over structural roles if symbolic equivariance saturates;
- learned generic priors trained only on permitted procedural environments;
- more efficient model search/MDL scoring;
- calibrated uncertainty for hypothesis/goal selection;
- improved long-horizon planning;
- exact Kaggle-platform rehearsal after owner gates;
- official competition submission after explicit owner approval.

Stop after the Build 001 draft PR and handoff.
