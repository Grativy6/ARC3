"""Measure the frozen Build 001 Stage 04 palette-equivariance contract.

This harness is intentionally synthetic-only.  It never imports a public-game
adapter or manifest.  Raw observations remain exact while paired comparisons
use the production level-scoped palette-role registry.
"""

from __future__ import annotations

import argparse
import os
import platform
import random
import statistics
import subprocess
import sys
import time
from collections import Counter
from collections.abc import Collection, Mapping, Sequence
from dataclasses import replace
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
from arc3.adapters.synthetic import SYNTHETIC_GAME_ID, SyntheticAdapter
from arc3.config import ARC3Config, BudgetConfig, derive_seed
from arc3.evaluation.artifacts import (
    atomic_write_json,
    canonical_json_bytes,
    seal_object,
    sha256_bytes,
    sha256_file,
)
from arc3.perception import CellChangeKind, PaletteRoleRegistry, measure_delta
from arc3.policy import (
    ARC3Controller,
    ControllerPhase,
    ControllerPreset,
    RunContext,
    preset_features,
)
from arc3.profiling import RobustnessVariant, TransformedSyntheticSession
from arc3.profiling.runtime import process_memory_sample
from arc3.trace import (
    EventJournal,
    ReplayEngine,
)
from arc3.trace import (
    canonical_bytes as trace_canonical_bytes,
)
from arc3.trace import (
    sha256_bytes as trace_sha256_bytes,
)
from arc3.types import (
    ActionName,
    ActionRequest,
    EvaluationSurface,
    GameId,
    GameStateName,
    JSONValue,
)

ROOT = Path(__file__).resolve().parents[1]
PREDECLARATION = ROOT / "docs" / "evidence" / "001-04-palette-equivariance-predeclaration.json"
DEFAULT_OUTPUT = Path("C:/a/arc3-b001/artifacts/stage04/palette-equivariance.json")
DEFAULT_WORK_ROOT = Path("C:/a/arc3-b001/artifacts/stage04/palette-equivariance-work")
ENVIRONMENT_SEEDS = tuple(range(32))
PERMUTATIONS_PER_SEED = 8
CHECKPOINT_SEEDS = tuple(range(16))
CAUSAL_CONTROL_CASES = 64
MAX_ACTIONS = 16
MAX_RESETS = 2
GRID_SIZE = 8
WALL_LIMIT_SECONDS = 600.0
CHECKPOINT_GAME_ID = "synthetic-stage04-checkpoint-walk-v1"


