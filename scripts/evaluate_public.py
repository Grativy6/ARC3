"""Guarded command-line entry point for Stage 15 public evaluation."""

from __future__ import annotations

import argparse
import json
import subprocess
from collections.abc import Sequence
from pathlib import Path

from arc3.adapters.arc_agi import ArcAGIAdapter
from arc3.config import ARC3Config
from arc3.errors import ARC3Error
from arc3.evaluation.public import (
    PublicEvaluationConfig,
    PublicPartitionManifest,
    inventory_local_assets,
)
from arc3.evaluation.public_runner import run_public_evaluation, verify_public_evaluation
from arc3.types import EnvironmentMode


def _csv_strings(value: str) -> tuple[str, ...]:
    items = tuple(item.strip().lower() for item in value.split(",") if item.strip())
    if not items or len(set(items)) != len(items):
        raise argparse.ArgumentTypeError("value must contain unique comma-separated names")
    return items


def _csv_ints(value: str) -> tuple[int, ...]:
    try:
        items = tuple(int(item.strip()) for item in value.split(",") if item.strip())
    except ValueError as error:
        raise argparse.ArgumentTypeError("value must contain comma-separated integers") from error
    if not items or len(set(items)) != len(items):
        raise argparse.ArgumentTypeError("value must contain unique comma-separated integers")
    return items


def _head() -> str:
    completed = subprocess.run(
        ("git", "rev-parse", "HEAD"),
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return completed.stdout.strip()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run frozen ARC3 policies on official local public games."
    )
    parser.add_argument(
        "--partition", choices=("smoke", "development", "public-holdout"), default="smoke"
    )
    parser.add_argument(
        "--game-ids",
        type=_csv_strings,
        help="optional ordered subset of the selected smoke/development partition",
    )
    parser.add_argument(
        "--agents",
        type=_csv_strings,
        default=("random", "cycle", "novelty", "trace", "full"),
    )
    parser.add_argument("--seeds", type=_csv_ints, default=(7, 11))
    parser.add_argument("--max-actions", type=int, default=80)
    parser.add_argument("--max-resets", type=int, default=8)
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    parser.add_argument("--hot-path-profile", action="store_true")
    parser.add_argument(
        "--python-allocation-tracing",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="diagnostic Python allocation tracing (enabled by default)",
    )
    parser.add_argument(
        "--automatic-checkpointing",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="FULL-controller automatic checkpoints (enabled by default)",
    )
    parser.add_argument("--frozen-commit")
    parser.add_argument(
        "--manifest", type=Path, default=Path("docs/evaluation/public-game-partitions.v0.1.json")
    )
    parser.add_argument(
        "--environments-dir", type=Path, default=Path("artifacts/stage15/public-environments")
    )
    parser.add_argument(
        "--recordings-dir", type=Path, default=Path("artifacts/stage15/official-recordings")
    )
    parser.add_argument("--output-root", type=Path, default=Path("artifacts/stage15/evaluations"))
    parser.add_argument(
        "--exposure-ledger",
        type=Path,
        default=Path("artifacts/stage15/public-exposure.jsonl"),
    )
    parser.add_argument("--evaluation-id")
    parser.add_argument("--milestone-id", default="build-000-stage15-v0.1")
    parser.add_argument("--acquire-missing", action="store_true")
    parser.add_argument("--allow-public-holdout", action="store_true")
    parser.add_argument("--sealed-development-manifest", type=Path)
    parser.add_argument("--inventory-only", action="store_true")
    parser.add_argument("--revalidate-online-metadata", action="store_true")
    parser.add_argument("--verify", type=Path)
    return parser


def _inventory(args: argparse.Namespace) -> dict[str, object]:
    manifest = PublicPartitionManifest.load(args.manifest)
    local = inventory_local_assets(manifest, args.environments_dir)
    discovery: dict[str, object] | None = None
    if args.revalidate_online_metadata:
        adapter = ArcAGIAdapter(
            ARC3Config.for_mode(EnvironmentMode.ONLINE, seed=0, network_enabled=True),
            environments_dir=args.environments_dir,
            recordings_dir=args.recordings_dir,
        )
        discovery = manifest.compare_discovery(adapter.list_games())
    return {
        "schema": "arc3.public-inventory.v0.1",
        "manifest_sha256": manifest.digest,
        "partition_counts": {
            partition: len(manifest.games(partition))
            for partition in ("smoke", "development", "public-holdout")
        },
        "local_assets": {game_id: local[game_id].to_dict() for game_id in sorted(local)},
        "online_metadata_revalidation": discovery,
        "gameplay_opened": False,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.verify is not None:
            verification = verify_public_evaluation(args.verify)
            print(json.dumps(verification, sort_keys=True, separators=(",", ":")))
            return 0 if verification["verified"] else 1
        if args.inventory_only:
            print(json.dumps(_inventory(args), sort_keys=True, separators=(",", ":")))
            return 0
        frozen_commit = args.frozen_commit
        if frozen_commit is None:
            parser.error("--frozen-commit is required for gameplay evaluation")
        outcome = run_public_evaluation(
            PublicEvaluationConfig(
                partition=args.partition,
                game_ids=args.game_ids,
                hot_path_profile=args.hot_path_profile,
                python_allocation_tracing=args.python_allocation_tracing,
                automatic_checkpointing=args.automatic_checkpointing,
                agents=args.agents,
                seeds=args.seeds,
                frozen_commit=frozen_commit,
                max_actions=args.max_actions,
                max_resets=args.max_resets,
                timeout_seconds=args.timeout_seconds,
                manifest_path=args.manifest,
                environments_dir=args.environments_dir,
                recordings_dir=args.recordings_dir,
                output_root=args.output_root,
                exposure_ledger=args.exposure_ledger,
                evaluation_id=args.evaluation_id,
                acquire_missing=args.acquire_missing,
                allow_public_holdout=args.allow_public_holdout,
                sealed_development_manifest=args.sealed_development_manifest,
                milestone_id=args.milestone_id,
            )
        )
        print(
            json.dumps(
                {
                    "schema": "arc3.public-evaluation.command.v0.1",
                    "evaluation_id": outcome.evaluation_id,
                    "evaluation_path": str(outcome.directory),
                    "status": outcome.status,
                    "claim": outcome.summary["claim"],
                    "surface": outcome.summary["surface"],
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 0 if outcome.status == "PASS" else 1
    except (ARC3Error, OSError, subprocess.SubprocessError, ValueError) as error:
        print(
            json.dumps(
                {
                    "schema": "arc3.public-evaluation.error.v0.1",
                    "status": "FAILED_INFRASTRUCTURE",
                    "kind": type(error).__name__,
                    "message": str(error),
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
