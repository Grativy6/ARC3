# ARC3 Build 003 — BLA–CLEF Mechanical Learner and Human-Scale Causal Exploration

> [!CAUTION]
> **Historical, nonoperative record.** ARC3 is retired. Commands, permissions, next steps, and continuation language below are quotations from an earlier state and grant no present authority. Do not execute them; see the root `AGENTS.md` and `SAFETY.md`.

Paste this entire instruction into Codex while working in the `Grativy6/ARC3` repository.

---

## Codex run instruction

Implement **ARC3 Build 003 — BLA–CLEF Mechanical Learner and Human-Scale Causal Exploration**.

The purpose of this build is to make the existing ARC3 candidate learn and reuse game mechanics through economical causal investigation. It should behave like a small, careful scientist: act, predict, observe, isolate consequences, retain reliable mechanics, localize surprises, and revise the smallest sufficient part of its model. It must build a broad, goal-relevant map of the game rather than enumerate every possible interaction.

This is an implementation and evaluation run, not a paper-writing exercise. Translate the source frameworks into bounded software mechanisms, tests, ablations, and evidence. Do not merely add framework terminology to comments or documentation.

### Controlling sources

Use the following in this order of authority for this build:

1. The current official ARC-AGI-3/Kaggle interface, rules, action semantics, and scoring methodology control benchmark behavior.
2. The repository's accepted Build 001 and Build 002 contracts, evidence, resource governors, and holdout ledger control project continuity.
3. **Boundary-Ledger Accounting in Primitive Axiom Layers**, Chris Pang, v0.9.1 public working draft, Zenodo record `20807530`: <https://zenodo.org/records/20807530>
4. **CLEF: Cluster-Layer Entropy Focus**, Chris Pang, v1.0 public theoretical framework, Zenodo record `21193511`: <https://zenodo.org/records/21193511>
5. PAL v2.2 controls PAL terminology if a conflict with older framework language appears. BLA and CLEF remain bounded companion implementations; they do not replace the benchmark specification or manufacture empirical authority.

Pin the exact source identities used in the Build 003 evidence. If a source cannot be retrieved or its identity cannot be verified, use a verified repository/local copy only if its provenance matches the cited record; otherwise stop with `BLOCKED_SOURCE_IDENTITY` before implementing framework-derived behavior.

Official ARC-AGI-3 sources to re-check at run time include:

- <https://docs.arcprize.org/methodology>
- <https://docs.arcprize.org/actions>
- <https://docs.arcprize.org/create-agent>
- <https://docs.arcprize.org/local-vs-online>
- <https://docs.arcprize.org/full-play-test>
- <https://github.com/arcprize/ARC-AGI-3-Kaggle-Starter>
- <https://github.com/arcprize/arc-agi>

Do not substitute remembered rules for current official documentation.

## 1. Base and authority gate

1. Fetch the repository and inspect `AGENTS.md`, the current branch topology, open Build 002 draft PR, implementation freeze, final evidence, and holdout authority before editing.
2. Build 003 must start from a clean `main` containing Build 002 final head `5448c53f3b7e08f606cf292e6068f3f9c9db16d4` or a verified merge-equivalent containing the same implementation and evidence state.
3. If Build 002 is not merged into `main`, stop read-only with `BLOCKED_BASE_NOT_MERGED`. Do not merge it, silently stack Build 003 on the draft branch, or rewrite history.
4. Preserve Build 001 as `PARTIAL` and `SEALED_UNCONSUMED`.
5. Preserve Build 002 as `PARTIAL` with exact evaluation `BLOCKED_EXTERNAL` unless new authorized evidence actually changes that status.
6. Preserve public-holdout authority at `0/1 consumed`. This build does not authorize Kaggle terms acceptance, credentials, notebook upload, online scorecard creation, submission, leaderboard interaction, or consumption of the sealed public holdout.
7. Offline play is authorized only on:
   - repository fixtures;
   - newly created hidden synthetic mechanic environments;
   - environments already and explicitly classified by the repository as open development/training surfaces that are not part of the sealed holdout.
