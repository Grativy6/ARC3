#!/usr/bin/env python3
"""Execute one frozen Stage 08 local-public timing cell in an isolated process.

This worker deliberately uses only the standard library until it has validated
the requested source checkout.  It can therefore load either the frozen Build
000 controller or the current Build 001 controller without mixing their Python
packages.  It never discovers games, downloads assets, or enables networking.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import time
import traceback
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import MethodType
from typing import Any, cast
from unittest.mock import patch

_SPEC_SCHEMA = "arc3.build-001.stage-08-worker-spec.v0.3"
_RESULT_SCHEMA = "arc3.build-001.stage-08-worker-result.v0.3"
_GAME_ID = "ar25-0c556536"
_STABLE_NAME = "ar25"
_VERSION = "0c556536"
_SEED = 7
_MAX_ACTIONS = 8
_MAX_RESETS = 8
_WORKER_WALL_SECONDS = 120.0
_EXPECTED_ASSET_SHA256 = "sha256:e796e615d2e10c93b849f9bf150308fbf84d624725deaf995d7ec2d1c2f86b22"
_PUBLIC_PARTITION_MANIFEST_SHA256 = (
    "sha256:682d5891c2aface54803d9bd1173c55ed21e89856e13b8a478fb9276ee963f2f"
)
_BUILD_000_COMMIT = "90ecf7267d5bb23d751d6f7ce3e8aa75f2f1a130"
_BUILD_000_TREE = "0cf6e00b2fcc399e7a99a62c20e91bb84d485f13"
_BUILD_001_BASELINE_COMMIT = "d0052555e721453746e4c443efea441da2cb4789"
_MEASUREMENT_MATRIX_SHA256 = (
    "sha256:ca507ee6e539e0544647aac792417b276806a848e656f2b7b4f1a368ba6b63a1"
)
_MEASUREMENT_PLAN_SHA256 = "sha256:b42326c4de76786982c07a18be2fcd73afe4583bdb11100e9cb6147b6c8e582c"
_PREDECLARATION_SHA256 = "sha256:3342b6e2635c0606391c9aea02b2fec0cf4c5642a3d38b95768a1b77b4520878"
_VARIANTS = {
    "FROZEN_BUILD_000_FULL",
    "BUILD_001_LEGACY_ALWAYS_DEEP",
    "BUILD_001_TWO_SPEED",
    "BUILD_001_TWO_SPEED_NO_PREDICTION_CACHE",
}


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _json_file_bytes(value: object) -> bytes:
    return _canonical_json_bytes(value) + b"\n"


def _sha256_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _seal(value: Mapping[str, object], *, hash_field: str) -> dict[str, object]:
    unsigned = {key: item for key, item in value.items() if key != hash_field}
    return {**unsigned, hash_field: _sha256_bytes(_canonical_json_bytes(unsigned))}


def _atomic_write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(_json_file_bytes(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _load_object(path: Path) -> dict[str, object]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return cast(dict[str, object], raw)


def _git(root: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        raise RuntimeError(f"git {' '.join(arguments)} failed: {completed.stderr.strip()[:300]}")
    return completed.stdout.strip()


def _git_success(root: Path, *arguments: str) -> bool:
    return (
        subprocess.run(
            ["git", "-C", str(root), *arguments],
            check=False,
            capture_output=True,
        ).returncode
        == 0
    )


def _validate_spec(raw: Mapping[str, object]) -> dict[str, object]:
    exact_fields = {
        "cell_id",
        "cell",
        "cell_root",
        "checkpoint_root",
        "development_identity",
        "environments_dir",
        "measurement_matrix_sha256",
        "measurement_plan_sha256",
        "predeclaration_sha256",
        "recordings_dir",
        "recordings_root",
        "schema",
        "source_commit",
        "source_root",
        "source_tree",
        "spec_hash",
        "trace_root",
        "variant",
    }
    if set(raw) != exact_fields:
        raise ValueError("Stage 08 worker spec fields are not exact")
    if raw.get("schema") != _SPEC_SCHEMA:
        raise ValueError("Stage 08 worker spec schema is unsupported")
    variant = raw.get("variant")
    if not isinstance(variant, str) or variant not in _VARIANTS:
        raise ValueError("Stage 08 worker variant is unsupported")
    if raw.get("measurement_matrix_sha256") != _MEASUREMENT_MATRIX_SHA256:
        raise ValueError("Stage 08 worker matrix identity changed")
    if raw.get("measurement_plan_sha256") != _MEASUREMENT_PLAN_SHA256:
        raise ValueError("Stage 08 worker plan identity changed")
    if raw.get("predeclaration_sha256") != _PREDECLARATION_SHA256:
        raise ValueError("Stage 08 worker predeclaration identity changed")
    expected = {
        "game_id": _GAME_ID,
        "partition": "development",
        "seed": _SEED,
        "max_actions": _MAX_ACTIONS,
        "max_resets": _MAX_RESETS,
        "worker_wall_seconds": _WORKER_WALL_SECONDS,
        "environment_mode": "LOCAL",
        "network_enabled": False,
        "acquire_missing": False,
        "asset_aggregate_sha256": _EXPECTED_ASSET_SHA256,
        "public_partition_manifest_sha256": _PUBLIC_PARTITION_MANIFEST_SHA256,
    }
    development = raw.get("development_identity")
    if not isinstance(development, Mapping):
        raise ValueError("Stage 08 worker development identity is missing")
    if set(development) != set(expected):
        raise ValueError("Stage 08 worker development identity fields are not exact")
    for key, value in expected.items():
        if development.get(key) != value:
            raise ValueError(f"Stage 08 worker rejected development identity field {key}")
    for key in (
        "cell_id",
        "cell_root",
        "source_root",
        "source_commit",
        "source_tree",
        "environments_dir",
        "recordings_dir",
        "recordings_root",
        "trace_root",
        "checkpoint_root",
    ):
        value = raw.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Stage 08 worker spec field {key} is invalid")
    for key in (
        "cell_root",
        "source_root",
        "environments_dir",
        "recordings_dir",
        "recordings_root",
        "trace_root",
        "checkpoint_root",
    ):
        if not Path(cast(str, raw[key])).is_absolute():
            raise ValueError(f"Stage 08 worker spec field {key} must be absolute")
    for key in ("source_commit", "source_tree"):
        value = cast(str, raw[key])
        if len(value) != 40 or any(character not in "0123456789abcdef" for character in value):
            raise ValueError(f"Stage 08 worker spec field {key} is not a full Git identity")
    spec_hash = raw.get("spec_hash")
    unsigned = {key: value for key, value in raw.items() if key != "spec_hash"}
    if spec_hash != _sha256_bytes(_canonical_json_bytes(unsigned)):
        raise ValueError("Stage 08 worker spec hash is invalid")
    if variant == "FROZEN_BUILD_000_FULL" and (
        raw["source_commit"] != _BUILD_000_COMMIT or raw["source_tree"] != _BUILD_000_TREE
    ):
        raise ValueError("frozen Build 000 worker identity changed")
    if variant != "FROZEN_BUILD_000_FULL" and raw["source_commit"] == _BUILD_000_COMMIT:
        raise ValueError("Build 001 worker cannot use the frozen Build 000 source")
    cell = raw.get("cell")
    if not isinstance(cell, Mapping):
        raise ValueError("Stage 08 worker cell is missing")
    expected_cell_fields = {
        "cell_id",
        "development_identity",
        "ordinal",
        "position",
        "repetition",
        "schema",
        "variant",
    }
    if set(cell) != expected_cell_fields or cell.get("schema") != (
        "arc3.build-001.stage-08.measurement-cell.v0.1"
    ):
        raise ValueError("Stage 08 worker cell fields are not exact")
    ordinal = cell.get("ordinal")
    repetition = cell.get("repetition")
    position = cell.get("position")
    if (
        not isinstance(ordinal, int)
        or isinstance(ordinal, bool)
        or not isinstance(repetition, int)
        or isinstance(repetition, bool)
        or not isinstance(position, int)
        or isinstance(position, bool)
        or not 0 <= repetition < 5
        or not 0 <= position < 4
        or ordinal != repetition * 4 + position
    ):
        raise ValueError("Stage 08 worker cell schedule is invalid")
    variant_order = (
        "FROZEN_BUILD_000_FULL",
        "BUILD_001_LEGACY_ALWAYS_DEEP",
        "BUILD_001_TWO_SPEED",
        "BUILD_001_TWO_SPEED_NO_PREDICTION_CACHE",
    )
    if cell.get("variant") != variant or variant != variant_order[(repetition + position) % 4]:
        raise ValueError("Stage 08 worker cell rotation is invalid")
    if cell.get("development_identity") != dict(development):
        raise ValueError("Stage 08 worker cell development identity changed")
    cell_core = {
        "development_identity": dict(development),
        "ordinal": ordinal,
        "position": position,
        "repetition": repetition,
        "variant": variant,
    }
    expected_cell_id = (
        f"stage08-cell-{ordinal:02d}-r{repetition}-p{position}-"
        f"{_sha256_bytes(_canonical_json_bytes(cell_core)).removeprefix('sha256:')[:16]}"
    )
    if cell.get("cell_id") != expected_cell_id or raw.get("cell_id") != expected_cell_id:
        raise ValueError("Stage 08 worker cell identity changed")
    return dict(raw)


def _validate_source(spec: Mapping[str, object]) -> dict[str, object]:
    source_root = Path(cast(str, spec["source_root"])).resolve()
    if not (source_root / "src/arc3").is_dir():
        raise RuntimeError("Stage 08 source root has no src/arc3 package")
    commit = _git(source_root, "rev-parse", "HEAD")
    tree = _git(source_root, "rev-parse", "HEAD^{tree}")
    status = _git(source_root, "status", "--porcelain", "--untracked-files=all")
    if commit != spec["source_commit"] or tree != spec["source_tree"] or status:
        raise RuntimeError("Stage 08 source checkout is not the exact clean declared identity")
    variant = cast(str, spec["variant"])
    baseline_ancestor = (
        True
        if variant == "FROZEN_BUILD_000_FULL"
        else _git_success(
            source_root, "merge-base", "--is-ancestor", _BUILD_001_BASELINE_COMMIT, "HEAD"
        )
    )
    if not baseline_ancestor:
        raise RuntimeError("Stage 08 Build 001 source does not descend from its frozen baseline")
    return {
        "build_001_baseline_ancestor": baseline_ancestor,
        "dirty_worktree": False,
        "git_commit": commit,
        "git_tree": tree,
        "source_root": source_root.as_posix(),
    }


def _validate_paths(spec: Mapping[str, object]) -> dict[str, str]:
    cell_root = Path(cast(str, spec["cell_root"])).resolve()
    source_root = Path(cast(str, spec["source_root"])).resolve()
    environments_dir = Path(cast(str, spec["environments_dir"])).resolve()
    recordings_root = Path(cast(str, spec["recordings_root"])).resolve()
    cell = cast(Mapping[str, object], spec["cell"])
    cell_id = cast(str, spec["cell_id"])
    ordinal = cast(int, cell["ordinal"])
    expected = {
        "checkpoint_root": cell_root / "checkpoint",
        "recordings_dir": recordings_root / "cells" / f"{ordinal:02d}-{cell_id}",
        "trace_root": cell_root / "trace",
    }
    observed = {
        key: Path(cast(str, spec[key])).resolve()
        for key in ("checkpoint_root", "recordings_dir", "trace_root")
    }
    if observed != expected:
        raise RuntimeError("Stage 08 worker output roots differ from the sealed cell layout")
    if cell_root.exists() or observed["recordings_dir"].exists():
        raise RuntimeError("Stage 08 worker writable cell and recording roots must be fresh")
    if not source_root.is_dir() or not environments_dir.is_dir():
        raise RuntimeError("Stage 08 worker read-only source roots are unavailable")
    protected = (source_root, environments_dir)
    writable = (cell_root, observed["recordings_dir"])
    for root in protected:
        for write_root in writable:
            try:
                write_root.relative_to(root)
            except ValueError:
                pass
            else:
                raise RuntimeError("Stage 08 writable root overlaps a read-only source root")
            try:
                root.relative_to(write_root)
            except ValueError:
                pass
            else:
                raise RuntimeError("Stage 08 read-only source root overlaps a writable root")
    for left, right in ((cell_root, recordings_root), (cell_root, observed["recordings_dir"])):
        try:
            left.relative_to(right)
        except ValueError:
            pass
        else:
            raise RuntimeError("Stage 08 cell and external recording roots overlap")
        try:
            right.relative_to(left)
        except ValueError:
            pass
        else:
            raise RuntimeError("Stage 08 cell and external recording roots overlap")
    if len(set(observed.values())) != len(observed):
        raise RuntimeError("Stage 08 worker output roots collide")
    cell_root.mkdir(parents=True, exist_ok=False)
    observed["recordings_dir"].parent.mkdir(parents=True, exist_ok=True)
    return {
        "cell_root": cell_root.as_posix(),
        "recordings_root": recordings_root.as_posix(),
        **{key: value.as_posix() for key, value in observed.items()},
    }


def _asset_identity(environments_dir: Path) -> dict[str, object]:
    directory = environments_dir.resolve() / _STABLE_NAME / _VERSION
    metadata = directory / "metadata.json"
    if not metadata.is_file():
        raise RuntimeError("frozen Stage 08 development asset is unavailable")
    files = tuple(
        (
            path.relative_to(directory).as_posix(),
            path.stat().st_size,
            _sha256_file(path),
        )
        for path in sorted(directory.rglob("*"))
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
    )
    aggregate = _sha256_bytes(_json_file_bytes(files))
    return {
        "aggregate_sha256": aggregate,
        "files": [{"bytes": size, "name": name, "sha256": digest} for name, size, digest in files],
        "game_id": _GAME_ID,
        "passed": aggregate == _EXPECTED_ASSET_SHA256,
        "source_semantically_inspected": False,
    }


def _directory_bytes(root: Path) -> int:
    if not root.is_dir():
        return 0
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file())


def _action_payload(action: object) -> dict[str, object]:
    typed_action = cast(Any, action)
    name = getattr(typed_action.name, "value", None)
    coordinate = typed_action.coordinate
    return {
        "coordinate": (None if coordinate is None else {"x": coordinate.x, "y": coordinate.y}),
        "name": name,
    }


def _observation_payload(observation: object) -> dict[str, object]:
    typed_observation = cast(Any, observation)
    frames = typed_observation.frames
    final_frame = frames[-1]
    state = getattr(typed_observation.state, "value", None)
    return {
        "available_actions": [
            getattr(action, "value", str(action)) for action in typed_observation.available_actions
        ],
        "frame_digest": str(final_frame.digest),
        "full_reset": bool(typed_observation.full_reset),
        "game_id": str(typed_observation.game_id),
        "levels_completed": int(typed_observation.levels_completed),
        "returned_action": (
            None
            if typed_observation.returned_action is None
            else _action_payload(typed_observation.returned_action)
        ),
        "state": state,
        "win_levels": int(typed_observation.win_levels),
    }


class _SocketDeny:
    """Count and reject the same five Python socket entry points as Stage 07."""

    def __init__(self) -> None:
        self.attempt_count = 0
        self._patches: list[Any] = []

    def _deny(self, *_args: object, **_kwargs: object) -> None:
        self.attempt_count += 1
        raise OSError("Stage 08 worker denies network access")

    def __enter__(self) -> _SocketDeny:
        self._patches = [
            patch("socket.create_connection", self._deny),
            patch("socket.getaddrinfo", self._deny),
            patch.object(socket.socket, "connect", self._deny),
            patch.object(socket.socket, "connect_ex", self._deny),
            patch.object(socket.socket, "sendto", self._deny),
        ]
        for active in self._patches:
            active.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        for active in reversed(self._patches):
            active.stop()


@dataclass(slots=True)
class _CheckpointTimer:
    wall_ns: int = 0
    cpu_ns: int = 0
    calls: int = 0

    def install(self, controller: Any) -> None:
        original = controller.checkpoint

        def measured(_controller: object, *args: object, **kwargs: object) -> object:
            wall_started = time.perf_counter_ns()
            cpu_started = time.process_time_ns()
            try:
                return original(*args, **kwargs)
            finally:
                self.wall_ns += max(0, time.perf_counter_ns() - wall_started)
                self.cpu_ns += max(0, time.process_time_ns() - cpu_started)
                self.calls += 1

        controller.checkpoint = MethodType(measured, controller)


@dataclass(slots=True)
class _WorkerState:
    spec: dict[str, object]
    source_identity: dict[str, object]
    asset_before: dict[str, object]
    started_wall_ns: int = field(default_factory=time.perf_counter_ns)
    started_cpu_ns: int = field(default_factory=time.process_time_ns)
    controller: Any | None = None
    controller_config: Any | None = None
    context: Any | None = None
    cadence_config: Any | None = None
    session: Any | None = None
    scorecard: Any | None = None
    checkpoint_timer: _CheckpointTimer = field(default_factory=_CheckpointTimer)
    attempted_boundaries: list[dict[str, object]] = field(default_factory=list)
    boundaries: list[dict[str, object]] = field(default_factory=list)
    submitted_boundaries: list[dict[str, object]] = field(default_factory=list)
    action_sequence: list[dict[str, object]] = field(default_factory=list)
    reset_boundaries: list[dict[str, object]] = field(default_factory=list)
    returned_consequences: list[dict[str, object]] = field(default_factory=list)
    environment_actions: int = 0
    resets: int = 0
    decision_attempts: int = 0
    adapter_submissions: int = 0
    returned_count: int = 0
    acknowledged_count: int = 0
    final_observation: Any | None = None
    peak_rss_bytes: int | None = None
    memory_sample_count: int = 0
    memory_invalid_count: int = 0
    memory_sources: set[str] = field(default_factory=set)
    network_attempt_count: int = 0
    network_guard: _SocketDeny | None = None
    controller_closed: bool = False
    session_closed: bool = False
    execution_phase: str = "worker-initialization"


def _memory_sample() -> dict[str, object]:
    try:
        from arc3.profiling.runtime import process_memory_sample

        raw = process_memory_sample()
        return dict(raw) if isinstance(raw, Mapping) else {}
    except Exception as error:  # pragma: no cover - platform fallback
        return {"reason": f"{type(error).__name__}: {error}", "peak_rss_bytes": None}


def _update_peak(state: _WorkerState) -> None:
    sample = _memory_sample()
    peak = sample.get("peak_rss_bytes")
    source = sample.get("measurement_source")
    if (
        isinstance(peak, int)
        and not isinstance(peak, bool)
        and peak >= 0
        and isinstance(source, str)
        and bool(source.strip())
    ):
        state.memory_sample_count += 1
        state.memory_sources.add(source)
        state.peak_rss_bytes = (
            peak if state.peak_rss_bytes is None else max(state.peak_rss_bytes, peak)
        )
    else:
        state.memory_invalid_count += 1


def _make_controller(state: _WorkerState) -> None:
    from arc3.config import ARC3Config, BudgetConfig
    from arc3.policy import ARC3Controller, ControllerPreset, RunContext
    from arc3.types import EnvironmentMode, GameId

    spec = state.spec
    budgets = BudgetConfig(
        max_actions=_MAX_ACTIONS,
        max_resets=_MAX_RESETS,
        decision_seconds=2.0,
        wall_clock_seconds=120.0,
        memory_megabytes=2048,
        max_coordinate_candidates=128,
        max_search_nodes=10_000,
        max_search_depth=32,
        max_trace_bytes=256 * 1024 * 1024,
    )
    config = ARC3Config.for_mode(
        EnvironmentMode.LOCAL,
        seed=_SEED,
        network_enabled=False,
        profile="stage08-two-speed-local-public",
        budgets=budgets,
    )
    context = RunContext(
        run_id=f"stage08:{spec['cell_id']}",
        episode_id=f"stage08:{spec['cell_id']}:episode",
        game_id=GameId(_GAME_ID),
        trace_root=Path(cast(str, spec["trace_root"])),
        checkpoint_root=Path(cast(str, spec["checkpoint_root"])),
        config=config,
        git_commit=cast(str, spec["source_commit"]),
        source_kind="arc3-stage08-local-public",
        source_version="0.1",
    )
    variant = cast(str, spec["variant"])
    if variant == "FROZEN_BUILD_000_FULL":
        controller = ARC3Controller(ControllerPreset.FULL)
        cadence_config = None
    else:
        from arc3.policy import CadenceConfig, DeliberationMode

        cadence_config = CadenceConfig(
            mode=(
                DeliberationMode.LEGACY_ALWAYS_DEEP
                if variant == "BUILD_001_LEGACY_ALWAYS_DEEP"
                else DeliberationMode.TWO_SPEED
            ),
            maximum_fast_streak=4,
            repeated_no_progress_threshold=2,
            prediction_cache_enabled=(variant != "BUILD_001_TWO_SPEED_NO_PREDICTION_CACHE"),
            cache_capacity=256,
        )
        controller = ARC3Controller(ControllerPreset.FULL, cadence_config=cadence_config)
    state.controller = controller
    state.controller_config = config
    state.context = context
    state.cadence_config = cadence_config
    state.checkpoint_timer.install(controller)


def _open_session(state: _WorkerState) -> None:
    from arc3.adapters.arc_agi import ArcAGIAdapter

    spec = state.spec
    if state.controller_config is None:
        raise RuntimeError("Stage 08 controller configuration is unavailable")
    adapter = ArcAGIAdapter(
        state.controller_config,
        environments_dir=Path(cast(str, spec["environments_dir"])),
        recordings_dir=Path(cast(str, spec["recordings_dir"])),
        save_recording=True,
        include_frame_data=True,
        environ={},
    )
    session = adapter.open(_GAME_ID, seed=_SEED)
    if str(session.observation.game_id) != _GAME_ID:
        raise RuntimeError("Stage 08 adapter returned the wrong game identity")
    state.session = session
    state.final_observation = session.observation


def _reasoning_binding_before_choose(state: _WorkerState) -> dict[str, object] | None:
    """Capture live Build 001 cadence state independently of emitted trace payloads."""

    if state.spec.get("variant") == "FROZEN_BUILD_000_FULL":
        return None
    if state.controller is None or state.controller_config is None or state.cadence_config is None:
        raise RuntimeError("Stage 08 cadence binding lacks controller configuration")
    controller = state.controller
    selection = getattr(controller, "_reasoning_selection", None)
    selected_event_id = getattr(controller, "_reasoning_selected_event_id", None)
    if selection is None or not isinstance(selected_event_id, str) or not selected_event_id:
        raise RuntimeError("Stage 08 cadence binding lacks a selected reasoning path")
    budgets = state.controller_config.budgets
    budget_limits = {
        "cache_capacity": state.cadence_config.cache_capacity,
        "coordinate_candidates": budgets.max_coordinate_candidates,
        "fast_streak": state.cadence_config.maximum_fast_streak,
        "retrodicted_transitions": budgets.max_actions,
        "search_depth": budgets.max_search_depth,
        "search_nodes": budgets.max_search_nodes,
    }
    action_registry_projection = controller._action_effects.projection()
    return {
        "action_registry_identity": _sha256_bytes(
            _canonical_json_bytes(action_registry_projection)
        ),
        "budget_limits": budget_limits,
        "cache_projection_hash": str(controller._prediction_cache.projection_hash),
        "configuration_hash": str(state.cadence_config.configuration_hash),
        "path_selected_event_id": selected_event_id,
        "selection": selection.to_dict(),
    }


def _reasoning_binding_after_choose(
    state: _WorkerState,
    before: Mapping[str, object] | None,
) -> dict[str, object] | None:
    """Recompute the terminal cadence receipt from live controller state."""

    if before is None:
        return None
    assert state.controller is not None
    controller = state.controller
    selection = getattr(controller, "_reasoning_selection", None)
    completed_event_id = getattr(controller, "_reasoning_completed_event_id", None)
    if selection is None or not isinstance(completed_event_id, str) or not completed_event_id:
        raise RuntimeError("Stage 08 cadence binding lacks a terminal reasoning receipt")
    before_artifacts = getattr(controller, "_reasoning_before_artifacts", None)
    if not isinstance(before_artifacts, tuple) or len(before_artifacts) != 3:
        raise RuntimeError("Stage 08 cadence binding lacks its prior artifact inventory")
    before_models, before_goals, before_plans = before_artifacts
    after_models, after_goals, after_plans = controller._reasoning_artifacts()
    produced_models = sorted(after_models - before_models)
    produced_goals = sorted(after_goals - before_goals)
    produced_plans = sorted(after_plans - before_plans)
    work_counts = {
        **controller._reasoning_work_counts,
        "goal_records_after": len(after_goals),
        "hypothesis_records_after": len(controller._hypotheses.all()),
        "hypothesis_records_before": controller._reasoning_before_hypotheses,
        "model_records_after": len(after_models),
        "preserved_transitions_available": (
            len(controller._transitions) if selection.path.value == "DEEP" else 0
        ),
        "produced_plans": len(produced_plans),
    }
    cache_projection_hash = str(controller._prediction_cache.projection_hash)
    artifact_projection_hash = _sha256_bytes(
        _canonical_json_bytes(
            {
                "cache_projection_hash": cache_projection_hash,
                "goal_ids": sorted(after_goals),
                "model_ids": sorted(after_models),
                "plan_ids": sorted(after_plans),
                "selection_hash": _sha256_bytes(_canonical_json_bytes(before["selection"])),
                "work_counts": work_counts,
            }
        )
    )
    status = controller._reasoning_terminal_status.value
    terminal = {
        "artifact_projection_hash": artifact_projection_hash,
        "budget_exhaustions": sorted(set(controller._reasoning_budget_exhaustions)),
        "cache_hits": (controller._prediction_cache.hits - controller._reasoning_before_cache_hits),
        "cache_invalidation_counts": {
            reason.value: count
            for reason, count in controller._prediction_cache.invalidation_counts.items()
        },
        "cache_misses": (
            controller._prediction_cache.misses - controller._reasoning_before_cache_misses
        ),
        "event_type": (
            "reasoning.fallback_used"
            if status == "FALLBACK_USED"
            else "reasoning.deliberation_completed"
        ),
        "integer_work_counts": work_counts,
        "path": selection.path.value,
        "path_selected_event_id": before["path_selected_event_id"],
        "produced_goal_ids": produced_goals,
        "produced_model_ids": produced_models,
        "produced_plan_ids": produced_plans,
        "status": status,
        "terminal_event_id": completed_event_id,
    }
    return {**before, "terminal": terminal}


def _select(state: _WorkerState, observation: Any) -> tuple[Any, dict[str, object]]:
    assert state.controller is not None
    controller = state.controller
    checkpoint_wall_before = state.checkpoint_timer.wall_ns
    checkpoint_cpu_before = state.checkpoint_timer.cpu_ns
    wall_started = time.perf_counter_ns()
    cpu_started = time.process_time_ns()
    if not state.boundaries and not state.reset_boundaries:
        state.execution_phase = "controller-reset"
        controller.reset(state.context)
        state.execution_phase = "controller-observe"
        controller.observe(observation)
    binding_cpu_started = time.process_time_ns()
    binding_wall_started = time.perf_counter_ns()
    reasoning_binding = _reasoning_binding_before_choose(state)
    binding_cpu_ns = max(0, time.process_time_ns() - binding_cpu_started)
    binding_wall_ns = max(0, time.perf_counter_ns() - binding_wall_started)
    state.execution_phase = "controller-choose"
    decision = controller.choose_action()
    choose_cpu_inclusive = max(0, time.process_time_ns() - cpu_started)
    choose_wall_inclusive = max(0, time.perf_counter_ns() - wall_started)
    reasoning_binding = _reasoning_binding_after_choose(state, reasoning_binding)
    action = _action_payload(decision.action)
    boundary = {
        "acknowledged_by_controller": False,
        "action": action,
        "adapter_crossed": False,
        "boundary_status": "censored",
        "consequence_returned": False,
        "decision_id": getattr(decision, "decision_id", None),
        "environment_action_identity": _sha256_bytes(_canonical_json_bytes(action)),
        "failure_phase": None,
        "observation_before": _observation_payload(observation),
        "observation_event_id": getattr(decision, "observation_event_id", None),
        "selected_event_id": getattr(decision, "selected_event_id", None),
        "submitted_event_id": getattr(decision, "submitted_event_id", None),
        "validated_event_id": getattr(decision, "validated_event_id", None),
        "choose_cpu_inclusive_ns": choose_cpu_inclusive,
        "choose_wall_inclusive_ns": choose_wall_inclusive,
        "choose_checkpoint_cpu_ns": state.checkpoint_timer.cpu_ns - checkpoint_cpu_before,
        "choose_checkpoint_wall_ns": state.checkpoint_timer.wall_ns - checkpoint_wall_before,
        "choose_binding_cpu_ns": binding_cpu_ns,
        "choose_binding_wall_ns": binding_wall_ns,
        "expected_reasoning_bindings": reasoning_binding,
    }
    boundary["checkpoint_cpu_ns"] = boundary["choose_checkpoint_cpu_ns"]
    boundary["checkpoint_wall_ns"] = boundary["choose_checkpoint_wall_ns"]
    boundary["choose_cpu_ns"] = max(
        0,
        choose_cpu_inclusive - cast(int, boundary["choose_checkpoint_cpu_ns"]) - binding_cpu_ns,
    )
    boundary["choose_wall_ns"] = max(
        0,
        choose_wall_inclusive - cast(int, boundary["choose_checkpoint_wall_ns"]) - binding_wall_ns,
    )
    return decision.action, boundary


def _accept(state: _WorkerState, observation: Any, boundary: dict[str, object]) -> None:
    assert state.controller is not None
    checkpoint_wall_before = state.checkpoint_timer.wall_ns
    checkpoint_cpu_before = state.checkpoint_timer.cpu_ns
    wall_started = time.perf_counter_ns()
    cpu_started = time.process_time_ns()
    receipt: Any | None = None
    try:
        state.execution_phase = "controller-consequence"
        receipt = state.controller.apply_consequence(observation)
    finally:
        consequence_cpu_inclusive = max(0, time.process_time_ns() - cpu_started)
        consequence_wall_inclusive = max(0, time.perf_counter_ns() - wall_started)
        consequence_checkpoint_cpu = state.checkpoint_timer.cpu_ns - checkpoint_cpu_before
        consequence_checkpoint_wall = state.checkpoint_timer.wall_ns - checkpoint_wall_before
        choose_cpu_inclusive = cast(int, boundary["choose_cpu_inclusive_ns"])
        choose_wall_inclusive = cast(int, boundary["choose_wall_inclusive_ns"])
        choose_checkpoint_cpu = cast(int, boundary["choose_checkpoint_cpu_ns"])
        choose_checkpoint_wall = cast(int, boundary["choose_checkpoint_wall_ns"])
        choose_binding_cpu = cast(int, boundary["choose_binding_cpu_ns"])
        choose_binding_wall = cast(int, boundary["choose_binding_wall_ns"])
        checkpoint_cpu = choose_checkpoint_cpu + consequence_checkpoint_cpu
        checkpoint_wall = choose_checkpoint_wall + consequence_checkpoint_wall
        boundary.update(
            {
                "checkpoint_cpu_ns": checkpoint_cpu,
                "checkpoint_wall_ns": checkpoint_wall,
                "choose_cpu_ns": max(
                    0,
                    choose_cpu_inclusive - choose_checkpoint_cpu - choose_binding_cpu,
                ),
                "choose_wall_ns": max(
                    0,
                    choose_wall_inclusive - choose_checkpoint_wall - choose_binding_wall,
                ),
                "consequence": _observation_payload(observation),
                "consequence_cpu_inclusive_ns": consequence_cpu_inclusive,
                "consequence_cpu_ns": max(
                    0, consequence_cpu_inclusive - consequence_checkpoint_cpu
                ),
                "consequence_event_id": (
                    None if receipt is None else getattr(receipt, "consequence_event_id", None)
                ),
                "consequence_event_hash": (
                    None if receipt is None else getattr(receipt, "consequence_event_hash", None)
                ),
                "consequence_frame_hashes": (
                    []
                    if receipt is None
                    else list(getattr(receipt.observation_receipt, "frame_hashes", ()))
                ),
                "consequence_observation_event_hash": (
                    None
                    if receipt is None
                    else getattr(receipt.observation_receipt, "observation_event_hash", None)
                ),
                "consequence_observation_event_id": (
                    None
                    if receipt is None
                    else getattr(receipt.observation_receipt, "observation_event_id", None)
                ),
                "consequence_wall_inclusive_ns": consequence_wall_inclusive,
                "consequence_wall_ns": max(
                    0, consequence_wall_inclusive - consequence_checkpoint_wall
                ),
                "controller_total_cpu_ns": (
                    choose_cpu_inclusive + consequence_cpu_inclusive - choose_binding_cpu
                ),
                "controller_total_wall_ns": (
                    choose_wall_inclusive + consequence_wall_inclusive - choose_binding_wall
                ),
            }
        )
    boundary["acknowledged_by_controller"] = True
    boundary["boundary_status"] = "normal"


def _run_episode(state: _WorkerState) -> None:
    from arc3.types import ActionName, GameStateName

    assert state.session is not None
    observation = state.session.observation
    while state.environment_actions < _MAX_ACTIONS:
        if observation.state is GameStateName.WIN:
            break
        state.decision_attempts += 1
        action, boundary = _select(state, observation)
        action_payload = cast(dict[str, object], boundary["action"])
        is_reset = action.name is ActionName.RESET
        boundary["is_reset"] = is_reset
        boundary["submission_ordinal"] = None
        boundary["action_ordinal"] = (
            len(state.reset_boundaries) if is_reset else len(state.boundaries)
        )
        state.attempted_boundaries.append(boundary)
        if action.name is ActionName.RESET and state.resets >= _MAX_RESETS:
            boundary["boundary_status"] = "censored"
            boundary["failure_phase"] = "worker-reset-budget-before-adapter"
            raise RuntimeError("Stage 08 controller exceeded the frozen reset budget")
        boundary["submission_ordinal"] = len(state.submitted_boundaries)
        state.submitted_boundaries.append(boundary)
        state.action_sequence.append(action_payload)
        if is_reset:
            state.resets += 1
            state.reset_boundaries.append(boundary)
        else:
            state.environment_actions += 1
            state.boundaries.append(boundary)
        state.adapter_submissions += 1
        boundary["adapter_crossed"] = True
        try:
            state.execution_phase = "adapter-step"
            returned = state.session.step(
                action,
                reasoning={
                    "category": "stage08-two-speed-measurement",
                    "summary": "generic offline controller; no game-specific policy rule",
                },
            )
        except Exception:
            boundary["boundary_status"] = "failed"
            boundary["failure_phase"] = "adapter-step"
            raise
        state.returned_count += 1
        boundary["consequence_returned"] = True
        state.returned_consequences.append(_observation_payload(returned))
        try:
            _accept(state, returned, boundary)
        except Exception:
            boundary["boundary_status"] = "failed"
            boundary["consequence"] = _observation_payload(returned)
            boundary["failure_phase"] = "controller-consequence-fold"
            state.final_observation = returned
            raise
        state.acknowledged_count += 1
        observation = returned
        state.final_observation = returned
        _update_peak(state)
    state.execution_phase = "adapter-close"
    state.scorecard = state.session.close()
    state.session_closed = True


def _close_controller(state: _WorkerState) -> None:
    if state.controller is None or state.controller_closed:
        return
    state.controller.close()
    state.controller_closed = True


def _restore_checkpoint(state: _WorkerState) -> dict[str, object]:
    if state.controller is None or state.context is None:
        return {"path": None, "restore_valid": False, "reason": "controller-unavailable"}
    checkpoint = getattr(state.controller, "_last_checkpoint", None)
    path = getattr(checkpoint, "path", None)
    if not isinstance(path, Path) or not path.is_file():
        return {"path": None, "restore_valid": False, "reason": "checkpoint-unavailable"}
    from arc3.policy import ARC3Controller, ControllerPreset

    original_trace_root = Path(cast(str, state.spec["trace_root"])).resolve()
    original_checkpoint_root = Path(cast(str, state.spec["checkpoint_root"])).resolve()
    restore_root = original_trace_root.parent / "restore-validation"
    restore_trace_root = restore_root / "trace"
    restore_checkpoint_root = restore_root / "checkpoint"
    if restore_root.exists():
        raise RuntimeError("Stage 08 checkpoint restore target already exists")
    shutil.copytree(original_trace_root, restore_trace_root)
    shutil.copytree(original_checkpoint_root, restore_checkpoint_root)
    try:
        relative_checkpoint = path.resolve().relative_to(original_checkpoint_root)
    except ValueError as error:
        raise RuntimeError("Stage 08 checkpoint escaped its declared root") from error
    copied_checkpoint = restore_checkpoint_root / relative_checkpoint
    if not copied_checkpoint.is_file() or _sha256_file(copied_checkpoint) != _sha256_file(path):
        raise RuntimeError("Stage 08 copied checkpoint identity changed")
    restore_context = replace(
        state.context,
        trace_root=restore_trace_root,
        checkpoint_root=restore_checkpoint_root,
    )

    expected_snapshot = state.controller.snapshot
    checkpoint_phase = getattr(checkpoint, "phase", None)
    checkpoint_phase_value = getattr(checkpoint_phase, "value", None)
    if not isinstance(checkpoint_phase_value, str):
        raise RuntimeError("Stage 08 checkpoint-compatible controller phase is unavailable")
    if state.cadence_config is None:
        restored = ARC3Controller.restore(
            restore_context,
            preset=ControllerPreset.FULL,
            checkpoint_path=copied_checkpoint,
        )
    else:
        restored = ARC3Controller.restore(
            restore_context,
            preset=ControllerPreset.FULL,
            checkpoint_path=copied_checkpoint,
            cadence_config=state.cadence_config,
        )
    try:
        pending = getattr(restored.snapshot, "pending_action", None)
        expected_projection = {
            "actions_used": expected_snapshot.actions_used,
            "active_goal_ids": list(expected_snapshot.active_goal_ids),
            "active_hypothesis_ids": list(expected_snapshot.active_hypothesis_ids),
            "active_world_model_ids": list(expected_snapshot.active_world_model_ids),
            "fault_count": expected_snapshot.fault_count,
            "level_index": expected_snapshot.level_index,
            "pending_action": (
                None
                if expected_snapshot.pending_action is None
                else _action_payload(expected_snapshot.pending_action)
            ),
            # ``close`` deliberately changes only the live wrapper phase to
            # CLOSED *after* writing the final resumable checkpoint.  Compare
            # against the phase captured by that checkpoint rather than the
            # non-resumable post-close wrapper phase.
            "phase": checkpoint_phase_value,
            "resets_used": expected_snapshot.resets_used,
            "step_index": expected_snapshot.step_index,
        }
        restored_snapshot = restored.snapshot
        restored_projection = {
            "actions_used": restored_snapshot.actions_used,
            "active_goal_ids": list(restored_snapshot.active_goal_ids),
            "active_hypothesis_ids": list(restored_snapshot.active_hypothesis_ids),
            "active_world_model_ids": list(restored_snapshot.active_world_model_ids),
            "fault_count": restored_snapshot.fault_count,
            "level_index": restored_snapshot.level_index,
            "pending_action": None if pending is None else _action_payload(pending),
            "phase": restored_snapshot.phase.value,
            "resets_used": restored_snapshot.resets_used,
            "step_index": restored_snapshot.step_index,
        }
        if restored_projection != expected_projection:
            raise RuntimeError("Stage 08 restored terminal controller snapshot changed")
        return {
            "checkpoint_sha256": _sha256_file(path),
            "closed_snapshot_phase": expected_snapshot.phase.value,
            "expected_snapshot": expected_projection,
            "next_action_equivalence_tested": False,
            "path": path.resolve().as_posix(),
            "pending_action": None if pending is None else _action_payload(pending),
            "restore_copy_path": copied_checkpoint.resolve().as_posix(),
            "restore_scope": "terminal-snapshot-only; FAST/DEEP next-action equivalence is tested separately",
            "restored_snapshot": restored_projection,
            "restore_valid": True,
        }
    finally:
        restored.close()


def _verified_semantic_frame_hashes(
    journal: Any,
    events: Sequence[Any],
) -> dict[str, tuple[str, ...]]:
    """Bind trace blob identities to normalized ``GridFrame`` identities.

    Trace frame descriptors hash their canonical JSON blob representation,
    while ``GridFrame.digest`` hashes a domain-separated binary grid.  Both are
    valid but intentionally distinct identities, so evidence validation must
    verify each namespace rather than compare them directly.
    """

    from arc3.adapters import GridFrame

    semantic_by_observation: dict[str, tuple[str, ...]] = {}
    for event in events:
        if event.event_type != "observation.received":
            continue
        raw_frames = event.payload.get("frames")
        if not isinstance(raw_frames, list) or not raw_frames:
            raise RuntimeError("Stage 08 observation trace frame descriptors are unavailable")
        semantic_hashes: list[str] = []
        for raw_descriptor in raw_frames:
            if not isinstance(raw_descriptor, Mapping):
                raise RuntimeError("Stage 08 observation trace frame descriptor is invalid")
            blob_hash = raw_descriptor.get("blob_hash")
            trace_frame_hash = raw_descriptor.get("frame_hash")
            if not isinstance(blob_hash, str) or not isinstance(trace_frame_hash, str):
                raise RuntimeError("Stage 08 observation trace frame hashes are invalid")
            rows = journal.blobs.get_frame(blob_hash)
            normalized_rows = [list(row) for row in rows]
            observed_trace_frame_hash = _sha256_bytes(_canonical_json_bytes(normalized_rows))
            frame = GridFrame.from_rows(rows)
            if (
                observed_trace_frame_hash != trace_frame_hash
                or raw_descriptor.get("width") != frame.width
                or raw_descriptor.get("height") != frame.height
                or raw_descriptor.get("palette") != list(frame.palette)
            ):
                raise RuntimeError("Stage 08 observation trace frame identity changed")
            semantic_hashes.append(str(frame.digest))
        semantic_by_observation[event.event_id] = tuple(semantic_hashes)
    return semantic_by_observation


def _trace_receipt(
    state: _WorkerState,
) -> tuple[dict[str, object], list[Any], dict[str, tuple[str, ...]]]:
    from arc3.trace import EventJournal, ReplayEngine

    trace_root = Path(cast(str, state.spec["trace_root"]))
    run_id = f"stage08:{state.spec['cell_id']}"
    journal = EventJournal(trace_root, run_id=run_id, fsync_on_flush=False)
    try:
        if journal.active_path.is_file() and journal.active_path.stat().st_size:
            journal.seal()
        events = list(ReplayEngine(journal).verify_integrity(verify_blobs=True))
        semantic_frame_hashes = _verified_semantic_frame_hashes(journal, events)
        counts: dict[str, int] = {}
        for event in events:
            counts[event.event_type] = counts.get(event.event_type, 0) + 1
        receipt = {
            "byte_length": _directory_bytes(trace_root),
            "event_count": len(events),
            "event_type_counts": counts,
            "frame_namespace_validation": {
                "observation_event_count": len(semantic_frame_hashes),
                "semantic_frame_digest_count": sum(
                    len(items) for items in semantic_frame_hashes.values()
                ),
                "semantic_grid_digests_derived": True,
                "trace_blob_hashes_verified": True,
                "trace_frame_hashes_verified": True,
            },
            "manifest_hash": journal.manifest.manifest_hash,
            "path": trace_root.resolve().as_posix(),
            "replay_verified": True,
            "tail_event_hash": events[-1].event_hash if events else None,
        }
        return receipt, events, semantic_frame_hashes
    finally:
        journal.close()


def _action_chain_projection(
    boundary: Mapping[str, object],
    events: Sequence[Any],
    semantic_frame_hashes: Mapping[str, tuple[str, ...]],
) -> dict[str, object]:
    def observation_receipt_matches(
        payload: object,
        event: Any,
    ) -> bool:
        if (
            not isinstance(payload, Mapping)
            or event is None
            or event.event_type != "observation.received"
        ):
            return False
        frames = event.payload.get("frames")
        metadata = event.payload.get("upstream_metadata")
        semantic_hashes = semantic_frame_hashes.get(event.event_id)
        if (
            not isinstance(frames, list)
            or not frames
            or not isinstance(metadata, Mapping)
            or semantic_hashes is None
            or len(semantic_hashes) != len(frames)
        ):
            return False
        return (
            semantic_hashes[-1] == payload.get("frame_digest")
            and event.game_id == payload.get("game_id")
            and event.payload.get("game_state") == payload.get("state")
            and event.payload.get("available_actions") == payload.get("available_actions")
            and event.payload.get("returned_action") == payload.get("returned_action")
            and metadata.get("levels_completed") == payload.get("levels_completed")
            and metadata.get("win_levels") == payload.get("win_levels")
            and metadata.get("full_reset") is payload.get("full_reset")
        )

    by_id = {event.event_id: event for event in events}
    order = {event.event_id: ordinal for ordinal, event in enumerate(events)}
    selected_id = boundary.get("selected_event_id")
    validated_id = boundary.get("validated_event_id")
    submitted_id = boundary.get("submitted_event_id")
    observation_id = boundary.get("observation_event_id")
    selected = by_id.get(selected_id) if isinstance(selected_id, str) else None
    validated = by_id.get(validated_id) if isinstance(validated_id, str) else None
    submitted = by_id.get(submitted_id) if isinstance(submitted_id, str) else None
    observation = by_id.get(observation_id) if isinstance(observation_id, str) else None
    consequences = [
        event
        for event in events
        if event.event_type == "consequence.received"
        and event.payload.get("submitted_event_id") == submitted_id
    ]
    consequence = consequences[0] if len(consequences) == 1 else None
    after_observation_id = boundary.get("consequence_observation_event_id")
    after_observation = (
        by_id.get(after_observation_id) if isinstance(after_observation_id, str) else None
    )
    action = boundary.get("action")
    decision_id = boundary.get("decision_id")
    observation_before = boundary.get("observation_before")
    consequence_returned = boundary.get("consequence_returned") is True
    acknowledged = boundary.get("acknowledged_by_controller") is True
    consequence_payload = boundary.get("consequence")
    consequence_frame_hashes = boundary.get("consequence_frame_hashes")
    returned_frames = (
        consequence.payload.get("returned_frames") if consequence is not None else None
    )
    returned_semantic_hashes = (
        semantic_frame_hashes.get(after_observation.event_id)
        if after_observation is not None
        else None
    )
    exact_return_binding = (
        isinstance(consequence_payload, Mapping)
        and consequence is not None
        and after_observation is not None
        and observation_receipt_matches(consequence_payload, after_observation)
        and isinstance(consequence_frame_hashes, list)
        and consequence_frame_hashes
        and returned_semantic_hashes is not None
        and isinstance(returned_frames, list)
        and returned_frames == after_observation.payload.get("frames")
        and consequence_frame_hashes == list(returned_semantic_hashes)
        and consequence_payload.get("frame_digest") == consequence_frame_hashes[-1]
        and consequence.payload.get("after_state") == consequence_payload.get("state")
        and consequence.payload.get("levels_completed")
        == consequence_payload.get("levels_completed")
        and consequence.payload.get("returned_action") == consequence_payload.get("returned_action")
        and boundary.get("consequence_event_hash") == consequence.event_hash
        and boundary.get("consequence_observation_event_hash") == after_observation.event_hash
        and order[consequence.event_id] + 1 == order[after_observation.event_id]
    )
    valid = (
        selected is not None
        and selected.event_type == "action.selected"
        and observation_receipt_matches(observation_before, observation)
        and validated is not None
        and validated.event_type == "action.validated"
        and submitted is not None
        and submitted.event_type == "action.submitted"
        and observation is not None
        and observation.event_type == "observation.received"
        and selected.payload.get("decision_id") == decision_id
        and validated.payload.get("decision_id") == decision_id
        and submitted.payload.get("decision_id") == decision_id
        and selected.payload.get("source_observation_event_id") == observation_id
        and selected.payload.get("selected_action") == action
        and validated.payload.get("action") == action
        and validated.payload.get("selected_event_id") == selected_id
        and submitted.payload.get("action") == action
        and submitted.payload.get("selected_event_id") == selected_id
        and submitted.payload.get("validated_event_id") == validated_id
        and order[observation.event_id]
        < order[selected.event_id]
        < order[validated.event_id]
        < order[submitted.event_id]
        and (
            (
                consequence_returned
                and consequence is not None
                and consequence.payload.get("selected_event_id") == selected_id
                and consequence.payload.get("action") == action
                and consequence.payload.get("submitted_action") == action
                and order[submitted.event_id] < order[consequence.event_id]
                and exact_return_binding
            )
            or (not consequence_returned and consequence is None)
        )
        and (
            not acknowledged
            or (
                consequence is not None
                and boundary.get("consequence_event_id") == consequence.event_id
            )
        )
    )
    return {
        "action_chain_valid": valid,
        "trace_consequence_event_id": None if consequence is None else consequence.event_id,
        "trace_consequence_observation_event_id": (
            None if after_observation is None else after_observation.event_id
        ),
    }


def _cadence_projection(
    state: _WorkerState,
    events: Sequence[Any],
    semantic_frame_hashes: Mapping[str, tuple[str, ...]],
) -> tuple[list[dict[str, object]], dict[str, object]]:
    variant = cast(str, state.spec["variant"])
    action_chains = {
        id(boundary): _action_chain_projection(boundary, events, semantic_frame_hashes)
        for boundary in state.submitted_boundaries
    }
    if variant == "FROZEN_BUILD_000_FULL":
        unavailable = {
            "availability": "unavailable-at-frozen-source",
            "cache_hits": None,
            "cache_invalidations": None,
            "cache_misses": None,
            "compilation_invocations": None,
            "prediction_invocations": None,
            "retrodicted_transitions": None,
            "search_expanded_nodes": None,
            "simulation_invocations": None,
        }
        return [
            {
                **boundary,
                **action_chains[id(boundary)],
                "deep_trigger_receipts": [],
                "ordered_triggers": [],
                "reasoning_path": None,
                "reasoning_terminal_receipt": None,
                "work": unavailable,
            }
            for boundary in state.submitted_boundaries
        ], {
            "action_receipts_complete": all(
                projection["action_chain_valid"] is True for projection in action_chains.values()
            ),
            "available": False,
            "deep_completed_count": None,
            "deep_selected_count": None,
            "typed_deep_receipts_complete": None,
        }

    by_id = {event.event_id: event for event in events}
    event_order = {event.event_id: ordinal for ordinal, event in enumerate(events)}
    projected: list[dict[str, object]] = []
    deep_selected = 0
    deep_completed = 0
    invalidation_total_before = 0
    receipt_valid = True

    def nonnegative_integer(value: object) -> int:
        return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0

    def nullable_identity(value: object) -> bool:
        return value is None or (isinstance(value, str) and bool(value.strip()))

    def expected_bindings(boundary: Mapping[str, object]) -> Mapping[str, object] | None:
        raw = boundary.get("expected_reasoning_bindings")
        return raw if isinstance(raw, Mapping) else None

    for boundary in state.submitted_boundaries:
        selected_event_id = boundary.get("selected_event_id")
        selected = by_id.get(selected_event_id) if isinstance(selected_event_id, str) else None
        terminal = None
        path_event = None
        if selected is not None:
            terminal_id = selected.payload.get("reasoning_completed_event_id")
            terminal = by_id.get(terminal_id) if isinstance(terminal_id, str) else None
        if terminal is not None:
            path_id = terminal.payload.get("path_selected_event_id")
            path_event = by_id.get(path_id) if isinstance(path_id, str) else None
        if (
            selected is None
            or selected.event_type != "action.selected"
            or terminal is None
            or terminal.event_type
            not in {"reasoning.deliberation_completed", "reasoning.fallback_used"}
            or path_event is None
            or path_event.event_type != "reasoning.path_selected"
        ):
            receipt_valid = False
            path = None
            triggers: list[str] = []
            trigger_receipts: list[dict[str, object]] = []
            terminal_receipt: dict[str, object] | None = None
            work_values: Mapping[str, object] = {}
            cache_hits = 0
            cache_misses = 0
            invalidation_total = invalidation_total_before
        else:
            binding = expected_bindings(boundary)
            expected_selection = binding.get("selection") if isinstance(binding, Mapping) else None
            expected_terminal = binding.get("terminal") if isinstance(binding, Mapping) else None
            path = terminal.payload.get("path")
            raw_triggers = path_event.payload.get("ordered_triggers", [])
            triggers = (
                [item for item in raw_triggers if isinstance(item, str)]
                if isinstance(raw_triggers, list)
                else []
            )
            raw_trigger_receipts = path_event.payload.get("trigger_sources", [])
            trigger_receipts = []
            trigger_receipts_valid = isinstance(raw_trigger_receipts, list)
            if isinstance(raw_trigger_receipts, list):
                for raw_item in raw_trigger_receipts:
                    if not isinstance(raw_item, Mapping):
                        trigger_receipts_valid = False
                        continue
                    raw_ids = raw_item.get("source_event_ids")
                    trigger = raw_item.get("trigger")
                    if (
                        not isinstance(trigger, str)
                        or not isinstance(raw_ids, list)
                        or not raw_ids
                        or any(not isinstance(item, str) or not item for item in raw_ids)
                        or raw_ids != sorted(set(raw_ids))
                    ):
                        trigger_receipts_valid = False
                        continue
                    trigger_receipts.append({"source_event_ids": list(raw_ids), "trigger": trigger})
            terminal_receipt = {
                "kind": terminal.event_type,
                "path": terminal.payload.get("path"),
                "path_selected_event_id": terminal.payload.get("path_selected_event_id"),
                "status": terminal.payload.get("status"),
                "terminal_event_id": terminal.event_id,
            }
            raw_work = terminal.payload.get("integer_work_counts", {})
            work_values = raw_work if isinstance(raw_work, Mapping) else {}
            cache_hits = terminal.payload.get("cache_hits", 0)
            cache_misses = terminal.payload.get("cache_misses", 0)
            raw_invalidations = terminal.payload.get("cache_invalidation_counts", {})
            invalidation_total = (
                sum(
                    value
                    for value in raw_invalidations.values()
                    if isinstance(value, int) and not isinstance(value, bool) and value >= 0
                )
                if isinstance(raw_invalidations, Mapping)
                else invalidation_total_before
            )
            if path == "DEEP":
                deep_selected += 1
                deep_completed += 1
                if variant != "BUILD_001_LEGACY_ALWAYS_DEEP" and not triggers:
                    receipt_valid = False
            source_ids = [
                source_id
                for item in trigger_receipts
                for source_id in cast(list[str], item["source_event_ids"])
                if isinstance(source_id, str)
            ]
            ordered_unique_source_ids = list(dict.fromkeys(source_ids))
            raw_flat_sources = path_event.payload.get("trigger_source_event_ids")
            matching_terminals = [
                event
                for event in events
                if event.event_type
                in {"reasoning.deliberation_completed", "reasoning.fallback_used"}
                and event.payload.get("path_selected_event_id") == path_event.event_id
            ]
            work_fields = (
                "compilation_invocations",
                "prediction_invocations",
                "retrodicted_transitions",
                "search_expanded_nodes",
                "simulation_invocations",
            )
            if (
                not trigger_receipts_valid
                or raw_triggers != triggers
                or [item.get("trigger") for item in trigger_receipts] != triggers
                or raw_flat_sources != ordered_unique_source_ids
                or terminal.payload.get("path_selected_event_id") != path_event.event_id
                or terminal.payload.get("path") != path
                or path_event.payload.get("path") != path
                or selected.payload.get("reasoning_completed_event_id") != terminal.event_id
                or len(matching_terminals) != 1
                or not (
                    event_order[path_event.event_id]
                    < event_order[terminal.event_id]
                    < event_order[selected.event_id]
                )
                or path not in {"FAST", "DEEP"}
                or terminal.payload.get("status")
                not in {"COMPLETED", "FALLBACK_USED", "BUDGET_EXHAUSTED", "FAILED"}
                or (terminal.event_type == "reasoning.fallback_used")
                != (terminal.payload.get("status") == "FALLBACK_USED")
                or not isinstance(path_event.payload.get("state_id"), str)
                or not isinstance(path_event.payload.get("mechanics_epoch_id"), str)
                or not nullable_identity(path_event.payload.get("goal_id"))
                or not nullable_identity(path_event.payload.get("plan_id"))
                or not isinstance(path_event.payload.get("goal_revision"), int)
                or isinstance(path_event.payload.get("goal_revision"), bool)
                or path_event.payload.get("schema") != "arc3.reasoning-cadence-selection.v0.1"
                or path_event.payload.get("observation_event_id")
                != boundary.get("observation_event_id")
                or path_event.payload.get("cadence_mode")
                != (
                    "LEGACY_ALWAYS_DEEP"
                    if variant == "BUILD_001_LEGACY_ALWAYS_DEEP"
                    else "TWO_SPEED"
                )
                or binding is None
                or not isinstance(expected_selection, Mapping)
                or not isinstance(expected_terminal, Mapping)
                or any(
                    path_event.payload.get(key) != value
                    for key, value in expected_selection.items()
                )
                or path_event.event_id != binding.get("path_selected_event_id")
                or path_event.payload.get("budget_limits") != binding.get("budget_limits")
                or path_event.payload.get("cache_projection_hash")
                != binding.get("cache_projection_hash")
                or path_event.payload.get("action_registry_identity")
                != binding.get("action_registry_identity")
                or path_event.payload.get("configuration_hash") != binding.get("configuration_hash")
                or state.cadence_config is None
                or path_event.payload.get("configuration_hash")
                != str(state.cadence_config.configuration_hash)
                or terminal.event_id != expected_terminal.get("terminal_event_id")
                or terminal.event_type != expected_terminal.get("event_type")
                or any(
                    terminal.payload.get(key) != value
                    for key, value in expected_terminal.items()
                    if key not in {"event_type", "terminal_event_id"}
                )
                or not isinstance(terminal.payload.get("budget_exhaustions"), list)
                or not isinstance(terminal.payload.get("produced_model_ids"), list)
                or not isinstance(terminal.payload.get("produced_goal_ids"), list)
                or not isinstance(terminal.payload.get("produced_plan_ids"), list)
                or not isinstance(terminal.payload.get("artifact_projection_hash"), str)
                or any(
                    nonnegative_integer(work_values.get(field)) != work_values.get(field)
                    for field in work_fields
                )
                or nonnegative_integer(cache_hits) != cache_hits
                or nonnegative_integer(cache_misses) != cache_misses
                or not isinstance(raw_invalidations, Mapping)
                or any(nonnegative_integer(value) != value for value in raw_invalidations.values())
                or invalidation_total < invalidation_total_before
                or any(
                    source_id not in event_order
                    or event_order[source_id] >= event_order[path_event.event_id]
                    for source_id in ordered_unique_source_ids
                )
            ):
                receipt_valid = False
        work = {
            "availability": "available",
            "cache_hits": cache_hits if isinstance(cache_hits, int) else 0,
            "cache_invalidations": max(0, invalidation_total - invalidation_total_before),
            "cache_misses": cache_misses if isinstance(cache_misses, int) else 0,
            "compilation_invocations": nonnegative_integer(
                work_values.get("compilation_invocations", 0)
            ),
            "prediction_invocations": nonnegative_integer(
                work_values.get("prediction_invocations", 0)
            ),
            "retrodicted_transitions": nonnegative_integer(
                work_values.get("retrodicted_transitions", 0)
            ),
            "search_expanded_nodes": nonnegative_integer(
                work_values.get("search_expanded_nodes", 0)
            ),
            "simulation_invocations": nonnegative_integer(
                work_values.get("simulation_invocations", 0)
            ),
        }
        invalidation_total_before = invalidation_total
        projected.append(
            {
                **boundary,
                **action_chains[id(boundary)],
                "deep_trigger_receipts": trigger_receipts,
                "ordered_triggers": triggers,
                "reasoning_path": path,
                "reasoning_terminal_receipt": terminal_receipt,
                "work": work,
            }
        )
    return projected, {
        "action_receipts_complete": all(
            projection["action_chain_valid"] is True for projection in action_chains.values()
        ),
        "available": True,
        "deep_completed_count": deep_completed,
        "deep_selected_count": deep_selected,
        "typed_deep_receipts_complete": receipt_valid and deep_selected == deep_completed,
    }


def _score_projection(state: _WorkerState) -> dict[str, object]:
    scorecard = state.scorecard
    if scorecard is None or not bool(getattr(scorecard, "verified", False)):
        return {
            "completed": None,
            "levels_completed": None,
            "score": None,
            "verified": False,
        }
    runs = cast(Sequence[Any], getattr(scorecard, "runs", ()))
    if len(runs) != 1 or str(runs[0].game_id) != _GAME_ID:
        raise RuntimeError("Stage 08 scorecard does not bind exactly one declared game")
    run = runs[0]
    final = state.final_observation
    final_state = getattr(getattr(final, "state", None), "value", None)
    final_levels = getattr(final, "levels_completed", None)
    if (
        int(run.actions) != state.environment_actions
        or int(run.resets) != state.resets
        or run.state.value != final_state
        or int(run.levels_completed) != final_levels
    ):
        raise RuntimeError("Stage 08 verified scorecard disagrees with observed execution")
    return {
        "completed": bool(run.completed),
        "levels_completed": int(run.levels_completed),
        "official_run_actions": int(run.actions),
        "official_run_levels_completed": int(run.levels_completed),
        "official_run_resets": int(run.resets),
        "official_run_state": run.state.value,
        "score": float(run.score),
        "scorer": str(scorecard.scorer),
        "verified": True,
    }


def _directory_identity(root: Path) -> dict[str, object]:
    files = (
        tuple(
            {
                "bytes": path.stat().st_size,
                "path": path.relative_to(root).as_posix(),
                "sha256": _sha256_file(path),
            }
            for path in sorted(root.rglob("*"))
            if path.is_file()
        )
        if root.is_dir()
        else ()
    )
    return {
        "aggregate_sha256": _sha256_bytes(_canonical_json_bytes(files)),
        "file_count": len(files),
        "files": list(files),
        "path": root.resolve().as_posix(),
    }


def _controller_fault_identities(events: Sequence[Any]) -> list[str]:
    fault_types = {
        "action.rejected_by_environment",
        "observation.parse_failed",
        "run.environment_fault",
    }
    identities: list[str] = []
    for event in events:
        if event.event_type not in fault_types:
            continue
        semantic_payload = {
            key: value for key, value in event.payload.items() if not key.endswith("_event_id")
        }
        digest = _sha256_bytes(
            _canonical_json_bytes({"event_type": event.event_type, "payload": semantic_payload})
        )
        identities.append(f"fault-{len(identities):03d}:{digest}")
    return identities


def _runtime_identity() -> dict[str, object]:
    packages: dict[str, str | None] = {}
    for name in ("arc-agi", "arcengine", "numpy", "pydantic"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    return {
        "cpu": platform.processor() or platform.machine() or None,
        "cpu_count": os.cpu_count(),
        "executable": sys.executable,
        "packages": packages,
        "platform": platform.platform(),
        "python": platform.python_version(),
    }


def _runtime_environment() -> dict[str, object]:
    exact = {
        "ALL_PROXY": "",
        "HTTP_PROXY": "",
        "HTTPS_PROXY": "",
        "NO_PROXY": "*",
        "PIP_NO_INDEX": "1",
        "PYTHONHASHSEED": "0",
        "PYTHONNOUSERSITE": "1",
        "UV_OFFLINE": "1",
    }
    observed = {key: os.environ.get(key) for key in exact}
    return {
        "expected": exact,
        "observed": observed,
        "passed": observed == exact,
    }


def _boundary_phase_counts(state: _WorkerState, *, is_reset: bool) -> dict[str, int]:
    attempted = [
        boundary for boundary in state.attempted_boundaries if boundary.get("is_reset") is is_reset
    ]
    submitted = [
        boundary for boundary in state.submitted_boundaries if boundary.get("is_reset") is is_reset
    ]
    return {
        "acknowledged": sum(
            boundary.get("acknowledged_by_controller") is True for boundary in submitted
        ),
        "attempted": len(attempted),
        "returned": sum(boundary.get("consequence_returned") is True for boundary in submitted),
        "submitted": len(submitted),
    }


def _failure_domain_for_phase(phase: str, failure: Exception) -> str:
    """Classify a terminal failure without inferring success from its symptoms."""

    if phase == "resources":
        return "RESOURCE"
    if isinstance(failure, (ImportError, ModuleNotFoundError)) or type(failure).__name__ in {
        "DependencyUnavailableError",
        "PackageNotFoundError",
    }:
        return "INFRASTRUCTURE"
    if phase.startswith("controller-") or phase in {"network", "worker-reset-budget"}:
        return "MECHANISM"
    return "INFRASTRUCTURE"


def _finalize(
    state: _WorkerState,
    *,
    error: Exception | None,
) -> dict[str, object]:
    initial_error = error
    failure_phase = state.execution_phase if error is not None else None
    validation_failures: list[str] = []
    if error is not None:
        validation_failures.append(f"execution:{type(error).__name__}:{error}")

    def fail(label: str, failure: Exception | str) -> None:
        nonlocal error, failure_phase
        detail = (
            f"{type(failure).__name__}:{failure}" if isinstance(failure, Exception) else failure
        )
        validation_failures.append(f"{label}:{detail}")
        if error is None:
            failure_phase = label
            error = (
                failure if isinstance(failure, Exception) else RuntimeError(f"{label}: {failure}")
            )

    if state.session is not None and not state.session_closed:
        try:
            state.execution_phase = "adapter-close"
            state.scorecard = state.session.close()
            state.session_closed = True
        except Exception as close_error:
            fail("session-close", close_error)
    try:
        state.execution_phase = "controller-close"
        _close_controller(state)
    except Exception as close_error:
        fail("controller-close", close_error)
    checkpoint: dict[str, object]
    try:
        checkpoint = _restore_checkpoint(state)
    except Exception as restore_error:
        checkpoint = {
            "path": None,
            "reason": f"{type(restore_error).__name__}: {restore_error}",
            "restore_valid": False,
        }
        fail("checkpoint-restore", restore_error)
    if checkpoint.get("restore_valid") is not True:
        fail("checkpoint-restore", "terminal checkpoint did not restore exactly")
    try:
        trace, events, semantic_frame_hashes = _trace_receipt(state)
    except Exception as trace_error:
        trace = {
            "byte_length": _directory_bytes(Path(cast(str, state.spec["trace_root"]))),
            "path": Path(cast(str, state.spec["trace_root"])).resolve().as_posix(),
            "replay_verified": False,
            "reason": f"{type(trace_error).__name__}: {trace_error}",
        }
        events = []
        semantic_frame_hashes = {}
        fail("trace-replay", trace_error)
    try:
        projected_boundaries, cadence = _cadence_projection(
            state,
            events,
            semantic_frame_hashes,
        )
    except Exception as cadence_error:
        projected_boundaries = [
            {
                **boundary,
                "action_chain_valid": False,
                "deep_trigger_receipts": [],
                "ordered_triggers": [],
                "reasoning_path": None,
                "reasoning_terminal_receipt": None,
                "trace_consequence_event_id": None,
                "work": {
                    "availability": "projection-failed",
                },
            }
            for boundary in state.submitted_boundaries
        ]
        cadence = {
            "action_receipts_complete": False,
            "available": False,
            "typed_deep_receipts_complete": False,
        }
        fail("cadence-projection", cadence_error)
    actions = [item for item in projected_boundaries if item.get("is_reset") is False]
    reset_boundaries = [item for item in projected_boundaries if item.get("is_reset") is True]
    try:
        score = _score_projection(state)
    except Exception as score_error:
        score = {
            "completed": None,
            "levels_completed": None,
            "score": None,
            "verified": False,
        }
        fail("score-reconciliation", score_error)
    try:
        asset_after = _asset_identity(Path(cast(str, state.spec["environments_dir"])))
    except Exception as asset_error:
        asset_after = {
            "aggregate_sha256": None,
            "passed": False,
            "reason": f"{type(asset_error).__name__}: {asset_error}",
        }
        fail("asset-after", asset_error)
    if asset_after != state.asset_before:
        fail("asset-stability", "development asset identity changed")
    try:
        source_end = _validate_source(state.spec)
    except Exception as source_error:
        source_end = {
            "reason": f"{type(source_error).__name__}: {source_error}",
        }
        fail("source-end", source_error)
    source_stability = {
        "end": source_end,
        "exact_identity_stable": source_end == state.source_identity,
        "start": state.source_identity,
    }
    if source_stability["exact_identity_stable"] is not True:
        fail("source-stability", "source commit, tree, or cleanliness changed")
    _update_peak(state)
    state.network_attempt_count = (
        state.network_guard.attempt_count
        if state.network_guard is not None
        else state.network_attempt_count
    )
    raw_trace_bytes = trace.get("byte_length")
    trace_bytes: int | None = (
        raw_trace_bytes
        if isinstance(raw_trace_bytes, int) and not isinstance(raw_trace_bytes, bool)
        else None
    )
    total_wall_ns = max(0, time.perf_counter_ns() - state.started_wall_ns)
    total_cpu_ns = max(0, time.process_time_ns() - state.started_cpu_ns)
    memory_valid = (
        state.peak_rss_bytes is not None
        and state.memory_sample_count > 0
        and state.memory_invalid_count == 0
        and len(state.memory_sources) == 1
    )
    decision_timings_valid = all(
        isinstance(boundary.get("choose_wall_ns"), int)
        and not isinstance(boundary.get("choose_wall_ns"), bool)
        and 0 <= cast(int, boundary["choose_wall_ns"]) <= 2_000_000_000
        for boundary in projected_boundaries
    )
    resources_valid = (
        memory_valid
        and cast(int, state.peak_rss_bytes) <= 2_147_483_648
        and trace_bytes is not None
        and trace_bytes <= 268_435_456
        and decision_timings_valid
        and total_wall_ns <= int(_WORKER_WALL_SECONDS * 1_000_000_000)
    )
    if not resources_valid:
        fail("resources", "RSS, trace, decision, or worker wall evidence is invalid")
    receipt_integrity_valid = (
        trace.get("replay_verified") is True
        and cadence.get("action_receipts_complete") is True
        and (
            state.spec["variant"] == "FROZEN_BUILD_000_FULL"
            or cadence.get("typed_deep_receipts_complete") is True
        )
    )
    if not receipt_integrity_valid:
        fail("receipt-integrity", "action or cadence receipt chain is incomplete")
    if state.network_attempt_count != 0:
        fail("network", "one or more guarded Python socket entry points were attempted")
    action_counts = _boundary_phase_counts(state, is_reset=False)
    reset_counts = _boundary_phase_counts(state, is_reset=True)
    exact_returned_consequences = [
        boundary.get("consequence")
        for boundary in projected_boundaries
        if boundary.get("consequence_returned") is True
    ]
    count_consistency = {
        "acknowledged_le_returned": state.acknowledged_count <= state.returned_count,
        "adapter_submissions_le_decisions": state.adapter_submissions <= state.decision_attempts,
        "attempted_boundaries_le_decisions": (
            len(state.attempted_boundaries) <= state.decision_attempts
        ),
        "budget_counts_match_boundaries": (
            state.environment_actions + state.resets == len(state.submitted_boundaries)
        ),
        "classified_submissions_match": (
            len(state.boundaries) + len(state.reset_boundaries) == len(state.submitted_boundaries)
        ),
        "returned_le_adapter_submissions": state.returned_count <= state.adapter_submissions,
        "submitted_boundaries_le_decisions": (
            len(state.submitted_boundaries) <= state.decision_attempts
        ),
        "typed_action_counts_monotone": (
            action_counts["attempted"]
            >= action_counts["submitted"]
            >= action_counts["returned"]
            >= action_counts["acknowledged"]
        ),
        "typed_reset_counts_monotone": (
            reset_counts["attempted"]
            >= reset_counts["submitted"]
            >= reset_counts["returned"]
            >= reset_counts["acknowledged"]
        ),
        "returned_consequence_order_exact": (
            state.returned_consequences == exact_returned_consequences
        ),
    }
    success_count_consistency = (
        initial_error is None
        and state.decision_attempts
        == len(state.submitted_boundaries)
        == state.adapter_submissions
        == state.returned_count
        == state.acknowledged_count
        and all(item.get("boundary_status") == "normal" for item in projected_boundaries)
    )
    if not all(count_consistency.values()) or (
        initial_error is None and not success_count_consistency
    ):
        fail("counts", "decision/submission/consequence counts are inconsistent")
    if initial_error is None and score.get("verified") is not True:
        fail("score", "normally completed worker lacks a verified scorecard")
    runtime_environment = _runtime_environment()
    if runtime_environment["passed"] is not True:
        fail("runtime-environment", "deterministic offline subprocess environment changed")
    controller_config_projection = (
        None
        if state.controller_config is None
        else {
            "config": state.controller_config.to_dict(),
            "config_hash": str(state.controller_config.hash),
        }
    )
    cadence_config_projection = (
        None
        if state.cadence_config is None
        else {
            "config": state.cadence_config.to_dict(),
            "configuration_hash": str(state.cadence_config.configuration_hash),
        }
    )
    config_projection = {
        "cadence": cadence_config_projection,
        "controller": controller_config_projection,
        "controller_preset": "full",
        "variant": state.spec["variant"],
    }
    recording_identity = _directory_identity(Path(cast(str, state.spec["recordings_dir"])))
    if initial_error is None and cast(int, recording_identity["file_count"]) == 0:
        fail("recording", "normally completed worker produced no immutable environment recording")
    status = "success" if error is None else "failure"
    terminal_failure_phase = None if error is None else failure_phase or "worker-finalization"
    failure_domain = (
        None
        if terminal_failure_phase is None
        else _failure_domain_for_phase(terminal_failure_phase, cast(Exception, error))
    )
    controller_fault_identities = _controller_fault_identities(events)
    payload: dict[str, object] = {
        "action_sequence": state.action_sequence,
        "action_counts": action_counts,
        "actions": actions,
        "attempted_boundaries": state.attempted_boundaries,
        "asset_after": asset_after,
        "asset_before": state.asset_before,
        "cadence": cadence,
        "cell_id": state.spec["cell_id"],
        "cell": state.spec["cell"],
        "checkpoint": checkpoint,
        "checkpoint_bytes": _directory_bytes(Path(cast(str, state.spec["checkpoint_root"]))),
        "completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "controller_fault_count": len(controller_fault_identities),
        "controller_fault_identities": controller_fault_identities,
        "counts": {
            "acknowledged_consequences": state.acknowledged_count,
            "adapter_submissions": state.adapter_submissions,
            "decision_attempts": state.decision_attempts,
            "classified_attempts": len(state.attempted_boundaries),
            "predicates": count_consistency,
            "returned_consequences": state.returned_count,
            "unclassified_attempts": state.decision_attempts - len(state.attempted_boundaries),
            "success_exact_counts": success_count_consistency,
        },
        "development_identity": state.spec["development_identity"],
        "environment_actions": state.environment_actions,
        "evidence_label": "local-public",
        "failure": (
            None
            if error is None
            else {
                "kind": type(error).__name__,
                "message": str(error)[:500],
                "traceback": "".join(
                    traceback.format_exception(type(error), error, error.__traceback__)
                )[-4000:],
            }
        ),
        "failure_domain": failure_domain,
        "failure_phase": terminal_failure_phase,
        "final_observation": (
            None
            if state.final_observation is None
            else _observation_payload(state.final_observation)
        ),
        "network_attempt_count": state.network_attempt_count,
        "network_guard": {
            "guarded_python_entry_points": [
                "socket.create_connection",
                "socket.getaddrinfo",
                "socket.socket.connect",
                "socket.socket.connect_ex",
                "socket.socket.sendto",
            ],
            "native_subprocess_or_preconnected_transport_excluded": True,
        },
        "peak_rss_bytes": state.peak_rss_bytes,
        "memory": {
            "invalid_sample_count": state.memory_invalid_count,
            "measurement_valid": memory_valid,
            "peak_rss_bytes": state.peak_rss_bytes,
            "sample_count": state.memory_sample_count,
            "source": next(iter(state.memory_sources)) if len(state.memory_sources) == 1 else None,
            "sources": sorted(state.memory_sources),
        },
        "primary_timing_scope": "non-reset normally-returned boundaries; resets remain gated evidence",
        "recordings": recording_identity,
        "reset_boundaries": reset_boundaries,
        "reset_counts": reset_counts,
        "resets": state.resets,
        "resources_valid": resources_valid,
        "receipt_integrity_valid": receipt_integrity_valid,
        "returned_consequences": state.returned_consequences,
        "runtime_identity": _runtime_identity(),
        "runtime_environment": runtime_environment,
        "schema": _RESULT_SCHEMA,
        "score": score,
        "source_identity": source_stability,
        "spec_hash": state.spec["spec_hash"],
        "status": status,
        "submitted_action_identities": [
            item.get("environment_action_identity") for item in projected_boundaries
        ],
        "submitted_boundaries": projected_boundaries,
        "total_cpu_ns": total_cpu_ns,
        "total_wall_ns": total_wall_ns,
        "trace": trace,
        "validation_failures": validation_failures,
        "variant": state.spec["variant"],
        "configuration": config_projection,
    }
    return _seal(payload, hash_field="worker_result_hash")


def execute(spec: dict[str, object]) -> dict[str, object]:
    started_wall_ns = time.perf_counter_ns()
    started_cpu_ns = time.process_time_ns()
    _validate_paths(spec)
    runtime_environment = _runtime_environment()
    if runtime_environment["passed"] is not True:
        raise RuntimeError("Stage 08 deterministic offline worker environment changed")
    with _SocketDeny() as network_guard:
        source_identity = _validate_source(spec)
        source_root = Path(cast(str, spec["source_root"])).resolve()
        sys.path.insert(0, str(source_root / "src"))
        asset_before = _asset_identity(Path(cast(str, spec["environments_dir"])))
        if asset_before["passed"] is not True:
            raise RuntimeError("frozen Stage 08 development asset identity changed before open")
        state = _WorkerState(
            spec=spec,
            source_identity=source_identity,
            asset_before=asset_before,
            started_wall_ns=started_wall_ns,
            started_cpu_ns=started_cpu_ns,
            network_guard=network_guard,
        )
        error: Exception | None = None
        try:
            _update_peak(state)
            state.execution_phase = "controller-initialization"
            _make_controller(state)
            state.execution_phase = "adapter-open"
            _open_session(state)
            state.execution_phase = "asset-after-open"
            asset_after_open = _asset_identity(Path(cast(str, spec["environments_dir"])))
            if asset_after_open != asset_before:
                raise RuntimeError("frozen Stage 08 asset changed while opening the environment")
            _run_episode(state)
        except Exception as run_error:
            error = run_error
        result = _finalize(state, error=error)
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    if not args.spec.is_absolute() or not args.output.is_absolute():
        raise SystemExit("Stage 08 worker requires absolute spec and output paths")
    if args.output.exists():
        raise SystemExit("Stage 08 worker output already exists and cannot be overwritten")
    try:
        spec = _validate_spec(_load_object(args.spec.resolve()))
        expected_output = Path(cast(str, spec["cell_root"])).resolve() / "worker-result.json"
        if args.output.resolve() != expected_output:
            raise ValueError("Stage 08 worker output differs from the sealed cell layout")
        result = execute(spec)
    except Exception as error:
        result = _seal(
            {
                "cell_id": None,
                "completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "failure": {
                    "kind": type(error).__name__,
                    "message": str(error)[:500],
                    "traceback": "".join(
                        traceback.format_exception(type(error), error, error.__traceback__)
                    )[-4000:],
                },
                "failure_domain": "INFRASTRUCTURE",
                "failure_phase": "worker-bootstrap",
                "schema": _RESULT_SCHEMA,
                "status": "failure",
            },
            hash_field="worker_result_hash",
        )
    _atomic_write_json(args.output.resolve(), result)
    return 0 if result.get("status") == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
