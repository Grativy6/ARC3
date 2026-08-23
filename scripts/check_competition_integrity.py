"""Emit a deterministic offline competition-integrity receipt."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path, PurePosixPath

from arc3.integrity import (
    DEFAULT_MAX_CANDIDATE_BYTES,
    IntegrityReceipt,
    build_integrity_receipt,
    read_bounded_regular_snapshot,
)

_PACKAGE_ONLY_PREFIXES = (".github/", "agent/", "scripts/", "src/", "tests/")
_PACKAGE_ONLY_ROOT_FILES = frozenset(
    {
        ".env.example",
        ".gitattributes",
        ".gitignore",
        "AGENTS.md",
        "LICENSE",
        "README.md",
        "THIRD_PARTY_NOTICES.md",
        "pyproject.toml",
        "upstream.lock.json",
        "uv.lock",
    }
)
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_MAX_SOURCE_SNAPSHOT_BYTES = 256 * 1024 * 1024
_MAX_SOURCE_SNAPSHOT_FILES = 20_000


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--lock", type=Path)
    parser.add_argument("--run-state", type=Path)
    parser.add_argument("--expected-manifest-sha256")
    parser.add_argument(
        "--archive",
        action="append",
        default=[],
        type=Path,
        help="ZIP-compatible final package to include in static assurance; repeatable",
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--max-candidate-bytes",
        type=int,
        default=DEFAULT_MAX_CANDIDATE_BYTES,
    )
    parser.add_argument(
        "--generated-at",
        help="explicit receipt timestamp; omitted/null keeps identical inputs byte-deterministic",
    )
    parser.add_argument(
        "--lock-only-metadata",
        action="store_true",
        help="do not enrich the lock from locally installed distribution metadata",
    )
    parser.add_argument(
        "--package-only",
        action="store_true",
        help=(
            "scan package/source surfaces without loading a public partition manifest or "
            "Build ledger; manifest-related arguments are forbidden"
        ),
    )
    parser.add_argument(
        "--expected-commit",
        help="literal clean Git commit required by --package-only",
    )
    return parser


def _git_environment() -> dict[str, str]:
    environment = {
        key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")
    }
    environment["GIT_NO_REPLACE_OBJECTS"] = "1"
    return environment


def _git_bytes(root: Path, *arguments: str, input_bytes: bytes | None = None) -> bytes:
    completed = subprocess.run(
        ("git", "--no-replace-objects", "-C", str(root.resolve()), *arguments),
        check=False,
        capture_output=True,
        env=_git_environment(),
        input=input_bytes,
        timeout=30,
    )
    if completed.returncode != 0:
        stderr = completed.stderr.decode("utf-8", errors="replace").strip()
        raise ValueError(
            f"package-only integrity Git command failed ({' '.join(arguments)}): "
            f"{stderr or 'no stderr'}"
        )
    return completed.stdout


def _git_text(root: Path, *arguments: str) -> str:
    try:
        return _git_bytes(root, *arguments).decode("utf-8", errors="strict").strip()
    except UnicodeDecodeError as error:
        raise ValueError("package-only integrity Git text is not portable UTF-8") from error


def _git_blob_bytes(root: Path, object_ids: Sequence[str]) -> dict[str, bytes]:
    unique_ids = tuple(dict.fromkeys(object_ids))
    if len(unique_ids) > _MAX_SOURCE_SNAPSHOT_FILES:
        raise ValueError("package-only integrity source snapshot exceeds the file-count limit")
    batch_input = "".join(f"{object_id}\n" for object_id in unique_ids).encode("ascii")
    metadata = _git_bytes(root, "cat-file", "--batch-check", input_bytes=batch_input)
    total_bytes = 0
    metadata_lines = metadata.decode("ascii", errors="strict").splitlines()
    if len(metadata_lines) != len(unique_ids):
        raise ValueError("package-only integrity received incomplete Git blob metadata")
    expected_sizes: list[int] = []
    for expected_id, line in zip(unique_ids, metadata_lines, strict=True):
        fields = line.split(" ")
        if len(fields) != 3 or fields[:2] != [expected_id, "blob"]:
            raise ValueError("package-only integrity received the wrong Git blob metadata")
        size = int(fields[2])
        if size > DEFAULT_MAX_CANDIDATE_BYTES:
            raise ValueError("package-only integrity Git blob exceeds the per-file byte limit")
        total_bytes += size
        if total_bytes > _MAX_SOURCE_SNAPSHOT_BYTES:
            raise ValueError("package-only integrity source snapshot exceeds the byte limit")
        expected_sizes.append(size)
    blobs: dict[str, bytes] = {}
    process = subprocess.Popen(
        ("git", "--no-replace-objects", "-C", str(root.resolve()), "cat-file", "--batch"),
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
                raise ValueError("package-only integrity received the wrong Git blob object")
            raw = process.stdout.read(expected_size)
            if len(raw) != expected_size or process.stdout.read(1) != b"\n":
                raise ValueError("package-only integrity received malformed Git blob framing")
            blobs[expected_id] = raw
        process.stdin.close()
        trailing = process.stdout.read(1)
        stderr = process.stderr.read(65_537)
        return_code = process.wait(timeout=30)
        if return_code != 0 or trailing or len(stderr) > 65_536:
            raise ValueError("package-only integrity Git blob stream failed closed")
    except BaseException:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=30)
        raise
    return blobs


def package_only_candidate_files(
    root: Path,
    expected_commit: str,
    *,
    candidate_snapshots: dict[str, bytes] | None = None,
) -> tuple[Path, ...]:
    """Return exact-commit package/source surfaces outside evaluation ledgers."""

    root = root.resolve()
    if _COMMIT.fullmatch(expected_commit) is None:
        raise ValueError("package-only integrity requires a full lowercase expected commit")
    if Path(_git_text(root, "rev-parse", "--show-toplevel")).resolve() != root:
        raise ValueError("package-only integrity root is not the exact Git top level")
    if _git_text(root, "rev-parse", "--verify", f"{expected_commit}^{{commit}}") != expected_commit:
        raise ValueError("package-only integrity expected commit did not resolve literally")
    if _git_text(root, "rev-parse", "HEAD") != expected_commit:
        raise ValueError("package-only integrity HEAD differs from the expected commit")
    if _git_text(root, "status", "--porcelain=v1", "--untracked-files=normal"):
        raise ValueError("package-only integrity requires a clean worktree")

    tree: dict[str, tuple[str, str]] = {}
    for entry in _git_bytes(root, "ls-tree", "-r", "-z", expected_commit).split(b"\0"):
        if not entry:
            continue
        metadata, separator, raw_path = entry.partition(b"\t")
        fields = metadata.split(b" ")
        if separator != b"\t" or len(fields) != 3:
            raise ValueError("package-only integrity received a malformed Git tree entry")
        try:
            mode, object_type, object_id = (
                field.decode("ascii", errors="strict") for field in fields
            )
            relative = raw_path.decode("utf-8", errors="strict")
        except UnicodeDecodeError as error:
            raise ValueError("package-only integrity found a non-portable Git tree") from error
        if relative in tree:
            raise ValueError("package-only integrity found a duplicate Git tree path")
        tree[relative] = (mode, object_id if object_type == "blob" else object_type)

    index_projection = _git_bytes(root, "ls-files", "-v", "-z")
    index_paths: set[str] = set()
    for record in (record for record in index_projection.split(b"\0") if record):
        if len(record) < 3 or record[1:2] != b" ":
            raise ValueError("package-only integrity received malformed Git index evidence")
        try:
            tag = record[:1].decode("ascii", errors="strict")
            relative = record[2:].decode("utf-8", errors="strict")
        except UnicodeDecodeError as error:
            raise ValueError("package-only integrity found a non-portable Git index") from error
        if tag != "H":
            raise ValueError(f"package-only integrity rejects non-H Git index entry: {relative}")
        if relative in index_paths:
            raise ValueError("package-only integrity found a duplicate Git index path")
        index_paths.add(relative)
    if index_paths != set(tree):
        raise ValueError("package-only integrity index membership differs from expected Git tree")
    stage_entries: dict[str, tuple[str, str]] = {}
    for record in _git_bytes(root, "ls-files", "--stage", "-z").split(b"\0"):
        if not record:
            continue
        metadata, separator, raw_path = record.partition(b"\t")
        fields = metadata.split(b" ")
        if separator != b"\t" or len(fields) != 3:
            raise ValueError("package-only integrity received malformed index-stage evidence")
        raw_mode, raw_object_id, stage = fields
        try:
            relative = raw_path.decode("utf-8", errors="strict")
            mode = raw_mode.decode("ascii", errors="strict")
            object_id = raw_object_id.decode("ascii", errors="strict")
        except UnicodeDecodeError as error:
            raise ValueError("package-only integrity found a non-portable index stage") from error
        if stage != b"0" or relative in stage_entries:
            raise ValueError("package-only integrity requires unique stage-0 index entries")
        stage_entries[relative] = (mode, object_id)
    if stage_entries != tree:
        raise ValueError("package-only integrity index projection differs from expected Git tree")

    names = tuple(sorted(tree))
    selected: list[Path] = []
    for name in names:
        portable = PurePosixPath(name)
        if (
            portable.is_absolute()
            or "\\" in name
            or any(part in {"", ".", ".."} for part in portable.parts)
        ):
            raise ValueError("package-only integrity found an unsafe Git tree path")
        normalized = portable.as_posix()
        if normalized in _PACKAGE_ONLY_ROOT_FILES or normalized.startswith(_PACKAGE_ONLY_PREFIXES):
            mode, object_id = tree[name]
            if mode not in {"100644", "100755"} or not re.fullmatch(r"[0-9a-f]{40,64}", object_id):
                raise ValueError(f"package-only candidate is not a regular Git blob: {normalized}")
            path = root.joinpath(*portable.parts)
            try:
                path.resolve().relative_to(root)
            except ValueError as error:
                raise ValueError("package-only candidate path escapes the repository") from error
            selected.append(path)
    if not selected:
        raise ValueError("package-only integrity found no tracked package/source files")
    blobs = _git_blob_bytes(root, [tree[path.relative_to(root).as_posix()][1] for path in selected])
    for path in selected:
        relative = path.relative_to(root).as_posix()
        expected = blobs[tree[relative][1]]
        live = read_bounded_regular_snapshot(
            root=root,
            path=path,
            max_bytes=DEFAULT_MAX_CANDIDATE_BYTES,
            path_label=relative,
        )
        if live != expected:
            raise ValueError(
                f"package-only candidate bytes differ from expected Git blob: {relative}"
            )
        if candidate_snapshots is not None:
            candidate_snapshots[relative] = expected
    return tuple(selected)


def _resolve_from_root(root: Path, value: Path | None, default: str) -> Path:
    selected = value if value is not None else Path(default)
    return (selected if selected.is_absolute() else root / selected).resolve()


def _validate_output_path(*, output: Path, protected: Sequence[Path]) -> None:
    if any(output == path for path in protected):
        raise ValueError("receipt output collides with a required input or supplied archive")
    if output.is_symlink() or (output.exists() and not output.is_file()):
        raise ValueError("receipt output must be a regular file path, never a symlink")
    if output.exists():
        try:
            IntegrityReceipt.from_bytes(output.read_bytes())
        except (OSError, UnicodeDecodeError, ValueError) as error:
            raise FileExistsError(
                "refusing to overwrite an existing file that is not a canonical integrity receipt"
            ) from error


def _atomic_write(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    root = args.root.resolve()
    if args.package_only and (
        args.manifest is not None
        or args.run_state is not None
        or args.expected_manifest_sha256 is not None
    ):
        print(
            "integrity scan refused: --package-only forbids manifest, run-state, and "
            "manifest-identity arguments",
            file=sys.stderr,
        )
        return 2
    if args.package_only and args.expected_commit is None:
        print(
            "integrity scan refused: --package-only requires --expected-commit",
            file=sys.stderr,
        )
        return 2
    manifest = (
        None
        if args.package_only
        else _resolve_from_root(
            root,
            args.manifest,
            "docs/evaluation/public-game-partitions.v0.1.json",
        )
    )
    lock = _resolve_from_root(root, args.lock, "uv.lock")
    run_state = (
        None
        if args.package_only
        else _resolve_from_root(root, args.run_state, "docs/ledger/run-state.json")
    )
    archives = tuple(_resolve_from_root(root, path, "") for path in args.archive)
    output = (
        _resolve_from_root(root, args.output, "integrity-receipt.json") if args.output else None
    )
    protected = (
        lock,
        root / "LICENSE",
        root / "pyproject.toml",
        root / "upstream.lock.json",
        root / "THIRD_PARTY_NOTICES.md",
        root / "agent/my_agent.py",
        *((manifest,) if manifest is not None else ()),
        *((run_state,) if run_state is not None else ()),
        *archives,
    )
    try:
        if output is not None:
            _validate_output_path(output=output, protected=protected)
        package_candidate_snapshots: dict[str, bytes] | None = None
        package_candidates: tuple[Path, ...] | None = None
        if args.package_only:
            assert args.expected_commit is not None
            package_candidate_snapshots = {}
            package_candidates = package_only_candidate_files(
                root,
                args.expected_commit,
                candidate_snapshots=package_candidate_snapshots,
            )
        receipt = build_integrity_receipt(
            root,
            manifest_path=manifest,
            lock_path=lock,
            run_state_path=run_state,
            expected_manifest_sha256=args.expected_manifest_sha256,
            archive_paths=archives,
            receipt_output_path=output,
            max_candidate_bytes=args.max_candidate_bytes,
            include_installed_metadata=not args.lock_only_metadata,
            generated_at=args.generated_at,
            semantic_public_manifest_access=not args.package_only,
            candidate_files=package_candidates,
            candidate_snapshots=package_candidate_snapshots,
        )
    except (FileExistsError, OSError, ValueError) as error:
        print(f"integrity scan refused: {error}", file=sys.stderr)
        return 2
    raw = receipt.canonical_bytes()
    if output is not None:
        _atomic_write(output, raw)
    sys.stdout.buffer.write(raw + b"\n")
    scoped_passed = (
        receipt.body.get("package_only_passed") is True if args.package_only else receipt.passed
    )
    return 0 if scoped_passed else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