8. Do not access an environment merely because the official toolkit technically permits unlimited local runs. Project holdout classification controls experimental use.
9. Create branch `build/003-bla-clef-mechanical-learner`.
10. Local edits, tests, deterministic offline experiments, commits, pushing this branch, and opening/updating a **draft** PR are in scope. Merging, releasing, publishing, spending money, accepting terms, using credentials, or externally messaging as Christopher are out of scope.

## 2. Primary claim under test

Pre-register this claim before running the final experiments:

> A game-agnostic online learner can conserve reliable mechanics across progressive levels, identify prediction residuals, localize new mechanics at the smallest useful causal layer, and reduce unnecessary exploratory actions without using game-specific solutions or exhaustive interaction search.

Break it into three falsifiable hypotheses:

- **H1 — transfer:** A learner that retains scoped mechanics across levels requires fewer exploratory actions on later levels than the same learner reset at every level, without reducing completion.
- **H2 — conservative repair:** When a local modifier is introduced, the learner preserves still-correct base mechanics and revises only the affected scope more often than it performs a global foundational rewrite.
- **H3 — layer relevance:** Adding the bounded CLEF layer/stopping mechanism to the BLA residual learner reduces redundant probes and representational over-expansion without reducing completion or worsening action efficiency.

Do not claim that synthetic confirmation establishes ARC-AGI-3 performance, RHAE, human cognition, general intelligence, or validation of BLA/CLEF as general scientific theories.

## 3. Non-negotiable learning behavior

Implement these behavioral rules once, centrally:

1. **Predict before acting.** Every environment action must have an explicit predicted consequence vector, even if some entries are `UNKNOWN`.
2. **Separate observation from interpretation.** Record what changed before naming a mechanic.
3. **Decompose consequences.** One action may change position, resources, inventory, topology, legal actions, status, score, animation, and terminal state. Do not collapse these into one success/failure label.
4. **Residuals open questions, not answers.** A mismatch may open a provisional boundary-ledger; it cannot establish a mechanic by itself.
5. **Prefer the smallest sufficient repair.** Search changed objects, contacts, terrain, resources, status, timing, and local interactions before reopening a reliable base rule.
6. **Conserve successful mechanics.** A mechanic that still predicts its declared consequences remains active within its scope even when another consequence surprises the learner.
7. **Earn reliability.** Repeated predictive success across distinct contexts raises support. Contradiction narrows, stresses, or reopens scope. No learned mechanic becomes infallible.
8. **Use stable mechanics; do not repeatedly probe them.** Stable rules receive passive confirmation whenever normal play exercises them. Explicit action-consuming checks target uncertain, consequential mechanics first.
9. **Carry mechanics across levels within a game.** Reset the level map and transient state, not the game's earned mechanic library.
10. **Quarantine game-specific mechanics between games.** Retain generic causal-learning operators and explicitly generic priors, but do not leak one game's tile identities, coordinates, goals, or rules into another game as facts.
11. **Build a relevant map, not an exhaustive interaction table.** Track reachable regions, object classes, resources, hazards, gates, goals/progress signals, and unresolved high-impact boundaries. Do not enumerate every action against every pixel or object.
12. **Treat actions as scarce.** Internal reasoning is cheaper than environment interaction under RHAE. Prefer actions that jointly advance the likely goal and discriminate important hypotheses.
13. **Retain history without keeping everything active.** Archive superseded hypotheses and receipts; bound the active working set.
14. **No game-specific code.** No game IDs, level IDs, fixed coordinates, walkthroughs, target layouts, handcrafted tile meanings, or per-game strategy branches may enter the learner.

## 4. Required architecture

Inspect and reuse the existing architecture before adding modules. Do not rewrite working Build 002 packaging, lifecycle, tournament governance, or adapter code unless a measured integration need requires a small change. Record every altered existing contract.

Names below describe responsibilities, not mandatory filenames.

### 4.1 CLEF layer declaration and readable state

Implement a compact, software-specific `LayerDeclaration` derived from CLEF v1.0:

