"""Run pytest with fail-closed denial of repository evidence/public paths."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, cast

from arc3.integrity import read_bounded_regular_snapshot
from scripts.package_only_path_guard import install

SCHEMA = "arc3.package-only-pytest.v0.4"
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_MAX_SOURCE_SNAPSHOT_BYTES = 256 * 1024 * 1024
_MAX_SOURCE_SNAPSHOT_FILES = 20_000
_CONFIG_CANDIDATES = frozenset(
    {"conftest.py", "pyproject.toml", "pytest.ini", "setup.cfg", "tox.ini", "uv.lock"}
)
_RUNNER_CLOSURE = frozenset(
    {
        ".github/workflows/ci.yml",
        "scripts/__init__.py",
        "scripts/package_only_path_guard.py",
        "scripts/package_only_pytest.py",
        "scripts/_package_only_bootstrap/sitecustomize.py",
    }
)
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
BUILD001_BOUNDARY_EXCLUSIONS: tuple[tuple[str, str], ...] = (
    (
        "tests/competition/test_run_build002_holdout.py",
        "the Build 002 production-preflight test intentionally copies the protected public "
        "partition manifest",
    ),
    (
        "tests/integration/test_evaluation_cli.py",
        "evaluation orchestration is outside the package-only verification boundary",
    ),
    (
        "tests/integration/test_kaggle_package_determinism.py",
        "the package builder transitively executes an isolated subprocess sandbox",
    ),
    (
        "tests/integration/test_pinned_agents_framework.py",
        "the POSIX-only exact pinned framework lifecycle transitively launches the competition "
        "subprocess and inspects platform runtime paths",
    ),
    (
        "tests/integration/test_retrodiction_decision_integration.py",
        "experiment-harness integration is outside the package-only verification boundary",
    ),
    (
        "tests/integration/test_stage16_runtime_profile.py",
        "long-form profiling is outside the package-only verification boundary",
    ),
    (
        "tests/integrity/test_dependencies.py",
        "the integrity fixture transitively invokes subprocess-backed source identity checks",
    ),
    (
        "tests/integrity/test_first_party_license.py",
        "the integrity fixture transitively invokes subprocess-backed source identity checks",
    ),
    (
        "tests/integrity/test_receipt.py",
        "integrity receipts transitively invoke subprocess-backed source identity checks",
    ),
    (
        "tests/integrity/test_repository_integrity.py",
        "the full-repository check intentionally reads the protected public partition manifest",
    ),
    (
        "tests/integrity/test_secret_scan.py",
        "the integrity fixture transitively invokes subprocess-backed source identity checks",
    ),
    (
        "tests/unit/test_diagnose_hot_path.py",
        "the profiler fixture transitively invokes subprocess-backed source identity checks",
    ),
    (
        "tests/unit/test_measure_hot_path.py",
        "the profiler fixture transitively invokes subprocess-backed source identity checks",
    ),
    (
        "tests/unit/test_memory_integrity.py",
        "the static memory check intentionally reads the protected public partition manifest",
    ),
    (
        "tests/unit/test_public_evaluation_contract.py",
        "the public evaluation contract intentionally reads protected evaluation evidence",
    ),
)
ORDINARY_CI_FULL_SUITE_COMMAND = "uv run pytest -q --cov-report=xml"
CLAIM_SCOPE = (
    "the exact receipt-listed tests and entire guard-permitted tracked tree matched immutable "
    "Git blobs from the claimed commit before and after execution, used ordinary H stage-0 "
    "index entries whose modes and blob IDs exactly matched that tree, made no Python-audited "
    "disallowed path access beyond allow-root-ancestor "
    "directory metadata and the exact read-only Linux RSS surface, and spawned no "
    "Python-audited child process; excluded files remain covered only by ordinary "
    "unfiltered CI; this is not OS containment"
)


@dataclass(frozen=True, slots=True)
class TestSelection:
    """Exact source-relative test-file projection for the guarded run."""

    all_test_files: tuple[str, ...]
    boundary_exclusion_reasons: tuple[tuple[str, str], ...]
    excluded_process_capable_tests: tuple[str, ...]
    selected_test_files: tuple[str, ...]
    source_closure_records: tuple[tuple[str, str], ...]
    source_commit: str | None
    source_index_stage_records: tuple[tuple[str, str, str], ...]
    source_index_tags: tuple[tuple[str, str], ...]

    def to_dict(self) -> dict[str, object]:
        all_files = list(self.all_test_files)
        selected = list(self.selected_test_files)
        closure_records = [
            {"path": path, "sha256": digest} for path, digest in self.source_closure_records
        ]
        stage_records = [
            {"blob": blob, "mode": mode, "path": path}
            for path, mode, blob in self.source_index_stage_records
        ]
        return {
            "all_test_file_count": len(all_files),
            "all_test_files": all_files,
            "all_test_files_sha256": _sha256(_canonical_bytes(all_files)),
            "boundary_exclusion_reasons": dict(self.boundary_exclusion_reasons),
            "excluded_boundary_tests": [path for path, _ in self.boundary_exclusion_reasons],
            "excluded_process_capable_tests": list(self.excluded_process_capable_tests),
            "selected_test_file_count": len(selected),
            "selected_test_files": selected,
            "selected_test_files_sha256": _sha256(_canonical_bytes(selected)),
            "source_closure_exact_git_commit_bound": self.source_commit is not None,
            "source_closure_file_count": len(closure_records),
            "source_closure_files": [record["path"] for record in closure_records],
            "source_closure_records": closure_records,
            "source_closure_sha256": _sha256(_canonical_bytes(closure_records)),
            "source_commit": self.source_commit,
            "source_index_stage_records": stage_records,
            "source_index_stage_sha256": _sha256(_canonical_bytes(stage_records)),
            "source_index_tags": dict(self.source_index_tags),
            "source_index_tags_sha256": _sha256(_canonical_bytes(dict(self.source_index_tags))),
        }


class _PytestEvidence:
    """Capture the exact files and item count collected by in-process pytest."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self.collected_test_count = 0
        self.collected_test_files: tuple[str, ...] = ()

    def pytest_collection_finish(self, session: Any) -> None:
        self.collected_test_count = len(session.items)
        paths: set[str] = set()
        for item in session.items:
            candidate = Path(str(item.path)).resolve()
            try:
                relative = candidate.relative_to(self._root).as_posix()
            except ValueError:
                relative = "@external-collected-test"
            paths.add(relative)
        self.collected_test_files = tuple(sorted(paths))


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


