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
AUTHORITY_SCHEMA = "arc3.build-001.stage-09-supervisor-bootstrap-authority.v0.2"
_SOURCE_PREFIXES = ("agent/", "scripts/", "src/arc3/")
_GIT_OBJECT_FORMAT = "sha1"
_CACHE_DIRECTORIES = frozenset(
    {".hypothesis", ".mypy_cache", ".pytest_cache", ".ruff_cache", "__pycache__"}
)


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


def _git_environment() -> dict[str, str]:
    environment = {
        key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")
    }
    environment["GIT_NO_REPLACE_OBJECTS"] = "1"
    return environment


def _git_bytes(root: Path, *arguments: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(root.resolve()), *arguments],
        check=False,
        capture_output=True,
        env=_git_environment(),
        timeout=15.0,
    )
    if result.returncode:
        raise RuntimeError(f"bootstrap git {' '.join(arguments)} failed")
    return result.stdout


def _git(*arguments: str) -> str:
    try:
        return _git_bytes(ROOT, *arguments).decode("utf-8", errors="strict").strip()
    except UnicodeDecodeError as error:
        raise RuntimeError(f"bootstrap git {' '.join(arguments)} returned non-UTF-8") from error


def _git_blob_oid(raw: bytes) -> str:
    header = f"blob {len(raw)}\0".encode("ascii")
    return hashlib.sha1(header + raw, usedforsecurity=False).hexdigest()


def _canonical_git_blobs(root: Path, object_ids: Sequence[str]) -> dict[str, bytes]:
    unique_ids = tuple(dict.fromkeys(object_ids))
    if not unique_ids:
        return {}
    result = subprocess.run(
        ["git", "-C", str(root.resolve()), "cat-file", "--batch"],
        check=False,
        capture_output=True,
        env=_git_environment(),
        input="".join(f"{object_id}\n" for object_id in unique_ids).encode("ascii"),
        timeout=30.0,
    )
    if result.returncode or result.stderr:
        raise RuntimeError("Stage 09 bootstrap cannot read canonical Git blobs")
    output = result.stdout
    cursor = 0
    blobs: dict[str, bytes] = {}
    for expected_id in unique_ids:
        header_end = output.find(b"\n", cursor)
        if header_end < 0:
            raise RuntimeError("Stage 09 bootstrap Git blob batch is truncated")
        fields = output[cursor:header_end].split()
        if len(fields) != 3 or fields[0] != expected_id.encode("ascii") or fields[1] != b"blob":
            raise RuntimeError("Stage 09 bootstrap Git blob batch identity changed")
        try:
            size = int(fields[2].decode("ascii", errors="strict"))
        except (UnicodeDecodeError, ValueError) as error:
            raise RuntimeError("Stage 09 bootstrap Git blob size is malformed") from error
        body_start = header_end + 1
        body_end = body_start + size
        if size < 0 or body_end >= len(output) or output[body_end : body_end + 1] != b"\n":
            raise RuntimeError("Stage 09 bootstrap Git blob body is truncated")
        blobs[expected_id] = output[body_start:body_end]
        cursor = body_end + 1
    if cursor != len(output):
        raise RuntimeError("Stage 09 bootstrap Git blob batch has trailing bytes")
    return blobs


def _tree_projection(root: Path, commit: str) -> dict[str, dict[str, str]]:
    try:
        object_format = (
            _git_bytes(root, "rev-parse", "--show-object-format")
            .decode("ascii", errors="strict")
            .strip()
        )
    except UnicodeDecodeError as error:
        raise RuntimeError("Stage 09 bootstrap Git object format is non-ASCII") from error
    if object_format != _GIT_OBJECT_FORMAT:
        raise RuntimeError("Stage 09 bootstrap Git object format changed")
    projection: dict[str, dict[str, str]] = {}
    for raw_entry in _git_bytes(root, "ls-tree", "-r", "-z", commit).split(b"\0"):
        if not raw_entry:
            continue
        metadata, separator, raw_path = raw_entry.partition(b"\t")
        fields = metadata.split()
        if not separator or len(fields) != 3:
            raise RuntimeError("Stage 09 bootstrap Git tree entry is malformed")
        try:
            mode, object_type, object_id = (field.decode("ascii") for field in fields)
            relative = raw_path.decode("utf-8", errors="strict")
        except UnicodeDecodeError as error:
            raise RuntimeError("Stage 09 bootstrap Git tree path is non-portable") from error
        if not relative.startswith(_SOURCE_PREFIXES):
            continue
        if (
            object_type != "blob"
            or mode not in {"100644", "100755"}
            or len(object_id) != 40
            or any(character not in "0123456789abcdef" for character in object_id)
            or relative.startswith("/")
            or "\\" in relative
            or any(part in {"", ".", ".."} for part in relative.split("/"))
            or relative in projection
        ):
            raise RuntimeError("Stage 09 bootstrap tree contains a non-regular source")
        projection[relative] = {"git_blob": object_id, "mode": mode}
    if not projection or any(
        relative not in projection
        for relative in (
            "scripts/_stage09_supervisor_bootstrap.py",
            "scripts/measure_development_recovery.py",
            "scripts/_stage09_development_worker.py",
            "src/arc3/evaluation/development_recovery.py",
        )
    ):
        raise RuntimeError("Stage 09 bootstrap tree projection is incomplete")
    return dict(sorted(projection.items()))


