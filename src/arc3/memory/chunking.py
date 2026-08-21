"""Bounded trace-chunk planning interfaces for long-running memory."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from arc3.trace import TraceEvent
from arc3.trace.canonical import canonical_bytes, sha256_bytes
from arc3.types import JSONValue

from .models import MemoryBudget, MemoryContractError


@dataclass(frozen=True, slots=True)
class TraceChunkPlan:
    """A non-mutating proposal for one contiguous raw-trace chunk."""

    first_event_id: str
    last_event_id: str
    first_event_hash: str
    last_event_hash: str
    event_count: int
    byte_length: int
    content_hash: str
    oversize_single_event: bool = False

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "first_event_id": self.first_event_id,
            "last_event_id": self.last_event_id,
            "first_event_hash": self.first_event_hash,
            "last_event_hash": self.last_event_hash,
            "event_count": self.event_count,
            "byte_length": self.byte_length,
            "content_hash": self.content_hash,
            "oversize_single_event": self.oversize_single_event,
        }


class TraceChunkPlanner:
    """Determine safe chunk boundaries without changing the Stage 03 journal."""

    def __init__(self, *, max_events: int, max_bytes: int) -> None:
        if isinstance(max_events, bool) or max_events <= 0:
            raise MemoryContractError("max_events must be a positive integer")
        if isinstance(max_bytes, bool) or max_bytes <= 0:
            raise MemoryContractError("max_bytes must be a positive integer")
        self.max_events = max_events
        self.max_bytes = max_bytes

    @classmethod
    def from_budget(cls, budget: MemoryBudget) -> TraceChunkPlanner:
        return cls(max_events=budget.trace_chunk_events, max_bytes=budget.trace_chunk_bytes)

    def should_seal(self, *, active_event_count: int, active_byte_length: int) -> bool:
        if active_event_count < 0 or active_byte_length < 0:
            raise MemoryContractError("active chunk measurements must be non-negative")
        return active_event_count >= self.max_events or active_byte_length >= self.max_bytes

    def plan(self, events: Sequence[TraceEvent]) -> tuple[TraceChunkPlan, ...]:
        """Partition ordered events while preserving exact IDs and event hashes."""

        if not events:
            return ()
        chunks: list[list[TraceEvent]] = []
        current: list[TraceEvent] = []
        current_bytes = 0
        for event in events:
            event.verify_hash()
            line_bytes = len(canonical_bytes(event.to_dict())) + 1
            if current and (
                len(current) >= self.max_events or current_bytes + line_bytes > self.max_bytes
            ):
                chunks.append(current)
                current = []
                current_bytes = 0
            current.append(event)
            current_bytes += line_bytes
        if current:
            chunks.append(current)
        result: list[TraceChunkPlan] = []
        for chunk in chunks:
            content = b"".join(canonical_bytes(event.to_dict()) + b"\n" for event in chunk)
            result.append(
                TraceChunkPlan(
                    first_event_id=chunk[0].event_id,
                    last_event_id=chunk[-1].event_id,
                    first_event_hash=chunk[0].event_hash,
                    last_event_hash=chunk[-1].event_hash,
                    event_count=len(chunk),
                    byte_length=len(content),
                    content_hash=sha256_bytes(content),
                    oversize_single_event=len(chunk) == 1 and len(content) > self.max_bytes,
                )
            )
        return tuple(result)
