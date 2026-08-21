# ARC3 target architecture

Status: **controlling design target for Build 000**  
Version: **0.1**  
Owner: **Christopher D. Pang**

This document defines the intended architecture. Implementations may narrow or revise it when measurements justify a change, but every material deviation must be recorded in `docs/ledger/DECISIONS.md`.

## 1. Design objective

Build a self-contained agent for ARC-AGI-3 that can enter an unfamiliar turn-based grid environment, discover its action semantics and mechanics, infer candidate goals, plan, act efficiently, preserve the history of failed ideas, and reuse legitimate knowledge across levels without game-specific scripts.

The benchmark exposes grids up to 64×64 with cell values 0–15 and a standardized variable action set: directional/simple actions, a general interaction action, coordinate action, undo, and reset. The final runtime must not require internet access.

The architecture prioritizes:

1. action efficiency;
2. falsifiable world models;
3. persistent but bounded memory;
4. replayability and provenance;
5. general mechanisms over public-game patches;
6. graceful failure and reopening.

## 2. Top-level loop

```text
receive frame(s) + metadata
        │
        ▼
normalize and hash observation
        │
        ▼
extract deltas, objects, relations, and affordance candidates
        │
        ▼
append immutable observation receipt
        │
        ▼
update candidate action semantics and transition hypotheses
        │
        ▼
retrodict prior trace; reject or narrow inconsistent rules
        │
        ▼
update candidate goal states and progress signals
        │
        ├── uncertainty too high ──► choose low-cost discriminating probe
        │
        └── model sufficient ──────► simulate plans and choose efficient action
                                            │
                                            ▼
                                validate action against current action space
                                            │
                                            ▼
                                      submit one action
                                            │
                                            ▼
                              compare consequence to predictions
                                            │
                                            ▼
                         preserve receipt; confirm, narrow, or reopen
```

No environment action may bypass this loop except a mandatory `RESET` from a game-over state or an explicitly documented emergency fallback after an internal error.

## 3. Proposed repository layout

Codex may adapt names to upstream framework requirements while preserving these responsibilities.

```text
ARC3/
├── AGENTS.md
├── README.md
├── pyproject.toml
├── upstream.lock.json
├── THIRD_PARTY_NOTICES.md
├── src/arc3/
│   ├── __init__.py
│   ├── cli.py
│   ├── config.py
│   ├── types.py
│   ├── adapters/
│   │   ├── arc_agi.py
│   │   ├── competition.py
│   │   └── synthetic.py
│   ├── trace/
│   │   ├── events.py
│   │   ├── ledger.py
│   │   ├── hashes.py
│   │   ├── replay.py
│   │   └── checkpoint.py
│   ├── perception/
│   │   ├── frame.py
│   │   ├── delta.py
│   │   ├── components.py
│   │   ├── tracking.py
│   │   └── salience.py
│   ├── hypotheses/
│   │   ├── base.py
│   │   ├── actions.py
│   │   ├── transitions.py
│   │   ├── objects.py
│   │   ├── goals.py
│   │   ├── evidence.py
│   │   └── registry.py
│   ├── world/
│   │   ├── state.py
│   │   ├── rules.py
│   │   ├── model.py
│   │   ├── retrodiction.py
│   │   └── simulator.py
│   ├── exploration/
│   │   ├── candidates.py
│   │   ├── information_gain.py
│   │   ├── probes.py
│   │   └── novelty.py
│   ├── planning/
│   │   ├── goals.py
│   │   ├── search.py
│   │   ├── plans.py
│   │   └── recovery.py
│   ├── memory/
│   │   ├── episode.py
│   │   ├── game.py
│   │   ├── generic.py
│   │   └── retrieval.py
│   ├── policy/
│   │   ├── controller.py
│   │   ├── baselines.py
│   │   └── fallback.py
│   └── evaluation/
│       ├── runner.py
│       ├── metrics.py
│       ├── ablations.py
│       └── reports.py
├── agent/
│   └── my_agent.py
├── scripts/
├── tests/
│   ├── unit/
│   ├── property/
│   ├── integration/
│   ├── replay/
│   └── competition/
├── fixtures/
├── recordings/              # ignored raw local outputs unless curated
├── artifacts/               # ignored large outputs
├── docs/
│   ├── workflows/
│   ├── specs/
│   ├── ledger/
│   ├── reports/
│   ├── handoffs/
│   ├── research/
│   └── legal/
└── notebooks/
```

## 4. State scopes

Keep four state scopes separate.

### 4.1 Step state

Exists only while selecting one action:

- latest normalized frame;
- available actions;
- immediate deltas;
- current plan node;
- candidate actions and utility scores;
- concise selection rationale.

