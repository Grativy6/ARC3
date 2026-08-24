"""Observation-only Build 003 ablation policies.

This module is imported inside the policy subprocess after evaluator modules
have been denied.  It deliberately depends only on the public observation
contract and production BLA/CLEF primitives.  Family names, seeds, rules,
transition truth, and oracle plans never enter this process.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter, deque
from dataclasses import asdict, dataclass

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
    ChannelValue,
    CompositionMode,
    ConsequenceChannel,
    ConsequenceVector,
    DisplacementEffect,
    EvidenceProvenance,
    MechanicalLearner,
    MechanicContext,
    MechanicLedgerBudget,
    MechanicScope,
    MechanicsError,
    ProbeCandidate,
    QuantityEffect,
    ScopeCeiling,
    ScoreProgressEffect,
    TerminalEffect,
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
    residuals_observed: int = 0
    residuals_localized: int = 0
    residuals_resolved: int = 0
    base_mechanics_retained: bool = False
    erroneous_global_reopenings: int = 0
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
        self._resource_refs: set[tuple[int, ActionName]] = set()
        self._metrics = [_LevelMetrics() for _ in range(10)]
        self._previous: Observation | None = None
        self._last_action: ActionRequest | None = None
        self._last_prediction_id: str | None = None
        self._last_reason = ""
        self._last_target: Point | None = None
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
        self._resource_delta_by_action: dict[tuple[int, ActionName], int] = {}
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
        self._visited.clear()
        self._blocked.clear()
        self._wall_colors.clear()
        self._pending_interaction = False
        self._interaction_used = False
        self._probe_counts.clear()
        self._failed_probe_signatures.clear()
        self._recolor_counts.clear()
        self._ignored_dynamic.clear()
        if not self._persistent:
            self._movement.clear()
            self._movement_refs.clear()
            self._resource_refs.clear()
            self._resource_delta_by_action.clear()
            self._learner = self._new_learner()
        elif self._learner is None:
            self._learner = self._new_learner()
        else:
            try:
                boundary = self._learner.start_level(self._context.level_scope)
                self._metrics[index].base_mechanics_retained = bool(
                    boundary.retained_refs and self._movement
                )
            except MechanicsError:
                # A bounded ledger can be replaced after its failure is counted;
                # learned action semantics remain observation-derived policy state.
                self._metrics[index].hazard_prediction_errors += 1
                self._learner = self._new_learner()
        if reset and self._persistent and self._movement:
            self._metrics[index].base_mechanics_retained = True
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
        self._last_prediction_id = None
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
        try:
            prediction = self._learner.predict(action, self._context, emitted_step=self._step)
            self._last_prediction_id = prediction.prediction_id
        except MechanicsError:
            metric.hazard_prediction_errors += 1
            self._learner = self._new_learner()
            prediction = self._learner.predict(action, self._context, emitted_step=self._step)
            self._last_prediction_id = prediction.prediction_id
        self._last_action = action
        self._last_reason = reason
        self._last_target = target
        self._last_player_position = self._player_position
        self._last_player_color = self._player_color
        self._step += 1

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
                return ActionRequest(ActionName.ACTION5), "probe-local-interaction", None
        for action, vector in sorted(self._movement.items(), key=lambda item: item[0].value):
            if self._player_position is not None and self._inside(
                _add(self._player_position, vector), observation
            ):
                return ActionRequest(action), "probe-reachability", None
        return ActionRequest(ActionName.ACTION5), "probe-no-reachable-candidate", None

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
                self._open_movement_mechanic(
                    action.name,
                    vector,
                    source=f"observed-displacement:{self._step}",
                    provenance=EvidenceProvenance.OBSERVED_THIS_GAME,
                )
            elif learned != vector:
                metric.movement_prediction_errors += 1
            entered_visible_candidate = _cell(before_rows, new_position) not in {0, color}
            if not self._interaction_used and (
                self._last_target == new_position or entered_visible_candidate
            ):
                self._pending_interaction = True
        elif action.name in MOVE_ACTIONS and old_position is not None:
            self._player_position = old_position
            self._player_color = old_color
            learned_vector = self._movement.get(action.name)
            target = (
                _add(old_position, learned_vector) if learned_vector is not None else None
            )
            if target is not None and self._inside(target, before):
                color = _cell(before_rows, target)
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
            key = (self._level_index, action.name)
            predicted_resource = self._resource_delta_by_action.get(key)
            if predicted_resource is None:
                self._resource_delta_by_action[key] = resource_delta
                self._open_resource_mechanic(action.name, resource_delta)
            elif predicted_resource != resource_delta:
                metric.resource_prediction_errors += 1

        self._update_dynamic_residuals(before, after, action)
        observed = self._mechanical_vector(
            action=action,
            displacement=displacement,
            resource_delta=resource_delta,
            before=before,
            after=after,
        )
        if self._learner is not None and self._last_prediction_id is not None:
            try:
                learning = self._learner.observe_consequence(
                    self._last_prediction_id,
                    observed,
                    source_event_ids=(f"observation:{self._step}",),
                    context_key=self._context.context_key,
                    observed_step=self._step,
                )
                if learning.residual.consequential:
                    metric.residuals_observed += 1
                    metric.residuals_localized += 1
                    self._learner.resolve_residual(learning.residual.residual_id)
                    metric.residuals_resolved += 1
            except MechanicsError:
                metric.hazard_prediction_errors += 1

        self._record_causal_receipt(before, after, action, displacement, resource_delta)
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

    def _observe_displacement(
        self,
        before: tuple[tuple[int, ...], ...],
        after: tuple[tuple[int, ...], ...],
        action: ActionRequest,
    ) -> tuple[Point, Point, int] | None:
        if action.name not in MOVE_ACTIONS:
            return None
        expected = self._movement.get(action.name)
        colors = sorted({value for row in before[1:] for value in row if value != 0})
        candidates: list[tuple[Point, Point, int]] = []
        for color in colors:
            old_positions = set(_positions(before, color))
            new_positions = set(_positions(after, color))
            for old in old_positions - new_positions:
                for new in new_positions - old_positions:
                    vector = (new[0] - old[0], new[1] - old[1])
                    if vector in CARDINALS and (expected is None or vector == expected):
                        candidates.append((old, new, color))
        if self._last_player_color is not None:
            matching = [item for item in candidates if item[2] == self._last_player_color]
            if len(matching) == 1:
                return matching[0]
        return candidates[0] if len(candidates) == 1 else None

    def _mechanical_vector(
        self,
        *,
        action: ActionRequest,
        displacement: tuple[Point, Point, int] | None,
        resource_delta: int,
        before: Observation,
        after: Observation,
    ) -> ConsequenceVector:
        controlled = ChannelValue.known_empty()
        if displacement is not None:
            old, new, _color = displacement
            controlled = ChannelValue.known(
                DisplacementEffect("controllable-object", new[0] - old[0], new[1] - old[1])
            )
        vector = ConsequenceVector(
            controlled_displacement=controlled,
            resource_changes=(
                ChannelValue.unknown()
                if action.name is ActionName.RESET
                else ChannelValue.known(QuantityEffect("visible-hud", resource_delta))
            ),
            score_progress_changes=ChannelValue.known(
                ScoreProgressEffect(
                    "levels-completed", after.levels_completed - before.levels_completed
                )
            ),
            terminal_changes=(
                ChannelValue.known(TerminalEffect(after.state))
                if before.state is not after.state or after.full_reset
                else ChannelValue.known_empty()
            ),
        )
        return vector

    def _open_movement_mechanic(
        self,
        action: ActionName,
        vector: Point,
        *,
        source: str,
        provenance: EvidenceProvenance,
    ) -> None:
        if self._learner is None or action in self._movement_refs:
            return
        consequence = ConsequenceVector(
            controlled_displacement=ChannelValue.known(
                DisplacementEffect("controllable-object", vector[0], vector[1])
            )
        )
        try:
            self._learner.ledger.open(
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
        except MechanicsError:
            self._metrics[self._level_index].hazard_prediction_errors += 1

    def _open_resource_mechanic(self, action: ActionName, delta: int) -> None:
        if self._learner is None:
            return
        key = (self._level_index, action)
        if key in self._resource_refs:
            return
        try:
            self._learner.ledger.open(
                action=action,
                scope=MechanicScope(
                    ScopeCeiling.LEVEL,
                    game_scope=self._game_scope,
                    level_scope=self._context.level_scope,
                ),
                consequence=ConsequenceVector(
                    resource_changes=ChannelValue.known(QuantityEffect("visible-hud", delta))
                ),
                composition_mode=CompositionMode.ADDITIVE,
                created_step=self._step,
                created_from_event_ids=(f"visible-hud-delta:{self._step}",),
                provenance=EvidenceProvenance.OBSERVED_THIS_GAME,
                mechanic_id=f"resource-l{self._level_index + 1}-{action.value.casefold()}",
                priority=80,
                note="level-local visible resource delta",
            )
            self._resource_refs.add(key)
        except MechanicsError:
            self._metrics[self._level_index].hazard_prediction_errors += 1

    def _update_dynamic_residuals(
        self, before: Observation, after: Observation, action: ActionRequest
    ) -> None:
        rows_before = _board(before)
        rows_after = _board(after)
        recurring: list[Point] = []
        for y in range(1, len(rows_before)):
            for x in range(len(rows_before[y])):
                old = rows_before[y][x]
                new = rows_after[y][x]
                point = (x, y)
                if old != 0 and new != 0 and old != new:
                    self._recolor_counts[point] += 1
                    if self._recolor_counts[point] >= 2:
                        recurring.append(point)
        if not recurring:
            return
        metric = self._metrics[self._level_index]
        if not self._clef_enabled:
            metric.residuals_observed += len(recurring)
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
            readability_wall=ReadabilityWall(max_detail_units=2, used_detail_units=2),
            dynamic_context=DynamicClaimContext(
                window=ActionWindow(max(0, self._step - 1), self._step),
                intervention=action,
                assumed_scope=StateScope.LEVEL,
                observation_return_path=("Observation.frames[-1].cells",),
            ),
        )
        for point in recurring:
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
                        "fixed-coordinate recurrence",
                        True,
                        evidence_event_ids=(f"observation:{self._step}",),
                    ),
                ),
            )
            decision = assess_residual(
                assessment,
                already_explained=True,
                changes_prediction=False,
                changes_action_selection=False,
                additional_detail_cost=1,
                expected_decision_value=0,
            )
            metric.residuals_observed += 1
            metric.residuals_localized += 1
            if decision.disposition is ResidualDisposition.STOP:
                self._ignored_dynamic.add(point)
                metric.residuals_resolved += 1

    def _record_causal_receipt(
        self,
        before: Observation,
        after: Observation,
        action: ActionRequest,
        displacement: tuple[Point, Point, int] | None,
        resource_delta: int,
    ) -> None:
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
        resource_prediction = self._resource_delta_by_action.get((self._level_index, action.name))
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
                if self._last_target is None
                else (f"cell:{self._last_target[0]},{self._last_target[1]}",)
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
        self._receipt_digests.append(_digest(receipt.to_dict()))


__all__ = ["SUPPORTED_VARIANTS", "ObservationOnlyVariantPolicy"]