class _Session(Protocol):
    @property
    def observation(self) -> Observation: ...

    def step(
        self,
        action: ActionRequest,
        *,
        reasoning: Mapping[str, JSONValue] | None = None,
    ) -> Observation: ...

    def close(self) -> ScoreSummary: ...


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


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
    for directory in (ROOT / "src" / "arc3", ROOT / "agent"):
        if directory.is_dir():
            candidates.extend(
                path
                for path in directory.rglob("*.py")
                if path.is_file() and "__pycache__" not in path.parts
            )
    candidates.extend(
        path
        for path in (
            Path(__file__).resolve(),
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
    worktree = _git_value("status", "--porcelain=v1")
    identity: dict[str, object] = {
        "branch": _git_value("branch", "--show-current"),
        "dirty_worktree": worktree is None or bool(worktree),
        "dirty_worktree_reason": "git status unavailable" if worktree is None else None,
        "first_party_source_file_count": len(entries),
        "first_party_source_hash": sha256_bytes(canonical_json_bytes(entries)),
        "git_commit": _git_value("rev-parse", "HEAD"),
        "git_tree": _git_value("rev-parse", "HEAD^{tree}"),
        "worktree_status_hash": (
            None if worktree is None else sha256_bytes((worktree + "\n").encode("utf-8"))
        ),
    }
    return seal_object(identity, hash_field="identity_hash")


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


def palette_permutation(seed: int, permutation_index: int) -> tuple[int, ...]:
    """Return the exact frozen full-domain palette bijection."""

    if seed not in ENVIRONMENT_SEEDS:
        raise ValueError("environment seed must be within the frozen 0..31 schedule")
    if not 0 <= permutation_index < PERMUTATIONS_PER_SEED:
        raise ValueError("permutation index must be within the frozen 0..7 schedule")
    values = list(range(16))
    rng = random.Random(derive_seed(seed, f"build-001-stage04-palette-{permutation_index}"))
    rng.shuffle(values)
    if values == list(range(16)):
        values = values[1:] + values[:1]
    return tuple(values)


def palette_suite_schedule() -> tuple[tuple[int, int, tuple[int, ...]], ...]:
    """Materialize all 32 x 8 frozen pair identities."""

    return tuple(
        (seed, index, palette_permutation(seed, index))
        for seed in ENVIRONMENT_SEEDS
        for index in range(PERMUTATIONS_PER_SEED)
    )


def _mapping(permutation: Sequence[int]) -> dict[int, int]:
    values = tuple(permutation)
    if len(values) != 16 or set(values) != set(range(16)):
        raise ValueError("palette transform must be a bijection over all 16 ARC colors")
    return dict(enumerate(values))


def _transform_frame(frame: GridFrame, permutation: Sequence[int]) -> GridFrame:
    mapping = _mapping(permutation)
    return GridFrame.from_rows(tuple(tuple(mapping[cell] for cell in row) for row in frame.cells))


def _transform_observation(
    observation: Observation,
    permutation: Sequence[int],
) -> Observation:
    return Observation(
        game_id=observation.game_id,
        frames=tuple(_transform_frame(frame, permutation) for frame in observation.frames),
        state=observation.state,
        levels_completed=observation.levels_completed,
        win_levels=observation.win_levels,
        available_actions=observation.available_actions,
        full_reset=observation.full_reset,
        returned_action=observation.returned_action,
        upstream_session_id=observation.upstream_session_id,
        upstream_metadata=observation.upstream_metadata,
    )


class PaletteMappedSession:
    """Apply a full palette bijection only at the observation boundary."""

    def __init__(self, session: _Session, permutation: Sequence[int]) -> None:
        self._session = session
        self.permutation = tuple(permutation)
        _mapping(self.permutation)
        self._observation = _transform_observation(session.observation, self.permutation)

    @property
    def observation(self) -> Observation:
        return self._observation

    def step(
        self,
        action: ActionRequest,
        *,
        reasoning: Mapping[str, JSONValue] | None = None,
    ) -> Observation:
        validate_action_request(self._observation, action)
        returned = self._session.step(action, reasoning=reasoning)
        self._observation = _transform_observation(returned, self.permutation)
        return self._observation

    def close(self) -> ScoreSummary:
        return self._session.close()


class CheckpointWalkSession:
    """Eight-by-eight walk whose first consequence is always nonterminal."""

    def __init__(self, *, seed: int, max_steps: int = MAX_ACTIONS) -> None:
        if seed not in CHECKPOINT_SEEDS:
            raise ValueError("checkpoint seed must be within the frozen 0..15 schedule")
        self._seed = seed
        self._max_steps = max_steps
        self._start = (seed % 4, (seed // 4) % 4)
        self._target = (self._start[0] + 3, self._start[1] + 3)
        self._agent = self._start
        self._actions = 0
        self._actions_since_reset = 0
        self._resets = 0
        self._state = GameStateName.NOT_FINISHED
        self._closed = False
        self._observation = self._make_observation(
            full_reset=True,
            returned_action=ActionRequest(ActionName.RESET),
        )

    @property
    def observation(self) -> Observation:
        return self._observation

    def _frame(self) -> GridFrame:
        rows = [[0 for _ in range(GRID_SIZE)] for _ in range(GRID_SIZE)]
        rows[self._target[1]][self._target[0]] = 2
        rows[self._agent[1]][self._agent[0]] = 1
        return GridFrame.from_rows(rows)

    def _make_observation(
        self,
        *,
        full_reset: bool,
        returned_action: ActionRequest,
    ) -> Observation:
        actions = (
            (
                ActionName.ACTION1,
                ActionName.ACTION2,
                ActionName.ACTION3,
                ActionName.ACTION4,
            )
            if self._state is GameStateName.NOT_FINISHED
            else ()
        )
        return Observation(
            game_id=GameId(CHECKPOINT_GAME_ID),
            frames=(self._frame(),),
            state=self._state,
            levels_completed=1 if self._state is GameStateName.WIN else 0,
            win_levels=1,
            available_actions=actions,
            full_reset=full_reset,
            returned_action=returned_action,
            upstream_metadata=(("seed", self._seed), ("step", self._actions)),
        )

    def step(
        self,
        action: ActionRequest,
        *,
        reasoning: Mapping[str, JSONValue] | None = None,
    ) -> Observation:
        del reasoning
        if self._closed:
            raise RuntimeError("checkpoint walk session is closed")
        validate_action_request(self._observation, action)
        if action.name is ActionName.RESET:
            self._agent = self._start
            self._actions_since_reset = 0
            self._resets += 1
            self._state = GameStateName.NOT_FINISHED
            self._observation = self._make_observation(
                full_reset=True,
                returned_action=action,
            )
            return self._observation
        x, y = self._agent
        dx, dy = {
            ActionName.ACTION1: (0, -1),
            ActionName.ACTION2: (0, 1),
            ActionName.ACTION3: (-1, 0),
            ActionName.ACTION4: (1, 0),
        }[action.name]
        self._agent = (
            min(GRID_SIZE - 1, max(0, x + dx)),
            min(GRID_SIZE - 1, max(0, y + dy)),
        )
        self._actions += 1
        self._actions_since_reset += 1
        if self._agent == self._target:
            self._state = GameStateName.WIN
        elif self._actions_since_reset >= self._max_steps:
            self._state = GameStateName.GAME_OVER
        self._observation = self._make_observation(
            full_reset=False,
            returned_action=action,
        )
        return self._observation

    def close(self) -> ScoreSummary:
        self._closed = True
        completed = self._state is GameStateName.WIN
        score = 1.0 if completed else 0.0
        run = ScoreRunSummary(
            game_id=GameId(CHECKPOINT_GAME_ID),
            score=score,
            levels_completed=1 if completed else 0,
            actions=self._actions,
            resets=self._resets,
            state=self._state,
            completed=completed,
            level_scores=(score,),
            level_actions=(self._actions,),
        )
        return ScoreSummary(
            surface=EvaluationSurface.SYNTHETIC,
            verified=True,
            scorer="arc3.build-001.stage04.checkpoint-walk.v0.1",
            score=score,
            runs=(run,),
        )


def _background_colors(frame: GridFrame) -> tuple[int, ...]:
    counts = Counter(cell for row in frame.cells for cell in row)
    maximum = max(counts.values())
    return tuple(color for color, count in counts.items() if count == maximum)


def _registry_projection(
    registry: PaletteRoleRegistry,
    observation: Observation,
) -> object:
    frame = observation.frames[-1]
    registry.observe(frame, background_colors=_background_colors(frame))
    return registry.canonical_projection()


def _action_payload(action: ActionRequest) -> dict[str, JSONValue]:
    coordinate = action.coordinate
    return {
        "name": action.name.value,
        "coordinate": (None if coordinate is None else {"x": coordinate.x, "y": coordinate.y}),
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
                "build-001-stage04-default-checkpoint"
                if automatic_checkpoints
                else "build-001-stage04-bulk-no-auto-checkpoint"
            ),
            budgets=BudgetConfig(
                max_actions=MAX_ACTIONS,
                max_resets=MAX_RESETS,
                wall_clock_seconds=60.0,
                max_search_nodes=2_048,
            ),
        ),
        git_commit=git_commit,
        source_kind="build-001-stage04-palette-equivariance",
        source_version="0.1",
    )


def _rss_value(sample: Mapping[str, JSONValue], key: str) -> int | None:
    value = sample.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _rss_report(
    before: Mapping[str, JSONValue],
    after: Mapping[str, JSONValue],
) -> dict[str, object]:
    before_current = _rss_value(before, "current_rss_bytes")
    after_current = _rss_value(after, "current_rss_bytes")
    peaks = [
        item
        for item in (
            _rss_value(before, "peak_rss_bytes"),
            _rss_value(after, "peak_rss_bytes"),
        )
        if item is not None
    ]
    return {
        "before": dict(before),
        "after": dict(after),
        "current_delta_bytes": (
            None
            if before_current is None or after_current is None
            else after_current - before_current
        ),
        "process_peak_rss_bytes": max(peaks) if peaks else None,
        "scope": "whole-process; peak may include earlier cases",
    }


def _verify_trace(root: Path, run_id: str, raw_frame_hashes: Sequence[str]) -> dict[str, object]:
    journal = EventJournal(root, run_id=run_id)
    engine = ReplayEngine(journal)
    events = engine.verify_integrity()
    replayed = engine.replay_frames()
    replayed_hashes = [str(item.frame_hash) for item in replayed]
    trace_files = [path for path in sorted(root.rglob("*")) if path.is_file()]
    trace_inventory = [
        {"path": path.relative_to(root).as_posix(), "sha256": sha256_file(path)}
        for path in trace_files
    ]
    result = {
        "event_count": len(events),
        "frame_count": len(replayed),
        "frame_hashes_match_raw_receipts": replayed_hashes == list(raw_frame_hashes),
        "manifest_hash": journal.manifest.manifest_hash,
        "manifest_file_sha256": (
            sha256_file(journal.manifest_path) if journal.manifest_path.is_file() else None
        ),
        "replay_verified": True,
        "tail_event_hash": events[-1].event_hash if events else None,
        "trace_file_count": len(trace_inventory),
        "trace_inventory_hash": sha256_bytes(canonical_json_bytes(trace_inventory)),
    }
    journal.close()
    return result


def _controller_projection(controller: ARC3Controller) -> object:
    return controller.palette_role_projection


def _trace_frame_hash(frame: GridFrame) -> str:
    """Reproduce the trace blob contract's canonical-JSON frame identity."""

    return trace_sha256_bytes(trace_canonical_bytes([list(row) for row in frame.cells]))


def _run_episode(
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
    features = replace(
        preset_features(ControllerPreset.FULL),
        use_memory=automatic_checkpoints,
    )
    controller = ARC3Controller(ControllerPreset.FULL, features=features)
    context = _context(
        root,
        run_id=run_id,
        game_id=str(session.observation.game_id),
        seed=seed,
        git_commit=git_commit,
        automatic_checkpoints=automatic_checkpoints,
    )
    registry = PaletteRoleRegistry(level_index=0, max_entries=16)
    observations = [session.observation]
    projections = [_registry_projection(registry, session.observation)]
    controller.reset(context)
    controller.observe(session.observation)
    actions: list[dict[str, JSONValue]] = []
    while len(actions) < MAX_ACTIONS and controller.phase not in {
        ControllerPhase.COMPLETE,
        ControllerPhase.GAME_OVER,
    }:
        decision = controller.choose_action()
        actions.append(_action_payload(decision.action))
        consequence = session.step(decision.action)
        observations.append(consequence)
        projections.append(_registry_projection(registry, consequence))
        controller.apply_consequence(consequence)
    snapshot = controller.snapshot
    controller_projection = _controller_projection(controller)
    terminal_state = session.observation.state
    controller.close()
    scorecard = session.close()
    cpu_ns = max(0, time.process_time_ns() - cpu_started_ns)
    wall_ns = max(0, time.perf_counter_ns() - wall_started_ns)
    after_rss = process_memory_sample()
    raw_hashes = [str(item.frames[-1].digest) for item in observations]
    trace_frame_hashes = [_trace_frame_hash(item.frames[-1]) for item in observations]
    trace = _verify_trace(context.trace_root, run_id, trace_frame_hashes)
    registry_state = registry.to_dict()
    return {
        "action_count": len(actions),
        "action_request_sequence": actions,
        "action_request_sequence_hash": sha256_bytes(canonical_json_bytes(actions)),
        "automatic_checkpoints": automatic_checkpoints,
        "canonical_palette_role_projections": projections,
        "canonical_palette_role_projection_hash": sha256_bytes(canonical_json_bytes(projections)),
        "completed": terminal_state is GameStateName.WIN,
        "controller_fault_count": snapshot.fault_count,
        "controller_palette_role_projection": controller_projection,
        "controller_palette_role_projection_hash": sha256_bytes(
            canonical_json_bytes(controller_projection)
        ),
        "cpu_ns": cpu_ns,
        "final_raw_frame_hash": raw_hashes[-1],
        "initial_raw_frame_hash": raw_hashes[0],
        "raw_frame_hashes": raw_hashes,
        "raw_trace_frame_hashes": trace_frame_hashes,
        "raw_palette_receipts": [list(item.frames[-1].palette) for item in observations],
        "registry_serialized_state": registry_state,
        "resets": scorecard.total_resets,
        "rss": _rss_report(before_rss, after_rss),
        "score": scorecard.score,
        "terminal_phase": terminal_state.value,
        "trace": trace,
        "wall_ns": wall_ns,
    }


def _pair_parity(base: Mapping[str, object], transformed: Mapping[str, object]) -> dict[str, bool]:
    return {
        "canonical_palette_role_projection": (
            base["canonical_palette_role_projections"]
            == transformed["canonical_palette_role_projections"]
            and base["controller_palette_role_projection"]
            == transformed["controller_palette_role_projection"]
        ),
        "completion": base["completed"] == transformed["completed"],
        "exact_action_request_sequence": (
            base["action_request_sequence"] == transformed["action_request_sequence"]
        ),
        "score": base["score"] == transformed["score"],
        "terminal_phase": base["terminal_phase"] == transformed["terminal_phase"],
        "traces": (
            cast(Mapping[str, object], base["trace"])["replay_verified"] is True
            and cast(Mapping[str, object], base["trace"])["frame_hashes_match_raw_receipts"] is True
            and cast(Mapping[str, object], transformed["trace"])["replay_verified"] is True
            and cast(Mapping[str, object], transformed["trace"])["frame_hashes_match_raw_receipts"]
            is True
        ),
    }


def _historical_suite(work_root: Path, git_commit: str) -> dict[str, object]:
    cases: list[dict[str, object]] = []
    for seed in (7, 11):
        base = _run_episode(
            SyntheticAdapter(seed=seed, size=GRID_SIZE, max_steps=MAX_ACTIONS).open(
                SYNTHETIC_GAME_ID,
                seed=seed,
            ),
            root=work_root / f"seed-{seed}" / "base",
            run_id=f"stage04-historical-{seed}-base",
            seed=seed,
            git_commit=git_commit,
            automatic_checkpoints=True,
        )
        palette_session = cast(
            _Session,
            TransformedSyntheticSession(
                seed=seed,
                size=GRID_SIZE,
                max_steps=MAX_ACTIONS,
                variant=RobustnessVariant.PALETTE,
            ),
        )
        transformed = _run_episode(
            palette_session,
            root=work_root / f"seed-{seed}" / "palette",
            run_id=f"stage04-historical-{seed}-palette",
            seed=seed,
            git_commit=git_commit,
            automatic_checkpoints=True,
        )
        parity = _pair_parity(base, transformed)
        cases.append(
            {
                "base": base,
                "historical_palette_mapping": {"0": 0, "1": 7, "2": 12},
                "palette": transformed,
                "parity": parity,
                "passed": (
                    all(parity.values())
                    and base["completed"] is True
                    and transformed["completed"] is True
                ),
                "seed": seed,
            }
        )
    return {
        "case_count": len(cases),
        "cases": cases,
        "passed_cases": sum(case["passed"] is True for case in cases),
    }


def _procedural_suite(work_root: Path, git_commit: str) -> dict[str, object]:
    base_episodes: dict[str, dict[str, object]] = {}
    pairs: list[dict[str, object]] = []
    for seed in ENVIRONMENT_SEEDS:
        base = _run_episode(
            SyntheticAdapter(seed=seed, size=GRID_SIZE, max_steps=MAX_ACTIONS).open(
                SYNTHETIC_GAME_ID,
                seed=seed,
            ),
            root=work_root / "base" / f"seed-{seed}",
            run_id=f"stage04-procedural-{seed}-base",
            seed=seed,
            git_commit=git_commit,
            automatic_checkpoints=False,
        )
        base_episodes[str(seed)] = base
        for permutation_index in range(PERMUTATIONS_PER_SEED):
            permutation = palette_permutation(seed, permutation_index)
            transformed = _run_episode(
                PaletteMappedSession(
                    SyntheticAdapter(seed=seed, size=GRID_SIZE, max_steps=MAX_ACTIONS).open(
                        SYNTHETIC_GAME_ID,
                        seed=seed,
                    ),
                    permutation,
                ),
                root=(work_root / "permuted" / f"seed-{seed}" / f"permutation-{permutation_index}"),
                run_id=f"stage04-procedural-{seed}-permutation-{permutation_index}",
                seed=seed,
                git_commit=git_commit,
                automatic_checkpoints=False,
            )
            parity = _pair_parity(base, transformed)
            raw_difference = base["initial_raw_frame_hash"] != transformed["initial_raw_frame_hash"]
            pairs.append(
                {
                    "base_episode_ref": f"seed-{seed}",
                    "nonidentity_raw_initial_frame_hash_difference": raw_difference,
                    "pair_passed": all(parity.values()) and raw_difference,
                    "palette_mapping": list(permutation),
                    "palette_mapping_hash": sha256_bytes(canonical_json_bytes(list(permutation))),
                    "parity": parity,
                    "permutation_index": permutation_index,
                    "seed": seed,
                    "transformed": transformed,
                }
            )
    predicate_counts = {
        key: sum(cast(Mapping[str, bool], pair["parity"])[key] for pair in pairs)
        for key in (
            "canonical_palette_role_projection",
            "completion",
            "exact_action_request_sequence",
            "score",
            "terminal_phase",
            "traces",
        )
    }
    predicate_counts["nonidentity_raw_initial_frame_hash_difference"] = sum(
        pair["nonidentity_raw_initial_frame_hash_difference"] is True for pair in pairs
    )
    return {
        "base_episode_count": len(base_episodes),
        "base_episodes": base_episodes,
        "pair_count": len(pairs),
        "pairs": pairs,
        "passed_pairs": sum(pair["pair_passed"] is True for pair in pairs),
        "predicate_pass_counts": predicate_counts,
    }


def _submitted_count(controller: ARC3Controller) -> int:
    return sum(
        event.event_type == "action.submitted" for event in controller.journal.verify_manifest()
    )


def _checkpoint_resumed_episode(
    *,
    seed: int,
    permutation: Sequence[int],
    root: Path,
    git_commit: str,
) -> dict[str, object]:
    session = PaletteMappedSession(CheckpointWalkSession(seed=seed), permutation)
    run_id = f"stage04-checkpoint-{seed}-resumed"
    context = _context(
        root,
        run_id=run_id,
        game_id=CHECKPOINT_GAME_ID,
        seed=seed,
        git_commit=git_commit,
        automatic_checkpoints=True,
    )
    controller = ARC3Controller(ControllerPreset.FULL)
    registry = PaletteRoleRegistry(level_index=0, max_entries=16)
    observations = [session.observation]
    projections = [_registry_projection(registry, session.observation)]
    actions: list[dict[str, JSONValue]] = []
    before_rss = process_memory_sample()
    wall_started_ns = time.perf_counter_ns()
    cpu_started_ns = time.process_time_ns()
    controller.reset(context)
    controller.observe(session.observation)
    first = controller.choose_action()
    actions.append(_action_payload(first.action))
    first_consequence = session.step(first.action)
    if first_consequence.state is not GameStateName.NOT_FINISHED:
        raise RuntimeError("checkpoint fixture reached terminal state before frozen boundary")
    observations.append(first_consequence)
    projections.append(_registry_projection(registry, first_consequence))
    controller.apply_consequence(first_consequence)
    projection_before = _controller_projection(controller)
    checkpoint = controller.checkpoint()
    derived_state = checkpoint.envelope.state.get("derived_controller_state")
    perception_state = (
        derived_state.get("perception_state") if isinstance(derived_state, dict) else None
    )
    registry_serialized = (
        isinstance(perception_state, dict) and "palette_role_registry" in perception_state
    )
    submitted_before = _submitted_count(controller)
    controller.journal.close()

    restored = ARC3Controller.restore(
        context,
        preset=ControllerPreset.FULL,
        checkpoint_path=checkpoint.path,
    )
    projection_after = _controller_projection(restored)
    submitted_after_restore = _submitted_count(restored)
    next_action = restored.choose_action()
    actions.append(_action_payload(next_action.action))
    submitted_after_next = _submitted_count(restored)
    consequence = session.step(next_action.action)
    observations.append(consequence)
    projections.append(_registry_projection(registry, consequence))
    restored.apply_consequence(consequence)
    while len(actions) < MAX_ACTIONS and restored.phase not in {
        ControllerPhase.COMPLETE,
        ControllerPhase.GAME_OVER,
    }:
        decision = restored.choose_action()
        actions.append(_action_payload(decision.action))
        consequence = session.step(decision.action)
        observations.append(consequence)
        projections.append(_registry_projection(registry, consequence))
        restored.apply_consequence(consequence)
    final_projection = _controller_projection(restored)
    snapshot = restored.snapshot
    terminal_state = session.observation.state
    restored.close()
    scorecard = session.close()
    cpu_ns = max(0, time.process_time_ns() - cpu_started_ns)
    wall_ns = max(0, time.perf_counter_ns() - wall_started_ns)
    after_rss = process_memory_sample()
    raw_hashes = [str(item.frames[-1].digest) for item in observations]
    trace_frame_hashes = [_trace_frame_hash(item.frames[-1]) for item in observations]
    trace = _verify_trace(context.trace_root, run_id, trace_frame_hashes)
    return {
        "action_count": len(actions),
        "action_request_sequence": actions,
        "canonical_palette_role_projections": projections,
        "checkpoint_file_sha256": sha256_file(checkpoint.path),
        "checkpoint_hash": checkpoint.envelope.checkpoint_hash,
        "checkpoint_palette_registry_serialized": registry_serialized,
        "completed": terminal_state is GameStateName.WIN,
        "controller_fault_count": snapshot.fault_count,
        "cpu_ns": cpu_ns,
        "final_controller_palette_role_projection": final_projection,
        "no_resubmission": (
            submitted_before == 1
            and submitted_after_restore == submitted_before
            and submitted_after_next == submitted_before + 1
        ),
        "projection_stable_across_restore": projection_before == projection_after,
        "raw_frame_hashes": raw_hashes,
        "raw_trace_frame_hashes": trace_frame_hashes,
        "resets": scorecard.total_resets,
        "rss": _rss_report(before_rss, after_rss),
        "score": scorecard.score,
        "terminal_phase": terminal_state.value,
        "trace": trace,
        "wall_ns": wall_ns,
    }


def _checkpoint_suite(work_root: Path, git_commit: str) -> dict[str, object]:
    cases: list[dict[str, object]] = []
    for seed in CHECKPOINT_SEEDS:
        permutation = palette_permutation(seed, 0)
        uninterrupted = _run_episode(
            PaletteMappedSession(CheckpointWalkSession(seed=seed), permutation),
            root=work_root / f"seed-{seed}" / "uninterrupted",
            run_id=f"stage04-checkpoint-{seed}-uninterrupted",
            seed=seed,
            git_commit=git_commit,
            automatic_checkpoints=True,
        )
        resumed = _checkpoint_resumed_episode(
            seed=seed,
            permutation=permutation,
            root=work_root / f"seed-{seed}" / "resumed",
            git_commit=git_commit,
        )
        parity = {
            "action_request_sequence": (
                uninterrupted["action_request_sequence"] == resumed["action_request_sequence"]
            ),
            "canonical_projection": (
                uninterrupted["canonical_palette_role_projections"]
                == resumed["canonical_palette_role_projections"]
                and uninterrupted["controller_palette_role_projection"]
                == resumed["final_controller_palette_role_projection"]
            ),
            "completion": uninterrupted["completed"] == resumed["completed"],
            "score": uninterrupted["score"] == resumed["score"],
            "terminal_phase": (uninterrupted["terminal_phase"] == resumed["terminal_phase"]),
            "trace": (
                cast(Mapping[str, object], uninterrupted["trace"])["replay_verified"] is True
                and cast(Mapping[str, object], resumed["trace"])["replay_verified"] is True
            ),
        }
        passed = (
            all(parity.values())
            and resumed["checkpoint_palette_registry_serialized"] is True
            and resumed["projection_stable_across_restore"] is True
            and resumed["no_resubmission"] is True
        )
        cases.append(
            {
                "pair_passed": passed,
                "palette_mapping": list(permutation),
                "parity": parity,
                "resumed": resumed,
                "seed": seed,
                "uninterrupted": uninterrupted,
            }
        )
    return {
        "case_count": len(cases),
        "cases": cases,
        "passed_cases": sum(case["pair_passed"] is True for case in cases),
    }


def _structural_delta_projection(
    before: GridFrame,
    after: GridFrame,
    *,
    backgrounds: Collection[int],
) -> list[dict[str, JSONValue]]:
    delta = measure_delta(before, after, background_colors=frozenset(backgrounds))
    return [{"x": item.x, "y": item.y, "kind": item.kind.value} for item in delta.cell_changes]


def _projection_sequence(frames: Sequence[GridFrame]) -> list[object]:
    registry = PaletteRoleRegistry(level_index=0, max_entries=16)
    result: list[object] = []
    for frame in frames:
        registry.observe(frame, background_colors=_background_colors(frame))
        result.append(registry.canonical_projection())
    return result


def _causal_control_case(seed: int) -> dict[str, object]:
    permutation = palette_permutation(seed % 32, seed % PERMUTATIONS_PER_SEED)
    moved_colors = [color for color in range(16) if permutation[color] != color]
    if not moved_colors:  # palette_permutation is nonidentity; defensive invariant
        raise RuntimeError("causal-control palette unexpectedly has no moved color")
    background = moved_colors[0]
    other_colors = [color for color in range(16) if color != background]
    mover = other_colors[seed % len(other_colors)]
    marker = other_colors[(seed * 5 + 1) % len(other_colors)]
    if marker == mover:
        marker = other_colors[(other_colors.index(marker) + 1) % len(other_colors)]
    x = 1 + seed % 3
    y = 1 + (seed // 3) % 3
    before_rows = [[background for _ in range(6)] for _ in range(6)]
    after_rows = [[background for _ in range(6)] for _ in range(6)]
    before_rows[y][x] = mover
    after_rows[y][x + 1] = mover
    before_rows[4][4] = marker
    after_rows[4][4] = marker
    before = GridFrame.from_rows(before_rows)
    after = GridFrame.from_rows(after_rows)
    joint_before = _transform_frame(before, permutation)
    joint_after = _transform_frame(after, permutation)
    one_sided_after = joint_after
    base_projection = _projection_sequence((before, after))
    joint_projection = _projection_sequence((joint_before, joint_after))
    base_delta = _structural_delta_projection(
        before,
        after,
        backgrounds=(background,),
    )
    joint_delta = _structural_delta_projection(
        joint_before,
        joint_after,
        backgrounds=(permutation[background],),
    )
    one_sided_delta = measure_delta(
        before,
        one_sided_after,
        background_colors=frozenset({background, permutation[background]}),
    )
    recolor_count = len(one_sided_delta.changes_of_kind(CellChangeKind.RECOLOR))
    joint_equivalent = base_projection == joint_projection and base_delta == joint_delta
    one_sided_distinguishable = (
        before.digest != one_sided_after.digest
        and one_sided_delta.changed_cell_count > 0
        and recolor_count > 0
    )
    return {
        "base_before_hash": str(before.digest),
        "base_after_hash": str(after.digest),
        "base_canonical_projection": base_projection,
        "base_structural_delta": base_delta,
        "joint_before_hash": str(joint_before.digest),
        "joint_after_hash": str(joint_after.digest),
        "joint_canonical_projection": joint_projection,
        "joint_equivalent": joint_equivalent,
        "joint_structural_delta": joint_delta,
        "one_sided_after_hash": str(one_sided_after.digest),
        "one_sided_changed_cell_count": one_sided_delta.changed_cell_count,
        "one_sided_distinguishable": one_sided_distinguishable,
        "one_sided_recolor_count": recolor_count,
        "palette_mapping": list(permutation),
        "seed": seed,
    }


def _causal_control_suite() -> dict[str, object]:
    cases = [_causal_control_case(seed) for seed in range(CAUSAL_CONTROL_CASES)]
    return {
        "case_count": len(cases),
        "cases": cases,
        "joint_equivalent_cases": sum(case["joint_equivalent"] is True for case in cases),
        "one_sided_distinguishable_cases": sum(
            case["one_sided_distinguishable"] is True for case in cases
        ),
    }


def _median_episode_wall_ns(suite: Mapping[str, object]) -> float | None:
    base = cast(Mapping[str, Mapping[str, object]], suite["base_episodes"])
    pairs = cast(Sequence[Mapping[str, object]], suite["pairs"])
    values = [cast(int, episode["wall_ns"]) for episode in base.values()]
    values.extend(
        cast(int, cast(Mapping[str, object], pair["transformed"])["wall_ns"]) for pair in pairs
    )
    return float(statistics.median(values)) if values else None


def measure_palette_equivariance(
    *,
    work_root: Path,
    command: Sequence[str],
) -> dict[str, object]:
    """Execute the exact frozen Stage 04 synthetic measurement matrix."""

    if work_root.exists():
        if not work_root.is_dir():
            raise ValueError(f"work root is not a directory: {work_root}")
        if any(work_root.iterdir()):
            raise ValueError(f"work root already contains data: {work_root}")
    work_root.mkdir(parents=True, exist_ok=True)
    source_identity = _source_identity()
    if source_identity["dirty_worktree"] is not False:
        raise RuntimeError("Stage 04 acceptance requires a clean committed source tree")
    git_commit_value = source_identity["git_commit"]
    if not isinstance(git_commit_value, str) or not git_commit_value:
        raise RuntimeError("Stage 04 acceptance requires an available git commit")

    started_at = _utc_now()
    wall_started_ns = time.perf_counter_ns()
    cpu_started_ns = time.process_time_ns()
    historical = _historical_suite(work_root / "historical", git_commit_value)
    procedural = _procedural_suite(work_root / "procedural", git_commit_value)
    checkpoint = _checkpoint_suite(work_root / "checkpoint-resume", git_commit_value)
    causal = _causal_control_suite()
    cpu_ns = max(0, time.process_time_ns() - cpu_started_ns)
    wall_ns = max(0, time.perf_counter_ns() - wall_started_ns)

    historical_pass = historical["passed_cases"] == 2
    procedural_pass = procedural["passed_pairs"] == 256
    checkpoint_pass = checkpoint["passed_cases"] == 16
    causal_case_count = cast(int, causal["case_count"])
    causal_pass = (
        causal_case_count >= 64
        and causal["joint_equivalent_cases"] == causal_case_count
        and causal["one_sided_distinguishable_cases"] == causal_case_count
    )
    within_resource_limit = wall_ns <= int(WALL_LIMIT_SECONDS * 1_000_000_000)
    status = (
        "PASS"
        if historical_pass
        and procedural_pass
        and checkpoint_pass
        and causal_pass
        and within_resource_limit
        else "FAILED_INFRASTRUCTURE"
        if not within_resource_limit
        else "FAILED_MECHANISM"
    )
    report: dict[str, object] = {
        "acceptance": {
            "causal_controls": causal_pass,
            "checkpoint_resume": checkpoint_pass,
            "historical_regressions": historical_pass,
            "procedural_pairs": procedural_pass,
            "registry_max_entries": 16,
            "source_clean": True,
            "within_600_second_wall_limit": within_resource_limit,
        },
        "causal_controls": causal,
        "checkpoint_resume_suite": checkpoint,
        "commands": [list(command)],
        "completed_at": _utc_now(),
        "configuration": {
            "automatic_checkpointing": {
                "bulk_procedural": False,
                "checkpoint_resume": True,
                "historical_regression": True,
            },
            "checkpoint_seeds": list(CHECKPOINT_SEEDS),
            "color_causal_control_cases": CAUSAL_CONTROL_CASES,
            "environment_seeds": list(ENVIRONMENT_SEEDS),
            "grid_size": GRID_SIZE,
            "hosted_inference": False,
            "max_actions": MAX_ACTIONS,
            "max_resets": MAX_RESETS,
            "network_enabled": False,
            "palette_domain": list(range(16)),
            "permutations_per_seed": PERMUTATIONS_PER_SEED,
            "preset": ControllerPreset.FULL.value,
            "public_assets_allowed": False,
            "wall_limit_seconds": WALL_LIMIT_SECONDS,
        },
        "evidence_label": "synthetic",
        "historical_regression": historical,
        "limitations": [
            "Synthetic palette equivariance does not establish public or hidden-game generalization.",
            "The bulk matrix reuses each seed's verified base episode across eight paired bijections.",
            "Whole-process peak RSS can include earlier cases in this single measurement process.",
            "One-sided controls preserve raw RECOLOR evidence; they do not assign semantic meaning to a color number.",
            "No public-game manifest, asset, adapter, source, or episode is accessed.",
        ],
        "predeclaration": {
            "path": PREDECLARATION.relative_to(ROOT).as_posix(),
            "sha256": sha256_file(PREDECLARATION),
        },
        "procedural_paired_suite": procedural,
        "resource_measurement": {
            "cpu_ns": cpu_ns,
            "median_bulk_episode_wall_ns": _median_episode_wall_ns(procedural),
            "wall_ns": wall_ns,
            "wall_seconds": wall_ns / 1_000_000_000,
        },
        "runtime_identity": _runtime_identity(),
        "schema": "arc3.build-001.stage-04-palette-equivariance.v0.1",
        "source_identity": source_identity,
        "started_at": started_at,
        "status": status,
        "work_root": str(work_root.resolve()),
    }
    return seal_object(report, hash_field="artifact_core_hash")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--work-root", type=Path, default=DEFAULT_WORK_ROOT)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    command = (
        str(Path(sys.executable).resolve()),
        str(Path(__file__).resolve()),
        "--output",
        str(args.output.resolve()),
        "--work-root",
        str(args.work_root.resolve()),
    )
    report = measure_palette_equivariance(work_root=args.work_root, command=command)
    atomic_write_json(args.output, report)
    receipt = {
        "artifact_core_hash": report["artifact_core_hash"],
        "output": str(args.output.resolve()),
        "schema": report["schema"],
        "status": report["status"],
    }
    sys.stdout.write(canonical_json_bytes(receipt).decode("utf-8"))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
