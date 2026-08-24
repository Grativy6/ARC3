"""Validate the evaluator-only Build 003 curriculum without opening any real game."""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--limit",
        type=int,
        default=30,
        help="diagnostic prefix of the frozen 30 seeds to validate (default: all)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not 1 <= args.limit <= 30:
        raise SystemExit("--limit must be between 1 and 30")
    repository = Path(__file__).resolve().parents[1]
    if str(repository) not in sys.path:
        sys.path.insert(0, str(repository))

    from evaluation_only.arc3_build003_curriculum.generator import (
        frozen_seeds,
        generate_curriculum,
    )
    from evaluation_only.arc3_build003_curriculum.oracle import validate_curriculum

    started = time.perf_counter()
    receipts: list[dict[str, object]] = []
    total_environment_actions = 0
    for seed in frozen_seeds()[: args.limit]:
        receipt = validate_curriculum(generate_curriculum(seed))
        total_environment_actions += receipt.environment_actions
        value = asdict(receipt)
        value["final_state"] = receipt.final_state.value
        value["plans"] = [
            {
                "family": plan.family.value,
                "action_count": len(plan.actions),
                "explored_states": plan.explored_states,
            }
            for plan in receipt.plans
        ]
        receipts.append(value)
    elapsed = time.perf_counter() - started
    output = {
        "schema": "arc3.build003.curriculum-oracle-batch.v0.1",
        "surface": "synthetic",
        "status": "PASS",
        "seed_count": len(receipts),
        "all_authoritative_win": all(row["final_state"] == "WIN" for row in receipts),
        "all_ten_levels_completed": all(row["levels_completed"] == 10 for row in receipts),
        "environment_actions": total_environment_actions,
        "wall_time_seconds": elapsed,
        "receipts": receipts,
        "claim_boundary": "No public, holdout, or official target game was opened.",
    }
    print(json.dumps(output, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
