"""Tests for dependency-free identifiers and environment value objects."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from arc3.types import ActionName, ActionRequest, Coordinate, EvaluationSurface


@pytest.mark.property
@given(
    x=st.integers(min_value=0, max_value=63),
    y=st.integers(min_value=0, max_value=63),
)
def test_coordinate_accepts_entire_official_domain(x: int, y: int) -> None:
    assert Coordinate(x=x, y=y) == Coordinate(x, y)


@pytest.mark.parametrize(
    ("x", "y"),
    [(-1, 0), (64, 0), (0, -1), (0, 64), (True, 0), (0, False)],
)
def test_coordinate_rejects_out_of_domain_and_boolean_values(x: int, y: int) -> None:
    with pytest.raises(ValueError, match="coordinates"):
        Coordinate(x=x, y=y)


def test_action6_strictly_requires_a_coordinate() -> None:
    coordinate = Coordinate(11, 37)

    assert ActionRequest(ActionName.ACTION6, coordinate).coordinate == coordinate
    with pytest.raises(ValueError, match="ACTION6 requires coordinate"):
        ActionRequest(ActionName.ACTION6)


@pytest.mark.parametrize(
    "action", [action for action in ActionName if action is not ActionName.ACTION6]
)
def test_non_coordinate_actions_strictly_forbid_coordinates(action: ActionName) -> None:
    assert ActionRequest(action).coordinate is None
    with pytest.raises(ValueError, match="forbids coordinate"):
        ActionRequest(action, Coordinate(0, 0))


def test_evaluation_surfaces_preserve_required_exact_labels() -> None:
    assert [surface.value for surface in EvaluationSurface] == [
        "synthetic",
        "local-public",
        "online-public",
        "Kaggle-public",
        "semi-private",
        "official-private",
    ]
