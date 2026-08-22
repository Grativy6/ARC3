"""Interpretable executable rule primitives for ARC3 world-model candidates."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

from arc3.errors import WorldModelError
from arc3.types import ActionName, ActionRequest, JSONValue

from .state import Attachment, Cell, SymbolicEntity, SymbolicState


class ConditionKind(StrEnum):
    FACT_PRESENT = "fact_present"
    FACT_ABSENT = "fact_absent"
    COUNTER_EQUALS = "counter_equals"
    TOGGLE_EQUALS = "toggle_equals"
    SELECTED = "selected"


@dataclass(frozen=True, slots=True, order=True)
class RuleCondition:
    """An explicit, inspectable scope narrowing for a rule."""

    kind: ConditionKind
    subject: str
    value: str | int | None = None

    def matches(self, state: SymbolicState) -> bool:
        if self.kind is ConditionKind.FACT_PRESENT:
            return self.subject in state.facts
        if self.kind is ConditionKind.FACT_ABSENT:
            return self.subject not in state.facts
        if self.kind is ConditionKind.COUNTER_EQUALS:
            return state.counter(self.subject) == self.value
        if self.kind is ConditionKind.TOGGLE_EQUALS:
            return state.toggle(self.subject) == self.value
        return state.selected_id == self.subject


class CollisionBehavior(StrEnum):
    BLOCK = "block"
    PASS = "pass"
    REMOVE_OBSTACLE = "remove_obstacle"
    REMOVE_MOVER = "remove_mover"


class TransformationKind(StrEnum):
    RECOLOR = "recolor"
    DELETE = "delete"
    ROTATE_CLOCKWISE = "rotate_clockwise"
    REFLECT_HORIZONTAL = "reflect_horizontal"
    TRANSLATE = "translate"


class SelectionMode(StrEnum):
    SELECT = "select"
    CLEAR = "clear"
    TOGGLE = "toggle"


class AttachmentMode(StrEnum):
    ATTACH = "attach"
    DETACH = "detach"


class CoordinateEffectKind(StrEnum):
    SELECT = "select"
    TOGGLE = "toggle"
    RECOLOR = "recolor"
    DELETE = "delete"
    TRANSLATE = "translate"
    ADD_FACT = "add_fact"


class ContactRelation(StrEnum):
    OVERLAP = "overlap"
    ADJACENT = "adjacent"


class ContactEffectKind(StrEnum):
    ADD_FACT = "add_fact"
    REMOVE_FACT = "remove_fact"
    SET_TOGGLE = "set_toggle"
    INCREMENT_COUNTER = "increment_counter"


@dataclass(frozen=True, slots=True)
class MovementRule:
    rule_id: str
    action: ActionName
    dx: int
    dy: int
    entity_id: str | None = None
    entity_kind: str | None = None
    conditions: tuple[RuleCondition, ...] = ()

    def __post_init__(self) -> None:
        _validate_rule(self.rule_id, self.conditions)
        if self.entity_id is None and self.entity_kind is None:
            raise WorldModelError("movement rule requires an entity ID or kind")
        if self.dx == 0 and self.dy == 0:
            raise WorldModelError("movement rule requires a non-zero displacement")


@dataclass(frozen=True, slots=True)
class NoOpRule:
    """An action-scoped identity consequence, not a model-wide empty program."""

    rule_id: str
    action: ActionName
    entity_id: str | None = None
    entity_kind: str | None = None
    conditions: tuple[RuleCondition, ...] = ()

    def __post_init__(self) -> None:
        _validate_rule(self.rule_id, self.conditions)
        if self.entity_id is None and self.entity_kind is None:
            raise WorldModelError("no-op rule requires an entity ID or kind")


@dataclass(frozen=True, slots=True)
class CollisionRule:
    rule_id: str
    moving_kind: str
    obstacle_kind: str
    behavior: CollisionBehavior
    conditions: tuple[RuleCondition, ...] = ()

    def __post_init__(self) -> None:
        _validate_rule(self.rule_id, self.conditions)


@dataclass(frozen=True, slots=True)
class ToggleRule:
    rule_id: str
    action: ActionName
    toggle_name: str
    values: tuple[str, ...] = ("off", "on")
    conditions: tuple[RuleCondition, ...] = ()

    def __post_init__(self) -> None:
        _validate_rule(self.rule_id, self.conditions)
        if len(self.values) < 2 or len(set(self.values)) != len(self.values):
            raise WorldModelError("toggle rules require at least two distinct values")


@dataclass(frozen=True, slots=True)
class TransformationRule:
    rule_id: str
    action: ActionName
    target_kind: str
    operation: TransformationKind
    parameters: tuple[tuple[str, int], ...] = ()
    conditions: tuple[RuleCondition, ...] = ()

    def __post_init__(self) -> None:
        _validate_rule(self.rule_id, self.conditions)


@dataclass(frozen=True, slots=True)
class CounterRule:
    rule_id: str
    action: ActionName
    counter_name: str
    delta: int
    modulus: int | None = None
    conditions: tuple[RuleCondition, ...] = ()

    def __post_init__(self) -> None:
        _validate_rule(self.rule_id, self.conditions)
        if self.modulus is not None and self.modulus < 1:
            raise WorldModelError("counter modulus must be positive")


@dataclass(frozen=True, slots=True)
class ContactRule:
    rule_id: str
    moving_kind: str
    target_kind: str
    relation: ContactRelation
    effect: ContactEffectKind
    effect_name: str
    effect_value: str | int | None = None
    conditions: tuple[RuleCondition, ...] = ()

    def __post_init__(self) -> None:
        _validate_rule(self.rule_id, self.conditions)


@dataclass(frozen=True, slots=True)
class SelectionRule:
    rule_id: str
    action: ActionName
    target_kind: str
    mode: SelectionMode = SelectionMode.SELECT
    conditions: tuple[RuleCondition, ...] = ()

    def __post_init__(self) -> None:
        _validate_rule(self.rule_id, self.conditions)


@dataclass(frozen=True, slots=True)
class AttachmentRule:
    rule_id: str
    action: ActionName
    child_kind: str
    parent_kind: str
    mode: AttachmentMode = AttachmentMode.ATTACH
    conditions: tuple[RuleCondition, ...] = ()

    def __post_init__(self) -> None:
        _validate_rule(self.rule_id, self.conditions)


@dataclass(frozen=True, slots=True)
class CoordinateEffectRule:
    rule_id: str
    action: ActionName
    target_kind: str
    effect: CoordinateEffectKind
    parameters: tuple[tuple[str, int | str], ...] = ()
    radius: int = 0
    conditions: tuple[RuleCondition, ...] = ()

    def __post_init__(self) -> None:
        _validate_rule(self.rule_id, self.conditions)
        if not self.action.requires_coordinates:
            raise WorldModelError("coordinate-effect rules require a coordinate action")
        if self.radius < 0:
            raise WorldModelError("coordinate-effect radius must be non-negative")


type RulePrimitive = (
    MovementRule
    | NoOpRule
    | CollisionRule
    | ToggleRule
    | TransformationRule
    | CounterRule
    | ContactRule
    | SelectionRule
    | AttachmentRule
    | CoordinateEffectRule
)


@dataclass(frozen=True, slots=True)
class RuleEffect:
    kind: str
    target: str
    before: JSONValue
    after: JSONValue


@dataclass(frozen=True, slots=True)
class RuleExecution:
    state: SymbolicState
    effects: tuple[RuleEffect, ...]
    applied_rule_ids: tuple[str, ...]


def conditions_match(conditions: tuple[RuleCondition, ...], state: SymbolicState) -> bool:
    return all(condition.matches(state) for condition in conditions)


def execute_rules(
    rules: tuple[RulePrimitive, ...], state: SymbolicState, action: ActionRequest
) -> RuleExecution:
    """Execute all applicable effects in a stable phase order."""

    current = state
    effects: list[RuleEffect] = []
    applied: list[str] = []
    ordered = sorted(rules, key=_rule_order)
    collisions = tuple(rule for rule in ordered if isinstance(rule, CollisionRule))
    contacts = tuple(rule for rule in ordered if isinstance(rule, ContactRule))
    for rule in ordered:
        if isinstance(rule, (CollisionRule, ContactRule)):
            continue
        if rule.action is not action.name or not conditions_match(rule.conditions, current):
            continue
        before_id = current.state_id
        if isinstance(rule, MovementRule):
            current, new_effects = _move(current, rule, collisions, contacts)
        elif isinstance(rule, NoOpRule):
            new_effects = (RuleEffect("no_op", rule.action.value, "unchanged", "unchanged"),)
        elif isinstance(rule, ToggleRule):
            current, new_effects = _toggle(current, rule)
        elif isinstance(rule, TransformationRule):
            current, new_effects = _transform(current, rule)
        elif isinstance(rule, CounterRule):
            current, new_effects = _counter(current, rule)
        elif isinstance(rule, SelectionRule):
            current, new_effects = _select(current, action, rule)
        elif isinstance(rule, AttachmentRule):
            current, new_effects = _attach(current, rule)
        else:
            current, new_effects = _coordinate(current, action, rule)
        if current.state_id != before_id or new_effects:
            applied.append(rule.rule_id)
            effects.extend(new_effects)
    return RuleExecution(current, tuple(effects), tuple(applied))


def rule_action(rule: RulePrimitive) -> ActionName | None:
    return rule.action if not isinstance(rule, (CollisionRule, ContactRule)) else None


def rule_complexity(rule: RulePrimitive) -> int:
    base = 1 + len(rule.conditions)
    if isinstance(rule, (TransformationRule, CoordinateEffectRule)):
        return base + len(rule.parameters)
    if isinstance(rule, ContactRule):
        return base + 2
    return base


def _move(
    state: SymbolicState,
    rule: MovementRule,
    collision_rules: tuple[CollisionRule, ...],
    contact_rules: tuple[ContactRule, ...],
) -> tuple[SymbolicState, tuple[RuleEffect, ...]]:
    targets = tuple(
        entity
        for entity in state.entities
        if (rule.entity_id is None or entity.entity_id == rule.entity_id)
        and (rule.entity_kind is None or entity.kind == rule.entity_kind)
    )
    current = state
    effects: list[RuleEffect] = []
    for original in targets:
        entity = current.entity(original.entity_id)
        if entity is None:
            continue
        moved = entity.translated(rule.dx, rule.dy)
        if any(not current.contains(cell) for cell in moved.cells):
            effects.append(RuleEffect("collision", entity.entity_id, "boundary", "blocked"))
            continue
        obstacles = tuple(
            other
            for other in current.entities
            if other.entity_id != entity.entity_id and set(other.cells) & set(moved.cells)
        )
        blocked = False
        for obstacle in obstacles:
            matching = next(
                (
                    candidate
                    for candidate in collision_rules
                    if _matches_entity_kind(entity, candidate.moving_kind)
                    and _matches_entity_kind(obstacle, candidate.obstacle_kind)
                    and conditions_match(candidate.conditions, current)
                ),
                None,
            )
            behavior = matching.behavior if matching is not None else CollisionBehavior.BLOCK
            if behavior is CollisionBehavior.BLOCK:
                blocked = True
                effects.append(
                    RuleEffect("collision", obstacle.entity_id, obstacle.kind, "blocked")
                )
            elif behavior is CollisionBehavior.REMOVE_OBSTACLE:
                current = current.remove_entity(obstacle.entity_id)
                effects.append(
                    RuleEffect("collision", obstacle.entity_id, obstacle.kind, "removed")
                )
            elif behavior is CollisionBehavior.REMOVE_MOVER:
                current = current.remove_entity(entity.entity_id)
                effects.append(RuleEffect("collision", entity.entity_id, entity.kind, "removed"))
                blocked = True
        if blocked:
            continue
        current = current.replace_entity(moved)
        effects.append(
            RuleEffect(
                "movement",
                entity.entity_id,
                [[cell.x, cell.y] for cell in entity.cells],
                [[cell.x, cell.y] for cell in moved.cells],
            )
        )
        current, attachment_effects = _follow_attachments(current, entity, moved)
        effects.extend(attachment_effects)
        current, contact_effects = _apply_contacts(current, moved, contact_rules)
        effects.extend(contact_effects)
    return current, tuple(effects)


def _matches_entity_kind(entity: SymbolicEntity, expected: str) -> bool:
    """Match either an interpreted kind or an anonymous palette-role identity."""

    return entity.kind == expected or dict(entity.attributes).get("palette_role") == expected


def _follow_attachments(
    state: SymbolicState, before: SymbolicEntity, after: SymbolicEntity
) -> tuple[SymbolicState, tuple[RuleEffect, ...]]:
    dx = after.anchor.x - before.anchor.x
    dy = after.anchor.y - before.anchor.y
    current = state
    effects: list[RuleEffect] = []
    for link in state.attachments:
        if link.parent_id != after.entity_id:
            continue
        child = current.entity(link.child_id)
        if child is None:
            continue
        moved = child.translated(dx, dy)
        if all(current.contains(cell) for cell in moved.cells):
            current = current.replace_entity(moved)
            effects.append(RuleEffect("attachment_follow", child.entity_id, "attached", "moved"))
    return current, tuple(effects)


def _apply_contacts(
    state: SymbolicState, mover: SymbolicEntity, rules: tuple[ContactRule, ...]
) -> tuple[SymbolicState, tuple[RuleEffect, ...]]:
    current = state
    effects: list[RuleEffect] = []
    for rule in rules:
        if mover.kind != rule.moving_kind or not conditions_match(rule.conditions, current):
            continue
        for target in current.entities_of_kind(rule.target_kind):
            if target.entity_id == mover.entity_id or not _in_contact(mover, target, rule.relation):
                continue
            before: JSONValue = None
            after: JSONValue = rule.effect_value
            if rule.effect is ContactEffectKind.ADD_FACT:
                before = rule.effect_name in current.facts
                current = current.with_fact(rule.effect_name)
                after = True
            elif rule.effect is ContactEffectKind.REMOVE_FACT:
                before = rule.effect_name in current.facts
                current = current.with_fact(rule.effect_name, present=False)
                after = False
            elif rule.effect is ContactEffectKind.SET_TOGGLE:
                before = current.toggle(rule.effect_name)
                current = current.with_toggle(rule.effect_name, str(rule.effect_value))
                after = current.toggle(rule.effect_name)
            else:
                before = current.counter(rule.effect_name)
                increment = rule.effect_value if isinstance(rule.effect_value, int) else 1
                current = current.with_counter(rule.effect_name, int(before) + increment)
                after = current.counter(rule.effect_name)
            effects.append(RuleEffect("contact", rule.effect_name, before, after))
    return current, tuple(effects)


def _in_contact(left: SymbolicEntity, right: SymbolicEntity, relation: ContactRelation) -> bool:
    if relation is ContactRelation.OVERLAP:
        return bool(set(left.cells) & set(right.cells))
    return any(
        abs(source.x - target.x) + abs(source.y - target.y) == 1
        for source in left.cells
        for target in right.cells
    )


def _toggle(state: SymbolicState, rule: ToggleRule) -> tuple[SymbolicState, tuple[RuleEffect, ...]]:
    before = state.toggle(rule.toggle_name, rule.values[0])
    try:
        index = rule.values.index(before)
    except ValueError:
        index = 0
    after = rule.values[(index + 1) % len(rule.values)]
    return state.with_toggle(rule.toggle_name, after), (
        RuleEffect("toggle", rule.toggle_name, before, after),
    )


def _transform(
    state: SymbolicState, rule: TransformationRule
) -> tuple[SymbolicState, tuple[RuleEffect, ...]]:
    current = state
    effects: list[RuleEffect] = []
    parameters = dict(rule.parameters)
    for entity in state.entities_of_kind(rule.target_kind):
        if rule.operation is TransformationKind.DELETE:
            current = current.remove_entity(entity.entity_id)
            effects.append(RuleEffect("transformation", entity.entity_id, "present", "deleted"))
            continue
        if rule.operation is TransformationKind.RECOLOR:
            updated = replace(entity, color=parameters.get("color", entity.color))
        elif rule.operation is TransformationKind.TRANSLATE:
            updated = entity.translated(parameters.get("dx", 0), parameters.get("dy", 0))
        else:
            anchor = entity.anchor
            relative = tuple((cell.x - anchor.x, cell.y - anchor.y) for cell in entity.cells)
            if rule.operation is TransformationKind.ROTATE_CLOCKWISE:
                transformed = tuple((y, -x) for x, y in relative)
            else:
                transformed = tuple((-x, y) for x, y in relative)
            min_x = min(x for x, _y in transformed)
            min_y = min(y for _x, y in transformed)
            updated = replace(
                entity,
                cells=tuple(
                    Cell(anchor.x + x - min_x, anchor.y + y - min_y) for x, y in transformed
                ),
            )
        if all(current.contains(cell) for cell in updated.cells):
            current = current.replace_entity(updated)
            effects.append(
                RuleEffect("transformation", entity.entity_id, entity.color, updated.color)
            )
    return current, tuple(effects)


def _counter(
    state: SymbolicState, rule: CounterRule
) -> tuple[SymbolicState, tuple[RuleEffect, ...]]:
    before = state.counter(rule.counter_name)
    after = before + rule.delta
    if rule.modulus is not None:
        after %= rule.modulus
    return state.with_counter(rule.counter_name, after), (
        RuleEffect("counter", rule.counter_name, before, after),
    )


def _select(
    state: SymbolicState, action: ActionRequest, rule: SelectionRule
) -> tuple[SymbolicState, tuple[RuleEffect, ...]]:
    if rule.mode is SelectionMode.CLEAR:
        return replace(state, selected_id=None), (
            RuleEffect("selection", "selected_id", state.selected_id, None),
        )
    targets = state.entities_of_kind(rule.target_kind)
    if action.coordinate is not None:
        coordinate = Cell(action.coordinate.x, action.coordinate.y)
        targets = tuple(item for item in targets if coordinate in item.cells)
    selected = targets[0].entity_id if targets else None
    if rule.mode is SelectionMode.TOGGLE and selected == state.selected_id:
        selected = None
    return replace(state, selected_id=selected), (
        RuleEffect("selection", "selected_id", state.selected_id, selected),
    )


def _attach(
    state: SymbolicState, rule: AttachmentRule
) -> tuple[SymbolicState, tuple[RuleEffect, ...]]:
    children = state.entities_of_kind(rule.child_kind)
    parents = state.entities_of_kind(rule.parent_kind)
    if state.selected_id is not None:
        children = tuple(item for item in children if item.entity_id == state.selected_id)
    if not children or not parents:
        return state, ()
    child, parent = children[0], parents[0]
    if rule.mode is AttachmentMode.DETACH:
        links = tuple(item for item in state.attachments if item.child_id != child.entity_id)
        return replace(state, attachments=links), (
            RuleEffect("attachment", child.entity_id, "attached", "detached"),
        )
    link = Attachment(
        child.entity_id,
        parent.entity_id,
        child.anchor.x - parent.anchor.x,
        child.anchor.y - parent.anchor.y,
    )
    return replace(state, attachments=(*state.attachments, link)), (
        RuleEffect("attachment", child.entity_id, "detached", parent.entity_id),
    )


def _coordinate(
    state: SymbolicState, action: ActionRequest, rule: CoordinateEffectRule
) -> tuple[SymbolicState, tuple[RuleEffect, ...]]:
    if action.coordinate is None:
        return state, ()
    point = Cell(action.coordinate.x, action.coordinate.y)
    targets = tuple(
        entity
        for entity in state.entities_of_kind(rule.target_kind)
        if min(abs(cell.x - point.x) + abs(cell.y - point.y) for cell in entity.cells)
        <= rule.radius
    )
    parameters = dict(rule.parameters)
    if rule.effect is CoordinateEffectKind.SELECT:
        selected = targets[0].entity_id if targets else None
        return replace(state, selected_id=selected), (
            RuleEffect("coordinate_selection", "selected_id", state.selected_id, selected),
        )
    if rule.effect is CoordinateEffectKind.ADD_FACT:
        fact = str(parameters.get("fact", "coordinate_effect"))
        return state.with_fact(fact), (RuleEffect("coordinate_fact", fact, False, True),)
    current = state
    effects: list[RuleEffect] = []
    for entity in targets:
        if rule.effect is CoordinateEffectKind.DELETE:
            current = current.remove_entity(entity.entity_id)
            after: JSONValue = "deleted"
        elif rule.effect is CoordinateEffectKind.RECOLOR:
            color = parameters.get("color")
            if not isinstance(color, int):
                raise WorldModelError("coordinate recolor requires an integer color")
            current = current.replace_entity(replace(entity, color=color))
            after = color
        elif rule.effect is CoordinateEffectKind.TRANSLATE:
            dx = parameters.get("dx", 0)
            dy = parameters.get("dy", 0)
            if not isinstance(dx, int) or not isinstance(dy, int):
                raise WorldModelError("coordinate translation requires integer dx/dy")
            moved = entity.translated(dx, dy)
            if all(current.contains(cell) for cell in moved.cells):
                current = current.replace_entity(moved)
            after = [[cell.x, cell.y] for cell in moved.cells]
        else:
            name = str(parameters.get("toggle", entity.entity_id))
            value = str(parameters.get("value", "on"))
            current = current.with_toggle(name, value)
            after = value
        effects.append(RuleEffect("coordinate_effect", entity.entity_id, entity.color, after))
    return current, tuple(effects)


def _validate_rule(rule_id: str, conditions: tuple[RuleCondition, ...]) -> None:
    if not rule_id.strip():
        raise WorldModelError("rule_id must be non-empty")
    if len(set(conditions)) != len(conditions):
        raise WorldModelError("rule conditions must be unique")


def _rule_order(rule: RulePrimitive) -> tuple[int, str]:
    phase = {
        SelectionRule: 0,
        AttachmentRule: 1,
        MovementRule: 2,
        NoOpRule: 2,
        ToggleRule: 3,
        TransformationRule: 4,
        CounterRule: 5,
        CoordinateEffectRule: 6,
        CollisionRule: 7,
        ContactRule: 8,
    }[type(rule)]
    return phase, rule.rule_id


__all__ = [
    "AttachmentMode",
    "AttachmentRule",
    "CollisionBehavior",
    "CollisionRule",
    "ConditionKind",
    "ContactEffectKind",
    "ContactRelation",
    "ContactRule",
    "CoordinateEffectKind",
    "CoordinateEffectRule",
    "CounterRule",
    "MovementRule",
    "NoOpRule",
    "RuleCondition",
    "RuleEffect",
    "RuleExecution",
    "RulePrimitive",
    "SelectionMode",
    "SelectionRule",
    "ToggleRule",
    "TransformationKind",
    "TransformationRule",
    "conditions_match",
    "execute_rules",
    "rule_action",
    "rule_complexity",
]