### 4.2 Episode/level state

Persists until level reset or terminal state:

- immutable action/observation trace;
- tracked object identities;
- action-effect signatures;
- active and rejected hypotheses;
- current world model ensemble;
- candidate goals;
- explored state graph;
- current plan and prediction errors.

### 4.3 Game state

Persists across levels of the same game during a run:

- stable action semantics;
- rules supported across levels;
- reusable object/relationship schemas;
- level progression structure;
- compressed summaries pointing back to raw trace events.

### 4.4 Generic state

May transfer across games only when it is game-independent:

- priors such as directional action mapping being plausible but defeasible;
- generic grid/object operations;
- exploration strategies;
- planner statistics;
- learned estimates of probe utility by abstract feature class.

Production code must not use game IDs to retrieve task-specific solutions.

## 5. Observation layer

### 5.1 Normalized frame

Represent each received frame with:

- exact integer grid;
- width and height;
- game state;
- score/progress metadata when provided;
- available action set;
- source frame index and timestamp;
- content hash;
- optional parent frame hash.

Do not infer meaning in the normalized observation object.

### 5.2 Delta extraction

For consecutive frames compute:

- changed-cell mask;
- added, removed, recolored, and translated components;
- bounding boxes and centroids;
- candidate object correspondences;
- global transformations;
- metadata changes;
- whether the action was an apparent no-op.

A delta is a measurement, not an explanation.

### 5.3 Object candidates

Use connected components and temporal correspondence to create object candidates. Identity must carry confidence and alternatives; visually similar regions are not automatically the same object.

Useful features:

- color histogram;
- shape mask and canonical transforms;
- size, centroid, bounding box;
- adjacency and containment;
- motion vector;
- persistence count;
- response correlation with actions;
- salience/proximity to changed regions.

## 6. Hypothesis system

A hypothesis is a typed, versioned claim with explicit evidence and falsification state.

Required fields:

- `hypothesis_id`;
- type;
- statement in machine-readable form;
- scope: step, level, game, or generic;
- created-from event IDs;
- predictions over possible actions;
- supporting receipts;
- contradicting receipts;
- confidence or weight;
- status: candidate, active, narrowed, rejected, unresolved, superseded;
- parent/superseding hypothesis IDs;
- last-tested step.

Primary hypothesis families:

1. action semantics;
2. controllable-object identity;
3. collision and traversability;
4. interaction/toggle rules;
5. coordinate-action target semantics;
6. state-transition rules;
7. progress and terminal conditions;
8. candidate goals;
9. level-to-level invariants.

Confidence may rank candidates but cannot erase counterevidence.

## 7. Retrodiction gate

Before promoting a candidate rule into the active world model:

1. run it against every compatible prior transition in scope;
2. measure explained transitions, unexplained transitions, false predictions, and ambiguity;
3. compare it with simpler and competing hypotheses;
4. reject, narrow, or retain uncertainty when contradictions remain;
5. store the retrodiction result as a receipt.

A later successful action may support a prior hypothesis but must not rewrite it as known before the action.

## 8. World model

The active world model should be an ensemble or weighted set of compatible rules rather than one brittle narrative.

Minimum capabilities:

- encode current symbolic state;
- predict frame/object/metadata consequences for candidate actions;
- return uncertainty and alternative outcomes;
- simulate short action sequences without touching the environment;
- identify states where models disagree;
- invalidate cached plans after a prediction error;
- preserve the rule lineage used by each plan.

Begin with interpretable rule forms:

- translations and rotations;
- contact/collision predicates;
- component creation/deletion/recoloring;
- selection and attachment state;
- counters and repeating cycles;
- local neighborhood transforms;
- coordinate target effects;
- conditional action availability.

Only introduce learned latent models after the symbolic system is measurable and the new model wins an ablation under the same action and compute budget.

## 9. Goal inference

Goals are hypotheses, not facts.

Candidate signals include:

- explicit score increase;
- transition to a new level or win state;
- stable environmental affordances such as targets, exits, matching shapes, empty slots, or completion counters;
- repeated structural motifs across levels;
- changes that reduce a well-supported task-specific discrepancy;
- human-efficient priors such as avoiding terminal failure and seeking novel progress states.

Keep separate:

- extrinsic progress evidence;
- intrinsic exploration utility;
- terminal-goal hypotheses;
- intermediate subgoals;
- confidence that a state is desirable;
- confidence that a plan reaches it.

Do not treat novelty alone as the objective once evidence of an external goal exists.

## 10. Exploration policy

Environment actions are expensive. Internal simulation is preferred.

Candidate action generation must:

