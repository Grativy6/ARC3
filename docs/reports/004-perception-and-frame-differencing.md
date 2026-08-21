# Stage 04 — Perception and frame differencing

- **Stage status:** PASS
- **Measured surface:** synthetic
- **Measured at:** 2026-08-21
- **Repository base during measurement:** `11a6dd20ad5f2ea77bbc09046ad4e8bf5818a3fc` with Stage 04 files uncommitted
- **Primary evidence:** `docs/evidence/004-perception-acceptance.json`

## Result

ARC3 now turns immutable raw grids into immutable geometric measurements without assigning
game roles or inferred intent. It preserves the adapter's canonical grid hash so one frame has
the same content identity at receipt and perception boundaries.

The perception pipeline measures:

- exact cell masks, additions, removals, recolors, extent changes, and scalar metadata deltas;
- same-color connected components under explicit 4- or 8-connectivity and configurable or
  ranked background candidates;
- color-independent shape signatures with declared translation, rotation, or reflection
  invariance;
- bounding boxes, centroids, areas, containment-by-bounds, adjacency, overlap, and repeated
  structural patterns;
- ranked cross-frame correspondence alternatives, translations, resize/shape changes,
  recolors, additions/removals, and conservative complete-frame shifts;
- bounded action-correlated controllability candidates after multiple observations;
- deterministic text/SVG renderings and concise measurement summaries.

## Uncertainty boundary

Correspondence is a candidate relation, not an object-identity fact. When two successors fall
within the configured score tolerance, both remain visible and no structural change is
promoted from that ambiguous match. A global shift is returned only when correspondence is
complete, every match is unique and exact-shape, and all displacements agree.

Likewise, action-correlated change never yields an accepted role. One sample remains
`insufficient`; even repeated support produces only `candidate`. Hypothesis promotion belongs
to later typed registries. A whole-word scan of `src/arc3/perception` found zero `player` or
`goal` labels.

## Verification

```text
Ruff check / format (Stage 04 paths): PASS
strict mypy (10 Stage 04 source files): PASS
focused pytest: 30 passed in 4.26s
observation semantic-label scan: 0 matches
```

The tests include exact delta fixtures, metadata presence-versus-null, changing extents,
stable hash/copy behavior, configurable background/connectivity, shape invariance, geometric
relations and repetition, explicit ambiguous matches, additions/removals, structural-change
classification, global shift, multi-sample controllability, bounded/escaped renderers, and
Hypothesis-generated palette/position/rotation/translation permutations.

## Maximum-frame benchmark

The reproducible benchmark processes two deterministic 64×64 frames through delta,
same-color component extraction, and temporal correspondence. Ten iterations measured
0.872938 seconds total (87.2938 ms/iteration) and 501,520 peak Python-traced bytes. Each
iteration measured 128 changed cells and 16 components in each frame. Exact frame hashes are
preserved in the primary evidence.

This satisfies the local acceptance test's conservative five-second single-iteration and
64 MiB peak-allocation ceilings. It is a **synthetic** Windows/Python measurement, not a
Kaggle-runtime receipt. Integrated latency remains subject to Stage 16 profiling.

## Commands

```text
python -m uv run ruff check src/arc3/perception scripts/benchmark_perception.py
python -m uv run ruff format --check src/arc3/perception scripts/benchmark_perception.py
python -m uv run mypy src/arc3/perception scripts/benchmark_perception.py
python -m uv run pytest -q --basetemp %TEMP%\arc3-stage04-final-pytest tests/unit/test_perception_frame.py tests/unit/test_perception_delta.py tests/unit/test_perception_components.py tests/unit/test_perception_tracking.py tests/unit/test_perception_salience_render.py tests/property/test_perception_invariance.py tests/integration/test_perception_pipeline.py
python -m uv run python scripts/benchmark_perception.py --iterations 10
rg -ni "\b(player|goal)\b" src/arc3/perception
```

## Preserved limits

- Component extraction depends on an explicit or measured background candidate and may require
  alternative segmentations downstream.
- Correspondence scores are hand-designed generic priors, not calibrated probabilities.
- Bounding-box containment is not proof of topological enclosure.
- The current renderer is a debugging surface, not a policy input.
- No public-game or hidden-game performance claim follows from perception fixture success.
