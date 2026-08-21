"""Non-destructive Trace v0.1 identity migration harness."""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from pathlib import Path

from arc3.errors import ARC3ValidationError, TraceIntegrityError
from arc3.types import JSONValue

from .canonical import (
    canonical_bytes,
    parse_json_bytes,
    require_array,
    require_object,
    require_sha256,
    sha256_bytes,
    sha256_json,
)
from .schema import EVENT_SCHEMA, MIGRATION_SCHEMA, TraceEvent, utc_now


def _read_events(path: Path) -> tuple[TraceEvent, ...]:
    try:
        content = path.read_bytes()
    except FileNotFoundError as error:
        raise TraceIntegrityError(f"migration source does not exist: {path}") from error
    if content and not content.endswith(b"\n"):
        raise TraceIntegrityError("migration source ends with a partial JSONL line")
    events: list[TraceEvent] = []
    ids: set[str] = set()
    previous: str | None = None
    for line_number, line in enumerate(content.splitlines(), start=1):
        try:
            event = TraceEvent.from_dict(
                require_object(parse_json_bytes(line), field="migration source event")
            )
        except (ARC3ValidationError, TraceIntegrityError) as error:
            raise TraceIntegrityError(
                f"invalid migration source event at line {line_number}: {error}"
            ) from error
        if event.event_id in ids:
            raise TraceIntegrityError(f"duplicate event_id in migration source: {event.event_id}")
        if events and event.previous_event_hash != previous:
            raise TraceIntegrityError(f"broken migration source chain at {event.event_id}")
        ids.add(event.event_id)
        events.append(event)
        previous = event.event_hash
    return tuple(events)


@dataclass(frozen=True, slots=True)
class MigrationManifest:
    """Receipt proving source preservation and destination identity."""

    source_path: str
    destination_path: str
    source_schema: str
    destination_schema: str
    source_hash: str
    destination_hash: str
    source_event_hashes: tuple[str, ...]
    destination_event_hashes: tuple[str, ...]
    semantic_changes: tuple[str, ...]
    replay_equivalent: bool
    created_at: str
    migration_hash: str
    schema: str = MIGRATION_SCHEMA

    def to_dict(self, *, include_hash: bool = True) -> dict[str, JSONValue]:
        result: dict[str, JSONValue] = {
            "schema": self.schema,
            "source_path": self.source_path,
            "destination_path": self.destination_path,
            "source_schema": self.source_schema,
            "destination_schema": self.destination_schema,
            "source_hash": self.source_hash,
            "destination_hash": self.destination_hash,
            "source_event_hashes": list(self.source_event_hashes),
            "destination_event_hashes": list(self.destination_event_hashes),
            "semantic_changes": list(self.semantic_changes),
            "replay_equivalent": self.replay_equivalent,
            "created_at": self.created_at,
        }
        if include_hash:
            result["migration_hash"] = self.migration_hash
        return result

    def computed_hash(self) -> str:
        return sha256_json(self.to_dict(include_hash=False))

    def verify(self) -> None:
        for field_name, value in {
            "source_hash": self.source_hash,
            "destination_hash": self.destination_hash,
            "migration_hash": self.migration_hash,
        }.items():
            try:
                require_sha256(value, field=field_name)
            except ARC3ValidationError as error:
                raise TraceIntegrityError(str(error)) from error
        if self.schema != MIGRATION_SCHEMA:
            raise TraceIntegrityError(f"unsupported migration schema: {self.schema!r}")
        if self.computed_hash() != self.migration_hash:
            raise TraceIntegrityError("migration manifest hash mismatch")

    @classmethod
    def from_dict(cls, raw: JSONValue) -> MigrationManifest:
        data = require_object(raw, field="migration manifest")

        def text(key: str) -> str:
            value = data.get(key)
            if not isinstance(value, str) or not value:
                raise TraceIntegrityError(f"migration manifest {key} must be a string")
            return value

        def strings(key: str) -> tuple[str, ...]:
            value = require_array(data.get(key), field=f"migration manifest {key}")
            if not all(isinstance(item, str) for item in value):
                raise TraceIntegrityError(f"migration manifest {key} must contain strings")
            return tuple(item for item in value if isinstance(item, str))

        replay_equivalent = data.get("replay_equivalent")
        if not isinstance(replay_equivalent, bool):
            raise TraceIntegrityError("migration replay_equivalent must be a boolean")
        manifest = cls(
            schema=text("schema"),
            source_path=text("source_path"),
            destination_path=text("destination_path"),
            source_schema=text("source_schema"),
            destination_schema=text("destination_schema"),
            source_hash=text("source_hash"),
            destination_hash=text("destination_hash"),
            source_event_hashes=strings("source_event_hashes"),
            destination_event_hashes=strings("destination_event_hashes"),
            semantic_changes=strings("semantic_changes"),
            replay_equivalent=replay_equivalent,
            created_at=text("created_at"),
            migration_hash=text("migration_hash"),
        )
        manifest.verify()
        return manifest