- respect the currently advertised action space;
- include mandatory reset only when appropriate;
- detect repeated no-ops and suppress them;
- preserve undo/reversible actions when available;
- generate `ACTION6` coordinates from salient points before broad search.

Suggested coordinate candidates, deduplicated and clipped to 0–63:

1. centers and changed cells of persistent components;
2. centers of empty regions/slots;
3. endpoints, corners, and boundaries of components;
4. locations implicated by competing hypotheses;
5. unexplored coarse-grid cells;
6. finer local samples around responsive coordinates.

Score a probe using an explicit function such as:

```text
utility(action) =
    expected_information_gain
  + expected_progress
  + reversibility_bonus
  + novelty_bonus
  - expected_failure_cost
  - repeated_action_penalty
  - coordinate_search_cost
  - remaining_budget_pressure
```

The exact formula must be measured and configurable.

## 11. Planning

When the model predicts a plausible goal path:

1. compile a symbolic state and action model;
2. use BFS/A*/uniform-cost search for deterministic short plans;
3. use bounded belief-state or Monte Carlo search when outcomes are uncertain;
4. score plans by expected completion, action count, risk, and information value;
5. execute one action at a time unless the environment contract guarantees a macro;
6. compare each result with the predicted next state;
7. immediately replan or reopen on material mismatch.

A stale plan must never outrank new evidence.

## 12. Memory and retrieval

Raw traces are append-only. Summaries are replaceable derived views.

Retrieval should prefer:

- exact recent episode events;
- rules with high support in the current scope;
- counterexamples to currently active hypotheses;
- prior levels with analogous abstract state, not merely visual similarity;
- generic priors only after current-game evidence.

Compression must never destroy the pointer to source events. Every summary should list the event range and hash it summarizes.

Checkpoint contents:

- current normalized state hash;
- trace position;
- hypothesis registry;
- active world models;
- goal candidates;
- explored-state graph;
- planner state;
- RNG state;
- configuration and code commit.

## 13. Controller contract

The production controller should expose a small deterministic API compatible with the official starter/framework.

Conceptually:

```python
class ARC3Controller:
    def reset(self, context: RunContext) -> None: ...
    def observe(self, frames: FrameBatch) -> ObservationReceipt: ...
    def choose_action(self) -> ActionDecision: ...
    def apply_consequence(self, frames: FrameBatch) -> ConsequenceReceipt: ...
    def checkpoint(self) -> Checkpoint: ...
```

`ActionDecision` must contain the environment action and coordinate data required by the SDK, plus internal receipt identifiers. The Kaggle adapter may strip internal metadata from the submitted action while retaining it locally.

## 14. Baselines and ablations

Pin at least these policies:

- random valid action;
- deterministic action cycle;
- novelty-only exploration;
- trace without retrodiction;
- retrodiction without planner;
- full ARC3 controller.

Useful ablations:

- no cross-level memory;
- no rejected-hypothesis retention;
- no object tracking;
- no coordinate salience;
- no information-gain term;
- no world-model simulation;
- no plan recovery.

Every claimed architectural benefit must be tied to a comparison.

## 15. Evaluation and deployment surfaces

Support three adapters without changing core policy:

1. synthetic deterministic environments for unit/property tests;
2. official local/API ARC-AGI toolkit for public development;
3. Kaggle competition wrapper with internet disabled.

Competition packaging must include all dependencies, weights, schemas, and configuration needed at runtime. No credential or network code should be reachable in competition mode.

## 16. Optional local model path

A local/open-weight model may later be used for bounded proposal generation if:

- its license permits competition distribution;
- it fits the current Kaggle hardware/time budget;
- the agent remains functional without it;
- its output is typed and validated;
- it cannot directly issue unvalidated environment actions;
- it outperforms the no-model baseline under controlled ablation.

Do not make an external LLM API part of the competition architecture.

## 17. Safety and failure behavior

- If the game is over, issue only `RESET` when allowed.
- If state parsing fails, retain the raw frame and choose the least destructive valid fallback.
- If all candidate models fail, reopen to exploration rather than inventing certainty.
- If the action budget is nearly exhausted, prioritize known progress plans over broad novelty.
- If checkpoint restoration cannot validate hashes/version, start a new episode ledger and preserve the incompatible checkpoint for diagnosis.
- If a public-game shortcut is discovered, record it as diagnostic evidence but do not hard-code it into production policy.

## 18. Success criteria

The architecture is realized when:

- every action has an auditable receipt chain;
- at least one public environment is completed by a general policy or a bounded failure is measured;
- replay determinism is tested;
- world-model hypotheses can be falsified and reopened;
- action efficiency is measured against baselines;
- the agent packages and runs with networking disabled;
- no production branch contains game-ID-specific action logic;
- an independent clean-clone command reproduces the reported result.
