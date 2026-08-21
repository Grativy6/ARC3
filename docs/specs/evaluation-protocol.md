# ARC3 evaluation protocol

Status: **controlling measurement protocol for Build 000**  
Version: **0.1**  
Owner: **Christopher D. Pang**

## 1. Purpose

This protocol prevents impressive-looking anecdotes from replacing reproducible measurement. It governs baselines, public-game development, ablations, offline packaging tests, and any later Kaggle results.

ARC-AGI-3 measures both completion and action efficiency. The official per-level Relative Human Action Efficiency score is:

```text
level_score = (human_baseline_actions / agent_actions)²
```

The official system caps a level at 1.15, weights later levels more heavily within a game, and averages game scores for the total score. Internal reasoning does not count as an environment action, but environment commands do.

The repository must use the official pinned scorer whenever available. Any local approximation must be labeled `approximate` and never substituted for an official scorecard.

## 2. Result labels

Every reported result must carry exactly one primary surface label:

| Label | Meaning |
|---|---|
| `synthetic` | Project-authored deterministic/mock environment |
| `local-public` | Official public game executed locally |
| `online-public` | Official public game via ARC API/scorecard |
| `Kaggle-public` | Public leaderboard result returned by Kaggle |
| `semi-private` | Result returned by an authorized semi-private evaluator |
| `official-private` | Final/private competition result returned by the designated evaluator |

Also record:

- `verified: true/false`;
- scorer source/version;
- whether human baselines were available;
- whether the run used public-game-derived memory or tuning;
- whether the result is a single run or an aggregate.

## 3. Reproducibility envelope

Every evaluation artifact must include:

```json
{
  "evaluation_id": "...",
  "surface": "local-public",
  "verified": false,
  "git_commit": "...",
  "dirty_worktree": false,
  "upstream_lock_hash": "sha256:...",
  "python_version": "3.12.x",
  "platform": "...",
  "hardware": {
    "cpu": "...",
    "gpu": "...",
    "ram_gb": 0
  },
  "agent_config": {},
  "config_hash": "sha256:...",
  "games": [],
  "seeds": [],
  "action_budget": 0,
  "wall_clock_budget_seconds": 0,
  "network_mode": "offline",
  "started_at": "...",
  "completed_at": "...",
  "artifact_hashes": {}
}
```

If any field cannot be known, set it to null and explain why. Do not omit it silently.

## 4. Benchmark partitions

Public games are both development material and a leakage risk. Create a versioned partition manifest after discovering the currently available public set.

Recommended initial split:

- **smoke** — 2–3 games used for fast integration and CI;
- **development** — games used for iterative debugging and instrumentation;
- **public holdout** — games not manually inspected and not used for hand-tuning until a declared evaluation milestone;
- **regression** — games/levels with fixed known failure traces used after they have already been opened;
- **all-public** — final public sweep, never treated as hidden generalization.

Partition by a deterministic hash of stable game name and a committed salt, not by choosing favorable games. Record game versions separately because versions may change.

Once a holdout result is opened, preserve that receipt and create a new milestone rather than pretending the game remains unseen.

## 5. Baselines

Pin and maintain these baseline policies:

### B0 — random valid

- uniform random among valid non-reset actions;
- coordinate action samples uniformly in range;
- deterministic under seed;
- mandatory reset handling.

### B1 — deterministic cycle

- cycles through available simple actions;
- deterministic coordinate grid sweep;
- suppresses actions unavailable in the current frame.

### B2 — novelty only

- selects the action predicted or historically observed to produce the most novel next frame/state;
- no explicit goal model or planner.

### B3 — trace + local action statistics

- records exact deltas and avoids repeated no-ops;
- no retrodiction gate or executable world model.

### B4 — full ARC3

- perception, typed hypotheses, retrodiction, world model, goal inference, planning, persistent memory, and reopening.

Never delete an older baseline after a better policy exists. Keep it runnable against the same harness.

## 6. Primary metrics

### Official-facing

- game/level completion;
- environment action count;
- official RHAE when scorer data is available;
- weighted game score;
- total score.

### Diagnostic