```text
L_min = (X, r, N_L, A_L, W_L)
```

where:

- `X` is the available frame/state/metadata field;
- `r` is the current aperture, segmentation scale, or resolution;
- `N_L` is the noise/readability threshold at that layer;
- `A_L` is the extraction or reading method;
- `W_L` is the readability wall beyond which added detail is unavailable or irrelevant to the current decision.

For dynamic action-effect claims, also track:

- sampled time/action window;
- the intervention/action;
- assumed regime/scope;
- the observation return path.

Provide at least these logical layers, adapting them to existing code rather than forcing a parallel stack:

1. raw frame and official metadata;
2. stable regions/components/object candidates;
3. relations such as adjacency, contact, containment, blocking, reachability, and shared visual class;
4. action-effect events and mechanic hypotheses;
5. planning state: goals/progress, resources, hazards, gates, and frontiers.

Use CLEF only where operationally justified:

- keep independent evidence channels separate before optional scalar reduction;
- treat required validity checks as gates that cannot be averaged away;
- promote a lower-layer residual into a higher-layer feature only when it remains readable above noise and improves prediction or action selection;
- stop splitting when the deeper distinction is below noise, already explained, beyond the readability wall, does not change a relevant prediction/action, or costs more than its expected decision value.

Do **not** import CLEF's physical surface-tension, curvature, free-energy, thermodynamic, or material-cost examples as game laws. For this build, CLEF supplies accountable layer declaration, checked coherence, coupling promotion, uncertainty, and scale-relevance stopping.

### 4.2 Causal event extractor

For every external action, produce a structured action receipt containing at least:

```text
receipt_id
game_scope_id
level_scope_id
step_index
before_state_ref
chosen_action_and_coordinates
legal_actions_before
predicted_effects
observed_effects
explained_effects
residual_effects
objects_or_regions_implicated
active_hypotheses_used
probe_or_progress_reason
resource_and_failure_risk
terminal_state
```

Observed effects must be factored when readable into channels such as:

- controllable-object displacement;
- other-object displacement or transformation;
- resource/HUD change;
- inventory or count change;
- legal-action change;
- topology, blocking, gate, or reachability change;
- status/animation change;
- score/progress change;
- `WIN`, `GAME_OVER`, or reset transition;
- delayed or currently unresolved consequence.

Use frame differencing, segmentation, connected components, object tracking, temporal correspondence, and existing learned features where appropriate. Avoid treating every changed pixel as an independent mechanic. Preserve compact evidence references or hashes so a higher-level interpretation remains traceable to the frame transition.

### 4.3 BLA mechanic ledger

Implement a versioned mechanic ledger. Each mechanic record should include:

```text
mechanic_id and version
scope: generic / game / level / region / object-class / state-conditional
cause or intervention
preconditions
predicted consequence vector
composition mode: base / additive / conditional / gating / override / delayed
support state and calibrated confidence/interval
evidence receipt refs
counterevidence and unresolved residual refs
dependencies
prediction success/failure counts by distinct context
last relevant observation
status
reopen handle
```

Use statuses equivalent to:

- `PROVISIONAL`
- `SUPPORTED`
- `STABLE_WITHIN_SCOPE`
- `STRESSED`
- `RECURRING_UNRESOLVED`
- `REOPENED`
- `REJECTED_OR_SUPERSEDED`

Do not overwrite prior mechanic versions. A revision creates a new version linked to the evidence and prior version. Superseded rules leave the active set but remain recoverable.

Represent the prediction residual as a structured vector:

```text
r_t = observed_effects - predicted_effects
```

The subtraction may be numeric, categorical, spatial, set-valued, or mixed. Residual thresholds must respect measurement noise and consequence. A visually large animation with no action relevance may remain below the active layer; a small change to a failure-linked resource may be high signal.

Operationalize BLA's authority rule:

- one observation may open a ledger;
- recurrence across independent contexts, inherited trusted structure, or lower-layer derivation is required to strengthen a pattern;
- predictive transfer to a later level is stronger evidence than repetition at one coordinate;
- uncertainty is the first boundary around a residual;
- saturation occurs when recovering another distinction no longer changes relevant prediction or action enough to justify its cost.

### 4.4 Conservative causal composition

The default effect model should be compositional and sparse:

```text
observed effect
  = base action effect
  + object/terrain/contact modifiers
  + resource or status modifiers
  + temporal/state modifiers
  + explicitly supported interaction terms
  + unresolved residual
```

Prefer a small conditional modifier over a global exception when it explains the evidence.

Canonical required example:

```text
stable rule: movement changes player position and costs 1 resource unit
new observation: entering a distinct tile changes position as predicted but resource rises by 4
first local candidate: movement cost -1 plus tile-entry restoration +5
alternatives: cancel-and-add, set-to-value, refill-to-cap, one-shot pickup, delayed trigger
```

The position consequence passively confirms movement. The resource residual opens a tile/resource ledger. Do not globally reject movement cost unless tile-local and interaction explanations repeatedly fail away from the tile.

When candidate explanations remain observationally equivalent, retain the ambiguity and choose the cheapest safe discriminating action only if resolving it can affect route, survival, completion, or future action budget.

### 4.5 Reliability and passive confirmation

Reliability must grow through earned predictive performance, not raw repetition count alone. Reward:

- correct prediction across different positions, directions, states, levels, and layouts;
- correct transfer after visual remapping;
- independent evidence channels;
- correct prediction of both occurrence and magnitude;
- survival of relevant counterfactual tests;
- lower-layer support that is actually available to the learner.

Penalize or narrow for:

- structured counterexamples;
- reliance on one coordinate, color, seed, or animation artifact;
- dependent duplicate evidence;
- unexplained sign or magnitude changes;
- failed transfer.

Never encode `confidence = 1.0` as permanent truth. Stable mechanics should be the last targets of explicit probes, but every naturally occurring use should update their passive predictive record.

### 4.6 Broad relevance map and bounded exploration

Maintain a compact exploration map containing:

- controllable entity candidates;
- reachable/visited regions and frontier regions;
- visually or behaviorally equivalent object/tile classes;
- resources and their observed links to failure, progress, or reachability;
- hazards, blockers, gates, switches, goals/progress indicators;
- new salient features;
- active high-impact residuals;
- unresolved dependencies between mechanics.

Do not maintain a full Cartesian product of actions × coordinates × objects × states.

Rank candidate actions using a documented, configurable policy shaped like:

```text
value(action)
  = expected goal/progress value
  + expected information gain × consequence relevance
  + expected future action savings
  - environment action cost
  - failure/resource risk
  - redundancy
  - computation/runtime pressure
```

Immature estimates may be qualitative or interval-valued. Do not create fake precision.

Default exploration limits must be configurable and justified by ablation. Begin conservatively with:

- no more than 4 active candidate explanations for one residual;
- no more than 2 deliberate repeats of an equivalent probe without new evidence;
- only the top 8 unresolved, reachable, consequence-relevant ledgers eligible for explicit probing at one decision;
- representative sampling of an equivalence class before member-by-member testing.

These are starting limits, not benchmark truths. Tune them only on open synthetic/training surfaces and report the effect.

For coordinate actions, target readable objects, region centers, boundaries, frontiers, or discriminating points. Never brute-force all coordinates. A fallback grid search is prohibited unless a bounded region has first been causally justified and the cost is explicitly accepted by the action governor.

Park low-impact unexplained visual changes rather than deleting them. Reopen them if they later correlate with failure, progress, resources, reachability, legal actions, or a repeated prediction residual.

### 4.7 Human-scale priors without hidden solutions

Use only documented interface knowledge and explicitly labeled generic game priors. Every prior must carry provenance:

- `OFFICIAL_INTERFACE`
- `GENERIC_GAME_PRIOR`
- `OBSERVED_THIS_GAME`
- `DERIVED_THIS_GAME`

Acceptable provisional priors include:

- repeated directional action semantics documented by ARC-AGI-3;
- a repeatedly moving coherent object may be controllable;
- a bar or count that changes with actions may be a resource or progress variable;
- zeroing a variable followed by reset links it provisionally to failure;
- repeated visual classes may share affordances;
- a new distinct object or tile introduced on a later level may be mechanically relevant.

Priors select economical first tests; they do not count as observed mechanics. Remove or narrow them when the trace disagrees.

### 4.8 Persistence boundaries

Within one game:

- persist the mechanic ledger across levels;
- retain support and counterevidence;
- reset layout-specific coordinates, transient objects, and level-local route plans;
- treat a new level as old mechanics plus a provisional delta, not as a blank world;
- allow later levels to refine or condition prior mechanics without erasing their earlier valid scope.

Between games:

- retain the learner, generic causal operators, generic visual abstractions, and source-labeled priors;
- quarantine game-specific mechanic records and learned object semantics;
- do not use previous game IDs or learned layouts as hints.

Across resets/failures:

- preserve evidence earned before failure;
- distinguish reset consequences from ordinary mechanics;
- avoid repeating a failed sequence unless it tests a materially different hypothesis or is the best supported route.

### 4.9 Planning with the learned model

Use the most reliable applicable mechanics to plan over the current broad map. Planning may be hierarchical or model-predictive, but must:

- distinguish known, probable, and unresolved transitions;
- account for resource/failure risk;
- favor progress while reserving limited exploration for consequential uncertainty;
- replan after every external action;
- use interaction rules only inside their earned scope;
- avoid long imagined rollouts through unsupported mechanics;
- fall back legally and gracefully under resource pressure.

Continue honoring Build 002's tournament governor, legal-action enforcement, runtime reserve, action accounting, and fallback behavior.

## 5. Implementation sequence

### Stage 0 — Identity and base preflight

- Verify source records, repository state, Build 001/002 evidence, current official interface, package constraints, and holdout ledger.
- Emit a preflight receipt before editing.
- Stop honestly on any identity, base, authorization, or environment ambiguity that could contaminate the holdout.

### Stage 1 — Existing-system audit and frozen baseline

- Map the current perception, memory, action selection, corpus, `MyAgent`, governor, trace, replay, and packaging paths.
- Identify existing mechanisms that already satisfy part of this workflow; reuse them.
- Freeze a reproducible pre-Build-003 baseline on synthetic/open fixtures only.
- Record tests, runtime, memory, action counts, and current failure modes.
- Do not tune against the sealed public set.

### Stage 2 — State/event representation

- Implement layer declarations, readable-state extraction, object/relation tracking, and structured action receipts.
- Prove that irrelevant pixel animation does not automatically become an active mechanic.
- Prove that resource, legal-action, reachability, and terminal changes remain visible even if their pixel footprint is small.

### Stage 3 — BLA residual and mechanic ledger

- Implement prediction vectors, structured residuals, provisional ledgers, candidate hypotheses, evidence updates, versioned revision, local-first reopening, and passive confirmation.
- Add deterministic serialization/replay in research mode.
- Keep competition-mode state bounded and in memory with sparse recovery; do not restore per-action checkpoint serialization.

### Stage 4 — CLEF layer relevance and stopping

- Implement noise/readability thresholds, independent evidence families, validity gates, coupling/residual promotion, and the scale-relevance stopping rule.
- Demonstrate that the learner can move upward from pixels to objects/relations/mechanics when useful and stop before exhaustive lower-layer analysis.

### Stage 5 — Relevance-bounded exploration and planning

- Implement the broad map, equivalence classes, action ranking, probe limits, goal/resource relevance, future-action savings, and risk accounting.
- Integrate with the existing governor rather than creating a second competing budget authority.

### Stage 6 — Cross-level persistence and scoped composition

- Persist mechanics within a game while resetting level-local state.
- Implement additive, conditional, gating, override, and delayed composition with conservative scope.
- Verify recovery after failure and quarantine between games.

### Stage 7 — Hidden progressive mechanic curriculum