def _git_environment() -> dict[str, str]:
    environment = {
        key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")
    }
    environment["GIT_NO_REPLACE_OBJECTS"] = "1"
    return environment


def _git_bytes(repository: Path, *arguments: str, input_bytes: bytes | None = None) -> bytes:
    completed = subprocess.run(
        ("git", "--no-replace-objects", "-C", str(repository.resolve()), *arguments),
        check=False,
        capture_output=True,
        env=_git_environment(),
        input=input_bytes,
    )
    if completed.returncode != 0:
        stderr = completed.stderr.decode("utf-8", errors="replace").strip()
        raise ValueError(
            f"exact source Git command failed ({' '.join(arguments)}): {stderr or 'no stderr'}"
        )
    return completed.stdout


def _git_tree(repository: Path, expected_commit: str) -> dict[str, tuple[str, str]]:
    top_level = Path(
        _git_bytes(repository, "rev-parse", "--show-toplevel").decode("utf-8").strip()
    ).resolve()
    if top_level != repository.resolve():
        raise ValueError("package-only pytest root is not the exact Git top level")
    resolved_commit = (
        _git_bytes(repository, "rev-parse", "--verify", f"{expected_commit}^{{commit}}")
        .decode("ascii")
        .strip()
    )
    if resolved_commit != expected_commit:
        raise ValueError("package-only pytest expected commit did not resolve literally")
    head = _git_bytes(repository, "rev-parse", "HEAD").decode("ascii").strip()
    if head != expected_commit:
        raise ValueError("package-only pytest expected commit is not the checked-out HEAD")
    tree: dict[str, tuple[str, str]] = {}
    for record in _git_bytes(repository, "ls-tree", "-r", "-z", expected_commit).split(b"\0"):
        if not record:
            continue
        metadata, separator, raw_path = record.partition(b"\t")
        fields = metadata.split(b" ")
        if separator != b"\t" or len(fields) != 3:
            raise ValueError("package-only pytest encountered malformed Git tree output")
        mode, object_type, object_id = fields
        if object_type != b"blob" or mode not in {b"100644", b"100755", b"120000"}:
            raise ValueError("package-only pytest does not permit non-blob Git tree leaves")
        try:
            relative = raw_path.decode("utf-8", errors="strict")
            object_name = object_id.decode("ascii", errors="strict")
        except UnicodeDecodeError as error:
            raise ValueError("package-only pytest requires portable UTF-8 Git paths") from error
        if relative in tree:
            raise ValueError("package-only pytest encountered a duplicate Git tree path")
        tree[relative] = (mode.decode("ascii", errors="strict"), object_name)
    stage_entries: dict[str, tuple[str, str]] = {}
    for record in _git_bytes(repository, "ls-files", "--stage", "-z").split(b"\0"):
        if not record:
            continue
        metadata, separator, raw_path = record.partition(b"\t")
        fields = metadata.split(b" ")
        if separator != b"\t" or len(fields) != 3:
            raise ValueError("package-only pytest encountered malformed Git index-stage output")
        raw_mode, raw_object_id, stage = fields
        try:
            relative = raw_path.decode("utf-8", errors="strict")
            stage_mode = raw_mode.decode("ascii", errors="strict")
            stage_object_id = raw_object_id.decode("ascii", errors="strict")
        except UnicodeDecodeError as error:
            raise ValueError("package-only pytest requires portable Git index entries") from error
        if stage != b"0" or relative in stage_entries:
            raise ValueError("package-only pytest requires unique stage-0 Git index entries")
        stage_entries[relative] = (stage_mode, stage_object_id)
    if stage_entries != tree:
        raise ValueError("package-only pytest Git index projection differs from expected tree")
    return tree


