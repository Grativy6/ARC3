"""Deterministic paired synthetic evaluation for Stage 14 ablations."""

from __future__ import annotations

import hashlib
import json
import math
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from arc3.adapters import EnvironmentSession
from arc3.adapters.synthetic import SYNTHETIC_GAME_ID, SyntheticAdapter
from arc3.config import ARC3Config, BudgetConfig
from arc3.errors import PolicyError
from arc3.lab import LabAdapter, LabPartition
from arc3.policy import (
    ARC3Controller,
    ControllerPhase,
    ControllerPreset,
    PresetFeatures,
    RunContext,
    preset_features,
)
from arc3.trace import EventJournal, TraceEvent, verify_event_chain
from arc3.trace.canonical import sha256_json
from arc3.types import EnvironmentMode, JSONValue

from .models import AblationId, ablation_spec, ablation_specs, features_for_ablation

ABLATION_SCHEMA = "arc3.ablations.paired.v0.1"
PROTOCOL_SCHEMA = "arc3.ablation-protocol.v0.1"
DEFAULT_NAVIGATION_SEEDS: tuple[int, ...] = (101, 211, 307, 401, 503, 601, 701, 809)
DEFAULT_PROTOCOL_PATH = Path(__file__).with_name("protocol.v0.1.json")


@dataclass(frozen=True, slots=True)
class AblationProtocol:
    """Predeclared cases and equal outer budgets for every policy variant."""

    navigation_seeds: tuple[int, ...] = DEFAULT_NAVIGATION_SEEDS
    lab_root_seed: int = 20_260_821
    lab_cases_per_partition: int = 3
    action_budget: int = 16
    reset_budget: int = 2
    grid_size: int = 8
    synthetic_max_steps: int = 32
    wall_clock_seconds: float = 120.0
    max_search_nodes: int = 2_048

    def __post_init__(self) -> None:
        if not self.navigation_seeds and self.lab_cases_per_partition == 0:
            raise ValueError("ablation protocol requires at least one case")
        if len(set(self.navigation_seeds)) != len(self.navigation_seeds):
            raise ValueError("navigation seeds must be unique")
        if any(
            isinstance(seed, bool) or not -(2**63) <= seed < 2**63 for seed in self.navigation_seeds
        ):
            raise ValueError("navigation seeds must be signed 64-bit integers")
        for name, value in (
            ("action_budget", self.action_budget),
            ("reset_budget", self.reset_budget),
            ("grid_size", self.grid_size),
            ("synthetic_max_steps", self.synthetic_max_steps),
            ("max_search_nodes", self.max_search_nodes),
        ):
            if isinstance(value, bool) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if isinstance(self.lab_cases_per_partition, bool) or self.lab_cases_per_partition < 0:
            raise ValueError("lab_cases_per_partition must be a non-negative integer")
        if not math.isfinite(self.wall_clock_seconds) or self.wall_clock_seconds <= 0:
            raise ValueError("wall_clock_seconds must be finite and positive")

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "action_budget": self.action_budget,
            "grid_size": self.grid_size,
            "lab_cases_per_partition": self.lab_cases_per_partition,
            "lab_partitions": [
                LabPartition.HELD_OUT_COMBINATIONS.value,
                LabPartition.HELD_OUT_FAMILIES.value,
            ],
            "lab_root_seed": self.lab_root_seed,
            "max_search_nodes": self.max_search_nodes,
            "navigation_seeds": list(self.navigation_seeds),
            "reset_budget": self.reset_budget,
            "scorer": "arc3.stage14.exact-synthetic-completion.v1",
            "synthetic_max_steps": self.synthetic_max_steps,
            "wall_clock_seconds": self.wall_clock_seconds,
        }


@dataclass(frozen=True, slots=True)
class _Case:
    case_key: str
    source: str
    game_id: str
    seed: int
    partition: str

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "case_key": self.case_key,
            "partition": self.partition,
            "seed": self.seed,
            "source": self.source,
        }


