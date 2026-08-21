from __future__ import annotations

import dataclasses

import pytest

from arc3.perception.benchmark import benchmark_maximum_frame


@pytest.mark.integration
def test_maximum_frame_pipeline_fits_local_decision_budget() -> None:
    result = benchmark_maximum_frame(iterations=1)

    assert result.changed_cells_per_iteration > 0
    assert result.components_before > 0
    assert result.components_after > 0
    assert result.before_hash != result.after_hash
    assert result.elapsed_seconds < 5.0
    assert result.peak_bytes < 64 * 1024 * 1024
    assert dataclasses.asdict(result)["iterations"] == 1
