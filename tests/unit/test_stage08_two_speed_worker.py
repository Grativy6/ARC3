"""Static and mock-only integrity tests for the isolated Stage 08 worker.

The tests deliberately do not open an ARC environment.  They exercise the
worker's sealed input/output, phase accounting, and receipt projections with
synthetic values so a public measurement cannot occur by importing this file.
"""

from __future__ import annotations

import copy
import importlib.util
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, cast

import pytest

from arc3.adapters import GridFrame, Observation
from arc3.config import ARC3Config, BudgetConfig
from arc3.evaluation.two_speed_measurement import (
    MeasurementVariant,
    build_measurement_matrix,
    canonical_measurement_hash,
    verify_canonical_object_hash,
)
from arc3.policy import ARC3Controller, ControllerPhase, ControllerPreset, RunContext
from arc3.trace import BlobStore
from arc3.types import ActionName, EnvironmentMode, GameId, GameStateName

ROOT = Path(__file__).resolve().parents[2]
WORKER_PATH = ROOT / "scripts" / "_stage08_two_speed_worker.py"


@pytest.fixture(scope="module")
def worker() -> ModuleType:
    """Load the executable worker without invoking its command-line entry point."""

    module_name = "_arc3_stage08_two_speed_worker_test"
    specification = importlib.util.spec_from_file_location(module_name, WORKER_PATH)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[module_name] = module
    specification.loader.exec_module(module)
    return module


def _spec(
    worker: ModuleType,
    root: Path,
    *,
    variant: MeasurementVariant = MeasurementVariant.BUILD_001_TWO_SPEED,
) -> dict[str, object]:
    cell = next(cell for cell in build_measurement_matrix() if cell.variant is variant)
    cell_root = (root / "cells" / cell.cell_id).resolve()
    recordings_root = (root / "recordings").resolve()
    source_commit = (
        worker._BUILD_000_COMMIT
        if variant is MeasurementVariant.FROZEN_BUILD_000_FULL
        else "1" * 40
    )
    source_tree = (
        worker._BUILD_000_TREE if variant is MeasurementVariant.FROZEN_BUILD_000_FULL else "2" * 40
    )
    unsigned: dict[str, object] = {
        "cell_id": cell.cell_id,
        "cell": cell.to_dict(),
        "cell_root": str(cell_root),
        "checkpoint_root": str(cell_root / "checkpoint"),
        "development_identity": cell.development.to_dict(),
        "environments_dir": str((root / "environments").resolve()),
        "measurement_matrix_sha256": worker._MEASUREMENT_MATRIX_SHA256,
        "measurement_plan_sha256": worker._MEASUREMENT_PLAN_SHA256,
        "predeclaration_sha256": worker._PREDECLARATION_SHA256,
        "recordings_dir": str(recordings_root / "cells" / f"{cell.ordinal:02d}-{cell.cell_id}"),
        "recordings_root": str(recordings_root),
        "schema": worker._SPEC_SCHEMA,
        "source_commit": source_commit,
        "source_root": str((root / "source").resolve()),
        "source_tree": source_tree,
        "trace_root": str(cell_root / "trace"),
        "variant": variant.value,
    }
    return cast(dict[str, object], worker._seal(unsigned, hash_field="spec_hash"))


def _reseal(worker: ModuleType, value: dict[str, object]) -> dict[str, object]:
    return cast(dict[str, object], worker._seal(value, hash_field="spec_hash"))


def _make_read_roots(spec: dict[str, object]) -> None:
    (Path(str(spec["source_root"])) / "src" / "arc3").mkdir(parents=True)
    Path(str(spec["environments_dir"])).mkdir(parents=True)


def _event(event_id: str, event_type: str, **payload: object) -> SimpleNamespace:
    return SimpleNamespace(
        event_hash=f"sha256:{event_id.encode('utf-8').hex():0<64}"[:71],
        event_id=event_id,
        event_type=event_type,
        game_id="ar25-0c556536",
        payload=payload,
    )


