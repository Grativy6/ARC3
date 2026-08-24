"""Run the preregistered Build 003 synthetic four-variant matrix."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from pathlib import Path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--build002-source-root", type=Path)
    parser.add_argument(
        "--variants",
        nargs="+",
        choices=(
            "BUILD002_FROZEN",
            "BLA_CLEF_LEVEL_RESET",
            "BLA_ONLY_PERSISTENT",
            "BLA_CLEF_FULL",
        ),
        default=(
            "BUILD002_FROZEN",
            "BLA_CLEF_LEVEL_RESET",
            "BLA_ONLY_PERSISTENT",
            "BLA_CLEF_FULL",
        ),
    )
    return parser


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not 1 <= args.limit <= 30:
        raise SystemExit("--limit must be between 1 and 30")
    if not 1 <= args.jobs <= 8:
        raise SystemExit("--jobs must be between 1 and 8")
    repository = Path(__file__).resolve().parents[1]
    for source in (repository, repository / "src"):
        if str(source) not in sys.path:
            sys.path.insert(0, str(source))

    from evaluation_only.arc3_build003_curriculum.generator import (
        case_for_seed,
        frozen_seeds,
        generate_curriculum,
    )
    from evaluation_only.arc3_build003_curriculum.runner import (
        SequenceExecution,
        run_sequence,
    )

    from arc3.evaluation.build003_results import (
        FAMILIES,
        VARIANTS,
        Build003ResultLedger,
        FrozenCase,
    )

    output_root = args.output_root.resolve()
    rows_path = output_root / "rows.jsonl"
    if rows_path.exists():
        raise SystemExit(f"replacement is forbidden; output already exists: {rows_path}")
    output_root.mkdir(parents=True, exist_ok=True)
    storage_key = hashlib.sha256(str(output_root).encode("utf-8")).hexdigest()[:8]
    storage_root = repository / "artifacts" / "b003w" / storage_key
    variant_storage_names = {
        "BUILD002_FROZEN": "b2",
        "BLA_CLEF_LEVEL_RESET": "lr",
        "BLA_ONLY_PERSISTENT": "bo",
        "BLA_CLEF_FULL": "bf",
    }
    selected_seeds = frozen_seeds()[: args.limit]
    started = time.perf_counter()
    executions: list[SequenceExecution] = []
    futures = {}
    with ThreadPoolExecutor(max_workers=args.jobs, thread_name_prefix="build003") as pool:
        for variant in args.variants:
            for seed in selected_seeds:
                spec = generate_curriculum(seed)
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

    complete_matrix = args.limit == 30 and tuple(args.variants) == VARIANTS
    paired_summary: dict[str, object] | None = None
    if complete_matrix:
        ledger = Build003ResultLedger(
            FrozenCase(case_for_seed(seed).case_id, seed) for seed in frozen_seeds()
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
    batch = {
        "schema": "arc3.build003.curriculum-matrix-receipt.v0.1",
        "surface": "synthetic",
        "status": "PASS" if complete_matrix else "PARTIAL",
        "complete_preregistered_matrix": complete_matrix,
        "case_count": args.limit,
        "variant_count": len(args.variants),
        "sequence_count": len(receipts),
        "row_count": len(rows),
        "expected_selected_row_count": args.limit * len(args.variants) * len(FAMILIES),
        "expected_full_row_count": 1200,
        "authoritative_win_sequences": wins,
        "run_status_counts": dict(sorted(status_counts.items())),
        "wall_time_seconds": elapsed,
        "rows_path": str(rows_path),
        "rows_sha256": _sha256(rows_path),
        "sequence_receipts_path": str(receipts_path),
        "sequence_receipts_sha256": _sha256(receipts_path),
        "worker_storage_root": str(storage_root),
        "paired_summary": paired_summary,
        "build002_source_root": (
            str(args.build002_source_root.resolve())
            if args.build002_source_root is not None
            else None
        ),
        "claim_boundary": (
            "Synthetic curriculum evidence only. No public, holdout, or official target "
            "game was opened, and this is not target-game WIN evidence."
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
                f"- Rows: `{len(rows)}` / `1200` preregistered",
                f"- Sequences: `{len(receipts)}`",
                f"- Authoritative synthetic WIN sequences: `{wins}`",
                f"- Run status counts: `{_canonical(status_counts)}`",
                f"- Wall time: `{elapsed:.6f}` seconds",
                f"- Rows SHA-256: `{batch['rows_sha256']}`",
                f"- Receipts SHA-256: `{batch['sequence_receipts_sha256']}`",
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