@dataclass(frozen=True, slots=True)
class EpisodeResult:
    """Raw, scorecard-backed values for one case and one feature configuration."""

    variant: str
    case_key: str
    partition: str
    seed: int
    completed: bool
    score: float
    actions: int
    resets: int
    final_state: str
    scorer: str
    verified: bool
    trace_events: int
    trace_bytes: int
    checkpoint_bytes: int
    decision_seconds: tuple[float, ...]
    wall_seconds: float
    trace_tail_hash: str
    action_digest: str
    event_counts: tuple[tuple[str, int], ...]
    coordinate_actions: int
    information_positive_candidates: int
    planned_prediction_mismatches: int
    trace_path: str
    fault: str | None = None

    @property
    def environment_commands(self) -> int:
        return self.actions + self.resets

    def semantic_dict(self) -> dict[str, JSONValue]:
        return {
            "action_digest": self.action_digest,
            "actions": self.actions,
            "case_key": self.case_key,
            "completed": self.completed,
            "coordinate_actions": self.coordinate_actions,
            "event_counts": {key: value for key, value in self.event_counts},
            "fault": self.fault,
            "final_state": self.final_state,
            "information_positive_candidates": self.information_positive_candidates,
            "partition": self.partition,
            "planned_prediction_mismatches": self.planned_prediction_mismatches,
            "resets": self.resets,
            "score": self.score,
            "scorer": self.scorer,
            "seed": self.seed,
            "trace_events": self.trace_events,
            "variant": self.variant,
            "verified": self.verified,
        }

    def to_dict(self) -> dict[str, JSONValue]:
        latencies = sorted(self.decision_seconds)
        return {
            **self.semantic_dict(),
            "checkpoint_bytes": self.checkpoint_bytes,
            "decision_latency_seconds": {
                "count": len(latencies),
                "maximum": max(latencies, default=0.0),
                "median": _percentile(latencies, 0.5),
                "p95": _percentile(latencies, 0.95),
                "total": sum(latencies),
            },
            "environment_commands": self.environment_commands,
            "trace_bytes": self.trace_bytes,
            "trace_path": self.trace_path,
            "trace_tail_hash": self.trace_tail_hash,
            "wall_seconds": self.wall_seconds,
        }


def _percentile(values: list[float], probability: float) -> float:
    if not values:
        return 0.0
    index = max(0, min(len(values) - 1, math.ceil(probability * len(values)) - 1))
    return values[index]


def _positive_information_candidates(events: tuple[TraceEvent, ...]) -> int:
    count = 0
    for event in events:
        if event.event_type != "action.candidates_generated":
            continue
        candidates = event.payload.get("candidates")
        if not isinstance(candidates, list):
            continue
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            information = candidate.get("information")
            if (
                isinstance(information, (int, float))
                and not isinstance(information, bool)
                and information > 0
            ):
                count += 1
    return count


def _planned_prediction_mismatches(events: tuple[TraceEvent, ...]) -> int:
    count = 0
    for event in events:
        if event.event_type != "consequence.mismatched_prediction":
            continue
        direct_plan_ids = event.payload.get("invalidated_plan_ids")
        if isinstance(direct_plan_ids, list) and direct_plan_ids:
            count += 1
            continue
        reopenings = event.payload.get("reopenings")
        if not isinstance(reopenings, list):
            continue
        for reopening in reopenings:
            if not isinstance(reopening, dict):
                continue
            invalidated = reopening.get("invalidated_plan_ids")
            if isinstance(invalidated, list) and invalidated:
                count += 1
                break
    return count


def _spec_payload() -> list[JSONValue]:
    return [
        {
            "ablation_id": spec.ablation_id.value,
            "component": spec.component,
            "disabled_feature": spec.disabled_feature,
            "expected_effect_surface": spec.expected_effect_surface,
            "question": spec.question,
        }
        for spec in ablation_specs()
    ]


def _manifest_integer(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"ablation protocol {field} is not an integer")
    return value


