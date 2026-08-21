"""Episode-scoped memory store."""

from __future__ import annotations

from arc3.types import StateScope

from .models import MemoryContractError, MemoryRecord, StoreResult
from .store import BoundedMemoryStore


class EpisodeMemoryStore(BoundedMemoryStore):
    """Retain records visible only in one level/episode."""

    def __init__(
        self,
        *,
        episode_id: str,
        game_scope_hash: str,
        max_records: int,
        max_bytes: int,
    ) -> None:
        if not episode_id:
            raise MemoryContractError("episode_id must be non-empty")
        MemoryRecord._validate_scope_hash(game_scope_hash, field_name="game_scope_hash")
        super().__init__(
            allowed_scope=StateScope.EPISODE,
            max_records=max_records,
            max_bytes=max_bytes,
        )
        self.episode_id = episode_id
        self.game_scope_hash = game_scope_hash

    def add(self, record: MemoryRecord, *, sequence: int) -> StoreResult:
        if record.episode_id != self.episode_id or record.game_scope_hash != self.game_scope_hash:
            raise MemoryContractError("episode memory record crosses its fixed scope")
        return super().add(record, sequence=sequence)
