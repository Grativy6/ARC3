"""Measure Stage 06 procedural-laboratory self-tests and pinned baselines."""

from __future__ import annotations

import argparse
import json
import time
from datetime import UTC, datetime

from arc3.lab import LabEvaluator, LabPartition, measure_baseline
from arc3.lab.models import EpisodeRecord
from arc3.trace.canonical import sha256_json


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root-seed", type=int, default=20260821)
    parser.add_argument("--episodes", type=int, default=30)
    parser.add_argument("--max-actions", type=int, default=64)
    return parser.parse_args()


def _record_payload(record: EpisodeRecord) -> dict[str, object]:
    return {
        "case_id": record.case_id,
        "family": record.family.value,
        "seed": record.seed,
        "completed": record.completed,
        "final_state": record.final_state.value,
        "actions": [
            {
                "name": action.name.value,
                "coordinate": (
                    [action.coordinate.x, action.coordinate.y]
                    if action.coordinate is not None
                    else None
                ),
            }
            for action in record.actions
        ],
        "frame_hashes": list(record.frame_hashes),
    }


def main() -> int:
    args = parse_args()
    if args.episodes <= 0 or args.max_actions <= 0:
        raise SystemExit("episodes and max-actions must be positive")
    started_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    self_test_seeds = (0, 1, 2, 17, 113, 808, args.root_seed)
    started = time.perf_counter()
    for seed in self_test_seeds:
        for partition in LabPartition:
            evaluator = LabEvaluator(partition=partition, root_seed=seed, count=args.episodes)
            evaluator.assert_no_observation_leakage()
            evaluator.assert_solvable()
    self_test_seconds = time.perf_counter() - started

    baselines: list[dict[str, object]] = []
    for partition in LabPartition:
        measurement = measure_baseline(
            partition=partition,
            root_seed=args.root_seed,
            episodes=args.episodes,
            max_actions=args.max_actions,
            policy="random",
        )
        record_payload = [_record_payload(record) for record in measurement.records]
        baselines.append(
            {
                "policy": measurement.policy,
                "partition": measurement.partition.value,
                "root_seed": measurement.root_seed,
                "episodes": measurement.episodes,
                "completed": measurement.completed,
                "environment_actions": measurement.environment_actions,
                "resets": measurement.resets,
                "completion_rate": measurement.completion_rate,
                "mean_actions": measurement.mean_actions,
                "action_budget": args.max_actions,
                "scorer": measurement.scorer,
                "records_sha256": sha256_json(record_payload),
            }
        )
    print(
        json.dumps(
            {
                "schema": "arc3.lab.baselines.v0.1",
                "label": "synthetic",
                "started_at": started_at,
                "completed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                "self_test": {
                    "seeds": list(self_test_seeds),
                    "partitions": [partition.value for partition in LabPartition],
                    "episodes": len(self_test_seeds) * len(LabPartition) * args.episodes,
                    "solvability": "PASS",
                    "observation_leakage": "PASS:0-detected-fields",
                    "elapsed_seconds": self_test_seconds,
                },
                "baselines": baselines,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
