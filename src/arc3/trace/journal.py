"""Append-only JSONL journal, recovery, chunk sealing, and verification."""

from __future__ import annotations

import gzip
import os
import threading
import uuid
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Final

from arc3.errors import ARC3ValidationError, TraceIntegrityError
from arc3.types import JSONValue, StateScope

from .blob import BlobStore
from .canonical import (
    canonical_bytes,
    parse_json_bytes,
    require_array,
    require_object,
    require_sha256,
    sha256_bytes,
    sha256_json,
)
from .schema import (
    MANIFEST_SCHEMA,
    CodeIdentity,
    SourceIdentity,
    TraceEvent,
    utc_now,
)

_NEWLINE: Final = b"\n"


@dataclass(frozen=True, slots=True)
class RecoveryReceipt:
    """Evidence of bytes discarded after an interrupted append."""

    path: Path
    original_byte_length: int
    recovered_byte_length: int
    discarded_byte_length: int


@dataclass(frozen=True, slots=True)
class ChunkManifestEntry:
    """Immutable facts about one sealed journal chunk."""

    sequence: int
    path: str
    compression: str | None
    chunk_hash: str
    stored_hash: str
    byte_length: int
    stored_byte_length: int
    event_count: int
    first_event_id: str
    last_event_id: str
    first_event_hash: str
    last_event_hash: str
    sealed_at: str
    compressed_copy_path: str | None = None
    compressed_copy_hash: str | None = None

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "sequence": self.sequence,
            "path": self.path,
            "compression": self.compression,
            "chunk_hash": self.chunk_hash,
            "stored_hash": self.stored_hash,
            "byte_length": self.byte_length,
            "stored_byte_length": self.stored_byte_length,
            "event_count": self.event_count,
            "first_event_id": self.first_event_id,
            "last_event_id": self.last_event_id,
            "first_event_hash": self.first_event_hash,
            "last_event_hash": self.last_event_hash,
            "sealed_at": self.sealed_at,
            "compressed_copy_path": self.compressed_copy_path,
            "compressed_copy_hash": self.compressed_copy_hash,
        }

    @classmethod
    def from_dict(cls, raw: JSONValue) -> ChunkManifestEntry:
        data = require_object(raw, field="manifest chunk")

        def text(key: str) -> str:
            value = data.get(key)
            if not isinstance(value, str) or not value:
                raise TraceIntegrityError(f"manifest chunk {key} must be a non-empty string")
            return value

        def integer(key: str) -> int:
            value = data.get(key)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise TraceIntegrityError(f"manifest chunk {key} must be a non-negative integer")
            return value

        compression_value = data.get("compression")
        if compression_value not in {None, "gzip"}:
            raise TraceIntegrityError("manifest chunk compression must be null or gzip")
        copy_path = data.get("compressed_copy_path")
        copy_hash = data.get("compressed_copy_hash")
        if copy_path is not None and not isinstance(copy_path, str):
            raise TraceIntegrityError("compressed_copy_path must be a string or null")
        if copy_hash is not None and not isinstance(copy_hash, str):
            raise TraceIntegrityError("compressed_copy_hash must be a string or null")
        if isinstance(copy_hash, str):
            require_sha256(copy_hash, field="compressed_copy_hash")
        entry = cls(
            sequence=integer("sequence"),
            path=text("path"),
            compression=compression_value,
            chunk_hash=text("chunk_hash"),
            stored_hash=text("stored_hash"),
            byte_length=integer("byte_length"),
            stored_byte_length=integer("stored_byte_length"),
            event_count=integer("event_count"),
            first_event_id=text("first_event_id"),
            last_event_id=text("last_event_id"),
            first_event_hash=text("first_event_hash"),
            last_event_hash=text("last_event_hash"),
            sealed_at=text("sealed_at"),
            compressed_copy_path=copy_path,
            compressed_copy_hash=copy_hash,
        )
        for field_name, hash_value in {
            "chunk_hash": entry.chunk_hash,
            "stored_hash": entry.stored_hash,
            "first_event_hash": entry.first_event_hash,
            "last_event_hash": entry.last_event_hash,
        }.items():
            require_sha256(hash_value, field=field_name)
        if entry.sequence <= 0 or entry.event_count <= 0:
            raise TraceIntegrityError("manifest sequence and event_count must be positive")
        return entry


