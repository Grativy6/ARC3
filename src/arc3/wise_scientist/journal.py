"""Small append-only, hash-linked journal for Wise Scientist commands."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from arc3.errors import TraceIntegrityError
from arc3.trace.canonical import canonical_bytes, normalize_json, sha256_json
from arc3.types import JSONValue

_SCHEMA = "arc3.wise-scientist.event.v0.1"
_GENESIS = "sha256:" + ("0" * 64)


@dataclass(frozen=True, slots=True)
class WiseEvent:
    """One immutable event from the dedicated Wise Scientist journal."""

    sequence: int
    event_type: str
    recorded_at: str
    payload: dict[str, JSONValue]
    previous_event_hash: str
    event_hash: str

    def body(self) -> dict[str, JSONValue]:
        return {
            "schema": _SCHEMA,
            "sequence": self.sequence,
            "event_type": self.event_type,
            "recorded_at": self.recorded_at,
            "payload": self.payload,
            "previous_event_hash": self.previous_event_hash,
        }

    def to_dict(self) -> dict[str, JSONValue]:
        return {**self.body(), "event_hash": self.event_hash}


class WiseJournal:
    """Append and verify deterministic Wise Scientist event records."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._events = self.verify(self.path) if self.path.exists() else ()

    @property
    def events(self) -> tuple[WiseEvent, ...]:
        return self._events

    @property
    def tail_hash(self) -> str:
        return self._events[-1].event_hash if self._events else _GENESIS

    def append(self, event_type: str, payload: object) -> WiseEvent:
        if not isinstance(event_type, str) or not event_type.strip():
            raise TraceIntegrityError("Wise Scientist event_type must be non-empty")
        normalized = normalize_json(payload)
        if not isinstance(normalized, dict):
            raise TraceIntegrityError("Wise Scientist event payload must be an object")
        body: dict[str, JSONValue] = {
            "schema": _SCHEMA,
            "sequence": len(self._events),
            "event_type": event_type.strip(),
            "recorded_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "payload": normalized,
            "previous_event_hash": self.tail_hash,
        }
        event_hash = sha256_json(body)
        event = WiseEvent(
            sequence=len(self._events),
            event_type=event_type.strip(),
            recorded_at=str(body["recorded_at"]),
            payload=normalized,
            previous_event_hash=self.tail_hash,
            event_hash=event_hash,
        )
        line = canonical_bytes(event.to_dict()) + b"\n"
        with self.path.open("ab") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())
        self._events = (*self._events, event)
        return event

    @staticmethod
    def verify(path: str | Path) -> tuple[WiseEvent, ...]:
        source = Path(path)
        if not source.exists():
            return ()
        events: list[WiseEvent] = []
        previous = _GENESIS
        with source.open("rb") as handle:
            for line_number, raw_line in enumerate(handle, start=1):
                if not raw_line.endswith(b"\n"):
                    raise TraceIntegrityError(
                        f"Wise Scientist journal line {line_number} is incomplete"
                    )
                try:
                    raw: object = json.loads(raw_line)
                except (UnicodeDecodeError, json.JSONDecodeError) as error:
                    raise TraceIntegrityError(
                        f"Wise Scientist journal line {line_number} is invalid JSON"
                    ) from error
                normalized = normalize_json(raw)
                if not isinstance(normalized, dict):
                    raise TraceIntegrityError(
                        f"Wise Scientist journal line {line_number} is not an object"
                    )
                required = {
                    "schema",
                    "sequence",
                    "event_type",
                    "recorded_at",
                    "payload",
                    "previous_event_hash",
                    "event_hash",
                }
                if set(normalized) != required:
                    raise TraceIntegrityError(
                        f"Wise Scientist journal line {line_number} has invalid fields"
                    )
                if normalized["schema"] != _SCHEMA:
                    raise TraceIntegrityError(
                        f"Wise Scientist journal line {line_number} has invalid schema"
                    )
                if normalized["sequence"] != len(events):
                    raise TraceIntegrityError(
                        f"Wise Scientist journal line {line_number} has invalid sequence"
                    )
                if normalized["previous_event_hash"] != previous:
                    raise TraceIntegrityError(
                        f"Wise Scientist journal line {line_number} breaks the hash chain"
                    )
                payload = normalized["payload"]
                if not isinstance(payload, dict):
                    raise TraceIntegrityError(
                        f"Wise Scientist journal line {line_number} payload is not an object"
                    )
                body = {key: value for key, value in normalized.items() if key != "event_hash"}
                calculated = sha256_json(body)
                if normalized["event_hash"] != calculated:
                    raise TraceIntegrityError(
                        f"Wise Scientist journal line {line_number} hash mismatch"
                    )
                event_type = normalized["event_type"]
                recorded_at = normalized["recorded_at"]
                event_hash = normalized["event_hash"]
                if not isinstance(event_type, str) or not event_type:
                    raise TraceIntegrityError(
                        f"Wise Scientist journal line {line_number} has invalid event_type"
                    )
                if not isinstance(recorded_at, str) or not recorded_at:
                    raise TraceIntegrityError(
                        f"Wise Scientist journal line {line_number} has invalid recorded_at"
                    )
                if not isinstance(event_hash, str):
                    raise TraceIntegrityError(
                        f"Wise Scientist journal line {line_number} has invalid event_hash"
                    )
                event = WiseEvent(
                    sequence=len(events),
                    event_type=event_type,
                    recorded_at=recorded_at,
                    payload=payload,
                    previous_event_hash=previous,
                    event_hash=event_hash,
                )
                events.append(event)
                previous = event.event_hash
        return tuple(events)


__all__ = ["WiseEvent", "WiseJournal"]
