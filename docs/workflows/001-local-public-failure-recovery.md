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
- Build 000 PR #3 was deliberately merged by repository owner Christopher D. Pang after the autonomous run stopped at its human merge gate; this was an owner action, not an autonomous Codex action. The exact provenance receipt is `docs/handoffs/000-owner-merge-provenance.md`.
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
2. Verify `docs/handoffs/000-owner-merge-provenance.md` and record that PR #3 was merged by Christopher D. Pang after Build 000 stopped at the merge gate; do not classify the merge as autonomous.
3. Verify Build 000 handoff/evidence hashes that Build 001 relies upon.
4. Create `build/001-local-public-recovery` from current `main` and switch to it.
5. Record host OS, CPU, RAM, GPU, Python/uv/git identities, network state, and wall-clock source.
6. Re-check mutable ARC-AGI-3 docs/toolkit identities and record any drift without silently upgrading.
7. Initialize fresh Build 001 ledger files.
8. Process MIT-0 only if the active owner instruction explicitly approves it as described in §3.
9. Verify the public holdout manifest remains sealed/unconsumed and record its identity without opening game episodes.
10. Run secret scan and git integrity check.

## Acceptance

- branch exists and is based on exact current `main`;
- owner merge provenance is explicitly recorded and consistent with GitHub history;
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

- the original failure is reproduced or an explicit compatibility/drift blocker is recorded;
- no holdout game is touched;
- no repair has yet changed production policy.

## Commit

`test(build-001): reproduce Build 000 local-public failure`

---

# STAGE 02 — Hot-path observability

## Objective

Measure where FULL spends time before optimizing anything.

## Tasks

1. Add phase-level timing around observation normalization, perception, correspondence, hypothesis update, retrodiction, goal inference, planning, trace/serialization, rendering/debug work, environment step, and checkpointing.
2. Record CPU time, wall time, RSS/peak RSS, action count, phase call counts, and cache hits/misses.
3. Ensure instrumentation can be disabled and has bounded overhead; measure that overhead on synthetic fixed episodes.
4. Separate one-time startup cost from per-action steady-state cost.
5. Identify repeated computations on unchanged or locally changed frames.
6. Emit per-run JSON/Parquet summaries without logging hidden chain-of-thought.
7. Add regression tests for instrumentation identity and disabled-mode equivalence.

## Acceptance

- >90% of measured controller wall time is attributable to named phases or explicitly labeled scheduler/OS remainder;
- instrumentation overhead is measured;
- same seeded policy decisions occur with instrumentation enabled/disabled when timing itself is not used as an input;
- no semantic behavior is changed solely to improve profiling.

## Commit

`perf(build-001): instrument ARC3 controller hot path`

---

# STAGE 03 — Causal throughput diagnosis

## Objective

Convert timing observations into bounded causal evidence rather than guessing.

## Tasks

1. Rank top wall-time consumers from Stage 02.
2. For each major consumer, run isolated microbenchmarks and one-at-a-time bypass/cache experiments on synthetic and development frames.
3. Measure marginal wall-time savings and behavioral/action differences.
4. Test likely Build 000 failure modes including:
   - combinatorial hypothesis growth;
   - repeated retrodiction over full history;
   - planning expansion explosion;
   - expensive component correspondence;
   - synchronous trace/blob writes;
   - checkpoint frequency;
   - repeated frame transformations;
   - Python object/validation overhead.
5. Do not permanently disable a mechanism merely because it is expensive; first distinguish implementation cost from functional value.
6. Write a causal bottleneck map with supported, contradicted, and unresolved candidates.

## Acceptance

- at least the top two material throughput causes have intervention evidence;
- proposed repairs have pre-change baseline numbers;
- remaining uncertainty is explicit.

## Commit

`bench(build-001): isolate causal local-public throughput bottlenecks`

---

# STAGE 04 — Palette equivariance

## Objective

Repair the failure where palette permutations destroy structurally identical tasks.

## Tasks

1. Diagnose where absolute color identity leaks into interpretation, hypothesis ranking, world-model rules, goals, or planning.
2. Introduce a generic structural color-role representation only where earned by relations/history, e.g. stable background candidate, controllable-component role, changed-object role, target-like relation; do not hard-code game-specific semantic colors.
3. Preserve raw colors in observation receipts while allowing derived canonical role IDs.
4. Make correspondence/hypothesis rules equivariant under bijective palette permutation where the environment dynamics are otherwise identical.
5. Generate large paired metamorphic suites with random palette bijections and seeds.
6. Require action-level equivalence under inverse mapping where applicable.
7. Keep cases where color itself is causally meaningful representable; equivariance must be conditional on observed rule structure, not an unconditional erasure of color.

