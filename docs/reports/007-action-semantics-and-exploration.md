# Stage 07 — Action semantics and information-efficient exploration

- **Stage status:** PASS
- **Measured surface:** synthetic
- **Mechanism result:** MECHANISM_OBSERVED
- **Measured at:** 2026-08-21
- **Repository base during measurement:** `54b09aa775973ca270f54ee42ff2d1c34ceb9f00` with Stage 07 files uncommitted
- **Primary evidence:** `docs/evidence/007-exploration-acceptance.json`

## Result

ARC3 now accumulates action-effect observations under generic structural state signatures and
ranks legal probes by explicit information, progress, reversibility, novelty, failure-risk,
repetition, and budget-pressure terms. Directional mappings for `ACTION1`–`ACTION4` begin only
as weight-0.25 generic priors; one contradictory observation outweighs and replaces the prior
for that condition.

The measured effect vocabulary retains simultaneous observable effects where appropriate:
no-op, movement, selection, interaction, undo, terminal, and metadata-only. These are measured
classes, not causal conclusions. Movement is proposed from exact translated same-color shapes;
later world-model evidence still controls causal promotion.

## Coordinate action probes

`ACTION6` candidates are bounded, deduplicated, and round-robin sampled from six generic
sources:

- component centers;
- changed cells;
- empty slots;
- corners and boundary midpoints;
- active-model disagreement cells;
- coarse-to-fine unexplored samples.

If several sources propose one coordinate, all supporting source labels remain attached.
Explored/out-of-bounds points are excluded, generation is deterministic, and a configurable
maximum prevents a dense source from exhausting the candidate budget.

## Suppression, undo, and fallback

Repeated no-ops are counted by both structural state signature and action. The same action is
suppressed after the configured threshold only under the unchanged condition; new structural
conditions reopen it. Suppression remains advisory when every legal option would otherwise be
removed.

`ACTION7` is never treated as undo from its name alone. It becomes eligible only after a
receipt shows that it restored a known prior frame and only while currently advertised.
`GAME_OVER` forces `RESET`. Near the action budget, the planner switches to a deterministic
progress-minus-risk fallback rather than spending the reserve on novelty.

## Held-out semantic-identification comparison

The pinned comparison generated 101 first-time typed cases from seed `20260821`. Each case had
two hidden alternatives, five generic actions, and one action whose predicted outcomes
discriminated the alternatives. Policy seed `7107` produced:

| Policy | Median actions | Total actions |
|---|---:|---:|
| information-directed exploration | 1.0 | 101 |
| random | 4.0 | 606 |
| deterministic cycle | 3.0 | 298 |

Median identification improved by 3 actions versus random and 2 versus cycle, so this bounded
mechanism is labeled `MECHANISM_OBSERVED`. The comparison deliberately isolates alternative
discrimination because the procedural lab API was still being integrated during Stage 07. It
does not measure puzzle completion, official action efficiency, or public/hidden performance.

## Verification

```text
Ruff check / format (Stage 07 paths): PASS
strict mypy (8 Stage 07 source files): PASS
focused pytest without coverage: 14 passed in 1.32s
Stage 07 public-game/game-specific sequence scan: 0 matches
```

Tests cover every effect class, duplicate-component movement rejection, weak-prior override,
conditioned statistics, all coordinate sources and bounds, alternative-discriminating utility,
repeated no-op suppression/reopening, evidence-gated undo, mandatory reset, budget fallback,
deterministic property-generated coordinate sets, and both comparison results/repeatability.

## Commands

```text
python -m uv run ruff check src/arc3/exploration scripts/measure_exploration.py tests/unit/test_exploration_effects.py tests/unit/test_exploration_coordinates.py tests/unit/test_exploration_policy.py tests/property/test_exploration_properties.py tests/integration/test_exploration_benchmark.py
python -m uv run ruff format --check src/arc3/exploration scripts/measure_exploration.py tests/unit/test_exploration_effects.py tests/unit/test_exploration_coordinates.py tests/unit/test_exploration_policy.py tests/property/test_exploration_properties.py tests/integration/test_exploration_benchmark.py
python -m uv run mypy src/arc3/exploration scripts/measure_exploration.py
python -m uv run pytest -q --no-cov --basetemp %TEMP%\arc3-stage07-final-pytest tests/unit/test_exploration_effects.py tests/unit/test_exploration_coordinates.py tests/unit/test_exploration_policy.py tests/property/test_exploration_properties.py tests/integration/test_exploration_benchmark.py
python -m uv run python scripts/measure_exploration.py --case-seed 20260821 --policy-seed 7107 --episodes 101
```

## Preserved limits

- The mechanism result is semantic-identification evidence, not game-completion evidence.
- Utility weights are generic configurable coefficients and are not calibrated expected utility.
- Geometric movement can remain ambiguous when similar components coexist.
- Full laboratory, public-development, and public-holdout comparisons remain Stages 14–15.