- time to first progress event;
- actions to first completed level;
- resets and game-over events;
- repeated no-op rate;
- invalid action rate;
- coordinate-action hit rate;
- unique state count;
- state revisitation rate;
- prediction accuracy by horizon;
- fraction of transitions explained by active world model;
- hypothesis creation/rejection/reopening counts;
- average hypotheses retained;
- retrodiction contradiction rate;
- planner success rate;
- replans caused by mismatch;
- trace bytes per action;
- peak RAM;
- decision latency percentiles;
- total wall clock.

### Generalization diagnostics

- performance by public partition;
- performance on unseen synthetic rule families;
- sensitivity to palette permutation;
- sensitivity to translation/rotation/reflection when semantics permit;
- sensitivity to irrelevant distractors;
- action-label remapping where the synthetic environment supports it;
- performance across seeds.

## 7. Action and compute budgets

Define budgets in configuration, not scattered constants.

Each run records:

- maximum actions per level/game;
- maximum resets;
- maximum decision latency;
- maximum wall-clock runtime;
- maximum RAM;
- maximum generated coordinate candidates;
- maximum search nodes/depth;
- maximum trace size.

Use the current official Kaggle constraints as the outer bound at execution time. Keep an internal safety margin. If official limits are unclear or changing, record the source and choose a conservative local budget rather than asserting a stale number.

## 8. Seed policy

- Every stochastic component receives a root seed.
- Derive component seeds deterministically from root seed + component name.
- Store Python, NumPy, ML-framework, and environment seeds when applicable.
- Run a minimum multi-seed set for architecture claims; five fixed seeds is a reasonable first target when runtime permits.
- Do not choose the best seed as the reported score. Report distribution and a predeclared aggregate.

## 9. Evaluation ladder

### E0 — static quality gate

Required:

- format/lint;
- strict type check;
- unit/property tests;
- secret scan;
- production-code game-ID scan;
- dependency license inventory.

### E1 — synthetic smoke

Required:

- deterministic toy environments;
- controller completes at least one simple unseen synthetic task;
- trace, checkpoint, and replay pass;
- injected failure recovery works.

### E2 — official SDK smoke

Required when network/upstream availability permits:

- list environments;
- instantiate at least one anonymous/public game;
- take validated actions;
- produce a scorecard/recording or bounded upstream blocker;
- no credential leakage.

### E3 — public development suite

- compare B0–B4 on the development partition;
- use identical budgets and seeds;
- report completions, actions, latency, and diagnostic metrics;
- retain raw traces locally and commit compact reports only.

### E4 — public holdout milestone

Before opening holdout:

1. commit code and configuration;
2. seal the development report;
3. declare no further pre-result edits;
4. run the committed holdout manifest once per predeclared seed;
5. publish all outcomes, including zero scores;
6. mark the holdout consumed for that milestone.

### E5 — all-public rehearsal

- clean clone;
- fully offline runtime after dependencies/games are packaged;
- current competition action and wall-clock limits;
- generated Kaggle notebook/package;
- same policy code as local harness;
- no manual per-game intervention.

### E6 — Kaggle packaging validation

- notebook builds;
- dependency bundle resolves with internet disabled;
- agent produces expected output artifact;
- no environment secret required at evaluation;
- actual upload/submission remains human-gated.

### E7 — external result

When an owner-authorized Kaggle/semi-private/private result exists:

- preserve returned score and source URL/ID;
- record submission commit and package hash;
- compare public/private agreement;
- do not infer causes without evidence;
- never rewrite the pre-submission report.

## 10. Ablation matrix

At minimum, evaluate the full system against:

| ID | Removed/changed component | Question |
|---|---|---|
| A1 | persistent game memory | Does cross-level trace help? |
| A2 | rejected-hypothesis retention | Does preserving failures reduce repeated mistakes? |
| A3 | retrodiction gate | Does history consistency improve action efficiency? |
| A4 | world-model simulation | Does internal planning save environment actions? |
| A5 | goal inference | Is progress coming only from novelty/exploration? |
| A6 | coordinate salience | Does structured `ACTION6` targeting beat uniform search? |
| A7 | planner recovery | Does mismatch-triggered replanning matter? |
| A8 | object tracking | Are temporal identities useful beyond raw deltas? |
| A9 | information-gain term | Does discriminating action choice beat heuristic order? |
| A10 | trace summaries | Do summaries help runtime without losing critical evidence? |

