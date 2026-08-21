"""Deterministic bounded storage shared by the three memory scopes."""

from __future__ import annotations

from dataclasses import dataclass

from arc3.trace.canonical import canonical_bytes
from arc3.types import JSONValue, StateScope

from .models import MemoryContractError, MemoryRecord, StoreResult


@dataclass(slots=True)
class _MemorySlot:
    record: MemoryRecord
    created_sequence: int
    last_access_sequence: int
    encoded_byte_size: int = 0

    def __post_init__(self) -> None:
        if self.encoded_byte_size == 0:
            self.encoded_byte_size = len(canonical_bytes(self.to_dict()))

    @property
    def byte_size(self) -> int:
        return self.encoded_byte_size

    @property
    def eviction_key(self) -> tuple[int, int, int, str]:
        return (
            self.record.importance,
            self.last_access_sequence,
            self.created_sequence,
            self.record.memory_id,
        )

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "record": self.record.to_dict(),
            "created_sequence": self.created_sequence,
            "last_access_sequence": self.last_access_sequence,
        }


class BoundedMemoryStore:
    """A scope-specific replaceable index with deterministic LRU/importance eviction."""

    def __init__(
        self,
        *,
        allowed_scope: StateScope,
        max_records: int,
        max_bytes: int,
    ) -> None:
        if allowed_scope not in {StateScope.EPISODE, StateScope.GAME, StateScope.GENERIC}:
            raise MemoryContractError("bounded memory store has an unsupported scope")
        if isinstance(max_records, bool) or max_records <= 0:
            raise MemoryContractError("max_records must be a positive integer")
        if isinstance(max_bytes, bool) or max_bytes <= 0:
            raise MemoryContractError("max_bytes must be a positive integer")
        self.allowed_scope = allowed_scope
        self.max_records = max_records
        self.max_bytes = max_bytes
        self._slots: dict[str, _MemorySlot] = {}
        self._slot_byte_size = 0
        self._empty_encoded_size = len(
            canonical_bytes(
                {
                    "scope": self.allowed_scope.value,
                    "max_records": self.max_records,
                    "max_bytes": self.max_bytes,
                    "slots": [],
                }
            )
        )

    @property
    def record_count(self) -> int:
        return len(self._slots)

    @property
    def byte_size(self) -> int:
        comma_bytes = max(0, self.record_count - 1)
        return self._empty_encoded_size + self._slot_byte_size + comma_bytes

    def records(self) -> tuple[MemoryRecord, ...]:
        return tuple(
            slot.record
            for slot in sorted(self._slots.values(), key=lambda item: item.created_sequence)
        )

    def slots(self) -> tuple[_MemorySlot, ...]:
        return tuple(self._slots.values())

    def add(self, record: MemoryRecord, *, sequence: int) -> StoreResult:
        if record.scope is not self.allowed_scope:
            raise MemoryContractError(
                f"{self.allowed_scope.value} store cannot retain {record.scope.value} memory"
            )
        if record.memory_id in self._slots:
            raise MemoryContractError(f"duplicate memory_id: {record.memory_id}")
        slot = _MemorySlot(record, sequence, sequence)
        self._slots[record.memory_id] = slot
        self._slot_byte_size += slot.byte_size
        evicted: list[str] = []
        while self.record_count > self.max_records or self.byte_size > self.max_bytes:
            candidate = self.eviction_candidate()
            if candidate is None:  # pragma: no cover - positive count invariant
                break
            evicted.append(candidate.record.memory_id)
            self.remove(candidate.record.memory_id)
        retained = record.memory_id in self._slots
        reason = None if retained else "record_exceeds_or_loses_bounded_eviction"
        return StoreResult(retained=retained, evicted_memory_ids=tuple(evicted), reason=reason)

    def install_slot(self, slot: _MemorySlot) -> None:
        """Restore one already validated slot without changing its access order."""

        if slot.record.scope is not self.allowed_scope:
            raise MemoryContractError("restored memory slot has the wrong scope")
        if slot.record.memory_id in self._slots:
            raise MemoryContractError(f"duplicate restored memory_id: {slot.record.memory_id}")
        self._slots[slot.record.memory_id] = slot
        self._slot_byte_size += slot.byte_size
        if self.record_count > self.max_records or self.byte_size > self.max_bytes:
            raise MemoryContractError("restored store exceeds its declared bounds")

    def remove(self, memory_id: str) -> MemoryRecord:
        try:
            slot = self._slots.pop(memory_id)
            self._slot_byte_size -= slot.byte_size
            return slot.record
        except KeyError as error:
            raise MemoryContractError(f"unknown memory_id: {memory_id}") from error

    def get(self, memory_id: str) -> MemoryRecord | None:
        slot = self._slots.get(memory_id)
        return slot.record if slot is not None else None

    def touch(self, memory_id: str, *, sequence: int) -> None:
        try:
            slot = self._slots[memory_id]
            previous_size = slot.byte_size
            slot.last_access_sequence = sequence
            slot.encoded_byte_size = len(canonical_bytes(slot.to_dict()))
            self._slot_byte_size += slot.byte_size - previous_size
        except KeyError as error:
            raise MemoryContractError(f"unknown memory_id: {memory_id}") from error

    def eviction_candidate(self) -> _MemorySlot | None:
        return min(self._slots.values(), key=lambda item: item.eviction_key, default=None)

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "scope": self.allowed_scope.value,
            "max_records": self.max_records,
            "max_bytes": self.max_bytes,
            "slots": [
                slot.to_dict()
                for slot in sorted(self._slots.values(), key=lambda item: item.created_sequence)
            ],
        }


def slot_from_dict(value: object) -> _MemorySlot:
    if not isinstance(value, dict):
        raise MemoryContractError("memory slot must be an object")
    created = value.get("created_sequence")
    accessed = value.get("last_access_sequence")
    if (
        isinstance(created, bool)
        or not isinstance(created, int)
        or created < 0
        or isinstance(accessed, bool)
        or not isinstance(accessed, int)
        or accessed < created
    ):
        raise MemoryContractError("memory slot sequences are invalid")
    return _MemorySlot(
        record=MemoryRecord.from_dict(value.get("record")),
        created_sequence=created,
        last_access_sequence=accessed,
    )
