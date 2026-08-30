"""Unit tests for Stage 13 policy identities and statistical summaries."""

from __future__ import annotations

import pytest

from arc3.adapters.synthetic import SYNTHETIC_GAME_ID, SyntheticAdapter
from arc3.evaluation.baselines import (
    BASELINES,
    NoveltyOnlyPolicy,
    TraceLocalStatisticsPolicy,
    baseline_descriptor,
)
from arc3.evaluation.models import EvaluationConfig
from arc3.evaluation.reports import build_summary
from arc3.evaluation.thresholds import (
    evaluate_performance_thresholds,
    load_performance_thresholds,
)


def test_b0_through_b4_are_pinned_without_substituting_full() -> None:
    assert [baseline.baseline_id for baseline in BASELINES] == ["B0", "B1", "B2", "B3", "B4"]
    assert all(baseline.status == "supported" for baseline in BASELINES)
    assert baseline_descriptor("full").limitation is None
    assert baseline_descriptor("mechanical").baseline_id == "B5"


@pytest.mark.parametrize("policy", [NoveltyOnlyPolicy(), TraceLocalStatisticsPolicy()])
def test_intermediate_baselines_emit_only_advertised_actions(policy: object) -> None:
    session = SyntheticAdapter(seed=7).open(SYNTHETIC_GAME_ID, seed=7)
    for _ in range(8):
        observation = session.observation
        action = policy.select(observation)  # type: ignore[attr-defined]
        assert action.name in observation.available_actions
        session.step(action)


@pytest.mark.parametrize(
    "kwargs,match",
    [
        ({"partition": "public-holdout"}, "synthetic smoke"),
        ({"agents": ()}, "agents"),
        ({"seeds": ()}, "seeds"),
        ({"max_actions": 0}, "max_actions"),
        ({"max_actions": 1.5}, "max_actions"),
        ({"max_resets": True}, "max_resets"),
        ({"timeout_seconds": 0.0}, "timeout_seconds"),
        ({"timeout_seconds": float("inf")}, "timeout_seconds"),
        ({"evaluation_id": "bad/path"}, "evaluation_id"),
    ],
)
def test_evaluation_config_rejects_ambiguous_or_unbounded_values(
    kwargs: dict[str, object], match: str
) -> None:
    arguments: dict[str, object] = {
        "partition": "smoke",
        "agents": ("random",),
        "seeds": (7,),
    }
    arguments.update(kwargs)
    with pytest.raises(ValueError, match=match):
        EvaluationConfig(**arguments)  # type: ignore[arg-type]


def test_summary_retains_failure_rows_and_requires_two_successful_policies() -> None:
    def result(agent: str, status: str) -> dict[str, object]:
        descriptor = baseline_descriptor(agent)
        return {
            "agent": agent,
            "baseline_id": descriptor.baseline_id,
            "status": status,
            "score": {"score": 1.0, "levels_completed": 1, "completed": True},
            "metrics": {"environment_actions": 3, "total_wall_clock_seconds": 0.1},
            "failure": None if status == "success" else {"kind": "injected"},
        }

    summary = build_summary(
        "unit",
        [result("random", "success"), result("cycle", "success"), result("full", "unsupported")],
    )
    assert summary["status"] == "PARTIAL"
    assert summary["failure_count"] == 1
    full = next(row for row in summary["policies"] if row["baseline_id"] == "B4")
    assert full["failed_or_unsupported_runs"] == 1
    assert full["failure_kinds"] == ["injected"]


def test_packaged_performance_thresholds_pass_stable_shape_and_detect_regression() -> None:
    declaration = load_performance_thresholds()
    assert declaration["basis"]["seeds"] == [7, 11]
    results = [
        {
            "run_id": f"{agent}-seed-{seed}",
            "agent": agent,
            "seed": seed,
            "status": "success",
            "metrics": {
                "invalid_action_rate": 0.0,
                "peak_ram_bytes": 1000,
                "decision_latency_seconds": {"p95": 0.001},
                "total_wall_clock_seconds": 0.01,
            },
        }
        for agent in ("random", "cycle", "novelty", "trace")
        for seed in (7, 11)
    ]
    benchmark = {
        "partition": "smoke",
        "surface": "synthetic",
        "network_mode": "offline",
        "agents": ["random", "cycle", "novelty", "trace"],
        "seeds": [7, 11],
        "max_actions": 16,
        "max_resets": 8,
        "timeout_seconds": 30.0,
    }
    assert evaluate_performance_thresholds(results, declaration=benchmark)["status"] == "PASS"
    assert evaluate_performance_thresholds(results[:-1], declaration=benchmark)["status"] == "FAIL"
    results[0]["metrics"]["invalid_action_rate"] = 0.1
    assert evaluate_performance_thresholds(results, declaration=benchmark)["status"] == "FAIL"
    assert evaluate_performance_thresholds(results)["status"] == "NOT_APPLICABLE"


def test_novelty_only_prioritizes_observed_novelty_over_least_tried_action() -> None:
    session = SyntheticAdapter(seed=3).open(SYNTHETIC_GAME_ID, seed=3)
    policy = NoveltyOnlyPolicy()
    first = policy.select(session.observation)
    changed = session.step(first)

    assert policy.select(changed) == first
