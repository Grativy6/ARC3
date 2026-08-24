#!/usr/bin/env python3
"""Execute one predeclared Stage 09 development cell from an exact source root."""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import subprocess
import sys
import sysconfig
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

_HARNESS_SOURCE_PREFIXES = ("agent/", "scripts/", "src/arc3/")
_HARNESS_GIT_OBJECT_FORMAT = "sha1"
_HARNESS_CACHE_DIRECTORIES = frozenset(
    {".hypothesis", ".mypy_cache", ".pytest_cache", ".ruff_cache", "__pycache__"}
)


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
    raw = path.read_bytes()
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("worker specification must be an object")
    if _canonical_bytes(value) != raw:
        raise ValueError("worker evidence must use exact canonical JSON bytes")
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
        os.path.abspath(sys.executable),
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
    environment = {
        key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")
    }
    environment["GIT_NO_REPLACE_OBJECTS"] = "1"
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", argument],
        check=True,
        capture_output=True,
        env=environment,
        text=True,
        timeout=10.0,
    )
    return result.stdout.strip()


def _status(root: Path) -> str:
    environment = {
        key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")
    }
    environment["GIT_NO_REPLACE_OBJECTS"] = "1"
    result = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain=v1", "--untracked-files=all"],
        check=True,
        capture_output=True,
        env=environment,
        text=True,
        timeout=10.0,
    )
    return result.stdout.strip()


def _git_bytes(root: Path, *arguments: str) -> bytes:
    environment = {
        key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")
    }
    environment["GIT_NO_REPLACE_OBJECTS"] = "1"
    result = subprocess.run(
        ["git", "-C", str(root.resolve()), *arguments],
        check=False,
        capture_output=True,
        env=environment,
        timeout=15.0,
    )
    if result.returncode:
        raise ValueError(f"Stage 09 worker git {' '.join(arguments)} failed")
    return result.stdout


def _git_blob_oid(raw: bytes) -> str:
    header = f"blob {len(raw)}\0".encode("ascii")
    return hashlib.sha1(header + raw, usedforsecurity=False).hexdigest()


def _harness_tree_projection(root: Path, commit: str) -> dict[str, dict[str, str]]:
    if _git(root.resolve(), "--show-object-format") != _HARNESS_GIT_OBJECT_FORMAT:
        raise ValueError("Stage 09 worker Git object format changed")
    projection: dict[str, dict[str, str]] = {}
    for raw_entry in _git_bytes(root, "ls-tree", "-r", "-z", commit).split(b"\0"):
        if not raw_entry:
            continue
        metadata, separator, raw_path = raw_entry.partition(b"\t")
        fields = metadata.split()
        if not separator or len(fields) != 3:
            raise ValueError("Stage 09 worker Git tree entry is malformed")
        try:
            mode, object_type, object_id = (field.decode("ascii") for field in fields)
            relative = raw_path.decode("utf-8", errors="strict")
        except UnicodeDecodeError as error:
            raise ValueError("Stage 09 worker Git tree path is non-portable") from error
        if not relative.startswith(_HARNESS_SOURCE_PREFIXES):
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
            raise ValueError("Stage 09 worker Git tree contains a non-regular source")
        projection[relative] = {"git_blob": object_id, "mode": mode}
    required = {
        "scripts/_stage09_supervisor_bootstrap.py",
        "scripts/measure_development_recovery.py",
        "scripts/_stage09_development_worker.py",
        "src/arc3/evaluation/development_recovery.py",
    }
    if not projection or not required.issubset(projection):
        raise ValueError("Stage 09 worker Git tree projection is incomplete")
    return dict(sorted(projection.items()))


def _path_has_symlink_component(root: Path, relative: str) -> bool:
    current = root.resolve()
    for part in relative.split("/"):
        current /= part
        if current.is_symlink():
            return True
    return False


def _live_harness_projection(
    root: Path, tree_projection: Mapping[str, Mapping[str, str]]
) -> dict[str, dict[str, object]]:
    repository = root.resolve()
    observed: dict[str, dict[str, object]] = {}
    for relative, identity in tree_projection.items():
        path = repository / relative
        raw: bytes | None = None
        if not _path_has_symlink_component(repository, relative) and path.is_file():
            try:
                raw = path.read_bytes()
            except OSError:
                raw = None
        observed[relative] = {
            "git_blob": _git_blob_oid(raw) if raw is not None else None,
            "mode": identity["mode"],
            "sha256": f"sha256:{hashlib.sha256(raw).hexdigest()}" if raw is not None else None,
        }
    return observed