def load_protocol_manifest(
    path: Path = DEFAULT_PROTOCOL_PATH,
) -> tuple[AblationProtocol, tuple[AblationId, ...], str]:
    """Load and exactly validate the frozen A1--A10 measurement declaration."""

    raw_bytes = path.read_bytes()
    loaded = json.loads(raw_bytes)
    if not isinstance(loaded, dict):
        raise ValueError("ablation protocol manifest must be an object")
    raw_protocol = loaded.get("protocol")
    if not isinstance(raw_protocol, dict):
        raise ValueError("ablation protocol manifest requires a protocol object")
    raw_seeds = raw_protocol.get("navigation_seeds")
    if not isinstance(raw_seeds, list) or not all(
        isinstance(seed, int) and not isinstance(seed, bool) for seed in raw_seeds
    ):
        raise ValueError("ablation protocol navigation seeds are malformed")
    wall_clock = raw_protocol.get("wall_clock_seconds")
    if isinstance(wall_clock, bool) or not isinstance(wall_clock, (int, float)):
        raise ValueError("ablation protocol wall-clock budget is malformed")
    protocol = AblationProtocol(
        navigation_seeds=tuple(raw_seeds),
        lab_root_seed=_manifest_integer(raw_protocol.get("lab_root_seed"), field="lab_root_seed"),
        lab_cases_per_partition=_manifest_integer(
            raw_protocol.get("lab_cases_per_partition"), field="lab_cases_per_partition"
        ),
        action_budget=_manifest_integer(raw_protocol.get("action_budget"), field="action_budget"),
        reset_budget=_manifest_integer(raw_protocol.get("reset_budget"), field="reset_budget"),
        grid_size=_manifest_integer(raw_protocol.get("grid_size"), field="grid_size"),
        synthetic_max_steps=_manifest_integer(
            raw_protocol.get("synthetic_max_steps"), field="synthetic_max_steps"
        ),
        wall_clock_seconds=float(wall_clock),
        max_search_nodes=_manifest_integer(
            raw_protocol.get("max_search_nodes"), field="max_search_nodes"
        ),
    )
    expected_protocol = AblationProtocol()
    expected: dict[str, JSONValue] = {
        "ablations": _spec_payload(),
        "claim": "NO_GENERALIZATION_CLAIM",
        "label": "synthetic",
        "protocol": expected_protocol.to_dict(),
        "schema": PROTOCOL_SCHEMA,
        "surface": "synthetic",
        "verified": True,
    }
    if loaded != expected:
        raise ValueError("ablation protocol manifest does not exactly match its typed contract")
    digest = "sha256:" + hashlib.sha256(raw_bytes).hexdigest()
    return protocol, tuple(AblationId), digest


def _tree_bytes(root: Path) -> int:
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file())


def _cases(protocol: AblationProtocol) -> tuple[_Case, ...]:
    cases = [
        _Case(
            case_key=f"navigation-seed-{seed}",
            source="deterministic-navigation",
            game_id=SYNTHETIC_GAME_ID,
            seed=seed,
            partition="predeclared-navigation-holdout",
        )
        for seed in protocol.navigation_seeds
    ]
    for partition in (
        LabPartition.HELD_OUT_COMBINATIONS,
        LabPartition.HELD_OUT_FAMILIES,
    ):
        if protocol.lab_cases_per_partition == 0:
            continue
        adapter = LabAdapter(
            partition=partition,
            root_seed=protocol.lab_root_seed,
            count=protocol.lab_cases_per_partition,
        )
        cases.extend(
            _Case(
                case_key=f"{partition.value}-{ordinal:04d}",
                source="procedural-laboratory",
                game_id=case.case_id,
                seed=case.seed,
                partition=partition.value,
            )
            for ordinal, case in enumerate(adapter.cases())
        )
    return tuple(cases)


