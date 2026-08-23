#!/usr/bin/env python3
"""Stdlib-only fail-closed launcher for the Stage 09 supervisor."""

from __future__ import annotations

import argparse
import builtins
import hashlib
import json
import os
import runpy
import subprocess
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]
SUPERVISOR = ROOT / "scripts/measure_development_recovery.py"
WORKER = ROOT / "scripts/_stage09_development_worker.py"
RUNTIME_BINDING = ROOT / "docs/evidence/001-09-runtime-binding.json"
AUTHORITY_SCHEMA = "arc3.build-001.stage-09-supervisor-bootstrap-authority.v0.1"


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        )
        + "\n"
    ).encode()


def _sha256_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _object_hash(value: Mapping[str, object], field: str) -> str:
    return _sha256_bytes(
        _canonical_bytes({key: item for key, item in value.items() if key != field})
    )


def _load_canonical(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict) or _canonical_bytes(value) != raw:
        raise RuntimeError(f"noncanonical bootstrap evidence: {path}")
    return cast(dict[str, Any], value)


def _git(*arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(ROOT), *arguments],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=15.0,
    )
    if result.returncode:
        raise RuntimeError(f"bootstrap git {' '.join(arguments)} failed")
    return result.stdout.strip()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--expected-harness-commit", required=True)
    parser.add_argument("--expected-harness-tree", required=True)
    parser.add_argument("--expected-bootstrap-sha256", required=True)
    parser.add_argument("--expected-supervisor-sha256", required=True)
    parser.add_argument("--expected-worker-sha256", required=True)
    parser.add_argument("--expected-protocol-sha256", required=True)
    parser.add_argument("--expected-runtime-binding-file-sha256", required=True)
    return parser


def _deny_network(event: str, _arguments: tuple[object, ...]) -> None:
    if event.startswith("socket."):
        raise RuntimeError("Stage 09 supervisor bootstrap denies network access")


def main(argv: Sequence[str] | None = None) -> int:
    args, remaining = _parser().parse_known_args(list(argv) if argv is not None else None)
    files = {
        "scripts/_stage09_supervisor_bootstrap.py": args.expected_bootstrap_sha256,
        "scripts/measure_development_recovery.py": args.expected_supervisor_sha256,
        "scripts/_stage09_development_worker.py": args.expected_worker_sha256,
        "src/arc3/evaluation/development_recovery.py": args.expected_protocol_sha256,
    }
    observed = {relative: _sha256_file(ROOT / relative) for relative in files}
    if (
        Path(_git("rev-parse", "--show-toplevel")).resolve() != ROOT
        or _git("rev-parse", "HEAD") != args.expected_harness_commit
        or _git("rev-parse", "HEAD^{tree}") != args.expected_harness_tree
        or _git("branch", "--show-current")
        or _git("status", "--porcelain=v1", "--untracked-files=all")
        or observed != files
    ):
        raise RuntimeError("Stage 09 bootstrap source authority changed")
    runtime_bytes = RUNTIME_BINDING.read_bytes()
    runtime = _load_canonical(RUNTIME_BINDING)
    if (
        _sha256_bytes(runtime_bytes) != args.expected_runtime_binding_file_sha256
        or runtime.get("schema") != "arc3.build-001.stage-09-runtime-environment.v0.2"
        or runtime.get("runtime_binding_hash") != _object_hash(runtime, "runtime_binding_hash")
    ):
        raise RuntimeError("Stage 09 bootstrap runtime binding changed")
    with tempfile.TemporaryDirectory(prefix="arc3-stage09-bootstrap-") as temporary:
        observation_path = Path(temporary) / "runtime-observation.json"
        command = [
            str(Path(sys.executable).resolve()),
            "-I",
            str(WORKER),
            "--bootstrap-runtime-binding",
            str(RUNTIME_BINDING),
            "--bootstrap-result",
            str(observation_path),
            "--bootstrap-harness-root",
            str(ROOT),
        ]
        result = subprocess.run(
            command,
            cwd=ROOT,
            env={key: value for key, value in os.environ.items() if key.upper() != "PYTHONPATH"},
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=180.0,
            check=False,
        )
        observation = _load_canonical(observation_path) if observation_path.is_file() else {}
        if (
            result.returncode != 0
            or result.stdout
            or result.stderr
            or observation.get("schema")
            != "arc3.build-001.stage-09-runtime-environment-observation.v0.2"
            or observation.get("observation_hash") != _object_hash(observation, "observation_hash")
            or observation.get("binding_hash") != runtime.get("runtime_binding_hash")
            or observation.get("passed") is not True
        ):
            raise RuntimeError("Stage 09 bootstrap runtime authority failed before import")
        runtime_observation_hash = observation["observation_hash"]
    authority: dict[str, object] = {
        "schema": AUTHORITY_SCHEMA,
        "files": observed,
        "git_commit": args.expected_harness_commit,
        "git_tree": args.expected_harness_tree,
        "runtime_binding_file_sha256": args.expected_runtime_binding_file_sha256,
        "runtime_binding_hash": runtime["runtime_binding_hash"],
        "runtime_observation_hash": runtime_observation_hash,
        "socket_audit_denial_installed": True,
    }
    authority["authority_hash"] = _object_hash(authority, "authority_hash")
    vars(builtins)["_arc3_stage09_supervisor_bootstrap_authority"] = authority
    sys.addaudithook(_deny_network)
    sys.argv = [
        str(SUPERVISOR),
        "--expected-harness-commit",
        args.expected_harness_commit,
        "--expected-harness-tree",
        args.expected_harness_tree,
        "--expected-bootstrap-sha256",
        args.expected_bootstrap_sha256,
        "--expected-supervisor-sha256",
        args.expected_supervisor_sha256,
        "--expected-worker-sha256",
        args.expected_worker_sha256,
        "--expected-protocol-sha256",
        args.expected_protocol_sha256,
        *remaining,
    ]
    runpy.run_path(str(SUPERVISOR), run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