def _live_non_cache_harness_paths(root: Path) -> tuple[str, ...]:
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
                elif name not in _HARNESS_CACHE_DIRECTORIES:
                    retained.append(name)
            raw_directories[:] = retained
            for name in sorted(filenames):
                found.add((directory_path / name).relative_to(repository).as_posix())
    return tuple(sorted(found))


def _harness_index_non_h_paths(root: Path, expected_paths: Sequence[str]) -> tuple[str, ...]:
    entries: dict[str, str] = {}
    anomalies: set[str] = set()
    raw = _git_bytes(root, "ls-files", "-v", "-z", "--", "agent", "scripts", "src/arc3")
    for raw_entry in raw.split(b"\0"):
        if not raw_entry:
            continue
        if len(raw_entry) < 3 or raw_entry[1:2] != b" ":
            raise ValueError("Stage 09 worker Git index entry is malformed")
        try:
            tag = raw_entry[:1].decode("ascii")
            relative = raw_entry[2:].decode("utf-8", errors="strict")
        except UnicodeDecodeError as error:
            raise ValueError("Stage 09 worker Git index path is non-portable") from error
        if relative in entries:
            anomalies.add(f"duplicate:{relative}")
        entries[relative] = tag
        if tag != "H":
            anomalies.add(f"{tag}:{relative}")
    expected = set(expected_paths)
    anomalies.update(f"missing:{relative}" for relative in expected.difference(entries))
    anomalies.update(f"extra:{relative}" for relative in set(entries).difference(expected))
    return tuple(sorted(anomalies))


def _harness_observation(root: Path, expected: Mapping[str, object]) -> dict[str, object]:
    files = expected.get("files")
    source_projection = expected.get("source_projection")
    required_files = {
        "scripts/_stage09_supervisor_bootstrap.py",
        "scripts/measure_development_recovery.py",
        "scripts/_stage09_development_worker.py",
        "src/arc3/evaluation/development_recovery.py",
    }
    if (
        expected.get("schema") != "arc3.build-001.stage-09-harness-source-binding.v0.2"
        or expected.get("binding_hash") != _object_hash(expected, "binding_hash")
        or expected.get("git_object_format") != _HARNESS_GIT_OBJECT_FORMAT
        or not isinstance(files, dict)
        or set(files) != required_files
        or any(
            not isinstance(digest, str)
            or len(digest) != 71
            or not digest.startswith("sha256:")
            or any(character not in "0123456789abcdef" for character in digest[7:])
            for digest in files.values()
        )
        or any(
            not isinstance(expected.get(field), str)
            or len(cast(str, expected[field])) != 40
            or any(character not in "0123456789abcdef" for character in cast(str, expected[field]))
            for field in ("git_commit", "git_tree")
        )
        or not isinstance(source_projection, dict)
        or not source_projection
        or not required_files.issubset(source_projection)
        or any(
            not isinstance(relative, str)
            or not relative.startswith(_HARNESS_SOURCE_PREFIXES)
            or relative.startswith("/")
            or "\\" in relative
            or any(part in {"", ".", ".."} for part in relative.split("/"))
            or not isinstance(identity, dict)
            or set(identity) != {"git_blob", "mode", "sha256"}
            or not isinstance(identity.get("git_blob"), str)
            or len(cast(str, identity["git_blob"])) != 40
            or any(
                character not in "0123456789abcdef" for character in cast(str, identity["git_blob"])
            )
            or identity.get("mode") not in {"100644", "100755"}
            or not isinstance(identity.get("sha256"), str)
            or len(cast(str, identity["sha256"])) != 71
            or not cast(str, identity["sha256"]).startswith("sha256:")
            or any(
                character not in "0123456789abcdef"
                for character in cast(str, identity["sha256"])[7:]
            )
            for relative, identity in source_projection.items()
        )
        or any(
            cast(dict[str, object], source_projection[relative]).get("sha256") != digest
            for relative, digest in files.items()
        )
    ):
        raise ValueError("Stage 09 harness source binding is invalid")
    resolved = root.resolve()
    try:
        branch = (
            _git_bytes(resolved, "branch", "--show-current")
            .decode("utf-8", errors="strict")
            .strip()
        )
    except UnicodeDecodeError as error:
        raise ValueError("Stage 09 worker Git branch is non-UTF-8") from error
    top_level = Path(_git(resolved, "--show-toplevel")).resolve()
    status = _status(resolved)
    commit = _git(resolved, "HEAD")
    object_format = _git(resolved, "--show-object-format")
    tree = _git(resolved, "HEAD^{tree}")
    tree_projection = _harness_tree_projection(resolved, commit)
    observed_projection = _live_harness_projection(resolved, tree_projection)
    observed_files = {
        relative: observed_projection[relative]["sha256"] for relative in required_files
    }
    live_paths = set(_live_non_cache_harness_paths(resolved))
    extra_paths = tuple(sorted(live_paths.difference(tree_projection)))
    index_non_h_paths = _harness_index_non_h_paths(resolved, tuple(tree_projection))
    predicates = {
        "clean": status == "",
        "commit": commit == expected.get("git_commit"),
        "detached": branch == "",
        "extra_files": not extra_paths,
        "files": observed_files == files,
        "index_flags": not index_non_h_paths,
        "object_format": object_format
        == expected.get("git_object_format")
        == _HARNESS_GIT_OBJECT_FORMAT,
        "projection": observed_projection == source_projection,
        "root": top_level == resolved,
        "tree": tree == expected.get("git_tree"),
    }
    payload: dict[str, object] = {
        "schema": "arc3.build-001.stage-09-harness-source-observation.v0.2",
        "binding_hash": expected["binding_hash"],
        "branch": branch,
        "dirty_worktree": bool(status),
        "extra_non_cache_paths": list(extra_paths),
        "files": observed_files,
        "git_commit": commit,
        "git_object_format": object_format,
        "git_tree": tree,
        "index_non_h_paths": list(index_non_h_paths),
        "passed": all(predicates.values()),
        "predicates": predicates,
        "root": resolved.as_posix(),
        "source_projection": observed_projection,
    }
    payload["observation_hash"] = _object_hash(payload, "observation_hash")
    return payload