def _open_case(case: _Case, protocol: AblationProtocol) -> EnvironmentSession:
    if case.source == "deterministic-navigation":
        return SyntheticAdapter(
            seed=case.seed,
            size=protocol.grid_size,
            max_steps=protocol.synthetic_max_steps,
        ).open(case.game_id)
    partition = LabPartition(case.partition)
    return LabAdapter(
        partition=partition,
        root_seed=protocol.lab_root_seed,
        count=protocol.lab_cases_per_partition,
    ).open(case.game_id)


def _context(
    root: Path,
    *,
    case: _Case,
    ordinal: int,
    variant: str,
    protocol: AblationProtocol,
    git_commit: str,
) -> RunContext:
    safe_variant = variant.lower()
    return RunContext(
        run_id=f"stage14-{safe_variant}-{ordinal:04d}",
        episode_id=f"stage14-{safe_variant}-episode-{ordinal:04d}",
        game_id=case.game_id,
        trace_root=root / safe_variant / f"{ordinal:04d}" / "trace",
        checkpoint_root=root / safe_variant / f"{ordinal:04d}" / "checkpoint",
        config=ARC3Config(
            mode=EnvironmentMode.SYNTHETIC,
            seed=case.seed,
            network_enabled=False,
            profile=f"stage14-{safe_variant}",
            budgets=BudgetConfig(
                max_actions=protocol.action_budget,
                max_resets=protocol.reset_budget,
                wall_clock_seconds=protocol.wall_clock_seconds,
                max_search_nodes=protocol.max_search_nodes,
            ),
        ),
        git_commit=git_commit,
        source_kind="stage14-paired-ablation",
        source_version="0.1",
    )


def _run_episode(
    root: Path,
    *,
    case: _Case,
    ordinal: int,
    variant: str,
    features: PresetFeatures,
    protocol: AblationProtocol,
    git_commit: str,
) -> EpisodeResult:
    session = _open_case(case, protocol)
    context = _context(
        root,
        case=case,
        ordinal=ordinal,
        variant=variant,
        protocol=protocol,
        git_commit=git_commit,
    )
    controller = ARC3Controller(ControllerPreset.FULL, features=features)
    decisions: list[float] = []
    submitted: list[dict[str, JSONValue]] = []
    fault: str | None = None
    started = time.perf_counter()
    controller.reset(context)
    controller.observe(session.observation)
    while controller.phase not in {ControllerPhase.COMPLETE, ControllerPhase.FAULTED}:
        snapshot = controller.snapshot
        if snapshot.actions_used >= protocol.action_budget:
            break
        if (
            controller.phase is ControllerPhase.GAME_OVER
            and snapshot.resets_used >= protocol.reset_budget
        ):
            break
        decision_started = time.perf_counter()
        try:
            decision = controller.choose_action()
        except PolicyError as error:
            fault = f"choose_action:{type(error).__name__}:{error}"
            break
        decisions.append(time.perf_counter() - decision_started)
        submitted.append(
            {
                "name": decision.action.name.value,
                "coordinate": (
                    [decision.action.coordinate.x, decision.action.coordinate.y]
                    if decision.action.coordinate is not None
                    else None
                ),
            }
        )
        try:
            controller.apply_consequence(session.step(decision.action))
        except PolicyError as error:
            fault = f"apply_consequence:{type(error).__name__}:{error}"
            break
    snapshot = controller.snapshot
    controller.close()
    scorecard = session.close()
    wall_seconds = time.perf_counter() - started
    if scorecard is None or len(scorecard.runs) != 1:
        raise RuntimeError("synthetic session did not return one exact scorecard")
    run = scorecard.runs[0]
    auditor = EventJournal(context.trace_root, run_id=context.run_id)
    events = auditor.verify_manifest()
    verify_event_chain(list(events))
    auditor.close()
    counts = Counter(event.event_type for event in events)
    trace_tail_hash = events[-1].event_hash
    return EpisodeResult(
        variant=variant,
        case_key=case.case_key,
        partition=case.partition,
        seed=case.seed,
        completed=run.completed,
        score=run.score,
        actions=snapshot.actions_used,
        resets=snapshot.resets_used,
        final_state=run.state.value,
        scorer=scorecard.scorer,
        verified=scorecard.verified,
        trace_events=len(events),
        trace_bytes=_tree_bytes(context.trace_root),
        checkpoint_bytes=(
            _tree_bytes(context.checkpoint_root) if context.checkpoint_root.exists() else 0
        ),
        decision_seconds=tuple(decisions),
        wall_seconds=wall_seconds,
        trace_tail_hash=trace_tail_hash,
        action_digest=sha256_json(submitted),
        event_counts=tuple(sorted(counts.items())),
        coordinate_actions=sum(item["coordinate"] is not None for item in submitted),
        information_positive_candidates=_positive_information_candidates(events),
        planned_prediction_mismatches=_planned_prediction_mismatches(events),
        trace_path=context.trace_root.relative_to(root).as_posix(),
        fault=fault,
    )


