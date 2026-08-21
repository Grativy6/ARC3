"""Compile compatible typed hypotheses into executable model alternatives."""

from __future__ import annotations

from dataclasses import dataclass

from arc3.errors import WorldModelError
from arc3.hypotheses import (
    ActionSemanticsStatement,
    CollisionTraversabilityStatement,
    ControllableObjectStatement,
    CoordinateActionTargetStatement,
    HypothesisRecord,
    InteractionToggleStatement,
    StateTransitionStatement,
)
from arc3.types import ActionName

from .model import ModelCandidate, make_model_candidate
from .rules import (
    AttachmentMode,
    AttachmentRule,
    CollisionBehavior,
    CollisionRule,
    ConditionKind,
    CoordinateEffectKind,
    CoordinateEffectRule,
    CounterRule,
    MovementRule,
    RuleCondition,
    RulePrimitive,
    SelectionMode,
    SelectionRule,
    ToggleRule,
    TransformationKind,
    TransformationRule,
)


@dataclass(frozen=True, slots=True)
class CompileIssue:
    hypothesis_id: str
    reason: str


@dataclass(frozen=True, slots=True)
class CompilationResult:
    candidates: tuple[ModelCandidate, ...]
    issues: tuple[CompileIssue, ...]


def compile_hypotheses(
    records: tuple[HypothesisRecord, ...], *, max_candidates: int = 32
) -> CompilationResult:
    """Retain distinct compatible alternatives instead of choosing one narrative."""

    live = tuple(record for record in records if record.is_ensemble_eligible)
    ranked = tuple(sorted(live, key=lambda item: (-item.rank_weight, item.hypothesis_id)))
    groups = _compatible_groups(ranked, max_candidates=max_candidates)
    issues: dict[tuple[str, str], CompileIssue] = {}
    candidates: list[ModelCandidate] = []
    seen: set[str] = set()
    controllable = {
        action: statement.object_id
        for record in ranked
        if isinstance((statement := record.statement), ControllableObjectStatement)
        for action in statement.response_actions
    }
    for group in groups:
        rules: list[RulePrimitive] = []
        residuals: list[str] = []
        for record in group:
            try:
                compiled, reason = _compile_record(record, controllable)
            except (ValueError, WorldModelError) as error:
                compiled, reason = (), f"invalid executable parameters: {error}"
            rules.extend(compiled)
            if reason is not None:
                issue = CompileIssue(record.hypothesis_id, reason)
                issues[(issue.hypothesis_id, issue.reason)] = issue
                residuals.append(f"{record.hypothesis_id}: {reason}")
        candidate = make_model_candidate(
            hypothesis_ids=tuple(record.hypothesis_id for record in group),
            rules=tuple(rules),
            rank_weight=sum(record.rank_weight for record in group),
            compile_residuals=tuple(residuals),
        )
        if candidate.model_id not in seen:
            seen.add(candidate.model_id)
            candidates.append(candidate)
    return CompilationResult(
        candidates=tuple(sorted(candidates, key=lambda item: (-item.rank_weight, item.model_id))),
        issues=tuple(sorted(issues.values(), key=lambda item: (item.hypothesis_id, item.reason))),
    )


def _compatible_groups(
    records: tuple[HypothesisRecord, ...], *, max_candidates: int
) -> tuple[tuple[HypothesisRecord, ...], ...]:
    groups: dict[tuple[str, ...], tuple[HypothesisRecord, ...]] = {}
    for seed in records:
        selected = [seed]
        for candidate in records:
            if candidate is seed:
                continue
            if all(_compatible(candidate, existing) for existing in selected):
                selected.append(candidate)
        key = tuple(sorted(item.hypothesis_id for item in selected))
        groups[key] = tuple(sorted(selected, key=lambda item: item.hypothesis_id))
        if len(groups) >= max_candidates:
            break
    if not groups and records:
        groups[(records[0].hypothesis_id,)] = (records[0],)
    return tuple(groups[key] for key in sorted(groups))


