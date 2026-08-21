"""Small structured JSON logging surface with recursive secret redaction."""

from __future__ import annotations

import json
import logging as stdlib_logging
import re
import sys
from collections.abc import Iterable, Mapping
from dataclasses import fields, is_dataclass
from datetime import UTC, date, datetime
from enum import Enum
from pathlib import Path
from types import TracebackType
from typing import IO

from arc3.types import JSONValue

REDACTED = "[REDACTED]"

_SENSITIVE_KEY_PARTS = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "auth_token",
        "cookie",
        "credential",
        "kaggle_key",
        "password",
        "private_key",
        "secret",
        "session",
        "token",
        "x_api_key",
    }
)
_SECRET_PATTERNS = (
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+"),
    re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"(?i)(https?://[^\s/:]+:)[^@\s]+(@)"),
)
_STANDARD_RECORD_KEYS = frozenset(stdlib_logging.LogRecord("", 0, "", 0, "", (), None).__dict__)


def _is_sensitive_key(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", "_", key.casefold()).strip("_")
    return any(
        normalized == part or normalized.startswith(f"{part}_") or normalized.endswith(f"_{part}")
        for part in _SENSITIVE_KEY_PARTS
    )


def _redact_string(value: str, extra_secrets: tuple[str, ...]) -> str:
    redacted = value
    for secret in extra_secrets:
        if secret:
            redacted = redacted.replace(secret, REDACTED)
    for pattern in _SECRET_PATTERNS:
        if pattern.pattern.startswith("(?i)(https?"):
            redacted = pattern.sub(r"\1" + REDACTED + r"\2", redacted)
        else:
            redacted = pattern.sub(REDACTED, redacted)
    return redacted


def redact(
    value: object,
    *,
    extra_secrets: Iterable[str] = (),
) -> JSONValue:
    """Convert arbitrary nested data into a redacted JSON-compatible value.

    Keys are checked at every mapping/dataclass depth. Cycles are represented
    explicitly and byte content is never logged.
    """

    secrets = tuple(secret for secret in extra_secrets if secret)
    return _redact_recursive(value, secrets=secrets, seen=set())


def _redact_recursive(
    value: object,
    *,
    secrets: tuple[str, ...],
    seen: set[int],
) -> JSONValue:
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return str(value)
        return value
    if isinstance(value, str):
        return _redact_string(value, secrets)
    if isinstance(value, bytes):
        return f"<bytes:{len(value)}>"
    if isinstance(value, Enum):
        return _redact_recursive(value.value, secrets=secrets, seen=seen)
    if isinstance(value, Path):
        return _redact_string(str(value), secrets)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, BaseException):
        return {
            "type": type(value).__name__,
            "message": _redact_string(str(value), secrets),
        }

    identity = id(value)
    if identity in seen:
        return "<cycle>"

    if is_dataclass(value) and not isinstance(value, type):
        seen.add(identity)
        try:
            result: dict[str, JSONValue] = {}
            for field in fields(value):
                result[field.name] = (
                    REDACTED
                    if _is_sensitive_key(field.name)
                    else _redact_recursive(getattr(value, field.name), secrets=secrets, seen=seen)
                )
            return result
        finally:
            seen.remove(identity)

    if isinstance(value, Mapping):
        seen.add(identity)
        try:
            mapped: dict[str, JSONValue] = {}
            for raw_key, item in value.items():
                key = _redact_string(str(raw_key), secrets)
                mapped[key] = (
                    REDACTED
                    if _is_sensitive_key(str(raw_key))
                    else _redact_recursive(item, secrets=secrets, seen=seen)
                )
            return mapped
        finally:
            seen.remove(identity)

    if isinstance(value, (list, tuple)):
        seen.add(identity)
        try:
            return [_redact_recursive(item, secrets=secrets, seen=seen) for item in value]
        finally:
            seen.remove(identity)

    if isinstance(value, (set, frozenset)):
        seen.add(identity)
        try:
            normalized = [_redact_recursive(item, secrets=secrets, seen=seen) for item in value]
            return sorted(
                normalized,
                key=lambda item: json.dumps(item, sort_keys=True, ensure_ascii=False),
            )
        finally:
            seen.remove(identity)

    # Avoid repr(value): arbitrary object representations can contain secrets.
    return f"<{type(value).__name__}>"


