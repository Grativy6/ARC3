"""Observation-to-effect classification without causal overclaiming."""

from __future__ import annotations

from collections import Counter

from arc3.adapters import Observation
from arc3.perception.components import ComponentConfig, extract_components
from arc3.perception.delta import measure_delta
from arc3.types import ActionName, ActionRequest, FrameHash, GameStateName

from .models import EffectClassification, EffectKind, StateFeatures


def _metadata(observation: Observation) -> dict[str, str | int | float | bool | None]:
    values: dict[str, str | int | float | bool | None] = {
        "state": observation.state.value,
        "levels_completed": observation.levels_completed,
        "win_levels": observation.win_levels,
        "available_actions": ",".join(action.value for action in observation.available_actions),
    }
    values.update(dict(observation.upstream_metadata))
    return values


def state_features(
    observation: Observation,
    *,
    changed_cell_count: int = 0,
    condition_tokens: tuple[str, ...] = (),
) -> StateFeatures:
    """Measure a compact condition key without using game identity."""

    grid = observation.frames[-1]
    components = extract_components(grid)
    return StateFeatures(
        width=grid.width,
        height=grid.height,
        palette_size=len(grid.palette),
        component_count=len(components),
        changed_cell_count=changed_cell_count,
        game_state=observation.state,
        available_actions=observation.available_actions,
        condition_tokens=condition_tokens,
    )


def _movement_displacement(before: Observation, after: Observation) -> tuple[int, int] | None:
    before_grid = before.frames[-1]
    after_grid = after.frames[-1]
    background = Counter(cell for row in before_grid.cells for cell in row).most_common(1)[0][0]
    config = ComponentConfig(background_candidates=(background,))
    old_components = extract_components(before_grid, config=config)
    new_components = extract_components(after_grid, config=config)
    candidates: list[tuple[int, int, int]] = []
    for old in old_components:
        for new in new_components:
            if old.color != new.color or old.translation_signature != new.translation_signature:
                continue
            dx = round(new.centroid[0] - old.centroid[0])
            dy = round(new.centroid[1] - old.centroid[1])
            old_points = {(point.x, point.y) for point in old.cells}
            new_points = {(point.x, point.y) for point in new.cells}
            translated = {(x + dx, y + dy) for x, y in old_points}
            touches_delta = any(
                before_grid.cells[y][x] != after_grid.cells[y][x]
                for x, y in old_points | new_points
            )
            if (dx, dy) != (0, 0) and translated == new_points and touches_delta:
                candidates.append((old.area, dx, dy))
    if not candidates:
        return None
    _area, dx, dy = max(candidates, key=lambda item: (item[0], -abs(item[1]) - abs(item[2])))
    return dx, dy


def classify_effect(
    before: Observation,
    after: Observation,
    action: ActionRequest,
    *,
    undo_target: FrameHash | None = None,
) -> EffectClassification:
    """Classify measured consequences; simultaneous labels remain visible."""

    old_grid = before.frames[-1]
    new_grid = after.frames[-1]
    delta = measure_delta(
        old_grid,
        new_grid,
        before_metadata=_metadata(before),
        after_metadata=_metadata(after),
    )
    kinds: set[EffectKind] = set()
    displacement = _movement_displacement(before, after) if delta.cell_changes else None
    became_terminal = before.state not in {
        GameStateName.WIN,
        GameStateName.GAME_OVER,
    } and after.state in {GameStateName.WIN, GameStateName.GAME_OVER}
    supported_undo = (
        action.name is ActionName.ACTION7
        and undo_target is not None
        and new_grid.digest == undo_target
    )

    if became_terminal:
        kinds.add(EffectKind.TERMINAL)
    if supported_undo:
        kinds.add(EffectKind.UNDO)
    elif action.name is ActionName.ACTION6 and (
        delta.cell_changes or delta.metadata_changes or became_terminal
    ):
        kinds.add(EffectKind.SELECTION)
    elif displacement is not None:
        kinds.add(EffectKind.MOVEMENT)
    elif delta.cell_changes:
        kinds.add(EffectKind.INTERACTION)

    if not delta.cell_changes and delta.metadata_changes:
        kinds.add(EffectKind.METADATA_ONLY)
    if not kinds:
        kinds.add(EffectKind.NO_OP)
    return EffectClassification(
        kinds=frozenset(kinds),
        displacement=displacement,
        changed_cells=delta.changed_cell_count,
        metadata_fields=tuple(change.field for change in delta.metadata_changes),
    )


__all__ = ["classify_effect", "state_features"]