def _canonical_distribution_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _distribution_record_identity(
    distribution: importlib.metadata.Distribution,
) -> dict[str, object]:
    record_items = [
        item
        for item in distribution.files or ()
        if str(item).replace("\\", "/").endswith(".dist-info/RECORD")
    ]
    if len(record_items) != 1:
        return {
            "hash_entry_count": 0,
            "installed_files_sha256": None,
            "record_entry_count": 0,
            "record_sha256": None,
            "record_verification_passed": False,
            "verified_hash_entry_count": 0,
        }
    record_path = Path(str(distribution.locate_file(record_items[0]))).resolve()
    if not record_path.is_file():
        return {
            "hash_entry_count": 0,
            "installed_files_sha256": None,
            "record_entry_count": 0,
            "record_sha256": None,
            "record_verification_passed": False,
            "verified_hash_entry_count": 0,
        }
    raw = record_path.read_bytes()
    try:
        rows = list(csv.reader(raw.decode("utf-8").splitlines()))
    except (UnicodeDecodeError, csv.Error):
        return {
            "hash_entry_count": 0,
            "installed_files_sha256": None,
            "record_entry_count": 0,
            "record_sha256": None,
            "record_verification_passed": False,
            "verified_hash_entry_count": 0,
        }
    installed_rows: list[tuple[str, int | None, str | None, str]] = []
    verified = 0
    for row in rows:
        if len(row) < 2 or not row[1]:
            continue
        algorithm, separator, encoded = row[1].partition("=")
        if separator != "=" or algorithm != "sha256" or not encoded:
            installed_rows.append((row[0], None, None, row[1]))
            continue
        installed = Path(str(distribution.locate_file(row[0]))).resolve()
        if installed.is_file():
            raw_file = installed.read_bytes()
            digest = _sha256_bytes(raw_file)
            declared = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)).hex()
            if digest == f"sha256:{declared}":
                verified += 1
            installed_rows.append((row[0].replace("\\", "/"), len(raw_file), digest, row[1]))
        else:
            installed_rows.append((row[0].replace("\\", "/"), None, None, row[1]))
    return {
        "hash_entry_count": len(installed_rows),
        "installed_files_sha256": _sha256_bytes(_canonical_bytes(installed_rows)),
        "record_entry_count": len(rows),
        "record_sha256": _sha256_bytes(raw),
        "record_verification_passed": verified == len(installed_rows),
        "verified_hash_entry_count": verified,
    }


