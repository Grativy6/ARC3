"""Integrated deterministic observation-model-plan-action ARC3 controller."""

from __future__ import annotations

import math
import random
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn, cast

from arc3.adapters import GridFrame, Observation, validate_action_request
from arc3.config import derive_seed
from arc3.errors import ARC3ValidationError, CompetitionIntegrityError, PolicyError
from arc3.exploration import (
    EffectKind,
    ExplorationPlanner,
    ProbeContext,
    ProbeOption,
    classify_effect,
    generate_coordinate_candidates,
    state_features,
)
from arc3.exploration import (
    ModelAlternative as ExplorationAlternative,
)
from arc3.exploration import (
    ModelPrediction as ExplorationPrediction,
)
from arc3.goals import (
    ActionGoalEstimate,
    EvidenceDirection,
    GoalAcquirer,
    GoalCandidate,
    GoalEvidence,
    GoalKind,
    GoalRegistry,
    GoalRole,
    GoalTransition,
    IntrinsicExplorationUtility,
    select_goal_action,
)
from arc3.hypotheses import (
    ActionSemanticsStatement,
    EvidenceKind,
    EvidenceReceipt,
    HypothesisRegistry,
    HypothesisScope,
)
from arc3.memory import (
    ControllerCheckpointManager,
    DerivedControllerState,
    PendingAction,
    PersistentMemory,
)
from arc3.memory import (
    ControllerPhase as MemoryControllerPhase,
)
from arc3.perception import (
    Component,
    ComponentConfig,
    FrameDelta,
    TrackingResult,
    extract_components,
    measure_delta,
    track_components,
)
from arc3.planning import (
    ActionEmission,
    Plan,
    PlanExecutor,
    PlanProblem,
    PlanScore,
    PlanStep,
    SearchAlgorithm,
    SearchBudget,
    SearchStatus,
    search,
)
from arc3.trace import CodeIdentity, EventJournal, SourceIdentity, TraceEvent
from arc3.trace.canonical import normalize_json, sha256_json
from arc3.types import (
    ActionName,
    ActionRequest,
    Coordinate,
    GameId,
    GameStateName,
    HypothesisStatus,
    JSONScalar,
    JSONValue,
    RationaleCategory,
    StateScope,
)
from arc3.world_model import (
    Attachment,
    Cell,
    ModelCandidate,
    PredictionBook,
    PredictionReceipt,
    PreservedTransition,
    PromotionStatus,
    SymbolicEntity,
    SymbolicState,
    WorldModelEnsemble,
    compile_hypotheses,
    gated_ensemble,
    retrodict,
)

from .models import (
    ActionDecision,
    CandidateAction,
    ConsequenceReceipt,
    ControllerCheckpoint,
    ControllerPhase,
    ControllerPreset,
    ControllerSnapshot,
    ObservationReceipt,
    PresetFeatures,
    RunContext,
    preset_features,
)
from .proposal import LocalProposalProvider, ProposalContext

_DIRECTIONAL_PRIORS: tuple[tuple[ActionName, int, int], ...] = (
    (ActionName.ACTION1, 0, -1),
    (ActionName.ACTION2, 0, 1),
    (ActionName.ACTION3, -1, 0),
    (ActionName.ACTION4, 1, 0),
)


@dataclass(frozen=True, slots=True)
class _PerceptionView:
    components: tuple[Component, ...]
    symbolic_state: SymbolicState
    delta: FrameDelta | None
    tracking: TrackingResult | None
    measurement_event_ids: tuple[str, ...]


def _action_payload(action: ActionRequest) -> dict[str, JSONValue]:
    coordinate = action.coordinate
    return {
        "name": action.name.value,
        "coordinate": ({"x": coordinate.x, "y": coordinate.y} if coordinate is not None else None),
    }


def _metadata(observation: Observation) -> dict[str, JSONScalar]:
    result = dict(observation.upstream_metadata)
    result.update(
        {
            "levels_completed": observation.levels_completed,
            "win_levels": observation.win_levels,
            "full_reset": observation.full_reset,
        }
    )
    return result


def _stable_entity_kind(component: Component) -> str:
    digest = sha256_json(
        {"shape": component.translation_signature, "color": component.color}
    ).removeprefix("sha256:")[:12]
    return f"observed-component:{digest}"


def _symbolic_state(
    frame: GridFrame, components: tuple[Component, ...]
) -> tuple[SymbolicState, dict[str, str]]:
    """Interpret measured components while retaining deterministic local identity."""

    grouped: dict[tuple[int, str], list[Component]] = {}
    for component in components:
        grouped.setdefault((component.color, component.translation_signature), []).append(component)
    entities: list[SymbolicEntity] = []
    component_to_entity: dict[str, str] = {}
    for (color, signature), group in sorted(grouped.items()):
        ordered = sorted(
            group,
            key=lambda item: (
                item.bounds.top,
                item.bounds.left,
                item.component_id,
            ),
        )
        shape_id = sha256_json({"shape": signature}).removeprefix("sha256:")[:12]
        for ordinal, component in enumerate(ordered):
            entity_id = f"entity:c{color}:{shape_id}:{ordinal}"
            component_to_entity[component.component_id] = entity_id
            entities.append(
                SymbolicEntity(
                    entity_id=entity_id,
                    kind=_stable_entity_kind(component),
                    cells=tuple(Cell(point.x, point.y) for point in component.cells),
                    color=color,
                    attributes=(("shape", signature),),
                )
            )
    return SymbolicState(width=frame.width, height=frame.height, entities=tuple(entities)), (
        component_to_entity
    )


def _entity_distance(state: SymbolicState, left_id: str, right_id: str) -> int | None:
    left = state.entity(left_id)
    right = state.entity(right_id)
    if left is None or right is None:
        return None
    return min(
        abs(left_cell.x - right_cell.x) + abs(left_cell.y - right_cell.y)
        for left_cell in left.cells
        for right_cell in right.cells
    )


