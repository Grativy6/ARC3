"""Run pytest with fail-closed denial of repository evidence/public paths."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import cast

from scripts.package_only_path_guard import install

SCHEMA = "arc3.package-only-pytest.v0.2"
_PROCESS_ESCAPE_TOKENS = (
    b"_posixsubprocess",
    b"_winapi",
    b"asyncio.create_subprocess",
    b"createprocess",
    b"ctypes",
    b"execve",
    b"fork(",
    b"multiprocessing",
    b"os.exec",
    b"os.fork",
    b"os.popen",
    b"os.spawn",
    b"os.startfile",
    b"os.system",
    b"pexpect",
    b"posix_spawn",
    b"subprocess",
    b"win32process",
)


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sha256(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _write_atomic(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _attempts(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    attempts: list[dict[str, str]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line:
            continue
        loaded: object = json.loads(line)
        if not isinstance(loaded, dict) or not all(
            isinstance(loaded.get(field), str) for field in ("event", "path")
        ):
            raise ValueError(f"guard attempt log line {line_number} has the wrong shape")
        attempts.append(cast(dict[str, str], loaded))
    return attempts


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--guard-log", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--allow-root", action="append", default=[], type=Path)
    parser.add_argument("--select-in-process-tests", action="store_true")
    parser.add_argument("pytest_args", nargs=argparse.REMAINDER)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    root = args.root.resolve()
    guard_log = args.guard_log.resolve()
    receipt_path = args.receipt.resolve()
    if guard_log.exists() or receipt_path.exists():
        print("package-only pytest refused: guard log and receipt must be fresh", file=sys.stderr)
        return 2
    excluded_process_capable_tests: list[str] = []
    selected_test_file_count = 0
    if args.select_in_process_tests:
        test_files = sorted((root / "tests").rglob("test_*.py"))
        for test_file in test_files:
            content = test_file.read_bytes().lower()
            relative = test_file.relative_to(root).as_posix()
            if any(token.lower() in content for token in _PROCESS_ESCAPE_TOKENS):
                excluded_process_capable_tests.append(relative)
            else:
                selected_test_file_count += 1
    allowed_roots = {
        root,
        guard_log.parent,
        receipt_path.parent,
        Path(sys.base_prefix).resolve(),
        Path(sys.prefix).resolve(),
        Path(os.devnull).resolve(),
        *(candidate.resolve() for candidate in args.allow_root),
    }
    os.environ["ARC3_PACKAGE_ONLY_ROOT"] = str(root)
    os.environ["ARC3_PACKAGE_ONLY_GUARD_LOG"] = str(guard_log)
    os.environ["ARC3_PACKAGE_ONLY_ALLOWED_ROOTS"] = json.dumps(
        [str(path) for path in sorted(allowed_roots)], separators=(",", ":")
    )
    os.environ["ARC3_PACKAGE_ONLY_PROTECTED_PATHS"] = json.dumps(
        [str(receipt_path)], separators=(",", ":")
    )
    bootstrap = root / "scripts" / "_package_only_bootstrap"
    inherited_path = os.pathsep.join((str(root), str(bootstrap)))
    os.environ["PYTHONPATH"] = inherited_path
    guard = install(
        root,
        guard_log,
        allowed_roots=tuple(allowed_roots),
        protected_paths=(receipt_path,),
    )
    pytest_args = list(args.pytest_args)
    if pytest_args[:1] == ["--"]:
        pytest_args.pop(0)
    for relative in excluded_process_capable_tests:
        pytest_args.extend(("--ignore", str(root / relative)))
    runner_failure: str | None = None
    try:
        import pytest

        pytest_exit_code = int(pytest.main(pytest_args))
    except BaseException as error:  # fail closed and preserve a boundary receipt
        pytest_exit_code = 4
        runner_failure = type(error).__name__
    finally:
        guard.close()
    attempts = _attempts(guard_log)
    status = "PASS" if pytest_exit_code == 0 and not attempts else "FAILED_BOUNDARY"
    body: dict[str, object] = {
        "attempt_count": len(attempts),
        "attempts": attempts,
        "allowed_root_count": len(allowed_roots),
        "allow_root_ancestor_directory_metadata_allowed": True,
        "canonical_paths": True,
        "child_processes_denied": True,
        "claim_scope": (
            "selected Python-level in-process tests made no Python-audited disallowed path "
            "access beyond allow-root-ancestor directory metadata and spawned no Python-audited "
            "child process; this is not OS containment"
        ),
        "excluded_process_capable_tests": excluded_process_capable_tests,
        "external_paths_default_denied": True,
        "protected_directories": ["artifacts", "docs/evaluation"],
        "protected_files": [
            "docs/ledger/build-001-run-state.json",
            "docs/ledger/run-state.json",
            "guard-attempt-log",
            "guard-receipt",
        ],
        "pytest_exit_code": pytest_exit_code,
        "runner_failure": runner_failure,
        "selected_test_file_count": selected_test_file_count,
        "selection_policy": (
            "static-process-capability-exclusion-plus-runtime-process-denial"
            if args.select_in_process_tests
            else "caller-selected-tests-plus-runtime-process-denial"
        ),
        "schema": SCHEMA,
        "status": status,
    }
    body["receipt_sha256"] = _sha256(_canonical_bytes(body))
    _write_atomic(receipt_path, _canonical_bytes(body))
    print(json.dumps(body, separators=(",", ":"), sort_keys=True))
    if attempts:
        return 3
    if runner_failure is not None:
        return 4
    return pytest_exit_code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
