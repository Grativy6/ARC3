"""Pinned performance-regression checks established after a stable smoke run."""

from __future__ import annotations

import json
from importlib.resources import files
from typing import Any


def load_performance_thresholds() -> dict[str, Any]:
    """Load the packaged, reviewable Stage 13 synthetic threshold declaration."""

    resource = files("arc3.evaluation").joinpath("performance-thresholds.v0.1.json")
    value = json.loads(resource.read_text(encoding="utf-8"))
    if (
        not isinstance(value, dict)
        or value.get("schema") != "arc3.evaluation.performance-thresholds.v0.1"
    ):
        raise ValueError("invalid packaged performance threshold declaration")
    return value


def evaluate_performance_thresholds(
    results: list[dict[str, Any]],
    *,
    declaration: dict[str, object] | None = None,
) -> dict[str, object]:
    """Evaluate only the exact benchmark declaration that established the thresholds."""

    threshold_declaration = load_performance_thresholds()
    basis = threshold_declaration["basis"]
    thresholds = threshold_declaration["thresholds"]
    scope_note = str(threshold_declaration["scope_note"])
    declared_agents = declaration.get("agents") if declaration is not None else None
    declared_seeds = declaration.get("seeds") if declaration is not None else None
    comparable = declaration is not None and (
        declaration.get("partition") == basis["partition"]
        and declaration.get("surface") == basis["surface"]
        and declaration.get("network_mode") == basis["network_mode"]
        and isinstance(declared_agents, list)
        and set(declared_agents) == set(basis["agents"])
        and isinstance(declared_seeds, list)
        and declared_seeds == list(basis["seeds"])
        and declaration.get("max_actions") == basis["max_actions"]
        and declaration.get("max_resets") == basis["max_resets"]
        and declaration.get("timeout_seconds") == basis["timeout_seconds"]
    )
    if not comparable:
        return {
            "schema": "arc3.evaluation.performance-regression.v0.1",
            "status": "NOT_APPLICABLE",
            "threshold_schema": threshold_declaration["schema"],
            "basis": basis,
            "scope_note": scope_note,
            "reason": "evaluation declaration does not match the pinned threshold basis",
            "checks": [],
        }
    successful = [result for result in results if result.get("status") == "success"]
    successful_policies = {str(result["agent"]) for result in successful}
    checks: list[dict[str, object]] = []

    expected_keys = {
        (str(agent), int(seed)) for agent in basis["agents"] for seed in basis["seeds"]
    }
    observed_keys = [(str(result.get("agent")), result.get("seed")) for result in results]
    exact_receipts = (
        len(observed_keys) == len(set(observed_keys)) and set(observed_keys) == expected_keys
    )
    checks.append(
        {
            "name": "exact_declared_run_receipts",
            "observed": len(observed_keys),
            "operator": "==",
            "threshold": len(expected_keys),
            "passed": exact_receipts,
        }
    )
    checks.append(
        {
            "name": "successful_run_count",
            "observed": len(successful),
            "operator": "==",
            "threshold": len(expected_keys),
            "passed": len(successful) == len(expected_keys),
        }
    )

    def check(name: str, observed: float, limit: float, operator: str = "<=") -> None:
        passed = observed <= limit if operator == "<=" else observed >= limit
        checks.append(
            {
                "name": name,
                "observed": observed,
                "operator": operator,
                "threshold": limit,
                "passed": passed,
            }
        )

    check(
        "successful_policy_count",
        float(len(successful_policies)),
        float(thresholds["minimum_successful_policy_count"]),
        ">=",
    )
    for result in successful:
        run_id = str(result["run_id"])
        metrics = result["metrics"]
        check(
            f"{run_id}:invalid_action_rate",
            float(metrics["invalid_action_rate"]),
            float(thresholds["maximum_invalid_action_rate"]),
        )
        check(
            f"{run_id}:peak_python_bytes",
            float(metrics["peak_ram_bytes"]),
            float(thresholds["maximum_peak_python_bytes"]),
        )
        p95 = metrics["decision_latency_seconds"]["p95"]
        if p95 is None:
            checks.append(
                {
                    "name": f"{run_id}:decision_p95_seconds",
                    "observed": None,
                    "operator": "<=",
                    "threshold": thresholds["maximum_decision_p95_seconds"],
                    "passed": False,
                }
            )
        else:
            check(
                f"{run_id}:decision_p95_seconds",
                float(p95),
                float(thresholds["maximum_decision_p95_seconds"]),
            )
        check(
            f"{run_id}:wall_clock_seconds",
            float(metrics["total_wall_clock_seconds"]),
            float(thresholds["maximum_run_wall_clock_seconds"]),
        )
    invalid_failures = [
        result
        for result in results
        if result.get("status") != "success"
        and isinstance(result.get("failure"), dict)
        and result["failure"].get("kind") in {"InvalidActionError", "invalid_action"}
    ]
    checks.append(
        {
            "name": "invalid_action_failure_count",
            "observed": float(len(invalid_failures)),
            "operator": "<=",
            "threshold": 0.0,
            "passed": not invalid_failures,
        }
    )
    return {
        "schema": "arc3.evaluation.performance-regression.v0.1",
        "status": "PASS" if checks and all(bool(item["passed"]) for item in checks) else "FAIL",
        "threshold_schema": threshold_declaration["schema"],
        "basis": basis,
        "scope_note": scope_note,
        "checks": checks,
    }


__all__ = ["evaluate_performance_thresholds", "load_performance_thresholds"]