## Acceptance

- the four Build 000 palette failures are repaired generically or narrowed with evidence;
- paired procedural palette permutations meet a predeclared high equivalence rate;
- tasks where color changes mechanics remain distinguishable;
- raw provenance remains intact.

## Commit

`fix(build-001): make structural inference palette-equivariant`

---

# STAGE 05 — Action equivariance

## Objective

Repair action-remapping failures without assuming cardinal meaning from action IDs.

## Tasks

1. Locate assumptions such as `ACTION1 == up` or fixed ordinal semantics in production and derived state.
2. Treat advertised action IDs as opaque handles until transition evidence earns an effect model.
3. Learn action signatures from observed object/frame transformations and retain alternatives under ambiguity.
4. Canonicalize learned effects separately from raw action IDs, e.g. translation vector, transform type, coordinate interaction, reset/undo evidence.
5. Ensure planner operates primarily over learned effects and resolves effects back to currently valid action handles.
6. Add random action-ID permutation suites, including partial action subsets and coordinate action behavior.
7. Preserve the special API constraints actually guaranteed by upstream (e.g. reset-only after game over) as interface facts, not learned gameplay rules.

## Acceptance

- Build 000 action-remap failures are repaired or explicitly narrowed;
- paired action permutation tests preserve behavior under inverse mapping at a predeclared high rate;
- production scan finds no unjustified cardinal action semantics.

## Commit

`fix(build-001): learn action semantics independently of action identifiers`

---

# STAGE 06 — Guaranteed rule-change reopening

## Objective

Actually exercise the rule-change behavior that Build 000 failed to reach.

## Tasks

1. Create at least two procedural tasks where a competent pre-change policy is guaranteed to encounter a mechanics change before terminal state.
2. Predeclare intervention time/trigger and expected observable contradiction.
3. Require:
   - pre-change rule becomes supported;
   - change creates a traceable contradiction;
   - dependent model/plan is invalidated;
   - prior history remains immutable;
   - candidate rule reopens or is superseded;
   - controller re-explores and completes or demonstrably adapts within a bounded post-change budget.
4. Add negative control with noise that should **not** cause unnecessary reopening.
5. Repeat over multiple seeds and palette/action permutations.

## Acceptance

Both intervention families are exercised on every required seed; receipt chains demonstrate the reopening event; false-positive reopening remains bounded.

## Commit

`test(build-001): verify rule-change contradiction and reopening`

---

# STAGE 07 — Retrodiction decision

## Objective

Resolve the Build 000 conflict instead of protecting retrodiction by design preference.

## Variants

At minimum compare:

- current/full retrodiction;
- no retrodiction;
- bounded recent-window retrodiction;
- event-triggered retrodiction only after contradiction/model change;
- cached incremental retrodiction if technically justified.

## Measurements

- completion;
- environment actions;
- wall time;
- CPU/RSS;
- accepted false rules;
- contradiction recovery;
- planning failures;
- synthetic plus permitted development tasks.

Use paired seeds/environments and identical action/wall budgets.

## Decision rule

Retrodiction remains in the hot path only if measured benefit justifies its cost on the predeclared metrics. Otherwise narrow, defer, or remove it. Preserve its full implementation if useful for offline audit/replay.

Do not call a small sample “proof.”

## Commit

`bench(build-001): resolve retrodiction hot-path tradeoff`

---

# STAGE 08 — Two-speed controller

## Objective

Make internal computation cheap enough to interact while retaining deep reasoning when evidence warrants it.

## Design target

### Fast path

Every action may use bounded:

- frame delta/correspondence;
- incremental action-effect update;
- local hypothesis updates;
- cached goal/progress checks;
- known-plan continuation;
- cheap contradiction detectors.

### Deliberative path

Invoke only on explicit triggers such as:

- startup/unknown action semantics;
- no viable plan;
- meaningful contradiction;
- goal uncertainty above threshold;
- structural novelty;
- repeated no-progress receipt;
- rule-change reopening.

The deliberative path may perform deeper world-model search, multi-hypothesis retrodiction, exploratory probe selection, and bounded planning.

## Tasks

