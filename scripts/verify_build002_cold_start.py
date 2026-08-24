"""Acquire a pinned wheelhouse and verify the exact Build 002 package offline.

This command never accesses Kaggle, accepts terms, uploads a notebook, or starts a
public game. Network access is used only by the optional acquisition phase and only
for the exact files.pythonhosted.org URLs already sealed in the package manifest.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path
from typing import cast

from arc3.packaging.cold_start import acquire_runtime_wheelhouse, run_linux_cold_start
from arc3.packaging.models import PackagingError
from arc3.packaging.util import canonical_json_bytes, write_bytes_atomic
from arc3.types import JSONValue


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-dir", type=Path, required=True)
    parser.add_argument("--wheelhouse", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument(
        "--acquire",
        action="store_true",
        help="download the exact sealed wheels into a fresh --wheelhouse before verification",
    )
    return parser


def _package_source_commit(package_manifest: Path) -> str:
    try:
        document: object = json.loads(package_manifest.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PackagingError(f"cannot read package manifest: {error}") from error
    if not isinstance(document, dict) or not isinstance(document.get("source"), dict):
        raise PackagingError("package manifest has no source identity")
    source = cast(dict[str, object], document["source"])
    commit = source.get("git_commit")
    if not isinstance(commit, str):
        raise PackagingError("package manifest source commit is missing")
    return commit


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    package_dir = args.package_dir.resolve()
    wheelhouse = args.wheelhouse.resolve()
    receipt_path = args.receipt.resolve()
    manifest = package_dir / "runtime-wheels-linux-cp312.json"
    requirements = package_dir / "runtime-requirements-linux-cp312.txt"
    payload = package_dir / "arc3-first-party.zip"
    package_manifest = package_dir / "package-manifest.json"

    acquisition: dict[str, JSONValue] | None = None
    try:
        if args.acquire:
            acquisition = acquire_runtime_wheelhouse(
                manifest,
                requirements,
                wheelhouse,
            ).to_dict()
        cold_start = run_linux_cold_start(
            manifest,
            requirements,
            wheelhouse,
            payload,
            package_manifest,
            source_commit=_package_source_commit(package_manifest),
        ).to_dict()
    except PackagingError as error:
        print(json.dumps({"error": str(error), "status": "FAILED"}, sort_keys=True))
        return 1

    result: dict[str, JSONValue] = {
        "acquisition": acquisition,
        "cold_start": cold_start,
        "kaggle_accessed": False,
        "public_environment_interactions": 0,
        "schema": "arc3.build-002-cold-start-command.v0.1",
        "status": cold_start["status"],
    }
    write_bytes_atomic(receipt_path, canonical_json_bytes(result))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if cold_start["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
