"""Canonical scalar metadata projection for observation differencing."""

from __future__ import annotations

from arc3.adapters import Observation
from arc3.types import JSONScalar

_OFFICIAL_FIELDS = frozenset(
    {
        "state",
        "levels_completed",
        "win_levels",
        "available_actions",
        "full_reset",
    }
)


def observation_metadata(observation: Observation) -> dict[str, JSONScalar]:
    """Project all official scalar state plus preserved upstream metadata.

    Official fields cannot be shadowed by an upstream key.  A colliding upstream
    field remains observable under the explicit ``upstream.`` namespace.
    Action order is normalized because legality is a set-valued observation.
    """

    projected: dict[str, JSONScalar] = {
        "state": observation.state.value,
        "levels_completed": observation.levels_completed,
        "win_levels": observation.win_levels,
        "available_actions": ",".join(
            sorted(action.value for action in observation.available_actions)
        ),
        "full_reset": observation.full_reset,
    }
    for key, value in observation.upstream_metadata:
        projected[key if key not in _OFFICIAL_FIELDS else f"upstream.{key}"] = value
    return projected


__all__ = ["observation_metadata"]
