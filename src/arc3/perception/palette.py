"""Level-scoped canonical palette roles derived from observation structure.

Raw ARC palette values remain measurement data.  This module gives downstream
interpretation a separate, stable identifier whose construction never ranks or
names a role by the numeric color value.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Collection, Mapping
from dataclasses import dataclass, replace

from arc3.adapters import GridFrame
from arc3.errors import ARC3ValidationError
from arc3.trace.canonical import require_sha256, sha256_json
from arc3.types import JSONValue

PALETTE_ROLE_SCHEMA = "arc3.perception.palette-role-registry.v0.1"
MAX_PALETTE_ROLES = 16


def _integer(value: object, *, field: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ARC3ValidationError(f"{field} must be an integer")
    if not minimum <= value <= maximum:
        raise ARC3ValidationError(f"{field} must be within {minimum}..{maximum}")
    return value


def _anonymous_identity_token(role_id: str, anonymous_ordinal: int) -> str:
    digest = sha256_json(
        {
            "schema": "arc3.perception.palette-anonymous-identity.v0.1",
            "role_id": role_id,
            "anonymous_ordinal": anonymous_ordinal,
        }
    ).removeprefix("sha256:")[:16]
    return f"palette-identity:{digest}:{anonymous_ordinal}"


@dataclass(frozen=True, slots=True)
class PaletteRoleEvidence:
    """Frozen structural evidence available when one raw color first appears."""

    background: bool
    cell_count: int
    boundary_count: int
    normalized_pattern: str

    def __post_init__(self) -> None:
        if self.cell_count < 1:
            raise ARC3ValidationError("palette role evidence requires observed cells")
        if not 0 <= self.boundary_count <= self.cell_count:
            raise ARC3ValidationError("palette boundary count is inconsistent")
        require_sha256(self.normalized_pattern, field="palette normalized pattern")

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "background": self.background,
            "cell_count": self.cell_count,
            "boundary_count": self.boundary_count,
            "normalized_pattern": self.normalized_pattern,
        }

    @classmethod
    def from_dict(cls, value: object) -> PaletteRoleEvidence:
        if not isinstance(value, Mapping):
            raise ARC3ValidationError("palette role evidence must be an object")
        background = value.get("background")
        pattern = value.get("normalized_pattern")
        if not isinstance(background, bool) or not isinstance(pattern, str):
            raise ARC3ValidationError("palette role evidence fields are malformed")
        return cls(
            background=background,
            cell_count=_integer(
                value.get("cell_count"), field="palette cell_count", minimum=1, maximum=4096
            ),
            boundary_count=_integer(
                value.get("boundary_count"),
                field="palette boundary_count",
                minimum=0,
                maximum=4096,
            ),
            normalized_pattern=pattern,
        )


@dataclass(frozen=True, slots=True)
class PaletteRoleAssignment:
    """One raw-color lookup entry and its revisable ambiguity marker.

    ``role_id`` names shared semantic evidence. ``identity_token`` is a stable,
    anonymous discriminator assigned by first-observation encounter order. It
    keeps structurally indistinguishable colors separate without deriving
    identity or priority from their numeric palette values.
    """

    raw_color: int
    role_id: str
    identity_token: str
    evidence: PaletteRoleEvidence
    ambiguous: bool = False

    def __post_init__(self) -> None:
        if isinstance(self.raw_color, bool) or not 0 <= self.raw_color <= 15:
            raise ARC3ValidationError("raw palette color must be an integer in 0..15")
        if not self.role_id.startswith("palette-role:"):
            raise ARC3ValidationError("palette role identity is malformed")
        if self.identity_token not in {
            _anonymous_identity_token(self.role_id, ordinal) for ordinal in range(MAX_PALETTE_ROLES)
        }:
            raise ARC3ValidationError("palette anonymous identity is malformed")

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "raw_color": self.raw_color,
            "role_id": self.role_id,
            "identity_token": self.identity_token,
            "evidence": self.evidence.to_dict(),
            "ambiguous": self.ambiguous,
        }


class PaletteRoleRegistry:
    """Bounded raw-color lookup with palette-equivariant canonical role IDs.

    Evidence is captured once per color per level.  Later motion therefore does
    not rewrite an earlier identity.  If the available structural evidence is
    identical, colors intentionally share a role ID and remain marked
    ambiguous instead of being ordered by their numeric labels.
    """

    def __init__(self, *, level_index: int = 0, max_entries: int = MAX_PALETTE_ROLES) -> None:
        if isinstance(level_index, bool) or not isinstance(level_index, int) or level_index < 0:
            raise ARC3ValidationError("palette registry level_index must be non-negative")
        if (
            isinstance(max_entries, bool)
            or not isinstance(max_entries, int)
            or not 1 <= max_entries <= MAX_PALETTE_ROLES
        ):
            raise ARC3ValidationError("palette registry max_entries must be within 1..16")
        self._level_index = level_index
        self._max_entries = max_entries
        self._assignments: dict[int, PaletteRoleAssignment] = {}

    @property
    def level_index(self) -> int:
        return self._level_index

    @property
    def max_entries(self) -> int:
        return self._max_entries

    def __len__(self) -> int:
        return len(self._assignments)

    def begin_level(self, level_index: int) -> None:
        """Enter a level scope, dropping only revisable prior-level mappings."""

        if isinstance(level_index, bool) or not isinstance(level_index, int) or level_index < 0:
            raise ARC3ValidationError("palette registry level_index must be non-negative")
        if level_index != self._level_index:
            self._level_index = level_index
            self._assignments.clear()

    @staticmethod
    def _evidence(
        frame: GridFrame,
        raw_color: int,
        *,
        background_colors: frozenset[int],
    ) -> PaletteRoleEvidence:
        cells = tuple(
            (x, y)
            for y, row in enumerate(frame.cells)
            for x, value in enumerate(row)
            if value == raw_color
        )
        if not cells:
            raise ARC3ValidationError("cannot assign an unobserved palette color")
        boundary_count = sum(
            x in {0, frame.width - 1} or y in {0, frame.height - 1} for x, y in cells
        )
        min_x = min(x for x, _y in cells)
        min_y = min(y for _x, y in cells)
        normalized = tuple(sorted((x - min_x, y - min_y) for x, y in cells))
        return PaletteRoleEvidence(
            background=raw_color in background_colors,
            cell_count=len(cells),
            boundary_count=boundary_count,
            normalized_pattern=sha256_json(
                {
                    "schema": "arc3.perception.palette-normalized-pattern.v0.1",
                    "width": max(x for x, _y in normalized) + 1,
                    "height": max(y for _x, y in normalized) + 1,
                    "cells": [list(cell) for cell in normalized],
                }
            ),
        )

    @staticmethod
    def _role_id(evidence: PaletteRoleEvidence) -> str:
        digest = sha256_json(
            {
                "schema": "arc3.perception.palette-role.v0.1",
                "evidence": evidence.to_dict(),
            }
        ).removeprefix("sha256:")[:16]
        prefix = "background" if evidence.background else "structural"
        return f"palette-role:{prefix}:{digest}"

    @staticmethod
    def _identity_token(role_id: str, anonymous_ordinal: int) -> str:
        """Derive an opaque token from semantic role plus encounter ordinal."""

        return _anonymous_identity_token(role_id, anonymous_ordinal)

    def observe(
        self,
        frame: GridFrame,
        *,
        background_colors: Collection[int],
    ) -> tuple[PaletteRoleAssignment, ...]:
        """Add newly observed colors without revising established identities."""

        backgrounds = frozenset(background_colors)
        if any(isinstance(color, bool) or not 0 <= color <= 15 for color in backgrounds):
            raise ARC3ValidationError("background colors must be integers in 0..15")
        encounter_order = tuple(dict.fromkeys(value for row in frame.cells for value in row))
        new_colors = tuple(color for color in encounter_order if color not in self._assignments)
        if len(self._assignments) + len(new_colors) > self._max_entries:
            raise ARC3ValidationError("palette role registry exceeds its declared bound")
        for raw_color in new_colors:
            evidence = self._evidence(
                frame,
                raw_color,
                background_colors=backgrounds,
            )
            role_id = self._role_id(evidence)
            anonymous_ordinal = sum(item.role_id == role_id for item in self._assignments.values())
            self._assignments[raw_color] = PaletteRoleAssignment(
                raw_color=raw_color,
                role_id=role_id,
                identity_token=self._identity_token(role_id, anonymous_ordinal),
                evidence=evidence,
            )
        counts = Counter(item.role_id for item in self._assignments.values())
        self._assignments = {
            raw_color: replace(item, ambiguous=counts[item.role_id] > 1)
            for raw_color, item in self._assignments.items()
        }
        return tuple(self._assignments[color] for color in encounter_order)

    def role_for(self, raw_color: int) -> PaletteRoleAssignment:
        try:
            return self._assignments[raw_color]
        except KeyError as error:
            raise ARC3ValidationError(
                f"palette color {raw_color!r} has not been observed"
            ) from error

    def canonical_role(self, raw_color: int) -> str:
        return self.role_for(raw_color).role_id

    def anonymous_identity(self, raw_color: int) -> str:
        """Return the stable, raw-value-free identity token for one color."""

        return self.role_for(raw_color).identity_token

    def canonical_projection(self) -> tuple[tuple[str, int, bool], ...]:
        """Return a raw-color-free multiset projection for metamorphic checks."""

        grouped: Counter[str] = Counter(item.role_id for item in self._assignments.values())
        background = {item.role_id: item.evidence.background for item in self._assignments.values()}
        return tuple(
            (role_id, grouped[role_id], background[role_id]) for role_id in sorted(grouped)
        )

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "schema": PALETTE_ROLE_SCHEMA,
            "level_index": self._level_index,
            "max_entries": self._max_entries,
            "assignments": [
                item.to_dict()
                for item in sorted(
                    self._assignments.values(),
                    key=lambda item: (item.role_id, item.identity_token),
                )
            ],
        }

    @classmethod
    def from_dict(cls, value: object) -> PaletteRoleRegistry:
        if not isinstance(value, Mapping):
            raise ARC3ValidationError("palette role registry must be an object")
        if value.get("schema") != PALETTE_ROLE_SCHEMA:
            raise ARC3ValidationError("unsupported palette role registry schema")
        registry = cls(
            level_index=_integer(
                value.get("level_index"),
                field="palette registry level_index",
                minimum=0,
                maximum=2**31 - 1,
            ),
            max_entries=_integer(
                value.get("max_entries"),
                field="palette registry max_entries",
                minimum=1,
                maximum=MAX_PALETTE_ROLES,
            ),
        )
        raw_assignments = value.get("assignments")
        if not isinstance(raw_assignments, list):
            raise ARC3ValidationError("palette registry assignments must be an array")
        if len(raw_assignments) > registry.max_entries:
            raise ARC3ValidationError("palette role registry exceeds its declared bound")
        for raw in raw_assignments:
            if not isinstance(raw, Mapping):
                raise ARC3ValidationError("palette role assignment must be an object")
            evidence = PaletteRoleEvidence.from_dict(raw.get("evidence"))
            raw_color = _integer(
                raw.get("raw_color"), field="raw palette color", minimum=0, maximum=15
            )
            role_id = raw.get("role_id")
            identity_token = raw.get("identity_token")
            ambiguous = raw.get("ambiguous")
            if (
                not isinstance(role_id, str)
                or not isinstance(identity_token, str)
                or not isinstance(ambiguous, bool)
            ):
                raise ARC3ValidationError("palette role assignment fields are malformed")
            if role_id != cls._role_id(evidence):
                raise ARC3ValidationError("palette role identity does not match its evidence")
            if raw_color in registry._assignments:
                raise ARC3ValidationError("duplicate raw palette color in registry")
            registry._assignments[raw_color] = PaletteRoleAssignment(
                raw_color,
                role_id,
                identity_token,
                evidence,
                ambiguous,
            )
        counts = Counter(item.role_id for item in registry._assignments.values())
        if any(
            item.ambiguous != (counts[item.role_id] > 1) for item in registry._assignments.values()
        ):
            raise ARC3ValidationError("palette role ambiguity marker is inconsistent")
        for role_id, count in counts.items():
            expected = {
                cls._identity_token(role_id, anonymous_ordinal)
                for anonymous_ordinal in range(count)
            }
            actual = {
                item.identity_token
                for item in registry._assignments.values()
                if item.role_id == role_id
            }
            if actual != expected:
                raise ARC3ValidationError("palette anonymous identity set is inconsistent")
        return registry


__all__ = [
    "MAX_PALETTE_ROLES",
    "PALETTE_ROLE_SCHEMA",
    "PaletteRoleAssignment",
    "PaletteRoleEvidence",
    "PaletteRoleRegistry",
]
