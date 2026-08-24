"""Observation-to-effect classification without causal overclaiming."""

from __future__ import annotations

from collections import Counter
from collections.abc import Collection

from arc3.adapters import Observation
from arc3.perception.components import ComponentConfig, extract_components
from arc3.perception.delta import measure_delta
from arc3.types import ActionRequest, FrameHash, GameStateName

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


def movement_displacements(
    before: Observation,
    after: Observation,
) -> tuple[tuple[int, int], ...]:
    """Return every receipt-supported rigid translation without choosing by identity."""

    before_grid = before.frames[-1]
    after_grid = after.frames[-1]
    background = Counter(cell for row in before_grid.cells for cell in row).most_common(1)[0][0]
    config = ComponentConfig(background_candidates=(background,))
    old_components = extract_components(before_grid, config=config)
    new_components = extract_components(after_grid, config=config)
    candidates: set[tuple[int, int]] = set()
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
                candidates.add((dx, dy))
    return tuple(sorted(candidates))


def classify_effect(
    before: Observation,
    after: Observation,
    action: ActionRequest,
    *,
    undo_target: FrameHash | None = None,
    prior_frame_hashes: Collection[FrameHash] = (),
) -> EffectClassification:
    """Classify measured consequences without assigning semantics from a handle name.

    ``undo_target`` is retained as a compatibility spelling for one preserved
    prior digest.  A restore classification applies to whichever submitted
    handle actually returned that prior frame.
    """

    old_grid = before.frames[-1]
    new_grid = after.frames[-1]
    delta = measure_delta(
        old_grid,
        new_grid,
        before_metadata=_metadata(before),
        after_metadata=_metadata(after),
    )
    kinds: set[EffectKind] = set()
    displacements = movement_displacements(before, after) if delta.cell_changes else ()
    displacement = displacements[0] if len(displacements) == 1 else None
    became_terminal = before.state not in {
        GameStateName.WIN,
        GameStateName.GAME_OVER,
    } and after.state in {GameStateName.WIN, GameStateName.GAME_OVER}
    restore_targets = set(prior_frame_hashes)
    if undo_target is not None:
        restore_targets.add(undo_target)
    supported_restore = new_grid.digest != old_grid.digest and new_grid.digest in restore_targets

    if became_terminal:
        kinds.add(EffectKind.TERMINAL)
    if supported_restore:
        kinds.add(EffectKind.UNDO)
    if displacements:
        kinds.add(EffectKind.MOVEMENT)
    elif delta.cell_changes and not supported_restore:
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


__all__ = ["classify_effect", "movement_displacements", "state_features"]