def _sha256_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _distribution_file_identity(name: str, prefixes: Sequence[str]) -> dict[str, object]:
    try:
        distribution = importlib.metadata.distribution(name)
    except importlib.metadata.PackageNotFoundError:
        return {
            "file_bytes": 0,
            "file_count": 0,
            "files_sha256": None,
            "record_entry_count": 0,
            "record_sha256": None,
            "hash_entry_count": 0,
            "installed_files_sha256": None,
            "record_verification_passed": False,
            "verified_hash_entry_count": 0,
            "version": None,
        }
    rows: list[tuple[str, int, str]] = []
    for item in sorted(distribution.files or (), key=lambda value: str(value).replace("\\", "/")):
        relative = str(item).replace("\\", "/")
        path = Path(str(distribution.locate_file(item))).resolve()
        if (
            any(relative.startswith(prefix) for prefix in prefixes)
            and path.is_file()
            and "__pycache__" not in path.parts
            and path.suffix != ".pyc"
        ):
            rows.append((relative, path.stat().st_size, _sha256_file(path)))
    return {
        "file_bytes": sum(row[1] for row in rows),
        "file_count": len(rows),
        "files_sha256": _sha256_bytes(_canonical_bytes(rows)),
        **_distribution_record_identity(distribution),
        "version": distribution.version,
    }


def _installed_distribution_inventory() -> dict[str, object]:
    names_and_versions: list[dict[str, str]] = []
    records: list[tuple[str, str, int, str | None, int, int, str | None, bool]] = []
    for distribution in importlib.metadata.distributions():
        raw_name = distribution.metadata.get("Name")
        if not isinstance(raw_name, str) or not raw_name:
            continue
        name = _canonical_distribution_name(raw_name)
        version = distribution.version
        record = _distribution_record_identity(distribution)
        names_and_versions.append({"name": name, "version": version})
        records.append(
            (
                name,
                version,
                cast(int, record["record_entry_count"]),
                cast(str | None, record["record_sha256"]),
                cast(int, record["hash_entry_count"]),
                cast(int, record["verified_hash_entry_count"]),
                cast(str | None, record["installed_files_sha256"]),
                cast(bool, record["record_verification_passed"]),
            )
        )
    names_and_versions.sort(key=lambda item: (item["name"], item["version"]))
    records.sort()
    if len({item["name"] for item in names_and_versions}) != len(names_and_versions):
        raise ValueError("Stage 09 installed distribution inventory contains duplicates")
    return {
        "distribution_count": len(names_and_versions),
        "hash_entry_count": sum(item[4] for item in records),
        "installed_files_sha256": _sha256_bytes(_canonical_bytes(records)),
        "names_and_versions": names_and_versions,
        "record_verification_passed": all(item[7] for item in records),
        "records_sha256": _sha256_bytes(_canonical_bytes([item[:4] for item in records])),
        "verified_hash_entry_count": sum(item[5] for item in records),
    }


def _tree_identity(root: Path, *, exclude_site_packages: bool = False) -> dict[str, object]:
    rows: list[tuple[str, int, str]] = []
    if root.is_dir():
        for path in sorted(root.rglob("*")):
            relative_path = path.relative_to(root)
            if (
                not path.is_file()
                or "__pycache__" in relative_path.parts
                or path.suffix == ".pyc"
                or (
                    exclude_site_packages
                    and any(
                        part in {"site-packages", "dist-packages"} for part in relative_path.parts
                    )
                )
            ):
                continue
            rows.append((relative_path.as_posix(), path.stat().st_size, _sha256_file(path)))
    return {
        "file_bytes": sum(row[1] for row in rows),
        "file_count": len(rows),
        "files_sha256": _sha256_bytes(_canonical_bytes(rows)),
        "root": root.resolve().as_posix(),
    }