def _write_atomic(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def identity_migrate(
    source_path: str | Path,
    destination_path: str | Path,
    *,
    semantic_changes: tuple[str, ...] = (),
) -> tuple[Path, MigrationManifest]:
    """Re-emit Trace v0.1 canonically while proving the source was untouched."""

    source = Path(source_path)
    destination = Path(destination_path)
    if source.resolve() == destination.resolve():
        raise TraceIntegrityError("migration destination must differ from its source")
    if destination.exists():
        raise TraceIntegrityError(f"migration refuses to overwrite destination: {destination}")
    source_before = source.read_bytes()
    source_hash = sha256_bytes(source_before)
    source_events = _read_events(source)
    destination_content = b"".join(
        canonical_bytes(event.to_dict()) + b"\n" for event in source_events
    )
    _write_atomic(destination, destination_content)
    destination_events = _read_events(destination)
    source_after = source.read_bytes()
    if source_after != source_before or sha256_bytes(source_after) != source_hash:
        raise TraceIntegrityError("migration modified its source")
    source_event_hashes = tuple(event.event_hash for event in source_events)
    destination_event_hashes = tuple(event.event_hash for event in destination_events)
    replay_equivalent = source_event_hashes == destination_event_hashes
    raw_manifest = MigrationManifest(
        source_path=source.as_posix(),
        destination_path=destination.as_posix(),
        source_schema=EVENT_SCHEMA,
        destination_schema=EVENT_SCHEMA,
        source_hash=source_hash,
        destination_hash=sha256_bytes(destination_content),
        source_event_hashes=source_event_hashes,
        destination_event_hashes=destination_event_hashes,
        semantic_changes=semantic_changes,
        replay_equivalent=replay_equivalent,
        created_at=utc_now(),
        migration_hash="sha256:" + "0" * 64,
    )
    manifest = MigrationManifest(
        source_path=raw_manifest.source_path,
        destination_path=raw_manifest.destination_path,
        source_schema=raw_manifest.source_schema,
        destination_schema=raw_manifest.destination_schema,
        source_hash=raw_manifest.source_hash,
        destination_hash=raw_manifest.destination_hash,
        source_event_hashes=raw_manifest.source_event_hashes,
        destination_event_hashes=raw_manifest.destination_event_hashes,
        semantic_changes=raw_manifest.semantic_changes,
        replay_equivalent=raw_manifest.replay_equivalent,
        created_at=raw_manifest.created_at,
        migration_hash=raw_manifest.computed_hash(),
    )
    manifest_path = destination.with_suffix(destination.suffix + ".migration.json")
    _write_atomic(manifest_path, canonical_bytes(manifest.to_dict()) + b"\n")
    return manifest_path, manifest


def verify_migration_manifest(path: str | Path) -> MigrationManifest:
    """Verify a migration receipt and both referenced file identities."""

    manifest_path = Path(path)
    try:
        manifest = MigrationManifest.from_dict(parse_json_bytes(manifest_path.read_bytes()))
    except FileNotFoundError as error:
        raise TraceIntegrityError(f"migration manifest does not exist: {manifest_path}") from error
    source = Path(manifest.source_path)
    destination = Path(manifest.destination_path)
    try:
        source_hash = sha256_bytes(source.read_bytes())
        destination_hash = sha256_bytes(destination.read_bytes())
    except FileNotFoundError as error:
        raise TraceIntegrityError(f"migration input/output is missing: {error}") from error
    if source_hash != manifest.source_hash or destination_hash != manifest.destination_hash:
        raise TraceIntegrityError("migration source or destination hash mismatch")
    source_events = _read_events(source)
    destination_events = _read_events(destination)
    if tuple(event.event_hash for event in source_events) != manifest.source_event_hashes:
        raise TraceIntegrityError("migration source event identities changed")
    if tuple(event.event_hash for event in destination_events) != manifest.destination_event_hashes:
        raise TraceIntegrityError("migration destination event identities changed")
    if (
        manifest.replay_equivalent
        and manifest.source_event_hashes != manifest.destination_event_hashes
    ):
        raise TraceIntegrityError("migration claims replay equivalence without matching events")
    return manifest


# Explicit name for future versioned migration registries.
migrate_identity = identity_migrate