@dataclass(frozen=True, slots=True)
class RunManifest:
    """Hash-protected inventory of sealed chunks for one run."""

    run_id: str
    created_at: str
    updated_at: str
    chunks: tuple[ChunkManifestEntry, ...]
    manifest_hash: str
    schema: str = MANIFEST_SCHEMA

    def to_dict(self, *, include_hash: bool = True) -> dict[str, JSONValue]:
        result: dict[str, JSONValue] = {
            "schema": self.schema,
            "run_id": self.run_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "chunks": [chunk.to_dict() for chunk in self.chunks],
        }
        if include_hash:
            result["manifest_hash"] = self.manifest_hash
        return result

    def computed_hash(self) -> str:
        return sha256_json(self.to_dict(include_hash=False))

    def verify_hash(self) -> None:
        require_sha256(self.manifest_hash, field="manifest_hash")
        if self.computed_hash() != self.manifest_hash:
            raise TraceIntegrityError("run manifest hash mismatch")

    @classmethod
    def empty(cls, run_id: str) -> RunManifest:
        now = utc_now()
        raw = cls(
            run_id=run_id,
            created_at=now,
            updated_at=now,
            chunks=(),
            manifest_hash="sha256:" + "0" * 64,
        )
        return cls(
            run_id=raw.run_id,
            created_at=raw.created_at,
            updated_at=raw.updated_at,
            chunks=raw.chunks,
            manifest_hash=raw.computed_hash(),
        )

    def with_chunk(self, entry: ChunkManifestEntry) -> RunManifest:
        raw = RunManifest(
            run_id=self.run_id,
            created_at=self.created_at,
            updated_at=utc_now(),
            chunks=(*self.chunks, entry),
            manifest_hash="sha256:" + "0" * 64,
        )
        return RunManifest(
            run_id=raw.run_id,
            created_at=raw.created_at,
            updated_at=raw.updated_at,
            chunks=raw.chunks,
            manifest_hash=raw.computed_hash(),
        )

    @classmethod
    def from_dict(cls, raw: JSONValue) -> RunManifest:
        data = require_object(raw, field="run manifest")
        schema = data.get("schema")
        run_id = data.get("run_id")
        created = data.get("created_at")
        updated = data.get("updated_at")
        manifest_hash = data.get("manifest_hash")
        if schema != MANIFEST_SCHEMA:
            raise TraceIntegrityError(f"unsupported run manifest schema: {schema!r}")
        if not all(
            isinstance(item, str) and item for item in (run_id, created, updated, manifest_hash)
        ):
            raise TraceIntegrityError("run manifest string identities are invalid")
        assert isinstance(run_id, str)
        assert isinstance(created, str)
        assert isinstance(updated, str)
        assert isinstance(manifest_hash, str)
        chunks = tuple(
            ChunkManifestEntry.from_dict(item)
            for item in require_array(data.get("chunks"), field="manifest chunks")
        )
        manifest = cls(
            run_id=run_id,
            created_at=created,
            updated_at=updated,
            chunks=chunks,
            manifest_hash=manifest_hash,
        )
        manifest.verify_hash()
        return manifest


def recover_partial_line(path: str | Path) -> RecoveryReceipt:
    """Discard only an unterminated final JSONL fragment after interruption."""

    journal_path = Path(path)
    if not journal_path.exists():
        return RecoveryReceipt(journal_path, 0, 0, 0)
    data = journal_path.read_bytes()
    original_length = len(data)
    if not data or data.endswith(_NEWLINE):
        return RecoveryReceipt(journal_path, original_length, original_length, 0)
    last_newline = data.rfind(_NEWLINE)
    recovered = data[: last_newline + 1] if last_newline >= 0 else b""
    with journal_path.open("r+b") as handle:
        handle.truncate(len(recovered))
        handle.flush()
        os.fsync(handle.fileno())
    return RecoveryReceipt(
        journal_path,
        original_length,
        len(recovered),
        original_length - len(recovered),
    )