def _git_blob_bytes(repository: Path, object_ids: Sequence[str]) -> dict[str, bytes]:
    unique_ids = tuple(dict.fromkeys(object_ids))
    if not unique_ids:
        return {}
    if len(unique_ids) > _MAX_SOURCE_SNAPSHOT_FILES:
        raise ValueError("package-only pytest source snapshot exceeds the file-count limit")
    batch_input = "".join(f"{object_id}\n" for object_id in unique_ids).encode("ascii")
    metadata = _git_bytes(repository, "cat-file", "--batch-check", input_bytes=batch_input)
    metadata_lines = metadata.decode("ascii", errors="strict").splitlines()
    if len(metadata_lines) != len(unique_ids):
        raise ValueError("package-only pytest received incomplete Git blob metadata")
    total_bytes = 0
    expected_sizes: list[int] = []
    for expected_id, line in zip(unique_ids, metadata_lines, strict=True):
        fields = line.split(" ")
        if len(fields) != 3 or fields[:2] != [expected_id, "blob"]:
            raise ValueError("package-only pytest received the wrong Git blob metadata")
        size = int(fields[2])
        if size > 32 * 1024 * 1024:
            raise ValueError("package-only pytest Git blob exceeds the per-file byte limit")
        total_bytes += size
        if total_bytes > _MAX_SOURCE_SNAPSHOT_BYTES:
            raise ValueError("package-only pytest source snapshot exceeds the byte limit")
        expected_sizes.append(size)
    blobs: dict[str, bytes] = {}
    process = subprocess.Popen(
        (
            "git",
            "--no-replace-objects",
            "-C",
            str(repository.resolve()),
            "cat-file",
            "--batch",
        ),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=_git_environment(),
    )
    assert process.stdin is not None and process.stdout is not None and process.stderr is not None
    try:
        for expected_id, expected_size in zip(unique_ids, expected_sizes, strict=True):
            process.stdin.write(f"{expected_id}\n".encode("ascii"))
            process.stdin.flush()
            header = process.stdout.readline(256)
            fields = header.rstrip(b"\n").decode("ascii", errors="strict").split(" ")
            if fields != [expected_id, "blob", str(expected_size)]:
                raise ValueError("package-only pytest received the wrong Git blob object")
            raw = process.stdout.read(expected_size)
            if len(raw) != expected_size or process.stdout.read(1) != b"\n":
                raise ValueError("package-only pytest received malformed Git blob framing")
            blobs[expected_id] = raw
        process.stdin.close()
        trailing = process.stdout.read(1)
        stderr = process.stderr.read(65_537)
        return_code = process.wait(timeout=30)
        if return_code != 0 or trailing or len(stderr) > 65_536:
            raise ValueError("package-only pytest Git blob stream failed closed")
    except BaseException:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=30)
        raise
    return blobs


