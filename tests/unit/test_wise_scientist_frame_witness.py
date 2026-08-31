from __future__ import annotations

import pytest

from arc3.adapters import GridFrame
from arc3.errors import ARC3ValidationError
from arc3.wise_scientist.frame_witness import (
    PositionChangeKind,
    measure_position_transition,
    require_position_transition,
)

PATTERN = (
    (12, 12, 12),
    (12, 9, 12),
    (9, 9, 9),
)
ORDINARY = frozenset({(-1, 0), (1, 0), (0, -1), (0, 1)})


def _frame(center: tuple[int, int], *, resource: int = 1) -> GridFrame:
    rows = [[3 for _x in range(9)] for _y in range(9)]
    left = center[0] - 1
    top = center[1] - 1
    for y, row in enumerate(PATTERN):
        for x, cell in enumerate(row):
            rows[top + y][left + x] = cell
    rows[8][8] = resource
    return GridFrame.from_rows(rows)


def test_position_witness_classifies_ordinary_move() -> None:
    transition = measure_position_transition(
        _frame((3, 3)),
        _frame((4, 3), resource=2),
        PATTERN,
        ordinary_displacements=ORDINARY,
    )

    assert transition.before.center == (3, 3)
    assert transition.after.center == (4, 3)
    assert transition.kind is PositionChangeKind.ORDINARY_MOVE


def test_position_witness_classifies_block_despite_hud_change() -> None:
    transition = measure_position_transition(
        _frame((3, 3), resource=1),
        _frame((3, 3), resource=2),
        PATTERN,
        ordinary_displacements=ORDINARY,
    )

    assert transition.displacement == (0, 0)
    assert transition.kind is PositionChangeKind.BLOCKED


def test_position_witness_classifies_respawn_as_discontinuity() -> None:
    transition = measure_position_transition(
        _frame((7, 1)),
        _frame((1, 7), resource=2),
        PATTERN,
        ordinary_displacements=ORDINARY,
    )

    assert transition.displacement == (-6, 6)
    assert transition.kind is PositionChangeKind.DISCONTINUITY


def test_position_witness_rejects_false_corridor_claim() -> None:
    transition = measure_position_transition(
        _frame((3, 3)),
        _frame((3, 3), resource=2),
        PATTERN,
        ordinary_displacements=ORDINARY,
    )

    with pytest.raises(ARC3ValidationError, match="disagrees with exact frames"):
        require_position_transition(
            transition,
            expected_before=(3, 3),
            expected_after=(4, 3),
            expected_kind=PositionChangeKind.ORDINARY_MOVE,
        )


def test_position_witness_rejects_ambiguous_pattern() -> None:
    frame = _frame((3, 3))
    rows = [list(row) for row in frame.cells]
    for y, row in enumerate(PATTERN):
        for x, cell in enumerate(row):
            rows[5 + y][5 + x] = cell

    with pytest.raises(ARC3ValidationError, match="exactly once"):
        measure_position_transition(
            frame,
            GridFrame.from_rows(rows),
            PATTERN,
            ordinary_displacements=ORDINARY,
        )
