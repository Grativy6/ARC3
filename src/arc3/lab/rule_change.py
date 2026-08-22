"""Deterministic Stage 06 mechanics-change laboratory.

The production-facing session exposes only normalized observations.  Case
identity, transforms, intervention state, terrain truth, and exact transition
annotations remain on the evaluator side of the boundary.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import StrEnum

from arc3.adapters import (
    GridFrame,
    Observation,
    ScoreRunSummary,
    ScoreSummary,
    validate_action_request,
)
from arc3.errors import EnvironmentStateError
from arc3.trace.canonical import sha256_json
from arc3.types import (
    ActionName,
    ActionRequest,
    EvaluationSurface,
    GameId,
    GameStateName,
    JSONValue,
)

RULE_CHANGE_GAME_ID = GameId("synthetic-stage06-rule-change-v1")
RULE_CHANGE_GRID_SIZE = 11
RULE_CHANGE_ACTIONS = (
    ActionName.ACTION1,
    ActionName.ACTION2,
    ActionName.ACTION3,
    ActionName.ACTION4,
)
RULE_CHANGE_SEEDS = (7, 11, 23, 29)


class RuleChangeFamily(StrEnum):
    """Frozen intervention families and the stationary control family."""

    ACTION_EFFECT_ROTATION = "action_effect_rotation"
    TRAVERSABILITY_FLIP = "traversability_flip"
    STATIONARY_NOISE = "stationary_noise_control"


class RuleChangeTiming(StrEnum):
    """Frozen pre-change support schedules."""

    EARLY_SUPPORT_2 = "early_support_2"
    LATE_SUPPORT_4 = "late_support_4"

    @property
    def support_required(self) -> int:
        return 2 if self is RuleChangeTiming.EARLY_SUPPORT_2 else 4

    @property
    def latest_trigger_action(self) -> int:
        return 16 if self is RuleChangeTiming.EARLY_SUPPORT_2 else 24


class PaletteVariant(StrEnum):
    """Frozen joint observation palette transforms."""

    IDENTITY = "identity"
    AFFINE_NONIDENTITY = "affine_nonidentity"


class ActionVariant(StrEnum):
    """Frozen raw-handle transforms."""

    IDENTITY = "identity"
    CYCLE1234 = "cycle1234"


class RuleChangeCaseKind(StrEnum):
    """Whether a case contains a persistent intervention or transient noise."""

    INTERVENTION = "intervention"
    NOISE = "noise"


class CheckpointBoundary(StrEnum):
    """Frozen controller checkpoint boundaries."""

    PRE_TRIGGER = "pre_trigger"
    POST_REOPEN = "post_reopen"


@dataclass(frozen=True, slots=True)
class RuleChangeCase:
    """Evaluator-owned identity for one entry in the frozen schedule."""

    case_id: str
    kind: RuleChangeCaseKind
    family: RuleChangeFamily
    timing: RuleChangeTiming
    seed: int
    palette_variant: PaletteVariant
    action_variant: ActionVariant
    rejection_count: int = 0

    @property
    def support_required(self) -> int:
        return self.timing.support_required


@dataclass(frozen=True, slots=True)
class RuleChangeCheckpointCase:
    """One exact entry in the eight-pair checkpoint schedule."""

    family: RuleChangeFamily
    timing: RuleChangeTiming
    seed: int
    boundary: CheckpointBoundary
    palette_variant: PaletteVariant = PaletteVariant.AFFINE_NONIDENTITY
    action_variant: ActionVariant = ActionVariant.CYCLE1234

    @property
    def case_id(self) -> str:
        return _intervention_case_id(
            self.family,
            self.timing,
            self.seed,
            self.palette_variant,
            self.action_variant,
        )


@dataclass(frozen=True, slots=True)
class RuleChangeTruthReceipt:
    """Immutable evaluator-only annotation for one environment transition."""

    receipt_id: str
    receipt_hash: str
    receipt_sequence: int
    previous_receipt_hash: str | None
    case_id: str
    step: int
    action: ActionRequest
    before_frame_hash: str
    after_frame_hash: str
    before_position: tuple[int, int]
    after_position: tuple[int, int]
    predecessor_effect: tuple[int, int]
    realized_effect: tuple[int, int]
    attempted_cell: tuple[int, int]
    attempted_role: str
    distinct_successor_evidence: bool
    result_kind: str
    pulse_kind: str
    pulse_armed: bool
    pulse_triggered: bool
    trigger_step: int | None
    mechanics_epoch: int
    coherent_successor_receipts: int
    successor_evidence_cells: tuple[tuple[int, int], ...]
    successor_evidence_handles: tuple[ActionName, ...]
    resumed_predecessor_receipts: int
    pulse_resolved: bool
    terminal_state: GameStateName

    def to_dict(self) -> dict[str, JSONValue]:
        """Return the sealed receipt without weakening its typed fields."""

        return {
            "action": _action_payload(self.action),
            "after_frame_hash": self.after_frame_hash,
            "after_position": list(self.after_position),
            "attempted_cell": list(self.attempted_cell),
            "attempted_role": self.attempted_role,
            "before_frame_hash": self.before_frame_hash,
            "before_position": list(self.before_position),
            "case_id": self.case_id,
            "coherent_successor_receipts": self.coherent_successor_receipts,
            "distinct_successor_evidence": self.distinct_successor_evidence,
            "mechanics_epoch": self.mechanics_epoch,
            "predecessor_effect": list(self.predecessor_effect),
            "previous_receipt_hash": self.previous_receipt_hash,
            "pulse_armed": self.pulse_armed,
            "pulse_kind": self.pulse_kind,
            "pulse_resolved": self.pulse_resolved,
            "pulse_triggered": self.pulse_triggered,
            "realized_effect": list(self.realized_effect),
            "receipt_hash": self.receipt_hash,
            "receipt_id": self.receipt_id,
            "receipt_sequence": self.receipt_sequence,
            "result_kind": self.result_kind,
            "resumed_predecessor_receipts": self.resumed_predecessor_receipts,
            "step": self.step,
            "successor_evidence_cells": [list(item) for item in self.successor_evidence_cells],
            "successor_evidence_handles": [item.value for item in self.successor_evidence_handles],
            "terminal_state": self.terminal_state.value,
            "trigger_step": self.trigger_step,
        }


@dataclass(frozen=True, slots=True)
class EvaluatedRuleChangeStep:
    """A production observation paired with separately held evaluator truth."""

    observation: Observation
    truth: RuleChangeTruthReceipt


@dataclass(frozen=True, slots=True)
class RuleChangeEvaluatorProjection:
    """Canonical evaluator state used only for measurement and replay checks."""

    action_count: int
    reset_count: int
    position: tuple[int, int]
    visible_target: tuple[int, int]
    calibrated_handles: tuple[ActionName, ...]
    prechange_support_cells: tuple[tuple[int, int], ...]
    prechange_support_receipts: int
    pulse_armed: bool
    pulse_triggered: bool
    trigger_step: int | None
    mechanics_epoch: int
    coherent_successor_receipts: int
    successor_evidence_cells: tuple[tuple[int, int], ...]
    successor_evidence_handles: tuple[ActionName, ...]
    resumed_predecessor_receipts: int
    pulse_resolved: bool
    terminal_state: GameStateName

    def to_dict(self) -> dict[str, JSONValue]:
        """Return a deterministic JSON projection."""

        return {
            "action_count": self.action_count,
            "calibrated_handles": [item.value for item in self.calibrated_handles],
            "coherent_successor_receipts": self.coherent_successor_receipts,
            "mechanics_epoch": self.mechanics_epoch,
            "position": list(self.position),
            "prechange_support_cells": [list(item) for item in self.prechange_support_cells],
            "prechange_support_receipts": self.prechange_support_receipts,
            "pulse_armed": self.pulse_armed,
            "pulse_resolved": self.pulse_resolved,
            "pulse_triggered": self.pulse_triggered,
            "reset_count": self.reset_count,
            "resumed_predecessor_receipts": self.resumed_predecessor_receipts,
            "terminal_state": self.terminal_state.value,
            "trigger_step": self.trigger_step,
            "successor_evidence_cells": [list(item) for item in self.successor_evidence_cells],
            "successor_evidence_handles": [item.value for item in self.successor_evidence_handles],
            "visible_target": list(self.visible_target),
        }


@dataclass(frozen=True, slots=True)
class _RuleChangeSpec:
    case: RuleChangeCase
    palette: tuple[int, ...]
    raw_effects: tuple[tuple[ActionName, tuple[int, int]], ...]
    start: tuple[int, int]
    training_waypoints: tuple[tuple[int, int], ...]
    final_target: tuple[int, int]
    primary_cells: frozenset[tuple[int, int]]
    bypass_cells: frozenset[tuple[int, int]]
    permanent_walls: frozenset[tuple[int, int]]

    @property
    def effects(self) -> dict[ActionName, tuple[int, int]]:
        return dict(self.raw_effects)


@dataclass(frozen=True, slots=True)
class _RuleChangeState:
    position: tuple[int, int]
    visible_target: tuple[int, int]
    waypoint_index: int = 0
    calibrated_handles: tuple[ActionName, ...] = ()
    prechange_support_cells: tuple[tuple[int, int], ...] = ()
    prechange_support_receipts: int = 0
    action_count: int = 0
    reset_count: int = 0
    pulse_armed: bool = False
    pulse_triggered: bool = False
    trigger_step: int | None = None
    mechanics_epoch: int = 0
    coherent_successor_receipts: int = 0
    successor_evidence_cells: tuple[tuple[int, int], ...] = ()
    successor_evidence_handles: tuple[ActionName, ...] = ()
    resumed_predecessor_receipts: int = 0
    pulse_resolved: bool = False
    terminal_state: GameStateName = GameStateName.NOT_FINISHED


@dataclass(frozen=True, slots=True)
class _Transition:
    state: _RuleChangeState
    truth_core: dict[str, JSONValue]


_BASE_EFFECTS: dict[ActionName, tuple[int, int]] = {
    ActionName.ACTION1: (0, -1),
    ActionName.ACTION2: (0, 1),
    ActionName.ACTION3: (-1, 0),
    ActionName.ACTION4: (1, 0),
}
_ACTION_CYCLE: dict[ActionName, ActionName] = {
    ActionName.ACTION1: ActionName.ACTION2,
    ActionName.ACTION2: ActionName.ACTION3,
    ActionName.ACTION3: ActionName.ACTION4,
    ActionName.ACTION4: ActionName.ACTION1,
}
_SEED_OFFSETS = dict(zip(RULE_CHANGE_SEEDS, (3, 7, 11, 15), strict=True))


def _action_payload(action: ActionRequest) -> dict[str, JSONValue]:
    return {
        "coordinate": (
            None
            if action.coordinate is None
            else {"x": action.coordinate.x, "y": action.coordinate.y}
        ),
        "name": action.name.value,
    }


def _intervention_case_id(
    family: RuleChangeFamily,
    timing: RuleChangeTiming,
    seed: int,
    palette: PaletteVariant,
    action: ActionVariant,
) -> str:
    return (
        f"stage06-intervention-{family.value}-{timing.value}-s{seed}-{palette.value}-{action.value}"
    )


def _noise_case_id(
    timing: RuleChangeTiming,
    seed: int,
    palette: PaletteVariant,
    action: ActionVariant,
) -> str:
    return f"stage06-noise-{timing.value}-s{seed}-{palette.value}-{action.value}"


def intervention_schedule() -> tuple[RuleChangeCase, ...]:
    """Return the exact ordered 64-case intervention matrix."""

    cases: list[RuleChangeCase] = []
    for family in (
        RuleChangeFamily.ACTION_EFFECT_ROTATION,
        RuleChangeFamily.TRAVERSABILITY_FLIP,
    ):
        for timing in RuleChangeTiming:
            for seed in RULE_CHANGE_SEEDS:
                for palette in PaletteVariant:
                    for action in ActionVariant:
                        cases.append(
                            RuleChangeCase(
                                case_id=_intervention_case_id(
                                    family, timing, seed, palette, action
                                ),
                                kind=RuleChangeCaseKind.INTERVENTION,
                                family=family,
                                timing=timing,
                                seed=seed,
                                palette_variant=palette,
                                action_variant=action,
                            )
                        )
    return tuple(cases)


def noise_control_schedule() -> tuple[RuleChangeCase, ...]:
    """Return the exact ordered 32-case stationary-noise matrix."""

    cases: list[RuleChangeCase] = []
    for timing in RuleChangeTiming:
        for seed in RULE_CHANGE_SEEDS:
            for palette in PaletteVariant:
                for action in ActionVariant:
                    cases.append(
                        RuleChangeCase(
                            case_id=_noise_case_id(timing, seed, palette, action),
                            kind=RuleChangeCaseKind.NOISE,
                            family=RuleChangeFamily.STATIONARY_NOISE,
                            timing=timing,
                            seed=seed,
                            palette_variant=palette,
                            action_variant=action,
                        )
                    )
    return tuple(cases)


def checkpoint_schedule() -> tuple[RuleChangeCheckpointCase, ...]:
    """Return the frozen eight-pair checkpoint/resume schedule."""

    return (
        RuleChangeCheckpointCase(
            RuleChangeFamily.ACTION_EFFECT_ROTATION,
            RuleChangeTiming.EARLY_SUPPORT_2,
            7,
            CheckpointBoundary.PRE_TRIGGER,
        ),
        RuleChangeCheckpointCase(
            RuleChangeFamily.ACTION_EFFECT_ROTATION,
            RuleChangeTiming.LATE_SUPPORT_4,
            11,
            CheckpointBoundary.PRE_TRIGGER,
        ),
        RuleChangeCheckpointCase(
            RuleChangeFamily.TRAVERSABILITY_FLIP,
            RuleChangeTiming.EARLY_SUPPORT_2,
            23,
            CheckpointBoundary.PRE_TRIGGER,
        ),
        RuleChangeCheckpointCase(
            RuleChangeFamily.TRAVERSABILITY_FLIP,
            RuleChangeTiming.LATE_SUPPORT_4,
            29,
            CheckpointBoundary.PRE_TRIGGER,
        ),
        RuleChangeCheckpointCase(
            RuleChangeFamily.ACTION_EFFECT_ROTATION,
            RuleChangeTiming.EARLY_SUPPORT_2,
            7,
            CheckpointBoundary.POST_REOPEN,
        ),
        RuleChangeCheckpointCase(
            RuleChangeFamily.ACTION_EFFECT_ROTATION,
            RuleChangeTiming.LATE_SUPPORT_4,
            11,
            CheckpointBoundary.POST_REOPEN,
        ),
        RuleChangeCheckpointCase(
            RuleChangeFamily.TRAVERSABILITY_FLIP,
            RuleChangeTiming.EARLY_SUPPORT_2,
            23,
            CheckpointBoundary.POST_REOPEN,
        ),
        RuleChangeCheckpointCase(
            RuleChangeFamily.TRAVERSABILITY_FLIP,
            RuleChangeTiming.LATE_SUPPORT_4,
            29,
            CheckpointBoundary.POST_REOPEN,
        ),
    )


def _palette(case: RuleChangeCase) -> tuple[int, ...]:
    if case.palette_variant is PaletteVariant.IDENTITY:
        return tuple(range(16))
    offset = _SEED_OFFSETS[case.seed]
    return tuple((5 * color + offset) % 16 for color in range(16))


def _raw_effects(case: RuleChangeCase) -> tuple[tuple[ActionName, tuple[int, int]], ...]:
    if case.action_variant is ActionVariant.IDENTITY:
        mapping = dict(_BASE_EFFECTS)
    else:
        mapping = {
            _ACTION_CYCLE[base_handle]: effect for base_handle, effect in _BASE_EFFECTS.items()
        }
    return tuple((handle, mapping[handle]) for handle in RULE_CHANGE_ACTIONS)


def _build_spec(case: RuleChangeCase) -> _RuleChangeSpec:
    if case.seed not in RULE_CHANGE_SEEDS:
        raise ValueError(f"seed is outside the frozen Stage 06 schedule: {case.seed}")
    support = case.support_required
    if case.family is RuleChangeFamily.ACTION_EFFECT_ROTATION:
        seed_index = RULE_CHANGE_SEEDS.index(case.seed)
        start = (1 + seed_index, 1 + 2 * seed_index)
        training = tuple(
            ((start[0] + offset) % RULE_CHANGE_GRID_SIZE, start[1])
            for offset in range(1, support + 2)
        )
        final_target = (
            (start[0] + 5) % RULE_CHANGE_GRID_SIZE,
            (start[1] + 5) % RULE_CHANGE_GRID_SIZE,
        )
        primary: frozenset[tuple[int, int]] = frozenset()
        bypass: frozenset[tuple[int, int]] = frozenset()
        walls: frozenset[tuple[int, int]] = frozenset()
    else:
        seed_index = RULE_CHANGE_SEEDS.index(case.seed)
        layouts = (
            ((1, 3), 1, (2, 3), (4, 5)),
            ((9, 5), -1, (4, 5), (6, 7)),
            ((1, 7), 1, (7, 8), (5, 6)),
            ((9, 3), -1, (2, 3), (4, 5)),
        )
        start, direction, primary_rows, bypass_rows = layouts[seed_index]
        # Keep the first guide outside every four-handle calibration trajectory,
        # then expose a distant same-role guide after the exact support threshold.
        # The distance is what lets the ordinary controller establish a real,
        # nontrivial plan that depends on the promoted traversability rule before
        # the evaluator is allowed to arm the pulse.
        support_waypoints = tuple(
            (start[0] + direction * (offset + 2), start[1]) for offset in range(support)
        )
        final_x = 9 if direction > 0 else 1
        bypass_edge = max(bypass_rows) if bypass_rows[0] > start[1] else min(bypass_rows)
        final_target = (
            (final_x, start[1])
            if case.family is RuleChangeFamily.STATIONARY_NOISE
            else (final_x, bypass_edge)
        )
        training = (*support_waypoints, (final_x, start[1]))
        # Keep the four-handle calibration footprint outside the affected
        # primary role. Otherwise calibration itself silently increments the
        # controller's primary-role evidence before the evaluator's two/four
        # distinct training entries, defeating the frozen exact-support gate.
        calibration_footprint = {
            (x, y) for x in (start[0], start[0] + direction) for y in primary_rows
        }
        # A two-cell-thick band keeps the destination role connected and
        # observable when the one-cell actor or guide temporarily occludes it.
        primary = frozenset(
            (x, y)
            for y in primary_rows
            for x in range(1, 10)
            if (x, y) not in calibration_footprint
        )
        bypass = frozenset((x, y) for y in bypass_rows for x in range(1, 10))
        # This cell is physically open for the west/east calibration pair, but
        # intentionally shares the modal wall colour.  Rendering a one-cell
        # decoration would create an unrelated navigation attractor.
        calibration_open = calibration_footprint | {(start[0] - direction, start[1])}
        traversable = set(primary) | set(bypass) | calibration_open
        walls = frozenset(
            (x, y)
            for y in range(RULE_CHANGE_GRID_SIZE)
            for x in range(RULE_CHANGE_GRID_SIZE)
            if (x, y) not in traversable
        )
    return _RuleChangeSpec(
        case=case,
        palette=_palette(case),
        raw_effects=_raw_effects(case),
        start=start,
        training_waypoints=training,
        final_target=final_target,
        primary_cells=primary,
        bypass_cells=bypass,
        permanent_walls=walls,
    )


def _initial_state(spec: _RuleChangeSpec) -> _RuleChangeState:
    return _RuleChangeState(
        position=spec.start,
        visible_target=(
            spec.training_waypoints[0] if spec.training_waypoints else spec.final_target
        ),
    )


def _rotate_clockwise(effect: tuple[int, int]) -> tuple[int, int]:
    return (-effect[1], effect[0])


def _point_add(
    point: tuple[int, int], effect: tuple[int, int], *, toroidal: bool
) -> tuple[int, int]:
    raw = (point[0] + effect[0], point[1] + effect[1])
    if toroidal:
        return (raw[0] % RULE_CHANGE_GRID_SIZE, raw[1] % RULE_CHANGE_GRID_SIZE)
    return (
        min(RULE_CHANGE_GRID_SIZE - 1, max(0, raw[0])),
        min(RULE_CHANGE_GRID_SIZE - 1, max(0, raw[1])),
    )


def _role(spec: _RuleChangeSpec, point: tuple[int, int]) -> str:
    if point in spec.primary_cells:
        return "primary"
    if point in spec.bypass_cells:
        return "bypass"
    if point in spec.permanent_walls:
        return "permanent-wall"
    return "neutral-open"


def _blocked(spec: _RuleChangeSpec, state: _RuleChangeState, role: str) -> bool:
    if spec.case.family is RuleChangeFamily.ACTION_EFFECT_ROTATION:
        return False
    if role == "permanent-wall":
        return True
    if spec.case.family is RuleChangeFamily.STATIONARY_NOISE:
        return role == "bypass"
    if state.mechanics_epoch == 0:
        return role == "bypass"
    return role == "primary"


def _render(spec: _RuleChangeSpec, state: _RuleChangeState) -> GridFrame:
    if spec.case.family is RuleChangeFamily.ACTION_EFFECT_ROTATION:
        rows = [[0 for _ in range(RULE_CHANGE_GRID_SIZE)] for _ in range(RULE_CHANGE_GRID_SIZE)]
    else:
        rows = [[5 for _ in range(RULE_CHANGE_GRID_SIZE)] for _ in range(RULE_CHANGE_GRID_SIZE)]
        for x, y in spec.primary_cells:
            rows[y][x] = 3
        for x, y in spec.bypass_cells:
            rows[y][x] = 4
    target_x, target_y = state.visible_target
    player_x, player_y = state.position
    rows[target_y][target_x] = 2
    rows[player_y][player_x] = 1
    transformed = [[spec.palette[cell] for cell in row] for row in rows]
    return GridFrame.from_rows(transformed)


def _projection(state: _RuleChangeState) -> RuleChangeEvaluatorProjection:
    return RuleChangeEvaluatorProjection(
        action_count=state.action_count,
        reset_count=state.reset_count,
        position=state.position,
        visible_target=state.visible_target,
        calibrated_handles=state.calibrated_handles,
        prechange_support_cells=state.prechange_support_cells,
        prechange_support_receipts=state.prechange_support_receipts,
        pulse_armed=state.pulse_armed,
        pulse_triggered=state.pulse_triggered,
        trigger_step=state.trigger_step,
        mechanics_epoch=state.mechanics_epoch,
        coherent_successor_receipts=state.coherent_successor_receipts,
        successor_evidence_cells=state.successor_evidence_cells,
        successor_evidence_handles=state.successor_evidence_handles,
        resumed_predecessor_receipts=state.resumed_predecessor_receipts,
        pulse_resolved=state.pulse_resolved,
        terminal_state=state.terminal_state,
    )


def _arm(spec: _RuleChangeSpec, state: _RuleChangeState) -> _RuleChangeState:
    if state.pulse_armed or state.pulse_triggered:
        raise ValueError("the Stage 06 pulse may be armed exactly once")
    if len(state.calibrated_handles) != len(RULE_CHANGE_ACTIONS):
        raise ValueError("complete four-handle calibration is required before arming")
    if state.prechange_support_receipts != spec.case.support_required:
        raise ValueError("trigger arming requires the exact frozen support threshold")
    if state.action_count > spec.case.timing.latest_trigger_action:
        raise ValueError("trigger arming missed the frozen exposure deadline")
    successor = spec.case.kind is RuleChangeCaseKind.INTERVENTION
    if len(_oracle_plan(spec, state, successor=successor)) < 3:
        raise ValueError("final post-trigger target violates the frozen distance floor")
    return replace(state, pulse_armed=True)


def _qualifying_action(
    spec: _RuleChangeSpec,
    state: _RuleChangeState,
    effect: tuple[int, int],
) -> bool:
    if spec.case.family is RuleChangeFamily.ACTION_EFFECT_ROTATION:
        return effect != (0, 0)
    attempted = _point_add(state.position, effect, toroidal=False)
    return _role(spec, attempted) == "primary"


def _advance(
    spec: _RuleChangeSpec,
    state: _RuleChangeState,
    action: ActionRequest,
) -> _Transition:
    if state.terminal_state is not GameStateName.NOT_FINISHED:
        raise EnvironmentStateError("cannot act after terminal completion")
    if action.name is ActionName.RESET:
        reset = replace(
            state,
            position=spec.start,
            reset_count=state.reset_count + 1,
            terminal_state=GameStateName.NOT_FINISHED,
        )
        return _Transition(
            reset,
            {
                "attempted_cell": list(state.position),
                "attempted_role": "lifecycle",
                "distinct_successor_evidence": False,
                "predecessor_effect": [0, 0],
                "pulse_kind": "none",
                "realized_effect": [0, 0],
                "result_kind": "reset",
            },
        )

    predecessor_effect = spec.effects[action.name]
    step = state.action_count + 1
    qualifying = _qualifying_action(spec, state, predecessor_effect)
    triggers_now = state.pulse_armed and not state.pulse_triggered and qualifying
    pulse_triggered = state.pulse_triggered or triggers_now
    mechanics_epoch = state.mechanics_epoch
    coherent_successor = state.coherent_successor_receipts
    successor_evidence_cells = state.successor_evidence_cells
    successor_evidence_handles = state.successor_evidence_handles
    resumed_predecessor = state.resumed_predecessor_receipts
    pulse_resolved = state.pulse_resolved
    pulse_kind = "none"
    realized_effect = predecessor_effect

    if spec.case.kind is RuleChangeCaseKind.INTERVENTION:
        if triggers_now:
            mechanics_epoch = 1
        if mechanics_epoch == 1:
            pulse_kind = "persistent-intervention"
            if spec.case.family is RuleChangeFamily.ACTION_EFFECT_ROTATION:
                realized_effect = _rotate_clockwise(predecessor_effect)
    elif triggers_now:
        pulse_kind = "transient-noise"
        realized_effect = (0, 0)
    elif pulse_triggered and not pulse_resolved and qualifying:
        pulse_kind = "stationary-recovery"
        resumed_predecessor += 1
        pulse_resolved = resumed_predecessor >= 2

    attempted = _point_add(
        state.position,
        realized_effect,
        toroidal=spec.case.family is RuleChangeFamily.ACTION_EFFECT_ROTATION,
    )
    attempted_role = _role(spec, attempted)
    blocked = _blocked(
        spec,
        replace(state, mechanics_epoch=mechanics_epoch),
        attempted_role,
    )
    if spec.case.kind is RuleChangeCaseKind.NOISE and triggers_now:
        blocked = True
    position = state.position if blocked else attempted
    actual_effect = (position[0] - state.position[0], position[1] - state.position[1])
    if spec.case.family is RuleChangeFamily.ACTION_EFFECT_ROTATION:
        actual_effect = realized_effect
    result_kind = "blocked" if blocked else "translation"
    distinct_successor_evidence = False
    if spec.case.kind is RuleChangeCaseKind.INTERVENTION and mechanics_epoch == 1:
        if spec.case.family is RuleChangeFamily.ACTION_EFFECT_ROTATION:
            if qualifying and action.name not in successor_evidence_handles:
                successor_evidence_handles = (*successor_evidence_handles, action.name)
                successor_evidence_cells = (*successor_evidence_cells, attempted)
                coherent_successor += 1
                distinct_successor_evidence = True
        elif attempted_role in {"primary", "bypass"} and attempted not in successor_evidence_cells:
            successor_evidence_cells = (*successor_evidence_cells, attempted)
            coherent_successor += 1
            distinct_successor_evidence = True
        pulse_resolved = coherent_successor >= 2

    calibrated = state.calibrated_handles
    if action.name not in calibrated:
        calibrated = (*calibrated, action.name)
    calibration_complete = len(calibrated) == len(RULE_CHANGE_ACTIONS)

    support_cells = state.prechange_support_cells
    support_receipts = state.prechange_support_receipts
    waypoint_index = state.waypoint_index
    visible_target = state.visible_target
    before_pulse = not pulse_triggered
    if calibration_complete and before_pulse and support_receipts < spec.case.support_required:
        supports = False
        if spec.case.family is RuleChangeFamily.ACTION_EFFECT_ROTATION:
            supports = actual_effect != (0, 0)
        elif attempted_role == "primary" and not blocked and position not in support_cells:
            supports = position in spec.training_waypoints
            if supports:
                support_cells = (*support_cells, position)
        if supports:
            support_receipts += 1
            waypoint_index += 1
            visible_target = (
                spec.training_waypoints[waypoint_index]
                if waypoint_index < len(spec.training_waypoints)
                else spec.final_target
            )

    # The guide stays fixed through the trigger and confirmation receipts.  Once
    # the pulse is resolved it yields to the evaluator-declared final target,
    # giving the policy only an ordinary returned observation, never truth data.
    if pulse_resolved:
        visible_target = spec.final_target

    terminal = GameStateName.NOT_FINISHED
    if pulse_triggered and pulse_resolved and position == spec.final_target:
        terminal = GameStateName.WIN
    next_state = _RuleChangeState(
        position=position,
        visible_target=visible_target,
        waypoint_index=waypoint_index,
        calibrated_handles=calibrated,
        prechange_support_cells=support_cells,
        prechange_support_receipts=support_receipts,
        action_count=step,
        reset_count=state.reset_count,
        pulse_armed=state.pulse_armed,
        pulse_triggered=pulse_triggered,
        trigger_step=step if triggers_now else state.trigger_step,
        mechanics_epoch=mechanics_epoch,
        coherent_successor_receipts=coherent_successor,
        successor_evidence_cells=successor_evidence_cells,
        successor_evidence_handles=successor_evidence_handles,
        resumed_predecessor_receipts=resumed_predecessor,
        pulse_resolved=pulse_resolved,
        terminal_state=terminal,
    )
    return _Transition(
        next_state,
        {
            "attempted_cell": list(attempted),
            "attempted_role": attempted_role,
            "distinct_successor_evidence": distinct_successor_evidence,
            "predecessor_effect": list(predecessor_effect),
            "pulse_kind": pulse_kind,
            "realized_effect": list(actual_effect),
            "result_kind": result_kind,
        },
    )


def _effect_for_current_truth(
    spec: _RuleChangeSpec,
    state: _RuleChangeState,
    action: ActionName,
    *,
    successor: bool,
) -> tuple[int, int]:
    effect = spec.effects[action]
    rotated = spec.case.family is RuleChangeFamily.ACTION_EFFECT_ROTATION and (
        successor or state.mechanics_epoch == 1
    )
    return _rotate_clockwise(effect) if rotated else effect


def _oracle_plan(
    spec: _RuleChangeSpec,
    state: _RuleChangeState,
    *,
    successor: bool,
) -> tuple[ActionRequest, ...]:
    """Find an evaluator-only shortest route under the declared mechanics truth."""

    target = spec.final_target
    queue: deque[tuple[tuple[int, int], tuple[ActionRequest, ...]]] = deque(((state.position, ()),))
    visited = {state.position}
    truth_state = replace(
        state,
        mechanics_epoch=(
            1
            if successor and spec.case.family is not RuleChangeFamily.STATIONARY_NOISE
            else state.mechanics_epoch
        ),
    )
    while queue:
        position, plan = queue.popleft()
        if position == target:
            return plan
        for action in RULE_CHANGE_ACTIONS:
            effect = _effect_for_current_truth(
                spec,
                truth_state,
                action,
                successor=successor,
            )
            candidate = _point_add(
                position,
                effect,
                toroidal=spec.case.family is RuleChangeFamily.ACTION_EFFECT_ROTATION,
            )
            if _blocked(spec, truth_state, _role(spec, candidate)):
                candidate = position
            if candidate in visited:
                continue
            visited.add(candidate)
            queue.append((candidate, (*plan, ActionRequest(action))))
    raise ValueError(f"Stage 06 case {spec.case.case_id} has no truth-level route")


class _RuleChangeEngine:
    __slots__ = ("spec", "state")

    def __init__(self, spec: _RuleChangeSpec) -> None:
        self.spec = spec
        self.state = _initial_state(spec)

    def arm(self) -> None:
        self.state = _arm(self.spec, self.state)

    def take(self, action: ActionRequest) -> _Transition:
        transition = _advance(self.spec, self.state, action)
        self.state = transition.state
        return transition


class RuleChangeSession:
    """Production-shaped environment with no evaluator truth API."""

    __slots__ = ("__closed", "__closed_scorecard", "__engine", "__observation")

    def __init__(self, spec: _RuleChangeSpec) -> None:
        self.__engine = _RuleChangeEngine(spec)
        self.__closed = False
        self.__closed_scorecard: ScoreSummary | None = None
        self.__observation = self.__make_observation(
            ActionRequest(ActionName.RESET), full_reset=True
        )

    @property
    def observation(self) -> Observation:
        return self.__observation

    def __make_observation(
        self, returned_action: ActionRequest, *, full_reset: bool
    ) -> Observation:
        state = self.__engine.state
        return Observation(
            game_id=RULE_CHANGE_GAME_ID,
            frames=(_render(self.__engine.spec, state),),
            state=state.terminal_state,
            levels_completed=1 if state.terminal_state is GameStateName.WIN else 0,
            win_levels=1,
            available_actions=(
                RULE_CHANGE_ACTIONS if state.terminal_state is GameStateName.NOT_FINISHED else ()
            ),
            full_reset=full_reset,
            returned_action=returned_action,
            upstream_metadata=(("attempt", state.reset_count), ("step", state.action_count)),
        )

    def step(
        self,
        action: ActionRequest,
        *,
        reasoning: Mapping[str, JSONValue] | None = None,
    ) -> Observation:
        del reasoning
        if self.__closed:
            raise EnvironmentStateError("rule-change environment session is closed")
        validate_action_request(self.__observation, action)
        self.__engine.take(action)
        self.__observation = self.__make_observation(
            action, full_reset=action.name is ActionName.RESET
        )
        return self.__observation

    def reset(self) -> Observation:
        return self.step(ActionRequest(ActionName.RESET))

    def scorecard(self) -> ScoreSummary:
        if self.__closed_scorecard is not None:
            return self.__closed_scorecard
        state = self.__engine.state
        completed = state.terminal_state is GameStateName.WIN
        score = 1.0 if completed else 0.0
        return ScoreSummary(
            surface=EvaluationSurface.SYNTHETIC,
            verified=True,
            scorer="arc3.build-001.stage06.rule-change.v0.1",
            score=score,
            runs=(
                ScoreRunSummary(
                    game_id=RULE_CHANGE_GAME_ID,
                    score=score,
                    levels_completed=int(completed),
                    actions=state.action_count,
                    resets=state.reset_count,
                    state=state.terminal_state,
                    completed=completed,
                    level_scores=(score,),
                    level_actions=(state.action_count,),
                ),
            ),
        )

    def close(self) -> ScoreSummary:
        if self.__closed_scorecard is None:
            self.__closed_scorecard = self.scorecard()
        self.__closed = True
        return self.__closed_scorecard

    def _evaluator_arm(self) -> None:
        """Mirror an evaluator decision without exposing truth in observations."""

        self.__engine.arm()

    def _evaluator_clone(self) -> RuleChangeSession:
        """Fork evaluator-owned execution state without exposing it to policy."""

        clone = object.__new__(RuleChangeSession)
        clone.__engine = _RuleChangeEngine(self.__engine.spec)
        clone.__engine.state = self.__engine.state
        clone.__closed = self.__closed
        clone.__closed_scorecard = self.__closed_scorecard
        clone.__observation = self.__observation
        return clone


class RuleChangeEvaluatorEpisode:
    """Evaluator wrapper owning intervention control and immutable truth receipts."""

    __slots__ = ("__receipts", "__shadow", "case", "session")

    def __init__(self, case: RuleChangeCase) -> None:
        spec = _build_spec(case)
        self.case = case
        self.__shadow = _RuleChangeEngine(spec)
        self.session = RuleChangeSession(spec)
        self.__receipts: tuple[RuleChangeTruthReceipt, ...] = ()

    @property
    def projection(self) -> RuleChangeEvaluatorProjection:
        return _projection(self.__shadow.state)

    @property
    def truth_receipts(self) -> tuple[RuleChangeTruthReceipt, ...]:
        return self.__receipts

    @property
    def layout_receipt(self) -> dict[str, JSONValue]:
        """Return evaluator-only layout generation and degeneracy evidence."""

        spec = self.__shadow.spec
        if spec.case.family is RuleChangeFamily.ACTION_EFFECT_ROTATION:
            armed_position = spec.training_waypoints[spec.case.support_required - 1]
            armed_state = replace(
                _initial_state(spec),
                position=armed_position,
                visible_target=spec.final_target,
                waypoint_index=spec.case.support_required,
                prechange_support_cells=spec.training_waypoints[: spec.case.support_required],
                prechange_support_receipts=spec.case.support_required,
            )
            route_length = len(_oracle_plan(spec, armed_state, successor=True))
            predicates: dict[str, JSONValue] = {
                "nonzero_predecessor_effects": all(
                    effect != (0, 0) for _handle, effect in spec.raw_effects
                ),
                "rotated_effects_distinct": all(
                    effect != _rotate_clockwise(effect) for _handle, effect in spec.raw_effects
                ),
                "successor_route_length_3_to_12": 3 <= route_length <= 12,
                "toroidal_alias_rejected": RULE_CHANGE_GRID_SIZE > 2,
            }
            topology = "toroidal"
        else:
            armed_position = spec.training_waypoints[spec.case.support_required - 1]
            armed_state = replace(
                _initial_state(spec),
                position=armed_position,
                visible_target=spec.final_target,
                waypoint_index=spec.case.support_required,
                prechange_support_cells=spec.training_waypoints[: spec.case.support_required],
                prechange_support_receipts=spec.case.support_required,
            )
            route_length = len(
                _oracle_plan(
                    spec,
                    armed_state,
                    successor=spec.case.kind is RuleChangeCaseKind.INTERVENTION,
                )
            )
            predicates = {
                "distinct_prechange_primary_entries": (
                    len(set(spec.training_waypoints[: spec.case.support_required]))
                    == spec.case.support_required
                ),
                "roles_disjoint": not (spec.primary_cells & spec.bypass_cells),
                "successor_route_length_3_to_12": 3 <= route_length <= 12,
                "two_distinct_discrimination_cells": (
                    len(spec.primary_cells | spec.bypass_cells) >= 2
                ),
                "unambiguous_affected_role": bool(spec.primary_cells) and bool(spec.bypass_cells),
            }
            topology = "bounded-two-lane"
        layout_core: dict[str, JSONValue] = {
            "action_variant": spec.case.action_variant.value,
            "bypass_cells": [list(item) for item in sorted(spec.bypass_cells)],
            "case_id": spec.case.case_id,
            "family": spec.case.family.value,
            "final_target": list(spec.final_target),
            "palette_variant": spec.case.palette_variant.value,
            "permanent_wall_count": len(spec.permanent_walls),
            "predicates": predicates,
            "primary_cells": [list(item) for item in sorted(spec.primary_cells)],
            "rejected_candidate_count": spec.case.rejection_count,
            "rejection_reasons": [],
            "seed": spec.case.seed,
            "start": list(spec.start),
            "successor_route_length": route_length,
            "timing": spec.case.timing.value,
            "topology": topology,
            "training_waypoints": [list(item) for item in spec.training_waypoints],
        }
        return {
            **layout_core,
            "layout_id": sha256_json({"domain": "arc3.stage06.layout-identity.v1", **layout_core}),
            "receipt_hash": sha256_json(
                {"domain": "arc3.stage06.layout-receipt.v1", **layout_core}
            ),
        }

    @property
    def ready_for_evaluator_arm(self) -> bool:
        state = self.__shadow.state
        return (
            not state.pulse_armed
            and not state.pulse_triggered
            and len(state.calibrated_handles) == len(RULE_CHANGE_ACTIONS)
            and state.prechange_support_receipts == self.case.support_required
            and state.action_count <= self.case.timing.latest_trigger_action
        )

    def arm_trigger(self) -> None:
        """Evaluator-only arm after the harness has independently proved readiness."""

        self.__shadow.arm()
        self.session._evaluator_arm()

    def trigger_eligible(self, action: ActionRequest) -> bool:
        """Return evaluator truth for the already-selected action only."""

        if action.name not in RULE_CHANGE_ACTIONS:
            return False
        return _qualifying_action(
            self.__shadow.spec,
            self.__shadow.state,
            self.__shadow.spec.effects[action.name],
        )

    def action_for_predecessor_effect(self, effect: tuple[int, int]) -> ActionRequest:
        """Return evaluator-only raw handle realizing a pre-change effect."""

        for action, candidate in self.__shadow.spec.raw_effects:
            if candidate == effect:
                return ActionRequest(action)
        raise ValueError(f"no predecessor action realizes {effect!r}")

    def action_for_successor_effect(self, effect: tuple[int, int]) -> ActionRequest:
        """Return evaluator-only raw handle realizing a persistent successor effect."""

        for action in RULE_CHANGE_ACTIONS:
            if (
                _effect_for_current_truth(
                    self.__shadow.spec,
                    self.__shadow.state,
                    action,
                    successor=True,
                )
                == effect
            ):
                return ActionRequest(action)
        raise ValueError(f"no successor action realizes {effect!r}")

    def successor_oracle_plan(self) -> tuple[ActionRequest, ...]:
        """Return an evaluator-only shortest plan under post-trigger truth."""

        return _oracle_plan(
            self.__shadow.spec,
            self.__shadow.state,
            successor=True,
        )

    def stationary_oracle_plan(self) -> tuple[ActionRequest, ...]:
        """Return an evaluator-only shortest plan under unchanged truth."""

        return _oracle_plan(
            self.__shadow.spec,
            self.__shadow.state,
            successor=False,
        )

    def fork(self) -> RuleChangeEvaluatorEpisode:
        """Fork one sealed evaluator prefix for checkpoint differential testing."""

        clone = object.__new__(RuleChangeEvaluatorEpisode)
        clone.case = self.case
        clone.__shadow = _RuleChangeEngine(self.__shadow.spec)
        clone.__shadow.state = self.__shadow.state
        clone.session = self.session._evaluator_clone()
        clone.__receipts = self.__receipts
        return clone

    def take(
        self,
        action: ActionRequest,
        *,
        reasoning: Mapping[str, JSONValue] | None = None,
    ) -> EvaluatedRuleChangeStep:
        before_frame = self.session.observation.frames[-1]
        before_position = self.__shadow.state.position
        transition = self.__shadow.take(action)
        observation = self.session.step(action, reasoning=reasoning)
        expected_frame = _render(self.__shadow.spec, transition.state)
        if observation.frames[-1] != expected_frame:
            raise AssertionError("production and evaluator rule-change states diverged")
        if observation.state is not transition.state.terminal_state:
            raise AssertionError("production and evaluator terminal states diverged")
        core: dict[str, JSONValue] = {
            "action": _action_payload(action),
            "after_frame_hash": str(observation.frames[-1].digest),
            "after_position": list(transition.state.position),
            "attempted_cell": transition.truth_core["attempted_cell"],
            "attempted_role": transition.truth_core["attempted_role"],
            "before_frame_hash": str(before_frame.digest),
            "before_position": list(before_position),
            "case_id": self.case.case_id,
            "coherent_successor_receipts": transition.state.coherent_successor_receipts,
            "distinct_successor_evidence": transition.truth_core["distinct_successor_evidence"],
            "mechanics_epoch": transition.state.mechanics_epoch,
            "predecessor_effect": transition.truth_core["predecessor_effect"],
            "pulse_armed": transition.state.pulse_armed,
            "pulse_kind": transition.truth_core["pulse_kind"],
            "pulse_resolved": transition.state.pulse_resolved,
            "pulse_triggered": transition.state.pulse_triggered,
            "realized_effect": transition.truth_core["realized_effect"],
            "result_kind": transition.truth_core["result_kind"],
            "receipt_sequence": len(self.__receipts) + 1,
            "resumed_predecessor_receipts": transition.state.resumed_predecessor_receipts,
            "step": transition.state.action_count,
            "terminal_state": transition.state.terminal_state.value,
            "trigger_step": transition.state.trigger_step,
            "successor_evidence_cells": [
                list(item) for item in transition.state.successor_evidence_cells
            ],
            "successor_evidence_handles": [
                item.value for item in transition.state.successor_evidence_handles
            ],
        }
        receipt_id = sha256_json({"domain": "arc3.stage06.truth-receipt-id.v1", **core})
        receipt_hash = sha256_json(
            {
                "domain": "arc3.stage06.truth-receipt.v1",
                "previous_receipt_hash": (
                    self.__receipts[-1].receipt_hash if self.__receipts else None
                ),
                "receipt_id": receipt_id,
                **core,
            }
        )
        predecessor = transition.truth_core["predecessor_effect"]
        realized = transition.truth_core["realized_effect"]
        attempted = transition.truth_core["attempted_cell"]
        if (
            not isinstance(predecessor, list)
            or len(predecessor) != 2
            or not all(isinstance(item, int) and not isinstance(item, bool) for item in predecessor)
            or not isinstance(realized, list)
            or len(realized) != 2
            or not all(isinstance(item, int) and not isinstance(item, bool) for item in realized)
            or not isinstance(attempted, list)
            or len(attempted) != 2
            or not all(isinstance(item, int) and not isinstance(item, bool) for item in attempted)
        ):
            raise AssertionError("transition effects are not canonical vectors")
        predecessor_x, predecessor_y = predecessor
        realized_x, realized_y = realized
        attempted_x, attempted_y = attempted
        assert isinstance(predecessor_x, int) and not isinstance(predecessor_x, bool)
        assert isinstance(predecessor_y, int) and not isinstance(predecessor_y, bool)
        assert isinstance(realized_x, int) and not isinstance(realized_x, bool)
        assert isinstance(realized_y, int) and not isinstance(realized_y, bool)
        assert isinstance(attempted_x, int) and not isinstance(attempted_x, bool)
        assert isinstance(attempted_y, int) and not isinstance(attempted_y, bool)
        receipt = RuleChangeTruthReceipt(
            receipt_id=receipt_id,
            receipt_hash=receipt_hash,
            receipt_sequence=len(self.__receipts) + 1,
            previous_receipt_hash=(self.__receipts[-1].receipt_hash if self.__receipts else None),
            case_id=self.case.case_id,
            step=transition.state.action_count,
            action=action,
            before_frame_hash=str(before_frame.digest),
            after_frame_hash=str(observation.frames[-1].digest),
            before_position=before_position,
            after_position=transition.state.position,
            predecessor_effect=(predecessor_x, predecessor_y),
            realized_effect=(realized_x, realized_y),
            attempted_cell=(attempted_x, attempted_y),
            attempted_role=str(transition.truth_core["attempted_role"]),
            distinct_successor_evidence=bool(transition.truth_core["distinct_successor_evidence"]),
            result_kind=str(transition.truth_core["result_kind"]),
            pulse_kind=str(transition.truth_core["pulse_kind"]),
            pulse_armed=transition.state.pulse_armed,
            pulse_triggered=transition.state.pulse_triggered,
            trigger_step=transition.state.trigger_step,
            mechanics_epoch=transition.state.mechanics_epoch,
            coherent_successor_receipts=transition.state.coherent_successor_receipts,
            successor_evidence_cells=transition.state.successor_evidence_cells,
            successor_evidence_handles=transition.state.successor_evidence_handles,
            resumed_predecessor_receipts=transition.state.resumed_predecessor_receipts,
            pulse_resolved=transition.state.pulse_resolved,
            terminal_state=transition.state.terminal_state,
        )
        self.__receipts = (*self.__receipts, receipt)
        return EvaluatedRuleChangeStep(observation=observation, truth=receipt)

    def assert_policy_blinded(self) -> None:
        """Reject evaluator truth from the complete normalized observation graph."""

        observation = self.session.observation
        if observation.game_id != RULE_CHANGE_GAME_ID:
            raise AssertionError("case-specific identity leaked through game_id")
        if tuple(key for key, _value in observation.upstream_metadata) != (
            "attempt",
            "step",
        ):
            raise AssertionError("unexpected evaluator metadata leaked to production")
        serialized = repr(observation).lower()
        forbidden = {
            self.case.case_id.lower(),
            self.case.family.value.lower(),
            self.case.timing.value.lower(),
            self.case.palette_variant.value.lower(),
            self.case.action_variant.value.lower(),
            "pulse_triggered",
            "terrain_truth",
        }
        leaked = sorted(token for token in forbidden if token in serialized)
        if leaked:
            raise AssertionError(f"evaluator truth leaked to production: {leaked}")


def open_rule_change_case(case: RuleChangeCase) -> RuleChangeEvaluatorEpisode:
    """Open one frozen evaluator case without exposing its truth to policy input."""

    episode = RuleChangeEvaluatorEpisode(case)
    episode.assert_policy_blinded()
    return episode


__all__ = [
    "RULE_CHANGE_ACTIONS",
    "RULE_CHANGE_GAME_ID",
    "RULE_CHANGE_GRID_SIZE",
    "RULE_CHANGE_SEEDS",
    "ActionVariant",
    "CheckpointBoundary",
    "EvaluatedRuleChangeStep",
    "PaletteVariant",
    "RuleChangeCase",
    "RuleChangeCaseKind",
    "RuleChangeCheckpointCase",
    "RuleChangeEvaluatorEpisode",
    "RuleChangeEvaluatorProjection",
    "RuleChangeFamily",
    "RuleChangeSession",
    "RuleChangeTiming",
    "RuleChangeTruthReceipt",
    "checkpoint_schedule",
    "intervention_schedule",
    "noise_control_schedule",
    "open_rule_change_case",
]