def _receipt_chain(
    worker: ModuleType,
    prefix: str,
    *,
    is_reset: bool,
    submission_ordinal: int,
    initial_semantic_frame_hash: str = "sha256:" + "b" * 64,
    initial_trace_frame_hash: str = "sha256:" + "d" * 64,
    returned_semantic_frame_hash: str = "sha256:" + "a" * 64,
    returned_trace_frame_hash: str = "sha256:" + "c" * 64,
) -> tuple[
    dict[str, object],
    list[SimpleNamespace],
    dict[str, tuple[str, ...]],
]:
    action = {"coordinate": None, "name": "RESET" if is_reset else "ACTION1"}
    observation_id = f"{prefix}-observation"
    selected_id = f"{prefix}-selected"
    validated_id = f"{prefix}-validated"
    submitted_id = f"{prefix}-submitted"
    consequence_id = f"{prefix}-consequence"
    after_observation_id = f"{prefix}-after-observation"
    decision_id = f"{prefix}-decision"
    initial_observation = {
        "available_actions": ["ACTION1", "RESET"],
        "frame_digest": initial_semantic_frame_hash,
        "full_reset": False,
        "game_id": "ar25-0c556536",
        "levels_completed": 0,
        "returned_action": None,
        "state": "NOT_FINISHED",
        "win_levels": 1,
    }
    returned_observation = {
        "available_actions": ["ACTION1", "RESET"],
        "frame_digest": returned_semantic_frame_hash,
        "full_reset": is_reset,
        "game_id": "ar25-0c556536",
        "levels_completed": 0,
        "returned_action": action,
        "state": "NOT_FINISHED",
        "win_levels": 1,
    }
    boundary: dict[str, object] = {
        "acknowledged_by_controller": True,
        "action": action,
        "action_ordinal": 0,
        "adapter_crossed": True,
        "boundary_status": "normal",
        "choose_wall_ns": 1,
        "consequence_event_id": consequence_id,
        "consequence_event_hash": _event(consequence_id, "unused").event_hash,
        "consequence_frame_hashes": [returned_semantic_frame_hash],
        "consequence_observation_event_hash": _event(after_observation_id, "unused").event_hash,
        "consequence_observation_event_id": after_observation_id,
        "consequence_returned": True,
        "consequence": returned_observation,
        "decision_id": decision_id,
        "environment_action_identity": worker._sha256_bytes(worker._canonical_json_bytes(action)),
        "failure_phase": None,
        "is_reset": is_reset,
        "observation_event_id": observation_id,
        "observation_before": initial_observation,
        "selected_event_id": selected_id,
        "submission_ordinal": submission_ordinal,
        "submitted_event_id": submitted_id,
        "validated_event_id": validated_id,
    }
    events = [
        _event(
            observation_id,
            "observation.received",
            available_actions=["ACTION1", "RESET"],
            frames=[{"frame_hash": initial_trace_frame_hash}],
            game_state="NOT_FINISHED",
            returned_action=None,
            upstream_metadata={
                "full_reset": False,
                "levels_completed": 0,
                "win_levels": 1,
            },
        ),
        _event(
            selected_id,
            "action.selected",
            decision_id=decision_id,
            selected_action=action,
            source_observation_event_id=observation_id,
        ),
        _event(
            validated_id,
            "action.validated",
            action=action,
            decision_id=decision_id,
            selected_event_id=selected_id,
        ),
        _event(
            submitted_id,
            "action.submitted",
            action=action,
            decision_id=decision_id,
            selected_event_id=selected_id,
            validated_event_id=validated_id,
        ),
        _event(
            consequence_id,
            "consequence.received",
            action=action,
            after_state="NOT_FINISHED",
            levels_completed=0,
            returned_action=action,
            returned_frames=[{"frame_hash": returned_trace_frame_hash}],
            selected_event_id=selected_id,
            submitted_action=action,
            submitted_event_id=submitted_id,
        ),
        _event(
            after_observation_id,
            "observation.received",
            available_actions=["ACTION1", "RESET"],
            frames=[{"frame_hash": returned_trace_frame_hash}],
            game_state="NOT_FINISHED",
            returned_action=action,
            upstream_metadata={
                "full_reset": is_reset,
                "levels_completed": 0,
                "win_levels": 1,
            },
        ),
    ]
    semantic_frame_hashes: dict[str, tuple[str, ...]] = {
        observation_id: (initial_semantic_frame_hash,),
        after_observation_id: (returned_semantic_frame_hash,),
    }
    return boundary, events, semantic_frame_hashes


def _minimal_boundary(*, is_reset: bool, status: str = "normal") -> dict[str, object]:
    return {
        "acknowledged_by_controller": status == "normal",
        "adapter_crossed": True,
        "boundary_status": status,
        "choose_wall_ns": 1,
        "consequence_returned": status in {"normal", "failed-after-return"},
        "environment_action_identity": "sha256:" + "a" * 64,
        "is_reset": is_reset,
    }