def _aggregate(results: tuple[EpisodeResult, ...]) -> dict[str, JSONValue]:
    completed = sum(result.completed for result in results)
    actions = sum(result.actions for result in results)
    resets = sum(result.resets for result in results)
    commands = actions + resets
    completed_actions = [result.actions for result in results if result.completed]
    latencies = sorted(value for result in results for value in result.decision_seconds)
    return {
        "action_efficiency_completed_per_command": completed / commands if commands else 0.0,
        "completed": completed,
        "completion_rate": completed / len(results),
        "coordinate_actions": sum(result.coordinate_actions for result in results),
        "episodes": len(results),
        "faults": sum(result.fault is not None for result in results),
        "mean_actions_all": actions / len(results),
        "mean_actions_completed": (
            sum(completed_actions) / len(completed_actions) if completed_actions else None
        ),
        "mean_score": sum(result.score for result in results) / len(results),
        "information_positive_candidates": sum(
            result.information_positive_candidates for result in results
        ),
        "planned_prediction_mismatches": sum(
            result.planned_prediction_mismatches for result in results
        ),
        "resets": resets,
        "total_actions": actions,
        "total_checkpoint_bytes": sum(result.checkpoint_bytes for result in results),
        "total_decision_seconds": sum(latencies),
        "total_environment_commands": commands,
        "total_trace_bytes": sum(result.trace_bytes for result in results),
        "total_trace_events": sum(result.trace_events for result in results),
        "total_wall_seconds": sum(result.wall_seconds for result in results),
        "decision_latency_seconds": {
            "count": len(latencies),
            "maximum": max(latencies, default=0.0),
            "median": _percentile(latencies, 0.5),
            "p95": _percentile(latencies, 0.95),
        },
    }


def _event_total(results: tuple[EpisodeResult, ...], event_type: str) -> int:
    return sum(dict(result.event_counts).get(event_type, 0) for result in results)


