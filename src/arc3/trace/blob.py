"""Content-addressed, deduplicated storage for trace frames and deltas."""

from __future__ import annotations

import os
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from arc3.errors import ARC3ValidationError, TraceIntegrityError
from arc3.types import JSONValue

from .canonical import (
    canonical_bytes,
    parse_json_bytes,
    require_object,
    require_sha256,
    sha256_bytes,
)


@dataclass(frozen=True, slots=True)
class BlobReceipt:
    """Stable identity and storage facts for one immutable blob."""

    blob_hash: str
    byte_length: int
    media_type: str
    created: bool


@dataclass(frozen=True, slots=True)
class FrameBlobReceipt:
    """Observation descriptor suitable for an ``observation.received`` event."""

    blob_hash: str
    frame_hash: str
    width: int
    height: int
    palette: tuple[int, ...]
    byte_length: int
    created: bool

    def to_payload(self) -> dict[str, JSONValue]:
        """Return the normalized observation frame descriptor."""

        return {
            "blob_hash": self.blob_hash,
            "frame_hash": self.frame_hash,
            "width": self.width,
            "height": self.height,
            "palette": list(self.palette),
        }


class BlobStore:
    """Write-once blob store partitioned by SHA-256 prefix."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, blob_hash: str) -> Path:
        """Resolve a validated blob identity without accepting path input."""

        digest = require_sha256(blob_hash, field="blob_hash").removeprefix("sha256:")
        return self.root / "sha256" / digest[:2] / f"{digest}.blob"

    def put_bytes(
        self, data: bytes, *, media_type: str = "application/octet-stream"
    ) -> BlobReceipt:
        """Store bytes once, verifying any existing identity collision."""

        if not media_type:
            raise ARC3ValidationError("blob media_type must be non-empty")
        blob_hash = sha256_bytes(data)
        path = self.path_for(blob_hash)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            existing = path.read_bytes()
            if existing != data:
                raise TraceIntegrityError(f"content-address collision at {path}")
            return BlobReceipt(blob_hash, len(data), media_type, created=False)

        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("xb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                temporary.replace(path)
            except FileExistsError:  # another writer won the same content race
                if path.read_bytes() != data:
                    raise TraceIntegrityError(f"content-address collision at {path}") from None
        finally:
            temporary.unlink(missing_ok=True)
        return BlobReceipt(blob_hash, len(data), media_type, created=True)

    def put_json(self, value: object, *, media_type: str = "application/json") -> BlobReceipt:
        """Store canonical JSON by content identity."""

        return self.put_bytes(canonical_bytes(value), media_type=media_type)

    def get_bytes(self, blob_hash: str) -> bytes:
        """Read and verify a blob before returning its content."""

        path = self.path_for(blob_hash)
        try:
            content = path.read_bytes()
        except FileNotFoundError as error:
            raise TraceIntegrityError(f"missing trace blob: {blob_hash}") from error
        observed = sha256_bytes(content)
        if observed != blob_hash:
            raise TraceIntegrityError(
                f"trace blob hash mismatch at {path}: expected {blob_hash}, observed {observed}"
            )
        return content

    def get_json(self, blob_hash: str) -> JSONValue:
        """Read, verify, and parse a canonical JSON blob."""

        return parse_json_bytes(self.get_bytes(blob_hash))

    def verify(self, blob_hash: str) -> int:
        """Verify one blob and return its byte length."""

        return len(self.get_bytes(blob_hash))

    def put_frame(self, frame: Sequence[Sequence[int]]) -> FrameBlobReceipt:
        """Validate and store an ARC frame as canonical JSON."""

        normalized = _normalize_frame(frame)
        content = canonical_bytes(normalized)
        receipt = self.put_bytes(content, media_type="application/vnd.arc3.frame+json")
        height = len(normalized)
        width = len(normalized[0])
        palette = tuple(sorted({cell for row in normalized for cell in row}))
        return FrameBlobReceipt(
            blob_hash=receipt.blob_hash,
            frame_hash=sha256_bytes(content),
            width=width,
            height=height,
            palette=palette,
            byte_length=receipt.byte_length,
            created=receipt.created,
        )

    def get_frame(self, blob_hash: str) -> tuple[tuple[int, ...], ...]:
        """Load a stored frame and revalidate its dimensions and palette."""

        value = self.get_json(blob_hash)
        if not isinstance(value, list):
            raise TraceIntegrityError("frame blob is not a JSON array")
        rows: list[list[int]] = []
        for raw_row in value:
            if not isinstance(raw_row, list):
                raise TraceIntegrityError("frame blob rows must be JSON arrays")
            row: list[int] = []
            for cell in raw_row:
                if isinstance(cell, bool) or not isinstance(cell, int):
                    raise TraceIntegrityError("frame blob cells must be integers")
                row.append(cell)
            rows.append(row)
        try:
            normalized = _normalize_frame(rows)
        except ARC3ValidationError as error:
            raise TraceIntegrityError(f"invalid frame blob: {error}") from error
        return tuple(tuple(row) for row in normalized)

    def put_delta(self, delta: Mapping[str, object]) -> BlobReceipt:
        """Store a structured cell/component delta by canonical identity."""

        return self.put_json(delta, media_type="application/vnd.arc3.delta+json")

    def get_delta(self, blob_hash: str) -> dict[str, JSONValue]:
        """Load and verify a structured delta object."""

        return require_object(self.get_json(blob_hash), field="delta blob")


def _normalize_frame(frame: Sequence[Sequence[int]]) -> list[list[int]]:
    if not frame or len(frame) > 64:
        raise ARC3ValidationError("frame height must be within 1..64")
    width = len(frame[0])
    if not 1 <= width <= 64:
        raise ARC3ValidationError("frame width must be within 1..64")
    normalized: list[list[int]] = []
    for row in frame:
        if len(row) != width:
            raise ARC3ValidationError("frame must be rectangular")
        normalized_row: list[int] = []
        for cell in row:
            if isinstance(cell, bool) or not isinstance(cell, int) or not 0 <= cell <= 15:
                raise ARC3ValidationError("frame cells must be integers within 0..15")
            normalized_row.append(cell)
        normalized.append(normalized_row)
    return normalized