def _finalize_state(
    worker: ModuleType,
    tmp_path: Path,
    *,
    initial_error: Exception | None,
    boundary: dict[str, object] | None = None,
) -> Any:
    spec = _spec(
        worker,
        tmp_path,
        variant=MeasurementVariant.FROZEN_BUILD_000_FULL,
    )
    for key in ("checkpoint_root", "recordings_dir", "trace_root"):
        Path(str(spec[key])).mkdir(parents=True, exist_ok=True)
    if initial_error is None:
        (Path(str(spec["recordings_dir"])) / "fixture.jsonl").write_text("{}\n", encoding="utf-8")
    state = worker._WorkerState(
        spec=spec,
        source_identity={"git_commit": spec["source_commit"]},
        asset_before={"aggregate_sha256": "sha256:" + "b" * 64, "passed": True},
    )
    state.peak_rss_bytes = 1_024
    state.memory_sample_count = 1
    state.memory_sources.add("synthetic-fixture-rss")
    if boundary is not None:
        state.decision_attempts = 1
        state.attempted_boundaries.append(boundary)
        if boundary.get("submission_ordinal") is not None:
            state.submitted_boundaries.append(boundary)
            state.adapter_submissions = 1
            if boundary.get("is_reset") is True:
                state.reset_boundaries.append(boundary)
                state.resets = 1
            else:
                state.boundaries.append(boundary)
                state.environment_actions = 1
            if boundary.get("consequence_returned") is True:
                state.returned_count = 1
            if boundary.get("acknowledged_by_controller") is True:
                state.acknowledged_count = 1
    return state


def _patch_successful_finalization_dependencies(
    worker: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    *,
    projected: Callable[[Any], list[dict[str, object]]] | None = None,
) -> None:
    monkeypatch.setattr(
        worker,
        "_restore_checkpoint",
        lambda _state: {"path": "fixture", "restore_valid": True},
    )
    monkeypatch.setattr(
        worker,
        "_trace_receipt",
        lambda _state: (
            {"byte_length": 0, "replay_verified": True},
            [],
            {},
        ),
    )

    def project(
        state: Any,
        _events: object,
        _semantic_frame_hashes: object,
    ) -> tuple[list[dict[str, object]], dict[str, object]]:
        boundaries = (
            projected(state)
            if projected is not None
            else [dict(boundary) for boundary in state.submitted_boundaries]
        )
        return boundaries, {
            "action_receipts_complete": True,
            "available": False,
            "typed_deep_receipts_complete": None,
        }

    monkeypatch.setattr(worker, "_cadence_projection", project)
    monkeypatch.setattr(
        worker,
        "_score_projection",
        lambda _state: {
            "completed": False,
            "levels_completed": 0,
            "score": 0.0,
            "verified": True,
        },
    )
    monkeypatch.setattr(worker, "_update_peak", lambda _state: None)
    monkeypatch.setattr(worker, "_runtime_identity", lambda: {"fixture": True})
    monkeypatch.setattr(
        worker,
        "_runtime_environment",
        lambda: {"expected": {}, "observed": {}, "passed": True},
    )
    monkeypatch.setattr(worker, "_controller_fault_identities", lambda _events: [])


def test_worker_hashes_match_the_typed_canonical_contract(worker: ModuleType) -> None:
    payload: dict[str, object] = {
        "alpha": [1, True, None, "café"],
        "nested": {"z": 3.5, "a": "value"},
    }
    sealed = worker._seal(payload, hash_field="result_hash")

    assert sealed["result_hash"] == canonical_measurement_hash(payload)
    assert verify_canonical_object_hash(sealed, hash_field="result_hash")

    tampered = copy.deepcopy(sealed)
    tampered["nested"] = {"z": 4.5, "a": "value"}
    assert not verify_canonical_object_hash(tampered, hash_field="result_hash")


def test_worker_accepts_the_exact_frozen_specs(worker: ModuleType, tmp_path: Path) -> None:
    for variant in MeasurementVariant:
        spec = _spec(worker, tmp_path / variant.value, variant=variant)
        assert worker._validate_spec(spec) == spec


