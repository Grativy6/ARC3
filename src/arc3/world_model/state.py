"""Deterministic symbolic state used by executable ARC3 world models."""

from __future__ import annotations

from dataclasses import dataclass, replace

from arc3.errors import WorldModelError
from arc3.trace.canonical import sha256_json
from arc3.types import JSONValue


def _text(value: str, *, field: str) -> str:
    if not value.strip():
        raise WorldModelError(f"{field} must be non-empty")
    return value


@dataclass(frozen=True, slots=True, order=True)
class Cell:
    """One unbounded symbolic cell; state construction enforces frame bounds."""

    x: int
    y: int

    def __post_init__(self) -> None:
        if isinstance(self.x, bool) or isinstance(self.y, bool):
            raise WorldModelError("cell coordinates must be integers")


@dataclass(frozen=True, slots=True)
class SymbolicEntity:
    """An interpreted entity candidate, separate from raw perception identity."""

    entity_id: str
    kind: str
    cells: tuple[Cell, ...]
    color: int | None = None
    attributes: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        _text(self.entity_id, field="entity_id")
        _text(self.kind, field="entity kind")
        cells = tuple(sorted(set(self.cells)))
        if not cells:
            raise WorldModelError("symbolic entities require at least one cell")
        object.__setattr__(self, "cells", cells)
        object.__setattr__(self, "attributes", tuple(sorted(set(self.attributes))))

    def translated(self, dx: int, dy: int) -> SymbolicEntity:
        return replace(self, cells=tuple(Cell(cell.x + dx, cell.y + dy) for cell in self.cells))

    @property
    def anchor(self) -> Cell:
        return min(self.cells)


@dataclass(frozen=True, slots=True, order=True)
class Attachment:
    """A retained child-to-parent relation with an anchor offset."""

    child_id: str
    parent_id: str
    dx: int
    dy: int


@dataclass(frozen=True, slots=True)
class SymbolicState:
    """Small immutable state on which candidate rules execute."""

    width: int
    height: int
    entities: tuple[SymbolicEntity, ...] = ()
    facts: tuple[str, ...] = ()
    counters: tuple[tuple[str, int], ...] = ()
    toggles: tuple[tuple[str, str], ...] = ()
    selected_id: str | None = None
    attachments: tuple[Attachment, ...] = ()

    def __post_init__(self) -> None:
        if self.width < 1 or self.height < 1:
            raise WorldModelError("symbolic state dimensions must be positive")
        entities = tuple(sorted(self.entities, key=lambda item: item.entity_id))
        if len({entity.entity_id for entity in entities}) != len(entities):
            raise WorldModelError("symbolic entity IDs must be unique")
        for entity in entities:
            if any(not self.contains(cell) for cell in entity.cells):
                raise WorldModelError("entity cell lies outside symbolic state")
        object.__setattr__(self, "entities", entities)
        object.__setattr__(self, "facts", tuple(sorted(set(self.facts))))
        object.__setattr__(self, "counters", _unique_pairs(self.counters, field="counter"))
        object.__setattr__(self, "toggles", _unique_pairs(self.toggles, field="toggle"))
        object.__setattr__(self, "attachments", tuple(sorted(set(self.attachments))))
        identifiers = {entity.entity_id for entity in entities}
        if self.selected_id is not None and self.selected_id not in identifiers:
            raise WorldModelError("selected entity must exist")
        for attachment in self.attachments:
            if attachment.child_id not in identifiers or attachment.parent_id not in identifiers:
                raise WorldModelError("attachment endpoints must exist")

    def contains(self, cell: Cell) -> bool:
        return 0 <= cell.x < self.width and 0 <= cell.y < self.height

    def entity(self, entity_id: str) -> SymbolicEntity | None:
        return next((item for item in self.entities if item.entity_id == entity_id), None)

    def entities_of_kind(self, kind: str) -> tuple[SymbolicEntity, ...]:
        return tuple(item for item in self.entities if item.kind == kind)

    def at(self, cell: Cell) -> tuple[SymbolicEntity, ...]:
        return tuple(item for item in self.entities if cell in item.cells)

    def counter(self, name: str, default: int = 0) -> int:
        return dict(self.counters).get(name, default)

    def toggle(self, name: str, default: str = "off") -> str:
        return dict(self.toggles).get(name, default)

    def replace_entity(self, entity: SymbolicEntity) -> SymbolicState:
        if self.entity(entity.entity_id) is None:
            raise WorldModelError(f"unknown entity: {entity.entity_id}")
        return replace(
            self,
            entities=tuple(
                entity if current.entity_id == entity.entity_id else current
                for current in self.entities
            ),
        )

    def remove_entity(self, entity_id: str) -> SymbolicState:
        if self.entity(entity_id) is None:
            return self
        return replace(
            self,
            entities=tuple(item for item in self.entities if item.entity_id != entity_id),
            selected_id=None if self.selected_id == entity_id else self.selected_id,
            attachments=tuple(
                item
                for item in self.attachments
                if item.child_id != entity_id and item.parent_id != entity_id
            ),
        )

    def with_fact(self, fact: str, *, present: bool = True) -> SymbolicState:
        _text(fact, field="fact")
        facts = set(self.facts)
        if present:
            facts.add(fact)
        else:
            facts.discard(fact)
        return replace(self, facts=tuple(facts))

    def with_counter(self, name: str, value: int) -> SymbolicState:
        values = dict(self.counters)
        values[_text(name, field="counter name")] = value
        return replace(self, counters=tuple(values.items()))

    def with_toggle(self, name: str, value: str) -> SymbolicState:
        values = dict(self.toggles)
        values[_text(name, field="toggle name")] = _text(value, field="toggle value")
        return replace(self, toggles=tuple(values.items()))

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "width": self.width,
            "height": self.height,
            "entities": [
                {
                    "entity_id": entity.entity_id,
                    "kind": entity.kind,
                    "cells": [[cell.x, cell.y] for cell in entity.cells],
                    "color": entity.color,
                    "attributes": [list(item) for item in entity.attributes],
                }
                for entity in self.entities
            ],
            "facts": list(self.facts),
            "counters": [[name, value] for name, value in self.counters],
            "toggles": [[name, value] for name, value in self.toggles],
            "selected_id": self.selected_id,
            "attachments": [
                {
                    "child_id": item.child_id,
                    "parent_id": item.parent_id,
                    "dx": item.dx,
                    "dy": item.dy,
                }
                for item in self.attachments
            ],
        }

    @property
    def state_id(self) -> str:
        return sha256_json(self.to_dict())


def _unique_pairs[T](pairs: tuple[tuple[str, T], ...], *, field: str) -> tuple[tuple[str, T], ...]:
    keys = [key for key, _value in pairs]
    if len(set(keys)) != len(keys):
        raise WorldModelError(f"{field} names must be unique")
    if any(not key.strip() for key in keys):
        raise WorldModelError(f"{field} names must be non-empty")
    return tuple(sorted(pairs))


__all__ = ["Attachment", "Cell", "SymbolicEntity", "SymbolicState"]
