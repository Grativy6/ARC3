#!/usr/bin/env python3
"""Execute one predeclared Stage 09 development cell from an exact source root."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        )
        + "\n"
    ).encode()


def _object_hash(value: Mapping[str, object], field: str) -> str:
    unsigned = {key: item for key, item in value.items() if key != field}
    return f"sha256:{hashlib.sha256(_canonical_bytes(unsigned)).hexdigest()}"


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("worker specification must be an object")
    return cast(dict[str, Any], value)


def _git(root: Path, argument: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", argument],
        check=True,
        capture_output=True,
        text=True,
        timeout=10.0,
    )
    return result.stdout.strip()


def _status(root: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain=v1", "--untracked-files=all"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10.0,
    )
    return result.stdout.strip()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", required=True, type=Path)
    parser.add_argument("--result", required=True, type=Path)
    args = parser.parse_args(list(argv) if argv is not None else None)
    spec = _load_object(args.spec.resolve())
    if spec.get("schema") != "arc3.build-001.stage-09-worker-spec.v0.2" or spec.get(
        "worker_spec_hash"
    ) != _object_hash(spec, "worker_spec_hash"):
        raise ValueError("Stage 09 worker specification hash/schema is invalid")
    source_root = Path(str(spec["source_root"])).resolve()
    expected_commit = str(spec["source_commit"])
    expected_tree = str(spec["source_tree"])
    if (
        _git(source_root, "HEAD") != expected_commit
        or _git(source_root, "HEAD^{tree}") != expected_tree
        or _status(source_root)
    ):
        raise ValueError("Stage 09 worker source checkout changed")
    sys.path.insert(0, str(source_root / "src"))
    import arc3
    from arc3.evaluation.artifacts import load_json
    from arc3.evaluation.public import _first_party_source_hash
    from arc3.evaluation.public_runner import _receipt_valid, _worker

    module_path = Path(str(arc3.__file__)).resolve()
    try:
        module_path.relative_to(source_root / "src")
    except ValueError as error:
        raise ValueError("Stage 09 worker imported ARC3 outside its declared source") from error
    if _first_party_source_hash() != spec.get("first_party_source_sha256"):
        raise ValueError("Stage 09 worker first-party source bytes changed")
    public_spec = spec.get("public_worker_spec")
    if not isinstance(public_spec, dict):
        raise ValueError("Stage 09 public worker specification is absent")
    result_path = args.result.resolve()
    if result_path.exists():
        raise FileExistsError("Stage 09 raw worker result already exists")
    result_path.parent.mkdir(parents=True, exist_ok=True)
    _worker(cast(dict[str, Any], public_spec), str(result_path))
    if (
        _git(source_root, "HEAD") != expected_commit
        or _git(source_root, "HEAD^{tree}") != expected_tree
        or _status(source_root)
        or _first_party_source_hash() != spec.get("first_party_source_sha256")
    ):
        raise ValueError("Stage 09 worker source checkout changed during execution")
    result = load_json(result_path)
    specification = public_spec.get("specification")
    identity = public_spec.get("identity")
    if not isinstance(specification, dict) or not isinstance(identity, dict):
        raise ValueError("Stage 09 public worker identity is absent")
    if not _receipt_valid(result, specification, identity.get("identity_hash")):
        raise ValueError("Stage 09 raw worker receipt validation failed")
    sys.stdout.buffer.write(
        _canonical_bytes(
            {
                "cell_id": spec["cell_id"],
                "raw_receipt_hash": result["receipt_hash"],
                "status": result["status"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
