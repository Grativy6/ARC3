"""Execute the one authorized Build 002 local-public holdout run.

This command never discovers or downloads assets.  A run plan names every
already-present input, gate receipt, and frozen artifact.  ``prepare`` creates
the two deterministic inputs which must be bound by those gate receipts: the
static asset inventory and a scorecard-collecting subclass of the production
agent.  ``run`` recreates those bytes, freezes the complete preflight, arms the
durable pre-``make`` seal, launches the pinned official framework exactly once,
and independently validates the terminal result.

The collected scorecard is deliberately a strict whitelist.  Credentials,
card identities, opaque values, source URLs, tags, and raw observations are
never persisted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, cast

from arc3.competition_runtime import FROZEN_COMPETITION_RUNTIME
from arc3.errors import EvaluationError
from arc3.evaluation.artifacts import canonical_json_bytes, seal_object, sha256_file
from arc3.evaluation.build002_holdout import (
    BUILD_002_ATTEMPT_ID,
    CANONICAL_STATE_RELATIVE,
    COMPETITION_LAUNCH_ARTIFACT_SCHEMA,
    EXECUTION_PROFILE_SCHEMA,
    FAILURE_RECEIPTS_SCHEMA,
    LOCAL_SCORECARD_SCHEMA,
    PER_GAME_MEMORY_MEASUREMENT,
    RAW_RUNTIME_SCORECARD_SCHEMA,
    TOURNAMENT_MEMORY_MEASUREMENT,
    ArtifactBinding,
    FailureClassification,
    GameMeasurement,
    LevelMeasurement,
    OneShotHoldoutSeal,
    ReceiptBinding,
    create_frozen_preflight,
    create_runtime_evidence_manifest,
    create_static_asset_inventory,
    launch_frozen_framework_once,
    pinned_toolkit_scorer_identity,
    recompute_pinned_toolkit_game_score,
    validate_consumed_failure,
    validate_terminal_result,
)
from arc3.packaging.models import ExternalSurfaceUnavailableError
from arc3.packaging.submission import validate_submission_parquet

RUN_PLAN_SCHEMA = "arc3.build-002.holdout-run-plan.v0.1"
RAW_SCORECARD_SCHEMA = RAW_RUNTIME_SCORECARD_SCHEMA
PREFLIGHT_STOP_SCHEMA = "arc3.build-002.pre-consumption-stop.v0.1"

GATE_ROLES = frozenset(
    {
        "competition-lifecycle",
        "dependency-and-config-identity",
        "deterministic-startup-and-replay",
        "frozen-source-config-artifacts",
        "notebook-build-and-offline-entry-point",
        "offline-cold-start",
        "official-source-identity",
        "package-and-license-inventory",
        "secret-and-integrity-scan",
        "submission-parquet-structure",
    }
)
ARTIFACT_ROLES = frozenset(
    {
        "agent-wrapper",
        "competition-runtime-config",
        "dependency-lock",
        "holdout-asset-inventory",
        "kaggle-notebook",
        "offline-package-candidate",
        "source-preview-contamination-receipt",
        "submission-parquet",
        "third-party-notices",
        "upstream-lock",
    }
)
_ALLOWED_GATEWAY_HOSTS = frozenset({"127.0.0.1", "::1", "gateway", "localhost"})
_RESOURCE_REASONS = frozenset(
    {
        "game-action-limit",
        "game-reset-limit",
        "tournament-action-limit",
        "game-time-limit",
        "tournament-playable-time-limit",
    }
)


class _LaunchReceipt(Protocol):
    def to_dict(self) -> dict[str, Any]: ...


class _Launch(Protocol):
    def __call__(
        self,
        seal: OneShotHoldoutSeal,
        framework_root: Path,
        agent_path: Path,
        *,
        gateway_host: str,
        gateway_port: int,
        working_root: Path,
        allow_test_fixture: bool,
        notebook_started_at_seconds: float,
    ) -> _LaunchReceipt: ...


@dataclass(frozen=True, slots=True)
class RunPlan:
    source_path: Path
    seed: int
    manifest: Path
    assets: dict[str, Path]
    gates: dict[str, Path]
    artifacts: dict[str, Path]
    framework_root: Path
    production_agent: Path
    gateway_host: str
    gateway_port: int
    submission_output: Path


@dataclass(frozen=True, slots=True)
class RunOutcome:
    status: str
    receipt: dict[str, Any]
    exit_code: int


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _object_field(value: object, name: str, default: object = None) -> object:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _canonical_enum(value: object) -> str | None:
    if value is None:
        return None
    name = getattr(value, "name", None)
    if isinstance(name, str):
        return name
    raw = getattr(value, "value", value)
    return str(raw)


def _required_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise EvaluationError(f"{field} must be a canonical non-empty string")
    return value


def _integer(value: object, field: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise EvaluationError(f"{field} must be an integer >= {minimum}")
    return value


def _number(value: object, field: str, *, maximum: float | None = None) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or float(value) < 0.0
        or (maximum is not None and float(value) > maximum)
    ):
        raise EvaluationError(f"{field} is outside its finite non-negative range")
    return float(value)


def _sequence(value: object, field: str) -> Sequence[object]:
    if not isinstance(value, (list, tuple)):
        raise EvaluationError(f"{field} must be a sequence")
    return value


def collect_scorecard_payload(scorecard: object, expected_games: Sequence[str]) -> dict[str, Any]:
    """Return the credential-free public scorer projection used by the runner."""

    expected = tuple(expected_games)
    raw_environments = _sequence(_object_field(scorecard, "environments"), "environments")
    rows: list[dict[str, Any]] = []
    for environment in raw_environments:
        game_id = _required_string(_object_field(environment, "id"), "environment.id")
        runs = _sequence(_object_field(environment, "runs"), f"{game_id}.runs")
        if len(runs) != 1:
            raise EvaluationError(f"{game_id} must have exactly one official scorecard run")
        run = runs[0]
        run_id = _object_field(run, "id")
        if run_id is not None and run_id != game_id:
            raise EvaluationError(f"{game_id} scorecard run identity changed")
        score = _number(_object_field(run, "score"), f"{game_id}.score", maximum=100.0)
        levels_completed = _integer(
            _object_field(run, "levels_completed"), f"{game_id}.levels_completed"
        )
        actions = _integer(_object_field(run, "actions"), f"{game_id}.actions")
        resets = _integer(_object_field(run, "resets", 0) or 0, f"{game_id}.resets")
        if resets > FROZEN_COMPETITION_RUNTIME.max_resets:
            raise EvaluationError(f"{game_id}.resets exceeds the frozen competition budget")
        level_scores = _sequence(_object_field(run, "level_scores"), f"{game_id}.level_scores")
        level_actions = _sequence(_object_field(run, "level_actions"), f"{game_id}.level_actions")
        level_baselines = _sequence(
            _object_field(run, "level_baseline_actions"),
            f"{game_id}.level_baseline_actions",
        )
        if not level_scores or not (
            len(level_scores) == len(level_actions) == len(level_baselines)
        ):
            raise EvaluationError(f"{game_id} scorecard level arrays are empty or misaligned")
        if levels_completed > len(level_scores):
            raise EvaluationError(f"{game_id} completed-level count exceeds its level rows")
        levels: list[dict[str, Any]] = []
        for index, (raw_score, raw_actions, raw_baseline) in enumerate(
            zip(level_scores, level_actions, level_baselines, strict=True), start=1
        ):
            baseline = _integer(raw_baseline, f"{game_id}.level[{index}].baseline")
            levels.append(
                {
                    "agent_actions": _integer(raw_actions, f"{game_id}.level[{index}].actions"),
                    "completed": index <= levels_completed,
                    "human_baseline_actions": baseline if baseline > 0 else None,
                    "level_index": index,
                    "toolkit_score": _number(
                        raw_score,
                        f"{game_id}.level[{index}].score",
                        maximum=115.0,
                    )
                    / 100.0,
                }
            )
        try:
            level_measurements = tuple(
                LevelMeasurement(
                    level_index=level["level_index"],
                    completed=level["completed"],
                    toolkit_score=level["toolkit_score"],
                    agent_actions=level["agent_actions"],
                    human_baseline_actions=level["human_baseline_actions"],
                )
                for level in levels
            )
        except (TypeError, ValueError) as error:
            raise EvaluationError(f"{game_id} level scores do not reconcile") from error
        normalized_game_score = score / 100.0
        if not math.isclose(
            normalized_game_score,
            recompute_pinned_toolkit_game_score(level_measurements),
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            raise EvaluationError(f"{game_id} game score does not reconcile with level rows")
        raw_completed = _object_field(run, "completed", False)
        if not isinstance(raw_completed, bool):
            raise EvaluationError(f"{game_id}.completed must be boolean")
        rows.append(
            {
                "actions": actions,
                "completed": raw_completed,
                "game_id": game_id,
                "levels": levels,
                "levels_completed": levels_completed,
                "resets": resets,
                "state": _canonical_enum(_object_field(run, "state")),
                "toolkit_score": normalized_game_score,
            }
        )
    if tuple(row["game_id"] for row in rows) != expected:
        raise EvaluationError("official scorecard environment order differs from the freeze")
    return {
        "games": rows,
        "scorer_identity": pinned_toolkit_scorer_identity(),
        "schema": RAW_SCORECARD_SCHEMA,
        "status": "PASS",
        "surface": "local-public",
    }


def _write_identical_or_once(path: Path, payload: Mapping[str, Any] | bytes) -> None:
    encoded = payload if isinstance(payload, bytes) else canonical_json_bytes(dict(payload))
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError:
        if path.read_bytes() != encoded:
            raise EvaluationError(f"immutable Build 002 artifact differs: {path}") from None


def persist_collected_scorecard(
    scorecard: object, expected_games: Sequence[str], working_root: Path
) -> None:
    """Persist one identical credential-free scorer projection from agent cleanup."""

    payload = collect_scorecard_payload(scorecard, expected_games)
    _write_identical_or_once(
        working_root / "arc3-runtime-receipts" / "raw-local-scorecard.json", payload
    )


def _collector_source(production_agent: Path) -> bytes:
    expected_hash = sha256_file(production_agent)
    source = f'''"""Frozen Build 002 scorecard collector; policy delegates to agent.my_agent."""
from __future__ import annotations

import inspect
from pathlib import Path

from agent.my_agent import MyAgent as _ProductionMyAgent
from scripts.run_build002_holdout import persist_collected_scorecard

_EXPECTED_POLICY_SHA256 = {expected_hash!r}
_actual_policy = Path(inspect.getfile(_ProductionMyAgent)).resolve()
if "sha256:" + __import__("hashlib").sha256(_actual_policy.read_bytes()).hexdigest() != _EXPECTED_POLICY_SHA256:
    raise RuntimeError("frozen Build 002 production policy identity changed")


class MyAgent(_ProductionMyAgent):
    def is_done(self, frames: list[object], latest_frame: object) -> bool:
        return super().is_done(frames, latest_frame)

    def choose_action(self, frames: list[object], latest_frame: object) -> object:
        return super().choose_action(frames, latest_frame)

    def cleanup(self, scorecard: object | None = None) -> None:
        if scorecard is not None:
            root = self._working_root
            if root is None:
                raise RuntimeError("Build 002 scorecard collector has no working root")
            persist_collected_scorecard(scorecard, self._expected_games, Path(root))
        super().cleanup(scorecard)


__all__ = ["MyAgent"]
'''
    return source.encode("utf-8")


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise EvaluationError(f"unreadable JSON object: {path}") from error
    if not isinstance(value, dict):
        raise EvaluationError(f"JSON root must be an object: {path}")
    return value


def _path(root: Path, value: object, field: str, *, inside: bool = True) -> Path:
    raw = _required_string(value, field)
    candidate = Path(raw)
    resolved = (root / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
    if inside:
        try:
            resolved.relative_to(root)
        except ValueError as error:
            raise EvaluationError(f"{field} must remain inside the repository") from error
    return resolved


def _path_map(
    root: Path,
    value: object,
    field: str,
    expected: frozenset[str] | None = None,
    *,
    inside: bool = True,
) -> dict[str, Path]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise EvaluationError(f"{field} must be an object of paths")
    if expected is not None and set(value) != expected:
        raise EvaluationError(f"{field} has an incomplete or expanded role set")
    return {
        key: _path(root, item, f"{field}.{key}", inside=inside)
        for key, item in cast(dict[str, object], value).items()
    }


def load_run_plan(root: Path, plan_path: Path) -> RunPlan:
    resolved_plan = plan_path.resolve()
    try:
        relative_plan = resolved_plan.relative_to(root.resolve()).as_posix()
    except ValueError as error:
        raise EvaluationError("Build 002 run plan must remain inside the repository") from error
    if not relative_plan or any(part in {"", ".", ".."} for part in relative_plan.split("/")):
        raise EvaluationError("Build 002 run plan path is not canonical")
    value = _load_json(resolved_plan)
    expected_fields = {
        "artifacts",
        "assets",
        "framework_root",
        "gateway_host",
        "gateway_port",
        "gates",
        "manifest",
        "production_agent",
        "schema",
        "seed",
        "submission_output",
    }
    if set(value) != expected_fields or value.get("schema") != RUN_PLAN_SCHEMA:
        raise EvaluationError("Build 002 run plan schema or exact field set is invalid")
    seed = value["seed"]
    if isinstance(seed, bool) or not isinstance(seed, int) or not -(2**63) <= seed < 2**63:
        raise EvaluationError("Build 002 run seed must be a signed 64-bit integer")
    host = _required_string(value["gateway_host"], "gateway_host")
    if host not in _ALLOWED_GATEWAY_HOSTS:
        raise EvaluationError("Build 002 gateway must be an allowed offline/sidecar host")
    port = _integer(value["gateway_port"], "gateway_port", minimum=1)
    if port > 65535:
        raise EvaluationError("gateway_port exceeds 65535")
    return RunPlan(
        source_path=resolved_plan,
        seed=seed,
        manifest=_path(root, value["manifest"], "manifest"),
        assets=_path_map(root, value["assets"], "assets", inside=False),
        gates=_path_map(root, value["gates"], "gates", GATE_ROLES),
        artifacts=_path_map(root, value["artifacts"], "artifacts", ARTIFACT_ROLES),
        framework_root=_path(root, value["framework_root"], "framework_root", inside=False),
        production_agent=_path(root, value["production_agent"], "production_agent"),
        gateway_host=host,
        gateway_port=port,
        submission_output=_path(
            root, value["submission_output"], "submission_output", inside=False
        ),
    )


def prepare_inputs(plan: RunPlan) -> dict[str, Any]:
    """Create deterministic inventory/collector bytes without opening an environment."""

    if not plan.manifest.is_file():
        raise FileNotFoundError(f"public partition manifest is unavailable: {plan.manifest}")
    if not plan.production_agent.is_file():
        raise FileNotFoundError(f"production agent is unavailable: {plan.production_agent}")
    missing_assets = sorted(game_id for game_id, path in plan.assets.items() if not path.is_file())
    if missing_assets:
        raise FileNotFoundError(
            "static public-holdout assets are unavailable for: " + ", ".join(missing_assets)
        )
    inventory = create_static_asset_inventory(plan.manifest, plan.assets)
    _write_identical_or_once(plan.artifacts["holdout-asset-inventory"], inventory)
    _write_identical_or_once(
        plan.artifacts["agent-wrapper"], _collector_source(plan.production_agent)
    )
    return {
        "agent_wrapper_sha256": sha256_file(plan.artifacts["agent-wrapper"]),
        "environment_make_interactions": 0,
        "holdout_asset_inventory_sha256": sha256_file(plan.artifacts["holdout-asset-inventory"]),
        "status": "PREPARED_NOT_CONSUMED",
    }


def _validate_available_inputs(plan: RunPlan) -> None:
    required = {
        "framework_root": plan.framework_root,
        "manifest": plan.manifest,
        "production_agent": plan.production_agent,
        **{f"gate:{role}": path for role, path in plan.gates.items()},
        **{f"artifact:{role}": path for role, path in plan.artifacts.items()},
    }
    missing = [name for name, path in required.items() if not path.exists()]
    if missing:
        raise FileNotFoundError("required frozen surfaces are unavailable: " + ", ".join(missing))
    if not plan.framework_root.is_dir():
        raise FileNotFoundError("official framework root is not an available directory")
    if plan.submission_output.exists():
        raise EvaluationError("submission output must be absent before the one-shot launch")


class _RssMonitor:
    def __init__(self) -> None:
        self._samples: list[tuple[float, int, int, str]] = []
        self._measurement_error: Exception | None = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._sample_loop, daemon=True)

    @staticmethod
    def _memory_sample() -> tuple[int, int, str]:
        # The pinned framework is deliberately sequential and executes in this
        # process, so process RSS covers the complete controller/framework
        # workload without adding an unpinned psutil dependency.
        from arc3.profiling.runtime import process_memory_sample

        sample = process_memory_sample()
        current = sample.get("current_rss_bytes")
        peak = sample.get("peak_rss_bytes")
        source = sample.get("measurement_source")
        if (
            not isinstance(current, int)
            or current <= 0
            or not isinstance(peak, int)
            or peak <= 0
            or not isinstance(source, str)
            or not source
        ):
            raise EvaluationError(
                "kernel current/peak RSS measurement is unavailable: " + str(sample.get("reason"))
            )
        if peak < current:
            raise EvaluationError("kernel peak RSS is below current RSS")
        return current, peak, source

    def _record_sample(self) -> None:
        current, peak, source = self._memory_sample()
        self._samples.append((time.monotonic(), current, peak, source))

    def _sample_loop(self) -> None:
        try:
            while not self._stop.wait(0.05):
                self._record_sample()
        except Exception as error:
            self._measurement_error = error
            self._stop.set()

    def __enter__(self) -> _RssMonitor:
        self._record_sample()
        self._thread.start()
        return self

    def __exit__(self, *_args: object) -> None:
        self._stop.set()
        self._thread.join(timeout=2.0)
        self._record_sample()

    def _require_measurements(self) -> None:
        if self._measurement_error is not None:
            raise EvaluationError("kernel RSS monitor failed") from self._measurement_error
        if not self._samples or any(
            current <= 0 or peak <= 0 for _, current, peak, _ in self._samples
        ):
            raise EvaluationError("kernel RSS monitor returned no positive measurement")

    @property
    def kernel_peak_rss_bytes(self) -> int:
        self._require_measurements()
        return max((peak for _, _, peak, _ in self._samples), default=0)

    @property
    def measurement_source(self) -> str:
        self._require_measurements()
        sources = {source for _, _, _, source in self._samples}
        if len(sources) != 1:
            raise EvaluationError("kernel RSS measurement source changed during tournament")
        return next(iter(sources))

    def sampled_current_rss_max_between(self, began: float, ended: float) -> int:
        self._require_measurements()
        values = [current for instant, current, _, _ in self._samples if began <= instant <= ended]
        if values:
            return max(values)
        # Very short games can fall entirely between 50 ms samples. The nearest
        # process-current sample remains a sample, never a per-game kernel peak.
        nearest = min(self._samples, key=lambda row: min(abs(row[0] - began), abs(row[0] - ended)))
        return nearest[1]


def _launch_mapping(receipt: object) -> dict[str, Any]:
    if isinstance(receipt, Mapping):
        return dict(cast(Mapping[str, Any], receipt))
    serializer = getattr(receipt, "to_dict", None)
    if not callable(serializer):
        raise EvaluationError("competition launcher returned no serializable receipt")
    value = serializer()
    if not isinstance(value, dict):
        raise EvaluationError("competition launcher receipt is not an object")
    return cast(dict[str, Any], value)


def _governor_rows(launch: Mapping[str, Any]) -> list[dict[str, Any]]:
    wrapper = launch.get("tournament_receipt")
    receipt = wrapper.get("receipt") if isinstance(wrapper, dict) else None
    rows = receipt.get("games") if isinstance(receipt, dict) else None
    if not isinstance(rows, list) or any(not isinstance(item, dict) for item in rows):
        raise EvaluationError("terminal governor game receipts are unavailable")
    return cast(list[dict[str, Any]], rows)


def _load_failure_receipts(runtime_root: Path) -> list[dict[str, str]]:
    receipt_root = runtime_root / "arc3-runtime-receipts"
    rows: list[dict[str, str]] = []
    for path in sorted(receipt_root.glob("failure-*.json")):
        value = _load_json(path)
        classification = _required_string(value.get("classification"), "classification")
        try:
            FailureClassification(classification)
        except ValueError as error:
            raise EvaluationError("runtime failure receipt has an unknown taxonomy") from error
        rows.append(
            {
                "boundary": _required_string(value.get("boundary"), "boundary"),
                "classification": classification,
                "game_id": _required_string(value.get("game_id"), "game_id"),
            }
        )
    return rows


def _primary_failure(
    game_id: str, completed: bool, reason: str, receipts: Sequence[Mapping[str, str]]
) -> FailureClassification | None:
    if completed:
        return None
    for receipt in receipts:
        if receipt.get("game_id") == game_id:
            return FailureClassification(receipt["classification"])
    if reason in _RESOURCE_REASONS:
        return FailureClassification.BUDGET_EXHAUSTION
    if reason == "win":
        return FailureClassification.PLATFORM
    return FailureClassification.EXECUTION


def _measurements(
    raw_scorecard: Mapping[str, Any],
    launch: Mapping[str, Any],
    monitor: _RssMonitor,
    failure_receipts: list[dict[str, str]],
) -> tuple[GameMeasurement, ...]:
    raw_games = raw_scorecard.get("games")
    if (
        raw_scorecard.get("schema") != RAW_SCORECARD_SCHEMA
        or raw_scorecard.get("scorer_identity") != pinned_toolkit_scorer_identity()
        or not isinstance(raw_games, list)
    ):
        raise EvaluationError("collected local scorecard is invalid")
    governors = _governor_rows(launch)
    if len(raw_games) != len(governors):
        raise EvaluationError("scorecard and governor game counts differ")
    measured: list[GameMeasurement] = []
    for raw, governor in zip(raw_games, governors, strict=True):
        if not isinstance(raw, dict):
            raise EvaluationError("scorecard game row is not an object")
        game_id = _required_string(raw.get("game_id"), "game_id")
        if governor.get("game_id") != game_id:
            raise EvaluationError("scorecard and governor game order differ")
        completed = raw.get("completed") is True
        reason = _required_string(governor.get("reason"), "governor.reason")
        levels_raw = raw.get("levels")
        if not isinstance(levels_raw, list):
            raise EvaluationError("scorecard game has no level rows")
        levels = tuple(
            LevelMeasurement(
                level_index=item["level_index"],
                completed=item["completed"],
                toolkit_score=item["toolkit_score"],
                agent_actions=item["agent_actions"],
                human_baseline_actions=item["human_baseline_actions"],
            )
            for item in levels_raw
            if isinstance(item, dict)
        )
        if len(levels) != len(levels_raw):
            raise EvaluationError("scorecard contains a malformed level row")
        began = _number(governor.get("began_at_seconds"), "governor.began_at_seconds")
        ended = _number(governor.get("finalized_at_seconds"), "governor.finalized_at_seconds")
        if ended < began:
            raise EvaluationError("governor finalized a game before it began")
        primary = _primary_failure(game_id, completed, reason, failure_receipts)
        if primary is not None and not any(
            item["game_id"] == game_id and item["classification"] == primary.value
            for item in failure_receipts
        ):
            failure_receipts.append(
                {
                    "boundary": f"derived-from-governor-stop:{reason}",
                    "classification": primary.value,
                    "game_id": game_id,
                }
            )
        raw_actions = _integer(raw.get("actions"), "scorecard.actions")
        authorized_actions = _integer(governor.get("actions_authorized"), "actions_authorized")
        if raw_actions != authorized_actions:
            raise EvaluationError("scorecard actions disagree with governor accounting")
        raw_resets = _integer(raw.get("resets"), "scorecard.resets")
        authorized_resets = _integer(governor.get("resets_authorized"), "resets_authorized")
        reset_limit = _integer(governor.get("reset_limit"), "reset_limit")
        if (
            raw_resets != authorized_resets
            or authorized_resets > reset_limit
            or reset_limit > FROZEN_COMPETITION_RUNTIME.max_resets
        ):
            raise EvaluationError("scorecard resets disagree with governor accounting")
        measured.append(
            GameMeasurement(
                game_id=game_id,
                completed=completed,
                levels_completed=_integer(raw.get("levels_completed"), "levels_completed"),
                actions=authorized_actions,
                resets=authorized_resets,
                toolkit_score=_number(raw.get("toolkit_score"), "toolkit_score", maximum=1.0),
                wall_seconds=_number(governor.get("elapsed_seconds"), "elapsed_seconds"),
                sampled_current_rss_max_bytes=monitor.sampled_current_rss_max_between(began, ended),
                allocated_seconds=_number(governor.get("allocated_seconds"), "allocated_seconds"),
                reserve_remaining_seconds=_number(
                    governor.get("reserve_remaining_seconds"), "reserve_remaining_seconds"
                ),
                stop_reason=reason,
                primary_failure=primary,
                levels=levels,
            )
        )
    return tuple(measured)


def _write_local_public_submission(measurements: tuple[GameMeasurement, ...], output: Path) -> None:
    """Materialize a local-public terminal projection, never an official score."""

    if output.exists():
        raise EvaluationError("submission output appeared before local result materialization")
    try:
        import pyarrow as pa  # type: ignore[import-untyped]
        import pyarrow.parquet as pq  # type: ignore[import-untyped]
    except (ImportError, ModuleNotFoundError) as error:  # pragma: no cover - locked dependency
        raise EvaluationError("the pinned Parquet writer is unavailable") from error
    output.parent.mkdir(parents=True, exist_ok=True)
    table = pa.table(
        {
            "row_id": pa.array(
                [f"{index}_{game.game_id}" for index, game in enumerate(measurements)],
                type=pa.string(),
            ),
            "game_id": pa.array([game.game_id for game in measurements], type=pa.string()),
            "end_of_game": pa.array([True] * len(measurements), type=pa.bool_()),
            "score": pa.array(
                [float(game.toolkit_score) for game in measurements], type=pa.float64()
            ),
        }
    )
    pq.write_table(
        table,
        output,
        compression="NONE",
        use_dictionary=False,
        write_statistics=False,
        version="2.6",
    )
    receipt = validate_submission_parquet(output)
    if receipt.status != "PASS":  # pragma: no cover - validator is fail-closed
        raise EvaluationError("local-public submission projection did not validate")


def _result_artifacts(
    state_root: Path,
    measurements: tuple[GameMeasurement, ...],
    launch: dict[str, Any],
    total_wall: float,
    peak_memory: int,
    peak_memory_source: str,
    failure_receipts: list[dict[str, str]],
    submission_output: Path,
) -> tuple[ArtifactBinding, ...]:
    root = state_root / "result-artifacts"
    launch_path = root / "competition-launch-receipt.json"
    profile_path = root / "execution-profile.json"
    failures_path = root / "failure-receipts.json"
    scorecard_path = root / "local-scorecard.json"
    runtime_manifest_path = root / "runtime-evidence-manifest.json"
    submission_path = root / "submission.parquet"
    _write_identical_or_once(
        launch_path,
        {
            "receipt": launch,
            "schema": COMPETITION_LAUNCH_ARTIFACT_SCHEMA,
            "status": "PASS",
        },
    )
    _write_identical_or_once(
        profile_path,
        {
            "games": [
                {
                    "game_id": game.game_id,
                    "sampled_current_rss_max_bytes": game.sampled_current_rss_max_bytes,
                    "wall_seconds": float(game.wall_seconds),
                }
                for game in measurements
            ],
            "peak_memory_bytes": peak_memory,
            "peak_memory_source": peak_memory_source,
            "per_game_memory_measurement": PER_GAME_MEMORY_MEASUREMENT,
            "schema": EXECUTION_PROFILE_SCHEMA,
            "status": "PASS",
            "total_wall_seconds": float(total_wall),
            "tournament_memory_measurement": TOURNAMENT_MEMORY_MEASUREMENT,
        },
    )
    _write_identical_or_once(
        failures_path,
        {
            "games": [
                {
                    "game_id": game.game_id,
                    "primary_failure": (
                        game.primary_failure.value if game.primary_failure is not None else None
                    ),
                    "stop_reason": game.stop_reason,
                }
                for game in measurements
            ],
            "receipts": failure_receipts,
            "schema": FAILURE_RECEIPTS_SCHEMA,
            "status": "PASS",
        },
    )
    _write_identical_or_once(
        scorecard_path,
        {
            "completed_games": sum(game.completed for game in measurements),
            "completed_levels": sum(game.levels_completed for game in measurements),
            "games": [
                {
                    "actions": game.actions,
                    "completed": game.completed,
                    "game_id": game.game_id,
                    "levels": [
                        {
                            "agent_actions": level.agent_actions,
                            "completed": level.completed,
                            "human_baseline_actions": level.human_baseline_actions,
                            "level_index": level.level_index,
                            "toolkit_score": float(level.toolkit_score),
                        }
                        for level in game.levels
                    ],
                    "levels_completed": game.levels_completed,
                    "resets": game.resets,
                    "toolkit_score": float(game.toolkit_score),
                }
                for game in measurements
            ],
            "official": False,
            "schema": LOCAL_SCORECARD_SCHEMA,
            "status": "PASS",
            "surface": "local-public",
            "total_actions": sum(game.actions for game in measurements),
            "total_resets": sum(game.resets for game in measurements),
            "total_score": sum(game.toolkit_score for game in measurements) / len(measurements),
        },
    )
    receipt = validate_submission_parquet(submission_output)
    if receipt.status != "PASS":
        raise EvaluationError("produced submission Parquet did not validate")
    _write_identical_or_once(submission_path, submission_output.read_bytes())
    _write_identical_or_once(
        runtime_manifest_path,
        create_runtime_evidence_manifest(
            state_root,
            expected_games=tuple(game.game_id for game in measurements),
        ),
    )
    return (
        ArtifactBinding("competition-launch-receipt", launch_path),
        ArtifactBinding("execution-profile", profile_path),
        ArtifactBinding("failure-receipts", failures_path),
        ArtifactBinding("local-scorecard", scorecard_path),
        ArtifactBinding("runtime-evidence-manifest", runtime_manifest_path),
        ArtifactBinding("submission-parquet", submission_path),
    )


def _freeze_preflight(root: Path, state_root: Path, plan: RunPlan) -> Path:
    path = state_root / "preflight.json"
    if path.is_file():
        # ``arm`` revalidates the immutable preflight and every bound byte.  A
        # pre-consumption external stop may therefore be retried without
        # manufacturing a new timestamped freeze.
        frozen = _load_json(path)
        binding = frozen.get("run_plan")
        if (
            not isinstance(binding, dict)
            or binding.get("sha256") != sha256_file(plan.source_path)
            or binding.get("byte_length") != plan.source_path.stat().st_size
        ):
            raise EvaluationError("existing Build 002 freeze binds a different run plan")
        try:
            expected_relative = plan.source_path.resolve().relative_to(root.resolve()).as_posix()
        except ValueError as error:
            raise EvaluationError("Build 002 run plan escapes the repository") from error
        if binding.get("path") != expected_relative:
            raise EvaluationError("existing Build 002 freeze binds a different run-plan path")
        return path
    preflight = create_frozen_preflight(
        root,
        attempt_id=BUILD_002_ATTEMPT_ID,
        seed=plan.seed,
        manifest_path=plan.manifest,
        run_plan_path=plan.source_path,
        gates=tuple(ReceiptBinding(role, path) for role, path in sorted(plan.gates.items())),
        artifacts=tuple(
            ArtifactBinding(role, path) for role, path in sorted(plan.artifacts.items())
        ),
    )
    _write_identical_or_once(path, preflight)
    return path


def _pre_consumption_stop(
    state_root: Path,
    *,
    status: str,
    stage: str,
    error: BaseException,
    rerun_authorized: bool = True,
) -> dict[str, Any]:
    payload = seal_object(
        {
            "attempt_id": BUILD_002_ATTEMPT_ID,
            "environment_make_interactions": 0,
            "error_type": type(error).__name__,
            "message_sha256": "sha256:" + hashlib.sha256(str(error).encode("utf-8")).hexdigest(),
            "official_rhae": None,
            "rerun_authorized": rerun_authorized,
            "schema": PREFLIGHT_STOP_SCHEMA,
            "sealed_at": _utc_now(),
            "stage": stage,
            "status": status,
        },
        hash_field="stop_hash",
    )
    digest = cast(str, payload["stop_hash"]).removeprefix("sha256:")
    _write_identical_or_once(state_root / "blockers" / f"{digest}.json", payload)
    return payload


def _post_seal_validation_stop(
    state_root: Path, *, stage: str, error: BaseException
) -> dict[str, Any]:
    """Preserve a validator failure without creating a second terminal attempt."""

    payload = seal_object(
        {
            "attempt_id": BUILD_002_ATTEMPT_ID,
            "boundary": stage,
            "error_type": type(error).__name__,
            "message_sha256": "sha256:" + hashlib.sha256(str(error).encode("utf-8")).hexdigest(),
            "official_rhae": None,
            "rerun_authorized": False,
            "schema": "arc3.build-002.post-seal-validation-failure.v0.1",
            "sealed_at": _utc_now(),
            "status": "FAILED_INFRASTRUCTURE",
            "terminal_result_present": True,
        },
        hash_field="failure_hash",
    )
    digest = cast(str, payload["failure_hash"]).removeprefix("sha256:")
    _write_identical_or_once(state_root / "validation-failures" / f"{digest}.json", payload)
    return payload


def _closed_authority_stop(state_root: Path, *, stage: str, error: BaseException) -> dict[str, Any]:
    """Record an attempted rerun without ever reopening consumed authority."""

    exposure_path = state_root / "exposure.jsonl"
    intent_count = 0
    if exposure_path.is_file():
        try:
            intent_count = len(exposure_path.read_text(encoding="utf-8").splitlines())
        except (OSError, UnicodeError):
            intent_count = 1
    payload = seal_object(
        {
            "attempt_id": BUILD_002_ATTEMPT_ID,
            "environment_make_interactions": intent_count,
            "error_type": type(error).__name__,
            "message_sha256": "sha256:" + hashlib.sha256(str(error).encode("utf-8")).hexdigest(),
            "official_rhae": None,
            "rerun_authorized": False,
            "schema": "arc3.build-002.closed-authority-stop.v0.1",
            "sealed_at": _utc_now(),
            "stage": stage,
            "status": "BLOCKED_AUTHORITY",
        },
        hash_field="stop_hash",
    )
    digest = cast(str, payload["stop_hash"]).removeprefix("sha256:")
    _write_identical_or_once(state_root / "authority-stops" / f"{digest}.json", payload)
    return payload


def _failure_finalization_stop(
    state_root: Path, *, stage: str, error: BaseException
) -> dict[str, Any]:
    """Preserve a fail-closed receipt if detailed terminal recovery itself fails."""

    payload = seal_object(
        {
            "attempt_id": BUILD_002_ATTEMPT_ID,
            "boundary": stage,
            "error_type": type(error).__name__,
            "message_sha256": "sha256:" + hashlib.sha256(str(error).encode("utf-8")).hexdigest(),
            "official_rhae": None,
            "rerun_authorized": False,
            "schema": "arc3.build-002.failure-finalization-stop.v0.1",
            "sealed_at": _utc_now(),
            "status": "FAILED_INFRASTRUCTURE",
        },
        hash_field="failure_hash",
    )
    digest = cast(str, payload["failure_hash"]).removeprefix("sha256:")
    _write_identical_or_once(state_root / "recovery-failures" / f"{digest}.json", payload)
    return payload


def _pre_consumption_status(error: BaseException, *, stale_lock: bool) -> str:
    if stale_lock:
        return "BLOCKED_RECOVERY"
    if isinstance(
        error,
        (FileNotFoundError, ConnectionError, ExternalSurfaceUnavailableError),
    ):
        return "BLOCKED_EXTERNAL"
    return "FAILED_PREFLIGHT"


def execute(
    root: Path,
    plan_path: Path,
    *,
    launcher: _Launch = launch_frozen_framework_once,
) -> RunOutcome:
    """Execute one production attempt; dependency injection exists only for focused tests."""

    resolved_root = root.resolve()
    state_root = resolved_root / CANONICAL_STATE_RELATIVE
    seal: OneShotHoldoutSeal | None = None
    stage = "load-plan"
    try:
        plan = load_run_plan(resolved_root, plan_path.resolve())
        stage = "prepare-deterministic-inputs"
        prepare_inputs(plan)
        stage = "availability-preflight"
        _validate_available_inputs(plan)
        stage = "freeze-preflight"
        preflight_path = _freeze_preflight(resolved_root, state_root, plan)
        stage = "arm-one-shot"
        seal = OneShotHoldoutSeal.arm(
            resolved_root, state_root=state_root, preflight_path=preflight_path
        )
        runtime_root = state_root / "runtime"
        runtime_root.mkdir(parents=True, exist_ok=True)
        (runtime_root / "arc3-agent-state").mkdir(parents=True, exist_ok=True)
        (runtime_root / "arc3-runtime-receipts").mkdir(parents=True, exist_ok=True)
        started = time.monotonic()
        stage = "official-framework-launch"
        with _RssMonitor() as monitor:
            receipt = launcher(
                seal,
                plan.framework_root,
                plan.artifacts["agent-wrapper"],
                gateway_host=plan.gateway_host,
                gateway_port=plan.gateway_port,
                working_root=runtime_root,
                allow_test_fixture=False,
                notebook_started_at_seconds=started,
            )
        total_wall = time.monotonic() - started
        launch = _launch_mapping(receipt)
        stage = "measurement-collection"
        raw = _load_json(runtime_root / "arc3-runtime-receipts" / "raw-local-scorecard.json")
        failure_receipts = _load_failure_receipts(runtime_root)
        measured = _measurements(raw, launch, monitor, failure_receipts)
        if tuple(game.game_id for game in measured) != seal.expected_games:
            raise EvaluationError("collected game identities differ from the armed freeze")
        _write_local_public_submission(measured, plan.submission_output)
        artifacts = _result_artifacts(
            state_root,
            measured,
            launch,
            total_wall,
            monitor.kernel_peak_rss_bytes,
            monitor.measurement_source,
            failure_receipts,
            plan.submission_output,
        )
        stage = "terminal-seal"
        terminal_status = (
            "PASS"
            if all(game.completed for game in measured) and not failure_receipts
            else "PARTIAL"
        )
        result = seal.seal_terminal_result(
            status=terminal_status,
            games=measured,
            launch_receipt=launch,
            total_wall_seconds=total_wall,
            peak_memory_bytes=monitor.kernel_peak_rss_bytes,
            peak_memory_source=monitor.measurement_source,
            result_artifacts=artifacts,
        )
        stage = "independent-validation"
        validated = validate_terminal_result(
            resolved_root, state_root=state_root, preflight_path=preflight_path
        )
        if validated != result:
            raise EvaluationError("independent terminal validation changed the sealed result")
        return RunOutcome(cast(str, result["status"]), result, 0)
    except BaseException as error:
        consumption_path = state_root / "holdout-consumed.json"
        if consumption_path.exists() and (seal is None or not seal.consumed):
            stopped = _closed_authority_stop(state_root, stage=stage, error=error)
            return RunOutcome("BLOCKED_AUTHORITY", stopped, 4)
        if seal is not None and seal.consumed:
            try:
                if (state_root / "result.json").is_file():
                    stopped = _post_seal_validation_stop(state_root, stage=stage, error=error)
                    return RunOutcome("FAILED_INFRASTRUCTURE", stopped, 3)
                failure_path = state_root / "failed-attempt.json"
                if not failure_path.exists():
                    seal.seal_consumed_failure(
                        classification=FailureClassification.PLATFORM,
                        boundary=stage,
                        error=error,
                    )
                preflight_path = state_root / "preflight.json"
                failure = validate_consumed_failure(
                    resolved_root,
                    state_root=state_root,
                    preflight_path=preflight_path,
                )
                return RunOutcome("FAILED_INFRASTRUCTURE", failure, 3)
            except BaseException as finalization_error:
                stopped = _failure_finalization_stop(
                    state_root, stage=stage, error=finalization_error
                )
                return RunOutcome("FAILED_INFRASTRUCTURE", stopped, 3)
        if seal is not None:
            try:
                seal.release_unconsumed()
            except BaseException as release_error:
                stopped = _failure_finalization_stop(
                    state_root,
                    stage="unconsumed-lock-release",
                    error=release_error,
                )
                return RunOutcome("FAILED_INFRASTRUCTURE", stopped, 3)
        stale_lock = (state_root / "run.lock").exists()
        status = _pre_consumption_status(error, stale_lock=stale_lock)
        stopped = _pre_consumption_stop(
            state_root,
            status=status,
            stage=stage,
            error=error,
            rerun_authorized=not stale_lock,
        )
        return RunOutcome(status, stopped, 2)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "run"))
    parser.add_argument("plan", type=Path)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    root = cast(Path, args.root).resolve()
    plan_path = cast(Path, args.plan)
    try:
        plan = load_run_plan(root, plan_path.resolve())
        if args.command == "prepare":
            outcome = prepare_inputs(plan)
            print(json.dumps(outcome, indent=2, sort_keys=True))
            return 0
        result = execute(root, plan_path.resolve())
        print(json.dumps(result.receipt, indent=2, sort_keys=True))
        return result.exit_code
    except Exception as error:
        print(
            json.dumps(
                {
                    "error_type": type(error).__name__,
                    "message_sha256": "sha256:"
                    + hashlib.sha256(str(error).encode("utf-8")).hexdigest(),
                    "status": "FAILED_PREFLIGHT",
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