class ARC3Controller:
    """One deterministic controller shared by all runtime adapters.

    ``choose_action`` records delivery across the policy/adapter boundary as
    ``action.submitted``.  Once that receipt exists, the only legal callback is
    ``apply_consequence``; checkpoint restoration therefore cannot resubmit it.
    """

    def __init__(
        self,
        preset: ControllerPreset | str = ControllerPreset.FULL,
        *,
        local_proposal_provider: LocalProposalProvider | None = None,
        features: PresetFeatures | None = None,
    ) -> None:
        self.preset = preset if isinstance(preset, ControllerPreset) else ControllerPreset(preset)
        selected_features = preset_features(self.preset) if features is None else features
        if self.preset is ControllerPreset.COMPETITION and selected_features != preset_features(
            ControllerPreset.COMPETITION
        ):
            raise CompetitionIntegrityError(
                "competition preset forbids experimental feature overrides"
            )
        self.features = selected_features
        if self.preset is ControllerPreset.COMPETITION and local_proposal_provider is not None:
            raise CompetitionIntegrityError(
                "competition preset forbids the experimental local proposal provider"
            )
        if local_proposal_provider is not None and not self.features.allow_local_proposals:
            raise PolicyError("local proposals are disabled by the selected controller preset")
        self._local_proposals = local_proposal_provider
        self._context: RunContext | None = None
        self._journal: EventJournal | None = None
        self._checkpoint_manager: ControllerCheckpointManager | None = None
        self._source: SourceIdentity | None = None
        self._code: CodeIdentity | None = None
        self._rng = random.Random(0)
        self._phase = ControllerPhase.NEW
        self._step_index = 0
        self._level_index = 0
        self._actions_used = 0
        self._resets_used = 0
        self._latest_observation: Observation | None = None
        self._latest_receipt: ObservationReceipt | None = None
        self._latest_view: _PerceptionView | None = None
        self._before_action_observation: Observation | None = None
        self._before_action_state: SymbolicState | None = None
        self._before_action_features: ProbeContext | None = None
        self._pending_action: PendingAction | None = None
        self._pending_prediction: PredictionReceipt | None = None
        self._restored_prediction_state_ids: tuple[str, ...] = ()
        self._restored_prediction_plan_ids: tuple[str, ...] = ()
        self._prediction_book = PredictionBook()
        self._hypotheses = HypothesisRegistry()
        self._goals = GoalRegistry()
        self._goal_acquirer = GoalAcquirer(self._goals)
        self._exploration = ExplorationPlanner()
        self._memory = PersistentMemory()
        self._plan_executor = PlanExecutor()
        self._pending_plan_emission = False
        self._planning_disabled_after_mismatch = False
        self._ensemble: WorldModelEnsemble | None = None
        self._model_candidates: tuple[ModelCandidate, ...] = ()
        self._transitions: list[PreservedTransition] = []
        self._transition_levels: dict[str, int] = {}
        self._transition_summaries: dict[int, list[PreservedTransition]] = {}
        self._component_to_entity: dict[str, str] = {}
        self._provisional_mover_id: str | None = None
        self._goal_targets: dict[str, tuple[str, str]] = {}
        self._active_goal_id: str | None = None
        self._goal_event_sequence_offset = 0
        self._action_counts: Counter[ActionRequest] = Counter()
        self._explored_coordinates: set[Coordinate] = set()
        self._traced_goal_events = 0
        self._fault_count = 0
        self._last_checkpoint: ControllerCheckpoint | None = None

    @property
    def phase(self) -> ControllerPhase:
        return self._phase

    @property
    def journal(self) -> EventJournal:
        if self._journal is None:
            raise PolicyError("controller has not been reset with a run context")
        return self._journal

    @property
    def context(self) -> RunContext:
        if self._context is None:
            raise PolicyError("controller has not been reset with a run context")
        return self._context

    @property
    def snapshot(self) -> ControllerSnapshot:
        active_hypotheses = tuple(
            record.hypothesis_id for record in self._hypotheses.ranked(include_rejected=False)
        )
        models = (
            tuple(candidate.model_id for candidate in self._ensemble.candidates)
            if self._ensemble is not None
            else ()
        )
        goals = tuple(
            record.candidate.goal_id for record in self._goals.records(include_retired=False)
        )
        return ControllerSnapshot(
            phase=self._phase,
            step_index=self._step_index,
            level_index=self._level_index,
            actions_used=self._actions_used,
            resets_used=self._resets_used,
            trace_events=self.journal.event_count if self._journal is not None else 0,
            pending_action=(self._pending_action.action if self._pending_action else None),
            active_hypothesis_ids=active_hypotheses,
            active_world_model_ids=models,
            active_goal_ids=goals,
            fault_count=self._fault_count,
        )

    def reset(self, context: RunContext) -> None:
        """Start one episode with fresh derived state and a durable raw journal."""

        if self._journal is not None:
            self._journal.close()
        if self.preset is ControllerPreset.COMPETITION:
            if context.config.network_enabled:
                raise CompetitionIntegrityError("competition controller cannot enable networking")
            if context.config.mode.value != "competition":
                raise CompetitionIntegrityError(
                    "competition preset requires a competition-mode ARC3Config"
                )
        ARC3Controller.__init__(
            self,
            self.preset,
            local_proposal_provider=self._local_proposals,
            features=self.features,
        )
        self._initialize_context(context)
        self._append(
            context.game_id,
            "run.started",
            {
                "preset": self.preset.value,
                "network_enabled": context.config.network_enabled,
                "features": self.features.to_dict(),
            },
            scope="run",
        )

    def _initialize_context(self, context: RunContext) -> None:
        self._context = context
        self._source = SourceIdentity(
            context.source_kind,
            context.source_version,
            {"preset": self.preset.value, "features": self.features.to_dict()},
        )
        self._code = CodeIdentity(
            context.git_commit,
            str(context.config.hash),
            {"profile": context.config.profile},
        )
        # Derived events are buffered between authority boundaries.  Raw
        # observations, submitted actions, returned consequences, checkpoints,
        # and close still force durable flushes explicitly below.
        self._journal = EventJournal(
            context.trace_root,
            run_id=context.run_id,
            flush_every=128,
        )
        self._checkpoint_manager = ControllerCheckpointManager(context.checkpoint_root)
        self._rng = random.Random(derive_seed(context.config.seed, "arc3-controller"))

    def _append(
        self,
        game_id: str,
        event_type: str,
        payload: Mapping[str, object],
        *,
        scope: StateScope | str = StateScope.EPISODE,
        step_index: int | None = None,
    ) -> TraceEvent:
        if self._source is None or self._code is None:
            raise PolicyError("controller identity is unavailable")
        return self.journal.append(
            episode_id=self.context.episode_id,
            game_id=game_id,
            level_index=self._level_index,
            step_index=self._step_index if step_index is None else step_index,
            event_type=event_type,
            source=self._source,
            scope=scope,
            payload=payload,
            code_identity=self._code,
        )

    def observe(self, frames: Observation | object) -> ObservationReceipt:
        """Validate one initial/unsolicited observation before selecting an action."""

        if self._phase is ControllerPhase.AWAITING_CONSEQUENCE:
            raise PolicyError(
                "pending action requires apply_consequence; observe cannot erase the boundary"
            )
        if self._phase in {ControllerPhase.COMPLETE, ControllerPhase.CLOSED}:
            raise PolicyError(f"cannot observe while controller is {self._phase.value}")
        observation = self._require_observation(frames)
        self._level_index = observation.levels_completed
        receipt, view = self._record_observation(observation, previous=None)
        self._latest_observation = observation
        self._latest_receipt = receipt
        self._latest_view = view
        self._phase_from_observation(observation)
        if self.features.use_hypotheses:
            self._seed_directional_hypotheses(receipt, view)
            self._update_world_models(observation)
        if self.features.use_goals:
            self._seed_contact_goal(observation, receipt, view)
        self._emit_local_proposals_if_enabled(observation, receipt, view)
        if self.features.use_memory:
            self._last_checkpoint = self.checkpoint()
        return receipt

    def _require_observation(self, value: Observation | object) -> Observation:
        if not isinstance(value, Observation):
            self._reject_observation(value, fault="expected immutable first-party Observation")
        if str(value.game_id) != self.context.game_id:
            self._reject_observation(
                value,
                fault="observation game identity does not match run context",
            )
        if not value.frames:
            self._reject_observation(
                value,
                fault="observation requires at least one normalized frame",
            )
        try:
            metadata = dict(value.upstream_metadata)
            if len(metadata) != len(value.upstream_metadata):
                raise ARC3ValidationError("upstream metadata keys must be unique")
            normalize_json(metadata)
        except (ARC3ValidationError, TypeError, ValueError):
            self._reject_observation(
                value,
                fault="upstream metadata is not canonical JSON",
            )
        return value

    def _reject_observation(self, value: object, *, fault: str) -> NoReturn:
        """Fault with a durable receipt that never serializes untrusted content."""

        self._fault_count += 1
        self._phase = ControllerPhase.FAULTED
        event = self._append(
            self.context.game_id,
            "observation.parse_failed",
            {
                "input_type": f"{type(value).__module__}.{type(value).__name__}",
                "fault": fault,
            },
        )
        raise PolicyError(f"malformed observation preserved as {event.event_id}")

    def _record_observation(
        self,
        observation: Observation,
        *,
        previous: Observation | None,
    ) -> tuple[ObservationReceipt, _PerceptionView]:
        frame_receipts = [
            self.journal.blobs.put_frame(frame.cells).to_payload() for frame in observation.frames
        ]
        raw = self._append(
            str(observation.game_id),
            "observation.received",
            {
                "frame_count": len(frame_receipts),
                "frames": frame_receipts,
                "game_state": observation.state.value,
                "score": None,
                "available_actions": [item.value for item in observation.available_actions],
                "returned_action": (
                    _action_payload(observation.returned_action)
                    if observation.returned_action is not None
                    else None
                ),
                "upstream_metadata": _metadata(observation),
            },
        )
        raw_id = raw.event_id
        raw_hash = raw.event_hash
        self.journal.flush()
        frame = observation.frames[-1]
        background = Counter(cell for row in frame.cells for cell in row).most_common(1)[0][0]
        components = extract_components(
            frame,
            config=ComponentConfig(background_candidates=(background,)),
        )
        symbolic, component_to_entity = _symbolic_state(frame, components)
        self._component_to_entity = component_to_entity
        measurement_ids: list[str] = []
        normalized_event = self._append(
            str(observation.game_id),
            "observation.normalized",
            {
                "source_observation_event_id": raw_id,
                "frame_hash": str(frame.digest),
                "width": frame.width,
                "height": frame.height,
            },
        )
        measurement_ids.append(normalized_event.event_id)

        delta: FrameDelta | None = None
        tracking: TrackingResult | None = None
        if previous is not None:
            prior_frame = previous.frames[-1]
            prior_background = Counter(
                cell for row in prior_frame.cells for cell in row
            ).most_common(1)[0][0]
            prior_components = extract_components(
                prior_frame,
                config=ComponentConfig(background_candidates=(prior_background,)),
            )
            delta = measure_delta(
                prior_frame,
                frame,
                before_metadata=_metadata(previous),
                after_metadata=_metadata(observation),
                background_colors=frozenset({prior_background, background}),
            )
            if self.features.use_object_tracking:
                tracking = track_components(
                    prior_components,
                    components,
                    frame_extent=(
                        max(prior_frame.width, frame.width),
                        max(prior_frame.height, frame.height),
                    ),
                )
            xs = [change.x for change in delta.cell_changes]
            ys = [change.y for change in delta.cell_changes]
            delta_event = self._append(
                str(observation.game_id),
                "observation.delta_measured",
                {
                    "before_frame_hash": str(delta.before_hash),
                    "after_frame_hash": str(delta.after_hash),
                    "changed_cell_count": delta.changed_cell_count,
                    "cell_changes": [
                        {
                            "x": change.x,
                            "y": change.y,
                            "before": change.before if change.before is not None else -1,
                            "after": change.after if change.after is not None else -1,
                            "kind": change.kind.value,
                        }
                        for change in delta.cell_changes
                    ],
                    "changed_bbox": ([min(xs), min(ys), max(xs), max(ys)] if xs and ys else None),
                    "component_changes": [
                        {
                            "before_id": change.before_id,
                            "after_id": change.after_id,
                            "kinds": [kind.value for kind in change.kinds],
                            "displacement": (
                                list(change.displacement)
                                if change.displacement is not None
                                else None
                            ),
                            "correspondence_score": change.correspondence_score,
                        }
                        for change in (tracking.changes if tracking is not None else ())
                    ],
                    "metadata_changes": {
                        change.field: {"before": change.before, "after": change.after}
                        for change in delta.metadata_changes
                    },
                    "apparent_noop": delta.changed_cell_count == 0,
                },
            )
            measurement_ids.append(delta_event.event_id)

        if self.features.use_measurements:
            event = self._append(
                str(observation.game_id),
                "perception.components_detected",
                {
                    "source_observation_event_id": raw_id,
                    "component_count": len(components),
                    "components": [
                        {
                            "component_id": component.component_id,
                            "entity_candidate_id": component_to_entity[component.component_id],
                            "color": component.color,
                            "area": component.area,
                            "bounds": [
                                component.bounds.left,
                                component.bounds.top,
                                component.bounds.right,
                                component.bounds.bottom,
                            ],
                            "translation_signature": component.translation_signature,
                        }
                        for component in components
                    ],
                    "interpretation_status": "measurement-only",
                },
            )
            measurement_ids.append(event.event_id)
            if tracking is not None:
                event = self._append(
                    str(observation.game_id),
                    "perception.object_correspondence_proposed",
                    {
                        "source_observation_event_id": raw_id,
                        "ambiguous": tracking.has_ambiguity,
                        "correspondence_count": len(tracking.correspondences),
                        "alternatives": [
                            {
                                "before_id": item.before_id,
                                "after_ids": [alt.after_id for alt in item.alternatives],
                                "scores": [alt.score for alt in item.alternatives],
                            }
                            for item in tracking.correspondences
                        ],
                    },
                )
                measurement_ids.append(event.event_id)

        receipt = ObservationReceipt(
            observation_event_id=raw_id,
            observation_event_hash=raw_hash,
            frame_hashes=tuple(str(item.digest) for item in observation.frames),
            measurement_event_ids=tuple(measurement_ids),
        )
        return receipt, _PerceptionView(
            components, symbolic, delta, tracking, tuple(measurement_ids)
        )

    def _phase_from_observation(self, observation: Observation) -> None:
        if observation.state is GameStateName.WIN:
            self._phase = ControllerPhase.COMPLETE
        elif observation.state is GameStateName.GAME_OVER:
            self._phase = ControllerPhase.GAME_OVER
        else:
            self._phase = ControllerPhase.OBSERVED

    def _seed_directional_hypotheses(
        self, receipt: ObservationReceipt, view: _PerceptionView
    ) -> dict[ActionName, str]:
        if not view.symbolic_state.entities:
            return {}
        provisional = min(
            view.symbolic_state.entities,
            key=lambda item: (len(item.cells), item.entity_id),
        )
        self._provisional_mover_id = provisional.entity_id
        scope_ref = f"level:{self._level_index}"
        existing = {
            record.statement.action: record.hypothesis_id
            for record in self._hypotheses.all()
            if isinstance(record.statement, ActionSemanticsStatement)
            and record.scope is HypothesisScope.LEVEL
            and record.scope_ref == scope_ref
            and record.status not in {HypothesisStatus.REJECTED, HypothesisStatus.SUPERSEDED}
        }
        seeded: dict[ActionName, str] = {}
        for action, dx, dy in _DIRECTIONAL_PRIORS:
            existing_id = existing.get(action.value)
            if existing_id is not None:
                seeded[action] = existing_id
                continue
            receipt_identity = receipt.observation_event_hash.removeprefix("sha256:")[:12]
            hypothesis_id = f"H-DIRECTIONAL-L{self._level_index}-{action.value}-{receipt_identity}"
            record = self._hypotheses.create(
                statement=ActionSemanticsStatement(
                    action=action.value,
                    effect="movement",
                    parameters={
                        "dx": dx,
                        "dy": dy,
                        "entity_id": provisional.entity_id,
                    },
                ),
                scope=HypothesisScope.LEVEL,
                scope_ref=scope_ref,
                created_from_event_ids=(receipt.observation_event_id,),
                occurred_step=self._step_index,
                hypothesis_id=hypothesis_id,
                initial_rank_weight=0,
                note="weak generic directional prior; not accepted evidence",
            )
            self._append(
                self.context.game_id,
                "hypothesis.created",
                {
                    "hypothesis_id": record.hypothesis_id,
                    "family": record.family.value,
                    "statement": record.statement.to_dict(),
                    "created_from_event_ids": list(record.created_from_event_ids),
                    "status": record.status.value,
                    "weight_kind": "uncalibrated_rank",
                    "note": "weak generic prior",
                },
            )
            seeded[action] = hypothesis_id
        return seeded

    def _seed_contact_goal(
        self,
        observation: Observation,
        receipt: ObservationReceipt,
        view: _PerceptionView,
    ) -> None:
        entities = view.symbolic_state.entities
        scope_ref = f"level:{self._level_index}"
        current = tuple(
            record
            for record in self._goals.records(include_retired=False)
            if record.candidate.kind is GoalKind.CONTACT
            and record.candidate.scope is HypothesisScope.LEVEL
            and record.candidate.scope_ref == scope_ref
        )
        if current:
            self._active_goal_id = current[0].candidate.goal_id
            return
        if len(entities) < 2:
            return
        mover_id = (
            self._provisional_mover_id
            or min(entities, key=lambda item: (len(item.cells), item.entity_id)).entity_id
        )
        candidates = [item for item in entities if item.entity_id != mover_id]
        target = min(
            candidates,
            key=lambda item: (
                _entity_distance(view.symbolic_state, mover_id, item.entity_id) or 10**9,
                len(item.cells),
                item.entity_id,
            ),
        )
        mover = view.symbolic_state.entity(mover_id)
        goal_id = (
            "goal:contact:"
            + sha256_json(
                {
                    "level": self._level_index,
                    "mover_kind": mover.kind if mover is not None else "unknown",
                    "target_kind": target.kind,
                    "source_observation_event_id": receipt.observation_event_id,
                }
            ).removeprefix("sha256:")[:24]
        )
        evidence = GoalEvidence(
            evidence_id=f"gev:contact:{receipt.observation_event_hash.removeprefix('sha256:')[:24]}",
            direction=EvidenceDirection.SUPPORT,
            source_event_ids=(receipt.observation_event_id,),
            observed_step=self._step_index,
            level_index=self._level_index,
            summary="generic proximity/contact affordance candidate",
            rank_impact=1,
        )
        self._goals.register(
            GoalCandidate(
                goal_id=goal_id,
                kind=GoalKind.CONTACT,
                role=GoalRole.INTERMEDIATE_SUBGOAL,
                scope=HypothesisScope.LEVEL,
                scope_ref=scope_ref,
                target_state=f"contact:{target.kind}",
                source_evidence=(evidence,),
                created_step=self._step_index,
            )
        )
        self._goal_targets[goal_id] = (mover_id, target.entity_id)
        self._active_goal_id = goal_id
        self._flush_goal_events(observation)

    def _flush_goal_events(self, observation: Observation) -> None:
        events = self._goals.events
        for event in events[self._traced_goal_events :]:
            payload = event.to_trace_payload()
            if self._goal_event_sequence_offset:
                sequence = event.sequence + self._goal_event_sequence_offset
                payload["goal_event_id"] = f"goal-event-{sequence:08d}"
                payload["sequence"] = sequence
            self._append(
                str(observation.game_id),
                event.event_type.value,
                payload,
            )
        self._traced_goal_events = len(events)

    def _emit_local_proposals_if_enabled(
        self,
        observation: Observation,
        receipt: ObservationReceipt,
        view: _PerceptionView,
    ) -> None:
        if self._local_proposals is None:
            return
        proposals = self._local_proposals.propose(
            ProposalContext(
                frame_hash=str(observation.frames[-1].digest),
                measurement_summary={
                    "component_count": len(view.components),
                    "changed_cell_count": (
                        view.delta.changed_cell_count if view.delta is not None else 0
                    ),
                },
                active_hypothesis_ids=tuple(
                    record.hypothesis_id for record in self._hypotheses.all()
                ),
                active_goal_ids=tuple(
                    record.candidate.goal_id
                    for record in self._goals.records(include_retired=False)
                ),
            )
        )
        for proposal in proposals:
            self._append(
                str(observation.game_id),
                "hypothesis.created",
                {
                    "proposal_id": proposal.proposal_id,
                    "family": proposal.family,
                    "statement": proposal.statement,
                    "source_observation_event_id": receipt.observation_event_id,
                    "status": "unvalidated-experimental-proposal",
                    "action_authority": "none",
                },
            )

    def _update_world_models(self, observation: Observation) -> None:
        if not self.features.use_world_model or not self._hypotheses.all():
            self._ensemble = None
            return
        current_scope = f"level:{self._level_index}"
        eligible = tuple(
            record
            for record in self._hypotheses.all()
            if record.scope is not HypothesisScope.LEVEL or record.scope_ref == current_scope
            if self.features.retain_rejected_hypotheses
            or (
                record.status is not HypothesisStatus.REJECTED and not record.contradiction_receipts
            )
        )
        compiled = compile_hypotheses(eligible)
        self._model_candidates = compiled.candidates
        level_transitions = (
            tuple(self._transition_summaries.get(self._level_index, ()))
            if self.features.use_trace_summaries
            else tuple(
                item
                for item in self._transitions
                if self._transition_levels.get(item.transition_id) == self._level_index
            )
        )
        artifacts = []
        for candidate in compiled.candidates:
            self._append(
                str(observation.game_id),
                "model.retrodiction_started",
                {
                    "model_id": candidate.model_id,
                    "transition_ids": [item.transition_id for item in level_transitions],
                },
            )
            artifact = retrodict(
                candidate,
                level_transitions,
                enabled=self.features.use_retrodiction_gate,
            )
            artifacts.append(artifact)
            self._append(
                str(observation.game_id),
                "model.retrodiction_completed",
                {
                    "artifact_id": artifact.artifact_id,
                    "model_id": artifact.model_id,
                    "status": artifact.status.value,
                    "complete": artifact.complete,
                    "tested_transition_ids": list(artifact.tested_transition_ids),
                    "matched_transition_ids": list(artifact.matched_transition_ids),
                    "contradiction_transition_ids": list(artifact.contradiction_transition_ids),
                    "score": artifact.score.total,
                    "weight_kind": artifact.score.weight_kind,
                },
            )
        accepted_ids = {
            artifact.model_id
            for artifact in artifacts
            if artifact.status is PromotionStatus.PROMOTED
            or (
                not self.features.use_retrodiction_gate
                and artifact.status is PromotionStatus.UNGATED_ABLATION
            )
        }
        if accepted_ids:
            self._ensemble = gated_ensemble(
                compiled.candidates,
                tuple(artifacts),
                allow_ungated_ablation=not self.features.use_retrodiction_gate,
            )
            for candidate in self._ensemble.candidates:
                self._append(
                    str(observation.game_id),
                    "model.rule_promoted",
                    {
                        "model_id": candidate.model_id,
                        "hypothesis_ids": list(candidate.hypothesis_ids),
                        "promotion_basis": (
                            "complete compatible-trace retrodiction"
                            if self.features.use_retrodiction_gate
                            else "ungated Stage 14 ablation"
                        ),
                    },
                )
        else:
            self._ensemble = None

    def _legal_actions(
        self, observation: Observation, view: _PerceptionView
    ) -> tuple[ActionRequest, ...]:
        if observation.state in {GameStateName.GAME_OVER, GameStateName.NOT_PLAYED}:
            return (ActionRequest(ActionName.RESET),)
        actions: list[ActionRequest] = []
        for name in observation.available_actions:
            if name is ActionName.ACTION6:
                limit = min(self.context.config.budgets.max_coordinate_candidates, 24)
                if self.features.use_coordinate_salience:
                    coordinates = tuple(
                        item.coordinate
                        for item in generate_coordinate_candidates(
                            observation.frames[-1],
                            components=view.components,
                            changed_cells=(
                                view.delta.cell_changes if view.delta is not None else ()
                            ),
                            explored=self._explored_coordinates,
                            max_candidates=limit,
                        )
                    )
                else:
                    frame = observation.frames[-1]
                    unexplored = [
                        Coordinate(x, y)
                        for y in range(frame.height)
                        for x in range(frame.width)
                        if Coordinate(x, y) not in self._explored_coordinates
                    ]
                    population = unexplored or [
                        Coordinate(x, y) for y in range(frame.height) for x in range(frame.width)
                    ]
                    coordinates = tuple(self._rng.sample(population, k=min(limit, len(population))))
                actions.extend(ActionRequest(name, coordinate) for coordinate in coordinates)
            else:
                actions.append(ActionRequest(name))
        return tuple(actions)

    def _fail_budget(self, *, budget: str, used: int, limit: int) -> None:
        """Enter a durable fault instead of silently overspending an action budget."""

        self._fault_count += 1
        self._phase = ControllerPhase.FAULTED
        self._append(
            self.context.game_id,
            "run.environment_fault",
            {
                "fault_type": "budget-exhausted",
                "budget": budget,
                "used": used,
                "limit": limit,
                "recovery": "owner-controlled reset or new bounded run required",
            },
            scope="run",
        )
        if self.features.use_memory:
            self._last_checkpoint = self.checkpoint()
        raise PolicyError(f"{budget} budget exhausted ({used}/{limit})")

    def _ensure_budget_available(self, action: ActionRequest) -> None:
        budgets = self.context.config.budgets
        if action.name is ActionName.RESET:
            if self._resets_used >= budgets.max_resets:
                self._fail_budget(
                    budget="max_resets",
                    used=self._resets_used,
                    limit=budgets.max_resets,
                )
            return
        if self._actions_used >= budgets.max_actions:
            self._fail_budget(
                budget="max_actions",
                used=self._actions_used,
                limit=budgets.max_actions,
            )

    def _record_actual_action(self, action: ActionRequest) -> None:
        """Count the action acknowledged by the environment, not a prior intention."""

        self._action_counts[action] += 1
        if action.name is ActionName.RESET:
            self._resets_used += 1
        else:
            self._actions_used += 1
        if action.coordinate is not None:
            self._explored_coordinates.add(action.coordinate)

    def _goal_option(
        self, action: ActionRequest, state: SymbolicState
    ) -> tuple[str | None, float, int]:
        goal_id = self._active_goal_id
        if (
            not self.features.use_world_model_simulation
            or goal_id is None
            or self._ensemble is None
            or goal_id not in self._goal_targets
        ):
            return None, 0.0, 0
        mover_id, target_id = self._goal_targets[goal_id]
        before_distance = _entity_distance(state, mover_id, target_id)
        prediction = self._ensemble.candidates[0].predict(state, action)
        after_distance = _entity_distance(prediction.after_state, mover_id, target_id)
        if before_distance is None or after_distance is None:
            return goal_id, 0.0, 0
        advance = max(0, before_distance - after_distance)
        return goal_id, min(1.0, float(advance)), advance

    def _candidate_actions(
        self, observation: Observation, view: _PerceptionView
    ) -> tuple[CandidateAction, ...]:
        legal = self._legal_actions(observation, view)
        if not legal:
            raise PolicyError("observation advertises no legal action")
        context = ProbeContext(
            state=state_features(
                observation,
                changed_cell_count=view.delta.changed_cell_count if view.delta else 0,
            ),
            actions_used=min(self._actions_used, self.context.config.budgets.max_actions),
            action_budget=self.context.config.budgets.max_actions,
        )
        options: list[CandidateAction] = []
        for action in legal:
            _goal_id, progress, _advance = self._goal_option(action, view.symbolic_state)
            estimate = self._exploration.statistics.estimate(context.state, action)
            failure = 0.25 if estimate.kind is EffectKind.NO_OP and not estimate.prior_only else 0.0
            novelty = 1.0 / (1.0 + self._action_counts[action])
            information = 0.0
            if self.features.use_information_gain and self._ensemble is not None:
                information = float(
                    len(self._ensemble.predict(view.symbolic_state, action).alternatives) > 1
                )
            utility = 2.0 * information + 1.25 * progress + 0.5 * novelty - 2.0 * failure
            options.append(
                CandidateAction(
                    action=action,
                    source="model-and-goal" if self._ensemble is not None else "generic-probe",
                    utility=round(utility, 9),
                    expected_progress=progress,
                    information=information,
                    failure_risk=failure,
                )
            )
        return tuple(options)

    def _exploration_alternatives(
        self, state: SymbolicState, actions: Sequence[ActionRequest]
    ) -> tuple[ExplorationAlternative, ...]:
        if (
            not self.features.use_world_model_simulation
            or not self.features.use_information_gain
            or self._ensemble is None
        ):
            return ()
        alternatives: list[ExplorationAlternative] = []
        for candidate in self._ensemble.candidates:
            predictions = tuple(
                ExplorationPrediction(
                    action,
                    candidate.predict(state, action).after_state_id,
                    EffectKind.INTERACTION,
                )
                for action in actions
            )
            alternatives.append(
                ExplorationAlternative(
                    identifier=candidate.model_id,
                    predictions=predictions,
                    weight=max(1.0, float(candidate.rank_weight + 1)),
                )
            )
        return tuple(alternatives)

    def _plan_action(
        self, observation: Observation, view: _PerceptionView
    ) -> tuple[ActionRequest, str, str] | None:
        if (
            not self.features.use_planning
            or not self.features.use_world_model_simulation
            or self._planning_disabled_after_mismatch
            or self._ensemble is None
            or self._active_goal_id is None
            or self._active_goal_id not in self._goal_targets
        ):
            return None
        goal_id = self._active_goal_id
        mover_id, target_id = self._goal_targets[goal_id]
        if (
            view.symbolic_state.entity(mover_id) is None
            or view.symbolic_state.entity(target_id) is None
        ):
            return None
        actions = tuple(
            action
            for action in self._legal_actions(observation, view)
            if action.name in {item[0] for item in _DIRECTIONAL_PRIORS}
        )
        if not actions:
            return None
        goal_record = self._goals.get(goal_id)
        goal_revision = f"{goal_record.status.value}:{goal_record.rank}:{goal_record.reopen_count}"
        model = self._ensemble.candidates[0]

        def goal_test(state: SymbolicState) -> bool:
            # Adjacency is the model-supported edge of an unknown collision/contact
            # rule.  Entering the target remains a separate falsifying live probe.
            distance = _entity_distance(state, mover_id, target_id)
            return distance is not None and distance <= 1

        def heuristic(state: SymbolicState) -> float:
            distance = _entity_distance(state, mover_id, target_id)
            return float(distance if distance is not None else state.width + state.height)

        problem = PlanProblem(
            problem_id=f"problem:{view.symbolic_state.state_id[-24:]}",
            initial_state=view.symbolic_state,
            model=model,
            goal_id=goal_id,
            goal_revision=goal_revision,
            available_actions=actions,
            goal_test=goal_test,
            heuristic=heuristic,
        )
        result = search(
            problem,
            algorithm=SearchAlgorithm.A_STAR,
            budget=SearchBudget(
                max_nodes=self.context.config.budgets.max_search_nodes,
                max_depth=self.context.config.budgets.max_search_depth,
                max_time_ms=max(
                    1,
                    min(
                        int(self.context.config.budgets.decision_seconds * 1_000),
                        5_000,
                    ),
                ),
            ),
        )
        payload = result.to_trace_payload()
        payload.update({"model_id": model.model_id, "goal_id": goal_id})
        self._append(str(observation.game_id), "simulation.plan_evaluated", payload)
        if result.status is not SearchStatus.FOUND or result.plan is None or not result.plan.steps:
            return None
        self._plan_executor = PlanExecutor()
        self._plan_executor.load(result.plan)
        for hypothesis_id in model.hypothesis_ids:
            self._hypotheses.register_dependent_plan(result.plan.plan_id, (hypothesis_id,))
        self._goals.selected(goal_id)
        self._flush_goal_events(observation)
        emission = self._plan_executor.next_action(
            view.symbolic_state,
            model_id=model.model_id,
            goal_id=goal_id,
            goal_revision=goal_revision,
            game_state=observation.state,
        )
        if not isinstance(emission, ActionEmission):
            return None
        return emission.action, emission.plan_id, "bounded A* plan under retrodicted model"

    def _contact_probe_action(
        self, observation: Observation, view: _PerceptionView
    ) -> tuple[ActionRequest, str, str] | None:
        """Probe an adjacent target without assuming pass/block/contact semantics."""

        goal_id = self._active_goal_id
        if goal_id is None or goal_id not in self._goal_targets:
            return None
        mover_id, target_id = self._goal_targets[goal_id]
        if _entity_distance(view.symbolic_state, mover_id, target_id) != 1:
            return None
        mover = view.symbolic_state.entity(mover_id)
        target = view.symbolic_state.entity(target_id)
        if mover is None or target is None:
            return None
        dx = target.anchor.x - mover.anchor.x
        dy = target.anchor.y - mover.anchor.y
        action_name = {
            (0, -1): ActionName.ACTION1,
            (0, 1): ActionName.ACTION2,
            (-1, 0): ActionName.ACTION3,
            (1, 0): ActionName.ACTION4,
        }.get((dx, dy))
        if action_name is None or action_name not in observation.available_actions:
            return None
        return (
            ActionRequest(action_name),
            f"probe:contact:{goal_id[-12:]}",
            "adjacent contact/collision discriminator",
        )

    def _probe_action(
        self,
        observation: Observation,
        view: _PerceptionView,
        candidates: tuple[CandidateAction, ...],
    ) -> tuple[ActionRequest, str | None, str]:
        context = ProbeContext(
            state=state_features(
                observation,
                changed_cell_count=view.delta.changed_cell_count if view.delta else 0,
            ),
            actions_used=min(self._actions_used, self.context.config.budgets.max_actions),
            action_budget=self.context.config.budgets.max_actions,
        )
        options = tuple(
            ProbeOption(
                candidate.action,
                progress=candidate.expected_progress,
                reversibility=(1.0 if candidate.action.name is ActionName.RESET else 0.0),
                novelty=min(1.0, 1.0 / (1.0 + self._action_counts[candidate.action])),
                failure_risk=candidate.failure_risk,
            )
            for candidate in candidates
        )
        if self.features.use_goals and self._goals.records(include_retired=False):
            estimates = tuple(
                ActionGoalEstimate(
                    action=candidate.action,
                    goal_id=self._active_goal_id,
                    goal_advance_rank=int(candidate.expected_progress > 0),
                    reachability_rank=int(candidate.expected_progress > 0),
                    exploration=IntrinsicExplorationUtility(
                        novelty=min(1.0, 1.0 / (1.0 + self._action_counts[candidate.action])),
                        information_gain=candidate.information,
                        reversibility=(1.0 if candidate.action.name is ActionName.RESET else 0.0),
                    ),
                    failure_risk_rank=int(candidate.failure_risk > 0),
                )
                for candidate in candidates
            )
            selected = select_goal_action(self._goals.records(include_retired=False), estimates)
            if selected.action is not None:
                return selected.action, selected.goal_id, selected.rationale
        ranked = self._exploration.select(
            options,
            context=context,
            alternatives=self._exploration_alternatives(
                view.symbolic_state, tuple(item.action for item in candidates)
            ),
        )
        return ranked.action, None, "bounded information-efficient generic probe"

    def _baseline_action(self, observation: Observation) -> ActionRequest:
        if observation.state in {GameStateName.NOT_PLAYED, GameStateName.GAME_OVER}:
            return ActionRequest(ActionName.RESET)
        available = tuple(sorted(observation.available_actions, key=lambda item: item.value))
        if not available:
            raise PolicyError("baseline preset has no advertised action")
        name = available[self._step_index % len(available)]
        coordinate = Coordinate(32, 32) if name is ActionName.ACTION6 else None
        return ActionRequest(name, coordinate)

    def choose_action(self) -> ActionDecision:
        """Select, validate, predict, and deliver exactly one action to the adapter."""

        if self._phase is ControllerPhase.AWAITING_CONSEQUENCE:
            raise PolicyError(
                "pending action already crossed the adapter boundary; do not resubmit"
            )
        if self._phase in {ControllerPhase.NEW, ControllerPhase.CLOSED}:
            raise PolicyError("controller needs a current observation before choosing")
        if self._phase is ControllerPhase.FAULTED:
            raise PolicyError("faulted controller cannot act on stale or untrusted state")
        if self._phase is ControllerPhase.COMPLETE:
            raise PolicyError("winning observation is terminal; no action is permitted")
        observation = self._latest_observation
        receipt = self._latest_receipt
        view = self._latest_view
        if observation is None or receipt is None or view is None:
            raise PolicyError("controller derived state is incomplete")

        candidates = self._candidate_actions(observation, view)
        candidate_event = self._append(
            str(observation.game_id),
            "action.candidates_generated",
            {
                "source_observation_event_id": receipt.observation_event_id,
                "candidates": [item.to_trace_payload() for item in candidates],
                "alternatives_summary": "legal actions ranked by declared generic terms",
            },
        )
        candidate_event_id = candidate_event.event_id

        plan_or_probe_id: str | None = None
        self._pending_plan_emission = False
        rationale = "deterministic action cycle preset"
        rationale_category = RationaleCategory.BASELINE
        try:
            if self.preset in {ControllerPreset.BASELINE, ControllerPreset.TRACE}:
                action = self._baseline_action(observation)
            elif self._phase is ControllerPhase.GAME_OVER:
                action = ActionRequest(ActionName.RESET)
                rationale = "game over permits only reset"
                rationale_category = RationaleCategory.MANDATORY_RESET
            else:
                contact_probe = self._contact_probe_action(observation, view)
                planned = (
                    None if contact_probe is not None else self._plan_action(observation, view)
                )
                if contact_probe is not None:
                    action, plan_or_probe_id, rationale = contact_probe
                    rationale_category = RationaleCategory.DISCRIMINATE_MODELS
                elif planned is not None:
                    action, plan_or_probe_id, rationale = planned
                    self._pending_plan_emission = True
                    rationale_category = RationaleCategory.FOLLOW_PLAN
                else:
                    action, plan_or_probe_id, rationale = self._probe_action(
                        observation, view, candidates
                    )
                    rationale_category = RationaleCategory.DISCRIMINATE_MODELS
        except Exception as error:
            self._fault_count += 1
            action = min(
                candidates,
                key=lambda item: (
                    self._action_counts[item.action],
                    item.action.name.value,
                    repr(item.action.coordinate),
                ),
            ).action
            rationale = f"deterministic legal fallback after {type(error).__name__}"
            rationale_category = RationaleCategory.FAULT_FALLBACK
            self._append(
                str(observation.game_id),
                "run.environment_fault",
                {
                    "fault_type": type(error).__name__,
                    "boundary": "candidate-selection",
                    "recovery": "least-repeated legal action",
                },
                scope="run",
            )
            self._append(
                str(observation.game_id),
                "action.fallback_used",
                {"action": _action_payload(action), "fault_type": type(error).__name__},
            )

        self._ensure_budget_available(action)
        validate_action_request(observation, action)
        active_hypothesis_ids = tuple(
            record.hypothesis_id for record in self._hypotheses.ranked(include_rejected=False)
        )
        active_model_ids = (
            tuple(candidate.model_id for candidate in self._ensemble.candidates)
            if self._ensemble is not None
            else ()
        )
        active_goal_ids = tuple(
            record.candidate.goal_id for record in self._goals.records(include_retired=False)
        )
        decision_id = (
            "decision:"
            + sha256_json(
                {
                    "observation_event_id": receipt.observation_event_id,
                    "step_index": self._step_index,
                    "action": _action_payload(action),
                    "candidate_event_id": candidate_event_id,
                }
            ).removeprefix("sha256:")[:24]
        )
        predicted_ids: tuple[str, ...] = ()
        selected = self._append(
            str(observation.game_id),
            "action.selected",
            {
                "decision_id": decision_id,
                "source_observation_event_id": receipt.observation_event_id,
                "selected_action": _action_payload(action),
                "candidate_utilities": [item.to_trace_payload() for item in candidates],
                "selected_probe_or_plan_id": plan_or_probe_id,
                "active_hypothesis_ids": list(active_hypothesis_ids),
                "predicted_outcome_ids": [],
                "active_goal_ids": list(active_goal_ids),
                "active_world_model_ids": list(active_model_ids),
                "rationale_category": rationale_category.value,
                "rationale_summary": rationale,
                "alternatives_summary": f"{len(candidates)} legal candidate(s) retained",
            },
        )
        selected_id = selected.event_id
        validated = self._append(
            str(observation.game_id),
            "action.validated",
            {
                "decision_id": decision_id,
                "selected_event_id": selected_id,
                "action": _action_payload(action),
                "available_actions": [item.value for item in observation.available_actions],
                "validation": "first-party legality check passed",
            },
        )
        validated_id = validated.event_id

        prediction_receipt_id: str | None = None
        self._pending_prediction = None
        self._restored_prediction_state_ids = ()
        self._restored_prediction_plan_ids = ()
        if (
            self.features.use_world_model_simulation
            and self._ensemble is not None
            and action.name is not ActionName.RESET
        ):
            prediction = self._prediction_book.emit(
                action_decision_id=decision_id,
                ensemble=self._ensemble,
                state=view.symbolic_state,
                action=action,
                dependent_plan_ids=((plan_or_probe_id,) if plan_or_probe_id else ()),
            )
            self._pending_prediction = prediction
            prediction_receipt_id = prediction.receipt_id
            predicted_ids = tuple(
                identifier
                for alternative in prediction.prediction.alternatives
                for identifier in alternative.prediction_ids
            )
            self._restored_prediction_state_ids = tuple(
                alternative.after_state_id for alternative in prediction.prediction.alternatives
            )
            self._restored_prediction_plan_ids = prediction.dependent_plan_ids
            self._append(
                str(observation.game_id),
                "simulation.prediction_emitted",
                prediction.to_dict(),
            )
        submitted = self._append(
            str(observation.game_id),
            "action.submitted",
            {
                "decision_id": decision_id,
                "selected_event_id": selected_id,
                "validated_event_id": validated_id,
                "action": _action_payload(action),
                "adapter_boundary": "delivered-to-runtime-adapter",
                "prediction_receipt_id": prediction_receipt_id,
            },
        )
        # The action receipt must be durable before the adapter is allowed to
        # execute it.  This also flushes the derived selection receipts that
        # explain the action without fsyncing each one independently.
        self.journal.flush()
        submitted_id = submitted.event_id
        self._pending_action = PendingAction(
            selected_event_id=selected_id,
            submitted_event_id=submitted_id,
            step_index=self._step_index,
            action=action,
            prediction_ids=predicted_ids,
        )
        self._before_action_observation = observation
        self._before_action_state = view.symbolic_state
        self._before_action_features = ProbeContext(
            state=state_features(
                observation,
                changed_cell_count=view.delta.changed_cell_count if view.delta else 0,
            ),
            actions_used=min(self._step_index, self.context.config.budgets.max_actions),
            action_budget=self.context.config.budgets.max_actions,
        )
        self._phase = ControllerPhase.AWAITING_CONSEQUENCE
        decision = ActionDecision(
            decision_id=decision_id,
            action=action,
            selected_event_id=selected_id,
            validated_event_id=validated_id,
            submitted_event_id=submitted_id,
            observation_event_id=receipt.observation_event_id,
            prediction_receipt_id=prediction_receipt_id,
            prediction_ids=predicted_ids,
            active_hypothesis_ids=active_hypothesis_ids,
            active_world_model_ids=active_model_ids,
            active_goal_ids=active_goal_ids,
            selected_probe_or_plan_id=plan_or_probe_id,
            alternatives=candidates,
            rationale_category=rationale_category,
            rationale_summary=rationale,
        )
        if self.features.use_memory:
            self._last_checkpoint = self.checkpoint()
        return decision

    def apply_consequence(self, frames: Observation | object) -> ConsequenceReceipt:
        """Apply exactly one returned consequence and reopen derived state on mismatch."""

        if self._phase is not ControllerPhase.AWAITING_CONSEQUENCE:
            raise PolicyError("apply_consequence requires one previously submitted action")
        pending = self._pending_action
        before = self._before_action_observation
        before_state = self._before_action_state
        before_context = self._before_action_features
        if pending is None or before is None or before_state is None or before_context is None:
            raise PolicyError("pending action state is incomplete")
        after = self._require_observation(frames)
        returned_action_mismatch = (
            after.returned_action is not None and after.returned_action != pending.action
        )
        previous_level = self._level_index

        returned_frames = [
            self.journal.blobs.put_frame(frame.cells).to_payload() for frame in after.frames
        ]
        consequence = self._append(
            str(after.game_id),
            "consequence.received",
            {
                "submitted_event_id": pending.submitted_event_id,
                "selected_event_id": pending.selected_event_id,
                "action": _action_payload(pending.action),
                "submitted_action": _action_payload(pending.action),
                "returned_action": (
                    _action_payload(after.returned_action)
                    if after.returned_action is not None
                    else None
                ),
                "before_state": before.state.value,
                "after_state": after.state.value,
                "returned_frames": returned_frames,
                "levels_completed": after.levels_completed,
            },
        )
        consequence_id = consequence.event_id
        consequence_hash = consequence.event_hash
        # Preserve the returned environment receipt before any revisable
        # interpretation or model update runs.
        self.journal.flush()
        # The consequence closes the submitted step; its returned observation is
        # the evidence boundary for the next decision step.
        self._step_index += 1
        self._level_index = after.levels_completed
        observation_receipt, view = self._record_observation(after, previous=before)
        observed_state = view.symbolic_state
        actual_action = after.returned_action or pending.action
        self._record_actual_action(actual_action)

        if returned_action_mismatch:
            rejected = self._append(
                str(after.game_id),
                "action.rejected_by_environment",
                {
                    "submitted_event_id": pending.submitted_event_id,
                    "consequence_event_id": consequence_id,
                    "observation_event_id": observation_receipt.observation_event_id,
                    "expected_action": _action_payload(pending.action),
                    "returned_action": _action_payload(actual_action),
                    "fault": "returned action identity mismatch",
                    "recovery": "fault with returned observation retained; do not replay stale action",
                },
            )
            self._fault_count += 1
            self._latest_observation = after
            self._latest_receipt = observation_receipt
            self._latest_view = view
            self._pending_action = None
            self._pending_prediction = None
            self._restored_prediction_state_ids = ()
            self._restored_prediction_plan_ids = ()
            self._before_action_observation = None
            self._before_action_state = None
            self._before_action_features = None
            self._pending_plan_emission = False
            self._plan_executor = PlanExecutor()
            self._phase = ControllerPhase.FAULTED
            if self.features.use_memory:
                self._last_checkpoint = self.checkpoint()
            raise PolicyError(
                "returned consequence does not match the pending action; "
                f"raw receipt preserved as {rejected.event_id}"
            )

        effect = classify_effect(before, after, pending.action)
        self._exploration.record_outcome(before_context, pending.action, effect)

        matched_prediction: bool | None = None
        reopened_models: tuple[str, ...] = ()
        invalidated_plans: set[str] = set()
        if self._pending_prediction is not None:
            assessment = self._prediction_book.match(
                self._pending_prediction.receipt_id, observed_state
            )
            matched_prediction = assessment.matched_any
            reopened_models = tuple(item.model_id for item in assessment.reopenings)
            invalidated_plans.update(
                plan_id for item in assessment.reopenings for plan_id in item.invalidated_plan_ids
            )
            event_type = (
                "consequence.matched_prediction"
                if assessment.matched_any
                else "consequence.mismatched_prediction"
            )
            self._append(
                str(after.game_id),
                event_type,
                assessment.to_dict(),
            )
        elif self._restored_prediction_state_ids:
            matched_prediction = observed_state.state_id in self._restored_prediction_state_ids
            if not matched_prediction:
                invalidated_plans.update(self._restored_prediction_plan_ids)
            self._append(
                str(after.game_id),
                (
                    "consequence.matched_prediction"
                    if matched_prediction
                    else "consequence.mismatched_prediction"
                ),
                {
                    "restored_pending_action": True,
                    "expected_state_ids": list(self._restored_prediction_state_ids),
                    "observed_state_id": observed_state.state_id,
                    "prediction_ids": list(pending.prediction_ids),
                    "invalidated_plan_ids": list(self._restored_prediction_plan_ids),
                    "revision": "deterministic replan after restored pending consequence",
                },
            )

        if self._pending_plan_emission:
            planning_consequence = self._plan_executor.apply_consequence(
                observed_state,
                game_state=after.state,
                undo_supported=self._exploration.statistics.supported_undo,
                same_model_viable=matched_prediction is not False,
            )
            if planning_consequence.recovery is not None:
                invalidated_plans.add(planning_consequence.plan_id)
            if not self.features.use_planner_recovery and not planning_consequence.matched:
                self._planning_disabled_after_mismatch = True
            self._pending_plan_emission = False

        if pending.action.name is not ActionName.RESET:
            transition = PreservedTransition(
                transition_id=f"transition:{pending.submitted_event_id}",
                before=before_state,
                action=pending.action,
                after=observed_state,
                source_event_ids=(
                    pending.selected_event_id,
                    pending.submitted_event_id,
                    consequence_id,
                    observation_receipt.observation_event_id,
                ),
            )
            self._transitions.append(transition)
            self._transition_levels[transition.transition_id] = previous_level
            self._transition_summaries.setdefault(previous_level, []).append(transition)
            if self.features.use_hypotheses:
                self._update_action_hypothesis(after, transition, consequence_id)

        progress_ids: tuple[str, ...] = ()
        if self.features.use_goals:
            acquisition = self._goal_acquirer.observe_transition(
                GoalTransition(
                    before=before,
                    after=after,
                    before_event_ids=(
                        self._latest_receipt.observation_event_id
                        if self._latest_receipt is not None
                        else pending.selected_event_id,
                    ),
                    after_event_ids=(consequence_id, observation_receipt.observation_event_id),
                    step=self._step_index,
                    level_scope_ref=f"level:{after.levels_completed}",
                    game_scope_ref="game:opaque-current-run",
                )
            )
            progress_ids = tuple(item.evidence.evidence_id for item in acquisition.progress_signals)
            if acquisition.progress_signals:
                self._append(
                    str(after.game_id),
                    "consequence.progress_detected",
                    {
                        "signal_ids": list(progress_ids),
                        "signal_kinds": [item.kind.value for item in acquisition.progress_signals],
                        "source_consequence_event_id": consequence_id,
                    },
                )
            if self._active_goal_id is not None and after.state is GameStateName.WIN:
                self._goal_acquirer.record_goal_test(
                    self._active_goal_id,
                    GoalTransition(
                        before=before,
                        after=after,
                        before_event_ids=(pending.selected_event_id,),
                        after_event_ids=(consequence_id,),
                        step=self._step_index,
                        level_scope_ref=f"level:{after.levels_completed}",
                        game_scope_ref="game:opaque-current-run",
                    ),
                    target_condition_reached=True,
                )
            self._flush_goal_events(after)

        self._latest_observation = after
        self._latest_receipt = observation_receipt
        self._latest_view = view
        self._pending_action = None
        self._pending_prediction = None
        self._restored_prediction_state_ids = ()
        self._restored_prediction_plan_ids = ()
        self._before_action_observation = None
        self._before_action_state = None
        self._before_action_features = None
        self._phase_from_observation(after)
        if after.levels_completed != previous_level:
            self._rotate_level_scope(
                after,
                observation_receipt,
                view,
                previous_level=previous_level,
                consequence_event_id=consequence_id,
            )
        if self.features.use_world_model and after.state is not GameStateName.WIN:
            self._update_world_models(after)
        if self.features.use_memory:
            self._last_checkpoint = self.checkpoint()
        return ConsequenceReceipt(
            consequence_event_id=consequence_id,
            consequence_event_hash=consequence_hash,
            observation_receipt=observation_receipt,
            matched_prediction=matched_prediction,
            reopened_model_ids=reopened_models,
            invalidated_plan_ids=tuple(sorted(invalidated_plans)),
            progress_signal_ids=progress_ids,
            phase=self._phase,
        )

    def _rotate_level_scope(
        self,
        observation: Observation,
        receipt: ObservationReceipt,
        view: _PerceptionView,
        *,
        previous_level: int,
        consequence_event_id: str,
    ) -> None:
        """Close one level's derived claims and seed a separate next-level scope."""

        sources = (consequence_event_id, receipt.observation_event_id)
        transition_event_type = (
            "consequence.level_completed"
            if self._level_index > previous_level
            else "observation.metadata_changed"
        )
        self._append(
            str(observation.game_id),
            transition_event_type,
            {
                "source_consequence_event_id": consequence_event_id,
                "source_observation_event_id": receipt.observation_event_id,
                "previous_level_index": previous_level,
                "new_level_index": self._level_index,
                "transition_kind": (
                    "level-progressed"
                    if self._level_index > previous_level
                    else "level-index-reopened-or-reset"
                ),
                "history_policy": "retain prior scope; do not apply it to the new level",
            },
        )

        previous_scope = f"level:{previous_level}"
        old_hypotheses = {
            record.statement.action: record.hypothesis_id
            for record in self._hypotheses.all()
            if isinstance(record.statement, ActionSemanticsStatement)
            and record.scope is HypothesisScope.LEVEL
            and record.scope_ref == previous_scope
            and record.status not in {HypothesisStatus.REJECTED, HypothesisStatus.SUPERSEDED}
        }
        for record in self._goals.records(include_retired=False):
            if (
                record.candidate.scope is HypothesisScope.LEVEL
                and record.candidate.scope_ref == previous_scope
            ):
                self._goals.retire(
                    record.candidate.goal_id,
                    source_event_ids=sources,
                    summary="level scope closed by an observed level transition",
                )
                if self._active_goal_id == record.candidate.goal_id:
                    self._active_goal_id = None
        self._flush_goal_events(observation)

        self._ensemble = None
        self._model_candidates = ()
        self._provisional_mover_id = None
        self._planning_disabled_after_mismatch = False
        if observation.state is GameStateName.WIN:
            return

        seeded = self._seed_directional_hypotheses(receipt, view)
        for action, old_id in sorted(old_hypotheses.items()):
            new_id = seeded.get(ActionName(action))
            if new_id is None or new_id == old_id:
                continue
            self._hypotheses.supersede(
                old_id,
                new_id,
                occurred_step=self._step_index,
                caused_by_event_ids=sources,
                note="prior level scope closed; successor remains a fresh candidate",
            )
            event = self._hypotheses.events[-1]
            self._append(str(observation.game_id), event.event_type.value, event.to_trace_payload())
        if self.features.use_goals:
            self._seed_contact_goal(observation, receipt, view)

    def _update_action_hypothesis(
        self,
        observation: Observation,
        transition: PreservedTransition,
        consequence_event_id: str,
    ) -> None:
        matching = tuple(
            record
            for record in self._hypotheses.all()
            if isinstance(record.statement, ActionSemanticsStatement)
            and record.statement.action == transition.action.name.value
            and record.scope_ref == f"level:{self._transition_levels[transition.transition_id]}"
            and record.status not in {HypothesisStatus.REJECTED, HypothesisStatus.SUPERSEDED}
            and (self.features.retain_rejected_hypotheses or not record.contradiction_receipts)
        )
        for record in matching:
            compiled = compile_hypotheses((record,))
            if not compiled.candidates:
                continue
            artifact = retrodict(compiled.candidates[0], (transition,))
            if artifact.promotable:
                evidence = EvidenceReceipt(
                    receipt_id=f"evidence:support:{transition.transition_id}",
                    kind=EvidenceKind.SUPPORT,
                    evidence_event_ids=(consequence_event_id,),
                    summary="executable action rule matched the preserved transition",
                    observed_step=self._step_index,
                    rank_impact=1,
                )
                updated = self._hypotheses.support(record.hypothesis_id, evidence)
                event_type = "hypothesis.supported"
            else:
                evidence = EvidenceReceipt(
                    receipt_id=f"evidence:contradiction:{transition.transition_id}",
                    kind=EvidenceKind.CONTRADICTION,
                    evidence_event_ids=(consequence_event_id,),
                    summary="executable action rule mismatched the preserved transition",
                    observed_step=self._step_index,
                    rank_impact=1,
                )
                updated = self._hypotheses.contradict(record.hypothesis_id, evidence)
                event_type = "hypothesis.contradicted"
            self._append(
                str(observation.game_id),
                event_type,
                {
                    "hypothesis_id": updated.hypothesis_id,
                    "evidence_receipt": evidence.to_dict(),
                    "status": updated.status.value,
                    "rank_weight": updated.rank_weight,
                    "weight_kind": "uncalibrated_rank",
                },
            )

    def checkpoint(self) -> ControllerCheckpoint:
        """Write a hash-bound snapshot at the current immutable trace tail."""

        if self._checkpoint_manager is None or self._code is None:
            raise PolicyError("controller checkpoint identity is unavailable")
        latest = self._latest_observation
        normalized_hash = (
            str(latest.frames[-1].digest)
            if latest is not None
            else sha256_json({"controller": "unobserved"})
        )
        memory_phase = (
            MemoryControllerPhase.AWAITING_CONSEQUENCE
            if self._phase is ControllerPhase.AWAITING_CONSEQUENCE
            else MemoryControllerPhase.GAME_OVER
            if self._phase is ControllerPhase.GAME_OVER
            else MemoryControllerPhase.READY
        )
        perception_state: dict[str, JSONValue] = {
            "latest_observation": self._serialize_observation(latest) if latest else None,
            "latest_observation_event_id": (
                self._latest_receipt.observation_event_id if self._latest_receipt else None
            ),
            "provisional_mover_id": self._provisional_mover_id,
        }
        state = DerivedControllerState(
            normalized_state_hash=normalized_hash,
            level_index=self._level_index,
            step_index=self._step_index,
            phase=memory_phase,
            perception_state=perception_state,
            action_semantics={
                "actions_used": self._actions_used,
                "resets_used": self._resets_used,
                "fault_count": self._fault_count,
                "action_counts": [
                    {"action": _action_payload(action), "count": count}
                    for action, count in sorted(
                        self._action_counts.items(),
                        key=lambda item: (
                            item[0].name.value,
                            repr(item[0].coordinate),
                        ),
                    )
                ],
            },
            hypothesis_registry=self._hypotheses.to_dict(),
            world_model_ensemble={
                "active_model_ids": (
                    [item.model_id for item in self._ensemble.candidates]
                    if self._ensemble is not None
                    else []
                ),
                "preserved_transitions": [
                    self._serialize_transition(item) for item in self._transitions
                ],
            },
            goal_registry={
                "active_goal_id": self._active_goal_id,
                "lifecycle_event_count": (
                    self._goal_event_sequence_offset + len(self._goals.events)
                ),
                "goal_targets": {
                    key: list(value) for key, value in sorted(self._goal_targets.items())
                },
                "records": [
                    {
                        "goal_id": item.candidate.goal_id,
                        "kind": item.candidate.kind.value,
                        "status": item.status.value,
                        "rank": item.rank,
                        "candidate": {
                            "goal_id": item.candidate.goal_id,
                            "kind": item.candidate.kind.value,
                            "role": item.candidate.role.value,
                            "scope": item.candidate.scope.value,
                            "scope_ref": item.candidate.scope_ref,
                            "target_state": item.candidate.target_state,
                            "source_evidence": [
                                self._serialize_goal_evidence(evidence)
                                for evidence in item.candidate.source_evidence
                            ],
                            "created_step": item.candidate.created_step,
                            "initial_rank": item.candidate.initial_rank,
                        },
                        "evidence": [
                            self._serialize_goal_evidence(evidence) for evidence in item.evidence
                        ],
                        "retirement": self._goal_retirement_payload(item.candidate.goal_id),
                    }
                    for item in self._goals.records()
                ],
            },
            explored_state_graph={
                "coordinate_count": len(self._explored_coordinates),
                "coordinates": [[item.x, item.y] for item in sorted(self._explored_coordinates)],
            },
            planner_state={
                "controller_features": self.features.to_dict(),
                "plan": (
                    self._serialize_plan(self._plan_executor.plan)
                    if self._plan_executor.plan is not None
                    else None
                ),
                "cursor": self._plan_executor.cursor,
                "pending_plan_emission": self._pending_plan_emission,
                "planning_disabled_after_mismatch": self._planning_disabled_after_mismatch,
                "pending_prediction": (
                    self._pending_prediction.to_dict()
                    if self._pending_prediction is not None
                    else None
                ),
                "restored_prediction_state_ids": list(self._restored_prediction_state_ids),
                "restored_prediction_plan_ids": list(self._restored_prediction_plan_ids),
                "controller_phase": self._phase.value,
                "restart_policy": "restore pending emission exactly; otherwise replan",
            },
            memory=self._memory,
            pending_action=self._pending_action,
            unresolved_residuals=(),
        )
        path, envelope = self._checkpoint_manager.write(
            journal=self.journal,
            episode_id=self.context.episode_id,
            code_identity=self._code,
            rng=self._rng,
            state=state,
        )
        return ControllerCheckpoint(path, envelope, self._phase)

    @classmethod
    def restore(
        cls,
        context: RunContext,
        *,
        preset: ControllerPreset | str = ControllerPreset.FULL,
        checkpoint_path: str | Path | None = None,
        features: PresetFeatures | None = None,
    ) -> ARC3Controller:
        """Restore a compatible checkpoint without emitting a pending action again."""

        controller = cls(preset, features=features)
        controller._initialize_context(context)
        if controller._checkpoint_manager is None or controller._code is None:
            raise PolicyError("checkpoint manager did not initialize")
        restored = controller._checkpoint_manager.restore(
            journal=controller.journal,
            episode_id=context.episode_id,
            code_identity=controller._code,
            path=checkpoint_path,
        )
        state = restored.state
        controller._rng = restored.rng
        controller._step_index = state.step_index
        controller._level_index = state.level_index
        controller._memory = state.memory
        controller._restore_action_counts(state.action_semantics)
        controller._hypotheses = HypothesisRegistry.from_dict(
            cast(Mapping[str, object], state.hypothesis_registry)
        )
        controller._pending_action = state.pending_action
        controller._provisional_mover_id = cast(
            str | None, state.perception_state.get("provisional_mover_id")
        )
        raw_observation = state.perception_state.get("latest_observation")
        if raw_observation is not None:
            controller._latest_observation = controller._deserialize_observation(raw_observation)
            controller._before_action_observation = controller._latest_observation
            frame = controller._latest_observation.frames[-1]
            background = Counter(cell for row in frame.cells for cell in row).most_common(1)[0][0]
            components = extract_components(
                frame, config=ComponentConfig(background_candidates=(background,))
            )
            symbolic, mapping = _symbolic_state(frame, components)
            controller._component_to_entity = mapping
            controller._latest_view = _PerceptionView(components, symbolic, None, None, ())
            controller._before_action_state = symbolic
            controller._before_action_features = ProbeContext(
                state=state_features(controller._latest_observation),
                actions_used=min(controller._actions_used, context.config.budgets.max_actions),
                action_budget=context.config.budgets.max_actions,
            )
        latest_event_id = state.perception_state.get("latest_observation_event_id")
        if isinstance(latest_event_id, str):
            source_event = controller.journal.get_event(latest_event_id)
            if source_event is not None and controller._latest_observation is not None:
                controller._latest_receipt = ObservationReceipt(
                    source_event.event_id,
                    source_event.event_hash,
                    tuple(str(frame.digest) for frame in controller._latest_observation.frames),
                    (),
                )
        controller._restore_world_state(state.world_model_ensemble)
        controller._restore_goal_state(state.goal_registry)
        controller._restore_explored_state(state.explored_state_graph)
        controller._phase = controller._restore_controller_phase(state)
        controller._restore_planner_state(state.planner_state)
        controller._last_checkpoint = ControllerCheckpoint(
            Path(checkpoint_path)
            if checkpoint_path is not None
            else controller._checkpoint_manager.store.latest_path,
            restored.envelope,
            controller._phase,
        )
        return controller

    def _restore_action_counts(self, value: Mapping[str, JSONValue]) -> None:
        raw = value.get("action_counts", [])
        if not isinstance(raw, list):
            raise PolicyError("checkpoint action_counts must be an array")
        for item in raw:
            if not isinstance(item, dict):
                continue
            action_value = item.get("action")
            count = item.get("count")
            if not isinstance(action_value, dict) or not isinstance(count, int):
                continue
            try:
                action = self._action_from_value(action_value)
            except (ValueError, KeyError):
                continue
            self._action_counts[action] = count
        actions_used = value.get("actions_used")
        resets_used = value.get("resets_used")
        fault_count = value.get("fault_count")
        for name, item in (
            ("actions_used", actions_used),
            ("resets_used", resets_used),
            ("fault_count", fault_count),
        ):
            if isinstance(item, bool) or not isinstance(item, int) or item < 0:
                raise PolicyError(f"checkpoint {name} is malformed")
        self._actions_used = cast(int, actions_used)
        self._resets_used = cast(int, resets_used)
        self._fault_count = cast(int, fault_count)
        counted_actions = sum(
            count
            for action, count in self._action_counts.items()
            if action.name is not ActionName.RESET
        )
        counted_resets = sum(
            count
            for action, count in self._action_counts.items()
            if action.name is ActionName.RESET
        )
        if counted_actions != self._actions_used or counted_resets != self._resets_used:
            raise PolicyError("checkpoint action totals do not match the action-count ledger")

    def _restore_explored_state(self, value: Mapping[str, JSONValue]) -> None:
        raw_coordinates = value.get("coordinates")
        expected_count = value.get("coordinate_count")
        if not isinstance(raw_coordinates, list):
            raise PolicyError("checkpoint explored coordinates must be an array")
        if isinstance(expected_count, bool) or not isinstance(expected_count, int):
            raise PolicyError("checkpoint explored coordinate count is malformed")
        restored: set[Coordinate] = set()
        for raw in raw_coordinates:
            if not isinstance(raw, list) or len(raw) != 2:
                raise PolicyError("checkpoint explored coordinate is malformed")
            x, y = raw
            if (
                isinstance(x, bool)
                or not isinstance(x, int)
                or isinstance(y, bool)
                or not isinstance(y, int)
            ):
                raise PolicyError("checkpoint explored coordinate values must be integers")
            restored.add(Coordinate(x, y))
        if len(restored) != expected_count:
            raise PolicyError("checkpoint explored coordinate count does not match its values")
        self._explored_coordinates = restored

    def _restore_controller_phase(self, state: DerivedControllerState) -> ControllerPhase:
        raw_phase = state.planner_state.get("controller_phase")
        if not isinstance(raw_phase, str):
            raise PolicyError("checkpoint exact controller phase is missing")
        try:
            phase = ControllerPhase(raw_phase)
        except ValueError as error:
            raise PolicyError("checkpoint exact controller phase is invalid") from error
        if phase is ControllerPhase.CLOSED:
            raise PolicyError("a closed controller phase cannot be resumed")
        expected_memory_phase = (
            MemoryControllerPhase.AWAITING_CONSEQUENCE
            if phase is ControllerPhase.AWAITING_CONSEQUENCE
            else MemoryControllerPhase.GAME_OVER
            if phase is ControllerPhase.GAME_OVER
            else MemoryControllerPhase.READY
        )
        if state.phase is not expected_memory_phase:
            raise PolicyError("checkpoint controller phases disagree")
        observation = self._latest_observation
        if phase is ControllerPhase.NEW and observation is not None:
            raise PolicyError("new checkpoint phase cannot contain an observation")
        if (
            phase
            in {
                ControllerPhase.OBSERVED,
                ControllerPhase.AWAITING_CONSEQUENCE,
                ControllerPhase.GAME_OVER,
                ControllerPhase.COMPLETE,
            }
            and observation is None
        ):
            raise PolicyError("checkpoint phase requires a current observation")
        if phase is ControllerPhase.COMPLETE and observation is not None:
            if observation.state is not GameStateName.WIN:
                raise PolicyError("complete checkpoint phase requires a winning observation")
        if phase is ControllerPhase.GAME_OVER and observation is not None:
            if observation.state is not GameStateName.GAME_OVER:
                raise PolicyError("game-over checkpoint phase requires a game-over observation")
        return phase

    def _restore_planner_state(self, value: Mapping[str, JSONValue]) -> None:
        raw_features = value.get("controller_features")
        if raw_features is not None and raw_features != self.features.to_dict():
            raise PolicyError("checkpoint controller feature identity does not match")
        planning_disabled = value.get("planning_disabled_after_mismatch", False)
        if not isinstance(planning_disabled, bool):
            raise PolicyError("checkpoint planner-recovery ablation marker is malformed")
        self._planning_disabled_after_mismatch = planning_disabled
        pending_plan = value.get("pending_plan_emission")
        if not isinstance(pending_plan, bool):
            raise PolicyError("checkpoint pending-plan marker is malformed")
        raw_state_ids = value.get("restored_prediction_state_ids", [])
        raw_plan_ids = value.get("restored_prediction_plan_ids", [])
        if (
            not isinstance(raw_state_ids, list)
            or not all(isinstance(item, str) for item in raw_state_ids)
            or not isinstance(raw_plan_ids, list)
            or not all(isinstance(item, str) for item in raw_plan_ids)
        ):
            raise PolicyError("checkpoint restored prediction identifiers are malformed")
        self._restored_prediction_state_ids = tuple(cast(list[str], raw_state_ids))
        self._restored_prediction_plan_ids = tuple(cast(list[str], raw_plan_ids))

        raw_plan = value.get("plan")
        if pending_plan:
            if (
                self._phase is not ControllerPhase.AWAITING_CONSEQUENCE
                or self._pending_action is None
                or self._before_action_state is None
                or self._latest_observation is None
                or not isinstance(raw_plan, Mapping)
            ):
                raise PolicyError("checkpoint pending plan lacks its action boundary")
            plan = self._deserialize_plan(raw_plan)
            self._plan_executor.load(plan)
            emission = self._plan_executor.next_action(
                self._before_action_state,
                model_id=plan.model_id,
                goal_id=plan.goal_id,
                goal_revision=plan.goal_revision,
                game_state=self._latest_observation.state,
            )
            if (
                not isinstance(emission, ActionEmission)
                or emission.action != self._pending_action.action
            ):
                raise PolicyError("checkpoint pending plan does not reproduce its submitted action")
            self._pending_plan_emission = True
        elif self._phase is not ControllerPhase.AWAITING_CONSEQUENCE and raw_plan is not None:
            # No environment action depends on this stale cursor.  The next
            # decision deterministically searches again from its observation.
            self._plan_executor = PlanExecutor()

        raw_prediction = value.get("pending_prediction")
        if raw_prediction is None:
            if self._pending_action is not None and self._pending_action.prediction_ids:
                if not self._restored_prediction_state_ids:
                    raise PolicyError("checkpoint pending prediction has no restorable outcomes")
            return
        if (
            not isinstance(raw_prediction, Mapping)
            or self._phase is not ControllerPhase.AWAITING_CONSEQUENCE
            or self._pending_action is None
            or self._before_action_state is None
            or self._ensemble is None
        ):
            raise PolicyError("checkpoint pending prediction lacks its model boundary")
        action_decision_id = raw_prediction.get("action_decision_id")
        raw_dependencies = raw_prediction.get("dependent_plan_ids")
        if (
            not isinstance(action_decision_id, str)
            or not isinstance(raw_dependencies, list)
            or not all(isinstance(item, str) for item in raw_dependencies)
        ):
            raise PolicyError("checkpoint pending prediction identity is malformed")
        rebuilt = self._prediction_book.emit(
            action_decision_id=action_decision_id,
            ensemble=self._ensemble,
            state=self._before_action_state,
            action=self._pending_action.action,
            dependent_plan_ids=tuple(cast(list[str], raw_dependencies)),
        )
        if rebuilt.to_dict() != dict(raw_prediction):
            raise PolicyError("checkpoint pending prediction does not reproduce exactly")
        self._pending_prediction = rebuilt
        self._restored_prediction_state_ids = tuple(
            item.after_state_id for item in rebuilt.prediction.alternatives
        )
        self._restored_prediction_plan_ids = rebuilt.dependent_plan_ids

    def _restore_world_state(self, value: Mapping[str, JSONValue]) -> None:
        raw = value.get("preserved_transitions", [])
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, dict):
                    transition = self._deserialize_transition(item)
                    level_index = item.get("level_index")
                    if isinstance(level_index, bool) or not isinstance(level_index, int):
                        raise PolicyError("checkpoint transition level is malformed")
                    self._transitions.append(transition)
                    self._transition_levels[transition.transition_id] = level_index
                    self._transition_summaries.setdefault(level_index, []).append(transition)
        current_scope = f"level:{self._level_index}"
        eligible = tuple(
            record
            for record in self._hypotheses.all()
            if record.scope is not HypothesisScope.LEVEL or record.scope_ref == current_scope
            if self.features.retain_rejected_hypotheses
            or (
                record.status is not HypothesisStatus.REJECTED and not record.contradiction_receipts
            )
        )
        compiled = compile_hypotheses(eligible)
        self._model_candidates = compiled.candidates
        level_transitions = (
            tuple(self._transition_summaries.get(self._level_index, ()))
            if self.features.use_trace_summaries
            else tuple(
                item
                for item in self._transitions
                if self._transition_levels.get(item.transition_id) == self._level_index
            )
        )
        artifacts = tuple(
            retrodict(
                candidate,
                level_transitions,
                enabled=self.features.use_retrodiction_gate,
            )
            for candidate in compiled.candidates
        )
        if any(
            artifact.status is PromotionStatus.PROMOTED
            or (
                not self.features.use_retrodiction_gate
                and artifact.status is PromotionStatus.UNGATED_ABLATION
            )
            for artifact in artifacts
        ):
            self._ensemble = gated_ensemble(
                compiled.candidates,
                artifacts,
                allow_ungated_ablation=not self.features.use_retrodiction_gate,
            )

    def _restore_goal_state(self, value: Mapping[str, JSONValue]) -> None:
        raw_records = value.get("records", [])
        if isinstance(raw_records, list):
            for raw_record in raw_records:
                if not isinstance(raw_record, dict):
                    continue
                raw_candidate = raw_record.get("candidate")
                if not isinstance(raw_candidate, dict):
                    continue
                candidate = self._deserialize_goal_candidate(raw_candidate)
                self._goals.register(candidate)
                source_ids = {evidence.evidence_id for evidence in candidate.source_evidence}
                raw_evidence = raw_record.get("evidence", [])
                if not isinstance(raw_evidence, list):
                    raise PolicyError("checkpoint goal evidence must be an array")
                for raw_item in raw_evidence:
                    evidence = self._deserialize_goal_evidence(raw_item)
                    if evidence.evidence_id in source_ids:
                        continue
                    if evidence.direction is EvidenceDirection.SUPPORT:
                        self._goals.support(candidate.goal_id, evidence)
                    else:
                        self._goals.contradict(candidate.goal_id, evidence)
                restored = self._goals.get(candidate.goal_id)
                expected_rank = raw_record.get("rank")
                expected_status = raw_record.get("status")
                if expected_status == "retired" and restored.status.value != "retired":
                    retirement = raw_record.get("retirement")
                    if not isinstance(retirement, dict):
                        raise PolicyError("checkpoint retired goal lacks retirement evidence")
                    raw_sources = retirement.get("source_event_ids")
                    summary = retirement.get("summary")
                    if (
                        not isinstance(raw_sources, list)
                        or not all(isinstance(item, str) for item in raw_sources)
                        or not isinstance(summary, str)
                    ):
                        raise PolicyError("checkpoint goal retirement is malformed")
                    restored = self._goals.retire(
                        candidate.goal_id,
                        source_event_ids=tuple(cast(list[str], raw_sources)),
                        summary=summary,
                    )
                if expected_rank != restored.rank or expected_status != restored.status.value:
                    raise PolicyError(
                        f"checkpoint goal state does not replay exactly: {candidate.goal_id}"
                    )
        original_event_count = value.get("lifecycle_event_count", len(self._goals.events))
        if (
            isinstance(original_event_count, bool)
            or not isinstance(original_event_count, int)
            or original_event_count < len(self._goals.events)
        ):
            raise PolicyError("checkpoint goal lifecycle count is invalid")
        self._goal_event_sequence_offset = original_event_count - len(self._goals.events)
        self._traced_goal_events = len(self._goals.events)
        self._goal_acquirer = GoalAcquirer(self._goals)

        active = value.get("active_goal_id")
        known_goal_ids = {item.candidate.goal_id for item in self._goals.records()}
        self._active_goal_id = (
            active if isinstance(active, str) and active in known_goal_ids else None
        )
        raw = value.get("goal_targets", {})
        if isinstance(raw, dict):
            for key, target in raw.items():
                if (
                    isinstance(key, str)
                    and isinstance(target, list)
                    and len(target) == 2
                    and all(isinstance(item, str) for item in target)
                ):
                    self._goal_targets[key] = (cast(str, target[0]), cast(str, target[1]))

    def _goal_retirement_payload(self, goal_id: str) -> dict[str, JSONValue] | None:
        for event in reversed(self._goals.events):
            if event.goal_id == goal_id and event.event_type.value == "goal.retired":
                return {
                    "source_event_ids": list(event.source_event_ids),
                    "summary": event.summary,
                }
        return None

    @staticmethod
    def _serialize_goal_evidence(evidence: GoalEvidence) -> dict[str, JSONValue]:
        return {
            "evidence_id": evidence.evidence_id,
            "direction": evidence.direction.value,
            "source_event_ids": list(evidence.source_event_ids),
            "observed_step": evidence.observed_step,
            "level_index": evidence.level_index,
            "summary": evidence.summary,
            "rank_impact": evidence.rank_impact,
        }

    @staticmethod
    def _deserialize_goal_evidence(value: object) -> GoalEvidence:
        if not isinstance(value, Mapping):
            raise PolicyError("checkpoint goal evidence must be an object")
        sources = value.get("source_event_ids")
        observed_step = value.get("observed_step")
        level_index = value.get("level_index")
        rank_impact = value.get("rank_impact")
        if (
            not isinstance(sources, list)
            or not all(isinstance(item, str) for item in sources)
            or isinstance(observed_step, bool)
            or not isinstance(observed_step, int)
            or isinstance(level_index, bool)
            or not isinstance(level_index, int)
            or isinstance(rank_impact, bool)
            or not isinstance(rank_impact, int)
        ):
            raise PolicyError("checkpoint goal evidence fields are malformed")
        try:
            direction = EvidenceDirection(str(value.get("direction")))
            return GoalEvidence(
                evidence_id=str(value.get("evidence_id")),
                direction=direction,
                source_event_ids=tuple(cast(list[str], sources)),
                observed_step=observed_step,
                level_index=level_index,
                summary=str(value.get("summary")),
                rank_impact=rank_impact,
            )
        except ValueError as error:
            raise PolicyError("checkpoint goal evidence is invalid") from error

    @classmethod
    def _deserialize_goal_candidate(cls, value: Mapping[str, object]) -> GoalCandidate:
        raw_sources = value.get("source_evidence")
        created_step = value.get("created_step")
        initial_rank = value.get("initial_rank")
        if (
            not isinstance(raw_sources, list)
            or isinstance(created_step, bool)
            or not isinstance(created_step, int)
            or isinstance(initial_rank, bool)
            or not isinstance(initial_rank, int)
        ):
            raise PolicyError("checkpoint goal candidate fields are malformed")
        try:
            return GoalCandidate(
                goal_id=str(value.get("goal_id")),
                kind=GoalKind(str(value.get("kind"))),
                role=GoalRole(str(value.get("role"))),
                scope=HypothesisScope(str(value.get("scope"))),
                scope_ref=str(value.get("scope_ref")),
                target_state=str(value.get("target_state")),
                source_evidence=tuple(cls._deserialize_goal_evidence(item) for item in raw_sources),
                created_step=created_step,
                initial_rank=initial_rank,
            )
        except ValueError as error:
            raise PolicyError("checkpoint goal candidate is invalid") from error

    @staticmethod
    def _serialize_observation(observation: Observation) -> dict[str, JSONValue]:
        return {
            "game_id": str(observation.game_id),
            "frames": [[list(row) for row in frame.cells] for frame in observation.frames],
            "state": observation.state.value,
            "levels_completed": observation.levels_completed,
            "win_levels": observation.win_levels,
            "available_actions": [item.value for item in observation.available_actions],
            "full_reset": observation.full_reset,
            "returned_action": (
                _action_payload(observation.returned_action)
                if observation.returned_action is not None
                else None
            ),
            "upstream_session_id": observation.upstream_session_id,
            "upstream_metadata": [[key, value] for key, value in observation.upstream_metadata],
        }

    @classmethod
    def _deserialize_observation(cls, value: object) -> Observation:
        if not isinstance(value, Mapping):
            raise PolicyError("checkpoint observation must be an object")
        frames = value.get("frames")
        actions = value.get("available_actions")
        metadata = value.get("upstream_metadata", [])
        if (
            not isinstance(frames, list)
            or not isinstance(actions, list)
            or not isinstance(metadata, list)
        ):
            raise PolicyError("checkpoint observation arrays are malformed")
        normalized_frames: list[GridFrame] = []
        for frame in frames:
            if not isinstance(frame, list):
                raise PolicyError("checkpoint frame must be a row array")
            rows: list[list[int]] = []
            for row in frame:
                if not isinstance(row, list) or any(
                    isinstance(cell, bool) or not isinstance(cell, int) for cell in row
                ):
                    raise PolicyError("checkpoint frame cells must be integers")
                rows.append(cast(list[int], row))
            normalized_frames.append(GridFrame.from_rows(rows))
        returned = value.get("returned_action")
        try:
            game_state = GameStateName(str(value.get("state")))
            available = tuple(ActionName(str(item)) for item in actions)
        except ValueError as error:
            raise PolicyError("checkpoint observation enum is malformed") from error
        pairs: list[tuple[str, JSONScalar]] = []
        for item in metadata:
            if not isinstance(item, list) or len(item) != 2 or not isinstance(item[0], str):
                raise PolicyError("checkpoint observation metadata is malformed")
            scalar = item[1]
            if scalar is not None and not isinstance(scalar, (str, bool, int, float)):
                raise PolicyError("checkpoint metadata must remain scalar")
            pairs.append((item[0], scalar))
        levels = value.get("levels_completed")
        wins = value.get("win_levels")
        if isinstance(levels, bool) or not isinstance(levels, int):
            raise PolicyError("checkpoint levels_completed is malformed")
        if isinstance(wins, bool) or not isinstance(wins, int):
            raise PolicyError("checkpoint win_levels is malformed")
        return Observation(
            game_id=GameId(str(value.get("game_id"))),
            frames=tuple(normalized_frames),
            state=game_state,
            levels_completed=levels,
            win_levels=wins,
            available_actions=available,
            full_reset=bool(value.get("full_reset")),
            returned_action=(
                cls._action_from_value(returned) if isinstance(returned, Mapping) else None
            ),
            upstream_session_id=cast(str | None, value.get("upstream_session_id")),
            upstream_metadata=tuple(pairs),
        )

    @staticmethod
    def _action_from_value(value: Mapping[str, object]) -> ActionRequest:
        name = ActionName(str(value["name"]))
        coordinate_value = value.get("coordinate")
        coordinate: Coordinate | None = None
        if isinstance(coordinate_value, Mapping):
            x = coordinate_value.get("x")
            y = coordinate_value.get("y")
            if isinstance(x, bool) or not isinstance(x, int):
                raise ValueError("coordinate x is invalid")
            if isinstance(y, bool) or not isinstance(y, int):
                raise ValueError("coordinate y is invalid")
            coordinate = Coordinate(x, y)
        return ActionRequest(name, coordinate)

    @classmethod
    def _serialize_plan(cls, plan: Plan) -> dict[str, JSONValue]:
        return {
            "plan_id": plan.plan_id,
            "problem_id": plan.problem_id,
            "model_id": plan.model_id,
            "goal_id": plan.goal_id,
            "goal_revision": plan.goal_revision,
            "algorithm": plan.algorithm.value,
            "initial_state_id": plan.initial_state_id,
            "final_state_id": plan.final_state_id,
            "steps": [
                {
                    "index": step.index,
                    "action": _action_payload(step.action),
                    "before_state_id": step.before_state_id,
                    "predicted_state": step.predicted_state.to_dict(),
                    "cost": step.cost,
                    "failure_risk": step.failure_risk,
                    "information_value": step.information_value,
                }
                for step in plan.steps
            ],
            "score": {
                "completion_likelihood": plan.score.completion_likelihood,
                "action_count": plan.score.action_count,
                "total_cost": plan.score.total_cost,
                "total_risk": plan.score.total_risk,
                "total_information": plan.score.total_information,
                "utility": plan.score.utility,
                "likelihood_kind": plan.score.likelihood_kind,
            },
        }

    @classmethod
    def _deserialize_plan(cls, value: Mapping[str, object]) -> Plan:
        raw_steps = value.get("steps")
        raw_score = value.get("score")
        if not isinstance(raw_steps, list) or not isinstance(raw_score, Mapping):
            raise PolicyError("checkpoint plan arrays are malformed")
        steps: list[PlanStep] = []
        for raw_step in raw_steps:
            if not isinstance(raw_step, Mapping):
                raise PolicyError("checkpoint plan step is malformed")
            index = raw_step.get("index")
            action = raw_step.get("action")
            predicted_state = raw_step.get("predicted_state")
            before_state_id = raw_step.get("before_state_id")
            if (
                isinstance(index, bool)
                or not isinstance(index, int)
                or not isinstance(action, Mapping)
                or not isinstance(predicted_state, Mapping)
                or not isinstance(before_state_id, str)
            ):
                raise PolicyError("checkpoint plan step fields are malformed")
            steps.append(
                PlanStep(
                    index=index,
                    action=cls._action_from_value(action),
                    before_state_id=before_state_id,
                    predicted_state=cls._state_from_dict(predicted_state),
                    cost=cls._finite_number(raw_step.get("cost"), field="plan step cost"),
                    failure_risk=cls._finite_number(
                        raw_step.get("failure_risk"), field="plan step failure_risk"
                    ),
                    information_value=cls._finite_number(
                        raw_step.get("information_value"), field="plan step information_value"
                    ),
                )
            )
        action_count = raw_score.get("action_count")
        likelihood_kind = raw_score.get("likelihood_kind")
        if (
            isinstance(action_count, bool)
            or not isinstance(action_count, int)
            or not isinstance(likelihood_kind, str)
        ):
            raise PolicyError("checkpoint plan score fields are malformed")
        try:
            algorithm = SearchAlgorithm(str(value.get("algorithm")))
            return Plan(
                plan_id=str(value.get("plan_id")),
                problem_id=str(value.get("problem_id")),
                model_id=str(value.get("model_id")),
                goal_id=str(value.get("goal_id")),
                goal_revision=str(value.get("goal_revision")),
                algorithm=algorithm,
                initial_state_id=str(value.get("initial_state_id")),
                final_state_id=str(value.get("final_state_id")),
                steps=tuple(steps),
                score=PlanScore(
                    completion_likelihood=cls._finite_number(
                        raw_score.get("completion_likelihood"),
                        field="plan completion likelihood",
                    ),
                    action_count=action_count,
                    total_cost=cls._finite_number(
                        raw_score.get("total_cost"), field="plan total cost"
                    ),
                    total_risk=cls._finite_number(
                        raw_score.get("total_risk"), field="plan total risk"
                    ),
                    total_information=cls._finite_number(
                        raw_score.get("total_information"), field="plan total information"
                    ),
                    utility=cls._finite_number(raw_score.get("utility"), field="plan utility"),
                    likelihood_kind=likelihood_kind,
                ),
            )
        except ValueError as error:
            raise PolicyError("checkpoint plan enum is invalid") from error

    @staticmethod
    def _finite_number(value: object, *, field: str) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise PolicyError(f"checkpoint {field} must be numeric")
        result = float(value)
        if not math.isfinite(result):
            raise PolicyError(f"checkpoint {field} must be finite")
        return result

    @staticmethod
    def _state_from_dict(value: Mapping[str, object]) -> SymbolicState:
        width = value.get("width")
        height = value.get("height")
        raw_entities = value.get("entities", [])
        raw_facts = value.get("facts", [])
        raw_counters = value.get("counters", [])
        raw_toggles = value.get("toggles", [])
        raw_attachments = value.get("attachments", [])
        if (
            isinstance(width, bool)
            or not isinstance(width, int)
            or isinstance(height, bool)
            or not isinstance(height, int)
            or not isinstance(raw_entities, list)
            or not isinstance(raw_facts, list)
            or not all(isinstance(item, str) for item in raw_facts)
            or not isinstance(raw_counters, list)
            or not isinstance(raw_toggles, list)
            or not isinstance(raw_attachments, list)
        ):
            raise PolicyError("serialized symbolic state is malformed")
        entities: list[SymbolicEntity] = []
        for raw in raw_entities:
            if not isinstance(raw, Mapping):
                raise PolicyError("serialized entity is malformed")
            raw_cells = raw.get("cells", [])
            if not isinstance(raw_cells, list):
                raise PolicyError("serialized entity cells are malformed")
            cells: list[Cell] = []
            for item in raw_cells:
                if not isinstance(item, list) or len(item) != 2:
                    raise PolicyError("serialized cell is malformed")
                x, y = item
                if (
                    isinstance(x, bool)
                    or not isinstance(x, int)
                    or isinstance(y, bool)
                    or not isinstance(y, int)
                ):
                    raise PolicyError("serialized cell coordinates are malformed")
                cells.append(Cell(x, y))
            color = raw.get("color")
            if color is not None and (isinstance(color, bool) or not isinstance(color, int)):
                raise PolicyError("serialized entity color is malformed")
            raw_attributes = raw.get("attributes", [])
            if not isinstance(raw_attributes, list):
                raise PolicyError("serialized entity attributes are malformed")
            attributes: list[tuple[str, str]] = []
            for item in raw_attributes:
                if (
                    not isinstance(item, list)
                    or len(item) != 2
                    or not all(isinstance(part, str) for part in item)
                ):
                    raise PolicyError("serialized entity attribute is malformed")
                attributes.append((cast(str, item[0]), cast(str, item[1])))
            entities.append(
                SymbolicEntity(
                    entity_id=str(raw.get("entity_id")),
                    kind=str(raw.get("kind")),
                    cells=tuple(cells),
                    color=color,
                    attributes=tuple(attributes),
                )
            )
        counters: list[tuple[str, int]] = []
        for item in raw_counters:
            if (
                not isinstance(item, list)
                or len(item) != 2
                or not isinstance(item[0], str)
                or isinstance(item[1], bool)
                or not isinstance(item[1], int)
            ):
                raise PolicyError("serialized counter is malformed")
            counters.append((item[0], item[1]))
        toggles: list[tuple[str, str]] = []
        for item in raw_toggles:
            if (
                not isinstance(item, list)
                or len(item) != 2
                or not isinstance(item[0], str)
                or not isinstance(item[1], str)
            ):
                raise PolicyError("serialized toggle is malformed")
            toggles.append((item[0], item[1]))
        attachments: list[Attachment] = []
        for raw in raw_attachments:
            if not isinstance(raw, Mapping):
                raise PolicyError("serialized attachment is malformed")
            child = raw.get("child_id")
            parent = raw.get("parent_id")
            dx = raw.get("dx")
            dy = raw.get("dy")
            if (
                not isinstance(child, str)
                or not isinstance(parent, str)
                or isinstance(dx, bool)
                or not isinstance(dx, int)
                or isinstance(dy, bool)
                or not isinstance(dy, int)
            ):
                raise PolicyError("serialized attachment fields are malformed")
            attachments.append(Attachment(child, parent, dx, dy))
        selected_id = value.get("selected_id")
        if selected_id is not None and not isinstance(selected_id, str):
            raise PolicyError("serialized selected entity is malformed")
        return SymbolicState(
            width,
            height,
            tuple(entities),
            facts=tuple(cast(list[str], raw_facts)),
            counters=tuple(counters),
            toggles=tuple(toggles),
            selected_id=selected_id,
            attachments=tuple(attachments),
        )

    def _serialize_transition(self, value: PreservedTransition) -> dict[str, JSONValue]:
        return {
            "transition_id": value.transition_id,
            "before": value.before.to_dict(),
            "action": _action_payload(value.action),
            "after": value.after.to_dict(),
            "source_event_ids": list(value.source_event_ids),
            "level_index": self._transition_levels[value.transition_id],
        }

    @classmethod
    def _deserialize_transition(cls, value: Mapping[str, object]) -> PreservedTransition:
        before = value.get("before")
        after = value.get("after")
        action = value.get("action")
        sources = value.get("source_event_ids", [])
        if (
            not isinstance(before, Mapping)
            or not isinstance(after, Mapping)
            or not isinstance(action, Mapping)
            or not isinstance(sources, list)
            or not all(isinstance(item, str) for item in sources)
        ):
            raise PolicyError("serialized transition is malformed")
        return PreservedTransition(
            transition_id=str(value.get("transition_id")),
            before=cls._state_from_dict(before),
            action=cls._action_from_value(action),
            after=cls._state_from_dict(after),
            source_event_ids=tuple(cast(list[str], sources)),
        )

    def close(self) -> None:
        """Flush the trace without inventing a completion result."""

        if self._journal is None or self._phase is ControllerPhase.CLOSED:
            return
        if self._phase is not ControllerPhase.AWAITING_CONSEQUENCE:
            events = self.journal.verify_manifest()
            if not events or events[-1].event_type != "run.completed":
                self._append(
                    self.context.game_id,
                    "run.completed",
                    {
                        "final_phase": self._phase.value,
                        "steps": self._step_index,
                        "actions_used": self._actions_used,
                        "resets_used": self._resets_used,
                        "fault_count": self._fault_count,
                    },
                    scope="run",
                )
        # The durable restart point must bind the final trace tail, including
        # run.completed.  A pending action remains checkpointable because its
        # action.submitted receipt is intentionally left as the tail.
        checkpoint_is_current = (
            self._last_checkpoint is not None
            and self._last_checkpoint.envelope.trace_tail_event_id == self.journal.tail_event_id
            and self._last_checkpoint.envelope.trace_tail_hash == self.journal.tail_hash
        )
        if self.features.use_memory and not checkpoint_is_current:
            self._last_checkpoint = self.checkpoint()
        self.journal.close()
        self._phase = ControllerPhase.CLOSED


__all__ = ["ARC3Controller"]