def _mechanism_exposure(
    full: tuple[EpisodeResult, ...], ablation_id: AblationId
) -> dict[str, JSONValue]:
    """Declare whether the paired cases actually reached the removed mechanism."""

    if ablation_id is AblationId.A1:
        checkpoint_bytes = sum(result.checkpoint_bytes for result in full)
        return {
            "status": "PARTIAL_PROXY_ONLY" if checkpoint_bytes else "NOT_EXERCISED",
            "evidence": {"full_checkpoint_bytes": checkpoint_bytes},
            "boundary": (
                "Checkpoint persistence is exercised, but no cross-level learned-rule retrieval "
                "is present in this suite."
            ),
        }
    if ablation_id is AblationId.A2:
        contradiction_events = _event_total(full, "hypothesis.contradicted")
        rejection_events = _event_total(full, "hypothesis.rejected")
        reached = contradiction_events + rejection_events
        return {
            "status": "EXERCISED" if reached else "NOT_EXERCISED",
            "evidence": {
                "hypothesis_contradiction_events": contradiction_events,
                "hypothesis_rejection_events": rejection_events,
            },
            "boundary": "Retention can affect behavior only after a rejection or contradiction.",
        }
    if ablation_id is AblationId.A3:
        receipts = _event_total(full, "model.retrodiction_completed")
        return {
            "status": "EXERCISED" if receipts else "NOT_EXERCISED",
            "evidence": {"retrodiction_receipts": receipts},
            "boundary": "Exposure records gate execution; score effects remain paired evidence.",
        }
    if ablation_id is AblationId.A4:
        predictions = _event_total(full, "simulation.prediction_emitted")
        plans = _event_total(full, "simulation.plan_evaluated")
        return {
            "status": "EXERCISED" if predictions + plans else "NOT_EXERCISED",
            "evidence": {"plan_evaluations": plans, "prediction_receipts": predictions},
            "boundary": "Exposure records executable simulation or search in FULL.",
        }
    if ablation_id is AblationId.A5:
        goals = _event_total(full, "goal.candidate_created")
        return {
            "status": "EXERCISED" if goals else "NOT_EXERCISED",
            "evidence": {"goal_candidates": goals},
            "boundary": "Exposure records falsifiable goal-candidate creation in FULL.",
        }
    if ablation_id is AblationId.A6:
        coordinate_actions = sum(result.coordinate_actions for result in full)
        return {
            "status": "EXERCISED" if coordinate_actions else "NOT_EXERCISED",
            "evidence": {"full_coordinate_actions": coordinate_actions},
            "boundary": "Salience cannot affect cases that advertise no coordinate action.",
        }
    if ablation_id is AblationId.A7:
        mismatches = sum(result.planned_prediction_mismatches for result in full)
        return {
            "status": "EXERCISED" if mismatches else "NOT_EXERCISED",
            "evidence": {"planned_prediction_mismatches": mismatches},
            "boundary": "Recovery can affect behavior only after a planned prediction mismatch.",
        }
    if ablation_id is AblationId.A8:
        correspondences = _event_total(full, "perception.object_correspondence_proposed")
        return {
            "status": ("TRACE_ONLY_NOT_POLICY_COUPLED" if correspondences else "NOT_EXERCISED"),
            "evidence": {"correspondence_receipts": correspondences},
            "boundary": (
                "Correspondence receipts are exercised but do not feed current symbolic entity "
                "construction, so this is not a behavioral object-tracking test."
            ),
        }
    if ablation_id is AblationId.A9:
        candidates = sum(result.information_positive_candidates for result in full)
        return {
            "status": "EXERCISED" if candidates else "NOT_EXERCISED",
            "evidence": {"positive_information_candidates": candidates},
            "boundary": "The term is exposed only when a candidate has positive information value.",
        }
    transitions = _event_total(full, "consequence.received")
    return {
        "status": "RUNTIME_ONLY" if transitions else "NOT_EXERCISED",
        "evidence": {"transition_lookups_available": transitions},
        "boundary": (
            "A10 selects bounded transition-summary lookup versus full-history scan; it is not "
            "a score mechanism, and latency/byte observations are descriptive."
        ),
    }


