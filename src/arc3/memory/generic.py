"""Generic cross-game structural memory store."""

from __future__ import annotations

from arc3.types import StateScope

from .store import BoundedMemoryStore


class GenericMemoryStore(BoundedMemoryStore):
    """Retain only rules whose record has earned generic scope."""

    def __init__(self, *, max_records: int, max_bytes: int) -> None:
        super().__init__(
            allowed_scope=StateScope.GENERIC,
            max_records=max_records,
            max_bytes=max_bytes,
        )

    # The base scope check plus MemoryRecord's two-origin gate are sufficient.
