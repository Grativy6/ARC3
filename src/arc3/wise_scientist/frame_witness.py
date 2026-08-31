"""Exact, game-agnostic frame witnesses for tracked board footprints.

The Wise Scientist journal deliberately stores observations without inferring
object identity.  A human or policy may nevertheless declare a distinctive
pixel pattern as a temporary tracked footprint.  This module then measures its
unique center before and after an action and refuses to call a block or a
discontinuous relocation ordinary corridor progress.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from arc3.adapters import GridFrame
from arc3.errors import ARC3ValidationError
from arc3.types import JSONValue


class PositionChangeKind(StrEnum):
    """Measured relationship between two unique footprint positions."""

    BLOCKED = "BLOCKED"
    ORDINARY_MOVE = "ORDINARY_MOVE"
    DISCONTINUITY = "DISCONTINUITY"


@dataclass(frozen=True, slots=True)
class PatternLocation:
    """One exact occurrence of a declared rectangular pattern."""

    top_left_x: int
    top_left_y: int
    width: int
    height: int

    @property
    def center(self) -> tuple[int, int]:
        """Return the exact center of an odd-sized tracked pattern."""

        return (
            self.top_left_x + self.width // 2,
            self.top_left_y + self.height // 2,
        )

    def to_dict(self) -> dict[str, JSONValue]:
        """Return a normalized evidence payload."""

        return {
            "top_left": [self.top_left_x, self.top_left_y],
            "center": list(self.center),
            "width": self.width,
            "height": self.height,
        }


@dataclass(frozen=True, slots=True)
class PositionTransition:
    """Exact before/after locations and their bounded classification."""

    before: PatternLocation
    after: PatternLocation
    kind: PositionChangeKind
    displacement: tuple[int, int]

    def to_dict(self) -> dict[str, JSONValue]:
        """Return a normalized evidence payload."""

        return {
            "before": self.before.to_dict(),
            "after": self.after.to_dict(),
            "kind": self.kind.value,
            "displacement": list(self.displacement),
        }


def _validated_pattern(pattern: tuple[tuple[int, ...], ...]) -> tuple[tuple[int, ...], ...]:
    if not pattern or not pattern[0]:
        raise ARC3ValidationError("tracked pattern must contain at least one cell")
    width = len(pattern[0])
    if len(pattern) % 2 == 0 or width % 2 == 0:
        raise ARC3ValidationError("tracked pattern dimensions must be odd")
    for row in pattern:
        if len(row) != width:
            raise ARC3ValidationError("tracked pattern rows must have equal width")
        if any(
            isinstance(cell, bool) or not isinstance(cell, int) or not 0 <= cell <= 15
            for cell in row
        ):
            raise ARC3ValidationError("tracked pattern cells must be integers in 0..15")
    return pattern


def locate_pattern(
    frame: GridFrame, pattern: tuple[tuple[int, ...], ...]
) -> tuple[PatternLocation, ...]:
    """Return every exact occurrence of ``pattern`` in row-major order."""

    checked = _validated_pattern(pattern)
    pattern_height = len(checked)
    pattern_width = len(checked[0])
    matches: list[PatternLocation] = []
    for top in range(frame.height - pattern_height + 1):
        for left in range(frame.width - pattern_width + 1):
            if all(
                frame.cells[top + y][left : left + pattern_width] == checked[y]
                for y in range(pattern_height)
            ):
                matches.append(
                    PatternLocation(
                        top_left_x=left,
                        top_left_y=top,
                        width=pattern_width,
                        height=pattern_height,
                    )
                )
    return tuple(matches)


def require_unique_pattern(
    frame: GridFrame,
    pattern: tuple[tuple[int, ...], ...],
    *,
    field: str,
) -> PatternLocation:
    """Return one location or reject absent/ambiguous identity evidence."""

    matches = locate_pattern(frame, pattern)
    if len(matches) != 1:
        raise ARC3ValidationError(
            f"{field} tracked pattern must occur exactly once; observed {len(matches)}"
        )
    return matches[0]


def measure_position_transition(
    before: GridFrame,
    after: GridFrame,
    pattern: tuple[tuple[int, ...], ...],
    *,
    ordinary_displacements: frozenset[tuple[int, int]],
) -> PositionTransition:
    """Measure and classify one declared footprint across final frames.

    ``ordinary_displacements`` is observation-derived configuration, not an
    inferred action mapping.  A zero displacement is always ``BLOCKED``;
    declared local displacements are ``ORDINARY_MOVE``; every other exact
    relocation is a ``DISCONTINUITY`` that must be explained before acting.
    """

    if (0, 0) in ordinary_displacements:
        raise ARC3ValidationError("ordinary displacements must not contain zero")
    before_location = require_unique_pattern(before, pattern, field="before frame")
    after_location = require_unique_pattern(after, pattern, field="after frame")
    displacement = (
        after_location.center[0] - before_location.center[0],
        after_location.center[1] - before_location.center[1],
    )
    if displacement == (0, 0):
        kind = PositionChangeKind.BLOCKED
    elif displacement in ordinary_displacements:
        kind = PositionChangeKind.ORDINARY_MOVE
    else:
        kind = PositionChangeKind.DISCONTINUITY
    return PositionTransition(
        before=before_location,
        after=after_location,
        kind=kind,
        displacement=displacement,
    )


def require_position_transition(
    transition: PositionTransition,
    *,
    expected_before: tuple[int, int],
    expected_after: tuple[int, int],
    expected_kind: PositionChangeKind,
) -> None:
    """Reject a narrative position claim that disagrees with exact frames."""

    observed = (transition.before.center, transition.after.center, transition.kind)
    expected = (expected_before, expected_after, expected_kind)
    if observed != expected:
        raise ARC3ValidationError(
            "position witness disagrees with exact frames: "
            f"expected {expected_before}->{expected_after} {expected_kind.value}; "
            f"observed {transition.before.center}->{transition.after.center} "
            f"{transition.kind.value}"
        )


__all__ = [
    "PatternLocation",
    "PositionChangeKind",
    "PositionTransition",
    "locate_pattern",
    "measure_position_transition",
    "require_position_transition",
    "require_unique_pattern",
]