Create a deterministic, procedural evaluation suite behind the same observation/action boundary used by the learner. The learner must not import, inspect, or receive the environment's rule configuration.

The suite must include progressive level families such as:

1. directional movement plus a fixed action-linked resource cost;
2. blocking/walls while preserving movement elsewhere;
3. a resource-restoring tile introduced after the base resource rule is stable;
4. reusable versus one-shot restoration;
5. a gate/switch or inventory interaction changing reachability;
6. pushing or moving another object;
7. a terrain/status modifier that composes with movement;
8. delayed consequences or a hidden-state response;
9. harmless animation/decorative changes that should not attract deep exploration;
10. held-out combinations of previously learned mechanics on new layouts.

Randomize colors, sprites, coordinates, layouts, counts, action labels where permitted by the fixture contract, and mechanic magnitudes. Include held-out mechanic **compositions**, not only held-out maps.

Keep environment definitions in evaluator-only modules. Add an import-boundary test proving runtime learner code cannot read fixture rules, solution paths, generator seeds, or privileged state.

### Stage 8 — Pre-registered ablation study

Run identical predeclared held-out seeds and action budgets across:

1. the frozen Build 002 baseline;
2. the mechanical learner with per-level mechanic reset;
3. BLA residual/ledger learning without CLEF layer relevance;
4. the full BLA + CLEF learner.

Use at least 30 held-out seeds per curriculum family unless resource preflight demonstrates that this would violate the declared budget; if reduced, justify and record the reduction before seeing results.

Report paired distributions, not only best runs or global means. Include medians, spread/confidence intervals, failures, and per-family results.

Primary metrics:

- levels completed;
- total environment actions;
- exploratory versus progress actions;
- redundant probes;
- actions until a mechanic becomes supported/stable;
- prediction error by consequence channel;
- residual localization and resolution rate;
- transfer savings on later levels;
- base-mechanic retention after a local modifier;
- erroneous global reopenings;
- unresolved-ledger count and active-ledger pressure;
- wall time and peak memory;
- replay determinism and receipt completeness.

No final seed may be replaced after results are visible. No result may be omitted because it is inconvenient.

### Stage 9 — Required adversarial tests

At minimum, prove or honestly fail each of these:

- one movement creates a provisional movement/resource hypothesis without claiming certainty;
- repeated movement across distinct contexts strengthens it;
- resource exhaustion plus reset strengthens the failure-link interpretation;
- a restoration tile creates a localized resource residual while preserving the correctly predicted movement consequence;
- the learner distinguishes additive restoration from at least one competing explanation with a minimal probe when that distinction matters;
- an established movement/resource rule transfers to a later level with fewer deliberate probes;
- a visually remapped but mechanically identical level does not force full relearning;
- harmless visual changes are parked below the active relevance threshold;
- a small but failure-relevant resource change outranks a large decorative change;
- low-confidence/high-impact mechanics are investigated before stable base mechanics;
- repeated local explanations that fail cause a deeper assumption to reopen;
- `ACTION6` or equivalent coordinate behavior does not devolve into whole-grid brute force;
- failure/reset retains earned mechanics without repeating an identical failed plan blindly;
- game-specific mechanics do not cross a game boundary;
- fixture privileged state is unreachable from the learner;
- disabling the ledger or cross-level persistence causes the expected measured loss rather than no change.

### Stage 10 — Performance, packaging, and competition compatibility

- After the synthetic acceptance gates pass, run at least one complete progressive level sequence through the real official offline interface **only** if the environment is already classified by repository evidence as open development/training and not as the sealed public holdout. Use the same learner code and action boundary intended for competition; do not substitute direct environment-state access. Record the replay, action receipts, mechanic-ledger evolution, completion, action count, redundant probes, and failures. If no such official open surface exists, report `OFFICIAL_OPEN_DEVELOPMENT_PLAY = UNAVAILABLE` and do not consume or relabel the holdout.
- Preserve explicit `RESEARCH_UNBOUNDED` and `COMPETITION_BOUNDED` modes.
- Research mode may emit full mechanic ledgers and receipts.
- Competition mode must keep compact bounded working state, sparse recovery, and a compact in-memory trace. Do not re-enable Build 002's measured performance hazards: allocator tracing or automatic per-action checkpoint serialization.
- Profile the new learner against the frozen Build 002 synthetic profile and report all regressions.
- Prove deterministic replay, lifecycle compliance, legal actions, bounded fallback, offline cold start, packaged dependency completeness, and notebook compatibility.
- Do not call synthetic action profiling RHAE or gameplay generalization evidence.

