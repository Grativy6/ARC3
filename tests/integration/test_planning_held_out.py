from arc3.planning import measure_planning_comparison
from arc3.types import EvaluationSurface


def test_planning_held_out_multistep_comparison_meets_stage_acceptance() -> None:
    comparison = measure_planning_comparison()
    assert comparison.surface is EvaluationSurface.SYNTHETIC
    assert comparison.split == "held-out-symbolic-multistep-v0.1"
    assert comparison.tasks == 24
    assert comparison.planning_completed == comparison.tasks
    assert comparison.planning_actions < comparison.exploration_only_actions
    assert comparison.planning_completion_rate >= comparison.exploration_completion_rate
    assert comparison.recovery_completed == comparison.tasks
    assert comparison.no_recovery_completed == 0
