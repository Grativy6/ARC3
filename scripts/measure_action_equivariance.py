"""Measure the frozen Build 001 Stage 05 action-equivariance contract.

The harness is synthetic-only.  Gameplay action identifiers are opaque wire
handles: procedural environments assign latent effects at their boundary and
paired variants permute only point-free handles.  The unavoidable same-prefix
calibration actions remain in every environment budget and are excluded only
from the explicitly named inverse-request numerator.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Protocol, cast

from arc3.adapters import (
    GridFrame,
    Observation,
    ScoreRunSummary,
    ScoreSummary,
    validate_action_request,
)
from arc3.config import ARC3Config, BudgetConfig, derive_seed
from arc3.evaluation.artifacts import (
    atomic_write_json,
    canonical_json_bytes,
    seal_object,
    sha256_bytes,
    sha256_file,
)
from arc3.exploration.action_registry import (
    ActionEffectRegistry,
    ActionEffectStatus,
    CanonicalEffectKind,
    CoordinateRelation,
)
from arc3.policy import (
    ARC3Controller,
    ControllerPhase,
    ControllerPreset,
    RunContext,
    preset_features,
)
from arc3.profiling import RobustnessVariant, TransformedSyntheticSession
from arc3.profiling.runtime import process_memory_sample
from arc3.trace import EventJournal, ReplayEngine
from arc3.trace import canonical_bytes as trace_canonical_bytes
from arc3.trace import sha256_bytes as trace_sha256_bytes
from arc3.types import (
    ActionName,
    ActionRequest,
    Coordinate,
    EvaluationSurface,
    GameId,
    GameStateName,
    JSONValue,
)

if not __package__:  # direct frozen command: python scripts/measure_action_equivariance.py
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.check_action_semantics import build_action_semantics_receipt

ROOT = Path(__file__).resolve().parents[1]
PREDECLARATION = ROOT / "docs/evidence/001-05-action-equivariance-predeclaration.json"
DEFAULT_OUTPUT = Path("C:/a/arc3-b001/artifacts/stage05/action-equivariance.json")
DEFAULT_WORK_ROOT = Path("C:/a/arc3-b001/artifacts/stage05/action-equivariance-work")
GRID_SIZE = 8
MAX_ACTIONS = 16
MAX_RESETS = 2
MAX_COORDINATE_CANDIDATES = 24
WALL_LIMIT_SECONDS = 600.0
EPISODE_WALL_LIMIT_SECONDS = 60.0
PEAK_RSS_LIMIT_BYTES = 1024 * 1024 * 1024
CALIBRATION_COORDINATE = Coordinate(3, 3)
CHECKPOINT_SEEDS = tuple(range(16))
HISTORICAL_SEEDS = (7, 11)
GAME_ID = GameId("synthetic-stage05-toroidal-action-v1")
_WIRE_RANK = {action: index for index, action in enumerate(ActionName)}
_BUILD_000_EXPOSURE_LEDGER = Path("C:/a/arc3-s15-6a0f6e5/artifacts/stage15/public-exposure.jsonl")
_STAGE_03_EXPOSURE_LEDGER = Path("C:/a/arc3-b001/artifacts/stage03/public-exposure.jsonl")
_KNOWN_PUBLIC_ENVIRONMENT_ROOTS = (
    Path("C:/a/arc3-s15-6a0f6e5/artifacts/stage15/public-environments"),
    ROOT / "artifacts/stage15/public-environments",
)
_FROZEN_EXPOSURE_HASHES = {
    "build-000": "sha256:cd9af42ed3a5ef9fa0dc201ddb10e32d2bcccee9df729aa0c7d53077c04c9ad4",
    "stage-03": "sha256:e02a9fa71206170a6fe2aeefb6935ae25141e2759937657475cead4389bb17aa",
}

_FULL_PERMUTATIONS: tuple[tuple[str, dict[ActionName, ActionName]], ...] = (
    (
        "swap12",
        {
            ActionName.ACTION1: ActionName.ACTION2,
            ActionName.ACTION2: ActionName.ACTION1,
            ActionName.ACTION3: ActionName.ACTION3,
            ActionName.ACTION4: ActionName.ACTION4,
        },
    ),
    (
        "swap34",
        {
            ActionName.ACTION1: ActionName.ACTION1,
            ActionName.ACTION2: ActionName.ACTION2,
            ActionName.ACTION3: ActionName.ACTION4,
            ActionName.ACTION4: ActionName.ACTION3,
        },
    ),
    (
        "swap12_swap34",
        {
            ActionName.ACTION1: ActionName.ACTION2,
            ActionName.ACTION2: ActionName.ACTION1,
            ActionName.ACTION3: ActionName.ACTION4,
            ActionName.ACTION4: ActionName.ACTION3,
        },
    ),
    (
        "cycle1234",
        {
            ActionName.ACTION1: ActionName.ACTION2,
            ActionName.ACTION2: ActionName.ACTION3,
            ActionName.ACTION3: ActionName.ACTION4,
            ActionName.ACTION4: ActionName.ACTION1,
        },
    ),
    (
        "cycle1432",
        {
            ActionName.ACTION1: ActionName.ACTION4,
            ActionName.ACTION2: ActionName.ACTION1,
            ActionName.ACTION3: ActionName.ACTION2,
            ActionName.ACTION4: ActionName.ACTION3,
        },
    ),
    (
        "reverse",
        {
            ActionName.ACTION1: ActionName.ACTION4,
            ActionName.ACTION2: ActionName.ACTION3,
            ActionName.ACTION3: ActionName.ACTION2,
            ActionName.ACTION4: ActionName.ACTION1,
        },
    ),
)

_TWO_ASSIGNMENTS: tuple[tuple[int, tuple[ActionName, ...]], ...] = (
    (16, (ActionName.ACTION1, ActionName.ACTION2)),
    (17, (ActionName.ACTION2, ActionName.ACTION3)),
    (18, (ActionName.ACTION3, ActionName.ACTION4)),
    (19, (ActionName.ACTION4, ActionName.ACTION5)),
    (20, (ActionName.ACTION5, ActionName.ACTION7)),
    (21, (ActionName.ACTION1, ActionName.ACTION7)),
    (22, (ActionName.ACTION2, ActionName.ACTION5)),
    (23, (ActionName.ACTION3, ActionName.ACTION7)),
)
_THREE_ASSIGNMENTS: tuple[tuple[int, tuple[ActionName, ...], str], ...] = (
    (24, (ActionName.ACTION1, ActionName.ACTION2, ActionName.ACTION3), "forward"),
    (25, (ActionName.ACTION2, ActionName.ACTION3, ActionName.ACTION4), "reverse"),
    (26, (ActionName.ACTION3, ActionName.ACTION4, ActionName.ACTION5), "forward"),
    (27, (ActionName.ACTION1, ActionName.ACTION4, ActionName.ACTION5), "reverse"),
    (28, (ActionName.ACTION2, ActionName.ACTION5, ActionName.ACTION7), "forward"),
    (29, (ActionName.ACTION1, ActionName.ACTION3, ActionName.ACTION7), "reverse"),
    (30, (ActionName.ACTION2, ActionName.ACTION4, ActionName.ACTION7), "forward"),
    (31, (ActionName.ACTION1, ActionName.ACTION5, ActionName.ACTION7), "reverse"),
)
_MIXED_ASSIGNMENTS: tuple[tuple[int, tuple[ActionName, ...], str], ...] = tuple(
    (seed, handles, "forward" if seed % 2 == 0 else "reverse")
    for seed, handles in (
        *(
            (seed, (ActionName.ACTION1, ActionName.ACTION2, ActionName.ACTION3))
            for seed in range(32, 36)
        ),
        *(
            (seed, (ActionName.ACTION2, ActionName.ACTION4, ActionName.ACTION5))
            for seed in range(36, 40)
        ),
        *(
            (seed, (ActionName.ACTION1, ActionName.ACTION5, ActionName.ACTION7))
            for seed in range(40, 44)
        ),
        *(
            (seed, (ActionName.ACTION3, ActionName.ACTION4, ActionName.ACTION7))
            for seed in range(44, 48)
        ),
    )
)


class _Session(Protocol):
    @property
    def observation(self) -> Observation: ...

    def step(self, action: ActionRequest) -> Observation: ...

    def close(self) -> ScoreSummary: ...


@dataclass(frozen=True, slots=True)
class ActionPairSpec:
    """One exact entry in the frozen 128-pair procedural schedule."""

    pair_id: str
    family: str
    seed: int
    handles: tuple[ActionName, ...]
    permutation_id: str
    permutation: tuple[tuple[ActionName, ActionName], ...]

    @property
    def pi(self) -> dict[ActionName, ActionName]:
        return dict(self.permutation)

    @property
    def calibration_length(self) -> int:
        return len(self.handles)


def _cycle_permutation(
    handles: Sequence[ActionName], direction: str
) -> dict[ActionName, ActionName]:
    values = tuple(handles)
    if len(values) != 3 or direction not in {"forward", "reverse"}:
        raise ValueError("three-handle permutations require forward or reverse")
    shift = 1 if direction == "forward" else -1
    return {value: values[(index + shift) % 3] for index, value in enumerate(values)}


def action_suite_schedule() -> tuple[ActionPairSpec, ...]:
    """Materialize exactly 96 + 8 + 8 + 16 frozen paired cases."""

    cases: list[ActionPairSpec] = []
    full_handles = (
        ActionName.ACTION1,
        ActionName.ACTION2,
        ActionName.ACTION3,
        ActionName.ACTION4,
    )
    for seed in range(16):
        for permutation_id, mapping in _FULL_PERMUTATIONS:
            cases.append(
                ActionPairSpec(
                    f"stage05-full_four_handle-s{seed:02d}-p{permutation_id}",
                    "full_four_handle",
                    seed,
                    full_handles,
                    permutation_id,
                    tuple(mapping.items()),
                )
            )
    for seed, handles in _TWO_ASSIGNMENTS:
        mapping = {handles[0]: handles[1], handles[1]: handles[0]}
        cases.append(
            ActionPairSpec(
                f"stage05-partial_two_handle-s{seed:02d}-pswap",
                "partial_two_handle",
                seed,
                handles,
                "swap",
                tuple(mapping.items()),
            )
        )
    for seed, handles, direction in _THREE_ASSIGNMENTS:
        cases.append(
            ActionPairSpec(
                f"stage05-partial_three_handle-s{seed:02d}-p{direction}",
                "partial_three_handle",
                seed,
                handles,
                direction,
                tuple(_cycle_permutation(handles, direction).items()),
            )
        )
    for seed, point_handles, direction in _MIXED_ASSIGNMENTS:
        handles = (*point_handles, ActionName.ACTION6)
        mapping = _cycle_permutation(point_handles, direction)
        mapping[ActionName.ACTION6] = ActionName.ACTION6
        cases.append(
            ActionPairSpec(
                f"stage05-mixed_coordinate-s{seed:02d}-p{direction}",
                "mixed_coordinate",
                seed,
                handles,
                direction,
                tuple(mapping.items()),
            )
        )
    return tuple(cases)


def _latent_effects(handles: Sequence[ActionName]) -> dict[ActionName, tuple[int, int] | None]:
    point_free = tuple(action for action in handles if action is not ActionName.ACTION6)
    translations = ((1, 0), (-1, 0), (0, 1), (0, -1))
    effects: dict[ActionName, tuple[int, int] | None] = {
        action: translations[index] for index, action in enumerate(point_free)
    }
    if ActionName.ACTION6 in handles:
        effects[ActionName.ACTION6] = None
    return effects


class ToroidalActionSession:
    """Commuting calibration arena with opaque, optionally permuted handles."""

    def __init__(self, specification: ActionPairSpec, *, transformed: bool) -> None:
        self.specification = specification
        self.transformed = transformed
        self.environment_seed = derive_seed(
            specification.seed, f"build-001-stage05-{specification.family}"
        )
        base_effects = _latent_effects(specification.handles)
        pi = specification.pi
        self._effects = (
            {pi.get(base, base): effect for base, effect in base_effects.items()}
            if transformed
            else base_effects
        )
        self._handles = tuple(sorted(specification.handles, key=_WIRE_RANK.__getitem__))
        self._initial = (1, 1 + self.environment_seed % 2)
        prefix_dx = sum(effect[0] for effect in base_effects.values() if effect is not None)
        prefix_dy = sum(effect[1] for effect in base_effects.values() if effect is not None)
        post_prefix = (
            (self._initial[0] + prefix_dx) % GRID_SIZE,
            (self._initial[1] + prefix_dy) % GRID_SIZE,
        )
        self._target = ((post_prefix[0] + 4) % GRID_SIZE, post_prefix[1])
        self._position = self._initial
        self._step_count = 0
        self._action_count = 0
        self._reset_count = 0
        self._coordinate_hits = 0
        self._post_calibration_coordinate_uses = 0
        self._state = GameStateName.NOT_FINISHED
        self._closed = False
        self._observation = self._make_observation(
            returned_action=ActionRequest(ActionName.RESET), full_reset=True
        )

    @property
    def observation(self) -> Observation:
        return self._observation

    @property
    def calibration_length(self) -> int:
        return len(self._handles)

    def _frame(self) -> GridFrame:
        rows = [[0 for _ in range(GRID_SIZE)] for _ in range(GRID_SIZE)]
        rows[self._target[1]][self._target[0]] = 2
        rows[self._position[1]][self._position[0]] = 1
        rows[7][7] = 3
        return GridFrame.from_rows(rows)

    def _make_observation(self, *, returned_action: ActionRequest, full_reset: bool) -> Observation:
        return Observation(
            game_id=GAME_ID,
            frames=(self._frame(),),
            state=self._state,
            levels_completed=1 if self._state is GameStateName.WIN else 0,
            win_levels=1,
            available_actions=self._handles if self._state is GameStateName.NOT_FINISHED else (),
            full_reset=full_reset,
            returned_action=returned_action,
            upstream_metadata=(
                ("coordinate_hits", self._coordinate_hits),
                ("environment_seed", self.specification.seed),
                ("step", self._step_count),
            ),
        )

    def canonical_effect(self, action: ActionRequest) -> dict[str, JSONValue]:
        effect = self._effects.get(action.name)
        if action.name is ActionName.ACTION6:
            coordinate = action.coordinate
            return {
                "kind": "coordinate",
                "coordinate": (
                    None if coordinate is None else {"x": coordinate.x, "y": coordinate.y}
                ),
            }
        return {
            "kind": "translation",
            "translation": list(cast(tuple[int, int], effect)),
        }

    def canonical_state(self) -> dict[str, JSONValue]:
        return {
            "coordinate_hits": self._coordinate_hits,
            "levels_completed": 1 if self._state is GameStateName.WIN else 0,
            "position": list(self._position),
            "post_calibration_coordinate_uses": self._post_calibration_coordinate_uses,
            "state": self._state.value,
            "target": list(self._target),
        }

    def step(self, action: ActionRequest) -> Observation:
        if self._closed:
            raise RuntimeError("toroidal action session is closed")
        validate_action_request(self._observation, action)
        if action.name is ActionName.RESET:
            self._position = self._initial
            self._state = GameStateName.NOT_FINISHED
            self._reset_count += 1
            self._step_count = 0
            self._coordinate_hits = 0
            self._post_calibration_coordinate_uses = 0
            self._observation = self._make_observation(returned_action=action, full_reset=True)
            return self._observation
        effect = self._effects[action.name]
        if effect is None:
            if action.coordinate == CALIBRATION_COORDINATE:
                self._coordinate_hits += 1
            if self._step_count >= self.calibration_length:
                self._post_calibration_coordinate_uses += 1
        else:
            self._position = (
                (self._position[0] + effect[0]) % GRID_SIZE,
                (self._position[1] + effect[1]) % GRID_SIZE,
            )
        self._step_count += 1
        self._action_count += 1
        coordinate_gate = (
            ActionName.ACTION6 not in self._handles or self._post_calibration_coordinate_uses > 0
        )
        if (
            self._step_count >= self.calibration_length + 4
            and self._position == self._target
            and coordinate_gate
        ):
            self._state = GameStateName.WIN
        self._observation = self._make_observation(returned_action=action, full_reset=False)
        return self._observation

    def close(self) -> ScoreSummary:
        self._closed = True
        completed = self._state is GameStateName.WIN
        score = 1.0 if completed else 0.0
        run = ScoreRunSummary(
            game_id=GAME_ID,
            score=score,
            levels_completed=1 if completed else 0,
            actions=self._action_count,
            resets=self._reset_count,
            state=self._state,
            completed=completed,
            level_scores=(score,),
            level_actions=(self._action_count,),
        )
        return ScoreSummary(
            surface=EvaluationSurface.SYNTHETIC,
            verified=True,
            scorer="arc3.build-001.stage05.toroidal-action.v0.1",
            score=score,
            runs=(run,),
        )


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _signed_seed(value: int) -> int:
    """Map a derived unsigned 64-bit seed into ARC3Config's signed domain."""

    return value if value < 2**63 else value - 2**64