def _protected_source_path(relative: str) -> bool:
    return relative in {
        "docs/ledger/build-001-run-state.json",
        "docs/ledger/run-state.json",
    } or relative.startswith(("artifacts/", "docs/evaluation/"))


def _execution_control_candidate(relative: str, selected: set[str]) -> bool:
    path = PurePosixPath(relative)
    if relative in selected or relative in _CONFIG_CANDIDATES or relative in _RUNNER_CLOSURE:
        return True
    if path.parts[:1] == ("tests",) and path.name in {"__init__.py", "conftest.py"}:
        return True
    return bool(
        path.suffix == ".py"
        and (
            path.parts[:1] == ("agent",)
            or path.parts[:2] == ("src", "arc3")
            or path.parts[:1] == ("scripts",)
        )
    )


def _live_source_closure(repository: Path, selected: set[str]) -> set[str]:
    candidates = set(selected)
    for relative in _CONFIG_CANDIDATES | _RUNNER_CLOSURE:
        if (repository / relative).exists() or (repository / relative).is_symlink():
            candidates.add(relative)
    for source_root in ("agent", "scripts", "src/arc3", "tests"):
        base = repository / source_root
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if not (path.is_file() or path.is_symlink()):
                continue
            relative = path.relative_to(repository).as_posix()
            if _execution_control_candidate(relative, selected):
                candidates.add(relative)
    return candidates


def _index_tags(repository: Path) -> dict[str, str]:
    tags: dict[str, str] = {}
    for record in _git_bytes(repository, "ls-files", "-v", "-z").split(b"\0"):
        if not record:
            continue
        if len(record) < 3 or record[1:2] != b" ":
            raise ValueError("package-only pytest encountered malformed Git index tags")
        try:
            tag = record[:1].decode("ascii", errors="strict")
            relative = record[2:].decode("utf-8", errors="strict")
        except UnicodeDecodeError as error:
            raise ValueError("package-only pytest requires portable Git index paths") from error
        tags[relative] = tag
    return tags