@pytest.mark.parametrize(
    ("case", "message"),
    [
        ("extra-field", "fields are not exact"),
        ("matrix", "matrix identity changed"),
        ("plan", "plan identity changed"),
        ("predeclaration", "predeclaration identity changed"),
        ("cell-fields", "cell fields are not exact"),
        ("cell-schedule", "cell schedule is invalid"),
        ("cell-rotation", "cell rotation is invalid"),
        ("cell-identity", "cell identity changed"),
    ],
)
def test_worker_rejects_spec_matrix_plan_and_schedule_drift(
    worker: ModuleType,
    tmp_path: Path,
    case: str,
    message: str,
) -> None:
    spec = _spec(worker, tmp_path)
    if case == "extra-field":
        spec["unexpected"] = "drift"
    elif case == "matrix":
        spec["measurement_matrix_sha256"] = "sha256:" + "0" * 64
    elif case == "plan":
        spec["measurement_plan_sha256"] = "sha256:" + "0" * 64
    elif case == "predeclaration":
        spec["predeclaration_sha256"] = "sha256:" + "0" * 64
    else:
        cell = copy.deepcopy(spec["cell"])
        assert isinstance(cell, dict)
        if case == "cell-fields":
            cell["unexpected"] = "drift"
        elif case == "cell-schedule":
            cell["ordinal"] = 19
        elif case == "cell-rotation":
            cell["variant"] = MeasurementVariant.FROZEN_BUILD_000_FULL.value
        else:
            cell["cell_id"] = "stage08-cell-tampered"
        spec["cell"] = cell
    spec = _reseal(worker, spec)

    with pytest.raises(ValueError, match=message):
        worker._validate_spec(spec)


def test_worker_rejects_an_invalid_spec_self_hash(worker: ModuleType, tmp_path: Path) -> None:
    spec = _spec(worker, tmp_path)
    spec["source_tree"] = "3" * 40

    with pytest.raises(ValueError, match="spec hash is invalid"):
        worker._validate_spec(spec)


def test_worker_paths_require_exact_fresh_contained_layout(
    worker: ModuleType, tmp_path: Path
) -> None:
    valid = _spec(worker, tmp_path / "valid")
    _make_read_roots(valid)
    projection = worker._validate_paths(valid)
    assert projection["cell_root"] == Path(str(valid["cell_root"])).as_posix()
    with pytest.raises(RuntimeError, match="must be fresh"):
        worker._validate_paths(valid)

    wrong_layout = _spec(worker, tmp_path / "wrong-layout")
    _make_read_roots(wrong_layout)
    wrong_layout["trace_root"] = str((tmp_path / "escaped-trace").resolve())
    with pytest.raises(RuntimeError, match="differ from the sealed cell layout"):
        worker._validate_paths(wrong_layout)

    overlap = _spec(worker, tmp_path / "overlap")
    source_root = Path(str(overlap["source_root"]))
    (source_root / "src" / "arc3").mkdir(parents=True)
    Path(str(overlap["environments_dir"])).mkdir(parents=True)
    overlap_cell = (source_root / "writable-cell").resolve()
    overlap["cell_root"] = str(overlap_cell)
    overlap["checkpoint_root"] = str(overlap_cell / "checkpoint")
    overlap["trace_root"] = str(overlap_cell / "trace")
    with pytest.raises(RuntimeError, match="overlaps a read-only source root"):
        worker._validate_paths(overlap)


def test_frozen_projection_preserves_interleaved_reset_order(worker: ModuleType) -> None:
    action_0, events_0, semantic_0 = _receipt_chain(
        worker, "a0", is_reset=False, submission_ordinal=0
    )
    reset, reset_events, reset_semantic = _receipt_chain(
        worker, "r0", is_reset=True, submission_ordinal=1
    )
    action_1, events_1, semantic_1 = _receipt_chain(
        worker, "a1", is_reset=False, submission_ordinal=2
    )
    state = worker._WorkerState(
        spec={"variant": MeasurementVariant.FROZEN_BUILD_000_FULL.value},
        source_identity={},
        asset_before={},
    )
    state.submitted_boundaries.extend((action_0, reset, action_1))

    projected, cadence = worker._cadence_projection(
        state,
        [*events_0, *reset_events, *events_1],
        {**semantic_0, **reset_semantic, **semantic_1},
    )

    assert [boundary["submission_ordinal"] for boundary in projected] == [0, 1, 2]
    assert [boundary["is_reset"] for boundary in projected] == [False, True, False]
    assert all(boundary["action_chain_valid"] is True for boundary in projected)
    assert cadence["action_receipts_complete"] is True


def test_action_chain_projection_fails_closed_on_link_tamper(worker: ModuleType) -> None:
    boundary, events, semantic_frame_hashes = _receipt_chain(
        worker, "tamper", is_reset=False, submission_ordinal=0
    )
    assert (
        worker._action_chain_projection(boundary, events, semantic_frame_hashes)[
            "action_chain_valid"
        ]
        is True
    )

    events[2].payload["selected_event_id"] = "wrong-selected-event"
    assert (
        worker._action_chain_projection(boundary, events, semantic_frame_hashes)[
            "action_chain_valid"
        ]
        is False
    )


