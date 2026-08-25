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
    parser.add_argument("--protocol", choices=("v0.1", "v0.2"), required=True)
    parser.add_argument("--seed-set", choices=("development", "heldout"), required=True)
    parser.add_argument(
        "--limit",
        type=int,
        help="diagnostic prefix of the explicitly selected seed set (default: all)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    repository = Path(__file__).resolve().parents[1]
    if str(repository) not in sys.path:
        sys.path.insert(0, str(repository))

    from evaluation_only.arc3_build003_curriculum.generator import (
        development_seeds,
        frozen_seeds,
        generate_curriculum,
    )
    from evaluation_only.arc3_build003_curriculum.oracle import validate_curriculum
    from evaluation_only.arc3_build003_curriculum.protocol import protocol_definition

    definition = protocol_definition(args.protocol)
    available_seeds = (
        frozen_seeds(definition) if args.seed_set == "heldout" else development_seeds(definition)
    )
    limit = len(available_seeds) if args.limit is None else args.limit
    if not 1 <= limit <= len(available_seeds):
        raise SystemExit(
            f"--limit must be between 1 and {len(available_seeds)} for {args.seed_set}"
        )

    started = time.perf_counter()
    receipts: list[dict[str, object]] = []
    total_environment_actions = 0
    for seed in available_seeds[:limit]:
        receipt = validate_curriculum(generate_curriculum(seed, definition))
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
        "schema": f"arc3.build003.curriculum-oracle-batch.{definition.version.value}",
        "surface": "synthetic",
        "status": "PASS",
        "protocol_version": definition.version.value,
        "protocol_id": definition.protocol_id,
        "seed_set": args.seed_set,
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