def build001_test_selection(
    root: Path,
    *,
    expected_commit: str | None = None,
) -> TestSelection:
    """Recompute the guarded subset and optionally bind its closure to Git blobs."""

    repository = root.resolve()
    git_tree: dict[str, tuple[str, str]] | None = None
    git_blobs: dict[str, bytes] = {}
    if expected_commit is not None:
        if _COMMIT.fullmatch(expected_commit) is None:
            raise ValueError("package-only pytest requires a full lowercase expected commit")
        git_tree = _git_tree(repository, expected_commit)
        all_test_files = tuple(
            sorted(
                relative
                for relative in git_tree
                if PurePosixPath(relative).parts[:1] == ("tests",)
                and PurePosixPath(relative).name.startswith("test_")
                and PurePosixPath(relative).suffix == ".py"
            )
        )
        live_test_files = {
            path.relative_to(repository).as_posix()
            for path in (repository / "tests").rglob("test_*.py")
            if path.is_file() or path.is_symlink()
        }
        if live_test_files != set(all_test_files):
            raise ValueError("live test-file membership differs from the exact Git commit")
        git_blobs = _git_blob_bytes(
            repository,
            [git_tree[relative][1] for relative in all_test_files],
        )
    else:
        all_test_files = tuple(
            sorted(
                path.relative_to(repository).as_posix()
                for path in (repository / "tests").rglob("test_*.py")
            )
        )
    if not all_test_files:
        raise ValueError("package-only pytest found no test files")
    all_test_set = set(all_test_files)
    boundary_exclusions = tuple(sorted(BUILD001_BOUNDARY_EXCLUSIONS))
    for relative, reason in boundary_exclusions:
        normalized = PurePosixPath(relative)
        if (
            normalized.is_absolute()
            or normalized.as_posix() != relative
            or not relative.startswith("tests/")
            or normalized.name.startswith("test_") is False
            or normalized.suffix != ".py"
            or any(part in {"", ".", ".."} for part in normalized.parts)
            or not reason.strip()
        ):
            raise ValueError(f"invalid Build 001 boundary exclusion policy: {relative!r}")
        if relative not in all_test_set:
            raise ValueError(f"stale Build 001 boundary exclusion policy: {relative}")
    boundary_paths = {path for path, _ in boundary_exclusions}
    process_capable: list[str] = []
    for relative in all_test_files:
        content = (
            git_blobs[git_tree[relative][1]]
            if git_tree is not None
            else read_bounded_regular_snapshot(
                root=repository,
                path=repository / relative,
                path_label=relative,
            )
        ).lower()
        if any(token.lower() in content for token in _PROCESS_ESCAPE_TOKENS):
            process_capable.append(relative)
    selected = tuple(
        relative
        for relative in all_test_files
        if relative not in boundary_paths and relative not in process_capable
    )
    if not selected:
        raise ValueError("package-only pytest boundary policy selected no tests")
    selected_set = set(selected)
    if git_tree is not None:
        expected_controls = {
            relative
            for relative in git_tree
            if _execution_control_candidate(relative, selected_set)
        }
        missing_required = (_CONFIG_CANDIDATES & {"pyproject.toml", "uv.lock"}) - expected_controls
        if missing_required or not _RUNNER_CLOSURE.issubset(expected_controls):
            raise ValueError(
                "exact Git test closure is missing required runner/configuration files"
            )
        live_controls = _live_source_closure(repository, selected_set)
        if live_controls != expected_controls:
            raise ValueError("live test execution closure membership differs from the Git commit")
        expected_closure = {
            relative for relative in git_tree if not _protected_source_path(relative)
        }
        git_blobs.update(
            _git_blob_bytes(
                repository,
                [git_tree[relative][1] for relative in sorted(expected_closure)],
            )
        )
        tags = _index_tags(repository)
        closure_tags = tuple(
            (relative, tags.get(relative, "MISSING")) for relative in sorted(expected_closure)
        )
        if any(tag != "H" for _, tag in closure_tags):
            raise ValueError("test execution closure contains a non-H Git index entry")
        closure_stages = tuple(
            (relative, git_tree[relative][0], git_tree[relative][1])
            for relative in sorted(expected_closure)
        )
        closure_records: list[tuple[str, str]] = []
        for relative in sorted(expected_closure):
            live_path = repository / relative
            if live_path.is_symlink() or not live_path.is_file():
                raise ValueError("test execution closure contains an alias or non-file path")
            expected_bytes = git_blobs[git_tree[relative][1]]
            live_bytes = read_bounded_regular_snapshot(
                root=repository,
                path=live_path,
                path_label=relative,
            )
            if live_bytes != expected_bytes:
                raise ValueError("test execution closure bytes differ from the exact Git commit")
            closure_records.append((relative, _sha256(expected_bytes)))
    else:
        live_closure = _live_source_closure(repository, selected_set)
        closure_records = [
            (
                relative,
                _sha256(
                    read_bounded_regular_snapshot(
                        root=repository,
                        path=repository / relative,
                        path_label=relative,
                    )
                ),
            )
            for relative in sorted(live_closure)
            if (repository / relative).is_file() and not (repository / relative).is_symlink()
        ]
        closure_tags = tuple((relative, "UNBOUND") for relative, _ in closure_records)
        closure_stages = tuple((relative, "UNBOUND", "UNBOUND") for relative, _ in closure_records)
    return TestSelection(
        all_test_files=all_test_files,
        boundary_exclusion_reasons=boundary_exclusions,
        excluded_process_capable_tests=tuple(process_capable),
        selected_test_files=selected,
        source_closure_records=tuple(closure_records),
        source_commit=expected_commit,
        source_index_stage_records=closure_stages,
        source_index_tags=closure_tags,
    )