1. Implement trigger contract and explicit compute budgets.
2. Add incremental caches keyed to immutable evidence/config identities.
3. Invalidate caches on relevant reopening events.
4. Never let timeout itself silently select an action; use explicit safe fallback policy.
5. Add deterministic replay tests across fast/deep transitions.
6. Profile action throughput and peak RSS.

## Acceptance

- material median per-action wall reduction from frozen Build 000 on the reproduction subset;
- synthetic mechanism performance remains within the regression floor defined in Stage 10;
- all deep-path invocations have typed triggers/receipts.

## Commit

`perf(build-001): add bounded fast and deliberative controller paths`

---

# STAGE 09 — Local-public development recovery

## Objective

Test whether Build 001 has crossed from “mechanism works synthetically” to “generic controller can actually interact effectively with official development games.”

## Freeze before running

Before this stage's decisive evaluation:

1. freeze production source commit;
2. freeze development partition already established by Build 000;
3. freeze seeds, action budget, per-run wall limit, overall wall limit, and hardware identity;
4. define PASS before looking at results.

Recommended minimum gate for this build:

- FULL completes at least **2 distinct development games/levels** that Build 000 FULL did not complete;
- at least **50% of scheduled FULL development runs terminate normally** rather than controller wall timeout;
- FULL beats B0 random on either completion count with no higher action budget, or completion-normalized action efficiency;
- no game-ID-specific code or source-reading shortcut;
- all evidence artifacts verify.

If the existing development partition is too small for these exact thresholds, Codex may predeclare a statistically/operationally equivalent criterion **before** running the decisive suite and record why.

## Baselines

Run frozen Build 000 FULL, B0 random, deterministic cycle, and Build 001 FULL under matched envelopes when feasible.

## Acceptance

Report PASS/PARTIAL/FAILED_MECHANISM exactly. Do not open holdout merely because the result “looks promising.”

## Commit

`bench(build-001): measure local-public recovery against frozen baselines`

---

# STAGE 10 — Robustness and regression

## Objective

Ensure the repair did not buy public interaction by destroying the synthetic mechanisms that motivated the architecture.

## Required suites

1. exact or identity-preserving Stage 13 Build 000 synthetic benchmark;
2. Stage 14 component ablations where still architecturally applicable;
3. palette permutation suite;
4. action remapping suite;
5. guaranteed rule-change suite;
6. trace replay/tamper tests;
7. checkpoint/resume;
8. deterministic seed repeatability;
9. resource profile;
10. static competition-integrity scan.

## Regression floor

Predeclare tolerances before running. At minimum, Build 001 should not lose the qualitative Stage 14 finding that world-model simulation and goal inference materially outperform their removal on the corresponding frozen synthetic benchmark, unless Build 001 produces direct evidence that the old benchmark was confounded. Any such reclassification must preserve the original result and create a new artifact; never rewrite Build 000.

## Acceptance

- no silent synthetic collapse;
- palette/action cases meet new targets;
- rule-change is exercised;
- evidence integrity passes;
- resource usage is compatible with the current intended competition envelope or is explicitly blocked.

## Commit

`test(build-001): seal robustness and regression milestone`

---

# STAGE 11 — Frozen milestone and holdout-opening gate

## Objective

Make the holdout decision mechanically from evidence already produced.

Before checking any holdout episode, create a signed/hash-bound local receipt containing:

- frozen source commit;
- config hash;
- dependency lock hash;
- development evidence artifact hashes;
- Stage 09 status;
- Stage 10 status;
- exact holdout-opening rule;
- holdout manifest hash;
- timestamp.

### Default holdout-opening rule

Open the ten-game public holdout only if:

1. Stage 09 = `PASS`;
2. Stage 10 = `PASS`;
3. no unresolved competition-integrity failure exists;
4. production source has not changed since decisive development evaluation;
5. holdout identity matches the sealed Build 000 manifest.

If any item fails, record `HOLDOUT_NOT_EARNED`, do not run it, and continue to packaging/reporting.

No human override during the autonomous run should weaken this gate merely to obtain a score. A later owner-directed exploratory run must be labeled separately from the sealed protocol.

## Commit

`chore(build-001): freeze milestone and evaluate holdout gate`

---

# STAGE 12 — One-shot public holdout evaluation, only if earned

## Objective

Measure generalization once without tuning on the result.

If Stage 11 did not earn the gate, write the non-consumption receipt and skip all game interaction in this stage.

