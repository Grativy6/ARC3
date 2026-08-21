"""Measure the pinned Stage 07 held-out semantic-identification comparison."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime

from arc3.exploration import compare_exploration_baselines, held_out_semantic_cases
from arc3.trace.canonical import sha256_json


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-seed", type=int, default=20260821)
    parser.add_argument("--policy-seed", type=int, default=7107)
    parser.add_argument("--episodes", type=int, default=101)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    started_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    cases = held_out_semantic_cases(seed=args.case_seed, count=args.episodes)
    result = compare_exploration_baselines(cases, seed=args.policy_seed)
    action_counts = {
        "exploration": list(result.exploration_actions),
        "random": list(result.random_actions),
        "cycle": list(result.cycle_actions),
    }
    print(
        json.dumps(
            {
                "schema": "arc3.exploration.comparison.v0.1",
                "label": "synthetic",
                "started_at": started_at,
                "completed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                "case_seed": args.case_seed,
                "policy_seed": args.policy_seed,
                "episodes": result.episodes,
                "status": result.status.value,
                "exploration_median": result.exploration_median,
                "random_median": result.random_median,
                "cycle_median": result.cycle_median,
                "improvement_over_random": result.improvement_over_random,
                "improvement_over_cycle": result.improvement_over_cycle,
                "exploration_total": sum(result.exploration_actions),
                "random_total": sum(result.random_actions),
                "cycle_total": sum(result.cycle_actions),
                "action_counts_sha256": sha256_json(action_counts),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
