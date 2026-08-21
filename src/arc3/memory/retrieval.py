"""Scoped persistent memory, deterministic retrieval, and eviction."""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterable, Mapping
from pathlib import Path

from arc3.errors import ARC3ValidationError
from arc3.trace.canonical import canonical_bytes, parse_json_bytes, require_object, sha256_bytes
from arc3.types import JSONValue, StateScope

from .episode import EpisodeMemoryStore
from .game import GameMemoryStore
from .generic import GenericMemoryStore
from .models import (
    MEMORY_SNAPSHOT_SCHEMA,
    MemoryAblations,
    MemoryBudget,
    MemoryContractError,
    MemoryHit,
    MemoryQuery,
    MemoryRecord,
    StoreResult,
)
from .store import BoundedMemoryStore, slot_from_dict


class PersistentMemory:
    """Three-scope memory whose summaries remain pointers into immutable trace."""

    def __init__(
        self,
        *,
        budget: MemoryBudget | None = None,
        ablations: MemoryAblations | None = None,
    ) -> None:
        self.budget = budget or MemoryBudget()
        self.ablations = ablations or MemoryAblations()
        self._sequence = 0
        self._episodes: dict[tuple[str, str], EpisodeMemoryStore] = {}
        self._games: dict[str, GameMemoryStore] = {}
        self._generic = GenericMemoryStore(
            max_records=self.budget.max_generic_records,
            max_bytes=self.budget.max_bytes,
        )

    @property
    def record_count(self) -> int:
        return sum(store.record_count for store in self._stores())

    @property
    def byte_size(self) -> int:
        return sum(store.byte_size for store in self._stores())

    @property
    def sequence(self) -> int:
        return self._sequence

    def _stores(self) -> tuple[BoundedMemoryStore, ...]:
        episodes = tuple(self._episodes[key] for key in sorted(self._episodes))
        games = tuple(self._games[key] for key in sorted(self._games))
        return (*episodes, *games, self._generic)

    def _episode_store(self, record: MemoryRecord) -> EpisodeMemoryStore:
        assert record.episode_id is not None
        assert record.game_scope_hash is not None
        key = (record.game_scope_hash, record.episode_id)
        store = self._episodes.get(key)
        if store is None:
            store = EpisodeMemoryStore(
                episode_id=record.episode_id,
                game_scope_hash=record.game_scope_hash,
                max_records=self.budget.max_episode_records,
                max_bytes=self.budget.max_bytes,
            )
            self._episodes[key] = store
        return store

    def _game_store(self, record: MemoryRecord) -> GameMemoryStore:
        assert record.game_scope_hash is not None
        store = self._games.get(record.game_scope_hash)
        if store is None:
            store = GameMemoryStore(
                game_scope_hash=record.game_scope_hash,
                max_records=self.budget.max_game_records,
                max_bytes=self.budget.max_bytes,
            )
            self._games[record.game_scope_hash] = store
        return store

    def add(self, record: MemoryRecord) -> StoreResult:
        """Add a derived record unless an explicit ablation disables it."""

        if not self.ablations.memory_enabled:
            return StoreResult(retained=False, reason="memory_disabled_ablation")
        if record.rejected_hypothesis_ids and not self.ablations.retain_rejected_hypotheses:
            return StoreResult(retained=False, reason="rejected_retention_disabled_ablation")
        if self.find(record.memory_id) is not None:
            raise MemoryContractError(f"duplicate memory_id: {record.memory_id}")
        self._sequence += 1
        if record.scope is StateScope.EPISODE:
            result = self._episode_store(record).add(record, sequence=self._sequence)
        elif record.scope is StateScope.GAME:
            result = self._game_store(record).add(record, sequence=self._sequence)
        else:
            result = self._generic.add(record, sequence=self._sequence)
        evicted = list(result.evicted_memory_ids)
        while self.record_count > self.budget.max_records or self.byte_size > self.budget.max_bytes:
            candidates = [
                (slot.eviction_key, store, slot.record.memory_id)
                for store in self._stores()
                if (slot := store.eviction_candidate()) is not None
            ]
            if not candidates:  # pragma: no cover - positive record count invariant
                break
            _, store, memory_id = min(candidates, key=lambda item: item[0])
            store.remove(memory_id)
            evicted.append(memory_id)
        self._prune_empty_stores()
        retained = self.find(record.memory_id) is not None
        reason = result.reason if retained else "record_exceeds_or_loses_global_eviction"
        return StoreResult(retained=retained, evicted_memory_ids=tuple(evicted), reason=reason)

    def _prune_empty_stores(self) -> None:
        self._episodes = {
            key: store for key, store in self._episodes.items() if store.record_count > 0
        }
        self._games = {key: store for key, store in self._games.items() if store.record_count > 0}

    def find(self, memory_id: str) -> MemoryRecord | None:
        for store in self._stores():
            found = store.get(memory_id)
            if found is not None:
                return found
        return None

    def all_records(self) -> tuple[MemoryRecord, ...]:
        return tuple(record for store in self._stores() for record in store.records())

    def _visible_stores(self, query: MemoryQuery) -> tuple[BoundedMemoryStore, ...]:
        stores: list[BoundedMemoryStore] = []
        if query.game_scope_hash is not None and query.episode_id is not None:
            episode = self._episodes.get((query.game_scope_hash, query.episode_id))
            if episode is not None:
                stores.append(episode)
        if query.game_scope_hash is not None:
            game = self._games.get(query.game_scope_hash)
            if game is not None:
                stores.append(game)
        if self._generic_allowed(query, stores):
            stores.append(self._generic)
        return tuple(stores)

    @staticmethod
    def _generic_allowed(
        query: MemoryQuery,
        current_stores: Iterable[BoundedMemoryStore],
    ) -> bool:
        if query.analogous_rule is None or not query.current_game_evidence_event_ids:
            return False
        cited = {
            event_id
            for store in current_stores
            for record in store.records()
            for event_id in record.summary.source_event_ids
        }
        return bool(cited & set(query.current_game_evidence_event_ids))

    @staticmethod
    def _score(record: MemoryRecord, query: MemoryQuery) -> tuple[int, tuple[str, ...]]:
        score = 0
        matched: list[str] = []
        if query.exact_event_id is not None and record.summary.references_event(
            query.exact_event_id
        ):
            score += 1000
            matched.append("exact_event")
        if query.abstract_state is not None and record.abstract_state is not None:
            similarity = query.abstract_state.similarity(record.abstract_state)
            if similarity > 0:
                score += round(400 * similarity)
                matched.append("abstract_state")
        if query.active_contradiction_ids:
            overlap = set(query.active_contradiction_ids) & set(record.active_contradiction_ids)
            if overlap:
                score += 600 + 25 * len(overlap)
                matched.append("active_contradiction")
        if query.analogous_rule is not None and record.rule_signature is not None:
            similarity = query.analogous_rule.similarity(record.rule_signature)
            if similarity > 0:
                score += round(300 * similarity)
                matched.append("analogous_rule")
        scope_bonus = {
            StateScope.EPISODE: 30,
            StateScope.GAME: 20,
            StateScope.GENERIC: 10,
        }[record.scope]
        if matched:
            score += scope_bonus + record.importance
        return score, tuple(matched)

    def retrieve(self, query: MemoryQuery) -> tuple[MemoryHit, ...]:
        """Retrieve by evidence identity and abstract structure, never task name."""

        if not self.ablations.memory_enabled:
            return ()
        scored: list[MemoryHit] = []
        stores = self._visible_stores(query)
        for store in stores:
            for record in store.records():
                if record.rejected_hypothesis_ids and not self.ablations.retain_rejected_hypotheses:
                    continue
                score, matched = self._score(record, query)
                if matched:
                    scored.append(MemoryHit(record=record, score=score, matched_by=matched))
        selected = tuple(
            sorted(
                scored,
                key=lambda hit: (-hit.score, -hit.record.importance, hit.record.memory_id),
            )[: query.limit]
        )
        for hit in selected:
            self._sequence += 1
            for store in stores:
                if store.get(hit.record.memory_id) is not None:
                    store.touch(hit.record.memory_id, sequence=self._sequence)
                    break
        return selected

    def to_dict(self) -> dict[str, JSONValue]:
        """Serialize the bounded derived index for checkpointing or local persistence."""

        return {
            "schema": MEMORY_SNAPSHOT_SCHEMA,
            "budget": self.budget.to_dict(),
            "ablations": self.ablations.to_dict(),
            "sequence": self._sequence,
            "episode_stores": [
                {
                    "episode_id": store.episode_id,
                    "game_scope_hash": store.game_scope_hash,
                    "store": store.to_dict(),
                }
                for store in (self._episodes[key] for key in sorted(self._episodes))
            ],
            "game_stores": [
                {"game_scope_hash": key, "store": self._games[key].to_dict()}
                for key in sorted(self._games)
            ],
            "generic_store": self._generic.to_dict(),
            "measured_record_count": self.record_count,
            "measured_byte_size": self.byte_size,
        }

    @property
    def snapshot_hash(self) -> str:
        return sha256_bytes(canonical_bytes(self.to_dict()))

    def save(self, path: str | Path) -> str:
        """Atomically replace a disposable snapshot; immutable trace remains authoritative."""

        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        content = canonical_bytes(self.to_dict()) + b"\n"
        temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("xb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
        return sha256_bytes(content)

    @classmethod
    def load(cls, path: str | Path) -> PersistentMemory:
        try:
            value = require_object(
                parse_json_bytes(Path(path).read_bytes()), field="memory snapshot"
            )
        except (OSError, ARC3ValidationError) as error:
            raise MemoryContractError(f"cannot load memory snapshot: {error}") from error
        return cls.from_dict(value)

    @classmethod
    def from_dict(cls, value: object) -> PersistentMemory:
        if not isinstance(value, Mapping):
            raise MemoryContractError("memory snapshot must be an object")
        if value.get("schema") != MEMORY_SNAPSHOT_SCHEMA:
            raise MemoryContractError("unsupported memory snapshot schema")
        budget = MemoryBudget.from_dict(value.get("budget"))
        memory = cls(
            budget=budget,
            ablations=MemoryAblations.from_dict(value.get("ablations")),
        )
        sequence = value.get("sequence")
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0:
            raise MemoryContractError("memory snapshot sequence is invalid")
        memory._sequence = sequence
        raw_episodes = value.get("episode_stores")
        raw_games = value.get("game_stores")
        raw_generic = value.get("generic_store")
        if not isinstance(raw_episodes, list) or not isinstance(raw_games, list):
            raise MemoryContractError("memory snapshot store lists are invalid")
        for raw in raw_episodes:
            if not isinstance(raw, Mapping):
                raise MemoryContractError("episode store snapshot must be an object")
            episode_id = raw.get("episode_id")
            scope_hash = raw.get("game_scope_hash")
            if not isinstance(episode_id, str) or not isinstance(scope_hash, str):
                raise MemoryContractError("episode store context is invalid")
            episode_store = EpisodeMemoryStore(
                episode_id=episode_id,
                game_scope_hash=scope_hash,
                max_records=budget.max_episode_records,
                max_bytes=budget.max_bytes,
            )
            cls._restore_slots(episode_store, raw.get("store"))
            memory._episodes[(scope_hash, episode_id)] = episode_store
        for raw in raw_games:
            if not isinstance(raw, Mapping):
                raise MemoryContractError("game store snapshot must be an object")
            scope_hash = raw.get("game_scope_hash")
            if not isinstance(scope_hash, str):
                raise MemoryContractError("game store context is invalid")
            game_store = GameMemoryStore(
                game_scope_hash=scope_hash,
                max_records=budget.max_game_records,
                max_bytes=budget.max_bytes,
            )
            cls._restore_slots(game_store, raw.get("store"))
            memory._games[scope_hash] = game_store
        cls._restore_slots(memory._generic, raw_generic)
        declared_count = value.get("measured_record_count")
        declared_bytes = value.get("measured_byte_size")
        if declared_count != memory.record_count or declared_bytes != memory.byte_size:
            raise MemoryContractError("memory snapshot measured bounds do not validate")
        if memory.record_count > budget.max_records or memory.byte_size > budget.max_bytes:
            raise MemoryContractError("memory snapshot exceeds its global budget")
        latest_access = max(
            (slot.last_access_sequence for store in memory._stores() for slot in store.slots()),
            default=0,
        )
        if latest_access > memory._sequence:
            raise MemoryContractError("memory snapshot sequence precedes a stored access")
        return memory

    @staticmethod
    def _restore_slots(store: BoundedMemoryStore, raw_store: object) -> None:
        if not isinstance(raw_store, Mapping):
            raise MemoryContractError("memory store snapshot must be an object")
        if raw_store.get("scope") != store.allowed_scope.value:
            raise MemoryContractError("memory store snapshot scope is incompatible")
        if raw_store.get("max_records") != store.max_records:
            raise MemoryContractError("memory store snapshot record bound is incompatible")
        if raw_store.get("max_bytes") != store.max_bytes:
            raise MemoryContractError("memory store snapshot byte bound is incompatible")
        raw_slots = raw_store.get("slots")
        if not isinstance(raw_slots, list):
            raise MemoryContractError("memory store slots must be an array")
        for raw_slot in raw_slots:
            store.install_slot(slot_from_dict(raw_slot))


def opaque_game_scope(*, run_scope_salt: str, environment_scope_token: str) -> str:
    """Create an opaque within-run scope handle, not a retrieval key for a solution."""

    if not run_scope_salt or not environment_scope_token:
        raise MemoryContractError("scope derivation inputs must be non-empty")
    return sha256_bytes(
        canonical_bytes(
            {
                "schema": "arc3.memory.opaque-game-scope.v0.1",
                "run_scope_salt": run_scope_salt,
                "environment_scope_token": environment_scope_token,
            }
        )
    )