@pytest.mark.parametrize(
    ("field", "tampered_value"),
    [
        ("frame_digest", "sha256:" + "f" * 64),
        ("full_reset", True),
        ("levels_completed", 1),
        ("win_levels", 2),
    ],
)
def test_action_chain_projection_fails_closed_on_returned_observation_tamper(
    worker: ModuleType,
    field: str,
    tampered_value: object,
) -> None:
    boundary, events, semantic_frame_hashes = _receipt_chain(
        worker, "returned-tamper", is_reset=False, submission_ordinal=0
    )
    consequence = cast(dict[str, object], boundary["consequence"])
    consequence[field] = tampered_value
    assert (
        worker._action_chain_projection(boundary, events, semantic_frame_hashes)[
            "action_chain_valid"
        ]
        is False
    )


def test_real_frame_hash_namespaces_are_distinct_and_jointly_validated(
    worker: ModuleType,
    tmp_path: Path,
) -> None:
    frame = GridFrame.from_rows(((1, 2), (3, 4)))
    blobs = BlobStore(tmp_path / "blobs")
    trace_receipt = blobs.put_frame(frame.cells)
    semantic_digest = str(frame.digest)
    assert trace_receipt.frame_hash != semantic_digest

    boundary, events, expected_semantic_hashes = _receipt_chain(
        worker,
        "real-hash-namespaces",
        is_reset=False,
        submission_ordinal=0,
        initial_semantic_frame_hash=semantic_digest,
        initial_trace_frame_hash=trace_receipt.frame_hash,
        returned_semantic_frame_hash=semantic_digest,
        returned_trace_frame_hash=trace_receipt.frame_hash,
    )
    descriptor = trace_receipt.to_payload()
    events[0].payload["frames"] = [descriptor]
    events[4].payload["returned_frames"] = [descriptor]
    events[5].payload["frames"] = [descriptor]

    observed_semantic_hashes = worker._verified_semantic_frame_hashes(
        SimpleNamespace(blobs=blobs),
        events,
    )

    assert observed_semantic_hashes == expected_semantic_hashes
    assert (
        worker._action_chain_projection(boundary, events, observed_semantic_hashes)[
            "action_chain_valid"
        ]
        is True
    )

    tampered = copy.deepcopy(events)
    tampered[5].payload["frames"][0]["frame_hash"] = "sha256:" + "f" * 64
    with pytest.raises(RuntimeError, match="trace frame identity changed"):
        worker._verified_semantic_frame_hashes(SimpleNamespace(blobs=blobs), tampered)


def test_real_close_restore_compares_the_checkpoint_compatible_phase(
    worker: ModuleType,
    tmp_path: Path,
) -> None:
    cell_root = tmp_path / "cell"
    context = RunContext(
        run_id="stage08-close-restore",
        episode_id="stage08-close-restore-episode",
        game_id="synthetic-stage08-close-restore",
        trace_root=cell_root / "trace",
        checkpoint_root=cell_root / "checkpoint",
        config=ARC3Config(
            mode=EnvironmentMode.SYNTHETIC,
            seed=7,
            profile="stage08-close-restore-test",
            budgets=BudgetConfig(max_actions=8, max_resets=8),
        ),
        git_commit="stage08-close-restore-test",
    )
    observation = Observation(
        game_id=GameId(context.game_id),
        frames=(GridFrame.from_rows(((0, 1), (1, 0))),),
        state=GameStateName.NOT_FINISHED,
        levels_completed=0,
        win_levels=1,
        available_actions=(ActionName.ACTION1,),
        full_reset=True,
    )
    controller = ARC3Controller(ControllerPreset.FULL)
    controller.reset(context)
    controller.observe(observation)
    checkpoint_compatible_snapshot = controller.snapshot
    state = worker._WorkerState(
        spec={
            "checkpoint_root": str(context.checkpoint_root),
            "trace_root": str(context.trace_root),
        },
        source_identity={},
        asset_before={},
    )
    state.context = context
    state.controller = controller

    worker._close_controller(state)
    assert checkpoint_compatible_snapshot.phase is ControllerPhase.OBSERVED
    assert controller.snapshot.phase is ControllerPhase.CLOSED

    receipt = worker._restore_checkpoint(state)

    assert receipt["restore_valid"] is True
    assert receipt["closed_snapshot_phase"] == ControllerPhase.CLOSED.value
    assert receipt["expected_snapshot"] == receipt["restored_snapshot"]
    expected = cast(dict[str, object], receipt["expected_snapshot"])
    assert expected["phase"] == ControllerPhase.OBSERVED.value