def _comparison(
    full: tuple[EpisodeResult, ...],
    ablated: tuple[EpisodeResult, ...],
    *,
    exposure: dict[str, JSONValue],
) -> dict[str, JSONValue]:
    if tuple(item.case_key for item in full) != tuple(item.case_key for item in ablated):
        raise ValueError("paired ablation case identities differ")
    paired: list[JSONValue] = []
    full_completion_advantage = 0
    ablated_minus_full_actions_at_equal_completion = 0
    comparable_completed = 0
    for reference, removed in zip(full, ablated, strict=True):
        completion_delta = int(reference.completed) - int(removed.completed)
        full_completion_advantage += completion_delta
        action_delta: int | None = None
        if reference.completed and removed.completed:
            comparable_completed += 1
            action_delta = removed.actions - reference.actions
            ablated_minus_full_actions_at_equal_completion += action_delta
        paired.append(
            {
                "ablation_actions": removed.actions,
                "ablation_completed": removed.completed,
                "ablation_score": removed.score,
                "actions_saved_by_full_at_equal_completion": action_delta,
                "case_key": reference.case_key,
                "completion_advantage_full": completion_delta,
                "full_actions": reference.actions,
                "full_completed": reference.completed,
                "full_score": reference.score,
                "partition": reference.partition,
                "seed": reference.seed,
            }
        )
    if full_completion_advantage > 0 or ablated_minus_full_actions_at_equal_completion > 0:
        behavioral_status = "MECHANISM_OBSERVED"
    elif full_completion_advantage < 0 or ablated_minus_full_actions_at_equal_completion < 0:
        behavioral_status = "FULL_COMPONENT_REGRESSION"
    else:
        behavioral_status = "MECHANISM_NOT_OBSERVED"
    exposure_status = exposure["status"]
    mechanism_status = "NOT_EXERCISED" if exposure_status == "NOT_EXERCISED" else behavioral_status
    return {
        "actions_saved_by_full_at_equal_completion": (
            ablated_minus_full_actions_at_equal_completion
        ),
        "comparable_completed_cases": comparable_completed,
        "completion_advantage_full": full_completion_advantage,
        "exposure": exposure,
        "behavioral_status": behavioral_status,
        "mechanism_status": mechanism_status,
        "paired": paired,
        "score_advantage_full": sum(item.score for item in full)
        - sum(item.score for item in ablated),
        "trace_bytes_delta_ablation_minus_full": sum(item.trace_bytes for item in ablated)
        - sum(item.trace_bytes for item in full),
        "trace_events_delta_ablation_minus_full": sum(item.trace_events for item in ablated)
        - sum(item.trace_events for item in full),
    }


def _representative(results: tuple[EpisodeResult, ...], *, completed: bool) -> JSONValue:
    match = next((result for result in results if result.completed is completed), None)
    if match is None:
        return None
    return {
        "case_key": match.case_key,
        "completed": match.completed,
        "trace_path": match.trace_path,
        "trace_tail_hash": match.trace_tail_hash,
    }


