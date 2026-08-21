# Stage 10 — Bounded planning and recovery

- **Stage status:** PASS
- **Measured surface:** synthetic
- **Mechanism result:** MECHANISM_OBSERVED
- **Measured at:** 2026-08-21
- **Repository base during measurement:** `ff7397907222fc317fb2a84b33f5ec2ab64ca7f9` with Stage 10 files uncommitted
- **Primary evidence:** `docs/evidence/010-planning-acceptance.json`

## Result

ARC3 now searches executable symbolic world models before spending environment actions. Bounded
breadth-first, uniform-cost, and A* search share explicit node, depth, and wall-clock limits and
stable action/state tie-breaks. A plan retains its model identity, goal identity and revision,
predicted states, per-step cost, risk, information value, completion estimate, and a deterministic
content-derived plan ID.

The executor releases exactly one action and then requires the returned symbolic consequence
before another action can be emitted. A model or goal revision invalidates the stale plan. A
prediction mismatch produces a concise source-ready receipt and chooses one declared recovery:
replan under the same model, request a supplied discriminating probe, reopen the model, use undo
only when supported, or reset after game over. The no-recovery ablation stops instead of blindly
continuing.

The current promoted model machinery is deterministic. Belief-state or Monte Carlo search was
therefore not added merely for complexity; unresolved model alternatives route to the bounded
discriminating-probe recovery path. This can be reopened when integrated uncertainty evidence
shows that explicit belief search improves equal-budget results.

## Held-out symbolic comparison

Twenty-four deterministically generated eight-by-eight tasks used unseen start, target, and
action-to-direction permutations. Each task had a 24-action environment budget:

| Variant | Synthetic completions | Environment actions |
|---|---:|---:|
| bounded A* planning | 24/24 | 174 |
| exploration-only deterministic cycle | 0/24 | 576 |
| replan after one injected prediction mismatch | 24/24 | 198 |
| no recovery after the same mismatch | 0/24 | 24 |

The result is `MECHANISM_OBSERVED`. Planning materially improved completion and action use over
the named exploration-only baseline, and traceable recovery improved completion over the
no-recovery ablation. The task manifest hash is
`sha256:feb356d28cd533825f59b4221154fff6055b7ae0ee052ab9302e389bd7b40a14`.

This is synthetic symbolic evidence. Tasks are compact obstacle-free navigation cases, targets
are evaluator supplied, the exploration baseline is deliberately simple, and the mismatch is an
injected first-action no-op. It is not evidence of raw-frame state construction, public-game
completion, or hidden-game generalization.

## Verification

```text
Ruff check / format (Stage 10 paths): PASS
strict mypy (7 Stage 10 source/script files): PASS
focused pytest without coverage: 10 passed in 3.87s
production public-ID/network/hosted scan: 0 matches
```

Tests cover all search orders and budget exits, deterministic plan identities, invalid numeric
metrics, one-action gating, model/goal invalidation, consequence matching, every recovery mode,
game-over reset, plan scoring, held-out comparison, and randomized bounded-search properties.

## Commands

```text
python -m uv run ruff check --no-cache src/arc3/planning scripts/measure_planning.py tests/unit/test_planning_search.py tests/unit/test_planning_execution.py tests/property/test_planning_properties.py tests/integration/test_planning_held_out.py
python -m uv run ruff format --check --no-cache src/arc3/planning scripts/measure_planning.py tests/unit/test_planning_search.py tests/unit/test_planning_execution.py tests/property/test_planning_properties.py tests/integration/test_planning_held_out.py
python -m uv run mypy --cache-dir %TEMP%\arc3-stage10-mypy-script src/arc3/planning scripts/measure_planning.py
python -m uv run pytest -q --no-cov --basetemp %TEMP%\arc3-stage10-final-pytest-2 tests/unit/test_planning_search.py tests/unit/test_planning_execution.py tests/property/test_planning_properties.py tests/integration/test_planning_held_out.py
python -m uv run python scripts/measure_planning.py --seed 20260821 --tasks 24 --action-budget 24
rg -ni "https?://|\b(requests|urllib|socket|httpx|openai|anthropic|google\.generativeai)\b|ls20-|ft09-|vc33-" src/arc3/planning
```

## Preserved limits

- Symbolic states, deterministic model, and target are supplied by the Stage 10 evaluator.
- Search correctness does not establish that upstream perception, goal acquisition, or model
  promotion chose the right problem.
- Plan completion likelihood and scoring weights are uncalibrated estimates, not probabilities.
- Full live controller wiring, persistent restart continuity, and full-game ablations remain
  Stages 11–14.
