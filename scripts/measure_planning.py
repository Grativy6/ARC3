"""Measure the pinned Stage 10 planning and recovery comparisons."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import UTC, datetime

from arc3.planning import measure_planning_comparison


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=20260821)
    parser.add_argument("--tasks", type=int, default=24)
    parser.add_argument("--action-budget", type=int, default=24)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    started_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    comparison = measure_planning_comparison(
        seed=args.seed,
        tasks=args.tasks,
        action_budget_per_task=args.action_budget,
    )
    mechanism_observed = (
        comparison.planning_completed > comparison.exploration_only_completed
        and comparison.recovery_completed > comparison.no_recovery_completed
    )
    result = asdict(comparison)
    result.update(
        {
            "schema": "arc3.planning.comparison.v0.1",
            "status": ("MECHANISM_OBSERVED" if mechanism_observed else "MECHANISM_NOT_OBSERVED"),
            "started_at": started_at,
            "completed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        }
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
