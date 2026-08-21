"""Canonical JSON and tagged SHA-256 helpers for immutable ARC3 receipts."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import asdict, is_dataclass
from enum import Enum
from pathlib import Path

from arc3.errors import ARC3ValidationError
from arc3.types import JSONValue

SHA256_PREFIX = "sha256:"
SHA256_HEX_LENGTH = 64


def normalize_json(value: object) -> JSONValue:
    """Return a recursively validated JSON value without lossy coercions.

    Tuples are intentionally normalized to arrays because checkpoints need to
    carry Python RNG state through JSON.  Sets and arbitrary iterables are
    rejected: their order is not a stable part of the trace contract.
    """

    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ARC3ValidationError("canonical JSON forbids NaN and infinity")
        return value
    if isinstance(value, Enum):
        return normalize_json(value.value)
    if isinstance(value, Path):
        return value.as_posix()
    if is_dataclass(value) and not isinstance(value, type):
        return normalize_json(asdict(value))
    if isinstance(value, Mapping):
        normalized: dict[str, JSONValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ARC3ValidationError("canonical JSON object keys must be strings")
            normalized[key] = normalize_json(item)
        return normalized
    if isinstance(value, tuple):
        return [normalize_json(item) for item in value]
    if isinstance(value, list):
        return [normalize_json(item) for item in value]
    raise ARC3ValidationError(f"value of type {type(value).__name__} is not canonical JSON data")


def canonical_json(value: object) -> str:
    """Serialize *value* using the trace contract's deterministic JSON form."""

    return json.dumps(
        normalize_json(value),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def canonical_bytes(value: object) -> bytes:
    """Return the canonical UTF-8 representation of *value*."""

    return canonical_json(value).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    """Hash bytes and retain the algorithm tag in the external identity."""

    return f"{SHA256_PREFIX}{hashlib.sha256(data).hexdigest()}"


def sha256_json(value: object) -> str:
    """Hash a canonical JSON value."""

    return sha256_bytes(canonical_bytes(value))


def is_sha256(value: object) -> bool:
    """Return whether *value* is a lowercase tagged SHA-256 digest."""

    if not isinstance(value, str) or not value.startswith(SHA256_PREFIX):
        return False
    digest = value.removeprefix(SHA256_PREFIX)
    return len(digest) == SHA256_HEX_LENGTH and all(char in "0123456789abcdef" for char in digest)


def require_sha256(value: object, *, field: str) -> str:
    """Validate and return a tagged SHA-256 digest."""

    if not is_sha256(value):
        raise ARC3ValidationError(f"{field} must be a lowercase tagged SHA-256 digest")
    assert isinstance(value, str)  # narrowed by is_sha256
    return value


def parse_json_bytes(data: bytes) -> JSONValue:
    """Parse JSON and revalidate it against the canonical value domain."""

    try:
        parsed: object = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ARC3ValidationError(f"invalid UTF-8 JSON: {error}") from error
    return normalize_json(parsed)


def require_object(value: JSONValue, *, field: str = "value") -> dict[str, JSONValue]:
    """Narrow a JSON value to an object for strict callers."""

    if not isinstance(value, dict):
        raise ARC3ValidationError(f"{field} must be a JSON object")
    return value


def require_array(value: JSONValue, *, field: str = "value") -> list[JSONValue]:
    """Narrow a JSON value to an array for strict callers."""

    if not isinstance(value, list):
        raise ARC3ValidationError(f"{field} must be a JSON array")
    return value


def require_string_sequence(value: JSONValue, *, field: str) -> tuple[str, ...]:
    """Validate a JSON array containing strings only."""

    items = require_array(value, field=field)
    if not all(isinstance(item, str) for item in items):
        raise ARC3ValidationError(f"{field} must contain only strings")
    return tuple(item for item in items if isinstance(item, str))


def json_sequence(value: Sequence[object]) -> list[JSONValue]:
    """Normalize a statically typed sequence for a JSON payload."""

    return [normalize_json(item) for item in value]
