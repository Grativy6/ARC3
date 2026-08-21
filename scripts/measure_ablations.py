"""Run the predeclared Stage 14 paired synthetic ablation matrix."""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from arc3.ablations import (
    AblationId,
    AblationProtocol,
    load_protocol_manifest,
    measure_ablations,
)
from arc3.trace.canonical import sha256_json
from arc3.types import JSONValue

ROOT = Path(__file__).resolve().parents[1]


def _git(*arguments: str) -> str:
    completed = subprocess.run(
        ("git", *arguments),
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return completed.stdout.strip() if completed.returncode == 0 else "unavailable"


def _package_version(name: str) -> str:
    try:
        return version(name)
    except PackageNotFoundError:
        return "not-installed"


def _parse_seeds(value: str) -> tuple[int, ...]:
    try:
        seeds = tuple(int(item.strip()) for item in value.split(",") if item.strip())
    except ValueError as error:
        raise argparse.ArgumentTypeError("seeds must be comma-separated integers") from error
    if not seeds:
        raise argparse.ArgumentTypeError("at least one navigation seed is required")
    return seeds


def _parse_ablations(value: str) -> tuple[AblationId, ...]:
    try:
        selected = tuple(AblationId(item.strip().upper()) for item in value.split(","))
    except ValueError as error:
        raise argparse.ArgumentTypeError("ablations must be identifiers A1 through A10") from error
    if not selected:
        raise argparse.ArgumentTypeError("at least one ablation is required")
    return selected


def _parser() -> argparse.ArgumentParser:
    frozen, frozen_ablations, _manifest_hash = load_protocol_manifest()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "artifacts" / "stage14" / "paired-ablation-final.json",
    )
    parser.add_argument(
        "--work-root",
        type=Path,
        default=ROOT / "artifacts" / "stage14" / "paired-ablation-final-data",
    )
    parser.add_argument(
        "--navigation-seeds",
        type=_parse_seeds,
        default=frozen.navigation_seeds,
    )
    parser.add_argument(
        "--lab-cases-per-partition", type=int, default=frozen.lab_cases_per_partition
    )
    parser.add_argument("--lab-root-seed", type=int, default=frozen.lab_root_seed)
    parser.add_argument("--action-budget", type=int, default=frozen.action_budget)
    parser.add_argument("--reset-budget", type=int, default=frozen.reset_budget)
    parser.add_argument("--grid-size", type=int, default=frozen.grid_size)
    parser.add_argument("--synthetic-max-steps", type=int, default=frozen.synthetic_max_steps)
    parser.add_argument("--wall-clock-seconds", type=float, default=frozen.wall_clock_seconds)
    parser.add_argument("--max-search-nodes", type=int, default=frozen.max_search_nodes)
    parser.add_argument(
        "--ablations",
        type=_parse_ablations,
        default=frozen_ablations,
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    invocation_arguments = list(sys.argv[1:] if argv is None else argv)
    args = _parser().parse_args(argv)
    if args.work_root.exists() and any(args.work_root.iterdir()):
        raise SystemExit(f"work root already contains data: {args.work_root}")
    protocol = AblationProtocol(
        navigation_seeds=args.navigation_seeds,
        lab_root_seed=args.lab_root_seed,
        lab_cases_per_partition=args.lab_cases_per_partition,
        action_budget=args.action_budget,
        reset_budget=args.reset_budget,
        grid_size=args.grid_size,
        synthetic_max_steps=args.synthetic_max_steps,
        wall_clock_seconds=args.wall_clock_seconds,
        max_search_nodes=args.max_search_nodes,
    )
    started_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    commit = _git("rev-parse", "HEAD")
    dirty = bool(_git("status", "--porcelain=v1"))
    report = measure_ablations(
        args.work_root,
        protocol=protocol,
        selected_ablations=args.ablations,
        git_commit=commit,
        repository_dirty=dirty,
        runtime_identity={
            "cpu": platform.processor() or platform.machine() or "unknown",
            "gpu": "not-used",
            "logical_cpu_count": os.cpu_count(),
            "platform": platform.platform(),
            "python": platform.python_version(),
            "packages": {
                "arc-agi": _package_version("arc-agi"),
                "arcengine": _package_version("arcengine"),
                "numpy": _package_version("numpy"),
                "pydantic": _package_version("pydantic"),
            },
        },
    )
    report["started_at"] = started_at
    report["completed_at"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    invocation_payload: list[JSONValue] = [argument for argument in invocation_arguments]
    report["invocation"] = {
        "arguments": invocation_payload,
        "executable": sys.executable,
        "script": Path(__file__).relative_to(ROOT).as_posix(),
    }
    report["local_work_root"] = str(args.work_root.resolve())
    report["artifact_core_hash"] = sha256_json(report)
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8", newline="\n")
    sys.stdout.write(rendered)
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