class StructuredJsonFormatter(stdlib_logging.Formatter):
    """One canonical JSON object per log record."""

    def __init__(self, *, extra_secrets: Iterable[str] = ()) -> None:
        super().__init__()
        self._extra_secrets = tuple(secret for secret in extra_secrets if secret)

    def format(self, record: stdlib_logging.LogRecord) -> str:
        timestamp = (
            datetime.fromtimestamp(record.created, tz=UTC)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z")
        )
        event_value = record.__dict__.get("arc3_event")
        structured_message: JSONValue | None = None
        if event_value is not None:
            event = str(event_value)
        elif isinstance(record.msg, (Mapping, list, tuple, set, frozenset)):
            event = "log.message"
            structured_message = redact(record.msg, extra_secrets=self._extra_secrets)
        else:
            event = record.getMessage()
        payload: dict[str, JSONValue] = {
            "schema": "arc3.log.v0.1",
            "timestamp": timestamp,
            "level": record.levelname,
            "logger": record.name,
            "event": _redact_string(event, self._extra_secrets),
        }

        raw_fields = record.__dict__.get("arc3_fields")
        if raw_fields is not None:
            payload["fields"] = redact(raw_fields, extra_secrets=self._extra_secrets)
        elif structured_message is not None:
            payload["fields"] = {"message": structured_message}
        else:
            extras = {
                key: value
                for key, value in record.__dict__.items()
                if key not in _STANDARD_RECORD_KEYS and not key.startswith("arc3_")
            }
            if extras:
                payload["fields"] = redact(extras, extra_secrets=self._extra_secrets)

        if record.exc_info:
            exc_type: type[BaseException] | None
            exc_value: BaseException | None
            traceback: TracebackType | None
            exc_type, exc_value, traceback = record.exc_info
            del exc_type, traceback
            if exc_value is not None:
                payload["exception"] = redact(exc_value, extra_secrets=self._extra_secrets)

        return json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )


def configure_structured_logger(
    name: str = "arc3",
    *,
    level: str | int = "INFO",
    stream: IO[str] | None = None,
    extra_secrets: Iterable[str] = (),
) -> stdlib_logging.Logger:
    """Configure an isolated, idempotent ARC3 JSON logger."""

    logger = stdlib_logging.getLogger(name)
    try:
        resolved_level = (
            stdlib_logging._nameToLevel.get(level.upper()) if isinstance(level, str) else level
        )
    except AttributeError as error:  # pragma: no cover - defensive type boundary
        raise ValueError(f"invalid logging level: {level!r}") from error
    if not isinstance(resolved_level, int):
        raise ValueError(f"invalid logging level: {level!r}")

    handler = stdlib_logging.StreamHandler(stream or sys.stderr)
    handler.setFormatter(StructuredJsonFormatter(extra_secrets=extra_secrets))
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(resolved_level)
    logger.propagate = False
    return logger


def get_logger(name: str = "arc3") -> stdlib_logging.Logger:
    """Return an ARC3 logger without mutating global logging configuration."""

    return stdlib_logging.getLogger(name)


def log_event(
    logger: stdlib_logging.Logger,
    event: str,
    *,
    level: int = stdlib_logging.INFO,
    **fields_: object,
) -> None:
    """Emit one structured event with fields held outside the message string."""

    logger.log(
        level,
        event,
        extra={"arc3_event": event, "arc3_fields": fields_},
    )


# Compatibility aliases for straightforward imports.
JsonFormatter = StructuredJsonFormatter
redact_secrets = redact
