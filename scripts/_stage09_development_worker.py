#!/usr/bin/env python3
"""Execute one predeclared Stage 09 development cell from an exact source root."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
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


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


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


def _harness_observation(root: Path, expected: Mapping[str, object]) -> dict[str, object]:
    files = expected.get("files")
    if (
        expected.get("schema") != "arc3.build-001.stage-09-harness-source-binding.v0.1"
        or expected.get("binding_hash") != _object_hash(expected, "binding_hash")
        or not isinstance(files, dict)
        or set(files)
        != {
            "scripts/measure_development_recovery.py",
            "scripts/_stage09_development_worker.py",
            "src/arc3/evaluation/development_recovery.py",
        }
    ):
        raise ValueError("Stage 09 harness source binding is invalid")
    resolved = root.resolve()
    branch = subprocess.run(
        ["git", "-C", str(resolved), "branch", "--show-current"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10.0,
    ).stdout.strip()
    top_level = Path(_git(resolved, "--show-toplevel")).resolve()
    status = _status(resolved)
    observed_files = {
        relative: _sha256_file(resolved / relative) if (resolved / relative).is_file() else None
        for relative in files
    }
    commit = _git(resolved, "HEAD")
    tree = _git(resolved, "HEAD^{tree}")
    predicates = {
        "clean": status == "",
        "commit": commit == expected.get("git_commit"),
        "detached": branch == "",
        "files": observed_files == files,
        "root": top_level == resolved,
        "tree": tree == expected.get("git_tree"),
    }
    payload: dict[str, object] = {
        "schema": "arc3.build-001.stage-09-harness-source-observation.v0.1",
        "binding_hash": expected["binding_hash"],
        "branch": branch,
        "dirty_worktree": bool(status),
        "files": observed_files,
        "git_commit": commit,
        "git_tree": tree,
        "passed": all(predicates.values()),
        "predicates": predicates,
        "root": resolved.as_posix(),
    }
    payload["observation_hash"] = _object_hash(payload, "observation_hash")
    return payload


def _distribution_source_identity(name: str, prefix: str) -> dict[str, object]:
    try:
        distribution = importlib.metadata.distribution(name)
    except importlib.metadata.PackageNotFoundError:
        return {"file_count": 0, "source_sha256": None, "version": None}
    rows: list[tuple[str, int, str]] = []
    for item in sorted(distribution.files or (), key=lambda value: str(value).replace("\\", "/")):
        relative = str(item).replace("\\", "/")
        path = Path(str(distribution.locate_file(item))).resolve()
        if (
            relative.startswith(prefix)
            and path.is_file()
            and "__pycache__" not in path.parts
            and path.suffix != ".pyc"
        ):
            rows.append((relative, path.stat().st_size, _sha256_file(path)))
    return {
        "file_count": len(rows),
        "source_sha256": f"sha256:{hashlib.sha256(_canonical_bytes(rows)).hexdigest()}",
        "version": distribution.version,
    }


def _runtime_observation(root: Path, expected: Mapping[str, object]) -> dict[str, object]:
    if expected.get("schema") != "arc3.build-001.stage-09-runtime-environment.v0.1" or expected.get(
        "runtime_binding_hash"
    ) != _object_hash(expected, "runtime_binding_hash"):
        raise ValueError("Stage 09 runtime environment binding is invalid")
    distributions = {
        "arc-agi": _distribution_source_identity("arc-agi", "arc_agi/"),
        "arcengine": _distribution_source_identity("arcengine", "arcengine/"),
    }
    raw_versions = expected.get("critical_versions")
    if not isinstance(raw_versions, dict):
        raise ValueError("Stage 09 critical runtime version binding is absent")
    critical_versions: dict[str, str | None] = {}
    for name in raw_versions:
        try:
            critical_versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            critical_versions[name] = None
    sdk_probe = subprocess.run(
        [
            str(Path(sys.executable).resolve()),
            "-I",
            "-c",
            (
                "import sys;from pathlib import Path;"
                "r=Path(sys.argv[1]).resolve();sys.path.insert(0,str(r/'src'));"
                "from arc3.adapters.arc_agi import _load_sdk_bindings;"
                "_load_sdk_bindings();print('PASS')"
            ),
            str(root.resolve()),
        ],
        cwd=root.resolve(),
        check=False,
        capture_output=True,
        timeout=30.0,
    )
    try:
        distribution = importlib.metadata.distribution("arc-agi")
        scorecard = Path(str(distribution.locate_file("arc_agi/scorecard.py"))).resolve()
        scorer_hash = _sha256_file(scorecard) if scorecard.is_file() else None
    except importlib.metadata.PackageNotFoundError:
        scorer_hash = None
    actual = {
        "cache_tag": sys.implementation.cache_tag,
        "critical_versions": critical_versions,
        "distributions": distributions,
        "executable": Path(sys.executable).resolve().as_posix(),
        "executable_sha256": _sha256_file(Path(sys.executable).resolve()),
        "implementation": platform.python_implementation(),
        "python_version": platform.python_version(),
        "sdk_import_probe": sdk_probe.returncode == 0 and sdk_probe.stdout.strip() == b"PASS",
        "scorer": {
            "distribution": "arc-agi",
            "module": "arc_agi/scorecard.py",
            "sha256": scorer_hash,
            "source_version": (
                f"arc-agi=={distributions['arc-agi']['version']} local ScorecardManager; "
                f"arcengine=={distributions['arcengine']['version']}"
            ),
        },
        "upstream_lock_sha256": _sha256_file(root / "upstream.lock.json"),
        "uv_lock_sha256": _sha256_file(root / "uv.lock"),
    }
    predicates = {key: actual[key] == expected.get(key) for key in actual}
    payload: dict[str, object] = {
        "schema": "arc3.build-001.stage-09-runtime-environment-observation.v0.1",
        "actual": actual,
        "binding_hash": expected["runtime_binding_hash"],
        "passed": all(predicates.values()),
        "predicates": predicates,
    }
    payload["observation_hash"] = _object_hash(payload, "observation_hash")
    return payload


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
    if spec.get("schema") != "arc3.build-001.stage-09-worker-spec.v0.3" or spec.get(
        "worker_spec_hash"
    ) != _object_hash(spec, "worker_spec_hash"):
        raise ValueError("Stage 09 worker specification hash/schema is invalid")
    if not _await_authorization(args, spec):
        return 73
    harness_root = Path(str(spec["harness_root"])).resolve()
    if Path(__file__).resolve() != harness_root / "scripts/_stage09_development_worker.py":
        raise ValueError("Stage 09 worker did not launch from its declared harness")
    expected_harness = spec.get("harness_source_expected")
    expected_runtime = spec.get("runtime_environment_expected")
    if not isinstance(expected_harness, dict) or not isinstance(expected_runtime, dict):
        raise ValueError("Stage 09 launch source/runtime binding is absent")
    harness_before = _harness_observation(harness_root, expected_harness)
    runtime_before = _runtime_observation(harness_root, expected_runtime)
    if harness_before.get("passed") is not True or runtime_before.get("passed") is not True:
        raise ValueError("Stage 09 launch source/runtime binding changed")
    if harness_before != spec.get("harness_source_before") or runtime_before != spec.get(
        "runtime_environment_before"
    ):
        raise ValueError("Stage 09 launch source/runtime observation changed before import")
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
    harness_after = _harness_observation(harness_root, expected_harness)
    runtime_after = _runtime_observation(harness_root, expected_runtime)
    if (
        _git(source_root, "HEAD") != expected_commit
        or _git(source_root, "HEAD^{tree}") != expected_tree
        or _status(source_root)
        or _first_party_source_hash() != spec.get("first_party_source_sha256")
        or harness_after.get("passed") is not True
        or runtime_after.get("passed") is not True
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
                "harness_binding_hash": expected_harness["binding_hash"],
                "harness_source_before_hash": harness_before["observation_hash"],
                "harness_source_after_hash": harness_after["observation_hash"],
                "raw_receipt_hash": result["receipt_hash"],
                "runtime_binding_hash": expected_runtime["runtime_binding_hash"],
                "runtime_environment_before_hash": runtime_before["observation_hash"],
                "runtime_environment_after_hash": runtime_after["observation_hash"],
                "status": result["status"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
