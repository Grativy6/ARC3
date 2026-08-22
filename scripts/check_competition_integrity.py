"""Emit a deterministic offline competition-integrity receipt."""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

from arc3.integrity import (
    DEFAULT_MAX_CANDIDATE_BYTES,
    IntegrityReceipt,
    build_integrity_receipt,
)


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
    return parser


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
    manifest = _resolve_from_root(
        root,
        args.manifest,
        "docs/evaluation/public-game-partitions.v0.1.json",
    )
    lock = _resolve_from_root(root, args.lock, "uv.lock")
    run_state = _resolve_from_root(root, args.run_state, "docs/ledger/run-state.json")
    archives = tuple(_resolve_from_root(root, path, "") for path in args.archive)
    output = (
        _resolve_from_root(root, args.output, "integrity-receipt.json") if args.output else None
    )
    protected = (
        manifest,
        lock,
        run_state,
        root / "LICENSE",
        root / "pyproject.toml",
        root / "upstream.lock.json",
        root / "THIRD_PARTY_NOTICES.md",
        root / "agent/my_agent.py",
        *archives,
    )
    try:
        if output is not None:
            _validate_output_path(output=output, protected=protected)
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
        )
    except (FileExistsError, OSError, ValueError) as error:
        print(f"integrity scan refused: {error}", file=sys.stderr)
        return 2
    raw = receipt.canonical_bytes()
    if output is not None:
        _atomic_write(output, raw)
    sys.stdout.buffer.write(raw + b"\n")
    return 0 if receipt.passed else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