def test_cadence_projection_binds_nullable_ids_mode_schema_and_observation(
    worker: ModuleType,
) -> None:
    boundary, events, semantic_frame_hashes = _receipt_chain(
        worker, "cadence", is_reset=False, submission_ordinal=0
    )
    observation, selected, validated, submitted, consequence, after_observation = events
    path_event = _event(
        "cadence-path",
        "reasoning.path_selected",
        action_registry_identity="sha256:" + "1" * 64,
        budget_limits={
            "cache_capacity": 256,
            "coordinate_candidates": 64,
            "fast_streak": 4,
            "retrodicted_transitions": 8,
            "search_depth": 8,
            "search_nodes": 256,
        },
        cache_projection_hash="sha256:" + "2" * 64,
        cadence_mode="TWO_SPEED",
        configuration_hash="sha256:" + "3" * 64,
        goal_id=None,
        goal_revision=0,
        mechanics_epoch_id="epoch-0",
        observation_event_id=boundary["observation_event_id"],
        ordered_triggers=[],
        path="FAST",
        plan_id=None,
        schema="arc3.reasoning-cadence-selection.v0.1",
        state_id="state-0",
        trigger_source_event_ids=[],
        trigger_sources=[],
    )
    terminal = _event(
        "cadence-terminal",
        "reasoning.deliberation_completed",
        artifact_projection_hash="sha256:" + "4" * 64,
        budget_exhaustions=[],
        cache_hits=0,
        cache_invalidation_counts={},
        cache_misses=0,
        integer_work_counts={
            "compilation_invocations": 0,
            "prediction_invocations": 0,
            "retrodicted_transitions": 0,
            "search_expanded_nodes": 0,
            "simulation_invocations": 0,
        },
        path="FAST",
        path_selected_event_id=path_event.event_id,
        produced_goal_ids=[],
        produced_model_ids=[],
        produced_plan_ids=[],
        status="COMPLETED",
    )
    selected.payload["reasoning_completed_event_id"] = terminal.event_id
    selection = {
        key: path_event.payload[key]
        for key in (
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
        )
    }
    boundary["expected_reasoning_bindings"] = {
        "action_registry_identity": path_event.payload["action_registry_identity"],
        "budget_limits": path_event.payload["budget_limits"],
        "cache_projection_hash": path_event.payload["cache_projection_hash"],
        "configuration_hash": path_event.payload["configuration_hash"],
        "path_selected_event_id": path_event.event_id,
        "selection": selection,
        "terminal": {
            **terminal.payload,
            "event_type": terminal.event_type,
            "terminal_event_id": terminal.event_id,
        },
    }
    ordered_events = [
        observation,
        path_event,
        terminal,
        selected,
        validated,
        submitted,
        consequence,
        after_observation,
    ]
    state = worker._WorkerState(
        spec={"variant": MeasurementVariant.BUILD_001_TWO_SPEED.value},
        source_identity={},
        asset_before={},
    )
    state.cadence_config = SimpleNamespace(configuration_hash="sha256:" + "3" * 64)
    state.submitted_boundaries.append(boundary)

    _projected, cadence = worker._cadence_projection(state, ordered_events, semantic_frame_hashes)
    assert cadence["typed_deep_receipts_complete"] is True

    path_event.payload["observation_event_id"] = "wrong-observation"
    _projected, tampered = worker._cadence_projection(state, ordered_events, semantic_frame_hashes)
    assert tampered["typed_deep_receipts_complete"] is False

    path_event.payload["observation_event_id"] = boundary["observation_event_id"]
    for field, tampered_value in (
        ("budget_limits", {}),
        ("cache_projection_hash", "sha256:" + "9" * 64),
        ("action_registry_identity", "sha256:" + "8" * 64),
    ):
        original = copy.deepcopy(path_event.payload[field])
        path_event.payload[field] = tampered_value
        _projected, tampered = worker._cadence_projection(
            state, ordered_events, semantic_frame_hashes
        )
        assert tampered["typed_deep_receipts_complete"] is False
        path_event.payload[field] = original

    terminal.payload["artifact_projection_hash"] = "sha256:" + "7" * 64
    _projected, tampered = worker._cadence_projection(state, ordered_events, semantic_frame_hashes)
    assert tampered["typed_deep_receipts_complete"] is False


