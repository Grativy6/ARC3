# Stage 06 — Synthetic environment laboratory

- **Stage status:** PASS
- **Measured surface:** synthetic
- **Measured at:** 2026-08-21
- **Repository base during measurement:** `22cc5c9de9d4b3d8814433b964f8a4c0687b537f` with Stage 06 files uncommitted
- **Primary evidence:** `docs/evidence/006-lab-acceptance.json`

## Result

ARC3 now has an official-shaped procedural laboratory for testing first-time interaction without
public-game memorization. A production session receives only normalized observations,
advertised actions, state, score metadata, and returned consequences. It receives no textual
instructions, rule-family label, target, oracle plan, transition explanation, or goal
annotation.

A separate evaluator owns exact transition annotations, action semantics, goal description,
oracle plan, reversibility flag, and contradiction markers. This boundary is enforced through
the public session API and automated leakage tests; it is not represented as an adversarial
security boundary against a developer reading first-party Python source.

## Rule families and partitions

Fifteen distinct procedural families cover unknown directional mapping, controllable-object
identification, conditional traversal, door/key toggles, coordinate targeting, color/shape
matching, cyclic timing, reversible versus irreversible consequences, delayed reward,
misleading novelty, partial observability, between-level rule change, a false initial
hypothesis, multiple compatible models, and game-over/reset recovery.

The versioned generator has three deterministic domains:

- development uses 12 families and development parameter ranges;
- held-out combinations reuse those families with unseen parameter combinations;
- held-out families use three rule families absent from development.

Seeded generation varies palette, object and target shapes, positions, directional action
mappings, distractors, layout/walls, size, and reversible/irreversible consequences. Identical
seed, count, and partition reproduce cases, initial frames, oracle plans, and transitions.

## Solvability, contradiction, and leakage

Seven fixed root seeds across all three partitions generated 630 episodes. Every oracle plan
completed under the executable environment, and the production observation graph exposed zero
forbidden evaluator fields. The self-test took 11.156787 seconds on the recorded local host.

The false-initial-hypothesis family deliberately produces two transitions that support a
directional rule and a third same action that contradicts it. Evaluator annotations identify
the reveal, while the production controller sees only ordinary observations and consequences.

Fast batches return immutable in-memory episode records containing action requests and frame
hashes. Durable hash-linked persistence remains the responsibility of Stage 03/13 integration.

## Pinned baseline measurement

Random-valid used root seed `20260821`, 30 episodes per partition, and a 64-action budget:

| Partition | Completed | Completion rate | Environment actions | Resets | Mean actions |
|---|---:|---:|---:|---:|---:|
| development | 10/30 | 33.33% | 1,407 | 0 | 46.9000 |
| held-out combinations | 9/30 | 30.00% | 1,594 | 0 | 53.1333 |
| held-out families | 2/30 | 6.67% | 1,840 | 10 | 61.3333 |

These are **synthetic** exact completion rates from `arc3.lab.completion-rate.v1`, not official
RHAE, online-public, Kaggle-public, semi-private, or official-private results. Per-episode
record-set hashes are preserved in the primary JSON evidence.

## Verification

```text
Ruff check / format (Stage 06 paths): PASS
strict mypy (6 Stage 06 source files): PASS
focused pytest without coverage: 16 passed in 12.74s
oracle solvability self-test: PASS (630/630)
production observation leakage self-test: PASS (0 detected fields)
```

The tests cover all family registrations, disjoint family splits, exact deterministic
generation, all randomization axes, public API isolation, false-leading evidence and later
contradiction, evaluator/session transition agreement, oracle completion, deterministic batch
records, baseline reproducibility, and property-generated seeds across every partition.

## Commands

```text
python -m uv run ruff check src/arc3/lab scripts/measure_lab_baselines.py
python -m uv run ruff format --check src/arc3/lab scripts/measure_lab_baselines.py
python -m uv run mypy src/arc3/lab scripts/measure_lab_baselines.py
python -m uv run pytest -q --no-cov --basetemp %TEMP%\arc3-stage06-final-pytest-nocov tests/unit/test_lab_catalog.py tests/unit/test_lab_transitions.py tests/property/test_lab_determinism.py tests/integration/test_lab_batch.py
python -m uv run python scripts/measure_lab_baselines.py --root-seed 20260821 --episodes 30 --max-actions 64
```

## Preserved limits

- Synthetic completion is diagnostic and cannot establish official-game fidelity or hidden
  generalization.
- Exact ground truth exists only for the evaluator and must never enter production controller
  inputs in later integrations.
- Batch records are not yet durable JSONL trace journals.
- The current environment uses compact grids and abstract mechanics; realism and difficulty
  coverage remain measurable open burdens.
