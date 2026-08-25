"""Independently audit and seal a completed Build 003 v0.2 held-out matrix."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    repository = (
        args.repository_root.resolve()
        if args.repository_root is not None
        else Path(__file__).resolve().parents[1]
    )
    for source in (repository, repository / "src"):
        if str(source) not in sys.path:
            sys.path.insert(0, str(source))

    from arc3.evaluation.build003_matrix_audit import audit_build003_matrix

    outcome = audit_build003_matrix(
        matrix_root=args.matrix_root,
        output_root=args.output_root,
        repository_root=repository,
    )
    print(
        json.dumps(
            {
                "errors": list(outcome.errors),
                "passed": outcome.passed,
                "receipt_path": str(outcome.receipt_path),
                "report_path": str(outcome.report_path),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0 if outcome.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
