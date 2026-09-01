"""Acquire and verify the exact public Strongwiz source used by this experiment."""

from __future__ import annotations

import argparse
import json
import subprocess
from collections.abc import Sequence
from pathlib import Path

from arc3.evaluation.strongwiz_operator import (
    STRONGWIZ_COMMIT,
    StrongwizSourceIdentity,
    verify_strongwiz_source,
)
from arc3.trace.canonical import canonical_json, normalize_json

ROOT = Path(__file__).resolve().parents[1]
SOURCE_URL = "https://github.com/Grativy6/strongwiz.git"
DEFAULT_SOURCE = ROOT / "playground" / "vendor" / "strongwiz"
DEFAULT_ARCHIVE = ROOT / "playground" / "tmp" / "strongwiz-6944642.tar"


def _inside_repository(path: Path) -> Path:
    resolved = path.resolve()
    root = ROOT.resolve()
    if resolved != root and root not in resolved.parents:
        raise ValueError("Strongwiz acquisition paths must remain inside this checkout")
    return resolved


def _run(*args: str, cwd: Path | None = None) -> None:
    subprocess.run(
        args,
        cwd=cwd,
        check=True,
        timeout=300,
    )


def acquire(source: Path, archive: Path) -> dict[str, object]:
    source = _inside_repository(source)
    archive = _inside_repository(archive)
    if not source.exists():
        source.parent.mkdir(parents=True, exist_ok=True)
        _run("git", "clone", "--no-checkout", SOURCE_URL, str(source))
        _run("git", "checkout", "--detach", STRONGWIZ_COMMIT, cwd=source)
    if not archive.exists():
        archive.parent.mkdir(parents=True, exist_ok=True)
        _run(
            "git",
            "archive",
            "--format=tar",
            f"--output={archive}",
            STRONGWIZ_COMMIT,
            cwd=source,
        )
    identity = StrongwizSourceIdentity(source_root=source, archive_path=archive)
    verified = verify_strongwiz_source(identity)
    payload = {
        **verified,
        "archive_path": archive.relative_to(ROOT.resolve()).as_posix(),
        "repository": SOURCE_URL,
        "schema": "arc3.strongwiz-source-acquisition.v0.1",
        "source_path": source.relative_to(ROOT.resolve()).as_posix(),
        "status": "PASS",
    }
    normalized = normalize_json(payload)
    if not isinstance(normalized, dict):
        raise ValueError("Strongwiz acquisition receipt is not an object")
    return dict(normalized)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        print(canonical_json(acquire(args.source, args.archive)))
        return 0
    except (OSError, subprocess.SubprocessError, ValueError) as error:
        print(
            json.dumps(
                {
                    "error": str(error),
                    "exception_type": type(error).__name__,
                    "schema": "arc3.strongwiz-source-acquisition-failure.v0.1",
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
