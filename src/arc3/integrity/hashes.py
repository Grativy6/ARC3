"""Canonical hashing primitives for deterministic integrity receipts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path

from arc3.types import JSONValue


def sha256_bytes(value: bytes) -> str:
    """Return a tagged SHA-256 digest."""

    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def sha256_file(path: Path) -> str:
    """Hash a file without interpreting its contents."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def canonical_json_bytes(value: Mapping[str, JSONValue]) -> bytes:
    """Serialize a JSON object with stable ordering and no insignificant whitespace."""

    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


__all__ = ["canonical_json_bytes", "sha256_bytes", "sha256_file"]
