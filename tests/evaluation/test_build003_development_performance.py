"""Development-only regressions for the Build 003 v0.2 observation policy."""

from __future__ import annotations

import pytest
from evaluation_only.arc3_build003_curriculum.generator import (
    development_seeds,
    generate_curriculum,
)
from evaluation_only.arc3_build003_curriculum.protocol import PROTOCOL_V0_2
from evaluation_only.arc3_build003_curriculum.runner import run_sequence


@pytest.mark.integration
def test_first_v02_development_seed_wins_within_frozen_budgets() -> None:
    seed = development_seeds(PROTOCOL_V0_2)[0]
    execution = run_sequence(
        generate_curriculum(seed, PROTOCOL_V0_2),
        "BLA_CLEF_FULL",
    )

    assert execution.receipt["seed"] == seed
    assert all(row.completed for row in execution.rows)
    assert execution.receipt["run_status"] == "SUCCESS"
    assert execution.receipt["final_state"] == "WIN"
    assert execution.receipt["levels_completed"] == 10
    assert execution.receipt["environment_actions"] <= 192
    assert execution.receipt["replay_deterministic"] is True
    assert execution.receipt["receipt_links_complete"] is True
