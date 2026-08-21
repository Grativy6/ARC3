"""Build and locally validate the ARC3 offline Kaggle candidate.

This command never authenticates, accepts terms, uploads, or submits.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from arc3.packaging.builder import build_kaggle_candidate
from arc3.packaging.models import PackagingError

REPOSITORY = Path(__file__).resolve().parents[1]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=REPOSITORY / "artifacts" / "kaggle" / "stage17",
        help="ignored output directory for generated package artifacts",
    )
    parser.add_argument(
        "--owner-username",
        default="OWNER_USERNAME",
        help="non-secret Kaggle username for kernel metadata; placeholder by default",
    )
    parser.add_argument(
        "--sandbox-timeout",
        type=float,
        default=120.0,
        help="maximum seconds for the network-blocked local notebook rehearsal",
    )
    parser.add_argument(
        "--allow-dirty-preacceptance",
        action="store_true",
        help=(
            "allow a dirty-tree rehearsal labeled PACKAGING_PREACCEPTANCE; never use this "
            "artifact as the final candidate"
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = build_kaggle_candidate(
            REPOSITORY,
            args.output,
            owner_username=args.owner_username,
            sandbox_timeout_seconds=args.sandbox_timeout,
            allow_dirty_preacceptance=args.allow_dirty_preacceptance,
        )
    except PackagingError as error:
        print(json.dumps({"status": "PACKAGING_FAILED", "error": str(error)}, sort_keys=True))
        return 1
    print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    print(
        "Owner-only boundary (not performed): review the candidate, set the Kaggle username, "
        "accept any required terms, upload/save the notebook, then explicitly submit it."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