Only claim benefit when the comparison uses the same game set, seed set, action budget, and scorer.

## 11. Synthetic environment suite

Create procedural test families that expose the same kinds of burdens without copying public games:

1. unknown directional mapping;
2. controllable-object identification among distractors;
3. walls and conditional traversal;
4. toggle/door/key interactions;
5. coordinate selection of an unknown target;
6. color/shape matching;
7. cyclic mechanisms and timing;
8. reversible vs irreversible actions;
9. delayed reward/progress;
10. misleading novelty;
11. partial observability through frame subsets;
12. rule change between levels with a preserved invariant;
13. false initial hypothesis requiring reopening;
14. multiple compatible world models requiring a discriminating probe;
15. game-over/reset-only recovery.

Parameterize colors, positions, shapes, action mappings, and distractors. Hold out parameter combinations and entire rule families.

## 12. Leakage and overfitting controls

Production agent policy must not:

- branch on known public game IDs/versions;
- contain copied public action sequences;
- import game implementation source at runtime;
- use public-game-specific textual rules;
- read committed reports to identify the current game and retrieve a solution;
- preserve private/semi-private frames.

Implement CI checks that scan production policy paths for the committed public game IDs. Allow IDs only in partition manifests, tests, reports, and adapter invocations.

Manual inspection of public game traces is allowed for debugging but must be recorded in the development ledger. It removes any claim that the inspected game is unseen.

## 13. Statistical reporting

For multi-seed results report:

- all individual observations in machine-readable form;
- mean, median, minimum, maximum;
- standard deviation or robust spread;
- paired differences when runs share seeds/environments;
- confidence intervals only when assumptions/method are stated;
- zero/failure runs, never filtered out silently.

Do not overuse significance testing on tiny game counts. Prefer effect sizes, paired traces, and explicit uncertainty.

## 14. Performance regression policy

Create a committed benchmark threshold file only after a stable baseline exists.

A change fails regression if, under the pinned smoke suite, it materially worsens any of:

- completions;
- action count at equal completion;
- invalid action rate;
- deterministic replay;
- peak memory beyond budget;
- decision latency beyond budget;
- offline packaging.

Allow an intentional regression only with a decision record explaining the tradeoff and a new comparison.

## 15. Report structure

Each milestone report should contain:

1. claim/status summary;
2. exact code/config/upstream identities;
3. evaluation surface and partition;
4. methods and budgets;
5. raw result table;
6. baseline and ablation comparisons;
7. representative trace links/IDs;
8. failures and counterexamples;
9. limitations and consumed holdouts;
10. next residuals;
11. reproduction commands;
12. artifact hashes.

Preferred files:

```text
docs/reports/<milestone>.md
artifacts/evaluations/<evaluation_id>/manifest.json
artifacts/evaluations/<evaluation_id>/results.jsonl
artifacts/evaluations/<evaluation_id>/summary.json
artifacts/evaluations/<evaluation_id>/reproduce.txt
```

Large artifacts remain ignored unless intentionally curated.

## 16. Claim vocabulary

Use these bounded result labels:

- `MECHANISM_OBSERVED`
- `MECHANISM_NOT_OBSERVED`
- `LOCAL_PUBLIC_IMPROVEMENT`
- `PUBLIC_HOLDOUT_IMPROVEMENT`
- `NO_GENERALIZATION_CLAIM`
- `PACKAGING_PASS`
- `BLOCKED_EXTERNAL`
- `FAILED_MECHANISM`
- `FAILED_INFRASTRUCTURE`

Examples:

- A synthetic improvement does not justify `PUBLIC_HOLDOUT_IMPROVEMENT`.
- A public-game win does not justify an AGI claim.
- A successful notebook build does not mean an official submission passed.

## 17. Required final comparison

Before the autonomous run closes, produce one table containing at least:

```text
policy | surface | games | seeds | levels completed | actions | RHAE/approx | wall time | peak RAM | notes
```

Include B0, B1, strongest intermediate agent, and final ARC3 agent. If a row could not run, include it with the blocker rather than omitting it.

## 18. Acceptance condition

Evaluation infrastructure passes when a clean-clone runner can execute the declared smoke suite, generate a sealed reproducibility envelope, compare at least two policies under identical budgets, verify trace/replay integrity, and produce an honest report even when every official game score is zero.
