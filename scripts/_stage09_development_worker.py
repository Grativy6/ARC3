#!/usr/bin/env python3
"""Execute one predeclared Stage 09 development cell from an exact source root."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
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


def _seal(value: Mapping[str, object], field: str) -> dict[str, object]:
    result = dict(value)
    result[field] = _object_hash(result, field)
    return result


def _atomic_create(path: Path, value: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(_canonical_bytes(value))
        stream.flush()
        os.fsync(stream.fileno())


def _expected_command(args: argparse.Namespace) -> list[str]:
    return [
        str(Path(sys.executable).resolve()),
        "-I",
        str(Path(__file__).resolve()),
        "--spec",
        str(args.spec.resolve()),
        "--result",
        str(args.result.resolve()),
        "--launch-receipt",
        str(args.launch_receipt.resolve()),
        "--authorization",
        str(args.authorization.resolve()),
        "--abort-receipt",
        str(args.abort_receipt.resolve()),
        "--launch-token",
        str(args.launch_token),
    ]


def _authorization_valid(args: argparse.Namespace, spec: Mapping[str, object]) -> bool:
    try:
        launch = _load_object(args.launch_receipt.resolve())
        authorization = _load_object(args.authorization.resolve())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return False
    command = _expected_command(args)
    spec_sha = f"sha256:{hashlib.sha256(args.spec.resolve().read_bytes()).hexdigest()}"
    return bool(
        launch.get("schema") == "arc3.build-001.stage-09-process-launch.v0.1"
        and launch.get("launch_receipt_hash") == _object_hash(launch, "launch_receipt_hash")
        and authorization.get("schema") == "arc3.build-001.stage-09-launch-authorization.v0.1"
        and authorization.get("authorization_hash")
        == _object_hash(authorization, "authorization_hash")
        and launch.get("pid") == os.getpid()
        and launch.get("launch_token") == args.launch_token
        and launch.get("authorization_path") == args.authorization.resolve().as_posix()
        and launch.get("command") == command
        and launch.get("worker_spec_hash") == spec.get("worker_spec_hash")
        and launch.get("worker_spec_sha256") == spec_sha
        and authorization.get("pid") == os.getpid()
        and authorization.get("launch_token") == args.launch_token
        and authorization.get("launch_receipt_hash") == launch.get("launch_receipt_hash")
        and authorization.get("process_creation_token") == launch.get("process_creation_token")
        and authorization.get("command") == command
        and authorization.get("worker_spec_hash") == spec.get("worker_spec_hash")
        and authorization.get("worker_spec_sha256") == spec_sha
        and authorization.get("raw_path") == args.result.resolve().as_posix()
        and authorization.get("abort_path") == args.abort_receipt.resolve().as_posix()
    )


def _await_authorization(args: argparse.Namespace, spec: Mapping[str, object]) -> bool:
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        if _authorization_valid(args, spec):
            return True
        time.sleep(0.02)
    abort = _seal(
        {
            "schema": "arc3.build-001.stage-09-worker-abort.v0.1",
            "authorization_path": args.authorization.resolve().as_posix(),
            "cell_id": spec.get("cell_id"),
            "environment_opened": False,
            "launch_receipt_path": args.launch_receipt.resolve().as_posix(),
            "launch_token": args.launch_token,
            "pid": os.getpid(),
            "reason": "launch-authorization-unavailable-or-invalid",
        },
        "worker_abort_hash",
    )
    try:
        _atomic_create(args.abort_receipt.resolve(), abort)
    except FileExistsError:
        if args.abort_receipt.resolve().read_bytes() != _canonical_bytes(abort):
            raise ValueError("existing Stage 09 worker abort receipt changed") from None
    return False


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
    parser.add_argument("--launch-receipt", required=True, type=Path)
    parser.add_argument("--authorization", required=True, type=Path)
    parser.add_argument("--abort-receipt", required=True, type=Path)
    parser.add_argument("--launch-token", required=True)
    args = parser.parse_args(list(argv) if argv is not None else None)
    spec = _load_object(args.spec.resolve())
    if spec.get("schema") != "arc3.build-001.stage-09-worker-spec.v0.2" or spec.get(
        "worker_spec_hash"
    ) != _object_hash(spec, "worker_spec_hash"):
        raise ValueError("Stage 09 worker specification hash/schema is invalid")
    if not _await_authorization(args, spec):
        return 73
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
