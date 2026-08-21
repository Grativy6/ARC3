# Stage 08 — Retrodictive executable world model

- **Stage status:** PASS
- **Measured surface:** synthetic
- **Mechanism result:** MECHANISM_OBSERVED
- **Measured at:** 2026-08-21
- **Repository base during measurement:** `64408e35bea561f3959791adc94d11885270eca4` with Stage 08 files uncommitted
- **Primary evidence:** `docs/evidence/008-world-model-acceptance.json`

## Result

ARC3 now compiles compatible typed hypotheses into executable candidate world models instead of
stopping at narrative descriptions. The symbolic state records bounded entities, cells, facts,
counters, toggles, selection, and attachments with deterministic content identities. Typed
primitives execute movement, collision, toggles, transformations, counters, contact,
selection, attachment, and coordinate effects.

Unsupported or malformed hypothesis semantics become explicit compilation residuals rather
than guessed behavior. Conflicting live hypotheses form separate model candidates; compatible
claims can compose. Candidate and alternative weights remain signed `uncalibrated_rank`
values.

## Retrodiction gate

Every candidate must produce a retrodiction artifact before promotion. The gate evaluates each
preserved compatible transition or records an explicit condition-based exclusion. The artifact
retains tested, excluded, matched, and contradicted transition IDs; structural residuals; fit;
complexity; contradiction count; residual coverage; rank; and gate status.

A model with any unexplained preserved contradiction is rejected. A model that excludes every
transition without testing one is also rejected. Property-generated histories verify that no
compatible contradiction can disappear behind promotion unless a declared condition genuinely
narrows the transition scope. The retrodiction-off path exists only as an explicit ablation.

When multiple promoted candidates predict different states, the ensemble retains every
distinct outcome with supporting model/prediction IDs. The bounded simulator branches over
those outcomes and deterministically simulates short action sequences under stable model and
state identities.

## Prediction and mismatch receipts

Before a live action, the prediction book emits an immutable-shaped receipt containing the
decision ID, state, action, ensemble, alternatives, supporting models, and dependent plans.
After the returned consequence, matching records which predictions fit. A mismatch preserves
the state residual, reopens affected models to candidate status, and explicitly invalidates
dependent plans. It does not silently continue an obsolete prediction.

## Held-out symbolic comparison

Two development transitions supported movement to the right. A deliberately higher-ranked
alternative predicted movement left. The retrodiction gate rejected that contradicted model;
the retrodiction-off ablation kept both and selected the false higher-ranked one.

Four unseen start/target parameter combinations were then simulated under externally supplied
right-action plans totaling 16 actions:

| Variant | Symbolic completions | Planned actions |
|---|---:|---:|
| retrodiction-gated | 4/4 | 16 |
| retrodiction off, highest rank | 0/4 | 16 |

This bounded result is `MECHANISM_OBSERVED`: retrodiction materially improved model selection
and predicted final states. It is **synthetic** symbolic-simulator evidence. Plans were supplied,
no environment action was submitted, and it is not evidence of integrated planning, public-game
completion, or hidden generalization.

## Verification

```text
Ruff check / format (Stage 08 paths): PASS
strict mypy (10 Stage 08 source files): PASS
focused pytest without coverage: 12 passed in 1.25s
production public-ID/network/hosted scan: 0 matches
```

Tests cover every primitive, condition handling, collisions, deterministic identities,
hypothesis compilation and residuals, alternative outcomes, full-history artifacts, explicit
exclusions, contradiction rejection, promotion requirements, retrodiction ablation, simulator
branching, prediction receipts, mismatch reopening, and the held-out comparison.

## Commands

```text
python -m uv run ruff check src/arc3/world_model scripts/measure_world_model.py tests/unit/test_world_model_rules.py tests/unit/test_world_model_retrodiction.py tests/property/test_world_model_retrodiction_gate.py tests/integration/test_world_model_held_out.py
python -m uv run ruff format --check src/arc3/world_model scripts/measure_world_model.py tests/unit/test_world_model_rules.py tests/unit/test_world_model_retrodiction.py tests/property/test_world_model_retrodiction_gate.py tests/integration/test_world_model_held_out.py
python -m uv run mypy src/arc3/world_model scripts/measure_world_model.py
python -m uv run pytest -q --no-cov --basetemp %TEMP%\arc3-stage08-final-pytest-2 tests/unit/test_world_model_rules.py tests/unit/test_world_model_retrodiction.py tests/property/test_world_model_retrodiction_gate.py tests/integration/test_world_model_held_out.py
python -m uv run python scripts/measure_world_model.py
rg -ni "https?://|\b(requests|urllib|socket|httpx|openai|anthropic|google\.generativeai)\b" src/arc3/world_model
```

## Preserved limits

- Automatic symbolic-state construction from perception remains controller-integration work.
- The comparison supplies plans and therefore tests model selection, not search quality.
- Project-authored symbolic fixtures do not establish official game fidelity.
- Compilation covers declared generic syntaxes and preserves unsupported statements as
  residuals; it does not pretend every future mechanic is expressible.