def _compatible(left: HypothesisRecord, right: HypothesisRecord) -> bool:
    if right.hypothesis_id in left.conflict_ids or left.hypothesis_id in right.conflict_ids:
        return False
    if right.hypothesis_id in left.compatible_ids or left.hypothesis_id in right.compatible_ids:
        return True
    return not (
        left.family is right.family
        and left.statement.conflict_domain() == right.statement.conflict_domain()
        and left.statement.to_dict() != right.statement.to_dict()
        and (left.scope_ref is None or right.scope_ref is None or left.scope_ref == right.scope_ref)
    )


def _compile_record(
    record: HypothesisRecord, controllable: dict[str, str]
) -> tuple[tuple[RulePrimitive, ...], str | None]:
    statement = record.statement
    conditions: tuple[RuleCondition, ...] = ()
    if isinstance(statement, ActionSemanticsStatement):
        conditions = _conditions(statement.conditions)
        try:
            action = ActionName(statement.action)
        except ValueError:
            return (), f"unsupported action {statement.action!r}"
        parameters = statement.parameters
        effect = statement.effect.lower()
        rule_id = f"rule:{record.hypothesis_id}"
        if effect in {"translate", "translation", "move", "movement"}:
            return (
                MovementRule(
                    rule_id,
                    action,
                    _integer(parameters.get("dx"), default=0),
                    _integer(parameters.get("dy"), default=0),
                    entity_id=_optional_text(parameters.get("entity_id"))
                    or controllable.get(statement.action),
                    entity_kind=_optional_text(parameters.get("entity_kind")),
                    conditions=conditions,
                ),
            ), None
        if effect == "toggle":
            name = _optional_text(parameters.get("toggle")) or "toggle"
            return (ToggleRule(rule_id, action, name, conditions=conditions),), None
        if effect in {"counter", "increment_counter"}:
            name = _optional_text(parameters.get("counter")) or "counter"
            return (
                CounterRule(
                    rule_id,
                    action,
                    name,
                    _integer(parameters.get("delta"), default=1),
                    _optional_integer(parameters.get("modulus")),
                    conditions,
                ),
            ), None
        if effect in {"select", "selection"}:
            kind = _optional_text(parameters.get("target_kind")) or "selectable"
            return (SelectionRule(rule_id, action, kind, SelectionMode.SELECT, conditions),), None
        if effect in {"attach", "detach"}:
            child = _optional_text(parameters.get("child_kind")) or "movable"
            parent = _optional_text(parameters.get("parent_kind")) or "anchor"
            mode = AttachmentMode.ATTACH if effect == "attach" else AttachmentMode.DETACH
            return (AttachmentRule(rule_id, action, child, parent, mode, conditions),), None
        transformation = {
            "recolor": TransformationKind.RECOLOR,
            "delete": TransformationKind.DELETE,
            "rotate": TransformationKind.ROTATE_CLOCKWISE,
            "reflect": TransformationKind.REFLECT_HORIZONTAL,
            "transform": TransformationKind.RECOLOR,
        }.get(effect)
        if transformation is not None:
            kind = _optional_text(parameters.get("target_kind")) or "transformable"
            numeric = tuple(
                sorted(
                    (key, value)
                    for key, value in parameters.items()
                    if isinstance(value, int) and not isinstance(value, bool)
                )
            )
            return (
                TransformationRule(rule_id, action, kind, transformation, numeric, conditions),
            ), None
        return (), f"action effect {statement.effect!r} has no executable primitive"
    if isinstance(statement, CollisionTraversabilityStatement):
        behavior = CollisionBehavior.PASS if statement.traversable else CollisionBehavior.BLOCK
        if statement.consequence == "remove_obstacle":
            behavior = CollisionBehavior.REMOVE_OBSTACLE
        elif statement.consequence == "remove_mover":
            behavior = CollisionBehavior.REMOVE_MOVER
        return (
            CollisionRule(
                f"rule:{record.hypothesis_id}",
                statement.moving_kind,
                statement.obstacle_kind,
                behavior,
                _conditions(statement.conditions),
            ),
        ), None
    if isinstance(statement, InteractionToggleStatement):
        try:
            action = ActionName(statement.trigger)
        except ValueError:
            return (), "contact-triggered toggle lacks an executable action binding"
        return (
            ToggleRule(
                f"rule:{record.hypothesis_id}",
                action,
                statement.target,
                ("off", statement.resulting_state),
                _conditions(statement.conditions),
            ),
        ), None
    if isinstance(statement, CoordinateActionTargetStatement):
        try:
            action = ActionName(statement.action)
            effect = CoordinateEffectKind(statement.effect)
        except ValueError:
            return (), "unsupported coordinate action or effect"
        return (
            CoordinateEffectRule(
                f"rule:{record.hypothesis_id}",
                action,
                statement.target_kind,
                effect,
                radius=statement.radius,
                conditions=_conditions(statement.conditions),
            ),
        ), None
    if isinstance(statement, StateTransitionStatement):
        return _compile_transition(record, statement)
    if isinstance(statement, ControllableObjectStatement):
        return (), "identity claim supplies a selector but no transition effect"
    return (), f"hypothesis family {record.family.value!r} is not an executable transition"