def measure_ablations(
    output_root: Path,
    *,
    protocol: AblationProtocol | None = None,
    selected_ablations: tuple[AblationId, ...] | None = None,
    git_commit: str = "working-tree-stage14",
    repository_dirty: bool = True,
    runtime_identity: dict[str, JSONValue] | None = None,
) -> dict[str, JSONValue]:
    """Run FULL once and each removal over the identical frozen case order."""

    frozen_protocol, frozen_ablations, protocol_manifest_hash = load_protocol_manifest()
    chosen_protocol = frozen_protocol if protocol is None else protocol
    chosen_ablations = frozen_ablations if selected_ablations is None else selected_ablations
    if not chosen_ablations or len(set(chosen_ablations)) != len(chosen_ablations):
        raise ValueError("selected ablations must be non-empty and unique")
    output_root.mkdir(parents=True, exist_ok=True)
    cases = _cases(chosen_protocol)
    full_features = preset_features(ControllerPreset.FULL)
    full = tuple(
        _run_episode(
            output_root,
            case=case,
            ordinal=ordinal,
            variant="FULL",
            features=full_features,
            protocol=chosen_protocol,
            git_commit=git_commit,
        )
        for ordinal, case in enumerate(cases)
    )
    variants: dict[str, tuple[EpisodeResult, ...]] = {"FULL": full}
    for ablation_id in chosen_ablations:
        variants[ablation_id.value] = tuple(
            _run_episode(
                output_root,
                case=case,
                ordinal=ordinal,
                variant=ablation_id.value,
                features=features_for_ablation(ablation_id),
                protocol=chosen_protocol,
                git_commit=git_commit,
            )
            for ordinal, case in enumerate(cases)
        )
    exposures: dict[str, dict[str, JSONValue]] = {
        ablation_id.value: _mechanism_exposure(full, ablation_id)
        for ablation_id in chosen_ablations
    }
    exposure_payload: dict[str, JSONValue] = {
        identifier: exposure for identifier, exposure in exposures.items()
    }
    comparisons: dict[str, JSONValue] = {
        ablation_id.value: {
            "component": ablation_spec(ablation_id).component,
            "disabled_feature": ablation_spec(ablation_id).disabled_feature,
            "expected_effect_surface": ablation_spec(ablation_id).expected_effect_surface,
            "question": ablation_spec(ablation_id).question,
            **_comparison(
                full,
                variants[ablation_id.value],
                exposure=exposures[ablation_id.value],
            ),
        }
        for ablation_id in chosen_ablations
    }
    semantic_results = {
        key: [result.semantic_dict() for result in value] for key, value in sorted(variants.items())
    }
    semantic_comparisons: dict[str, JSONValue] = {
        key: {field: value for field, value in comparison.items() if not field.startswith("trace_")}
        for key, raw_comparison in sorted(comparisons.items())
        if isinstance(raw_comparison, dict)
        for comparison in (raw_comparison,)
    }
    all_verified = all(result.verified for results in variants.values() for result in results)
    no_faults = all(result.fault is None for results in variants.values() for result in results)
    variant_payloads: dict[str, JSONValue] = {
        key: {
            "aggregate": _aggregate(results),
            "features": (
                full_features.to_dict()
                if key == "FULL"
                else features_for_ablation(AblationId(key)).to_dict()
            ),
            "raw_results": [result.to_dict() for result in results],
            "representative_failure": _representative(results, completed=False),
            "representative_success": _representative(results, completed=True),
        }
        for key, results in sorted(variants.items())
    }
    report: dict[str, JSONValue] = {
        "schema": ABLATION_SCHEMA,
        "status": "PASS" if all_verified and no_faults else "PARTIAL",
        "label": "synthetic",
        "verified": all_verified,
        "claim": "NO_GENERALIZATION_CLAIM",
        "ablation_boundaries": exposure_payload,
        "git_commit": git_commit,
        "dirty_worktree": repository_dirty,
        "protocol": chosen_protocol.to_dict(),
        "protocol_manifest": "src/arc3/ablations/protocol.v0.1.json",
        "protocol_manifest_hash": protocol_manifest_hash,
        "protocol_manifest_matches_run": (
            chosen_protocol == frozen_protocol and chosen_ablations == frozen_ablations
        ),
        "protocol_hash": sha256_json(chosen_protocol.to_dict()),
        "cases": [case.to_dict() for case in cases],
        "case_manifest_hash": sha256_json([case.to_dict() for case in cases]),
        "runtime": runtime_identity or {},
        "variants": variant_payloads,
        "comparisons": comparisons,
        "semantic_digest": sha256_json(
            {
                "cases": [case.to_dict() for case in cases],
                "comparisons": semantic_comparisons,
                "protocol": chosen_protocol.to_dict(),
                "results": semantic_results,
            }
        ),
        "limitations": [
            "The result is synthetic and cannot establish public or hidden-game generalization.",
            "A1 exercises durable controller memory/checkpoint persistence; the current integrated controller does not yet retrieve a learned cross-level game rule in this suite.",
            "A2 can only affect candidates after contradiction; cases that create no retained contradiction do not exercise it.",
            "A6 is isolated only in cases advertising coordinate actions.",
            "A7 is isolated only after a planned prediction mismatch.",
            "A8 currently changes correspondence receipts but not symbolic entity construction.",
            "A10 compares a bounded transition index with full-history scanning; timing is descriptive and is not used alone for a mechanism-benefit claim.",
            "No human action baselines are available, so no official or approximate RHAE is reported.",
        ],
    }
    return report


__all__ = [
    "ABLATION_SCHEMA",
    "DEFAULT_NAVIGATION_SEEDS",
    "DEFAULT_PROTOCOL_PATH",
    "PROTOCOL_SCHEMA",
    "AblationProtocol",
    "EpisodeResult",
    "load_protocol_manifest",
    "measure_ablations",
]
