"""Pure receipt checks for the Build 003 production mechanical profiler."""

from __future__ import annotations

from typing import Any

from scripts.profile_build003_mechanical import (
    EXPECTED_CYCLES,
    MAX_CYCLE_SECONDS,
    MAX_PEAK_RSS_BYTES,
    _build_comparison,
)


def _run(
    role: str,
    *,
    repetition: int,
    actions: tuple[str, ...] = ("ACTION6", "ACTION6", "ACTION6"),
    cycle: float = 0.2,
    rss: int = 1024,
    route: str | None = None,
) -> dict[str, Any]:
    return {
        "action_names": list(actions),
        "cycle_seconds": [cycle] * EXPECTED_CYCLES,
        "mechanical_receipt_count": EXPECTED_CYCLES if role == "build003" else None,
        "peak_rss_bytes": rss,
        "policy_route": route,
        "repetition": repetition,
        "role": role,
        "synthetic_terminal_observed": True,
        "total_seconds": cycle * EXPECTED_CYCLES,
    }


def test_matched_profile_passes_and_reports_directional_regressions() -> None:
    build003 = [_run("build003", repetition=index, route="mechanical") for index in range(2)]
    build002 = [_run("build002", repetition=index, cycle=0.1, rss=512) for index in range(2)]

    result = _build_comparison(build003, build002)

    assert result["status"] == "PASS"
    assert result["verified"] is True
    assert result["regressions"] == {
        "cycle_maximum_slower_than_build002": True,
        "peak_rss_higher_than_build002": True,
        "total_mean_slower_than_build002": True,
    }
    assert result["claim"] == "SYNTHETIC_PERFORMANCE_ONLY_NO_GAMEPLAY_OR_RHAE_CLAIM"


def test_profile_fails_closed_on_route_determinism_or_budget_loss() -> None:
    build003 = [
        _run(
            "build003",
            repetition=0,
            route="controller",
            cycle=MAX_CYCLE_SECONDS + 0.01,
            rss=MAX_PEAK_RSS_BYTES + 1,
        ),
        _run(
            "build003",
            repetition=1,
            actions=("ACTION6", "ACTION6", "ACTION5"),
            route="controller",
            cycle=MAX_CYCLE_SECONDS + 0.01,
            rss=MAX_PEAK_RSS_BYTES + 1,
        ),
    ]
    build002 = [_run("build002", repetition=index) for index in range(2)]

    result = _build_comparison(build003, build002)

    assert result["status"] == "FAILED_MECHANISM"
    assert result["verified"] is False
    assert result["checks"] == {
        "build002_action_sequence_deterministic": True,
        "build003_action_sequence_deterministic": False,
        "build003_cycle_budget": False,
        "build003_peak_rss_budget": False,
        "build003_production_mechanical_route": False,
        "matched_cycle_count": True,
        "synthetic_terminal_observed": True,
    }