### Stage 11 — Evidence freeze and handoff

Freeze implementation before generating final evidence. After the freeze, permit documentation/evidence-only commits and prove no code, test, package, or configuration drift.

Create at minimum:

- `docs/research/ARC3-Build-003-report.md`
- `docs/handoffs/003-bla-clef-mechanical-learner.md`
- `docs/evidence/003-final-evidence-index.json`
- a source-to-implementation mapping for every BLA/CLEF mechanism actually used;
- pre-registration and seed manifest;
- ablation results in machine-readable and human-readable forms;
- replay/receipt samples for required adversarial cases;
- performance and cold-start receipts;
- secret scan and environment-access receipt;
- hashes for configuration, implementation candidate, packaged payload, evidence index, and key result tables.

Open or update a **draft** PR. Do not merge it.

## 6. Acceptance and claim gates

Build 003 may report `MECHANISM_CONFIRMED_SYNTHETIC` only if all of the following hold:

1. Hidden progressive-mechanic tests pass without privileged fixture access or game-specific branches.
2. Cross-level persistence improves later-level exploration efficiency over per-level reset on predeclared held-out seeds without a material completion regression.
3. Full BLA + CLEF reduces redundant probing or representational over-expansion relative to BLA-only without a material completion/action-efficiency regression.
4. Local modifiers preserve still-correct base mechanics in the required adversarial cases.
5. Every external action has a complete, replay-linked receipt.
6. Competition-bounded memory/runtime remain within the existing governor and cold-start/package gates pass.
7. The full test matrix, source scan, secret scan, formatting, lint, typing, and existing Build 001/002 protected verification pass.

If implementation succeeds but comparative evidence is incomplete, report `PARTIAL`.

If the exact ARC/Kaggle environment remains unavailable, report `BLOCKED_EXTERNAL` for exact benchmark evaluation while separately reporting the synthetic mechanism result. Do not collapse those statuses.

Always include:

```text
OFFICIAL_ARC3_RHAE = NOT_MEASURED
PUBLIC_HOLDOUT_CONSUMED = 0/1
NO_ARC3_GENERALIZATION_CLAIM
```

unless an independently authorized future run genuinely changes them.

## 7. Final Codex response

Lead with what was actually implemented and what the experiments showed. Include:

- branch, implementation-freeze commit, final head, and draft PR;
- exact status labels;
- public-holdout ledger;
- source identities;
- architecture delivered;
- ablation results and failures;
- test/CI totals by platform;
- runtime, peak memory, and package/cold-start results;
- evidence artifact paths and principal hashes;
- blockers and remaining uncertainties;
- confirmation that no terms, credentials, Kaggle uploads/submissions, scorecards, money, releases, merges, or external messages were used or sent.

Do not use passing software tests as evidence that the learner understands ARC-AGI-3. Do not treat framework alignment as performance evidence. Do not call a synthetic result RHAE. Preserve every open burden explicitly.

---

## Intended behavioral summary

The finished learner should follow this compact loop:

```text
read the smallest useful state
→ predict consequences
→ choose progress or one economical probe
→ act once
→ separate observed consequences
→ compute structured residuals
→ localize the smallest changed boundary
→ update scoped mechanic ledgers
→ strengthen reliable predictions passively
→ retain unresolved alternatives without activating all of them
→ plan over the broad relevant map
→ repeat
```

The target is accumulated, economical understanding: not a blank-slate reset, not a walkthrough, and not an exhaustive search.
