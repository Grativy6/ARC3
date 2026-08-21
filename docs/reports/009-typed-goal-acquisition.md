# Stage 09 — Typed goal acquisition

- **Stage status:** PASS
- **Measured surface:** synthetic
- **Mechanism result:** MECHANISM_OBSERVED
- **Measured at:** 2026-08-21
- **Repository base during measurement:** `f87cdb2d5eaa0be90f90fcbb301babefd78574e2` with Stage 09 files uncommitted
- **Primary evidence:** `docs/evidence/009-goal-acceptance.json`

## Result

ARC3 now represents states worth pursuing as falsifiable, source-linked goal candidates rather
than folding progress, novelty, and completion into one score. Candidate records preserve goal
kind, role, scope, target, immutable source event IDs, uncalibrated rank, contradictions,
retirement, and reopening history. A compact bridge exposes candidates to the typed hypothesis
vocabulary without promoting them to accepted rules or action authorization.

Explicit metadata comparison detects score, progress, level, completed-level, win, and game-over
transitions. Generic geometry proposes exits, enclosed matching slots, repeated-pattern
completion, component contact, and stable discrepancy reduction. These structural measurements
remain hypotheses until correlated with explicit progress or later tests. Repeated structure
across level scopes can produce a separately sourced game-scope candidate.

## Goal roles and lifecycle

External progress, intermediate subgoals, and terminal hypotheses have distinct types.
Intrinsic novelty, information gain, and reversibility remain an exploration-utility value and
cannot become a goal record. Selection combines an active goal's desirability and estimated
reachability with bounded exploration utility. Once explicit external-progress evidence reaches
the declared integer threshold, novelty stops contributing to action selection; information and
reversibility remain available for useful probes.

Contradicting tests lower the candidate's uncalibrated rank and retire it after the configured
threshold. Later independent support reopens the record while retaining every prior evidence
item and lifecycle event. Reports expose the source event IDs and use mechanism language rather
than simulated intention or belief.

## Delayed/proxy-goal comparison

Sixty-four deterministic held-out label permutations each contained a five-action delayed
progress path paired with a locally novel non-progressing path. Both variants received the same
five-action budget:

| Variant | Synthetic completions | Actions |
|---|---:|---:|
| goal-aware selection after strong progress evidence | 64/64 | 320 |
| novelty-only | 0/64 | 320 |

The result is `MECHANISM_OBSERVED` under scorer
`arc3.goals.delayed-proxy-completion.v1`. It shows that the typed selector can preserve a delayed
externally supported target instead of repeatedly choosing novelty. The fixture supplies the
candidate evidence and per-action model estimates; it does not measure perception-to-goal
accuracy, integrated planning, public-game completion, or hidden-game generalization.

## Verification

```text
Ruff check / format (Stage 09 paths): PASS
strict mypy (10 Stage 09 source/script files): PASS
focused pytest without coverage: 19 passed in 1.48s
production public-ID/network/hosted scan: 0 matches
```

Tests cover metadata signals, generic structural proposals, cross-level evidence, role
separation, deterministic identities, duplicate evidence, retirement/reopening, report source
links, novelty suppression, validation properties, and the delayed/proxy comparison.

## Commands

```text
python -m uv run ruff check --no-cache src/arc3/goals scripts/measure_goals.py tests/unit/test_goals_progress.py tests/unit/test_goals_registry.py tests/unit/test_goals_selection.py tests/unit/test_goals_structure.py tests/integration/test_goals_acquisition.py tests/integration/test_goals_delayed_proxy.py tests/property/test_goals_properties.py
python -m uv run ruff format --check --no-cache src/arc3/goals scripts/measure_goals.py tests/unit/test_goals_progress.py tests/unit/test_goals_registry.py tests/unit/test_goals_selection.py tests/unit/test_goals_structure.py tests/integration/test_goals_acquisition.py tests/integration/test_goals_delayed_proxy.py tests/property/test_goals_properties.py
python -m uv run mypy --cache-dir %TEMP%\arc3-stage09-mypy-script src/arc3/goals scripts/measure_goals.py
python -m uv run pytest -q --no-cov --basetemp %TEMP%\arc3-stage09-final-pytest tests/unit/test_goals_progress.py tests/unit/test_goals_registry.py tests/unit/test_goals_selection.py tests/unit/test_goals_structure.py tests/integration/test_goals_acquisition.py tests/integration/test_goals_delayed_proxy.py tests/property/test_goals_properties.py
python -m uv run python scripts/measure_goals.py --case-seed 20260821 --episodes 64 --horizon 5
rg -ni "https?://|\b(requests|urllib|socket|httpx|openai|anthropic|google\.generativeai)\b|ls20-|ft09-|vc33-" src/arc3/goals
```

## Preserved limits

- Structural feature heuristics are generic and uncalibrated; a proposal is not proof of a goal.
- The comparison begins after strong external-progress evidence and does not evaluate its
  discovery cost.
- Planning, live consequence validation, and full controller integration remain Stages 10–12.
- Project-authored synthetic results do not establish official environment fidelity.