def _compile_transition(
    record: HypothesisRecord, statement: StateTransitionStatement
) -> tuple[tuple[RulePrimitive, ...], str | None]:
    try:
        action = ActionName(statement.action)
    except ValueError:
        return (), f"unsupported action {statement.action!r}"
    rules: list[RulePrimitive] = []
    for index, effect in enumerate(statement.effects):
        parts = effect.split(":")
        rule_id = f"rule:{record.hypothesis_id}:{index}"
        conditions = _conditions(statement.preconditions)
        if len(parts) == 4 and parts[0] == "move":
            rules.append(
                MovementRule(
                    rule_id,
                    action,
                    int(parts[2]),
                    int(parts[3]),
                    entity_kind=parts[1],
                    conditions=conditions,
                )
            )
        elif len(parts) == 3 and parts[0] == "counter":
            rules.append(
                CounterRule(rule_id, action, parts[1], int(parts[2]), conditions=conditions)
            )
        elif len(parts) == 2 and parts[0] == "toggle":
            rules.append(ToggleRule(rule_id, action, parts[1], conditions=conditions))
    if rules:
        return tuple(rules), None
    return (), "state-transition effects use no recognized executable syntax"


def _conditions(values: tuple[str, ...]) -> tuple[RuleCondition, ...]:
    result: list[RuleCondition] = []
    for value in values:
        if value.startswith("!fact:"):
            result.append(RuleCondition(ConditionKind.FACT_ABSENT, value[6:]))
        elif value.startswith("fact:"):
            result.append(RuleCondition(ConditionKind.FACT_PRESENT, value[5:]))
        elif value.startswith("selected:"):
            result.append(RuleCondition(ConditionKind.SELECTED, value[9:]))
        elif value.startswith("counter:") and "=" in value:
            name, expected = value[8:].split("=", 1)
            result.append(RuleCondition(ConditionKind.COUNTER_EQUALS, name, int(expected)))
        elif value.startswith("toggle:") and "=" in value:
            name, expected = value[7:].split("=", 1)
            result.append(RuleCondition(ConditionKind.TOGGLE_EQUALS, name, expected))
        else:
            result.append(RuleCondition(ConditionKind.FACT_PRESENT, value))
    return tuple(sorted(set(result)))


def _integer(value: object, *, default: int) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else default


def _optional_integer(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _optional_text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


__all__ = ["CompilationResult", "CompileIssue", "compile_hypotheses"]
