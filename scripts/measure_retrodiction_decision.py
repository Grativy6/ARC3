#!/usr/bin/env python3
"""Run the frozen Build 001 Stage 07 retrodiction decision protocol.

The default command is deliberately non-executing: it validates the composite
premeasurement contract and the checked-in false-rule manifest.  ``--execute``
is required to create the official 280-cell result.  The runner never opens a
public holdout identity and denies socket construction for every measured cell.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import platform
import socket
import statistics
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import asdict, dataclass, replace
from itertools import product
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from arc3.ablations import runner as stage14_runner  # noqa: E402
from arc3.ablations.models import AblationId, features_for_ablation  # noqa: E402
from arc3.adapters import Observation  # noqa: E402
from arc3.adapters.arc_agi import ArcAGIAdapter  # noqa: E402
from arc3.config import ARC3Config, BudgetConfig  # noqa: E402
from arc3.errors import EvaluationError, PolicyError  # noqa: E402
from arc3.evaluation.artifacts import (  # noqa: E402
    atomic_write_json,
    canonical_json_bytes,
    seal_object,
    sha256_bytes,
    sha256_file,
    verify_object_hash,
)
from arc3.evaluation.public import (  # noqa: E402
    LocalAssetIdentity,
    PublicExposureLedger,
    PublicPartitionManifest,
    local_asset_identity,
    run_public_episode,
)
from arc3.evaluation.retrodiction_decision import (  # noqa: E402
    AMENDMENT_PATH,
    AMENDMENT_SHA256,
    FALSE_RULE_MANIFEST_PATH,
    MAX_OVERALL_WALL_SECONDS,
    MAX_PEAK_RSS_BYTES,
    MICRO_HISTORY_SIZES,
    MICRO_REPETITIONS,
    MICRO_WARMUPS,
    MODE_ORDER,
    PREDECLARATION_PATH,
    PREDECLARATION_SHA256,
    PUBLIC_PARTITION_PATH,
    PUBLIC_PARTITION_SHA256,
    CellMeasurement,
    EvaluationCell,
    EvaluationGroup,
    FalseRuleCase,
    MicrobenchmarkMeasurement,
    ModeGateResult,
    build_evaluation_matrix,
    build_false_rule_cases,
    build_false_rule_manifest,
    cell_budget_passed,
    choose_retrodiction_decision,
    evaluate_replacement_gates,
    selected_rule_change_cases,
    validate_false_rule_manifest,
)
from arc3.policy import (  # noqa: E402
    ARC3Controller,
    ControllerPhase,
    ControllerPreset,
    PresetFeatures,
    RunContext,
    preset_features,
)
from arc3.profiling.hot_path import HotPathProfiler  # noqa: E402
from arc3.profiling.runtime import process_memory_sample  # noqa: E402
from arc3.trace import EventJournal, ReplayEngine, TraceEvent, verify_event_chain  # noqa: E402
from arc3.trace.canonical import normalize_json, sha256_json  # noqa: E402
from arc3.types import (  # noqa: E402
    ActionName,
    ActionRequest,
    EnvironmentMode,
    GameId,
    GameStateName,
    JSONValue,
)
from arc3.world_model.model import ModelCandidate, make_model_candidate  # noqa: E402
from arc3.world_model.retrodiction import (  # noqa: E402
    MatchedPredictionEvidence,
    PreservedTransition,
    PromotionStatus,
    RetrodictionConfig,
    RetrodictionEvaluation,
    RetrodictionMode,
    RetrodictionPlan,
    RetrodictionRequest,
    RetrodictionRuntime,
)
from arc3.world_model.rules import MovementRule  # noqa: E402
from arc3.world_model.state import Cell, SymbolicEntity, SymbolicState  # noqa: E402

DEFAULT_OUTPUT = Path("C:/a/arc3-b001/artifacts/stage07/retrodiction-decision-attempt-01.json")
DEFAULT_WORK_ROOT = Path("C:/a/arc3-b001/artifacts/stage07/retrodiction-decision-work-attempt-01")
DEFAULT_EXPOSURE_LEDGER = Path("C:/a/arc3-b001/artifacts/stage07/public-exposure.jsonl")
DEFAULT_ENVIRONMENTS_DIR = Path("C:/a/arc3-s15-6a0f6e5/artifacts/stage15/public-environments")
DEFAULT_RECORDINGS_DIR = Path("C:/a/arc3-b001/artifacts/stage07/development-recordings")
_EXPECTED_DEVELOPMENT_ASSET_IDENTITY = LocalAssetIdentity(
    game_id="ar25-0c556536",
    files=(
        (
            "ar25.py",
            77_599,
            "sha256:6aed29a43629d8f9537d3d84553cec095b5d0002225db1c407754ffd4343b694",
        ),
        (
            "metadata.json",
            378,
            "sha256:94bb5161b1b6c8ada3399755b6602f2142e5570d11d2a477d6c65608d2b4be1c",
        ),
    ),
    aggregate_sha256="sha256:e796e615d2e10c93b849f9bf150308fbf84d624725deaf995d7ec2d1c2f86b22",
)
_STAGE06_SCRIPT = ROOT / "scripts/measure_rule_change_reopening.py"
_EXPECTED_BRANCH = "build/001-local-public-recovery"
_SOURCE_BASELINE_COMMIT = "8e3400cebda87f75b8bb3fd0c8d592d2125a6869"
_INHERITED_EXPOSURE_LEDGERS = (
    (
        "build-000",
        Path("C:/a/arc3-s15-6a0f6e5/artifacts/stage15/public-exposure.jsonl"),
        "sha256:cd9af42ed3a5ef9fa0dc201ddb10e32d2bcccee9df729aa0c7d53077c04c9ad4",
    ),
    (
        "stage-03",
        Path("C:/a/arc3-b001/artifacts/stage03/public-exposure.jsonl"),
        "sha256:e02a9fa71206170a6fe2aeefb6935ae25141e2759937657475cead4389bb17aa",
    ),
)
_SOURCE_PATHS = (
    ROOT / "src/arc3",
    ROOT / "scripts/measure_retrodiction_decision.py",
    ROOT / "docs/evidence/001-07-retrodiction-predeclaration.json",
    ROOT / "docs/evidence/001-07-retrodiction-predeclaration-amendment-01.json",
    ROOT / "docs/evidence/001-07-false-rule-case-manifest.json",
    ROOT / "pyproject.toml",
    ROOT / "uv.lock",
)
_FULL_STATUS = {PromotionStatus.PROMOTED}
_TIMING_PATHS = ("cold_exact_n", "append_one_from_verified_n_minus_1_prefix")


@dataclass(frozen=True, slots=True)
class RawMicrobenchmark:
    """Raw samples and semantics for one frozen 60-cell timing row."""

    measurement: MicrobenchmarkMeasurement
    warmup_wall_ns: tuple[int, ...]
    warmup_cpu_ns: tuple[int, ...]
    measured_wall_ns: tuple[int, ...]
    measured_cpu_ns: tuple[int, ...]
    artifact_ids: tuple[str, ...]
    plan_reasons: tuple[str, ...]
    prefix_counts: tuple[int, ...]
    suffix_counts: tuple[int, ...]

    def to_dict(self) -> dict[str, JSONValue]:
        return cast(dict[str, JSONValue], normalize_json(asdict(self)))


@dataclass(frozen=True, slots=True)
class _TimedRetrodiction:
    wall_ns: int
    cpu_ns: int
    plan: RetrodictionPlan
    evaluation: RetrodictionEvaluation


class _SocketDeny(AbstractContextManager["_SocketDeny"]):
    """Deny common socket entry points and count every attempted use."""

    def __init__(self) -> None:
        self.attempt_count = 0
        self._stack: list[Any] = []

    def _denied(self, *_args: object, **_kwargs: object) -> None:
        self.attempt_count += 1
        raise RuntimeError("Stage 07 offline socket access denied")

    def __enter__(self) -> _SocketDeny:
        for target in ("socket", "create_connection", "getaddrinfo"):
            replacement = self._denied
            manager = patch.object(socket, target, replacement)
            manager.start()
            self._stack.append(manager)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object,
    ) -> None:
        del exc_type, exc, traceback
        while self._stack:
            self._stack.pop().stop()


def _git_value(*arguments: str) -> str | None:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if completed.returncode != 0:
        return None
    return completed.stdout.strip()


def _git_success(*arguments: str) -> bool:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=False,
    )
    return completed.returncode == 0


def _inventory(paths: Sequence[Path]) -> tuple[dict[str, JSONValue], ...]:
    files: list[Path] = []
    for path in paths:
        if path.is_dir():
            files.extend(
                item
                for item in path.rglob("*")
                if item.is_file() and "__pycache__" not in item.parts and item.suffix != ".pyc"
            )
        elif path.is_file():
            files.append(path)
        else:
            raise EvaluationError(f"source identity path is missing: {path}")
    unique = sorted(set(files), key=lambda item: item.relative_to(ROOT).as_posix())
    return tuple(
        {
            "bytes": path.stat().st_size,
            "path": path.relative_to(ROOT).as_posix(),
            "sha256": sha256_file(path),
        }
        for path in unique
    )


def _source_identity() -> dict[str, object]:
    head = _git_value("rev-parse", "HEAD")
    tree = _git_value("rev-parse", "HEAD^{tree}")
    branch = _git_value("branch", "--show-current")
    status = _git_value("status", "--porcelain=v1", "--untracked-files=all")
    if head is None or tree is None or branch is None or status is None:
        raise EvaluationError("Stage 07 git source identity is unavailable")
    inventory = _inventory(_SOURCE_PATHS)
    return seal_object(
        {
            "amendment_sha256": sha256_file(AMENDMENT_PATH),
            "branch": branch,
            "dirty_worktree": bool(status),
            "false_rule_manifest_sha256": sha256_file(FALSE_RULE_MANIFEST_PATH),
            "first_party_inventory": list(inventory),
            "first_party_source_hash": sha256_json(list(inventory)),
            "git_commit": head,
            "git_tree": tree,
            "predeclaration_sha256": sha256_file(PREDECLARATION_PATH),
            "public_partition_sha256": sha256_file(PUBLIC_PARTITION_PATH),
            "schema": "arc3.build-001.stage-07-source-identity.v0.1",
            "source_baseline_ancestor": _git_success(
                "merge-base", "--is-ancestor", _SOURCE_BASELINE_COMMIT, "HEAD"
            ),
            "source_baseline_commit": _SOURCE_BASELINE_COMMIT,
            "status_porcelain": status,
        },
        hash_field="identity_hash",
    )


def _source_stability(start: Mapping[str, object], end: Mapping[str, object]) -> dict[str, object]:
    fields = (
        "amendment_sha256",
        "branch",
        "dirty_worktree",
        "false_rule_manifest_sha256",
        "first_party_source_hash",
        "git_commit",
        "git_tree",
        "predeclaration_sha256",
        "public_partition_sha256",
        "source_baseline_ancestor",
        "source_baseline_commit",
    )
    predicates = {
        "clean_at_start": start.get("dirty_worktree") is False,
        "clean_at_end": end.get("dirty_worktree") is False,
        "exact_identity_stable": all(start.get(field) == end.get(field) for field in fields),
    }
    return {
        "passed": all(predicates.values()),
        "predicates": predicates,
        "start_identity_hash": start.get("identity_hash"),
        "end_identity_hash": end.get("identity_hash"),
    }


def _development_asset_receipt(observed: LocalAssetIdentity | None) -> dict[str, object]:
    """Bind the development game to its previously measured opaque byte identity."""

    expected = _EXPECTED_DEVELOPMENT_ASSET_IDENTITY
    predicates = {
        "present": observed is not None,
        "game_id": observed is not None and observed.game_id == expected.game_id,
        "ordered_file_identity": observed is not None and observed.files == expected.files,
        "aggregate_sha256": (
            observed is not None and observed.aggregate_sha256 == expected.aggregate_sha256
        ),
        "exact_identity": observed == expected,
    }
    return {
        "expected": expected.to_dict(),
        "observed": observed.to_dict() if observed is not None else None,
        "passed": all(predicates.values()),
        "predicates": predicates,
    }


def _require_composite_contract() -> dict[str, object]:
    predicates = {
        "base_sha256": sha256_file(PREDECLARATION_PATH) == PREDECLARATION_SHA256,
        "amendment_sha256": sha256_file(AMENDMENT_PATH) == AMENDMENT_SHA256,
        "partition_sha256": sha256_file(PUBLIC_PARTITION_PATH) == PUBLIC_PARTITION_SHA256,
    }
    loaded = json.loads(FALSE_RULE_MANIFEST_PATH.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise EvaluationError("false-rule case manifest is not an object")
    manifest_predicates = validate_false_rule_manifest(cast(dict[str, object], loaded))
    predicates.update({f"manifest_{key}": value for key, value in manifest_predicates.items()})
    if not all(predicates.values()):
        raise EvaluationError(f"Stage 07 composite contract failed: {predicates}")
    return {
        "amendment_sha256": AMENDMENT_SHA256,
        "base_sha256": PREDECLARATION_SHA256,
        "false_rule_manifest_sha256": sha256_file(FALSE_RULE_MANIFEST_PATH),
        "passed": True,
        "predicates": predicates,
    }


def _holdout_integrity(
    exposure_path: Path,
    environments_dir: Path,
    *,
    inherited_ledgers: Sequence[tuple[str, Path, str]] = _INHERITED_EXPOSURE_LEDGERS,
) -> dict[str, object]:
    manifest = PublicPartitionManifest.load(PUBLIC_PARTITION_PATH)
    ledger = PublicExposureLedger(exposure_path)
    events = ledger.events()
    holdout_ids = {item.game_id for item in manifest.games("public-holdout")}
    development_entries = tuple(manifest.games("development"))
    development_ids = {item.game_id for item in development_entries}
    development_entry = next(
        (item for item in development_entries if item.game_id == "ar25-0c556536"),
        None,
    )
    development_asset = _development_asset_receipt(
        local_asset_identity(environments_dir, development_entry)
        if development_entry is not None
        else None
    )
    current_holdout = 0
    for event in events:
        payload = event.get("payload")
        if not isinstance(payload, Mapping):
            continue
        game_id = payload.get("game_id")
        partition = payload.get("partition")
        current_holdout += int(game_id in holdout_ids or partition == "public-holdout")
    inherited_receipts: list[dict[str, object]] = []
    inherited_holdout = 0
    for label, path, expected_sha256 in inherited_ledgers:
        digest = sha256_file(path) if path.is_file() else None
        inherited_events = PublicExposureLedger(path).events() if path.is_file() else ()
        holdout_count = 0
        for event in inherited_events:
            payload = event.get("payload")
            if not isinstance(payload, Mapping):
                continue
            holdout_count += int(
                payload.get("game_id") in holdout_ids
                or payload.get("partition") == "public-holdout"
            )
        inherited_holdout += holdout_count
        inherited_receipts.append(
            {
                "entry_count": len(inherited_events),
                "expected_sha256": expected_sha256,
                "holdout_event_count": holdout_count,
                "label": label,
                "path": str(path.resolve()),
                "sha256": digest,
                "verified": digest == expected_sha256,
            }
        )
    attempted_holdout = current_holdout + inherited_holdout
    local_holdout_assets = [
        item.game_id
        for item in manifest.games("public-holdout")
        if local_asset_identity(environments_dir, item) is not None
    ]
    predicates = {
        "development_asset_identity": development_asset["passed"] is True,
        "development_identity_present": "ar25-0c556536" in development_ids,
        "holdout_identity_count": len(holdout_ids) == 10,
        "inherited_exposure_ledgers": all(item["verified"] is True for item in inherited_receipts),
        "manifest_sha256": manifest.digest == PUBLIC_PARTITION_SHA256,
        "public_holdout_gameplay_events": attempted_holdout == 0,
        "public_holdout_local_assets": not local_holdout_assets,
    }
    return {
        "development_asset_identity": development_asset,
        "development_identity": "ar25-0c556536",
        "exposure_ledgers": inherited_receipts,
        "locally_acquired_holdout_asset_ids": local_holdout_assets,
        "passed": all(predicates.values()),
        "predicates": predicates,
        "public_holdout_gameplay_events": attempted_holdout,
        "stage07_public_holdout_gameplay_events": current_holdout,
        "status": "SEALED_UNCONSUMED" if all(predicates.values()) else "VIOLATED",
    }


def _require_fresh_targets(
    output: Path,
    work_root: Path,
    *,
    exposure_ledger: Path | None = None,
    recordings_dir: Path | None = None,
) -> None:
    if output.exists():
        raise EvaluationError(f"Stage 07 output already exists and cannot be overwritten: {output}")
    if exposure_ledger is not None and exposure_ledger.exists():
        raise EvaluationError(
            f"Stage 07 exposure ledger already exists and cannot be overwritten: {exposure_ledger}"
        )
    if work_root.exists():
        if not work_root.is_dir() or any(work_root.iterdir()):
            raise EvaluationError(
                f"Stage 07 work root already exists and is not empty: {work_root}"
            )
    if recordings_dir is not None and recordings_dir.exists():
        if not recordings_dir.is_dir() or any(recordings_dir.iterdir()):
            raise EvaluationError(
                f"Stage 07 recordings root already exists and is not empty: {recordings_dir}"
            )


def _require_official_paths(
    *,
    output: Path,
    work_root: Path,
    exposure_ledger: Path,
    environments_dir: Path,
    recordings_dir: Path,
) -> None:
    """Reject caller-selected paths that can evade the frozen attempt and holdout scope."""

    supplied = {
        "output": output,
        "work_root": work_root,
        "exposure_ledger": exposure_ledger,
        "environments_dir": environments_dir,
        "recordings_dir": recordings_dir,
    }
    expected = {
        "output": DEFAULT_OUTPUT,
        "work_root": DEFAULT_WORK_ROOT,
        "exposure_ledger": DEFAULT_EXPOSURE_LEDGER,
        "environments_dir": DEFAULT_ENVIRONMENTS_DIR,
        "recordings_dir": DEFAULT_RECORDINGS_DIR,
    }
    mismatches = {
        key: {"expected": str(expected[key].resolve()), "supplied": str(value.resolve())}
        for key, value in supplied.items()
        if value.resolve() != expected[key].resolve()
    }
    if mismatches:
        raise EvaluationError(
            f"official Stage 07 paths differ from the frozen contract: {mismatches}"
        )


def _features_for_mode(
    mode: RetrodictionMode, template: PresetFeatures | None = None
) -> PresetFeatures:
    features = (
        features_for_ablation(AblationId.A3)
        if mode is RetrodictionMode.NONE
        else preset_features(ControllerPreset.FULL)
    )
    if template is not None:
        features = replace(features, use_memory=template.use_memory)
    return features


def _retrodiction_config(mode: RetrodictionMode) -> RetrodictionConfig:
    return RetrodictionConfig(mode=mode, capacity=64, window=8)


def _micro_state(x: int) -> SymbolicState:
    return SymbolicState(
        width=80,
        height=3,
        entities=(SymbolicEntity("mover", "mover", (Cell(x, 1),)),),
    )


def build_micro_history(size: int) -> tuple[ModelCandidate, tuple[PreservedTransition, ...]]:
    """Build one fixed matching ACTION1/+1 history for a frozen size."""

    if size not in MICRO_HISTORY_SIZES:
        raise EvaluationError("microbenchmark history size is outside the frozen schedule")
    action = ActionRequest(ActionName.ACTION1)
    model = make_model_candidate(
        hypothesis_ids=("H-stage07-micro-movement",),
        rules=(MovementRule("R-stage07-micro-movement", ActionName.ACTION1, 1, 0, "mover"),),
        rank_weight=1,
    )
    transitions = tuple(
        PreservedTransition(
            transition_id=f"stage07-micro-n{size:04d}-t{index:03d}",
            before=_micro_state(index + 1),
            action=action,
            after=_micro_state(index + 2),
            source_event_ids=(
                f"event:stage07-micro-n{size:04d}-t{index:03d}:before",
                f"event:stage07-micro-n{size:04d}-t{index:03d}:after",
            ),
            compatible_model_ids=(model.model_id,),
        )
        for index in range(size)
    )
    return model, transitions


def _matched_evidence(transition: PreservedTransition) -> MatchedPredictionEvidence:
    suffix = transition.transition_id
    model_id = transition.compatible_model_ids[0]
    return MatchedPredictionEvidence(
        transition_id=suffix,
        model_id=model_id,
        prediction_event_id=f"event:prediction:{suffix}",
        prediction_receipt_id=f"receipt:prediction:{suffix}",
        consequence_event_id=f"event:consequence:{suffix}",
        assessment_receipt_id=f"receipt:assessment:{suffix}",
        matched=True,
        match_scope="whole-symbolic-state",
    )


def _request(
    model: ModelCandidate,
    transitions: tuple[PreservedTransition, ...],
    *,
    evidence: tuple[MatchedPredictionEvidence, ...] = (),
) -> RetrodictionRequest:
    return RetrodictionRequest(
        model=model,
        transitions=transitions,
        mechanics_epoch_id="mechanics-epoch:stage07-micro:0000",
        matched_evidence=evidence,
    )


def _execute_timed(
    runtime: RetrodictionRuntime,
    request: RetrodictionRequest,
    *,
    receipt_id: str,
) -> _TimedRetrodiction:
    wall_started = time.perf_counter_ns()
    cpu_started = time.process_time_ns()
    plan = runtime.plan(request)
    evaluation = runtime.execute(plan)
    runtime.commit(evaluation, source_receipt_event_id=receipt_id)
    cpu_ns = max(0, time.process_time_ns() - cpu_started)
    wall_ns = max(0, time.perf_counter_ns() - wall_started)
    return _TimedRetrodiction(wall_ns, cpu_ns, plan, evaluation)


def _one_micro_sample(
    mode: RetrodictionMode,
    size: int,
    path: str,
    sample_index: int,
) -> _TimedRetrodiction:
    model, transitions = build_micro_history(size)
    runtime = RetrodictionRuntime(_retrodiction_config(mode))
    if path == "append_one_from_verified_n_minus_1_prefix":
        prefix = _request(model, transitions[:-1])
        prefix_plan = runtime.plan(prefix)
        prefix_evaluation = runtime.execute(prefix_plan)
        runtime.commit(
            prefix_evaluation,
            source_receipt_event_id=f"receipt:micro:{mode.value}:{size}:{sample_index}:prefix",
        )
        evidence = (
            (_matched_evidence(transitions[-1]),)
            if mode is RetrodictionMode.EVENT_TRIGGERED
            else ()
        )
        request = _request(model, transitions, evidence=evidence)
    elif path == "cold_exact_n":
        request = _request(model, transitions)
    else:
        raise EvaluationError("unknown Stage 07 microbenchmark path")
    return _execute_timed(
        runtime,
        request,
        receipt_id=f"receipt:micro:{mode.value}:{size}:{sample_index}:measured",
    )


def measure_microbenchmark_cell(
    mode: RetrodictionMode,
    size: int,
    path: str,
    *,
    warmups: int = MICRO_WARMUPS,
    repetitions: int = MICRO_REPETITIONS,
) -> RawMicrobenchmark:
    """Measure one frozen cell with fresh runtime state for every repetition."""

    if isinstance(warmups, bool) or warmups < 0:
        raise EvaluationError("microbenchmark warmups must be non-negative")
    if isinstance(repetitions, bool) or repetitions <= 0:
        raise EvaluationError("microbenchmark repetitions must be positive")
    warm = tuple(_one_micro_sample(mode, size, path, index) for index in range(warmups))
    measured = tuple(
        _one_micro_sample(mode, size, path, warmups + index) for index in range(repetitions)
    )
    full_reference = _one_micro_sample(
        RetrodictionMode.FULL,
        size,
        "cold_exact_n",
        warmups + repetitions + 1,
    )
    evaluations = tuple(item.evaluation for item in measured)
    matching = all(
        not item.artifact.contradiction_transition_ids
        and item.artifact.model_id == full_reference.evaluation.artifact.model_id
        for item in evaluations
    )
    full_parity = all(item.artifact == full_reference.evaluation.artifact for item in evaluations)
    expected_cache_hit = (
        mode in {RetrodictionMode.EVENT_TRIGGERED, RetrodictionMode.CACHED_INCREMENTAL}
        and path == "append_one_from_verified_n_minus_1_prefix"
    )
    cache_hit = all(item.plan.cache_hit for item in measured) if expected_cache_hit else False
    semantic_parity = matching and (mode is not RetrodictionMode.CACHED_INCREMENTAL or full_parity)
    measurement = MicrobenchmarkMeasurement(
        mode=mode,
        history_size=size,
        path=path,
        median_wall_ns=int(statistics.median(item.wall_ns for item in measured)),
        median_cpu_ns=int(statistics.median(item.cpu_ns for item in measured)),
        semantic_parity=semantic_parity,
        cache_hit=cache_hit,
        full_artifact_parity=(full_parity if mode is RetrodictionMode.CACHED_INCREMENTAL else True),
    )
    return RawMicrobenchmark(
        measurement=measurement,
        warmup_wall_ns=tuple(item.wall_ns for item in warm),
        warmup_cpu_ns=tuple(item.cpu_ns for item in warm),
        measured_wall_ns=tuple(item.wall_ns for item in measured),
        measured_cpu_ns=tuple(item.cpu_ns for item in measured),
        artifact_ids=tuple(item.evaluation.artifact.artifact_id for item in measured),
        plan_reasons=tuple(item.plan.reason.value for item in measured),
        prefix_counts=tuple(item.plan.prefix_count for item in measured),
        suffix_counts=tuple(item.plan.suffix_count for item in measured),
    )


def _run_false_rule_cell(
    cell: EvaluationCell,
    case: FalseRuleCase,
    cell_root: Path,
) -> tuple[CellMeasurement, dict[str, object]]:
    before_rss = process_memory_sample()
    wall_started = time.perf_counter_ns()
    cpu_started = time.process_time_ns()
    config = _retrodiction_config(cell.mode)
    evaluations: dict[str, RetrodictionEvaluation] = {}
    plans: dict[str, RetrodictionPlan] = {}
    roundtrips: dict[str, bool] = {}
    for truth, model in (("TRUE", case.true_model), ("FALSE", case.false_model)):
        runtime = RetrodictionRuntime(config)
        request = RetrodictionRequest(
            model=model,
            transitions=case.transitions,
            mechanics_epoch_id=f"mechanics-epoch:stage07:{case.code}",
        )
        plan = runtime.plan(request)
        evaluation = runtime.execute(plan)
        runtime.commit(
            evaluation,
            source_receipt_event_id=f"receipt:{cell.cell_id}:{truth.lower()}",
        )
        restored = RetrodictionRuntime.from_dict(runtime.to_dict(), expected_config=config)
        replay_plan = restored.plan(request)
        replay_evaluation = restored.execute(replay_plan)
        roundtrips[truth] = (
            restored.to_dict() == runtime.to_dict()
            and replay_evaluation.artifact == evaluation.artifact
        )
        plans[truth] = plan
        evaluations[truth] = evaluation
    wall_ns = max(0, time.perf_counter_ns() - wall_started)
    cpu_ns = max(0, time.process_time_ns() - cpu_started)
    after_rss = process_memory_sample()
    memory = _memory_receipt(before_rss, after_rss)
    peak = cast(int, memory["peak_rss_bytes"])
    true_accepted = evaluations["TRUE"].artifact.status in (
        _FULL_STATUS | {PromotionStatus.UNGATED_ABLATION}
    )
    false_accepted = evaluations["FALSE"].artifact.status in (
        _FULL_STATUS | {PromotionStatus.UNGATED_ABLATION}
    )
    record = seal_object(
        {
            "case": case.to_manifest(),
            "cell": cell.to_dict(),
            "checkpoint_roundtrip": roundtrips,
            "artifact_projection": [
                _evaluation_artifact_projection(evaluations[truth]) for truth in ("TRUE", "FALSE")
            ],
            "evaluations": {
                truth: evaluation.to_trace_payload() for truth, evaluation in evaluations.items()
            },
            "plans": {truth: plan.to_trace_payload() for truth, plan in plans.items()},
            "schema": "arc3.build-001.stage-07-false-rule-cell.v0.1",
        },
        hash_field="receipt_hash",
    )
    cell_root.mkdir(parents=True, exist_ok=False)
    receipt_path = cell_root / "receipt.json"
    atomic_write_json(receipt_path, record)
    receipt_valid = verify_object_hash(record, hash_field="receipt_hash") and (
        sha256_file(receipt_path) == sha256_bytes(canonical_json_bytes(record))
    )
    measurement = CellMeasurement(
        cell_id=cell.cell_id,
        completed=true_accepted and not false_accepted,
        score=float(true_accepted and not false_accepted),
        levels_completed=int(true_accepted and not false_accepted),
        actions=0,
        resets=0,
        wall_ns=wall_ns,
        cpu_ns=cpu_ns,
        retrodiction_wall_ns=wall_ns,
        retrodiction_cpu_ns=cpu_ns,
        peak_rss_bytes=peak,
        current_rss_bytes=cast(int, memory.get("current_rss_bytes") or 0),
        command_count=0,
        accepted_true_model_ids=(case.true_model.model_id,) if true_accepted else (),
        accepted_false_model_ids=(case.false_model.model_id,) if false_accepted else (),
        cache_hit_count=sum(int(plan.cache_hit) for plan in plans.values()),
        full_artifact_parity=(
            cell.mode is not RetrodictionMode.CACHED_INCREMENTAL or all(roundtrips.values())
        ),
        event_reuse_receipts_valid=(
            cell.mode is not RetrodictionMode.EVENT_TRIGGERED
            or all(not plan.cache_hit for plan in plans.values())
        ),
        trace_valid=receipt_valid,
        checkpoint_valid=all(roundtrips.values()),
        replay_valid=all(roundtrips.values()),
        artifact_receipts_valid=receipt_valid and all(roundtrips.values()),
        source_identity_valid=True,
        memory_measurement_valid=memory["passed"] is True,
    )
    return measurement, {
        "measurement": asdict(measurement),
        "memory": memory,
        "receipt_path": str(receipt_path.resolve()),
        "receipt_sha256": sha256_file(receipt_path),
    }


def _rss_bytes(sample: Mapping[str, object]) -> int:
    values = [
        value
        for key in ("peak_rss_bytes", "current_rss_bytes")
        if isinstance((value := sample.get(key)), int) and not isinstance(value, bool)
    ]
    return max(values, default=0)


def _memory_receipt(*samples: Mapping[str, object]) -> dict[str, object]:
    """Preserve current/peak RSS and fail closed when the host surface is unavailable."""

    current_values = [
        value
        for sample in samples
        if isinstance((value := sample.get("current_rss_bytes")), int)
        and not isinstance(value, bool)
        and value >= 0
    ]
    peak_values = [
        value
        for sample in samples
        if isinstance((value := sample.get("peak_rss_bytes")), int)
        and not isinstance(value, bool)
        and value >= 0
    ]
    sources = [
        value for sample in samples if isinstance((value := sample.get("measurement_source")), str)
    ]
    passed = bool(current_values and peak_values) and all(
        source != "unavailable" for source in sources
    )
    return {
        "current_rss_bytes": current_values[-1] if current_values else None,
        "peak_rss_bytes": max(peak_values) if peak_values else 0,
        "passed": passed,
        "samples": [dict(sample) for sample in samples],
        "sources": sources,
    }


def _trace_events(trace_root: Path, run_id: str) -> tuple[TraceEvent, ...]:
    journal = EventJournal(trace_root, run_id=run_id, fsync_on_flush=False)
    try:
        replay = ReplayEngine(journal)
        events = replay.verify_integrity(verify_blobs=True)
        replay.replay_frames()
        verify_event_chain(list(events))
        return events
    finally:
        journal.close()


def _trace_counts(events: Sequence[TraceEvent]) -> dict[str, int]:
    result: dict[str, int] = {}
    for event in events:
        result[event.event_type] = result.get(event.event_type, 0) + 1
    return result


def _profile_retrodiction(profile: Mapping[str, object]) -> tuple[int, int, int]:
    raw_phases = profile.get("phases")
    phases = raw_phases if isinstance(raw_phases, Mapping) else {}
    phase = phases.get("retrodiction")
    payload = phase if isinstance(phase, Mapping) else {}
    wall = payload.get("inclusive_wall_ns", 0)
    cpu = payload.get("inclusive_cpu_ns", 0)
    hits = payload.get("cache_hits", 0)
    return (
        wall if isinstance(wall, int) and not isinstance(wall, bool) else 0,
        cpu if isinstance(cpu, int) and not isinstance(cpu, bool) else 0,
        hits if isinstance(hits, int) and not isinstance(hits, bool) else 0,
    )


def _evaluation_artifact_projection(
    evaluation: RetrodictionEvaluation,
) -> dict[str, JSONValue]:
    value = normalize_json(asdict(evaluation.artifact))
    if not isinstance(value, dict):
        raise EvaluationError("retrodiction artifact projection is not an object")
    return value


def _retrodiction_receipt_metrics(
    profile: Mapping[str, object], events: Sequence[TraceEvent]
) -> dict[str, object]:
    phases = profile.get("phases")
    phase = phases.get("retrodiction") if isinstance(phases, Mapping) else None
    payload = phase if isinstance(phase, Mapping) else {}
    completions = tuple(
        event for event in events if event.event_type == "model.retrodiction_completed"
    )
    omitted: list[JSONValue] = []
    for event in completions:
        raw_omissions = event.payload.get("omissions")
        if isinstance(raw_omissions, list):
            omitted.extend(raw_omissions)
    rebuild_reasons = {"first-use", "non-prefix", "invalidated", "event-full-audit"}
    return {
        "cache_hits": payload.get("cache_hits", 0),
        "cache_misses": payload.get("cache_misses", 0),
        "cache_opportunity_misses": payload.get("cache_opportunity_misses", 0),
        "completion_count": len(completions),
        "eviction_count": sum(
            len(cast(list[object], raw))
            for event in completions
            if isinstance((raw := event.payload.get("evicted_cache_keys")), list)
        ),
        "omissions": omitted,
        "rebuild_count": sum(
            event.payload.get("reason") in rebuild_reasons for event in completions
        ),
        "suffix_transition_count": sum(
            value
            for event in completions
            if isinstance((value := event.payload.get("suffix_count")), int)
            and not isinstance(value, bool)
            and value >= 0
        ),
    }


def _prediction_alternative_matches(
    value: object,
    *,
    model_id: str,
    matched_prediction_ids: set[str],
) -> bool:
    if not isinstance(value, Mapping):
        return False
    raw_models = value.get("supporting_model_ids")
    raw_predictions = value.get("prediction_ids")
    if (
        not isinstance(raw_models, list)
        or not all(isinstance(item, str) for item in raw_models)
        or not isinstance(raw_predictions, list)
        or not all(isinstance(item, str) for item in raw_predictions)
    ):
        return False
    return model_id in cast(list[str], raw_models) and bool(
        set(cast(list[str], raw_predictions)) & matched_prediction_ids
    )


def _event_receipt_integrity(
    events: Sequence[TraceEvent], mode: RetrodictionMode
) -> tuple[bool, bool]:
    completions = tuple(
        event for event in events if event.event_type == "model.retrodiction_completed"
    )
    cached_parity = all(
        event.payload.get("result_complete") is True and event.payload.get("complete_scope") is True
        for event in completions
    )
    if mode is not RetrodictionMode.EVENT_TRIGGERED:
        no_foreign_authority = all(
            event.payload.get("authorizing_matched_prediction_evidence") == []
            for event in events
            if event.event_type
            in {
                "model.retrodiction_started",
                "model.retrodiction_completed",
                "model.retrodiction_reused",
            }
        )
        return cached_parity, no_foreign_authority
    by_id = {event.event_id: event for event in events}
    event_order = {event.event_id: index for index, event in enumerate(events)}
    assessment_events = tuple(
        event
        for event in events
        if event.event_type
        in {"consequence.matched_prediction", "consequence.mismatched_prediction"}
        and isinstance(event.payload.get("receipt_id"), str)
    )
    assessments = {cast(str, event.payload["receipt_id"]): event for event in assessment_events}
    if len(assessments) != len(assessment_events):
        return cached_parity, False
    authorization_keys = {
        "assessment_receipt_id",
        "consequence_event_id",
        "match_scope",
        "matched",
        "model_id",
        "prediction_event_id",
        "prediction_receipt_id",
        "source_ordered",
        "transition_id",
    }
    plan_link_keys = (
        "authorizing_matched_prediction_evidence",
        "cache_hit",
        "cache_key",
        "complete_scope",
        "full_eligible_history_count",
        "full_eligible_history_hash",
        "generation",
        "mechanics_epoch_id",
        "mode",
        "model_id",
        "model_semantic_fingerprint",
        "prefix_count",
        "prior_artifact_id",
        "prior_source_receipt_event_id",
        "reason",
        "retrodiction_configuration_hash",
        "selected_history_count",
        "selected_history_hash",
        "selected_transition_ids",
        "suffix_count",
    )
    reuse_valid = True
    referenced_started_ids: set[str] = set()
    referenced_reused_ids: set[str] = set()
    for event in completions:
        started_id = event.payload.get("retrodiction_started_event_id")
        started = by_id.get(started_id) if isinstance(started_id, str) else None
        if (
            started is None
            or started.event_type != "model.retrodiction_started"
            or event_order[started.event_id] >= event_order[event.event_id]
            or any(started.payload.get(key) != event.payload.get(key) for key in plan_link_keys)
        ):
            reuse_valid = False
            continue
        referenced_started_ids.add(started.event_id)
        raw_authority = event.payload.get("authorizing_matched_prediction_evidence")
        if not isinstance(raw_authority, list) or not all(
            isinstance(item, Mapping) for item in raw_authority
        ):
            reuse_valid = False
            continue
        reused_id = event.payload.get("retrodiction_reused_event_id")
        reused_flag = event.payload.get("reused")
        reused = by_id.get(reused_id) if isinstance(reused_id, str) else None
        if reused_flag is True:
            if (
                reused is None
                or reused.event_type != "model.retrodiction_reused"
                or reused.payload.get("retrodiction_started_event_id") != started.event_id
                or any(reused.payload.get(key) != event.payload.get(key) for key in plan_link_keys)
                or not (
                    event_order[started.event_id]
                    < event_order[reused.event_id]
                    < event_order[event.event_id]
                )
            ):
                reuse_valid = False
            else:
                referenced_reused_ids.add(reused.event_id)
        elif reused_flag is not False or reused_id is not None:
            reuse_valid = False
        if event.payload.get("reason") != "event-receipt-reuse":
            reuse_valid = reuse_valid and not raw_authority
            continue
        if reused_flag is not True:
            reuse_valid = False
        suffix_count = event.payload.get("suffix_count")
        prefix_count = event.payload.get("prefix_count")
        selected_transition_ids = event.payload.get("selected_transition_ids")
        if (
            isinstance(suffix_count, bool)
            or not isinstance(suffix_count, int)
            or suffix_count <= 0
            or isinstance(prefix_count, bool)
            or not isinstance(prefix_count, int)
            or not isinstance(selected_transition_ids, list)
            or not all(isinstance(item, str) for item in selected_transition_ids)
            or not 0 <= prefix_count < len(selected_transition_ids)
            or len(raw_authority) != suffix_count
            or [
                item.get("transition_id")
                for item in cast(list[Mapping[str, object]], raw_authority)
            ]
            != cast(list[str], selected_transition_ids)[prefix_count:]
            or suffix_count != len(selected_transition_ids) - prefix_count
        ):
            reuse_valid = False
            continue
        model_id = event.payload.get("model_id")
        for item in cast(list[Mapping[str, object]], raw_authority):
            prediction_id = item.get("prediction_event_id")
            consequence_id = item.get("consequence_event_id")
            assessment_id = item.get("assessment_receipt_id")
            prediction = by_id.get(prediction_id) if isinstance(prediction_id, str) else None
            consequence = by_id.get(consequence_id) if isinstance(consequence_id, str) else None
            assessment = assessments.get(assessment_id) if isinstance(assessment_id, str) else None
            alternatives = (
                prediction.payload.get("alternatives") if prediction is not None else None
            )
            matched_prediction_ids = (
                assessment.payload.get("matched_prediction_ids") if assessment is not None else None
            )
            controlled_model_ids = (
                assessment.payload.get("controlled_projection_match_model_ids")
                if assessment is not None
                else None
            )
            model_prediction_matched = (
                isinstance(model_id, str)
                and isinstance(alternatives, list)
                and isinstance(matched_prediction_ids, list)
                and all(isinstance(value, str) for value in matched_prediction_ids)
                and any(
                    _prediction_alternative_matches(
                        alternative,
                        model_id=model_id,
                        matched_prediction_ids=set(cast(list[str], matched_prediction_ids)),
                    )
                    for alternative in alternatives
                )
            ) or (
                isinstance(model_id, str)
                and isinstance(controlled_model_ids, list)
                and model_id in controlled_model_ids
            )
            selected = (
                by_id.get(cast(str, consequence.payload.get("selected_event_id")))
                if consequence is not None
                and isinstance(consequence.payload.get("selected_event_id"), str)
                else None
            )
            if (
                set(item) != authorization_keys
                or item.get("model_id") != model_id
                or item.get("matched") is not True
                or item.get("source_ordered") is not True
                or item.get("match_scope")
                not in {"whole-symbolic-state", "controlled-entity-projection"}
                or prediction is None
                or prediction.event_type != "simulation.prediction_emitted"
                or prediction.payload.get("receipt_id") != item.get("prediction_receipt_id")
                or consequence is None
                or consequence.event_type != "consequence.received"
                or assessment is None
                or assessment.event_type != "consequence.matched_prediction"
                or assessment.payload.get("prediction_receipt_id")
                != item.get("prediction_receipt_id")
                or assessment.payload.get("match_scope") != item.get("match_scope")
                or selected is None
                or selected.event_type != "action.selected"
                or selected.payload.get("decision_id")
                != prediction.payload.get("action_decision_id")
                or prediction.payload.get("action") != consequence.payload.get("action")
                or not model_prediction_matched
                or not (
                    event_order[prediction.event_id]
                    < event_order[consequence.event_id]
                    < event_order[assessment.event_id]
                    < event_order[started.event_id]
                )
            ):
                reuse_valid = False
        source_id = event.payload.get("prior_source_receipt_event_id")
        source = by_id.get(source_id) if isinstance(source_id, str) else None
        if (
            source is None
            or source.event_type != "model.retrodiction_completed"
            or source.payload.get("artifact_id") != event.payload.get("prior_artifact_id")
            or source.payload.get("model_id") != model_id
            or event_order[source.event_id] >= event_order[started.event_id]
        ):
            reuse_valid = False
    started_ids = {
        event.event_id for event in events if event.event_type == "model.retrodiction_started"
    }
    reused_ids = {
        event.event_id for event in events if event.event_type == "model.retrodiction_reused"
    }
    reuse_valid = (
        reuse_valid
        and referenced_started_ids == started_ids
        and referenced_reused_ids == reused_ids
    )
    return cached_parity, reuse_valid


def _artifact_receipt_integrity(events: Sequence[TraceEvent]) -> bool:
    """Require every new completion receipt to carry its exact typed artifact projection."""

    completions = tuple(
        event for event in events if event.event_type == "model.retrodiction_completed"
    )
    for event in completions:
        projection = event.payload.get("artifact_projection")
        if not isinstance(projection, Mapping):
            return False
        score = projection.get("score")
        if not isinstance(score, Mapping):
            return False
        expected = {
            "artifact_id": projection.get("artifact_id"),
            "compatible_transition_ids": projection.get("compatible_transition_ids"),
            "complete": projection.get("complete"),
            "contradiction_transition_ids": projection.get("contradiction_transition_ids"),
            "explicitly_excluded_transition_ids": projection.get(
                "explicitly_excluded_transition_ids"
            ),
            "matched_transition_ids": projection.get("matched_transition_ids"),
            "model_id": projection.get("model_id"),
            "result_complete": projection.get("complete"),
            "score": score.get("total"),
            "status": projection.get("status"),
            "tested_transition_ids": projection.get("tested_transition_ids"),
            "weight_kind": score.get("weight_kind"),
        }
        if any(event.payload.get(key) != value for key, value in expected.items()):
            return False
    return True


def _artifact_projection(events: Sequence[TraceEvent]) -> tuple[dict[str, JSONValue], ...]:
    """Project immutable completion receipts for exact paired artifact comparison."""

    projected: list[dict[str, JSONValue]] = []
    for event in events:
        if event.event_type != "model.retrodiction_completed":
            continue
        projected.append(
            {
                "artifact_id": event.payload.get("artifact_id"),
                "compatible_transition_ids": event.payload.get("compatible_transition_ids", []),
                "contradiction_transition_ids": event.payload.get(
                    "contradiction_transition_ids", []
                ),
                "explicitly_excluded_transition_ids": event.payload.get(
                    "explicitly_excluded_transition_ids", []
                ),
                "full_eligible_history_hash": event.payload.get("full_eligible_history_hash"),
                "matched_transition_ids": event.payload.get("matched_transition_ids", []),
                "mechanics_epoch_id": event.payload.get("mechanics_epoch_id"),
                "model_id": event.payload.get("model_id"),
                "model_semantic_fingerprint": event.payload.get("model_semantic_fingerprint"),
                "status": event.payload.get("status"),
                "tested_transition_ids": event.payload.get("tested_transition_ids", []),
            }
        )
    return tuple(projected)


def _checkpoint_restore(
    controller: ARC3Controller,
    context: RunContext,
    *,
    features: PresetFeatures,
    config: RetrodictionConfig,
) -> tuple[str | None, bool]:
    """Write one terminal checkpoint and prove exact typed restore before sealing."""

    before = controller.snapshot
    controller.close()
    auditor = EventJournal(context.trace_root, run_id=context.run_id, fsync_on_flush=False)
    try:
        events = ReplayEngine(auditor).verify_integrity(verify_blobs=True)
    finally:
        auditor.close()
    if not events or events[-1].event_type != "run.checkpoint_written":
        raise EvaluationError("closed controller did not leave an authoritative checkpoint receipt")
    checkpoint_hash = events[-1].payload.get("checkpoint_hash")
    if not isinstance(checkpoint_hash, str) or not checkpoint_hash.startswith("sha256:"):
        raise EvaluationError("authoritative checkpoint receipt has no exact checkpoint hash")
    checkpoint_path = (
        context.checkpoint_root / f"checkpoint-{checkpoint_hash.removeprefix('sha256:')}.json"
    ).resolve()
    if not checkpoint_path.is_file():
        raise EvaluationError("authoritative content-addressed checkpoint is missing")
    restored = ARC3Controller.restore(
        context,
        preset=ControllerPreset.FULL,
        checkpoint_path=checkpoint_path,
        features=features,
        retrodiction_config=config,
    )
    try:
        after = restored.snapshot
        passed = (
            after.trace_events == before.trace_events + 2
            and replace(after, trace_events=before.trace_events) == before
        )
    finally:
        restored.close()
    return str(checkpoint_path), passed


def _restore_closed_checkpoint(
    context: RunContext,
    *,
    features: PresetFeatures,
    config: RetrodictionConfig,
) -> tuple[str, bool]:
    """Restore a terminal checkpoint emitted by an already-closed reused harness run."""

    events = _trace_events(context.trace_root, context.run_id)
    if not events or events[-1].event_type != "run.checkpoint_written":
        raise EvaluationError("closed reused run has no authoritative terminal checkpoint")
    checkpoint_hash = events[-1].payload.get("checkpoint_hash")
    if not isinstance(checkpoint_hash, str) or not checkpoint_hash.startswith("sha256:"):
        raise EvaluationError("closed reused run checkpoint receipt has no exact hash")
    checkpoint_path = (
        context.checkpoint_root / f"checkpoint-{checkpoint_hash.removeprefix('sha256:')}.json"
    ).resolve()
    if not checkpoint_path.is_file():
        raise EvaluationError("closed reused run content-addressed checkpoint is missing")
    restored = ARC3Controller.restore(
        context,
        preset=ControllerPreset.FULL,
        checkpoint_path=checkpoint_path,
        features=features,
        retrodiction_config=config,
    )
    try:
        restored_snapshot = restored.snapshot
        passed = restored_snapshot.trace_events == len(events)
    finally:
        restored.close()
    _trace_events(context.trace_root, context.run_id)
    return str(checkpoint_path), passed


class _TerminalCheckpointController(ARC3Controller):
    """Emit one truthful terminal checkpoint without enabling per-action persistence."""

    def close(self) -> None:
        if self._journal is None or self._phase is ControllerPhase.CLOSED:
            return
        if self._phase is not ControllerPhase.AWAITING_CONSEQUENCE:
            events = self.journal.verify_manifest()
            last_material_event = next(
                (
                    event
                    for event in reversed(events)
                    if event.event_type != "run.checkpoint_written"
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
        tail = self.journal.tail_event
        checkpoint_is_current = (
            self._last_checkpoint is not None
            and tail is not None
            and tail.event_type == "run.checkpoint_written"
            and tail.payload.get("checkpoint_hash")
            == self._last_checkpoint.envelope.checkpoint_hash
        )
        if not checkpoint_is_current:
            self._last_checkpoint = self.checkpoint()
        self.journal.close()
        self._phase = ControllerPhase.CLOSED


def _episode_measurement(
    *,
    cell: EvaluationCell,
    completed: bool,
    score: float,
    levels_completed: int,
    final_state: str,
    actions: int,
    resets: int,
    wall_ns: int,
    cpu_ns: int,
    memory: Mapping[str, object],
    profile: Mapping[str, object],
    events: Sequence[TraceEvent],
    checkpoint_path: str | None,
    checkpoint_valid: bool,
    controller_fault_count: int,
    invalid_request_count: int,
    trace_root: Path,
) -> tuple[CellMeasurement, dict[str, object]]:
    counts = _trace_counts(events)
    retrodiction_wall, retrodiction_cpu, cache_hits = _profile_retrodiction(profile)
    peak_rss = memory.get("peak_rss_bytes")
    if not isinstance(peak_rss, int) or isinstance(peak_rss, bool) or peak_rss < 0:
        peak_rss = 0
    current_rss = memory.get("current_rss_bytes")
    if not isinstance(current_rss, int) or isinstance(current_rss, bool) or current_rss < 0:
        current_rss = 0
    parity, reuse_valid = _event_receipt_integrity(events, cell.mode)
    artifact_receipts_valid = _artifact_receipt_integrity(events) and checkpoint_valid
    planning_failures = sum(
        event.event_type == "simulation.plan_evaluated" and event.payload.get("status") != "found"
        for event in events
    )
    prediction_mismatches = counts.get("consequence.mismatched_prediction", 0)
    measurement = CellMeasurement(
        cell_id=cell.cell_id,
        completed=completed,
        score=score,
        levels_completed=levels_completed,
        actions=actions,
        resets=resets,
        wall_ns=wall_ns,
        cpu_ns=cpu_ns,
        retrodiction_wall_ns=retrodiction_wall,
        retrodiction_cpu_ns=retrodiction_cpu,
        peak_rss_bytes=peak_rss,
        current_rss_bytes=current_rss,
        command_count=counts.get("action.submitted", 0),
        planning_failures=planning_failures,
        prediction_mismatches=prediction_mismatches,
        cache_hit_count=cache_hits,
        full_artifact_parity=parity,
        event_reuse_receipts_valid=reuse_valid,
        trace_valid=True,
        checkpoint_valid=checkpoint_valid,
        replay_valid=True,
        artifact_receipts_valid=artifact_receipts_valid,
        source_identity_valid=True,
        memory_measurement_valid=memory.get("passed") is True,
        controller_fault_count=controller_fault_count,
        invalid_request_count=invalid_request_count,
    )
    trace_inventory = _work_inventory(trace_root)
    checkpoint_inventory: tuple[dict[str, JSONValue], ...] = ()
    if checkpoint_path is not None:
        checkpoint = Path(checkpoint_path)
        if checkpoint.is_file():
            checkpoint_inventory = _work_inventory(checkpoint.parent)
    return measurement, {
        "artifact_projection": list(_artifact_projection(events)),
        "artifact_receipts_verified": artifact_receipts_valid,
        "checkpoint_path": checkpoint_path,
        "checkpoint_bytes": sum(cast(int, item["bytes"]) for item in checkpoint_inventory),
        "checkpoint_inventory_hash": sha256_json(list(checkpoint_inventory)),
        "event_type_counts": counts,
        "final_state": final_state,
        "hot_path_profile": dict(profile),
        "memory": dict(memory),
        "measurement": asdict(measurement),
        "retrodiction_receipt_metrics": _retrodiction_receipt_metrics(profile, events),
        "trace_bytes": sum(cast(int, item["bytes"]) for item in trace_inventory),
        "trace_event_count": len(events),
        "trace_inventory_hash": sha256_json(list(trace_inventory)),
        "trace_root": str(trace_root.resolve()),
        "trace_tail_hash": events[-1].event_hash if events else None,
    }


def _run_stage14_cell(
    cell: EvaluationCell,
    *,
    cell_root: Path,
    git_commit: str,
) -> tuple[CellMeasurement, dict[str, object]]:
    protocol, _ablations, _manifest_hash = stage14_runner.load_protocol_manifest()
    cases = stage14_runner._cases(protocol)
    case = cases[cell.group_case_ordinal]
    if case.case_key != cell.case_id or case.seed != cell.seed:
        raise EvaluationError("Stage 14 runtime case disagrees with frozen Stage 07 cell")
    session = stage14_runner._open_case(case, protocol)
    context = stage14_runner._context(
        cell_root,
        case=case,
        ordinal=cell.group_case_ordinal,
        variant=f"stage07-{cell.mode.value}",
        protocol=protocol,
        git_commit=git_commit,
    )
    features = _features_for_mode(cell.mode)
    config = _retrodiction_config(cell.mode)
    profiler = HotPathProfiler()
    controller = ARC3Controller(
        ControllerPreset.FULL,
        features=features,
        hot_path_profiler=profiler,
        retrodiction_config=config,
    )
    fault_count = 0
    invalid_count = 0
    before_rss = process_memory_sample()
    wall_started = time.perf_counter_ns()
    cpu_started = time.process_time_ns()
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
        try:
            decision = controller.choose_action()
        except PolicyError:
            fault_count += 1
            break
        try:
            consequence = session.step(decision.action)
        except Exception:
            invalid_count += 1
            raise
        try:
            controller.apply_consequence(consequence)
        except PolicyError:
            fault_count += 1
            break
    snapshot = controller.snapshot
    checkpoint_path: str | None = None
    checkpoint_valid = False
    try:
        checkpoint_path, checkpoint_valid = _checkpoint_restore(
            controller,
            context,
            features=features,
            config=config,
        )
    except (OSError, PolicyError, ValueError):
        controller.close()
    scorecard = session.close()
    wall_ns = max(0, time.perf_counter_ns() - wall_started)
    cpu_ns = max(0, time.process_time_ns() - cpu_started)
    if scorecard is None or len(scorecard.runs) != 1:
        raise EvaluationError("Stage 14 session returned no exact one-run scorecard")
    run = scorecard.runs[0]
    events = _trace_events(context.trace_root, context.run_id)
    profile = profiler.summary(total_wall_ns=wall_ns)
    after_rss = process_memory_sample()
    memory = _memory_receipt(before_rss, after_rss)
    return _episode_measurement(
        cell=cell,
        completed=run.completed,
        score=run.score,
        levels_completed=run.levels_completed,
        final_state=run.state.value,
        actions=snapshot.actions_used,
        resets=snapshot.resets_used,
        wall_ns=wall_ns,
        cpu_ns=cpu_ns,
        memory=memory,
        profile=profile,
        events=events,
        checkpoint_path=checkpoint_path,
        checkpoint_valid=checkpoint_valid,
        controller_fault_count=fault_count + snapshot.fault_count,
        invalid_request_count=invalid_count,
        trace_root=context.trace_root,
    )


_stage06_module: Any | None = None


def _load_stage06_module() -> Any:
    global _stage06_module
    if _stage06_module is not None:
        return _stage06_module
    specification = importlib.util.spec_from_file_location(
        "arc3_stage06_measurement_reuse", _STAGE06_SCRIPT
    )
    if specification is None or specification.loader is None:
        raise EvaluationError("Stage 06 measurement harness cannot be loaded")
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    try:
        specification.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(specification.name, None)
        raise
    _stage06_module = module
    return module


def _run_stage06_cell(
    cell: EvaluationCell,
    *,
    cell_root: Path,
    git_commit: str,
) -> tuple[CellMeasurement, dict[str, object]]:
    case = selected_rule_change_cases()[cell.group_case_ordinal]
    if case.case_id != cell.case_id or case.seed != cell.seed:
        raise EvaluationError("Stage 06 runtime case disagrees with frozen Stage 07 cell")
    module = _load_stage06_module()
    profiler = HotPathProfiler()
    config = _retrodiction_config(cell.mode)

    def factory(
        preset: ControllerPreset | str = ControllerPreset.FULL,
        *,
        local_proposal_provider: object | None = None,
        features: PresetFeatures | None = None,
        hot_path_profiler: object | None = None,
        retrodiction_config: RetrodictionConfig | None = None,
    ) -> ARC3Controller:
        del local_proposal_provider, hot_path_profiler, retrodiction_config
        return _TerminalCheckpointController(
            preset,
            features=_features_for_mode(cell.mode, features),
            hot_path_profiler=profiler,
            retrodiction_config=config,
        )

    with patch.object(module, "ARC3Controller", factory):
        result = cast(
            dict[str, object],
            module._run_case(case, root=cell_root, git_commit=git_commit),
        )
    trace = result.get("trace")
    trace_payload = trace if isinstance(trace, Mapping) else {}
    trace_root_value = trace_payload.get("trace_root")
    if not isinstance(trace_root_value, str):
        raise EvaluationError("Stage 06 reused run did not return an exact trace root")
    trace_root = Path(trace_root_value)
    run_id = case.case_id.replace("_", "-")
    context = cast(
        RunContext,
        module._context(
            cell_root,
            run_id=run_id,
            seed=case.seed,
            git_commit=git_commit,
            checkpointing=False,
        ),
    )
    stage06_features = _features_for_mode(
        cell.mode,
        replace(preset_features(ControllerPreset.FULL), use_memory=False),
    )
    checkpoint_path, checkpoint_valid = _restore_closed_checkpoint(
        context,
        features=stage06_features,
        config=config,
    )
    events = _trace_events(trace_root, run_id)
    wall_ns = result.get("wall_ns")
    cpu_ns = result.get("cpu_ns")
    if not isinstance(wall_ns, int) or isinstance(wall_ns, bool):
        raise EvaluationError("Stage 06 reused wall receipt is malformed")
    if not isinstance(cpu_ns, int) or isinstance(cpu_ns, bool):
        raise EvaluationError("Stage 06 reused CPU receipt is malformed")
    profile = profiler.summary(total_wall_ns=wall_ns)
    lifecycle = result.get("lifecycle")
    lifecycle_payload = lifecycle if isinstance(lifecycle, Mapping) else {}
    lifecycle_predicates = lifecycle_payload.get("predicates")
    predicate_map = lifecycle_predicates if isinstance(lifecycle_predicates, Mapping) else {}
    projection = result.get("final_lifecycle_projection")
    projection_map = projection if isinstance(projection, Mapping) else {}
    raw_epochs = projection_map.get("epochs")
    epochs = raw_epochs if isinstance(raw_epochs, list) else []
    confirmed_false_epochs = sum(
        isinstance(epoch, Mapping)
        and isinstance(epoch.get("epoch_index"), int)
        and cast(int, epoch["epoch_index"]) > 0
        for epoch in epochs
    )
    score = result.get("score")
    actions = result.get("action_count")
    resets = result.get("reset_count")
    fault_count = result.get("controller_fault_count")
    rss = result.get("rss")
    rss_payload = rss if isinstance(rss, Mapping) else {}
    memory_before_raw = rss_payload.get("before")
    memory_after_raw = rss_payload.get("after")
    memory = _memory_receipt(
        memory_before_raw if isinstance(memory_before_raw, Mapping) else {},
        memory_after_raw if isinstance(memory_after_raw, Mapping) else {},
    )
    terminal = result.get("terminal_state")
    measurement, raw = _episode_measurement(
        cell=cell,
        completed=terminal == GameStateName.WIN.value,
        score=float(score)
        if isinstance(score, (int, float)) and not isinstance(score, bool)
        else 0.0,
        levels_completed=int(terminal == GameStateName.WIN.value),
        final_state=str(terminal),
        actions=actions if isinstance(actions, int) and not isinstance(actions, bool) else 0,
        resets=resets if isinstance(resets, int) and not isinstance(resets, bool) else 0,
        wall_ns=wall_ns,
        cpu_ns=cpu_ns,
        memory=memory,
        profile=profile,
        events=events,
        checkpoint_path=checkpoint_path,
        checkpoint_valid=checkpoint_valid,
        controller_fault_count=(
            fault_count if isinstance(fault_count, int) and not isinstance(fault_count, bool) else 0
        ),
        invalid_request_count=0,
        trace_root=trace_root,
    )
    prefix_immutability = trace_payload.get("prefix_immutability")
    prefix_immutability_payload = (
        prefix_immutability if isinstance(prefix_immutability, Mapping) else {}
    )
    measurement = replace(
        measurement,
        intervention_triggered=(
            result.get("trigger_step") is not None if cell.group_case_ordinal < 16 else False
        ),
        strict_stage06_lifecycle_passed=lifecycle_payload.get("passed") is True,
        raw_noise_resolved=(
            predicate_map.get("candidate_resolved_as_noise") is True
            if cell.group_case_ordinal >= 16
            else False
        ),
        confirmed_false_epochs=confirmed_false_epochs,
        trace_valid=(
            trace_payload.get("replay_verified") is True
            and prefix_immutability_payload.get("passed") is True
        ),
        replay_valid=trace_payload.get("replay_verified") is True,
    )
    raw["measurement"] = asdict(measurement)
    raw["stage06_result"] = result
    return measurement, raw


class _ControllerEvaluationPolicy:
    manages_trace = True

    def __init__(
        self,
        context: RunContext,
        *,
        mode: RetrodictionMode,
        profiler: HotPathProfiler,
    ) -> None:
        self.features = _features_for_mode(mode)
        self.config = _retrodiction_config(mode)
        self.controller = ARC3Controller(
            ControllerPreset.FULL,
            features=self.features,
            hot_path_profiler=profiler,
            retrodiction_config=self.config,
        )
        self.context = context
        self.started = False

    def select(self, observation: Observation) -> ActionRequest:
        if not self.started:
            self.controller.reset(self.context)
            self.controller.observe(observation)
            self.started = True
        return self.controller.choose_action().action

    def accept_consequence(self, observation: Observation) -> None:
        if not self.started:
            raise PolicyError("Stage 07 public consequence is out of order")
        self.controller.apply_consequence(observation)

    def close(self) -> None:
        self.controller.close()


def _development_context(cell: EvaluationCell, cell_root: Path, git_commit: str) -> RunContext:
    budgets = BudgetConfig(
        max_actions=80,
        max_resets=8,
        wall_clock_seconds=120.0,
        max_search_nodes=2_048,
    )
    config = ARC3Config.for_mode(
        EnvironmentMode.LOCAL,
        seed=cell.seed,
        network_enabled=False,
        profile=f"stage07-retrodiction-{cell.mode.value}",
        budgets=budgets,
    )
    return RunContext(
        run_id=cell.cell_id,
        episode_id=f"episode:{cell.cell_id}",
        game_id=GameId(cell.case_id),
        trace_root=cell_root / "trace",
        checkpoint_root=cell_root / "checkpoint",
        config=config,
        git_commit=git_commit,
        source_kind="arc3-stage07-local-public-development",
        source_version="0.1",
    )


def _run_public_cell(
    cell: EvaluationCell,
    *,
    cell_root: Path,
    git_commit: str,
    exposure_ledger: Path,
    environments_dir: Path,
    recordings_dir: Path,
) -> tuple[CellMeasurement, dict[str, object]]:
    if cell.case_id != "ar25-0c556536" or cell.partition != "development":
        raise EvaluationError("Stage 07 public selector rejected a non-development identity")
    manifest = PublicPartitionManifest.load(PUBLIC_PARTITION_PATH)
    selected = tuple(
        entry for entry in manifest.games("development") if entry.game_id == cell.case_id
    )
    if len(selected) != 1:
        raise EvaluationError("Stage 07 development identity is not uniquely selected")
    asset_before_open = _development_asset_receipt(
        local_asset_identity(environments_dir, selected[0])
    )
    if asset_before_open["passed"] is not True:
        raise EvaluationError("frozen Stage 07 development asset identity changed before open")
    PublicExposureLedger(exposure_ledger).append(
        "stage07.development_episode_started",
        {
            "assignment_hash": selected[0].assignment_hash,
            "case_id": cell.case_id,
            "cell_id": cell.cell_id,
            "game_id": cell.case_id,
            "mode": cell.mode.value,
            "partition": "development",
            "seed": cell.seed,
        },
    )
    context = _development_context(cell, cell_root, git_commit)
    profiler = HotPathProfiler()
    policy = _ControllerEvaluationPolicy(context, mode=cell.mode, profiler=profiler)
    adapter = ArcAGIAdapter(
        ARC3Config.for_mode(
            EnvironmentMode.LOCAL,
            seed=cell.seed,
            network_enabled=False,
        ),
        environments_dir=environments_dir,
        recordings_dir=recordings_dir / cell.cell_id,
        save_recording=True,
        include_frame_data=True,
        environ={},
    )
    before_rss = process_memory_sample()
    wall_started = time.perf_counter_ns()
    cpu_started = time.process_time_ns()
    session = adapter.open(cell.case_id, seed=cell.seed)
    if str(session.observation.game_id) != cell.case_id:
        raise EvaluationError("Stage 07 adapter returned the wrong development identity")
    asset_after_open = _development_asset_receipt(
        local_asset_identity(environments_dir, selected[0])
    )
    if asset_after_open["passed"] is not True or asset_after_open != asset_before_open:
        raise EvaluationError("frozen Stage 07 development asset identity changed during open")
    scorecard = None
    checkpoint_path: str | None = None
    checkpoint_valid = False
    fault_count = 0
    invalid_count = 0
    try:
        scorecard, metrics = run_public_episode(
            session,
            policy,
            max_actions=80,
            max_resets=8,
            hot_path_profiler=profiler,
        )
        try:
            checkpoint_path, checkpoint_valid = _checkpoint_restore(
                policy.controller,
                context,
                features=policy.features,
                config=policy.config,
            )
        except (OSError, PolicyError, ValueError):
            policy.close()
    except PolicyError:
        fault_count += 1
        raise
    except Exception:
        invalid_count += 1
        raise
    asset_after_episode = _development_asset_receipt(
        local_asset_identity(environments_dir, selected[0])
    )
    if asset_after_episode["passed"] is not True or asset_after_episode != asset_before_open:
        raise EvaluationError("frozen Stage 07 development asset identity changed during episode")
    wall_ns = max(0, time.perf_counter_ns() - wall_started)
    cpu_ns = max(0, time.process_time_ns() - cpu_started)
    if scorecard is None or len(scorecard.runs) != 1:
        raise EvaluationError("Stage 07 public development returned no exact scorecard")
    run = scorecard.runs[0]
    measured_actions = metrics.get("environment_actions")
    measured_resets = metrics.get("resets")
    if (
        isinstance(measured_actions, bool)
        or not isinstance(measured_actions, int)
        or isinstance(measured_resets, bool)
        or not isinstance(measured_resets, int)
    ):
        raise EvaluationError("Stage 07 public action accounting is malformed")
    events = _trace_events(context.trace_root, context.run_id)
    profile = profiler.summary(total_wall_ns=wall_ns)
    after_rss = process_memory_sample()
    memory = _memory_receipt(before_rss, after_rss)
    measurement, raw = _episode_measurement(
        cell=cell,
        completed=run.completed,
        score=run.score,
        levels_completed=run.levels_completed,
        final_state=run.state.value,
        actions=measured_actions,
        resets=measured_resets,
        wall_ns=wall_ns,
        cpu_ns=cpu_ns,
        memory=memory,
        profile=profile,
        events=events,
        checkpoint_path=checkpoint_path,
        checkpoint_valid=checkpoint_valid,
        controller_fault_count=fault_count,
        invalid_request_count=invalid_count,
        trace_root=context.trace_root,
    )
    raw["asset_identity"] = asset_before_open["observed"]
    raw["asset_identity_after_episode"] = asset_after_episode
    raw["asset_identity_after_open"] = asset_after_open
    raw["asset_identity_before_open"] = asset_before_open
    raw["asset_identity_stable"] = True
    raw["official_local_scorecard"] = normalize_json(asdict(scorecard))
    raw["public_metrics"] = metrics
    return measurement, raw


def _run_cell(
    cell: EvaluationCell,
    *,
    cell_root: Path,
    git_commit: str,
    false_cases: Mapping[str, FalseRuleCase],
    exposure_ledger: Path,
    environments_dir: Path,
    recordings_dir: Path,
) -> tuple[CellMeasurement, dict[str, object]]:
    if cell.group is EvaluationGroup.A_STAGE14:
        return _run_stage14_cell(cell, cell_root=cell_root, git_commit=git_commit)
    if cell.group is EvaluationGroup.B_FALSE_RULE:
        return _run_false_rule_cell(cell, false_cases[cell.case_id], cell_root)
    if cell.group is EvaluationGroup.C_RULE_CHANGE:
        return _run_stage06_cell(cell, cell_root=cell_root, git_commit=git_commit)
    return _run_public_cell(
        cell,
        cell_root=cell_root,
        git_commit=git_commit,
        exposure_ledger=exposure_ledger,
        environments_dir=environments_dir,
        recordings_dir=recordings_dir,
    )


def _failure_measurement(
    cell: EvaluationCell,
    error: BaseException,
    *,
    cell_root: Path,
) -> tuple[CellMeasurement, dict[str, object]]:
    failure = seal_object(
        {
            "cell": cell.to_dict(),
            "error_kind": type(error).__name__,
            "error_message": str(error),
            "schema": "arc3.build-001.stage-07-cell-failure.v0.1",
        },
        hash_field="failure_hash",
    )
    cell_root.mkdir(parents=True, exist_ok=True)
    path = cell_root / "failure.json"
    atomic_write_json(path, failure)
    measurement = CellMeasurement(
        cell_id=cell.cell_id,
        completed=False,
        score=0.0,
        levels_completed=0,
        actions=0,
        resets=0,
        wall_ns=0,
        cpu_ns=0,
        retrodiction_wall_ns=0,
        retrodiction_cpu_ns=0,
        peak_rss_bytes=0,
        trace_valid=False,
        checkpoint_valid=False,
        replay_valid=False,
        artifact_receipts_valid=False,
        source_identity_valid=False,
        memory_measurement_valid=False,
        controller_fault_count=int(isinstance(error, PolicyError)),
        invalid_request_count=int(not isinstance(error, PolicyError)),
    )
    return measurement, {
        "failure": failure,
        "failure_path": str(path.resolve()),
        "failure_sha256": sha256_file(path),
        "measurement": asdict(measurement),
    }


def _development_asset_matrix_integrity(
    cells: Sequence[EvaluationCell],
    raw_records: Mapping[str, Mapping[str, object]],
) -> dict[str, object]:
    """Require every frozen D cell to carry the same three exact asset snapshots."""

    development_cells = tuple(
        cell for cell in cells if cell.group is EvaluationGroup.D_LOCAL_PUBLIC
    )
    expected = _EXPECTED_DEVELOPMENT_ASSET_IDENTITY.to_dict()
    per_cell: dict[str, bool] = {}
    for cell in development_cells:
        record = raw_records.get(cell.cell_id)
        receipts = (
            tuple(
                record.get(key)
                for key in (
                    "asset_identity_before_open",
                    "asset_identity_after_open",
                    "asset_identity_after_episode",
                )
            )
            if isinstance(record, Mapping)
            else ()
        )
        per_cell[cell.cell_id] = bool(
            len(receipts) == 3
            and record is not None
            and record.get("asset_identity_stable") is True
            and all(
                isinstance(receipt, Mapping)
                and receipt.get("passed") is True
                and receipt.get("expected") == expected
                and receipt.get("observed") == expected
                for receipt in receipts
            )
        )
    predicates = {
        "exact_development_cell_count": len(development_cells) == 10,
        "exact_record_count": len(per_cell) == 10,
        "all_cell_snapshots_exact": len(per_cell) == 10 and all(per_cell.values()),
    }
    return {
        "expected": expected,
        "passed": all(predicates.values()),
        "per_cell": per_cell,
        "predicates": predicates,
    }


def _apply_global_integrity(
    cells: Sequence[EvaluationCell],
    measurements: Sequence[CellMeasurement],
    raw_records: Mapping[str, Mapping[str, object]],
    *,
    development_asset_integrity: Mapping[str, object] | None = None,
    source_valid: bool,
    holdout_exposure_count: int,
) -> tuple[CellMeasurement, ...]:
    by_pair_mode = {(cell.pair_key, cell.mode): cell for cell in cells}
    by_id = {item.cell_id: item for item in measurements}
    updated: list[CellMeasurement] = []
    raw_development_cells = (
        development_asset_integrity.get("per_cell", {})
        if isinstance(development_asset_integrity, Mapping)
        else {}
    )
    development_cells = raw_development_cells if isinstance(raw_development_cells, Mapping) else {}
    for cell in cells:
        item = by_id[cell.cell_id]
        parity = item.full_artifact_parity
        if cell.mode is RetrodictionMode.CACHED_INCREMENTAL:
            full_cell = by_pair_mode[(cell.pair_key, RetrodictionMode.FULL)]
            full_projection = raw_records.get(full_cell.cell_id, {}).get("artifact_projection")
            current_projection = raw_records.get(cell.cell_id, {}).get("artifact_projection")
            parity = (
                isinstance(full_projection, list)
                and bool(full_projection)
                and current_projection == full_projection
            )
        updated.append(
            replace(
                item,
                full_artifact_parity=parity,
                source_identity_valid=(
                    item.source_identity_valid
                    and source_valid
                    and (
                        cell.group is not EvaluationGroup.D_LOCAL_PUBLIC
                        or development_cells.get(cell.cell_id) is True
                    )
                ),
                holdout_exposure_count=holdout_exposure_count,
            )
        )
    return tuple(updated)


def _work_inventory(root: Path) -> tuple[dict[str, JSONValue], ...]:
    return tuple(
        {
            "bytes": path.stat().st_size,
            "path": path.relative_to(root).as_posix(),
            "sha256": sha256_file(path),
        }
        for path in sorted(root.rglob("*"))
        if path.is_file()
    )


def _package_version(name: str) -> str | None:
    try:
        from importlib.metadata import version

        return version(name)
    except Exception:
        return None


def _runtime_identity() -> dict[str, object]:
    return {
        "architecture": platform.machine(),
        "logical_cpu_count": os.cpu_count(),
        "packages": {
            name: _package_version(name)
            for name in ("arc-agi", "arcengine", "numpy", "psutil", "pytest", "ruff", "mypy")
        },
        "platform": platform.platform(),
        "python_executable": str(Path(sys.executable).resolve()),
        "python_version": platform.python_version(),
    }


def _verification_commands() -> tuple[tuple[str, ...], ...]:
    python = str(Path(sys.executable).resolve())
    return (
        (
            python,
            "-m",
            "pytest",
            "-q",
            "tests/unit/test_retrodiction_modes.py",
            "tests/property/test_retrodiction_modes_property.py",
            "tests/unit/test_retrodiction_decision.py",
            "tests/integration/test_retrodiction_decision_integration.py",
            "tests/integration/test_controller_retrodiction_modes.py",
            "tests/replay/test_retrodiction_checkpoint.py",
            "tests/replay/test_controller_checkpoint.py",
            "tests/competition/test_controller_offline_integrity.py",
            "tests/integrity/test_secret_scan.py",
            "--no-cov",
            "--basetemp",
            "C:/a/arc3-b001/pytest-stage07-official",
        ),
        (
            python,
            "-m",
            "ruff",
            "check",
            "src/arc3/evaluation/retrodiction_decision.py",
            "src/arc3/world_model/retrodiction.py",
            "src/arc3/policy/controller.py",
            "scripts/measure_retrodiction_decision.py",
            "tests/unit/test_retrodiction_decision.py",
            "tests/integration/test_retrodiction_decision_integration.py",
        ),
        (
            python,
            "-m",
            "ruff",
            "format",
            "--check",
            "src/arc3/evaluation/retrodiction_decision.py",
            "src/arc3/world_model/retrodiction.py",
            "src/arc3/policy/controller.py",
            "scripts/measure_retrodiction_decision.py",
            "tests/unit/test_retrodiction_decision.py",
            "tests/integration/test_retrodiction_decision_integration.py",
        ),
        (
            python,
            "-m",
            "mypy",
            "--strict",
            "src/arc3/evaluation/retrodiction_decision.py",
            "src/arc3/world_model/retrodiction.py",
            "src/arc3/policy/controller.py",
            "scripts/measure_retrodiction_decision.py",
        ),
        (
            python,
            "scripts/check_competition_integrity.py",
            "--run-state",
            "docs/ledger/build-001-run-state.json",
        ),
    )


def _run_verification_command(
    command: Sequence[str], root: Path, ordinal: int
) -> dict[str, object]:
    wall_started = time.perf_counter_ns()
    timed_out = False
    infrastructure_failure = False
    try:
        completed = subprocess.run(
            list(command),
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300.0,
        )
        returncode = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr
    except subprocess.TimeoutExpired as error:
        timed_out = True
        returncode = None
        stdout = str(error.stdout or "")
        stderr = str(error.stderr or "")
    except OSError as error:
        infrastructure_failure = True
        returncode = None
        stdout = ""
        stderr = f"{type(error).__name__}: {error}"
    receipt = seal_object(
        {
            "command": list(command),
            "infrastructure_failure": infrastructure_failure,
            "passed": returncode == 0 and not timed_out and not infrastructure_failure,
            "returncode": returncode,
            "schema": "arc3.build-001.stage-07-verification-command.v0.1",
            "stderr_sha256": sha256_bytes(stderr.encode("utf-8")),
            "stdout_sha256": sha256_bytes(stdout.encode("utf-8")),
            "timed_out": timed_out,
            "timeout_seconds": 300.0,
            "wall_ns": max(0, time.perf_counter_ns() - wall_started),
        },
        hash_field="receipt_hash",
    )
    path = root / f"verification-{ordinal:02d}.json"
    atomic_write_json(path, receipt)
    return {**receipt, "path": str(path.resolve()), "sha256": sha256_file(path)}


def _run_verification(root: Path) -> dict[str, object]:
    root.mkdir(parents=True, exist_ok=False)
    receipts = tuple(
        _run_verification_command(command, root, ordinal)
        for ordinal, command in enumerate(_verification_commands())
    )
    return {
        "command_count": len(receipts),
        "infrastructure_failure_count": sum(
            item["infrastructure_failure"] is True for item in receipts
        ),
        "passed": all(item["passed"] is True for item in receipts),
        "receipts": list(receipts),
        "timeout_count": sum(item["timed_out"] is True for item in receipts),
    }


def measure_retrodiction_decision(
    *,
    output: Path,
    work_root: Path,
    exposure_ledger: Path,
    environments_dir: Path,
    recordings_dir: Path,
    command: Sequence[str],
) -> dict[str, object]:
    """Run all 280 frozen cells and 60 microbenchmark cells exactly once."""

    _require_official_paths(
        output=output,
        work_root=work_root,
        exposure_ledger=exposure_ledger,
        environments_dir=environments_dir,
        recordings_dir=recordings_dir,
    )
    _require_fresh_targets(
        output,
        work_root,
        exposure_ledger=exposure_ledger,
        recordings_dir=recordings_dir,
    )
    contract = _require_composite_contract()
    source_start = _source_identity()
    if source_start.get("dirty_worktree") is not False:
        raise EvaluationError("official Stage 07 measurement requires a clean committed tree")
    if source_start.get("branch") != _EXPECTED_BRANCH:
        raise EvaluationError("official Stage 07 measurement requires the frozen Build 001 branch")
    if source_start.get("source_baseline_ancestor") is not True:
        raise EvaluationError(
            "official Stage 07 source does not descend from the frozen checkpoint"
        )
    git_commit = source_start.get("git_commit")
    if not isinstance(git_commit, str):
        raise EvaluationError("official Stage 07 measurement has no git commit identity")
    holdout_start = _holdout_integrity(exposure_ledger, environments_dir)
    if holdout_start.get("passed") is not True:
        raise EvaluationError("public holdout is not sealed before Stage 07 measurement")
    work_root.mkdir(parents=True, exist_ok=True)
    matrix = build_evaluation_matrix()
    false_cases = {item.case_id: item for item in build_false_rule_cases()}
    measurements: list[CellMeasurement] = []
    raw_records: dict[str, dict[str, object]] = {}
    failures: list[dict[str, object]] = []
    raw_micro: list[RawMicrobenchmark] = []
    before_rss = process_memory_sample()
    wall_started = time.perf_counter_ns()
    cpu_started = time.process_time_ns()
    wall_limit_ns = int(MAX_OVERALL_WALL_SECONDS * 1_000_000_000)
    wall_limit_recorded = False
    with _SocketDeny() as network_guard:
        for cell in matrix:
            if time.perf_counter_ns() - wall_started > wall_limit_ns:
                failures.append(
                    {
                        "cell_id": cell.cell_id,
                        "error_kind": "ResourceLimitExceeded",
                        "error_message": "Stage 07 overall 3600-second wall limit exceeded",
                    }
                )
                wall_limit_recorded = True
                break
            cell_root = work_root / "cells" / f"{cell.ordinal:03d}-{cell.cell_id[-16:]}"
            cell_before_rss = process_memory_sample()
            cell_wall_started = time.perf_counter_ns()
            cell_cpu_started = time.process_time_ns()
            network_attempts_before = network_guard.attempt_count
            try:
                measurement, record = _run_cell(
                    cell,
                    cell_root=cell_root,
                    git_commit=git_commit,
                    false_cases=false_cases,
                    exposure_ledger=exposure_ledger,
                    environments_dir=environments_dir,
                    recordings_dir=recordings_dir,
                )
            except Exception as error:
                measurement, record = _failure_measurement(cell, error, cell_root=cell_root)
                failures.append(
                    {
                        "cell_id": cell.cell_id,
                        "error_kind": type(error).__name__,
                        "error_message": str(error),
                    }
                )
            cell_wall_ns = max(0, time.perf_counter_ns() - cell_wall_started)
            cell_cpu_ns = max(0, time.process_time_ns() - cell_cpu_started)
            cell_memory = _memory_receipt(cell_before_rss, process_memory_sample())
            current_rss = cell_memory.get("current_rss_bytes")
            peak_rss = cell_memory.get("peak_rss_bytes")
            measurement = replace(
                measurement,
                wall_ns=cell_wall_ns,
                cpu_ns=cell_cpu_ns,
                current_rss_bytes=(
                    current_rss
                    if isinstance(current_rss, int) and not isinstance(current_rss, bool)
                    else 0
                ),
                peak_rss_bytes=(
                    peak_rss if isinstance(peak_rss, int) and not isinstance(peak_rss, bool) else 0
                ),
                memory_measurement_valid=(
                    measurement.memory_measurement_valid and cell_memory["passed"] is True
                ),
                network_attempt_count=(network_guard.attempt_count - network_attempts_before),
            )
            runner_measurement = record.get("measurement")
            record["memory"] = cell_memory
            record["measurement"] = asdict(measurement)
            record["orchestrator_resources"] = {
                "cpu_ns": cell_cpu_ns,
                "memory": cell_memory,
                "network_attempt_count": measurement.network_attempt_count,
                "wall_ns": cell_wall_ns,
            }
            record["runner_measurement"] = runner_measurement
            measurements.append(measurement)
            raw_records[cell.cell_id] = record
            if time.perf_counter_ns() - wall_started > wall_limit_ns:
                failures.append(
                    {
                        "cell_id": cell.cell_id,
                        "error_kind": "ResourceLimitExceeded",
                        "error_message": "Stage 07 overall 3600-second wall limit exceeded",
                    }
                )
                wall_limit_recorded = True
                break
        if len(measurements) == len(matrix) and not wall_limit_recorded:
            for mode, size, timing_path in product(MODE_ORDER, MICRO_HISTORY_SIZES, _TIMING_PATHS):
                if time.perf_counter_ns() - wall_started > wall_limit_ns:
                    failures.append(
                        {
                            "cell_id": f"micro:{mode.value}:{size}:{timing_path}",
                            "error_kind": "ResourceLimitExceeded",
                            "error_message": "Stage 07 overall 3600-second wall limit exceeded",
                        }
                    )
                    wall_limit_recorded = True
                    break
                raw_micro.append(measure_microbenchmark_cell(mode, size, timing_path))
    verification = _run_verification(work_root / "verification")
    source_end = _source_identity()
    source_stability = _source_stability(source_start, source_end)
    holdout_end = _holdout_integrity(exposure_ledger, environments_dir)
    development_asset_integrity = _development_asset_matrix_integrity(matrix, raw_records)
    measurements_final = _apply_global_integrity(
        matrix,
        measurements,
        raw_records,
        development_asset_integrity=development_asset_integrity,
        source_valid=source_stability["passed"] is True,
        holdout_exposure_count=cast(int, holdout_end["public_holdout_gameplay_events"]),
    )
    micro_measurements = tuple(item.measurement for item in raw_micro)
    gates: tuple[ModeGateResult, ...] = ()
    provisional_decision = "KEEP_FULL"
    if len(measurements_final) == len(matrix) and len(micro_measurements) == 60:
        gates = evaluate_replacement_gates(measurements_final, micro_measurements)
        provisional_decision = choose_retrodiction_decision(gates).value
    wall_ns = max(0, time.perf_counter_ns() - wall_started)
    cpu_ns = max(0, time.process_time_ns() - cpu_started)
    after_rss = process_memory_sample()
    memory = _memory_receipt(before_rss, after_rss)
    peak_rss = cast(int, memory["peak_rss_bytes"])
    inventory = _work_inventory(work_root)
    exact_execution = (
        len(measurements_final) == len(matrix) and len(micro_measurements) == 60 and not failures
    )
    integrity = (
        exact_execution
        and development_asset_integrity["passed"] is True
        and source_stability["passed"] is True
        and holdout_end["passed"] is True
        and network_guard.attempt_count == 0
        and memory["passed"] is True
        and peak_rss <= MAX_PEAK_RSS_BYTES
        and wall_ns <= int(MAX_OVERALL_WALL_SECONDS * 1_000_000_000)
        and verification["passed"] is True
        and all(item.hard_integrity_passed for item in measurements_final)
        and len(measurements_final) == len(matrix)
        and all(
            cell_budget_passed(cell, measurement)
            for cell, measurement in zip(matrix, measurements_final, strict=True)
        )
    )
    decision = provisional_decision if integrity else "KEEP_FULL"
    report = seal_object(
        {
            "commands": [list(command)],
            "completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "composite_contract": contract,
            "configuration": {
                "cache_capacity": 64,
                "evaluation_cells": 280,
                "execution": "serial",
                "hosted_inference": False,
                "microbenchmark_cells": 60,
                "microbenchmark_repetitions": MICRO_REPETITIONS,
                "microbenchmark_warmups": MICRO_WARMUPS,
                "mode_order": [mode.value for mode in MODE_ORDER],
                "network_enabled": False,
                "overall_wall_seconds": MAX_OVERALL_WALL_SECONDS,
                "peak_rss_limit_bytes": MAX_PEAK_RSS_BYTES,
            },
            "decision": decision,
            "development_asset_integrity": development_asset_integrity,
            "provisional_decision": provisional_decision,
            "evidence_labels": ["synthetic", "local-public"],
            "failures": failures,
            "holdout_end": holdout_end,
            "holdout_start": holdout_start,
            "matrix": [item.to_dict() for item in matrix],
            "matrix_hash": sha256_json([item.to_dict() for item in matrix]),
            "measurements": [asdict(item) for item in measurements_final],
            "microbenchmarks": [item.to_dict() for item in raw_micro],
            "mode_gates": [item.to_dict() for item in gates],
            "network_deny_guard": {
                "attempt_count": network_guard.attempt_count,
                "passed": network_guard.attempt_count == 0,
            },
            "raw_cell_records": raw_records,
            "resources": {
                "cpu_ns": cpu_ns,
                "memory_measurement": memory,
                "peak_rss_bytes": peak_rss,
                "peak_rss_within_limit": peak_rss <= MAX_PEAK_RSS_BYTES,
                "wall_ns": wall_ns,
                "wall_within_limit": wall_ns <= int(MAX_OVERALL_WALL_SECONDS * 1_000_000_000),
            },
            "runtime_identity": _runtime_identity(),
            "schema": "arc3.build-001.stage-07-retrodiction-decision.v0.1",
            "source_identity_end": source_end,
            "source_identity_stability": source_stability,
            "source_identity_start": source_start,
            "status": "PASS" if integrity else "PARTIAL",
            "verification": verification,
            "work_inventory": list(inventory),
            "work_inventory_hash": sha256_json(list(inventory)),
            "work_root": str(work_root.resolve()),
        },
        hash_field="artifact_core_hash",
    )
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--work-root", type=Path, default=DEFAULT_WORK_ROOT)
    parser.add_argument("--exposure-ledger", type=Path, default=DEFAULT_EXPOSURE_LEDGER)
    parser.add_argument("--environments-dir", type=Path, default=DEFAULT_ENVIRONMENTS_DIR)
    parser.add_argument("--recordings-dir", type=Path, default=DEFAULT_RECORDINGS_DIR)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--materialize-manifest", action="store_true")
    return parser


def _materialize_manifest() -> dict[str, object]:
    if FALSE_RULE_MANIFEST_PATH.exists():
        loaded = json.loads(FALSE_RULE_MANIFEST_PATH.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict) or not all(
            validate_false_rule_manifest(cast(dict[str, object], loaded)).values()
        ):
            raise EvaluationError("existing false-rule manifest differs from the frozen build")
        return cast(dict[str, object], loaded)
    manifest = build_false_rule_manifest()
    atomic_write_json(FALSE_RULE_MANIFEST_PATH, manifest)
    return manifest


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    if args.materialize_manifest:
        manifest = _materialize_manifest()
        sys.stdout.buffer.write(canonical_json_bytes(manifest))
        return 0
    contract = _require_composite_contract()
    if not args.execute:
        sys.stdout.buffer.write(
            canonical_json_bytes(
                {
                    "composite_contract": contract,
                    "execution_started": False,
                    "matrix_cells": len(build_evaluation_matrix()),
                    "schema": "arc3.build-001.stage-07-validation.v0.1",
                    "status": "READY_NOT_EXECUTED",
                }
            )
        )
        return 0
    command = (
        str(Path(sys.executable).resolve()),
        str(Path(__file__).resolve()),
        "--execute",
        "--output",
        str(args.output.resolve()),
        "--work-root",
        str(args.work_root.resolve()),
        "--exposure-ledger",
        str(args.exposure_ledger.resolve()),
        "--environments-dir",
        str(args.environments_dir.resolve()),
        "--recordings-dir",
        str(args.recordings_dir.resolve()),
    )
    report = measure_retrodiction_decision(
        output=args.output,
        work_root=args.work_root,
        exposure_ledger=args.exposure_ledger,
        environments_dir=args.environments_dir,
        recordings_dir=args.recordings_dir,
        command=command,
    )
    atomic_write_json(args.output, report)
    sys.stdout.buffer.write(
        canonical_json_bytes(
            {
                "artifact_core_hash": report["artifact_core_hash"],
                "decision": report["decision"],
                "output": str(args.output.resolve()),
                "status": report["status"],
            }
        )
    )
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
