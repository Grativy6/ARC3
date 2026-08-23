"""Create or verify environment-free Build 001 Stage 11/12 receipts."""

from __future__ import annotations

import argparse
import json
import subprocess
from collections.abc import Sequence
from pathlib import Path

from arc3.errors import ARC3Error, EvaluationError
from arc3.evaluation.artifacts import sha256_file
from arc3.evaluation.holdout_gate import (
    HoldoutDecision,
    HoldoutEvaluationDeclaration,
    create_holdout_gate_receipt,
    create_nonconsumption_receipt,
    load_bound_holdout_gate,
    load_canonical_receipt,
    validate_nonconsumption_receipt,
    write_canonical_once,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "docs/evaluation/public-game-partitions.v0.1.json"


def _csv_ints(value: str) -> tuple[int, ...]:
    try:
        result = tuple(int(item.strip()) for item in value.split(",") if item.strip())
    except ValueError as error:
        raise argparse.ArgumentTypeError("seeds must be comma-separated integers") from error
    if not result or len(set(result)) != len(result):
        raise argparse.ArgumentTypeError("seeds must be non-empty and unique")
    return result


def _binding_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--gate", type=Path, required=True)
    parser.add_argument("--gate-file-sha256", required=True)
    parser.add_argument("--gate-core-hash", required=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    gate = commands.add_parser("gate", help="evaluate the five frozen Stage 11 criteria")
    gate.add_argument("--stage09", type=Path, required=True)
    gate.add_argument("--stage09-file-sha256", required=True)
    gate.add_argument("--stage09-core-hash", required=True)
    gate.add_argument("--stage10", type=Path, required=True)
    gate.add_argument("--stage10-file-sha256", required=True)
    gate.add_argument("--stage10-core-hash", required=True)
    gate.add_argument("--integrity", type=Path, required=True)
    gate.add_argument("--integrity-file-sha256", required=True)
    gate.add_argument("--integrity-receipt-sha256", required=True)
    gate.add_argument("--development-source-root", type=Path, required=True)
    gate.add_argument("--execution-source-root", type=Path, default=ROOT)
    gate.add_argument("--frozen-commit", required=True)
    gate.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    gate.add_argument("--manifest-sha256", required=True)
    gate.add_argument("--evaluation-id", required=True)
    gate.add_argument("--seeds", type=_csv_ints, default=(7, 11))
    gate.add_argument("--max-actions", type=int, default=80)
    gate.add_argument("--max-resets", type=int, default=8)
    gate.add_argument("--timeout-seconds", type=float, default=120.0)
    gate.add_argument("--generated-at")
    gate.add_argument("--output", type=Path, required=True)
    gate.add_argument(
        "--nonconsumption-output",
        type=Path,
        required=True,
        help="created atomically iff the decision is HOLDOUT_NOT_EARNED",
    )

    verify_gate = commands.add_parser("verify-gate", help="verify exact Stage 11 anchors")
    _binding_arguments(verify_gate)

    nonconsume = commands.add_parser(
        "nonconsume", help="create Stage 12 nonconsumption from a not-earned gate"
    )
    _binding_arguments(nonconsume)
    nonconsume.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    nonconsume.add_argument("--generated-at")
    nonconsume.add_argument("--output", type=Path, required=True)

    verify_nonconsume = commands.add_parser(
        "verify-nonconsumption", help="verify Stage 12 and its bound Stage 11 receipt"
    )
    verify_nonconsume.add_argument("--receipt", type=Path, required=True)
    verify_nonconsume.add_argument("--gate", type=Path, required=True)
    verify_nonconsume.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    return parser


def _gate(args: argparse.Namespace) -> dict[str, object]:
    evaluation = HoldoutEvaluationDeclaration(
        evaluation_id=args.evaluation_id,
        agents=("full",),
        seeds=args.seeds,
        max_actions=args.max_actions,
        max_resets=args.max_resets,
        timeout_seconds=args.timeout_seconds,
    )
    receipt = create_holdout_gate_receipt(
        stage09_path=args.stage09,
        stage09_file_sha256=args.stage09_file_sha256,
        stage09_core_hash=args.stage09_core_hash,
        stage10_path=args.stage10,
        stage10_file_sha256=args.stage10_file_sha256,
        stage10_core_hash=args.stage10_core_hash,
        integrity_path=args.integrity,
        integrity_file_sha256=args.integrity_file_sha256,
        integrity_receipt_sha256=args.integrity_receipt_sha256,
        development_source_root=args.development_source_root,
        execution_source_root=args.execution_source_root,
        expected_execution_commit=args.frozen_commit,
        manifest_path=args.manifest,
        expected_manifest_sha256=args.manifest_sha256,
        evaluation=evaluation,
        generated_at=args.generated_at,
    )
    write_canonical_once(args.output, receipt)
    gate_file_sha256 = sha256_file(args.output.resolve())
    gate_core_hash = str(receipt["artifact_core_hash"])
    nonconsumption: dict[str, object] | None = None
    if receipt["decision"] == HoldoutDecision.NOT_EARNED.value:
        stage12 = create_nonconsumption_receipt(
            gate_path=args.output,
            gate_file_sha256=gate_file_sha256,
            gate_core_hash=gate_core_hash,
            manifest_path=args.manifest,
            generated_at=args.generated_at,
        )
        write_canonical_once(args.nonconsumption_output, stage12)
        nonconsumption = {
            "artifact_core_hash": stage12["artifact_core_hash"],
            "file_sha256": sha256_file(args.nonconsumption_output.resolve()),
            "path": args.nonconsumption_output.resolve().as_posix(),
        }
    return {
        "decision": receipt["decision"],
        "gate": {
            "artifact_core_hash": gate_core_hash,
            "file_sha256": gate_file_sha256,
            "path": args.output.resolve().as_posix(),
        },
        "nonconsumption": nonconsumption,
        "schema": "arc3.build-001.holdout-gate.command.v0.1",
    }


def _verify_gate(args: argparse.Namespace) -> dict[str, object]:
    gate = load_bound_holdout_gate(
        args.gate,
        expected_file_sha256=args.gate_file_sha256,
        expected_core_hash=args.gate_core_hash,
    )
    return {
        "decision": gate.decision.value,
        "schema": "arc3.build-001.holdout-gate.verification.v0.1",
        "verified": True,
    }


def _nonconsume(args: argparse.Namespace) -> dict[str, object]:
    receipt = create_nonconsumption_receipt(
        gate_path=args.gate,
        gate_file_sha256=args.gate_file_sha256,
        gate_core_hash=args.gate_core_hash,
        manifest_path=args.manifest,
        generated_at=args.generated_at,
    )
    write_canonical_once(args.output, receipt)
    return {
        "artifact_core_hash": receipt["artifact_core_hash"],
        "file_sha256": sha256_file(args.output.resolve()),
        "schema": "arc3.build-001.holdout-nonconsumption.command.v0.1",
        "verified": True,
    }


def _verify_nonconsumption(args: argparse.Namespace) -> dict[str, object]:
    receipt = load_canonical_receipt(args.receipt)
    validate_nonconsumption_receipt(
        receipt,
        gate_path=args.gate,
        manifest_path=args.manifest,
    )
    return {
        "schema": "arc3.build-001.holdout-nonconsumption.verification.v0.1",
        "verified": True,
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    try:
        if args.command == "gate":
            result = _gate(args)
        elif args.command == "verify-gate":
            result = _verify_gate(args)
        elif args.command == "nonconsume":
            result = _nonconsume(args)
        elif args.command == "verify-nonconsumption":
            result = _verify_nonconsumption(args)
        else:  # pragma: no cover - argparse enforces the command set
            raise EvaluationError("unsupported holdout-gate command")
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0
    except (ARC3Error, OSError, subprocess.SubprocessError, ValueError) as error:
        print(
            json.dumps(
                {
                    "kind": type(error).__name__,
                    "message": str(error),
                    "schema": "arc3.build-001.holdout-gate.error.v0.1",
                    "status": "FAILED_INFRASTRUCTURE",
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
