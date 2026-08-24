"""Build the launch-free, hash-bound ARC3 Build 002 preflight bundle.

The command performs no network acquisition, Kaggle authentication, scorecard
operation, public environment interaction, or holdout arming.  A missing exact
external surface produces a durable ``BLOCKED_EXTERNAL`` receipt with zero
consumption; a semantic evidence failure produces ``FAILED_PREFLIGHT`` and no
PASS gates.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from arc3.evaluation.artifacts import canonical_json_bytes
from arc3.evaluation.build002_preflight import (
    build_preflight_bundle,
    bundle_paths,
    load_preflight_bundle_request,
)
from arc3.packaging.util import write_bytes_atomic

REPOSITORY = Path(__file__).resolve().parents[1]
PREFLIGHT_FAILURE_SCHEMA = "arc3.build-002.preflight-failure.v0.1"
PREFLIGHT_EXTERNAL_STOP_SCHEMA = "arc3.build-002.preflight-external-stop.v0.1"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=REPOSITORY)
    parser.add_argument("--request", type=Path, required=True)
    return parser


def _sha256_bytes(raw: bytes) -> str:
    return f"sha256:{hashlib.sha256(raw).hexdigest()}"


def _sealed(document: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(document)
    result["receipt_sha256"] = _sha256_bytes(canonical_json_bytes(result))
    return result


def _git_identity(root: Path) -> dict[str, str] | None:
    try:
        completed = subprocess.run(
            ("git", "--no-replace-objects", "-C", str(root), "rev-parse", "HEAD", "HEAD^{tree}"),
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    rows = completed.stdout.splitlines()
    if len(rows) != 2 or any(len(value) != 40 for value in rows):
        return None
    return {"commit": rows[0], "tree": rows[1]}


def _state_is_pristine(root: Path) -> bool:
    state = root / "artifacts" / "build002" / "holdout-one-shot"
    return not any(
        (state / name).exists()
        for name in (
            "exposure.jsonl",
            "failed-attempt.json",
            "holdout-consumed.json",
            "launch.json",
            "preflight.json",
            "result.json",
            "run.lock",
        )
    )


def _write_stop_receipt(
    root: Path,
    request_path: Path,
    *,
    error: BaseException,
    status: str,
) -> tuple[Path | None, str]:
    """Preserve a no-interaction stop only when the request resolves safely."""

    try:
        request = load_preflight_bundle_request(root, request_path)
    except BaseException:
        return None, status
    paths = bundle_paths(request)
    request.output_directory.mkdir(parents=True, exist_ok=True)
    pristine = _state_is_pristine(root)
    if status == "BLOCKED_EXTERNAL" and not pristine:
        status = "BLOCKED_RECOVERY"
    target = (
        paths.blocker if status == "BLOCKED_EXTERNAL" else request.output_directory / "failure.json"
    )
    schema = (
        PREFLIGHT_EXTERNAL_STOP_SCHEMA if status == "BLOCKED_EXTERNAL" else PREFLIGHT_FAILURE_SCHEMA
    )
    receipt = _sealed(
        {
            "authority": {
                "holdout_authority_consumed": False if pristine else None,
                "rerun_authorized": pristine,
            },
            "claim_boundary": (
                "preflight stopped before arming or any environment interaction"
                if pristine
                else "canonical holdout state exists; authority requires recovery review"
            ),
            "environment_actions": 0,
            "environment_make_interactions": 0,
            "error": {
                "kind": type(error).__name__,
                "message_sha256": _sha256_bytes(str(error).encode("utf-8")),
            },
            "request_sha256": _sha256_bytes(request_path.read_bytes()),
            "schema": schema,
            "source": _git_identity(root),
            "status": status,
        }
    )
    write_bytes_atomic(target, canonical_json_bytes(receipt))
    return target, status


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    root = args.root.resolve()
    request_path = args.request.resolve()
    try:
        request = load_preflight_bundle_request(root, request_path)
        result = build_preflight_bundle(request)
    except FileNotFoundError as error:
        receipt, actual_status = _write_stop_receipt(
            root,
            request_path,
            error=error,
            status="BLOCKED_EXTERNAL",
        )
        print(
            json.dumps(
                {
                    "receipt": receipt.as_posix() if receipt is not None else None,
                    "status": actual_status,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 4 if actual_status == "BLOCKED_RECOVERY" else 3
    except BaseException as error:
        receipt, actual_status = _write_stop_receipt(
            root,
            request_path,
            error=error,
            status="FAILED_PREFLIGHT",
        )
        print(type(error).__name__, file=sys.stderr)
        if receipt is not None:
            print(json.dumps({"receipt": receipt.as_posix(), "status": actual_status}))
        return 2
    print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    return 3 if result.status == "BLOCKED_EXTERNAL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
