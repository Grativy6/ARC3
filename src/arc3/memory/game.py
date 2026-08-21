"""Game-scoped cross-level memory store."""

from __future__ import annotations

from arc3.types import StateScope

from .models import MemoryContractError, MemoryRecord, StoreResult
from .store import BoundedMemoryStore


class GameMemoryStore(BoundedMemoryStore):
    """Retain learned rules across levels under one opaque scope handle."""

    def __init__(self, *, game_scope_hash: str, max_records: int, max_bytes: int) -> None:
        MemoryRecord._validate_scope_hash(game_scope_hash, field_name="game_scope_hash")
        super().__init__(
            allowed_scope=StateScope.GAME,
            max_records=max_records,
            max_bytes=max_bytes,
        )
        self.game_scope_hash = game_scope_hash

    def add(self, record: MemoryRecord, *, sequence: int) -> StoreResult:
        if record.game_scope_hash != self.game_scope_hash:
            raise MemoryContractError("game memory record crosses its fixed opaque scope")
        return super().add(record, sequence=sequence)