def test_boundary_phase_counts_preserve_partial_action_and_reset_attempts(
    worker: ModuleType,
) -> None:
    action = _minimal_boundary(is_reset=False, status="failed-after-return")
    action["submission_ordinal"] = 0
    reset = _minimal_boundary(is_reset=True, status="censored")
    reset["adapter_crossed"] = False
    reset["submission_ordinal"] = None
    state = worker._WorkerState(spec={}, source_identity={}, asset_before={})
    state.attempted_boundaries.extend((action, reset))
    state.submitted_boundaries.append(action)

    assert worker._boundary_phase_counts(state, is_reset=False) == {
        "acknowledged": 0,
        "attempted": 1,
        "returned": 1,
        "submitted": 1,
    }
    assert worker._boundary_phase_counts(state, is_reset=True) == {
        "acknowledged": 0,
        "attempted": 1,
        "returned": 0,
        "submitted": 0,
    }


def test_accept_excludes_live_binding_instrumentation_from_controller_totals(
    worker: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = worker._WorkerState(spec={}, source_identity={}, asset_before={})
    state.controller = SimpleNamespace(apply_consequence=lambda _observation: None)
    monkeypatch.setattr(worker, "_observation_payload", lambda _observation: {"state": "X"})
    boundary: dict[str, object] = {
        "choose_binding_cpu_ns": 5,
        "choose_binding_wall_ns": 7,
        "choose_checkpoint_cpu_ns": 10,
        "choose_checkpoint_wall_ns": 20,
        "choose_cpu_inclusive_ns": 100,
        "choose_wall_inclusive_ns": 200,
    }

    worker._accept(state, object(), boundary)

    assert boundary["choose_cpu_ns"] == 85
    assert boundary["choose_wall_ns"] == 173
    assert boundary["controller_total_cpu_ns"] == (
        boundary["choose_cpu_ns"]
        + cast(int, boundary["consequence_cpu_ns"])
        + cast(int, boundary["checkpoint_cpu_ns"])
    )
    assert boundary["controller_total_wall_ns"] == (
        boundary["choose_wall_ns"]
        + cast(int, boundary["consequence_wall_ns"])
        + cast(int, boundary["checkpoint_wall_ns"])
    )


def test_finalize_retains_partial_phase_counts_and_failure_status(
    worker: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    boundary = _minimal_boundary(is_reset=False, status="failed")
    boundary["submission_ordinal"] = 0
    state = _finalize_state(
        worker,
        tmp_path,
        initial_error=RuntimeError("synthetic adapter failure"),
        boundary=boundary,
    )
    state.execution_phase = "adapter-step"
    _patch_successful_finalization_dependencies(worker, monkeypatch)
    monkeypatch.setattr(worker, "_asset_identity", lambda _root: state.asset_before)
    monkeypatch.setattr(worker, "_validate_source", lambda _specification: state.source_identity)

    result = worker._finalize(state, error=RuntimeError("synthetic adapter failure"))

    assert result["status"] == "failure"
    assert result["failure_domain"] == "INFRASTRUCTURE"
    assert result["failure_phase"] == "adapter-step"
    assert result["action_counts"] == {
        "acknowledged": 0,
        "attempted": 1,
        "returned": 0,
        "submitted": 1,
    }
    assert result["reset_counts"] == {
        "acknowledged": 0,
        "attempted": 0,
        "returned": 0,
        "submitted": 0,
    }
    assert result["counts"]["predicates"]["typed_action_counts_monotone"] is True
    assert result["validation_failures"][0].startswith("execution:RuntimeError")
    assert verify_canonical_object_hash(result, hash_field="worker_result_hash")


@pytest.mark.parametrize("invalidity", ["unavailable", "mixed-source"])
def test_finalize_fails_closed_when_rss_evidence_is_invalid(
    worker: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    invalidity: str,
) -> None:
    state = _finalize_state(worker, tmp_path / invalidity, initial_error=None)
    if invalidity == "unavailable":
        state.peak_rss_bytes = None
        state.memory_sample_count = 0
        state.memory_invalid_count = 1
        state.memory_sources.clear()
    else:
        state.memory_sample_count = 2
        state.memory_sources.add("synthetic-second-rss-source")
    _patch_successful_finalization_dependencies(worker, monkeypatch)
    monkeypatch.setattr(worker, "_asset_identity", lambda _root: state.asset_before)
    monkeypatch.setattr(worker, "_validate_source", lambda _specification: state.source_identity)

    result = worker._finalize(state, error=None)

    assert result["status"] == "failure"
    assert result["memory"]["measurement_valid"] is False
    assert result["resources_valid"] is False
    assert result["failure_domain"] == "RESOURCE"
    assert result["failure_phase"] == "resources"
    assert any(item.startswith("resources:") for item in result["validation_failures"])


def test_memory_sampling_rejects_an_unnamed_source(
    worker: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = worker._WorkerState(spec={}, source_identity={}, asset_before={})
    monkeypatch.setattr(worker, "_memory_sample", lambda: {"peak_rss_bytes": 4_096})

    worker._update_peak(state)

    assert state.peak_rss_bytes is None
    assert state.memory_sample_count == 0
    assert state.memory_invalid_count == 1
    assert state.memory_sources == set()


@pytest.mark.parametrize("drift", ["asset", "source"])
def test_finalize_rejects_source_or_asset_drift(
    worker: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    drift: str,
) -> None:
    state = _finalize_state(worker, tmp_path / drift, initial_error=None)
    _patch_successful_finalization_dependencies(worker, monkeypatch)
    asset_after = (
        {"aggregate_sha256": "sha256:" + "c" * 64, "passed": True}
        if drift == "asset"
        else state.asset_before
    )
    source_after = {"git_commit": "changed"} if drift == "source" else state.source_identity
    monkeypatch.setattr(worker, "_asset_identity", lambda _root: asset_after)
    monkeypatch.setattr(worker, "_validate_source", lambda _specification: source_after)

    result = worker._finalize(state, error=None)

    assert result["status"] == "failure"
    expected = "asset-stability:" if drift == "asset" else "source-stability:"
    assert any(item.startswith(expected) for item in result["validation_failures"])


def test_score_projection_reconciles_all_observed_counters(worker: ModuleType) -> None:
    run = SimpleNamespace(
        actions=2,
        completed=False,
        game_id=worker._GAME_ID,
        levels_completed=1,
        resets=1,
        score=0.25,
        state=SimpleNamespace(value="NOT_FINISHED"),
    )
    state = worker._WorkerState(spec={}, source_identity={}, asset_before={})
    state.scorecard = SimpleNamespace(verified=True, runs=(run,), scorer="fixture-scorer")
    state.environment_actions = 2
    state.resets = 1
    state.final_observation = SimpleNamespace(
        levels_completed=1,
        state=SimpleNamespace(value="NOT_FINISHED"),
    )

    projection = worker._score_projection(state)
    assert projection["verified"] is True
    assert projection["official_run_actions"] == 2
    assert projection["official_run_resets"] == 1

    state.environment_actions = 3
    with pytest.raises(RuntimeError, match="disagrees with observed execution"):
        worker._score_projection(state)


def test_runtime_environment_requires_every_frozen_offline_value(
    worker: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    expected = {
        "ALL_PROXY": "",
        "HTTP_PROXY": "",
        "HTTPS_PROXY": "",
        "NO_PROXY": "*",
        "PIP_NO_INDEX": "1",
        "PYTHONHASHSEED": "0",
        "PYTHONNOUSERSITE": "1",
        "UV_OFFLINE": "1",
    }
    for key, value in expected.items():
        monkeypatch.setenv(key, value)
    assert worker._runtime_environment() == {
        "expected": expected,
        "observed": expected,
        "passed": True,
    }

    monkeypatch.setenv("PYTHONHASHSEED", "random")
    assert worker._runtime_environment()["passed"] is False


def test_source_validation_rejects_cleanliness_drift_through_git_mocks(
    worker: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = _spec(worker, tmp_path)
    source_root = Path(str(spec["source_root"]))
    (source_root / "src" / "arc3").mkdir(parents=True)

    def clean_git(_root: Path, *arguments: str) -> str:
        if arguments == ("rev-parse", "HEAD"):
            return str(spec["source_commit"])
        if arguments == ("rev-parse", "HEAD^{tree}"):
            return str(spec["source_tree"])
        if arguments == ("status", "--porcelain", "--untracked-files=all"):
            return ""
        raise AssertionError(arguments)

    monkeypatch.setattr(worker, "_git", clean_git)
    monkeypatch.setattr(worker, "_git_success", lambda *_args: True)
    assert worker._validate_source(spec)["dirty_worktree"] is False

    def dirty_git(root: Path, *arguments: str) -> str:
        if arguments == ("status", "--porcelain", "--untracked-files=all"):
            return " M src/arc3/policy/controller.py"
        return clean_git(root, *arguments)

    monkeypatch.setattr(worker, "_git", dirty_git)
    with pytest.raises(RuntimeError, match="not the exact clean declared identity"):
        worker._validate_source(spec)
