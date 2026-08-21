"""Small deterministic perception benchmark used by Stage 04 verification."""

from __future__ import annotations

import time
import tracemalloc
from dataclasses import dataclass

from arc3.perception.components import Component, ComponentConfig, extract_components
from arc3.perception.delta import measure_delta
from arc3.perception.frame import normalize_grid
from arc3.perception.tracking import track_components


@dataclass(frozen=True, slots=True)
class PerceptionBenchmark:
    iterations: int
    elapsed_seconds: float
    peak_bytes: int
    changed_cells_per_iteration: int
    components_before: int
    components_after: int
    before_hash: str
    after_hash: str


def _maximum_grid(seed: int) -> tuple[tuple[int, ...], ...]:
    """Generate a deterministic 64x64 low-component-count measurement fixture."""

    rows = [[0 for _x in range(64)] for _y in range(64)]
    for index in range(16):
        left = 3 + (index % 4) * 15 + seed
        top = 3 + (index // 4) * 15
        color = 1 + (index % 15)
        for y in range(top, top + 4):
            for x in range(left, left + 4):
                rows[y][x] = color
    return tuple(tuple(row) for row in rows)


def benchmark_maximum_frame(*, iterations: int = 3) -> PerceptionBenchmark:
    """Measure the exact Stage 04 pipeline on maximum-size grids."""

    if iterations < 1:
        raise ValueError("iterations must be positive")
    before = normalize_grid(_maximum_grid(0))
    after = normalize_grid(_maximum_grid(1))
    config = ComponentConfig(background_candidates=(0,))
    tracemalloc.start()
    started = time.perf_counter()
    before_components: tuple[Component, ...] = ()
    after_components: tuple[Component, ...] = ()
    delta = measure_delta(before, after)
    for _index in range(iterations):
        delta = measure_delta(before, after)
        before_components = extract_components(before, config=config)
        after_components = extract_components(after, config=config)
        track_components(before_components, after_components, frame_extent=(64, 64))
    elapsed = time.perf_counter() - started
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return PerceptionBenchmark(
        iterations=iterations,
        elapsed_seconds=elapsed,
        peak_bytes=peak,
        changed_cells_per_iteration=delta.changed_cell_count,
        components_before=len(before_components),
        components_after=len(after_components),
        before_hash=str(before.digest),
        after_hash=str(after.digest),
    )