def _events_from_jsonl(content: bytes, *, path: Path) -> list[TraceEvent]:
    if content and not content.endswith(_NEWLINE):
        raise TraceIntegrityError(f"journal chunk contains a partial final line: {path}")
    events: list[TraceEvent] = []
    for line_number, line in enumerate(content.splitlines(), start=1):
        if not line.strip():
            raise TraceIntegrityError(f"blank JSONL line at {path}:{line_number}")
        try:
            parsed = require_object(parse_json_bytes(line), field="event envelope")
            event = TraceEvent.from_dict(parsed)
        except (ARC3ValidationError, TraceIntegrityError) as error:
            raise TraceIntegrityError(f"invalid event at {path}:{line_number}: {error}") from error
        events.append(event)
    return events


class EventJournal:
    """Single-writer append journal with independently verifiable sealed chunks."""

    def __init__(
        self,
        root: str | Path,
        *,
        run_id: str,
        flush_every: int = 1,
        fsync_on_flush: bool = True,
    ) -> None:
        if not run_id:
            raise ARC3ValidationError("run_id must be non-empty")
        if isinstance(flush_every, bool) or flush_every <= 0:
            raise ARC3ValidationError("flush_every must be a positive integer")
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id
        self.flush_every = flush_every
        self.fsync_on_flush = fsync_on_flush
        self.active_path = self.root / "active.jsonl"
        self.manifest_path = self.root / "manifest.json"
        self.blobs = BlobStore(self.root / "blobs")
        self._lock = threading.RLock()
        self._pending_since_flush = 0
        self._closed = False
        self.recovery_receipt = recover_partial_line(self.active_path)
        self._manifest = self._load_manifest()
        if self._manifest.run_id != self.run_id:
            raise TraceIntegrityError(
                f"manifest run_id {self._manifest.run_id!r} does not match {self.run_id!r}"
            )
        sealed_events = self._verify_sealed_chunks()
        active_events = _events_from_jsonl(
            self.active_path.read_bytes() if self.active_path.exists() else b"",
            path=self.active_path,
        )
        expected_previous = sealed_events[-1].event_hash if sealed_events else None
        self._verify_segment(active_events, expected_previous=expected_previous)
        self._event_ids = {event.event_id for event in (*sealed_events, *active_events)}
        if len(self._event_ids) != len(sealed_events) + len(active_events):
            raise TraceIntegrityError("duplicate event_id across sealed and active journal data")
        all_events = [*sealed_events, *active_events]
        self._tail_event_id = all_events[-1].event_id if all_events else None
        self._tail_hash = all_events[-1].event_hash if all_events else None
        self._active_event_count = len(active_events)
        self._handle: BinaryIO = self.active_path.open("ab")

    @property
    def tail_event_id(self) -> str | None:
        return self._tail_event_id

    @property
    def tail_hash(self) -> str | None:
        return self._tail_hash

    @property
    def event_count(self) -> int:
        return len(self._event_ids)

    @property
    def manifest(self) -> RunManifest:
        return self._manifest

    def _load_manifest(self) -> RunManifest:
        if not self.manifest_path.exists():
            return RunManifest.empty(self.run_id)
        try:
            parsed = parse_json_bytes(self.manifest_path.read_bytes())
            return RunManifest.from_dict(parsed)
        except ARC3ValidationError as error:
            raise TraceIntegrityError(f"invalid run manifest: {error}") from error

    def _chunk_stored_bytes(self, entry: ChunkManifestEntry) -> bytes:
        candidate = (self.root / entry.path).resolve()
        try:
            candidate.relative_to(self.root.resolve())
        except ValueError as error:
            raise TraceIntegrityError(
                f"manifest path escapes trace root: {entry.path!r}"
            ) from error
        try:
            return candidate.read_bytes()
        except FileNotFoundError as error:
            raise TraceIntegrityError(f"missing sealed chunk: {entry.path}") from error

    def _chunk_content(self, entry: ChunkManifestEntry) -> bytes:
        stored = self._chunk_stored_bytes(entry)
        if len(stored) != entry.stored_byte_length or sha256_bytes(stored) != entry.stored_hash:
            raise TraceIntegrityError(f"stored chunk identity mismatch: {entry.path}")
        if entry.compression == "gzip":
            try:
                content = gzip.decompress(stored)
            except (gzip.BadGzipFile, EOFError) as error:
                raise TraceIntegrityError(f"invalid gzip chunk: {entry.path}") from error
        else:
            content = stored
        if len(content) != entry.byte_length or sha256_bytes(content) != entry.chunk_hash:
            raise TraceIntegrityError(f"uncompressed chunk identity mismatch: {entry.path}")
        if entry.compressed_copy_path is not None:
            compressed_path = self.root / entry.compressed_copy_path
            try:
                compressed = compressed_path.read_bytes()
            except FileNotFoundError as error:
                raise TraceIntegrityError(
                    f"missing compressed chunk copy: {entry.compressed_copy_path}"
                ) from error
            if (
                entry.compressed_copy_hash is None
                or sha256_bytes(compressed) != entry.compressed_copy_hash
            ):
                raise TraceIntegrityError("compressed chunk copy hash mismatch")
            try:
                if gzip.decompress(compressed) != content:
                    raise TraceIntegrityError("compressed chunk copy changes uncompressed bytes")
            except (gzip.BadGzipFile, EOFError) as error:
                raise TraceIntegrityError("compressed chunk copy is invalid gzip") from error
        return content

    @staticmethod
    def _verify_segment(events: list[TraceEvent], *, expected_previous: str | None) -> None:
        previous = expected_previous
        ids: set[str] = set()
        for event in events:
            event.verify_hash()
            if event.event_id in ids:
                raise TraceIntegrityError(f"duplicate event_id: {event.event_id}")
            if event.previous_event_hash != previous:
                raise TraceIntegrityError(
                    f"broken previous hash at {event.event_id}: "
                    f"expected {previous!r}, got {event.previous_event_hash!r}"
                )
            ids.add(event.event_id)
            previous = event.event_hash

    def _verify_sealed_chunks(self) -> list[TraceEvent]:
        self._manifest.verify_hash()
        events: list[TraceEvent] = []
        prior_hash: str | None = None
        expected_sequence = 1
        event_ids: set[str] = set()
        for entry in self._manifest.chunks:
            if entry.sequence != expected_sequence:
                raise TraceIntegrityError("manifest chunk sequence is not contiguous")
            content = self._chunk_content(entry)
            chunk_events = _events_from_jsonl(content, path=self.root / entry.path)
            self._verify_segment(chunk_events, expected_previous=prior_hash)
            if len(chunk_events) != entry.event_count:
                raise TraceIntegrityError(f"chunk event count mismatch: {entry.path}")
            if not chunk_events:  # pragma: no cover - positive count checked on parse
                raise TraceIntegrityError(f"sealed chunk is empty: {entry.path}")
            first = chunk_events[0]
            last = chunk_events[-1]
            observed_metadata = (
                first.event_id,
                last.event_id,
                first.event_hash,
                last.event_hash,
            )
            expected_metadata = (
                entry.first_event_id,
                entry.last_event_id,
                entry.first_event_hash,
                entry.last_event_hash,
            )
            if observed_metadata != expected_metadata:
                raise TraceIntegrityError(f"chunk boundary metadata mismatch: {entry.path}")
            for event in chunk_events:
                if event.event_id in event_ids:
                    raise TraceIntegrityError(f"duplicate event_id: {event.event_id}")
                event_ids.add(event.event_id)
            events.extend(chunk_events)
            prior_hash = last.event_hash
            expected_sequence += 1
        return events

    def append(
        self,
        *,
        episode_id: str,
        game_id: str,
        level_index: int,
        step_index: int,
        event_type: str,
        source: SourceIdentity,
        scope: StateScope | str,
        payload: Mapping[str, object],
        code_identity: CodeIdentity,
        event_id: str | None = None,
        occurred_at: str | None = None,
    ) -> TraceEvent:
        """Create and durably append an event linked to the current tail."""

        with self._lock:
            self._ensure_open()
            event = TraceEvent.create(
                run_id=self.run_id,
                episode_id=episode_id,
                game_id=game_id,
                level_index=level_index,
                step_index=step_index,
                event_type=event_type,
                source=source,
                scope=scope,
                payload=payload,
                code_identity=code_identity,
                previous_event_hash=self._tail_hash,
                event_id=event_id,
                occurred_at=occurred_at,
            )
            self.append_event(event)
            return event

    def append_event(self, event: TraceEvent) -> None:
        """Append a pre-built event only when identity and linkage match."""

        with self._lock:
            self._ensure_open()
            event.verify_hash()
            if event.run_id != self.run_id:
                raise TraceIntegrityError("event run_id does not match journal")
            if event.event_id in self._event_ids:
                raise TraceIntegrityError(f"duplicate event_id: {event.event_id}")
            if event.previous_event_hash != self._tail_hash:
                raise TraceIntegrityError(
                    f"event previous hash {event.previous_event_hash!r} does not match "
                    f"journal tail {self._tail_hash!r}"
                )
            self._handle.write(canonical_bytes(event.to_dict()) + _NEWLINE)
            self._pending_since_flush += 1
            self._active_event_count += 1
            self._event_ids.add(event.event_id)
            self._tail_event_id = event.event_id
            self._tail_hash = event.event_hash
            if self._pending_since_flush >= self.flush_every:
                self.flush()

    def flush(self) -> None:
        """Flush userspace buffers and optionally fsync the active journal."""

        with self._lock:
            self._ensure_open()
            self._handle.flush()
            if self.fsync_on_flush:
                os.fsync(self._handle.fileno())
            self._pending_since_flush = 0

    def _write_manifest(self, manifest: RunManifest) -> None:
        temporary = self.manifest_path.with_name(
            f".{self.manifest_path.name}.{uuid.uuid4().hex}.tmp"
        )
        try:
            with temporary.open("xb") as handle:
                handle.write(canonical_bytes(manifest.to_dict()) + _NEWLINE)
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(self.manifest_path)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _write_file_atomic(path: Path, content: bytes) -> None:
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("xb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)

    def seal(
        self,
        *,
        compress: bool = False,
        remove_uncompressed: bool = False,
    ) -> ChunkManifestEntry:
        """Seal the active chunk, optionally retaining only a verified gzip copy."""

        if remove_uncompressed and not compress:
            raise ARC3ValidationError("remove_uncompressed requires compress=True")
        with self._lock:
            self._ensure_open()
            self.flush()
            if self._active_event_count == 0:
                raise TraceIntegrityError("cannot seal an empty active journal")
            self._handle.close()
            content = self.active_path.read_bytes()
            events = _events_from_jsonl(content, path=self.active_path)
            if len(events) != self._active_event_count:
                raise TraceIntegrityError("active event count changed before sealing")
            sequence = len(self._manifest.chunks) + 1
            plain_name = f"chunk-{sequence:06d}.jsonl"
            plain_path = self.root / plain_name
            if plain_path.exists():
                raise TraceIntegrityError(f"refusing to overwrite sealed chunk: {plain_name}")
            self.active_path.replace(plain_path)

            compressed_name: str | None = None
            compressed_hash: str | None = None
            primary_path = plain_path
            primary_content = content
            compression: str | None = None
            if compress:
                compressed = gzip.compress(content, compresslevel=9, mtime=0)
                if gzip.decompress(compressed) != content:  # pragma: no cover - library invariant
                    raise TraceIntegrityError("gzip verification changed sealed chunk bytes")
                compressed_name = f"{plain_name}.gz"
                compressed_path = self.root / compressed_name
                if compressed_path.exists():
                    raise TraceIntegrityError(
                        f"refusing to overwrite compressed chunk: {compressed_name}"
                    )
                self._write_file_atomic(compressed_path, compressed)
                compressed_hash = sha256_bytes(compressed)
                if remove_uncompressed:
                    plain_path.unlink()
                    primary_path = compressed_path
                    primary_content = compressed
                    compression = "gzip"
                    compressed_name = None
                    compressed_hash = None

            first = events[0]
            last = events[-1]
            entry = ChunkManifestEntry(
                sequence=sequence,
                path=primary_path.name,
                compression=compression,
                chunk_hash=sha256_bytes(content),
                stored_hash=sha256_bytes(primary_content),
                byte_length=len(content),
                stored_byte_length=len(primary_content),
                event_count=len(events),
                first_event_id=first.event_id,
                last_event_id=last.event_id,
                first_event_hash=first.event_hash,
                last_event_hash=last.event_hash,
                sealed_at=utc_now(),
                compressed_copy_path=compressed_name,
                compressed_copy_hash=compressed_hash,
            )
            updated_manifest = self._manifest.with_chunk(entry)
            self._write_manifest(updated_manifest)
            self._manifest = updated_manifest
            self._active_event_count = 0
            self._pending_since_flush = 0
            self._handle = self.active_path.open("ab")
            return entry

    def verify_manifest(self, *, include_active: bool = True) -> tuple[TraceEvent, ...]:
        """Independently verify all chunk bytes, hashes, links, and active data."""

        with self._lock:
            self._ensure_open()
            self.flush()
            sealed = self._verify_sealed_chunks()
            if not include_active:
                return tuple(sealed)
            active = _events_from_jsonl(self.active_path.read_bytes(), path=self.active_path)
            prior = sealed[-1].event_hash if sealed else None
            self._verify_segment(active, expected_previous=prior)
            ids = [event.event_id for event in (*sealed, *active)]
            if len(set(ids)) != len(ids):
                raise TraceIntegrityError("duplicate event_id across journal")
            return tuple((*sealed, *active))

    def verify_referenced_blobs(self) -> tuple[str, ...]:
        """Verify every recursively referenced ``blob_hash`` in the journal."""

        verified: set[str] = set()

        def visit(value: JSONValue) -> None:
            if isinstance(value, dict):
                for key, child in value.items():
                    if key == "blob_hash":
                        if not isinstance(child, str):
                            raise TraceIntegrityError("blob_hash reference is not a string")
                        self.blobs.verify(child)
                        verified.add(child)
                    else:
                        visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)

        for event in self.verify_manifest():
            visit(event.payload)
        return tuple(sorted(verified))

    def iter_events(self, *, verify: bool = True) -> Iterator[TraceEvent]:
        """Iterate in append order, verifying by default."""

        if verify:
            yield from self.verify_manifest()
            return
        with self._lock:
            self._ensure_open()
            self.flush()
            for entry in self._manifest.chunks:
                yield from _events_from_jsonl(
                    self._chunk_content(entry), path=self.root / entry.path
                )
            yield from _events_from_jsonl(self.active_path.read_bytes(), path=self.active_path)

    def chunk_hashes(self) -> tuple[str, ...]:
        """Return the ordered source chunk hashes for derived summaries."""

        return tuple(entry.chunk_hash for entry in self._manifest.chunks)

    def close(self) -> None:
        """Flush and close the active writer without sealing it."""

        with self._lock:
            if self._closed:
                return
            self._handle.flush()
            if self.fsync_on_flush:
                os.fsync(self._handle.fileno())
            self._handle.close()
            self._closed = True

    def _ensure_open(self) -> None:
        if self._closed:
            raise TraceIntegrityError("journal is closed")

    def __enter__(self) -> EventJournal:
        self._ensure_open()
        return self

    def __exit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        self.close()


# Compact compatibility names for downstream controller code.
TraceJournal = EventJournal
Journal = EventJournal
