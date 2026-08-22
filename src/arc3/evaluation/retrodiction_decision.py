"""Frozen Stage 07 retrodiction-decision cases, matrix, and decision gates.

This module is evaluation infrastructure.  Evaluator truth and public-game
identity remain outside production policy state.  The base declaration and its
single premeasurement amendment jointly control every value materialized here.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import cast

from arc3.ablations import runner as stage14_runner
from arc3.errors import EvaluationError
from arc3.evaluation.artifacts import seal_object, sha256_file
from arc3.evaluation.public import PublicPartitionManifest
from arc3.lab.rule_change import (
    RuleChangeCase,
    intervention_schedule,
    noise_control_schedule,
)
from arc3.trace.canonical import normalize_json, sha256_json
from arc3.types import ActionName, ActionRequest, Coordinate, JSONValue
from arc3.world_model.model import ModelCandidate, make_model_candidate
from arc3.world_model.retrodiction import PreservedTransition, RetrodictionMode
from arc3.world_model.rules import (
    CollisionBehavior,
    CollisionRule,
    ConditionKind,
    ContactEffectKind,
    ContactRelation,
    ContactRule,
    CounterRule,
    MovementRule,
    NoOpRule,
    RuleCondition,
    RulePrimitive,
    SelectionRule,
    ToggleRule,
    TransformationKind,
    TransformationRule,
)
from arc3.world_model.state import Cell, SymbolicEntity, SymbolicState

ROOT = Path(__file__).resolve().parents[3]
PREDECLARATION_PATH = ROOT / "docs/evidence/001-07-retrodiction-predeclaration.json"
PREDECLARATION_SHA256 = "sha256:d4eb82f2e0c04e1c94be4d6fbaa8862aa808cc07932042a02d0c5fbcc02dc608"
AMENDMENT_PATH = ROOT / "docs/evidence/001-07-retrodiction-predeclaration-amendment-01.json"
AMENDMENT_SHA256 = "sha256:5c8ff0c91602d86ecaadd61197dfb80681f618ad4e6c810c26933ca337fdcc3b"
FALSE_RULE_MANIFEST_PATH = ROOT / "docs/evidence/001-07-false-rule-case-manifest.json"
PUBLIC_PARTITION_PATH = ROOT / "docs/evaluation/public-game-partitions.v0.1.json"
PUBLIC_PARTITION_SHA256 = "sha256:682d5891c2aface54803d9bd1173c55ed21e89856e13b8a478fb9276ee963f2f"
STAGE14_CASE_MANIFEST_SHA256 = (
    "sha256:121264695566131342f3af9fbdefa0b3a0a2c812759467ef3863fcdbe339caa9"
)
STAGE14_PROTOCOL_SHA256 = "sha256:41539f8cf16481ce465221ec7a1b7dcfe79952f06bdd3d9521b9fc24a75614b4"
STAGE14_PROTOCOL_MANIFEST_SHA256 = (
    "sha256:b00c45337f451ecde9af097ce68c8eb60203a7516bff55d9ed7c40868700b369"
)

MODE_ORDER = (
    RetrodictionMode.FULL,
    RetrodictionMode.NONE,
    RetrodictionMode.RECENT_WINDOW_8,
    RetrodictionMode.EVENT_TRIGGERED,
    RetrodictionMode.CACHED_INCREMENTAL,
)
MICRO_HISTORY_SIZES = (2, 4, 8, 16, 32, 64)
MICRO_WARMUPS = 5
MICRO_REPETITIONS = 31
MICRO_MATERIAL_HISTORY_FLOOR = 16
MAX_OVERALL_WALL_SECONDS = 3_600.0
MAX_PEAK_RSS_BYTES = 2 * 1024 * 1024 * 1024
RETRODICTION_CACHE_CAPACITY = 64

_GROUP_A_COUNT = 14
_GROUP_B_COUNT = 8
_GROUP_C_COUNT = 32
_GROUP_D_COUNT = 2
EXPECTED_EVALUATION_CELLS = 280

_C_INTERVENTION_IDS = (
    "stage06-intervention-action_effect_rotation-early_support_2-s7-identity-identity",
    "stage06-intervention-action_effect_rotation-early_support_2-s11-affine_nonidentity-cycle1234",
    "stage06-intervention-action_effect_rotation-early_support_2-s23-identity-identity",
    "stage06-intervention-action_effect_rotation-early_support_2-s29-affine_nonidentity-cycle1234",
    "stage06-intervention-action_effect_rotation-late_support_4-s7-identity-cycle1234",
    "stage06-intervention-action_effect_rotation-late_support_4-s11-affine_nonidentity-identity",
    "stage06-intervention-action_effect_rotation-late_support_4-s23-identity-cycle1234",
    "stage06-intervention-action_effect_rotation-late_support_4-s29-affine_nonidentity-identity",
    "stage06-intervention-traversability_flip-early_support_2-s7-affine_nonidentity-identity",
    "stage06-intervention-traversability_flip-early_support_2-s11-identity-cycle1234",
    "stage06-intervention-traversability_flip-early_support_2-s23-affine_nonidentity-identity",
    "stage06-intervention-traversability_flip-early_support_2-s29-identity-cycle1234",
    "stage06-intervention-traversability_flip-late_support_4-s7-affine_nonidentity-cycle1234",
    "stage06-intervention-traversability_flip-late_support_4-s11-identity-identity",
    "stage06-intervention-traversability_flip-late_support_4-s23-affine_nonidentity-cycle1234",
    "stage06-intervention-traversability_flip-late_support_4-s29-identity-identity",
)
_C_NOISE_IDS = (
    "stage06-noise-early_support_2-s7-identity-identity",
    "stage06-noise-early_support_2-s7-affine_nonidentity-cycle1234",
    "stage06-noise-early_support_2-s11-affine_nonidentity-cycle1234",
    "stage06-noise-early_support_2-s11-identity-identity",
    "stage06-noise-early_support_2-s23-identity-identity",
    "stage06-noise-early_support_2-s23-affine_nonidentity-cycle1234",
    "stage06-noise-early_support_2-s29-affine_nonidentity-cycle1234",
    "stage06-noise-early_support_2-s29-identity-identity",
    "stage06-noise-late_support_4-s7-identity-cycle1234",
    "stage06-noise-late_support_4-s7-affine_nonidentity-identity",
    "stage06-noise-late_support_4-s11-affine_nonidentity-identity",
    "stage06-noise-late_support_4-s11-identity-cycle1234",
    "stage06-noise-late_support_4-s23-identity-cycle1234",
    "stage06-noise-late_support_4-s23-affine_nonidentity-identity",
    "stage06-noise-late_support_4-s29-affine_nonidentity-identity",
    "stage06-noise-late_support_4-s29-identity-cycle1234",
)
_FALSE_RULE_CASE_IDS = (
    "stage07-false-rule-b01-movement-sign",
    "stage07-false-rule-b02-noop-vs-translation",
    "stage07-false-rule-b03-collision-pass-vs-block",
    "stage07-false-rule-b04-toggle-cycle",
    "stage07-false-rule-b05-counter-delta",
    "stage07-false-rule-b06-recolor-value",
    "stage07-false-rule-b07-contact-effect",
    "stage07-false-rule-b08-coordinate-selection",
)


class EvaluationGroup(StrEnum):
    """Frozen Stage 07 matrix group."""

    A_STAGE14 = "A"
    B_FALSE_RULE = "B"
    C_RULE_CHANGE = "C"
    D_LOCAL_PUBLIC = "D"


class RetrodictionDecision(StrEnum):
    KEEP_FULL = "KEEP_FULL"
    REMOVE_NONE = "REMOVE_NONE"
    NARROW_RECENT_WINDOW_8 = "NARROW_RECENT_WINDOW_8"
    DEFER_EVENT_TRIGGERED = "DEFER_EVENT_TRIGGERED"
    CACHE_INCREMENTAL = "CACHE_INCREMENTAL"


_DECISION_BY_MODE = {
    RetrodictionMode.NONE: RetrodictionDecision.REMOVE_NONE,
    RetrodictionMode.RECENT_WINDOW_8: RetrodictionDecision.NARROW_RECENT_WINDOW_8,
    RetrodictionMode.EVENT_TRIGGERED: RetrodictionDecision.DEFER_EVENT_TRIGGERED,
    RetrodictionMode.CACHED_INCREMENTAL: RetrodictionDecision.CACHE_INCREMENTAL,
}
_COVERAGE_TIE_ORDER = (
    RetrodictionMode.CACHED_INCREMENTAL,
    RetrodictionMode.EVENT_TRIGGERED,
    RetrodictionMode.RECENT_WINDOW_8,
    RetrodictionMode.NONE,
)


@dataclass(frozen=True, slots=True)
class FalseRuleCase:
    """One evaluator-known TRUE/FALSE pair over a sealed 12-transition history."""

    case_id: str
    seed: int
    code: str
    action: ActionRequest
    true_model: ModelCandidate
    false_model: ModelCandidate
    transitions: tuple[PreservedTransition, ...]
    rare_true: str
    rare_false: str
    ordinary_shared: str

    def __post_init__(self) -> None:
        if self.case_id not in _FALSE_RULE_CASE_IDS:
            raise EvaluationError("false-rule case identity is outside the frozen declaration")
        expected_seed = _FALSE_RULE_CASE_IDS.index(self.case_id) + 1
        if self.seed != expected_seed:
            raise EvaluationError("false-rule seed disagrees with the amendment")
        if self.code != f"B{expected_seed:02d}":
            raise EvaluationError("false-rule code disagrees with its case identity")
        if len(self.transitions) != 12:
            raise EvaluationError("false-rule history must contain exactly 12 transitions")
        expected_ids = tuple(f"stage07-b{expected_seed:02d}-t{index:02d}" for index in range(12))
        if tuple(item.transition_id for item in self.transitions) != expected_ids:
            raise EvaluationError("false-rule transition order is not frozen T00 through T11")
        if self.true_model.rank_weight != 1 or self.false_model.rank_weight != 9:
            raise EvaluationError("false-rule candidate rank weights must remain 1 and 9")
        compatible = {self.true_model.model_id, self.false_model.model_id}
        if any(set(item.compatible_model_ids) != compatible for item in self.transitions):
            raise EvaluationError("false-rule transitions must bind both sealed candidates")
        if "rare" not in self.transitions[0].before.facts:
            raise EvaluationError("T00 must expose the frozen rare fact")
        if any("rare" in item.before.facts for item in self.transitions[1:]):
            raise EvaluationError("ordinary false-rule history must omit the rare fact")

    def to_manifest(self) -> dict[str, JSONValue]:
        value: dict[str, JSONValue] = {
            "action": _action_payload(self.action),
            "case_id": self.case_id,
            "code": self.code,
            "false_model": _model_payload(self.false_model),
            "ordinary_shared": self.ordinary_shared,
            "rare_false": self.rare_false,
            "rare_true": self.rare_true,
            "seed": self.seed,
            "transitions": [_transition_payload(item) for item in self.transitions],
            "true_model": _model_payload(self.true_model),
        }
        return cast(dict[str, JSONValue], normalize_json(value))


@dataclass(frozen=True, slots=True)
class EvaluationCell:
    """One immutable case/mode pairing in the exact 280-cell matrix."""

    ordinal: int
    group: EvaluationGroup
    group_case_ordinal: int
    case_id: str
    pair_key: str
    seed: int
    mode: RetrodictionMode
    evidence_label: str
    partition: str
    budgets: tuple[tuple[str, int | float], ...]

    @property
    def cell_id(self) -> str:
        digest = sha256_json(
            {
                "case_id": self.case_id,
                "group": self.group.value,
                "mode": self.mode.value,
                "ordinal": self.ordinal,
                "pair_key": self.pair_key,
                "seed": self.seed,
            }
        ).removeprefix("sha256:")[:16]
        return f"stage07-cell-{self.ordinal:03d}-{self.group.value}-{digest}"

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "budgets": {key: value for key, value in self.budgets},
            "case_id": self.case_id,
            "cell_id": self.cell_id,
            "evidence_label": self.evidence_label,
            "group": self.group.value,
            "group_case_ordinal": self.group_case_ordinal,
            "mode": self.mode.value,
            "mode_configuration": _mode_configuration(self.mode),
            "ordinal": self.ordinal,
            "pair_key": self.pair_key,
            "partition": self.partition,
            "seed": self.seed,
        }


@dataclass(frozen=True, slots=True)
class CellMeasurement:
    """Decision-relevant measured receipt for one frozen matrix cell."""

    cell_id: str
    completed: bool
    score: float
    levels_completed: int
    actions: int
    resets: int
    wall_ns: int
    cpu_ns: int
    retrodiction_wall_ns: int
    retrodiction_cpu_ns: int
    peak_rss_bytes: int
    planning_failures: int = 0
    prediction_mismatches: int = 0
    accepted_true_model_ids: tuple[str, ...] = ()
    accepted_false_model_ids: tuple[str, ...] = ()
    intervention_triggered: bool | None = None
    strict_stage06_lifecycle_passed: bool | None = None
    raw_noise_resolved: bool | None = None
    confirmed_false_epochs: int = 0
    cache_hit_count: int = 0
    full_artifact_parity: bool = True
    event_reuse_receipts_valid: bool = True
    trace_valid: bool = True
    checkpoint_valid: bool = True
    replay_valid: bool = True
    source_identity_valid: bool = True
    controller_fault_count: int = 0
    invalid_request_count: int = 0
    network_attempt_count: int = 0
    holdout_exposure_count: int = 0

    def __post_init__(self) -> None:
        integer_values = (
            self.levels_completed,
            self.actions,
            self.resets,
            self.wall_ns,
            self.cpu_ns,
            self.retrodiction_wall_ns,
            self.retrodiction_cpu_ns,
            self.peak_rss_bytes,
            self.planning_failures,
            self.prediction_mismatches,
            self.confirmed_false_epochs,
            self.cache_hit_count,
            self.controller_fault_count,
            self.invalid_request_count,
            self.network_attempt_count,
            self.holdout_exposure_count,
        )
        if not self.cell_id or any(isinstance(item, bool) or item < 0 for item in integer_values):
            raise EvaluationError("cell measurement identity and counts must be non-negative")

    @property
    def hard_integrity_passed(self) -> bool:
        return (
            self.trace_valid
            and self.checkpoint_valid
            and self.replay_valid
            and self.source_identity_valid
            and self.controller_fault_count == 0
            and self.invalid_request_count == 0
            and self.network_attempt_count == 0
            and self.holdout_exposure_count == 0
            and self.peak_rss_bytes <= MAX_PEAK_RSS_BYTES
        )


@dataclass(frozen=True, slots=True)
class MicrobenchmarkMeasurement:
    """Median timing receipt for one mode, history size, and frozen path."""

    mode: RetrodictionMode
    history_size: int
    path: str
    median_wall_ns: int
    median_cpu_ns: int
    semantic_parity: bool
    cache_hit: bool = False
    full_artifact_parity: bool = True

    def __post_init__(self) -> None:
        if self.history_size not in MICRO_HISTORY_SIZES:
            raise EvaluationError("microbenchmark history size is outside the frozen schedule")
        if self.path not in {"cold_exact_n", "append_one_from_verified_n_minus_1_prefix"}:
            raise EvaluationError("microbenchmark path is outside the frozen protocol")
        if (
            isinstance(self.median_wall_ns, bool)
            or self.median_wall_ns < 0
            or isinstance(self.median_cpu_ns, bool)
            or self.median_cpu_ns < 0
        ):
            raise EvaluationError("microbenchmark medians must be non-negative integers")


@dataclass(frozen=True, slots=True)
class ModeGateResult:
    mode: RetrodictionMode
    eligible: bool
    paired_retrodiction_cpu_ns_per_action: float | None
    predicates: tuple[tuple[str, bool], ...]

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "eligible": self.eligible,
            "mode": self.mode.value,
            "paired_retrodiction_cpu_ns_per_action": self.paired_retrodiction_cpu_ns_per_action,
            "predicates": {key: value for key, value in self.predicates},
        }


def _action_payload(action: ActionRequest) -> dict[str, JSONValue]:
    return {
        "coordinate": (
            None
            if action.coordinate is None
            else {"x": action.coordinate.x, "y": action.coordinate.y}
        ),
        "name": action.name.value,
    }


def _rule_payload(rule: RulePrimitive) -> dict[str, JSONValue]:
    value = normalize_json(asdict(rule))
    if not isinstance(value, dict):
        raise EvaluationError("normalized rule payload is not an object")
    value["type"] = type(rule).__name__
    return cast(dict[str, JSONValue], normalize_json(value))


def _model_payload(model: ModelCandidate) -> dict[str, JSONValue]:
    return {
        "compile_residuals": list(model.compile_residuals),
        "hypothesis_ids": list(model.hypothesis_ids),
        "model_id": model.model_id,
        "rank_weight": model.rank_weight,
        "rules": [_rule_payload(rule) for rule in model.rules],
    }


def _transition_payload(transition: PreservedTransition) -> dict[str, JSONValue]:
    return {
        "action": _action_payload(transition.action),
        "after": transition.after.to_dict(),
        "after_state_id": transition.after.state_id,
        "before": transition.before.to_dict(),
        "before_state_id": transition.before.state_id,
        "compatible_model_ids": list(transition.compatible_model_ids),
        "source_event_ids": list(transition.source_event_ids),
        "transition_id": transition.transition_id,
    }


def _mode_configuration(mode: RetrodictionMode) -> dict[str, JSONValue]:
    return {
        "cache_capacity": RETRODICTION_CACHE_CAPACITY,
        "mode": mode.value,
        "use_retrodiction_gate": mode is not RetrodictionMode.NONE,
        "window": 8,
    }


def _condition(kind: ConditionKind) -> tuple[RuleCondition, ...]:
    return (RuleCondition(kind, "rare"),)


def _entity(entity_id: str, kind: str, x: int, *, color: int | None = None) -> SymbolicEntity:
    return SymbolicEntity(entity_id, kind, (Cell(x, 1),), color=color)


def _state(
    *entities: SymbolicEntity,
    rare: bool = False,
    counters: tuple[tuple[str, int], ...] = (),
    toggles: tuple[tuple[str, str], ...] = (),
) -> SymbolicState:
    return SymbolicState(
        width=8,
        height=4,
        entities=tuple(entities),
        facts=("rare",) if rare else (),
        counters=counters,
        toggles=toggles,
    )


def _make_candidate(
    code: str, truth: str, rules: Iterable[RulePrimitive], *, rank_weight: int
) -> ModelCandidate:
    ordered = tuple(sorted(rules, key=lambda item: item.rule_id))
    return make_model_candidate(
        hypothesis_ids=(f"H-{code}-{truth}",),
        rules=ordered,
        rank_weight=rank_weight,
    )


def _ordinary_before(code: str, ordinal: int) -> SymbolicState:
    x = 1 + (ordinal % 5)
    if code in {"B03", "B07"}:
        return _state(_entity("mover", "mover", x))
    if code == "B08":
        return _state(_entity("choice-normal", "choice-normal", 2))
    return _state(_entity("piece", "piece", x))


def _false_rule_case(
    *,
    ordinal: int,
    action: ActionRequest,
    true_rules: tuple[RulePrimitive, ...],
    false_rules: tuple[RulePrimitive, ...],
    t00_before: SymbolicState,
    rare_true: str,
    rare_false: str,
    ordinary_shared: str,
) -> FalseRuleCase:
    code = f"B{ordinal:02d}"
    case_id = _FALSE_RULE_CASE_IDS[ordinal - 1]
    true_model = _make_candidate(code, "TRUE", true_rules, rank_weight=1)
    false_model = _make_candidate(code, "FALSE", false_rules, rank_weight=9)
    compatible = tuple(sorted((true_model.model_id, false_model.model_id)))
    transitions: list[PreservedTransition] = []
    for index in range(12):
        transition_id = f"stage07-b{ordinal:02d}-t{index:02d}"
        before = t00_before if index == 0 else _ordinary_before(code, index)
        after = true_model.predict(before, action).after_state
        transitions.append(
            PreservedTransition(
                transition_id=transition_id,
                before=before,
                action=action,
                after=after,
                source_event_ids=(
                    f"event:{transition_id}:before",
                    f"event:{transition_id}:after",
                ),
                compatible_model_ids=compatible,
            )
        )
    return FalseRuleCase(
        case_id=case_id,
        seed=ordinal,
        code=code,
        action=action,
        true_model=true_model,
        false_model=false_model,
        transitions=tuple(transitions),
        rare_true=rare_true,
        rare_false=rare_false,
        ordinary_shared=ordinary_shared,
    )


def build_false_rule_cases() -> tuple[FalseRuleCase, ...]:
    """Materialize all eight amended, evaluator-known false-rule histories."""

    present = _condition(ConditionKind.FACT_PRESENT)
    absent = _condition(ConditionKind.FACT_ABSENT)
    result = (
        _false_rule_case(
            ordinal=1,
            action=ActionRequest(ActionName.ACTION1),
            true_rules=(
                MovementRule(
                    "R-B01-TRUE-RARE",
                    ActionName.ACTION1,
                    1,
                    0,
                    entity_kind="piece",
                    conditions=present,
                ),
                MovementRule(
                    "R-B01-SHARED-NORMAL",
                    ActionName.ACTION1,
                    1,
                    0,
                    entity_kind="piece",
                    conditions=absent,
                ),
            ),
            false_rules=(
                MovementRule(
                    "R-B01-FALSE-RARE",
                    ActionName.ACTION1,
                    -1,
                    0,
                    entity_kind="piece",
                    conditions=present,
                ),
                MovementRule(
                    "R-B01-SHARED-NORMAL",
                    ActionName.ACTION1,
                    1,
                    0,
                    entity_kind="piece",
                    conditions=absent,
                ),
            ),
            t00_before=_state(_entity("piece", "piece", 3), rare=True),
            rare_true="Movement(piece,+1,0)",
            rare_false="Movement(piece,-1,0)",
            ordinary_shared="Movement(piece,+1,0)",
        ),
        _false_rule_case(
            ordinal=2,
            action=ActionRequest(ActionName.ACTION2),
            true_rules=(
                NoOpRule(
                    "R-B02-TRUE-RARE", ActionName.ACTION2, entity_kind="piece", conditions=present
                ),
                MovementRule(
                    "R-B02-SHARED-NORMAL",
                    ActionName.ACTION2,
                    1,
                    0,
                    entity_kind="piece",
                    conditions=absent,
                ),
            ),
            false_rules=(
                MovementRule(
                    "R-B02-FALSE-RARE",
                    ActionName.ACTION2,
                    1,
                    0,
                    entity_kind="piece",
                    conditions=present,
                ),
                MovementRule(
                    "R-B02-SHARED-NORMAL",
                    ActionName.ACTION2,
                    1,
                    0,
                    entity_kind="piece",
                    conditions=absent,
                ),
            ),
            t00_before=_state(_entity("piece", "piece", 3), rare=True),
            rare_true="NoOp(piece)",
            rare_false="Movement(piece,+1,0)",
            ordinary_shared="Movement(piece,+1,0)",
        ),
        _false_rule_case(
            ordinal=3,
            action=ActionRequest(ActionName.ACTION3),
            true_rules=(
                CollisionRule(
                    "R-B03-TRUE-RARE", "mover", "terrain", CollisionBehavior.BLOCK, present
                ),
                MovementRule("R-B03-SHARED-NORMAL", ActionName.ACTION3, 1, 0, entity_kind="mover"),
            ),
            false_rules=(
                CollisionRule(
                    "R-B03-FALSE-RARE", "mover", "terrain", CollisionBehavior.PASS, present
                ),
                MovementRule("R-B03-SHARED-NORMAL", ActionName.ACTION3, 1, 0, entity_kind="mover"),
            ),
            t00_before=_state(
                _entity("mover", "mover", 2),
                _entity("terrain", "terrain", 3),
                rare=True,
            ),
            rare_true="Collision(mover,terrain,BLOCK)",
            rare_false="Collision(mover,terrain,PASS)",
            ordinary_shared="Movement(mover,+1,0)",
        ),
        _false_rule_case(
            ordinal=4,
            action=ActionRequest(ActionName.ACTION4),
            true_rules=(
                ToggleRule("R-B04-TRUE-RARE", ActionName.ACTION4, "mode", ("off", "on"), present),
                MovementRule(
                    "R-B04-SHARED-NORMAL",
                    ActionName.ACTION4,
                    1,
                    0,
                    entity_kind="piece",
                    conditions=absent,
                ),
            ),
            false_rules=(
                ToggleRule(
                    "R-B04-FALSE-RARE",
                    ActionName.ACTION4,
                    "mode",
                    ("off", "standby", "on"),
                    present,
                ),
                MovementRule(
                    "R-B04-SHARED-NORMAL",
                    ActionName.ACTION4,
                    1,
                    0,
                    entity_kind="piece",
                    conditions=absent,
                ),
            ),
            t00_before=_state(rare=True, toggles=(("mode", "off"),)),
            rare_true="Toggle(mode,off/on)",
            rare_false="Toggle(mode,off/standby/on)",
            ordinary_shared="Movement(piece,+1,0)",
        ),
        _false_rule_case(
            ordinal=5,
            action=ActionRequest(ActionName.ACTION1),
            true_rules=(
                CounterRule("R-B05-TRUE-RARE", ActionName.ACTION1, "tally", 1, conditions=present),
                MovementRule(
                    "R-B05-SHARED-NORMAL",
                    ActionName.ACTION1,
                    1,
                    0,
                    entity_kind="piece",
                    conditions=absent,
                ),
            ),
            false_rules=(
                CounterRule("R-B05-FALSE-RARE", ActionName.ACTION1, "tally", 2, conditions=present),
                MovementRule(
                    "R-B05-SHARED-NORMAL",
                    ActionName.ACTION1,
                    1,
                    0,
                    entity_kind="piece",
                    conditions=absent,
                ),
            ),
            t00_before=_state(rare=True, counters=(("tally", 0),)),
            rare_true="Counter(tally,+1)",
            rare_false="Counter(tally,+2)",
            ordinary_shared="Movement(piece,+1,0)",
        ),
        _false_rule_case(
            ordinal=6,
            action=ActionRequest(ActionName.ACTION2),
            true_rules=(
                TransformationRule(
                    "R-B06-TRUE-RARE",
                    ActionName.ACTION2,
                    "token",
                    TransformationKind.RECOLOR,
                    (("color", 3),),
                    present,
                ),
                MovementRule(
                    "R-B06-SHARED-NORMAL",
                    ActionName.ACTION2,
                    1,
                    0,
                    entity_kind="piece",
                    conditions=absent,
                ),
            ),
            false_rules=(
                TransformationRule(
                    "R-B06-FALSE-RARE",
                    ActionName.ACTION2,
                    "token",
                    TransformationKind.RECOLOR,
                    (("color", 4),),
                    present,
                ),
                MovementRule(
                    "R-B06-SHARED-NORMAL",
                    ActionName.ACTION2,
                    1,
                    0,
                    entity_kind="piece",
                    conditions=absent,
                ),
            ),
            t00_before=_state(_entity("token", "token", 3, color=2), rare=True),
            rare_true="Transformation(token,RECOLOR,color=3)",
            rare_false="Transformation(token,RECOLOR,color=4)",
            ordinary_shared="Movement(piece,+1,0)",
        ),
        _false_rule_case(
            ordinal=7,
            action=ActionRequest(ActionName.ACTION3),
            true_rules=(
                ContactRule(
                    "R-B07-TRUE-RARE",
                    "mover",
                    "target",
                    ContactRelation.ADJACENT,
                    ContactEffectKind.ADD_FACT,
                    "contacted",
                    conditions=present,
                ),
                MovementRule("R-B07-SHARED-NORMAL", ActionName.ACTION3, 1, 0, entity_kind="mover"),
            ),
            false_rules=(
                ContactRule(
                    "R-B07-FALSE-RARE",
                    "mover",
                    "target",
                    ContactRelation.ADJACENT,
                    ContactEffectKind.SET_TOGGLE,
                    "contacted",
                    "on",
                    present,
                ),
                MovementRule("R-B07-SHARED-NORMAL", ActionName.ACTION3, 1, 0, entity_kind="mover"),
            ),
            t00_before=_state(
                _entity("mover", "mover", 2),
                _entity("beacon", "target", 4),
                rare=True,
            ),
            rare_true="Contact(mover,target,ADJACENT,ADD_FACT,contacted)",
            rare_false="Contact(mover,target,ADJACENT,SET_TOGGLE,contacted=on)",
            ordinary_shared="Movement(mover,+1,0)",
        ),
        _false_rule_case(
            ordinal=8,
            action=ActionRequest(ActionName.ACTION6, Coordinate(2, 1)),
            true_rules=(
                SelectionRule(
                    "R-B08-TRUE-RARE", ActionName.ACTION6, "choice-good", conditions=present
                ),
                SelectionRule(
                    "R-B08-SHARED-NORMAL", ActionName.ACTION6, "choice-normal", conditions=absent
                ),
            ),
            false_rules=(
                SelectionRule(
                    "R-B08-FALSE-RARE", ActionName.ACTION6, "choice-bad", conditions=present
                ),
                SelectionRule(
                    "R-B08-SHARED-NORMAL", ActionName.ACTION6, "choice-normal", conditions=absent
                ),
            ),
            t00_before=_state(
                _entity("choice-good", "choice-good", 2),
                _entity("choice-bad", "choice-bad", 2),
                rare=True,
            ),
            rare_true="Selection(choice-good)",
            rare_false="Selection(choice-bad)",
            ordinary_shared="Selection(choice-normal)",
        ),
    )
    if tuple(item.case_id for item in result) != _FALSE_RULE_CASE_IDS:
        raise EvaluationError("false-rule case order diverged from the composite contract")
    return result


def _stage14_case_payloads() -> tuple[dict[str, JSONValue], ...]:
    protocol, _ablations, manifest_hash = stage14_runner.load_protocol_manifest()
    cases = stage14_runner._cases(protocol)
    payloads = tuple(item.to_dict() for item in cases)
    if manifest_hash != STAGE14_PROTOCOL_MANIFEST_SHA256:
        raise EvaluationError("Stage 14 protocol-manifest identity changed")
    if sha256_json(protocol.to_dict()) != STAGE14_PROTOCOL_SHA256:
        raise EvaluationError("Stage 14 typed protocol identity changed")
    if sha256_json(list(payloads)) != STAGE14_CASE_MANIFEST_SHA256:
        raise EvaluationError("Stage 14 case-manifest identity changed")
    if len(payloads) != _GROUP_A_COUNT:
        raise EvaluationError("Stage 14 case count changed")
    return payloads


def selected_rule_change_cases() -> tuple[RuleChangeCase, ...]:
    """Return the exact balanced Stage 06 subset without executing it."""

    all_cases = (*intervention_schedule(), *noise_control_schedule())
    by_id = {item.case_id: item for item in all_cases}
    selected_ids = (*_C_INTERVENTION_IDS, *_C_NOISE_IDS)
    if len(by_id) != len(all_cases) or set(selected_ids) - set(by_id):
        raise EvaluationError("Stage 06 schedule no longer contains the frozen Stage 07 subset")
    selected = tuple(by_id[item] for item in selected_ids)
    if len(selected) != _GROUP_C_COUNT:
        raise EvaluationError("Stage 07 rule-change subset must contain exactly 32 cases")
    return selected


def _development_identity() -> dict[str, JSONValue]:
    manifest = PublicPartitionManifest.load(PUBLIC_PARTITION_PATH)
    if manifest.digest != PUBLIC_PARTITION_SHA256:
        raise EvaluationError("public partition manifest identity changed")
    matches = tuple(
        item for item in manifest.games("development") if item.game_id == "ar25-0c556536"
    )
    if len(matches) != 1:
        raise EvaluationError("frozen Stage 07 development game is not uniquely development")
    entry = matches[0]
    if (
        entry.stable_name != "ar25"
        or entry.assignment_hash
        != "90423451e4cc21a85da6aed98ef9359685517addec73ab8e71a8b351d4940cda"
        or entry.partition != "development"
    ):
        raise EvaluationError("frozen Stage 07 development identity changed")
    return {
        "assignment_hash": entry.assignment_hash,
        "game_id": entry.game_id,
        "partition": entry.partition,
        "stable_name": entry.stable_name,
    }


def build_evaluation_matrix() -> tuple[EvaluationCell, ...]:
    """Build the exact A/B/C/D then case/mode ordered 280-cell matrix."""

    case_rows: list[
        tuple[
            EvaluationGroup,
            int,
            str,
            str,
            int,
            str,
            str,
            tuple[tuple[str, int | float], ...],
        ]
    ] = []
    for case_ordinal, raw in enumerate(_stage14_case_payloads()):
        case_id = cast(str, raw["case_key"])
        case_rows.append(
            (
                EvaluationGroup.A_STAGE14,
                case_ordinal,
                case_id,
                case_id,
                cast(int, raw["seed"]),
                "synthetic",
                cast(str, raw["partition"]),
                (
                    ("action_budget", 16),
                    ("grid_size", 8),
                    ("max_search_nodes", 2_048),
                    ("reset_budget", 2),
                    ("synthetic_max_steps", 32),
                    ("wall_seconds", 120.0),
                ),
            )
        )
    for case_ordinal, false_rule_case in enumerate(build_false_rule_cases()):
        case_rows.append(
            (
                EvaluationGroup.B_FALSE_RULE,
                case_ordinal,
                false_rule_case.case_id,
                false_rule_case.case_id,
                false_rule_case.seed,
                "synthetic",
                "false-rule-history",
                (("height", 4), ("transition_count", 12), ("width", 8)),
            )
        )
    for case_ordinal, rule_change_case in enumerate(selected_rule_change_cases()):
        case_rows.append(
            (
                EvaluationGroup.C_RULE_CHANGE,
                case_ordinal,
                rule_change_case.case_id,
                rule_change_case.case_id,
                rule_change_case.seed,
                "synthetic",
                "stage06-intervention" if case_ordinal < 16 else "stage06-noise",
                (
                    ("action_budget", 48),
                    ("max_search_nodes", 2_048),
                    ("reset_budget", 2),
                    ("wall_seconds", 60.0),
                ),
            )
        )
    development = _development_identity()
    for case_ordinal, seed in enumerate((7, 23)):
        game_id = cast(str, development["game_id"])
        case_rows.append(
            (
                EvaluationGroup.D_LOCAL_PUBLIC,
                case_ordinal,
                game_id,
                f"{game_id}-s{seed}",
                seed,
                "local-public",
                "development",
                (("action_budget", 80), ("reset_budget", 8), ("worker_wall_seconds", 120.0)),
            )
        )
    expected_case_count = _GROUP_A_COUNT + _GROUP_B_COUNT + _GROUP_C_COUNT + _GROUP_D_COUNT
    if len(case_rows) != expected_case_count:
        raise EvaluationError("Stage 07 case-row count changed")
    cells: list[EvaluationCell] = []
    for row in case_rows:
        group, case_ordinal, case_id, pair_key, seed, label, partition, budgets = row
        for mode in MODE_ORDER:
            cells.append(
                EvaluationCell(
                    ordinal=len(cells),
                    group=group,
                    group_case_ordinal=case_ordinal,
                    case_id=case_id,
                    pair_key=pair_key,
                    seed=seed,
                    mode=mode,
                    evidence_label=label,
                    partition=partition,
                    budgets=budgets,
                )
            )
    if len(cells) != EXPECTED_EVALUATION_CELLS:
        raise EvaluationError("Stage 07 evaluation matrix must contain exactly 280 cells")
    if len({item.cell_id for item in cells}) != len(cells):
        raise EvaluationError("Stage 07 cell identities must be unique")
    return tuple(cells)


def build_false_rule_manifest() -> dict[str, object]:
    """Build the deterministic composite-contract manifest before measurement."""

    if sha256_file(PREDECLARATION_PATH) != PREDECLARATION_SHA256:
        raise EvaluationError("Stage 07 base predeclaration hash changed")
    if sha256_file(AMENDMENT_PATH) != AMENDMENT_SHA256:
        raise EvaluationError("Stage 07 premeasurement amendment hash changed")
    cases = build_false_rule_cases()
    case_payload = [item.to_manifest() for item in cases]
    cells = build_evaluation_matrix()
    matrix_payload = [item.to_dict() for item in cells]
    core: dict[str, object] = {
        "case_count": len(cases),
        "composite_contract": {
            "amendment_path": AMENDMENT_PATH.relative_to(ROOT).as_posix(),
            "amendment_sha256": AMENDMENT_SHA256,
            "base_path": PREDECLARATION_PATH.relative_to(ROOT).as_posix(),
            "base_sha256": PREDECLARATION_SHA256,
        },
        "evaluation_cell_count": len(cells),
        "evaluation_matrix": matrix_payload,
        "evaluation_matrix_hash": sha256_json(matrix_payload),
        "false_rule_case_manifest_hash": sha256_json(case_payload),
        "false_rule_cases": case_payload,
        "group_cell_counts": {"A": 70, "B": 40, "C": 160, "D": 10},
        "label": "synthetic",
        "microbenchmark": {
            "case_ids": [f"stage07-retrodiction-micro-n{size:04d}" for size in MICRO_HISTORY_SIZES],
            "history_sizes": list(MICRO_HISTORY_SIZES),
            "material_history_floor": MICRO_MATERIAL_HISTORY_FLOOR,
            "measured_repetitions_per_cell": MICRO_REPETITIONS,
            "paths": ["cold_exact_n", "append_one_from_verified_n_minus_1_prefix"],
            "warmups_per_cell": MICRO_WARMUPS,
        },
        "mode_order": [item.value for item in MODE_ORDER],
        "public_holdout": "SEALED_UNCONSUMED",
        "schema": "arc3.build-001.stage-07-false-rule-case-manifest.v0.1",
        "status": "FROZEN_PREMEASUREMENT",
    }
    return seal_object(core, hash_field="manifest_core_hash")


def validate_false_rule_manifest(value: Mapping[str, object]) -> dict[str, bool]:
    """Fail closed unless supplied bytes exactly match the deterministic manifest."""

    expected = build_false_rule_manifest()
    predicates = {
        "exact_manifest": dict(value) == expected,
        "schema": value.get("schema") == expected["schema"],
        "case_count": value.get("case_count") == 8,
        "evaluation_cell_count": value.get("evaluation_cell_count") == 280,
        "base_contract": cast(Mapping[str, object], value.get("composite_contract", {})).get(
            "base_sha256"
        )
        == PREDECLARATION_SHA256,
        "amendment_contract": cast(Mapping[str, object], value.get("composite_contract", {})).get(
            "amendment_sha256"
        )
        == AMENDMENT_SHA256,
    }
    return predicates


def _measurements_by_cell(
    cells: Sequence[EvaluationCell], measurements: Sequence[CellMeasurement]
) -> dict[str, CellMeasurement]:
    expected = {item.cell_id for item in cells}
    by_id = {item.cell_id: item for item in measurements}
    if len(by_id) != len(measurements) or set(by_id) != expected:
        raise EvaluationError("measurements must cover the exact 280-cell manifest once")
    return by_id


def _micro_by_key(
    measurements: Sequence[MicrobenchmarkMeasurement],
) -> dict[tuple[RetrodictionMode, int, str], MicrobenchmarkMeasurement]:
    by_key = {(item.mode, item.history_size, item.path): item for item in measurements}
    expected = {
        (mode, size, path)
        for mode in MODE_ORDER
        for size in MICRO_HISTORY_SIZES
        for path in ("cold_exact_n", "append_one_from_verified_n_minus_1_prefix")
    }
    if len(by_key) != len(measurements) or set(by_key) != expected:
        raise EvaluationError("microbenchmarks must cover the exact 60-cell timing protocol")
    return by_key


def _improved(candidate: int | float, baseline: int | float, fraction: float) -> bool:
    return candidate <= baseline * (1.0 - fraction)


def _not_more_than(candidate: int | float, baseline: int | float, fraction: float) -> bool:
    return candidate <= baseline * (1.0 + fraction)


def evaluate_replacement_gates(
    measurements: Sequence[CellMeasurement],
    microbenchmarks: Sequence[MicrobenchmarkMeasurement],
) -> tuple[ModeGateResult, ...]:
    """Apply the frozen paired replacement gates without choosing post-result rows."""

    cells = build_evaluation_matrix()
    by_id = _measurements_by_cell(cells, measurements)
    micro = _micro_by_key(microbenchmarks)
    cells_by_pair_mode = {(item.pair_key, item.mode): item for item in cells}
    fixed_pairs = tuple(
        item.pair_key
        for item in cells
        if item.mode is RetrodictionMode.FULL
        and item.group
        in {
            EvaluationGroup.A_STAGE14,
            EvaluationGroup.C_RULE_CHANGE,
            EvaluationGroup.D_LOCAL_PUBLIC,
        }
        and by_id[item.cell_id].actions >= 9
    )
    comparison_pairs = tuple(
        item.pair_key
        for item in cells
        if item.mode is RetrodictionMode.FULL
        and item.group
        in {
            EvaluationGroup.A_STAGE14,
            EvaluationGroup.C_RULE_CHANGE,
            EvaluationGroup.D_LOCAL_PUBLIC,
        }
    )
    results: list[ModeGateResult] = []
    false_cases_by_id = {item.case_id: item for item in build_false_rule_cases()}
    for mode in MODE_ORDER[1:]:
        candidate_cells = tuple(item for item in cells if item.mode is mode)
        full_cells = tuple(item for item in cells if item.mode is RetrodictionMode.FULL)
        hard_integrity = all(
            by_id[item.cell_id].hard_integrity_passed for item in (*full_cells, *candidate_cells)
        )

        b_cells = tuple(
            item for item in candidate_cells if item.group is EvaluationGroup.B_FALSE_RULE
        )
        false_rule_gate = all(
            by_id[item.cell_id].accepted_true_model_ids
            == (false_cases_by_id[item.case_id].true_model.model_id,)
            and by_id[item.cell_id].accepted_false_model_ids == ()
            for item in b_cells
        )

        paired_outcomes = True
        paired_actions = True
        paired_planning = True
        for pair_key in comparison_pairs:
            full_cell = cells_by_pair_mode[(pair_key, RetrodictionMode.FULL)]
            candidate_cell = cells_by_pair_mode[(pair_key, mode)]
            full = by_id[full_cell.cell_id]
            candidate = by_id[candidate_cell.cell_id]
            paired_outcomes = paired_outcomes and (
                int(candidate.completed) >= int(full.completed)
                and candidate.levels_completed >= full.levels_completed
                and candidate.score >= full.score
            )
            paired_actions = paired_actions and candidate.actions <= full.actions + 1
            paired_planning = paired_planning and (
                candidate.planning_failures <= full.planning_failures
                and candidate.prediction_mismatches <= full.prediction_mismatches
            )

        full_acd = tuple(
            by_id[item.cell_id]
            for item in full_cells
            if item.group
            in {
                EvaluationGroup.A_STAGE14,
                EvaluationGroup.C_RULE_CHANGE,
                EvaluationGroup.D_LOCAL_PUBLIC,
            }
        )
        candidate_acd = tuple(
            by_id[item.cell_id]
            for item in candidate_cells
            if item.group
            in {
                EvaluationGroup.A_STAGE14,
                EvaluationGroup.C_RULE_CHANGE,
                EvaluationGroup.D_LOCAL_PUBLIC,
            }
        )
        aggregate_outcomes = (
            sum(item.completed for item in candidate_acd)
            >= sum(item.completed for item in full_acd)
            and sum(item.levels_completed for item in candidate_acd)
            >= sum(item.levels_completed for item in full_acd)
            and sum(item.score for item in candidate_acd) >= sum(item.score for item in full_acd)
            and sum(item.planning_failures for item in candidate_acd)
            <= sum(item.planning_failures for item in full_acd)
            and sum(item.prediction_mismatches for item in candidate_acd)
            <= sum(item.prediction_mismatches for item in full_acd)
        )
        aggregate_actions = sum(item.actions for item in candidate_acd) <= 1.05 * sum(
            item.actions for item in full_acd
        )
        episode_wall = sum(item.wall_ns for item in candidate_acd) <= 1.05 * sum(
            item.wall_ns for item in full_acd
        )

        full_cost = tuple(
            by_id[cells_by_pair_mode[(pair_key, RetrodictionMode.FULL)].cell_id]
            for pair_key in fixed_pairs
        )
        candidate_cost = tuple(
            by_id[cells_by_pair_mode[(pair_key, mode)].cell_id] for pair_key in fixed_pairs
        )
        full_actions = sum(item.actions for item in full_cost)
        candidate_actions = sum(item.actions for item in candidate_cost)
        full_wall_per_action = (
            sum(item.retrodiction_wall_ns for item in full_cost) / full_actions
            if full_actions
            else 0.0
        )
        candidate_wall_per_action = (
            sum(item.retrodiction_wall_ns for item in candidate_cost) / candidate_actions
            if candidate_actions
            else 0.0
        )
        full_cpu_per_action = (
            sum(item.retrodiction_cpu_ns for item in full_cost) / full_actions
            if full_actions
            else 0.0
        )
        candidate_cpu_per_action = (
            sum(item.retrodiction_cpu_ns for item in candidate_cost) / candidate_actions
            if candidate_actions
            else 0.0
        )
        cost_gate = bool(
            fixed_pairs
            and full_actions
            and candidate_actions
            and _improved(candidate_wall_per_action, full_wall_per_action, 0.25)
            and _improved(candidate_cpu_per_action, full_cpu_per_action, 0.25)
            and episode_wall
        )

        a_completion = all(
            not by_id[cells_by_pair_mode[(pair_key, RetrodictionMode.FULL)].cell_id].completed
            or by_id[cells_by_pair_mode[(pair_key, mode)].cell_id].completed
            for pair_key in comparison_pairs
            if cells_by_pair_mode[(pair_key, mode)].group is EvaluationGroup.A_STAGE14
        )
        c_cells = tuple(
            item for item in candidate_cells if item.group is EvaluationGroup.C_RULE_CHANGE
        )
        c_interventions = c_cells[:16]
        c_noise = c_cells[16:]
        mechanics_gate = (
            len(c_interventions) == len(c_noise) == 16
            and all(by_id[item.cell_id].intervention_triggered is True for item in c_interventions)
            and all(
                by_id[item.cell_id].raw_noise_resolved is True
                and by_id[item.cell_id].confirmed_false_epochs == 0
                for item in c_noise
            )
            and all(
                by_id[
                    cells_by_pair_mode[(item.pair_key, RetrodictionMode.FULL)].cell_id
                ].strict_stage06_lifecycle_passed
                is not True
                or by_id[item.cell_id].strict_stage06_lifecycle_passed is True
                for item in c_cells
            )
        )

        micro_semantics = all(
            micro[(mode, size, path)].semantic_parity
            for size in MICRO_HISTORY_SIZES
            for path in ("cold_exact_n", "append_one_from_verified_n_minus_1_prefix")
        )
        micro_cost = True
        for size in MICRO_HISTORY_SIZES:
            if size < MICRO_MATERIAL_HISTORY_FLOOR:
                continue
            for path in ("cold_exact_n", "append_one_from_verified_n_minus_1_prefix"):
                current = micro[(mode, size, path)]
                baseline = micro[(RetrodictionMode.FULL, size, path)]
                improvement_required = (
                    mode
                    in {
                        RetrodictionMode.NONE,
                        RetrodictionMode.RECENT_WINDOW_8,
                    }
                    or path == "append_one_from_verified_n_minus_1_prefix"
                )
                if improvement_required:
                    micro_cost = (
                        micro_cost
                        and _improved(current.median_wall_ns, baseline.median_wall_ns, 0.25)
                        and _improved(current.median_cpu_ns, baseline.median_cpu_ns, 0.25)
                    )
                else:
                    micro_cost = (
                        micro_cost
                        and _not_more_than(current.median_wall_ns, baseline.median_wall_ns, 0.05)
                        and _not_more_than(current.median_cpu_ns, baseline.median_cpu_ns, 0.05)
                    )
        mode_specific = micro_semantics and micro_cost
        if mode is RetrodictionMode.CACHED_INCREMENTAL:
            mode_specific = (
                mode_specific
                and all(by_id[item.cell_id].full_artifact_parity for item in candidate_cells)
                and any(by_id[item.cell_id].cache_hit_count > 0 for item in candidate_cells)
            )
            mode_specific = mode_specific and all(
                micro[(mode, size, path)].full_artifact_parity
                for size in MICRO_HISTORY_SIZES
                for path in ("cold_exact_n", "append_one_from_verified_n_minus_1_prefix")
            )
        if mode is RetrodictionMode.EVENT_TRIGGERED:
            mode_specific = mode_specific and all(
                by_id[item.cell_id].event_reuse_receipts_valid for item in candidate_cells
            )

        predicates = (
            ("hard_integrity", hard_integrity),
            ("false_rule_gate_B", false_rule_gate),
            ("completion_gate_A", a_completion),
            ("mechanics_gate_C", mechanics_gate),
            ("paired_outcome_gate_ACD", paired_outcomes),
            ("aggregate_outcome_gate_ACD", aggregate_outcomes),
            ("paired_planning_gate_ACD", paired_planning),
            ("paired_action_gate", paired_actions),
            ("aggregate_action_gate", aggregate_actions),
            ("cost_gate", cost_gate),
            ("mode_specific_microbenchmark_gate", mode_specific),
        )
        results.append(
            ModeGateResult(
                mode=mode,
                eligible=all(value for _key, value in predicates),
                paired_retrodiction_cpu_ns_per_action=(
                    candidate_cpu_per_action if candidate_actions else None
                ),
                predicates=predicates,
            )
        )
    return tuple(results)


def choose_retrodiction_decision(results: Sequence[ModeGateResult]) -> RetrodictionDecision:
    """Choose the lowest measured eligible CPU, using the frozen 5% coverage tie break."""

    by_mode = {item.mode: item for item in results}
    expected = set(MODE_ORDER[1:])
    if len(by_mode) != len(results) or set(by_mode) != expected:
        raise EvaluationError("decision requires exactly one gate result per replacement mode")
    eligible = tuple(
        item
        for item in results
        if item.eligible and item.paired_retrodiction_cpu_ns_per_action is not None
    )
    if not eligible:
        return RetrodictionDecision.KEEP_FULL
    minimum = min(cast(float, item.paired_retrodiction_cpu_ns_per_action) for item in eligible)
    tied = {
        item.mode
        for item in eligible
        if cast(float, item.paired_retrodiction_cpu_ns_per_action) <= minimum * 1.05
    }
    selected = next(mode for mode in _COVERAGE_TIE_ORDER if mode in tied)
    return _DECISION_BY_MODE[selected]


__all__ = [
    "AMENDMENT_PATH",
    "AMENDMENT_SHA256",
    "EXPECTED_EVALUATION_CELLS",
    "FALSE_RULE_MANIFEST_PATH",
    "MICRO_HISTORY_SIZES",
    "MICRO_REPETITIONS",
    "MICRO_WARMUPS",
    "MODE_ORDER",
    "PREDECLARATION_PATH",
    "PREDECLARATION_SHA256",
    "CellMeasurement",
    "EvaluationCell",
    "EvaluationGroup",
    "FalseRuleCase",
    "MicrobenchmarkMeasurement",
    "ModeGateResult",
    "RetrodictionDecision",
    "build_evaluation_matrix",
    "build_false_rule_cases",
    "build_false_rule_manifest",
    "choose_retrodiction_decision",
    "evaluate_replacement_gates",
    "selected_rule_change_cases",
    "validate_false_rule_manifest",
]