def _validate_exact_pytest_args(pytest_args: Sequence[str]) -> None:
    """Permit output/temp controls only; selection comes exclusively from source projection."""

    index = 0
    while index < len(pytest_args):
        argument = pytest_args[index]
        if argument in {"-q", "--no-cov"}:
            index += 1
            continue
        if argument == "--basetemp":
            if index + 1 >= len(pytest_args):
                raise ValueError("--basetemp requires a value")
            index += 2
            continue
        if argument.startswith("--basetemp=") and argument != "--basetemp=":
            index += 1
            continue
        raise ValueError("exact package-only selection refused caller pytest argument: " + argument)


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


def _attempts_bytes(raw: bytes) -> list[dict[str, str]]:
    attempts: list[dict[str, str]] = []
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeDecodeError as error:
        raise ValueError("guard attempt log is not UTF-8") from error
    for line_number, line in enumerate(lines, start=1):
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
    parser.add_argument("--build001-boundary-policy", action="store_true")
    parser.add_argument("--expected-commit")
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
    pytest_args = list(args.pytest_args)
    if pytest_args[:1] == ["--"]:
        pytest_args.pop(0)
    if any(
        argument == "--rootdir" or argument.startswith("--rootdir=") for argument in pytest_args
    ):
        print("package-only pytest refused: caller cannot override --rootdir", file=sys.stderr)
        return 2
    if args.select_in_process_tests != args.build001_boundary_policy:
        print(
            "package-only pytest refused: exact selection requires the frozen Build 001 policy",
            file=sys.stderr,
        )
        return 2
    if args.select_in_process_tests != (args.expected_commit is not None):
        print(
            "package-only pytest refused: exact selection requires an expected commit",
            file=sys.stderr,
        )
        return 2
    selection: TestSelection | None = None
    if args.select_in_process_tests:
        try:
            _validate_exact_pytest_args(pytest_args)
            selection = build001_test_selection(root, expected_commit=args.expected_commit)
        except (OSError, ValueError) as error:
            print(f"package-only pytest refused: {error}", file=sys.stderr)
            return 2
    framework_root = guard_log.parent / "framework-runtime"
    framework_temp = framework_root / "tmp"
    framework_home = framework_root / "home"
    framework_cache = framework_root / "cache"
    for directory in (framework_temp, framework_home, framework_cache):
        directory.mkdir(parents=True, exist_ok=True)
    os.environ.update(
        {
            "APPDATA": str(framework_home / "AppData" / "Roaming"),
            "HOME": str(framework_home),
            "LOCALAPPDATA": str(framework_home / "AppData" / "Local"),
            "TEMP": str(framework_temp),
            "TMP": str(framework_temp),
            "TMPDIR": str(framework_temp),
            "USERPROFILE": str(framework_home),
            "XDG_CACHE_HOME": str(framework_cache),
        }
    )
    if selection is not None:
        os.environ.pop("PYTEST_ADDOPTS", None)
        os.environ.pop("PYTEST_PLUGINS", None)
    tempfile.tempdir = str(framework_temp)
    allowed_roots = {
        root,
        guard_log.parent,
        receipt_path.parent,
        Path(sys.base_prefix).resolve(),
        Path(sys.prefix).resolve(),
        Path(os.devnull).resolve(),
        *(candidate.resolve() for candidate in args.allow_root),
    }
    canonical_allowed_roots = tuple(
        os.path.normcase(os.path.realpath(os.path.abspath(path))) for path in allowed_roots
    )
    original_sys_path_count = len(sys.path)
    sys.path[:] = [
        entry
        for entry in sys.path
        if any(
            (candidate := os.path.normcase(os.path.realpath(os.path.abspath(entry or Path.cwd()))))
            == allowed
            or candidate.startswith(allowed + os.sep)
            for allowed in canonical_allowed_roots
        )
    ]
    filtered_sys_path_count = original_sys_path_count - len(sys.path)
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
    pytest_args[:0] = ["--rootdir", str(root), "-p", "no:cacheprovider"]
    if selection is not None:
        pytest_args.extend(str(root / relative) for relative in selection.selected_test_files)
    pytest_evidence = _PytestEvidence(root)
    runner_failure: str | None = None
    try:
        import pytest

        pytest_exit_code = int(pytest.main(pytest_args, plugins=[pytest_evidence]))
    except BaseException as error:  # fail closed and preserve a boundary receipt
        pytest_exit_code = 4
        runner_failure = type(error).__name__
    finally:
        guard.close()
    source_projection_matches_after_tests = True
    if selection is not None:
        try:
            source_projection_matches_after_tests = (
                build001_test_selection(root, expected_commit=args.expected_commit) == selection
            )
        except (OSError, ValueError):
            source_projection_matches_after_tests = False
    attempt_log_snapshot = read_bounded_regular_snapshot(
        root=guard_log.parent,
        path=guard_log,
        path_label=guard_log.name,
    )
    attempts = _attempts_bytes(attempt_log_snapshot)
    status = "PASS" if pytest_exit_code == 0 and not attempts else "FAILED_BOUNDARY"
    selection_projection = (
        selection.to_dict()
        if selection is not None
        else {
            "all_test_file_count": 0,
            "all_test_files": [],
            "all_test_files_sha256": _sha256(_canonical_bytes([])),
            "boundary_exclusion_reasons": {},
            "excluded_boundary_tests": [],
            "excluded_process_capable_tests": [],
            "selected_test_file_count": 0,
            "selected_test_files": [],
            "selected_test_files_sha256": _sha256(_canonical_bytes([])),
            "source_closure_exact_git_commit_bound": False,
            "source_closure_file_count": 0,
            "source_closure_files": [],
            "source_closure_records": [],
            "source_closure_sha256": _sha256(_canonical_bytes([])),
            "source_commit": None,
            "source_index_stage_records": [],
            "source_index_stage_sha256": _sha256(_canonical_bytes([])),
            "source_index_tags": {},
            "source_index_tags_sha256": _sha256(_canonical_bytes({})),
        }
    )
    collected_matches_selection = selection is None or (
        pytest_evidence.collected_test_files == selection.selected_test_files
    )
    if not collected_matches_selection:
        status = "FAILED_BOUNDARY"
    if not source_projection_matches_after_tests:
        status = "FAILED_BOUNDARY"
    body: dict[str, object] = {
        "attempt_count": len(attempts),
        "attempt_log_sha256": _sha256(attempt_log_snapshot),
        "attempts": attempts,
        "allowed_root_count": len(allowed_roots),
        "allow_root_ancestor_directory_metadata_allowed": True,
        "canonical_paths": True,
        "child_processes_denied": True,
        "claim_scope": CLAIM_SCOPE,
        "collected_test_count": pytest_evidence.collected_test_count,
        "collected_test_files": list(pytest_evidence.collected_test_files),
        "collection_matches_selected_files": collected_matches_selection,
        "external_paths_default_denied": True,
        "framework_writable_state": "isolated-under-allowed-guard-parent",
        "kernel_telemetry_read_count": guard.kernel_telemetry_read_count,
        "kernel_telemetry_read_only": True,
        "kernel_telemetry_paths": ["/proc/self/status"] if sys.platform.startswith("linux") else [],
        "ordinary_ci_full_suite_command": ORDINARY_CI_FULL_SUITE_COMMAND,
        "protected_directories": ["artifacts", "docs/evaluation"],
        "protected_files": [
            "docs/ledger/build-001-run-state.json",
            "docs/ledger/run-state.json",
            "guard-attempt-log",
            "guard-receipt",
        ],
        "pytest_rootdir_forced": True,
        "pytest_exit_code": pytest_exit_code,
        "runner_failure": runner_failure,
        "selection_policy": (
            "exact-git-blob-execution-closure-v0.4-plus-runtime-boundary-denial"
            if args.select_in_process_tests
            else "caller-selected-tests-plus-runtime-process-denial"
        ),
        "source_projection_matches_after_tests": source_projection_matches_after_tests,
        "sys_path_entries_outside_allowed_roots_removed": filtered_sys_path_count,
        "schema": SCHEMA,
        "status": status,
    }
    body.update(selection_projection)
    body["receipt_sha256"] = _sha256(_canonical_bytes(body))
    _write_atomic(receipt_path, _canonical_bytes(body))
    print(json.dumps(body, separators=(",", ":"), sort_keys=True))
    if attempts or not collected_matches_selection or not source_projection_matches_after_tests:
        return 3
    if runner_failure is not None:
        return 4
    return pytest_exit_code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
