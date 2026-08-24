"""Integrated deterministic observation-model-plan-action ARC3 controller."""

from __future__ import annotations

import math
import random
from collections import Counter, deque
from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import asdict, dataclass, replace
from functools import wraps
from pathlib import Path
from typing import Literal, NoReturn, Protocol, TypeVar, cast

from arc3.adapters import GridFrame, Observation, validate_action_request
from arc3.adapters.interface_semantics import (
    OFFICIAL_COMPETITION_INTERFACE,
    InterfaceSemantics,
)
from arc3.config import derive_seed
from arc3.errors import (
    ARC3ValidationError,
    CheckpointError,
    CompetitionIntegrityError,
    PlanningError,
    PolicyError,
    WorldModelError,
)
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
from arc3.exploration.action_registry import (
    ActionEffectObservation,
    ActionEffectRegistry,
    ActionEffectStatus,
    CanonicalActionEffect,
    CanonicalEffectKind,
    CoordinateRelation,
    action_condition_signature,
)
from arc3.goals import (
    ActionGoalEstimate,
    EvidenceDirection,
    GoalAcquirer,
    GoalAcquisitionResult,
    GoalCandidate,
    GoalEvidence,
    GoalKind,
    GoalRegistry,
    GoalRole,
    GoalStatus,
    GoalTransition,
    IntrinsicExplorationUtility,
    ProgressSignal,
    detect_progress_signals,
    positive_external_progress,
    progress_snapshot,
    select_goal_action,
)
from arc3.hypotheses import (
    ActionSemanticsStatement,
    CollisionTraversabilityStatement,
    EvidenceKind,
    EvidenceReceipt,
    HypothesisRegistry,
    HypothesisScope,
)
from arc3.memory import (
    ControllerCheckpointManager,
    DerivedControllerState,
    MemoryContractError,
    PendingAction,
    PersistentMemory,
)
from arc3.memory import (
    ControllerPhase as MemoryControllerPhase,
)
from arc3.perception import (
    Component,
    ComponentChange,
    ComponentChangeKind,
    ComponentConfig,
    FrameDelta,
    PaletteRoleAssignment,
    PaletteRoleRegistry,
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
from arc3.trace import (
    CodeIdentity,
    EventJournal,
    SourceIdentity,
    TraceEvent,
    abandoned_event_ids,
    authoritative_events,
)
from arc3.trace.authority import is_revisable_interruption_event_type
from arc3.trace.canonical import normalize_json, sha256_json
from arc3.types import (
    ActionName,
    ActionRequest,
    Coordinate,
    DisplacementEvidenceKind,
    ExecutionMode,
    FrameHash,
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
    CollisionBehavior,
    CollisionRule,
    EnsemblePrediction,
    MatchedPredictionEvidence,
    MechanicsChangeCandidate,
    MechanicsChangeDomain,
    MechanicsChangeStatus,
    MechanicsLifecycle,
    ModelCandidate,
    MovementRule,
    NoOpRule,
    PredictionBook,
    PredictionReceipt,
    PreservedTransition,
    PromotionStatus,
    RetrodictionArtifact,
    RetrodictionConfig,
    RetrodictionEvaluation,
    RetrodictionMode,
    RetrodictionOmission,
    RetrodictionPlan,
    RetrodictionReason,
    RetrodictionRequest,
    RetrodictionRuntime,
    SymbolicEntity,
    SymbolicState,
    WorldModelEnsemble,
    compile_hypotheses,
    gated_ensemble,
    model_semantic_fingerprint,
    retrodict,
)
from arc3.world_model.rules import rule_action

from .cadence import (
    BoundedCanonicalLRU,
    CacheInvalidationReason,
    CacheValueKind,
    CadenceConfig,
    CadenceSelection,
    CadenceSignals,
    CadenceState,
    CanonicalCacheKey,
    DeliberationStatus,
    DerivedCacheValue,
    ModelCacheIdentity,
    ReasoningPath,
    select_reasoning_path,
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

_RETRODICTION_FORCE_FULL_EVENTS = frozenset(
    {
        "consequence.mismatched_prediction",
        "hypothesis.reopened",
        "mechanics.change_candidate_created",
        "mechanics.change_candidate_resolved",
        "mechanics.change_confirmed",
        "mechanics.epoch_opened",
        "model.rule_demoted",
    }
)
_HotPathChangeKindValue = Literal[
    "initial",
    "unchanged",
    "history_growth",
    "global_change",
]


class _HotPathProfiler(Protocol):
    """Structural profiling boundary kept independent of policy decisions."""

    @property
    def enabled(self) -> bool: ...

    def span(self, phase: str) -> AbstractContextManager[None]: ...

    def boundary(self, kind: str, *, actions: int) -> None: ...

    def cache(
        self,
        phase: str,
        hit: bool | None,
        *,
        input_key: str | None = None,
        change_kind: str | None = None,
    ) -> None: ...

    def summary(self, total_wall_ns: int | None = None) -> dict[str, JSONValue]: ...


_ControllerMethod = TypeVar("_ControllerMethod", bound=Callable[..., object])


def _profiled(
    phase: str,
    boundary_kind: str | None = None,
) -> Callable[[_ControllerMethod], _ControllerMethod]:
    """Measure a method only when an external profiler is explicitly enabled."""

    def decorate(method: _ControllerMethod) -> _ControllerMethod:
        @wraps(method)
        def measured(self: ARC3Controller, *args: object, **kwargs: object) -> object:
            profiler = self._hot_path_profiler
            if profiler is None or not profiler.enabled:
                return method(self, *args, **kwargs)
            with profiler.span(phase):
                result = method(self, *args, **kwargs)
            # Boundary telemetry intentionally runs after the measured policy
            # span so profiler/RSS overhead cannot be charged to policy work.
            if boundary_kind is not None:
                profiler.boundary(boundary_kind, actions=self._actions_used)
            return result

        return cast(_ControllerMethod, measured)

    return decorate


@dataclass(frozen=True, slots=True)
class _PerceptionView:
    components: tuple[Component, ...]
    symbolic_state: SymbolicState
    delta: FrameDelta | None
    tracking: TrackingResult | None
    measurement_event_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _ActionHypothesisUpdate:
    """Typed result of interpreting one preserved transition against live rules."""

    supported_hypothesis_ids: tuple[str, ...] = ()
    contradicted_hypothesis_ids: tuple[str, ...] = ()
    support_trace_event_ids: tuple[str, ...] = ()
    contradiction_trace_event_ids: tuple[str, ...] = ()
    created_hypothesis_ids: tuple[str, ...] = ()
    support_trace_event_pairs: tuple[tuple[str, str], ...] = ()
    contradiction_trace_event_pairs: tuple[tuple[str, str], ...] = ()
    destination_role_observation: _DestinationRoleObservation | None = None
    destination_role_supported_hypothesis_ids: tuple[str, ...] = ()
    destination_role_contradicted_hypothesis_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _DestinationRoleObservation:
    """Revisable destination-role interpretation from one preserved transition."""

    moving_kind: str
    obstacle_kind: str
    traversable: bool
    condition_signature: str
    discrimination_context_id: str


@dataclass(frozen=True, slots=True)
class _ControlledTranslationCandidate:
    """Typed direct displacement or unpromoted topology alternative."""

    translation: tuple[int, int]
    evidence_kind: DisplacementEvidenceKind


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


def _stable_entity_kind(component: Component, palette_role: PaletteRoleAssignment) -> str:
    digest = sha256_json(
        {"shape": component.translation_signature, "palette_role": palette_role.role_id}
    ).removeprefix("sha256:")[:12]
    return f"observed-component:{digest}"


def _symbolic_state(
    frame: GridFrame,
    components: tuple[Component, ...],
    palette_roles: PaletteRoleRegistry,
) -> tuple[SymbolicState, dict[str, str]]:
    """Interpret measured components while retaining deterministic local identity."""

    grouped: dict[tuple[str, str], list[Component]] = {}
    for component in components:
        identity_token = palette_roles.anonymous_identity(component.color)
        grouped.setdefault((identity_token, component.translation_signature), []).append(component)
    entities: list[SymbolicEntity] = []
    component_to_entity: dict[str, str] = {}
    for (identity_token, signature), group in sorted(grouped.items()):
        ordered = sorted(
            group,
            key=lambda item: (
                item.bounds.top,
                item.bounds.left,
                item.bounds.bottom,
                item.bounds.right,
            ),
        )
        shape_id = sha256_json({"shape": signature}).removeprefix("sha256:")[:12]
        identity_fragment = identity_token.removeprefix("palette-identity:").replace(":", "-")
        for ordinal, component in enumerate(ordered):
            palette_role = palette_roles.role_for(component.color)
            entity_id = f"entity:{identity_fragment}:{shape_id}:{ordinal}"
            component_to_entity[component.component_id] = entity_id
            entities.append(
                SymbolicEntity(
                    entity_id=entity_id,
                    kind=_stable_entity_kind(component, palette_role),
                    cells=tuple(Cell(point.x, point.y) for point in component.cells),
                    color=component.color,
                    attributes=(
                        ("palette_role", palette_role.role_id),
                        ("palette_role_ambiguity", str(palette_role.ambiguous).lower()),
                        ("palette_anonymous_identity", palette_role.identity_token),
                        ("shape", signature),
                    ),
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
        hot_path_profiler: _HotPathProfiler | None = None,
        retrodiction_config: RetrodictionConfig | None = None,
        cadence_config: CadenceConfig | None = None,
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
        if self.preset is ControllerPreset.COMPETITION and retrodiction_config is not None:
            raise CompetitionIntegrityError(
                "competition preset forbids explicit retrodiction overrides"
            )
        if self.preset is ControllerPreset.COMPETITION and cadence_config is not None:
            raise CompetitionIntegrityError(
                "competition preset forbids explicit reasoning-cadence overrides"
            )
        if local_proposal_provider is not None and not self.features.allow_local_proposals:
            raise PolicyError("local proposals are disabled by the selected controller preset")
        default_retrodiction_mode = (
            RetrodictionMode.FULL
            if selected_features.use_retrodiction_gate
            else RetrodictionMode.NONE
        )
        selected_retrodiction = retrodiction_config or RetrodictionConfig(
            mode=default_retrodiction_mode
        )
        if (selected_retrodiction.mode is RetrodictionMode.NONE) != (
            not selected_features.use_retrodiction_gate
        ):
            raise PolicyError(
                "NONE retrodiction must pair with use_retrodiction_gate=false; "
                "all other modes require the gate"
            )
        self._local_proposals = local_proposal_provider
        self._hot_path_profiler = hot_path_profiler
        self._retrodiction_config_explicit = retrodiction_config is not None
        self._retrodiction_runtime = RetrodictionRuntime(selected_retrodiction)
        self._cadence_config_explicit = cadence_config is not None
        self._cadence_config = cadence_config or CadenceConfig()
        self._cadence_state = CadenceState.initial(self._cadence_config)
        self._prediction_cache = BoundedCanonicalLRU(self._cadence_config.cache_capacity)
        self._reasoning_selection: CadenceSelection | None = None
        self._reasoning_selected_event_id: str | None = None
        self._reasoning_completed_event_id: str | None = None
        self._reasoning_force_fallback = False
        self._reasoning_terminal_status = DeliberationStatus.COMPLETED
        self._reasoning_fault_type: str | None = None
        self._reasoning_before_artifacts: tuple[set[str], set[str], set[str]] = (
            set(),
            set(),
            set(),
        )
        self._reasoning_before_hypotheses = 0
        self._reasoning_before_cache_hits = 0
        self._reasoning_before_cache_misses = 0
        self._reasoning_work_counts: dict[str, int] = {}
        self._reasoning_budget_exhaustions: list[str] = []
        self._cadence_reopening_event_ids: list[str] = []
        self._cadence_contradiction_event_ids: list[str] = []
        self._collect_cadence_trigger_events = False
        self._cadence_folded_observation_event_id: str | None = None
        self._cadence_checkpoint_state_event_id: str | None = None
        self._cadence_activation_event_id: str | None = None
        self._pending_goal_transitions: list[GoalTransition] = []
        self._abandoned_trace_event_ids: set[str] = set()
        # Names a raw/derived fold that has not reached a fully represented
        # controller boundary.  Interrupted folds are preserved in the journal,
        # but their transient in-memory state must never become authoritative.
        self._transient_fold_boundary: str | None = None
        self._retrodiction_force_full_source_event_ids: list[str] = []
        self._matched_prediction_evidence: dict[tuple[str, str], MatchedPredictionEvidence] = {}
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
        self._pending_prediction_event_id: str | None = None
        self._restored_prediction_state_ids: tuple[str, ...] = ()
        self._restored_prediction_plan_ids: tuple[str, ...] = ()
        self._prediction_book = PredictionBook()
        self._hypotheses = HypothesisRegistry()
        self._goals = GoalRegistry()
        self._goal_acquirer = GoalAcquirer(self._goals)
        self._action_effects = ActionEffectRegistry(level_index=0)
        self._action_effect_epoch_history: dict[str, dict[str, JSONValue]] = {}
        self._exploration = ExplorationPlanner(action_registry=self._action_effects)
        self._memory = PersistentMemory()
        self._plan_executor = PlanExecutor()
        self._pending_plan_emission = False
        self._planning_disabled_after_mismatch = False
        self._ensemble: WorldModelEnsemble | None = None
        self._model_candidates: tuple[ModelCandidate, ...] = ()
        self._transitions: list[PreservedTransition] = []
        self._transition_levels: dict[str, int] = {}
        self._transition_epochs: dict[str, str] = {}
        self._transition_summaries: dict[int, list[PreservedTransition]] = {}
        self._mechanics = MechanicsLifecycle(level_index=0)
        self._suspended_model_ids: set[str] = set()
        self._demoted_model_ids: set[str] = set()
        self._invalidated_plan_ids: set[str] = set()
        self._resolved_noise_transition_ids: set[str] = set()
        self._provisional_probe_handle: ActionName | None = None
        self._reexploration_handle: ActionName | None = None
        self._reexploration_candidate_id: str | None = None
        self._pending_change_candidate_id: str | None = None
        self._pending_reexploration_candidate_id: str | None = None
        self._palette_roles = PaletteRoleRegistry(level_index=0)
        self._calibration_handles: tuple[ActionName, ...] = ()
        self._calibrated_handles: set[ActionName] = set()
        self._calibration_pending_handle: ActionName | None = None
        self._pending_canonical_effect: CanonicalActionEffect | None = None
        self._pending_resolution_kind: str | None = None
        self._recent_frame_hashes: list[FrameHash] = []
        self._component_to_entity: dict[str, str] = {}
        self._provisional_mover_id: str | None = None
        self._mover_reassignment_candidate_id: str | None = None
        self._mover_reassignment_last_component_id: str | None = None
        self._mover_reassignment_source_event_ids: list[str] = []
        self._mover_reassignment_action_handles: set[ActionName] = set()
        self._mover_reassignment_displacements: set[tuple[int, int]] = set()
        self._goal_targets: dict[str, tuple[str, str]] = {}
        self._active_goal_id: str | None = None
        self._goal_event_sequence_offset = 0
        self._action_counts: Counter[ActionRequest] = Counter()
        self._explored_coordinates: set[Coordinate] = set()
        self._traced_goal_events = 0
        self._fault_count = 0
        self._last_checkpoint: ControllerCheckpoint | None = None
        self._last_sparse_checkpoint_level = -1
        self._interface_semantics: InterfaceSemantics | None = None
        self._interface_semantics_emitted_levels: set[int] = set()
        self._compact_trace: deque[dict[str, JSONValue]] = deque(maxlen=0)

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
    def hot_path_profile(self) -> dict[str, JSONValue] | None:
        """Return derived profiling data without exposing it to policy selection."""

        profiler = self._hot_path_profiler
        return profiler.summary() if profiler is not None and profiler.enabled else None

    @property
    def compact_trace_projection(self) -> tuple[dict[str, JSONValue], ...]:
        """Return bounded in-memory competition receipts without raw frames."""

        return tuple(dict(item) for item in self._compact_trace)

    @property
    def interface_semantics_projection(self) -> dict[str, JSONValue] | None:
        """Expose the source-bound competition interface grant, when active."""

        semantics = self._interface_semantics
        return semantics.to_dict() if semantics is not None else None

    @property
    def search_time_budget_enforced(self) -> bool:
        """Report whether wall-clock search termination is authoritative in this mode."""

        return self.context.config.execution_mode is ExecutionMode.COMPETITION_BOUNDED

    @property
    def retrodiction_config(self) -> RetrodictionConfig:
        """Return the complete typed retrodiction policy identity."""

        return self._retrodiction_runtime.config

    @property
    def retrodiction_state(self) -> dict[str, JSONValue]:
        """Return a derived checkpoint projection without granting action authority."""

        return self._retrodiction_runtime.to_dict()

    @property
    def cadence_config(self) -> CadenceConfig:
        """Return the complete typed reasoning-cadence identity."""

        return self._cadence_config

    @property
    def cadence_state(self) -> dict[str, JSONValue]:
        """Expose current cadence counters as non-authoritative telemetry."""

        return self._cadence_state.to_dict()

    @property
    def prediction_cache_state(self) -> dict[str, JSONValue]:
        """Expose the bounded pure-computation cache for verification."""

        return self._prediction_cache.to_dict()

    @property
    def palette_role_projection(self) -> tuple[tuple[str, int, bool], ...]:
        """Expose only the raw-color-free role projection for verification."""

        return self._palette_roles.canonical_projection()

    @property
    def action_effect_projection(self) -> dict[str, JSONValue]:
        """Expose the bounded derived registry for synthetic verification."""

        return self._action_effects.projection()

    @property
    def action_calibration_projection(self) -> dict[str, JSONValue]:
        """Expose calibration progress without promoting opaque handle meanings."""

        return {
            "level_index": self._level_index,
            "handles": [item.value for item in self._calibration_handles],
            "completed_handles": [
                item.value for item in self._calibration_handles if item in self._calibrated_handles
            ],
            "cursor": self._calibration_cursor,
            "pending_handle": (
                self._calibration_pending_handle.value
                if self._calibration_pending_handle is not None
                else None
            ),
            **(
                {
                    "granted_handles": [
                        item.value
                        for item in ActionName
                        if self._interface_semantics is not None
                        and self._interface_semantics.is_granted(item)
                    ],
                    "interface_semantics": self.interface_semantics_projection,
                }
                if self._interface_semantics is not None
                else {}
            ),
        }

    @property
    def mechanics_lifecycle_projection(self) -> dict[str, JSONValue]:
        """Expose bounded, derived mechanics state without fixture truth."""

        projection_level = self._level_index
        if (
            self._latest_observation is not None
            and self._latest_observation.state is GameStateName.WIN
            and self._transitions
        ):
            projection_level = self._transition_levels[self._transitions[-1].transition_id]
        projection = self._mechanics.projection(level_index=projection_level)
        current_epoch_id = cast(str, projection["active_epoch_id"])
        active_hypotheses = tuple(
            record
            for record in self._hypotheses.all()
            if record.status is HypothesisStatus.ACTIVE
            and self._mechanics.hypothesis_epoch(record.hypothesis_id) == current_epoch_id
        )
        active_models = (
            tuple(candidate.model_id for candidate in self._ensemble.candidates)
            if self._ensemble is not None
            else ()
        )
        active_plan = self._plan_executor.plan
        active_plan_cursor = self._plan_executor.cursor
        active_plan_step = (
            active_plan.steps[active_plan_cursor]
            if active_plan is not None and active_plan_cursor < len(active_plan.steps)
            else None
        )
        latest_symbolic_state_id = (
            self._latest_view.symbolic_state.state_id if self._latest_view is not None else None
        )
        pending_alternatives = (
            self._pending_prediction.prediction.alternatives
            if self._pending_prediction is not None
            else ()
        )
        pending_model_ids = sorted(
            {
                model_id
                for alternative in pending_alternatives
                for model_id in alternative.supporting_model_ids
            }
        )
        active_plan_dependency_satisfied = False
        if active_plan is not None and active_plan.model_id in active_models:
            containing_model = next(
                (
                    candidate
                    for candidate in (
                        self._ensemble.candidates if self._ensemble is not None else ()
                    )
                    if candidate.model_id == active_plan.model_id
                ),
                None,
            )
            active_plan_dependency_satisfied = bool(
                containing_model is not None
                and containing_model.hypothesis_ids
                and all(
                    active_plan.plan_id in self._hypotheses.dependent_plan_ids(hypothesis_id)
                    for hypothesis_id in containing_model.hypothesis_ids
                )
            )
        contact_probe_pending = bool(
            self._latest_observation is not None
            and self._latest_view is not None
            and self._contact_probe_action(self._latest_observation, self._latest_view) is not None
        )
        projection.update(
            {
                "suspended_model_ids": cast(list[JSONValue], sorted(self._suspended_model_ids)),
                "demoted_model_ids": cast(list[JSONValue], sorted(self._demoted_model_ids)),
                "invalidated_plan_ids": cast(list[JSONValue], sorted(self._invalidated_plan_ids)),
                "resolved_noise_transition_ids": cast(
                    list[JSONValue], sorted(self._resolved_noise_transition_ids)
                ),
                "provisional_probe_handle": (
                    self._provisional_probe_handle.value
                    if self._provisional_probe_handle is not None
                    else None
                ),
                "reexploration_handle": (
                    self._reexploration_handle.value
                    if self._reexploration_handle is not None
                    else None
                ),
                "reexploration_candidate_id": self._reexploration_candidate_id,
                "pending_change_candidate_id": self._pending_change_candidate_id,
                "pending_reexploration_candidate_id": (self._pending_reexploration_candidate_id),
                "action_effect_epoch_history": {
                    key: value for key, value in sorted(self._action_effect_epoch_history.items())
                },
                "readiness": cast(
                    dict[str, JSONValue],
                    {
                        "calibration_complete": (
                            self._calibration_cursor == len(self._calibration_handles)
                        ),
                        "active_hypothesis_ids": [
                            record.hypothesis_id for record in active_hypotheses
                        ],
                        "active_hypothesis_domains": {
                            record.hypothesis_id: record.family.value
                            for record in active_hypotheses
                        },
                        "active_hypothesis_statements": {
                            record.hypothesis_id: record.statement.to_dict()
                            for record in active_hypotheses
                        },
                        "active_hypothesis_support_counts": {
                            record.hypothesis_id: len(record.support_receipts)
                            for record in active_hypotheses
                        },
                        "active_action_bindings": {
                            action.value: cast(
                                list[JSONValue],
                                sorted(
                                    record.hypothesis_id
                                    for record in active_hypotheses
                                    if isinstance(record.statement, ActionSemanticsStatement)
                                    and record.statement.action == action.value
                                ),
                            )
                            for action in self._calibration_handles
                        },
                        "active_model_ids": list(active_models),
                        "active_model_hypothesis_ids": {
                            candidate.model_id: list(candidate.hypothesis_ids)
                            for candidate in (
                                self._ensemble.candidates if self._ensemble is not None else ()
                            )
                        },
                        "active_plan_id": active_plan.plan_id if active_plan is not None else None,
                        "active_plan_model_id": (
                            active_plan.model_id if active_plan is not None else None
                        ),
                        "active_plan_step_count": (
                            len(active_plan.steps) if active_plan is not None else 0
                        ),
                        "active_plan_cursor": active_plan_cursor,
                        "active_plan_current_step_action": (
                            _action_payload(active_plan_step.action)
                            if active_plan_step is not None
                            else None
                        ),
                        "active_plan_current_step_before_state_id": (
                            active_plan_step.before_state_id
                            if active_plan_step is not None
                            else None
                        ),
                        "active_plan_current_step_predicted_state_id": (
                            active_plan_step.predicted_state_id
                            if active_plan_step is not None
                            else None
                        ),
                        "latest_symbolic_state_id": latest_symbolic_state_id,
                        "active_plan_current_at_latest_state": bool(
                            active_plan_step is not None
                            and active_plan_step.before_state_id == latest_symbolic_state_id
                        ),
                        "active_plan_current_step_nontrivial": bool(
                            active_plan_step is not None
                            and active_plan_step.before_state_id
                            != active_plan_step.predicted_state_id
                        ),
                        "active_plan_nontrivial": bool(
                            active_plan_step is not None
                            and active_plan_step.before_state_id
                            != active_plan_step.predicted_state_id
                        ),
                        "active_plan_invalidated": bool(
                            active_plan is not None
                            and active_plan.plan_id in self._invalidated_plan_ids
                        ),
                        "active_plan_dependency_satisfied": active_plan_dependency_satisfied,
                        "pending_action_present": self._pending_action is not None,
                        "action_boundary_open": bool(
                            self._phase is ControllerPhase.OBSERVED
                            and self._pending_action is None
                            and self._pending_prediction is None
                        ),
                        "higher_priority_probe_present": bool(
                            self._calibration_cursor != len(self._calibration_handles)
                            or self._provisional_probe_handle is not None
                            or self._reexploration_handle is not None
                            or contact_probe_pending
                        ),
                        "pending_prediction_receipt_id": (
                            self._pending_prediction.receipt_id
                            if self._pending_prediction is not None
                            else None
                        ),
                        "pending_prediction_model_ids": cast(list[JSONValue], pending_model_ids),
                        "pending_prediction_nontrivial": bool(
                            self._pending_prediction is not None
                            and any(
                                alternative.after_state_id
                                != self._pending_prediction.before_state_id
                                for alternative in pending_alternatives
                            )
                        ),
                        "pending_prediction_alternatives": [
                            {
                                "after_state_id": alternative.after_state_id,
                                "supporting_model_ids": list(alternative.supporting_model_ids),
                            }
                            for alternative in pending_alternatives
                        ],
                        "pending_prediction_dependent_plan_ids": (
                            list(self._pending_prediction.dependent_plan_ids)
                            if self._pending_prediction is not None
                            else []
                        ),
                    },
                ),
            }
        )
        return projection

    @property
    def _calibration_cursor(self) -> int:
        for index, handle in enumerate(self._calibration_handles):
            if handle not in self._calibrated_handles:
                return index
        return len(self._calibration_handles)

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

    @_profiled("startup", "reset")
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
            if context.config.execution_mode is not ExecutionMode.COMPETITION_BOUNDED:
                raise CompetitionIntegrityError(
                    "competition preset requires COMPETITION_BOUNDED execution mode"
                )
            if context.config.runtime_policy.allocator_tracing_enabled:
                raise CompetitionIntegrityError("competition execution forbids allocator tracing")
        proposal_provider = self._local_proposals
        selected_features = self.features
        profiler = self._hot_path_profiler
        selected_retrodiction = (
            self._retrodiction_runtime.config if self._retrodiction_config_explicit else None
        )
        selected_cadence = self._cadence_config if self._cadence_config_explicit else None
        ARC3Controller.__init__(
            self,
            self.preset,
            local_proposal_provider=proposal_provider,
            features=selected_features,
            hot_path_profiler=profiler,
            retrodiction_config=selected_retrodiction,
            cadence_config=selected_cadence,
        )
        self._initialize_context(context)
        # A reset establishes fresh source/configuration and lifecycle
        # boundaries.  The cache is empty, but typed causal counters still
        # preserve why no reusable value crossed either boundary.
        self._prediction_cache.invalidate(CacheInvalidationReason.SOURCE_OR_CONFIGURATION_CHANGE)
        self._prediction_cache.invalidate(CacheInvalidationReason.LEVEL_TRANSITION_OR_RESET)
        started = self._append(
            context.game_id,
            "run.started",
            {
                "preset": self.preset.value,
                "network_enabled": context.config.network_enabled,
                "execution_mode": context.config.execution_mode.value,
                "runtime_policy": asdict(context.config.runtime_policy),
                "features": self.features.to_dict(),
                "retrodiction_config": self._retrodiction_runtime.config.to_dict(),
                "retrodiction_configuration_hash": sha256_json(
                    self._retrodiction_runtime.config.to_dict()
                ),
                "cadence_config": self._cadence_config.to_dict(),
                "cadence_configuration_hash": self._cadence_config.configuration_hash,
            },
            scope="run",
        )
        self._cadence_activation_event_id = started.event_id

    def _initialize_context(self, context: RunContext) -> None:
        self._context = context
        if context.config.execution_mode is ExecutionMode.COMPETITION_BOUNDED:
            self._interface_semantics = OFFICIAL_COMPETITION_INTERFACE
        self._compact_trace = deque(maxlen=context.config.runtime_policy.compact_trace_capacity)
        self._mechanics = MechanicsLifecycle(
            level_index=0,
            maximum_transitions_per_epoch=context.config.budgets.max_actions,
        )
        self._source = SourceIdentity(
            context.source_kind,
            context.source_version,
            {
                "preset": self.preset.value,
                "features": self.features.to_dict(),
                "retrodiction_config": self._retrodiction_runtime.config.to_dict(),
                "retrodiction_configuration_hash": sha256_json(
                    self._retrodiction_runtime.config.to_dict()
                ),
                "cadence_config": self._cadence_config.to_dict(),
                "cadence_configuration_hash": self._cadence_config.configuration_hash,
                "execution_mode": context.config.execution_mode.value,
                "interface_semantics": (
                    self._interface_semantics.to_dict()
                    if self._interface_semantics is not None
                    else None
                ),
                "runtime_policy": asdict(context.config.runtime_policy),
            },
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

    @_profiled("trace_serialization")
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
        event = self.journal.append(
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
        if event_type in _RETRODICTION_FORCE_FULL_EVENTS:
            self._retrodiction_force_full_source_event_ids.append(event.event_id)
        if self._collect_cadence_trigger_events:
            if event_type in {
                "hypothesis.reopened",
                "model.rule_demoted",
                "mechanics.change_confirmed",
                "mechanics.epoch_opened",
                "goal.reopened",
            }:
                self._cadence_reopening_event_ids.append(event.event_id)
            if event_type in {
                "consequence.mismatched_prediction",
                "hypothesis.contradicted",
                "goal.contradicted",
                "mechanics.change_candidate_created",
            }:
                self._cadence_contradiction_event_ids.append(event.event_id)
        if self._cadence_state.deliberation_in_progress:
            if event_type == "model.retrodiction_started":
                raw_transition_ids = event.payload.get("transition_ids")
                transition_count = (
                    len(raw_transition_ids) if isinstance(raw_transition_ids, list) else 0
                )
                self._reasoning_work_counts["retrodiction_invocations"] += 1
                self._reasoning_work_counts["retrodicted_transitions"] += transition_count
                self._reasoning_work_counts["prediction_invocations"] += transition_count
            elif event_type == "simulation.plan_evaluated":
                expanded = event.payload.get("expanded_nodes")
                generated = event.payload.get("generated_transitions")
                self._reasoning_work_counts["simulation_invocations"] += 1
                if isinstance(expanded, int) and not isinstance(expanded, bool):
                    self._reasoning_work_counts["search_expanded_nodes"] += expanded
                if isinstance(generated, int) and not isinstance(generated, bool):
                    self._reasoning_work_counts["search_generated_transitions"] += generated
                    self._reasoning_work_counts["prediction_invocations"] += generated
                status = event.payload.get("status")
                if status in {
                    SearchStatus.NODE_BUDGET.value,
                    SearchStatus.DEPTH_BUDGET.value,
                    SearchStatus.TIME_BUDGET.value,
                }:
                    self._reasoning_budget_exhaustions.append(str(status))
                    self._reasoning_terminal_status = DeliberationStatus.BUDGET_EXHAUSTED
        if self._compact_trace.maxlen:
            self._compact_trace.append(
                {
                    "event_hash": event.event_hash,
                    "event_id": event.event_id,
                    "event_type": event.event_type,
                    "level_index": event.level_index,
                    "step_index": event.step_index,
                }
            )
        return event

    def _policy_events(self) -> tuple[TraceEvent, ...]:
        """Return verified receipts excluding explicitly reopened derived suffixes."""

        return tuple(
            event
            for event in authoritative_events(self.journal.verify_manifest())
            if event.event_id not in self._abandoned_trace_event_ids
        )

    def _rebuild_compact_trace(self) -> None:
        """Rehydrate the bounded receipt view from the immutable journal."""

        if not self._compact_trace.maxlen:
            return
        self._compact_trace.clear()
        for event in self.journal.verify_manifest():
            self._compact_trace.append(
                {
                    "event_hash": event.event_hash,
                    "event_id": event.event_id,
                    "event_type": event.event_type,
                    "level_index": event.level_index,
                    "step_index": event.step_index,
                }
            )

    def _validated_abandoned_trace_event_ids(
        self,
        current_suffix: Sequence[TraceEvent],
    ) -> set[str]:
        """Rebuild every immutable interrupted-deliberation exclusion."""

        historical = set(abandoned_event_ids(self.journal.verify_manifest()))
        historical.update(event.event_id for event in current_suffix)
        return historical

    def _cache_source_identity(self) -> str:
        if self._source is None:
            raise PolicyError("reasoning cache source identity is unavailable")
        return sha256_json(self._source.to_dict())

    def _cache_configuration_identity(self) -> str:
        if self._code is None:
            raise PolicyError("reasoning cache configuration identity is unavailable")
        return sha256_json(
            {
                "cadence_configuration_hash": self._cadence_config.configuration_hash,
                "controller_config_hash": self._code.config_hash,
                "features": self.features.to_dict(),
                "retrodiction_configuration_hash": (
                    self._retrodiction_runtime.config.configuration_hash
                ),
            }
        )

    def _action_registry_identity(self) -> str:
        return sha256_json(self._action_effects.projection())

    @staticmethod
    def _structural_identity(view: _PerceptionView) -> str:
        """Hash palette-anonymous topology while ignoring ordinary translation."""

        entities: list[dict[str, JSONValue]] = []
        for entity in view.symbolic_state.entities:
            anchor = entity.anchor
            entities.append(
                {
                    "kind": entity.kind,
                    "relative_cells": [
                        [cell.x - anchor.x, cell.y - anchor.y] for cell in entity.cells
                    ],
                    "attributes": [
                        [key, value]
                        for key, value in entity.attributes
                        if key not in {"palette_anonymous_identity", "palette_role"}
                    ],
                }
            )
        return sha256_json(
            {
                "width": view.symbolic_state.width,
                "height": view.symbolic_state.height,
                "entities": sorted(entities, key=sha256_json),
                "facts": list(view.symbolic_state.facts),
                "toggles": [list(item) for item in view.symbolic_state.toggles],
                "attachments": [
                    {
                        "child_id": item.child_id,
                        "parent_id": item.parent_id,
                        "dx": item.dx,
                        "dy": item.dy,
                    }
                    for item in view.symbolic_state.attachments
                ],
            }
        )

    def _current_plan_id(self, view: _PerceptionView) -> str | None:
        plan = self._plan_executor.plan
        if (
            plan is None
            or self._ensemble is None
            or self._active_goal_id is None
            or plan.plan_id in self._invalidated_plan_ids
            or self._plan_executor.cursor >= len(plan.steps)
            or plan.steps[self._plan_executor.cursor].before_state_id
            != view.symbolic_state.state_id
        ):
            return None
        model = next(
            (item for item in self._ensemble.candidates if item.model_id == plan.model_id),
            None,
        )
        if model is None or self._active_goal_id != plan.goal_id:
            return None
        try:
            goal = self._goals.get(plan.goal_id)
        except KeyError:
            return None
        revision = f"{goal.status.value}:{goal.rank}:{goal.reopen_count}"
        if not plan.is_current(
            model_id=model.model_id,
            goal_id=goal.candidate.goal_id,
            goal_revision=revision,
        ):
            return None
        return plan.plan_id

    def _reasoning_budget_limits(self) -> dict[str, int]:
        budgets = self.context.config.budgets
        return {
            "cache_capacity": self._cadence_config.cache_capacity,
            "coordinate_candidates": budgets.max_coordinate_candidates,
            "fast_streak": self._cadence_config.maximum_fast_streak,
            "retrodicted_transitions": budgets.max_actions,
            "search_depth": budgets.max_search_depth,
            "search_nodes": budgets.max_search_nodes,
        }

    def _reasoning_artifacts(self) -> tuple[set[str], set[str], set[str]]:
        models = (
            {item.model_id for item in self._ensemble.candidates}
            if self._ensemble is not None
            else set()
        )
        goals = {item.candidate.goal_id for item in self._goals.records(include_retired=False)}
        plan = self._plan_executor.plan
        plans = {plan.plan_id} if plan is not None else set()
        return models, goals, plans

    def _run_reasoning_cycle(
        self,
        observation: Observation,
        receipt: ObservationReceipt,
        view: _PerceptionView,
        *,
        initial: bool,
        progress_made: bool,
        evidence_already_folded: bool = False,
        goal_revision_transition: PreservedTransition | None = None,
        goal_revision_consequence_event_id: str | None = None,
    ) -> None:
        """Select and perform one deterministic path, deferring its terminal receipt."""

        structural_identity = self._structural_identity(view)
        if (goal_revision_transition is None) != (goal_revision_consequence_event_id is None):
            raise PolicyError("goal revision requires a complete consequence boundary")
        prior_structural_identity = self._cadence_state.last_structural_identity
        structural_novelty = (
            not initial
            and prior_structural_identity is not None
            and prior_structural_identity != structural_identity
        )
        if not evidence_already_folded:
            self._cadence_state = self._cadence_state.fold_consequence(
                progress_made=progress_made,
                structural_identity=structural_identity,
            )
            self._cadence_folded_observation_event_id = receipt.observation_event_id
        self._reasoning_selection = None
        self._reasoning_selected_event_id = None
        self._reasoning_completed_event_id = None
        self._reasoning_force_fallback = False
        if self.features.use_memory and not evidence_already_folded:
            # Persist the complete always-on evidence fold while cadence is
            # checkpointable.  Deliberation may be recomputed after recovery;
            # a half-completed path is never serialized as finished work.
            self._maybe_automatic_checkpoint(
                boundary="evidence-fold",
                force=initial or observation.state is GameStateName.WIN,
            )
        if observation.state is GameStateName.WIN:
            self._collect_cadence_trigger_events = False
            self._cadence_reopening_event_ids.clear()
            self._cadence_contradiction_event_ids.clear()
            return
        plan_id = self._current_plan_id(view)
        high_goal_uncertainty = False
        if self._active_goal_id is not None:
            try:
                goal = self._goals.get(self._active_goal_id)
            except KeyError:
                high_goal_uncertainty = True
            else:
                # Candidate status alone does not block a source-bound plan:
                # goal desirability remains revisable, while executable model,
                # state, and plan authority are validated separately.
                high_goal_uncertainty = goal.status is GoalStatus.RETIRED or goal.rank <= 0
        signals = CadenceSignals(
            observation_event_id=receipt.observation_event_id,
            state_id=view.symbolic_state.state_id,
            mechanics_epoch_id=self._mechanics.active_epoch(self._level_index).epoch_id,
            goal_id=self._active_goal_id,
            goal_revision=self._goal_event_sequence_offset + len(self._goals.events),
            plan_id=plan_id,
            has_valid_plan=plan_id is not None,
            startup_unknown_action_event_ids=((receipt.observation_event_id,) if initial else ()),
            reopening_event_ids=tuple(self._cadence_reopening_event_ids),
            meaningful_contradiction_event_ids=tuple(self._cadence_contradiction_event_ids),
            structural_novelty_event_ids=(
                (receipt.observation_event_id,) if structural_novelty else ()
            ),
            high_goal_uncertainty_event_ids=(
                (receipt.observation_event_id,) if high_goal_uncertainty else ()
            ),
        )
        selection = select_reasoning_path(
            self._cadence_config,
            self._cadence_state,
            signals,
        )
        self._collect_cadence_trigger_events = False
        self._cadence_reopening_event_ids.clear()
        self._cadence_contradiction_event_ids.clear()
        selected_event = self._append(
            str(observation.game_id),
            "reasoning.path_selected",
            {
                **selection.to_dict(),
                "observation_event_id": receipt.observation_event_id,
                "cadence_mode": self._cadence_config.mode.value,
                "budget_limits": self._reasoning_budget_limits(),
                "cache_projection_hash": self._prediction_cache.projection_hash,
                "action_registry_identity": self._action_registry_identity(),
            },
        )
        self._cadence_state = self._cadence_state.begin(selection)
        self._reasoning_selection = selection
        self._reasoning_selected_event_id = selected_event.event_id
        self._reasoning_force_fallback = False
        self._reasoning_terminal_status = DeliberationStatus.COMPLETED
        self._reasoning_fault_type = None
        self._reasoning_before_artifacts = self._reasoning_artifacts()
        self._reasoning_before_hypotheses = len(self._hypotheses.all())
        self._reasoning_before_cache_hits = self._prediction_cache.hits
        self._reasoning_before_cache_misses = self._prediction_cache.misses
        self._reasoning_budget_exhaustions = []
        self._reasoning_work_counts = {
            "compilation_invocations": 0,
            "deep_invocations": int(selection.path is ReasoningPath.DEEP),
            "prediction_invocations": 0,
            "retrodicted_transitions": 0,
            "retrodiction_invocations": 0,
            "search_expanded_nodes": 0,
            "search_generated_transitions": 0,
            "simulation_invocations": 0,
        }
        try:
            if selection.path is ReasoningPath.DEEP:
                prior_model_projection = tuple(
                    (
                        model_semantic_fingerprint(item),
                        item.rank_weight,
                    )
                    for item in (self._ensemble.candidates if self._ensemble is not None else ())
                )
                prior_goal_projection = sha256_json(
                    {
                        "active_goal_id": self._active_goal_id,
                        "records": [item.to_dict() for item in self._goals.records()],
                    }
                )
                if self.features.use_goals:
                    self._drain_pending_goal_updates(observation)
                if (
                    goal_revision_transition is not None
                    and goal_revision_consequence_event_id is not None
                    and self.features.use_goals
                ):
                    self._retarget_contact_goal_after_progress(
                        observation,
                        receipt,
                        view,
                        goal_revision_transition,
                        consequence_event_id=goal_revision_consequence_event_id,
                    )
                if self.features.use_world_model:
                    self._reasoning_work_counts["compilation_invocations"] += 1
                    self._update_world_models(observation)
                if self.features.use_goals:
                    self._seed_contact_goal(observation, receipt, view)
                if self.features.use_planning:
                    self._stage_plan_for_next_choice(
                        observation,
                        view,
                        propagate_failure=True,
                    )
                current_model_projection = tuple(
                    (
                        model_semantic_fingerprint(item),
                        item.rank_weight,
                    )
                    for item in (self._ensemble.candidates if self._ensemble is not None else ())
                )
                if current_model_projection != prior_model_projection:
                    self._prediction_cache.invalidate(CacheInvalidationReason.MODEL_STATUS_CHANGE)
                if (
                    sha256_json(
                        {
                            "active_goal_id": self._active_goal_id,
                            "records": [item.to_dict() for item in self._goals.records()],
                        }
                    )
                    != prior_goal_projection
                ):
                    self._prediction_cache.invalidate(CacheInvalidationReason.GOAL_REVISION)
        except Exception as error:
            self._reasoning_terminal_status = DeliberationStatus.FALLBACK_USED
            self._reasoning_fault_type = type(error).__name__
            self._reasoning_force_fallback = True
            self._fault_count += 1
            self._append(
                str(observation.game_id),
                "run.environment_fault",
                {
                    "fault_type": self._reasoning_fault_type,
                    "boundary": "reasoning-deliberation",
                    "recovery": "deterministic legal action fallback",
                },
                scope="run",
            )

    def _complete_reasoning_cycle(
        self,
        observation: Observation,
        *,
        advance_cadence: bool = True,
    ) -> TraceEvent:
        """Emit the one terminal receipt after current-decision cache work."""

        selection = self._reasoning_selection
        selected_event_id = self._reasoning_selected_event_id
        if selection is None or selected_event_id is None:
            raise PolicyError("reasoning completion lacks its selected path")
        if not self._cadence_state.deliberation_in_progress:
            raise PolicyError("reasoning completion has no in-progress cadence state")
        before_models, before_goals, before_plans = self._reasoning_before_artifacts
        after_models, after_goals, after_plans = self._reasoning_artifacts()
        produced_models = tuple(sorted(after_models - before_models))
        produced_goals = tuple(sorted(after_goals - before_goals))
        produced_plans = tuple(sorted(after_plans - before_plans))
        work_counts = {
            **self._reasoning_work_counts,
            "goal_records_after": len(after_goals),
            "hypothesis_records_after": len(self._hypotheses.all()),
            "hypothesis_records_before": self._reasoning_before_hypotheses,
            "model_records_after": len(after_models),
            "preserved_transitions_available": (
                len(self._transitions) if selection.path is ReasoningPath.DEEP else 0
            ),
            "produced_plans": len(produced_plans),
        }
        status = self._reasoning_terminal_status
        terminal_payload: dict[str, object] = {
            "path_selected_event_id": selected_event_id,
            "path": selection.path.value,
            "status": status.value,
            "integer_work_counts": work_counts,
            "budget_exhaustions": sorted(set(self._reasoning_budget_exhaustions)),
            "cache_hits": self._prediction_cache.hits - self._reasoning_before_cache_hits,
            "cache_misses": self._prediction_cache.misses - self._reasoning_before_cache_misses,
            "cache_invalidation_counts": {
                reason.value: self._prediction_cache.invalidation_counts[reason]
                for reason in CacheInvalidationReason
            },
            "produced_model_ids": list(produced_models),
            "produced_goal_ids": list(produced_goals),
            "produced_plan_ids": list(produced_plans),
            "artifact_projection_hash": sha256_json(
                {
                    "cache_projection_hash": self._prediction_cache.projection_hash,
                    "goal_ids": sorted(after_goals),
                    "model_ids": sorted(after_models),
                    "plan_ids": sorted(after_plans),
                    "selection_hash": selection.selection_hash,
                    "work_counts": work_counts,
                }
            ),
        }
        if self._reasoning_fault_type is not None:
            terminal_payload["fault_type"] = self._reasoning_fault_type
            terminal_payload["recovery"] = (
                "deterministic legal action fallback"
                if status is DeliberationStatus.FALLBACK_USED
                else "no action crossed the adapter boundary"
            )
        event_type = (
            "reasoning.fallback_used"
            if status is DeliberationStatus.FALLBACK_USED
            else "reasoning.deliberation_completed"
        )
        terminal = self._append(
            str(observation.game_id),
            event_type,
            terminal_payload,
        )
        self._cadence_state = (
            self._cadence_state.complete(
                selection,
                completed_event_id=terminal.event_id,
                status=status,
            )
            if advance_cadence
            else self._cadence_state.abort(
                selection,
                completed_event_id=terminal.event_id,
                status=status,
            )
        )
        self._reasoning_completed_event_id = terminal.event_id
        return terminal

    @_profiled("controller_orchestration", "observe")
    def observe(self, frames: Observation | object) -> ObservationReceipt:
        """Validate one initial/unsolicited observation before selecting an action."""

        if self._phase is ControllerPhase.AWAITING_CONSEQUENCE:
            raise PolicyError(
                "pending action requires apply_consequence; observe cannot erase the boundary"
            )
        if self._phase in {ControllerPhase.COMPLETE, ControllerPhase.CLOSED}:
            raise PolicyError(f"cannot observe while controller is {self._phase.value}")
        if self._transient_fold_boundary is not None:
            raise PolicyError("interrupted controller fold requires checkpoint recovery")
        if self._cadence_state.deliberation_in_progress:
            previous = self._latest_observation
            if previous is None:
                raise PolicyError("superseded reasoning lacks its observation boundary")
            self._reasoning_terminal_status = DeliberationStatus.FAILED
            self._reasoning_fault_type = "ObservationSupersededBeforeAction"
            self._complete_reasoning_cycle(previous)
        self._transient_fold_boundary = "observation-processing"
        observation = self._require_observation(frames)
        self._level_index = observation.levels_completed
        receipt, view = self._record_observation(observation, previous=None)
        self._latest_observation = observation
        self._latest_receipt = receipt
        self._latest_view = view
        self._phase_from_observation(observation)
        self._prepare_action_level(observation)
        self._remember_frame(observation.frames[-1].digest)
        self._set_provisional_mover(view)
        self._emit_local_proposals_if_enabled(observation, receipt, view)
        self._transient_fold_boundary = None
        self._run_reasoning_cycle(
            observation,
            receipt,
            view,
            initial=True,
            progress_made=True,
        )
        return receipt

    @_profiled("observation_normalization")
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
        if self._transient_fold_boundary == "observation-processing":
            # Validation failed before an observation receipt or any derived
            # interpretation was admitted.  The typed parse-failure receipt is
            # therefore a complete durable fault boundary.  In contrast, a
            # malformed returned consequence leaves an already-submitted
            # adapter crossing unresolved and must stay transient.
            self._transient_fold_boundary = None
        raise PolicyError(f"malformed observation preserved as {event.event_id}")

    @_profiled("perception")
    def _record_observation(
        self,
        observation: Observation,
        *,
        previous: Observation | None,
    ) -> tuple[ObservationReceipt, _PerceptionView]:
        frame_receipts = self._store_frames(observation.frames)
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
                "upstream_session_id": observation.upstream_session_id,
                "upstream_metadata": _metadata(observation),
            },
        )
        raw_id = raw.event_id
        raw_hash = raw.event_hash
        self._flush_trace()
        frame = observation.frames[-1]
        background = Counter(cell for row in frame.cells for cell in row).most_common(1)[0][0]
        self._palette_roles.begin_level(self._level_index)
        self._palette_roles.observe(frame, background_colors=(background,))
        components = extract_components(
            frame,
            config=ComponentConfig(background_candidates=(background,)),
        )
        symbolic, component_to_entity = _symbolic_state(frame, components, self._palette_roles)
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
                tracking = self._track_correspondence(
                    prior_components,
                    components,
                    (
                        max(prior_frame.width, frame.width),
                        max(prior_frame.height, frame.height),
                    ),
                    input_key=f"{prior_frame.digest}|{frame.digest}",
                    change_kind=self._frame_change_kind(delta, frame),
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

        if self._hot_path_profiler is not None:
            self._hot_path_profiler.cache(
                "perception",
                None,
                input_key=str(frame.digest),
                change_kind=("initial" if delta is None else self._frame_change_kind(delta, frame)),
            )

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
                            "palette_role": self._palette_roles.canonical_role(component.color),
                            "palette_anonymous_identity": (
                                self._palette_roles.anonymous_identity(component.color)
                            ),
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

    @_profiled("trace_serialization")
    def _store_frames(self, frames: Sequence[GridFrame]) -> list[dict[str, JSONValue]]:
        payloads: list[dict[str, JSONValue]] = []
        for frame in frames:
            receipt = self.journal.blobs.put_frame(frame.cells)
            if self._hot_path_profiler is not None:
                self._hot_path_profiler.cache(
                    "trace_serialization",
                    not receipt.created,
                    input_key=receipt.frame_hash,
                    change_kind="global_change" if receipt.created else "unchanged",
                )
            payloads.append(receipt.to_payload())
        return payloads

    @_profiled("trace_serialization")
    def _flush_trace(self) -> None:
        self.journal.flush()

    @_profiled("correspondence")
    def _track_correspondence(
        self,
        before: tuple[Component, ...],
        after: tuple[Component, ...],
        frame_extent: tuple[int, int],
        *,
        input_key: str,
        change_kind: str,
    ) -> TrackingResult:
        if self._hot_path_profiler is not None:
            self._hot_path_profiler.cache(
                "correspondence",
                None,
                input_key=input_key,
                change_kind=change_kind,
            )
        return track_components(before, after, frame_extent=frame_extent)

    @staticmethod
    def _frame_change_kind(delta: FrameDelta, frame: GridFrame) -> str:
        if delta.changed_cell_count == 0:
            return "unchanged"
        area = max(1, frame.width * frame.height)
        return "local_change" if delta.changed_cell_count * 4 <= area else "global_change"

    def _phase_from_observation(self, observation: Observation) -> None:
        if observation.state is GameStateName.WIN:
            self._phase = ControllerPhase.COMPLETE
            self._plan_executor = PlanExecutor()
            self._pending_plan_emission = False
        elif observation.state is GameStateName.GAME_OVER:
            self._phase = ControllerPhase.GAME_OVER
            self._plan_executor = PlanExecutor()
            self._pending_plan_emission = False
        else:
            self._phase = ControllerPhase.OBSERVED

    def _prepare_action_level(self, observation: Observation) -> None:
        """Bind a fresh level to its initially advertised opaque handles."""

        if self._action_effects.level_index != self._level_index:
            self._action_effects = ActionEffectRegistry(level_index=self._level_index)
            self._exploration.action_registry = self._action_effects
            self._calibration_handles = ()
            self._calibrated_handles.clear()
            self._calibration_pending_handle = None
            self._recent_frame_hashes.clear()
        self._action_effects.register_handles(observation.available_actions)
        if (
            self._interface_semantics is not None
            and self._level_index not in self._interface_semantics_emitted_levels
        ):
            advertised = set(observation.available_actions)
            self._append(
                str(observation.game_id),
                "interface.semantics_granted",
                {
                    "granted_available_actions": [
                        item.value
                        for item in ActionName
                        if item in advertised and self._interface_semantics.is_granted(item)
                    ],
                    "semantics": self._interface_semantics.to_dict(),
                    "variable_available_actions": [
                        item.value
                        for item in self._interface_semantics.evidence_driven_actions
                        if item in advertised
                    ],
                },
                scope=StateScope.LEVEL,
            )
            self._interface_semantics_emitted_levels.add(self._level_index)
        if not self._calibration_handles and observation.state not in {
            GameStateName.NOT_PLAYED,
            GameStateName.GAME_OVER,
            GameStateName.WIN,
        }:
            advertised = set(observation.available_actions)
            self._calibration_handles = tuple(
                item
                for item in ActionName
                if item is not ActionName.RESET
                and item in advertised
                and (
                    self._interface_semantics is None
                    or item in self._interface_semantics.evidence_driven_actions
                )
            )

    def _remember_frame(self, digest: FrameHash) -> None:
        self._recent_frame_hashes.append(digest)
        del self._recent_frame_hashes[:-32]

    def _next_calibration_action(self, observation: Observation) -> ActionRequest | None:
        if self._calibration_cursor >= len(self._calibration_handles):
            return None
        handle = self._calibration_handles[self._calibration_cursor]
        if handle not in observation.available_actions:
            return None
        coordinate = Coordinate(3, 3) if handle is ActionName.ACTION6 else None
        return ActionRequest(handle, coordinate)

    def _resolved_effect_for(
        self,
        observation: Observation,
        action: ActionRequest,
    ) -> tuple[CanonicalActionEffect | None, str | None]:
        condition = action_condition_signature(observation)
        effects = self._action_effects.accepted_effects(
            action.name,
            condition_signature=condition,
        )
        if len(effects) == 1:
            return effects[0], "accepted-effect-binding"
        translation = self._action_effects.accepted_translation(
            action.name,
            condition_signature=condition,
        )
        if translation is None:
            translation = self._active_action_translation(action.name)
            if translation is not None:
                resolution_kind = (
                    "official-interface-direction-grant"
                    if self._interface_semantics is not None
                    and self._interface_semantics.translation_for(action.name) is not None
                    else "active-controlled-translation-binding"
                )
                return (
                    CanonicalActionEffect(
                        CanonicalEffectKind.TRANSLATION,
                        translation,
                        CoordinateRelation.NOT_APPLICABLE,
                        None,
                        condition,
                    ),
                    resolution_kind,
                )
        if translation is None:
            return None, None
        representatives = tuple(
            candidate.canonical_effect
            for candidate in self._action_effects.candidates_for(
                action.name,
                condition_signature=condition,
            )
            if candidate.status is not ActionEffectStatus.CONTRADICTED
            and candidate.canonical_effect.translation == translation
        )
        return (
            min(representatives, key=lambda item: item.semantic_key),
            "accepted-translation-facet-binding",
        )

    def _active_action_translation(
        self,
        action: ActionName,
        *,
        epoch_id: str | None = None,
        include_provisionally_suspended: bool = False,
    ) -> tuple[int, int] | None:
        """Return one accepted mover-scoped translation in the active mechanics epoch."""

        if self._interface_semantics is not None:
            granted = self._interface_semantics.translation_for(action)
            if granted is not None:
                return granted
        target_epoch_id = epoch_id or self._mechanics.active_epoch(self._level_index).epoch_id
        allowed_statuses = {HypothesisStatus.ACTIVE}
        if (
            include_provisionally_suspended
            and self._mechanics.live_candidate(
                level_index=self._level_index,
                opaque_handle=action.value,
            )
            is not None
        ):
            allowed_statuses.update({HypothesisStatus.CANDIDATE, HypothesisStatus.UNRESOLVED})
        translations: set[tuple[int, int]] = set()
        for record in self._hypotheses.all():
            statement = record.statement
            if (
                record.status not in allowed_statuses
                or self._mechanics.hypothesis_epoch(record.hypothesis_id) != target_epoch_id
                or not isinstance(statement, ActionSemanticsStatement)
                or statement.action != action.value
                or statement.effect.lower() not in {"translate", "translation", "move", "movement"}
            ):
                continue
            dx = statement.parameters.get("dx")
            dy = statement.parameters.get("dy")
            if (
                isinstance(dx, int)
                and not isinstance(dx, bool)
                and isinstance(dy, int)
                and not isinstance(dy, bool)
                and (dx, dy) != (0, 0)
            ):
                translations.add((dx, dy))
        return next(iter(translations)) if len(translations) == 1 else None

    def _resolve_active_translation(
        self,
        translation: tuple[int, int],
        *,
        available_actions: Sequence[ActionName],
    ) -> ActionName | None:
        """Invert current mover-scoped bindings without a cardinal-name prior."""

        matches = tuple(
            action
            for action in available_actions
            if action is not ActionName.RESET
            and self._active_action_translation(action) == translation
        )
        return min(matches, key=lambda item: item.value) if matches else None

    def _learned_restore_action(self, observation: Observation) -> ActionRequest | None:
        condition = action_condition_signature(observation)
        for handle in self._action_effects.canonical_order(
            observation.available_actions,
            condition_signature=condition,
        ):
            if handle.requires_coordinates:
                continue
            effects = self._action_effects.accepted_effects(
                handle,
                condition_signature=condition,
            )
            if len(effects) == 1 and effects[0].effect_kind is CanonicalEffectKind.RESTORE:
                return ActionRequest(handle)
        return None

    def _set_provisional_mover(
        self,
        view: _PerceptionView,
        *,
        observed_mover_id: str | None = None,
    ) -> None:
        """Select a structural entity candidate without assigning action semantics."""

        if not view.symbolic_state.entities:
            self._provisional_mover_id = None
            return

        def structural_provisional_key(entity: SymbolicEntity) -> tuple[int, int, str]:
            boundary_evidence = (
                self._palette_roles.role_for(entity.color).evidence.boundary_count
                if entity.color is not None
                else 0
            )
            return (len(entity.cells), -boundary_evidence, entity.entity_id)

        provisional = (
            view.symbolic_state.entity(observed_mover_id)
            if observed_mover_id is not None
            else min(
                view.symbolic_state.entities,
                key=structural_provisional_key,
            )
        )
        if provisional is None:
            raise PolicyError("observed mover is absent from the current symbolic state")
        self._provisional_mover_id = provisional.entity_id

    def _clear_mover_reassignment(self) -> None:
        self._mover_reassignment_candidate_id = None
        self._mover_reassignment_last_component_id = None
        self._mover_reassignment_source_event_ids.clear()
        self._mover_reassignment_action_handles.clear()
        self._mover_reassignment_displacements.clear()

    def _action_effect_receipt_for_consequence(
        self,
        consequence_event_id: str,
        *,
        expected_action: ActionName,
    ) -> ActionEffectObservation:
        """Recover one exact raw action-effect receipt from the immutable journal."""

        matches = tuple(
            event
            for event in self._policy_events()
            if event.event_type == "action.effect_observed"
            and event.payload.get("source_consequence_event_id") == consequence_event_id
        )
        if len(matches) != 1:
            raise PolicyError(
                "confirmed mover history requires one immutable action-effect receipt"
            )
        payload = matches[0].payload
        raw_effects = payload.get("canonical_effects")
        before_digest = payload.get("before_digest")
        after_digest = payload.get("after_digest")
        if (
            payload.get("raw_handle") != expected_action.value
            or not isinstance(raw_effects, list)
            or not raw_effects
            or not all(isinstance(item, dict) for item in raw_effects)
            or not isinstance(before_digest, str)
            or not isinstance(after_digest, str)
        ):
            raise PolicyError("immutable action-effect receipt is malformed")
        try:
            canonical_effects = tuple(
                CanonicalActionEffect.from_projection(cast(Mapping[str, object], item))
                for item in raw_effects
            )
        except ValueError as error:
            raise PolicyError("immutable action-effect receipt is malformed") from error
        return ActionEffectObservation(
            source_event_id=consequence_event_id,
            raw_handle=expected_action,
            canonical_effects=canonical_effects,
            before_digest=FrameHash(before_digest),
            after_digest=FrameHash(after_digest),
        )

    def _reinterpret_confirmed_mover_history(
        self,
        observation: Observation,
        *,
        consequence_event_ids: tuple[str, ...],
        current_consequence_event_id: str,
        confirmation_event_id: str,
    ) -> None:
        """Reuse paid-for deferred receipts after mover lineage becomes authoritative.

        Raw transitions and observation-level effects remain unchanged.  Only
        prior transitions in the exact diverse-receipt confirmation window are
        interpreted against the newly established mover identity.
        """

        current_epoch_id = self._mechanics.active_epoch(self._level_index).epoch_id
        for consequence_event_id in consequence_event_ids:
            if consequence_event_id == current_consequence_event_id:
                # The current transition is preserved and interpreted later in
                # the ordinary consequence pipeline.
                continue
            matching_transitions = tuple(
                transition
                for transition in self._transitions
                if len(transition.source_event_ids) == 4
                and transition.source_event_ids[2] == consequence_event_id
                and self._transition_levels.get(transition.transition_id) == self._level_index
                and self._transition_epochs.get(transition.transition_id) == current_epoch_id
            )
            if len(matching_transitions) != 1:
                raise PolicyError(
                    "confirmed mover evidence does not identify one preserved transition"
                )
            transition = matching_transitions[0]
            raw = self._action_effect_receipt_for_consequence(
                consequence_event_id,
                expected_action=transition.action.name,
            )
            interpreted = self._controlled_action_effect_observation(
                observation,
                transition,
                raw,
                interpretation_timing="retrospective-after-mover-lineage-confirmation",
                authority_event_ids=(confirmation_event_id,),
                confirmation_consequence_event_ids=consequence_event_ids,
            )
            self._update_action_hypothesis(
                observation,
                transition,
                consequence_event_id,
                interpreted,
            )

    @staticmethod
    def _compatible_mover_lineage(
        predecessor: SymbolicEntity | None,
        successor: SymbolicEntity | None,
    ) -> bool:
        """Require stable observed structure before revising controlled identity."""

        if predecessor is None or successor is None:
            return False
        predecessor_attributes = dict(predecessor.attributes)
        successor_attributes = dict(successor.attributes)
        return (
            len(predecessor.cells) == len(successor.cells)
            and predecessor_attributes.get("shape") == successor_attributes.get("shape")
            and predecessor_attributes.get("palette_anonymous_identity")
            == successor_attributes.get("palette_anonymous_identity")
        )

    @staticmethod
    def _component_for_entity(
        entity: SymbolicEntity | None,
        components: Sequence[Component],
    ) -> Component | None:
        """Recover an observation-local component for one symbolic entity."""

        if entity is None:
            return None
        entity_cells = {(cell.x, cell.y) for cell in entity.cells}
        matches = tuple(
            component
            for component in components
            if component.color == entity.color
            and {(cell.x, cell.y) for cell in component.cells} == entity_cells
        )
        return matches[0] if len(matches) == 1 else None

    @staticmethod
    def _mover_candidate_is_receipt_supported(
        change: ComponentChange,
        component: Component,
        *,
        frame_width: int,
        frame_height: int,
    ) -> bool:
        """Bound controllability evidence to a compact exact correspondence.

        A merge, split, recolour, resize, or weak correspondence remains useful
        observation evidence, but it cannot transfer controlled-entity authority.
        The relative area bound excludes large terrain fragments without naming a
        palette, shape, game, or action.
        """

        if frame_width < 1 or frame_height < 1:
            return False
        if change.correspondence_score is None or change.correspondence_score < 0.7:
            return False
        if set(change.kinds) != {ComponentChangeKind.TRANSLATION}:
            return False
        frame_area = frame_width * frame_height
        compact_area = component.area <= max(4, frame_area // 8)
        bounded_width = component.bounds.width <= max(2, (3 * frame_width) // 4)
        bounded_height = component.bounds.height <= max(2, (3 * frame_height) // 4)
        return compact_area and bounded_width and bounded_height

    def _supersede_mover_hypotheses(
        self,
        observation: Observation,
        *,
        prior_mover_id: str,
        successor_mover_id: str,
        source_event_ids: tuple[str, ...],
    ) -> None:
        """Preserve and supersede entity-bound action rules after lineage confirmation."""

        epoch_id = self._mechanics.active_epoch(self._level_index).epoch_id
        predecessor_records = tuple(
            record
            for record in self._hypotheses.all()
            if isinstance(record.statement, ActionSemanticsStatement)
            and record.statement.parameters.get("entity_id") != successor_mover_id
            and record.is_ensemble_eligible
            and self._mechanics.hypothesis_epoch(record.hypothesis_id) == epoch_id
        )
        if not predecessor_records:
            return
        affected_model_ids = {
            model.model_id
            for model in self._model_candidates
            if any(
                hypothesis_id in model.hypothesis_ids
                for hypothesis_id in (record.hypothesis_id for record in predecessor_records)
            )
        }
        self._suspended_model_ids.update(affected_model_ids)
        for record in predecessor_records:
            statement = cast(ActionSemanticsStatement, record.statement)
            parameters = dict(statement.parameters)
            parameters["entity_id"] = successor_mover_id
            successor_statement = ActionSemanticsStatement(
                action=statement.action,
                effect=statement.effect,
                parameters=parameters,
                conditions=statement.conditions,
            )
            digest = sha256_json(
                {
                    "predecessor_hypothesis_id": record.hypothesis_id,
                    "successor_mover_id": successor_mover_id,
                    "mechanics_epoch_id": epoch_id,
                    "occurred_step": self._step_index,
                }
            ).removeprefix("sha256:")[:24]
            successor = self._hypotheses.create(
                statement=successor_statement,
                scope=record.scope,
                scope_ref=record.scope_ref,
                created_from_event_ids=source_event_ids,
                occurred_step=self._step_index,
                hypothesis_id=f"H-ACTION-LINEAGE-{digest}",
                parent_ids=(record.hypothesis_id,),
                initial_rank_weight=record.rank_weight,
                note="controlled mover lineage revised from diverse compatible receipts",
            )
            self._mechanics.register_hypotheses((successor.hypothesis_id,), epoch_id=epoch_id)
            lifecycle_event = self._hypotheses.events[-1]
            payload = lifecycle_event.to_trace_payload()
            payload["mechanics_epoch_id"] = epoch_id
            self._append(
                str(observation.game_id),
                "hypothesis.created",
                payload,
            )
            self._hypotheses.supersede(
                record.hypothesis_id,
                successor.hypothesis_id,
                occurred_step=self._step_index,
                caused_by_event_ids=source_event_ids,
                note="diverse compatible receipts established a successor mover lineage",
            )
            lifecycle_event = self._hypotheses.events[-1]
            self._append(
                str(observation.game_id),
                "hypothesis.superseded",
                lifecycle_event.to_trace_payload(),
            )
            invalidated_plan_ids = self._hypotheses.dependent_plan_ids(record.hypothesis_id)
            self._invalidated_plan_ids.update(invalidated_plan_ids)
            if invalidated_plan_ids:
                self._append(
                    str(observation.game_id),
                    "simulation.plan_invalidated",
                    {
                        "plan_ids": list(invalidated_plan_ids),
                        "source_event_ids": list(source_event_ids),
                        "source_hypothesis_id": record.hypothesis_id,
                        "reason": "controlled mover lineage was superseded",
                    },
                )
        self._ensemble = None
        self._plan_executor = PlanExecutor()
        self._pending_plan_emission = False

    def _adopt_observed_mover(
        self,
        observation: Observation,
        receipt: ObservationReceipt,
        view: _PerceptionView,
        before_state: SymbolicState,
        before_components: Sequence[Component],
        submitted_action: ActionRequest,
        *,
        consequence_event_id: str,
    ) -> bool:
        """Return whether entity-bound mechanics may use this transition.

        A structural guess is not control authority.  When motion points to a
        different component, the controller keeps the raw receipt and defers
        entity-bound semantics until two consecutive, coherent consequences
        provide both handle and displacement diversity.  An already controlled
        lineage may change its local entity ID, but only through the tracked
        predecessor component.  Merge/split, recolour, resize, weak matching,
        and large moving terrain remain explicit ambiguous evidence.
        """

        tracking = view.tracking
        if tracking is None:
            return True
        moved_changes = tuple(
            change
            for change in tracking.changes
            if change.after_id is not None
            and ComponentChangeKind.TRANSLATION in change.kinds
            and change.displacement not in {None, (0, 0)}
        )
        epoch_id = self._mechanics.active_epoch(self._level_index).epoch_id
        mover_has_dependent_rule = self._provisional_mover_id is not None and any(
            isinstance(record.statement, ActionSemanticsStatement)
            and record.statement.parameters.get("entity_id") == self._provisional_mover_id
            and record.is_ensemble_eligible
            and self._mechanics.hypothesis_epoch(record.hypothesis_id) == epoch_id
            for record in self._hypotheses.all()
        )
        prior_entity = (
            before_state.entity(self._provisional_mover_id)
            if self._provisional_mover_id is not None
            else None
        )
        prior_component = self._component_for_entity(prior_entity, before_components)
        prior_component_id = prior_component.component_id if prior_component is not None else None

        def after_entity_id(change: ComponentChange) -> str | None:
            return (
                self._component_to_entity.get(change.after_id)
                if change.after_id is not None
                else None
            )

        controlled_changes = tuple(
            change for change in moved_changes if change.before_id == prior_component_id
        )
        direct_controlled = tuple(
            change
            for change in controlled_changes
            if after_entity_id(change) == self._provisional_mover_id
        )
        if direct_controlled and (mover_has_dependent_rule or len(moved_changes) == 1):
            self._clear_mover_reassignment()
            return True

        continuing_changes = tuple(
            change
            for change in moved_changes
            if change.before_id == self._mover_reassignment_last_component_id
        )
        moved_change: ComponentChange | None = None
        if len(continuing_changes) == 1:
            moved_change = continuing_changes[0]
        elif len(controlled_changes) == 1 and mover_has_dependent_rule:
            moved_change = controlled_changes[0]
        elif not mover_has_dependent_rule and len(moved_changes) == 1:
            moved_change = moved_changes[0]

        if moved_change is None:
            if mover_has_dependent_rule and prior_component_id is not None:
                # Motion elsewhere does not revise a receipt-backed controlled
                # entity.  Its stationary outcome may still inform collision.
                self._clear_mover_reassignment()
                return True
            self._append(
                str(observation.game_id),
                "perception.salience_computed",
                {
                    "salience_kind": "ambiguous-controllability-deferred",
                    "source_consequence_event_id": consequence_event_id,
                    "source_observation_event_id": receipt.observation_event_id,
                    "prior_entity_candidate_id": self._provisional_mover_id,
                    "moving_component_count": len(moved_changes),
                    "candidate_retained": self._mover_reassignment_candidate_id is not None,
                    "revision": "entity-bound action semantics deferred",
                },
            )
            return False

        component_id = moved_change.after_id
        assert component_id is not None
        mover_id = self._component_to_entity.get(component_id)
        candidate_component = next(
            (component for component in view.components if component.component_id == component_id),
            None,
        )
        candidate_entity = view.symbolic_state.entity(mover_id) if mover_id is not None else None
        lineage_predecessor = (
            before_state.entity(self._mover_reassignment_candidate_id)
            if self._mover_reassignment_candidate_id is not None
            else prior_entity
            if mover_has_dependent_rule
            else None
        )
        valid_receipt = (
            mover_id is not None
            and candidate_component is not None
            and self._mover_candidate_is_receipt_supported(
                moved_change,
                candidate_component,
                frame_width=observation.frames[-1].width,
                frame_height=observation.frames[-1].height,
            )
            and (
                lineage_predecessor is None
                or self._compatible_mover_lineage(lineage_predecessor, candidate_entity)
            )
        )
        if not valid_receipt:
            self._clear_mover_reassignment()
            self._append(
                str(observation.game_id),
                "perception.object_correspondence_rejected",
                {
                    "source_consequence_event_id": consequence_event_id,
                    "source_observation_event_id": receipt.observation_event_id,
                    "prior_entity_candidate_id": self._provisional_mover_id,
                    "observed_entity_candidate_id": mover_id,
                    "reason": (
                        "correspondence is weak, non-exact, structurally incompatible, "
                        "or exceeds the bounded mover footprint"
                    ),
                    "authority": "controlled mover unchanged; action semantics deferred",
                },
            )
            return False

        displacement = cast(tuple[int, int], moved_change.displacement)
        is_continuation = (
            self._mover_reassignment_candidate_id is not None
            and moved_change.before_id == self._mover_reassignment_last_component_id
        )
        if not is_continuation:
            self._mover_reassignment_source_event_ids = [consequence_event_id]
            self._mover_reassignment_action_handles = {submitted_action.name}
            self._mover_reassignment_displacements = {displacement}
        elif consequence_event_id not in self._mover_reassignment_source_event_ids:
            self._mover_reassignment_source_event_ids.append(consequence_event_id)
            self._mover_reassignment_action_handles.add(submitted_action.name)
            self._mover_reassignment_displacements.add(displacement)
        self._mover_reassignment_candidate_id = mover_id
        self._mover_reassignment_last_component_id = component_id

        has_diverse_control_evidence = (
            len(self._mover_reassignment_action_handles) >= 2
            and len(self._mover_reassignment_displacements) >= 2
        )
        if len(self._mover_reassignment_source_event_ids) < 2 or not has_diverse_control_evidence:
            if len(self._mover_reassignment_source_event_ids) == 2:
                # Keep a one-receipt rolling boundary; later diversity must be
                # demonstrated by an actual pair, not accumulated narratively.
                self._mover_reassignment_source_event_ids = [consequence_event_id]
                self._mover_reassignment_action_handles = {submitted_action.name}
                self._mover_reassignment_displacements = {displacement}
            self._append(
                str(observation.game_id),
                "perception.salience_computed",
                {
                    "salience_kind": "provisional-controllability-revision",
                    "source_consequence_event_id": consequence_event_id,
                    "source_observation_event_id": receipt.observation_event_id,
                    "prior_entity_candidate_id": self._provisional_mover_id,
                    "observed_entity_candidate_id": mover_id,
                    "support_count": len(self._mover_reassignment_source_event_ids),
                    "distinct_action_handles": len(self._mover_reassignment_action_handles),
                    "distinct_displacements": len(self._mover_reassignment_displacements),
                    "confirmation_rule": (
                        "two consecutive compatible consequences with action and direction diversity"
                    ),
                    "revision": "derived candidate only; mover authority unchanged",
                },
            )
            return False

        prior_mover_id = self._provisional_mover_id
        source_event_ids = tuple(self._mover_reassignment_source_event_ids)
        assert mover_id is not None
        self._set_provisional_mover(view, observed_mover_id=mover_id)
        self._clear_mover_reassignment()
        if prior_mover_id is not None and source_event_ids:
            self._supersede_mover_hypotheses(
                observation,
                prior_mover_id=prior_mover_id,
                successor_mover_id=mover_id,
                source_event_ids=source_event_ids,
            )
        if self._active_goal_id is not None:
            target = self._select_contact_target(view.symbolic_state, mover_id)
            if target is not None:
                self._bind_contact_goal(
                    observation,
                    receipt,
                    view,
                    goal_id=self._active_goal_id,
                    mover_id=mover_id,
                    target_id=target.entity_id,
                    reason="observed mover-lineage revision",
                    source_consequence_event_id=consequence_event_id,
                )
        confirmation = self._append(
            str(observation.game_id),
            "perception.salience_computed",
            {
                "salience_kind": "observed-controllability-revision",
                "source_consequence_event_id": consequence_event_id,
                "source_observation_event_id": receipt.observation_event_id,
                "prior_entity_candidate_id": prior_mover_id,
                "observed_entity_candidate_id": mover_id,
                "supporting_consequence_event_ids": list(
                    source_event_ids or (consequence_event_id,)
                ),
                "evidence": "sole tracked component with nonzero translation",
                "revision": "derived interpretation only; raw receipts remain unchanged",
            },
        )
        self._reinterpret_confirmed_mover_history(
            observation,
            consequence_event_ids=source_event_ids,
            current_consequence_event_id=consequence_event_id,
            confirmation_event_id=confirmation.event_id,
        )
        return True

    @staticmethod
    def _select_contact_target(state: SymbolicState, mover_id: str) -> SymbolicEntity | None:
        """Select a compact observed role before a fragmented surface component."""

        if state.entity(mover_id) is None:
            # A temporarily occluded mover cannot ground a new contact binding.
            # Keep the prior goal history revisable and retry on a later
            # observation instead of substituting another visible entity.
            return None
        candidates = tuple(item for item in state.entities if item.entity_id != mover_id)
        if not candidates:
            return None

        def anonymous_identity(entity: SymbolicEntity) -> str:
            return dict(entity.attributes).get("palette_anonymous_identity", entity.kind)

        identity_footprints = {
            identity: sum(
                len(item.cells) for item in state.entities if anonymous_identity(item) == identity
            )
            for identity in {anonymous_identity(item) for item in state.entities}
        }

        def target_key(entity: SymbolicEntity) -> tuple[int, int, int, str]:
            distance = _entity_distance(state, mover_id, entity.entity_id)
            return (
                identity_footprints[anonymous_identity(entity)],
                len(entity.cells),
                distance if distance is not None else state.width + state.height,
                entity.entity_id,
            )

        return min(candidates, key=target_key)

    @_profiled("goal_inference")
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
            and record.candidate.goal_id in self._goal_targets
            and all(
                view.symbolic_state.entity(entity_id) is not None
                for entity_id in self._goal_targets[record.candidate.goal_id]
            )
        )
        if current:
            record = current[0]
            goal_id = record.candidate.goal_id
            if self._active_goal_id != goal_id:
                mover_id, target_id = self._goal_targets[goal_id]
                self._bind_contact_goal(
                    observation,
                    receipt,
                    view,
                    goal_id=goal_id,
                    mover_id=mover_id,
                    target_id=target_id,
                    reason="source-visible contact goal reactivated",
                )
            return
        if len(entities) < 2:
            return
        mover_id = (
            self._provisional_mover_id
            or min(entities, key=lambda item: (len(item.cells), item.entity_id)).entity_id
        )
        target = self._select_contact_target(view.symbolic_state, mover_id)
        if target is None:
            return
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
        self._flush_goal_events(observation)
        self._bind_contact_goal(
            observation,
            receipt,
            view,
            goal_id=goal_id,
            mover_id=mover_id,
            target_id=target.entity_id,
            reason="contact candidate created from ordinary observation",
        )

    def _bind_contact_goal(
        self,
        observation: Observation,
        receipt: ObservationReceipt,
        view: _PerceptionView,
        *,
        goal_id: str,
        mover_id: str,
        target_id: str,
        reason: str,
        source_consequence_event_id: str | None = None,
    ) -> None:
        """Record a receipt-grounded contact binding before it gains policy authority."""

        record = self._goals.get(goal_id)
        mover = view.symbolic_state.entity(mover_id)
        target = view.symbolic_state.entity(target_id)
        previous = self._goal_targets.get(goal_id)
        if (
            record.candidate.kind is not GoalKind.CONTACT
            or mover is None
            or target is None
            or (
                previous != (mover_id, target_id)
                and self._select_contact_target(view.symbolic_state, mover_id) != target
            )
        ):
            raise PolicyError("contact goal binding is not derived from the source observation")
        binding = (mover_id, target_id)
        self._goal_targets[goal_id] = binding
        self._active_goal_id = goal_id
        self._append(
            str(observation.game_id),
            "goal.target_bound",
            {
                "goal_id": goal_id,
                "mover_entity_id": mover_id,
                "target_entity_id": target_id,
                "source_observation_event_id": receipt.observation_event_id,
                "source_consequence_event_id": source_consequence_event_id,
                "source_symbolic_state_id": view.symbolic_state.state_id,
                "goal_target_state": record.candidate.target_state,
                "previous_binding": list(previous) if previous is not None else None,
                "binding_reason": reason,
                "activates_goal": True,
            },
        )

    def _retarget_contact_goal_after_progress(
        self,
        observation: Observation,
        receipt: ObservationReceipt,
        view: _PerceptionView,
        transition: PreservedTransition,
        *,
        consequence_event_id: str,
    ) -> None:
        """Retire a reached contact target and derive a fresh observed candidate.

        The prior goal remains in the lifecycle registry.  Retargeting is
        permitted only when the returned consequence shows the mover occupying
        the target's prior cells and that target has disappeared or changed
        position.  The next candidate is derived from the new observation.
        """

        goal_id = self._active_goal_id
        if goal_id is None or goal_id not in self._goal_targets:
            return
        record = self._goals.get(goal_id)
        if record.candidate.kind is not GoalKind.CONTACT:
            return
        mover_id, target_id = self._goal_targets[goal_id]
        before_mover = transition.before.entity(mover_id)
        after_mover = transition.after.entity(mover_id)
        before_target = transition.before.entity(target_id)
        after_target = transition.after.entity(target_id)
        if before_mover is None or after_mover is None or before_target is None:
            return
        reached_prior_cells = bool(set(after_mover.cells) & set(before_target.cells))
        target_changed = after_target is None or after_target.cells != before_target.cells
        target_disappeared = after_target is None
        if not target_disappeared and not (reached_prior_cells and target_changed):
            return

        active_plan = self._plan_executor.plan
        if active_plan is not None and active_plan.goal_id == goal_id:
            self._invalidated_plan_ids.add(active_plan.plan_id)
            self._append(
                str(observation.game_id),
                "simulation.plan_invalidated",
                {
                    "plan_ids": [active_plan.plan_id],
                    "source_event_ids": [
                        consequence_event_id,
                        receipt.observation_event_id,
                    ],
                    "source_goal_id": goal_id,
                    "reason": "contact target changed after observed progress",
                },
            )
            self._plan_executor = PlanExecutor()
        sources = (consequence_event_id, receipt.observation_event_id)
        self._goals.retire(
            goal_id,
            source_event_ids=sources,
            summary=(
                "contact target disappeared from the returned observation"
                if target_disappeared
                else "contact target changed after mover reached its prior observed cells"
            ),
        )
        self._active_goal_id = None
        self._flush_goal_events(observation)
        self._seed_contact_goal(observation, receipt, view)

    @_profiled("goal_inference")
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

    @_profiled("world_model_compilation")
    def _update_world_models(self, observation: Observation) -> None:
        if not self.features.use_world_model or not self._hypotheses.all():
            self._ensemble = None
            return
        current_scope = f"level:{self._level_index}"
        current_epoch_id = self._mechanics.active_epoch(self._level_index).epoch_id
        eligible = tuple(
            record
            for record in self._hypotheses.all()
            if record.scope is not HypothesisScope.LEVEL or record.scope_ref == current_scope
            if self._mechanics.hypothesis_epoch(record.hypothesis_id) == current_epoch_id
            if self.features.retain_rejected_hypotheses
            or (
                record.status is not HypothesisStatus.REJECTED and not record.contradiction_receipts
            )
        )
        if not eligible:
            self._model_candidates = ()
            self._ensemble = None
            return
        compiled = compile_hypotheses(eligible)
        self._model_candidates = compiled.candidates
        level_transitions = (
            tuple(
                item
                for item in self._transition_summaries.get(self._level_index, ())
                if self._transition_epochs.get(item.transition_id) == current_epoch_id
                and item.transition_id not in self._resolved_noise_transition_ids
            )
            if self.features.use_trace_summaries
            else tuple(
                item
                for item in self._transitions
                if self._transition_levels.get(item.transition_id) == self._level_index
                and self._transition_epochs.get(item.transition_id) == current_epoch_id
                and item.transition_id not in self._resolved_noise_transition_ids
            )
        )
        artifacts: list[RetrodictionArtifact] = []
        completed_by_model: dict[str, tuple[RetrodictionEvaluation, TraceEvent]] = {}
        force_full_source_event_ids = tuple(self._retrodiction_force_full_source_event_ids)
        runtime_before = self._retrodiction_runtime.to_dict()
        try:
            for candidate in compiled.candidates:
                (
                    request,
                    deferred_unclaimed_action_ids,
                    deferred_collision_ambiguous_ids,
                ) = self._retrodiction_request(
                    candidate,
                    level_transitions,
                    mechanics_epoch_id=current_epoch_id,
                    force_full_source_event_ids=force_full_source_event_ids,
                )
                plan = self._plan_retrodiction(request)
                candidate_receipt_payload: dict[str, JSONValue] = {
                    "candidate_compile_residuals": list(candidate.compile_residuals),
                    "candidate_hypothesis_ids": list(candidate.hypothesis_ids),
                    "candidate_rank_weight": candidate.rank_weight,
                }
                started = self._append(
                    str(observation.game_id),
                    "model.retrodiction_started",
                    {
                        **plan.to_trace_payload(),
                        **candidate_receipt_payload,
                        "namespace_key": plan.namespace_key,
                        # Legacy receipt fields remain stable for Build 000 replay.
                        "transition_ids": [item.transition_id for item in request.transitions],
                        "deferred_unclaimed_action_transition_ids": list(
                            deferred_unclaimed_action_ids
                        ),
                        "deferred_collision_ambiguous_transition_ids": list(
                            deferred_collision_ambiguous_ids
                        ),
                    },
                )
                evaluation = self._execute_retrodiction(plan)
                reused: TraceEvent | None = None
                if evaluation.reused:
                    reused = self._append(
                        str(observation.game_id),
                        "model.retrodiction_reused",
                        {
                            **evaluation.to_trace_payload(),
                            **candidate_receipt_payload,
                            "namespace_key": plan.namespace_key,
                            "retrodiction_started_event_id": started.event_id,
                        },
                    )
                artifact = evaluation.artifact
                completed = self._append(
                    str(observation.game_id),
                    "model.retrodiction_completed",
                    {
                        **evaluation.to_trace_payload(),
                        **candidate_receipt_payload,
                        "artifact_projection": normalize_json(asdict(artifact)),
                        "complete": artifact.complete,
                        "namespace_key": plan.namespace_key,
                        "retrodiction_reused_event_id": (
                            reused.event_id if reused is not None else None
                        ),
                        "retrodiction_started_event_id": started.event_id,
                    },
                )
                self._commit_retrodiction(
                    evaluation,
                    source_receipt_event_id=completed.event_id,
                )
                artifacts.append(artifact)
                completed_by_model[candidate.model_id] = (evaluation, completed)
        except (ARC3ValidationError, WorldModelError):
            self._retrodiction_runtime = RetrodictionRuntime.from_dict(
                runtime_before,
                expected_config=self._retrodiction_runtime.config,
            )
            raise
        if compiled.candidates:
            self._retrodiction_force_full_source_event_ids.clear()
        accepted_ids = {
            artifact.model_id
            for artifact in artifacts
            if artifact.status is PromotionStatus.PROMOTED
            or (
                not self.features.use_retrodiction_gate
                and artifact.status is PromotionStatus.UNGATED_ABLATION
            )
            if artifact.model_id not in self._suspended_model_ids
            and artifact.model_id not in self._demoted_model_ids
        }
        if accepted_ids:
            self._ensemble = gated_ensemble(
                tuple(item for item in compiled.candidates if item.model_id in accepted_ids),
                tuple(item for item in artifacts if item.model_id in accepted_ids),
                allow_ungated_ablation=not self.features.use_retrodiction_gate,
            )
            self._mechanics.register_models(
                (candidate.model_id for candidate in self._ensemble.candidates),
                epoch_id=current_epoch_id,
            )
            for candidate in self._ensemble.candidates:
                evaluation, completed = completed_by_model[candidate.model_id]
                self._append(
                    str(observation.game_id),
                    "model.rule_promoted",
                    {
                        "model_id": candidate.model_id,
                        "hypothesis_ids": list(candidate.hypothesis_ids),
                        "mechanics_epoch_id": current_epoch_id,
                        "retrodiction_artifact_id": evaluation.artifact.artifact_id,
                        "retrodiction_completed_event_id": completed.event_id,
                        "retrodiction_mode": evaluation.plan.mode.value,
                        "retrodiction_reason": evaluation.plan.reason.value,
                        "promotion_basis": (
                            "complete compatible-trace retrodiction"
                            if self.features.use_retrodiction_gate
                            else "ungated Stage 14 ablation"
                        ),
                    },
                )
        else:
            self._ensemble = None

    def _retrodiction_request(
        self,
        candidate: ModelCandidate,
        transitions: tuple[PreservedTransition, ...],
        *,
        mechanics_epoch_id: str,
        force_full_source_event_ids: tuple[str, ...],
    ) -> tuple[RetrodictionRequest, tuple[str, ...], tuple[str, ...]]:
        (
            compatible,
            deferred_unclaimed_action_ids,
            deferred_collision_ambiguous_ids,
        ) = self._candidate_retrodiction_partition(candidate, transitions)
        projected = tuple(
            self._candidate_retrodiction_projection(candidate, transition)
            for transition in compatible
        )
        resolved_noise_ids = tuple(
            sorted(
                transition_id
                for transition_id in self._resolved_noise_transition_ids
                if self._transition_levels.get(transition_id) == self._level_index
                and self._transition_epochs.get(transition_id) == mechanics_epoch_id
            )
        )
        omissions = tuple(
            RetrodictionOmission(transition_id, reason)
            for transition_id, reason in (
                *((item, "unclaimed-action") for item in deferred_unclaimed_action_ids),
                *((item, "collision-ambiguous") for item in deferred_collision_ambiguous_ids),
                *((item, "resolved-noise") for item in resolved_noise_ids),
            )
        )
        matched_evidence = tuple(
            evidence
            for transition in projected
            if (
                evidence := self._matched_prediction_evidence.get(
                    (transition.transition_id, candidate.model_id)
                )
            )
            is not None
        )
        return (
            RetrodictionRequest(
                model=candidate,
                transitions=projected,
                mechanics_epoch_id=mechanics_epoch_id,
                omissions=omissions,
                resolved_noise_transition_ids=resolved_noise_ids,
                force_full_source_event_ids=force_full_source_event_ids,
                matched_evidence=matched_evidence,
            ),
            deferred_unclaimed_action_ids,
            deferred_collision_ambiguous_ids,
        )

    @_profiled("retrodiction")
    def _plan_retrodiction(
        self,
        request: RetrodictionRequest,
    ) -> RetrodictionPlan:
        return self._retrodiction_runtime.plan(request)

    @_profiled("retrodiction")
    def _execute_retrodiction(
        self,
        plan: RetrodictionPlan,
    ) -> RetrodictionEvaluation:
        if self._hot_path_profiler is not None:
            self._hot_path_profiler.cache(
                "retrodiction",
                plan.cache_hit,
                input_key=plan.cache_key,
                change_kind=self._retrodiction_hot_path_change_kind(plan),
            )
        return self._retrodiction_runtime.execute(plan)

    @_profiled("retrodiction")
    def _commit_retrodiction(
        self,
        evaluation: RetrodictionEvaluation,
        *,
        source_receipt_event_id: str,
    ) -> None:
        self._retrodiction_runtime.commit(
            evaluation,
            source_receipt_event_id=source_receipt_event_id,
        )

    @staticmethod
    def _retrodiction_hot_path_change_kind(plan: RetrodictionPlan) -> _HotPathChangeKindValue:
        """Map retrodiction semantics onto stable profiler-only change classes."""

        if plan.reason in {
            RetrodictionReason.DISABLED,
            RetrodictionReason.EXACT_CACHE_HIT,
        }:
            return "unchanged"
        if plan.reason is RetrodictionReason.FIRST_USE:
            return "initial"
        if plan.reason in {
            RetrodictionReason.PREFIX_EXTENSION,
            RetrodictionReason.EVENT_RECEIPT_REUSE,
        }:
            return "history_growth"
        if plan.reason in {
            RetrodictionReason.NON_PREFIX,
            RetrodictionReason.INVALIDATED,
        }:
            return "global_change"
        if plan.reason in {
            RetrodictionReason.FULL,
            RetrodictionReason.EVENT_FULL_AUDIT,
        }:
            return "initial" if plan.generation == 1 else "global_change"
        if plan.reason is RetrodictionReason.RECENT_WINDOW:
            return "initial" if plan.state_access_ordinal == 0 else "history_growth"
        raise PolicyError(f"unsupported retrodiction reason: {plan.reason.value}")

    @staticmethod
    def _candidate_retrodiction_projection(
        candidate: ModelCandidate,
        transition: PreservedTransition,
    ) -> PreservedTransition:
        """Project pure movement models onto the entities they claim to govern.

        Exogenous waypoint motion and terrain occlusion remain in the preserved
        transition and trace residuals.  They are omitted only from this
        explicitly derived handle-semantics test, preventing unrelated object
        motion from falsifying the claimed controlled displacement.
        """

        if not candidate.rules or any(
            not isinstance(rule, (MovementRule, NoOpRule, CollisionRule))
            for rule in candidate.rules
        ):
            return transition
        entity_rules = tuple(
            rule for rule in candidate.rules if isinstance(rule, (MovementRule, NoOpRule))
        )
        governed_ids = {
            entity.entity_id
            for rule in entity_rules
            for entity in transition.before.entities
            if (rule.entity_id is None or entity.entity_id == rule.entity_id)
            and (rule.entity_kind is None or entity.kind == rule.entity_kind)
        }
        if not governed_ids:
            return transition

        def project(state: SymbolicState) -> SymbolicState:
            entities = tuple(
                entity for entity in state.entities if entity.entity_id in governed_ids
            )
            present = {entity.entity_id for entity in entities}
            return SymbolicState(
                width=state.width,
                height=state.height,
                entities=entities,
                facts=state.facts,
                counters=state.counters,
                toggles=state.toggles,
                selected_id=(state.selected_id if state.selected_id in present else None),
                attachments=tuple(
                    item
                    for item in state.attachments
                    if item.child_id in present and item.parent_id in present
                ),
            )

        return PreservedTransition(
            transition_id=transition.transition_id,
            before=project(transition.before),
            action=transition.action,
            after=project(transition.after),
            source_event_ids=transition.source_event_ids,
            compatible_model_ids=transition.compatible_model_ids,
        )

    @staticmethod
    def _candidate_retrodiction_transitions(
        candidate: ModelCandidate,
        transitions: tuple[PreservedTransition, ...],
    ) -> tuple[PreservedTransition, ...]:
        """Return transitions within the candidate's claimed executable action scope."""

        return ARC3Controller._candidate_retrodiction_partition(candidate, transitions)[0]

    @staticmethod
    def _candidate_retrodiction_partition(
        candidate: ModelCandidate,
        transitions: tuple[PreservedTransition, ...],
    ) -> tuple[tuple[PreservedTransition, ...], tuple[str, ...], tuple[str, ...]]:
        """Partition claimed transitions from explicit, source-honest deferrals.

        A partial candidate makes no identity/no-op claim about actions for which
        it has no executable rule.  Collision and occlusion have their own typed
        destination-role evidence, so exact handle-semantics retrodiction also
        defers ambiguous occupied-destination transitions.  Raw transitions stay
        preserved; both deferral classes are retained in the trace receipt.
        """

        movement_rules = tuple(rule for rule in candidate.rules if isinstance(rule, MovementRule))
        collision_rules = tuple(rule for rule in candidate.rules if isinstance(rule, CollisionRule))
        governed_actions = frozenset(
            action for rule in candidate.rules if (action := rule_action(rule)) is not None
        )

        def matches_kind(entity: SymbolicEntity, expected: str) -> bool:
            return (
                entity.kind == expected or dict(entity.attributes).get("palette_role") == expected
            )

        def collision_ambiguous(transition: PreservedTransition) -> bool:
            applicable = tuple(
                rule for rule in movement_rules if rule.action is transition.action.name
            )
            for rule in applicable:
                movers = tuple(
                    entity
                    for entity in transition.before.entities
                    if (rule.entity_id is None or entity.entity_id == rule.entity_id)
                    and (rule.entity_kind is None or entity.kind == rule.entity_kind)
                )
                for mover in movers:
                    destination = mover.translated(rule.dx, rule.dy)
                    if any(not transition.before.contains(cell) for cell in destination.cells):
                        return True
                    obstacles = tuple(
                        other
                        for other in transition.before.entities
                        if other.entity_id != mover.entity_id
                        and bool(set(other.cells) & set(destination.cells))
                    )
                    after_mover = transition.after.entity(mover.entity_id)
                    if (
                        after_mover is not None
                        and after_mover.cells == mover.cells
                        and not obstacles
                    ):
                        # Modal/background terrain is intentionally absent from
                        # the component graph.  A stationary receipt at such a
                        # destination is topology/collision ambiguity, not a
                        # contradiction of the action's supported displacement.
                        # The raw no-op remains in the trace and action registry.
                        return True
                    for obstacle in obstacles:
                        relation = next(
                            (
                                item
                                for item in collision_rules
                                if matches_kind(mover, item.moving_kind)
                                and matches_kind(obstacle, item.obstacle_kind)
                            ),
                            None,
                        )
                        if relation is None or relation.behavior in {
                            CollisionBehavior.BLOCK,
                            CollisionBehavior.REMOVE_MOVER,
                        }:
                            return True
            return False

        unclaimed = tuple(
            transition
            for transition in transitions
            if transition.action.name not in governed_actions
        )
        claimed = tuple(
            transition for transition in transitions if transition.action.name in governed_actions
        )
        collision_deferred = tuple(
            transition for transition in claimed if collision_ambiguous(transition)
        )
        collision_ids = {transition.transition_id for transition in collision_deferred}
        accepted = tuple(
            transition for transition in claimed if transition.transition_id not in collision_ids
        )
        return (
            accepted,
            tuple(transition.transition_id for transition in unclaimed),
            tuple(transition.transition_id for transition in collision_deferred),
        )

    def _controlled_prediction_match_model_ids(
        self,
        *,
        before: SymbolicState,
        action: ActionRequest,
        after: SymbolicState,
        source_event_ids: tuple[str, ...],
    ) -> tuple[str, ...]:
        """Return models whose declared controlled projection matched exactly.

        Whole symbolic frames include exogenous guides and component fragments.
        A model promoted through controlled-entity retrodiction predicts that
        same typed projection.  We retain exact whole-state mismatch in the
        consequence payload while allowing a source-honest projection match to
        preserve the model's scoped authority.
        """

        if self._ensemble is None:
            return ()
        boundary = PreservedTransition(
            transition_id=f"pending-projection:{source_event_ids[-1]}",
            before=before,
            action=action,
            after=after,
            source_event_ids=source_event_ids,
        )
        matched: list[str] = []
        for candidate in self._ensemble.candidates:
            compatible = self._candidate_retrodiction_transitions(candidate, (boundary,))
            if not compatible:
                continue
            projected = self._candidate_retrodiction_projection(candidate, compatible[0])
            if candidate.predict(projected.before, action).after_state == projected.after:
                matched.append(candidate.model_id)
        return tuple(sorted(matched))

    def _record_prediction_match_evidence(
        self,
        *,
        transition_id: str,
        prediction: PredictionReceipt,
        prediction_event_id: str | None,
        consequence_event_id: str,
        assessment_receipt_id: str,
        assessment_event: TraceEvent,
        observed_state_id: str,
        controlled_match_model_ids: tuple[str, ...],
    ) -> None:
        """Retain candidate-specific match evidence without replacing raw receipts."""

        if prediction_event_id is None:
            return
        prediction_event = self.journal.get_event(prediction_event_id)
        consequence_event = self.journal.get_event(consequence_event_id)
        submitted_event_id = (
            consequence_event.payload.get("submitted_event_id")
            if consequence_event is not None
            else None
        )
        selected_event_id = (
            consequence_event.payload.get("selected_event_id")
            if consequence_event is not None
            else None
        )
        submitted_event = (
            self.journal.get_event(submitted_event_id)
            if isinstance(submitted_event_id, str)
            else None
        )
        selected_event = (
            self.journal.get_event(selected_event_id)
            if isinstance(selected_event_id, str)
            else None
        )
        prediction_payload = prediction.to_dict()
        mechanics_epoch_id = assessment_event.payload.get("mechanics_epoch_id")
        if (
            prediction_event is None
            or prediction_event.event_type != "simulation.prediction_emitted"
            or prediction_event.payload.get("receipt_id") != prediction.receipt_id
            or {
                key: item
                for key, item in prediction_event.payload.items()
                if key
                not in {
                    "cache_hit",
                    "cache_key_hash",
                    "cache_projection_hash",
                    "mechanics_epoch_id",
                }
            }
            != prediction_payload
            or consequence_event is None
            or consequence_event.event_type != "consequence.received"
            or submitted_event is None
            or submitted_event.event_type != "action.submitted"
            or selected_event is None
            or selected_event.event_type != "action.selected"
            or submitted_event.payload.get("selected_event_id") != selected_event.event_id
            or submitted_event.payload.get("decision_id") != prediction.action_decision_id
            or selected_event.payload.get("decision_id") != prediction.action_decision_id
            or submitted_event.payload.get("action") != _action_payload(prediction.action)
            or selected_event.payload.get("selected_action") != _action_payload(prediction.action)
            or consequence_event.payload.get("action") != _action_payload(prediction.action)
            or not isinstance(mechanics_epoch_id, str)
            or prediction_event.payload.get("mechanics_epoch_id") != mechanics_epoch_id
            or selected_event.payload.get("mechanics_epoch_id") != mechanics_epoch_id
            or assessment_event.event_type
            not in {"consequence.matched_prediction", "consequence.mismatched_prediction"}
            or assessment_event.payload.get("receipt_id") != assessment_receipt_id
        ):
            return
        exact_model_ids = {
            model_id
            for alternative in prediction.prediction.alternatives
            if alternative.after_state_id == observed_state_id
            for model_id in alternative.supporting_model_ids
        }
        controlled_ids = set(controlled_match_model_ids)
        predicted_model_ids = {
            model_id
            for alternative in prediction.prediction.alternatives
            for model_id in alternative.supporting_model_ids
        }
        for model_id in sorted(predicted_model_ids | controlled_ids):
            matched = model_id in exact_model_ids or model_id in controlled_ids
            scope = (
                "whole-symbolic-state"
                if model_id in exact_model_ids
                else "controlled-entity-projection"
                if model_id in controlled_ids
                else "none"
            )
            evidence = MatchedPredictionEvidence(
                transition_id=transition_id,
                model_id=model_id,
                prediction_event_id=prediction_event_id,
                prediction_receipt_id=prediction.receipt_id,
                consequence_event_id=consequence_event_id,
                assessment_receipt_id=assessment_receipt_id,
                matched=matched,
                match_scope=scope,
            )
            self._matched_prediction_evidence[(transition_id, model_id)] = evidence

    def _rebuild_matched_prediction_evidence_from_trace(self) -> None:
        """Reconstruct event-triggered evidence from immutable source receipts."""

        events = self._policy_events()
        event_by_id = {event.event_id: event for event in events}
        event_order = {event.event_id: index for index, event in enumerate(events)}
        predictions: dict[str, TraceEvent] = {}
        assessments: dict[str, TraceEvent] = {}
        for event in events:
            if event.event_type == "simulation.prediction_emitted":
                receipt_id = event.payload.get("receipt_id")
                if not isinstance(receipt_id, str) or receipt_id in predictions:
                    raise PolicyError("immutable prediction receipt identity is malformed")
                predictions[receipt_id] = event
            elif event.event_type in {
                "consequence.matched_prediction",
                "consequence.mismatched_prediction",
            }:
                prediction_receipt_id = event.payload.get("prediction_receipt_id")
                if prediction_receipt_id is None and event.payload.get("restored_pending_action"):
                    continue
                if (
                    not isinstance(prediction_receipt_id, str)
                    or prediction_receipt_id in assessments
                ):
                    raise PolicyError("immutable consequence assessment identity is malformed")
                assessments[prediction_receipt_id] = event

        rebuilt: dict[tuple[str, str], MatchedPredictionEvidence] = {}
        for transition in self._transitions:
            if len(transition.source_event_ids) != 4:
                raise PolicyError("checkpoint transition source quartet is incomplete")
            selected_id, submitted_id, consequence_id, _ = transition.source_event_ids
            selected = event_by_id.get(selected_id)
            submitted = event_by_id.get(submitted_id)
            consequence = event_by_id.get(consequence_id)
            if selected is None or submitted is None or consequence is None:
                raise PolicyError("checkpoint prediction evidence source is absent")
            prediction_receipt_id = submitted.payload.get("prediction_receipt_id")
            if prediction_receipt_id is None:
                continue
            if not isinstance(prediction_receipt_id, str):
                raise PolicyError("immutable submitted prediction identity is malformed")
            prediction = predictions.get(prediction_receipt_id)
            assessment = assessments.get(prediction_receipt_id)
            if prediction is None or assessment is None:
                raise PolicyError(
                    "checkpoint transition prediction lacks immutable assessment receipts"
                )
            if not (
                event_order[selected_id]
                < event_order[prediction.event_id]
                < event_order[submitted_id]
                < event_order[consequence_id]
                < event_order[assessment.event_id]
            ):
                raise PolicyError("immutable prediction evidence is not source-ordered")
            transition_epoch_id = self._transition_epochs.get(transition.transition_id)
            decision_id = selected.payload.get("decision_id")
            coordinate = transition.action.coordinate
            expected_prediction_action: dict[str, JSONValue] = {
                "name": transition.action.name.value,
                "coordinate": ([coordinate.x, coordinate.y] if coordinate is not None else None),
            }
            if (
                not isinstance(decision_id, str)
                or not isinstance(transition_epoch_id, str)
                or selected.event_type != "action.selected"
                or submitted.event_type != "action.submitted"
                or submitted.payload.get("selected_event_id") != selected_id
                or submitted.payload.get("decision_id") != decision_id
                or prediction.payload.get("action_decision_id") != decision_id
                or prediction.payload.get("action") != expected_prediction_action
                or prediction.payload.get("mechanics_epoch_id") != transition_epoch_id
                or selected.payload.get("mechanics_epoch_id") != transition_epoch_id
                or assessment.payload.get("mechanics_epoch_id") != transition_epoch_id
            ):
                raise PolicyError(
                    "immutable prediction action/decision/epoch disagrees with transition"
                )
            raw_alternatives = prediction.payload.get("alternatives")
            raw_matched_ids = assessment.payload.get("matched_prediction_ids")
            raw_mismatched_ids = assessment.payload.get("mismatched_prediction_ids")
            raw_controlled_ids = assessment.payload.get("controlled_projection_match_model_ids", [])
            assessment_receipt_id = assessment.payload.get("receipt_id")
            if (
                not isinstance(raw_alternatives, list)
                or not all(isinstance(item, Mapping) for item in raw_alternatives)
                or not isinstance(raw_matched_ids, list)
                or not all(isinstance(item, str) for item in raw_matched_ids)
                or not isinstance(raw_mismatched_ids, list)
                or not all(isinstance(item, str) for item in raw_mismatched_ids)
                or not isinstance(raw_controlled_ids, list)
                or not all(isinstance(item, str) for item in raw_controlled_ids)
                or not isinstance(assessment_receipt_id, str)
            ):
                raise PolicyError("immutable prediction assessment payload is malformed")
            matched_ids = set(cast(list[str], raw_matched_ids))
            mismatched_ids = set(cast(list[str], raw_mismatched_ids))
            controlled_ids = set(cast(list[str], raw_controlled_ids))
            predicted_ids: set[str] = set()
            predicted_model_ids: set[str] = set()
            exact_model_ids: set[str] = set()
            alternatives = cast(list[Mapping[str, object]], raw_alternatives)
            for alternative in alternatives:
                raw_supporting = alternative.get("supporting_model_ids")
                raw_prediction_ids = alternative.get("prediction_ids")
                if (
                    not isinstance(raw_supporting, list)
                    or not raw_supporting
                    or not all(isinstance(item, str) for item in raw_supporting)
                    or not isinstance(raw_prediction_ids, list)
                    or not raw_prediction_ids
                    or not all(isinstance(item, str) for item in raw_prediction_ids)
                ):
                    raise PolicyError("immutable prediction alternative is malformed")
                supporting = set(cast(list[str], raw_supporting))
                alternative_prediction_ids = set(cast(list[str], raw_prediction_ids))
                if (
                    len(supporting) != len(raw_supporting)
                    or len(alternative_prediction_ids) != len(raw_prediction_ids)
                    or predicted_model_ids & supporting
                    or predicted_ids & alternative_prediction_ids
                    or len(supporting) != len(alternative_prediction_ids)
                ):
                    raise PolicyError("immutable prediction alternative identity is ambiguous")
                predicted_model_ids.update(supporting)
                predicted_ids.update(alternative_prediction_ids)
                alternative_matches = alternative_prediction_ids & matched_ids
                if alternative_matches:
                    if alternative_prediction_ids != alternative_matches:
                        raise PolicyError("immutable whole-state match splits one alternative")
                    exact_model_ids.update(supporting)
            if (
                matched_ids & mismatched_ids
                or matched_ids | mismatched_ids != predicted_ids
                or not controlled_ids.issubset(predicted_model_ids)
                or prediction.payload.get("before_state_id") != transition.before.state_id
                or assessment.payload.get("observed_state_id") != transition.after.state_id
                or consequence.event_type != "consequence.received"
            ):
                raise PolicyError("immutable prediction assessment disagrees with transition")
            expected_scope = (
                "whole-symbolic-state"
                if matched_ids
                else "controlled-entity-projection"
                if controlled_ids
                else "none"
            )
            expected_event_type = (
                "consequence.matched_prediction"
                if exact_model_ids or controlled_ids
                else "consequence.mismatched_prediction"
            )
            if (
                assessment.event_type != expected_event_type
                or assessment.payload.get("exact_state_match") is not bool(matched_ids)
                or assessment.payload.get("match_scope") != expected_scope
            ):
                raise PolicyError("immutable prediction assessment classification is malformed")
            for model_id in sorted(predicted_model_ids):
                exact_match = model_id in exact_model_ids
                controlled_match = model_id in controlled_ids
                evidence = MatchedPredictionEvidence(
                    transition_id=transition.transition_id,
                    model_id=model_id,
                    prediction_event_id=prediction.event_id,
                    prediction_receipt_id=prediction_receipt_id,
                    consequence_event_id=consequence_id,
                    assessment_receipt_id=assessment_receipt_id,
                    matched=exact_match or controlled_match,
                    match_scope=(
                        "whole-symbolic-state"
                        if exact_match
                        else "controlled-entity-projection"
                        if controlled_match
                        else "none"
                    ),
                )
                rebuilt[(transition.transition_id, model_id)] = evidence
        self._matched_prediction_evidence = rebuilt

    def _legal_actions(
        self, observation: Observation, view: _PerceptionView
    ) -> tuple[ActionRequest, ...]:
        if observation.state in {GameStateName.GAME_OVER, GameStateName.NOT_PLAYED}:
            return (ActionRequest(ActionName.RESET),)
        actions: list[ActionRequest] = []
        names: tuple[ActionName, ...]
        if self._calibration_cursor < len(self._calibration_handles):
            advertised = set(observation.available_actions)
            names = tuple(
                item for item in ActionName if item is not ActionName.RESET and item in advertised
            )
        else:
            names = self._action_effects.canonical_order(
                observation.available_actions,
                condition_signature=action_condition_signature(observation),
            )
        calibration = self._next_calibration_action(observation)
        for name in names:
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
                if calibration is not None and calibration.name is ActionName.ACTION6:
                    calibration_coordinate = Coordinate(3, 3)
                    coordinates = (
                        calibration_coordinate,
                        *(item for item in coordinates if item != calibration_coordinate),
                    )[:limit]
                actions.extend(ActionRequest(name, coordinate) for coordinate in coordinates)
            else:
                actions.append(ActionRequest(name))
        return tuple(actions)

    def _maybe_automatic_checkpoint(self, *, boundary: str, force: bool = False) -> None:
        """Apply the execution-mode persistence schedule without disabling memory."""

        if not self.features.use_memory:
            return
        policy = self.context.config.runtime_policy
        sparse_due = (
            boundary == "evidence-fold"
            and self._step_index > 0
            and self._step_index % policy.sparse_checkpoint_interval_actions == 0
        )
        level_due = boundary == "evidence-fold" and (
            self._level_index != self._last_sparse_checkpoint_level
        )
        if not (policy.automatic_per_action_checkpoints or force or sparse_due or level_due):
            return
        self._last_checkpoint = self.checkpoint()
        self._last_sparse_checkpoint_level = self._level_index

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
        if self._cadence_state.deliberation_in_progress:
            latest = self._latest_observation
            if latest is None:
                raise PolicyError("budget exhaustion lacks its observation boundary")
            self._reasoning_terminal_status = DeliberationStatus.BUDGET_EXHAUSTED
            self._reasoning_budget_exhaustions.append(budget)
            self._complete_reasoning_cycle(latest, advance_cadence=False)
        if self._transient_fold_boundary == "action-construction":
            # No action crossed the adapter boundary.  Clear only the
            # action-construction scratch fields after the immutable fault and
            # terminal cadence receipts exist, then commit the faulted state.
            self._pending_plan_emission = False
            self._calibration_pending_handle = None
            self._pending_canonical_effect = None
            self._pending_resolution_kind = None
            self._pending_change_candidate_id = None
            self._pending_reexploration_candidate_id = None
            self._transient_fold_boundary = None
        self._maybe_automatic_checkpoint(boundary="failure", force=True)
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
        self,
        action: ActionRequest,
        state: SymbolicState,
        *,
        allow_model_simulation: bool,
    ) -> tuple[str | None, float, int]:
        goal_id = self._active_goal_id
        if (
            not self.features.use_world_model_simulation
            or not allow_model_simulation
            or goal_id is None
            or self._ensemble is None
            or goal_id not in self._goal_targets
        ):
            return None, 0.0, 0
        mover_id, target_id = self._goal_targets[goal_id]
        before_distance = _entity_distance(state, mover_id, target_id)
        if self._cadence_state.deliberation_in_progress:
            self._reasoning_work_counts["prediction_invocations"] += 1
            self._reasoning_work_counts["simulation_invocations"] += 1
        prediction = self._ensemble.candidates[0].predict(state, action)
        after_distance = _entity_distance(prediction.after_state, mover_id, target_id)
        if before_distance is None or after_distance is None:
            return goal_id, 0.0, 0
        advance = max(0, before_distance - after_distance)
        return goal_id, min(1.0, float(advance)), advance

    def _candidate_actions(
        self,
        observation: Observation,
        view: _PerceptionView,
        *,
        allow_model_simulation: bool,
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
            _goal_id, progress, _advance = self._goal_option(
                action,
                view.symbolic_state,
                allow_model_simulation=allow_model_simulation,
            )
            estimate = self._exploration.statistics.estimate(context.state, action)
            failure = 0.25 if estimate.kind is EffectKind.NO_OP and not estimate.prior_only else 0.0
            novelty = 1.0 / (1.0 + self._action_counts[action])
            information = 0.0
            if (
                allow_model_simulation
                and self.features.use_information_gain
                and self._ensemble is not None
            ):
                if self._cadence_state.deliberation_in_progress:
                    self._reasoning_work_counts["prediction_invocations"] += 1
                    self._reasoning_work_counts["simulation_invocations"] += 1
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
            if self._cadence_state.deliberation_in_progress:
                self._reasoning_work_counts["prediction_invocations"] += len(actions)
                self._reasoning_work_counts["simulation_invocations"] += len(actions)
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

    @_profiled("planning")
    def _plan_action(
        self,
        observation: Observation,
        view: _PerceptionView,
        *,
        stage_only: bool = False,
        allow_new_search: bool = True,
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
        condition = action_condition_signature(observation)
        actions = tuple(
            action
            for action in self._legal_actions(observation, view)
            if not action.name.requires_coordinates
            and (
                self._action_effects.accepted_translation(
                    action.name,
                    condition_signature=condition,
                )
                is not None
                or self._active_action_translation(action.name) is not None
            )
        )
        if not actions:
            return None
        goal_record = self._goals.get(goal_id)
        goal_revision = f"{goal_record.status.value}:{goal_record.rank}:{goal_record.reopen_count}"
        model = self._ensemble.candidates[0]
        existing_plan = self._plan_executor.plan
        existing_cursor = self._plan_executor.cursor
        if (
            existing_plan is not None
            and existing_plan.plan_id not in self._invalidated_plan_ids
            and existing_plan.is_current(
                model_id=model.model_id,
                goal_id=goal_id,
                goal_revision=goal_revision,
            )
            and existing_cursor < len(existing_plan.steps)
            and existing_plan.steps[existing_cursor].before_state_id == view.symbolic_state.state_id
        ):
            if stage_only:
                return (
                    existing_plan.steps[existing_cursor].action,
                    existing_plan.plan_id,
                    "current staged bounded A* plan under retrodicted model",
                )
            emission = self._plan_executor.next_action(
                view.symbolic_state,
                model_id=model.model_id,
                goal_id=goal_id,
                goal_revision=goal_revision,
                game_state=observation.state,
            )
            if isinstance(emission, ActionEmission):
                return (
                    emission.action,
                    emission.plan_id,
                    "bounded A* plan under retrodicted model",
                )
        elif existing_plan is not None:
            # A prepared plan is revisable derived state.  If its source model,
            # goal revision, or current symbolic state changed before action
            # selection, discard it and search again without treating that as
            # an environment consequence.
            self._plan_executor = PlanExecutor()

        if not allow_new_search:
            return None

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
                # Research mode preserves its deterministic node/depth boundary.
                # Competition mode additionally enforces the elapsed boundary.
                max_time_ms=max(
                    1,
                    math.ceil(self.context.config.budgets.decision_seconds * 1_000),
                ),
            ),
            enforce_time_budget=self.search_time_budget_enforced,
        )
        payload = result.to_trace_payload()
        payload.update(
            {
                "model_id": model.model_id,
                "goal_id": goal_id,
                "mechanics_epoch_id": self._mechanics.active_epoch(self._level_index).epoch_id,
                "plan_payload_hash": (
                    sha256_json(self._serialize_plan(result.plan))
                    if result.status is SearchStatus.FOUND and result.plan is not None
                    else None
                ),
                "dependent_hypothesis_ids": (
                    list(model.hypothesis_ids)
                    if result.status is SearchStatus.FOUND
                    and result.plan is not None
                    and result.plan.steps
                    else []
                ),
            }
        )
        self._append(str(observation.game_id), "simulation.plan_evaluated", payload)
        if result.status is not SearchStatus.FOUND or result.plan is None or not result.plan.steps:
            return None
        if result.plan.plan_id in self._invalidated_plan_ids:
            return None
        self._plan_executor = PlanExecutor()
        self._plan_executor.load(result.plan)
        for hypothesis_id in model.hypothesis_ids:
            self._hypotheses.register_dependent_plan(result.plan.plan_id, (hypothesis_id,))
        self._goals.selected(goal_id)
        self._flush_goal_events(observation)
        if stage_only:
            return (
                result.plan.steps[0].action,
                result.plan.plan_id,
                "staged bounded A* plan under retrodicted model",
            )
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

    def _stage_plan_for_next_choice(
        self,
        observation: Observation,
        view: _PerceptionView,
        *,
        propagate_failure: bool = False,
    ) -> None:
        """Load a checkpointable plan without selecting or predicting an action.

        Planning is internal computation.  The next explicit
        :meth:`choose_action` call releases one plan step and emits the ordinary
        action-bound prediction; this staging method creates neither.
        """

        if (
            self._phase is not ControllerPhase.OBSERVED
            or self._pending_action is not None
            or self._calibration_cursor != len(self._calibration_handles)
            or self._provisional_probe_handle is not None
            or self._reexploration_handle is not None
        ):
            return
        try:
            self._plan_action(observation, view, stage_only=True)
        except Exception as error:
            # Plan staging is optional derived computation. Preserve the
            # observation boundary and let the ordinary next-choice fault
            # fallback select a legal action rather than rejecting a valid
            # returned consequence.
            self._plan_executor = PlanExecutor()
            self._pending_plan_emission = False
            self._fault_count += 1
            self._append(
                str(observation.game_id),
                "run.environment_fault",
                {
                    "fault_type": type(error).__name__,
                    "boundary": "consequence-tail-plan-staging",
                    "recovery": "retain observation and defer to next-choice fallback",
                },
                scope="run",
            )
            if propagate_failure:
                raise

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
        action_name = self._action_effects.resolve_translation(
            (dx, dy),
            condition_signature=action_condition_signature(observation),
            available_actions=observation.available_actions,
        )
        if action_name is None:
            action_name = self._resolve_active_translation(
                (dx, dy), available_actions=observation.available_actions
            )
        if action_name is None or action_name.requires_coordinates:
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
        *,
        allow_model_simulation: bool,
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
                reversibility=(
                    1.0
                    if candidate.action.name is ActionName.RESET
                    or (
                        self._interface_semantics is not None
                        and candidate.action.name is self._interface_semantics.undo_action
                    )
                    else 0.0
                ),
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
                        reversibility=(
                            1.0
                            if candidate.action.name is ActionName.RESET
                            or (
                                self._interface_semantics is not None
                                and candidate.action.name is self._interface_semantics.undo_action
                            )
                            else 0.0
                        ),
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
            alternatives=(
                self._exploration_alternatives(
                    view.symbolic_state, tuple(item.action for item in candidates)
                )
                if allow_model_simulation
                else ()
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

    def _change_probe_action(
        self, observation: Observation, view: _PerceptionView
    ) -> tuple[ActionRequest, str, bool] | None:
        """Return one generic affected-domain probe while authority is withheld."""

        handle = self._reexploration_handle or self._provisional_probe_handle
        if handle is None or handle not in observation.available_actions:
            return None
        reexploration = self._reexploration_handle is not None
        if reexploration:
            candidate_id = self._reexploration_candidate_id
            candidate = (
                self._mechanics.candidate(candidate_id) if candidate_id is not None else None
            )
        else:
            candidate = self._mechanics.live_candidate(
                level_index=self._level_index,
                opaque_handle=handle.value,
            )
            candidate_id = candidate.candidate_id if candidate is not None else None
        if candidate_id is None:
            raise PolicyError("mechanics probe has no source change candidate")
        legal_actions = self._legal_actions(observation, view)
        if (
            not reexploration
            and candidate is not None
            and candidate.change_domain is MechanicsChangeDomain.ACTION_MAPPING
        ):
            tested_handles = {
                context.removeprefix("opaque-handle:")
                for context in candidate.supporting_discrimination_context_ids
                if context.startswith("opaque-handle:")
            }
            unseen_mapping_actions = tuple(
                action
                for action in legal_actions
                if action.name.value not in tested_handles
                and self._active_action_translation(
                    action.name,
                    epoch_id=candidate.predecessor_epoch_id,
                    include_provisionally_suspended=True,
                )
                is not None
            )
            if unseen_mapping_actions:
                return (
                    min(
                        unseen_mapping_actions,
                        key=lambda action: (self._action_counts[action], action.name.value),
                    ),
                    candidate_id,
                    False,
                )
        if (
            not reexploration
            and candidate is not None
            and candidate.change_domain is MechanicsChangeDomain.DESTINATION_ROLE
        ):
            affected_roles = {
                (
                    statement.moving_kind,
                    statement.obstacle_kind,
                )
                for hypothesis_id in candidate.affected_hypothesis_ids
                if (record := self._hypotheses.find(hypothesis_id)) is not None
                if isinstance((statement := record.statement), CollisionTraversabilityStatement)
            }
            unseen: list[tuple[int, int, ActionRequest]] = []
            for order, action in enumerate(legal_actions):
                translation = self._active_action_translation(
                    action.name,
                    epoch_id=candidate.predecessor_epoch_id,
                    include_provisionally_suspended=True,
                )
                if translation is None:
                    continue
                context = self._destination_role_context(view.symbolic_state, translation)
                if (
                    context is None
                    or (context[0], context[1]) not in affected_roles
                    or context[3] in candidate.supporting_discrimination_context_ids
                ):
                    continue
                unseen.append((self._action_counts[action], order, action))
            if unseen:
                return min(unseen, key=lambda item: (item[0], item[1]))[2], candidate_id, False
        actions = tuple(item for item in legal_actions if item.name is handle)
        if not actions:
            return None
        return actions[0], candidate_id, reexploration

    def _successor_rule_revalidation_action(
        self,
        observation: Observation,
        view: _PerceptionView,
    ) -> tuple[ActionRequest, str] | None:
        """Probe one missing successor-epoch handle after ordinary calibration.

        A mechanics change can strand initial successor calibration on a newly
        blocked surface.  The predecessor displacement is used only to choose
        an information-bearing probe; it is not copied into successor
        authority.  An executable rule is created only from the returned
        successor receipt.  Observation-derived destination-role hypotheses
        prefer a currently supported traversable context.
        """

        if self._calibration_cursor < len(self._calibration_handles):
            return None
        epoch = self._mechanics.active_epoch(self._level_index)
        if epoch.parent_epoch_id is None or epoch.caused_by_change_candidate_id is None:
            return None
        bound_handles = {
            statement.action
            for record in self._hypotheses.all()
            if record.status is HypothesisStatus.ACTIVE
            and self._mechanics.hypothesis_epoch(record.hypothesis_id) == epoch.epoch_id
            and isinstance((statement := record.statement), ActionSemanticsStatement)
        }
        role_claims = tuple(
            statement
            for record in self._hypotheses.all()
            if record.status is HypothesisStatus.ACTIVE
            and self._mechanics.hypothesis_epoch(record.hypothesis_id) == epoch.epoch_id
            and isinstance((statement := record.statement), CollisionTraversabilityStatement)
        )
        role_probes: list[tuple[int, str, ActionRequest]] = []
        for action in self._legal_actions(observation, view):
            if action.name.requires_coordinates:
                continue
            translation = self._active_action_translation(action.name)
            if translation is None:
                continue
            context = self._destination_role_context(view.symbolic_state, translation)
            if context is None or any(
                claim.moving_kind == context[0] and claim.obstacle_kind == context[1]
                for claim in role_claims
            ):
                continue
            role_probes.append(
                (
                    self._action_effects.observation_count(action.name),
                    action.name.value,
                    action,
                )
            )
        if role_probes:
            return (
                min(role_probes, key=lambda item: item[:2])[2],
                epoch.caused_by_change_candidate_id,
            )

        probes: list[tuple[int, int, str, ActionRequest]] = []
        for action in self._legal_actions(observation, view):
            if action.name.value in bound_handles or action.name.requires_coordinates:
                continue
            translation = self._active_action_translation(
                action.name,
                epoch_id=epoch.parent_epoch_id,
            )
            if translation is None:
                continue
            context = self._destination_role_context(view.symbolic_state, translation)
            role_rank = 1
            if context is not None:
                matching = tuple(
                    claim
                    for claim in role_claims
                    if claim.moving_kind == context[0] and claim.obstacle_kind == context[1]
                )
                if len(matching) == 1:
                    role_rank = 0 if matching[0].traversable else 2
            probes.append(
                (
                    role_rank,
                    self._action_effects.observation_count(action.name),
                    action.name.value,
                    action,
                )
            )
        if not probes:
            return None
        return min(probes, key=lambda item: item[:3])[3], epoch.caused_by_change_candidate_id

    def _prediction_for_action(
        self,
        state: SymbolicState,
        action: ActionRequest,
    ) -> tuple[EnsemblePrediction, bool | None, CanonicalCacheKey | None]:
        """Return pure prediction computation; receipt authority is minted later."""

        ensemble = self._ensemble
        if ensemble is None:
            raise PolicyError("prediction requested without an active ensemble")
        if not self._cadence_config.prediction_cache_enabled:
            self._reasoning_work_counts["prediction_invocations"] += 1
            self._reasoning_work_counts["simulation_invocations"] += 1
            return ensemble.predict(state, action), None, None
        key = CanonicalCacheKey(
            source_identity=self._cache_source_identity(),
            configuration_identity=self._cache_configuration_identity(),
            symbolic_state_id=state.state_id,
            action=action,
            ordered_models=tuple(
                ModelCacheIdentity(
                    semantic_identity=model_semantic_fingerprint(candidate),
                    rank_weight=candidate.rank_weight,
                )
                for candidate in ensemble.candidates
            ),
            mechanics_epoch_id=self._mechanics.active_epoch(self._level_index).epoch_id,
            action_registry_identity=self._action_registry_identity(),
            value_kind=CacheValueKind.PREDICTION,
        )
        cached = self._prediction_cache.get(key)
        if cached is not None:
            return cached.prediction, True, key
        self._reasoning_work_counts["prediction_invocations"] += 1
        self._reasoning_work_counts["simulation_invocations"] += 1
        prediction = ensemble.predict(state, action)
        self._prediction_cache.put(key, DerivedCacheValue(prediction=prediction))
        return prediction, False, key

    @_profiled("action_selection", "choose_action")
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
        if self._transient_fold_boundary is not None:
            raise PolicyError("interrupted action construction requires checkpoint recovery")
        self._transient_fold_boundary = "action-construction"
        if self._reasoning_selection is None or not self._cadence_state.deliberation_in_progress:
            # Historical checkpoints predate cadence state.  Reconstruct one
            # current-observation reasoning boundary before permitting action.
            self._run_reasoning_cycle(
                observation,
                receipt,
                view,
                initial=self._step_index == 0,
                progress_made=True,
                evidence_already_folded=(
                    self._cadence_folded_observation_event_id == receipt.observation_event_id
                ),
            )
        if self._reasoning_selection is None or not self._cadence_state.deliberation_in_progress:
            raise PolicyError("action selection lacks an in-progress reasoning boundary")
        allow_deep_work = self._reasoning_selection.path is ReasoningPath.DEEP

        candidates = self._candidate_actions(
            observation,
            view,
            allow_model_simulation=allow_deep_work,
        )
        candidate_event = self._append(
            str(observation.game_id),
            "action.candidates_generated",
            {
                "source_observation_event_id": receipt.observation_event_id,
                "candidates": [item.to_trace_payload() for item in candidates],
                "candidate_bindings": {
                    name.value: [
                        candidate.projection()
                        for candidate in self._action_effects.candidates_for(
                            name,
                            condition_signature=action_condition_signature(observation),
                        )
                    ]
                    for name in self._action_effects.canonical_order(
                        observation.available_actions,
                        condition_signature=action_condition_signature(observation),
                    )
                },
                "alternatives_summary": "legal actions ranked by declared generic terms",
            },
        )
        candidate_event_id = candidate_event.event_id

        plan_or_probe_id: str | None = None
        self._pending_plan_emission = False
        rationale = "deterministic action cycle preset"
        rationale_category = RationaleCategory.BASELINE
        self._calibration_pending_handle = None
        self._pending_canonical_effect = None
        self._pending_resolution_kind = None
        self._pending_change_candidate_id = None
        self._pending_reexploration_candidate_id = None
        try:
            if self._reasoning_force_fallback:
                raise PolicyError("reasoning deliberation selected deterministic fallback")
            if self.preset in {ControllerPreset.BASELINE, ControllerPreset.TRACE}:
                action = self._baseline_action(observation)
            elif self._phase is ControllerPhase.GAME_OVER:
                action = ActionRequest(ActionName.RESET)
                rationale = "game over permits only reset"
                rationale_category = RationaleCategory.MANDATORY_RESET
            else:
                change_probe = self._change_probe_action(observation, view)
                calibration = (
                    None if change_probe is not None else self._next_calibration_action(observation)
                )
                contact_probe = (
                    None
                    if change_probe is not None or calibration is not None
                    else self._contact_probe_action(observation, view)
                )
                planned = (
                    None
                    if change_probe is not None
                    or calibration is not None
                    or contact_probe is not None
                    else self._plan_action(
                        observation,
                        view,
                        allow_new_search=allow_deep_work,
                    )
                )
                successor_revalidation = (
                    None
                    if change_probe is not None
                    or calibration is not None
                    or contact_probe is not None
                    or planned is not None
                    else self._successor_rule_revalidation_action(observation, view)
                )
                if change_probe is not None:
                    action, candidate_id, reexploration = change_probe
                    plan_or_probe_id = candidate_id
                    if reexploration:
                        self._pending_reexploration_candidate_id = candidate_id
                        self._reexploration_handle = None
                        self._reexploration_candidate_id = None
                        rationale = "fresh successor-epoch mechanics re-exploration"
                        rationale_category = RationaleCategory.REEXPLORATION
                    else:
                        self._pending_change_candidate_id = candidate_id
                        rationale = "provisional mechanics-change discrimination probe"
                        rationale_category = RationaleCategory.DISCRIMINATE_MODELS
                    self._pending_resolution_kind = "mechanics-change-probe"
                elif calibration is not None:
                    action = calibration
                    self._calibration_pending_handle = action.name
                    self._pending_resolution_kind = "calibration-prefix"
                    plan_or_probe_id = candidate_event_id
                    rationale = "frozen one-receipt opaque-handle calibration"
                    rationale_category = RationaleCategory.DISCRIMINATE_MODELS
                elif contact_probe is not None:
                    action, plan_or_probe_id, rationale = contact_probe
                    rationale_category = RationaleCategory.DISCRIMINATE_MODELS
                elif planned is not None:
                    action, plan_or_probe_id, rationale = planned
                    self._pending_plan_emission = True
                    rationale_category = RationaleCategory.FOLLOW_PLAN
                elif successor_revalidation is not None:
                    action, plan_or_probe_id = successor_revalidation
                    self._pending_reexploration_candidate_id = plan_or_probe_id
                    self._pending_resolution_kind = "successor-rule-revalidation"
                    rationale = "successor-epoch rule revalidation in an observed context"
                    rationale_category = RationaleCategory.REEXPLORATION
                else:
                    action, plan_or_probe_id, rationale = self._probe_action(
                        observation,
                        view,
                        candidates,
                        allow_model_simulation=allow_deep_work,
                    )
                    rationale_category = RationaleCategory.DISCRIMINATE_MODELS
        except Exception as error:
            self._fault_count += 1
            self._reasoning_terminal_status = DeliberationStatus.FALLBACK_USED
            if self._reasoning_fault_type is None:
                self._reasoning_fault_type = type(error).__name__
            _, fallback = min(
                enumerate(candidates),
                key=lambda item: (self._action_counts[item[1].action], item[0]),
            )
            action = fallback.action
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

        if self._pending_resolution_kind is None:
            resolved_effect, resolved_kind = self._resolved_effect_for(observation, action)
            self._pending_canonical_effect = resolved_effect
            self._pending_resolution_kind = (
                "lifecycle-interface"
                if action.name is ActionName.RESET
                else resolved_kind
                if resolved_kind is not None
                else "unresolved-information-probe"
            )

        self._ensure_budget_available(action)
        validate_action_request(observation, action)
        current_epoch_id = self._mechanics.active_epoch(self._level_index).epoch_id
        active_hypothesis_ids = tuple(
            record.hypothesis_id
            for record in self._hypotheses.ranked(include_rejected=False)
            if record.status is HypothesisStatus.ACTIVE
            and self._mechanics.hypothesis_epoch(record.hypothesis_id) == current_epoch_id
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
        prediction_receipt_id: str | None = None
        prediction_event_payload: dict[str, JSONValue] | None = None
        self._pending_prediction = None
        self._pending_prediction_event_id = None
        self._restored_prediction_state_ids = ()
        self._restored_prediction_plan_ids = ()
        if (
            self.features.use_world_model_simulation
            and self._ensemble is not None
            and action.name is not ActionName.RESET
        ):
            prediction_value, prediction_cache_hit, prediction_cache_key = (
                self._prediction_for_action(view.symbolic_state, action)
            )
            prediction = self._prediction_book.emit_prediction(
                action_decision_id=decision_id,
                prediction=prediction_value,
                dependent_plan_ids=(
                    (plan_or_probe_id,)
                    if plan_or_probe_id is not None and plan_or_probe_id.startswith("plan:")
                    else ()
                ),
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
            prediction_event_payload = {
                **prediction.to_dict(),
                "mechanics_epoch_id": self._mechanics.active_epoch(self._level_index).epoch_id,
                "cache_hit": prediction_cache_hit,
                "cache_key_hash": (
                    prediction_cache_key.key_hash if prediction_cache_key is not None else None
                ),
                "cache_projection_hash": self._prediction_cache.projection_hash,
            }
        self._complete_reasoning_cycle(observation)
        if self._reasoning_completed_event_id is None:
            raise PolicyError("current action lacks a completed reasoning receipt")
        selected = self._append(
            str(observation.game_id),
            "action.selected",
            {
                "decision_id": decision_id,
                "source_observation_event_id": receipt.observation_event_id,
                "selected_action": _action_payload(action),
                "selected_canonical_effect": (
                    self._pending_canonical_effect.projection()
                    if self._pending_canonical_effect is not None
                    else None
                ),
                "raw_resolution_kind": self._pending_resolution_kind,
                "candidate_utilities": [item.to_trace_payload() for item in candidates],
                "selected_probe_or_plan_id": plan_or_probe_id,
                "active_hypothesis_ids": list(active_hypothesis_ids),
                "predicted_outcome_ids": list(predicted_ids),
                "active_goal_ids": list(active_goal_ids),
                "active_world_model_ids": list(active_model_ids),
                "mechanics_epoch_id": self._mechanics.active_epoch(self._level_index).epoch_id,
                "reexploration": (rationale_category is RationaleCategory.REEXPLORATION),
                "rationale_category": rationale_category.value,
                "rationale_summary": rationale,
                "alternatives_summary": f"{len(candidates)} legal candidate(s) retained",
                "reasoning_completed_event_id": self._reasoning_completed_event_id,
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
        if prediction_event_payload is not None:
            prediction_event = self._append(
                str(observation.game_id),
                "simulation.prediction_emitted",
                prediction_event_payload,
            )
            self._pending_prediction_event_id = prediction_event.event_id
        submitted = self._append(
            str(observation.game_id),
            "action.submitted",
            {
                "decision_id": decision_id,
                "selected_event_id": selected_id,
                "validated_event_id": validated_id,
                "action": _action_payload(action),
                "selected_canonical_effect": (
                    self._pending_canonical_effect.projection()
                    if self._pending_canonical_effect is not None
                    else None
                ),
                "raw_resolution_kind": self._pending_resolution_kind,
                "adapter_boundary": "delivered-to-runtime-adapter",
                "prediction_receipt_id": prediction_receipt_id,
            },
        )
        # The action receipt must be durable before the adapter is allowed to
        # execute it.  This also flushes the derived selection receipts that
        # explain the action without fsyncing each one independently.
        self._flush_trace()
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
        # All state needed to represent the submitted action is now present.
        # Clearing this before the pending-action checkpoint lets a checkpoint
        # write failure be retried without treating a complete decision as an
        # abandonable derived-only suffix.
        self._transient_fold_boundary = None
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
        self._maybe_automatic_checkpoint(boundary="action-submitted")
        return decision

    @_profiled("controller_orchestration", "apply_consequence")
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
        if self._transient_fold_boundary is not None:
            raise PolicyError("interrupted controller fold requires checkpoint recovery")
        self._transient_fold_boundary = "consequence-application"
        after = self._require_observation(frames)
        returned_action_mismatch = (
            after.returned_action is not None and after.returned_action != pending.action
        )
        previous_level = self._level_index
        self._collect_cadence_trigger_events = True
        self._cadence_reopening_event_ids.clear()
        self._cadence_contradiction_event_ids.clear()

        returned_frames = self._store_frames(after.frames)
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
        self._flush_trace()
        # The consequence closes the submitted step; its returned observation is
        # the evidence boundary for the next decision step.
        self._step_index += 1
        self._level_index = after.levels_completed
        observation_receipt, view = self._record_observation(after, previous=before)
        entity_binding_authoritative = True
        if (
            self.features.use_hypotheses
            and not returned_action_mismatch
            and after.levels_completed == previous_level
        ):
            entity_binding_authoritative = self._adopt_observed_mover(
                after,
                observation_receipt,
                view,
                before_state,
                self._latest_view.components if self._latest_view is not None else (),
                pending.action,
                consequence_event_id=consequence_id,
            )
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
            self._pending_prediction_event_id = None
            self._restored_prediction_state_ids = ()
            self._restored_prediction_plan_ids = ()
            self._before_action_observation = None
            self._before_action_state = None
            self._before_action_features = None
            self._pending_plan_emission = False
            self._calibration_pending_handle = None
            self._pending_canonical_effect = None
            self._pending_resolution_kind = None
            self._plan_executor = PlanExecutor()
            self._phase = ControllerPhase.FAULTED
            self._collect_cadence_trigger_events = False
            self._prediction_cache.invalidate(
                CacheInvalidationReason.ACTION_SPACE_OR_CALIBRATION_CHANGE
            )
            self._transient_fold_boundary = None
            self._maybe_automatic_checkpoint(boundary="failure", force=True)
            raise PolicyError(
                "returned consequence does not match the pending action; "
                f"raw receipt preserved as {rejected.event_id}"
            )

        action_effect_observation: ActionEffectObservation | None = None
        prior_accepted_translation: tuple[int, int] | None = None
        prior_models = self._ensemble.candidates if self._ensemble is not None else ()
        prior_action_registry_identity = self._action_registry_identity()
        if pending.action.name is not ActionName.RESET:
            before_condition = action_condition_signature(before)
            prior_accepted_translation = self._action_effects.accepted_translation(
                pending.action.name,
                condition_signature=before_condition,
            )
            if prior_accepted_translation is None:
                prior_accepted_translation = self._active_action_translation(
                    pending.action.name,
                    epoch_id=self._mechanics.active_epoch(previous_level).epoch_id,
                    include_provisionally_suspended=True,
                )
            action_effect_observation = self._action_effects.observe_transition(
                before,
                pending.action,
                after,
                source_event_id=consequence_id,
                prior_frame_hashes=tuple(self._recent_frame_hashes),
            )
            if self._calibration_pending_handle is pending.action.name:
                self._calibrated_handles.add(pending.action.name)
            self._append(
                str(after.game_id),
                "action.effect_observed",
                {
                    "source_consequence_event_id": consequence_id,
                    "raw_handle": pending.action.name.value,
                    "canonical_effects": [
                        item.projection() for item in action_effect_observation.canonical_effects
                    ],
                    "ambiguous": action_effect_observation.ambiguous,
                    "before_digest": str(action_effect_observation.before_digest),
                    "after_digest": str(action_effect_observation.after_digest),
                    "candidates": [
                        item.projection()
                        for item in self._action_effects.candidates_for(pending.action.name)
                    ],
                    "candidate_count": self._action_effects.candidate_count,
                    "calibration_cursor": self._calibration_cursor,
                    "registry_level_index": self._action_effects.level_index,
                },
            )
            if self._action_registry_identity() != prior_action_registry_identity:
                self._prediction_cache.invalidate(
                    CacheInvalidationReason.ACTION_SPACE_OR_CALIBRATION_CHANGE
                )

        effect = classify_effect(
            before,
            after,
            pending.action,
            prior_frame_hashes=tuple(self._recent_frame_hashes),
        )
        self._exploration.record_outcome(before_context, pending.action, effect)

        matched_prediction: bool | None = None
        reopened_models: tuple[str, ...] = ()
        invalidated_plans: set[str] = set()
        if self._pending_prediction is not None:
            assessment = self._prediction_book.match(
                self._pending_prediction.receipt_id, observed_state
            )
            controlled_match_model_ids = self._controlled_prediction_match_model_ids(
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
            matched_prediction = assessment.matched_any or bool(controlled_match_model_ids)
            if not matched_prediction:
                self._prediction_cache.invalidate(CacheInvalidationReason.PREDICTION_MISMATCH)
                invalidated_plans.update(
                    plan_id
                    for item in assessment.reopenings
                    for plan_id in item.invalidated_plan_ids
                )
            event_type = (
                "consequence.matched_prediction"
                if matched_prediction
                else "consequence.mismatched_prediction"
            )
            assessment_payload = assessment.to_dict()
            exact_state_reopenings = assessment_payload.pop("reopenings", [])
            assessment_payload.update(
                {
                    # The exact whole-state comparison remains visible even when
                    # a model's explicitly controlled projection matches.  Only
                    # an unscoped mismatch reopens models or invalidates plans.
                    "exact_state_match": assessment.matched_any,
                    "exact_state_reopenings": exact_state_reopenings,
                    "controlled_projection_match_model_ids": list(controlled_match_model_ids),
                    "match_scope": (
                        "whole-symbolic-state"
                        if assessment.matched_any
                        else (
                            "controlled-entity-projection" if controlled_match_model_ids else "none"
                        )
                    ),
                    "reopenings": ([] if controlled_match_model_ids else exact_state_reopenings),
                    "provisional_only": not matched_prediction,
                    "mechanics_epoch_id": self._mechanics.active_epoch(previous_level).epoch_id,
                }
            )
            assessment_event = self._append(
                str(after.game_id),
                event_type,
                assessment_payload,
            )
            self._record_prediction_match_evidence(
                transition_id=f"transition:{pending.submitted_event_id}",
                prediction=self._pending_prediction,
                prediction_event_id=self._pending_prediction_event_id,
                consequence_event_id=consequence_id,
                assessment_receipt_id=assessment.receipt_id,
                assessment_event=assessment_event,
                observed_state_id=observed_state.state_id,
                controlled_match_model_ids=controlled_match_model_ids,
            )
        elif self._restored_prediction_state_ids:
            matched_prediction = observed_state.state_id in self._restored_prediction_state_ids
            if not matched_prediction:
                self._prediction_cache.invalidate(CacheInvalidationReason.PREDICTION_MISMATCH)
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
                restore_action=self._learned_restore_action(after),
                same_model_viable=matched_prediction is not False,
            )
            if planning_consequence.recovery is not None:
                invalidated_plans.add(planning_consequence.plan_id)
            if not self.features.use_planner_recovery and not planning_consequence.matched:
                self._planning_disabled_after_mismatch = True
            self._pending_plan_emission = False

        preserved_transition: PreservedTransition | None = None
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
            preserved_transition = transition
            transition_epoch_id = self._mechanics.active_epoch(previous_level).epoch_id
            self._mechanics.register_transition(
                transition.transition_id, epoch_id=transition_epoch_id
            )
            self._transitions.append(transition)
            self._transition_levels[transition.transition_id] = previous_level
            self._transition_epochs[transition.transition_id] = transition_epoch_id
            self._transition_summaries.setdefault(previous_level, []).append(transition)
            if self.features.use_hypotheses:
                interpreted_action_effect = (
                    self._controlled_action_effect_observation(
                        after,
                        transition,
                        action_effect_observation,
                    )
                    if action_effect_observation is not None and entity_binding_authoritative
                    else None
                )
                action_hypothesis_update = self._update_action_hypothesis(
                    after,
                    transition,
                    consequence_id,
                    interpreted_action_effect,
                )
                traversability_update = (
                    self._update_traversability_hypothesis(
                        after,
                        transition,
                        consequence_id,
                        interpreted_action_effect,
                        prior_accepted_translation,
                    )
                    if interpreted_action_effect is not None
                    else _ActionHypothesisUpdate()
                )
                hypothesis_update = self._merge_hypothesis_updates(
                    action_hypothesis_update,
                    traversability_update,
                )
                if hypothesis_update.contradicted_hypothesis_ids:
                    self._prediction_cache.invalidate(
                        CacheInvalidationReason.HYPOTHESIS_CONTRADICTION_OR_REOPENING
                    )
                if (
                    interpreted_action_effect is not None
                    and after.levels_completed == previous_level
                ):
                    reopened_models = self._update_mechanics_lifecycle(
                        after,
                        transition,
                        interpreted_action_effect,
                        prior_accepted_translation=prior_accepted_translation,
                        hypothesis_update=hypothesis_update,
                        prior_models=prior_models,
                        invalidated_plan_ids=invalidated_plans,
                    )
                    if reopened_models:
                        self._prediction_cache.invalidate(
                            CacheInvalidationReason.MODEL_STATUS_CHANGE
                        )

        progress_ids: tuple[str, ...] = ()
        progress_signals: tuple[ProgressSignal, ...] = ()
        goal_update_transition: GoalTransition | None = None
        if self.features.use_goals:
            goal_update_transition = GoalTransition(
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
            progress_signals = self._measure_goal_progress(goal_update_transition)
            progress_ids = tuple(item.evidence.evidence_id for item in progress_signals)
            self._pending_goal_transitions.append(goal_update_transition)
            if progress_signals:
                self._append(
                    str(after.game_id),
                    "consequence.progress_detected",
                    {
                        "signal_ids": list(progress_ids),
                        "signal_kinds": [item.kind.value for item in progress_signals],
                        "source_consequence_event_id": consequence_id,
                    },
                )
            if after.state is GameStateName.WIN:
                prior_goal_projection = sha256_json(
                    {
                        "active_goal_id": self._active_goal_id,
                        "records": [item.to_dict() for item in self._goals.records()],
                    }
                )
                self._drain_pending_goal_updates(after)
                if self._active_goal_id is not None:
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
                if (
                    sha256_json(
                        {
                            "active_goal_id": self._active_goal_id,
                            "records": [item.to_dict() for item in self._goals.records()],
                        }
                    )
                    != prior_goal_projection
                ):
                    self._prediction_cache.invalidate(CacheInvalidationReason.GOAL_REVISION)

        self._latest_observation = after
        self._latest_receipt = observation_receipt
        self._latest_view = view
        self._pending_action = None
        self._pending_prediction = None
        self._pending_prediction_event_id = None
        self._restored_prediction_state_ids = ()
        self._restored_prediction_plan_ids = ()
        self._before_action_observation = None
        self._before_action_state = None
        self._before_action_features = None
        self._calibration_pending_handle = None
        self._pending_canonical_effect = None
        self._pending_resolution_kind = None
        self._pending_change_candidate_id = None
        self._pending_reexploration_candidate_id = None
        self._phase_from_observation(after)
        if after.levels_completed != previous_level:
            self._rotate_level_scope(
                after,
                observation_receipt,
                view,
                previous_level=previous_level,
                consequence_event_id=consequence_id,
            )
            self._prediction_cache.invalidate(CacheInvalidationReason.LEVEL_TRANSITION_OR_RESET)
        else:
            self._prepare_action_level(after)
            self._remember_frame(after.frames[-1].digest)
        if pending.action.name is ActionName.RESET:
            self._prediction_cache.invalidate(CacheInvalidationReason.LEVEL_TRANSITION_OR_RESET)
        self._transient_fold_boundary = None
        self._run_reasoning_cycle(
            after,
            observation_receipt,
            view,
            initial=False,
            progress_made=positive_external_progress(progress_signals)
            or after.levels_completed > previous_level
            or after.state is GameStateName.WIN,
            goal_revision_transition=(
                preserved_transition if after.state is not GameStateName.WIN else None
            ),
            goal_revision_consequence_event_id=(
                consequence_id
                if preserved_transition is not None and after.state is not GameStateName.WIN
                else None
            ),
        )
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

    @staticmethod
    def _measure_goal_progress(transition: GoalTransition) -> tuple[ProgressSignal, ...]:
        """Measure explicit progress without seeding or revising goal hypotheses."""

        before = progress_snapshot(
            transition.before,
            step=max(0, transition.step - 1),
            source_event_ids=transition.before_event_ids,
        )
        after = progress_snapshot(
            transition.after,
            step=transition.step,
            source_event_ids=transition.after_event_ids,
        )
        return detect_progress_signals(before, after)

    def _drain_pending_goal_updates(self, observation: Observation) -> None:
        """Apply receipt-backed goal revisions only inside a DEEP/terminal boundary."""

        while self._pending_goal_transitions:
            transition = self._pending_goal_transitions[0]
            self._acquire_goal_transition(transition)
            del self._pending_goal_transitions[0]
        self._flush_goal_events(observation)

    @_profiled("goal_inference")
    def _acquire_goal_transition(self, transition: GoalTransition) -> GoalAcquisitionResult:
        if self._hot_path_profiler is not None:
            self._hot_path_profiler.cache(
                "goal_inference",
                None,
                input_key=(
                    f"{transition.before.frames[-1].digest}|"
                    f"{transition.after.frames[-1].digest}|{transition.level_scope_ref}"
                ),
                change_kind=(
                    "unchanged"
                    if transition.before.frames[-1].digest == transition.after.frames[-1].digest
                    else "local_change"
                ),
            )
        return self._goal_acquirer.observe_transition(transition)

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
        self._plan_executor = PlanExecutor()
        self._pending_plan_emission = False
        previous_epoch_id = self._mechanics.active_epoch(previous_level).epoch_id
        self._action_effect_epoch_history.setdefault(
            previous_epoch_id, self._action_effects.projection()
        )
        self._mechanics.start_level(self._level_index)
        self._suspended_model_ids.clear()
        self._provisional_probe_handle = None
        self._reexploration_handle = None
        self._reexploration_candidate_id = None
        self._pending_change_candidate_id = None
        self._pending_reexploration_candidate_id = None
        self._provisional_mover_id = None
        self._clear_mover_reassignment()
        self._planning_disabled_after_mismatch = False
        self._action_effects = ActionEffectRegistry(level_index=self._level_index)
        self._exploration.action_registry = self._action_effects
        self._calibration_handles = ()
        self._calibrated_handles.clear()
        self._calibration_pending_handle = None
        self._recent_frame_hashes.clear()
        self._prepare_action_level(observation)
        self._remember_frame(observation.frames[-1].digest)
        if observation.state is GameStateName.WIN:
            return

        self._set_provisional_mover(view)

    @staticmethod
    def _merge_hypothesis_updates(
        *updates: _ActionHypothesisUpdate,
    ) -> _ActionHypothesisUpdate:
        """Combine source-ordered updates without duplicating derived identities."""

        destination_observations = tuple(
            update.destination_role_observation
            for update in updates
            if update.destination_role_observation is not None
        )
        if len(destination_observations) > 1:
            raise PolicyError("one transition produced multiple destination-role interpretations")
        return _ActionHypothesisUpdate(
            supported_hypothesis_ids=tuple(
                dict.fromkeys(
                    item for update in updates for item in update.supported_hypothesis_ids
                )
            ),
            contradicted_hypothesis_ids=tuple(
                dict.fromkeys(
                    item for update in updates for item in update.contradicted_hypothesis_ids
                )
            ),
            support_trace_event_ids=tuple(
                item for update in updates for item in update.support_trace_event_ids
            ),
            contradiction_trace_event_ids=tuple(
                item for update in updates for item in update.contradiction_trace_event_ids
            ),
            created_hypothesis_ids=tuple(
                dict.fromkeys(item for update in updates for item in update.created_hypothesis_ids)
            ),
            support_trace_event_pairs=tuple(
                item for update in updates for item in update.support_trace_event_pairs
            ),
            contradiction_trace_event_pairs=tuple(
                item for update in updates for item in update.contradiction_trace_event_pairs
            ),
            destination_role_observation=(
                destination_observations[0] if destination_observations else None
            ),
            destination_role_supported_hypothesis_ids=tuple(
                dict.fromkeys(
                    item
                    for update in updates
                    for item in update.destination_role_supported_hypothesis_ids
                )
            ),
            destination_role_contradicted_hypothesis_ids=tuple(
                dict.fromkeys(
                    item
                    for update in updates
                    for item in update.destination_role_contradicted_hypothesis_ids
                )
            ),
        )

    @staticmethod
    def _axis_displacement_alternatives(before: int, after: int, extent: int) -> tuple[int, ...]:
        """Retain direct displacement and an unpromoted boundary-wrap alternative."""

        direct = after - before
        alternatives = {direct}
        if extent > 1 and before == 0 and after == extent - 1:
            alternatives.add(-1)
        elif extent > 1 and before == extent - 1 and after == 0:
            alternatives.add(1)
        return tuple(sorted(alternatives))

    @classmethod
    def _controlled_translation_candidates(
        cls,
        *,
        before: Cell,
        after: Cell,
        width: int,
        height: int,
    ) -> tuple[_ControlledTranslationCandidate, ...]:
        """Type direct displacement separately from observational wrap alternatives."""

        direct = (after.x - before.x, after.y - before.y)
        translations = {
            (dx, dy)
            for dx in cls._axis_displacement_alternatives(before.x, after.x, width)
            for dy in cls._axis_displacement_alternatives(before.y, after.y, height)
            if (dx, dy) != (0, 0)
        }
        return tuple(
            _ControlledTranslationCandidate(
                translation=translation,
                evidence_kind=(
                    DisplacementEvidenceKind.DIRECT_OBSERVATION
                    if translation == direct
                    else DisplacementEvidenceKind.WRAP_TOPOLOGY_CANDIDATE
                ),
            )
            for translation in sorted(translations)
        )

    def _controlled_action_effect_observation(
        self,
        observation: Observation,
        transition: PreservedTransition,
        raw: ActionEffectObservation,
        *,
        interpretation_timing: str = "contemporaneous",
        authority_event_ids: tuple[str, ...] = (),
        confirmation_consequence_event_ids: tuple[str, ...] = (),
    ) -> ActionEffectObservation:
        """Interpret one established mover correspondence without editing the raw receipt.

        Whole-frame deltas can contain guide, target, or terrain motion unrelated to
        the submitted handle.  Once a mover correspondence is established, its
        before/after anchors supply a narrower, revisable interpretation.  The
        raw observation-level effect remains in ``action.effect_observed``.
        """

        mover_id = self._provisional_mover_id
        before_mover = transition.before.entity(mover_id) if mover_id is not None else None
        after_mover = transition.after.entity(mover_id) if mover_id is not None else None
        if before_mover is None or after_mover is None:
            return raw
        displacement_candidates = self._controlled_translation_candidates(
            before=before_mover.anchor,
            after=after_mover.anchor,
            width=transition.before.width,
            height=transition.before.height,
        )
        condition = raw.canonical_effects[0].condition_signature
        relation = raw.canonical_effects[0].coordinate_relation
        translations = tuple(item.translation for item in displacement_candidates)
        effects = (
            tuple(
                CanonicalActionEffect(
                    CanonicalEffectKind.TRANSLATION,
                    translation,
                    relation,
                    None,
                    condition,
                )
                for translation in translations
            )
            if translations
            else (
                CanonicalActionEffect(
                    CanonicalEffectKind.NO_OP,
                    None,
                    relation,
                    None,
                    condition,
                ),
            )
        )
        interpreted = ActionEffectObservation(
            source_event_id=raw.source_event_id,
            raw_handle=raw.raw_handle,
            canonical_effects=effects,
            before_digest=raw.before_digest,
            after_digest=raw.after_digest,
        )
        self._append(
            str(observation.game_id),
            "action.controlled_effect_interpreted",
            {
                "source_consequence_event_id": raw.source_event_id,
                "source_transition_id": transition.transition_id,
                "mover_entity_id": mover_id,
                "raw_canonical_effects": [item.projection() for item in raw.canonical_effects],
                "controlled_canonical_effect": (
                    effects[0].projection() if len(effects) == 1 else None
                ),
                "controlled_canonical_effects": [item.projection() for item in effects],
                "translation_interpretations": [
                    {
                        "translation": list(item.translation),
                        "evidence_kind": item.evidence_kind.value,
                        "has_action_authority": False,
                    }
                    for item in displacement_candidates
                ],
                "derivation": (
                    "established symbolic mover correspondence; direct displacement retained, "
                    "with boundary-wrap alternative unpromoted when observationally compatible"
                ),
                "interpretation_timing": interpretation_timing,
                "authority_event_ids": list(authority_event_ids),
                "confirmation_consequence_event_ids": list(confirmation_consequence_event_ids),
                "mechanics_epoch_id": self._transition_epochs[transition.transition_id],
            },
        )
        return interpreted

    def _destination_role_context(
        self,
        state: SymbolicState,
        translation: tuple[int, int],
    ) -> tuple[str, str, str, str] | None:
        """Identify a destination-role test without consulting its consequence."""

        mover_id = self._provisional_mover_id
        if mover_id is None:
            return None
        mover = state.entity(mover_id)
        if mover is None:
            return None
        dx, dy = translation
        destination_cells = tuple(Cell(cell.x + dx, cell.y + dy) for cell in mover.cells)
        if any(not state.contains(cell) for cell in destination_cells):
            return None
        obstacles = {
            entity.entity_id: entity
            for cell in destination_cells
            for entity in state.at(cell)
            if entity.entity_id != mover.entity_id
        }
        if not obstacles:
            return None

        def palette_role(entity: SymbolicEntity) -> str | None:
            return dict(entity.attributes).get("palette_role")

        moving_kind = palette_role(mover)
        # A marker can visually occlude the attempted terrain cell.  A connected
        # structural surface that borders the cell from multiple orthogonal
        # directions supplies generic, defeasible destination-role evidence.
        destination_set = set(destination_cells)
        inferred_surfaces = tuple(
            entity
            for entity in state.entities
            if entity.entity_id not in {mover.entity_id, *obstacles}
            and len(entity.cells) > len(mover.cells)
            and sum(
                any(
                    abs(cell.x - destination.x) + abs(cell.y - destination.y) == 1
                    for cell in entity.cells
                )
                for destination in destination_set
            )
            >= 1
            and sum(
                abs(cell.x - destination.x) + abs(cell.y - destination.y) == 1
                for destination in destination_set
                for cell in entity.cells
            )
            >= 2
        )
        inferred_surface_roles = {
            role for entity in inferred_surfaces if (role := palette_role(entity)) is not None
        }
        direct_obstacle_roles = {
            role for entity in obstacles.values() if (role := palette_role(entity)) is not None
        }
        obstacle_kinds = (
            inferred_surface_roles if len(inferred_surface_roles) == 1 else direct_obstacle_roles
        )
        if moving_kind is None or len(obstacle_kinds) != 1:
            return None
        obstacle_kind = next(iter(obstacle_kinds))
        condition_signature = sha256_json(
            {
                "domain": MechanicsChangeDomain.DESTINATION_ROLE.value,
                "width": state.width,
                "height": state.height,
                "moving_kind": moving_kind,
                "obstacle_kind": obstacle_kind,
            }
        )
        discrimination_context_id = sha256_json(
            {
                "domain": MechanicsChangeDomain.DESTINATION_ROLE.value,
                "obstacle_kind": obstacle_kind,
                "destination_cells": [
                    [cell.x, cell.y]
                    for cell in sorted(destination_cells, key=lambda item: (item.y, item.x))
                ],
            }
        )
        return (
            moving_kind,
            obstacle_kind,
            condition_signature,
            discrimination_context_id,
        )

    def _destination_role_observation(
        self,
        transition: PreservedTransition,
        action_effect_observation: ActionEffectObservation,
        prior_accepted_translation: tuple[int, int] | None,
    ) -> _DestinationRoleObservation | None:
        """Interpret a move attempt against one anonymously identified destination role."""

        if prior_accepted_translation is None:
            return None
        context = self._destination_role_context(
            transition.before,
            prior_accepted_translation,
        )
        if context is None:
            return None
        observed_translations = {
            item.translation
            for item in action_effect_observation.canonical_effects
            if item.translation is not None
        }
        if prior_accepted_translation in observed_translations:
            traversable = True
        elif not observed_translations:
            traversable = False
        else:
            # A different non-zero displacement is action-semantics evidence,
            # not evidence about the attempted destination's terrain role.
            return None
        return _DestinationRoleObservation(
            moving_kind=context[0],
            obstacle_kind=context[1],
            traversable=traversable,
            condition_signature=context[2],
            discrimination_context_id=context[3],
        )

    def _update_traversability_hypothesis(
        self,
        observation: Observation,
        transition: PreservedTransition,
        consequence_event_id: str,
        action_effect_observation: ActionEffectObservation,
        prior_accepted_translation: tuple[int, int] | None,
    ) -> _ActionHypothesisUpdate:
        """Update a destination-role claim without treating every block as a rule change."""

        interpreted = self._destination_role_observation(
            transition,
            action_effect_observation,
            prior_accepted_translation,
        )
        if interpreted is None:
            return _ActionHypothesisUpdate()
        epoch_id = self._transition_epochs[transition.transition_id]
        scope_ref = f"level:{self._transition_levels[transition.transition_id]}"
        matching_domain = tuple(
            record
            for record in self._hypotheses.all()
            if isinstance(record.statement, CollisionTraversabilityStatement)
            and record.scope_ref == scope_ref
            and self._mechanics.hypothesis_epoch(record.hypothesis_id) == epoch_id
            and record.statement.moving_kind == interpreted.moving_kind
            and record.statement.obstacle_kind == interpreted.obstacle_kind
            and record.status not in {HypothesisStatus.REJECTED, HypothesisStatus.SUPERSEDED}
        )
        exact = tuple(
            record
            for record in matching_domain
            if cast(CollisionTraversabilityStatement, record.statement).traversable
            is interpreted.traversable
        )
        created_ids: list[str] = []
        # A contradictory alternative stays implicit until the repeated-change
        # gate opens a successor epoch.  This preserves source order and avoids
        # assigning a successor hypothesis identity after only one outlier.
        if not exact and not matching_domain:
            statement = CollisionTraversabilityStatement(
                moving_kind=interpreted.moving_kind,
                obstacle_kind=interpreted.obstacle_kind,
                traversable=interpreted.traversable,
                consequence=("entered" if interpreted.traversable else "blocked"),
            )
            digest = sha256_json(
                {
                    "statement": statement.to_dict(),
                    "mechanics_epoch_id": epoch_id,
                    "source_event_id": consequence_event_id,
                }
            ).removeprefix("sha256:")[:24]
            created = self._hypotheses.create(
                statement=statement,
                scope=HypothesisScope.LEVEL,
                scope_ref=scope_ref,
                created_from_event_ids=transition.source_event_ids,
                occurred_step=self._step_index,
                hypothesis_id=f"H-TRAVERSABILITY-{digest}",
                initial_rank_weight=0,
                note="destination-role relation induced from an observed move attempt",
            )
            self._mechanics.register_hypotheses((created.hypothesis_id,), epoch_id=epoch_id)
            created_ids.append(created.hypothesis_id)
            matching_domain = (*matching_domain, created)
            lifecycle_event = self._hypotheses.events[-1]
            payload = lifecycle_event.to_trace_payload()
            payload["mechanics_epoch_id"] = epoch_id
            self._append(
                str(observation.game_id),
                "hypothesis.created",
                payload,
            )

        supported_ids: list[str] = []
        contradicted_ids: list[str] = []
        support_event_ids: list[str] = []
        contradiction_event_ids: list[str] = []
        support_event_pairs: list[tuple[str, str]] = []
        contradiction_event_pairs: list[tuple[str, str]] = []

        def record_evidence(record_id: str, *, supports: bool, summary: str) -> None:
            evidence = EvidenceReceipt(
                receipt_id=(
                    f"evidence:{'support' if supports else 'contradiction'}:"
                    f"{record_id}:{transition.transition_id}"
                ),
                kind=EvidenceKind.SUPPORT if supports else EvidenceKind.CONTRADICTION,
                evidence_event_ids=(consequence_event_id,),
                summary=summary,
                observed_step=self._step_index,
                rank_impact=1,
            )
            updated = (
                self._hypotheses.support(record_id, evidence)
                if supports
                else self._hypotheses.contradict(record_id, evidence)
            )
            event_type = "hypothesis.supported" if supports else "hypothesis.contradicted"
            lifecycle_event = self._hypotheses.events[-1]
            payload = lifecycle_event.to_trace_payload()
            payload.update(
                {
                    "evidence_receipt": evidence.to_dict(),
                    "rank_weight": updated.rank_weight,
                    "mechanics_epoch_id": epoch_id,
                }
            )
            traced = self._append(
                str(observation.game_id),
                event_type,
                payload,
            )
            if supports:
                supported_ids.append(record_id)
                support_event_ids.append(traced.event_id)
                support_event_pairs.append((record_id, traced.event_id))
            else:
                contradicted_ids.append(record_id)
                contradiction_event_ids.append(traced.event_id)
                contradiction_event_pairs.append((record_id, traced.event_id))

        for record in matching_domain:
            supports = (
                cast(CollisionTraversabilityStatement, record.statement).traversable
                is interpreted.traversable
            )
            record_evidence(
                record.hypothesis_id,
                supports=supports,
                summary=(
                    "destination-role relation matched the preserved transition"
                    if supports
                    else "destination-role relation contradicted by the preserved transition"
                ),
            )

        return _ActionHypothesisUpdate(
            supported_hypothesis_ids=tuple(supported_ids),
            contradicted_hypothesis_ids=tuple(contradicted_ids),
            support_trace_event_ids=tuple(support_event_ids),
            contradiction_trace_event_ids=tuple(contradiction_event_ids),
            created_hypothesis_ids=tuple(created_ids),
            support_trace_event_pairs=tuple(support_event_pairs),
            contradiction_trace_event_pairs=tuple(contradiction_event_pairs),
            destination_role_observation=interpreted,
            destination_role_supported_hypothesis_ids=tuple(supported_ids),
            destination_role_contradicted_hypothesis_ids=tuple(contradicted_ids),
        )

    @_profiled("hypothesis_update")
    def _update_action_hypothesis(
        self,
        observation: Observation,
        transition: PreservedTransition,
        consequence_event_id: str,
        action_effect_observation: ActionEffectObservation | None,
    ) -> _ActionHypothesisUpdate:
        scope_ref = f"level:{self._transition_levels[transition.transition_id]}"
        transition_epoch_id = self._transition_epochs[transition.transition_id]
        created_ids: list[str] = []
        if action_effect_observation is not None and self._provisional_mover_id is not None:
            existing_handle_claims = tuple(
                record
                for record in self._hypotheses.all()
                if isinstance(record.statement, ActionSemanticsStatement)
                and record.statement.action == transition.action.name.value
                and record.scope_ref == scope_ref
                and self._mechanics.hypothesis_epoch(record.hypothesis_id) == transition_epoch_id
                and record.status not in {HypothesisStatus.REJECTED, HypothesisStatus.SUPERSEDED}
            )
            observed_translations = {
                item.translation
                for item in action_effect_observation.canonical_effects
                if item.translation is not None
            }
            accepted_translation = (
                next(iter(observed_translations)) if len(observed_translations) == 1 else None
            )
            accepted_effect = (
                action_effect_observation.canonical_effects[0]
                if len(action_effect_observation.canonical_effects) == 1
                else None
            )
            # Alternative successor identifiers are reserved until the repeated
            # contradiction gate confirms an epoch change.  A fresh epoch has
            # no handle claim, so its first scoped consequence may seed one.
            if not existing_handle_claims and (
                accepted_translation is not None
                or (
                    accepted_effect is not None
                    and accepted_effect.effect_kind is not CanonicalEffectKind.NO_OP
                )
            ):
                parameters: dict[str, JSONValue] = {"entity_id": self._provisional_mover_id}
                if accepted_translation is not None:
                    dx, dy = accepted_translation
                    parameters.update({"dx": dx, "dy": dy})
                    effect_name = "translation"
                else:
                    if accepted_effect is None:
                        raise PolicyError("accepted action effect unexpectedly absent")
                    effect_name = accepted_effect.effect_kind.value
                new_statement = ActionSemanticsStatement(
                    action=transition.action.name.value,
                    effect=effect_name,
                    parameters=parameters,
                )
                digest = sha256_json(
                    {
                        "statement": new_statement.to_dict(),
                        "level_index": self._transition_levels[transition.transition_id],
                        "source_event_id": consequence_event_id,
                    }
                ).removeprefix("sha256:")[:24]
                created = self._hypotheses.create(
                    statement=new_statement,
                    scope=HypothesisScope.LEVEL,
                    scope_ref=scope_ref,
                    created_from_event_ids=transition.source_event_ids,
                    occurred_step=self._step_index,
                    hypothesis_id=f"H-ACTION-EFFECT-{digest}",
                    initial_rank_weight=0,
                    note="mover-scoped effect induced from a returned consequence",
                )
                self._mechanics.register_hypotheses(
                    (created.hypothesis_id,), epoch_id=transition_epoch_id
                )
                created_ids.append(created.hypothesis_id)
                lifecycle_event = self._hypotheses.events[-1]
                payload = lifecycle_event.to_trace_payload()
                payload["mechanics_epoch_id"] = transition_epoch_id
                self._append(
                    str(observation.game_id),
                    "hypothesis.created",
                    payload,
                )

        matching = tuple(
            record
            for record in self._hypotheses.all()
            if isinstance(record.statement, ActionSemanticsStatement)
            and record.statement.action == transition.action.name.value
            and record.scope_ref == scope_ref
            and self._mechanics.hypothesis_epoch(record.hypothesis_id) == transition_epoch_id
            and record.status not in {HypothesisStatus.REJECTED, HypothesisStatus.SUPERSEDED}
            and (self.features.retain_rejected_hypotheses or not record.contradiction_receipts)
        )
        supported_ids: list[str] = []
        contradicted_ids: list[str] = []
        support_event_ids: list[str] = []
        contradiction_event_ids: list[str] = []
        support_event_pairs: list[tuple[str, str]] = []
        contradiction_event_pairs: list[tuple[str, str]] = []
        for record in matching:
            record_statement = cast(ActionSemanticsStatement, record.statement)
            semantic_match: bool | None = None
            if action_effect_observation is not None:
                observed_translations = {
                    item.translation
                    for item in action_effect_observation.canonical_effects
                    if item.translation is not None
                }
                effect_name = record_statement.effect.lower()
                if effect_name in {"translate", "translation", "move", "movement"}:
                    expected_dx = record_statement.parameters.get("dx")
                    expected_dy = record_statement.parameters.get("dy")
                    if (
                        isinstance(expected_dx, int)
                        and not isinstance(expected_dx, bool)
                        and isinstance(expected_dy, int)
                        and not isinstance(expected_dy, bool)
                    ):
                        expected = (expected_dx, expected_dy)
                        if expected in observed_translations:
                            semantic_match = True
                        elif observed_translations:
                            semantic_match = False
                        else:
                            # A stationary consequence alone cannot distinguish an
                            # action-semantics change from an unseen collision,
                            # boundary, or other topology rule.  Destination-role
                            # hypotheses carry that contradiction when observable.
                            continue
                elif effect_name in {"no-op", "noop", "identity"}:
                    semantic_match = transition.before == transition.after
            if semantic_match is None:
                compiled = compile_hypotheses((record,))
                if not compiled.candidates:
                    continue
                test_transitions = self._candidate_retrodiction_transitions(
                    compiled.candidates[0], (transition,)
                )
                if not test_transitions:
                    continue
                semantic_match = retrodict(compiled.candidates[0], test_transitions).promotable
            if semantic_match:
                evidence = EvidenceReceipt(
                    receipt_id=(
                        f"evidence:support:{record.hypothesis_id}:{transition.transition_id}"
                    ),
                    kind=EvidenceKind.SUPPORT,
                    evidence_event_ids=(consequence_event_id,),
                    summary="executable action rule matched the preserved transition",
                    observed_step=self._step_index,
                    rank_impact=1,
                )
                updated = self._hypotheses.support(record.hypothesis_id, evidence)
                event_type = "hypothesis.supported"
                supported_ids.append(record.hypothesis_id)
            else:
                evidence = EvidenceReceipt(
                    receipt_id=(
                        f"evidence:contradiction:{record.hypothesis_id}:{transition.transition_id}"
                    ),
                    kind=EvidenceKind.CONTRADICTION,
                    evidence_event_ids=(consequence_event_id,),
                    summary="executable action rule mismatched the preserved transition",
                    observed_step=self._step_index,
                    rank_impact=1,
                )
                updated = self._hypotheses.contradict(record.hypothesis_id, evidence)
                event_type = "hypothesis.contradicted"
                contradicted_ids.append(record.hypothesis_id)
            lifecycle_event = self._hypotheses.events[-1]
            payload = lifecycle_event.to_trace_payload()
            payload.update(
                {
                    "evidence_receipt": evidence.to_dict(),
                    "rank_weight": updated.rank_weight,
                    "mechanics_epoch_id": transition_epoch_id,
                }
            )
            traced = self._append(
                str(observation.game_id),
                event_type,
                payload,
            )
            if event_type == "hypothesis.supported":
                support_event_ids.append(traced.event_id)
                support_event_pairs.append((record.hypothesis_id, traced.event_id))
            else:
                contradiction_event_ids.append(traced.event_id)
                contradiction_event_pairs.append((record.hypothesis_id, traced.event_id))
        return _ActionHypothesisUpdate(
            supported_hypothesis_ids=tuple(sorted(supported_ids)),
            contradicted_hypothesis_ids=tuple(sorted(contradicted_ids)),
            support_trace_event_ids=tuple(support_event_ids),
            contradiction_trace_event_ids=tuple(contradiction_event_ids),
            created_hypothesis_ids=tuple(sorted(created_ids)),
            support_trace_event_pairs=tuple(support_event_pairs),
            contradiction_trace_event_pairs=tuple(contradiction_event_pairs),
        )

    @staticmethod
    def _effect_signature(effects: Sequence[CanonicalActionEffect]) -> str:
        """Hash the persistent, raw-handle-free mechanics facet of a consequence.

        A frame can also be classified as a restore because it matches an older
        digest.  That episode-relative annotation remains in the immutable
        action-effect receipt, but it must not split an otherwise identical
        translation rule by position or visit history.
        """

        translations = tuple(
            sorted({item.translation for item in effects if item.translation is not None})
        )
        if translations:
            material: dict[str, JSONValue] = {
                "persistent_effect_kind": "translation",
                "translations": [list(item) for item in translations],
            }
        else:
            persistent_kinds: list[JSONValue] = list(
                sorted(
                    {
                        item.effect_kind.value
                        for item in effects
                        if item.effect_kind is not CanonicalEffectKind.RESTORE
                    }
                    or {CanonicalEffectKind.NO_OP.value}
                )
            )
            material = {"persistent_effect_kinds": persistent_kinds}
        return sha256_json(material)

    @staticmethod
    def _translation_signature(translation: tuple[int, int]) -> str:
        """Hash the same persistent facet from an accepted translation binding."""

        return sha256_json(
            {
                "persistent_effect_kind": "translation",
                "translations": [list(translation)],
            }
        )

    @staticmethod
    def _action_mapping_change_signature(
        predecessor: tuple[int, int],
        effects: Sequence[CanonicalActionEffect],
    ) -> str | None:
        """Describe a handle-free transform from old to observed displacement."""

        translations = tuple(
            sorted({item.translation for item in effects if item.translation is not None})
        )
        if len(translations) != 1:
            return None
        successor = translations[0]
        px, py = predecessor
        relation = (
            "identity"
            if successor == predecessor
            else "rotate-clockwise"
            if successor == (-py, px)
            else "rotate-counterclockwise"
            if successor == (py, -px)
            else "reverse"
            if successor == (-px, -py)
            else None
        )
        if relation is None:
            return sha256_json(
                {
                    "domain": MechanicsChangeDomain.ACTION_MAPPING.value,
                    "relation": "unclassified",
                    "predecessor": list(predecessor),
                    "successor": list(successor),
                }
            )
        return sha256_json(
            {
                "domain": MechanicsChangeDomain.ACTION_MAPPING.value,
                "relation": relation,
            }
        )

    @staticmethod
    def _destination_role_effect_signature(
        *,
        moving_kind: str,
        obstacle_kind: str,
        traversable: bool,
    ) -> str:
        """Hash an anonymous terrain-role consequence independently of its handle."""

        return sha256_json(
            {
                "domain": MechanicsChangeDomain.DESTINATION_ROLE.value,
                "moving_kind": moving_kind,
                "obstacle_kind": obstacle_kind,
                "traversable": traversable,
            }
        )

    @staticmethod
    def _evidence_event_for_hypotheses(
        event_pairs: Sequence[tuple[str, str]],
        hypothesis_ids: Sequence[str],
    ) -> str | None:
        affected = set(hypothesis_ids)
        return next(
            (event_id for hypothesis_id, event_id in event_pairs if hypothesis_id in affected), None
        )

    def _suspend_change_authority(
        self,
        candidate: MechanicsChangeCandidate,
    ) -> None:
        """Withhold candidate-dependent action authority without calling it demotion."""

        self._suspended_model_ids.update(candidate.affected_model_ids)
        self._invalidated_plan_ids.update(candidate.invalidated_plan_ids)
        if self._ensemble is not None:
            self._ensemble = self._ensemble.without(candidate.affected_model_ids)
        self._prediction_cache.invalidate(CacheInvalidationReason.MODEL_STATUS_CHANGE)
        self._plan_executor = PlanExecutor()
        self._pending_plan_emission = False

    def _transition_ids_sourced_by(self, trace_event_ids: Sequence[str]) -> tuple[str, ...]:
        """Resolve derived transition IDs through retained evidence pointers."""

        source_ids: set[str] = set()
        for trace_event_id in trace_event_ids:
            event = self.journal.get_event(trace_event_id)
            if event is None:
                continue
            raw_receipt = event.payload.get("evidence_receipt")
            if not isinstance(raw_receipt, dict):
                continue
            raw_sources = raw_receipt.get("evidence_event_ids")
            if isinstance(raw_sources, list):
                source_ids.update(item for item in raw_sources if isinstance(item, str))
        return tuple(
            sorted(
                transition.transition_id
                for transition in self._transitions
                if set(transition.source_event_ids) & source_ids
            )
        )

    def _confirm_mechanics_change(
        self,
        observation: Observation,
        transition: PreservedTransition,
        candidate: MechanicsChangeCandidate,
    ) -> None:
        """Emit the ordered confirmed-change lifecycle and open one fresh epoch."""

        predecessor_epoch = self._mechanics.epoch(candidate.predecessor_epoch_id)
        self._append(
            str(observation.game_id),
            "model.rule_demoted",
            {
                "model_ids": list(candidate.affected_model_ids),
                "hypothesis_ids": list(candidate.affected_hypothesis_ids),
                "mechanics_epoch_id": predecessor_epoch.epoch_id,
                "change_candidate_id": candidate.candidate_id,
                "supporting_contradiction_event_ids": list(
                    candidate.supporting_contradiction_event_ids
                ),
                "invalidated_plan_ids": list(candidate.invalidated_plan_ids),
                "new_status": "demoted",
            },
        )
        self._demoted_model_ids.update(candidate.affected_model_ids)
        self._suspended_model_ids.difference_update(candidate.affected_model_ids)

        for hypothesis_id in candidate.affected_hypothesis_ids:
            record = self._hypotheses.find(hypothesis_id)
            if record is None or record.status in {
                HypothesisStatus.REJECTED,
                HypothesisStatus.SUPERSEDED,
            }:
                continue
            evidence = EvidenceReceipt(
                receipt_id=f"evidence:reopen:{candidate.candidate_id}:{hypothesis_id}",
                kind=EvidenceKind.CONTRADICTION,
                evidence_event_ids=candidate.supporting_contradiction_event_ids,
                summary="confirmed mechanics change reopens predecessor rule",
                observed_step=self._step_index,
                rank_impact=1,
            )
            invalidation = self._hypotheses.reopen(
                hypothesis_id,
                evidence,
                invalidated_plan_ids=candidate.invalidated_plan_ids,
                note="confirmed successor evidence; predecessor retained as prior-epoch history",
            )
            lifecycle_event = self._hypotheses.events[-1]
            self._invalidated_plan_ids.update(invalidation.plan_ids)
            payload = lifecycle_event.to_trace_payload()
            payload.update(
                {
                    "mechanics_epoch_id": predecessor_epoch.epoch_id,
                    "change_candidate_id": candidate.candidate_id,
                }
            )
            self._append(str(observation.game_id), "hypothesis.reopened", payload)

        self._append(
            str(observation.game_id),
            "mechanics.change_confirmed",
            {
                **candidate.to_dict(),
                "source_transition_id": transition.transition_id,
                "confirmation_rule": "two coherent successor consequences",
            },
        )
        successor = self._mechanics.open_successor_epoch(
            candidate.candidate_id,
            start_transition_id=transition.transition_id,
        )
        self._append(
            str(observation.game_id),
            "mechanics.epoch_opened",
            {
                **successor.to_dict(),
                "predecessor_epoch_id": predecessor_epoch.epoch_id,
                "history_policy": "prior receipts retained; only successor epoch has authority",
            },
        )
        self._prediction_cache.invalidate(
            CacheInvalidationReason.HYPOTHESIS_CONTRADICTION_OR_REOPENING
        )
        self._prediction_cache.invalidate(CacheInvalidationReason.MECHANICS_EPOCH_CHANGE)

        self._action_effect_epoch_history[predecessor_epoch.epoch_id] = (
            self._action_effects.projection()
        )
        self._action_effects = ActionEffectRegistry(level_index=self._level_index)
        self._exploration.action_registry = self._action_effects
        # The successor registry starts at the confirmation consequence.  Do
        # not let predecessor frame recurrence silently influence its fresh
        # action semantics; the returned successor observation is remembered
        # once by the normal consequence tail below.
        self._recent_frame_hashes.clear()
        self._calibrated_handles.clear()
        self._calibration_pending_handle = None
        self._ensemble = None
        self._model_candidates = ()
        self._plan_executor = PlanExecutor()
        self._pending_plan_emission = False
        # A mismatch in the predecessor epoch cannot permanently disable
        # planning under independently retrodicted successor-epoch models.
        self._planning_disabled_after_mismatch = False
        self._provisional_probe_handle = None
        self._pending_change_candidate_id = None
        self._reexploration_handle = transition.action.name
        self._reexploration_candidate_id = candidate.candidate_id

    def _update_mechanics_lifecycle(
        self,
        observation: Observation,
        transition: PreservedTransition,
        action_effect_observation: ActionEffectObservation,
        *,
        prior_accepted_translation: tuple[int, int] | None,
        hypothesis_update: _ActionHypothesisUpdate,
        prior_models: tuple[ModelCandidate, ...],
        invalidated_plan_ids: set[str],
    ) -> tuple[str, ...]:
        """Fold generic repeated effect evidence into change points and epochs."""

        handle = transition.action.name
        role_observation = hypothesis_update.destination_role_observation
        role_hypothesis_ids = (
            *hypothesis_update.destination_role_supported_hypothesis_ids,
            *hypothesis_update.destination_role_contradicted_hypothesis_ids,
        )
        candidate = self._mechanics.live_candidate(
            level_index=self._level_index,
            opaque_handle=handle.value,
            affected_hypothesis_ids=role_hypothesis_ids,
        )

        if candidate is not None:
            if candidate.change_domain is MechanicsChangeDomain.ACTION_MAPPING:
                if prior_accepted_translation is None:
                    self._provisional_probe_handle = ActionName(candidate.opaque_handle)
                    return ()
                mapping_signature = self._action_mapping_change_signature(
                    prior_accepted_translation,
                    action_effect_observation.canonical_effects,
                )
                if mapping_signature is None:
                    self._provisional_probe_handle = ActionName(candidate.opaque_handle)
                    return ()
                observed_signature = mapping_signature
                observation_condition_signature = action_effect_observation.canonical_effects[
                    0
                ].condition_signature
                discrimination_context_id = f"opaque-handle:{handle.value}"
                contradiction_event_id = self._evidence_event_for_hypotheses(
                    hypothesis_update.contradiction_trace_event_pairs,
                    candidate.affected_hypothesis_ids,
                )
            elif candidate.change_domain is MechanicsChangeDomain.DESTINATION_ROLE:
                if role_observation is None or not set(role_hypothesis_ids) & set(
                    candidate.affected_hypothesis_ids
                ):
                    # An unrelated handle consequence does not resolve a
                    # role-scoped candidate in either direction.
                    self._provisional_probe_handle = ActionName(candidate.opaque_handle)
                    return ()
                observed_signature = self._destination_role_effect_signature(
                    moving_kind=role_observation.moving_kind,
                    obstacle_kind=role_observation.obstacle_kind,
                    traversable=role_observation.traversable,
                )
                observation_condition_signature = role_observation.condition_signature
                discrimination_context_id = role_observation.discrimination_context_id
                contradiction_event_id = self._evidence_event_for_hypotheses(
                    hypothesis_update.contradiction_trace_event_pairs,
                    candidate.affected_hypothesis_ids,
                )
            else:
                observed_signature = self._effect_signature(
                    action_effect_observation.canonical_effects
                )
                observation_condition_signature = action_effect_observation.canonical_effects[
                    0
                ].condition_signature
                discrimination_context_id = f"opaque-handle:{handle.value}"
                contradiction_event_id = self._evidence_event_for_hypotheses(
                    hypothesis_update.contradiction_trace_event_pairs,
                    candidate.affected_hypothesis_ids,
                )
            if observation_condition_signature != candidate.observation_condition_signature:
                # A changed observation condition is neither successor support
                # nor predecessor recovery. Keep the probe live without
                # manufacturing evidence across contexts.
                self._provisional_probe_handle = ActionName(candidate.opaque_handle)
                return ()
            if observed_signature == candidate.successor_effect_signature:
                if contradiction_event_id is None:
                    return ()
                if not self._mechanics.successor_support_is_new(
                    candidate.candidate_id,
                    contradiction_event_id=contradiction_event_id,
                    contradiction_transition_id=transition.transition_id,
                    discrimination_context_id=discrimination_context_id,
                    successor_effect_signature=observed_signature,
                    observation_condition_signature=observation_condition_signature,
                ):
                    self._provisional_probe_handle = ActionName(candidate.opaque_handle)
                    return ()
                self._append_mechanics_successor_support(
                    observation,
                    transition,
                    candidate,
                    contradiction_event_id=contradiction_event_id,
                    observed_signature=observed_signature,
                    observation_condition_signature=observation_condition_signature,
                    discrimination_context_id=discrimination_context_id,
                )
                supported = self._mechanics.support_successor(
                    candidate.candidate_id,
                    contradiction_event_id=contradiction_event_id,
                    contradiction_transition_id=transition.transition_id,
                    discrimination_context_id=discrimination_context_id,
                    successor_effect_signature=observed_signature,
                    observation_condition_signature=observation_condition_signature,
                    observed_step=self._step_index,
                )
                if supported.provisional_status is MechanicsChangeStatus.CONFIRMED:
                    self._confirm_mechanics_change(observation, transition, supported)
                    return supported.affected_model_ids
                self._provisional_probe_handle = ActionName(candidate.opaque_handle)
                return ()
            if observed_signature == candidate.predecessor_effect_signature:
                recovery_support = self._append(
                    str(observation.game_id),
                    "mechanics.predecessor_recovery_supported",
                    {
                        "candidate_id": candidate.candidate_id,
                        "predecessor_epoch_id": candidate.predecessor_epoch_id,
                        "source_transition_id": transition.transition_id,
                        "source_consequence_event_id": transition.source_event_ids[2],
                        "source_observation_event_id": transition.source_event_ids[3],
                        "observed_effect_signature": observed_signature,
                        "observation_condition_signature": observation_condition_signature,
                        "discrimination_context_id": discrimination_context_id,
                        "affected_hypothesis_ids": list(candidate.affected_hypothesis_ids),
                        "support_index": len(candidate.predecessor_recovery_event_ids) + 1,
                        "interpretation": "predecessor-consistent consequence",
                    },
                )
                recovered = self._mechanics.support_predecessor(
                    candidate.candidate_id,
                    evidence_event_id=recovery_support.event_id,
                    observed_step=self._step_index,
                )
                if recovered.provisional_status is MechanicsChangeStatus.RESOLVED_NOISE:
                    resolved_noise_ids = self._transition_ids_sourced_by(
                        (recovered.first_contradiction_event_id,)
                    )
                    self._resolved_noise_transition_ids.update(resolved_noise_ids)
                    self._suspended_model_ids.difference_update(recovered.affected_model_ids)
                    self._provisional_probe_handle = None
                    self._pending_change_candidate_id = None
                    self._append(
                        str(observation.game_id),
                        "mechanics.change_candidate_resolved",
                        {
                            **recovered.to_dict(),
                            "resolution": "two predecessor-consistent consequences",
                            "history_policy": "outlier retained as immutable counterevidence",
                            "retrodiction_excluded_transition_ids": list(resolved_noise_ids),
                        },
                    )
                else:
                    self._provisional_probe_handle = ActionName(candidate.opaque_handle)
                return ()
            contradicted = self._mechanics.contradict_candidate(
                candidate.candidate_id, observed_step=self._step_index
            )
            self._provisional_probe_handle = None
            self._append(
                str(observation.game_id),
                "mechanics.change_candidate_resolved",
                {
                    **contradicted.to_dict(),
                    "resolution": "incoherent third effect contradicted the fixed successor",
                    "observed_effect_signature": observed_signature,
                    "source_transition_id": transition.transition_id,
                    "model_authority": "affected predecessor models remain suspended",
                    "recovery": "generic exploration without affected-model authority",
                },
            )
            return ()

        change_domain = MechanicsChangeDomain.ACTION_MAPPING
        action_contradictions = tuple(
            hypothesis_id
            for hypothesis_id in hypothesis_update.contradicted_hypothesis_ids
            if (record := self._hypotheses.find(hypothesis_id)) is not None
            and isinstance(record.statement, ActionSemanticsStatement)
        )
        current_epoch_id = self._mechanics.active_epoch(self._level_index).epoch_id
        affected_hypotheses = tuple(
            record.hypothesis_id
            for record in self._hypotheses.all()
            if isinstance(record.statement, ActionSemanticsStatement)
            and record.is_ensemble_eligible
            and self._mechanics.hypothesis_epoch(record.hypothesis_id) == current_epoch_id
        )
        contradiction_event_id = self._evidence_event_for_hypotheses(
            hypothesis_update.contradiction_trace_event_pairs,
            action_contradictions,
        )
        if (
            role_observation is not None
            and hypothesis_update.destination_role_contradicted_hypothesis_ids
        ):
            change_domain = MechanicsChangeDomain.DESTINATION_ROLE
            affected_hypotheses = hypothesis_update.destination_role_contradicted_hypothesis_ids
            predecessor_signatures = {
                self._destination_role_effect_signature(
                    moving_kind=statement.moving_kind,
                    obstacle_kind=statement.obstacle_kind,
                    traversable=statement.traversable,
                )
                for hypothesis_id in affected_hypotheses
                if (record := self._hypotheses.find(hypothesis_id)) is not None
                if isinstance((statement := record.statement), CollisionTraversabilityStatement)
            }
            if len(predecessor_signatures) != 1:
                return ()
            predecessor_signature = next(iter(predecessor_signatures))
            observed_signature = self._destination_role_effect_signature(
                moving_kind=role_observation.moving_kind,
                obstacle_kind=role_observation.obstacle_kind,
                traversable=role_observation.traversable,
            )
            observation_condition_signature = role_observation.condition_signature
            discrimination_context_id = role_observation.discrimination_context_id
            contradiction_event_id = self._evidence_event_for_hypotheses(
                hypothesis_update.contradiction_trace_event_pairs,
                affected_hypotheses,
            )
        else:
            if prior_accepted_translation is None:
                return ()
            predecessor_signature = sha256_json(
                {
                    "domain": MechanicsChangeDomain.ACTION_MAPPING.value,
                    "relation": "identity",
                }
            )
            mapping_signature = self._action_mapping_change_signature(
                prior_accepted_translation,
                action_effect_observation.canonical_effects,
            )
            if mapping_signature is None:
                return ()
            observed_signature = mapping_signature
            observation_condition_signature = action_effect_observation.canonical_effects[
                0
            ].condition_signature
            discrimination_context_id = f"opaque-handle:{handle.value}"
        if not affected_hypotheses or contradiction_event_id is None:
            return ()
        if observed_signature == predecessor_signature:
            return ()
        affected_models = tuple(
            sorted(
                candidate_model.model_id
                for candidate_model in prior_models
                if set(candidate_model.hypothesis_ids) & set(affected_hypotheses)
            )
        )
        if not affected_models:
            return ()
        dependent_plans = {
            plan_id
            for hypothesis_id in affected_hypotheses
            for plan_id in self._hypotheses.dependent_plan_ids(hypothesis_id)
        }
        dependent_plans.update(invalidated_plan_ids)
        opened = self._mechanics.open_candidate(
            level_index=self._level_index,
            change_domain=change_domain,
            opaque_handle=handle.value,
            predecessor_effect_signature=predecessor_signature,
            successor_effect_signature=observed_signature,
            observation_condition_signature=observation_condition_signature,
            affected_hypothesis_ids=affected_hypotheses,
            affected_model_ids=affected_models,
            contradiction_event_id=contradiction_event_id,
            contradiction_transition_id=transition.transition_id,
            discrimination_context_id=discrimination_context_id,
            invalidated_plan_ids=dependent_plans,
            opened_step=self._step_index,
        )
        self._suspend_change_authority(opened)
        invalidated_plan_ids.update(opened.invalidated_plan_ids)
        self._provisional_probe_handle = handle
        self._append(
            str(observation.game_id),
            "mechanics.change_candidate_created",
            {
                **opened.to_dict(),
                "source_transition_id": transition.transition_id,
                "source_consequence_event_id": action_effect_observation.source_event_id,
                "model_authority": "provisionally-suspended",
                "confirmation_rule": "one additional coherent successor consequence",
            },
        )
        self._append_mechanics_successor_support(
            observation,
            transition,
            opened,
            contradiction_event_id=contradiction_event_id,
            observed_signature=observed_signature,
            observation_condition_signature=observation_condition_signature,
            discrimination_context_id=discrimination_context_id,
        )
        return ()

    def _append_mechanics_successor_support(
        self,
        observation: Observation,
        transition: PreservedTransition,
        candidate: MechanicsChangeCandidate,
        *,
        contradiction_event_id: str,
        observed_signature: str,
        observation_condition_signature: str,
        discrimination_context_id: str,
    ) -> None:
        """Preserve one candidate-linked interpretation of successor evidence."""

        support_triples = tuple(
            zip(
                candidate.supporting_contradiction_event_ids,
                candidate.supporting_successor_transition_ids,
                candidate.supporting_discrimination_context_ids,
                strict=True,
            )
        )
        support_triple = (
            contradiction_event_id,
            transition.transition_id,
            discrimination_context_id,
        )
        support_index = (
            support_triples.index(support_triple) + 1
            if support_triple in support_triples
            else len(support_triples) + 1
        )
        self._append(
            str(observation.game_id),
            "mechanics.successor_evidence_supported",
            {
                "candidate_id": candidate.candidate_id,
                "support_index": support_index,
                "predecessor_epoch_id": candidate.predecessor_epoch_id,
                "change_domain": candidate.change_domain.value,
                "opaque_handle": candidate.opaque_handle,
                "affected_hypothesis_ids": list(candidate.affected_hypothesis_ids),
                "contradiction_event_id": contradiction_event_id,
                "source_transition_id": transition.transition_id,
                "source_action_selected_event_id": transition.source_event_ids[0],
                "source_action_submitted_event_id": transition.source_event_ids[1],
                "source_consequence_event_id": transition.source_event_ids[2],
                "source_observation_event_id": transition.source_event_ids[3],
                "raw_action_handle": transition.action.name.value,
                "action": _action_payload(transition.action),
                "observed_effect_signature": observed_signature,
                "observation_condition_signature": observation_condition_signature,
                "discrimination_context_id": discrimination_context_id,
                "interpretation": "successor-consistent contradiction consequence",
            },
        )

    def _safe_fold_checkpoint_for_pending_deliberation(
        self,
    ) -> ControllerCheckpoint | None:
        """Return the exact pre-deliberation fold checkpoint when recoverable.

        The durable automatic checkpoint is written after the observation or
        consequence fold and before ``reasoning.path_selected``.  Returning it
        is safe only while every later receipt is on the closed revisable
        interruption allowlist; restore will then reopen precisely that suffix.
        """

        manager = self._checkpoint_manager
        checkpoint = self._last_checkpoint
        receipt = self._latest_receipt
        if (
            manager is None
            or checkpoint is None
            or receipt is None
            or not checkpoint.path.is_file()
        ):
            return None
        try:
            persisted = manager.store.load(checkpoint.path)
            state = DerivedControllerState.from_dict(
                persisted.state.get("derived_controller_state")
            )
            events = self.journal.verify_manifest()
        except (CheckpointError, MemoryContractError, OSError, ValueError):
            return None
        planner = state.planner_state
        cadence = planner.get("cadence_state")
        if not isinstance(cadence, Mapping):
            return None
        commitments = tuple(
            (index, event)
            for index, event in enumerate(events)
            if event.event_type == "run.checkpoint_written"
            and event.episode_id == self.context.episode_id
        )
        if not commitments:
            return None
        commitment_index, commitment = commitments[-1]
        suffix = events[commitment_index + 1 :]
        if (
            persisted.checkpoint_hash != checkpoint.envelope.checkpoint_hash
            or commitment.payload.get("checkpoint_hash") != persisted.checkpoint_hash
            or commitment.payload.get("pending_submitted_event_id") is not None
            or not suffix
            or any(
                event.episode_id != self.context.episode_id
                or not is_revisable_interruption_event_type(event.event_type)
                for event in suffix
            )
            or state.pending_action is not None
            or state.step_index != self._step_index
            or state.level_index != self._level_index
            or state.perception_state.get("latest_observation_event_id")
            != receipt.observation_event_id
            or planner.get("cadence_folded_observation_event_id") != receipt.observation_event_id
            or cadence.get("pending_selection_hash") is not None
            or cadence.get("pending_path") is not None
        ):
            return None
        return checkpoint

    @_profiled("checkpointing")
    def checkpoint(self) -> ControllerCheckpoint:
        """Return a safe hash-bound restart point.

        Normally this writes a snapshot at the current immutable trace tail.
        If an automatic pre-deliberation fold checkpoint already commits the
        exact observation boundary and only safely revisable derived receipts
        follow it, return that existing content-addressed checkpoint unchanged.
        """

        if self._checkpoint_manager is None or self._code is None or self._source is None:
            raise PolicyError("controller checkpoint identity is unavailable")
        if self._transient_fold_boundary is not None:
            raise PolicyError(f"checkpoint refused during partial {self._transient_fold_boundary}")
        if self._cadence_activation_event_id is None:
            raise PolicyError("controller cadence activation identity is unavailable")
        if self._cadence_state.deliberation_in_progress:
            safe_fold = self._safe_fold_checkpoint_for_pending_deliberation()
            if safe_fold is not None:
                return safe_fold
            if self.preset not in {ControllerPreset.BASELINE, ControllerPreset.TRACE}:
                raise PolicyError("checkpoint refused while reasoning deliberation is in progress")
            latest = self._latest_observation
            if latest is None:
                raise PolicyError("pending reasoning lacks its observation boundary")
            self._reasoning_terminal_status = DeliberationStatus.FAILED
            self._reasoning_fault_type = "CheckpointRequestedBeforeAction"
            self._complete_reasoning_cycle(latest, advance_cadence=False)
        pending_goal_transitions = [
            self._serialize_goal_transition(item) for item in self._pending_goal_transitions
        ]
        cadence_commitment = self._append(
            self.context.game_id,
            "reasoning.checkpoint_state",
            {
                "cadence_configuration_hash": (self._cadence_config.configuration_hash),
                "cadence_activation_event_id": self._cadence_activation_event_id,
                "cadence_folded_observation_event_id": (self._cadence_folded_observation_event_id),
                "cadence_state": self._cadence_state.to_checkpoint_dict(),
                "prediction_cache_projection_hash": (self._prediction_cache.projection_hash),
                "prediction_cache_telemetry_hash": sha256_json(self._prediction_cache.to_dict()),
                "pending_goal_transitions_hash": sha256_json(pending_goal_transitions),
                "pending_submitted_event_id": (
                    self._pending_action.submitted_event_id
                    if self._pending_action is not None
                    else None
                ),
                "reasoning_completed_event_id": (self._reasoning_completed_event_id),
                "reasoning_selected_event_id": self._reasoning_selected_event_id,
                "reasoning_selection": (
                    self._reasoning_selection.to_dict()
                    if self._reasoning_selection is not None
                    else None
                ),
            },
            scope="run",
        )
        self._cadence_checkpoint_state_event_id = cadence_commitment.event_id
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
            "mover_reassignment_candidate_id": self._mover_reassignment_candidate_id,
            "mover_reassignment_last_component_id": (self._mover_reassignment_last_component_id),
            "mover_reassignment_source_event_ids": list(self._mover_reassignment_source_event_ids),
            "mover_reassignment_action_handles": [
                item.value
                for item in sorted(
                    self._mover_reassignment_action_handles, key=lambda item: item.value
                )
            ],
            "mover_reassignment_displacements": [
                [dx, dy] for dx, dy in sorted(self._mover_reassignment_displacements)
            ],
            "palette_role_registry": self._palette_roles.to_dict(),
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
                "registry": self._action_effects.projection(),
                "epoch_history": {
                    key: value for key, value in sorted(self._action_effect_epoch_history.items())
                },
                "calibration_handles": [item.value for item in self._calibration_handles],
                "calibrated_handles": [
                    item.value
                    for item in self._calibration_handles
                    if item in self._calibrated_handles
                ],
                "calibration_pending_handle": (
                    self._calibration_pending_handle.value
                    if self._calibration_pending_handle is not None
                    else None
                ),
                "pending_canonical_effect": (
                    self._pending_canonical_effect.projection()
                    if self._pending_canonical_effect is not None
                    else None
                ),
                "pending_resolution_kind": self._pending_resolution_kind,
                "interface_semantics_emitted_levels": cast(
                    list[JSONValue], sorted(self._interface_semantics_emitted_levels)
                ),
                "recent_frame_hashes": [str(item) for item in self._recent_frame_hashes],
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
                "active_model_receipt_event_ids": cast(
                    dict[str, JSONValue], self._active_model_receipt_event_ids()
                ),
                "preserved_transitions": [
                    self._serialize_transition(item) for item in self._transitions
                ],
                "retrodiction_state": self._retrodiction_runtime.to_dict(),
                "retrodiction_pending_force_full_source_event_ids": list(
                    self._retrodiction_force_full_source_event_ids
                ),
                "mechanics_lifecycle": self._mechanics.to_dict(),
                "suspended_model_ids": cast(list[JSONValue], sorted(self._suspended_model_ids)),
                "demoted_model_ids": cast(list[JSONValue], sorted(self._demoted_model_ids)),
                "invalidated_plan_ids": cast(list[JSONValue], sorted(self._invalidated_plan_ids)),
                "resolved_noise_transition_ids": cast(
                    list[JSONValue], sorted(self._resolved_noise_transition_ids)
                ),
                "provisional_probe_handle": (
                    self._provisional_probe_handle.value
                    if self._provisional_probe_handle is not None
                    else None
                ),
                "reexploration_handle": (
                    self._reexploration_handle.value
                    if self._reexploration_handle is not None
                    else None
                ),
                "reexploration_candidate_id": self._reexploration_candidate_id,
                "pending_change_candidate_id": self._pending_change_candidate_id,
                "pending_reexploration_candidate_id": (self._pending_reexploration_candidate_id),
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
                        **item.to_dict(),
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
                "cadence_config": self._cadence_config.to_dict(),
                "cadence_activation_event_id": self._cadence_activation_event_id,
                "cadence_state": self._cadence_state.to_checkpoint_dict(),
                "cadence_folded_observation_event_id": (self._cadence_folded_observation_event_id),
                "cadence_checkpoint_state_event_id": (self._cadence_checkpoint_state_event_id),
                "prediction_cache": self._prediction_cache.to_dict(),
                "pending_goal_transitions": cast(list[JSONValue], pending_goal_transitions),
                "reasoning_selection": (
                    self._reasoning_selection.to_dict()
                    if self._reasoning_selection is not None
                    else None
                ),
                "reasoning_selected_event_id": self._reasoning_selected_event_id,
                "reasoning_completed_event_id": self._reasoning_completed_event_id,
                "reasoning_force_fallback": self._reasoning_force_fallback,
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
                "pending_prediction_event_id": self._pending_prediction_event_id,
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
        checkpoint = ControllerCheckpoint(path, envelope, self._phase)
        self._last_checkpoint = checkpoint
        return checkpoint

    def _preflight_checkpoint_runtime_identity(self, path: str | Path | None) -> None:
        """Report caller-selected runtime mismatches before strict source binding.

        The full restore still validates the exact current source identity.  A
        read-only hash-validated envelope preflight merely distinguishes an
        intentional cadence, feature, or retrodiction mismatch from unrelated
        source drift so the public controller API raises its documented
        ``PolicyError`` rather than leaking the lower-level commitment error.
        """

        if self._checkpoint_manager is None:
            raise PolicyError("checkpoint manager did not initialize")
        authoritative_path = path
        if authoritative_path is None:
            # ``latest.json`` is a replaceable convenience pointer, not trace
            # authority.  Select the same content-addressed envelope named by
            # the last immutable commitment that the strict restore validates
            # below, so an orphan newer write cannot influence diagnostics.
            commitments = tuple(
                event
                for event in self.journal.verify_manifest()
                if event.episode_id == self.context.episode_id
                and event.event_type == "run.checkpoint_written"
            )
            if not commitments:
                return
            committed_hash = commitments[-1].payload.get("checkpoint_hash")
            if not isinstance(committed_hash, str):
                return
            authoritative_path = self._checkpoint_manager.store.content_addressed_path(
                committed_hash
            )
        envelope = self._checkpoint_manager.store.load(authoritative_path)
        state = DerivedControllerState.from_dict(envelope.state.get("derived_controller_state"))
        checkpoint_features = state.planner_state.get("controller_features")
        if checkpoint_features is not None and checkpoint_features != self.features.to_dict():
            raise PolicyError("checkpoint controller feature identity does not match")
        checkpoint_cadence = state.planner_state.get("cadence_config")
        if checkpoint_cadence is not None:
            try:
                parsed_cadence = CadenceConfig.from_dict(checkpoint_cadence)
            except PolicyError as error:
                raise PolicyError("checkpoint cadence/cache state is malformed") from error
            if parsed_cadence != self._cadence_config:
                raise PolicyError("checkpoint cadence configuration does not match runtime")
        checkpoint_retrodiction = state.world_model_ensemble.get("retrodiction_state")
        if isinstance(checkpoint_retrodiction, Mapping):
            if checkpoint_retrodiction.get("config") != self._retrodiction_runtime.config.to_dict():
                raise PolicyError("checkpoint retrodiction runtime does not match controller")

    @classmethod
    def restore(
        cls,
        context: RunContext,
        *,
        preset: ControllerPreset | str = ControllerPreset.FULL,
        checkpoint_path: str | Path | None = None,
        features: PresetFeatures | None = None,
        hot_path_profiler: _HotPathProfiler | None = None,
        retrodiction_config: RetrodictionConfig | None = None,
        cadence_config: CadenceConfig | None = None,
        legacy_checkpoint_code_identity: CodeIdentity | None = None,
        legacy_checkpoint_source_identity: SourceIdentity | None = None,
    ) -> ARC3Controller:
        """Restore a compatible checkpoint without emitting a pending action again."""

        if (legacy_checkpoint_code_identity is None) != (legacy_checkpoint_source_identity is None):
            raise PolicyError(
                "legacy checkpoint migration requires both exact code and source identities"
            )
        legacy_migration_requested = legacy_checkpoint_code_identity is not None

        controller = cls(
            preset,
            features=features,
            hot_path_profiler=hot_path_profiler,
            retrodiction_config=retrodiction_config,
            cadence_config=cadence_config,
        )
        controller._initialize_context(context)
        if (
            controller._checkpoint_manager is None
            or controller._code is None
            or controller._source is None
        ):
            raise PolicyError("checkpoint manager did not initialize")
        current_code_identity = controller._code
        current_source_identity = controller._source
        if legacy_checkpoint_code_identity is not None and (
            legacy_checkpoint_code_identity.git_commit == current_code_identity.git_commit
            or legacy_checkpoint_code_identity.config_hash != current_code_identity.config_hash
            or legacy_checkpoint_code_identity.details != current_code_identity.details
        ):
            raise PolicyError(
                "legacy checkpoint migration may cross only to a different git commit under "
                "the same configuration identity"
            )
        if not legacy_migration_requested:
            controller._preflight_checkpoint_runtime_identity(checkpoint_path)
        restored = controller._checkpoint_manager.restore(
            journal=controller.journal,
            episode_id=context.episode_id,
            code_identity=(
                legacy_checkpoint_code_identity
                if legacy_checkpoint_code_identity is not None
                else current_code_identity
            ),
            source_identity=(
                legacy_checkpoint_source_identity
                if legacy_checkpoint_source_identity is not None
                else current_source_identity
            ),
            path=checkpoint_path,
            defer_payload_commitment=True,
        )
        controller._abandoned_trace_event_ids = controller._validated_abandoned_trace_event_ids(
            restored.abandoned_suffix_events
        )
        state = restored.state
        checkpoint_has_cadence = "cadence_config" in state.planner_state
        if legacy_migration_requested and checkpoint_has_cadence:
            raise PolicyError(
                "explicit legacy checkpoint migration is restricted to cadence-less checkpoints"
            )
        if not legacy_migration_requested and not checkpoint_has_cadence:
            raise PolicyError(
                "cadence-less checkpoint restore requires explicit legacy code and source identities"
            )
        controller._rng = restored.rng
        controller._step_index = state.step_index
        controller._level_index = state.level_index
        controller._memory = state.memory
        controller._pending_action = state.pending_action
        controller._restore_action_counts(state.action_semantics)
        controller._hypotheses = HypothesisRegistry.from_dict(
            cast(Mapping[str, object], state.hypothesis_registry)
        )
        raw_controller_features = state.planner_state.get("controller_features")
        if (
            raw_controller_features is not None
            and raw_controller_features != controller.features.to_dict()
        ):
            raise PolicyError("checkpoint controller feature identity does not match")
        controller._provisional_mover_id = cast(
            str | None, state.perception_state.get("provisional_mover_id")
        )
        raw_reassignment_candidate = state.perception_state.get("mover_reassignment_candidate_id")
        if raw_reassignment_candidate is not None and not isinstance(
            raw_reassignment_candidate, str
        ):
            raise PolicyError("checkpoint mover reassignment candidate is malformed")
        raw_reassignment_sources = state.perception_state.get(
            "mover_reassignment_source_event_ids", []
        )
        if not isinstance(raw_reassignment_sources, list) or any(
            not isinstance(item, str) for item in raw_reassignment_sources
        ):
            raise PolicyError("checkpoint mover reassignment evidence is malformed")
        if len(raw_reassignment_sources) > 2:
            raise PolicyError("checkpoint mover reassignment evidence exceeds its bound")
        controller._mover_reassignment_candidate_id = raw_reassignment_candidate
        raw_reassignment_component = state.perception_state.get(
            "mover_reassignment_last_component_id"
        )
        if raw_reassignment_component is not None and not isinstance(
            raw_reassignment_component, str
        ):
            raise PolicyError("checkpoint mover reassignment component is malformed")
        controller._mover_reassignment_last_component_id = raw_reassignment_component
        controller._mover_reassignment_source_event_ids = cast(
            list[str], list(raw_reassignment_sources)
        )
        raw_reassignment_handles = state.perception_state.get(
            "mover_reassignment_action_handles", []
        )
        if not isinstance(raw_reassignment_handles, list) or not all(
            isinstance(item, str) for item in raw_reassignment_handles
        ):
            raise PolicyError("checkpoint mover reassignment handles are malformed")
        try:
            controller._mover_reassignment_action_handles = {
                ActionName(item) for item in cast(list[str], raw_reassignment_handles)
            }
        except ValueError as error:
            raise PolicyError("checkpoint mover reassignment handle is unsupported") from error
        if ActionName.RESET in controller._mover_reassignment_action_handles:
            raise PolicyError("checkpoint mover reassignment cannot use RESET")
        raw_reassignment_displacements = state.perception_state.get(
            "mover_reassignment_displacements", []
        )
        if not isinstance(raw_reassignment_displacements, list):
            raise PolicyError("checkpoint mover reassignment displacements are malformed")
        parsed_displacements: set[tuple[int, int]] = set()
        for displacement in raw_reassignment_displacements:
            if (
                not isinstance(displacement, list)
                or len(displacement) != 2
                or any(isinstance(item, bool) or not isinstance(item, int) for item in displacement)
            ):
                raise PolicyError("checkpoint mover reassignment displacement is malformed")
            parsed_displacements.add((cast(int, displacement[0]), cast(int, displacement[1])))
        if len(parsed_displacements) > len(ActionName):
            raise PolicyError("checkpoint mover reassignment displacement bound exceeded")
        controller._mover_reassignment_displacements = parsed_displacements
        if (
            len(
                {
                    bool(raw_reassignment_candidate),
                    bool(raw_reassignment_component),
                    bool(raw_reassignment_sources),
                }
            )
            != 1
        ):
            raise PolicyError("checkpoint mover reassignment candidate/evidence disagree")
        if not raw_reassignment_candidate and (
            controller._mover_reassignment_action_handles
            or controller._mover_reassignment_displacements
        ):
            raise PolicyError("checkpoint mover reassignment diversity lacks a candidate")
        raw_palette_roles = state.perception_state.get("palette_role_registry")
        try:
            controller._palette_roles = (
                PaletteRoleRegistry.from_dict(raw_palette_roles)
                if raw_palette_roles is not None
                else PaletteRoleRegistry(level_index=state.level_index)
            )
        except ARC3ValidationError as error:
            raise PolicyError("checkpoint palette role registry is malformed") from error
        if controller._palette_roles.level_index != state.level_index:
            raise PolicyError("checkpoint palette role level does not match controller state")
        raw_observation = state.perception_state.get("latest_observation")
        if raw_observation is not None:
            controller._latest_observation = controller._deserialize_observation(raw_observation)
            controller._before_action_observation = controller._latest_observation
            frame = controller._latest_observation.frames[-1]
            background = Counter(cell for row in frame.cells for cell in row).most_common(1)[0][0]
            controller._palette_roles.observe(frame, background_colors=(background,))
            components = extract_components(
                frame, config=ComponentConfig(background_candidates=(background,))
            )
            symbolic, mapping = _symbolic_state(frame, components, controller._palette_roles)
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
        controller._validate_restored_evidence_state(state)
        controller._checkpoint_manager.validate_restored_commitment(restored)
        controller._rebuild_compact_trace()
        controller._last_checkpoint = ControllerCheckpoint(
            Path(checkpoint_path)
            if checkpoint_path is not None
            else controller._checkpoint_manager.store.latest_path,
            restored.envelope,
            controller._phase,
        )
        controller._last_sparse_checkpoint_level = controller._level_index
        wrote_recovery_receipt = False
        if restored.abandoned_suffix_events:
            suffix = restored.abandoned_suffix_events
            controller._append(
                context.game_id,
                "reasoning.interruption_reopened",
                {
                    "checkpoint_commitment_event_id": restored.commitment_event.event_id,
                    "abandoned_event_ids": [event.event_id for event in suffix],
                    "abandoned_event_hashes": [event.event_hash for event in suffix],
                    "abandoned_tail_hash": suffix[-1].event_hash,
                    "recovery_policy": (
                        "preserve immutable receipts; remove interrupted derived suffix "
                        "from policy authority; recompute from checkpointed evidence fold"
                    ),
                },
                scope="run",
            )
            wrote_recovery_receipt = True
        if legacy_migration_requested:
            assert legacy_checkpoint_code_identity is not None
            assert legacy_checkpoint_source_identity is not None
            activation = controller._append(
                context.game_id,
                "reasoning.cadence_activated",
                {
                    "cadence_config": controller._cadence_config.to_dict(),
                    "cadence_configuration_hash": (controller._cadence_config.configuration_hash),
                    "source_checkpoint_commitment_event_id": (restored.commitment_event.event_id),
                    "source_checkpoint_hash": restored.envelope.checkpoint_hash,
                    "legacy_checkpoint_source_identity": (
                        legacy_checkpoint_source_identity.to_dict()
                    ),
                    "legacy_checkpoint_code_identity": (legacy_checkpoint_code_identity.to_dict()),
                    "current_activation_source_identity": current_source_identity.to_dict(),
                    "current_activation_code_identity": current_code_identity.to_dict(),
                    "migration_policy": (
                        "validate the cadence-less checkpoint under its explicit legacy "
                        "source/code identity; preserve historical actions as pre-cadence "
                        "evidence; begin typed cadence authority under the current source/code "
                        "identity at this immutable activation receipt"
                    ),
                },
                scope="run",
            )
            controller._cadence_activation_event_id = activation.event_id
            wrote_recovery_receipt = True
        if wrote_recovery_receipt:
            controller._flush_trace()
            if controller.features.use_memory:
                controller._last_checkpoint = controller.checkpoint()
        if hot_path_profiler is not None:
            hot_path_profiler.boundary("restore", actions=controller._actions_used)
        return controller

    def _observation_from_trace_event(self, event: TraceEvent) -> Observation:
        """Rebuild one observation from immutable frame blobs and its raw receipt."""

        if event.event_type != "observation.received":
            raise PolicyError("checkpoint observation source is not an observation receipt")
        raw_frames = event.payload.get("frames")
        raw_actions = event.payload.get("available_actions")
        raw_metadata = event.payload.get("upstream_metadata")
        if (
            not isinstance(raw_frames, list)
            or not raw_frames
            or not all(isinstance(item, Mapping) for item in raw_frames)
            or not isinstance(raw_actions, list)
            or not all(isinstance(item, str) for item in raw_actions)
            or not isinstance(raw_metadata, Mapping)
        ):
            raise PolicyError("immutable observation receipt is malformed")
        frame_descriptors = cast(list[dict[str, JSONValue]], raw_frames)
        action_values = cast(list[str], raw_actions)
        metadata_values = cast(Mapping[str, object], raw_metadata)
        frames: list[GridFrame] = []
        for descriptor in frame_descriptors:
            blob_hash = descriptor.get("blob_hash")
            frame_hash = descriptor.get("frame_hash")
            width = descriptor.get("width")
            height = descriptor.get("height")
            palette = descriptor.get("palette")
            if (
                not isinstance(blob_hash, str)
                or frame_hash != blob_hash
                or isinstance(width, bool)
                or not isinstance(width, int)
                or isinstance(height, bool)
                or not isinstance(height, int)
                or not isinstance(palette, list)
                or any(isinstance(item, bool) or not isinstance(item, int) for item in palette)
            ):
                raise PolicyError("immutable observation frame descriptor is malformed")
            frame = GridFrame(self.journal.blobs.get_frame(blob_hash))
            if frame.width != width or frame.height != height or list(frame.palette) != palette:
                raise PolicyError("immutable observation frame descriptor disagrees with its blob")
            frames.append(frame)
        try:
            state = GameStateName(str(event.payload.get("game_state")))
            available_actions = tuple(ActionName(item) for item in action_values)
        except ValueError as error:
            raise PolicyError("immutable observation enum is malformed") from error
        levels_completed = metadata_values.get("levels_completed")
        win_levels = metadata_values.get("win_levels")
        full_reset = metadata_values.get("full_reset")
        if (
            isinstance(levels_completed, bool)
            or not isinstance(levels_completed, int)
            or isinstance(win_levels, bool)
            or not isinstance(win_levels, int)
            or not isinstance(full_reset, bool)
        ):
            raise PolicyError("immutable observation lifecycle metadata is malformed")
        returned_value = event.payload.get("returned_action")
        upstream_session_id = event.payload.get("upstream_session_id")
        if upstream_session_id is not None and not isinstance(upstream_session_id, str):
            raise PolicyError("immutable observation session identity is malformed")
        returned_action = (
            self._action_from_value(returned_value) if isinstance(returned_value, Mapping) else None
        )
        if returned_value is not None and not isinstance(returned_value, Mapping):
            raise PolicyError("immutable observation returned action is malformed")
        reserved = {"levels_completed", "win_levels", "full_reset"}
        upstream_metadata: list[tuple[str, JSONScalar]] = []
        for key, raw_value in metadata_values.items():
            if not isinstance(key, str) or key in reserved:
                continue
            if not isinstance(raw_value, (str, int, float, bool)) and raw_value is not None:
                raise PolicyError("immutable observation metadata must remain scalar")
            upstream_metadata.append((key, raw_value))
        return Observation(
            game_id=GameId(event.game_id),
            frames=tuple(frames),
            state=state,
            levels_completed=levels_completed,
            win_levels=win_levels,
            available_actions=available_actions,
            full_reset=full_reset,
            returned_action=returned_action,
            upstream_session_id=upstream_session_id,
            upstream_metadata=tuple(upstream_metadata),
        )

    def _replay_symbolic_observations(
        self,
        observation_events: Sequence[TraceEvent],
    ) -> tuple[dict[str, SymbolicState], PaletteRoleRegistry]:
        """Replay level-scoped palette identity before rebuilding each state."""

        registry = PaletteRoleRegistry(level_index=0)
        states: dict[str, SymbolicState] = {}
        try:
            for event in observation_events:
                observation = self._observation_from_trace_event(event)
                frame = observation.frames[-1]
                background = Counter(cell for row in frame.cells for cell in row).most_common(1)[0][
                    0
                ]
                registry.begin_level(observation.levels_completed)
                registry.observe(frame, background_colors=(background,))
                components = extract_components(
                    frame,
                    config=ComponentConfig(background_candidates=(background,)),
                )
                symbolic, _ = _symbolic_state(frame, components, registry)
                states[event.event_id] = symbolic
        except ARC3ValidationError as error:
            raise PolicyError("immutable palette-role replay is malformed") from error
        return states, registry

    def _validate_restored_evidence_state(self, state: DerivedControllerState) -> None:
        """Reject checkpoint authority that cannot be re-derived from the trace."""

        events = self._policy_events()
        self.journal.verify_referenced_blobs()
        event_by_id = {event.event_id: event for event in events}
        event_order = {event.event_id: index for index, event in enumerate(events)}

        def traced_cadence_selection(event: TraceEvent) -> CadenceSelection:
            selection_keys = {
                "configuration_hash",
                "goal_id",
                "goal_revision",
                "mechanics_epoch_id",
                "ordered_triggers",
                "path",
                "plan_id",
                "schema",
                "state_id",
                "trigger_source_event_ids",
                "trigger_sources",
            }
            try:
                selection = CadenceSelection.from_dict(
                    {key: event.payload.get(key) for key in selection_keys}
                )
            except PolicyError as error:
                raise PolicyError("immutable cadence selection payload is malformed") from error
            observation_id = event.payload.get("observation_event_id")
            observation_event = (
                event_by_id.get(observation_id) if isinstance(observation_id, str) else None
            )
            if (
                selection.configuration_hash != self._cadence_config.configuration_hash
                or event.payload.get("cadence_mode") != self._cadence_config.mode.value
                or event.payload.get("budget_limits") != self._reasoning_budget_limits()
                or observation_event is None
                or observation_event.event_type != "observation.received"
                or event_order[observation_event.event_id] >= event_order[event.event_id]
                or any(
                    source_id not in event_order
                    or event_order[source_id] >= event_order[event.event_id]
                    for source_id in selection.trigger_source_event_ids
                )
                or (
                    self._cadence_config.mode.value == "TWO_SPEED"
                    and selection.path is ReasoningPath.DEEP
                    and not selection.ordered_triggers
                )
            ):
                raise PolicyError("immutable cadence selection lacks trace-derived authority")
            return selection

        if "cadence_config" in state.planner_state:
            commitment_id = self._cadence_checkpoint_state_event_id
            commitment = event_by_id.get(commitment_id) if isinstance(commitment_id, str) else None
            cadence_commitments = tuple(
                event for event in events if event.event_type == "reasoning.checkpoint_state"
            )
            expected_commitment_payload: dict[str, object] = {
                "cadence_activation_event_id": self._cadence_activation_event_id,
                "cadence_configuration_hash": (self._cadence_config.configuration_hash),
                "cadence_folded_observation_event_id": (self._cadence_folded_observation_event_id),
                "cadence_state": self._cadence_state.to_checkpoint_dict(),
                "pending_goal_transitions_hash": sha256_json(
                    [
                        self._serialize_goal_transition(item)
                        for item in self._pending_goal_transitions
                    ]
                ),
                "prediction_cache_projection_hash": (self._prediction_cache.projection_hash),
                "prediction_cache_telemetry_hash": sha256_json(self._prediction_cache.to_dict()),
                "pending_submitted_event_id": (
                    self._pending_action.submitted_event_id
                    if self._pending_action is not None
                    else None
                ),
                "reasoning_completed_event_id": (self._reasoning_completed_event_id),
                "reasoning_selected_event_id": self._reasoning_selected_event_id,
                "reasoning_selection": (
                    self._reasoning_selection.to_dict()
                    if self._reasoning_selection is not None
                    else None
                ),
            }
            if (
                commitment is None
                or commitment.event_type != "reasoning.checkpoint_state"
                or not cadence_commitments
                or cadence_commitments[-1].event_id != commitment.event_id
                or commitment.payload != expected_commitment_payload
                or len(events) < 2
                or events[-1].event_type != "run.checkpoint_written"
                or event_order[commitment.event_id] != len(events) - 2
            ):
                raise PolicyError(
                    "checkpoint cadence/cache state disagrees with immutable commitment"
                )
            activation = event_by_id.get(self._cadence_activation_event_id or "")
            if activation is None:
                raise PolicyError("immutable cadence activation receipt is absent")
            if activation.event_type == "run.started":
                if (
                    activation.payload.get("cadence_config") != self._cadence_config.to_dict()
                    or activation.payload.get("cadence_configuration_hash")
                    != self._cadence_config.configuration_hash
                ):
                    raise PolicyError("immutable run cadence configuration is malformed")
            elif activation.event_type == "reasoning.cadence_activated":
                source_commitment_id = activation.payload.get(
                    "source_checkpoint_commitment_event_id"
                )
                source_commitment = (
                    event_by_id.get(source_commitment_id)
                    if isinstance(source_commitment_id, str)
                    else None
                )
                if (
                    activation.payload.get("cadence_config") != self._cadence_config.to_dict()
                    or activation.payload.get("cadence_configuration_hash")
                    != self._cadence_config.configuration_hash
                    or source_commitment is None
                    or source_commitment.event_type != "run.checkpoint_written"
                    or event_order[source_commitment.event_id] >= event_order[activation.event_id]
                    or activation.payload.get("source_checkpoint_hash")
                    != source_commitment.payload.get("checkpoint_hash")
                    or activation.payload.get("legacy_checkpoint_source_identity")
                    != source_commitment.source.to_dict()
                    or activation.payload.get("legacy_checkpoint_code_identity")
                    != source_commitment.code_identity.to_dict()
                    or activation.payload.get("current_activation_source_identity")
                    != activation.source.to_dict()
                    or activation.payload.get("current_activation_code_identity")
                    != activation.code_identity.to_dict()
                ):
                    raise PolicyError("immutable migrated cadence activation is malformed")
            else:
                raise PolicyError("immutable cadence activation event type is invalid")
            for action_event in (
                event
                for event in events
                if event.event_type == "action.selected"
                and event_order[event.event_id] > event_order[activation.event_id]
            ):
                terminal_id = action_event.payload.get("reasoning_completed_event_id")
                terminal = event_by_id.get(terminal_id) if isinstance(terminal_id, str) else None
                selected_path_id = (
                    terminal.payload.get("path_selected_event_id") if terminal is not None else None
                )
                selected_path = (
                    event_by_id.get(selected_path_id) if isinstance(selected_path_id, str) else None
                )
                traced_selection = (
                    traced_cadence_selection(selected_path) if selected_path is not None else None
                )
                if (
                    terminal is None
                    or terminal.event_type
                    not in {
                        "reasoning.deliberation_completed",
                        "reasoning.fallback_used",
                    }
                    or selected_path is None
                    or selected_path.event_type != "reasoning.path_selected"
                    or not (
                        event_order[selected_path.event_id]
                        < event_order[terminal.event_id]
                        < event_order[action_event.event_id]
                    )
                    or selected_path.payload.get("observation_event_id")
                    != action_event.payload.get("source_observation_event_id")
                    or terminal.payload.get("path") != selected_path.payload.get("path")
                    or traced_selection is None
                ):
                    raise PolicyError(
                        "immutable action selection lacks its completed reasoning chain"
                    )
            if self._reasoning_selection is not None:
                selected_path = event_by_id.get(self._reasoning_selected_event_id or "")
                terminal = event_by_id.get(self._reasoning_completed_event_id or "")
                traced_selection = (
                    traced_cadence_selection(selected_path) if selected_path is not None else None
                )
                if (
                    selected_path is None
                    or selected_path.event_type != "reasoning.path_selected"
                    or terminal is None
                    or terminal.event_type
                    not in {
                        "reasoning.deliberation_completed",
                        "reasoning.fallback_used",
                    }
                    or terminal.payload.get("path_selected_event_id") != selected_path.event_id
                    or terminal.payload.get("path") != self._reasoning_selection.path.value
                    or traced_selection != self._reasoning_selection
                    or selected_path.payload.get("action_registry_identity")
                    != self._action_registry_identity()
                ):
                    raise PolicyError("checkpoint current reasoning receipt chain is invalid")
        observation_events = tuple(
            event
            for event in events
            if event.event_type == "observation.received"
            and event.episode_id == self.context.episode_id
        )
        replayed_states, replayed_palette_roles = self._replay_symbolic_observations(
            observation_events
        )
        replayed_observations = {
            event.event_id: self._observation_from_trace_event(event)
            for event in observation_events
        }
        latest_event_id = state.perception_state.get("latest_observation_event_id")
        if self._latest_observation is None:
            if latest_event_id is not None or observation_events:
                raise PolicyError("checkpoint latest observation authority is inconsistent")
            if state.normalized_state_hash != sha256_json({"controller": "unobserved"}):
                raise PolicyError("checkpoint unobserved state hash is inconsistent")
            return
        if (
            not isinstance(latest_event_id, str)
            or not observation_events
            or latest_event_id != observation_events[-1].event_id
        ):
            raise PolicyError("checkpoint latest observation is not the trace tail observation")
        traced_latest = self._observation_from_trace_event(observation_events[-1])
        latest = self._latest_observation
        if (
            latest.game_id != traced_latest.game_id
            or latest.frames != traced_latest.frames
            or latest.state is not traced_latest.state
            or latest.levels_completed != traced_latest.levels_completed
            or latest.win_levels != traced_latest.win_levels
            or latest.available_actions != traced_latest.available_actions
            or latest.full_reset is not traced_latest.full_reset
            or latest.returned_action != traced_latest.returned_action
            or latest.upstream_session_id != traced_latest.upstream_session_id
            or _metadata(latest) != _metadata(traced_latest)
        ):
            raise PolicyError("checkpoint latest observation disagrees with immutable receipt")
        if state.normalized_state_hash != str(latest.frames[-1].digest):
            raise PolicyError("checkpoint normalized state hash disagrees with latest frame")
        latest_trace = observation_events[-1]
        if (
            latest_trace.level_index != state.level_index
            or latest_trace.step_index != state.step_index
            or latest.levels_completed != state.level_index
        ):
            raise PolicyError("checkpoint observation level/step boundary is inconsistent")
        normalized_events = tuple(
            event
            for event in events[event_order[latest_event_id] + 1 :]
            if event.event_type == "observation.normalized"
            and event.payload.get("source_observation_event_id") == latest_event_id
        )
        if len(normalized_events) != 1 or normalized_events[0].payload.get("frame_hash") != str(
            latest.frames[-1].digest
        ):
            raise PolicyError("checkpoint latest normalized observation is not trace-derived")

        measurement_types = {
            "observation.normalized",
            "observation.delta_measured",
            "perception.components_detected",
            "perception.object_correspondence_proposed",
        }
        measurement_ids = tuple(
            event.event_id
            for event in events[event_order[latest_event_id] + 1 :]
            if event.step_index == latest_trace.step_index
            and event.episode_id == self.context.episode_id
            and event.event_type in measurement_types
        )
        current_view = self._latest_view
        if current_view is None:
            raise PolicyError("checkpoint latest perception view is absent")
        if (
            replayed_palette_roles.to_dict() != self._palette_roles.to_dict()
            or replayed_states.get(latest_event_id) != current_view.symbolic_state
        ):
            raise PolicyError("checkpoint palette or symbolic-state authority is not trace-derived")
        delta: FrameDelta | None = None
        tracking: TrackingResult | None = None
        if len(observation_events) >= 2:
            previous = self._observation_from_trace_event(observation_events[-2])
            prior_frame = previous.frames[-1]
            current_frame = latest.frames[-1]
            prior_background = Counter(
                cell for row in prior_frame.cells for cell in row
            ).most_common(1)[0][0]
            current_background = Counter(
                cell for row in current_frame.cells for cell in row
            ).most_common(1)[0][0]
            prior_components = extract_components(
                prior_frame,
                config=ComponentConfig(background_candidates=(prior_background,)),
            )
            delta = measure_delta(
                prior_frame,
                current_frame,
                before_metadata=_metadata(previous),
                after_metadata=_metadata(latest),
                background_colors=frozenset({prior_background, current_background}),
            )
            if self.features.use_object_tracking:
                tracking = track_components(
                    prior_components,
                    current_view.components,
                    frame_extent=(
                        max(prior_frame.width, current_frame.width),
                        max(prior_frame.height, current_frame.height),
                    ),
                )
        self._latest_view = _PerceptionView(
            current_view.components,
            current_view.symbolic_state,
            delta,
            tracking,
            measurement_ids,
        )
        source_event = event_by_id[latest_event_id]
        self._latest_receipt = ObservationReceipt(
            source_event.event_id,
            source_event.event_hash,
            tuple(str(frame.digest) for frame in latest.frames),
            measurement_ids,
        )

        for transition in self._transitions:
            if len(transition.source_event_ids) != 4:
                raise PolicyError("checkpoint transition source quartet is incomplete")
            selected_id, submitted_id, consequence_id, after_observation_id = (
                transition.source_event_ids
            )
            try:
                selected = event_by_id[selected_id]
                submitted = event_by_id[submitted_id]
                consequence = event_by_id[consequence_id]
                after_observation = event_by_id[after_observation_id]
            except KeyError as error:
                raise PolicyError("checkpoint transition source is absent from trace") from error
            if (
                selected.event_type != "action.selected"
                or submitted.event_type != "action.submitted"
                or consequence.event_type != "consequence.received"
                or after_observation.event_type != "observation.received"
                or not (
                    event_order[selected_id]
                    < event_order[submitted_id]
                    < event_order[consequence_id]
                    < event_order[after_observation_id]
                )
                or transition.transition_id != f"transition:{submitted_id}"
                or events[event_order[consequence_id] + 1].event_id != after_observation_id
                or selected.episode_id != self.context.episode_id
                or submitted.episode_id != self.context.episode_id
                or consequence.episode_id != self.context.episode_id
                or after_observation.episode_id != self.context.episode_id
                or selected.game_id != self.context.game_id
                or submitted.game_id != self.context.game_id
                or consequence.game_id != self.context.game_id
                or after_observation.game_id != self.context.game_id
                or selected.step_index != submitted.step_index
                or submitted.step_index != consequence.step_index
                or after_observation.step_index != consequence.step_index + 1
                or selected.level_index != submitted.level_index
                or submitted.level_index != consequence.level_index
                or self._transition_levels.get(transition.transition_id) != selected.level_index
            ):
                raise PolicyError("checkpoint transition source order/type is inconsistent")
            before_observation_id = selected.payload.get("source_observation_event_id")
            before_observation = (
                event_by_id.get(before_observation_id)
                if isinstance(before_observation_id, str)
                else None
            )
            expected_action = _action_payload(transition.action)
            if (
                before_observation is None
                or before_observation.event_type != "observation.received"
                or selected.payload.get("selected_action") != expected_action
                or submitted.payload.get("action") != expected_action
                or consequence.payload.get("action") != expected_action
                or consequence.payload.get("selected_event_id") != selected_id
                or consequence.payload.get("submitted_event_id") != submitted_id
                or consequence.payload.get("returned_frames")
                != after_observation.payload.get("frames")
                or (
                    after_observation.payload.get("returned_action") is not None
                    and after_observation.payload.get("returned_action") != expected_action
                )
            ):
                raise PolicyError("checkpoint transition action/source linkage is inconsistent")
            if transition.before != replayed_states.get(
                before_observation.event_id
            ) or transition.after != replayed_states.get(after_observation.event_id):
                raise PolicyError("checkpoint transition states disagree with frame receipts")

        transition_by_id = {item.transition_id: item for item in self._transitions}
        lifecycle_epochs = tuple(
            item
            for item in cast(list[object], self._mechanics.to_dict().get("epochs", []))
            if isinstance(item, dict)
        )
        child_boundary_ids = {
            cast(str, item["start_transition_id"])
            for item in lifecycle_epochs
            if isinstance(item.get("start_transition_id"), str)
        }
        current_epoch_id = self._mechanics.active_epoch(self._level_index).epoch_id
        replayed_epoch_registries: dict[str, dict[str, JSONValue]] = {}
        replayed_current_hashes: tuple[FrameHash, ...] = ()
        replayed_current_calibration: tuple[ActionName, ...] = ()
        replayed_current_calibrated: set[ActionName] = set()
        for epoch_payload in lifecycle_epochs:
            epoch_id = cast(str, epoch_payload["epoch_id"])
            level_index = cast(int, epoch_payload["level_index"])
            epoch_transitions = tuple(
                sorted(
                    (
                        transition
                        for transition in self._transitions
                        if self._transition_epochs.get(transition.transition_id) == epoch_id
                    ),
                    key=lambda transition: event_order[transition.source_event_ids[0]],
                )
            )
            start_transition_id = epoch_payload.get("start_transition_id")
            if isinstance(start_transition_id, str):
                start_transition = transition_by_id.get(start_transition_id)
                start_observation_id = (
                    start_transition.source_event_ids[-1] if start_transition is not None else None
                )
            else:
                start_observation_id = next(
                    (
                        event.event_id
                        for event in observation_events
                        if replayed_observations[event.event_id].levels_completed == level_index
                    ),
                    None,
                )
            if not isinstance(start_observation_id, str):
                raise PolicyError("checkpoint action registry epoch lacks a start observation")
            start_observation = replayed_observations[start_observation_id]
            registry = ActionEffectRegistry(level_index=level_index)
            registry.register_handles(start_observation.available_actions)
            calibration = (
                tuple(
                    action
                    for action in ActionName
                    if action is not ActionName.RESET
                    and action in start_observation.available_actions
                    and (
                        self._interface_semantics is None
                        or action in self._interface_semantics.evidence_driven_actions
                    )
                )
                if start_observation.state
                not in {GameStateName.NOT_PLAYED, GameStateName.GAME_OVER, GameStateName.WIN}
                else ()
            )
            calibrated: set[ActionName] = set()
            recent_hashes = [start_observation.frames[-1].digest]
            for transition in epoch_transitions:
                selected = event_by_id[transition.source_event_ids[0]]
                consequence_id = transition.source_event_ids[2]
                before_id = selected.payload.get("source_observation_event_id")
                after_id = transition.source_event_ids[-1]
                if not isinstance(before_id, str):
                    raise PolicyError("checkpoint action-effect source observation is malformed")
                replayed_before_observation = replayed_observations[before_id]
                replayed_after_observation = replayed_observations[after_id]
                registry.register_handles(replayed_before_observation.available_actions)
                effect_observation = registry.observe_transition(
                    replayed_before_observation,
                    transition.action,
                    replayed_after_observation,
                    source_event_id=consequence_id,
                    prior_frame_hashes=recent_hashes,
                )
                effect_events = tuple(
                    event
                    for event in events
                    if event.event_type == "action.effect_observed"
                    and event.payload.get("source_consequence_event_id") == consequence_id
                )
                if (
                    len(effect_events) != 1
                    or effect_events[0].payload.get("raw_handle") != transition.action.name.value
                    or effect_events[0].payload.get("canonical_effects")
                    != [item.projection() for item in effect_observation.canonical_effects]
                    or effect_events[0].payload.get("candidates")
                    != [
                        item.projection()
                        for item in registry.candidates_for(transition.action.name)
                    ]
                    or effect_events[0].payload.get("candidate_count") != registry.candidate_count
                ):
                    raise PolicyError("checkpoint action-effect registry disagrees with receipts")
                if selected.payload.get("rationale_summary") == (
                    "frozen one-receipt opaque-handle calibration"
                ):
                    calibrated.add(transition.action.name)
                recent_hashes.append(replayed_after_observation.frames[-1].digest)
                del recent_hashes[:-32]
                if (
                    transition.transition_id not in child_boundary_ids
                    and replayed_after_observation.levels_completed == level_index
                ):
                    registry.register_handles(replayed_after_observation.available_actions)
            replayed_epoch_registries[epoch_id] = registry.projection()
            if epoch_id == current_epoch_id:
                replayed_current_hashes = tuple(recent_hashes)
                replayed_current_calibration = calibration
                replayed_current_calibrated = calibrated

        expected_archived_registries = {
            epoch_id: projection
            for epoch_id, projection in replayed_epoch_registries.items()
            if epoch_id != current_epoch_id
        }
        action_semantics_mismatches = tuple(
            label
            for label, differs in (
                (
                    "active-registry",
                    replayed_epoch_registries.get(current_epoch_id)
                    != self._action_effects.projection(),
                ),
                (
                    "archived-registries",
                    self._action_effect_epoch_history != expected_archived_registries,
                ),
                (
                    "recent-frame-hashes",
                    tuple(self._recent_frame_hashes) != replayed_current_hashes,
                ),
                ("calibration-handles", self._calibration_handles != replayed_current_calibration),
                ("calibrated-handles", self._calibrated_handles != replayed_current_calibrated),
            )
            if differs
        )
        if action_semantics_mismatches:
            raise PolicyError(
                "checkpoint action semantics/calibration are not trace-derived: "
                + ", ".join(action_semantics_mismatches)
            )

        semantics_events = tuple(
            event for event in events if event.event_type == "interface.semantics_granted"
        )
        if self._interface_semantics is None:
            if semantics_events or self._interface_semantics_emitted_levels:
                raise PolicyError("research checkpoint contains competition interface grants")
        else:
            expected_semantics = self._interface_semantics.to_dict()
            observed_levels: set[int] = set()
            for event in semantics_events:
                prior_observations = tuple(
                    observation_event
                    for observation_event in observation_events
                    if observation_event.level_index == event.level_index
                    and event_order[observation_event.event_id] < event_order[event.event_id]
                )
                if not prior_observations or event.level_index in observed_levels:
                    raise PolicyError(
                        "competition interface grant is duplicated or lacks its observation"
                    )
                advertised = set(
                    replayed_observations[prior_observations[-1].event_id].available_actions
                )
                expected_payload: dict[str, object] = {
                    "granted_available_actions": [
                        item.value
                        for item in ActionName
                        if item in advertised and self._interface_semantics.is_granted(item)
                    ],
                    "semantics": expected_semantics,
                    "variable_available_actions": [
                        item.value
                        for item in self._interface_semantics.evidence_driven_actions
                        if item in advertised
                    ],
                }
                if event.payload != expected_payload:
                    raise PolicyError("competition interface grant disagrees with its source")
                observed_levels.add(event.level_index)
            if observed_levels != self._interface_semantics_emitted_levels:
                raise PolicyError("checkpoint interface grant levels are not trace-derived")

        pending_action = self._pending_action
        pending_selected = (
            event_by_id.get(pending_action.selected_event_id)
            if pending_action is not None
            else None
        )
        expected_pending_handle = (
            pending_action.action.name
            if pending_selected is not None
            and pending_action is not None
            and pending_selected.payload.get("rationale_summary")
            == "frozen one-receipt opaque-handle calibration"
            else None
        )
        expected_pending_effect = (
            pending_selected.payload.get("selected_canonical_effect")
            if pending_selected is not None
            else None
        )
        expected_pending_resolution = (
            pending_selected.payload.get("raw_resolution_kind")
            if pending_selected is not None
            else None
        )
        if (
            self._calibration_pending_handle is not expected_pending_handle
            or (
                self._pending_canonical_effect.projection()
                if self._pending_canonical_effect is not None
                else None
            )
            != expected_pending_effect
            or self._pending_resolution_kind != expected_pending_resolution
        ):
            raise PolicyError("checkpoint pending action semantics disagree with selection receipt")

        goal_event_types = {
            "goal.candidate_created",
            "goal.supported",
            "goal.contradicted",
            "goal.selected_for_planning",
            "goal.reopened",
            "goal.retired",
        }
        traced_goal_events = tuple(
            event for event in events if event.event_type in goal_event_types
        )
        raw_goal_event_count = state.goal_registry.get("lifecycle_event_count")
        if raw_goal_event_count != len(traced_goal_events):
            raise PolicyError("checkpoint goal lifecycle count disagrees with immutable trace")
        last_goal_records: dict[str, dict[str, JSONValue]] = {}
        created_goal_order: dict[str, int] = {}
        for sequence, trace_event in enumerate(traced_goal_events):
            goal_id = trace_event.payload.get("goal_id")
            goal_event_id = trace_event.payload.get("goal_event_id")
            raw_sources = trace_event.payload.get("source_event_ids")
            raw_record = trace_event.payload.get("record")
            if (
                not isinstance(goal_id, str)
                or goal_event_id != f"goal-event-{sequence:08d}"
                or trace_event.payload.get("sequence") != sequence
                or not isinstance(raw_sources, list)
                or not all(isinstance(item, str) for item in raw_sources)
                or not isinstance(raw_record, dict)
            ):
                raise PolicyError("immutable goal lifecycle receipt is malformed")
            goal_source_ids = cast(list[str], raw_sources)
            if any(
                source_id not in event_order
                or event_order[source_id] >= event_order[trace_event.event_id]
                for source_id in goal_source_ids
            ):
                raise PolicyError("immutable goal evidence is absent or not source-ordered")
            record_projection = raw_record
            raw_candidate = record_projection.get("candidate")
            raw_evidence = record_projection.get("evidence")
            if (
                record_projection.get("goal_id") != goal_id
                or record_projection.get("status") != trace_event.payload.get("new_status")
                or record_projection.get("rank") != trace_event.payload.get("rank_after")
                or not isinstance(raw_candidate, dict)
                or raw_candidate.get("goal_id") != goal_id
                or not isinstance(raw_evidence, list)
                or not all(isinstance(item, dict) for item in raw_evidence)
            ):
                raise PolicyError("immutable goal record projection is malformed")
            evidence_projection = cast(list[dict[str, JSONValue]], raw_evidence)
            previous_projection = last_goal_records.get(goal_id)
            previous_evidence = (
                cast(list[dict[str, JSONValue]], previous_projection["evidence"])
                if previous_projection is not None
                else []
            )
            if trace_event.event_type == "goal.candidate_created":
                if (
                    previous_projection is not None
                    or trace_event.payload.get("previous_status") is not None
                ):
                    raise PolicyError("immutable goal candidate creation is duplicated")
                candidate_sources = raw_candidate.get("source_evidence")
                if candidate_sources != evidence_projection:
                    raise PolicyError("immutable goal candidate evidence disagrees at creation")
                created_goal_order[goal_id] = event_order[trace_event.event_id]
            else:
                if (
                    previous_projection is None
                    or trace_event.payload.get("previous_status")
                    != previous_projection.get("status")
                    or raw_candidate != previous_projection.get("candidate")
                    or evidence_projection[: len(previous_evidence)] != previous_evidence
                ):
                    raise PolicyError("immutable goal lifecycle does not preserve prior history")
                evidence_delta = evidence_projection[len(previous_evidence) :]
                allowed_delta = (
                    {1}
                    if trace_event.event_type
                    in {"goal.supported", "goal.contradicted", "goal.reopened"}
                    else {0, 1}
                    if trace_event.event_type == "goal.retired"
                    else {0}
                )
                if len(evidence_delta) not in allowed_delta:
                    raise PolicyError(
                        "immutable goal evidence delta disagrees with lifecycle event"
                    )
                if evidence_delta:
                    new_evidence = evidence_delta[0]
                    expected_direction = (
                        EvidenceDirection.CONTRADICTION.value
                        if trace_event.event_type in {"goal.contradicted", "goal.retired"}
                        else EvidenceDirection.SUPPORT.value
                    )
                    if (
                        new_evidence.get("direction") != expected_direction
                        or new_evidence.get("source_event_ids") != goal_source_ids
                        or new_evidence.get("summary") != trace_event.payload.get("summary")
                        or new_evidence.get("observed_step") != trace_event.step_index
                    ):
                        raise PolicyError("immutable goal evidence payload disagrees with event")
                elif trace_event.event_type == "goal.selected_for_planning" and (
                    record_projection != previous_projection
                ):
                    raise PolicyError("goal selection receipt rewrites goal authority")
            last_goal_records[goal_id] = record_projection

        current_goal_records = {
            record.candidate.goal_id: record.to_dict() for record in self._goals.records()
        }
        raw_goal_records = state.goal_registry.get("records")
        if not isinstance(raw_goal_records, list) or not all(
            isinstance(item, dict) for item in raw_goal_records
        ):
            raise PolicyError("checkpoint goal records are malformed")
        checkpoint_goal_records: dict[str, dict[str, JSONValue]] = {}
        for raw_record_item in cast(list[dict[str, JSONValue]], raw_goal_records):
            raw_goal_id = raw_record_item.get("goal_id")
            if not isinstance(raw_goal_id, str) or raw_goal_id in checkpoint_goal_records:
                raise PolicyError("checkpoint goal record identity is malformed")
            checkpoint_goal_records[raw_goal_id] = {
                key: value for key, value in raw_record_item.items() if key != "retirement"
            }
        if (
            checkpoint_goal_records != current_goal_records
            or last_goal_records != current_goal_records
        ):
            raise PolicyError("checkpoint goal candidate/evidence authority disagrees with trace")

        replayed_goal_targets: dict[str, tuple[str, str]] = {}
        replayed_active_goal_id: str | None = None
        for trace_event in events:
            if trace_event.event_type == "goal.target_bound":
                goal_id = trace_event.payload.get("goal_id")
                mover_id = trace_event.payload.get("mover_entity_id")
                target_id = trace_event.payload.get("target_entity_id")
                source_observation_id = trace_event.payload.get("source_observation_event_id")
                source_consequence_id = trace_event.payload.get("source_consequence_event_id")
                if (
                    not isinstance(goal_id, str)
                    or not isinstance(mover_id, str)
                    or not isinstance(target_id, str)
                    or not isinstance(source_observation_id, str)
                    or goal_id not in created_goal_order
                    or source_observation_id not in replayed_states
                ):
                    raise PolicyError("immutable goal target binding is malformed")
                source_state = replayed_states[source_observation_id]
                mover = source_state.entity(mover_id)
                target = source_state.entity(target_id)
                current_goal_projection = current_goal_records.get(goal_id)
                current_candidate_projection = (
                    current_goal_projection.get("candidate")
                    if current_goal_projection is not None
                    else None
                )
                if not isinstance(current_candidate_projection, dict):
                    raise PolicyError("immutable goal target names an unknown candidate")
                previous_binding = replayed_goal_targets.get(goal_id)
                selected_target = (
                    self._select_contact_target(source_state, mover_id)
                    if mover is not None
                    else None
                )
                source_observation = event_by_id[source_observation_id]
                if (
                    mover is None
                    or target is None
                    or (
                        previous_binding != (mover_id, target_id)
                        and (selected_target is None or selected_target.entity_id != target_id)
                    )
                    or trace_event.payload.get("source_symbolic_state_id") != source_state.state_id
                    or trace_event.payload.get("goal_target_state")
                    != current_candidate_projection.get("target_state")
                    or current_candidate_projection.get("kind") != GoalKind.CONTACT.value
                    or trace_event.payload.get("previous_binding")
                    != (list(previous_binding) if previous_binding is not None else None)
                    or not isinstance(trace_event.payload.get("binding_reason"), str)
                    or trace_event.payload.get("activates_goal") is not True
                    or event_order[trace_event.event_id] <= created_goal_order[goal_id]
                    or event_order[trace_event.event_id] <= event_order[source_observation_id]
                    or trace_event.step_index != source_observation.step_index
                ):
                    raise PolicyError("immutable goal target binding is not receipt-derived")
                if source_consequence_id is not None:
                    source_consequence = (
                        event_by_id.get(source_consequence_id)
                        if isinstance(source_consequence_id, str)
                        else None
                    )
                    if (
                        source_consequence is None
                        or source_consequence.event_type != "consequence.received"
                        or events[event_order[source_consequence.event_id] + 1].event_id
                        != source_observation_id
                    ):
                        raise PolicyError("immutable goal target consequence linkage disagrees")
                replayed_goal_targets[goal_id] = (mover_id, target_id)
                replayed_active_goal_id = goal_id
            elif trace_event.event_type == "goal.retired":
                retired_goal_id = trace_event.payload.get("goal_id")
                if replayed_active_goal_id == retired_goal_id:
                    replayed_active_goal_id = None
            elif trace_event.event_type == "goal.selected_for_planning":
                selected_goal_id = trace_event.payload.get("goal_id")
                if selected_goal_id != replayed_active_goal_id:
                    raise PolicyError("immutable active goal selection is not target-bound")
        if (
            self._goal_targets != replayed_goal_targets
            or self._active_goal_id != replayed_active_goal_id
        ):
            raise PolicyError("checkpoint active goal/target authority disagrees with trace fold")

        replayed_planning_disabled = False
        if not self.features.use_planner_recovery:
            plan_model_ids = {
                cast(str, event.payload["plan_id"]): cast(str, event.payload["model_id"])
                for event in events
                if event.event_type == "simulation.plan_evaluated"
                and event.payload.get("status") == SearchStatus.FOUND.value
                and isinstance(event.payload.get("plan_id"), str)
                and isinstance(event.payload.get("model_id"), str)
            }
            predictions = {
                cast(str, event.payload["receipt_id"]): event
                for event in events
                if event.event_type == "simulation.prediction_emitted"
                and isinstance(event.payload.get("receipt_id"), str)
            }
            for trace_event in events:
                if trace_event.event_type in {
                    "consequence.level_completed",
                    "mechanics.epoch_opened",
                }:
                    replayed_planning_disabled = False
                    continue
                if trace_event.event_type not in {
                    "consequence.matched_prediction",
                    "consequence.mismatched_prediction",
                }:
                    continue
                prediction_receipt_id = trace_event.payload.get("prediction_receipt_id")
                prediction_event = (
                    predictions.get(prediction_receipt_id)
                    if isinstance(prediction_receipt_id, str)
                    else None
                )
                if prediction_event is None:
                    continue
                dependent_plan_ids = prediction_event.payload.get("dependent_plan_ids")
                alternatives = prediction_event.payload.get("alternatives")
                observed_state_id = trace_event.payload.get("observed_state_id")
                if (
                    not isinstance(dependent_plan_ids, list)
                    or not all(isinstance(item, str) for item in dependent_plan_ids)
                    or not dependent_plan_ids
                    or not isinstance(alternatives, list)
                    or not isinstance(observed_state_id, str)
                ):
                    continue
                for plan_id in cast(list[str], dependent_plan_ids):
                    model_id = plan_model_ids.get(plan_id)
                    predicted_state_ids = {
                        cast(str, alternative.get("after_state_id"))
                        for alternative in alternatives
                        if isinstance(alternative, dict)
                        and isinstance(alternative.get("after_state_id"), str)
                        and isinstance(alternative.get("supporting_model_ids"), list)
                        and model_id in cast(list[object], alternative["supporting_model_ids"])
                    }
                    if model_id is None or len(predicted_state_ids) != 1:
                        raise PolicyError(
                            "immutable planner mismatch lacks one plan-model prediction"
                        )
                    if observed_state_id not in predicted_state_ids:
                        replayed_planning_disabled = True
        if self._planning_disabled_after_mismatch is not replayed_planning_disabled:
            raise PolicyError("checkpoint planner-recovery disable flag disagrees with trace fold")

        for hypothesis_event in self._hypotheses.events:
            hypothesis_source_ids = tuple(
                dict.fromkeys(
                    (
                        *hypothesis_event.created_from_event_ids,
                        *hypothesis_event.caused_by_event_ids,
                        *(
                            hypothesis_event.receipt.evidence_event_ids
                            if hypothesis_event.receipt is not None
                            else ()
                        ),
                    )
                )
            )
            if hypothesis_event.occurred_step > state.step_index or any(
                source_id not in event_by_id for source_id in hypothesis_source_ids
            ):
                raise PolicyError("checkpoint hypothesis evidence is absent from trace")
            trace_matches = tuple(
                event
                for event in events
                if event.event_type == hypothesis_event.event_type.value
                and event.payload.get("hypothesis_id") == hypothesis_event.hypothesis_id
                and event.step_index == hypothesis_event.occurred_step
            )
            if len(trace_matches) != 1:
                raise PolicyError("checkpoint hypothesis lifecycle lacks an immutable trace event")
            traced_hypothesis_event = trace_matches[0]
            expected_hypothesis_payload = hypothesis_event.to_trace_payload()
            if any(
                traced_hypothesis_event.payload.get(key) != value
                for key, value in expected_hypothesis_payload.items()
            ):
                raise PolicyError("checkpoint hypothesis payload disagrees with immutable trace")
            matched_order = event_order[traced_hypothesis_event.event_id]
            if any(event_order[source_id] >= matched_order for source_id in hypothesis_source_ids):
                raise PolicyError("checkpoint hypothesis evidence is not source-ordered")

        replayed_dependent_plans: dict[str, set[str]] = {}
        promoted_model_hypotheses: dict[str, tuple[str, ...]] = {}
        for trace_event in events:
            if trace_event.event_type == "model.rule_promoted":
                promoted_model_id = trace_event.payload.get("model_id")
                raw_promoted_hypotheses = trace_event.payload.get("hypothesis_ids")
                if (
                    not isinstance(promoted_model_id, str)
                    or not isinstance(raw_promoted_hypotheses, list)
                    or not all(isinstance(item, str) for item in raw_promoted_hypotheses)
                ):
                    raise PolicyError("immutable model promotion dependency is malformed")
                promoted_hypotheses = tuple(cast(list[str], raw_promoted_hypotheses))
                previous_hypotheses = promoted_model_hypotheses.setdefault(
                    promoted_model_id, promoted_hypotheses
                )
                if previous_hypotheses != promoted_hypotheses:
                    raise PolicyError("one model identity changed hypothesis dependencies")
            elif trace_event.event_type == "simulation.plan_evaluated":
                raw_dependencies = trace_event.payload.get("dependent_hypothesis_ids")
                if not isinstance(raw_dependencies, list) or not all(
                    isinstance(item, str) for item in raw_dependencies
                ):
                    raise PolicyError("immutable plan dependency receipt is malformed")
                dependency_ids = tuple(cast(list[str], raw_dependencies))
                evaluated_plan_id = trace_event.payload.get("plan_id")
                evaluated_model_id = trace_event.payload.get("model_id")
                if dependency_ids:
                    if (
                        trace_event.payload.get("status") != SearchStatus.FOUND.value
                        or not isinstance(evaluated_plan_id, str)
                        or not isinstance(evaluated_model_id, str)
                        or promoted_model_hypotheses.get(evaluated_model_id) != dependency_ids
                    ):
                        raise PolicyError(
                            "immutable plan dependency disagrees with promoted model authority"
                        )
                    for hypothesis_id in dependency_ids:
                        replayed_dependent_plans.setdefault(hypothesis_id, set()).add(
                            evaluated_plan_id
                        )
            elif trace_event.event_type == "hypothesis.reopened":
                reopened_hypothesis_id = trace_event.payload.get("hypothesis_id")
                if isinstance(reopened_hypothesis_id, str):
                    replayed_dependent_plans.pop(reopened_hypothesis_id, None)
        current_dependent_plans = {
            record.hypothesis_id: set(self._hypotheses.dependent_plan_ids(record.hypothesis_id))
            for record in self._hypotheses.all()
            if self._hypotheses.dependent_plan_ids(record.hypothesis_id)
        }
        if current_dependent_plans != replayed_dependent_plans:
            raise PolicyError("checkpoint dependent-plan authority disagrees with trace fold")

        lifecycle_projection = self._mechanics.to_dict()
        raw_hypothesis_epochs = lifecycle_projection.get("hypothesis_epochs")
        raw_model_epochs = lifecycle_projection.get("model_epochs")
        if not isinstance(raw_hypothesis_epochs, dict) or not isinstance(raw_model_epochs, dict):
            raise PolicyError("checkpoint mechanics authority maps are malformed")
        known_hypothesis_ids = {record.hypothesis_id for record in self._hypotheses.all()}
        if not set(raw_hypothesis_epochs).issubset(known_hypothesis_ids):
            raise PolicyError("checkpoint mechanics authority names an unknown hypothesis")
        replayed_hypothesis_epochs: dict[str, str] = {}
        for record in self._hypotheses.all():
            record_source_ids = set(record.created_from_event_ids)
            source_epochs = {
                self._transition_epochs[transition.transition_id]
                for transition in self._transitions
                if record_source_ids & set(transition.source_event_ids)
            }
            if len(source_epochs) != 1:
                raise PolicyError("checkpoint hypothesis epoch is not source-derived")
            replayed_hypothesis_epochs[record.hypothesis_id] = next(iter(source_epochs))
        if raw_hypothesis_epochs != replayed_hypothesis_epochs:
            raise PolicyError("checkpoint hypothesis epoch map disagrees with trace sources")
        replayed_model_epochs: dict[str, str] = {}
        for event in events:
            if event.event_type != "model.rule_promoted":
                continue
            promoted_model_id = event.payload.get("model_id")
            promoted_epoch_value = event.payload.get("mechanics_epoch_id")
            if not isinstance(promoted_model_id, str) or not isinstance(promoted_epoch_value, str):
                raise PolicyError("immutable model promotion receipt is malformed")
            known_epoch = replayed_model_epochs.setdefault(promoted_model_id, promoted_epoch_value)
            if known_epoch != promoted_epoch_value:
                raise PolicyError("one model identity was promoted across mechanics epochs")
        if raw_model_epochs != replayed_model_epochs:
            raise PolicyError("checkpoint model epoch map disagrees with promotion receipts")
        known_model_ids = set(raw_model_epochs)
        if not (self._suspended_model_ids | self._demoted_model_ids).issubset(known_model_ids):
            raise PolicyError("checkpoint mechanics authority names an unknown model")
        if not self._resolved_noise_transition_ids.issubset(
            {transition.transition_id for transition in self._transitions}
        ):
            raise PolicyError("checkpoint noise exclusion names an unknown transition")
        traced_demoted = {
            model_id
            for event in events
            if event.event_type == "model.rule_demoted"
            for model_id in cast(list[object], event.payload.get("model_ids", []))
            if isinstance(model_id, str)
        }
        if self._demoted_model_ids != traced_demoted:
            raise PolicyError("checkpoint demoted-model authority disagrees with trace")
        traced_suspended: set[str] = set()
        for event in events:
            if event.event_type == "mechanics.change_candidate_created":
                traced_suspended.update(
                    model_id
                    for model_id in cast(list[object], event.payload.get("affected_model_ids", []))
                    if isinstance(model_id, str)
                )
            elif event.event_type == "mechanics.change_candidate_resolved":
                if event.payload.get("resolution") == ("two predecessor-consistent consequences"):
                    traced_suspended.difference_update(
                        model_id
                        for model_id in cast(
                            list[object], event.payload.get("affected_model_ids", [])
                        )
                        if isinstance(model_id, str)
                    )
            elif event.event_type == "model.rule_demoted":
                traced_suspended.difference_update(
                    model_id
                    for model_id in cast(list[object], event.payload.get("model_ids", []))
                    if isinstance(model_id, str)
                )
            elif event.event_type == "consequence.level_completed":
                traced_suspended.clear()
        if self._suspended_model_ids != traced_suspended:
            raise PolicyError("checkpoint suspended-model authority disagrees with trace")
        traced_noise = {
            transition_id
            for event in events
            if event.event_type == "mechanics.change_candidate_resolved"
            and event.payload.get("resolution") == "two predecessor-consistent consequences"
            for transition_id in cast(
                list[object], event.payload.get("retrodiction_excluded_transition_ids", [])
            )
            if isinstance(transition_id, str)
        }
        if self._resolved_noise_transition_ids != traced_noise:
            raise PolicyError("checkpoint noise exclusion authority disagrees with trace")
        for candidate in self._mechanics.candidates():
            contradiction_sources = tuple(
                event_by_id.get(source_id)
                for source_id in candidate.supporting_contradiction_event_ids
            )
            if any(
                source is None or source.event_type != "hypothesis.contradicted"
                for source in contradiction_sources
            ):
                raise PolicyError("checkpoint mechanics candidate evidence is absent from trace")
            created = tuple(
                event
                for event in events
                if event.event_type == "mechanics.change_candidate_created"
                and event.payload.get("candidate_id") == candidate.candidate_id
            )
            if len(created) != 1:
                raise PolicyError("checkpoint mechanics candidate lacks one opening trace event")
            opening = created[0]
            successor_support_events = tuple(
                event
                for event in events
                if event.event_type == "mechanics.successor_evidence_supported"
                and event.payload.get("candidate_id") == candidate.candidate_id
            )
            first_successor_support = (
                successor_support_events[0] if successor_support_events else None
            )
            immutable_candidate_fields = {
                "candidate_id",
                "level_index",
                "predecessor_epoch_id",
                "affected_hypothesis_ids",
                "affected_model_ids",
                "first_contradiction_event_id",
                "opened_step",
                "change_domain",
                "opaque_handle",
                "predecessor_effect_signature",
                "successor_effect_signature",
                "observation_condition_signature",
                "invalidated_plan_ids",
            }
            candidate_projection = candidate.to_dict()
            if (
                any(
                    opening.payload.get(field) != candidate_projection[field]
                    for field in immutable_candidate_fields
                )
                or opening.payload.get("provisional_status")
                != MechanicsChangeStatus.CANDIDATE.value
            ):
                raise PolicyError("checkpoint mechanics candidate opening payload disagrees")
            opening_transition_id = opening.payload.get("source_transition_id")
            if (
                not isinstance(opening_transition_id, str)
                or first_successor_support is None
                or opening_transition_id
                != first_successor_support.payload.get("source_transition_id")
                or opening.payload.get("supporting_contradiction_event_ids")
                != [first_successor_support.payload.get("contradiction_event_id")]
                or opening.payload.get("supporting_successor_transition_ids")
                != [first_successor_support.payload.get("source_transition_id")]
                or opening.payload.get("supporting_discrimination_context_ids")
                != [first_successor_support.payload.get("discrimination_context_id")]
                or self._transition_epochs.get(opening_transition_id)
                != candidate.predecessor_epoch_id
            ):
                raise PolicyError("checkpoint mechanics candidate opening transition disagrees")
            terminal_type = (
                "mechanics.change_confirmed"
                if candidate.provisional_status is MechanicsChangeStatus.CONFIRMED
                else "mechanics.change_candidate_resolved"
                if candidate.provisional_status
                in {
                    MechanicsChangeStatus.RESOLVED_NOISE,
                    MechanicsChangeStatus.CONTRADICTED,
                }
                else None
            )
            terminal_events = tuple(
                event
                for event in events
                if event.event_type
                in {"mechanics.change_confirmed", "mechanics.change_candidate_resolved"}
                and event.payload.get("candidate_id") == candidate.candidate_id
            )
            recovery_events = tuple(
                event
                for event in events
                if event.event_type == "mechanics.predecessor_recovery_supported"
                and event.payload.get("candidate_id") == candidate.candidate_id
            )
            if tuple(event.event_id for event in recovery_events) != (
                candidate.predecessor_recovery_event_ids
            ):
                raise PolicyError(
                    "checkpoint mechanics predecessor recovery disagrees with trace fold"
                )
            if (
                candidate.provisional_status is MechanicsChangeStatus.CANDIDATE
                and len(recovery_events) > 1
            ) or (
                candidate.provisional_status is MechanicsChangeStatus.RESOLVED_NOISE
                and len(recovery_events) != 2
            ):
                raise PolicyError(
                    "checkpoint mechanics predecessor recovery count disagrees with status"
                )
            terminal_order = (
                event_order[terminal_events[0].event_id] if len(terminal_events) == 1 else None
            )
            support_indices = tuple(
                event.payload.get("support_index") for event in successor_support_events
            )
            support_indices_are_integers = all(
                isinstance(value, int) and not isinstance(value, bool) for value in support_indices
            )
            traced_contradiction_ids = tuple(
                event.payload.get("contradiction_event_id") for event in successor_support_events
            )
            traced_successor_transition_ids = tuple(
                event.payload.get("source_transition_id") for event in successor_support_events
            )
            traced_discrimination_context_ids = tuple(
                event.payload.get("discrimination_context_id") for event in successor_support_events
            )
            if (
                len(successor_support_events) != len(candidate.supporting_successor_transition_ids)
                or not support_indices_are_integers
                or support_indices != tuple(range(1, len(successor_support_events) + 1))
                or traced_contradiction_ids != candidate.supporting_contradiction_event_ids
                or traced_successor_transition_ids != candidate.supporting_successor_transition_ids
                or traced_discrimination_context_ids
                != candidate.supporting_discrimination_context_ids
            ):
                raise PolicyError(
                    "checkpoint mechanics successor support disagrees with trace fold"
                )
            for support_index, support_event in enumerate(successor_support_events, start=1):
                source_transition_id = support_event.payload.get("source_transition_id")
                contradiction_event_id = support_event.payload.get("contradiction_event_id")
                successor_transition = (
                    transition_by_id.get(source_transition_id)
                    if isinstance(source_transition_id, str)
                    else None
                )
                contradiction_source = (
                    event_by_id.get(contradiction_event_id)
                    if isinstance(contradiction_event_id, str)
                    else None
                )
                if (
                    not isinstance(source_transition_id, str)
                    or successor_transition is None
                    or contradiction_source is None
                ):
                    raise PolicyError("checkpoint mechanics successor support lacks its sources")
                selected_id, submitted_id, consequence_id, observation_id = (
                    successor_transition.source_event_ids
                )
                controlled_interpretations = tuple(
                    event
                    for event in events
                    if event.event_type == "action.controlled_effect_interpreted"
                    and event.payload.get("source_transition_id") == source_transition_id
                )
                raw_receipt = contradiction_source.payload.get("evidence_receipt")
                evidence_event_ids = (
                    raw_receipt.get("evidence_event_ids") if isinstance(raw_receipt, dict) else None
                )
                if (
                    support_event.payload.get("support_index") != support_index
                    or support_event.payload.get("predecessor_epoch_id")
                    != candidate.predecessor_epoch_id
                    or support_event.payload.get("change_domain") != candidate.change_domain.value
                    or support_event.payload.get("opaque_handle") != candidate.opaque_handle
                    or support_event.payload.get("affected_hypothesis_ids")
                    != list(candidate.affected_hypothesis_ids)
                    or support_event.payload.get("source_action_selected_event_id") != selected_id
                    or support_event.payload.get("source_action_submitted_event_id") != submitted_id
                    or support_event.payload.get("source_consequence_event_id") != consequence_id
                    or support_event.payload.get("source_observation_event_id") != observation_id
                    or support_event.payload.get("raw_action_handle")
                    != successor_transition.action.name.value
                    or support_event.payload.get("action")
                    != _action_payload(successor_transition.action)
                    or support_event.payload.get("observed_effect_signature")
                    != candidate.successor_effect_signature
                    or support_event.payload.get("observation_condition_signature")
                    != candidate.observation_condition_signature
                    or support_event.payload.get("interpretation")
                    != "successor-consistent contradiction consequence"
                    or contradiction_source.event_type != "hypothesis.contradicted"
                    or contradiction_source.payload.get("hypothesis_id")
                    not in candidate.affected_hypothesis_ids
                    or not isinstance(evidence_event_ids, list)
                    or not set(cast(list[object], evidence_event_ids))
                    & set(successor_transition.source_event_ids)
                    or self._transition_epochs.get(source_transition_id)
                    != candidate.predecessor_epoch_id
                    or event_order[support_event.event_id] <= event_order[opening.event_id]
                    or event_order[support_event.event_id] <= event_order[observation_id]
                    or (
                        terminal_order is not None
                        and event_order[support_event.event_id] >= terminal_order
                    )
                    or support_event.episode_id != opening.episode_id
                    or support_event.game_id != opening.game_id
                    or support_event.level_index != candidate.level_index
                    or support_event.step_index != event_by_id[observation_id].step_index
                    or len(controlled_interpretations) != 1
                    or controlled_interpretations[0].payload.get("source_consequence_event_id")
                    != consequence_id
                    or controlled_interpretations[0].payload.get("mechanics_epoch_id")
                    != candidate.predecessor_epoch_id
                    or event_order[controlled_interpretations[0].event_id]
                    >= event_order[support_event.event_id]
                ):
                    raise PolicyError("checkpoint mechanics successor support linkage disagrees")
            for support_index, recovery_event in enumerate(recovery_events, start=1):
                source_transition_id = recovery_event.payload.get("source_transition_id")
                recorded_support_index = recovery_event.payload.get("support_index")
                recovery_transition = (
                    transition_by_id.get(source_transition_id)
                    if isinstance(source_transition_id, str)
                    else None
                )
                if not isinstance(source_transition_id, str) or recovery_transition is None:
                    raise PolicyError(
                        "checkpoint mechanics predecessor recovery lacks its transition"
                    )
                source_consequence_id = recovery_transition.source_event_ids[2]
                source_observation_id = recovery_transition.source_event_ids[3]
                controlled_interpretations = tuple(
                    event
                    for event in events
                    if event.event_type == "action.controlled_effect_interpreted"
                    and event.payload.get("source_transition_id") == source_transition_id
                )
                expected_context = f"opaque-handle:{recovery_transition.action.name.value}"
                recorded_context = recovery_event.payload.get("discrimination_context_id")
                if (
                    self._transition_epochs.get(source_transition_id)
                    != candidate.predecessor_epoch_id
                    or event_order[recovery_transition.source_event_ids[0]]
                    <= event_order[opening.event_id]
                    or event_order[source_observation_id] >= event_order[recovery_event.event_id]
                    or (
                        terminal_order is not None
                        and event_order[recovery_event.event_id] >= terminal_order
                    )
                    or recovery_event.episode_id != opening.episode_id
                    or recovery_event.game_id != opening.game_id
                    or recovery_event.level_index != candidate.level_index
                    or recovery_event.step_index != event_by_id[source_observation_id].step_index
                    or recovery_event.payload.get("candidate_id") != candidate.candidate_id
                    or recovery_event.payload.get("predecessor_epoch_id")
                    != candidate.predecessor_epoch_id
                    or recovery_event.payload.get("source_consequence_event_id")
                    != source_consequence_id
                    or recovery_event.payload.get("source_observation_event_id")
                    != source_observation_id
                    or recovery_event.payload.get("observed_effect_signature")
                    != candidate.predecessor_effect_signature
                    or recovery_event.payload.get("observation_condition_signature")
                    != candidate.observation_condition_signature
                    or recovery_event.payload.get("affected_hypothesis_ids")
                    != list(candidate.affected_hypothesis_ids)
                    or isinstance(recorded_support_index, bool)
                    or not isinstance(recorded_support_index, int)
                    or recorded_support_index != support_index
                    or recovery_event.payload.get("interpretation")
                    != "predecessor-consistent consequence"
                    or not isinstance(recorded_context, str)
                    or not recorded_context
                    or (
                        candidate.change_domain
                        in {
                            MechanicsChangeDomain.ACTION_MAPPING,
                            MechanicsChangeDomain.OPAQUE_HANDLE,
                        }
                        and recorded_context != expected_context
                    )
                    or len(controlled_interpretations) != 1
                    or controlled_interpretations[0].payload.get("source_consequence_event_id")
                    != source_consequence_id
                    or controlled_interpretations[0].payload.get("mechanics_epoch_id")
                    != candidate.predecessor_epoch_id
                    or event_order[controlled_interpretations[0].event_id]
                    >= event_order[recovery_event.event_id]
                ):
                    raise PolicyError("checkpoint mechanics predecessor recovery linkage disagrees")
            tested_steps = [opening.step_index]
            tested_steps.extend(event.step_index for event in successor_support_events)
            tested_steps.extend(event.step_index for event in recovery_events)
            if (
                terminal_events
                and candidate.provisional_status is MechanicsChangeStatus.CONTRADICTED
            ):
                tested_steps.append(terminal_events[0].step_index)
            if candidate.last_tested_step != max(tested_steps):
                raise PolicyError(
                    "checkpoint mechanics candidate last-tested step is not trace-derived"
                )
            if terminal_type is None:
                if terminal_events:
                    raise PolicyError("checkpoint live mechanics candidate has a terminal trace")
            elif (
                len(terminal_events) != 1
                or terminal_events[0].event_type != terminal_type
                or any(
                    terminal_events[0].payload.get(field) != value
                    for field, value in candidate_projection.items()
                )
                or event_order[terminal_events[0].event_id] <= event_order[opening.event_id]
            ):
                raise PolicyError("checkpoint mechanics terminal status disagrees with trace")
            for transition_id in candidate.supporting_successor_transition_ids:
                successor_transition = next(
                    (item for item in self._transitions if item.transition_id == transition_id),
                    None,
                )
                if (
                    successor_transition is None
                    or self._transition_epochs.get(transition_id) != candidate.predecessor_epoch_id
                    or not any(
                        source is not None
                        and source.event_id in candidate.supporting_contradiction_event_ids
                        and set(
                            cast(
                                list[str],
                                cast(dict[str, object], source.payload["evidence_receipt"])[
                                    "evidence_event_ids"
                                ],
                            )
                        )
                        & set(successor_transition.source_event_ids)
                        for source in contradiction_sources
                    )
                ):
                    raise PolicyError("checkpoint mechanics successor evidence linkage disagrees")
        for raw_epoch_item in cast(list[object], lifecycle_projection.get("epochs", [])):
            if not isinstance(raw_epoch_item, dict) or raw_epoch_item.get("epoch_index") == 0:
                continue
            successor_epoch_payload = cast(dict[str, object], raw_epoch_item)
            immutable_epoch_fields = (
                "epoch_id",
                "level_index",
                "epoch_index",
                "parent_epoch_id",
                "start_transition_id",
                "caused_by_change_candidate_id",
            )
            if not any(
                event.event_type == "mechanics.epoch_opened"
                and all(
                    event.payload.get(key) == successor_epoch_payload.get(key)
                    for key in immutable_epoch_fields
                )
                and event.payload.get("status") == "ACTIVE"
                for event in events
            ):
                raise PolicyError("checkpoint mechanics epoch lacks an immutable opening event")

        known_plan_ids = {
            cast(str, event.payload.get("plan_id"))
            for event in events
            if event.event_type == "simulation.plan_evaluated"
            and isinstance(event.payload.get("plan_id"), str)
        }
        traced_invalidated_plan_ids = {
            plan_id
            for event in events
            if event.event_type
            in {
                "mechanics.change_candidate_created",
                "model.rule_demoted",
                "hypothesis.reopened",
            }
            for plan_id in cast(list[object], event.payload.get("invalidated_plan_ids", []))
            if isinstance(plan_id, str)
        }
        traced_invalidated_plan_ids.update(
            plan_id
            for event in events
            if event.event_type == "simulation.plan_invalidated"
            for plan_id in cast(list[object], event.payload.get("plan_ids", []))
            if isinstance(plan_id, str)
        )
        if not traced_invalidated_plan_ids.issubset(known_plan_ids):
            raise PolicyError("checkpoint invalidated-plan authority is not trace-derived")
        if self._invalidated_plan_ids != traced_invalidated_plan_ids:
            raise PolicyError("checkpoint invalidated-plan authority disagrees with trace fold")
        if self._mover_reassignment_candidate_id is not None:
            if (
                self._mover_reassignment_last_component_id is None
                or self._component_to_entity.get(self._mover_reassignment_last_component_id)
                != self._mover_reassignment_candidate_id
            ):
                raise PolicyError(
                    "checkpoint mover-lineage candidate is not present in the latest observation"
                )
        replayed_action_counts: Counter[ActionRequest] = Counter()
        for event in events:
            if (
                event.event_type != "consequence.received"
                or event.episode_id != self.context.episode_id
            ):
                continue
            raw_action = event.payload.get("returned_action") or event.payload.get("action")
            if not isinstance(raw_action, Mapping):
                raise PolicyError("immutable consequence action is malformed")
            try:
                replayed_action_counts[self._action_from_value(raw_action)] += 1
            except (KeyError, ValueError) as error:
                raise PolicyError("immutable consequence action is malformed") from error
        replayed_actions_used = sum(
            count
            for action, count in replayed_action_counts.items()
            if action.name is not ActionName.RESET
        )
        replayed_resets_used = sum(
            count
            for action, count in replayed_action_counts.items()
            if action.name is ActionName.RESET
        )
        replayed_fault_count = sum(
            event.event_type in {"observation.parse_failed", "run.environment_fault"}
            or event.event_type == "action.rejected_by_environment"
            for event in events
            if event.episode_id == self.context.episode_id
        )
        if (
            self._action_counts != replayed_action_counts
            or self._actions_used != replayed_actions_used
            or self._resets_used != replayed_resets_used
            or self._fault_count != replayed_fault_count
        ):
            raise PolicyError("checkpoint action/fault totals disagree with immutable receipts")
        for source_id in self._mover_reassignment_source_event_ids:
            source = event_by_id.get(source_id)
            if source is None or source.event_type != "consequence.received":
                raise PolicyError("checkpoint mover-lineage evidence is not a consequence receipt")

    def _restore_action_counts(self, value: Mapping[str, JSONValue]) -> None:
        raw_registry = value.get("registry")
        if raw_registry is None:
            self._action_effects = ActionEffectRegistry(level_index=self._level_index)
        elif isinstance(raw_registry, Mapping):
            try:
                self._action_effects = ActionEffectRegistry.from_projection(
                    cast(Mapping[str, object], raw_registry)
                )
            except ValueError as error:
                raise PolicyError("checkpoint action-effect registry is malformed") from error
        else:
            raise PolicyError("checkpoint action-effect registry must be an object")
        if self._action_effects.level_index != self._level_index:
            raise PolicyError("checkpoint action-effect registry level does not match controller")
        self._exploration.action_registry = self._action_effects
        raw_history = value.get("epoch_history", {})
        if not isinstance(raw_history, Mapping):
            raise PolicyError("checkpoint action-effect epoch history must be an object")
        restored_history: dict[str, dict[str, JSONValue]] = {}
        for epoch_id, raw_projection in raw_history.items():
            if not isinstance(epoch_id, str) or not isinstance(raw_projection, Mapping):
                raise PolicyError("checkpoint action-effect epoch history is malformed")
            try:
                ActionEffectRegistry.from_projection(cast(Mapping[str, object], raw_projection))
            except ValueError as error:
                raise PolicyError(
                    "checkpoint archived action-effect projection is malformed"
                ) from error
            normalized = normalize_json(raw_projection)
            if not isinstance(normalized, dict):
                raise PolicyError("checkpoint archived action-effect projection is not an object")
            restored_history[epoch_id] = normalized
        self._action_effect_epoch_history = restored_history

        raw_calibration = value.get("calibration_handles", [])
        raw_calibrated = value.get("calibrated_handles", [])
        if (
            not isinstance(raw_calibration, list)
            or not all(isinstance(item, str) for item in raw_calibration)
            or not isinstance(raw_calibrated, list)
            or not all(isinstance(item, str) for item in raw_calibrated)
        ):
            raise PolicyError("checkpoint action calibration handles are malformed")
        try:
            calibration = tuple(ActionName(cast(str, item)) for item in raw_calibration)
            calibrated = tuple(ActionName(cast(str, item)) for item in raw_calibrated)
        except ValueError as error:
            raise PolicyError("checkpoint action calibration handle is invalid") from error
        expected_order = tuple(
            item for item in ActionName if item is not ActionName.RESET and item in calibration
        )
        if (
            ActionName.RESET in calibration
            or len(set(calibration)) != len(calibration)
            or calibration != expected_order
            or calibrated != calibration[: len(calibrated)]
        ):
            raise PolicyError("checkpoint action calibration order is invalid")
        self._calibration_handles = calibration
        self._calibrated_handles = set(calibrated)

        raw_semantics_levels = value.get("interface_semantics_emitted_levels", [])
        if (
            not isinstance(raw_semantics_levels, list)
            or any(
                isinstance(item, bool) or not isinstance(item, int) or item < 0
                for item in raw_semantics_levels
            )
            or len(set(cast(list[int], raw_semantics_levels))) != len(raw_semantics_levels)
        ):
            raise PolicyError("checkpoint interface semantics levels are malformed")
        self._interface_semantics_emitted_levels = set(cast(list[int], raw_semantics_levels))

        raw_pending_handle = value.get("calibration_pending_handle")
        if raw_pending_handle is None:
            self._calibration_pending_handle = None
        elif isinstance(raw_pending_handle, str):
            try:
                self._calibration_pending_handle = ActionName(raw_pending_handle)
            except ValueError as error:
                raise PolicyError("checkpoint pending calibration handle is invalid") from error
        else:
            raise PolicyError("checkpoint pending calibration handle is malformed")
        if self._calibration_pending_handle is not None:
            if (
                self._calibration_cursor >= len(self._calibration_handles)
                or self._calibration_handles[self._calibration_cursor]
                is not self._calibration_pending_handle
                or self._pending_action is None
                or self._pending_action.action.name is not self._calibration_pending_handle
            ):
                raise PolicyError("checkpoint pending calibration boundary is inconsistent")

        raw_effect = value.get("pending_canonical_effect")
        if raw_effect is None:
            self._pending_canonical_effect = None
        elif isinstance(raw_effect, Mapping):
            try:
                self._pending_canonical_effect = CanonicalActionEffect.from_projection(
                    cast(Mapping[str, object], raw_effect)
                )
            except ValueError as error:
                raise PolicyError("checkpoint pending canonical effect is invalid") from error
        else:
            raise PolicyError("checkpoint pending canonical effect is malformed")
        raw_resolution = value.get("pending_resolution_kind")
        if raw_resolution is not None and not isinstance(raw_resolution, str):
            raise PolicyError("checkpoint pending action resolution is malformed")
        self._pending_resolution_kind = raw_resolution

        raw_hashes = value.get("recent_frame_hashes", [])
        if (
            not isinstance(raw_hashes, list)
            or len(raw_hashes) > 32
            or not all(isinstance(item, str) and item.startswith("sha256:") for item in raw_hashes)
        ):
            raise PolicyError("checkpoint recent frame hashes are malformed")
        self._recent_frame_hashes = [FrameHash(cast(str, item)) for item in raw_hashes]

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

    def _validate_restored_plan_authority(self, plan: Plan, *, cursor: int) -> None:
        """Rebind every executable staged-plan facet to current derived authority."""

        if self._ensemble is None:
            raise PolicyError("checkpoint plan has no current executable model")
        current_epoch_id = self._mechanics.active_epoch(self._level_index).epoch_id
        model = next(
            (
                candidate
                for candidate in self._ensemble.candidates
                if candidate.model_id == plan.model_id
            ),
            None,
        )
        if (
            model is None
            or plan.model_id in self._suspended_model_ids
            or plan.model_id in self._demoted_model_ids
            or self._mechanics.model_epoch(plan.model_id) != current_epoch_id
        ):
            raise PolicyError("checkpoint plan model lacks current-epoch authority")
        if (
            plan.plan_id in self._invalidated_plan_ids
            or self._active_goal_id != plan.goal_id
            or plan.goal_id not in self._goal_targets
        ):
            raise PolicyError("checkpoint plan goal/current authority is invalid")
        goal_record = self._goals.get(plan.goal_id)
        expected_goal_revision = (
            f"{goal_record.status.value}:{goal_record.rank}:{goal_record.reopen_count}"
        )
        if plan.goal_revision != expected_goal_revision:
            raise PolicyError("checkpoint plan goal revision is stale")
        if not model.hypothesis_ids or any(
            plan.plan_id not in self._hypotheses.dependent_plan_ids(hypothesis_id)
            for hypothesis_id in model.hypothesis_ids
        ):
            raise PolicyError("checkpoint plan dependency closure is absent")
        if cursor >= len(plan.steps):
            raise PolicyError("checkpoint staged plan has no current step")
        boundary_state = (
            self._before_action_state
            if self._phase is ControllerPhase.AWAITING_CONSEQUENCE
            else self._latest_view.symbolic_state
            if self._latest_view is not None
            else None
        )
        if boundary_state is None or plan.steps[cursor].before_state_id != boundary_state.state_id:
            raise PolicyError("checkpoint plan current step is stale at the observation boundary")
        predicted = boundary_state
        for step in plan.steps[cursor:]:
            if step.before_state_id != predicted.state_id:
                raise PolicyError("checkpoint plan step chain is discontinuous")
            predicted = model.predict(predicted, step.action).after_state
            if step.predicted_state != predicted:
                raise PolicyError("checkpoint plan prediction disagrees with its current model")
        plan_events = tuple(
            event
            for event in self._policy_events()
            if event.event_type == "simulation.plan_evaluated"
            and event.payload.get("status") == SearchStatus.FOUND.value
            and event.payload.get("plan_id") == plan.plan_id
            and event.payload.get("model_id") == plan.model_id
            and event.payload.get("goal_id") == plan.goal_id
            and event.payload.get("mechanics_epoch_id") == current_epoch_id
            and event.payload.get("plan_payload_hash") == sha256_json(self._serialize_plan(plan))
        )
        if len(plan_events) != 1:
            raise PolicyError("checkpoint plan lacks an immutable evaluation receipt")

    def _restore_planner_state(self, value: Mapping[str, JSONValue]) -> None:
        raw_features = value.get("controller_features")
        if raw_features is not None and raw_features != self.features.to_dict():
            raise PolicyError("checkpoint controller feature identity does not match")
        cadence_fields = {
            "cadence_activation_event_id",
            "cadence_checkpoint_state_event_id",
            "cadence_config",
            "cadence_folded_observation_event_id",
            "cadence_state",
            "pending_goal_transitions",
            "prediction_cache",
            "reasoning_selection",
            "reasoning_selected_event_id",
            "reasoning_completed_event_id",
            "reasoning_force_fallback",
        }
        present_cadence_fields = cadence_fields & set(value)
        if present_cadence_fields and present_cadence_fields != cadence_fields:
            raise PolicyError("checkpoint cadence state is only partially present")
        if present_cadence_fields:
            try:
                restored_config = CadenceConfig.from_dict(value.get("cadence_config"))
                restored_state = CadenceState.from_checkpoint_dict(value.get("cadence_state"))
                restored_cache = BoundedCanonicalLRU.from_dict(
                    value.get("prediction_cache"),
                    expected_capacity=self._cadence_config.cache_capacity,
                )
            except PolicyError as error:
                raise PolicyError("checkpoint cadence/cache state is malformed") from error
            if (
                restored_config != self._cadence_config
                or restored_state.configuration_hash != self._cadence_config.configuration_hash
            ):
                raise PolicyError("checkpoint cadence configuration does not match runtime")
            raw_cache = value.get("prediction_cache")
            if not isinstance(raw_cache, Mapping):
                raise PolicyError("checkpoint prediction cache must be an object")
            raw_entries = raw_cache.get("entries_lru_to_mru")
            if not isinstance(raw_entries, list):
                raise PolicyError("checkpoint prediction cache entries are malformed")
            expected_source_identity = self._cache_source_identity()
            expected_configuration_identity = self._cache_configuration_identity()
            for raw_entry in raw_entries:
                if not isinstance(raw_entry, Mapping):
                    raise PolicyError("checkpoint prediction cache entry is malformed")
                raw_key = raw_entry.get("key")
                if (
                    not isinstance(raw_key, Mapping)
                    or raw_key.get("source_identity") != expected_source_identity
                    or raw_key.get("configuration_identity") != expected_configuration_identity
                ):
                    raise PolicyError("checkpoint prediction cache source/configuration is stale")
            raw_goal_transitions = value.get("pending_goal_transitions")
            if (
                not isinstance(raw_goal_transitions, list)
                or len(raw_goal_transitions) > self.context.config.budgets.max_actions
            ):
                raise PolicyError("checkpoint pending goal transition queue is malformed")
            pending_goal_transitions = [
                self._deserialize_goal_transition(item) for item in raw_goal_transitions
            ]
            for transition in pending_goal_transitions:
                before_events = tuple(
                    self.journal.get_event(event_id) for event_id in transition.before_event_ids
                )
                after_events = tuple(
                    self.journal.get_event(event_id) for event_id in transition.after_event_ids
                )
                if (
                    len(before_events) != 1
                    or before_events[0] is None
                    or before_events[0].event_type != "observation.received"
                    or len(after_events) != 2
                    or after_events[0] is None
                    or after_events[0].event_type != "consequence.received"
                    or after_events[1] is None
                    or after_events[1].event_type != "observation.received"
                ):
                    raise PolicyError(
                        "checkpoint pending goal transition lacks immutable receipt sources"
                    )
                traced_before = self._observation_from_trace_event(before_events[0])
                traced_after = self._observation_from_trace_event(after_events[1])
                if (
                    transition.before != traced_before
                    or transition.after != traced_after
                    or transition.step != after_events[1].step_index
                    or transition.level_scope_ref != f"level:{transition.after.levels_completed}"
                    or transition.game_scope_ref != "game:opaque-current-run"
                ):
                    raise PolicyError(
                        "checkpoint pending goal transition disagrees with immutable receipts"
                    )
            raw_selection = value.get("reasoning_selection")
            selection = None if raw_selection is None else CadenceSelection.from_dict(raw_selection)
            selected_event_id = value.get("reasoning_selected_event_id")
            completed_event_id = value.get("reasoning_completed_event_id")
            force_fallback = value.get("reasoning_force_fallback")
            folded_observation_event_id = value.get("cadence_folded_observation_event_id")
            checkpoint_state_event_id = value.get("cadence_checkpoint_state_event_id")
            activation_event_id = value.get("cadence_activation_event_id")
            if selected_event_id is not None and (
                not isinstance(selected_event_id, str) or not selected_event_id
            ):
                raise PolicyError("checkpoint reasoning selected event ID is malformed")
            if completed_event_id is not None and (
                not isinstance(completed_event_id, str) or not completed_event_id
            ):
                raise PolicyError("checkpoint reasoning completed event ID is malformed")
            if not isinstance(force_fallback, bool):
                raise PolicyError("checkpoint reasoning fallback marker is malformed")
            if folded_observation_event_id is not None and (
                not isinstance(folded_observation_event_id, str) or not folded_observation_event_id
            ):
                raise PolicyError("checkpoint cadence fold observation ID is malformed")
            if not isinstance(checkpoint_state_event_id, str) or not checkpoint_state_event_id:
                raise PolicyError("checkpoint cadence commitment event ID is malformed")
            if not isinstance(activation_event_id, str) or not activation_event_id:
                raise PolicyError("checkpoint cadence activation event ID is malformed")
            if selection is None:
                if selected_event_id is not None or completed_event_id is not None:
                    raise PolicyError("checkpoint reasoning IDs lack their typed selection")
            elif (
                selection.configuration_hash != self._cadence_config.configuration_hash
                or not isinstance(selected_event_id, str)
                or not isinstance(completed_event_id, str)
                or restored_state.last_completed_deliberation_event_id != completed_event_id
            ):
                raise PolicyError("checkpoint reasoning selection/completion is inconsistent")
            self._cadence_state = restored_state
            self._prediction_cache = restored_cache
            self._reasoning_selection = selection
            self._reasoning_selected_event_id = selected_event_id
            self._reasoning_completed_event_id = completed_event_id
            self._reasoning_force_fallback = force_fallback
            self._cadence_folded_observation_event_id = folded_observation_event_id
            self._cadence_checkpoint_state_event_id = checkpoint_state_event_id
            self._cadence_activation_event_id = activation_event_id
            self._pending_goal_transitions = pending_goal_transitions
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
        raw_cursor = value.get("cursor")
        if isinstance(raw_cursor, bool) or not isinstance(raw_cursor, int):
            raise PolicyError("checkpoint plan cursor is malformed")
        if raw_plan is None:
            if raw_cursor != 0 or pending_plan:
                raise PolicyError("checkpoint plan cursor/emission lacks a plan")
        elif not isinstance(raw_plan, Mapping):
            raise PolicyError("checkpoint plan is malformed")
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
            self._validate_restored_plan_authority(plan, cursor=raw_cursor)
            try:
                self._plan_executor.restore(plan, cursor=raw_cursor)
            except PlanningError as error:
                raise PolicyError("checkpoint pending plan cursor is invalid") from error
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
            plan = self._deserialize_plan(raw_plan)
            self._validate_restored_plan_authority(plan, cursor=raw_cursor)
            try:
                self._plan_executor.restore(plan, cursor=raw_cursor)
            except PlanningError as error:
                raise PolicyError("checkpoint plan cursor is invalid") from error
        elif self._phase is ControllerPhase.AWAITING_CONSEQUENCE and raw_plan is not None:
            raise PolicyError("checkpoint awaiting consequence has an unmarked plan emission")

        raw_prediction = value.get("pending_prediction")
        raw_prediction_event_id = value.get("pending_prediction_event_id")
        if raw_prediction is None:
            if raw_prediction_event_id is not None:
                raise PolicyError("checkpoint pending prediction event lacks a pending prediction")
            if self._pending_action is not None and self._pending_action.prediction_ids:
                if not self._restored_prediction_state_ids:
                    raise PolicyError("checkpoint pending prediction has no restorable outcomes")
        else:
            if (
                not isinstance(raw_prediction, Mapping)
                or not isinstance(raw_prediction_event_id, str)
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
            prediction_event = self.journal.get_event(raw_prediction_event_id)
            if (
                prediction_event is None
                or prediction_event.event_type != "simulation.prediction_emitted"
                or prediction_event.payload.get("receipt_id") != rebuilt.receipt_id
                or {
                    key: item
                    for key, item in prediction_event.payload.items()
                    if key
                    not in {
                        "cache_hit",
                        "cache_key_hash",
                        "cache_projection_hash",
                        "mechanics_epoch_id",
                    }
                }
                != rebuilt.to_dict()
            ):
                raise PolicyError(
                    "checkpoint pending prediction lacks its immutable emission receipt"
                )
            self._pending_prediction = rebuilt
            self._pending_prediction_event_id = raw_prediction_event_id
            self._restored_prediction_state_ids = tuple(
                item.after_state_id for item in rebuilt.prediction.alternatives
            )
            self._restored_prediction_plan_ids = rebuilt.dependent_plan_ids

    def _restore_world_state(self, value: Mapping[str, JSONValue]) -> None:
        raw_retrodiction_state = value.get("retrodiction_state")
        try:
            restored_retrodiction_runtime = RetrodictionRuntime.from_dict(
                raw_retrodiction_state,
                expected_config=self._retrodiction_runtime.config,
            )
        except WorldModelError as error:
            raise PolicyError("checkpoint retrodiction runtime is malformed") from error
        if not isinstance(
            raw_retrodiction_state, Mapping
        ) or restored_retrodiction_runtime.to_dict() != dict(raw_retrodiction_state):
            raise PolicyError("checkpoint retrodiction runtime does not round-trip exactly")
        raw_force_full_ids = value.get("retrodiction_pending_force_full_source_event_ids", [])
        if (
            not isinstance(raw_force_full_ids, list)
            or not all(isinstance(item, str) and bool(item.strip()) for item in raw_force_full_ids)
            or len(set(cast(list[str], raw_force_full_ids))) != len(raw_force_full_ids)
        ):
            raise PolicyError("checkpoint pending retrodiction triggers are malformed")
        trace_events = self._policy_events()
        last_completed_index = max(
            (
                index
                for index, event in enumerate(trace_events)
                if event.event_type == "model.retrodiction_completed"
            ),
            default=-1,
        )
        expected_force_full_ids = [
            event.event_id
            for event in trace_events[last_completed_index + 1 :]
            if event.event_type in _RETRODICTION_FORCE_FULL_EVENTS
        ]
        if cast(list[str], raw_force_full_ids) != expected_force_full_ids:
            raise PolicyError("checkpoint pending retrodiction triggers disagree with trace fold")
        self._retrodiction_runtime = restored_retrodiction_runtime
        self._retrodiction_force_full_source_event_ids = list(cast(list[str], raw_force_full_ids))

        raw_mechanics = value.get("mechanics_lifecycle")
        if raw_mechanics is None:
            self._mechanics = MechanicsLifecycle(
                level_index=self._level_index,
                maximum_transitions_per_epoch=self.context.config.budgets.max_actions,
            )
            legacy_epoch_id = self._mechanics.active_epoch(self._level_index).epoch_id
            self._mechanics.register_hypotheses(
                (record.hypothesis_id for record in self._hypotheses.all()),
                epoch_id=legacy_epoch_id,
            )
        elif isinstance(raw_mechanics, Mapping):
            try:
                self._mechanics = MechanicsLifecycle.from_dict(
                    cast(Mapping[str, object], raw_mechanics),
                    expected_maximum_transitions_per_epoch=(
                        self.context.config.budgets.max_actions
                    ),
                )
            except WorldModelError as error:
                raise PolicyError("checkpoint mechanics lifecycle is malformed") from error
        else:
            raise PolicyError("checkpoint mechanics lifecycle must be an object")
        current_epoch_id = self._mechanics.active_epoch(self._level_index).epoch_id

        def restore_id_set(field: str) -> set[str]:
            raw_ids = value.get(field, [])
            if not isinstance(raw_ids, list) or not all(isinstance(item, str) for item in raw_ids):
                raise PolicyError(f"checkpoint {field} must be an array of strings")
            return set(cast(list[str], raw_ids))

        self._suspended_model_ids = restore_id_set("suspended_model_ids")
        self._demoted_model_ids = restore_id_set("demoted_model_ids")
        self._invalidated_plan_ids = restore_id_set("invalidated_plan_ids")
        self._resolved_noise_transition_ids = restore_id_set("resolved_noise_transition_ids")

        def restore_handle(field: str) -> ActionName | None:
            raw_handle = value.get(field)
            if raw_handle is None:
                return None
            if not isinstance(raw_handle, str):
                raise PolicyError(f"checkpoint {field} must be a string or null")
            try:
                handle = ActionName(raw_handle)
            except ValueError as error:
                raise PolicyError(f"checkpoint {field} is not an action handle") from error
            if handle is ActionName.RESET:
                raise PolicyError(f"checkpoint {field} cannot be RESET")
            return handle

        self._provisional_probe_handle = restore_handle("provisional_probe_handle")
        self._reexploration_handle = restore_handle("reexploration_handle")
        for field in (
            "reexploration_candidate_id",
            "pending_change_candidate_id",
            "pending_reexploration_candidate_id",
        ):
            raw_identifier = value.get(field)
            if raw_identifier is not None and not isinstance(raw_identifier, str):
                raise PolicyError(f"checkpoint {field} must be a string or null")
            setattr(self, f"_{field}", raw_identifier)
        for candidate_id in (
            self._reexploration_candidate_id,
            self._pending_change_candidate_id,
            self._pending_reexploration_candidate_id,
        ):
            if candidate_id is not None:
                self._mechanics.candidate(candidate_id)

        raw = value.get("preserved_transitions", [])
        if not isinstance(raw, list) or not all(isinstance(item, Mapping) for item in raw):
            raise PolicyError("checkpoint preserved transitions must be an array of objects")
        transition_values = cast(list[Mapping[str, object]], raw)
        seen_transition_ids: set[str] = set()
        for item in transition_values:
            transition = self._deserialize_transition(item)
            if transition.transition_id in seen_transition_ids:
                raise PolicyError("checkpoint contains a duplicate preserved transition")
            seen_transition_ids.add(transition.transition_id)
            level_index = item.get("level_index")
            if isinstance(level_index, bool) or not isinstance(level_index, int):
                raise PolicyError("checkpoint transition level is malformed")
            raw_epoch_id = item.get("mechanics_epoch_id")
            if raw_epoch_id is None and raw_mechanics is None:
                raw_epoch_id = self._mechanics.active_epoch(level_index).epoch_id
            if not isinstance(raw_epoch_id, str):
                raise PolicyError("checkpoint transition mechanics epoch is malformed")
            epoch = self._mechanics.epoch(raw_epoch_id)
            if epoch.level_index != level_index:
                raise PolicyError("checkpoint transition mechanics epoch level mismatch")
            if raw_mechanics is None:
                try:
                    self._mechanics.register_transition(
                        transition.transition_id, epoch_id=raw_epoch_id
                    )
                except WorldModelError as error:
                    raise PolicyError(
                        "checkpoint transition membership disagrees with mechanics lifecycle"
                    ) from error
            elif self._mechanics.transition_epoch(transition.transition_id) != raw_epoch_id:
                raise PolicyError(
                    "checkpoint transition membership disagrees with mechanics lifecycle"
                )
            self._transitions.append(transition)
            self._transition_levels[transition.transition_id] = level_index
            self._transition_epochs[transition.transition_id] = raw_epoch_id
            self._transition_summaries.setdefault(level_index, []).append(transition)
        lifecycle_transition_ids = set(
            cast(
                dict[str, JSONValue],
                self._mechanics.to_dict()["transition_epochs"],
            )
        )
        if lifecycle_transition_ids != seen_transition_ids:
            raise PolicyError("checkpoint transition set disagrees with mechanics lifecycle")
        self._rebuild_matched_prediction_evidence_from_trace()
        current_scope = f"level:{self._level_index}"
        eligible = tuple(
            record
            for record in self._hypotheses.all()
            if record.scope is not HypothesisScope.LEVEL or record.scope_ref == current_scope
            if self._mechanics.hypothesis_epoch(record.hypothesis_id) == current_epoch_id
            if self.features.retain_rejected_hypotheses
            or (
                record.status is not HypothesisStatus.REJECTED and not record.contradiction_receipts
            )
        )
        compiled = compile_hypotheses(eligible)
        self._model_candidates = compiled.candidates
        receipt_candidates = self._validate_retrodiction_runtime_receipts(compiled.candidates)
        raw_active_ids = value.get("active_model_ids", [])
        if (
            not isinstance(raw_active_ids, list)
            or not all(isinstance(item, str) for item in raw_active_ids)
            or len(set(cast(list[str], raw_active_ids))) != len(raw_active_ids)
        ):
            raise PolicyError("checkpoint active model IDs are malformed")
        active_ids = cast(list[str], raw_active_ids)
        raw_active_receipts = value.get("active_model_receipt_event_ids")
        if raw_active_receipts is not None:
            if (
                not isinstance(raw_active_receipts, Mapping)
                or set(raw_active_receipts) != set(active_ids)
                or not all(
                    isinstance(model_id, str) and isinstance(event_id, str) and bool(event_id)
                    for model_id, event_id in raw_active_receipts.items()
                )
                or len(set(raw_active_receipts.values())) != len(raw_active_receipts)
            ):
                raise PolicyError("checkpoint active model receipt binding is malformed")
            trace_events = self._policy_events()
            event_by_id = {event.event_id: event for event in trace_events}
            promotion_pairs = {
                (
                    event.payload.get("model_id"),
                    event.payload.get("retrodiction_completed_event_id"),
                )
                for event in trace_events
                if event.event_type == "model.rule_promoted"
            }
            exact_candidates: list[ModelCandidate] = []
            for model_id in active_ids:
                completed_id = raw_active_receipts.get(model_id)
                completed = event_by_id.get(completed_id) if isinstance(completed_id, str) else None
                candidate = (
                    receipt_candidates.get(completed.event_id) if completed is not None else None
                )
                if (
                    completed is None
                    or completed.event_type != "model.retrodiction_completed"
                    or candidate is None
                    or candidate.model_id != model_id
                    or completed.payload.get("mechanics_epoch_id") != current_epoch_id
                    or completed.payload.get("status")
                    not in {
                        PromotionStatus.PROMOTED.value,
                        PromotionStatus.UNGATED_ABLATION.value,
                    }
                    or completed.payload.get("model_semantic_fingerprint")
                    != model_semantic_fingerprint(candidate)
                    or (model_id, completed.event_id) not in promotion_pairs
                    or model_id in self._suspended_model_ids
                    or model_id in self._demoted_model_ids
                ):
                    raise PolicyError(
                        "checkpoint active model lacks exact immutable retrodiction authority"
                    )
                exact_candidates.append(candidate)
            self._ensemble = (
                WorldModelEnsemble(tuple(exact_candidates)) if exact_candidates else None
            )
            exact_by_id = {candidate.model_id: candidate for candidate in exact_candidates}
            self._model_candidates = tuple(
                exact_by_id.get(candidate.model_id, candidate) for candidate in compiled.candidates
            )
            if self._ensemble is not None:
                self._mechanics.register_models(
                    (candidate.model_id for candidate in self._ensemble.candidates),
                    epoch_id=current_epoch_id,
                )
        else:
            # Pre-cadence checkpoints did not bind the last compiled model
            # weights to their promotion receipts.  Preserve the legacy exact
            # recompilation path for one-way migration only.
            self._restore_legacy_active_ensemble(
                active_ids=active_ids,
                compiled_candidates=compiled.candidates,
                current_epoch_id=current_epoch_id,
            )

    def _restore_legacy_active_ensemble(
        self,
        *,
        active_ids: Sequence[str],
        compiled_candidates: tuple[ModelCandidate, ...],
        current_epoch_id: str,
    ) -> None:
        """Reconstruct the active ensemble used by checkpoints before receipt binding."""

        level_transitions = (
            tuple(
                item
                for item in self._transition_summaries.get(self._level_index, ())
                if self._transition_epochs.get(item.transition_id) == current_epoch_id
            )
            if self.features.use_trace_summaries
            else tuple(
                item
                for item in self._transitions
                if self._transition_levels.get(item.transition_id) == self._level_index
                and self._transition_epochs.get(item.transition_id) == current_epoch_id
            )
        )
        level_transitions = tuple(
            item
            for item in level_transitions
            if item.transition_id not in self._resolved_noise_transition_ids
        )
        artifacts: tuple[RetrodictionArtifact, ...] = tuple(
            self._retrodiction_runtime.execute(
                self._retrodiction_runtime.plan(
                    self._retrodiction_request(
                        candidate,
                        level_transitions,
                        mechanics_epoch_id=current_epoch_id,
                        force_full_source_event_ids=tuple(
                            self._retrodiction_force_full_source_event_ids
                        ),
                    )[0]
                )
            ).artifact
            for candidate in compiled_candidates
        )
        if any(
            (
                artifact.status is PromotionStatus.PROMOTED
                or (
                    not self.features.use_retrodiction_gate
                    and artifact.status is PromotionStatus.UNGATED_ABLATION
                )
            )
            and artifact.model_id not in self._suspended_model_ids
            and artifact.model_id not in self._demoted_model_ids
            for artifact in artifacts
        ):
            accepted_ids = {
                artifact.model_id
                for artifact in artifacts
                if (
                    artifact.status is PromotionStatus.PROMOTED
                    or (
                        not self.features.use_retrodiction_gate
                        and artifact.status is PromotionStatus.UNGATED_ABLATION
                    )
                )
                and artifact.model_id not in self._suspended_model_ids
                and artifact.model_id not in self._demoted_model_ids
            }
            self._ensemble = gated_ensemble(
                tuple(item for item in compiled_candidates if item.model_id in accepted_ids),
                tuple(item for item in artifacts if item.model_id in accepted_ids),
                allow_ungated_ablation=not self.features.use_retrodiction_gate,
            )
            self._mechanics.register_models(
                (candidate.model_id for candidate in self._ensemble.candidates),
                epoch_id=current_epoch_id,
            )
        restored_active = (
            sorted(candidate.model_id for candidate in self._ensemble.candidates)
            if self._ensemble is not None
            else []
        )
        if sorted(active_ids) != restored_active:
            raise PolicyError("checkpoint active model ensemble does not replay exactly")

    def _candidate_from_retrodiction_receipt(
        self,
        receipt: TraceEvent,
    ) -> ModelCandidate:
        """Recompile one historical candidate from retained typed hypotheses."""

        model_id = receipt.payload.get("model_id")
        raw_hypothesis_ids = receipt.payload.get("candidate_hypothesis_ids")
        raw_compile_residuals = receipt.payload.get("candidate_compile_residuals")
        rank_weight = receipt.payload.get("candidate_rank_weight")
        if (
            not isinstance(model_id, str)
            or not isinstance(raw_hypothesis_ids, list)
            or not raw_hypothesis_ids
            or not all(isinstance(item, str) for item in raw_hypothesis_ids)
            or len(set(cast(list[str], raw_hypothesis_ids))) != len(raw_hypothesis_ids)
            or not isinstance(raw_compile_residuals, list)
            or not all(isinstance(item, str) for item in raw_compile_residuals)
            or isinstance(rank_weight, bool)
            or not isinstance(rank_weight, int)
        ):
            raise PolicyError("immutable retrodiction candidate receipt is malformed")
        hypothesis_ids = tuple(cast(list[str], raw_hypothesis_ids))
        historical_records = []
        for hypothesis_id in hypothesis_ids:
            record = self._hypotheses.find(hypothesis_id)
            if record is None:
                raise PolicyError("immutable retrodiction candidate names an unknown hypothesis")
            historical_records.append(replace(record, status=HypothesisStatus.CANDIDATE))
        candidates = compile_hypotheses(tuple(historical_records)).candidates
        candidate = next((item for item in candidates if item.model_id == model_id), None)
        compile_residuals = tuple(cast(list[str], raw_compile_residuals))
        if (
            candidate is None
            or candidate.hypothesis_ids != hypothesis_ids
            or candidate.compile_residuals != compile_residuals
        ):
            raise PolicyError("immutable retrodiction candidate does not recompile exactly")
        return replace(candidate, rank_weight=rank_weight)

    def _validate_retrodiction_runtime_receipts(
        self,
        candidates: Sequence[ModelCandidate],
    ) -> dict[str, ModelCandidate]:
        """Bind restored cache/cost state to reconstructible immutable receipts."""

        events = self._policy_events()
        event_by_id = {event.event_id: event for event in events}
        event_order = {event.event_id: index for index, event in enumerate(events)}
        completed_events = tuple(
            event for event in events if event.event_type == "model.retrodiction_completed"
        )
        state = self._retrodiction_runtime.state
        if state.access_ordinal != len(completed_events):
            raise PolicyError("checkpoint retrodiction access ordinal disagrees with receipts")
        run_started_events = tuple(event for event in events if event.event_type == "run.started")
        if (
            len(run_started_events) != 1
            or run_started_events[0].payload.get("retrodiction_config")
            != self._retrodiction_runtime.config.to_dict()
            or run_started_events[0].payload.get("retrodiction_configuration_hash")
            != self._retrodiction_runtime.config.configuration_hash
        ):
            raise PolicyError("immutable run retrodiction configuration is malformed")
        completion_ordinals = {
            event.event_id: ordinal for ordinal, event in enumerate(completed_events, start=1)
        }
        candidate_by_id = {candidate.model_id: candidate for candidate in candidates}
        transition_by_id = {
            transition.transition_id: transition for transition in self._transitions
        }
        receipt_candidates: dict[str, ModelCandidate] = {}

        plan_receipt_keys = (
            "authorizing_matched_prediction_evidence",
            "cache_hit",
            "cache_key",
            "candidate_compile_residuals",
            "candidate_hypothesis_ids",
            "candidate_rank_weight",
            "complete_scope",
            "force_full_source_event_ids",
            "full_audit",
            "full_eligible_history_count",
            "full_eligible_history_hash",
            "generation",
            "mechanics_epoch_id",
            "mode",
            "model_id",
            "model_semantic_fingerprint",
            "namespace_key",
            "omissions",
            "prefix_count",
            "prior_artifact_id",
            "prior_source_receipt_event_id",
            "reason",
            "resolved_noise_transition_ids",
            "retrodiction_configuration_hash",
            "selected_history_count",
            "selected_history_hash",
            "selected_transition_ids",
            "suffix_count",
        )
        expected_generations: dict[str, int] = {}
        for completed in completed_events:
            started_id = completed.payload.get("retrodiction_started_event_id")
            namespace_key = completed.payload.get("namespace_key")
            generation = completed.payload.get("generation")
            raw_mode = completed.payload.get("mode")
            raw_reason = completed.payload.get("reason")
            full_audit = completed.payload.get("full_audit")
            complete_scope = completed.payload.get("complete_scope")
            started = event_by_id.get(started_id) if isinstance(started_id, str) else None
            try:
                mode = RetrodictionMode(raw_mode) if isinstance(raw_mode, str) else None
                reason = RetrodictionReason(raw_reason) if isinstance(raw_reason, str) else None
            except ValueError:
                mode = None
                reason = None
            allowed_reasons = {
                RetrodictionMode.FULL: {RetrodictionReason.FULL},
                RetrodictionMode.NONE: {RetrodictionReason.DISABLED},
                RetrodictionMode.RECENT_WINDOW_8: {RetrodictionReason.RECENT_WINDOW},
                RetrodictionMode.CACHED_INCREMENTAL: {
                    RetrodictionReason.FIRST_USE,
                    RetrodictionReason.EXACT_CACHE_HIT,
                    RetrodictionReason.PREFIX_EXTENSION,
                    RetrodictionReason.NON_PREFIX,
                    RetrodictionReason.INVALIDATED,
                },
                RetrodictionMode.EVENT_TRIGGERED: {
                    RetrodictionReason.FIRST_USE,
                    RetrodictionReason.EXACT_CACHE_HIT,
                    RetrodictionReason.EVENT_RECEIPT_REUSE,
                    RetrodictionReason.EVENT_FULL_AUDIT,
                },
            }
            full_audit_reasons = {
                RetrodictionReason.FULL,
                RetrodictionReason.FIRST_USE,
                RetrodictionReason.NON_PREFIX,
                RetrodictionReason.INVALIDATED,
                RetrodictionReason.EVENT_FULL_AUDIT,
            }
            if (
                started is None
                or started.event_type != "model.retrodiction_started"
                or not isinstance(namespace_key, str)
                or isinstance(generation, bool)
                or not isinstance(generation, int)
                or not isinstance(full_audit, bool)
                or not isinstance(complete_scope, bool)
                or mode is None
                or reason is None
                or mode is not self._retrodiction_runtime.config.mode
                or reason not in allowed_reasons[mode]
                or full_audit is not (reason in full_audit_reasons)
                or complete_scope
                is not (mode not in {RetrodictionMode.NONE, RetrodictionMode.RECENT_WINDOW_8})
                or completed.payload.get("retrodiction_configuration_hash")
                != self._retrodiction_runtime.config.configuration_hash
                or event_order[started.event_id] >= event_order[completed.event_id]
                or any(
                    started.payload.get(key) != completed.payload.get(key)
                    for key in plan_receipt_keys
                )
            ):
                raise PolicyError("immutable retrodiction start/completion chain is malformed")
            previous_generation = expected_generations.get(namespace_key, 0)
            expected_generation = previous_generation + int(full_audit)
            if generation != expected_generation:
                raise PolicyError("immutable retrodiction generation is not receipt-derived")
            expected_generations[namespace_key] = expected_generation
            force_full_ids = completed.payload.get("force_full_source_event_ids")
            if not isinstance(force_full_ids, list) or not all(
                isinstance(item, str)
                and item in event_order
                and event_order[item] < event_order[started.event_id]
                and event_by_id[item].event_type in _RETRODICTION_FORCE_FULL_EVENTS
                for item in force_full_ids
            ):
                raise PolicyError("immutable force-full retrodiction sources are malformed")
            raw_authorizing_evidence = completed.payload.get(
                "authorizing_matched_prediction_evidence"
            )
            selected_transition_ids = completed.payload.get("selected_transition_ids")
            prefix_count = completed.payload.get("prefix_count")
            if (
                not isinstance(raw_authorizing_evidence, list)
                or not all(isinstance(item, Mapping) for item in raw_authorizing_evidence)
                or not isinstance(selected_transition_ids, list)
                or not all(isinstance(item, str) for item in selected_transition_ids)
                or isinstance(prefix_count, bool)
                or not isinstance(prefix_count, int)
                or not 0 <= prefix_count <= len(selected_transition_ids)
            ):
                raise PolicyError("immutable retrodiction authorization payload is malformed")
            if reason is RetrodictionReason.EVENT_RECEIPT_REUSE:
                model_id = completed.payload.get("model_id")
                if mode is not RetrodictionMode.EVENT_TRIGGERED or not isinstance(model_id, str):
                    raise PolicyError("event-triggered authorization mode/model is malformed")
                suffix_transition_ids = cast(list[str], selected_transition_ids)[prefix_count:]
                expected_authorization: list[dict[str, JSONValue]] = []
                for transition_id in suffix_transition_ids:
                    evidence = self._matched_prediction_evidence.get((transition_id, model_id))
                    if evidence is None:
                        raise PolicyError(
                            "event-triggered reuse lacks trace-derived matched evidence"
                        )
                    expected_authorization.append(evidence.to_dict())
                if (
                    not expected_authorization
                    or [
                        dict(item)
                        for item in cast(list[Mapping[str, JSONValue]], raw_authorizing_evidence)
                    ]
                    != expected_authorization
                ):
                    raise PolicyError(
                        "event-triggered authorization disagrees with suffix receipts"
                    )
            elif raw_authorizing_evidence:
                raise PolicyError("non-event retrodiction invents matched-evidence authorization")

            receipt_model_id = completed.payload.get("model_id")
            if not isinstance(receipt_model_id, str):
                raise PolicyError("immutable retrodiction artifact model is malformed")
            current_candidate = candidate_by_id.get(receipt_model_id)
            candidate = (
                current_candidate
                if current_candidate is not None
                and current_candidate.rank_weight == completed.payload.get("candidate_rank_weight")
                and list(current_candidate.hypothesis_ids)
                == completed.payload.get("candidate_hypothesis_ids")
                and list(current_candidate.compile_residuals)
                == completed.payload.get("candidate_compile_residuals")
                else self._candidate_from_retrodiction_receipt(completed)
            )
            raw_request_transition_ids = started.payload.get("transition_ids")
            if (
                not isinstance(raw_request_transition_ids, list)
                or not all(isinstance(item, str) for item in raw_request_transition_ids)
                or len(set(cast(list[str], raw_request_transition_ids)))
                != len(raw_request_transition_ids)
            ):
                raise PolicyError("immutable retrodiction request transition order is malformed")
            request_transition_ids = cast(list[str], raw_request_transition_ids)
            expected_selected_ids = (
                []
                if mode is RetrodictionMode.NONE
                else request_transition_ids[-self._retrodiction_runtime.config.window :]
                if mode is RetrodictionMode.RECENT_WINDOW_8
                else request_transition_ids
            )
            if cast(list[str], selected_transition_ids) != expected_selected_ids:
                raise PolicyError("immutable retrodiction selected scope is malformed")
            artifact_transition_ids = (
                request_transition_ids
                if mode is RetrodictionMode.NONE
                else cast(list[str], selected_transition_ids)
            )
            try:
                raw_transitions = tuple(
                    transition_by_id[transition_id] for transition_id in artifact_transition_ids
                )
            except KeyError as error:
                raise PolicyError(
                    "immutable retrodiction artifact names an unknown transition"
                ) from error
            mechanics_epoch_id = completed.payload.get("mechanics_epoch_id")
            if not isinstance(mechanics_epoch_id, str) or any(
                self._transition_epochs.get(transition.transition_id) != mechanics_epoch_id
                for transition in raw_transitions
            ):
                raise PolicyError("immutable retrodiction artifact crosses mechanics epochs")
            projected = tuple(
                replace(
                    self._candidate_retrodiction_projection(candidate, transition),
                    compatible_model_ids=(),
                )
                for transition in raw_transitions
            )
            artifact = retrodict(
                candidate,
                projected,
                enabled=mode is not RetrodictionMode.NONE,
            )
            expected_artifact_payload: dict[str, JSONValue] = {
                "artifact_id": artifact.artifact_id,
                "compatible_transition_ids": list(artifact.compatible_transition_ids),
                "complete": artifact.complete,
                "contradiction_transition_ids": list(artifact.contradiction_transition_ids),
                "explicitly_excluded_transition_ids": list(
                    artifact.explicitly_excluded_transition_ids
                ),
                "matched_transition_ids": list(artifact.matched_transition_ids),
                "result_complete": artifact.complete,
                "score": artifact.score.total,
                "status": artifact.status.value,
                "tested_transition_ids": list(artifact.tested_transition_ids),
                "weight_kind": artifact.score.weight_kind,
            }
            raw_artifact_projection = completed.payload.get("artifact_projection")
            if raw_artifact_projection is not None and raw_artifact_projection != normalize_json(
                asdict(artifact)
            ):
                raise PolicyError(
                    "immutable retrodiction artifact projection does not reconstruct exactly"
                )
            artifact_mismatches = tuple(
                key
                for key, value in expected_artifact_payload.items()
                if completed.payload.get(key) != value
            )
            if artifact_mismatches:
                raise PolicyError(
                    "immutable retrodiction artifact receipt does not reconstruct exactly: "
                    f"{artifact_mismatches}"
                )
            receipt_candidates[completed.event_id] = candidate

            reused_id = completed.payload.get("retrodiction_reused_event_id")
            reused_flag = completed.payload.get("reused")
            if not isinstance(reused_flag, bool):
                raise PolicyError("immutable retrodiction reuse marker is malformed")
            if reused_flag:
                reused = event_by_id.get(reused_id) if isinstance(reused_id, str) else None
                if (
                    reused is None
                    or reused.event_type != "model.retrodiction_reused"
                    or reused.payload.get("retrodiction_started_event_id") != started.event_id
                    or not (
                        event_order[started.event_id]
                        < event_order[reused.event_id]
                        < event_order[completed.event_id]
                    )
                    or any(
                        reused.payload.get(key) != completed.payload.get(key)
                        for key in reused.payload
                        if key != "retrodiction_started_event_id"
                    )
                ):
                    raise PolicyError("immutable retrodiction reuse chain is malformed")
            elif reused_id is not None:
                raise PolicyError("immutable non-reused retrodiction cites a reuse receipt")
        if dict(state.trigger_generations) != expected_generations:
            raise PolicyError("checkpoint retrodiction generations disagree with receipts")

        for entry in state.cache_entries:
            cache_completed = event_by_id.get(entry.source_receipt_event_id)
            expected_access_ordinal = completion_ordinals.get(entry.source_receipt_event_id)
            if (
                cache_completed is None
                or cache_completed.event_type != "model.retrodiction_completed"
                or entry.access_ordinal != expected_access_ordinal
            ):
                raise PolicyError(
                    "checkpoint retrodiction cache lacks exact receipt-order authority"
                )
            candidate = receipt_candidates[cache_completed.event_id]
            try:
                raw_transitions = tuple(
                    transition_by_id[outcome.transition_id] for outcome in entry.outcomes
                )
            except KeyError as error:
                raise PolicyError(
                    "checkpoint retrodiction cache names an unknown transition"
                ) from error
            if any(
                self._transition_epochs.get(transition.transition_id) != entry.mechanics_epoch_id
                for transition in raw_transitions
            ):
                raise PolicyError("checkpoint retrodiction cache crosses mechanics epochs")
            projected = tuple(
                self._candidate_retrodiction_projection(candidate, transition)
                for transition in raw_transitions
            )
            request = RetrodictionRequest(
                model=candidate,
                transitions=projected,
                mechanics_epoch_id=entry.mechanics_epoch_id,
                omissions=entry.omissions,
                resolved_noise_transition_ids=entry.resolved_noise_transition_ids,
                force_full_source_event_ids=tuple(
                    cast(
                        list[str],
                        cache_completed.payload.get("force_full_source_event_ids", []),
                    )
                ),
            )
            outcome_ids = [outcome.transition_id for outcome in entry.outcomes]
            tested_ids = [
                outcome.transition_id
                for outcome in entry.outcomes
                if outcome.kind.value != "excluded"
            ]
            excluded_ids = [
                outcome.transition_id
                for outcome in entry.outcomes
                if outcome.kind.value == "excluded"
            ]
            matched_ids = [
                outcome.transition_id
                for outcome in entry.outcomes
                if outcome.kind.value == "matched"
            ]
            contradicted_ids = [
                outcome.transition_id
                for outcome in entry.outcomes
                if outcome.kind.value == "contradicted"
            ]
            if (
                cache_completed.payload.get("model_id") != entry.model_id
                or cache_completed.payload.get("model_semantic_fingerprint")
                != entry.model_semantic_fingerprint
                or cache_completed.payload.get("mechanics_epoch_id") != entry.mechanics_epoch_id
                or cache_completed.payload.get("namespace_key") != entry.namespace_key
                or cache_completed.payload.get("cache_key") != entry.cache_key
                or cache_completed.payload.get("retrodiction_configuration_hash")
                != entry.configuration_hash
                or cache_completed.payload.get("full_eligible_history_hash") != entry.history_key
                or cache_completed.payload.get("full_eligible_history_count") != entry.prefix_length
                or cache_completed.payload.get("compatible_transition_ids") != outcome_ids
                or cache_completed.payload.get("tested_transition_ids") != tested_ids
                or cache_completed.payload.get("explicitly_excluded_transition_ids") != excluded_ids
                or cache_completed.payload.get("matched_transition_ids") != matched_ids
                or cache_completed.payload.get("contradiction_transition_ids") != contradicted_ids
                or cache_completed.payload.get("artifact_id") != entry.materialized_artifact_id
                or cache_completed.payload.get("omissions")
                != [item.to_dict() for item in entry.omissions]
                or cache_completed.payload.get("resolved_noise_transition_ids")
                != list(entry.resolved_noise_transition_ids)
            ):
                raise PolicyError("checkpoint retrodiction cache disagrees with completion receipt")
            try:
                entry.validate_against(
                    config=self._retrodiction_runtime.config,
                    request=request,
                    materialized_artifact_id=cast(str, cache_completed.payload["artifact_id"]),
                    source_receipt_event_id=cache_completed.event_id,
                )
            except WorldModelError as error:
                raise PolicyError(
                    "checkpoint retrodiction cache fails exact reconstruction"
                ) from error

        for promotion in (event for event in events if event.event_type == "model.rule_promoted"):
            completed_id = promotion.payload.get("retrodiction_completed_event_id")
            promotion_completed = (
                event_by_id.get(completed_id) if isinstance(completed_id, str) else None
            )
            if (
                promotion_completed is None
                or promotion_completed.event_type != "model.retrodiction_completed"
                or event_order[promotion_completed.event_id] >= event_order[promotion.event_id]
                or promotion.payload.get("model_id") != promotion_completed.payload.get("model_id")
                or promotion.payload.get("mechanics_epoch_id")
                != promotion_completed.payload.get("mechanics_epoch_id")
                or promotion.payload.get("retrodiction_artifact_id")
                != promotion_completed.payload.get("artifact_id")
                or promotion.payload.get("retrodiction_mode")
                != promotion_completed.payload.get("mode")
                or promotion.payload.get("retrodiction_reason")
                != promotion_completed.payload.get("reason")
                or promotion_completed.payload.get("status")
                not in {
                    PromotionStatus.PROMOTED.value,
                    PromotionStatus.UNGATED_ABLATION.value,
                }
            ):
                raise PolicyError("immutable model promotion lacks retrodiction authority")
        return receipt_candidates

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
        return evidence.to_dict()

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

    @classmethod
    def _serialize_goal_transition(cls, transition: GoalTransition) -> dict[str, JSONValue]:
        return {
            "before": cls._serialize_observation(transition.before),
            "after": cls._serialize_observation(transition.after),
            "before_event_ids": list(transition.before_event_ids),
            "after_event_ids": list(transition.after_event_ids),
            "step": transition.step,
            "level_scope_ref": transition.level_scope_ref,
            "game_scope_ref": transition.game_scope_ref,
        }

    @classmethod
    def _deserialize_goal_transition(cls, value: object) -> GoalTransition:
        if not isinstance(value, Mapping):
            raise PolicyError("checkpoint pending goal transition must be an object")
        before_ids = value.get("before_event_ids")
        after_ids = value.get("after_event_ids")
        step = value.get("step")
        level_scope_ref = value.get("level_scope_ref")
        game_scope_ref = value.get("game_scope_ref")
        if (
            not isinstance(before_ids, list)
            or not before_ids
            or not all(isinstance(item, str) and item for item in before_ids)
            or not isinstance(after_ids, list)
            or not after_ids
            or not all(isinstance(item, str) and item for item in after_ids)
            or isinstance(step, bool)
            or not isinstance(step, int)
            or step < 0
            or not isinstance(level_scope_ref, str)
            or not level_scope_ref
            or not isinstance(game_scope_ref, str)
            or not game_scope_ref
        ):
            raise PolicyError("checkpoint pending goal transition fields are malformed")
        return GoalTransition(
            before=cls._deserialize_observation(value.get("before")),
            after=cls._deserialize_observation(value.get("after")),
            before_event_ids=tuple(cast(list[str], before_ids)),
            after_event_ids=tuple(cast(list[str], after_ids)),
            step=step,
            level_scope_ref=level_scope_ref,
            game_scope_ref=game_scope_ref,
        )

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
            plan = Plan(
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
        if any(
            not item.strip()
            for item in (
                plan.plan_id,
                plan.problem_id,
                plan.model_id,
                plan.goal_id,
                plan.goal_revision,
                plan.initial_state_id,
                plan.final_state_id,
            )
        ):
            raise PolicyError("checkpoint plan identities must be non-empty")
        if not plan.steps or tuple(step.index for step in plan.steps) != tuple(
            range(len(plan.steps))
        ):
            raise PolicyError("checkpoint plan step indices are not contiguous")
        if (
            plan.problem_id != f"problem:{plan.initial_state_id[-24:]}"
            or plan.steps[0].before_state_id != plan.initial_state_id
            or any(
                step.before_state_id != plan.steps[index - 1].predicted_state_id
                for index, step in enumerate(plan.steps[1:], start=1)
            )
            or plan.final_state_id != plan.steps[-1].predicted_state_id
        ):
            raise PolicyError("checkpoint plan state chain is malformed")
        expected_plan_id = (
            "plan:"
            + sha256_json(
                {
                    "problem_id": plan.problem_id,
                    "model_id": plan.model_id,
                    "goal_id": plan.goal_id,
                    "goal_revision": plan.goal_revision,
                    "algorithm": plan.algorithm.value,
                    "initial_state_id": plan.initial_state_id,
                    "actions": [
                        {
                            "name": step.action.name.value,
                            "coordinate": (
                                [step.action.coordinate.x, step.action.coordinate.y]
                                if step.action.coordinate is not None
                                else None
                            ),
                        }
                        for step in plan.steps
                    ],
                }
            ).removeprefix("sha256:")[:24]
        )
        if plan.plan_id != expected_plan_id:
            raise PolicyError("checkpoint plan identity disagrees with its complete action path")
        score_totals = (
            (plan.score.total_cost, sum(step.cost for step in plan.steps)),
            (plan.score.total_risk, sum(step.failure_risk for step in plan.steps)),
            (
                plan.score.total_information,
                sum(step.information_value for step in plan.steps),
            ),
        )
        if plan.score.action_count != len(plan.steps) or any(
            not math.isclose(actual, expected, rel_tol=0.0, abs_tol=1e-9)
            for actual, expected in score_totals
        ):
            raise PolicyError("checkpoint plan score disagrees with its complete path")
        return plan

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
            "compatible_model_ids": list(value.compatible_model_ids),
            "level_index": self._transition_levels[value.transition_id],
            "mechanics_epoch_id": self._transition_epochs[value.transition_id],
        }

    def _active_model_receipt_event_ids(self) -> dict[str, str]:
        """Bind each live model to the exact promotion-producing audit receipt."""

        if self._ensemble is None:
            return {}
        events = self._policy_events()
        event_by_id = {event.event_id: event for event in events}
        promotions = tuple(event for event in events if event.event_type == "model.rule_promoted")
        receipt_ids: dict[str, str] = {}
        for candidate in self._ensemble.candidates:
            semantic_fingerprint = model_semantic_fingerprint(candidate)
            for promotion in reversed(promotions):
                if promotion.payload.get("model_id") != candidate.model_id:
                    continue
                completed_id = promotion.payload.get("retrodiction_completed_event_id")
                completed = event_by_id.get(completed_id) if isinstance(completed_id, str) else None
                if (
                    completed is not None
                    and completed.event_type == "model.retrodiction_completed"
                    and completed.payload.get("model_semantic_fingerprint") == semantic_fingerprint
                    and completed.payload.get("candidate_rank_weight") == candidate.rank_weight
                    and completed.payload.get("candidate_hypothesis_ids")
                    == list(candidate.hypothesis_ids)
                    and completed.payload.get("candidate_compile_residuals")
                    == list(candidate.compile_residuals)
                ):
                    receipt_ids[candidate.model_id] = completed.event_id
                    break
            if candidate.model_id not in receipt_ids:
                raise PolicyError("active world model lacks an exact immutable promotion receipt")
        return receipt_ids

    @classmethod
    def _deserialize_transition(cls, value: Mapping[str, object]) -> PreservedTransition:
        before = value.get("before")
        after = value.get("after")
        action = value.get("action")
        sources = value.get("source_event_ids", [])
        compatible_model_ids = value.get("compatible_model_ids", [])
        if (
            not isinstance(before, Mapping)
            or not isinstance(after, Mapping)
            or not isinstance(action, Mapping)
            or not isinstance(sources, list)
            or not all(isinstance(item, str) for item in sources)
            or not isinstance(compatible_model_ids, list)
            or not all(
                isinstance(item, str) and bool(item.strip()) for item in compatible_model_ids
            )
            or len(set(cast(list[str], compatible_model_ids))) != len(compatible_model_ids)
        ):
            raise PolicyError("serialized transition is malformed")
        return PreservedTransition(
            transition_id=str(value.get("transition_id")),
            before=cls._state_from_dict(before),
            action=cls._action_from_value(action),
            after=cls._state_from_dict(after),
            source_event_ids=tuple(cast(list[str], sources)),
            compatible_model_ids=tuple(cast(list[str], compatible_model_ids)),
        )

    @_profiled("finalize")
    def close(self) -> None:
        """Flush the trace without inventing a completion result."""

        if self._journal is None or self._phase is ControllerPhase.CLOSED:
            return
        if self._transient_fold_boundary is not None:
            # Closing the journal flushes immutable receipts but deliberately
            # adds neither a false run completion nor a snapshot of a partial
            # observation, decision, or consequence fold.  Restore then either
            # reopens an explicitly safe derived suffix or rejects an uncertain
            # raw/external boundary.
            self.journal.close()
            self._phase = ControllerPhase.CLOSED
            return
        if self._cadence_state.deliberation_in_progress:
            latest = self._latest_observation
            if latest is None:
                raise PolicyError("pending reasoning lacks its observation boundary")
            self._reasoning_terminal_status = DeliberationStatus.FAILED
            self._reasoning_fault_type = "ControllerClosedBeforeAction"
            self._complete_reasoning_cycle(latest, advance_cadence=False)
        if self._phase is not ControllerPhase.AWAITING_CONSEQUENCE:
            events = self._policy_events()
            last_material_event = next(
                (
                    event
                    for event in reversed(events)
                    if event.event_type
                    not in {"reasoning.checkpoint_state", "run.checkpoint_written"}
                ),
                None,
            )
            if last_material_event is None or last_material_event.event_type != "run.completed":
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
        tail = self.journal.tail_event
        checkpoint_is_current = (
            self._last_checkpoint is not None
            and tail is not None
            and tail.event_type == "run.checkpoint_written"
            and tail.payload.get("checkpoint_hash")
            == self._last_checkpoint.envelope.checkpoint_hash
        )
        if self.features.use_memory and not checkpoint_is_current:
            self._maybe_automatic_checkpoint(boundary="finalize", force=True)
        self.journal.close()
        self._phase = ControllerPhase.CLOSED


__all__ = ["ARC3Controller"]