def _python_base_identity() -> dict[str, object]:
    base_prefix = Path(sys.base_prefix).resolve()
    stdlib_root = Path(sysconfig.get_path("stdlib")).resolve()
    base_executable = Path(getattr(sys, "_base_executable", sys.executable)).resolve()
    dll_rows: list[tuple[str, int, str]] = []
    for path in sorted(base_prefix.glob("*.dll")):
        if path.is_file():
            dll_rows.append((path.name, path.stat().st_size, _sha256_file(path)))
    dll_root = base_prefix / "DLLs"
    if dll_root.is_dir():
        for path in sorted(dll_root.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
                relative = f"DLLs/{path.relative_to(dll_root).as_posix()}"
                dll_rows.append((relative, path.stat().st_size, _sha256_file(path)))
    return {
        "base_executable": base_executable.as_posix(),
        "base_executable_sha256": _sha256_file(base_executable),
        "base_prefix": base_prefix.as_posix(),
        "dll_file_bytes": sum(row[1] for row in dll_rows),
        "dll_file_count": len(dll_rows),
        "dll_files_sha256": _sha256_bytes(_canonical_bytes(dll_rows)),
        "stdlib": _tree_identity(stdlib_root, exclude_site_packages=True),
    }


def _runtime_observation(root: Path, expected: Mapping[str, object]) -> dict[str, object]:
    if expected.get("schema") != "arc3.build-001.stage-09-runtime-environment.v0.2" or expected.get(
        "runtime_binding_hash"
    ) != _object_hash(expected, "runtime_binding_hash"):
        raise ValueError("Stage 09 runtime environment binding is invalid")
    distributions = {
        "arc-agi": _distribution_file_identity("arc-agi", ("arc_agi/",)),
        "arcengine": _distribution_file_identity("arcengine", ("arcengine/",)),
        "numpy": _distribution_file_identity("numpy", ("numpy/", "numpy.libs/")),
        "pydantic": _distribution_file_identity("pydantic", ("pydantic/",)),
        "pydantic-core": _distribution_file_identity("pydantic-core", ("pydantic_core/",)),
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
    try:
        distribution = importlib.metadata.distribution("arc-agi")
        scorecard = Path(str(distribution.locate_file("arc_agi/scorecard.py"))).resolve()
        scorer_hash = _sha256_file(scorecard) if scorecard.is_file() else None
    except importlib.metadata.PackageNotFoundError:
        scorer_hash = None
    static_actual = {
        "bootstrap_boundary": {
            "residual": None,
            "supervisor_pre_first_party_runtime_validation": True,
            "worker_pre_first_party_runtime_validation": True,
        },
        "cache_tag": sys.implementation.cache_tag,
        "critical_versions": critical_versions,
        "distributions": distributions,
        "installed_distribution_inventory": _installed_distribution_inventory(),
        "executable": Path(sys.executable).resolve().as_posix(),
        "executable_sha256": _sha256_file(Path(sys.executable).resolve()),
        "implementation": platform.python_implementation(),
        "python_version": platform.python_version(),
        "python_base": _python_base_identity(),
        "sdk_probe_network_denied": True,
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
    static_expected = {
        key: value
        for key, value in expected.items()
        if key not in {"runtime_binding_hash", "schema", "sdk_import_probe"}
    }
    static_pass = static_actual == static_expected
    sdk_import_probe = False
    if static_pass:
        sdk_probe = subprocess.run(
            [
                os.path.abspath(sys.executable),
                "-I",
                "-c",
                (
                    "import sys;from pathlib import Path;"
                    'exec("def _deny(event,args):\\n '
                    "   if event.startswith('socket.'): raise RuntimeError('network denied')\");"
                    "sys.addaudithook(_deny);"
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
        sdk_import_probe = sdk_probe.returncode == 0 and sdk_probe.stdout.strip() == b"PASS"
    actual = {**static_actual, "sdk_import_probe": sdk_import_probe}
    predicates = {key: actual[key] == expected.get(key) for key in actual}
    payload: dict[str, object] = {
        "schema": "arc3.build-001.stage-09-runtime-environment-observation.v0.2",
        "actual": actual,
        "binding_hash": expected["runtime_binding_hash"],
        "passed": all(predicates.values()),
        "predicates": predicates,
    }
    payload["observation_hash"] = _object_hash(payload, "observation_hash")
    return payload


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path)
    parser.add_argument("--result", type=Path)
    parser.add_argument("--launch-receipt", type=Path)
    parser.add_argument("--authorization", type=Path)
    parser.add_argument("--abort-receipt", type=Path)
    parser.add_argument("--launch-token")
    parser.add_argument("--bootstrap-runtime-binding", type=Path)
    parser.add_argument("--bootstrap-result", type=Path)
    parser.add_argument("--bootstrap-harness-root", type=Path)
    args = parser.parse_args(list(argv) if argv is not None else None)
    bootstrap_values = (
        args.bootstrap_runtime_binding,
        args.bootstrap_result,
        args.bootstrap_harness_root,
    )
    if any(value is not None for value in bootstrap_values):
        if not all(value is not None for value in bootstrap_values):
            raise ValueError("Stage 09 bootstrap runtime arguments are incomplete")
        expected = _load_object(cast(Path, args.bootstrap_runtime_binding).resolve())
        observation = _runtime_observation(
            cast(Path, args.bootstrap_harness_root).resolve(), expected
        )
        _atomic_create(cast(Path, args.bootstrap_result).resolve(), observation)
        return 0 if observation.get("passed") is True else 74
    if any(
        value is None
        for value in (
            args.spec,
            args.result,
            args.launch_receipt,
            args.authorization,
            args.abort_receipt,
            args.launch_token,
        )
    ):
        raise ValueError("Stage 09 worker invocation arguments are incomplete")
    spec = _load_object(args.spec.resolve())
    if spec.get("schema") != "arc3.build-001.stage-09-worker-spec.v0.4" or spec.get(
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