def _path_has_symlink_component(root: Path, relative: str) -> bool:
    current = root.resolve()
    for part in relative.split("/"):
        current /= part
        if current.is_symlink():
            return True
    return False


def _live_non_cache_paths(root: Path) -> tuple[str, ...]:
    repository = root.resolve()
    found: set[str] = set()
    for relative_root in ("agent", "scripts", "src/arc3"):
        base = repository / relative_root
        if base.is_symlink():
            found.add(relative_root)
            continue
        if not base.is_dir():
            continue
        for directory, raw_directories, filenames in os.walk(base, followlinks=False):
            directory_path = Path(directory)
            retained: list[str] = []
            for name in sorted(raw_directories):
                candidate = directory_path / name
                if candidate.is_symlink():
                    found.add(candidate.relative_to(repository).as_posix())
                elif name not in _CACHE_DIRECTORIES:
                    retained.append(name)
            raw_directories[:] = retained
            for name in sorted(filenames):
                found.add((directory_path / name).relative_to(repository).as_posix())
    return tuple(sorted(found))


def _index_non_h_paths(root: Path, expected_paths: Sequence[str]) -> tuple[str, ...]:
    entries: dict[str, str] = {}
    anomalies: set[str] = set()
    raw = _git_bytes(root, "ls-files", "-v", "-z", "--", "agent", "scripts", "src/arc3")
    for raw_entry in raw.split(b"\0"):
        if not raw_entry:
            continue
        if len(raw_entry) < 3 or raw_entry[1:2] != b" ":
            raise RuntimeError("Stage 09 bootstrap Git index entry is malformed")
        try:
            tag = raw_entry[:1].decode("ascii")
            relative = raw_entry[2:].decode("utf-8", errors="strict")
        except UnicodeDecodeError as error:
            raise RuntimeError("Stage 09 bootstrap Git index path is non-portable") from error
        if relative in entries:
            anomalies.add(f"duplicate:{relative}")
        entries[relative] = tag
        if tag != "H":
            anomalies.add(f"{tag}:{relative}")
    expected = set(expected_paths)
    anomalies.update(f"missing:{relative}" for relative in expected.difference(entries))
    anomalies.update(f"extra:{relative}" for relative in set(entries).difference(expected))
    return tuple(sorted(anomalies))


def _verified_source_projection(root: Path, commit: str) -> dict[str, dict[str, str]]:
    repository = root.resolve()
    tree_projection = _tree_projection(repository, commit)
    live_paths = set(_live_non_cache_paths(repository))
    extra_paths = sorted(live_paths.difference(tree_projection))
    index_non_h = _index_non_h_paths(repository, tuple(tree_projection))
    canonical_blobs = _canonical_git_blobs(
        repository, tuple(identity["git_blob"] for identity in tree_projection.values())
    )
    projection: dict[str, dict[str, str]] = {}
    mismatches: list[str] = []
    for relative, identity in tree_projection.items():
        path = repository / relative
        if _path_has_symlink_component(repository, relative) or not path.is_file():
            mismatches.append(relative)
            continue
        raw = path.read_bytes()
        live_blob = _git_blob_oid(raw)
        canonical_sha256 = _sha256_bytes(canonical_blobs[identity["git_blob"]])
        live_sha256 = _sha256_bytes(raw)
        if live_blob != identity["git_blob"] or live_sha256 != canonical_sha256:
            mismatches.append(relative)
        projection[relative] = {
            "git_blob": identity["git_blob"],
            "mode": identity["mode"],
            "sha256": canonical_sha256,
        }
    if extra_paths or index_non_h or mismatches or set(projection) != set(tree_projection):
        raise RuntimeError("Stage 09 bootstrap complete source projection changed")
    return projection


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


def _lexical_python_launcher() -> str:
    return os.path.abspath(sys.executable)


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
        or _git("rev-parse", "--show-object-format") != _GIT_OBJECT_FORMAT
        or _git("rev-parse", "HEAD") != args.expected_harness_commit
        or _git("rev-parse", "HEAD^{tree}") != args.expected_harness_tree
        or _git("branch", "--show-current")
        or _git("status", "--porcelain=v1", "--untracked-files=all")
        or observed != files
    ):
        raise RuntimeError("Stage 09 bootstrap source authority changed")
    source_projection = _verified_source_projection(ROOT, args.expected_harness_commit)
    if any(source_projection[relative]["sha256"] != digest for relative, digest in files.items()):
        raise RuntimeError("Stage 09 bootstrap anchor hashes differ from the full projection")
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
            _lexical_python_launcher(),
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
            env={
                key: value
                for key, value in os.environ.items()
                if key.upper() != "PYTHONPATH" and not key.upper().startswith("GIT_")
            },
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
        "git_object_format": _GIT_OBJECT_FORMAT,
        "git_tree": args.expected_harness_tree,
        "runtime_binding_file_sha256": args.expected_runtime_binding_file_sha256,
        "runtime_binding_hash": runtime["runtime_binding_hash"],
        "runtime_observation_hash": runtime_observation_hash,
        "socket_audit_denial_installed": True,
        "source_projection": source_projection,
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
