"""Run the preregistered Build 003 synthetic four-variant matrix."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from pathlib import Path

MATRIX_VARIANTS = (
    "BUILD002_FROZEN",
    "BLA_CLEF_LEVEL_RESET",
    "BLA_ONLY_PERSISTENT",
    "BLA_CLEF_FULL",
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", choices=("v0.1", "v0.2"), required=True)
    parser.add_argument("--seed-set", choices=("development", "heldout"), required=True)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--worker-storage-root", type=Path)
    parser.add_argument("--build002-source-root", type=Path)
    parser.add_argument(
        "--variants",
        nargs="+",
        choices=MATRIX_VARIANTS,
        default=MATRIX_VARIANTS,
    )
    return parser


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _git(source_root: Path, *arguments: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(source_root), *arguments],
        text=True,
        encoding="utf-8",
        stderr=subprocess.STDOUT,
    ).strip()


def _matrix_status(
    *,
    complete_preregistered_matrix: bool,
    paired_summary: dict[str, object] | None,
    status_counts: dict[str, int],
) -> tuple[str, str]:
    """Separate matrix structure from literal decisions and evidence validity."""

    if not complete_preregistered_matrix:
        return "PARTIAL", "INCOMPLETE_OR_NON_V02_SELECTION"
    if status_counts.get("FAILED_INFRASTRUCTURE", 0) > 0:
        return "FAILED_INFRASTRUCTURE", "ONE_OR_MORE_SEQUENCE_INFRASTRUCTURE_FAILURES"
    if status_counts.get("POLICY_ERROR", 0) > 0:
        return "FAILED_MECHANISM", "ONE_OR_MORE_SEQUENCE_POLICY_FAILURES"
    if paired_summary is None:
        return "FAILED_INFRASTRUCTURE", "COMPLETE_MATRIX_HAS_NO_PAIRED_SUMMARY"
    decisions = paired_summary.get("decisions")
    if not isinstance(decisions, dict):
        return "FAILED_INFRASTRUCTURE", "PAIRED_SUMMARY_HAS_NO_DECISION_RECEIPT"
    if decisions.get("matrix_passed") is True:
        return "PASS", "PREREGISTERED_H1_H2_H3_AND_EVIDENCE_QUALITY_PASSED"
    return "FAILED_MECHANISM", "PREREGISTERED_HYPOTHESIS_OR_EVIDENCE_GATE_FAILED"


def _is_complete_v02_matrix(
    *, protocol_version: str, seed_set: str, limit: int, variants: tuple[str, ...]
) -> bool:
    """Recognize only the exact frozen v0.2 held-out selector set."""

    return (
        protocol_version == "v0.2"
        and seed_set == "heldout"
        and limit == 30
        and variants == MATRIX_VARIANTS
    )


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not 1 <= args.jobs <= 8:
        raise SystemExit("--jobs must be between 1 and 8")
    repository = Path(__file__).resolve().parents[1]
    for source in (repository, repository / "src"):
        if str(source) not in sys.path:
            sys.path.insert(0, str(source))

    from evaluation_only.arc3_build003_curriculum.generator import (
        case_for_seed,
        development_seeds,
        frozen_seeds,
        generate_curriculum,
    )
    from evaluation_only.arc3_build003_curriculum.protocol import protocol_definition
    from evaluation_only.arc3_build003_curriculum.runner import (
        SequenceExecution,
        budgets_for_protocol,
        run_sequence,
    )

    from arc3.evaluation.build003_results import (
        FAMILIES,
        Build003ResultLedger,
        FrozenCase,
    )
    from arc3.evaluation.build003_results import VARIANTS as RESULT_VARIANTS

    if RESULT_VARIANTS != MATRIX_VARIANTS:
        raise RuntimeError("matrix CLI and result-ledger variant identities diverged")

    definition = protocol_definition(args.protocol)
    if "BUILD002_FROZEN" in args.variants:
        if args.build002_source_root is None:
            raise SystemExit("BUILD002_FROZEN requires --build002-source-root")
        baseline_root = args.build002_source_root.resolve()
        try:
            baseline_commit = _git(baseline_root, "rev-parse", "HEAD")
            baseline_tree = _git(baseline_root, "show", "-s", "--format=%T", "HEAD")
            baseline_status = _git(baseline_root, "status", "--porcelain=v1")
        except (OSError, subprocess.CalledProcessError) as error:
            raise SystemExit(f"Build 002 source preflight failed: {error}") from error
        if (
            baseline_commit != definition.baseline.commit
            or baseline_tree != definition.baseline.tree
        ):
            raise SystemExit(
                "Build 002 source identity mismatch: expected "
                f"{definition.baseline.commit}/{definition.baseline.tree}, observed "
                f"{baseline_commit}/{baseline_tree}"
            )
        if baseline_status:
            raise SystemExit("Build 002 source root must be clean")
        args.build002_source_root = baseline_root
    available_seeds = (
        frozen_seeds(definition) if args.seed_set == "heldout" else development_seeds(definition)
    )
    limit = len(available_seeds) if args.limit is None else args.limit
    if not 1 <= limit <= len(available_seeds):
        raise SystemExit(
            f"--limit must be between 1 and {len(available_seeds)} for {args.seed_set}"
        )

    output_root = args.output_root.resolve()
    if output_root.exists() and any(output_root.iterdir()):
        raise SystemExit(f"replacement is forbidden; output root is not empty: {output_root}")
    output_root.mkdir(parents=True, exist_ok=True)
    rows_path = output_root / "rows.jsonl"
    storage_root = (
        args.worker_storage_root.resolve()
        if args.worker_storage_root is not None
        else output_root / "worker-storage"
    )
    if storage_root.exists() and any(storage_root.iterdir()):
        raise SystemExit(f"replacement is forbidden; worker storage is not empty: {storage_root}")
    variant_storage_names = {
        "BUILD002_FROZEN": "b2",
        "BLA_CLEF_LEVEL_RESET": "lr",
        "BLA_ONLY_PERSISTENT": "bo",
        "BLA_CLEF_FULL": "bf",
    }
    selected_seeds = available_seeds[:limit]
    started = time.perf_counter()
    executions: list[SequenceExecution] = []
    futures = {}
    with ThreadPoolExecutor(max_workers=args.jobs, thread_name_prefix="build003") as pool:
        for variant in args.variants:
            for seed in selected_seeds:
                spec = generate_curriculum(seed, definition)
                future = pool.submit(
                    run_sequence,
                    spec,
                    variant,
                    build002_source_root=args.build002_source_root,
                    storage_root=storage_root / variant_storage_names[variant],
                )
                futures[future] = (variant, seed)
        for future in as_completed(futures):
            variant, seed = futures[future]
            try:
                completed_execution = future.result()
            except Exception as error:
                raise RuntimeError(
                    f"unrepresented sequence failure for {variant} seed {seed}: {error}"
                ) from error
            executions.append(completed_execution)

    def execution_key(item: SequenceExecution) -> tuple[str, int]:
        seed = item.receipt["seed"]
        if not isinstance(seed, int) or isinstance(seed, bool):
            raise ValueError("sequence receipt seed is invalid")
        return str(item.receipt["variant"]), seed

    executions.sort(key=execution_key)
    typed_rows = [row for execution in executions for row in execution.rows]
    rows: list[dict[str, object]] = []
    for row in typed_rows:
        value: dict[str, object] = asdict(row)
        value["state"] = row.state.value
        rows.append(value)
    receipts = [execution.receipt for execution in executions]
    rows_path.write_text(
        "".join(_canonical(row) + "\n" for row in rows), encoding="utf-8", newline="\n"
    )
    receipts_path = output_root / "sequence-receipts.jsonl"
    receipts_path.write_text(
        "".join(_canonical(receipt) + "\n" for receipt in receipts),
        encoding="utf-8",
        newline="\n",
    )

    complete_matrix = _is_complete_v02_matrix(
        protocol_version=definition.version.value,
        seed_set=args.seed_set,
        limit=limit,
        variants=tuple(args.variants),
    )
    paired_summary: dict[str, object] | None = None
    if complete_matrix:
        ledger = Build003ResultLedger(
            FrozenCase(case_for_seed(seed, definition).case_id, seed)
            for seed in frozen_seeds(definition)
        )
        ledger.append_many(typed_rows)
        ledger.require_complete()
        paired_summary = ledger.preregistered_summary()

    elapsed = time.perf_counter() - started
    status_counts: dict[str, int] = {}
    wins = 0
    for receipt in receipts:
        status = str(receipt["run_status"])
        status_counts[status] = status_counts.get(status, 0) + 1
        wins += receipt["final_state"] == "WIN"
    matrix_status, matrix_status_reason = _matrix_status(
        complete_preregistered_matrix=complete_matrix,
        paired_summary=paired_summary,
        status_counts=status_counts,
    )
    protocol_path = repository / definition.protocol_path
    manifest_path = repository / definition.manifest_path
    preregistration_path = repository / definition.preregistration_path
    batch = {
        "schema": definition.matrix_receipt_schema,
        "surface": "synthetic",
        "status": matrix_status,
        "status_reason": matrix_status_reason,
        "matrix_structure_status": "COMPLETE_V02" if complete_matrix else "PARTIAL_SELECTION",
        "complete_preregistered_matrix": complete_matrix,
        "protocol_version": definition.version.value,
        "protocol_id": definition.protocol_id,
        "protocol_path": str(protocol_path),
        "protocol_sha256": _sha256(protocol_path),
        "manifest_path": str(manifest_path),
        "manifest_sha256": _sha256(manifest_path),
        "preregistration_path": str(preregistration_path),
        "preregistration_sha256": _sha256(preregistration_path),
        "seed_set": args.seed_set,
        "case_count": limit,
        "variant_count": len(args.variants),
        "sequence_count": len(receipts),
        "row_count": len(rows),
        "expected_selected_row_count": limit * len(args.variants) * len(FAMILIES),
        "expected_full_row_count": 1200,
        "authoritative_win_sequences": wins,
        "run_status_counts": dict(sorted(status_counts.items())),
        "wall_time_seconds": elapsed,
        "rows_path": str(rows_path),
        "rows_sha256": _sha256(rows_path),
        "sequence_receipts_path": str(receipts_path),
        "sequence_receipts_sha256": _sha256(receipts_path),
        "worker_storage_root": str(storage_root),
        "budgets": asdict(budgets_for_protocol(definition)),
        "build002_baseline_identity": asdict(definition.baseline),
        "paired_summary": paired_summary,
        "build002_source_root": (
            str(args.build002_source_root.resolve())
            if args.build002_source_root is not None
            else None
        ),
        "claim_boundary": (
            "Synthetic curriculum evidence only. Matrix PASS, if earned, covers only the "
            "preregistered H1-H3 and evidence-quality decisions; it is not overall Workflow "
            "acceptance or target-game WIN evidence. No public, target holdout, or official "
            "target game was opened."
        ),
    }
    receipt_path = output_root / "matrix-receipt.json"
    receipt_path.write_text(_canonical(batch) + "\n", encoding="utf-8", newline="\n")
    report_path = output_root / "REPORT.md"
    report_path.write_text(
        "\n".join(
            (
                "# Build 003 synthetic curriculum matrix",
                "",
                f"- Status: `{batch['status']}`",
                f"- Status reason: `{batch['status_reason']}`",
                f"- Structure: `{batch['matrix_structure_status']}`",
                f"- Protocol: `{definition.protocol_id}`",
                f"- Seed set: `{args.seed_set}`",
                f"- Rows: `{len(rows)}` / `1200` preregistered",
                f"- Sequences: `{len(receipts)}`",
                f"- Authoritative synthetic WIN sequences: `{wins}`",
                f"- Run status counts: `{_canonical(status_counts)}`",
                f"- Wall time: `{elapsed:.6f}` seconds",
                f"- Rows SHA-256: `{batch['rows_sha256']}`",
                f"- Receipts SHA-256: `{batch['sequence_receipts_sha256']}`",
                f"- Frozen Build 002 commit: `{definition.baseline.commit}`",
                f"- Frozen Build 002 tree: `{definition.baseline.tree}`",
                "",
                "This is synthetic evidence only. No public, holdout, or official target game "
                "was opened, and these results do not establish target-game completion.",
                "",
            )
        ),
        encoding="utf-8",
        newline="\n",
    )
    print(_canonical({**batch, "receipt_path": str(receipt_path), "report_path": str(report_path)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