If earned:

1. run exactly one predeclared FULL evaluation on all ten holdout games with fixed seeds/budgets;
2. do not inspect game source;
3. preserve raw terminal artifacts and scorecards if returned;
4. run frozen baselines only if the sealed protocol predeclared them and their actions do not contaminate the FULL run;
5. report completion/action/runtime metrics with exact labels;
6. do **not** modify production policy in response to holdout outcomes within Build 001.

After the run, holdout observations may be analyzed diagnostically for a future Build 002, but Build 001's policy stays frozen.

Official RHAE may be claimed only if an official scorecard actually reports it.

## Commit

`bench(build-001): record sealed public holdout result`

or, when not earned:

`docs(build-001): record sealed holdout non-consumption`

---

# STAGE 13 — Offline package and clean-clone verification

## Objectives

Produce a deterministic, competition-compatible package candidate from the frozen Build 001 source.

## Tasks

1. Reuse Build 000 package machinery rather than gratuitously rewriting it.
2. Refresh only first-party source and required locked dependencies.
3. Build twice and compare byte identities where deterministic packaging supports it.
4. Verify offline import and local gateway-shaped execution.
5. Run secret/integrity/license inventory scans.
6. Run a fresh clean-clone setup/test/package cycle on Windows and, through CI, Linux.
7. Measure wall time, peak RSS, archive size, wheel count, and startup behavior.
8. If exact private Kaggle wheels/gateway remain unavailable, preserve that as `BLOCKED_EXTERNAL`, not PASS.
9. Do not upload or submit.

## Acceptance

- deterministic package candidate;
- exact source/lock identity receipt;
- full test/lint/type suite passes or bounded failures are reported;
- offline execution works on available surfaces;
- no secrets;
- no official submission.

## Commit

`build(001): seal offline ARC3 package candidate`

---

# STAGE 14 — Research report, handoff, and draft PR

## Required artifacts

- `docs/research/ARC3-Build-001-report.md`
- `docs/handoffs/001-local-public-recovery.md`
- final Build 001 evidence manifest
- final run-state / decision / burden ledgers
- benchmark/ablation tables generated from machine-readable artifacts
- deterministic package receipt
- updated draft PR body

## Report structure

1. source and machine identity;
2. Build 000 inherited evidence;
3. reproduction diagnosis;
4. throughput causal map;
5. palette/action equivariance results;
6. rule-change reopening result;
7. retrodiction decision;
8. two-speed controller architecture;
9. development evaluation;
10. regression suite;
11. holdout gate decision;
12. holdout result only if earned;
13. package/reproducibility;
14. exact failures/open burdens;
15. smallest owner-only next actions.

### Claim discipline

Allowed claims must be bounded by measured labels. Examples:

- `LOCAL_PUBLIC_RECOVERY_OBSERVED`
- `THROUGHPUT_BOTTLENECK_IDENTIFIED`
- `PALETTE_EQUIVARIANCE_OBSERVED`
- `ACTION_EQUIVARIANCE_OBSERVED`
- `RULE_CHANGE_REOPENING_OBSERVED`
- `HOLDOUT_GATE_EARNED`
- `HOLDOUT_NOT_EARNED`
- `PUBLIC_HOLDOUT_RESULT_OBSERVED`

Do not claim AGI, consciousness, hidden-game generalization, PAL validation, or official competition performance.

## Final verification

Run the strongest available equivalent of:

```bash
uv sync --frozen --all-extras --dev --python 3.12 --link-mode copy
uv lock --check --offline
uv run ruff check --no-cache .
uv run ruff format --check --no-cache .
uv run mypy --strict src agent scripts
uv run pytest -q
uv run pytest -q --no-cov tests/replay tests/property/test_trace_properties.py
uv run arc3 doctor --json
```

Then:

- validate every final evidence hash/path/object;
- run git integrity and secret scans;
- verify source identity has not changed since the frozen decisive evaluation/package source unless the final changes are documentation/evidence only and explicitly recorded;
- push final branch;
- open/update a **draft**, unmerged PR;
- report final commit SHA, PR URL, CI state, package hash, and exact build status.

## Final status

One of:

- `BUILD 001: PASS`
- `BUILD 001: PARTIAL`
- `BUILD 001: FAILED_MECHANISM`
- `BUILD 001: BLOCKED_EXTERNAL`

Do not stop merely because one experiment fails; finish all independent work and leave the repository resumable.
