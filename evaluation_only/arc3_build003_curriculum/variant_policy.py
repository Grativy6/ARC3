"""Observation-only Build 003 ablation policies.

This module is imported inside the policy subprocess after evaluator modules
have been denied.  It deliberately depends only on the public observation
contract and production BLA/CLEF primitives.  Family names, seeds, rules,
transition truth, and oracle plans never enter this process.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict, deque
from dataclasses import asdict, dataclass, field

from arc3.adapters import Observation
from arc3.exploration import (
    CausalActionReceipt,
    EffectChannel,
    EffectKnowledge,
    EffectVector,
    FactoredEffect,
    ResourceFailureRisk,
    RiskLevel,
    compare_effect_vectors,
    extract_observed_effects,
)
from arc3.mechanics import (
    CHANNEL_ORDER,
    ChannelResidual,
    ChannelValue,
    CompositionMode,
    ConsequenceChannel,
    ConsequenceVector,
    DelayedEffect,
    DisplacementEffect,
    EvidenceProvenance,
    KnowledgeState,
    LearningReceipt,
    LegalActionEffect,
    MechanicalLearner,
    MechanicContext,
    MechanicLedgerBudget,
    MechanicPredictionReceipt,
    MechanicRef,
    MechanicScope,
    MechanicsError,
    ObjectEffect,
    ObjectOperation,
    ProbeCandidate,
    QuantityEffect,
    ResidualKind,
    ScopeCeiling,
    ScoreProgressEffect,
    StatusEffect,
    TerminalEffect,
    TopologyEffect,
    TopologyOperation,
)
from arc3.perception import (
    ActionWindow,
    DynamicClaimContext,
    EvidenceFamily,
    EvidenceReading,
    LayerAssessment,
    LayerDeclaration,
    LogicalLayer,
    ReadabilityThreshold,
    ReadabilityWall,
    ResidualDisposition,
    ValidityGate,
    assess_residual,
    measure_delta,
    normalize_grid,
)
from arc3.types import ActionName, ActionRequest, GameStateName, StateScope

Point = tuple[int, int]
MOVE_ACTIONS = (
    ActionName.ACTION1,
    ActionName.ACTION2,
    ActionName.ACTION3,
    ActionName.ACTION4,
)
CARDINALS: frozenset[Point] = frozenset({(0, -1), (0, 1), (-1, 0), (1, 0)})
SUPPORTED_VARIANTS = frozenset({"BLA_CLEF_LEVEL_RESET", "BLA_ONLY_PERSISTENT", "BLA_CLEF_FULL"})


def _channel_counter() -> dict[str, int]:
    return {channel.value: 0 for channel in CHANNEL_ORDER}


def _composition_counter() -> dict[str, int]:
    return {mode.value: 0 for mode in CompositionMode}


@dataclass(frozen=True, slots=True)
class _TransitionFacts:
    """Observation-derived facts retained before any mechanic interpretation."""

    context: MechanicContext
    observed: ConsequenceVector
    controlled_displacement: tuple[Point, Point, int] | None
    other_object_motion: tuple[str, Point] | None
    target: Point | None
    target_role: str | None
    changed_points: tuple[Point, ...]
    visible_effect_signature: str | None
    source_event_id: str


@dataclass(slots=True)
class _TrackedRepair:
    residual_id: str
    ref: MechanicRef
    channel: ConsequenceChannel
    failures: int = 0


@dataclass(frozen=True, slots=True)
class _HistoryFact:
    step: int
    action: ActionName
    context: MechanicContext
    source_event_id: str
    visible_effect_signature: str | None


@dataclass(frozen=True, slots=True)
class _ActionLink:
    step: int
    level_index: int
    action: dict[str, object]
    prediction_id: str
    prediction_digest: str
    before_ref: str
    after_ref: str
    learning_digest: str
    causal_receipt_digest: str
    complete: bool

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class _LevelMetrics:
    environment_actions: int = 0
    resets: int = 0
    exploratory_actions: int = 0
    progress_actions: int = 0
    redundant_probes: int = 0
    actions_to_stable: int | None = None
    movement_prediction_errors: int = 0
    resource_prediction_errors: int = 0
    access_prediction_errors: int = 0
    hazard_prediction_errors: int = 0
    prediction_errors_by_channel: dict[str, int] = field(default_factory=_channel_counter)
    residuals_observed: int = 0
    residuals_localized: int = 0
    residuals_resolved: int = 0
    base_mechanics_retained: bool = False
    observed_retained_matches: int = 0
    erroneous_global_reopenings: int | None = None
    passive_confirmations: int = 0
    transfer_confirmations: int = 0
    local_repair_candidates_opened: int = 0
    local_repairs_confirmed: int = 0
    local_repair_failures: int = 0
    base_reopenings: int = 0
    composition_events: dict[str, int] = field(default_factory=_composition_counter)
    clef_promotions: int = 0
    clef_parks: int = 0
    clef_stops: int = 0
    other_object_effects_observed: int = 0
    topology_changes_confirmed: int = 0
    delayed_candidates_confirmed: int = 0
    unresolved_ledger_count: int = 0
    active_ledger_pressure: int = 0
    receipt_count: int = 0
    complete_receipt_count: int = 0
    completed: bool = False

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _resource(observation: Observation) -> int:
    row = observation.frames[-1].cells[0]
    return sum(1 << index for index, value in enumerate(row[:5]) if value != 0)


def _board(observation: Observation) -> tuple[tuple[int, ...], ...]:
    return observation.frames[-1].cells


def _positions(rows: tuple[tuple[int, ...], ...], color: int) -> tuple[Point, ...]:
    return tuple(
        (x, y)
        for y, row in enumerate(rows)
        if y > 0
        for x, value in enumerate(row)
        if value == color
    )


def _cell(rows: tuple[tuple[int, ...], ...], point: Point) -> int:
    return rows[point[1]][point[0]]


def _add(left: Point, right: Point) -> Point:
    return left[0] + right[0], left[1] + right[1]


def _digest(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _metadata_int(observation: Observation, key: str, default: int) -> int:
    value = dict(observation.upstream_metadata).get(key, default)
    return value if isinstance(value, int) and not isinstance(value, bool) else default


def _observation_ref(observation: Observation) -> str:
    """Hash only the public observation fields used by the policy and runner audit."""

    return _digest(
        {
            "frames": [
                {
                    "digest": str(frame.digest),
                    "width": frame.width,
                    "height": frame.height,
                }
                for frame in observation.frames
            ],
            "state": observation.state.value,
            "levels_completed": observation.levels_completed,
            "win_levels": observation.win_levels,
            "available_actions": [action.value for action in observation.available_actions],
            "full_reset": observation.full_reset,
            "returned_action": (
                None
                if observation.returned_action is None
                else {
                    "name": observation.returned_action.name.value,
                    "coordinate": (
                        None
                        if observation.returned_action.coordinate is None
                        else {
                            "x": observation.returned_action.coordinate.x,
                            "y": observation.returned_action.coordinate.y,
                        }
                    ),
                }
            ),
            "metadata": list(observation.upstream_metadata),
        }
    )


def _role_signature(rows: tuple[tuple[int, ...], ...], point: Point | None) -> str | None:
    """Return a level-local visible role without attaching semantic meaning."""

    if point is None or not (0 <= point[1] < len(rows) and 0 <= point[0] < len(rows[0])):
        return None
    color = _cell(rows, point)
    neighbors = tuple(
        sorted(
            (
                dx,
                dy,
                rows[point[1] + dy][point[0] + dx],
            )
            for dy in (-1, 0, 1)
            for dx in (-1, 0, 1)
            if 0 <= point[1] + dy < len(rows) and 0 <= point[0] + dx < len(rows[0])
        )
    )
    return _digest({"color": color, "neighbors": neighbors})[:31]


def _quantity_delta(value: ChannelValue) -> int | None:
    if value.knowledge is KnowledgeState.UNKNOWN:
        return None
    if value.is_known_empty:
        return 0
    if len(value.effects) != 1:
        return None
    effect = value.effects[0]
    return effect.delta if isinstance(effect, QuantityEffect) else None


def _quantity_value(subject: str, delta: int) -> ChannelValue:
    return (
        ChannelValue.known_empty()
        if delta == 0
        else ChannelValue.known(QuantityEffect(subject, delta))
    )


def _score_value(metric: str, delta: int) -> ChannelValue:
    return (
        ChannelValue.known_empty()
        if delta == 0
        else ChannelValue.known(ScoreProgressEffect(metric, delta))
    )


def _known_value(vector: ConsequenceVector, channel: ConsequenceChannel) -> ChannelValue:
    return vector.get(channel)


class ObservationOnlyVariantPolicy:
    """Small deterministic learner that derives every policy fact from observations."""

    def __init__(self, variant: str) -> None:
        if variant not in SUPPORTED_VARIANTS:
            raise ValueError(f"unsupported observation-only variant: {variant}")
        self.variant = variant
        self._persistent = variant != "BLA_CLEF_LEVEL_RESET"
        self._clef_enabled = variant != "BLA_ONLY_PERSISTENT"
        self._game_scope = ""
        self._level_index = 0
        self._attempt = 0
        self._step = 0
        self._learner: MechanicalLearner | None = None
        self._movement: dict[ActionName, Point] = {}
        self._movement_refs: set[ActionName] = set()
        self._resource_refs: set[ActionName] = set()
        self._baseline_refs: dict[tuple[ActionName, ConsequenceChannel], MechanicRef] = {}
        self._metrics = [_LevelMetrics() for _ in range(10)]
        self._previous: Observation | None = None
        self._last_action: ActionRequest | None = None
        self._last_prediction: MechanicPredictionReceipt | None = None
        self._last_before_ref: str | None = None
        self._last_reason = ""
        self._last_target: Point | None = None
        self._last_context_target: Point | None = None
        self._last_player_position: Point | None = None
        self._last_player_color: int | None = None
        self._player_position: Point | None = None
        self._player_color: int | None = None
        self._visited: set[Point] = set()
        self._blocked: set[Point] = set()
        self._wall_colors: set[int] = set()
        self._pending_interaction = False
        self._interaction_used = False
        self._probe_counts: Counter[ActionName] = Counter()
        self._failed_probe_signatures: Counter[tuple[ActionName, Point | None]] = Counter()
        self._recolor_counts: Counter[Point] = Counter()
        self._ignored_dynamic: set[Point] = set()
        self._resource_delta_by_action: dict[ActionName, int] = {}
        self._under_player_roles: dict[Point, str] = {}
        self._blocked_history: dict[Point, str] = {}
        self._retained_refs: set[MechanicRef] = set()
        self._transferred_refs: set[MechanicRef] = set()
        self._origin_residuals: dict[MechanicRef, tuple[str, int]] = {}
        self._pending_residual_refs: dict[str, set[MechanicRef]] = {}
        self._repairs: dict[MechanicRef, _TrackedRepair] = {}
        self._repair_keys: dict[str, MechanicRef] = {}
        self._history: deque[_HistoryFact] = deque(maxlen=8)
        self._delayed_evidence: dict[tuple[str, str, int], set[str]] = {}
        self._delayed_refs: dict[tuple[str, str, int], MechanicRef] = {}
        self._action_links: list[_ActionLink] = []
        self._receipt_digests: list[str] = []

    @property
    def _context(self) -> MechanicContext:
        return MechanicContext(
            game_scope=self._game_scope,
            level_scope=f"level-{self._level_index + 1}-attempt-{self._attempt}",
        )

    def _new_learner(self) -> MechanicalLearner:
        return MechanicalLearner(
            game_scope=self._game_scope,
            level_scope=self._context.level_scope,
            budget=MechanicLedgerBudget(max_events=4096, max_contexts_per_channel=128),
        )

    def _enter_level(self, index: int, *, reset: bool = False) -> None:
        self._level_index = index
        self._player_position = None
        self._player_color = None
        self._last_context_target = None
        self._visited.clear()
        self._blocked.clear()
        self._wall_colors.clear()
        self._pending_interaction = False
        self._interaction_used = False
        self._probe_counts.clear()
        self._failed_probe_signatures.clear()
        self._recolor_counts.clear()
        self._ignored_dynamic.clear()
        self._under_player_roles.clear()
        self._blocked_history.clear()
        self._history.clear()
        self._delayed_evidence.clear()
        self._delayed_refs.clear()
        self._retained_refs.clear()
        self._transferred_refs.clear()
        if not self._persistent:
            self._movement.clear()
            self._movement_refs.clear()
            self._resource_refs.clear()
            self._resource_delta_by_action.clear()
            self._baseline_refs.clear()
            self._repairs.clear()
            self._repair_keys.clear()
            self._origin_residuals.clear()
            self._pending_residual_refs.clear()
            self._learner = self._new_learner()
        elif self._learner is None:
            self._learner = self._new_learner()
        else:
            try:
                boundary = self._learner.start_level(self._context.level_scope)
                self._retained_refs.update(boundary.retained_refs)
            except MechanicsError:
                # A bounded ledger can be replaced after its failure is counted;
                # learned action semantics remain observation-derived policy state.
                self._metrics[index].hazard_prediction_errors += 1
                self._learner = self._new_learner()
        if self._persistent and len(self._movement) == len(MOVE_ACTIONS):
            self._metrics[index].actions_to_stable = 0

    def choose_action(self, observation: Observation) -> ActionRequest:
        if not self._game_scope:
            self._game_scope = str(observation.game_id)
            self._attempt = _metadata_int(observation, "attempt", 0)
            self._enter_level(observation.levels_completed)
        self._consume_observation(observation)
        if observation.state is GameStateName.WIN:
            raise RuntimeError("WIN is terminal and has no next action")
        if observation.state in {GameStateName.GAME_OVER, GameStateName.NOT_PLAYED}:
            action = ActionRequest(ActionName.RESET)
            self._begin_action(action, "mandatory-reset", target=None)
            return action
        action, reason, target = self._select_nonterminal_action(observation)
        self._begin_action(action, reason, target=target)
        return action

    def finalize(self, observation: Observation) -> dict[str, object]:
        self._consume_observation(observation)
        if self._learner is not None:
            current = self._metrics[min(self._level_index, 9)]
            current.unresolved_ledger_count = max(
                current.unresolved_ledger_count,
                len(self._learner.open_residuals)
                + (0 if self._clef_enabled else len(self._recolor_counts)),
            )
            current.active_ledger_pressure = max(
                current.active_ledger_pressure,
                len(self._learner.ledger.active()) + len(self._learner.open_residuals),
            )
        return {
            "schema": "arc3.build003.worker-summary.v0.1",
            "variant": self.variant,
            "levels": [item.to_dict() for item in self._metrics],
            "receipt_digest": _digest(self._receipt_digests),
            "receipt_count": len(self._receipt_digests),
            "action_links": [item.to_dict() for item in self._action_links],
            "final_state": observation.state.value,
            "levels_completed": observation.levels_completed,
            "win_levels": observation.win_levels,
        }

    def _consume_observation(self, observation: Observation) -> None:
        if self._previous is None or self._last_action is None:
            self._previous = observation
            return
        before = self._previous
        old_level = self._level_index
        self._integrate_transition(before, observation, self._last_action)
        self._previous = observation
        self._last_action = None
        self._last_prediction = None
        self._last_before_ref = None
        if observation.full_reset:
            self._attempt = _metadata_int(observation, "attempt", self._attempt + 1)
            self._enter_level(0, reset=True)
        elif observation.levels_completed > before.levels_completed:
            self._metrics[old_level].completed = True
            if observation.state is not GameStateName.WIN:
                self._enter_level(observation.levels_completed)

    def _begin_action(self, action: ActionRequest, reason: str, *, target: Point | None) -> None:
        metric = self._metrics[self._level_index]
        if action.name is not ActionName.RESET:
            metric.environment_actions += 1
            if reason.startswith("probe") or reason.startswith("interact"):
                metric.exploratory_actions += 1
            else:
                metric.progress_actions += 1
        else:
            metric.resets += 1
        if self._learner is None:
            raise RuntimeError("mechanical learner is not initialized")
        observation = self._previous
        if observation is None:
            raise RuntimeError("an action requires a current observation")
        action_target = self._action_target(action, target)
        context = self._context_for(observation, action_target)
        try:
            prediction = self._learner.predict(action, context, emitted_step=self._step)
        except MechanicsError:
            metric.hazard_prediction_errors += 1
            self._learner = self._new_learner()
            prediction = self._learner.predict(action, context, emitted_step=self._step)
        self._last_prediction = prediction
        self._last_before_ref = _observation_ref(observation)
        used_modes = {
            self._learner.ledger.get(ref).version.composition_mode
            for channel in CHANNEL_ORDER
            for ref in prediction.composition.contributors_for(channel)
        }
        for mode in used_modes:
            metric.composition_events[mode.value] += 1
        self._last_action = action
        self._last_reason = reason
        self._last_target = target
        self._last_context_target = action_target
        self._last_player_position = self._player_position
        self._last_player_color = self._player_color
        self._step += 1

    def _action_target(self, action: ActionRequest, explicit: Point | None) -> Point | None:
        if self._player_position is not None and action.name in self._movement:
            return _add(self._player_position, self._movement[action.name])
        return explicit

    def _context_for(self, observation: Observation, target: Point | None) -> MechanicContext:
        role = _role_signature(_board(observation), target)
        return MechanicContext(
            game_scope=self._game_scope,
            level_scope=self._context.level_scope,
            object_roles=() if role is None else (role,),
        )

    def _select_nonterminal_action(
        self, observation: Observation
    ) -> tuple[ActionRequest, str, Point | None]:
        if self._player_position is None or len(self._movement) < 3:
            action = self._probe_action(observation)
            return ActionRequest(action), "probe-movement", None
        if len(self._movement) == 3:
            missing_action = next(action for action in MOVE_ACTIONS if action not in self._movement)
            missing_vector = next(
                vector for vector in CARDINALS if vector not in self._movement.values()
            )
            self._movement[missing_action] = missing_vector
            self._open_movement_mechanic(
                missing_action,
                missing_vector,
                source=f"generic-cardinal-completion:{self._step}",
                provenance=EvidenceProvenance.GENERIC_GAME_PRIOR,
            )
            metric = self._metrics[self._level_index]
            if metric.actions_to_stable is None:
                metric.actions_to_stable = metric.environment_actions
        if self._pending_interaction and ActionName.ACTION5 in observation.available_actions:
            self._pending_interaction = False
            self._interaction_used = True
            if self._player_position is not None:
                self._visited.add(self._player_position)
            return ActionRequest(ActionName.ACTION5), "interact-candidate", self._player_position

        path = self._path_to_nearest_candidate(observation)
        if path:
            vector, target = path
            action = next(
                action
                for action, learned in sorted(
                    self._movement.items(), key=lambda item: item[0].value
                )
                if learned == vector
            )
            return ActionRequest(action), "progress-nearest-visible-candidate", target

        # No candidate is currently reachable.  A single interaction or a
        # reversible move is the smallest observation-only discriminating act.
        if ActionName.ACTION5 in observation.available_actions:
            signature = (ActionName.ACTION5, self._player_position)
            if self._failed_probe_signatures[signature] < 1:
                self._failed_probe_signatures[signature] += 1
                selected = self._consequential_probe_action(
                    observation, allowed_actions=(ActionName.ACTION5,)
                )
                return (
                    ActionRequest(selected or ActionName.ACTION5),
                    "probe-consequential-residual"
                    if selected is not None
                    else "probe-local-interaction",
                    None,
                )
        for action, vector in sorted(self._movement.items(), key=lambda item: item[0].value):
            if self._player_position is not None and self._inside(
                _add(self._player_position, vector), observation
            ):
                selected = self._consequential_probe_action(observation, allowed_actions=(action,))
                return (
                    ActionRequest(selected or action),
                    "probe-consequential-residual"
                    if selected is not None
                    else "probe-reachability",
                    None,
                )
        return ActionRequest(ActionName.ACTION5), "probe-no-reachable-candidate", None

    def _consequential_probe_action(
        self,
        observation: Observation,
        *,
        allowed_actions: tuple[ActionName, ...],
    ) -> ActionName | None:
        if self._learner is None or not self._learner.open_residuals:
            return None
        channels = tuple(
            sorted(
                {
                    residual.channel
                    for record in self._learner.open_residuals
                    for residual in record.residual.consequential
                },
                key=CHANNEL_ORDER.index,
            )
        )
        if not channels:
            return None
        candidates = tuple(
            ProbeCandidate(
                action=ActionRequest(action),
                context=self._context,
                target_channels=channels,
                expected_information_gain=2 if action not in self._movement else 1,
                reversibility=1 if action in self._movement else 0,
                failure_cost=1,
                novelty=1,
                repetition_count=min(self._probe_counts[action], 2),
            )
            for action in allowed_actions
            if action in observation.available_actions
            if action is not ActionName.RESET and action is not ActionName.ACTION6
        )
        if not candidates:
            return None
        try:
            choice = self._learner.choose_probe(candidates)
        except MechanicsError:
            return None
        selected = choice.selected.action.name
        self._probe_counts[selected] += 1
        if self._probe_counts[selected] > 1:
            self._metrics[self._level_index].redundant_probes += 1
        return selected

    def _probe_action(self, observation: Observation) -> ActionName:
        if self._learner is None:
            raise RuntimeError("mechanical learner is not initialized")
        candidates: list[ProbeCandidate] = []
        available = set(observation.available_actions)
        for action in MOVE_ACTIONS:
            if action not in available:
                continue
            novelty = 2 if action not in self._movement else 1
            candidates.append(
                ProbeCandidate(
                    action=ActionRequest(action),
                    context=self._context,
                    target_channels=(ConsequenceChannel.CONTROLLED_DISPLACEMENT,),
                    expected_information_gain=novelty,
                    reversibility=1,
                    failure_cost=1,
                    novelty=novelty,
                    repetition_count=min(self._probe_counts[action], 1),
                )
            )
        choice = self._learner.choose_probe(candidates)
        selected = choice.selected.action.name
        self._probe_counts[selected] += 1
        if self._probe_counts[selected] > 1:
            self._metrics[self._level_index].redundant_probes += 1
        return selected

    def _path_to_nearest_candidate(self, observation: Observation) -> tuple[Point, Point] | None:
        if self._player_position is None:
            return None
        rows = _board(observation)
        counts = Counter(
            value
            for y, row in enumerate(rows)
            if y > 0
            for value in row
            if value != 0 and value != self._player_color
        )
        candidates = {
            (x, y)
            for y, row in enumerate(rows)
            if y > 0
            for x, value in enumerate(row)
            if value != 0
            and value != self._player_color
            and counts[value] == 1
            and (x, y) not in self._visited
            and (x, y) not in self._ignored_dynamic
            and (x, y) not in self._blocked
        }
        if not candidates:
            return None
        obstacles = {
            (x, y)
            for y, row in enumerate(rows)
            if y > 0
            for x, value in enumerate(row)
            if value in self._wall_colors
        } | self._blocked
        start = self._player_position
        frontier: deque[Point] = deque([start])
        prior: dict[Point, Point | None] = {start: None}
        reached: Point | None = None
        while frontier:
            current = frontier.popleft()
            if current in candidates:
                reached = current
                break
            for vector in sorted(CARDINALS):
                child = _add(current, vector)
                if child in prior or child in obstacles or not self._inside(child, observation):
                    continue
                prior[child] = current
                frontier.append(child)
        if reached is None:
            return None
        child = reached
        while prior[child] != start:
            parent = prior[child]
            if parent is None:
                return None
            child = parent
        return (child[0] - start[0], child[1] - start[1]), reached

    @staticmethod
    def _inside(point: Point, observation: Observation) -> bool:
        rows = _board(observation)
        return 0 < point[0] < len(rows[0]) - 1 and 0 < point[1] < len(rows) - 1

    def _integrate_transition(
        self,
        before: Observation,
        after: Observation,
        action: ActionRequest,
    ) -> None:
        metric = self._metrics[self._level_index]
        before_rows = _board(before)
        after_rows = _board(after)
        old_position = self._last_player_position
        old_color = self._last_player_color
        displacement = self._observe_displacement(before_rows, after_rows, action)
        if action.name in MOVE_ACTIONS and displacement is not None:
            old_position, new_position, color = displacement
            vector = (new_position[0] - old_position[0], new_position[1] - old_position[1])
            self._player_position = new_position
            self._player_color = color
            learned = self._movement.get(action.name)
            if learned is None:
                self._movement[action.name] = vector
            entered_visible_candidate = _cell(before_rows, new_position) not in {0, color}
            if not self._interaction_used and (
                self._last_target == new_position or entered_visible_candidate
            ):
                self._pending_interaction = True
        elif action.name in MOVE_ACTIONS and old_position is not None:
            self._player_position = old_position
            self._player_color = old_color
            learned_vector = self._movement.get(action.name)
            target = _add(old_position, learned_vector) if learned_vector is not None else None
            if target is not None and self._inside(target, before):
                color = _cell(before_rows, target)
                role = _role_signature(before_rows, target)
                if role is not None:
                    self._blocked_history[target] = role
                if color != 0:
                    if sum(row.count(color) for row in before_rows[1:]) >= 3:
                        self._wall_colors.add(color)
                    else:
                        self._blocked.add(target)
                metric.access_prediction_errors += 1
                signature = (action.name, target)
                self._failed_probe_signatures[signature] += 1
                if self._failed_probe_signatures[signature] > 1:
                    metric.redundant_probes += 1

        before_resource = _resource(before)
        after_resource = _resource(after)
        resource_delta = after_resource - before_resource
        if action.name is not ActionName.RESET:
            predicted_resource = self._resource_delta_by_action.get(action.name)
            if predicted_resource is None:
                self._resource_delta_by_action[action.name] = resource_delta

        facts = self._transition_facts(
            action=action,
            displacement=displacement,
            resource_delta=resource_delta,
            before=before,
            after=after,
        )
        if facts.other_object_motion is not None:
            metric.other_object_effects_observed += 1
        if not facts.observed.topology_changes.is_unknown:
            metric.topology_changes_confirmed += 1
        self._update_dynamic_residuals(before, after, action, facts)
        learning: LearningReceipt | None = None
        prediction = self._last_prediction
        if self._learner is not None and prediction is not None:
            try:
                learning = self._learner.observe_consequence(
                    prediction.prediction_id,
                    facts.observed,
                    source_event_ids=(facts.source_event_id,),
                    context_key=prediction.context.context_key,
                    observed_step=self._step,
                )
                self._process_learning(prediction, learning, facts, action)
            except MechanicsError:
                metric.hazard_prediction_errors += 1

        causal_digest, causal_complete = self._record_causal_receipt(
            before, after, action, displacement, resource_delta
        )
        if prediction is not None and self._last_before_ref is not None:
            learning_digest = _digest(
                {"status": "missing"} if learning is None else learning.to_dict()
            )
            self._action_links.append(
                _ActionLink(
                    step=self._step,
                    level_index=self._level_index,
                    action={
                        "name": action.name.value,
                        "coordinate": (
                            None
                            if action.coordinate is None
                            else {
                                "x": action.coordinate.x,
                                "y": action.coordinate.y,
                            }
                        ),
                    },
                    prediction_id=prediction.prediction_id,
                    prediction_digest=_digest(prediction.to_dict()),
                    before_ref=self._last_before_ref,
                    after_ref=_observation_ref(after),
                    learning_digest=learning_digest,
                    causal_receipt_digest=causal_digest,
                    complete=causal_complete and learning is not None,
                )
            )
        for y, row in enumerate(after_rows):
            for x, value in enumerate(row):
                if (x, y) in self._blocked and value != _cell(before_rows, (x, y)):
                    self._blocked.discard((x, y))
        if after.state is GameStateName.GAME_OVER:
            metric.hazard_prediction_errors += 1
        if self._learner is not None:
            metric.unresolved_ledger_count = max(
                metric.unresolved_ledger_count,
                len(self._learner.open_residuals)
                + (0 if self._clef_enabled else len(self._recolor_counts)),
            )
            metric.active_ledger_pressure = max(
                metric.active_ledger_pressure,
                len(self._learner.ledger.active()) + len(self._learner.open_residuals),
            )

    def _transition_facts(
        self,
        *,
        action: ActionRequest,
        displacement: tuple[Point, Point, int] | None,
        resource_delta: int,
        before: Observation,
        after: Observation,
    ) -> _TransitionFacts:
        """Factor public before/after evidence without filling unreadable channels."""

        before_rows = _board(before)
        after_rows = _board(after)
        changed = tuple(
            (x, y)
            for y, row in enumerate(before_rows)
            for x, value in enumerate(row)
            if value != after_rows[y][x]
        )
        accounted: set[Point] = set()
        controlled = ChannelValue.unknown()
        if action.name is not ActionName.RESET:
            if displacement is not None:
                old, new, _ = displacement
                accounted.update((old, new))
                controlled = ChannelValue.known(
                    DisplacementEffect("controllable-object", new[0] - old[0], new[1] - old[1])
                )
            elif action.name not in MOVE_ACTIONS or self._last_player_position is not None:
                controlled = ChannelValue.known_empty()

        other_motion = self._observe_other_object_motion(
            before_rows,
            after_rows,
            changed=changed,
            displacement=displacement,
        )
        if other_motion is not None:
            subject, vector, old, new = other_motion
            accounted.update((old, new))
            other_objects = ChannelValue.known(
                ObjectEffect(
                    subject,
                    ObjectOperation.MOVED,
                    f"dx={vector[0]},dy={vector[1]}",
                )
            )
        else:
            non_hud_unaccounted = {
                point for point in changed if point[1] > 0 and point not in accounted
            }
            other_objects = (
                ChannelValue.known_empty() if not non_hud_unaccounted else ChannelValue.unknown()
            )

        before_actions = set(before.available_actions)
        after_actions = set(after.available_actions)
        legal_effects = tuple(
            LegalActionEffect(candidate, candidate in after_actions)
            for candidate in sorted(before_actions ^ after_actions, key=lambda item: item.value)
        )
        legal = ChannelValue.known(*legal_effects)

        topology = ChannelValue.unknown()
        if displacement is not None and displacement[1] in self._blocked_history:
            destination = displacement[1]
            topology = ChannelValue.known(
                TopologyEffect(
                    relation="observed-traversability",
                    operation=TopologyOperation.OPENED,
                    source=self._blocked_history[destination],
                )
            )

        recolors = tuple(
            point
            for point in changed
            if point[1] > 0
            and point not in accounted
            and _cell(before_rows, point) != 0
            and _cell(after_rows, point) != 0
        )
        visible_signature = None
        if recolors and len(recolors) <= 4:
            visible_signature = _digest(
                [(point, _cell(before_rows, point), _cell(after_rows, point)) for point in recolors]
            )
            status = ChannelValue.known(StatusEffect("visible-region", visible_signature))
        elif not {point for point in changed if point[1] > 0 and point not in accounted}:
            status = ChannelValue.known_empty()
        else:
            status = ChannelValue.unknown()

        context_target = self._last_context_target
        if context_target is None:
            context_target = self._last_target
        target_role = _role_signature(before_rows, context_target)
        context = (
            self._last_prediction.context
            if self._last_prediction is not None
            else self._context_for(before, context_target)
        )
        observed = ConsequenceVector(
            controlled_displacement=controlled,
            other_object_effects=other_objects,
            resource_changes=(
                ChannelValue.unknown()
                if action.name is ActionName.RESET
                else _quantity_value("visible-hud", resource_delta)
            ),
            inventory_changes=ChannelValue.unknown(),
            legal_action_changes=legal,
            topology_changes=topology,
            status_animation_changes=status,
            score_progress_changes=_score_value(
                "levels-completed", after.levels_completed - before.levels_completed
            ),
            terminal_changes=(
                ChannelValue.known(TerminalEffect(after.state))
                if before.state is not after.state or after.full_reset
                else ChannelValue.known_empty()
            ),
            delayed_effects=ChannelValue.unknown(),
        )
        return _TransitionFacts(
            context=context,
            observed=observed,
            controlled_displacement=displacement,
            other_object_motion=(
                None if other_motion is None else (other_motion[0], other_motion[1])
            ),
            target=context_target,
            target_role=target_role,
            changed_points=changed,
            visible_effect_signature=visible_signature,
            source_event_id=f"observation:{self._step}",
        )

    def _observe_other_object_motion(
        self,
        before: tuple[tuple[int, ...], ...],
        after: tuple[tuple[int, ...], ...],
        *,
        changed: tuple[Point, ...],
        displacement: tuple[Point, Point, int] | None,
    ) -> tuple[str, Point, Point, Point] | None:
        controlled = None if displacement is None else (displacement[0], displacement[1])
        candidates: list[tuple[str, Point, Point, Point]] = []
        removed_by_color: dict[int, list[Point]] = defaultdict(list)
        created_by_color: dict[int, list[Point]] = defaultdict(list)
        for point in changed:
            if point[1] == 0:
                continue
            old_color = _cell(before, point)
            new_color = _cell(after, point)
            if old_color != 0:
                removed_by_color[old_color].append(point)
            if new_color != 0:
                created_by_color[new_color].append(point)
        for color in sorted(removed_by_color.keys() & created_by_color.keys()):
            removed = removed_by_color[color]
            created = created_by_color[color]
            if len(removed) != 1 or len(created) != 1:
                continue
            old = removed[0]
            new = created[0]
            if controlled == (old, new):
                continue
            vector = new[0] - old[0], new[1] - old[1]
            if vector not in CARDINALS:
                continue
            role = _role_signature(before, old)
            if role is not None:
                candidates.append((role, vector, old, new))
        return candidates[0] if len(candidates) == 1 else None

    def _process_learning(
        self,
        prediction: MechanicPredictionReceipt,
        learning: LearningReceipt,
        facts: _TransitionFacts,
        action: ActionRequest,
    ) -> None:
        if self._learner is None:
            return
        metric = self._metrics[self._level_index]
        consequential = learning.residual.consequential
        if consequential:
            metric.residuals_observed += 1
            metric.residuals_localized += 1
        metric.passive_confirmations += len(learning.passive_support_receipt_ids)

        mismatches = tuple(
            item
            for item in learning.residual.channels
            if item.kind not in {ResidualKind.MATCH, ResidualKind.UNREADABLE_OBSERVATION}
        )
        for item in mismatches:
            metric.prediction_errors_by_channel[item.channel.value] += 1
        metric.movement_prediction_errors += sum(
            item.channel is ConsequenceChannel.CONTROLLED_DISPLACEMENT for item in mismatches
        )
        metric.resource_prediction_errors += sum(
            item.channel is ConsequenceChannel.RESOURCE_CHANGES for item in mismatches
        )
        metric.access_prediction_errors += sum(
            item.channel
            in {ConsequenceChannel.LEGAL_ACTION_CHANGES, ConsequenceChannel.TOPOLOGY_CHANGES}
            for item in mismatches
        )

        matched_channels_by_ref: dict[MechanicRef, set[ConsequenceChannel]] = {}
        for item in learning.residual.channels:
            if item.kind is not ResidualKind.MATCH:
                continue
            for ref in item.contributor_refs:
                matched_channels_by_ref.setdefault(ref, set()).add(item.channel)

        for ref, channels in matched_channels_by_ref.items():
            if ref in self._retained_refs and ref not in self._transferred_refs:
                try:
                    self._learner.confirm_transfer(
                        ref,
                        channels=channels,
                        source_event_ids=(facts.source_event_id,),
                        context_key=prediction.context.context_key,
                        observed_step=self._step,
                        receipt_id=_digest(
                            {
                                "kind": "cross-level-transfer",
                                "ref": ref.to_dict(),
                                "event": facts.source_event_id,
                                "channels": sorted(item.value for item in channels),
                            }
                        ),
                    )
                    self._transferred_refs.add(ref)
                    metric.transfer_confirmations += 1
                    metric.observed_retained_matches += 1
                    metric.base_mechanics_retained = True
                except MechanicsError:
                    metric.hazard_prediction_errors += 1
            if ref in self._repairs:
                metric.local_repairs_confirmed += 1
                self._repairs.pop(ref, None)
            self._resolve_origin_for_ref(ref)

        contributed = {
            ref
            for channel in CHANNEL_ORDER
            for ref in prediction.composition.contributors_for(channel)
        }
        for ref in tuple(sorted(contributed & set(self._repairs))):
            tracked = self._repairs.get(ref)
            if tracked is None:
                continue
            channel_residual = learning.residual.for_channel(tracked.channel)
            if not channel_residual.consequential:
                continue
            tracked.failures += 1
            metric.local_repair_failures += 1
            try:
                self._learner.record_local_repair_failure(tracked.residual_id)
                if tracked.failures >= 2:
                    reopened = self._learner.reopen_implicated(
                        tracked.residual_id,
                        source_event_ids=(facts.source_event_id,),
                        observed_step=self._step,
                    )
                    metric.base_reopenings += len(reopened)
                    self._learner.ledger.reject(
                        ref,
                        occurred_step=self._step,
                        caused_by_event_ids=(facts.source_event_id,),
                        note="bounded local repair failed twice",
                    )
                    self._repairs.pop(ref, None)
            except MechanicsError:
                metric.hazard_prediction_errors += 1

        initial_bundle = self._open_initial_bundle(action.name, consequential, facts)
        for item in consequential:
            if item.kind is ResidualKind.UNKNOWN_PREDICTION and not item.observed.is_unknown:
                initial_ref = initial_bundle.get(item.channel)
                if initial_ref is None:
                    initial_ref = self._initial_ref_for(
                        action.name, item.channel, item.observed, facts
                    )
                if initial_ref is not None:
                    self._associate_origin(initial_ref, learning.residual.residual_id)
                continue
            if not item.contributor_refs:
                continue
            if any(ref in self._repairs for ref in item.contributor_refs):
                continue
            repair_ref = self._open_local_repair(action.name, item, facts)
            if repair_ref is not None:
                self._associate_origin(repair_ref, learning.residual.residual_id)
                self._repairs[repair_ref] = _TrackedRepair(
                    learning.residual.residual_id, repair_ref, item.channel
                )
                metric.local_repair_candidates_opened += 1

        self._update_delayed_evidence(action, facts)

    def _open_initial_bundle(
        self,
        action: ActionName,
        residuals: tuple[ChannelResidual, ...],
        facts: _TransitionFacts,
    ) -> dict[ConsequenceChannel, MechanicRef]:
        """Open one game baseline for jointly observed, compatible channels."""

        if self._learner is None:
            return {}
        selected: dict[ConsequenceChannel, ChannelValue] = {}
        for residual in residuals:
            channel = residual.channel
            observed = residual.observed
            if (
                residual.kind is not ResidualKind.UNKNOWN_PREDICTION
                or observed.is_unknown
                or (action, channel) in self._baseline_refs
            ):
                continue
            if channel in {
                ConsequenceChannel.INVENTORY_CHANGES,
                ConsequenceChannel.TOPOLOGY_CHANGES,
                ConsequenceChannel.STATUS_ANIMATION_CHANGES,
                ConsequenceChannel.DELAYED_EFFECTS,
            }:
                continue
            if (
                channel is ConsequenceChannel.CONTROLLED_DISPLACEMENT
                and action in MOVE_ACTIONS
                and observed.is_known_empty
            ):
                continue
            if channel is ConsequenceChannel.OTHER_OBJECT_EFFECTS and not observed.is_known_empty:
                continue
            selected[channel] = observed
        if not selected:
            return {}
        consequence = ConsequenceVector.unknown()
        for channel, value in selected.items():
            consequence = consequence.with_channel(channel, value)
        identifier = _digest(
            {
                "action": action.value,
                "channels": sorted(channel.value for channel in selected),
                "step": self._step,
            }
        ).removeprefix("sha256:")[:12]
        try:
            view = self._learner.ledger.open(
                action=action,
                scope=MechanicScope(ScopeCeiling.GAME, game_scope=self._game_scope),
                consequence=consequence,
                composition_mode=CompositionMode.BASE,
                created_step=self._step,
                created_from_event_ids=(facts.source_event_id,),
                provenance=EvidenceProvenance.OBSERVED_THIS_GAME,
                mechanic_id=f"observed-baseline-{action.value.casefold()}-{identifier}",
                priority=70,
                note="joint observation-derived action baseline",
            )
        except MechanicsError:
            self._metrics[self._level_index].hazard_prediction_errors += 1
            return {}
        for channel in selected:
            self._baseline_refs[(action, channel)] = view.ref
        if ConsequenceChannel.CONTROLLED_DISPLACEMENT in selected:
            self._movement_refs.add(action)
        if ConsequenceChannel.RESOURCE_CHANGES in selected:
            self._resource_refs.add(action)
        return {channel: view.ref for channel in selected}

    def _associate_origin(self, ref: MechanicRef, residual_id: str) -> None:
        self._origin_residuals[ref] = (residual_id, self._level_index)
        self._pending_residual_refs.setdefault(residual_id, set()).add(ref)

    def _resolve_origin_for_ref(self, ref: MechanicRef) -> None:
        if self._learner is None:
            return
        origin = self._origin_residuals.pop(ref, None)
        if origin is None:
            return
        residual_id, origin_level = origin
        pending = self._pending_residual_refs.get(residual_id)
        if pending is None:
            return
        pending.discard(ref)
        if pending:
            return
        self._pending_residual_refs.pop(residual_id, None)
        self._learner.resolve_residual(residual_id)
        self._metrics[origin_level].residuals_resolved += 1

    def _initial_ref_for(
        self,
        action: ActionName,
        channel: ConsequenceChannel,
        observed: ChannelValue,
        facts: _TransitionFacts,
    ) -> MechanicRef | None:
        existing = self._baseline_refs.get((action, channel))
        if existing is not None:
            return existing
        if channel in {
            ConsequenceChannel.INVENTORY_CHANGES,
            ConsequenceChannel.DELAYED_EFFECTS,
        }:
            return None
        if channel is ConsequenceChannel.CONTROLLED_DISPLACEMENT:
            if action in self._movement_refs:
                return self._baseline_refs.get((action, channel))
            if action in MOVE_ACTIONS and observed.is_known_empty:
                if facts.target_role is None:
                    return None
                return self._open_channel_mechanic(
                    action,
                    channel,
                    observed,
                    CompositionMode.GATING,
                    facts,
                    level_local=True,
                    note="observed context-specific blocked displacement",
                )
        if channel is ConsequenceChannel.RESOURCE_CHANGES and action in self._resource_refs:
            return self._baseline_refs.get((action, channel))
        local = (
            channel
            in {
                ConsequenceChannel.OTHER_OBJECT_EFFECTS,
                ConsequenceChannel.TOPOLOGY_CHANGES,
                ConsequenceChannel.STATUS_ANIMATION_CHANGES,
            }
            and not observed.is_known_empty
        )
        mode = CompositionMode.CONDITIONAL if local else CompositionMode.BASE
        ref = self._open_channel_mechanic(
            action,
            channel,
            observed,
            mode,
            facts,
            level_local=local,
            note="observation-derived initial channel assertion",
        )
        if ref is not None and mode is CompositionMode.BASE:
            self._baseline_refs[(action, channel)] = ref
        return ref

    def _open_local_repair(
        self,
        action: ActionName,
        residual: ChannelResidual,
        facts: _TransitionFacts,
    ) -> MechanicRef | None:
        channel = residual.channel
        predicted = residual.predicted
        observed = residual.observed
        contributor_refs = residual.contributor_refs
        key = _digest(
            {
                "action": action.value,
                "channel": channel.value,
                "context": facts.context.to_dict(),
                "predicted": predicted.to_dict(),
                "observed": observed.to_dict(),
            }
        )
        existing = self._repair_keys.get(key)
        if existing is not None:
            return None
        mode = CompositionMode.CONDITIONAL
        value = observed
        if channel is ConsequenceChannel.RESOURCE_CHANGES:
            predicted_delta = _quantity_delta(predicted)
            observed_delta = _quantity_delta(observed)
            if predicted_delta is not None and observed_delta is not None:
                correction = observed_delta - predicted_delta
                value = _quantity_value("visible-hud", correction)
                mode = (
                    CompositionMode.ADDITIVE
                    if not facts.context.object_roles
                    else CompositionMode.CONDITIONAL
                )
        elif channel is ConsequenceChannel.CONTROLLED_DISPLACEMENT:
            if observed.is_known_empty:
                mode = CompositionMode.GATING
            elif any(self._mode_for_ref(ref) is CompositionMode.GATING for ref in contributor_refs):
                mode = CompositionMode.OVERRIDE
            else:
                predicted_move = self._single_displacement(predicted)
                observed_move = self._single_displacement(observed)
                if predicted_move is not None and observed_move is not None:
                    value = ChannelValue.known(
                        DisplacementEffect(
                            observed_move.subject,
                            observed_move.dx - predicted_move.dx,
                            observed_move.dy - predicted_move.dy,
                        )
                    )
        elif not predicted.is_known_empty:
            mode = CompositionMode.OVERRIDE
        ref = self._open_channel_mechanic(
            action,
            channel,
            value,
            mode,
            facts,
            level_local=True,
            note="narrow observation-derived repair candidate",
        )
        if ref is not None:
            self._repair_keys[key] = ref
        return ref

    @staticmethod
    def _single_displacement(value: ChannelValue) -> DisplacementEffect | None:
        if len(value.effects) != 1 or not isinstance(value.effects[0], DisplacementEffect):
            return None
        return value.effects[0]

    def _mode_for_ref(self, ref: MechanicRef) -> CompositionMode | None:
        if self._learner is None:
            return None
        try:
            return self._learner.ledger.get(ref).version.composition_mode
        except MechanicsError:
            return None

    def _open_channel_mechanic(
        self,
        action: ActionName,
        channel: ConsequenceChannel,
        value: ChannelValue,
        mode: CompositionMode,
        facts: _TransitionFacts,
        *,
        level_local: bool,
        note: str,
    ) -> MechanicRef | None:
        if self._learner is None or value.is_unknown:
            return None
        scope = (
            MechanicScope(
                ScopeCeiling.LEVEL,
                game_scope=self._game_scope,
                level_scope=facts.context.level_scope,
                object_roles=facts.context.object_roles,
            )
            if level_local
            else MechanicScope(ScopeCeiling.GAME, game_scope=self._game_scope)
        )
        identifier = _digest(
            {
                "action": action.value,
                "channel": channel.value,
                "mode": mode.value,
                "scope": scope.to_dict(),
                "value": value.to_dict(),
                "step": self._step,
            }
        ).removeprefix("sha256:")[:16]
        try:
            view = self._learner.ledger.open(
                action=action,
                scope=scope,
                consequence=ConsequenceVector.unknown().with_channel(channel, value),
                composition_mode=mode,
                created_step=self._step,
                created_from_event_ids=(facts.source_event_id,),
                provenance=EvidenceProvenance.OBSERVED_THIS_GAME,
                mechanic_id=f"observed-{channel.value}-{identifier}",
                priority=95 if level_local else 70,
                note=note,
            )
            return view.ref
        except MechanicsError:
            self._metrics[self._level_index].hazard_prediction_errors += 1
            return None

    def _update_delayed_evidence(self, action: ActionRequest, facts: _TransitionFacts) -> None:
        signature = facts.visible_effect_signature
        if signature is not None and not any(
            point in self._ignored_dynamic for point in facts.changed_points
        ):
            for prior in self._history:
                lag = self._step - prior.step
                if not 1 <= lag <= 3:
                    continue
                key = (prior.action.value, signature, lag)
                evidence = self._delayed_evidence.setdefault(key, set())
                evidence.add(prior.source_event_id)
                competing = {
                    candidate[0] for candidate in self._delayed_evidence if candidate[1:] == key[1:]
                }
                if len(evidence) < 2 or len(competing) != 1 or key in self._delayed_refs:
                    continue
                delayed = ChannelValue.known(
                    DelayedEffect(
                        delay_steps=lag,
                        target_channel=ConsequenceChannel.STATUS_ANIMATION_CHANGES,
                        signature=signature,
                    )
                )
                ref = self._open_channel_mechanic(
                    prior.action,
                    ConsequenceChannel.DELAYED_EFFECTS,
                    delayed,
                    CompositionMode.DELAYED,
                    facts,
                    level_local=True,
                    note="repeated fixed-lag visible association",
                )
                if ref is not None:
                    self._delayed_refs[key] = ref
                    self._metrics[self._level_index].delayed_candidates_confirmed += 1
        self._history.append(
            _HistoryFact(
                step=self._step,
                action=action.name,
                context=facts.context,
                source_event_id=facts.source_event_id,
                visible_effect_signature=facts.visible_effect_signature,
            )
        )

    def _observe_displacement(
        self,
        before: tuple[tuple[int, ...], ...],
        after: tuple[tuple[int, ...], ...],
        action: ActionRequest,
    ) -> tuple[Point, Point, int] | None:
        if action.name not in MOVE_ACTIONS:
            return None
        expected = self._movement.get(action.name)
        removed_by_color: dict[int, list[Point]] = defaultdict(list)
        created_by_color: dict[int, list[Point]] = defaultdict(list)
        for y, row in enumerate(before):
            if y == 0:
                continue
            for x, old_color in enumerate(row):
                new_color = after[y][x]
                if old_color == new_color:
                    continue
                point = (x, y)
                if old_color != 0:
                    removed_by_color[old_color].append(point)
                if new_color != 0:
                    created_by_color[new_color].append(point)
        candidates: list[tuple[Point, Point, int]] = []
        for color in sorted(removed_by_color.keys() & created_by_color.keys()):
            for old in removed_by_color[color]:
                for new in created_by_color[color]:
                    vector = (new[0] - old[0], new[1] - old[1])
                    if vector in CARDINALS and (expected is None or vector == expected):
                        candidates.append((old, new, color))
        if self._last_player_color is not None:
            matching = [item for item in candidates if item[2] == self._last_player_color]
            if len(matching) == 1:
                return matching[0]
        return candidates[0] if len(candidates) == 1 else None

    def _open_movement_mechanic(
        self,
        action: ActionName,
        vector: Point,
        *,
        source: str,
        provenance: EvidenceProvenance,
    ) -> MechanicRef | None:
        if self._learner is None or action in self._movement_refs:
            return self._baseline_refs.get((action, ConsequenceChannel.CONTROLLED_DISPLACEMENT))
        consequence = ConsequenceVector(
            controlled_displacement=ChannelValue.known(
                DisplacementEffect("controllable-object", vector[0], vector[1])
            )
        )
        try:
            view = self._learner.ledger.open(
                action=action,
                scope=MechanicScope(ScopeCeiling.GAME, game_scope=self._game_scope),
                consequence=consequence,
                composition_mode=CompositionMode.BASE,
                created_step=self._step,
                created_from_event_ids=(source,),
                provenance=provenance,
                mechanic_id=f"movement-{action.value.casefold()}",
                priority=90,
                note="observation-derived cardinal displacement",
            )
            self._movement_refs.add(action)
            self._baseline_refs[(action, ConsequenceChannel.CONTROLLED_DISPLACEMENT)] = view.ref
            return view.ref
        except MechanicsError:
            self._metrics[self._level_index].hazard_prediction_errors += 1
            return None

    def _open_resource_mechanic(self, action: ActionName, delta: int) -> MechanicRef | None:
        if self._learner is None:
            return None
        if action in self._resource_refs:
            return self._baseline_refs.get((action, ConsequenceChannel.RESOURCE_CHANGES))
        try:
            view = self._learner.ledger.open(
                action=action,
                scope=MechanicScope(ScopeCeiling.GAME, game_scope=self._game_scope),
                consequence=ConsequenceVector(
                    resource_changes=_quantity_value("visible-hud", delta)
                ),
                composition_mode=CompositionMode.BASE,
                created_step=self._step,
                created_from_event_ids=(f"visible-hud-delta:{self._step}",),
                provenance=EvidenceProvenance.OBSERVED_THIS_GAME,
                mechanic_id=f"resource-{action.value.casefold()}",
                priority=80,
                note="observation-derived visible resource baseline",
            )
            self._resource_refs.add(action)
            self._baseline_refs[(action, ConsequenceChannel.RESOURCE_CHANGES)] = view.ref
            return view.ref
        except MechanicsError:
            self._metrics[self._level_index].hazard_prediction_errors += 1
            return None

    def _update_dynamic_residuals(
        self,
        before: Observation,
        after: Observation,
        action: ActionRequest,
        facts: _TransitionFacts,
    ) -> None:
        rows_before = _board(before)
        rows_after = _board(after)
        changed_recolors: list[Point] = []
        for point in facts.changed_points:
            if point[1] == 0:
                continue
            old = _cell(rows_before, point)
            new = _cell(rows_after, point)
            if old != 0 and new != 0:
                self._recolor_counts[point] += 1
                changed_recolors.append(point)
        if not changed_recolors:
            return
        metric = self._metrics[self._level_index]
        if not self._clef_enabled:
            metric.residuals_observed += len(changed_recolors)
            return
        declaration = LayerDeclaration(
            declaration_id=f"clef-action-effects-l{self._level_index + 1}",
            layer=LogicalLayer.ACTION_EFFECTS,
            available_fields=("frame.cells", "official.state", "official.levels_completed"),
            aperture="one before/after public observation",
            noise_thresholds=(
                ReadabilityThreshold(EvidenceFamily.FRAME_CELLS, 1),
                ReadabilityThreshold(EvidenceFamily.TEMPORAL_TRACKING, 2),
            ),
            extraction_method="exact recurring fixed-coordinate recolor",
            reader_identity="build003-observation-only-policy",
            readability_wall=ReadabilityWall(max_detail_units=3, used_detail_units=1),
            dynamic_context=DynamicClaimContext(
                window=ActionWindow(max(0, self._step - 1), max(1, self._step)),
                intervention=action,
                assumed_scope=StateScope.LEVEL,
                observation_return_path=("Observation.frames[-1].cells",),
            ),
        )
        for point in changed_recolors:
            relevant = point in {facts.target, self._last_player_position, self._player_position}
            recurring = self._recolor_counts[point] >= 2
            assessment = LayerAssessment(
                declaration=declaration,
                readings=(
                    EvidenceReading(
                        EvidenceFamily.FRAME_CELLS,
                        f"coordinate:{point[0]},{point[1]}",
                        1,
                        (f"observation:{self._step}",),
                    ),
                    EvidenceReading(
                        EvidenceFamily.TEMPORAL_TRACKING,
                        f"coordinate:{point[0]},{point[1]}",
                        self._recolor_counts[point],
                        (f"observation:{self._step}",),
                    ),
                ),
                validity_gates=(
                    ValidityGate(
                        "fixed-coordinate recurrence or action-local target",
                        recurring or relevant,
                        evidence_event_ids=(f"observation:{self._step}",),
                    ),
                ),
            )
            decision = assess_residual(
                assessment,
                already_explained=recurring and not relevant,
                changes_prediction=relevant,
                changes_action_selection=relevant,
                additional_detail_cost=1,
                expected_decision_value=2 if relevant else 0,
            )
            metric.residuals_observed += 1
            metric.residuals_localized += 1
            if decision.disposition is ResidualDisposition.PROMOTE:
                metric.clef_promotions += 1
                repair_key = _digest(
                    {
                        "kind": "clef-promoted-status",
                        "action": action.name.value,
                        "role": facts.target_role,
                        "status": facts.observed.status_animation_changes.to_dict(),
                    }
                )
                if repair_key not in self._repair_keys:
                    ref = self._open_channel_mechanic(
                        action.name,
                        ConsequenceChannel.STATUS_ANIMATION_CHANGES,
                        facts.observed.status_animation_changes,
                        CompositionMode.CONDITIONAL,
                        facts,
                        level_local=True,
                        note="CLEF-promoted action-relevant visible status",
                    )
                    if ref is not None:
                        self._repair_keys[repair_key] = ref
            elif decision.disposition is ResidualDisposition.PARK:
                metric.clef_parks += 1
            else:
                metric.clef_stops += 1
                self._ignored_dynamic.add(point)
                metric.residuals_resolved += 1

    def _record_causal_receipt(
        self,
        before: Observation,
        after: Observation,
        action: ActionRequest,
        displacement: tuple[Point, Point, int] | None,
        resource_delta: int,
    ) -> tuple[str, bool]:
        before_grid = normalize_grid(_board(before))
        after_grid = normalize_grid(_board(after))
        delta = measure_delta(
            before_grid,
            after_grid,
            before_metadata={
                "state": before.state.value,
                "levels_completed": before.levels_completed,
            },
            after_metadata={
                "state": after.state.value,
                "levels_completed": after.levels_completed,
            },
        )
        recognized: list[FactoredEffect] = []
        if displacement is not None:
            old, new, _color = displacement
            recognized.append(
                FactoredEffect(
                    EffectChannel.CONTROLLABLE_OBJECT_DISPLACEMENT,
                    EffectKnowledge.KNOWN,
                    {"dx": new[0] - old[0], "dy": new[1] - old[1]},
                    (f"frame:{after_grid.digest}",),
                )
            )
        if action.name is not ActionName.RESET:
            recognized.append(
                FactoredEffect(
                    EffectChannel.RESOURCE_HUD_CHANGE,
                    EffectKnowledge.KNOWN,
                    {"delta": resource_delta},
                    (f"frame:{after_grid.digest}",),
                )
            )
        observed = extract_observed_effects(
            before,
            after,
            delta,
            recognized_effects=tuple(recognized),
            evidence_refs=(f"frame:{after_grid.digest}",),
        )
        expected: list[FactoredEffect] = []
        if action.name in self._movement:
            vector = self._movement[action.name]
            expected.append(
                FactoredEffect(
                    EffectChannel.CONTROLLABLE_OBJECT_DISPLACEMENT,
                    EffectKnowledge.KNOWN,
                    {"dx": vector[0], "dy": vector[1]},
                )
            )
        resource_prediction = self._resource_delta_by_action.get(action.name)
        if resource_prediction is not None:
            expected.append(
                FactoredEffect(
                    EffectChannel.RESOURCE_HUD_CHANGE,
                    EffectKnowledge.KNOWN,
                    {"delta": resource_prediction},
                )
            )
        predicted = EffectVector.from_effects(tuple(expected))
        comparison = compare_effect_vectors(predicted, observed)
        resource = _resource(after)
        risk = (
            RiskLevel.TERMINAL
            if after.state is GameStateName.GAME_OVER
            else RiskLevel.ELEVATED
            if resource <= 4
            else RiskLevel.LOW
        )
        receipt_id = _digest(
            {
                "step": self._step,
                "before": str(before_grid.digest),
                "action": action.name.value,
                "after": str(after_grid.digest),
            }
        )
        receipt = CausalActionReceipt(
            receipt_id=receipt_id,
            game_scope_id=self._game_scope,
            level_scope_id=self._context.level_scope,
            step_index=self._step,
            before_state_ref=str(before_grid.digest),
            chosen_action_and_coordinates=action,
            legal_actions_before=before.available_actions,
            predicted_effects=predicted,
            observed_effects=observed,
            explained_effects=comparison.explained_effects,
            residual_effects=comparison.residual_effects,
            objects_or_regions_implicated=(
                ()
                if self._last_context_target is None
                else (f"cell:{self._last_context_target[0]},{self._last_context_target[1]}",)
            ),
            active_hypotheses_used=(
                ()
                if self._learner is None
                else tuple(
                    f"{view.ref.mechanic_id}@{view.ref.version}"
                    for view in self._learner.ledger.active()
                )
            ),
            probe_or_progress_reason=self._last_reason,
            resource_and_failure_risk=ResourceFailureRisk(
                risk,
                f"visible five-bit HUD value {resource}",
                (f"frame:{after_grid.digest}",),
            ),
            terminal_state=after.state,
        )
        metric = self._metrics[self._level_index]
        metric.receipt_count += 1
        metric.complete_receipt_count += int(receipt.complete)
        digest = _digest(receipt.to_dict())
        self._receipt_digests.append(digest)
        return digest, receipt.complete


__all__ = ["SUPPORTED_VARIANTS", "ObservationOnlyVariantPolicy"]
