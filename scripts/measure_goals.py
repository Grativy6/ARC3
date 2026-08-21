"""Measure the pinned Stage 09 delayed/proxy-goal comparison."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import UTC, datetime

from arc3.goals import compare_goal_policy_to_novelty, held_out_goal_traps
from arc3.trace.canonical import sha256_json


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-seed", type=int, default=20260821)
    parser.add_argument("--episodes", type=int, default=64)
    parser.add_argument("--horizon", type=int, default=5)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    started_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    cases = held_out_goal_traps(
        seed=args.case_seed,
        count=args.episodes,
        horizon=args.horizon,
    )
    comparison = compare_goal_policy_to_novelty(cases)
    case_manifest = [
        {
            "case_id": case.case_id,
            "progress_actions": [action.name.value for action in case.progress_actions],
            "novelty_actions": [action.name.value for action in case.novelty_actions],
        }
        for case in cases
    ]
    result = asdict(comparison)
    result.update(
        {
            "schema": "arc3.goals.comparison.v0.1",
            "case_seed": args.case_seed,
            "case_manifest_sha256": sha256_json(case_manifest),
            "started_at": started_at,
            "completed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        }
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
