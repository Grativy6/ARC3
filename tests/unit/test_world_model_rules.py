from __future__ import annotations

from arc3.types import ActionName, ActionRequest, Coordinate
from arc3.world_model import (
    AttachmentMode,
    AttachmentRule,
    Cell,
    CollisionBehavior,
    CollisionRule,
    ContactEffectKind,
    ContactRelation,
    ContactRule,
    CoordinateEffectKind,
    CoordinateEffectRule,
    CounterRule,
    MovementRule,
    SelectionMode,
    SelectionRule,
    SymbolicEntity,
    SymbolicState,
    ToggleRule,
    TransformationKind,
    TransformationRule,
    execute_rules,
)


def entity(identifier: str, kind: str, x: int, y: int, *, color: int = 1) -> SymbolicEntity:
    return SymbolicEntity(identifier, kind, (Cell(x, y),), color)


def test_movement_collision_and_contact_are_executable_and_visible() -> None:
    state = SymbolicState(
        5,
        5,
        (entity("m", "mover", 1, 1), entity("w", "wall", 2, 1)),
    )
    movement = MovementRule("move", ActionName.ACTION1, 1, 0, entity_kind="mover")

    blocked = execute_rules((movement,), state, ActionRequest(ActionName.ACTION1))
    assert blocked.state == state
    assert blocked.effects[0].kind == "collision"

    pass_through = CollisionRule("pass", "mover", "wall", CollisionBehavior.PASS)
    contact = ContactRule(
        "touch",
        "mover",
        "wall",
        ContactRelation.OVERLAP,
        ContactEffectKind.ADD_FACT,
        "touched",
    )
    advanced = execute_rules(
        (movement, pass_through, contact), state, ActionRequest(ActionName.ACTION1)
    )

    assert advanced.state.entity("m") == entity("m", "mover", 2, 1)
    assert "touched" in advanced.state.facts
    assert {effect.kind for effect in advanced.effects} == {"movement", "contact"}


def test_toggle_counter_transformation_selection_and_coordinate_effects_execute() -> None:
    state = SymbolicState(6, 6, (entity("p", "piece", 1, 1, color=2),))
    rules = (
        ToggleRule("toggle", ActionName.ACTION2, "door"),
        CounterRule("counter", ActionName.ACTION2, "ticks", 1, modulus=3),
        TransformationRule(
            "recolor",
            ActionName.ACTION3,
            "piece",
            TransformationKind.RECOLOR,
            (("color", 7),),
        ),
        SelectionRule("select", ActionName.ACTION6, "piece", SelectionMode.SELECT),
        CoordinateEffectRule(
            "coordinate-recolor",
            ActionName.ACTION6,
            "piece",
            CoordinateEffectKind.RECOLOR,
            (("color", 9),),
        ),
    )

    toggled = execute_rules(rules, state, ActionRequest(ActionName.ACTION2)).state
    transformed = execute_rules(rules, toggled, ActionRequest(ActionName.ACTION3)).state
    selected = execute_rules(
        rules,
        transformed,
        ActionRequest(ActionName.ACTION6, Coordinate(1, 1)),
    ).state

    assert toggled.toggle("door") == "on"
    assert toggled.counter("ticks") == 1
    assert transformed.entity("p") is not None
    assert transformed.entity("p").color == 7  # type: ignore[union-attr]
    assert selected.selected_id == "p"
    assert selected.entity("p") is not None
    assert selected.entity("p").color == 9  # type: ignore[union-attr]


def test_attachment_follows_parent_motion_and_can_be_detached() -> None:
    state = SymbolicState(
        7,
        7,
        (entity("child", "token", 1, 2), entity("parent", "carrier", 1, 1)),
        selected_id="child",
    )
    attach = AttachmentRule("attach", ActionName.ACTION5, "token", "carrier", AttachmentMode.ATTACH)
    move = MovementRule("move", ActionName.ACTION1, 1, 0, entity_kind="carrier")
    detach = AttachmentRule("detach", ActionName.ACTION4, "token", "carrier", AttachmentMode.DETACH)

    attached = execute_rules((attach, move, detach), state, ActionRequest(ActionName.ACTION5)).state
    moved = execute_rules((attach, move, detach), attached, ActionRequest(ActionName.ACTION1)).state
    detached = execute_rules((attach, move, detach), moved, ActionRequest(ActionName.ACTION4)).state

    assert attached.attachments[0].child_id == "child"
    assert moved.entity("parent").anchor == Cell(2, 1)  # type: ignore[union-attr]
    assert moved.entity("child").anchor == Cell(2, 2)  # type: ignore[union-attr]
    assert detached.attachments == ()