def _git_value(*arguments: str) -> str | None:
    try:
        completed = subprocess.run(
            ("git", *arguments),
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return completed.stdout.strip() if completed.returncode == 0 else None


def _package_version(name: str) -> str:
    try:
        return version(name)
    except PackageNotFoundError:
        return "not-installed"


def _source_identity() -> dict[str, object]:
    candidates: list[Path] = []
    for directory in (ROOT / "src/arc3", ROOT / "agent"):
        candidates.extend(
            path
            for path in directory.rglob("*.py")
            if path.is_file() and "__pycache__" not in path.parts
        )
    candidates.extend(
        path
        for path in (
            Path(__file__).resolve(),
            ROOT / "scripts/check_action_semantics.py",
            PREDECLARATION,
            ROOT / "pyproject.toml",
            ROOT / "uv.lock",
        )
        if path.is_file()
    )
    entries = [
        {"path": path.relative_to(ROOT).as_posix(), "sha256": sha256_file(path)}
        for path in sorted(set(candidates))
    ]
    status = _git_value("status", "--porcelain=v1")
    return seal_object(
        {
            "branch": _git_value("branch", "--show-current"),
            "dirty_worktree": status is None or bool(status),
            "dirty_worktree_reason": "git status unavailable" if status is None else None,
            "first_party_source_file_count": len(entries),
            "first_party_source_hash": sha256_bytes(canonical_json_bytes(entries)),
            "git_commit": _git_value("rev-parse", "HEAD"),
            "git_tree": _git_value("rev-parse", "HEAD^{tree}"),
            "worktree_status_hash": (
                None if status is None else sha256_bytes((status + "\n").encode("utf-8"))
            ),
        },
        hash_field="identity_hash",
    )


def _runtime_identity() -> dict[str, object]:
    memory = process_memory_sample()
    return {
        "logical_cpu_count": os.cpu_count(),
        "machine": platform.machine(),
        "memory_measurement_source": memory.get("measurement_source"),
        "packages": {
            "arc3": _package_version("arc3"),
            "numpy": _package_version("numpy"),
            "pydantic": _package_version("pydantic"),
            "psutil": _package_version("psutil"),
        },
        "platform": platform.platform(),
        "processor": platform.processor() or None,
        "python": platform.python_version(),
        "python_executable": str(Path(sys.executable).resolve()),
        "python_implementation": platform.python_implementation(),
        "timer": {"cpu": "time.process_time_ns", "wall": "time.perf_counter_ns"},
    }


def _context(
    root: Path,
    *,
    run_id: str,
    game_id: str,
    seed: int,
    git_commit: str,
    automatic_checkpoints: bool,
) -> RunContext:
    return RunContext(
        run_id=run_id,
        episode_id=f"{run_id}-episode",
        game_id=game_id,
        trace_root=root / "trace",
        checkpoint_root=root / "checkpoint",
        config=ARC3Config(
            seed=seed,
            network_enabled=False,
            profile=(
                "build-001-stage05-checkpoint"
                if automatic_checkpoints
                else "build-001-stage05-bulk-no-auto-checkpoint"
            ),
            budgets=BudgetConfig(
                max_actions=MAX_ACTIONS,
                max_resets=MAX_RESETS,
                wall_clock_seconds=60.0,
                max_coordinate_candidates=MAX_COORDINATE_CANDIDATES,
                max_search_nodes=2_048,
            ),
        ),
        git_commit=git_commit,
        source_kind="build-001-stage05-action-equivariance",
        source_version="0.1",
    )


def _action_payload(action: ActionRequest) -> dict[str, JSONValue]:
    return {
        "name": action.name.value,
        "coordinate": (
            None
            if action.coordinate is None
            else {"x": action.coordinate.x, "y": action.coordinate.y}
        ),
    }


def _trace_frame_hash(frame: GridFrame) -> str:
    return trace_sha256_bytes(trace_canonical_bytes([list(row) for row in frame.cells]))


def _verify_trace(root: Path, run_id: str, frame_hashes: Sequence[str]) -> dict[str, object]:
    journal = EventJournal(root, run_id=run_id)
    engine = ReplayEngine(journal)
    events = engine.verify_integrity()
    replayed = engine.replay_frames()
    trace_files = [path for path in sorted(root.rglob("*")) if path.is_file()]
    inventory = [
        {"path": path.relative_to(root).as_posix(), "sha256": sha256_file(path)}
        for path in trace_files
    ]
    event_counts: dict[str, int] = {}
    for event in events:
        event_counts[event.event_type] = event_counts.get(event.event_type, 0) + 1
    result = {
        "event_count": len(events),
        "event_type_counts": event_counts,
        "frame_count": len(replayed),
        "frame_hashes_match_raw_receipts": (
            [str(item.frame_hash) for item in replayed] == list(frame_hashes)
        ),
        "manifest_hash": journal.manifest.manifest_hash,
        "replay_verified": True,
        "selected_action_receipts": [
            {
                "raw_resolution_kind": event.payload.get("raw_resolution_kind"),
                "selected_action": event.payload.get("selected_action"),
                "selected_canonical_effect": event.payload.get("selected_canonical_effect"),
            }
            for event in events
            if event.event_type == "action.selected"
        ],
        "tail_event_hash": events[-1].event_hash if events else None,
        "trace_file_count": len(inventory),
        "trace_inventory_hash": sha256_bytes(canonical_json_bytes(inventory)),
    }
    journal.close()
    return result


def _registry_projection(controller: ARC3Controller) -> object:
    return getattr(controller, "action_effect_projection", None)


def _calibration_projection(controller: ARC3Controller) -> object:
    return getattr(controller, "action_calibration_projection", None)


def _rss_value(sample: Mapping[str, JSONValue], key: str) -> int | None:
    value = sample.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _rss_report(
    before: Mapping[str, JSONValue], after: Mapping[str, JSONValue]
) -> dict[str, object]:
    peaks = [
        item
        for item in (_rss_value(before, "peak_rss_bytes"), _rss_value(after, "peak_rss_bytes"))
        if item is not None
    ]
    return {
        "before": dict(before),
        "after": dict(after),
        "process_peak_rss_bytes": max(peaks) if peaks else None,
        "scope": "whole-process; peak may include earlier cases",
    }


def _run_controller_episode(
    session: _Session,
    *,
    root: Path,
    run_id: str,
    seed: int,
    git_commit: str,
    automatic_checkpoints: bool,
) -> dict[str, object]:
    before_rss = process_memory_sample()
    wall_started_ns = time.perf_counter_ns()
    cpu_started_ns = time.process_time_ns()
    features = replace(preset_features(ControllerPreset.FULL), use_memory=automatic_checkpoints)
    controller = ARC3Controller(ControllerPreset.FULL, features=features)
    context = _context(
        root,
        run_id=run_id,
        game_id=str(session.observation.game_id),
        seed=seed,
        git_commit=git_commit,
        automatic_checkpoints=automatic_checkpoints,
    )
    observations = [session.observation]
    actions: list[dict[str, JSONValue]] = []
    canonical_effects: list[object] = []
    canonical_states: list[object] = [
        session.canonical_state() if isinstance(session, ToroidalActionSession) else None
    ]
    registry_projections: list[object] = []
    calibration_projections: list[object] = []
    failures: list[dict[str, str]] = []
    controller.reset(context)
    controller.observe(session.observation)
    if automatic_checkpoints:
        registry_projections.append(_registry_projection(controller))
        calibration_projections.append(_calibration_projection(controller))
    while len(actions) < MAX_ACTIONS and controller.phase not in {
        ControllerPhase.COMPLETE,
        ControllerPhase.GAME_OVER,
    }:
        try:
            decision = controller.choose_action()
            action = decision.action
            consequence = session.step(action)
        except Exception as error:  # retained as a typed measurement failure
            failures.append({"kind": type(error).__name__, "message": str(error)})
            break
        actions.append(_action_payload(action))
        if isinstance(session, ToroidalActionSession):
            canonical_effects.append(session.canonical_effect(action))
            canonical_states.append(session.canonical_state())
        observations.append(consequence)
        controller.apply_consequence(consequence)
        if automatic_checkpoints:
            registry_projections.append(_registry_projection(controller))
            calibration_projections.append(_calibration_projection(controller))
    snapshot = controller.snapshot
    terminal_state = session.observation.state
    controller.close()
    scorecard = session.close()
    wall_ns = max(0, time.perf_counter_ns() - wall_started_ns)
    cpu_ns = max(0, time.process_time_ns() - cpu_started_ns)
    after_rss = process_memory_sample()
    trace_hashes = [_trace_frame_hash(item.frames[-1]) for item in observations]
    trace = _verify_trace(context.trace_root, run_id, trace_hashes)
    return {
        "action_count": len(actions),
        "action_request_sequence": actions,
        "calibration_projections": calibration_projections,
        "canonical_effect_trajectory": canonical_effects,
        "canonical_state_trajectory": canonical_states,
        "completed": scorecard.runs[0].completed,
        "controller_fault_count": snapshot.fault_count,
        "cpu_ns": cpu_ns,
        "failures": failures,
        "final_action_calibration_projection": _calibration_projection(controller),
        "final_action_effect_projection": _registry_projection(controller),
        "initial_raw_frame_hash": str(observations[0].frames[-1].digest),
        "raw_frame_hashes": [str(item.frames[-1].digest) for item in observations],
        "registry_projections": registry_projections,
        "resets": scorecard.total_resets,
        "rss": _rss_report(before_rss, after_rss),
        "score": scorecard.score,
        "terminal_phase": terminal_state.value,
        "trace": trace,
        "wall_ns": wall_ns,
    }


def _inverse_payload(
    payload: Mapping[str, object], pi: Mapping[ActionName, ActionName]
) -> dict[str, object]:
    inverse = {paired.value: base.value for base, paired in pi.items()}
    raw_name = str(payload["name"])
    return {
        "name": inverse.get(raw_name, raw_name),
        "coordinate": payload.get("coordinate"),
    }


def _trace_passed(episode: Mapping[str, object]) -> bool:
    trace = cast(Mapping[str, object], episode["trace"])
    return trace["replay_verified"] is True and trace["frame_hashes_match_raw_receipts"] is True


def _post_prefix_trajectories(
    episode: Mapping[str, object], calibration_length: int
) -> tuple[list[object], list[object]]:
    """Return consequences strictly after the charged calibration prefix."""

    effects = cast(Sequence[object], episode["canonical_effect_trajectory"])
    states = cast(Sequence[object], episode["canonical_state_trajectory"])
    return list(effects[calibration_length:]), list(states[calibration_length + 1 :])


def _procedural_pair(
    specification: ActionPairSpec,
    *,
    root: Path,
    git_commit: str,
) -> dict[str, object]:
    environment_seed = derive_seed(specification.seed, f"build-001-stage05-{specification.family}")
    base = _run_controller_episode(
        ToroidalActionSession(specification, transformed=False),
        root=root / "base",
        run_id=f"{specification.pair_id}-base",
        seed=_signed_seed(environment_seed),
        git_commit=git_commit,
        automatic_checkpoints=False,
    )
    paired = _run_controller_episode(
        ToroidalActionSession(specification, transformed=True),
        root=root / "permuted",
        run_id=f"{specification.pair_id}-permuted",
        seed=_signed_seed(environment_seed),
        git_commit=git_commit,
        automatic_checkpoints=False,
    )
    k = specification.calibration_length
    base_actions = cast(Sequence[Mapping[str, object]], base["action_request_sequence"])
    paired_actions = cast(Sequence[Mapping[str, object]], paired["action_request_sequence"])
    expected_prefix = [
        {
            "name": action.value,
            "coordinate": ({"x": 3, "y": 3} if action is ActionName.ACTION6 else None),
        }
        for action in sorted(specification.handles, key=_WIRE_RANK.__getitem__)
    ]
    base_prefix = list(base_actions[:k])
    paired_prefix = list(paired_actions[:k])
    base_post = list(base_actions[k:])
    paired_post = list(paired_actions[k:])
    inverse_paired = [_inverse_payload(item, specification.pi) for item in paired_post]
    denominator = max(len(base_post), len(inverse_paired))
    numerator = sum(left == right for left, right in zip(base_post, inverse_paired, strict=False))
    inverse_exact = denominator >= 4 and numerator == denominator
    base_effects, base_states = _post_prefix_trajectories(base, k)
    paired_effects, paired_states = _post_prefix_trajectories(paired, k)
    # State index zero is the initial observation and index K is the prefix
    # boundary.  Eligible post-prefix consequences therefore begin at K + 1.
    coordinate_parity = True
    coordinate_executed = True
    if specification.family == "mixed_coordinate":
        coordinate_base = [
            item for item in base_actions[k:] if item["name"] == ActionName.ACTION6.value
        ]
        coordinate_paired = [
            item for item in paired_actions[k:] if item["name"] == ActionName.ACTION6.value
        ]
        coordinate_executed = bool(coordinate_base) and bool(coordinate_paired)
        coordinate_parity = coordinate_base == coordinate_paired
    predicates = {
        "calibration_prefix_base": base_prefix == expected_prefix,
        "calibration_prefix_permuted": paired_prefix == expected_prefix,
        "canonical_effect_trajectory": base_effects == paired_effects,
        "canonical_state_trajectory_after_prefix": base_states == paired_states,
        "completion": base["completed"] == paired["completed"],
        "coordinate_exact_request_and_consequence": coordinate_executed and coordinate_parity,
        "minimum_four_post_calibration_actions": denominator >= 4,
        "post_calibration_inverse_requests": inverse_exact,
        "score": base["score"] == paired["score"],
        "terminal_phase": base["terminal_phase"] == paired["terminal_phase"],
        "traces": _trace_passed(base) and _trace_passed(paired),
        "validity": (
            not base["failures"]
            and not paired["failures"]
            and base["controller_fault_count"] == 0
            and paired["controller_fault_count"] == 0
            and base["resets"] == 0
            and paired["resets"] == 0
        ),
    }
    return {
        "base": base,
        "calibration_length": k,
        "environment_seed": environment_seed,
        "family": specification.family,
        "inverse_request_denominator": denominator,
        "inverse_request_numerator": numerator,
        "pair_id": specification.pair_id,
        "pair_passed": all(predicates.values()),
        "permutation": {key.value: value.value for key, value in specification.pi.items()},
        "permutation_id": specification.permutation_id,
        "permuted": paired,
        "predicates": predicates,
        "seed": specification.seed,
    }


def _procedural_suite(work_root: Path, git_commit: str) -> dict[str, object]:
    cases = [
        _procedural_pair(
            specification,
            root=work_root / specification.pair_id,
            git_commit=git_commit,
        )
        for specification in action_suite_schedule()
    ]
    total_denominator = sum(cast(int, item["inverse_request_denominator"]) for item in cases)
    total_numerator = sum(cast(int, item["inverse_request_numerator"]) for item in cases)
    predicate_names = tuple(cast(Mapping[str, bool], cases[0]["predicates"])) if cases else ()
    return {
        "family_counts": {
            family: sum(item["family"] == family for item in cases)
            for family in (
                "full_four_handle",
                "partial_two_handle",
                "partial_three_handle",
                "mixed_coordinate",
            )
        },
        "pair_count": len(cases),
        "pairs": cases,
        "passed_pairs": sum(item["pair_passed"] is True for item in cases),
        "post_calibration_inverse_request_equivariance": (
            total_numerator / total_denominator if total_denominator else None
        ),
        "post_calibration_inverse_request_numerator": total_numerator,
        "post_calibration_inverse_request_denominator": total_denominator,
        "predicate_pass_counts": {
            name: sum(cast(Mapping[str, bool], item["predicates"])[name] for item in cases)
            for name in predicate_names
        },
    }


def _historical_suite(work_root: Path, git_commit: str) -> dict[str, object]:
    cases: list[dict[str, object]] = []
    for seed in HISTORICAL_SEEDS:
        base = _run_controller_episode(
            TransformedSyntheticSession(
                seed=seed,
                size=GRID_SIZE,
                max_steps=MAX_ACTIONS,
                variant=RobustnessVariant.BASE,
            ),
            root=work_root / f"seed-{seed}" / "base",
            run_id=f"stage05-historical-{seed}-base",
            seed=seed,
            git_commit=git_commit,
            automatic_checkpoints=True,
        )
        remapped = _run_controller_episode(
            TransformedSyntheticSession(
                seed=seed,
                size=GRID_SIZE,
                max_steps=MAX_ACTIONS,
                variant=RobustnessVariant.ACTION_REMAP,
            ),
            root=work_root / f"seed-{seed}" / "action-remap",
            run_id=f"stage05-historical-{seed}-action-remap",
            seed=seed,
            git_commit=git_commit,
            automatic_checkpoints=True,
        )
        predicates = {
            "both_complete": base["completed"] is True and remapped["completed"] is True,
            "budget": (
                cast(int, base["action_count"]) <= MAX_ACTIONS
                and cast(int, remapped["action_count"]) <= MAX_ACTIONS
                and cast(int, base["resets"]) <= MAX_RESETS
                and cast(int, remapped["resets"]) <= MAX_RESETS
            ),
            "score": base["score"] == remapped["score"],
            "terminal_phase": base["terminal_phase"] == remapped["terminal_phase"],
            "traces": _trace_passed(base) and _trace_passed(remapped),
            "validity": (
                not base["failures"]
                and not remapped["failures"]
                and base["controller_fault_count"] == 0
                and remapped["controller_fault_count"] == 0
            ),
        }
        cases.append(
            {
                "base": base,
                "case_passed": all(predicates.values()),
                "full_sequence_inverse_request_metric": ("NOT_APPLICABLE_CALIBRATION_SYMMETRY"),
                "predicates": predicates,
                "remapped": remapped,
                "seed": seed,
            }
        )
    return {
        "case_count": len(cases),
        "cases": cases,
        "passed_cases": sum(item["case_passed"] is True for item in cases),
    }


def _rows(points: Sequence[tuple[int, int, int]], *, size: int = 8) -> list[list[int]]:
    rows = [[0 for _ in range(size)] for _ in range(size)]
    for x, y, color in points:
        rows[y][x] = color
    return rows


def _observation(
    rows: Sequence[Sequence[int]],
    *,
    returned_action: ActionRequest | None,
    metadata: tuple[tuple[str, int | str | bool | float | None], ...] = (),
    available_actions: tuple[ActionName, ...] = tuple(ActionName)[1:],
) -> Observation:
    return Observation(
        game_id=GAME_ID,
        frames=(GridFrame.from_rows(rows),),
        state=GameStateName.NOT_FINISHED,
        levels_completed=0,
        win_levels=1,
        available_actions=available_actions,
        returned_action=returned_action,
        upstream_metadata=metadata,
    )


def _candidate_projection(registry: ActionEffectRegistry) -> list[Mapping[str, object]]:
    projection = registry.projection()
    candidates = projection.get("candidates")
    if not isinstance(candidates, list):
        raise RuntimeError("action-effect registry projection omitted candidates")
    return cast(list[Mapping[str, object]], candidates)


def _request(handle: ActionName) -> ActionRequest:
    return ActionRequest(
        handle,
        CALIBRATION_COORDINATE if handle.requires_coordinates else None,
    )


def _registry_roundtrip(registry: ActionEffectRegistry) -> dict[str, object]:
    projection = registry.projection()
    restored = ActionEffectRegistry.from_projection(projection)
    raw = canonical_json_bytes(projection)
    return {
        "candidate_count": registry.candidate_count,
        "max_candidates_per_handle": registry.max_candidates_per_handle,
        "max_raw_handles": registry.max_raw_handles,
        "projection_hash": sha256_bytes(raw),
        "projection_roundtrip_exact": restored.projection() == projection,
    }


def _raw_receipt(
    before: Observation,
    action: ActionRequest,
    after: Observation,
    source_event_id: str,
) -> dict[str, object]:
    return seal_object(
        {
            "action": _action_payload(action),
            "after_frame_hash": str(after.frames[-1].digest),
            "before_frame_hash": str(before.frames[-1].digest),
            "returned_action": (
                _action_payload(after.returned_action)
                if after.returned_action is not None
                else None
            ),
            "source_event_id": source_event_id,
        },
        hash_field="receipt_hash",
    )


def _multi_displacement_case(seed: int) -> dict[str, object]:
    action = _request(tuple(ActionName)[1 + seed % 7])
    before = _observation(_rows(((1, 1, 1), (5, 5, 2))), returned_action=None)
    after = _observation(
        _rows(((2, 1, 1), (5, 4, 2))),
        returned_action=action,
    )
    source = f"stage05-control-multi-{seed}"
    registry = ActionEffectRegistry()
    observation = registry.observe_transition(before, action, after, source_event_id=source)
    candidates = registry.candidates_for(action.name)
    translations = {
        candidate.canonical_effect.translation
        for candidate in candidates
        if candidate.canonical_effect.translation is not None
    }
    passed = (
        observation.ambiguous
        and translations == {(1, 0), (0, -1)}
        and all(candidate.status is ActionEffectStatus.AMBIGUOUS for candidate in candidates)
        and not registry.accepted_effects(action.name)
    )
    return {
        "case_id": source,
        "family": "multi_displacement_ambiguity",
        "passed": passed,
        "raw_receipts": [_raw_receipt(before, action, after, source)],
        "registry": registry.projection(),
        "replay": _registry_roundtrip(registry),
        "seed": seed,
    }


def _conditional_case(seed: int) -> dict[str, object]:
    action = _request(tuple(ActionName)[1 + seed % 7])
    before_move = _observation(_rows(((1, 1, 1),)), returned_action=None)
    after_move = _observation(_rows(((2, 1, 1),)), returned_action=action)
    before_noop = _observation(_rows(((1, 1, 1), (6, 6, 2))), returned_action=None)
    after_noop = _observation(_rows(((1, 1, 1), (6, 6, 2))), returned_action=action)
    move_source = f"stage05-control-conditional-{seed}-movement"
    noop_source = f"stage05-control-conditional-{seed}-noop"
    registry = ActionEffectRegistry()
    registry.observe_transition(before_move, action, after_move, source_event_id=move_source)
    registry.observe_transition(before_noop, action, after_noop, source_event_id=noop_source)
    candidates = registry.candidates_for(action.name)
    kinds = {candidate.canonical_effect.effect_kind for candidate in candidates}
    conditions = {candidate.canonical_effect.condition_signature for candidate in candidates}
    passed = (
        CanonicalEffectKind.TRANSLATION in kinds
        and CanonicalEffectKind.NO_OP in kinds
        and len(conditions) == 2
        and all(candidate.status is ActionEffectStatus.ACCEPTED for candidate in candidates)
    )
    return {
        "case_id": f"stage05-control-conditional-{seed}",
        "family": "conditional_noop_and_movement",
        "passed": passed,
        "raw_receipts": [
            _raw_receipt(before_move, action, after_move, move_source),
            _raw_receipt(before_noop, action, after_noop, noop_source),
        ],
        "registry": registry.projection(),
        "replay": _registry_roundtrip(registry),
        "seed": seed,
    }


def _restore_case(seed: int) -> dict[str, object]:
    restore_handles = (ActionName.ACTION2, ActionName.ACTION5, ActionName.ACTION7)
    restore_handle = restore_handles[(seed - 1200) % len(restore_handles)]
    restore_action = ActionRequest(restore_handle)
    prior = _observation(_rows(((1, 1, 1),)), returned_action=None)
    changed = _observation(_rows(((2, 1, 1),)), returned_action=None)
    restored = _observation(_rows(((1, 1, 1),)), returned_action=restore_action)
    source = f"stage05-control-restore-{seed}-{restore_handle.value}"
    registry = ActionEffectRegistry()
    registry.observe_transition(
        changed,
        restore_action,
        restored,
        source_event_id=source,
        prior_frame_hashes=(prior.frames[-1].digest,),
    )
    raw_receipts = [_raw_receipt(changed, restore_action, restored, source)]
    action7_negative = True
    if restore_handle is not ActionName.ACTION7:
        negative_action = ActionRequest(ActionName.ACTION7)
        negative_after = _observation(_rows(((3, 1, 1),)), returned_action=negative_action)
        negative_source = f"stage05-control-restore-{seed}-action7-negative"
        registry.observe_transition(
            changed,
            negative_action,
            negative_after,
            source_event_id=negative_source,
            prior_frame_hashes=(prior.frames[-1].digest,),
        )
        raw_receipts.append(_raw_receipt(changed, negative_action, negative_after, negative_source))
        action7_negative = all(
            candidate.canonical_effect.effect_kind is not CanonicalEffectKind.RESTORE
            for candidate in registry.candidates_for(ActionName.ACTION7)
        )
    restore_candidates = registry.candidates_for(restore_handle)
    passed = (
        any(
            candidate.canonical_effect.effect_kind is CanonicalEffectKind.RESTORE
            and candidate.status is ActionEffectStatus.ACCEPTED
            for candidate in restore_candidates
        )
        and action7_negative
        and all(
            candidate.canonical_effect.effect_kind is not CanonicalEffectKind.RESTORE
            for handle in registry.handles
            if handle is not restore_handle
            for candidate in registry.candidates_for(handle)
        )
    )
    return {
        "action7_negative": action7_negative,
        "case_id": f"stage05-control-restore-{seed}",
        "family": "restore_any_handle_and_action7_negative",
        "passed": passed,
        "raw_receipts": raw_receipts,
        "registry": registry.projection(),
        "replay": _registry_roundtrip(registry),
        "restore_handle": restore_handle.value,
        "seed": seed,
    }


def _coordinate_case(seed: int) -> dict[str, object]:
    action = ActionRequest(ActionName.ACTION6, CALIBRATION_COORDINATE)
    before = _observation(_rows(((3, 3, 1), (7, 7, 2))), returned_action=None)
    changed_point = (3, 3, 3) if seed % 2 == 0 else (7, 7, 3)
    unchanged = (7, 7, 2) if seed % 2 == 0 else (3, 3, 1)
    after = _observation(_rows((changed_point, unchanged)), returned_action=action)
    source = f"stage05-control-coordinate-{seed}"
    registry = ActionEffectRegistry()
    registry.observe_transition(before, action, after, source_event_id=source)
    candidates = registry.candidates_for(ActionName.ACTION6)
    expected = CoordinateRelation.LOCAL if seed % 2 == 0 else CoordinateRelation.DISTANT
    passed = (
        bool(candidates)
        and all(
            candidate.canonical_effect.coordinate_relation is expected for candidate in candidates
        )
        and all(
            candidate.canonical_effect.effect_kind is CanonicalEffectKind.TRANSFORM
            for candidate in candidates
        )
    )
    return {
        "case_id": source,
        "expected_coordinate_relation": expected.value,
        "family": "coordinate_related_and_unrelated_change",
        "passed": passed,
        "raw_receipts": [_raw_receipt(before, action, after, source)],
        "registry": registry.projection(),
        "replay": _registry_roundtrip(registry),
        "seed": seed,
    }


def _causal_control_suite() -> dict[str, object]:
    cases: list[dict[str, object]] = []
    cases.extend(_multi_displacement_case(seed) for seed in range(1000, 1016))
    cases.extend(_conditional_case(seed) for seed in range(1100, 1116))
    cases.extend(_restore_case(seed) for seed in range(1200, 1216))
    cases.extend(_coordinate_case(seed) for seed in range(1300, 1316))
    return {
        "case_count": len(cases),
        "cases": cases,
        "family_counts": {
            family: sum(item["family"] == family for item in cases)
            for family in (
                "multi_displacement_ambiguity",
                "conditional_noop_and_movement",
                "restore_any_handle_and_action7_negative",
                "coordinate_related_and_unrelated_change",
            )
        },
        "passed_cases": sum(
            item["passed"] is True
            and cast(Mapping[str, object], item["replay"])["projection_roundtrip_exact"] is True
            for item in cases
        ),
    }


def _submitted_count(controller: ARC3Controller) -> int:
    return sum(
        event.event_type == "action.submitted" for event in controller.journal.verify_manifest()
    )


def _checkpoint_has_registry(checkpoint_state: Mapping[str, object]) -> bool:
    derived = checkpoint_state.get("derived_controller_state")
    if not isinstance(derived, Mapping):
        return False
    semantics = derived.get("action_semantics")
    return isinstance(semantics, Mapping) and isinstance(semantics.get("registry"), Mapping)


def _canonical_registry_projection(value: object) -> object:
    """Canonicalize run-local receipt IDs while preserving provenance topology."""

    if not isinstance(value, Mapping):
        return value
    candidates_value = value.get("candidates")
    processed_value = value.get("processed_event_ids")
    if not isinstance(candidates_value, Sequence) or isinstance(candidates_value, (str, bytes)):
        return dict(value)
    if not isinstance(processed_value, Sequence) or isinstance(processed_value, (str, bytes)):
        return dict(value)

    aliases: dict[str, str] = {}

    def alias(source: str) -> str:
        if source not in aliases:
            aliases[source] = f"receipt-{len(aliases):08d}"
        return aliases[source]

    canonical_candidates: list[object] = []
    for candidate_value in candidates_value:
        if not isinstance(candidate_value, Mapping):
            canonical_candidates.append(candidate_value)
            continue
        candidate = dict(candidate_value)
        sources = candidate.get("source_event_ids")
        if isinstance(sources, Sequence) and not isinstance(sources, (str, bytes)):
            candidate["source_event_ids"] = [
                alias(source) if isinstance(source, str) else source for source in sources
            ]
        canonical_candidates.append(candidate)

    for source in processed_value:
        if isinstance(source, str):
            alias(source)
    canonical = dict(value)
    canonical["candidates"] = canonical_candidates
    canonical["processed_event_ids"] = sorted(aliases.values())
    return canonical


def _checkpoint_resumed_episode(
    specification: ActionPairSpec,
    *,
    root: Path,
    git_commit: str,
) -> dict[str, object]:
    session = ToroidalActionSession(specification, transformed=True)
    run_id = f"stage05-checkpoint-{specification.seed}"
    environment_seed = derive_seed(specification.seed, "build-001-stage05-full_four_handle")
    context = _context(
        root,
        run_id=run_id,
        game_id=str(GAME_ID),
        seed=_signed_seed(environment_seed),
        git_commit=git_commit,
        automatic_checkpoints=True,
    )
    controller = ARC3Controller(ControllerPreset.FULL)
    observations = [session.observation]
    actions: list[dict[str, JSONValue]] = []
    effects: list[object] = []
    states: list[object] = [session.canonical_state()]
    failures: list[dict[str, str]] = []
    before_rss = process_memory_sample()
    wall_started_ns = time.perf_counter_ns()
    cpu_started_ns = time.process_time_ns()
    controller.reset(context)
    controller.observe(session.observation)
    for _ in range(specification.calibration_length):
        decision = controller.choose_action()
        action = decision.action
        consequence = session.step(action)
        actions.append(_action_payload(action))
        effects.append(session.canonical_effect(action))
        states.append(session.canonical_state())
        observations.append(consequence)
        controller.apply_consequence(consequence)
    if session.observation.state is not GameStateName.NOT_FINISHED:
        raise RuntimeError("checkpoint fixture terminated during calibration")
    projection_before = _registry_projection(controller)
    calibration_before = _calibration_projection(controller)
    checkpoint = controller.checkpoint()
    state_value = checkpoint.envelope.state
    registry_serialized = _checkpoint_has_registry(cast(Mapping[str, object], state_value))
    submitted_before = _submitted_count(controller)
    controller.journal.close()

    restored = ARC3Controller.restore(
        context,
        preset=ControllerPreset.FULL,
        checkpoint_path=checkpoint.path,
    )
    projection_after = _registry_projection(restored)
    calibration_after = _calibration_projection(restored)
    submitted_after_restore = _submitted_count(restored)
    while len(actions) < MAX_ACTIONS and restored.phase not in {
        ControllerPhase.COMPLETE,
        ControllerPhase.GAME_OVER,
    }:
        try:
            decision = restored.choose_action()
            action = decision.action
            consequence = session.step(action)
        except Exception as error:
            failures.append({"kind": type(error).__name__, "message": str(error)})
            break
        actions.append(_action_payload(action))
        effects.append(session.canonical_effect(action))
        states.append(session.canonical_state())
        observations.append(consequence)
        restored.apply_consequence(consequence)
    snapshot = restored.snapshot
    submitted_final = _submitted_count(restored)
    final_projection = _registry_projection(restored)
    final_calibration = _calibration_projection(restored)
    terminal_state = session.observation.state
    restored.close()
    scorecard = session.close()
    wall_ns = max(0, time.perf_counter_ns() - wall_started_ns)
    cpu_ns = max(0, time.process_time_ns() - cpu_started_ns)
    after_rss = process_memory_sample()
    trace_hashes = [_trace_frame_hash(item.frames[-1]) for item in observations]
    trace = _verify_trace(context.trace_root, run_id, trace_hashes)
    return {
        "action_count": len(actions),
        "action_request_sequence": actions,
        "boundary_calibration_projection": calibration_before,
        "boundary_registry_projection": projection_before,
        "calibration_projection_stable_across_restore": (calibration_before == calibration_after),
        "canonical_effect_trajectory": effects,
        "canonical_state_trajectory": states,
        "checkpoint_file_sha256": sha256_file(checkpoint.path),
        "checkpoint_hash": checkpoint.envelope.checkpoint_hash,
        "checkpoint_registry_serialized": registry_serialized,
        "completed": scorecard.runs[0].completed,
        "controller_fault_count": snapshot.fault_count,
        "cpu_ns": cpu_ns,
        "failures": failures,
        "final_calibration_projection": final_calibration,
        "final_registry_projection": final_projection,
        "no_resubmission": (
            submitted_before == specification.calibration_length
            and submitted_after_restore == submitted_before
            and submitted_final == len(actions)
        ),
        "raw_frame_hashes": [str(item.frames[-1].digest) for item in observations],
        "registry_projection_stable_across_restore": projection_before == projection_after,
        "resets": scorecard.total_resets,
        "rss": _rss_report(before_rss, after_rss),
        "score": scorecard.score,
        "terminal_phase": terminal_state.value,
        "trace": trace,
        "wall_ns": wall_ns,
    }


def _selected_choice(episode: Mapping[str, object], index: int) -> object:
    trace = cast(Mapping[str, object], episode["trace"])
    receipts = cast(Sequence[object], trace["selected_action_receipts"])
    return receipts[index] if index < len(receipts) else None


def _checkpoint_suite(
    work_root: Path,
    git_commit: str,
    *,
    seeds: Sequence[int] = CHECKPOINT_SEEDS,
) -> dict[str, object]:
    schedule = action_suite_schedule()[:96]
    cases: list[dict[str, object]] = []
    for seed in seeds:
        if seed not in CHECKPOINT_SEEDS:
            raise ValueError(f"checkpoint seed is outside the frozen schedule: {seed}")
        specification = schedule[seed * 6 + seed % 6]
        run_id = f"stage05-checkpoint-{seed}"
        uninterrupted = _run_controller_episode(
            ToroidalActionSession(specification, transformed=True),
            root=work_root / f"seed-{seed}" / "uninterrupted",
            run_id=run_id,
            seed=_signed_seed(derive_seed(seed, "build-001-stage05-full_four_handle")),
            git_commit=git_commit,
            automatic_checkpoints=True,
        )
        resumed = _checkpoint_resumed_episode(
            specification,
            root=work_root / f"seed-{seed}" / "resumed",
            git_commit=git_commit,
        )
        k = specification.calibration_length
        uninterrupted_registry = cast(Sequence[object], uninterrupted["registry_projections"])
        uninterrupted_calibration = cast(Sequence[object], uninterrupted["calibration_projections"])
        uninterrupted_boundary_registry = (
            uninterrupted_registry[k] if len(uninterrupted_registry) > k else None
        )
        resumed_boundary_registry = resumed["boundary_registry_projection"]
        canonical_uninterrupted_registry = _canonical_registry_projection(
            uninterrupted_boundary_registry
        )
        canonical_resumed_registry = _canonical_registry_projection(resumed_boundary_registry)
        predicates = {
            "boundary_calibration_projection": (
                len(uninterrupted_calibration) > k
                and uninterrupted_calibration[k] == resumed["boundary_calibration_projection"]
            ),
            "boundary_registry_projection": (
                len(uninterrupted_registry) > k
                and canonical_uninterrupted_registry == canonical_resumed_registry
            ),
            "calibration_projection_stable_across_restore": resumed[
                "calibration_projection_stable_across_restore"
            ]
            is True,
            "final_action_sequence": (
                uninterrupted["action_request_sequence"] == resumed["action_request_sequence"]
            ),
            "final_canonical_effect_trajectory": (
                uninterrupted["canonical_effect_trajectory"]
                == resumed["canonical_effect_trajectory"]
            ),
            "final_canonical_state_trajectory": (
                uninterrupted["canonical_state_trajectory"] == resumed["canonical_state_trajectory"]
            ),
            "final_result": (
                uninterrupted["completed"] == resumed["completed"]
                and uninterrupted["score"] == resumed["score"]
                and uninterrupted["terminal_phase"] == resumed["terminal_phase"]
            ),
            "next_canonical_choice": (
                _selected_choice(uninterrupted, k) == _selected_choice(resumed, k)
            ),
            "no_resubmission": resumed["no_resubmission"] is True,
            "registry_projection_stable_across_restore": resumed[
                "registry_projection_stable_across_restore"
            ]
            is True,
            "registry_serialized": resumed["checkpoint_registry_serialized"] is True,
            "traces": _trace_passed(uninterrupted) and _trace_passed(resumed),
            "validity": (
                not uninterrupted["failures"]
                and not resumed["failures"]
                and uninterrupted["controller_fault_count"] == 0
                and resumed["controller_fault_count"] == 0
            ),
        }
        cases.append(
            {
                "case_passed": all(predicates.values()),
                "boundary_registry_comparison": {
                    "comparison": "exact after ordinal canonicalization of run-local receipt IDs",
                    "resumed_hash": sha256_bytes(canonical_json_bytes(canonical_resumed_registry)),
                    "uninterrupted_hash": sha256_bytes(
                        canonical_json_bytes(canonical_uninterrupted_registry)
                    ),
                },
                "permutation_id": specification.permutation_id,
                "predicates": predicates,
                "resumed": resumed,
                "seed": seed,
                "uninterrupted": uninterrupted,
            }
        )
    return {
        "case_count": len(cases),
        "cases": cases,
        "passed_cases": sum(item["case_passed"] is True for item in cases),
    }


def _jsonl_objects(path: Path) -> list[dict[str, object]]:
    if not path.is_file():
        return []
    objects: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        value = json.loads(line)
        if isinstance(value, dict):
            objects.append(cast(dict[str, object], value))
    return objects


def _contains_exact_string(value: object, targets: frozenset[str]) -> bool:
    if isinstance(value, str):
        return value in targets
    if isinstance(value, Mapping):
        return any(_contains_exact_string(item, targets) for item in value.values())
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return any(_contains_exact_string(item, targets) for item in value)
    return False


def _holdout_integrity(
    *,
    manifest_path: Path | None = None,
    exposure_ledgers: Sequence[tuple[str, Path]] | None = None,
    acquisition_roots: Sequence[Path] | None = None,
) -> dict[str, object]:
    selected_manifest = manifest_path or (ROOT / "docs/evaluation/public-game-partitions.v0.1.json")
    manifest = json.loads(selected_manifest.read_text(encoding="utf-8"))
    games = manifest.get("games", []) if isinstance(manifest, dict) else []
    holdout_ids = frozenset(
        str(item["game_id"])
        for item in games
        if isinstance(item, dict)
        and item.get("partition") == "public-holdout"
        and isinstance(item.get("game_id"), str)
    )
    using_frozen_ledgers = exposure_ledgers is None
    selected_ledgers = tuple(
        exposure_ledgers
        or (
            ("build-000", _BUILD_000_EXPOSURE_LEDGER),
            ("stage-03", _STAGE_03_EXPOSURE_LEDGER),
        )
    )
    ledger_receipts: list[dict[str, object]] = []
    holdout_events = 0
    for label, path in selected_ledgers:
        events = _jsonl_objects(path)
        ledger_holdout_events = sum(_contains_exact_string(event, holdout_ids) for event in events)
        holdout_events += ledger_holdout_events
        digest = sha256_file(path) if path.is_file() else None
        expected_digest = _FROZEN_EXPOSURE_HASHES.get(label) if using_frozen_ledgers else None
        ledger_receipts.append(
            {
                "event_count": len(events),
                "exists": path.is_file(),
                "frozen_sha256": expected_digest,
                "holdout_event_count": ledger_holdout_events,
                "label": label,
                "path": str(path),
                "sha256": digest,
                "sha256_matches_frozen": (
                    digest == expected_digest if expected_digest is not None else None
                ),
            }
        )

    roots = tuple(
        dict.fromkeys(
            path.resolve() for path in (acquisition_roots or _KNOWN_PUBLIC_ENVIRONMENT_ROOTS)
        )
    )
    asset_presence = [
        {
            "holdout_asset_directories_present": sum(
                (root / game_id).exists() for game_id in holdout_ids
            ),
            "path": str(root),
        }
        for root in roots
    ]
    acquired = sum(cast(int, item["holdout_asset_directories_present"]) for item in asset_presence)
    ledgers_present = all(item["exists"] is True for item in ledger_receipts)
    frozen_hashes_match = all(
        item["sha256_matches_frozen"] in {True, None} for item in ledger_receipts
    )
    build000_receipt = next(
        (item for item in ledger_receipts if item["label"] == "build-000"), None
    )
    stage03_receipt = next((item for item in ledger_receipts if item["label"] == "stage-03"), None)
    return {
        "acquisition_roots": asset_presence,
        "build_000_exposure_ledger": (
            build000_receipt["path"] if build000_receipt is not None else None
        ),
        "build_000_exposure_ledger_sha256": (
            build000_receipt["sha256"] if build000_receipt is not None else None
        ),
        "exposure_ledgers": ledger_receipts,
        "frozen_exposure_hashes_match": frozen_hashes_match,
        "locally_acquired_holdout_assets": acquired,
        "manifest_holdout_count": len(holdout_ids),
        "public_holdout_gameplay_events": holdout_events,
        "public_partition_manifest": str(selected_manifest),
        "public_partition_manifest_sha256": sha256_file(selected_manifest),
        "stage_03_exposure_ledger": (
            stage03_receipt["path"] if stage03_receipt is not None else None
        ),
        "stage_03_exposure_ledger_sha256": (
            stage03_receipt["sha256"] if stage03_receipt is not None else None
        ),
        "stage_05_public_gameplay_events": 0,
        "status": (
            "SEALED_UNCONSUMED"
            if len(holdout_ids) == 10
            and holdout_events == 0
            and acquired == 0
            and ledgers_present
            and frozen_hashes_match
            else "INTEGRITY_FAILURE"
        ),
    }


def _walk_named_values(value: object, name: str) -> list[object]:
    results: list[object] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            if key == name:
                results.append(item)
            results.extend(_walk_named_values(item, name))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for item in value:
            results.extend(_walk_named_values(item, name))
    return results


def _registry_projection_objects(value: object) -> list[Mapping[str, object]]:
    projections: list[Mapping[str, object]] = []
    if isinstance(value, Mapping):
        if value.get("schema") == "arc3.action-effect-registry.v1":
            projections.append(value)
            return projections
        for item in value.values():
            projections.extend(_registry_projection_objects(item))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for item in value:
            projections.extend(_registry_projection_objects(item))
    return projections


def _registry_bounds_summary(*suites: Mapping[str, object]) -> dict[str, object]:
    projections = [
        projection for suite in suites for projection in _registry_projection_objects(suite)
    ]
    maximum_handles = 0
    maximum_candidates = 0
    maximum_total_candidates = 0
    maximum_declared_handles = 0
    maximum_declared_candidates = 0
    violations: list[dict[str, object]] = []
    for index, projection in enumerate(projections):
        handles = projection.get("handles")
        candidates = projection.get("candidates")
        declared_handles = projection.get("max_raw_handles")
        declared_candidates = projection.get("max_candidates_per_handle")
        if not isinstance(handles, Sequence) or isinstance(handles, (str, bytes)):
            violations.append({"projection_index": index, "reason": "invalid handles"})
            continue
        if not isinstance(candidates, Sequence) or isinstance(candidates, (str, bytes)):
            violations.append({"projection_index": index, "reason": "invalid candidates"})
            continue
        if (
            isinstance(declared_handles, bool)
            or not isinstance(declared_handles, int)
            or isinstance(declared_candidates, bool)
            or not isinstance(declared_candidates, int)
        ):
            violations.append({"projection_index": index, "reason": "invalid declared bounds"})
            continue
        by_handle: dict[str, int] = {}
        malformed_candidate = False
        for candidate in candidates:
            if not isinstance(candidate, Mapping) or not isinstance(
                candidate.get("raw_handle"), str
            ):
                malformed_candidate = True
                continue
            raw_handle = cast(str, candidate["raw_handle"])
            by_handle[raw_handle] = by_handle.get(raw_handle, 0) + 1
        observed_per_handle = max(by_handle.values(), default=0)
        maximum_handles = max(maximum_handles, len(handles))
        maximum_candidates = max(maximum_candidates, observed_per_handle)
        maximum_total_candidates = max(maximum_total_candidates, len(candidates))
        maximum_declared_handles = max(maximum_declared_handles, declared_handles)
        maximum_declared_candidates = max(maximum_declared_candidates, declared_candidates)
        reasons: list[str] = []
        if malformed_candidate:
            reasons.append("malformed candidate")
        if len(handles) > 7 or declared_handles > 7:
            reasons.append("raw handle bound exceeded")
        if observed_per_handle > 32 or declared_candidates > 32:
            reasons.append("per-handle candidate bound exceeded")
        if len(set(str(item) for item in handles)) != len(handles):
            reasons.append("duplicate raw handles")
        if reasons:
            violations.append({"projection_index": index, "reasons": reasons})
    return {
        "maximum_declared_candidates_per_handle": maximum_declared_candidates,
        "maximum_declared_raw_handles": maximum_declared_handles,
        "maximum_observed_candidates_per_handle": maximum_candidates,
        "maximum_observed_candidates_total": maximum_total_candidates,
        "maximum_observed_raw_handles": maximum_handles,
        "passed": bool(projections) and not violations,
        "projection_count": len(projections),
        "violations": violations,
    }


def _episode_records(value: object) -> list[Mapping[str, object]]:
    episodes: list[Mapping[str, object]] = []
    if isinstance(value, Mapping):
        required = {"action_count", "controller_fault_count", "failures", "trace"}
        if required.issubset(value):
            episodes.append(value)
            return episodes
        for item in value.values():
            episodes.extend(_episode_records(item))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for item in value:
            episodes.extend(_episode_records(item))
    return episodes


def _aggregate_measurements(*suites: Mapping[str, object]) -> dict[str, object]:
    episodes = [episode for suite in suites for episode in _episode_records(suite)]
    action_counts = [
        cast(int, episode["action_count"])
        for episode in episodes
        if isinstance(episode.get("action_count"), int)
        and not isinstance(episode.get("action_count"), bool)
    ]
    reset_counts = [
        cast(int, episode.get("resets"))
        for episode in episodes
        if isinstance(episode.get("resets"), int) and not isinstance(episode.get("resets"), bool)
    ]
    fault_counts = [
        cast(int, episode["controller_fault_count"])
        for episode in episodes
        if isinstance(episode.get("controller_fault_count"), int)
        and not isinstance(episode.get("controller_fault_count"), bool)
    ]
    failure_count = sum(
        len(failures)
        for episode in episodes
        if isinstance((failures := episode.get("failures")), Sequence)
        and not isinstance(failures, (str, bytes))
    )
    traces = [
        cast(Mapping[str, object], episode["trace"])
        for episode in episodes
        if isinstance(episode.get("trace"), Mapping)
    ]
    event_count = sum(
        cast(int, trace["event_count"])
        for trace in traces
        if isinstance(trace.get("event_count"), int)
        and not isinstance(trace.get("event_count"), bool)
    )
    trace_file_count = sum(
        cast(int, trace["trace_file_count"])
        for trace in traces
        if isinstance(trace.get("trace_file_count"), int)
        and not isinstance(trace.get("trace_file_count"), bool)
    )
    trace_failures = sum(
        trace.get("replay_verified") is not True
        or trace.get("frame_hashes_match_raw_receipts") is not True
        for trace in traces
    )
    causal_raw_receipts = sum(
        len(receipts)
        for suite in suites
        for receipts in _walk_named_values(suite, "raw_receipts")
        if isinstance(receipts, Sequence) and not isinstance(receipts, (str, bytes))
    )
    action_budget_violations = sum(count > MAX_ACTIONS for count in action_counts)
    reset_budget_violations = sum(count > MAX_RESETS for count in reset_counts)
    controller_fault_count = sum(fault_counts)
    return {
        "action_budget_violations": action_budget_violations,
        "causal_control_raw_receipt_count": causal_raw_receipts,
        "controller_episode_count": len(episodes),
        "controller_fault_count": controller_fault_count,
        "environment_action_count": sum(action_counts),
        "invalid_request_count": failure_count,
        "invalid_request_count_basis": (
            "conservative count of every caught choose, validation, or step failure"
        ),
        "maximum_episode_action_count": max(action_counts, default=0),
        "passed": (
            bool(episodes)
            and failure_count == 0
            and controller_fault_count == 0
            and trace_failures == 0
            and action_budget_violations == 0
            and reset_budget_violations == 0
        ),
        "reset_budget_violations": reset_budget_violations,
        "trace_event_count": event_count,
        "trace_file_count": trace_file_count,
        "trace_replay_failure_count": trace_failures,
        "traced_episode_count": len(traces),
    }


def _resource_summary(
    *suites: Mapping[str, object], wall_ns: int, cpu_ns: int
) -> dict[str, object]:
    episode_walls = [
        item
        for suite in suites
        for item in _walk_named_values(suite, "wall_ns")
        if isinstance(item, int) and not isinstance(item, bool)
    ]
    peaks = [
        item
        for suite in suites
        for item in _walk_named_values(suite, "process_peak_rss_bytes")
        if isinstance(item, int) and not isinstance(item, bool)
    ]
    peak = max(peaks) if peaks else None
    maximum_episode = max(episode_walls) if episode_walls else None
    return {
        "cpu_ns": cpu_ns,
        "maximum_episode_wall_limit_seconds": EPISODE_WALL_LIMIT_SECONDS,
        "maximum_episode_wall_ns": maximum_episode,
        "maximum_episode_wall_within_limit": (
            maximum_episode is not None
            and maximum_episode <= int(EPISODE_WALL_LIMIT_SECONDS * 1_000_000_000)
        ),
        "median_episode_wall_ns": (
            float(statistics.median(episode_walls)) if episode_walls else None
        ),
        "peak_rss_bytes": peak,
        "peak_rss_limit_bytes": PEAK_RSS_LIMIT_BYTES,
        "peak_rss_within_limit": peak is not None and peak <= PEAK_RSS_LIMIT_BYTES,
        "wall_limit_seconds": WALL_LIMIT_SECONDS,
        "wall_ns": wall_ns,
        "wall_seconds": wall_ns / 1_000_000_000,
        "wall_within_limit": wall_ns <= int(WALL_LIMIT_SECONDS * 1_000_000_000),
    }


def measure_action_equivariance(
    *,
    work_root: Path,
    command: Sequence[str],
) -> dict[str, object]:
    """Execute the exact frozen Stage 05 synthetic measurement matrix."""

    if work_root.exists():
        if not work_root.is_dir():
            raise ValueError(f"work root is not a directory: {work_root}")
        if any(work_root.iterdir()):
            raise ValueError(f"work root already contains data: {work_root}")
    work_root.mkdir(parents=True, exist_ok=True)
    source_identity = _source_identity()
    if source_identity["dirty_worktree"] is not False:
        raise RuntimeError("Stage 05 acceptance requires a clean committed source tree")
    git_commit_value = source_identity["git_commit"]
    if not isinstance(git_commit_value, str) or not git_commit_value:
        raise RuntimeError("Stage 05 acceptance requires an available git commit")

    started_at = _utc_now()
    before_rss = process_memory_sample()
    wall_started_ns = time.perf_counter_ns()
    cpu_started_ns = time.process_time_ns()
    static_scan = build_action_semantics_receipt(ROOT)
    historical = _historical_suite(work_root / "historical", git_commit_value)
    procedural = _procedural_suite(work_root / "procedural", git_commit_value)
    causal = _causal_control_suite()
    checkpoint = _checkpoint_suite(work_root / "checkpoint-resume", git_commit_value)
    holdout = _holdout_integrity()
    registry_bounds = _registry_bounds_summary(historical, procedural, causal, checkpoint)
    aggregate = _aggregate_measurements(historical, procedural, causal, checkpoint)
    cpu_ns = max(0, time.process_time_ns() - cpu_started_ns)
    wall_ns = max(0, time.perf_counter_ns() - wall_started_ns)
    after_rss = process_memory_sample()
    resources = _resource_summary(
        historical,
        procedural,
        checkpoint,
        wall_ns=wall_ns,
        cpu_ns=cpu_ns,
    )
    process_peaks = [
        value
        for value in (
            _rss_value(before_rss, "peak_rss_bytes"),
            _rss_value(after_rss, "peak_rss_bytes"),
            cast(int | None, resources["peak_rss_bytes"]),
        )
        if value is not None
    ]
    resources["peak_rss_bytes"] = max(process_peaks) if process_peaks else None
    resources["peak_rss_within_limit"] = (
        bool(process_peaks) and max(process_peaks) <= PEAK_RSS_LIMIT_BYTES
    )

    historical_pass = historical["passed_cases"] == 2
    procedural_pass = (
        procedural["pair_count"] == 128
        and procedural["passed_pairs"] == 128
        and procedural["post_calibration_inverse_request_equivariance"] == 1.0
    )
    causal_pass = causal["case_count"] == 64 and causal["passed_cases"] == 64
    checkpoint_pass = checkpoint["case_count"] == 16 and checkpoint["passed_cases"] == 16
    static_pass = static_scan["passed"] is True
    integrity_pass = holdout["status"] == "SEALED_UNCONSUMED"
    registry_pass = registry_bounds["passed"] is True
    aggregate_pass = aggregate["passed"] is True
    resource_pass = (
        resources["wall_within_limit"] is True
        and resources["maximum_episode_wall_within_limit"] is True
        and resources["peak_rss_within_limit"] is True
    )
    if not resource_pass:
        status = "FAILED_INFRASTRUCTURE"
    elif not historical_pass or not static_pass:
        status = "FAILED_MECHANISM"
    elif (
        procedural_pass
        and causal_pass
        and checkpoint_pass
        and integrity_pass
        and registry_pass
        and aggregate_pass
    ):
        status = "PASS"
    else:
        status = "PARTIAL"
    report: dict[str, object] = {
        "acceptance": {
            "aggregate_runtime_integrity": aggregate_pass,
            "causal_controls": causal_pass,
            "checkpoint_resume": checkpoint_pass,
            "historical_regressions": historical_pass,
            "holdout_integrity": integrity_pass,
            "procedural_pairs": procedural_pass,
            "registry_bounds": registry_pass,
            "resource_limits": resource_pass,
            "source_clean": True,
            "static_action_semantics": static_pass,
        },
        "aggregate_measurements": aggregate,
        "causal_control_suite": causal,
        "checkpoint_resume_suite": checkpoint,
        "commands": [list(command)],
        "completed_at": _utc_now(),
        "configuration": {
            "action_effect_candidates_per_handle_max": 32,
            "action_effect_registry_max_handles": 7,
            "automatic_checkpointing": {
                "bulk_procedural": False,
                "checkpoint_resume": True,
                "historical_regression": True,
            },
            "calibration_coordinate": {"x": 3, "y": 3},
            "calibration_prefix_excluded_from_inverse_metric_only": True,
            "calibration_prefix_in_action_budgets": True,
            "causal_control_cases": 64,
            "checkpoint_seeds": list(CHECKPOINT_SEEDS),
            "grid_size": GRID_SIZE,
            "historical_seeds": list(HISTORICAL_SEEDS),
            "hosted_inference": False,
            "max_actions": MAX_ACTIONS,
            "max_coordinate_candidates": MAX_COORDINATE_CANDIDATES,
            "max_resets": MAX_RESETS,
            "network_enabled": False,
            "procedural_pairs": 128,
            "public_assets_allowed": False,
            "wall_limit_seconds": WALL_LIMIT_SECONDS,
        },
        "evidence_label": "synthetic",
        "historical_regression_suite": historical,
        "holdout_integrity": holdout,
        "limitations": [
            "Synthetic action equivariance does not establish public or hidden-game generalization.",
            "Calibration is an explicit symmetry breaker and remains charged to all action budgets.",
            "Full-sequence inverse equivalence is not claimed before differing transition evidence.",
            "Whole-process peak RSS can include earlier cases in this single process.",
            "No public game episode, source, asset, adapter, or hosted inference service is used.",
        ],
        "predeclaration": {
            "path": PREDECLARATION.relative_to(ROOT).as_posix(),
            "sha256": sha256_file(PREDECLARATION),
        },
        "procedural_paired_suite": procedural,
        "registry_bounds_measurement": registry_bounds,
        "resource_measurement": resources,
        "runtime_identity": _runtime_identity(),
        "schema": "arc3.build-001.stage-05-action-equivariance.v0.1",
        "source_identity": source_identity,
        "started_at": started_at,
        "static_action_semantics": static_scan,
        "status": status,
        "work_root": str(work_root.resolve()),
    }
    return seal_object(report, hash_field="artifact_core_hash")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--work-root", type=Path, default=DEFAULT_WORK_ROOT)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    command = (
        str(Path(sys.executable).resolve()),
        str(Path(__file__).resolve()),
        "--output",
        str(args.output.resolve()),
        "--work-root",
        str(args.work_root.resolve()),
    )
    report = measure_action_equivariance(work_root=args.work_root, command=command)
    atomic_write_json(args.output, report)
    sys.stdout.write(
        canonical_json_bytes(
            {
                "artifact_core_hash": report["artifact_core_hash"],
                "output": str(args.output.resolve()),
                "schema": report["schema"],
                "status": report["status"],
            }
        ).decode("utf-8")
    )
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
