#!/usr/bin/env python3
"""Measure the frozen Build 001 Stage 06 mechanics-reopening contract."""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import statistics
import subprocess
import sys
import time
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from itertools import pairwise
from pathlib import Path
from tempfile import gettempdir
from typing import cast
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from arc3.adapters import Observation  # noqa: E402
from arc3.config import ARC3Config, BudgetConfig  # noqa: E402
from arc3.evaluation.artifacts import atomic_write_json, seal_object  # noqa: E402
from arc3.integrity.hashes import (  # noqa: E402
    canonical_json_bytes,
    sha256_bytes,
    sha256_file,
)
from arc3.integrity.scanner import build_integrity_receipt  # noqa: E402
from arc3.lab.rule_change import (  # noqa: E402
    RULE_CHANGE_ACTIONS,
    RULE_CHANGE_GAME_ID,
    RULE_CHANGE_SEEDS,
    ActionVariant,
    CheckpointBoundary,
    PaletteVariant,
    RuleChangeCase,
    RuleChangeCaseKind,
    RuleChangeCheckpointCase,
    RuleChangeEvaluatorEpisode,
    RuleChangeFamily,
    RuleChangeTiming,
    checkpoint_schedule,
    intervention_schedule,
    noise_control_schedule,
    open_rule_change_case,
)
from arc3.memory import CHECKPOINT_COMMITMENT_SCHEMA  # noqa: E402
from arc3.policy import (  # noqa: E402
    ActionDecision,
    ARC3Controller,
    ControllerPhase,
    ControllerPreset,
    PresetFeatures,
    RunContext,
    preset_features,
)
from arc3.profiling.runtime import process_memory_sample  # noqa: E402
from arc3.trace import (  # noqa: E402
    CHECKPOINT_SCHEMA,
    EventJournal,
    ReplayEngine,
    compute_frame_delta,
)
from arc3.trace.canonical import canonical_bytes as trace_canonical_bytes  # noqa: E402
from arc3.trace.canonical import sha256_bytes as trace_sha256_bytes  # noqa: E402
from arc3.trace.canonical import sha256_json  # noqa: E402
from arc3.trace.schema import TraceEvent  # noqa: E402
from arc3.types import ActionName, ActionRequest, JSONValue  # noqa: E402
from scripts.check_action_semantics import build_action_semantics_receipt  # noqa: E402

PREDECLARATION = ROOT / "docs/evidence/001-06-rule-change-predeclaration.json"
PREDECLARATION_SHA256 = "sha256:0bca5f32986c79008cf6ee01a83867262cda591f477239a5b8e9bccd90e37434"
STAGE05_ACCEPTANCE_COMMIT = "916c801"
PUBLIC_PARTITION_MANIFEST_SHA256 = (
    "sha256:682d5891c2aface54803d9bd1173c55ed21e89856e13b8a478fb9276ee963f2f"
)
STAGE05_EVIDENCE_PATH = Path("docs/evidence/001-05-action-equivariance.json")
STAGE05_EVIDENCE_BLOB_OID = "b25078fe3ae2cbc57db2d367b0f7424bbde63195"
STAGE05_EVIDENCE_SHA256 = "sha256:7d9a72d9e222944a60cf92cb2b3bd5db2e33f46d5a64be4d22f91df224adf85a"
DEFAULT_OUTPUT = Path("C:/a/arc3-b001/artifacts/stage06/rule-change-reopening.json")
DEFAULT_WORK_ROOT = Path("C:/a/arc3-b001/artifacts/stage06/rule-change-reopening-work")
MAX_ACTIONS = 48
MAX_RESETS = 2
MAX_TRIGGER_ACTION = 24
MAX_CONFIRMATION_ACTIONS = 4
MAX_POST_TRIGGER_ACTIONS = 16
MAX_WALL_SECONDS_PER_EXECUTION = 60.0
MAX_WALL_SECONDS_FULL = 900.0
MAX_PEAK_RSS_BYTES = 1024 * 1024 * 1024
MAX_TRACE_BYTES = 64 * 1024 * 1024
MAX_CHECKPOINT_BYTES = 64 * 1024 * 1024
MAX_SEARCH_NODES = 2_048
MAX_SEARCH_DEPTH = 32
MAX_COORDINATE_CANDIDATES = 24

_FALSE_POSITIVE_EVENTS = frozenset(
    {
        "mechanics.change_confirmed",
        "mechanics.epoch_opened",
        "model.rule_demoted",
        "hypothesis.reopened",
    }
)
_INFRASTRUCTURE_FAILURE_KINDS = frozenset(
    {
        "FAILED_INFRASTRUCTURE",
        "FileNotFoundError",
        "OSError",
        "PermissionError",
    }
)
_ORDERED_LIFECYCLE = (
    "consequence.received",
    "observation.normalized",
    "hypothesis.contradicted",
    "mechanics.change_candidate_created",
    "model.rule_demoted",
    "hypothesis.reopened",
    "mechanics.change_confirmed",
    "mechanics.epoch_opened",
    "action.selected:reexploration",
    "hypothesis.supported:successor",
    "model.rule_promoted:successor",
    "consequence.matched_prediction:successor",
)
_CHECKPOINT_COMMITMENT_FIELDS = frozenset(
    {
        "checkpoint_hash",
        "checkpoint_schema",
        "checkpoint_sequence",
        "commitment_schema",
        "config_hash",
        "controller_phase",
        "derived_controller_schema",
        "derived_controller_state_hash",
        "envelope_prior_trace_tail_event_id",
        "envelope_prior_trace_tail_hash",
        "git_commit",
        "level_index",
        "memory_phase",
        "pending_submitted_event_id",
        "rng_state_hash",
        "step_index",
    }
)
_FOCUSED_VERIFICATION_TESTS = (
    "tests/unit/test_rule_change_fixture.py",
    "tests/unit/test_measure_rule_change.py",
    "tests/unit/test_mechanics_lifecycle.py",
    "tests/integration/test_rule_change_reopening.py",
    "tests/integration/test_memory_checkpoint_resume.py",
    "tests/replay/test_controller_checkpoint.py",
)
_CANDIDATE_STATIC_SCALAR_FIELDS = (
    "candidate_id",
    "change_domain",
    "first_contradiction_event_id",
    "level_index",
    "observation_condition_signature",
    "opaque_handle",
    "opened_step",
    "predecessor_effect_signature",
    "predecessor_epoch_id",
    "successor_effect_signature",
)
_CANDIDATE_STATIC_SEQUENCE_FIELDS = (
    "affected_hypothesis_ids",
    "affected_model_ids",
    "invalidated_plan_ids",
    "predecessor_recovery_event_ids",
)


@dataclass(frozen=True, slots=True)
class _BoundaryRequest:
    boundary: CheckpointBoundary
    resume: bool


@dataclass(slots=True)
class _CaseStart:
    """One live controller/evaluator continuation from a sealed shared prefix."""

    episode: RuleChangeEvaluatorEpisode
    controller: ARC3Controller
    context: RunContext
    features: PresetFeatures
    run_id: str
    observations: list[Observation]
    actions: list[dict[str, JSONValue]]
    decisions: list[dict[str, object]]
    evaluator_trajectory: list[dict[str, JSONValue]]
    failures: list[dict[str, object]]
    prefix_seal: dict[str, object] | None
    readiness_receipt: dict[str, object] | None
    boundary: dict[str, object]
    pending_decision: ActionDecision | None
    prefix_wall_ns: int
    prefix_cpu_ns: int
    before_rss: dict[str, JSONValue]


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


def _git_bytes(*arguments: str) -> bytes | None:
    """Read a Git object without text or newline conversion."""

    try:
        completed = subprocess.run(
            ("git", *arguments),
            cwd=ROOT,
            check=False,
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return completed.stdout if completed.returncode == 0 else None


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
            "first_party_source_files": entries,
            "first_party_source_hash": trace_sha256_bytes(trace_canonical_bytes(entries)),
            "git_commit": _git_value("rev-parse", "HEAD"),
            "git_tree": _git_value("rev-parse", "HEAD^{tree}"),
            "predeclaration_sha256": sha256_file(PREDECLARATION),
            "worktree_status_hash": (
                None if status is None else sha256_bytes((status + "\n").encode("utf-8"))
            ),
        },
        hash_field="identity_hash",
    )


def _source_identity_stability(
    start: Mapping[str, object], end: Mapping[str, object]
) -> dict[str, object]:
    """Fail closed unless the complete sealed source identity stayed unchanged."""

    predicates = {
        "clean_at_start": start.get("dirty_worktree") is False,
        "clean_at_end": end.get("dirty_worktree") is False,
        "git_commit": start.get("git_commit") == end.get("git_commit"),
        "git_tree": start.get("git_tree") == end.get("git_tree"),
        "first_party_source_hash": start.get("first_party_source_hash")
        == end.get("first_party_source_hash"),
        "predeclaration_sha256": start.get("predeclaration_sha256")
        == end.get("predeclaration_sha256")
        == PREDECLARATION_SHA256,
        "sealed_identity": start.get("identity_hash") == end.get("identity_hash"),
        "exact_identity": dict(start) == dict(end),
    }
    return {
        "end_identity_hash": end.get("identity_hash"),
        "passed": all(predicates.values()),
        "predicates": predicates,
        "start_identity_hash": start.get("identity_hash"),
    }


def _runtime_identity() -> dict[str, object]:
    memory = process_memory_sample()
    return {
        "logical_cpu_count": os.cpu_count(),
        "machine": platform.machine(),
        "memory_measurement_source": memory.get("measurement_source"),
        "packages": {
            "arc3": _package_version("arc3"),
            "arc-agi": _package_version("arc-agi"),
            "arcengine": _package_version("arcengine"),
            "coverage": _package_version("coverage"),
            "hypothesis": _package_version("hypothesis"),
            "mypy": _package_version("mypy"),
            "numpy": _package_version("numpy"),
            "pyarrow": _package_version("pyarrow"),
            "pydantic": _package_version("pydantic"),
            "psutil": _package_version("psutil"),
            "pytest": _package_version("pytest"),
            "pytest-cov": _package_version("pytest-cov"),
            "ruff": _package_version("ruff"),
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
    seed: int,
    git_commit: str,
    checkpointing: bool,
) -> RunContext:
    return RunContext(
        run_id=run_id,
        episode_id=f"{run_id}-episode",
        game_id=str(RULE_CHANGE_GAME_ID),
        trace_root=root / "trace",
        checkpoint_root=root / "checkpoint",
        config=ARC3Config(
            seed=seed,
            network_enabled=False,
            profile=("build-001-stage06-checkpoint" if checkpointing else "build-001-stage06-bulk"),
            budgets=BudgetConfig(
                max_actions=MAX_ACTIONS,
                max_resets=MAX_RESETS,
                wall_clock_seconds=MAX_WALL_SECONDS_PER_EXECUTION,
                memory_megabytes=1024,
                max_coordinate_candidates=MAX_COORDINATE_CANDIDATES,
                max_search_nodes=MAX_SEARCH_NODES,
                max_search_depth=MAX_SEARCH_DEPTH,
                max_trace_bytes=MAX_TRACE_BYTES,
            ),
        ),
        git_commit=git_commit,
        source_kind="build-001-stage06-rule-change",
        source_version="0.1",
    )


def _action_payload(action: ActionRequest) -> dict[str, JSONValue]:
    return {
        "coordinate": (
            None
            if action.coordinate is None
            else {"x": action.coordinate.x, "y": action.coordinate.y}
        ),
        "name": action.name.value,
    }


def _trace_frame_hash(frame: object) -> str:
    cells = getattr(frame, "cells", None)
    if not isinstance(cells, tuple):
        raise TypeError("normalized trace frame does not expose immutable cells")
    return trace_sha256_bytes(trace_canonical_bytes([list(row) for row in cells]))


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


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: object) -> Sequence[object]:
    return value if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) else ()


def _mechanics_projection(controller: ARC3Controller) -> dict[str, JSONValue]:
    value = getattr(controller, "mechanics_lifecycle_projection", None)
    if not isinstance(value, dict):
        return {}
    return cast(dict[str, JSONValue], value)


def _events(controller: ARC3Controller) -> tuple[TraceEvent, ...]:
    controller.journal.flush()
    return controller.journal.verify_manifest(include_active=True)


def _submitted_count(controller: ARC3Controller) -> int:
    return sum(event.event_type == "action.submitted" for event in _events(controller))


def _support_receipt_ids(
    events: Sequence[TraceEvent], hypothesis_ids: frozenset[str]
) -> tuple[str, ...]:
    receipts: set[str] = set()
    for event in events:
        if event.event_type != "hypothesis.supported":
            continue
        hypothesis_id = event.payload.get("hypothesis_id")
        evidence = event.payload.get("evidence_receipt")
        if hypothesis_id not in hypothesis_ids or not isinstance(evidence, dict):
            continue
        receipt_id = evidence.get("receipt_id")
        if isinstance(receipt_id, str):
            receipts.add(receipt_id)
    return tuple(sorted(receipts))


def _readiness_receipt(
    controller: ARC3Controller,
    episode: RuleChangeEvaluatorEpisode,
    action: ActionRequest,
) -> dict[str, object]:
    projection = _mechanics_projection(controller)
    readiness = _mapping(projection.get("readiness"))
    bindings = _mapping(readiness.get("active_action_bindings"))
    action_bound_ids = frozenset(
        item for item in _sequence(bindings.get(action.name.value)) if isinstance(item, str)
    )
    expected_domain = (
        "collision_traversability"
        if episode.case.family
        in {
            RuleChangeFamily.TRAVERSABILITY_FLIP,
            RuleChangeFamily.STATIONARY_NOISE,
        }
        else "action_semantics"
    )
    hypothesis_domains = _mapping(readiness.get("active_hypothesis_domains"))
    domain_ids = frozenset(
        hypothesis_id
        for hypothesis_id, domain in hypothesis_domains.items()
        if isinstance(hypothesis_id, str) and domain == expected_domain
    )
    bound_ids = (
        domain_ids
        if episode.case.family
        in {
            RuleChangeFamily.TRAVERSABILITY_FLIP,
            RuleChangeFamily.STATIONARY_NOISE,
        }
        else action_bound_ids & domain_ids
    )
    support_counts = _mapping(readiness.get("active_hypothesis_support_counts"))
    exact_support_ids = frozenset(
        hypothesis_id
        for hypothesis_id in bound_ids
        if support_counts.get(hypothesis_id) == episode.case.support_required
    )
    active_models = tuple(
        item for item in _sequence(readiness.get("active_model_ids")) if isinstance(item, str)
    )
    events = _events(controller)
    support_ids = _support_receipt_ids(events, exact_support_ids)
    readiness_model_hypotheses = _mapping(readiness.get("active_model_hypothesis_ids"))
    promoted_model_hypotheses = {
        model_id: frozenset(item for item in _sequence(hypothesis_ids) if isinstance(item, str))
        for model_id, hypothesis_ids in readiness_model_hypotheses.items()
        if isinstance(model_id, str)
    }
    affected_promoted_models = frozenset(
        model_id
        for model_id in active_models
        if promoted_model_hypotheses.get(model_id, frozenset()) & exact_support_ids
    )
    active_plan_id = readiness.get("active_plan_id")
    active_plan_model_id = readiness.get("active_plan_model_id")
    prediction_id = readiness.get("pending_prediction_receipt_id")
    pending_prediction_model_ids = frozenset(
        item
        for item in _sequence(readiness.get("pending_prediction_model_ids"))
        if isinstance(item, str)
    )
    pending_prediction_dependent_plan_ids = tuple(
        item
        for item in _sequence(readiness.get("pending_prediction_dependent_plan_ids"))
        if isinstance(item, str)
    )
    plan_depends_on_affected_model = (
        isinstance(active_plan_id, str)
        and isinstance(active_plan_model_id, str)
        and active_plan_model_id in affected_promoted_models
        and readiness.get("active_plan_dependency_satisfied") is True
    )
    prediction_depends_on_affected_model = isinstance(prediction_id, str) and bool(
        pending_prediction_model_ids & affected_promoted_models
    )
    predicates = {
        "affected_hypothesis_active": bool(exact_support_ids),
        "affected_hypothesis_domain_typed": bool(domain_ids),
        "calibration_complete": readiness.get("calibration_complete") is True,
        "dependent_plan_registered": plan_depends_on_affected_model,
        "environment_exact_support_threshold": (
            episode.projection.prechange_support_receipts == episode.case.support_required
        ),
        "exact_controller_support_threshold": bool(exact_support_ids),
        "minimum_distinct_support": len(support_ids) >= episode.case.support_required,
        "nontrivial_plan": readiness.get("active_plan_nontrivial") is True,
        "nontrivial_prediction": (
            readiness.get("pending_prediction_nontrivial") is True
            and prediction_depends_on_affected_model
        ),
        "promoted_predecessor_model": (bool(active_models) and bool(affected_promoted_models)),
        "qualifying_action": episode.trigger_eligible(action),
        "trigger_deadline": (
            episode.projection.action_count + 1 <= episode.case.timing.latest_trigger_action
        ),
    }
    return {
        "active_action_binding_ids": sorted(bound_ids),
        "active_domain_hypothesis_ids": sorted(domain_ids),
        "active_model_ids": list(active_models),
        "affected_promoted_model_ids": sorted(affected_promoted_models),
        "exact_support_hypothesis_ids": sorted(exact_support_ids),
        "expected_hypothesis_domain": expected_domain,
        "active_plan_id": active_plan_id,
        "active_plan_model_id": active_plan_model_id,
        "affected_raw_handle": action.name.value,
        "distinct_support_receipt_count": len(support_ids),
        "distinct_support_receipt_ids": list(support_ids),
        "pending_prediction_receipt_id": prediction_id,
        "pending_prediction_model_ids": sorted(pending_prediction_model_ids),
        "pending_prediction_dependent_plan_ids": list(pending_prediction_dependent_plan_ids),
        "pending_prediction_alternatives": [
            dict(_mapping(item))
            for item in _sequence(readiness.get("pending_prediction_alternatives"))
        ],
        "predicates": predicates,
        "ready": all(predicates.values()),
        "trace_event_count": len(events),
    }


def _recursive_hash_references(value: object, *, names: frozenset[str]) -> set[str]:
    found: set[str] = set()
    if isinstance(value, Mapping):
        for key, item in value.items():
            if key in names and isinstance(item, str) and item.startswith("sha256:"):
                found.add(item)
            found.update(_recursive_hash_references(item, names=names))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for item in value:
            found.update(_recursive_hash_references(item, names=names))
    return found


def _raw_prefix_files(trace_root: Path) -> tuple[Path, ...]:
    return tuple(
        path
        for path in sorted(trace_root.rglob("*"))
        if path.is_file() and (path.suffix in {".jsonl", ".blob", ".bin"} or "blobs" in path.parts)
    )


def _capture_prefix(controller: ARC3Controller) -> dict[str, object]:
    events = _events(controller)
    serialized = [event.to_dict() for event in events]
    root = controller.context.trace_root
    raw_files = []
    for path in _raw_prefix_files(root):
        data = path.read_bytes()
        raw_files.append(
            {
                "byte_length": len(data),
                "path": path.relative_to(root).as_posix(),
                "prefix_sha256": trace_sha256_bytes(data),
            }
        )
    return {
        "blob_hashes": sorted(
            {
                hash_value
                for event in serialized
                for hash_value in _recursive_hash_references(
                    event, names=frozenset({"blob_hash", "frame_hash"})
                )
            }
        ),
        "event_bytes_sha256": trace_sha256_bytes(trace_canonical_bytes(serialized)),
        "event_count": len(events),
        "event_hashes": [event.event_hash for event in events],
        "event_ids": [event.event_id for event in events],
        "raw_file_prefixes": raw_files,
        "tail_event_hash": events[-1].event_hash if events else None,
        "tail_event_id": events[-1].event_id if events else None,
    }


def _verify_prefix(
    trace_root: Path, final_events: Sequence[TraceEvent], seal: Mapping[str, object] | None
) -> dict[str, object]:
    if seal is None:
        return {"passed": False, "reason": "trigger prefix was never sealed"}
    event_count = seal.get("event_count")
    if not isinstance(event_count, int) or isinstance(event_count, bool):
        return {"passed": False, "reason": "invalid prefix event count"}
    prefix_events = tuple(final_events[:event_count])
    serialized = [event.to_dict() for event in prefix_events]
    file_checks: list[dict[str, object]] = []
    for value in _sequence(seal.get("raw_file_prefixes")):
        entry = _mapping(value)
        relative = entry.get("path")
        length = entry.get("byte_length")
        expected = entry.get("prefix_sha256")
        if not isinstance(relative, str) or not isinstance(length, int):
            file_checks.append({"passed": False, "reason": "invalid prefix inventory"})
            continue
        path = trace_root / Path(relative)
        data = path.read_bytes()[:length] if path.is_file() else b""
        measured = trace_sha256_bytes(data)
        file_checks.append(
            {
                "byte_length": length,
                "measured_sha256": measured,
                "passed": len(data) == length and measured == expected,
                "path": relative,
            }
        )
    event_ids = [event.event_id for event in prefix_events]
    event_hashes = [event.event_hash for event in prefix_events]
    measured_blob_hashes = sorted(
        {
            hash_value
            for event in serialized
            for hash_value in _recursive_hash_references(
                event, names=frozenset({"blob_hash", "frame_hash"})
            )
        }
    )
    hash_links_valid = all(
        event.previous_event_hash == (prefix_events[index - 1].event_hash if index else None)
        for index, event in enumerate(prefix_events)
    )
    predicates = {
        "blob_references": measured_blob_hashes == seal.get("blob_hashes"),
        "event_bytes": (
            trace_sha256_bytes(trace_canonical_bytes(serialized)) == seal.get("event_bytes_sha256")
        ),
        "event_hashes": event_hashes == seal.get("event_hashes"),
        "event_ids": event_ids == seal.get("event_ids"),
        "event_count": len(prefix_events) == event_count,
        "previous_hash_links": hash_links_valid,
        "raw_file_prefixes": bool(file_checks)
        and all(item.get("passed") is True for item in file_checks),
        "tail_event_hash": (
            (prefix_events[-1].event_hash if prefix_events else None) == seal.get("tail_event_hash")
        ),
        "tail_event_id": (
            (prefix_events[-1].event_id if prefix_events else None) == seal.get("tail_event_id")
        ),
    }
    return {
        "file_checks": file_checks,
        "passed": all(predicates.values()),
        "predicates": predicates,
    }


def _truth_receipt_report(episode: RuleChangeEvaluatorEpisode) -> dict[str, object]:
    receipts = episode.truth_receipts
    failures: list[dict[str, object]] = []
    previous: str | None = None
    for receipt in receipts:
        value = receipt.to_dict()
        core = {
            key: item
            for key, item in value.items()
            if key not in {"receipt_hash", "receipt_id", "previous_receipt_hash"}
        }
        expected_id = sha256_json({"domain": "arc3.stage06.truth-receipt-id.v1", **core})
        expected_hash = sha256_json(
            {
                "domain": "arc3.stage06.truth-receipt.v1",
                "previous_receipt_hash": previous,
                "receipt_id": expected_id,
                **core,
            }
        )
        if (
            receipt.receipt_id != expected_id
            or receipt.receipt_hash != expected_hash
            or receipt.previous_receipt_hash != previous
        ):
            failures.append(
                {
                    "receipt_id": receipt.receipt_id,
                    "receipt_sequence": receipt.receipt_sequence,
                }
            )
        previous = receipt.receipt_hash
    values = [receipt.to_dict() for receipt in receipts]
    layout = episode.layout_receipt
    layout_core = {
        key: value for key, value in layout.items() if key not in {"layout_id", "receipt_hash"}
    }
    layout_verified = (
        layout.get("layout_id")
        == sha256_json({"domain": "arc3.stage06.layout-identity.v1", **layout_core})
        and layout.get("receipt_hash")
        == sha256_json({"domain": "arc3.stage06.layout-receipt.v1", **layout_core})
        and all(value is True for value in _mapping(layout.get("predicates")).values())
    )
    distinct_successor = [receipt for receipt in receipts if receipt.distinct_successor_evidence]
    semantic_predicates: dict[str, bool] = {
        "coherent_successor_count_matches_distinct_receipts": (
            not receipts or receipts[-1].coherent_successor_receipts == len(distinct_successor)
        ),
    }
    if (
        episode.case.kind is RuleChangeCaseKind.INTERVENTION
        and episode.case.family is RuleChangeFamily.ACTION_EFFECT_ROTATION
    ):
        evidence_handles = [receipt.action.name for receipt in distinct_successor]
        semantic_predicates.update(
            {
                "action_successor_handles_distinct": len(evidence_handles)
                == len(set(evidence_handles)),
                "action_successor_is_global_clockwise_mapping": all(
                    receipt.realized_effect
                    == (-receipt.predecessor_effect[1], receipt.predecessor_effect[0])
                    for receipt in distinct_successor
                ),
            }
        )
    if (
        episode.case.kind is RuleChangeCaseKind.INTERVENTION
        and episode.case.family is RuleChangeFamily.TRAVERSABILITY_FLIP
    ):
        evidence_cells = [receipt.attempted_cell for receipt in distinct_successor]
        semantic_predicates["traversability_successor_cells_distinct"] = len(evidence_cells) == len(
            set(evidence_cells)
        )
    return {
        "chain_failure_count": len(failures),
        "chain_failures": failures,
        "duplicate_receipt_ids": len(receipts) - len({receipt.receipt_id for receipt in receipts}),
        "receipt_count": len(receipts),
        "receipts": values,
        "receipts_hash": trace_sha256_bytes(trace_canonical_bytes(values)),
        "layout_generation_receipt": layout,
        "layout_generation_verified": layout_verified,
        "semantic_predicates": semantic_predicates,
        "tail_receipt_hash": receipts[-1].receipt_hash if receipts else None,
        "verified": layout_verified
        and not failures
        and len(receipts) == len({receipt.receipt_id for receipt in receipts})
        and all(semantic_predicates.values()),
        "semantic_verified": all(semantic_predicates.values()),
    }


def _delta_projection(value: Mapping[str, object]) -> dict[str, object]:
    """Retain only raw delta fields that offline replay can recompute exactly."""

    cells = [
        {
            "after": item.get("after"),
            "before": item.get("before"),
            "x": item.get("x"),
            "y": item.get("y"),
        }
        for raw in _sequence(value.get("cell_changes"))
        for item in (_mapping(raw),)
    ]
    return {
        "after_frame_hash": value.get("after_frame_hash"),
        "apparent_noop": value.get("apparent_noop"),
        "before_frame_hash": value.get("before_frame_hash"),
        "cell_changes": cells,
        "changed_bbox": value.get("changed_bbox"),
        "changed_cell_count": value.get("changed_cell_count"),
    }


_CANDIDATE_PROJECTION_FIELDS = (
    "affected_hypothesis_ids",
    "affected_model_ids",
    "candidate_id",
    "change_domain",
    "first_contradiction_event_id",
    "invalidated_plan_ids",
    "last_tested_step",
    "level_index",
    "observation_condition_signature",
    "opaque_handle",
    "opened_step",
    "predecessor_effect_signature",
    "predecessor_epoch_id",
    "predecessor_recovery_event_ids",
    "provisional_status",
    "successor_effect_signature",
    "supporting_contradiction_event_ids",
    "supporting_discrimination_context_ids",
    "supporting_successor_transition_ids",
)
_EPOCH_PROJECTION_FIELDS = (
    "active_hypothesis_ids",
    "active_model_ids",
    "caused_by_change_candidate_id",
    "epoch_id",
    "epoch_index",
    "level_index",
    "parent_epoch_id",
    "start_transition_id",
    "status",
)


def _epoch_coordinates(epoch_id: str) -> tuple[int, int] | None:
    prefix = "mechanics-epoch:L"
    if not epoch_id.startswith(prefix):
        return None
    try:
        level, epoch = epoch_id.removeprefix(prefix).split(":", maxsplit=1)
        return int(level), int(epoch)
    except ValueError:
        return None


def _integer_sort_key(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else -1


def _projection_lifecycle_core(projection: Mapping[str, object]) -> dict[str, object]:
    epochs = [
        {key: epoch.get(key) for key in _EPOCH_PROJECTION_FIELDS}
        for raw in _sequence(projection.get("epochs"))
        for epoch in (_mapping(raw),)
    ]
    candidates = [
        {key: candidate.get(key) for key in _CANDIDATE_PROJECTION_FIELDS}
        for raw in _sequence(projection.get("change_candidates"))
        for candidate in (_mapping(raw),)
    ]
    return {
        "active_epoch_id": projection.get("active_epoch_id"),
        "change_candidates": sorted(candidates, key=lambda item: str(item.get("candidate_id"))),
        "demoted_model_ids": sorted(
            item for item in _sequence(projection.get("demoted_model_ids")) if isinstance(item, str)
        ),
        "epochs": sorted(
            epochs,
            key=lambda item: (
                _integer_sort_key(item.get("level_index")),
                _integer_sort_key(item.get("epoch_index")),
                str(item.get("epoch_id")),
            ),
        ),
        "hypothesis_epochs": dict(sorted(_mapping(projection.get("hypothesis_epochs")).items())),
        "invalidated_plan_ids": sorted(
            item
            for item in _sequence(projection.get("invalidated_plan_ids"))
            if isinstance(item, str)
        ),
        "model_epochs": dict(sorted(_mapping(projection.get("model_epochs")).items())),
        "resolved_noise_transition_ids": sorted(
            item
            for item in _sequence(projection.get("resolved_noise_transition_ids"))
            if isinstance(item, str)
        ),
        "suspended_model_ids": sorted(
            item
            for item in _sequence(projection.get("suspended_model_ids"))
            if isinstance(item, str)
        ),
    }


def _fold_lifecycle_timeline(
    timeline: Sequence[Mapping[str, object]],
) -> tuple[dict[str, object], list[str]]:
    """Rebuild lifecycle indices solely from immutable typed-event payloads."""

    epochs: dict[str, dict[str, object]] = {}
    candidates: dict[str, dict[str, object]] = {}
    hypothesis_epochs: dict[str, str] = {}
    model_epochs: dict[str, str] = {}
    suspended: set[str] = set()
    demoted: set[str] = set()
    invalidated: set[str] = set()
    resolved_noise: set[str] = set()
    active_epoch_id: str | None = None

    def ensure_epoch(epoch_id: str, fallback_level: int) -> dict[str, object]:
        coordinates = _epoch_coordinates(epoch_id)
        level_index, epoch_index = coordinates or (fallback_level, 0)
        return epochs.setdefault(
            epoch_id,
            {
                "active_hypothesis_ids": [],
                "active_model_ids": [],
                "caused_by_change_candidate_id": None,
                "epoch_id": epoch_id,
                "epoch_index": epoch_index,
                "level_index": level_index,
                "parent_epoch_id": None,
                "start_transition_id": None,
                "status": "ACTIVE",
            },
        )

    for raw_event in timeline:
        event_type = raw_event.get("event_type")
        event_id = raw_event.get("event_id")
        payload = _mapping(raw_event.get("payload"))
        level_value = raw_event.get("level_index")
        level_index = (
            level_value if isinstance(level_value, int) and not isinstance(level_value, bool) else 0
        )
        epoch_ref = payload.get("mechanics_epoch_id")
        if isinstance(epoch_ref, str):
            ensure_epoch(epoch_ref, level_index)
            if event_type == "action.selected":
                active_epoch_id = epoch_ref
        predecessor_epoch = payload.get("predecessor_epoch_id")
        if isinstance(predecessor_epoch, str):
            ensure_epoch(predecessor_epoch, level_index)

        if event_type == "simulation.plan_invalidated":
            invalidated.update(
                item for item in _sequence(payload.get("plan_ids")) if isinstance(item, str)
            )
        if event_type in {
            "mechanics.change_candidate_created",
            "mechanics.change_confirmed",
            "mechanics.change_candidate_resolved",
        }:
            candidate_invalidations = {
                item
                for item in _sequence(payload.get("invalidated_plan_ids"))
                if isinstance(item, str)
            }
            invalidated.update(candidate_invalidations)
            candidate_id = payload.get("candidate_id")
            if isinstance(candidate_id, str):
                candidate = candidates.setdefault(candidate_id, {})
                candidate.update(
                    {
                        key: payload.get(key)
                        for key in _CANDIDATE_PROJECTION_FIELDS
                        if key in payload
                    }
                )
                affected_models = {
                    item
                    for item in _sequence(payload.get("affected_model_ids"))
                    if isinstance(item, str)
                }
                if event_type == "mechanics.change_candidate_created":
                    suspended.update(affected_models)
                else:
                    suspended.difference_update(affected_models)
                if event_type == "mechanics.change_candidate_resolved":
                    resolved_noise.update(
                        item
                        for item in _sequence(payload.get("retrodiction_excluded_transition_ids"))
                        if isinstance(item, str)
                    )

        if event_type == "mechanics.epoch_opened":
            opened_epoch_id = payload.get("epoch_id")
            if isinstance(opened_epoch_id, str):
                opened = ensure_epoch(opened_epoch_id, level_index)
                opened.update(
                    {
                        key: payload.get(key)
                        for key in _EPOCH_PROJECTION_FIELDS
                        if key in payload
                        and key not in {"active_hypothesis_ids", "active_model_ids"}
                    }
                )
                parent = payload.get("parent_epoch_id")
                if isinstance(parent, str):
                    ensure_epoch(parent, level_index)["status"] = "CLOSED"
                active_epoch_id = opened_epoch_id

        if event_type == "model.rule_demoted":
            demoted.update(
                item
                for item in _recursive_named_strings(
                    payload, names=frozenset({"model_id", "model_ids"})
                )
                if item.startswith("world-model:")
            )

        hypothesis_id = payload.get("hypothesis_id")
        if isinstance(hypothesis_id, str) and event_type in {
            "hypothesis.created",
            "hypothesis.supported",
            "hypothesis.contradicted",
            "hypothesis.reopened",
        }:
            hypothesis_epoch = epoch_ref if isinstance(epoch_ref, str) else active_epoch_id
            if isinstance(hypothesis_epoch, str):
                ensure_epoch(hypothesis_epoch, level_index)
                hypothesis_epochs.setdefault(hypothesis_id, hypothesis_epoch)

        if event_type == "model.rule_promoted":
            model_id = payload.get("model_id")
            if isinstance(model_id, str) and isinstance(epoch_ref, str):
                ensure_epoch(epoch_ref, level_index)
                model_epochs.setdefault(model_id, epoch_ref)

        del event_id

    for hypothesis_id, epoch_id in hypothesis_epochs.items():
        values = cast(list[str], ensure_epoch(epoch_id, 0)["active_hypothesis_ids"])
        if hypothesis_id not in values:
            values.append(hypothesis_id)
    for model_id, epoch_id in model_epochs.items():
        values = cast(list[str], ensure_epoch(epoch_id, 0)["active_model_ids"])
        if model_id not in values:
            values.append(model_id)
    for epoch in epochs.values():
        cast(list[str], epoch["active_hypothesis_ids"]).sort()
        cast(list[str], epoch["active_model_ids"]).sort()

    folded: dict[str, object] = {
        "active_epoch_id": active_epoch_id,
        "change_candidates": sorted(
            (
                {key: candidate.get(key) for key in _CANDIDATE_PROJECTION_FIELDS}
                for candidate in candidates.values()
            ),
            key=lambda item: str(item.get("candidate_id")),
        ),
        "demoted_model_ids": sorted(demoted),
        "epochs": sorted(
            epochs.values(),
            key=lambda item: (
                _integer_sort_key(item.get("level_index")),
                _integer_sort_key(item.get("epoch_index")),
                str(item.get("epoch_id")),
            ),
        ),
        "hypothesis_epochs": dict(sorted(hypothesis_epochs.items())),
        "invalidated_plan_ids": sorted(invalidated),
        "model_epochs": dict(sorted(model_epochs.items())),
        "resolved_noise_transition_ids": sorted(resolved_noise),
        "suspended_model_ids": sorted(suspended),
    }
    consistency_failures: list[str] = []
    epoch_ids = set(epochs)
    if active_epoch_id not in epoch_ids:
        consistency_failures.append("active epoch is absent from rebuilt index")
    for candidate in candidates.values():
        status = candidate.get("provisional_status")
        recoveries = _sequence(candidate.get("predecessor_recovery_event_ids"))
        if status == "CONFIRMED" and not _coherent_candidate_confirmation(candidate, candidate):
            consistency_failures.append(
                "confirmed candidate lacks two distinct coherent successor contexts"
            )
        if status == "RESOLVED_NOISE" and len(recoveries) < 2:
            consistency_failures.append("resolved-noise candidate lacks two recoveries")
    for epoch in epochs.values():
        caused_by = epoch.get("caused_by_change_candidate_id")
        if caused_by is not None and (
            not isinstance(caused_by, str)
            or candidates.get(caused_by, {}).get("provisional_status") != "CONFIRMED"
        ):
            consistency_failures.append("opened epoch lacks a confirmed causal candidate")
        parent = epoch.get("parent_epoch_id")
        if parent is not None and parent not in epoch_ids:
            consistency_failures.append("opened epoch parent is absent")
    indices_by_level: dict[int, list[int]] = {}
    for epoch in epochs.values():
        level = epoch.get("level_index")
        index = epoch.get("epoch_index")
        if isinstance(level, int) and isinstance(index, int):
            indices_by_level.setdefault(level, []).append(index)
    if any(sorted(indices) != list(range(len(indices))) for indices in indices_by_level.values()):
        consistency_failures.append("epoch indices are not contiguous")
    return folded, consistency_failures


def _lifecycle_replay_report(
    events: Sequence[TraceEvent], final_projection: Mapping[str, object]
) -> dict[str, object]:
    """Fold immutable lifecycle events and compare the independently rebuilt index."""

    timeline = tuple(
        {
            "event_id": event.event_id,
            "event_type": event.event_type,
            "level_index": event.level_index,
            "payload": event.payload,
        }
        for event in events
    )
    folded, consistency_failures = _fold_lifecycle_timeline(timeline)
    projected = _projection_lifecycle_core(final_projection)
    predicates = {
        "event_fold_consistent": not consistency_failures,
        "event_fold_matches_final_projection": folded == projected,
    }
    return {
        "consistency_failures": consistency_failures,
        "final_projection_hash": trace_sha256_bytes(trace_canonical_bytes(projected)),
        "folded_projection": folded,
        "folded_projection_hash": trace_sha256_bytes(trace_canonical_bytes(folded)),
        "passed": all(predicates.values()),
        "predicates": predicates,
    }


def _recursive_event_ids(value: object) -> frozenset[str]:
    found: set[str] = set()
    if isinstance(value, str):
        if value.startswith("E-"):
            found.add(value)
    elif isinstance(value, Mapping):
        for item in value.values():
            found.update(_recursive_event_ids(item))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for item in value:
            found.update(_recursive_event_ids(item))
    return frozenset(found)


def _causal_action_replay(
    events: Sequence[TraceEvent],
    *,
    expected_actions: Sequence[Mapping[str, object]],
    expected_reset_count: int,
) -> dict[str, object]:
    """Rebuild exact selected/validated/submitted/returned action chains."""

    event_by_id = {event.event_id: event for event in events}
    event_index = {event.event_id: index for index, event in enumerate(events)}
    selected = [event for event in events if event.event_type == "action.selected"]
    validated = [event for event in events if event.event_type == "action.validated"]
    submitted = [event for event in events if event.event_type == "action.submitted"]
    consequences = [event for event in events if event.event_type == "consequence.received"]
    failures: list[dict[str, object]] = []
    rebuilt_actions: list[object] = []

    for position, selected_event in enumerate(selected):
        action = selected_event.payload.get("selected_action")
        decision_id = selected_event.payload.get("decision_id")
        rebuilt_actions.append(action)
        if (
            position >= len(validated)
            or position >= len(submitted)
            or position >= len(consequences)
        ):
            failures.append(
                {
                    "event_id": selected_event.event_id,
                    "reason": "incomplete causal action quartet",
                }
            )
            continue
        validated_event = validated[position]
        submitted_event = submitted[position]
        consequence_event = consequences[position]
        predicates = {
            "selected_before_validated": (
                event_index[selected_event.event_id] < event_index[validated_event.event_id]
            ),
            "validated_before_submitted": (
                event_index[validated_event.event_id] < event_index[submitted_event.event_id]
            ),
            "submitted_before_consequence": (
                event_index[submitted_event.event_id] < event_index[consequence_event.event_id]
            ),
            "validated_selected_ref": (
                validated_event.payload.get("selected_event_id") == selected_event.event_id
            ),
            "submitted_selected_ref": (
                submitted_event.payload.get("selected_event_id") == selected_event.event_id
            ),
            "submitted_validated_ref": (
                submitted_event.payload.get("validated_event_id") == validated_event.event_id
            ),
            "consequence_selected_ref": (
                consequence_event.payload.get("selected_event_id") == selected_event.event_id
            ),
            "consequence_submitted_ref": (
                consequence_event.payload.get("submitted_event_id") == submitted_event.event_id
            ),
            "decision_identity": (
                validated_event.payload.get("decision_id") == decision_id
                and submitted_event.payload.get("decision_id") == decision_id
            ),
            "action_payload_identity": (
                validated_event.payload.get("action") == action
                and submitted_event.payload.get("action") == action
                and consequence_event.payload.get("action") == action
                and consequence_event.payload.get("submitted_action") == action
                and consequence_event.payload.get("returned_action") == action
            ),
        }
        if not all(predicates.values()):
            failures.append(
                {
                    "event_id": selected_event.event_id,
                    "predicates": predicates,
                    "reason": "causal action payload or reference mismatch",
                }
            )

    source_failures: list[dict[str, object]] = []
    for index, event in enumerate(events):
        for referenced_id in sorted(_recursive_event_ids(event.payload)):
            referenced_index = event_index.get(referenced_id)
            if (
                referenced_id not in event_by_id
                or referenced_index is None
                or referenced_index >= index
            ):
                source_failures.append(
                    {
                        "event_id": event.event_id,
                        "referenced_event_id": referenced_id,
                    }
                )
    stages = (
        ("action.selected", selected, "selected_action"),
        ("action.validated", validated, "action"),
        ("action.submitted", submitted, "action"),
        ("consequence.received", consequences, "action"),
    )
    reset_counts = {
        event_type: sum(
            _mapping(event.payload.get(action_key)).get("name") == "RESET" for event in stage
        )
        for event_type, stage, action_key in stages
    }
    predicates = {
        "causal_quartets": not failures,
        "exact_action_sequence": rebuilt_actions == [dict(item) for item in expected_actions],
        "recursive_source_closure": not source_failures,
        "reset_accounting": all(count == expected_reset_count for count in reset_counts.values()),
        "stage_cardinality": (
            len(selected)
            == len(validated)
            == len(submitted)
            == len(consequences)
            == len(expected_actions)
        ),
    }
    return {
        "failures": failures,
        "passed": all(predicates.values()),
        "predicates": predicates,
        "rebuilt_actions": rebuilt_actions,
        "recursive_source_failures": source_failures,
        "reset_counts": reset_counts,
    }


def _observation_blinding_report(
    events: Sequence[TraceEvent], *, forbidden_values: Sequence[str] = ()
) -> dict[str, object]:
    forbidden_fragments = (
        "action_variant",
        "case_id",
        "intervention",
        "mechanics_epoch",
        "palette_variant",
        "pulse_",
        "terrain_truth",
        "timing",
    )
    failures: list[dict[str, object]] = []
    forbidden_value_set = frozenset(forbidden_values)

    def inspect(value: object, path: str) -> None:
        if isinstance(value, Mapping):
            for key, item in value.items():
                lowered = str(key).lower()
                if any(fragment in lowered for fragment in forbidden_fragments):
                    failures.append({"path": f"{path}.{key}", "reason": "forbidden truth key"})
                inspect(item, f"{path}.{key}")
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            for index, item in enumerate(value):
                inspect(item, f"{path}[{index}]")
        elif isinstance(value, str) and value in forbidden_value_set:
            failures.append({"path": path, "reason": "evaluator truth identifier value"})

    observations = [event for event in events if event.event_type == "observation.received"]
    for event in observations:
        inspect(event.payload, event.event_id)
    return {
        "failure_count": len(failures),
        "failures": failures,
        "observation_count": len(observations),
        "passed": bool(observations) and not failures,
        "truth_identifier_count": len(forbidden_value_set),
    }


def _trace_report(
    trace_root: Path,
    run_id: str,
    frame_hashes: Sequence[str],
    normalized_frame_hashes: Sequence[str],
    prefix_seal: Mapping[str, object] | None,
    final_projection: Mapping[str, object],
    expected_action_count: int,
    expected_actions: Sequence[Mapping[str, object]],
    expected_reset_count: int,
    expected_terminal_state: str,
    forbidden_truth_identifiers: Sequence[str],
) -> dict[str, object]:
    journal = EventJournal(trace_root, run_id=run_id)
    engine = ReplayEngine(journal)
    events = engine.verify_integrity()
    replayed = engine.replay_frames()
    rebuilt_deltas = tuple(
        compute_frame_delta(before.frame, after.frame)
        for before, after in pairwise(replayed)
        if before.episode_id == after.episode_id
    )
    referenced_blobs = journal.verify_referenced_blobs()
    files = [path for path in sorted(trace_root.rglob("*")) if path.is_file()]
    inventory = [
        {
            "byte_length": path.stat().st_size,
            "path": path.relative_to(trace_root).as_posix(),
            "sha256": sha256_file(path),
        }
        for path in files
    ]
    event_counts = Counter(event.event_type for event in events)
    duplicate_event_ids = len(events) - len({event.event_id for event in events})
    evidence_ids: list[str] = []
    for event in events:
        evidence = event.payload.get("evidence_receipt")
        if isinstance(evidence, dict):
            receipt_id = evidence.get("receipt_id")
            if isinstance(receipt_id, str):
                evidence_ids.append(receipt_id)
    duplicate_evidence_ids = len(evidence_ids) - len(set(evidence_ids))
    trace_bytes = sum(path.stat().st_size for path in files)
    prefix = _verify_prefix(trace_root, events, prefix_seal)
    recorded_deltas = [
        _delta_projection(event.payload)
        for event in events
        if event.event_type == "observation.delta_measured"
    ]
    recorded_normalized_frame_hashes = [
        event.payload.get("frame_hash")
        for event in events
        if event.event_type == "observation.normalized"
    ]
    replayed_deltas: list[dict[str, object]] = []
    replayed_delta_index = 0
    latest_frame_index: dict[str, int] = {}
    for frame_index, receipt in enumerate(replayed):
        key = receipt.episode_id
        prior_index = latest_frame_index.get(key)
        if prior_index is not None:
            delta = _delta_projection(rebuilt_deltas[replayed_delta_index].to_dict())
            delta["before_frame_hash"] = normalized_frame_hashes[prior_index]
            delta["after_frame_hash"] = normalized_frame_hashes[frame_index]
            replayed_deltas.append(delta)
            replayed_delta_index += 1
        latest_frame_index[key] = frame_index
    action_event_counts = {
        event_type: event_counts[event_type]
        for event_type in (
            "action.selected",
            "action.submitted",
            "action.validated",
            "consequence.received",
        )
    }
    last_observation = next(
        (event for event in reversed(events) if event.event_type == "observation.received"),
        None,
    )
    lifecycle_replay = _lifecycle_replay_report(events, final_projection)
    causal_action_replay = _causal_action_replay(
        events,
        expected_actions=expected_actions,
        expected_reset_count=expected_reset_count,
    )
    observation_blinding = _observation_blinding_report(
        events, forbidden_values=forbidden_truth_identifiers
    )
    replay_predicates = {
        "action_causal_counts": all(
            count == expected_action_count for count in action_event_counts.values()
        ),
        "delta_sequence": replayed_deltas == recorded_deltas,
        "frame_hash_sequence": [str(item.frame_hash) for item in replayed] == list(frame_hashes),
        "causal_action_replay": causal_action_replay["passed"] is True,
        "lifecycle_projection": lifecycle_replay["passed"] is True,
        "normalized_frame_sequence": recorded_normalized_frame_hashes
        == list(normalized_frame_hashes),
        "observation_blinding": observation_blinding["passed"] is True,
        "terminal_state": (
            last_observation is not None
            and last_observation.payload.get("game_state") == expected_terminal_state
        ),
    }
    result = {
        "action_event_counts": action_event_counts,
        "causal_action_replay": causal_action_replay,
        "delta_replay_count": len(replayed_deltas),
        "delta_sequence_matches_recorded": replay_predicates["delta_sequence"],
        "duplicate_event_ids": duplicate_event_ids,
        "duplicate_evidence_receipt_ids": duplicate_evidence_ids,
        "event_count": len(events),
        "event_type_counts": dict(sorted(event_counts.items())),
        "frame_count": len(replayed),
        "frame_hashes_match_raw_observations": replay_predicates["frame_hash_sequence"],
        "lifecycle_replay": lifecycle_replay,
        "manifest_hash": journal.manifest.manifest_hash,
        "observation_blinding": observation_blinding,
        "prefix_immutability": prefix,
        "referenced_blob_count": len(referenced_blobs),
        "replay_predicates": replay_predicates,
        "replay_verified": all(replay_predicates.values()),
        "tail_event_hash": events[-1].event_hash if events else None,
        "trace_bytes": trace_bytes,
        "trace_file_count": len(files),
        "trace_inventory": inventory,
        "trace_inventory_hash": trace_sha256_bytes(trace_canonical_bytes(inventory)),
        "trace_root": str(trace_root.resolve()),
        "trace_within_limit": trace_bytes <= MAX_TRACE_BYTES,
    }
    journal.close()
    return result


def _event_label(event: TraceEvent, predecessor_epoch_id: str | None) -> str:
    if event.event_type == "action.selected" and event.payload.get("reexploration") is True:
        return "action.selected:reexploration"
    if event.event_type in {
        "hypothesis.supported",
        "model.rule_promoted",
        "consequence.matched_prediction",
    }:
        epoch_id = event.payload.get("mechanics_epoch_id")
        if isinstance(epoch_id, str) and epoch_id != predecessor_epoch_id:
            return f"{event.event_type}:successor"
    return event.event_type


def _coherent_candidate_confirmation(
    created_payload: Mapping[str, object], confirmation_payload: Mapping[str, object]
) -> bool:
    """Require two distinct, candidate-coherent successor discrimination contexts."""

    contradictions = tuple(
        item
        for item in _sequence(confirmation_payload.get("supporting_contradiction_event_ids"))
        if isinstance(item, str)
    )
    transitions = tuple(
        item
        for item in _sequence(confirmation_payload.get("supporting_successor_transition_ids"))
        if isinstance(item, str)
    )
    contexts = tuple(
        item
        for item in _sequence(confirmation_payload.get("supporting_discrimination_context_ids"))
        if isinstance(item, str)
    )
    domain = confirmation_payload.get("change_domain")
    domain_contexts_valid = len(contexts) == 2 and len(contexts) == len(set(contexts))
    if domain == "ACTION_MAPPING":
        domain_contexts_valid = domain_contexts_valid and all(
            item.startswith("opaque-handle:") for item in contexts
        )
    static_fields_preserved = all(
        confirmation_payload.get(field) == created_payload.get(field)
        for field in _CANDIDATE_STATIC_SCALAR_FIELDS
    ) and all(
        tuple(_sequence(confirmation_payload.get(field)))
        == tuple(_sequence(created_payload.get(field)))
        for field in _CANDIDATE_STATIC_SEQUENCE_FIELDS
    )
    return (
        static_fields_preserved
        and confirmation_payload.get("provisional_status") == "CONFIRMED"
        and len(contradictions) == 2
        and len(contradictions) == len(set(contradictions))
        and len(transitions) == 2
        and len(transitions) == len(set(transitions))
        and len(contradictions) == len(transitions) == len(contexts)
        and domain_contexts_valid
    )


def _linked_candidate_confirmation_support(
    events: Sequence[TraceEvent],
    created: TraceEvent,
    confirmation: TraceEvent,
) -> dict[str, object]:
    """Validate every successor-support tuple against its immutable causal sources."""

    event_index = {event.event_id: index for index, event in enumerate(events)}
    candidate_id = created.payload.get("candidate_id")
    contradictions = tuple(
        item
        for item in _sequence(confirmation.payload.get("supporting_contradiction_event_ids"))
        if isinstance(item, str)
    )
    transitions = tuple(
        item
        for item in _sequence(confirmation.payload.get("supporting_successor_transition_ids"))
        if isinstance(item, str)
    )
    contexts = tuple(
        item
        for item in _sequence(confirmation.payload.get("supporting_discrimination_context_ids"))
        if isinstance(item, str)
    )
    support_events = tuple(
        event
        for event in events
        if event.event_type == "mechanics.successor_evidence_supported"
        and event.payload.get("candidate_id") == candidate_id
    )
    affected_hypotheses = tuple(
        item
        for item in _sequence(created.payload.get("affected_hypothesis_ids"))
        if isinstance(item, str)
    )
    created_index = event_index.get(created.event_id)
    confirmation_index = event_index.get(confirmation.event_id)
    support_events_by_index = {
        support_index: event
        for event in support_events
        if isinstance(support_index := event.payload.get("support_index"), int)
    }
    support_event_indices = tuple(
        event_index.get(support_events_by_index[support_index].event_id)
        for support_index in (1, 2)
        if support_index in support_events_by_index
    )
    support_ordered_around_candidate = bool(
        len(support_events) == len(support_events_by_index) == 2
        and len(support_event_indices) == 2
        and isinstance(created_index, int)
        and isinstance(confirmation_index, int)
        and cast(int, support_event_indices[0])
        < cast(int, support_event_indices[1])
        < confirmation_index
    )
    receipt_reports: list[dict[str, object]] = []
    all_receipts_valid = (
        _coherent_candidate_confirmation(created.payload, confirmation.payload)
        and len(support_events) == len(contradictions) == 2
        and isinstance(created_index, int)
        and isinstance(confirmation_index, int)
        and support_ordered_around_candidate
    )
    for support_index, (contradiction_id, transition_id, context_id) in enumerate(
        zip(contradictions, transitions, contexts, strict=False), start=1
    ):
        support = next(
            (
                event
                for event in support_events
                if event.payload.get("support_index") == support_index
            ),
            None,
        )
        payload = support.payload if support is not None else {}
        selected_id = payload.get("source_action_selected_event_id")
        submitted_id = payload.get("source_action_submitted_event_id")
        consequence_id = payload.get("source_consequence_event_id")
        observation_id = payload.get("source_observation_event_id")
        selected = next(
            (event for event in events if event.event_id == selected_id),
            None,
        )
        submitted = next(
            (event for event in events if event.event_id == submitted_id),
            None,
        )
        consequence = next(
            (event for event in events if event.event_id == consequence_id),
            None,
        )
        observation = next(
            (event for event in events if event.event_id == observation_id),
            None,
        )
        contradiction = next(
            (event for event in events if event.event_id == contradiction_id),
            None,
        )
        controlled = tuple(
            event
            for event in events
            if event.event_type == "action.controlled_effect_interpreted"
            and event.payload.get("source_transition_id") == transition_id
            and event.payload.get("source_consequence_event_id") == consequence_id
            and event.payload.get("mechanics_epoch_id")
            == created.payload.get("predecessor_epoch_id")
        )
        source_events = (selected, submitted, consequence, observation, contradiction, support)
        source_indices = tuple(
            event_index.get(event.event_id) if event is not None else None
            for event in source_events
        )
        exact_types = (
            selected is not None
            and selected.event_type == "action.selected"
            and submitted is not None
            and submitted.event_type == "action.submitted"
            and consequence is not None
            and consequence.event_type == "consequence.received"
            and observation is not None
            and observation.event_type == "observation.received"
            and contradiction is not None
            and contradiction.event_type == "hypothesis.contradicted"
            and support is not None
            and support.event_type == "mechanics.successor_evidence_supported"
            and len(controlled) == 1
        )
        source_chain_ordered = bool(
            exact_types
            and all(isinstance(index, int) for index in source_indices)
            and cast(int, source_indices[0])
            < cast(int, source_indices[1])
            < cast(int, source_indices[2])
            < cast(int, source_indices[3])
            < event_index[controlled[0].event_id]
            < cast(int, source_indices[4])
        )
        support_boundary_ordered = bool(
            source_chain_ordered
            and isinstance(created_index, int)
            and isinstance(confirmation_index, int)
            and (
                cast(int, source_indices[4]) < created_index < cast(int, source_indices[5])
                if support_index == 1
                else created_index
                < cast(int, source_indices[0])
                < cast(int, source_indices[4])
                < cast(int, source_indices[5])
            )
            and cast(int, source_indices[5]) < confirmation_index
        )
        causal_order = support_boundary_ordered and support_ordered_around_candidate
        action = _mapping(payload.get("action"))
        exact_action = bool(action) and all(
            _mapping(value) == action
            for value in (
                selected.payload.get("selected_action") if selected else None,
                submitted.payload.get("action") if submitted else None,
                consequence.payload.get("action") if consequence else None,
                consequence.payload.get("submitted_action") if consequence else None,
                consequence.payload.get("returned_action") if consequence else None,
                observation.payload.get("returned_action") if observation else None,
            )
        )
        contradiction_receipt = _mapping(
            contradiction.payload.get("evidence_receipt") if contradiction else None
        )
        exact_contradiction = (
            contradiction is not None
            and contradiction.payload.get("hypothesis_id") in affected_hypotheses
            and tuple(_sequence(contradiction.payload.get("caused_by_event_ids")))
            == (consequence_id,)
            and tuple(_sequence(contradiction.payload.get("evidence_event_ids")))
            == (consequence_id,)
            and tuple(_sequence(contradiction_receipt.get("evidence_event_ids")))
            == (consequence_id,)
            and contradiction_receipt.get("kind") == "contradiction"
        )
        exact_receipt = (
            payload.get("candidate_id") == candidate_id
            and payload.get("support_index") == support_index
            and payload.get("predecessor_epoch_id") == created.payload.get("predecessor_epoch_id")
            and payload.get("change_domain") == created.payload.get("change_domain")
            and payload.get("opaque_handle") == created.payload.get("opaque_handle")
            and tuple(_sequence(payload.get("affected_hypothesis_ids"))) == affected_hypotheses
            and payload.get("contradiction_event_id") == contradiction_id
            and payload.get("source_transition_id") == transition_id
            and transition_id == f"transition:{submitted_id}"
            and payload.get("observed_effect_signature")
            == created.payload.get("successor_effect_signature")
            and payload.get("observation_condition_signature")
            == created.payload.get("observation_condition_signature")
            and payload.get("discrimination_context_id") == context_id
            and payload.get("raw_action_handle") == action.get("name")
            and payload.get("interpretation") == "successor-consistent contradiction consequence"
            and submitted is not None
            and submitted.payload.get("selected_event_id") == selected_id
            and consequence is not None
            and consequence.payload.get("selected_event_id") == selected_id
            and consequence.payload.get("submitted_event_id") == submitted_id
            and observation is not None
            and contradiction is not None
            and support is not None
            and support.step_index == observation.step_index == contradiction.step_index
            and support.episode_id == created.episode_id
            and support.game_id == created.game_id
            and support.level_index == created.level_index
        )
        if created.payload.get("change_domain") == "ACTION_MAPPING":
            exact_receipt = (
                exact_receipt
                and isinstance(action.get("name"), str)
                and context_id == f"opaque-handle:{action.get('name')}"
            )
        receipt_valid = bool(
            exact_types and causal_order and exact_action and exact_contradiction and exact_receipt
        )
        all_receipts_valid = all_receipts_valid and receipt_valid
        receipt_reports.append(
            {
                "causal_order": causal_order,
                "contradiction_event_id": contradiction_id,
                "discrimination_context_id": context_id,
                "exact_action": exact_action,
                "exact_contradiction": exact_contradiction,
                "exact_receipt": exact_receipt,
                "source_transition_id": transition_id,
                "support_event_id": support.event_id if support is not None else None,
                "support_index": support_index,
                "valid": receipt_valid,
            }
        )
    opening_tuple_matches = bool(
        contradictions
        and transitions
        and contexts
        and created.payload.get("first_contradiction_event_id") == contradictions[0]
        and created.payload.get("source_transition_id") == transitions[0]
        and created.payload.get("source_consequence_event_id")
        == _mapping(support_events[0].payload if support_events else {}).get(
            "source_consequence_event_id"
        )
        and tuple(_sequence(created.payload.get("supporting_discrimination_context_ids")))
        == (contexts[0],)
        and confirmation.payload.get("source_transition_id") == transitions[-1]
    )
    predicates = {
        "every_support_receipt_causally_closed": all_receipts_valid,
        "opening_and_confirmation_sources_match": opening_tuple_matches,
        "support_ordered_around_candidate": support_ordered_around_candidate,
    }
    return {
        "candidate_id": candidate_id,
        "passed": all(predicates.values()),
        "predicates": predicates,
        "support_receipts": receipt_reports,
    }


def _candidate_linked_successor_hypothesis(
    events: Sequence[TraceEvent],
    *,
    start_index: int,
    candidate_id: str,
    candidate_payload: Mapping[str, object],
    successor_epoch_id: str,
    affected_hypotheses: set[str],
) -> tuple[TraceEvent, TraceEvent, TraceEvent] | None:
    """Find a typed successor hypothesis induced by a candidate re-exploration receipt."""

    event_index = {event.event_id: index for index, event in enumerate(events)}
    for support_index, support in enumerate(events):
        successor_hypothesis_id = support.payload.get("hypothesis_id")
        if (
            support_index <= start_index
            or support.event_type != "hypothesis.supported"
            or support.payload.get("mechanics_epoch_id") != successor_epoch_id
            or not isinstance(successor_hypothesis_id, str)
            or successor_hypothesis_id in affected_hypotheses
        ):
            continue
        support_evidence = _mapping(support.payload.get("evidence_receipt"))
        cited_consequences = tuple(
            item
            for item in _sequence(support_evidence.get("evidence_event_ids"))
            if isinstance(item, str)
        )
        if len(cited_consequences) != 1:
            continue
        consequence_id = cited_consequences[0]
        consequence_position = event_index.get(consequence_id)
        if not isinstance(consequence_position, int):
            continue
        consequence = events[consequence_position]
        selected_id = consequence.payload.get("selected_event_id")
        submitted_id = consequence.payload.get("submitted_event_id")
        selected_position = event_index.get(selected_id) if isinstance(selected_id, str) else None
        submitted_position = (
            event_index.get(submitted_id) if isinstance(submitted_id, str) else None
        )
        if not isinstance(selected_position, int) or not isinstance(submitted_position, int):
            continue
        selected = events[selected_position]
        submitted = events[submitted_position]
        if not (
            selected.event_type == "action.selected"
            and selected.payload.get("reexploration") is True
            and selected.payload.get("selected_probe_or_plan_id") == candidate_id
            and selected.payload.get("mechanics_epoch_id") == successor_epoch_id
            and submitted.event_type == "action.submitted"
            and submitted.payload.get("selected_event_id") == selected_id
            and consequence.event_type == "consequence.received"
            and consequence.payload.get("submitted_event_id") == submitted_id
            and selected_position < submitted_position < consequence_position < support_index
        ):
            continue
        observation_match = next(
            (
                (index, event)
                for index, event in enumerate(
                    events[consequence_position + 1 : support_index],
                    start=consequence_position + 1,
                )
                if event.event_type == "observation.received"
            ),
            None,
        )
        creation_match = next(
            (
                (index, event)
                for index, event in enumerate(
                    events[consequence_position + 1 : support_index],
                    start=consequence_position + 1,
                )
                if event.event_type == "hypothesis.created"
                and event.payload.get("hypothesis_id") == successor_hypothesis_id
                and event.payload.get("mechanics_epoch_id") == successor_epoch_id
            ),
            None,
        )
        transition_id = f"transition:{submitted_id}"
        controlled_match = next(
            (
                (index, event)
                for index, event in enumerate(
                    events[consequence_position + 1 : support_index],
                    start=consequence_position + 1,
                )
                if event.event_type == "action.controlled_effect_interpreted"
                and event.payload.get("source_transition_id") == transition_id
                and event.payload.get("source_consequence_event_id") == consequence_id
                and event.payload.get("mechanics_epoch_id") == successor_epoch_id
            ),
            None,
        )
        if observation_match is None or creation_match is None or controlled_match is None:
            continue
        creation = creation_match[1]
        statement = _mapping(creation.payload.get("statement"))
        controlled_effect = _mapping(controlled_match[1].payload.get("controlled_canonical_effect"))
        action = _mapping(selected.payload.get("selected_action"))
        exact_sources = tuple(_sequence(creation.payload.get("created_from_event_ids"))) == (
            selected_id,
            submitted_id,
            consequence_id,
            observation_match[1].event_id,
        )
        exact_action = bool(action) and all(
            _mapping(value) == action
            for value in (
                submitted.payload.get("action"),
                consequence.payload.get("action"),
                consequence.payload.get("submitted_action"),
                consequence.payload.get("returned_action"),
                observation_match[1].payload.get("returned_action"),
            )
        )
        typed_statement = False
        change_domain = candidate_payload.get("change_domain")
        if change_domain == "ACTION_MAPPING":
            parameters = _mapping(statement.get("parameters"))
            dx = parameters.get("dx")
            dy = parameters.get("dy")
            translation = _sequence(controlled_effect.get("translation"))
            typed_statement = (
                creation.payload.get("family") == "action_semantics"
                and creation.payload.get("hypothesis_type") == "action_semantics"
                and statement.get("action") == action.get("name")
                and statement.get("effect") == "translation"
                and isinstance(dx, int)
                and not isinstance(dx, bool)
                and isinstance(dy, int)
                and not isinstance(dy, bool)
                and (dx != 0 or dy != 0)
                and controlled_effect.get("effect_kind") == "translation"
                and tuple(translation) == (dx, dy)
            )
        elif change_domain == "DESTINATION_ROLE":
            moving_kind = statement.get("moving_kind")
            obstacle_kind = statement.get("obstacle_kind")
            traversable = statement.get("traversable")
            expected_kind = "translation" if traversable is True else "no-op"
            expected_consequence = "entered" if traversable is True else "blocked"
            frames = tuple(
                _mapping(value) for value in _sequence(observation_match[1].payload.get("frames"))
            )
            frame = frames[0] if len(frames) == 1 else {}
            width = frame.get("width")
            height = frame.get("height")
            role_effect_signature = (
                sha256_json(
                    {
                        "domain": "DESTINATION_ROLE",
                        "moving_kind": moving_kind,
                        "obstacle_kind": obstacle_kind,
                        "traversable": traversable,
                    }
                )
                if isinstance(moving_kind, str)
                and isinstance(obstacle_kind, str)
                and isinstance(traversable, bool)
                else None
            )
            role_condition_signature = (
                sha256_json(
                    {
                        "domain": "DESTINATION_ROLE",
                        "width": width,
                        "height": height,
                        "moving_kind": moving_kind,
                        "obstacle_kind": obstacle_kind,
                    }
                )
                if isinstance(width, int)
                and not isinstance(width, bool)
                and width > 0
                and isinstance(height, int)
                and not isinstance(height, bool)
                and height > 0
                and isinstance(moving_kind, str)
                and isinstance(obstacle_kind, str)
                else None
            )
            typed_statement = (
                creation.payload.get("family") == "collision_traversability"
                and creation.payload.get("hypothesis_type") == "collision_traversability"
                and isinstance(moving_kind, str)
                and isinstance(obstacle_kind, str)
                and isinstance(traversable, bool)
                and statement.get("consequence") == expected_consequence
                and controlled_effect.get("effect_kind") == expected_kind
                and role_effect_signature == candidate_payload.get("successor_effect_signature")
                and role_condition_signature
                == candidate_payload.get("observation_condition_signature")
            )
        if (
            observation_match[0] < controlled_match[0] < creation_match[0] < support_index
            and exact_sources
            and exact_action
            and typed_statement
            and tuple(_sequence(support.payload.get("caused_by_event_ids"))) == (consequence_id,)
            and tuple(_sequence(support.payload.get("evidence_event_ids"))) == (consequence_id,)
        ):
            return selected, creation, support
    return None


def _matched_promoted_successor_model(
    events: Sequence[TraceEvent],
    *,
    start_index: int,
    successor_epoch_id: str,
    successor_hypothesis_id: str,
) -> tuple[TraceEvent, TraceEvent] | None:
    """Bind a promoted successor model to the alternative that actually matched."""

    event_index = {event.event_id: index for index, event in enumerate(events)}
    for promotion_index, promotion in enumerate(events):
        promoted_model_id = promotion.payload.get("model_id")
        if (
            promotion_index <= start_index
            or promotion.event_type != "model.rule_promoted"
            or promotion.payload.get("mechanics_epoch_id") != successor_epoch_id
            or successor_hypothesis_id not in _sequence(promotion.payload.get("hypothesis_ids"))
            or not isinstance(promoted_model_id, str)
        ):
            continue
        for prediction_index, prediction in enumerate(events):
            prediction_receipt_id = prediction.payload.get("receipt_id")
            if (
                prediction_index <= promotion_index
                or prediction.event_type != "simulation.prediction_emitted"
                or prediction.payload.get("mechanics_epoch_id") != successor_epoch_id
                or not isinstance(prediction_receipt_id, str)
            ):
                continue
            model_prediction_ids = {
                prediction_id
                for alternative_value in _sequence(prediction.payload.get("alternatives"))
                for prediction_id in _sequence(_mapping(alternative_value).get("prediction_ids"))
                if isinstance(prediction_id, str)
                and promoted_model_id
                in _sequence(_mapping(alternative_value).get("supporting_model_ids"))
            }
            if not model_prediction_ids:
                continue
            submitted_match = next(
                (
                    (index, event)
                    for index, event in enumerate(
                        events[prediction_index + 1 :], start=prediction_index + 1
                    )
                    if event.event_type == "action.submitted"
                    and event.payload.get("prediction_receipt_id") == prediction_receipt_id
                ),
                None,
            )
            if submitted_match is None:
                continue
            submitted_index, submitted = submitted_match
            selected_id = submitted.payload.get("selected_event_id")
            selected_index = event_index.get(selected_id) if isinstance(selected_id, str) else None
            consequence_match = next(
                (
                    (index, event)
                    for index, event in enumerate(
                        events[submitted_index + 1 :], start=submitted_index + 1
                    )
                    if event.event_type == "consequence.received"
                    and event.payload.get("submitted_event_id") == submitted.event_id
                ),
                None,
            )
            if not isinstance(selected_index, int) or consequence_match is None:
                continue
            selected = events[selected_index]
            consequence_index, consequence = consequence_match
            for matched_index, matched in enumerate(
                events[consequence_index + 1 :], start=consequence_index + 1
            ):
                if (
                    matched.event_type != "consequence.matched_prediction"
                    or matched.payload.get("prediction_receipt_id") != prediction_receipt_id
                    or matched.payload.get("mechanics_epoch_id") != successor_epoch_id
                ):
                    continue
                observation_match = next(
                    (
                        (index, event)
                        for index, event in enumerate(
                            events[consequence_index + 1 : matched_index],
                            start=consequence_index + 1,
                        )
                        if event.event_type == "observation.received"
                    ),
                    None,
                )
                matched_prediction_ids = {
                    item
                    for item in _sequence(matched.payload.get("matched_prediction_ids"))
                    if isinstance(item, str)
                }
                controlled_models = {
                    item
                    for item in _sequence(
                        matched.payload.get("controlled_projection_match_model_ids")
                    )
                    if isinstance(item, str)
                }
                action = _mapping(prediction.payload.get("action"))
                action_closed = bool(action) and all(
                    _mapping(value) == action
                    for value in (
                        selected.payload.get("selected_action"),
                        submitted.payload.get("action"),
                        consequence.payload.get("action"),
                        consequence.payload.get("submitted_action"),
                        consequence.payload.get("returned_action"),
                        (
                            observation_match[1].payload.get("returned_action")
                            if observation_match is not None
                            else None
                        ),
                    )
                )
                exact_links = (
                    selected.event_type == "action.selected"
                    and selected.payload.get("decision_id")
                    == prediction.payload.get("action_decision_id")
                    == submitted.payload.get("decision_id")
                    and submitted.payload.get("selected_event_id") == selected.event_id
                    and consequence.payload.get("selected_event_id") == selected.event_id
                    and observation_match is not None
                    and selected_index
                    < prediction_index
                    < submitted_index
                    < consequence_index
                    < observation_match[0]
                    < matched_index
                )
                model_matched = bool(
                    model_prediction_ids & matched_prediction_ids
                    or promoted_model_id in controlled_models
                )
                if action_closed and exact_links and model_matched:
                    return promotion, matched
    return None


def _candidate_authority_closure(
    events: Sequence[TraceEvent],
    *,
    candidate_index: int,
    confirmation_index: int,
    created: TraceEvent,
    confirmation: TraceEvent,
) -> tuple[TraceEvent, TraceEvent] | None:
    """Require complete, candidate-exact demotion and hypothesis reopening receipts."""

    candidate_id = created.payload.get("candidate_id")
    predecessor_epoch_id = created.payload.get("predecessor_epoch_id")
    affected_models = {
        item
        for item in _sequence(created.payload.get("affected_model_ids"))
        if isinstance(item, str)
    }
    affected_hypotheses = {
        item
        for item in _sequence(created.payload.get("affected_hypothesis_ids"))
        if isinstance(item, str)
    }
    invalidated_plans = {
        item
        for item in _sequence(created.payload.get("invalidated_plan_ids"))
        if isinstance(item, str)
    }
    contradictions = tuple(
        item
        for item in _sequence(confirmation.payload.get("supporting_contradiction_event_ids"))
        if isinstance(item, str)
    )

    def exact_unique_strings(value: object, expected: set[str]) -> bool:
        items = tuple(item for item in _sequence(value) if isinstance(item, str))
        return len(items) == len(set(items)) and set(items) == expected

    demotions = tuple(
        (index, event)
        for index, event in enumerate(
            events[candidate_index + 1 : confirmation_index], start=candidate_index + 1
        )
        if event.event_type == "model.rule_demoted"
        and event.payload.get("change_candidate_id") == candidate_id
    )
    if len(demotions) != 1 or not affected_models or not affected_hypotheses:
        return None
    demotion_index, demotion = demotions[0]
    if not (
        exact_unique_strings(demotion.payload.get("model_ids"), affected_models)
        and exact_unique_strings(demotion.payload.get("hypothesis_ids"), affected_hypotheses)
        and exact_unique_strings(demotion.payload.get("invalidated_plan_ids"), invalidated_plans)
        and tuple(_sequence(demotion.payload.get("supporting_contradiction_event_ids")))
        == contradictions
        and demotion.payload.get("mechanics_epoch_id") == predecessor_epoch_id
        and demotion.payload.get("new_status") == "demoted"
    ):
        return None

    reopenings = tuple(
        (index, event)
        for index, event in enumerate(
            events[candidate_index + 1 : confirmation_index], start=candidate_index + 1
        )
        if event.event_type == "hypothesis.reopened"
        and event.payload.get("change_candidate_id") == candidate_id
    )
    reopened_ids = tuple(event.payload.get("hypothesis_id") for _, event in reopenings)
    if not (
        len(reopenings) == len(affected_hypotheses)
        and len(reopened_ids) == len(set(reopened_ids))
        and set(reopened_ids) == affected_hypotheses
        and all(demotion_index < index < confirmation_index for index, _ in reopenings)
    ):
        return None
    for _, reopening in reopenings:
        receipt = _mapping(reopening.payload.get("receipt"))
        if not (
            reopening.payload.get("mechanics_epoch_id") == predecessor_epoch_id
            and tuple(_sequence(reopening.payload.get("caused_by_event_ids"))) == contradictions
            and tuple(_sequence(reopening.payload.get("evidence_event_ids"))) == contradictions
            and exact_unique_strings(
                reopening.payload.get("invalidated_plan_ids"), invalidated_plans
            )
            and receipt.get("kind") == "contradiction"
            and tuple(_sequence(receipt.get("evidence_event_ids"))) == contradictions
            and reopening.payload.get("new_status") == "candidate"
        ):
            return None
    return demotion, reopenings[0][1]


def _linked_lifecycle_chain(
    events: Sequence[TraceEvent], *, predecessor_epoch_id: str | None
) -> tuple[bool, list[dict[str, object]], list[str]]:
    """Require one candidate-linked, source-closed successor lifecycle chain."""

    event_index = {event.event_id: index for index, event in enumerate(events)}

    def later(
        start: int,
        predicate: Callable[[TraceEvent], bool],
    ) -> tuple[int, TraceEvent] | None:
        return next(
            (
                (index, event)
                for index, event in enumerate(events[start + 1 :], start=start + 1)
                if predicate(event)
            ),
            None,
        )

    def confirmation_for(
        candidate_id: str, created_payload: Mapping[str, object]
    ) -> Callable[[TraceEvent], bool]:
        def predicate(event: TraceEvent) -> bool:
            return (
                event.event_type == "mechanics.change_confirmed"
                and event.payload.get("candidate_id") == candidate_id
                and _coherent_candidate_confirmation(created_payload, event.payload)
            )

        return predicate

    def epoch_for(candidate_id: str) -> Callable[[TraceEvent], bool]:
        def predicate(event: TraceEvent) -> bool:
            return (
                event.event_type == "mechanics.epoch_opened"
                and event.payload.get("caused_by_change_candidate_id") == candidate_id
                and event.payload.get("parent_epoch_id") == predecessor_epoch_id
            )

        return predicate

    def reexploration_for(
        candidate_id: str, successor_epoch_id: str
    ) -> Callable[[TraceEvent], bool]:
        def predicate(event: TraceEvent) -> bool:
            return (
                event.event_type == "action.selected"
                and event.payload.get("reexploration") is True
                and event.payload.get("selected_probe_or_plan_id") == candidate_id
                and event.payload.get("mechanics_epoch_id") == successor_epoch_id
            )

        return predicate

    def support_for(
        successor_epoch_id: str, affected_hypotheses: frozenset[str] | set[str]
    ) -> Callable[[TraceEvent], bool]:
        def predicate(event: TraceEvent) -> bool:
            return (
                event.event_type == "hypothesis.supported"
                and event.payload.get("mechanics_epoch_id") == successor_epoch_id
                and event.payload.get("hypothesis_id") not in affected_hypotheses
            )

        return predicate

    def promotion_for(
        successor_epoch_id: str, successor_hypothesis_id: object
    ) -> Callable[[TraceEvent], bool]:
        def predicate(event: TraceEvent) -> bool:
            return (
                event.event_type == "model.rule_promoted"
                and event.payload.get("mechanics_epoch_id") == successor_epoch_id
                and successor_hypothesis_id in _sequence(event.payload.get("hypothesis_ids"))
            )

        return predicate

    def matched_for(successor_epoch_id: str) -> Callable[[TraceEvent], bool]:
        def predicate(event: TraceEvent) -> bool:
            return (
                event.event_type == "consequence.matched_prediction"
                and event.payload.get("mechanics_epoch_id") == successor_epoch_id
            )

        return predicate

    failures: list[str] = []
    for candidate_index, created in enumerate(events):
        if created.event_type != "mechanics.change_candidate_created":
            continue
        candidate_id = created.payload.get("candidate_id")
        source_consequence_id = created.payload.get("source_consequence_event_id")
        contradiction_id = created.payload.get("first_contradiction_event_id")
        affected_hypotheses = {
            item
            for item in _sequence(created.payload.get("affected_hypothesis_ids"))
            if isinstance(item, str)
        }
        if not all(
            isinstance(item, str)
            for item in (candidate_id, source_consequence_id, contradiction_id)
        ):
            failures.append("candidate lacks typed causal identities")
            continue
        assert isinstance(candidate_id, str)
        assert isinstance(source_consequence_id, str)
        assert isinstance(contradiction_id, str)
        consequence_index = event_index.get(source_consequence_id)
        contradiction_index = event_index.get(contradiction_id)
        if (
            consequence_index is None
            or events[consequence_index].event_type != "consequence.received"
        ):
            failures.append(f"{candidate_id}: source consequence is absent")
            continue
        if (
            contradiction_index is None
            or events[contradiction_index].event_type != "hypothesis.contradicted"
            or events[contradiction_index].payload.get("hypothesis_id") not in affected_hypotheses
        ):
            failures.append(f"{candidate_id}: first contradiction is not linked")
            continue
        normalized = next(
            (
                (index, event)
                for index, event in enumerate(
                    events[consequence_index + 1 : contradiction_index],
                    start=consequence_index + 1,
                )
                if event.event_type == "observation.normalized"
            ),
            None,
        )
        if normalized is None or not (
            consequence_index < normalized[0] < contradiction_index < candidate_index
        ):
            failures.append(
                f"{candidate_id}: raw consequence/observation/contradiction order fails"
            )
            continue

        confirmation = later(
            candidate_index,
            confirmation_for(candidate_id, created.payload),
        )
        if confirmation is None:
            failures.append(f"{candidate_id}: linked confirmation is absent")
            continue
        confirmation_support = _linked_candidate_confirmation_support(
            events, created, confirmation[1]
        )
        if confirmation_support["passed"] is not True:
            failures.append(f"{candidate_id}: confirmation support lacks exact causal closure")
            continue
        authority_closure = _candidate_authority_closure(
            events,
            candidate_index=candidate_index,
            confirmation_index=confirmation[0],
            created=created,
            confirmation=confirmation[1],
        )
        if authority_closure is None:
            failures.append(f"{candidate_id}: candidate authority closure is incomplete")
            continue
        demotion_event, reopening_event = authority_closure
        opened = later(
            confirmation[0],
            epoch_for(candidate_id),
        )
        if opened is None:
            failures.append(f"{candidate_id}: linked successor epoch is absent")
            continue
        successor_epoch_id = opened[1].payload.get("epoch_id")
        if not isinstance(successor_epoch_id, str):
            failures.append(f"{candidate_id}: successor epoch identity is absent")
            continue
        successor = _candidate_linked_successor_hypothesis(
            events,
            start_index=opened[0],
            candidate_id=candidate_id,
            candidate_payload=created.payload,
            successor_epoch_id=successor_epoch_id,
            affected_hypotheses=affected_hypotheses,
        )
        if successor is None:
            failures.append(
                f"{candidate_id}: candidate-linked typed successor hypothesis is absent"
            )
            continue
        reexploration_event, _creation_event, support_event = successor
        support_index = event_index[support_event.event_id]
        successor_hypothesis_id = support_event.payload.get("hypothesis_id")
        if not isinstance(successor_hypothesis_id, str):
            failures.append(f"{candidate_id}: successor hypothesis identity is absent")
            continue
        successor_use = _matched_promoted_successor_model(
            events,
            start_index=support_index,
            successor_epoch_id=successor_epoch_id,
            successor_hypothesis_id=successor_hypothesis_id,
        )
        if successor_use is None:
            failures.append(
                f"{candidate_id}: promoted successor model did not causally match its own "
                "alternative"
            )
            continue
        promotion_event, matched_event = successor_use
        chain = (
            events[consequence_index],
            normalized[1],
            events[contradiction_index],
            created,
            demotion_event,
            reopening_event,
            confirmation[1],
            opened[1],
            reexploration_event,
            support_event,
            promotion_event,
            matched_event,
        )
        return (
            True,
            [
                {
                    "event_hash": event.event_hash,
                    "event_id": event.event_id,
                    "event_type": _ORDERED_LIFECYCLE[index],
                    "step_index": event.step_index,
                }
                for index, event in enumerate(chain)
            ],
            [],
        )
    if not failures:
        failures.append("no mechanics change candidate was created")
    return False, [], failures


def _lifecycle_summary(projection: Mapping[str, object], case: RuleChangeCase) -> dict[str, object]:
    inverse_handles = {
        "ACTION1": "ACTION4",
        "ACTION2": "ACTION1",
        "ACTION3": "ACTION2",
        "ACTION4": "ACTION3",
    }

    def canonical_handle(value: object) -> object:
        if case.action_variant is ActionVariant.CYCLE1234 and isinstance(value, str):
            return inverse_handles.get(value, value)
        return value

    epochs = []
    for raw in _sequence(projection.get("epochs")):
        epoch = _mapping(raw)
        epochs.append(
            {
                "active_hypotheses": len(_sequence(epoch.get("active_hypothesis_ids"))),
                "active_models": len(_sequence(epoch.get("active_model_ids"))),
                "epoch_index": epoch.get("epoch_index"),
                "has_parent": epoch.get("parent_epoch_id") is not None,
                "status": epoch.get("status"),
            }
        )
    candidates = []
    for raw in _sequence(projection.get("change_candidates")):
        candidate = _mapping(raw)
        candidates.append(
            {
                "contradiction_count": len(
                    _sequence(candidate.get("supporting_contradiction_event_ids"))
                ),
                "opaque_handle": canonical_handle(candidate.get("opaque_handle")),
                "predecessor_effect_signature": candidate.get("predecessor_effect_signature"),
                "predecessor_recovery_count": len(
                    _sequence(candidate.get("predecessor_recovery_event_ids"))
                ),
                "provisional_status": candidate.get("provisional_status"),
                "successor_effect_signature": candidate.get("successor_effect_signature"),
            }
        )
    active_epoch_id = projection.get("active_epoch_id")
    active_epoch_index = next(
        (
            _mapping(epoch).get("epoch_index")
            for epoch in _sequence(projection.get("epochs"))
            if _mapping(epoch).get("epoch_id") == active_epoch_id
        ),
        None,
    )
    return {
        "active_epoch_index": active_epoch_index,
        "candidates": candidates,
        "demoted_model_count": len(_sequence(projection.get("demoted_model_ids"))),
        "epochs": epochs,
        "invalidated_plan_count": len(_sequence(projection.get("invalidated_plan_ids"))),
        "reexploration_handle": canonical_handle(projection.get("reexploration_handle")),
        "suspended_model_count": len(_sequence(projection.get("suspended_model_ids"))),
    }


def _event_source_closure_after(
    events: Sequence[TraceEvent], start_index: int
) -> tuple[TraceEvent, ...]:
    return tuple(events[start_index:])


def _invalidated_plan_ids(payload: Mapping[str, object]) -> frozenset[str]:
    """Collect plan invalidations from both direct and assessment payloads."""

    invalidated = {
        item for item in _sequence(payload.get("invalidated_plan_ids")) if isinstance(item, str)
    }
    for reopening_value in _sequence(payload.get("reopenings")):
        reopening = _mapping(reopening_value)
        invalidated.update(
            item
            for item in _sequence(reopening.get("invalidated_plan_ids"))
            if isinstance(item, str)
        )
    return frozenset(invalidated)


def _recursive_named_strings(value: object, *, names: frozenset[str]) -> frozenset[str]:
    found: set[str] = set()
    if isinstance(value, Mapping):
        for key, item in value.items():
            if key in names:
                if isinstance(item, str):
                    found.add(item)
                else:
                    found.update(child for child in _sequence(item) if isinstance(child, str))
            found.update(_recursive_named_strings(item, names=names))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for item in value:
            found.update(_recursive_named_strings(item, names=names))
    return frozenset(found)


def _used_plan_ids(event_type: str, payload: Mapping[str, object]) -> frozenset[str]:
    if event_type not in {
        "action.selected",
        "simulation.prediction_emitted",
        "simulation.plan_evaluated",
    }:
        return frozenset()
    return frozenset(
        item
        for item in _recursive_named_strings(
            payload,
            names=frozenset({"dependent_plan_ids", "plan_id", "selected_probe_or_plan_id"}),
        )
        if item.startswith("plan:")
    )


def _used_model_ids(event_type: str, payload: Mapping[str, object]) -> frozenset[str]:
    if event_type not in {
        "action.selected",
        "simulation.prediction_emitted",
        "simulation.plan_evaluated",
    }:
        return frozenset()
    return frozenset(
        item
        for item in _recursive_named_strings(
            payload,
            names=frozenset(
                {
                    "active_world_model_ids",
                    "model_id",
                    "model_ids",
                    "supporting_model_ids",
                }
            ),
        )
        if item.startswith("world-model:")
    )


def _stale_authority_uses(
    timeline: Sequence[tuple[str, Mapping[str, object]]],
    *,
    epoch_open_index: int,
) -> tuple[list[str], list[str], list[str]]:
    """Find only uses that occur after authority was actually revoked."""

    revoked_models_so_far: set[str] = set()
    invalidated_so_far: set[str] = set()
    reopened_predecessor_hypotheses: set[str] = set()
    stale_model_uses: list[str] = []
    stale_plan_uses: list[str] = []
    stale_hypothesis_uses: list[str] = []
    for event_type, payload in timeline:
        if event_type == "mechanics.change_candidate_created":
            revoked_models_so_far.update(
                item
                for item in _recursive_named_strings(
                    payload, names=frozenset({"affected_model_ids"})
                )
                if item.startswith("world-model:")
            )
        if event_type == "model.rule_demoted":
            revoked_models_so_far.update(
                item
                for item in _recursive_named_strings(
                    payload, names=frozenset({"model_id", "model_ids"})
                )
                if item.startswith("world-model:")
            )
        invalidated_so_far.update(_invalidated_plan_ids(payload))
        if event_type == "hypothesis.reopened":
            hypothesis_id = payload.get("hypothesis_id")
            if isinstance(hypothesis_id, str):
                reopened_predecessor_hypotheses.add(hypothesis_id)
        if event_type not in {
            "action.selected",
            "simulation.prediction_emitted",
            "simulation.plan_evaluated",
        }:
            continue
        stale_model_uses.extend(
            sorted(_used_model_ids(event_type, payload) & revoked_models_so_far)
        )
        stale_plan_uses.extend(sorted(_used_plan_ids(event_type, payload) & invalidated_so_far))
        if event_type == "action.selected":
            active_hypotheses = _recursive_named_strings(
                payload, names=frozenset({"active_hypothesis_ids"})
            )
            stale_hypothesis_uses.extend(
                sorted(active_hypotheses & reopened_predecessor_hypotheses)
            )
    _ = epoch_open_index  # The epoch boundary is reported separately; revocation is immediate.
    return stale_model_uses, stale_plan_uses, stale_hypothesis_uses


def _linked_noise_closure(
    events: Sequence[TraceEvent],
    truth_receipts: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """Prove that the trigger-sourced candidate itself resolves as stationary noise."""

    event_index = {event.event_id: index for index, event in enumerate(events)}
    truth_trigger_step = next(
        (
            receipt.get("step")
            for receipt in truth_receipts
            if receipt.get("pulse_triggered") is True
            and receipt.get("trigger_step") == receipt.get("step")
        ),
        None,
    )
    trigger_consequence = next(
        (event for event in events if event.event_type == "consequence.received"),
        None,
    )
    created = (
        next(
            (
                event
                for event in events
                if event.event_type == "mechanics.change_candidate_created"
                and trigger_consequence is not None
                and event.payload.get("source_consequence_event_id") == trigger_consequence.event_id
                and event.step_index == truth_trigger_step
            ),
            None,
        )
        if trigger_consequence is not None
        else None
    )
    candidate_id = created.payload.get("candidate_id") if created is not None else None
    resolved = next(
        (
            event
            for event in events
            if event.event_type == "mechanics.change_candidate_resolved"
            and isinstance(candidate_id, str)
            and event.payload.get("candidate_id") == candidate_id
            and event.payload.get("provisional_status") == "RESOLVED_NOISE"
        ),
        None,
    )
    recovery_ids = (
        tuple(
            item
            for item in _sequence(resolved.payload.get("predecessor_recovery_event_ids"))
            if isinstance(item, str)
        )
        if resolved is not None
        else ()
    )
    resumed_recovery_steps: list[int] = []
    previous_recovery_count = 0
    evaluator_counter_valid = True
    for truth_receipt in truth_receipts:
        count = truth_receipt.get("resumed_predecessor_receipts")
        step = truth_receipt.get("step")
        if not isinstance(count, int) or isinstance(count, bool):
            evaluator_counter_valid = False
            continue
        if count < previous_recovery_count or count > 2:
            evaluator_counter_valid = False
        if count > previous_recovery_count:
            if count != previous_recovery_count + 1 or not isinstance(step, int):
                evaluator_counter_valid = False
            elif not isinstance(step, bool):
                resumed_recovery_steps.append(step)
        previous_recovery_count = count
    evaluator_counter_valid = (
        evaluator_counter_valid
        and previous_recovery_count == 2
        and len(resumed_recovery_steps) == 2
    )

    recovery_receipts: list[dict[str, object]] = []
    recovery_sources_valid = (
        resolved is not None
        and created is not None
        and len(recovery_ids) == 2
        and len(set(recovery_ids)) == 2
    )
    recovery_contexts: list[str] = []
    if recovery_sources_valid and resolved is not None and created is not None:
        created_index = event_index[created.event_id]
        resolved_index = event_index[resolved.event_id]
        predecessor_epoch_id = created.payload.get("predecessor_epoch_id")
        predecessor_signature = created.payload.get("predecessor_effect_signature")
        condition_signature = created.payload.get("observation_condition_signature")
        affected_hypotheses = {
            item
            for item in _sequence(created.payload.get("affected_hypothesis_ids"))
            if isinstance(item, str)
        }
        for support_index, recovery_id in enumerate(recovery_ids, start=1):
            recovery_index = event_index.get(recovery_id)
            recovery = events[recovery_index] if isinstance(recovery_index, int) else None
            payload = recovery.payload if recovery is not None else {}
            transition_id = payload.get("source_transition_id")
            submitted_id = (
                transition_id.removeprefix("transition:")
                if isinstance(transition_id, str) and transition_id.startswith("transition:")
                else None
            )
            submitted_index = (
                event_index.get(submitted_id) if isinstance(submitted_id, str) else None
            )
            submitted = events[submitted_index] if isinstance(submitted_index, int) else None
            selected_id = (
                submitted.payload.get("selected_event_id") if submitted is not None else None
            )
            selected_index = event_index.get(selected_id) if isinstance(selected_id, str) else None
            selected = events[selected_index] if isinstance(selected_index, int) else None
            consequence_id = payload.get("source_consequence_event_id")
            consequence_index = (
                event_index.get(consequence_id) if isinstance(consequence_id, str) else None
            )
            consequence = events[consequence_index] if isinstance(consequence_index, int) else None
            observation_id = payload.get("source_observation_event_id")
            observation_index = (
                event_index.get(observation_id) if isinstance(observation_id, str) else None
            )
            observation = events[observation_index] if isinstance(observation_index, int) else None
            interpretation_matches = [
                (index, event)
                for index, event in enumerate(events)
                if event.event_type == "action.controlled_effect_interpreted"
                and event.payload.get("source_transition_id") == transition_id
                and event.payload.get("source_consequence_event_id") == consequence_id
                and event.payload.get("mechanics_epoch_id") == predecessor_epoch_id
            ]
            context_id = payload.get("discrimination_context_id")
            if isinstance(context_id, str):
                recovery_contexts.append(context_id)
            action_payload = _mapping(selected.payload.get("selected_action")) if selected else {}
            causal_action_equal = bool(action_payload) and all(
                _mapping(value) == action_payload
                for value in (
                    submitted.payload.get("action") if submitted else None,
                    consequence.payload.get("action") if consequence else None,
                    consequence.payload.get("submitted_action") if consequence else None,
                    consequence.payload.get("returned_action") if consequence else None,
                )
            )
            causal_order = (
                isinstance(selected_index, int)
                and isinstance(submitted_index, int)
                and isinstance(consequence_index, int)
                and isinstance(observation_index, int)
                and isinstance(recovery_index, int)
                and len(interpretation_matches) == 1
                and created_index
                < selected_index
                < submitted_index
                < consequence_index
                < observation_index
                < interpretation_matches[0][0]
                < recovery_index
                < resolved_index
            )
            event_types_valid = (
                recovery is not None
                and recovery.event_type == "mechanics.predecessor_recovery_supported"
                and selected is not None
                and selected.event_type == "action.selected"
                and submitted is not None
                and submitted.event_type == "action.submitted"
                and consequence is not None
                and consequence.event_type == "consequence.received"
                and observation is not None
                and observation.event_type == "observation.received"
            )
            exact_payload = (
                payload.get("candidate_id") == candidate_id
                and payload.get("predecessor_epoch_id") == predecessor_epoch_id
                and payload.get("observed_effect_signature") == predecessor_signature
                and payload.get("observation_condition_signature") == condition_signature
                and payload.get("interpretation") == "predecessor-consistent consequence"
                and payload.get("support_index") == support_index
                and {
                    item
                    for item in _sequence(payload.get("affected_hypothesis_ids"))
                    if isinstance(item, str)
                }
                == affected_hypotheses
                and isinstance(context_id, str)
            )
            causal_payload = (
                submitted is not None
                and consequence is not None
                and observation is not None
                and consequence.payload.get("submitted_event_id") == submitted.event_id
                and consequence.payload.get("selected_event_id") == selected_id
                and recovery is not None
                and observation.step_index == recovery.step_index
                and recovery.step_index
                == (
                    resumed_recovery_steps[support_index - 1]
                    if len(resumed_recovery_steps) >= support_index
                    else None
                )
            )
            if created.payload.get("change_domain") in {"ACTION_MAPPING", "OPAQUE_HANDLE"}:
                action_name = action_payload.get("name")
                exact_payload = (
                    exact_payload
                    and isinstance(action_name, str)
                    and context_id == f"opaque-handle:{action_name}"
                )
            receipt_valid = bool(
                causal_order
                and event_types_valid
                and exact_payload
                and causal_payload
                and causal_action_equal
            )
            recovery_sources_valid = recovery_sources_valid and receipt_valid
            recovery_receipts.append(
                {
                    "causal_action_equal": causal_action_equal,
                    "causal_order": causal_order,
                    "event_id": recovery_id,
                    "exact_payload": exact_payload,
                    "source_consequence_event_id": consequence_id,
                    "source_observation_event_id": observation_id,
                    "source_transition_id": transition_id,
                    "support_index": support_index,
                    "valid": receipt_valid,
                }
            )
        recovery_sources_valid = (
            recovery_sources_valid
            and len(recovery_contexts) == 2
            and len(set(recovery_contexts)) == 2
        )
    candidate_false_positives = [
        event.event_id
        for event in events
        if event.event_type in _FALSE_POSITIVE_EVENTS
        and isinstance(candidate_id, str)
        and candidate_id
        in _recursive_named_strings(
            event.payload,
            names=frozenset(
                {
                    "candidate_id",
                    "caused_by_change_candidate_id",
                    "change_candidate_id",
                }
            ),
        )
    ]
    predicates = {
        "trigger_consequence_present": trigger_consequence is not None,
        "trigger_sourced_candidate_present": created is not None,
        "same_candidate_resolved_noise": resolved is not None,
        "evaluator_recovery_counter": evaluator_counter_valid,
        "two_exact_typed_causal_recoveries": recovery_sources_valid,
        "candidate_has_no_false_positive_reopening": not candidate_false_positives,
    }
    return {
        "candidate_id": candidate_id,
        "candidate_false_positive_event_ids": candidate_false_positives,
        "created_event_id": created.event_id if created is not None else None,
        "passed": all(predicates.values()),
        "predicates": predicates,
        "recovery_event_ids": list(recovery_ids),
        "recovery_receipts": recovery_receipts,
        "resumed_recovery_steps": resumed_recovery_steps,
        "resolved_event_id": resolved.event_id if resolved is not None else None,
        "trigger_consequence_event_id": (
            trigger_consequence.event_id if trigger_consequence is not None else None
        ),
    }


def _lifecycle_predicates(
    *,
    case: RuleChangeCase,
    events: Sequence[TraceEvent],
    prefix_event_count: int,
    final_projection: Mapping[str, object],
    completed: bool,
    trigger_step: int | None,
    final_action_count: int,
    pulse_resolved: bool,
    evaluator_confirmation_step: int | None,
    truth_receipts: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    post_trigger = _event_source_closure_after(events, prefix_event_count)
    epochs = tuple(_mapping(item) for item in _sequence(final_projection.get("epochs")))
    predecessor_epoch_id = (
        cast(str, epochs[0].get("epoch_id"))
        if epochs and isinstance(epochs[0].get("epoch_id"), str)
        else None
    )
    lifecycle_passed, matched, lifecycle_link_failures = _linked_lifecycle_chain(
        post_trigger,
        predecessor_epoch_id=predecessor_epoch_id,
    )
    controller_confirmation_step = next(
        (
            item.get("step_index")
            for item in matched
            if item.get("event_type") == "mechanics.change_confirmed"
        ),
        None,
    )
    epoch_open_index = next(
        (
            index
            for index, event in enumerate(post_trigger)
            if event.event_type == "mechanics.epoch_opened"
        ),
        len(post_trigger),
    )
    stale_model_uses, stale_plan_uses, stale_hypothesis_uses = _stale_authority_uses(
        tuple((event.event_type, event.payload) for event in post_trigger),
        epoch_open_index=epoch_open_index,
    )
    candidates = tuple(
        _mapping(item) for item in _sequence(final_projection.get("change_candidates"))
    )
    tested_level_epoch_indices = [
        item.get("epoch_index") for item in epochs if item.get("level_index") == 0
    ]
    false_positive_events = [
        event.event_id for event in post_trigger if event.event_type in _FALSE_POSITIVE_EVENTS
    ]
    post_trigger_consequences = [
        event.event_id for event in post_trigger if event.event_type == "consequence.received"
    ]
    trigger_to_completion = None if trigger_step is None else final_action_count - trigger_step
    if case.kind is RuleChangeCaseKind.NOISE:
        noise_closure = _linked_noise_closure(post_trigger, truth_receipts)
        resolved_noise = any(
            candidate.get("provisional_status") == "RESOLVED_NOISE" for candidate in candidates
        )
        predicates: dict[str, object] = {
            "candidate_resolved_as_noise": resolved_noise,
            "candidate_specific_noise_closure": noise_closure["passed"] is True,
            "completion": completed,
            "completion_within_post_trigger_budget": (
                trigger_to_completion is not None
                and trigger_to_completion <= MAX_POST_TRIGGER_ACTIONS
            ),
            "false_positive_reopenings": not false_positive_events,
            "predecessor_epoch_retained": tested_level_epoch_indices == [0],
            "pulse_resolved": pulse_resolved,
            "third_outcome_trace_coverage": len(post_trigger_consequences) >= 3,
        }
        return {
            "false_positive_event_ids": false_positive_events,
            "noise_closure": noise_closure,
            "post_trigger_consequence_event_ids": post_trigger_consequences,
            "passed": all(value is True for value in predicates.values()),
            "predicates": predicates,
            "trigger_to_completion_actions": trigger_to_completion,
        }
    predicates = {
        "completion": completed,
        "completion_within_post_trigger_budget": (
            trigger_to_completion is not None and trigger_to_completion <= MAX_POST_TRIGGER_ACTIONS
        ),
        "explicit_reexploration": any(
            _event_label(event, predecessor_epoch_id) == "action.selected:reexploration"
            for event in post_trigger
        ),
        "ordered_lifecycle_chain": lifecycle_passed,
        "controller_evaluator_confirmation_agreement": (
            isinstance(controller_confirmation_step, int)
            and controller_confirmation_step == evaluator_confirmation_step
        ),
        "predecessor_history_queryable": len(epochs) >= 2 and bool(candidates),
        "pulse_resolved": pulse_resolved,
        "stale_model_absent": not stale_model_uses,
        "stale_plan_absent": not stale_plan_uses,
        "stale_predecessor_hypothesis_absent": not stale_hypothesis_uses,
        "successor_epoch_retained": tested_level_epoch_indices == [0, 1],
        "third_outcome_trace_coverage": len(post_trigger_consequences) >= 3,
    }
    return {
        "matched_lifecycle": matched,
        "controller_confirmation_step": controller_confirmation_step,
        "evaluator_confirmation_step": evaluator_confirmation_step,
        "lifecycle_link_failures": lifecycle_link_failures,
        "post_trigger_consequence_event_ids": post_trigger_consequences,
        "passed": all(value is True for value in predicates.values()),
        "predicates": predicates,
        "stale_model_uses": stale_model_uses,
        "stale_plan_uses": stale_plan_uses,
        "stale_predecessor_hypothesis_uses": stale_hypothesis_uses,
        "trigger_to_completion_actions": trigger_to_completion,
    }


def _pretrigger_checkpoint_report(
    controller: ARC3Controller, episode: RuleChangeEvaluatorEpisode
) -> dict[str, object]:
    """Prove the frozen plan-only boundary before trigger-eligible selection."""

    readiness = _mapping(_mechanics_projection(controller).get("readiness"))
    expected_domain = (
        "collision_traversability"
        if episode.case.family
        in {
            RuleChangeFamily.TRAVERSABILITY_FLIP,
            RuleChangeFamily.STATIONARY_NOISE,
        }
        else "action_semantics"
    )
    domains = _mapping(readiness.get("active_hypothesis_domains"))
    support_counts = _mapping(readiness.get("active_hypothesis_support_counts"))
    staged_action_payload = _mapping(readiness.get("active_plan_current_step_action"))
    staged_action_name = staged_action_payload.get("name")
    bindings = _mapping(readiness.get("active_action_bindings"))
    staged_action_binding_values = (
        bindings.get(staged_action_name) if isinstance(staged_action_name, str) else None
    )
    staged_action_bindings = {
        item for item in _sequence(staged_action_binding_values) if isinstance(item, str)
    }
    exact_domain_hypotheses = {
        hypothesis_id
        for hypothesis_id, domain in domains.items()
        if isinstance(hypothesis_id, str)
        and domain == expected_domain
        and support_counts.get(hypothesis_id) == episode.case.support_required
    }
    affected_hypotheses = (
        exact_domain_hypotheses
        if episode.case.family
        in {
            RuleChangeFamily.TRAVERSABILITY_FLIP,
            RuleChangeFamily.STATIONARY_NOISE,
        }
        else exact_domain_hypotheses & staged_action_bindings
    )
    events = _events(controller)
    trace_supported_hypotheses = {
        hypothesis_id
        for hypothesis_id in affected_hypotheses
        if len(_support_receipt_ids(events, frozenset({hypothesis_id})))
        == episode.case.support_required
    }
    active_models = {
        item for item in _sequence(readiness.get("active_model_ids")) if isinstance(item, str)
    }
    model_hypotheses = _mapping(readiness.get("active_model_hypothesis_ids"))
    affected_models = {
        model_id
        for model_id in active_models
        if isinstance(model_id, str)
        and {item for item in _sequence(model_hypotheses.get(model_id)) if isinstance(item, str)}
        & trace_supported_hypotheses
    }
    active_plan_model_id = readiness.get("active_plan_model_id")
    active_plan_step_count = readiness.get("active_plan_step_count")
    active_plan_cursor = readiness.get("active_plan_cursor")
    staged_action: ActionRequest | None = None
    if isinstance(staged_action_name, str):
        try:
            action_name = ActionName(staged_action_name)
        except ValueError:
            action_name = None
        if action_name in RULE_CHANGE_ACTIONS and staged_action_payload.get("coordinate") is None:
            assert action_name is not None
            staged_action = ActionRequest(action_name)
    predicates = {
        "action_boundary_open": readiness.get("action_boundary_open") is True,
        "active_plan_current_at_latest_state": (
            readiness.get("active_plan_current_at_latest_state") is True
        ),
        "active_plan_current_step_nontrivial": (
            readiness.get("active_plan_current_step_nontrivial") is True
        ),
        "active_plan_current_step_typed": (
            isinstance(readiness.get("active_plan_current_step_before_state_id"), str)
            and isinstance(readiness.get("active_plan_current_step_predicted_state_id"), str)
            and readiness.get("active_plan_current_step_before_state_id")
            == readiness.get("latest_symbolic_state_id")
            and readiness.get("active_plan_current_step_before_state_id")
            != readiness.get("active_plan_current_step_predicted_state_id")
        ),
        "active_plan_cursor_current": (
            isinstance(active_plan_step_count, int)
            and not isinstance(active_plan_step_count, bool)
            and active_plan_step_count > 0
            and isinstance(active_plan_cursor, int)
            and not isinstance(active_plan_cursor, bool)
            and 0 <= active_plan_cursor < active_plan_step_count
        ),
        "active_plan_dependency_satisfied": (
            isinstance(readiness.get("active_plan_id"), str)
            and active_plan_model_id in affected_models
            and readiness.get("active_plan_dependency_satisfied") is True
        ),
        "active_plan_invalidated": readiness.get("active_plan_invalidated") is False,
        "affected_hypothesis_active_exact_support": bool(affected_hypotheses),
        "affected_hypothesis_trace_support": bool(trace_supported_hypotheses),
        "affected_promoted_model_current": bool(affected_models),
        "calibration_complete": readiness.get("calibration_complete") is True,
        "environment_exact_support_threshold": (
            episode.projection.prechange_support_receipts == episode.case.support_required
        ),
        "evaluator_ready_for_arm": episode.ready_for_evaluator_arm,
        "higher_priority_probe_absent": (readiness.get("higher_priority_probe_present") is False),
        "pending_action_absent": readiness.get("pending_action_present") is False,
        "pending_prediction_absent": (
            readiness.get("pending_prediction_receipt_id") is None
            and not _sequence(readiness.get("pending_prediction_model_ids"))
            and not _sequence(readiness.get("pending_prediction_dependent_plan_ids"))
            and not _sequence(readiness.get("pending_prediction_alternatives"))
            and readiness.get("pending_prediction_nontrivial") is False
        ),
        "staged_action_selectable": (
            staged_action is not None
            and staged_action.name in episode.session.observation.available_actions
        ),
        "staged_action_trigger_eligible": (
            staged_action is not None and episode.trigger_eligible(staged_action)
        ),
    }
    return {
        "affected_hypothesis_ids": sorted(trace_supported_hypotheses),
        "affected_model_ids": sorted(affected_models),
        "expected_hypothesis_domain": expected_domain,
        "mechanics_readiness": dict(readiness),
        "predicates": predicates,
        "ready": all(value is True for value in predicates.values()),
        "staged_action": (_action_payload(staged_action) if staged_action is not None else None),
    }


def _pretrigger_checkpoint_ready(
    controller: ARC3Controller, episode: RuleChangeEvaluatorEpisode
) -> bool:
    report = _pretrigger_checkpoint_report(controller, episode)
    return report["ready"] is True


def _postreopen_checkpoint_ready(controller: ARC3Controller) -> bool:
    projection = _mechanics_projection(controller)
    candidates = tuple(_mapping(item) for item in _sequence(projection.get("change_candidates")))
    epochs = tuple(_mapping(item) for item in _sequence(projection.get("epochs")))
    active_epoch = projection.get("active_epoch_id")
    active_index = next(
        (item.get("epoch_index") for item in epochs if item.get("epoch_id") == active_epoch),
        None,
    )
    return active_index == 1 and any(
        item.get("provisional_status") == "CONFIRMED" for item in candidates
    )


def _checkpoint_bytes(root: Path) -> int:
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file())


def _checkpoint_resource_report(
    *,
    checkpointing: bool,
    boundary_checkpoint_bytes: object,
    final_checkpoint_bytes: object,
) -> dict[str, object]:
    """Apply the frozen limit to each aggregate-root checkpoint measurement."""

    boundary_within_limit = not checkpointing or (
        isinstance(boundary_checkpoint_bytes, int)
        and not isinstance(boundary_checkpoint_bytes, bool)
        and boundary_checkpoint_bytes <= MAX_CHECKPOINT_BYTES
    )
    final_within_limit = not checkpointing or (
        isinstance(final_checkpoint_bytes, int)
        and not isinstance(final_checkpoint_bytes, bool)
        and final_checkpoint_bytes <= MAX_CHECKPOINT_BYTES
    )
    return {
        "boundary_checkpoint_bytes": boundary_checkpoint_bytes,
        "boundary_checkpoint_within_limit": boundary_within_limit,
        "final_checkpoint_bytes": final_checkpoint_bytes,
        "final_checkpoint_within_limit": final_within_limit,
        "limit_bytes": MAX_CHECKPOINT_BYTES,
        "measurement_scope": (
            "aggregate bytes of every file under this execution's checkpoint root at each "
            "measurement; the final measurement includes retained boundary and automatic "
            "checkpoint files"
        ),
        "passed": boundary_within_limit and final_within_limit,
    }


def _checkpoint_commitment_report(
    events: Sequence[TraceEvent], *, envelope: Mapping[str, object]
) -> dict[str, object]:
    """Verify the current receipt while preserving its prior-tail envelope boundary."""

    receipt = events[-1] if events else None
    prior = events[-2] if len(events) >= 2 else None
    payload = receipt.payload if receipt is not None else {}
    envelope_state = _mapping(envelope.get("state"))
    derived_state = _mapping(envelope_state.get("derived_controller_state"))
    planner_state = _mapping(derived_state.get("planner_state"))
    pending_action = _mapping(derived_state.get("pending_action"))
    expected_pending_submitted_id = (
        pending_action.get("submitted_event_id") if pending_action else None
    )
    checkpoint_events = tuple(
        event
        for event in events
        if receipt is not None
        and event.episode_id == receipt.episode_id
        and event.event_type == "run.checkpoint_written"
    )
    predicates = {
        "exact_payload_schema": set(payload) == _CHECKPOINT_COMMITMENT_FIELDS,
        "current_tail_is_commitment_receipt": (
            receipt is not None
            and receipt.event_type == "run.checkpoint_written"
            and receipt.scope == "run"
        ),
        "contiguous_checkpoint_sequence": (
            tuple(event.payload.get("checkpoint_sequence") for event in checkpoint_events)
            == tuple(range(1, len(checkpoint_events) + 1))
            and payload.get("checkpoint_sequence") == len(checkpoint_events)
        ),
        "receipt_immediately_follows_envelope_tail": (
            receipt is not None
            and prior is not None
            and receipt.previous_event_hash == prior.event_hash
            and envelope.get("trace_tail_event_id") == prior.event_id
            and envelope.get("trace_tail_hash") == prior.event_hash
            and payload.get("envelope_prior_trace_tail_event_id") == prior.event_id
            and payload.get("envelope_prior_trace_tail_hash") == prior.event_hash
        ),
        "checkpoint_hash": payload.get("checkpoint_hash") == envelope.get("checkpoint_hash"),
        "checkpoint_schema": (
            payload.get("checkpoint_schema") == envelope.get("schema") == CHECKPOINT_SCHEMA
        ),
        "derived_controller_state_hash": (
            bool(derived_state)
            and payload.get("derived_controller_state_hash") == sha256_json(derived_state)
        ),
        "rng_state_hash": payload.get("rng_state_hash") == sha256_json(envelope.get("rng_state")),
        "source_identity": (
            payload.get("git_commit") == envelope.get("git_commit")
            and payload.get("config_hash") == envelope.get("config_hash")
            and receipt is not None
            and receipt.code_identity.git_commit == envelope.get("git_commit")
            and receipt.code_identity.config_hash == envelope.get("config_hash")
            and receipt.run_id == envelope.get("run_id")
            and receipt.episode_id == envelope.get("episode_id")
            and prior is not None
            and receipt.game_id == prior.game_id
            and receipt.source == prior.source
        ),
        "controller_position": (
            payload.get("derived_controller_schema") == derived_state.get("schema")
            and payload.get("memory_phase") == derived_state.get("phase")
            and payload.get("controller_phase")
            == planner_state.get("controller_phase", derived_state.get("phase"))
            and payload.get("level_index") == derived_state.get("level_index")
            and payload.get("step_index") == derived_state.get("step_index")
            and payload.get("pending_submitted_event_id") == expected_pending_submitted_id
        ),
        "commitment_schema": (payload.get("commitment_schema") == CHECKPOINT_COMMITMENT_SCHEMA),
    }
    return {
        "current_trace_tail_event_hash": receipt.event_hash if receipt is not None else None,
        "current_trace_tail_event_id": receipt.event_id if receipt is not None else None,
        "envelope_prior_trace_tail_event_hash": envelope.get("trace_tail_hash"),
        "envelope_prior_trace_tail_event_id": envelope.get("trace_tail_event_id"),
        "passed": all(predicates.values()),
        "predicates": predicates,
        "receipt": receipt.to_dict() if receipt is not None else None,
    }


def _take_boundary_checkpoint(
    controller: ARC3Controller,
    episode: RuleChangeEvaluatorEpisode,
    *,
    context: RunContext,
    features: PresetFeatures,
    request: _BoundaryRequest,
) -> tuple[ARC3Controller, dict[str, object]]:
    before_projection = _mechanics_projection(controller)
    before_action_effects = controller.action_effect_projection
    submitted_before = _submitted_count(controller)
    checkpoint = controller.checkpoint()
    checkpoint_events = _events(controller)
    commitment = _checkpoint_commitment_report(
        checkpoint_events,
        envelope=checkpoint.envelope.to_dict(),
    )
    checkpoint_bytes = _checkpoint_bytes(context.checkpoint_root)
    record: dict[str, object] = {
        "action_effect_projection": before_action_effects,
        "action_index": episode.projection.action_count,
        "boundary": request.boundary.value,
        "checkpoint_bytes": checkpoint_bytes,
        "checkpoint_file_sha256": sha256_file(checkpoint.path),
        "checkpoint_hash": checkpoint.envelope.checkpoint_hash,
        "checkpoint_path": str(checkpoint.path.resolve()),
        "checkpoint_commitment": commitment,
        "checkpoint_commitment_verified": commitment["passed"] is True,
        "checkpoint_within_limit": checkpoint_bytes <= MAX_CHECKPOINT_BYTES,
        "checkpoint_measurement_scope": (
            "aggregate bytes of every file under this execution's checkpoint root at the boundary"
        ),
        "evaluator_projection": episode.projection.to_dict(),
        "mechanics_projection": before_projection,
        "resumed": request.resume,
        "rng_state_hash": sha256_json(checkpoint.envelope.rng_state),
        "controller_state_hash": sha256_json(checkpoint.envelope.state),
        "current_trace_tail_event_id": commitment["current_trace_tail_event_id"],
        "current_trace_tail_hash": commitment["current_trace_tail_event_hash"],
        "envelope_prior_trace_tail_event_id": checkpoint.envelope.trace_tail_event_id,
        "envelope_prior_trace_tail_hash": checkpoint.envelope.trace_tail_hash,
        "trace_tail_event_id": checkpoint.envelope.trace_tail_event_id,
        "trace_tail_hash": checkpoint.envelope.trace_tail_hash,
        "submitted_before": submitted_before,
    }
    if not request.resume:
        record["submitted_after_restore"] = submitted_before
        record["no_resubmission"] = True
        record["projection_stable_across_restore"] = True
        return controller, record
    controller.journal.close()
    restored = ARC3Controller.restore(
        context,
        preset=ControllerPreset.FULL,
        checkpoint_path=checkpoint.path,
        features=features,
    )
    submitted_after = _submitted_count(restored)
    record["submitted_after_restore"] = submitted_after
    record["no_resubmission"] = submitted_after == submitted_before
    record["projection_stable_across_restore"] = (
        _mechanics_projection(restored) == before_projection
        and restored.action_effect_projection == before_action_effects
    )
    return restored, record


def _case_run_id(case: RuleChangeCase, suffix: str | None = None) -> str:
    base = case.case_id.replace("_", "-")
    return base if suffix is None else f"{base}-{suffix}"


_DYNAMIC_ID_PREFIXES = (
    "E-",
    "H-",
    "action-decision:",
    "consequence-assessment:",
    "evidence:",
    "gev:",
    "goal:",
    "mechanics-change:",
    "plan:",
    "prediction-receipt:",
    "prediction:",
    "retrodiction:",
    "transition:",
    "world-model:",
)

_UNORDERED_DYNAMIC_ID_LIST_KEYS = frozenset(
    {
        "active_goal_ids",
        "active_hypothesis_ids",
        "active_model_ids",
        "affected_hypothesis_ids",
        "affected_model_ids",
        "demoted_model_ids",
        "invalidated_plan_ids",
        "pending_change_candidate_ids",
        "pending_prediction_dependent_plan_ids",
        "pending_prediction_model_ids",
        "suspended_model_ids",
    }
)
_UNORDERED_DYNAMIC_ID_MAPPING_KEYS = frozenset(
    {
        "active_action_bindings",
        "active_model_hypothesis_ids",
        "dependent_plans",
    }
)


def _dynamic_id_namespace(value: str) -> str | None:
    return next(
        (prefix.removesuffix(":-") for prefix in _DYNAMIC_ID_PREFIXES if value.startswith(prefix)),
        None,
    )


def _semantic_identifier_projection(value: object, events: Sequence[TraceEvent]) -> object:
    """Canonicalize runtime identities by first immutable-trace occurrence."""

    identities: dict[str, str] = {}
    counts: Counter[str] = Counter()

    def identity(item: str) -> str:
        namespace = _dynamic_id_namespace(item)
        if namespace is None:
            return item
        if item not in identities:
            counts[namespace] += 1
            identities[item] = f"<{namespace}:{counts[namespace]:04d}>"
        return identities[item]

    def visit(item: object) -> None:
        if isinstance(item, str):
            identity(item)
        elif isinstance(item, Mapping):
            for key, child in item.items():
                identity(str(key))
                visit(child)
        elif isinstance(item, Sequence) and not isinstance(item, (str, bytes)):
            for child in item:
                visit(child)

    for event in events:
        identity(event.event_id)
        visit(event.payload)
    visit(value)

    def project(item: object, path: tuple[str, ...] = ()) -> object:
        if isinstance(item, str):
            return identity(item)
        if isinstance(item, Mapping):
            return {
                identity(str(key)): project(child, (*path, str(key)))
                for key, child in sorted(item.items(), key=lambda pair: str(pair[0]))
            }
        if isinstance(item, Sequence) and not isinstance(item, (str, bytes)):
            projected = [project(child, path) for child in item]
            unordered_dynamic_ids = bool(path) and (
                path[-1] in _UNORDERED_DYNAMIC_ID_LIST_KEYS
                or (len(path) >= 2 and path[-2] in _UNORDERED_DYNAMIC_ID_MAPPING_KEYS)
            )
            if unordered_dynamic_ids and all(isinstance(child, str) for child in projected):
                return sorted(cast(list[str], projected))
            return projected
        return item

    return project(value)


def _decision_payload(decision: ActionDecision) -> dict[str, object]:
    return {
        "action": _action_payload(decision.action),
        "active_goal_ids": list(decision.active_goal_ids),
        "active_hypothesis_ids": list(decision.active_hypothesis_ids),
        "active_world_model_ids": list(decision.active_world_model_ids),
        "decision_id": decision.decision_id,
        "prediction_receipt_id": decision.prediction_receipt_id,
        "rationale_category": decision.rationale_category.value,
        "selected_probe_or_plan_id": decision.selected_probe_or_plan_id,
    }


def _run_case(
    case: RuleChangeCase,
    *,
    root: Path,
    git_commit: str,
    boundary_request: _BoundaryRequest | None = None,
    starting: _CaseStart | None = None,
) -> dict[str, object]:
    checkpointing = boundary_request is not None or starting is not None
    wall_started_ns = time.perf_counter_ns()
    cpu_started_ns = time.process_time_ns()
    prefix_wall_ns = 0
    prefix_cpu_ns = 0
    pending_decision: ActionDecision | None = None
    if starting is None:
        episode = open_rule_change_case(case)
        episode.assert_policy_blinded()
        features = replace(preset_features(ControllerPreset.FULL), use_memory=checkpointing)
        controller = ARC3Controller(ControllerPreset.FULL, features=features)
        run_suffix = None
        if boundary_request is not None:
            run_suffix = (
                f"{boundary_request.boundary.value}-"
                f"{'resumed' if boundary_request.resume else 'uninterrupted'}"
            )
        run_id = _case_run_id(case, run_suffix)
        context = _context(
            root,
            run_id=run_id,
            seed=case.seed,
            git_commit=git_commit,
            checkpointing=checkpointing,
        )
        before_rss = process_memory_sample()
        observations = [episode.session.observation]
        actions: list[dict[str, JSONValue]] = []
        decisions: list[dict[str, object]] = []
        evaluator_trajectory = [episode.projection.to_dict()]
        failures: list[dict[str, object]] = []
        prefix_seal: dict[str, object] | None = None
        readiness_receipt: dict[str, object] | None = None
        boundary: dict[str, object] | None = None
        controller.reset(context)
        controller.observe(episode.session.observation)
    else:
        episode = starting.episode
        episode.assert_policy_blinded()
        controller = starting.controller
        context = starting.context
        features = starting.features
        run_id = starting.run_id
        observations = starting.observations
        actions = starting.actions
        decisions = starting.decisions
        evaluator_trajectory = starting.evaluator_trajectory
        failures = starting.failures
        prefix_seal = starting.prefix_seal
        readiness_receipt = starting.readiness_receipt
        boundary = starting.boundary
        pending_decision = starting.pending_decision
        prefix_wall_ns = starting.prefix_wall_ns
        prefix_cpu_ns = starting.prefix_cpu_ns
        before_rss = starting.before_rss

    while episode.projection.action_count < MAX_ACTIONS and controller.phase not in {
        ControllerPhase.COMPLETE,
        ControllerPhase.GAME_OVER,
        ControllerPhase.FAULTED,
    }:
        try:
            if boundary_request is not None and boundary is None:
                at_boundary = (
                    boundary_request.boundary is CheckpointBoundary.PRE_TRIGGER
                    and _pretrigger_checkpoint_ready(controller, episode)
                ) or (
                    boundary_request.boundary is CheckpointBoundary.POST_REOPEN
                    and _postreopen_checkpoint_ready(controller)
                )
                if at_boundary:
                    controller, boundary = _take_boundary_checkpoint(
                        controller,
                        episode,
                        context=context,
                        features=features,
                        request=boundary_request,
                    )

            decision = pending_decision or controller.choose_action()
            pending_decision = None
            action = decision.action
            candidate_readiness = _readiness_receipt(controller, episode, action)
            if (
                not episode.projection.pulse_armed
                and not episode.projection.pulse_triggered
                and candidate_readiness["ready"] is True
            ):
                prefix_seal = prefix_seal or _capture_prefix(controller)
                episode.arm_trigger()
                if readiness_receipt is not None:
                    candidate_readiness["pretrigger_boundary_readiness"] = readiness_receipt
                readiness_receipt = candidate_readiness
                readiness_receipt["trace_prefix_seal"] = prefix_seal
            evaluated = episode.take(
                action,
                reasoning={
                    "category": "stage06-measurement",
                    "policy_truth_access": False,
                },
            )
            observations.append(evaluated.observation)
            actions.append(_action_payload(action))
            decisions.append(_decision_payload(decision))
            controller.apply_consequence(evaluated.observation)
            evaluator_trajectory.append(episode.projection.to_dict())
            if (
                not episode.projection.pulse_triggered
                and episode.projection.action_count >= MAX_TRIGGER_ACTION
            ):
                failures.append(
                    {
                        "kind": "FAILED_MECHANISM",
                        "message": "frozen trigger was not reached by action 24",
                    }
                )
                break
        except Exception as error:
            failures.append(
                {
                    "kind": type(error).__name__,
                    "message": str(error),
                }
            )
            break

    snapshot = controller.snapshot
    final_mechanics = _mechanics_projection(controller)
    final_action_effects = controller.action_effect_projection
    submitted_final = _submitted_count(controller)
    final_rng_state_hash: str | None = None
    final_controller_state_hash: str | None = None
    final_controller_semantic_state_hash: str | None = None
    final_action_effect_semantic_hash: str | None = None
    final_lifecycle_semantic_hash: str | None = None
    final_checkpoint_hash: str | None = None
    final_checkpoint_file_sha256: str | None = None
    final_checkpoint_bytes: int | None = None
    final_checkpoint_commitment: dict[str, object] | None = None
    controller.close()
    scorecard = episode.session.close()
    final_projection = episode.projection
    trace_hashes = [_trace_frame_hash(item.frames[-1]) for item in observations]
    normalized_hashes = [str(item.frames[-1].digest) for item in observations]
    trace = _trace_report(
        context.trace_root,
        run_id,
        trace_hashes,
        normalized_hashes,
        prefix_seal,
        final_mechanics,
        final_projection.action_count,
        actions,
        final_projection.reset_count,
        scorecard.runs[0].state.value,
        (
            case.case_id,
            str(episode.layout_receipt["layout_id"]),
            *(receipt.receipt_id for receipt in episode.truth_receipts),
            *(receipt.receipt_hash for receipt in episode.truth_receipts),
        ),
    )
    truth = _truth_receipt_report(episode)
    trigger_step = final_projection.trigger_step
    confirmation_step = next(
        (receipt.step for receipt in episode.truth_receipts if receipt.pulse_resolved),
        None,
    )
    prefix_count_value = prefix_seal.get("event_count") if prefix_seal is not None else 0
    prefix_count = (
        prefix_count_value
        if isinstance(prefix_count_value, int) and not isinstance(prefix_count_value, bool)
        else 0
    )
    journal = EventJournal(context.trace_root, run_id=run_id)
    final_events = journal.verify_manifest(include_active=True)
    if checkpointing:
        try:
            final_checkpoint_path = context.checkpoint_root / "latest.json"
            final_checkpoint_value = json.loads(final_checkpoint_path.read_bytes())
            if not isinstance(final_checkpoint_value, dict):
                raise ValueError("final checkpoint envelope is not an object")
            final_checkpoint_envelope = cast(dict[str, object], final_checkpoint_value)
            final_checkpoint_commitment = _checkpoint_commitment_report(
                final_events,
                envelope=final_checkpoint_envelope,
            )
            final_rng_state_hash = sha256_json(final_checkpoint_envelope.get("rng_state"))
            final_controller_state = _mapping(final_checkpoint_envelope.get("state"))
            final_controller_state_hash = sha256_json(final_controller_state)
            final_controller_semantic_state_hash = trace_sha256_bytes(
                trace_canonical_bytes(
                    _semantic_identifier_projection(final_controller_state, final_events)
                )
            )
            final_action_effect_semantic_hash = trace_sha256_bytes(
                trace_canonical_bytes(
                    _semantic_identifier_projection(final_action_effects, final_events)
                )
            )
            final_lifecycle_semantic_hash = trace_sha256_bytes(
                trace_canonical_bytes(
                    _semantic_identifier_projection(final_mechanics, final_events)
                )
            )
            final_checkpoint_hash_value = final_checkpoint_envelope.get("checkpoint_hash")
            final_checkpoint_hash = (
                final_checkpoint_hash_value
                if isinstance(final_checkpoint_hash_value, str)
                else None
            )
            final_checkpoint_file_sha256 = sha256_file(final_checkpoint_path)
            final_checkpoint_bytes = _checkpoint_bytes(context.checkpoint_root)
            if final_checkpoint_commitment["passed"] is not True:
                raise ValueError("final checkpoint commitment receipt failed verification")
        except Exception as error:
            failures.append(
                {
                    "kind": type(error).__name__,
                    "message": f"final checkpoint failed: {error}",
                }
            )
    if boundary is not None:
        shared_seal = _mapping(boundary.get("shared_prefix_seal"))
        boundary["shared_prefix_immutability"] = _verify_prefix(
            context.trace_root,
            final_events,
            shared_seal if shared_seal else None,
        )
    lifecycle = _lifecycle_predicates(
        case=case,
        events=final_events,
        prefix_event_count=prefix_count,
        final_projection=final_mechanics,
        completed=scorecard.runs[0].completed,
        trigger_step=trigger_step,
        final_action_count=final_projection.action_count,
        pulse_resolved=final_projection.pulse_resolved,
        evaluator_confirmation_step=confirmation_step,
        truth_receipts=tuple(receipt.to_dict() for receipt in episode.truth_receipts),
    )
    journal.close()
    trigger_receipts = [
        receipt
        for receipt in episode.truth_receipts
        if receipt.trigger_step == receipt.step and receipt.pulse_triggered
    ]
    trigger_to_confirmation = (
        None
        if trigger_step is None or confirmation_step is None
        else confirmation_step - trigger_step
    )
    wall_ns = prefix_wall_ns + max(0, time.perf_counter_ns() - wall_started_ns)
    cpu_ns = prefix_cpu_ns + max(0, time.process_time_ns() - cpu_started_ns)
    after_rss = process_memory_sample()
    rss = _rss_report(before_rss, after_rss)
    peak = rss.get("process_peak_rss_bytes")
    checkpoint_resources = _checkpoint_resource_report(
        checkpointing=checkpointing,
        boundary_checkpoint_bytes=(
            boundary.get("checkpoint_bytes") if boundary is not None else None
        ),
        final_checkpoint_bytes=final_checkpoint_bytes,
    )
    if boundary is not None:
        boundary["final_checkpoint_bytes"] = final_checkpoint_bytes
        boundary["final_checkpoint_within_limit"] = checkpoint_resources[
            "final_checkpoint_within_limit"
        ]
        boundary["checkpoint_aggregate_measurement_scope"] = checkpoint_resources[
            "measurement_scope"
        ]
    resource_predicates = {
        "actions": final_projection.action_count <= MAX_ACTIONS,
        "checkpoint_bytes": checkpoint_resources["passed"] is True,
        "final_checkpoint_within_limit": checkpoint_resources["final_checkpoint_within_limit"]
        is True,
        "peak_rss": isinstance(peak, int) and peak <= MAX_PEAK_RSS_BYTES,
        "resets": final_projection.reset_count <= MAX_RESETS,
        "trace_bytes": trace["trace_within_limit"] is True,
        "wall": wall_ns <= int(MAX_WALL_SECONDS_PER_EXECUTION * 1_000_000_000),
    }
    core_predicates = {
        "controller_faults": snapshot.fault_count == 0,
        "exactly_one_trigger": len(trigger_receipts) == 1,
        "hard_exposure_deadline": (
            trigger_step is not None and trigger_step <= case.timing.latest_trigger_action
        ),
        "lifecycle": lifecycle["passed"] is True,
        "no_failures": not failures,
        "policy_blinded": True,
        "prefix_immutability": _mapping(trace.get("prefix_immutability")).get("passed") is True,
        "readiness_proved": readiness_receipt is not None,
        "resource_limits": all(resource_predicates.values()),
        "trace_replay": (
            trace["replay_verified"] is True
            and trace["frame_hashes_match_raw_observations"] is True
            and trace["duplicate_event_ids"] == 0
            and trace["duplicate_evidence_receipt_ids"] == 0
        ),
        "truth_receipts": truth["verified"] is True,
    }
    if case.kind is RuleChangeCaseKind.INTERVENTION:
        core_predicates["confirmation_within_budget"] = (
            trigger_to_confirmation is not None
            and trigger_to_confirmation <= MAX_CONFIRMATION_ACTIONS
        )
    else:
        core_predicates["stationary_epoch"] = final_projection.mechanics_epoch == 0
    if checkpointing:
        core_predicates["final_checkpoint_commitment"] = (
            final_checkpoint_commitment is not None
            and final_checkpoint_commitment.get("passed") is True
        )
    if boundary_request is not None:
        core_predicates["checkpoint_boundary_reached"] = boundary is not None
        core_predicates["checkpoint_no_resubmission"] = (
            boundary is not None and boundary.get("no_resubmission") is True
        )
        core_predicates["checkpoint_projection_restore"] = (
            boundary is not None and boundary.get("projection_stable_across_restore") is True
        )
    return {
        "action_count": final_projection.action_count,
        "action_effect_projection": final_action_effects,
        "action_request_sequence": actions,
        "boundary_checkpoint": boundary,
        "case": {
            "action_variant": case.action_variant.value,
            "case_id": case.case_id,
            "family": case.family.value,
            "kind": case.kind.value,
            "palette_variant": case.palette_variant.value,
            "rejection_count": case.rejection_count,
            "seed": case.seed,
            "timing": case.timing.value,
        },
        "case_passed": all(core_predicates.values()),
        "confirmation_step": confirmation_step,
        "controller_fault_count": snapshot.fault_count,
        "cpu_ns": cpu_ns,
        "decisions": decisions,
        "evaluator_trajectory": evaluator_trajectory,
        "failures": failures,
        "final_evaluator_projection": final_projection.to_dict(),
        "final_checkpoint_bytes": final_checkpoint_bytes,
        "final_checkpoint_commitment": final_checkpoint_commitment,
        "final_checkpoint_file_sha256": final_checkpoint_file_sha256,
        "final_checkpoint_hash": final_checkpoint_hash,
        "final_checkpoint_within_limit": checkpoint_resources["final_checkpoint_within_limit"],
        "final_controller_state_hash": final_controller_state_hash,
        "final_controller_semantic_state_hash": final_controller_semantic_state_hash,
        "final_lifecycle_projection": final_mechanics,
        "final_lifecycle_semantic_hash": final_lifecycle_semantic_hash,
        "final_action_effect_semantic_hash": final_action_effect_semantic_hash,
        "final_rng_state_hash": final_rng_state_hash,
        "lifecycle": lifecycle,
        "lifecycle_summary": _lifecycle_summary(final_mechanics, case),
        "predicates": core_predicates,
        "raw_frame_hashes": [str(item.frames[-1].digest) for item in observations],
        "readiness_receipt": readiness_receipt,
        "reset_count": final_projection.reset_count,
        "resource_predicates": resource_predicates,
        "checkpoint_resource_measurement": checkpoint_resources,
        "rss": rss,
        "score": scorecard.score,
        "submitted_action_count": submitted_final,
        "terminal_state": scorecard.runs[0].state.value,
        "trace": trace,
        "trigger_step": trigger_step,
        "trigger_to_confirmation_actions": trigger_to_confirmation,
        "truth": truth,
        "wall_ns": wall_ns,
    }


def _case_from_checkpoint(specification: RuleChangeCheckpointCase) -> RuleChangeCase:
    return next(
        case
        for case in intervention_schedule()
        if case.family is specification.family
        and case.timing is specification.timing
        and case.seed == specification.seed
        and case.palette_variant is specification.palette_variant
        and case.action_variant is specification.action_variant
    )


def _prepare_shared_checkpoint_starts(
    case: RuleChangeCase,
    *,
    root: Path,
    git_commit: str,
    boundary: CheckpointBoundary,
) -> tuple[_CaseStart, _CaseStart]:
    """Drive one prefix, checkpoint it once, then fork evaluator and storage state."""

    source_root = root / "uninterrupted"
    resumed_root = root / "resumed"
    run_id = _case_run_id(case, f"{boundary.value}-shared")
    features = replace(preset_features(ControllerPreset.FULL), use_memory=True)
    context = _context(
        source_root,
        run_id=run_id,
        seed=case.seed,
        git_commit=git_commit,
        checkpointing=True,
    )
    before_rss = process_memory_sample()
    wall_started_ns = time.perf_counter_ns()
    cpu_started_ns = time.process_time_ns()
    episode = open_rule_change_case(case)
    episode.assert_policy_blinded()
    controller = ARC3Controller(ControllerPreset.FULL, features=features)
    controller.reset(context)
    controller.observe(episode.session.observation)
    observations = [episode.session.observation]
    actions: list[dict[str, JSONValue]] = []
    decisions: list[dict[str, object]] = []
    evaluator_trajectory = [episode.projection.to_dict()]
    failures: list[dict[str, object]] = []
    trigger_prefix_seal: dict[str, object] | None = None
    readiness_receipt: dict[str, object] | None = None
    pending_decision: ActionDecision | None = None

    while episode.projection.action_count < MAX_ACTIONS and controller.phase not in {
        ControllerPhase.COMPLETE,
        ControllerPhase.GAME_OVER,
        ControllerPhase.FAULTED,
    }:
        if boundary is CheckpointBoundary.PRE_TRIGGER and _pretrigger_checkpoint_ready(
            controller, episode
        ):
            boundary_readiness_seal = _capture_prefix(controller)
            readiness_receipt = {
                **_pretrigger_checkpoint_report(controller, episode),
                "boundary": boundary.value,
                "trace_prefix_seal": boundary_readiness_seal,
            }
            break
        if boundary is CheckpointBoundary.POST_REOPEN and _postreopen_checkpoint_ready(controller):
            break
        decision = controller.choose_action()
        candidate_readiness = _readiness_receipt(controller, episode, decision.action)
        if (
            not episode.projection.pulse_armed
            and not episode.projection.pulse_triggered
            and candidate_readiness["ready"] is True
        ):
            trigger_prefix_seal = _capture_prefix(controller)
            episode.arm_trigger()
            readiness_receipt = candidate_readiness
            readiness_receipt["trace_prefix_seal"] = trigger_prefix_seal
        evaluated = episode.take(
            decision.action,
            reasoning={
                "category": "stage06-measurement",
                "policy_truth_access": False,
            },
        )
        observations.append(evaluated.observation)
        actions.append(_action_payload(decision.action))
        decisions.append(_decision_payload(decision))
        controller.apply_consequence(evaluated.observation)
        evaluator_trajectory.append(episode.projection.to_dict())
        if (
            not episode.projection.pulse_triggered
            and episode.projection.action_count >= MAX_TRIGGER_ACTION
        ):
            raise RuntimeError("shared checkpoint prefix did not reach the trigger by action 24")

    # A later trigger receipt is not evidence that the frozen pre-choose
    # checkpoint boundary was reached.  Re-evaluate the exact boundary
    # predicate here so a missed boundary fails closed instead of silently
    # checkpointing a completed episode.
    reached = (
        _pretrigger_checkpoint_ready(controller, episode)
        if boundary is CheckpointBoundary.PRE_TRIGGER
        else _postreopen_checkpoint_ready(controller)
    )
    if not reached:
        raise RuntimeError(f"shared checkpoint boundary was not reached: {boundary.value}")

    shared_prefix_seal = _capture_prefix(controller)
    controller, base_record = _take_boundary_checkpoint(
        controller,
        episode,
        context=context,
        features=features,
        request=_BoundaryRequest(boundary, False),
    )
    base_record.update(
        {
            "shared_prefix": True,
            "shared_prefix_seal": shared_prefix_seal,
            "next_action": (
                _action_payload(pending_decision.action) if pending_decision is not None else None
            ),
            "next_action_trigger_eligible": None,
            "dependent_rule_closure": (
                _mapping(readiness_receipt).get("ready") is True
                if boundary is CheckpointBoundary.PRE_TRIGGER
                else None
            ),
        }
    )
    source_checkpoint = Path(cast(str, base_record["checkpoint_path"]))
    checkpoint_relative = source_checkpoint.relative_to(context.checkpoint_root.resolve())
    controller.journal.flush()
    evaluator_fork = episode.fork()
    if resumed_root.exists():
        raise ValueError(f"shared checkpoint resume root already exists: {resumed_root}")
    shutil.copytree(source_root, resumed_root)
    resumed_context = _context(
        resumed_root,
        run_id=run_id,
        seed=case.seed,
        git_commit=git_commit,
        checkpointing=True,
    )
    copied_checkpoint = resumed_context.checkpoint_root / checkpoint_relative
    restored = ARC3Controller.restore(
        resumed_context,
        preset=ControllerPreset.FULL,
        checkpoint_path=copied_checkpoint,
        features=features,
    )
    restored_submitted = _submitted_count(restored)
    resumed_record = dict(base_record)
    resumed_record.update(
        {
            "checkpoint_path": str(copied_checkpoint.resolve()),
            "resumed": True,
            "source_checkpoint_path": str(source_checkpoint.resolve()),
            "submitted_after_restore": restored_submitted,
            "no_resubmission": restored_submitted == base_record["submitted_before"],
            "projection_stable_across_restore": (
                _mechanics_projection(restored) == base_record["mechanics_projection"]
                and restored.action_effect_projection == base_record["action_effect_projection"]
            ),
        }
    )
    prefix_wall_ns = max(0, time.perf_counter_ns() - wall_started_ns)
    prefix_cpu_ns = max(0, time.process_time_ns() - cpu_started_ns)

    def start(
        *,
        branch_episode: RuleChangeEvaluatorEpisode,
        branch_controller: ARC3Controller,
        branch_context: RunContext,
        record: dict[str, object],
    ) -> _CaseStart:
        return _CaseStart(
            episode=branch_episode,
            controller=branch_controller,
            context=branch_context,
            features=features,
            run_id=run_id,
            observations=list(observations),
            actions=[dict(item) for item in actions],
            decisions=[dict(item) for item in decisions],
            evaluator_trajectory=[dict(item) for item in evaluator_trajectory],
            failures=[dict(item) for item in failures],
            prefix_seal=(dict(trigger_prefix_seal) if trigger_prefix_seal is not None else None),
            readiness_receipt=(dict(readiness_receipt) if readiness_receipt is not None else None),
            boundary=record,
            pending_decision=pending_decision,
            prefix_wall_ns=prefix_wall_ns,
            prefix_cpu_ns=prefix_cpu_ns,
            before_rss=dict(before_rss),
        )

    return (
        start(
            branch_episode=episode,
            branch_controller=controller,
            branch_context=context,
            record=base_record,
        ),
        start(
            branch_episode=evaluator_fork,
            branch_controller=restored,
            branch_context=resumed_context,
            record=resumed_record,
        ),
    )


def _canonical_handle(case: RuleChangeCase, value: object) -> object:
    if case.action_variant is not ActionVariant.CYCLE1234 or not isinstance(value, str):
        return value
    return {
        "ACTION1": "ACTION4",
        "ACTION2": "ACTION1",
        "ACTION3": "ACTION2",
        "ACTION4": "ACTION3",
    }.get(value, value)


def _canonical_action_sequence(result: Mapping[str, object]) -> list[object]:
    case_value = _mapping(result.get("case"))
    case = RuleChangeCase(
        case_id=cast(str, case_value["case_id"]),
        kind=RuleChangeCaseKind(cast(str, case_value["kind"])),
        family=RuleChangeFamily(cast(str, case_value["family"])),
        timing=RuleChangeTiming(cast(str, case_value["timing"])),
        seed=cast(int, case_value["seed"]),
        palette_variant=PaletteVariant(cast(str, case_value["palette_variant"])),
        action_variant=ActionVariant(cast(str, case_value["action_variant"])),
    )
    canonical: list[object] = []
    for raw in _sequence(result.get("action_request_sequence")):
        action = dict(_mapping(raw))
        action["name"] = _canonical_handle(case, action.get("name"))
        canonical.append(action)
    return canonical


def _canonical_truth_trajectory(result: Mapping[str, object]) -> list[dict[str, object]]:
    case_value = _mapping(result.get("case"))
    case = RuleChangeCase(
        case_id=cast(str, case_value["case_id"]),
        kind=RuleChangeCaseKind(cast(str, case_value["kind"])),
        family=RuleChangeFamily(cast(str, case_value["family"])),
        timing=RuleChangeTiming(cast(str, case_value["timing"])),
        seed=cast(int, case_value["seed"]),
        palette_variant=PaletteVariant(cast(str, case_value["palette_variant"])),
        action_variant=ActionVariant(cast(str, case_value["action_variant"])),
    )
    truth = _mapping(result.get("truth"))
    canonical: list[dict[str, object]] = []
    for raw in _sequence(truth.get("receipts")):
        receipt = _mapping(raw)
        canonical.append(
            {
                "after_position": receipt.get("after_position"),
                "attempted_cell": receipt.get("attempted_cell"),
                "attempted_role": receipt.get("attempted_role"),
                "coherent_successor_receipts": receipt.get("coherent_successor_receipts"),
                "distinct_successor_evidence": receipt.get("distinct_successor_evidence"),
                "mechanics_epoch": receipt.get("mechanics_epoch"),
                "predecessor_effect": receipt.get("predecessor_effect"),
                "pulse_kind": receipt.get("pulse_kind"),
                "pulse_resolved": receipt.get("pulse_resolved"),
                "realized_effect": receipt.get("realized_effect"),
                "result_kind": receipt.get("result_kind"),
                "resumed_predecessor_receipts": receipt.get("resumed_predecessor_receipts"),
                "successor_evidence_cells": receipt.get("successor_evidence_cells"),
                "successor_evidence_handles": [
                    _canonical_handle(case, item)
                    for item in _sequence(receipt.get("successor_evidence_handles"))
                ],
                "terminal_state": receipt.get("terminal_state"),
            }
        )
    return canonical


def _metamorphic_groups(
    results: Sequence[Mapping[str, object]], *, noise: bool
) -> dict[str, object]:
    groups: dict[tuple[object, ...], list[Mapping[str, object]]] = {}
    for result in results:
        case = _mapping(result.get("case"))
        key = (
            *(
                (case.get("timing"), case.get("seed"))
                if noise
                else (
                    case.get("family"),
                    case.get("timing"),
                    case.get("seed"),
                )
            ),
        )
        groups.setdefault(key, []).append(result)
    records: list[dict[str, object]] = []
    expected_transforms = {
        (palette.value, action.value) for palette in PaletteVariant for action in ActionVariant
    }
    for key, items in sorted(groups.items(), key=lambda item: repr(item[0])):
        reference = items[0]
        reference_actions = _canonical_action_sequence(reference)
        reference_truth = _canonical_truth_trajectory(reference)
        reference_lifecycle = reference.get("lifecycle_summary")
        reference_trigger = reference.get("trigger_step")
        reference_post_actions = (
            cast(int, reference.get("action_count")) - reference_trigger
            if isinstance(reference.get("action_count"), int) and isinstance(reference_trigger, int)
            else None
        )
        predicates = {
            "all_four_transforms": len(items) == 4,
            "exact_2x2_transform_membership": {
                (
                    _mapping(item.get("case")).get("palette_variant"),
                    _mapping(item.get("case")).get("action_variant"),
                )
                for item in items
            }
            == expected_transforms,
            "canonical_action_sequence": all(
                _canonical_action_sequence(item) == reference_actions for item in items
            ),
            "canonical_successor_lifecycle": all(
                item.get("lifecycle_summary") == reference_lifecycle for item in items
            ),
            "canonical_truth_trajectory": all(
                _canonical_truth_trajectory(item) == reference_truth for item in items
            ),
            "completion": all(item.get("terminal_state") == "WIN" for item in items),
            "lifecycle_outcome": all(item.get("case_passed") is True for item in items),
            "post_trigger_action_count": all(
                (
                    cast(int, item.get("action_count")) - cast(int, item.get("trigger_step"))
                    if isinstance(item.get("action_count"), int)
                    and isinstance(item.get("trigger_step"), int)
                    else None
                )
                == reference_post_actions
                for item in items
            ),
            "trigger_receipt_count": all(
                item.get("trigger_step") == reference_trigger for item in items
            ),
        }
        records.append(
            {
                "group": list(key),
                "passed": all(predicates.values()),
                "predicates": predicates,
            }
        )
    return {
        "group_count": len(records),
        "groups": records,
        "passed_groups": sum(item["passed"] is True for item in records),
    }


def _intervention_suite(work_root: Path, git_commit: str) -> dict[str, object]:
    cases = [
        _run_case(
            case,
            root=work_root / case.case_id,
            git_commit=git_commit,
        )
        for case in intervention_schedule()
    ]
    families = Counter(
        _mapping(item["case"]).get("family")
        for item in cases
        if item.get("trigger_step") is not None
    )
    metamorphic = _metamorphic_groups(cases, noise=False)
    return {
        "case_count": len(cases),
        "cases": cases,
        "exercised_by_family": dict(sorted(families.items(), key=lambda item: str(item[0]))),
        "exercised_cases": sum(item["trigger_step"] is not None for item in cases),
        "metamorphic": metamorphic,
        "passed_cases": sum(item["case_passed"] is True for item in cases),
    }


def _noise_suite(work_root: Path, git_commit: str) -> dict[str, object]:
    cases = [
        _run_case(
            case,
            root=work_root / case.case_id,
            git_commit=git_commit,
        )
        for case in noise_control_schedule()
    ]
    false_positives = sum(
        len(_sequence(_mapping(item.get("lifecycle")).get("false_positive_event_ids")))
        for item in cases
    )
    metamorphic = _metamorphic_groups(cases, noise=True)
    return {
        "case_count": len(cases),
        "cases": cases,
        "false_positive_reopenings": false_positives,
        "metamorphic": metamorphic,
        "passed_cases": sum(item["case_passed"] is True for item in cases),
        "resolved_as_noise": sum(
            _mapping(_mapping(item.get("lifecycle")).get("predicates")).get(
                "candidate_resolved_as_noise"
            )
            is True
            for item in cases
        ),
    }


def _checkpoint_pair(
    specification: RuleChangeCheckpointCase,
    *,
    root: Path,
    git_commit: str,
) -> dict[str, object]:
    case = _case_from_checkpoint(specification)
    try:
        uninterrupted_start, resumed_start = _prepare_shared_checkpoint_starts(
            case,
            root=root,
            git_commit=git_commit,
            boundary=specification.boundary,
        )
    except Exception as error:
        return {
            "boundary": specification.boundary.value,
            "case_id": case.case_id,
            "failures": [
                {
                    "kind": type(error).__name__,
                    "message": str(error),
                }
            ],
            "pair_passed": False,
            "predicates": {"shared_prefix_prepared": False},
            "resumed": {},
            "uninterrupted": {},
        }
    uninterrupted = _run_case(
        case,
        root=root / "uninterrupted",
        git_commit=git_commit,
        boundary_request=_BoundaryRequest(specification.boundary, False),
        starting=uninterrupted_start,
    )
    resumed = _run_case(
        case,
        root=root / "resumed",
        git_commit=git_commit,
        boundary_request=_BoundaryRequest(specification.boundary, True),
        starting=resumed_start,
    )
    uninterrupted_boundary = dict(_mapping(uninterrupted.get("boundary_checkpoint")))
    resumed_boundary = dict(_mapping(resumed.get("boundary_checkpoint")))
    uninterrupted["boundary_checkpoint"] = uninterrupted_boundary
    resumed["boundary_checkpoint"] = resumed_boundary
    action_index = uninterrupted_boundary.get("action_index")
    trigger_step = uninterrupted.get("trigger_step")
    truth_receipts = _sequence(_mapping(uninterrupted.get("truth")).get("receipts"))
    resumed_truth_receipts = _sequence(_mapping(resumed.get("truth")).get("receipts"))
    third_outcome_count = sum(
        isinstance(trigger_step, int)
        and isinstance(_mapping(item).get("step"), int)
        and cast(int, _mapping(item).get("step")) >= trigger_step
        for item in truth_receipts
    )
    pretrigger = specification.boundary is CheckpointBoundary.PRE_TRIGGER
    postreopen = specification.boundary is CheckpointBoundary.POST_REOPEN
    uninterrupted_actions = _sequence(uninterrupted.get("action_request_sequence"))
    resumed_actions = _sequence(resumed.get("action_request_sequence"))
    first_uninterrupted_action = (
        uninterrupted_actions[action_index]
        if isinstance(action_index, int) and action_index < len(uninterrupted_actions)
        else None
    )
    first_resumed_action = (
        resumed_actions[action_index]
        if isinstance(action_index, int) and action_index < len(resumed_actions)
        else None
    )
    uninterrupted_postchoose = _mapping(uninterrupted.get("readiness_receipt"))
    resumed_postchoose = _mapping(resumed.get("readiness_receipt"))
    uninterrupted_prechoose = _mapping(
        uninterrupted_postchoose.get("pretrigger_boundary_readiness")
    )
    resumed_prechoose = _mapping(resumed_postchoose.get("pretrigger_boundary_readiness"))
    uninterrupted_prechoose_predicates = _mapping(uninterrupted_prechoose.get("predicates"))
    resumed_prechoose_predicates = _mapping(resumed_prechoose.get("predicates"))
    uninterrupted_postchoose_predicates = _mapping(uninterrupted_postchoose.get("predicates"))
    resumed_postchoose_predicates = _mapping(resumed_postchoose.get("predicates"))
    uninterrupted_prechoose_seal = _mapping(uninterrupted_prechoose.get("trace_prefix_seal"))
    resumed_prechoose_seal = _mapping(resumed_prechoose.get("trace_prefix_seal"))
    uninterrupted_postchoose_seal = _mapping(uninterrupted_postchoose.get("trace_prefix_seal"))
    resumed_postchoose_seal = _mapping(resumed_postchoose.get("trace_prefix_seal"))
    if pretrigger and isinstance(action_index, int):
        first_uninterrupted_truth = (
            _mapping(truth_receipts[action_index]) if action_index < len(truth_receipts) else {}
        )
        first_resumed_truth = (
            _mapping(resumed_truth_receipts[action_index])
            if action_index < len(resumed_truth_receipts)
            else {}
        )
        uninterrupted_boundary["next_action"] = first_uninterrupted_action
        resumed_boundary["next_action"] = first_resumed_action
        uninterrupted_boundary["next_action_trigger_eligible"] = (
            first_uninterrupted_truth.get("pulse_triggered") is True
            and first_uninterrupted_truth.get("trigger_step") == action_index + 1
        )
        resumed_boundary["next_action_trigger_eligible"] = (
            first_resumed_truth.get("pulse_triggered") is True
            and first_resumed_truth.get("trigger_step") == action_index + 1
        )
    predicates = {
        "action_requests_from_boundary": (
            isinstance(action_index, int)
            and _sequence(uninterrupted.get("action_request_sequence"))[action_index:]
            == _sequence(resumed.get("action_request_sequence"))[action_index:]
        ),
        "action_reset_counts": (
            uninterrupted.get("action_count") == resumed.get("action_count")
            and uninterrupted.get("reset_count") == resumed.get("reset_count")
        ),
        "boundary_action_index": (
            action_index is not None and action_index == resumed_boundary.get("action_index")
        ),
        "boundary_evaluator_projection": (
            uninterrupted_boundary.get("evaluator_projection")
            == resumed_boundary.get("evaluator_projection")
        ),
        "boundary_reached": bool(uninterrupted_boundary) and bool(resumed_boundary),
        "boundary_shared_checkpoint": (
            uninterrupted_boundary.get("shared_prefix") is True
            and resumed_boundary.get("shared_prefix") is True
            and uninterrupted_boundary.get("checkpoint_commitment_verified") is True
            and resumed_boundary.get("checkpoint_commitment_verified") is True
            and uninterrupted_boundary.get("checkpoint_commitment")
            == resumed_boundary.get("checkpoint_commitment")
            and uninterrupted_boundary.get("checkpoint_hash")
            == resumed_boundary.get("checkpoint_hash")
            and uninterrupted_boundary.get("checkpoint_file_sha256")
            == resumed_boundary.get("checkpoint_file_sha256")
            and uninterrupted_boundary.get("envelope_prior_trace_tail_event_id")
            == resumed_boundary.get("envelope_prior_trace_tail_event_id")
            and uninterrupted_boundary.get("envelope_prior_trace_tail_hash")
            == resumed_boundary.get("envelope_prior_trace_tail_hash")
            and uninterrupted_boundary.get("current_trace_tail_event_id")
            == resumed_boundary.get("current_trace_tail_event_id")
            and uninterrupted_boundary.get("current_trace_tail_hash")
            == resumed_boundary.get("current_trace_tail_hash")
        ),
        "boundary_prefix_tail_blob_invariants": (
            uninterrupted_boundary.get("shared_prefix_seal")
            == resumed_boundary.get("shared_prefix_seal")
            and uninterrupted_boundary.get("envelope_prior_trace_tail_event_id")
            == _mapping(uninterrupted_boundary.get("shared_prefix_seal")).get("tail_event_id")
            and uninterrupted_boundary.get("envelope_prior_trace_tail_hash")
            == _mapping(uninterrupted_boundary.get("shared_prefix_seal")).get("tail_event_hash")
            and _mapping(
                _mapping(uninterrupted_boundary.get("shared_prefix_immutability")).get("predicates")
            ).get("tail_event_hash")
            is True
            and _mapping(
                _mapping(uninterrupted_boundary.get("shared_prefix_immutability")).get("predicates")
            ).get("tail_event_id")
            is True
            and _mapping(
                _mapping(uninterrupted_boundary.get("shared_prefix_immutability")).get("predicates")
            ).get("blob_references")
            is True
            and _mapping(
                _mapping(resumed_boundary.get("shared_prefix_immutability")).get("predicates")
            ).get("tail_event_hash")
            is True
            and _mapping(
                _mapping(resumed_boundary.get("shared_prefix_immutability")).get("predicates")
            ).get("tail_event_id")
            is True
            and _mapping(
                _mapping(resumed_boundary.get("shared_prefix_immutability")).get("predicates")
            ).get("blob_references")
            is True
        ),
        "checkpoint_hashes_present": (
            isinstance(uninterrupted_boundary.get("checkpoint_hash"), str)
            and isinstance(resumed_boundary.get("checkpoint_hash"), str)
        ),
        "checkpoint_size": (
            uninterrupted_boundary.get("checkpoint_within_limit") is True
            and resumed_boundary.get("checkpoint_within_limit") is True
            and uninterrupted.get("final_checkpoint_within_limit") is True
            and resumed.get("final_checkpoint_within_limit") is True
        ),
        "final_checkpoint_commitments": (
            _mapping(uninterrupted.get("final_checkpoint_commitment")).get("passed") is True
            and _mapping(resumed.get("final_checkpoint_commitment")).get("passed") is True
            and _mapping(uninterrupted.get("final_checkpoint_commitment")).get(
                "envelope_prior_trace_tail_event_hash"
            )
            != _mapping(uninterrupted.get("final_checkpoint_commitment")).get(
                "current_trace_tail_event_hash"
            )
            and _mapping(resumed.get("final_checkpoint_commitment")).get(
                "envelope_prior_trace_tail_event_hash"
            )
            != _mapping(resumed.get("final_checkpoint_commitment")).get(
                "current_trace_tail_event_hash"
            )
        ),
        "final_evaluator_projection": (
            uninterrupted.get("final_evaluator_projection")
            == resumed.get("final_evaluator_projection")
        ),
        "final_lifecycle_projection": (
            uninterrupted.get("lifecycle_summary") == resumed.get("lifecycle_summary")
            and uninterrupted.get("final_lifecycle_semantic_hash")
            == resumed.get("final_lifecycle_semantic_hash")
            and isinstance(uninterrupted.get("final_lifecycle_semantic_hash"), str)
        ),
        "final_action_effect_state": (
            uninterrupted.get("final_action_effect_semantic_hash")
            == resumed.get("final_action_effect_semantic_hash")
            and isinstance(uninterrupted.get("final_action_effect_semantic_hash"), str)
        ),
        "final_controller_full_semantic_state": (
            uninterrupted.get("final_controller_semantic_state_hash")
            == resumed.get("final_controller_semantic_state_hash")
            and isinstance(uninterrupted.get("final_controller_semantic_state_hash"), str)
        ),
        "final_result": (
            uninterrupted.get("terminal_state") == resumed.get("terminal_state")
            and uninterrupted.get("score") == resumed.get("score")
        ),
        "no_resubmission": resumed_boundary.get("no_resubmission") is True,
        "pretrigger_next_action_gate": (
            not pretrigger
            or (
                isinstance(action_index, int)
                and uninterrupted_boundary.get("dependent_rule_closure") is True
                and uninterrupted_prechoose.get("ready") is True
                and resumed_prechoose.get("ready") is True
                and bool(uninterrupted_prechoose_predicates)
                and all(value is True for value in uninterrupted_prechoose_predicates.values())
                and uninterrupted_prechoose_predicates == resumed_prechoose_predicates
                and uninterrupted_prechoose.get("staged_action") == first_uninterrupted_action
                and resumed_prechoose.get("staged_action") == first_resumed_action
                and uninterrupted_postchoose.get("ready") is True
                and resumed_postchoose.get("ready") is True
                and bool(uninterrupted_postchoose_predicates)
                and all(value is True for value in uninterrupted_postchoose_predicates.values())
                and uninterrupted_postchoose_predicates == resumed_postchoose_predicates
                and isinstance(uninterrupted_postchoose.get("pending_prediction_receipt_id"), str)
                and isinstance(resumed_postchoose.get("pending_prediction_receipt_id"), str)
                and uninterrupted_postchoose.get("pending_prediction_model_ids")
                == resumed_postchoose.get("pending_prediction_model_ids")
                and uninterrupted_postchoose.get("pending_prediction_dependent_plan_ids")
                == resumed_postchoose.get("pending_prediction_dependent_plan_ids")
                and uninterrupted_postchoose.get("pending_prediction_alternatives")
                == resumed_postchoose.get("pending_prediction_alternatives")
                and isinstance(uninterrupted_prechoose_seal.get("event_count"), int)
                and isinstance(resumed_prechoose_seal.get("event_count"), int)
                and isinstance(uninterrupted_postchoose_seal.get("event_count"), int)
                and isinstance(resumed_postchoose_seal.get("event_count"), int)
                and cast(int, uninterrupted_postchoose_seal.get("event_count"))
                > cast(int, uninterrupted_prechoose_seal.get("event_count"))
                and cast(int, resumed_postchoose_seal.get("event_count"))
                > cast(int, resumed_prechoose_seal.get("event_count"))
                and uninterrupted_boundary.get("submitted_before") == action_index
                and resumed_boundary.get("submitted_before") == action_index
                and first_uninterrupted_action is not None
                and first_uninterrupted_action == first_resumed_action
                and uninterrupted_boundary.get("next_action") == first_uninterrupted_action
                and resumed_boundary.get("next_action") == first_resumed_action
                and uninterrupted_boundary.get("next_action_trigger_eligible") is True
                and resumed_boundary.get("next_action_trigger_eligible") is True
                and uninterrupted.get("trigger_step") == action_index + 1
                and resumed.get("trigger_step") == action_index + 1
            )
        ),
        "postreopen_third_outcome": (
            third_outcome_count >= 3
            and (
                not postreopen
                or (
                    isinstance(action_index, int)
                    and isinstance(uninterrupted.get("action_count"), int)
                    and cast(int, uninterrupted.get("action_count")) > action_index
                )
            )
        ),
        "raw_consequences": (
            uninterrupted.get("raw_frame_hashes") == resumed.get("raw_frame_hashes")
        ),
        "truth_receipts_from_boundary": (
            isinstance(action_index, int)
            and _canonical_truth_trajectory(uninterrupted)[action_index:]
            == _canonical_truth_trajectory(resumed)[action_index:]
        ),
        "rng_state": (
            uninterrupted_boundary.get("rng_state_hash") == resumed_boundary.get("rng_state_hash")
            and uninterrupted.get("final_rng_state_hash") == resumed.get("final_rng_state_hash")
            and isinstance(uninterrupted.get("final_rng_state_hash"), str)
        ),
        "shared_prefix_immutable": (
            _mapping(uninterrupted_boundary.get("shared_prefix_immutability")).get("passed") is True
            and _mapping(resumed_boundary.get("shared_prefix_immutability")).get("passed") is True
        ),
        "trace_replay": (
            _mapping(uninterrupted.get("trace")).get("replay_verified") is True
            and _mapping(resumed.get("trace")).get("replay_verified") is True
        ),
        "validity": (
            uninterrupted.get("case_passed") is True and resumed.get("case_passed") is True
        ),
    }
    return {
        "boundary": specification.boundary.value,
        "case_id": case.case_id,
        "pair_passed": all(predicates.values()),
        "predicates": predicates,
        "resumed": resumed,
        "uninterrupted": uninterrupted,
    }


def _checkpoint_suite(work_root: Path, git_commit: str) -> dict[str, object]:
    pairs = [
        _checkpoint_pair(
            specification,
            root=work_root
            / f"pair-{index:02d}-{specification.family.value}-{specification.boundary.value}",
            git_commit=git_commit,
        )
        for index, specification in enumerate(checkpoint_schedule())
    ]
    completed_controller_executions = sum(
        bool(_mapping(pair.get(branch)).get("case"))
        for pair in pairs
        for branch in ("uninterrupted", "resumed")
    )
    return {
        "controller_execution_count": completed_controller_executions,
        "logical_pair_count": len(pairs),
        "pairs": pairs,
        "passed_pairs": sum(item["pair_passed"] is True for item in pairs),
        "planned_controller_execution_count": 2 * len(pairs),
        "shared_prefix_preparation_failure_count": sum(
            bool(_sequence(pair.get("failures"))) for pair in pairs
        ),
    }


def _jsonl_objects(path: Path) -> list[dict[str, object]]:
    values: list[dict[str, object]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_number} is not a JSON object")
            values.append(value)
    return values


def _contains_exact_string(value: object, targets: frozenset[str]) -> bool:
    if isinstance(value, str):
        return value in targets
    if isinstance(value, Mapping):
        return any(_contains_exact_string(item, targets) for item in value.values())
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return any(_contains_exact_string(item, targets) for item in value)
    return False


def _holdout_source_bindings(
    *,
    manifest_bytes: bytes,
    stage05_bytes: bytes,
    accepted_stage05_bytes: bytes | None,
    accepted_stage05_blob_oid: str | None,
) -> dict[str, object]:
    """Bind sealed holdout metadata to the frozen manifest and accepted Stage 05 blob."""

    manifest_sha256 = sha256_bytes(manifest_bytes)
    stage05_sha256 = sha256_bytes(stage05_bytes)
    accepted_stage05_sha256 = (
        sha256_bytes(accepted_stage05_bytes) if accepted_stage05_bytes is not None else None
    )
    predicates = {
        "public_partition_manifest_sha256": (manifest_sha256 == PUBLIC_PARTITION_MANIFEST_SHA256),
        "stage05_acceptance_commit_blob_oid": (
            accepted_stage05_blob_oid == STAGE05_EVIDENCE_BLOB_OID
        ),
        "stage05_acceptance_blob_available": accepted_stage05_bytes is not None,
        "stage05_acceptance_blob_sha256": (accepted_stage05_sha256 == STAGE05_EVIDENCE_SHA256),
        "stage05_current_evidence_sha256": stage05_sha256 == STAGE05_EVIDENCE_SHA256,
        "stage05_current_bytes_equal_accepted_blob": (
            accepted_stage05_bytes is not None and stage05_bytes == accepted_stage05_bytes
        ),
    }
    return {
        "accepted_stage05_blob_oid": accepted_stage05_blob_oid,
        "accepted_stage05_commit": STAGE05_ACCEPTANCE_COMMIT,
        "accepted_stage05_sha256": accepted_stage05_sha256,
        "expected_manifest_sha256": PUBLIC_PARTITION_MANIFEST_SHA256,
        "expected_stage05_blob_oid": STAGE05_EVIDENCE_BLOB_OID,
        "expected_stage05_sha256": STAGE05_EVIDENCE_SHA256,
        "manifest_sha256": manifest_sha256,
        "passed": all(predicates.values()),
        "predicates": predicates,
        "stage05_sha256": stage05_sha256,
    }


def _holdout_integrity() -> dict[str, object]:
    manifest_path = ROOT / "docs/evaluation/public-game-partitions.v0.1.json"
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    if not isinstance(manifest, dict):
        raise ValueError("public partition manifest is not an object")
    identities = frozenset(
        str(game["game_id"])
        for game in cast(list[dict[str, object]], manifest["games"])
        if game.get("partition") == "public-holdout"
    )
    ledgers = (
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
    exposure_reports: list[dict[str, object]] = []
    holdout_events = 0
    for label, path, expected_hash in ledgers:
        measured_hash = sha256_file(path) if path.is_file() else None
        values = _jsonl_objects(path) if path.is_file() else []
        matches = sum(_contains_exact_string(value, identities) for value in values)
        holdout_events += matches
        exposure_reports.append(
            {
                "entry_count": len(values),
                "expected_sha256": expected_hash,
                "holdout_event_count": matches,
                "label": label,
                "path": str(path),
                "sha256": measured_hash,
                "verified": measured_hash == expected_hash,
            }
        )
    inherited_path = ROOT / STAGE05_EVIDENCE_PATH
    inherited_bytes = inherited_path.read_bytes()
    inherited = json.loads(inherited_bytes)
    inherited_holdout = _mapping(_mapping(inherited).get("holdout"))
    inherited_assets = inherited_holdout.get("locally_acquired_holdout_assets")
    inherited_holdout_predicates = {
        "accepted_stage05_status": inherited.get("status") == "PASS",
        "build000_exposure_hash": inherited_holdout.get("build_000_exposure_ledger_sha256")
        == ledgers[0][2],
        "holdout_status": inherited_holdout.get("status") == "SEALED_UNCONSUMED",
        "locally_acquired_holdout_assets": inherited_assets == 0,
        "public_holdout_gameplay_events": (
            inherited_holdout.get("public_holdout_gameplay_events") == 0
        ),
        "public_partition_manifest_sha256": (
            inherited_holdout.get("public_partition_manifest_sha256")
            == PUBLIC_PARTITION_MANIFEST_SHA256
        ),
        "stage03_exposure_hash": inherited_holdout.get("stage_03_exposure_ledger_sha256")
        == ledgers[1][2],
        "stage05_public_gameplay_events": (
            inherited_holdout.get("stage_05_public_gameplay_events") == 0
        ),
    }
    accepted_stage05_object = f"{STAGE05_ACCEPTANCE_COMMIT}:{STAGE05_EVIDENCE_PATH.as_posix()}"
    source_bindings = _holdout_source_bindings(
        manifest_bytes=manifest_bytes,
        stage05_bytes=inherited_bytes,
        accepted_stage05_bytes=_git_bytes("cat-file", "blob", accepted_stage05_object),
        accepted_stage05_blob_oid=_git_value("rev-parse", accepted_stage05_object),
    )
    status = (
        "SEALED_UNCONSUMED"
        if len(identities) == 10
        and holdout_events == 0
        and inherited_assets == 0
        and all(inherited_holdout_predicates.values())
        and all(report["verified"] is True for report in exposure_reports)
        and source_bindings["passed"] is True
        else "INTEGRITY_FAILURE"
    )
    return {
        "exposure_ledgers": exposure_reports,
        "holdout_identity_count": len(identities),
        "inherited_asset_check": {
            "locally_acquired_holdout_assets": inherited_assets,
            "path": inherited_path.relative_to(ROOT).as_posix(),
            "passed": all(inherited_holdout_predicates.values()),
            "predicates": inherited_holdout_predicates,
            "sha256": sha256_file(inherited_path),
        },
        "locally_acquired_holdout_assets": inherited_assets,
        "manifest_path": manifest_path.relative_to(ROOT).as_posix(),
        "manifest_sha256": sha256_file(manifest_path),
        "note": (
            "No public asset directory was listed or opened; Stage 06 revalidated only "
            "the sealed manifest, existing exposure ledgers, and inherited Stage 05 metadata."
        ),
        "public_holdout_gameplay_events": holdout_events,
        "source_bindings": source_bindings,
        "status": status,
    }


def _execution_records(
    intervention: Mapping[str, object],
    noise: Mapping[str, object],
    checkpoint: Mapping[str, object],
) -> tuple[Mapping[str, object], ...]:
    records = [
        _mapping(item) for suite in (intervention, noise) for item in _sequence(suite.get("cases"))
    ]
    for raw_pair in _sequence(checkpoint.get("pairs")):
        pair = _mapping(raw_pair)
        records.append(_mapping(pair.get("uninterrupted")))
        records.append(_mapping(pair.get("resumed")))
    return tuple(records)


def _all_failure_records(
    intervention: Mapping[str, object],
    noise: Mapping[str, object],
    checkpoint: Mapping[str, object],
) -> tuple[Mapping[str, object], ...]:
    """Return execution and pair-level preparation failures exactly once."""

    failures = [
        _mapping(failure)
        for execution in _execution_records(intervention, noise, checkpoint)
        for failure in _sequence(execution.get("failures"))
    ]
    failures.extend(
        _mapping(failure)
        for raw_pair in _sequence(checkpoint.get("pairs"))
        for failure in _sequence(_mapping(raw_pair).get("failures"))
    )
    return tuple(failures)


def _infrastructure_failure_count(
    intervention: Mapping[str, object],
    noise: Mapping[str, object],
    checkpoint: Mapping[str, object],
) -> int:
    """Count only host/tooling failures, including shared-prefix preparation failures."""

    return sum(
        failure.get("kind") in _INFRASTRUCTURE_FAILURE_KINDS
        for failure in _all_failure_records(intervention, noise, checkpoint)
    )


def _aggregate_measurements(
    intervention: Mapping[str, object],
    noise: Mapping[str, object],
    checkpoint: Mapping[str, object],
) -> dict[str, object]:
    executions = _execution_records(intervention, noise, checkpoint)
    trace_replay_passed = sum(
        _mapping(item.get("trace")).get("replay_verified") is True
        and _mapping(item.get("trace")).get("frame_hashes_match_raw_observations") is True
        for item in executions
    )
    prefix_passed = sum(
        _mapping(_mapping(item.get("trace")).get("prefix_immutability")).get("passed") is True
        for item in executions
    )
    completed_controller_executions = sum(bool(_mapping(item.get("case"))) for item in executions)
    pair_preparation_failures = sum(
        bool(_sequence(_mapping(item).get("failures")))
        for item in _sequence(checkpoint.get("pairs"))
    )
    return {
        "completed_executions": sum(item.get("terminal_state") == "WIN" for item in executions),
        "controller_execution_count": completed_controller_executions,
        "controller_fault_count": sum(
            cast(int, item.get("controller_fault_count", 0)) for item in executions
        ),
        "environment_action_count": sum(
            cast(int, item.get("action_count", 0)) for item in executions
        ),
        "failure_count": len(_all_failure_records(intervention, noise, checkpoint)),
        "invalid_request_count": sum(
            failure.get("kind") in {"InvalidActionError", "EnvironmentStateError"}
            for failure in _all_failure_records(intervention, noise, checkpoint)
        ),
        "prefix_immutability_passed": prefix_passed,
        "planned_controller_execution_count": len(executions),
        "reset_count": sum(cast(int, item.get("reset_count", 0)) for item in executions),
        "trace_event_count": sum(
            cast(int, _mapping(item.get("trace")).get("event_count", 0)) for item in executions
        ),
        "trace_file_count": sum(
            cast(int, _mapping(item.get("trace")).get("trace_file_count", 0)) for item in executions
        ),
        "trace_replay_passed": trace_replay_passed,
        "truth_receipt_count": sum(
            cast(int, _mapping(item.get("truth")).get("receipt_count", 0)) for item in executions
        ),
        "truth_receipts_verified": sum(
            _mapping(item.get("truth")).get("verified") is True for item in executions
        ),
        "shared_prefix_preparation_failure_count": pair_preparation_failures,
    }


def _resource_summary(
    intervention: Mapping[str, object],
    noise: Mapping[str, object],
    checkpoint: Mapping[str, object],
    *,
    wall_ns: int,
    cpu_ns: int,
) -> dict[str, object]:
    executions = _execution_records(intervention, noise, checkpoint)
    walls = [
        cast(int, item.get("wall_ns"))
        for item in executions
        if isinstance(item.get("wall_ns"), int)
    ]
    peaks = [
        cast(int, _mapping(item.get("rss")).get("process_peak_rss_bytes"))
        for item in executions
        if isinstance(_mapping(item.get("rss")).get("process_peak_rss_bytes"), int)
    ]
    maximum_wall = max(walls) if walls else None
    peak = max(peaks) if peaks else None
    return {
        "cpu_ns": cpu_ns,
        "maximum_execution_wall_limit_seconds": MAX_WALL_SECONDS_PER_EXECUTION,
        "maximum_execution_wall_ns": maximum_wall,
        "maximum_execution_wall_within_limit": (
            maximum_wall is not None
            and maximum_wall <= int(MAX_WALL_SECONDS_PER_EXECUTION * 1_000_000_000)
        ),
        "median_execution_wall_ns": (float(statistics.median(walls)) if walls else None),
        "peak_rss_bytes": peak,
        "peak_rss_limit_bytes": MAX_PEAK_RSS_BYTES,
        "peak_rss_within_limit": peak is not None and peak <= MAX_PEAK_RSS_BYTES,
        "wall_limit_seconds": MAX_WALL_SECONDS_FULL,
        "wall_ns": wall_ns,
        "wall_seconds": wall_ns / 1_000_000_000,
        "wall_within_limit": wall_ns <= int(MAX_WALL_SECONDS_FULL * 1_000_000_000),
    }


def _failed_mechanism_predicates(
    intervention: Mapping[str, object],
    noise: Mapping[str, object],
    static_scan: Mapping[str, object],
) -> dict[str, bool]:
    """Evaluate the frozen mechanism-failure clauses without outcome relabeling."""

    intervention_cases = tuple(_mapping(item) for item in _sequence(intervention.get("cases")))
    noise_cases = tuple(_mapping(item) for item in _sequence(noise.get("cases")))
    expected_exposures = {
        (family.value, timing.value, seed, palette.value, action.value)
        for family in (
            RuleChangeFamily.ACTION_EFFECT_ROTATION,
            RuleChangeFamily.TRAVERSABILITY_FLIP,
        )
        for timing in RuleChangeTiming
        for seed in RULE_CHANGE_SEEDS
        for palette in PaletteVariant
        for action in ActionVariant
    }
    exercised_exposures = {
        (
            case.get("family"),
            case.get("timing"),
            case.get("seed"),
            case.get("palette_variant"),
            case.get("action_variant"),
        )
        for result in intervention_cases
        for case in (_mapping(result.get("case")),)
        if isinstance(result.get("trigger_step"), int)
    }

    def lifecycle_predicate(result: Mapping[str, object], name: str) -> bool:
        lifecycle = _mapping(result.get("lifecycle"))
        return _mapping(lifecycle.get("predicates")).get(name) is True

    family_has_confirmation: dict[str, bool] = {}
    family_has_bounded_adaptation: dict[str, bool] = {}
    for family in (
        RuleChangeFamily.ACTION_EFFECT_ROTATION,
        RuleChangeFamily.TRAVERSABILITY_FLIP,
    ):
        family_cases = tuple(
            result
            for result in intervention_cases
            if _mapping(result.get("case")).get("family") == family.value
        )
        family_has_confirmation[family.value] = any(
            lifecycle_predicate(result, "ordered_lifecycle_chain")
            and lifecycle_predicate(result, "pulse_resolved")
            for result in family_cases
        )
        family_has_bounded_adaptation[family.value] = any(
            lifecycle_predicate(result, "ordered_lifecycle_chain")
            and lifecycle_predicate(result, "completion_within_post_trigger_budget")
            for result in family_cases
        )

    reopened_cases = tuple(
        result
        for result in intervention_cases
        if lifecycle_predicate(result, "successor_epoch_retained")
    )
    stale_authority_retained = any(
        not lifecycle_predicate(result, "stale_model_absent")
        or not lifecycle_predicate(result, "stale_plan_absent")
        or not lifecycle_predicate(result, "stale_predecessor_hypothesis_absent")
        for result in reopened_cases
    )
    predecessor_history_mutated = any(
        isinstance(result.get("trigger_step"), int)
        and _mapping(_mapping(result.get("trace")).get("prefix_immutability")).get("passed")
        is not True
        for result in intervention_cases
    )
    noise_false_positive = cast(int, noise.get("false_positive_reopenings", 0)) > 0 or any(
        _mapping(result.get("final_evaluator_projection")).get("mechanics_epoch") != 0
        for result in noise_cases
    )
    identity_leak = static_scan.get("passed") is not True or any(
        _mapping(_mapping(result.get("trace")).get("observation_blinding")).get("passed")
        is not True
        for result in (*intervention_cases, *noise_cases)
    )
    return {
        "action_or_game_identity_leaked": identity_leak,
        "coherent_successor_unconfirmed_for_a_family": not all(family_has_confirmation.values()),
        "predecessor_history_mutated": predecessor_history_mutated,
        "repair_has_no_bounded_adaptation_for_a_family": not all(
            family_has_bounded_adaptation.values()
        ),
        "required_seed_transform_exposure_missing": exercised_exposures != expected_exposures,
        "single_stationary_outlier_confirmed_epoch": noise_false_positive,
        "stale_authority_retained_after_reopening": stale_authority_retained,
    }


def _classify_stage_status(
    *,
    acceptance_passed: bool,
    failed_mechanism_predicates: Mapping[str, bool],
    infrastructure_failure_count: int,
) -> str:
    """Apply the frozen top-level outcome labels with infrastructure kept narrow."""

    if infrastructure_failure_count > 0:
        return "FAILED_INFRASTRUCTURE"
    if any(failed_mechanism_predicates.values()):
        return "FAILED_MECHANISM"
    return "PASS" if acceptance_passed else "PARTIAL"


def _run_verification_command(
    *,
    check_id: str,
    command: Sequence[str],
    output_root: Path,
    timeout_seconds: float,
) -> dict[str, object]:
    """Run and seal one frozen source/quality check with complete text output."""

    started_ns = time.perf_counter_ns()
    infrastructure_failure = False
    timed_out = False
    try:
        completed = subprocess.run(
            tuple(command),
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
        )
        exit_code: int | None = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr
    except subprocess.TimeoutExpired as error:
        exit_code = None
        stdout = (
            error.stdout
            if isinstance(error.stdout, str)
            else (error.stdout or b"").decode("utf-8", errors="replace")
        )
        captured_stderr = (
            error.stderr
            if isinstance(error.stderr, str)
            else (error.stderr or b"").decode("utf-8", errors="replace")
        )
        timeout_message = f"TimeoutExpired: {error}"
        stderr = (
            f"{captured_stderr.rstrip()}\n{timeout_message}" if captured_stderr else timeout_message
        )
        timed_out = True
    except (OSError, subprocess.SubprocessError) as error:
        exit_code = None
        stdout = ""
        stderr = f"{type(error).__name__}: {error}"
        infrastructure_failure = True
    receipt = seal_object(
        {
            "check_id": check_id,
            "command": list(command),
            "exit_code": exit_code,
            "infrastructure_failure": infrastructure_failure,
            "passed": exit_code == 0 and not infrastructure_failure,
            "stderr": stderr,
            "stderr_sha256": sha256_bytes(stderr.encode("utf-8")),
            "stdout": stdout,
            "stdout_sha256": sha256_bytes(stdout.encode("utf-8")),
            "timed_out": timed_out,
            "timeout_seconds": timeout_seconds,
            "wall_ns": max(0, time.perf_counter_ns() - started_ns),
        },
        hash_field="receipt_hash",
    )
    path = output_root / f"{check_id}.json"
    atomic_write_json(path, receipt)
    return {
        **receipt,
        "artifact_path": str(path.resolve()),
        "artifact_sha256": sha256_file(path),
    }


def _verification_receipts(output_root: Path) -> dict[str, object]:
    """Bind lint, format, strict typing, and focused replay/integration checks."""

    output_root.mkdir(parents=True, exist_ok=True)
    python = str(Path(sys.executable).resolve())
    pytest_basetemp = _verification_pytest_basetemp()
    checks = (
        (
            "ruff-lint",
            (python, "-m", "ruff", "check", "--no-cache", "."),
            120.0,
        ),
        (
            "ruff-format",
            (python, "-m", "ruff", "format", "--check", "--no-cache", "."),
            120.0,
        ),
        (
            "mypy-strict",
            (
                python,
                "-m",
                "mypy",
                "--cache-dir",
                str((output_root / "mypy-cache").resolve()),
                "src",
                "agent",
                "scripts",
            ),
            300.0,
        ),
        (
            "pytest-focused-replay",
            (
                python,
                "-m",
                "pytest",
                "-q",
                *_FOCUSED_VERIFICATION_TESTS,
                "--no-cov",
                "--basetemp",
                str(pytest_basetemp),
            ),
            300.0,
        ),
    )
    receipts = [
        _run_verification_command(
            check_id=check_id,
            command=command,
            output_root=output_root,
            timeout_seconds=timeout,
        )
        for check_id, command, timeout in checks
    ]
    return {
        "check_count": len(receipts),
        "infrastructure_failure_count": sum(
            item["infrastructure_failure"] is True for item in receipts
        ),
        "passed": all(item["passed"] is True for item in receipts),
        "passed_count": sum(item["passed"] is True for item in receipts),
        "receipts": receipts,
    }


def _verification_pytest_basetemp(
    environ: Mapping[str, str] | None = None,
) -> Path:
    """Return a short deterministic pytest root safe for Windows blob paths."""

    variables = os.environ if environ is None else environ
    override = variables.get("ARC3_STAGE06_PYTEST_BASETEMP")
    if override:
        return Path(override).resolve()
    return (Path(gettempdir()) / "arc3-stage06-verification").resolve()


def _competition_integrity_binding(output_root: Path) -> dict[str, object]:
    """Write and bind the broad production competition-integrity receipt."""

    output_root.mkdir(parents=True, exist_ok=True)
    path = output_root / "competition-integrity.json"
    receipt = build_integrity_receipt(ROOT, receipt_output_path=path)
    value = receipt.to_dict()
    atomic_write_json(path, value)
    return {
        "artifact_path": str(path.resolve()),
        "artifact_sha256": sha256_file(path),
        "finding_counts": value.get("finding_counts"),
        "passed": receipt.passed,
        "receipt_sha256": receipt.receipt_sha256,
        "schema": value.get("schema"),
    }


def _action_semantics_binding(output_root: Path) -> dict[str, object]:
    """Write and bind the dedicated raw-action/game-table static receipt."""

    output_root.mkdir(parents=True, exist_ok=True)
    path = output_root / "action-semantics.json"
    receipt = build_action_semantics_receipt(ROOT)
    atomic_write_json(path, receipt)
    return {
        **receipt,
        "artifact_path": str(path.resolve()),
        "artifact_sha256": sha256_file(path),
    }


def measure_rule_change_reopening(
    *,
    work_root: Path,
    command: Sequence[str],
) -> dict[str, object]:
    """Execute the exact frozen Stage 06 synthetic measurement matrix."""

    if work_root.exists():
        if not work_root.is_dir():
            raise ValueError(f"work root is not a directory: {work_root}")
        if any(work_root.iterdir()):
            raise ValueError(f"work root already contains data: {work_root}")
    work_root.mkdir(parents=True, exist_ok=True)
    source_identity = _source_identity()
    if source_identity["dirty_worktree"] is not False:
        raise RuntimeError("Stage 06 acceptance requires a clean committed source tree")
    git_commit = source_identity.get("git_commit")
    if not isinstance(git_commit, str) or not git_commit:
        raise RuntimeError("Stage 06 acceptance requires an available git commit")
    if source_identity.get("predeclaration_sha256") != PREDECLARATION_SHA256:
        raise RuntimeError("Stage 06 frozen predeclaration hash does not match")
    if _git_value("merge-base", "--is-ancestor", STAGE05_ACCEPTANCE_COMMIT, git_commit) is None:
        raise RuntimeError("Stage 06 source must descend from the Stage 05 acceptance checkpoint")

    started_at = _utc_now()
    before_rss = process_memory_sample()
    wall_started_ns = time.perf_counter_ns()
    cpu_started_ns = time.process_time_ns()
    verification = _verification_receipts(work_root / "verification")
    static_scan = _action_semantics_binding(work_root / "verification")
    competition_integrity = _competition_integrity_binding(work_root / "verification")
    with patch(
        "socket.socket",
        side_effect=RuntimeError("Stage 06 competition-mode socket access denied"),
    ) as socket_constructor:
        intervention = _intervention_suite(work_root / "intervention", git_commit)
        noise = _noise_suite(work_root / "stationary-noise", git_commit)
        checkpoint = _checkpoint_suite(work_root / "checkpoint-resume", git_commit)
    socket_guard = {
        "attempt_count": socket_constructor.call_count,
        "network_enabled": False,
        "passed": socket_constructor.call_count == 0,
        "policy": "socket.socket constructor denied during all controller executions",
    }
    aggregate = _aggregate_measurements(intervention, noise, checkpoint)
    holdout = _holdout_integrity()
    cpu_ns = max(0, time.process_time_ns() - cpu_started_ns)
    wall_ns = max(0, time.perf_counter_ns() - wall_started_ns)
    resources = _resource_summary(
        intervention,
        noise,
        checkpoint,
        wall_ns=wall_ns,
        cpu_ns=cpu_ns,
    )
    after_rss = process_memory_sample()
    process_peaks = [
        value
        for value in (
            _rss_value(before_rss, "peak_rss_bytes"),
            _rss_value(after_rss, "peak_rss_bytes"),
            resources.get("peak_rss_bytes"),
        )
        if isinstance(value, int) and not isinstance(value, bool)
    ]
    resources["peak_rss_bytes"] = max(process_peaks) if process_peaks else None
    resources["peak_rss_within_limit"] = (
        bool(process_peaks) and max(process_peaks) <= MAX_PEAK_RSS_BYTES
    )
    source_identity_end = _source_identity()
    source_identity_stability = _source_identity_stability(source_identity, source_identity_end)
    source_identity_pass = source_identity_stability["passed"] is True
    resource_pass = (
        resources["wall_within_limit"] is True
        and resources["maximum_execution_wall_within_limit"] is True
        and resources["peak_rss_within_limit"] is True
    )
    intervention_pass = (
        intervention["case_count"] == 64
        and intervention["exercised_cases"] == 64
        and intervention["passed_cases"] == 64
        and _mapping(intervention.get("metamorphic")).get("passed_groups") == 16
    )
    noise_pass = (
        noise["case_count"] == 32
        and noise["passed_cases"] == 32
        and noise["resolved_as_noise"] == 32
        and noise["false_positive_reopenings"] == 0
        and _mapping(noise.get("metamorphic")).get("passed_groups") == 8
    )
    checkpoint_pass = checkpoint["logical_pair_count"] == 8 and checkpoint["passed_pairs"] == 8
    aggregate_pass = (
        aggregate["planned_controller_execution_count"] == 112
        and aggregate["shared_prefix_preparation_failure_count"] == 0
        and aggregate["controller_execution_count"] == 112
        and aggregate["trace_replay_passed"] == 112
        and aggregate["prefix_immutability_passed"] == 112
        and aggregate["truth_receipts_verified"] == 112
        and aggregate["controller_fault_count"] == 0
        and aggregate["invalid_request_count"] == 0
    )
    integrity_pass = holdout["status"] == "SEALED_UNCONSUMED"
    competition_integrity_pass = competition_integrity["passed"] is True
    verification_pass = verification["passed"] is True
    static_pass = static_scan["passed"] is True and competition_integrity_pass
    socket_pass = socket_guard["passed"] is True
    acceptance_passed = all(
        (
            intervention_pass,
            noise_pass,
            checkpoint_pass,
            aggregate_pass,
            competition_integrity_pass,
            integrity_pass,
            resource_pass,
            source_identity_pass,
            static_pass,
            socket_pass,
            verification_pass,
        )
    )
    mechanism_failures = _failed_mechanism_predicates(intervention, noise, {"passed": static_pass})
    infrastructure_failure_count = _infrastructure_failure_count(
        intervention, noise, checkpoint
    ) + cast(int, verification.get("infrastructure_failure_count", 0))
    status = _classify_stage_status(
        acceptance_passed=acceptance_passed,
        failed_mechanism_predicates=mechanism_failures,
        infrastructure_failure_count=infrastructure_failure_count,
    )
    configuration: dict[str, object] = {
        "controller_executions": 112,
        "controller_executions_are_planned": True,
        "execution_backend": "cpu",
        "hosted_inference": False,
        "max_actions": MAX_ACTIONS,
        "max_checkpoint_bytes": MAX_CHECKPOINT_BYTES,
        "max_confirmation_actions": MAX_CONFIRMATION_ACTIONS,
        "max_coordinate_candidates": MAX_COORDINATE_CANDIDATES,
        "max_parallel_workers": 1,
        "max_peak_rss_bytes": MAX_PEAK_RSS_BYTES,
        "max_post_trigger_actions": MAX_POST_TRIGGER_ACTIONS,
        "max_resets": MAX_RESETS,
        "max_search_depth": MAX_SEARCH_DEPTH,
        "max_search_nodes": MAX_SEARCH_NODES,
        "max_trace_bytes": MAX_TRACE_BYTES,
        "max_trigger_action": MAX_TRIGGER_ACTION,
        "max_wall_seconds_for_full_measurement": MAX_WALL_SECONDS_FULL,
        "max_wall_seconds_per_execution": MAX_WALL_SECONDS_PER_EXECUTION,
        "network_enabled": False,
        "public_assets_allowed": False,
        "public_holdout_allowed": False,
        "raw_observation_or_receipt_mutation_allowed": False,
        "per_execution_wall_scope": (
            "environment/controller initialization (or shared checkpoint prefix) through final "
            "checkpoint, trace sealing and replay, truth-chain verification, and independent "
            "lifecycle fold; this is not policy-only time"
        ),
    }
    report: dict[str, object] = {
        "acceptance": {
            "aggregate_trace_replay_and_immutability": aggregate_pass,
            "checkpoint_resume_pairs": checkpoint_pass,
            "competition_integrity": competition_integrity_pass,
            "holdout_integrity": integrity_pass,
            "intervention_cases": intervention_pass,
            "noise_controls": noise_pass,
            "resource_limits": resource_pass,
            "source_clean": source_identity_pass,
            "source_stable": source_identity_pass,
            "static_action_semantics": static_pass,
            "socket_deny_guard": socket_pass,
            "verification_receipts": verification_pass,
        },
        "aggregate_measurements": aggregate,
        "checkpoint_resume_suite": checkpoint,
        "commands": [list(command)],
        "completed_at": _utc_now(),
        "configuration": configuration,
        "configuration_hash": trace_sha256_bytes(trace_canonical_bytes(configuration)),
        "competition_integrity": competition_integrity,
        "decision_rule": {
            "acceptance_passed": acceptance_passed,
            "failed_mechanism_predicates": mechanism_failures,
            "infrastructure_failure_count": infrastructure_failure_count,
            "resource_miss_is_not_automatically_infrastructure": True,
        },
        "evidence_label": "synthetic",
        "holdout_integrity": holdout,
        "intervention_suite": intervention,
        "limitations": [
            "Synthetic guaranteed exposure does not establish public or hidden-game generalization.",
            "The evaluator controls arming only after trace-proven readiness and never supplies truth to policy.",
            "Whole-process peak RSS can include earlier cases in this single process.",
            "No public game episode, source, asset, adapter, or hosted inference service is used.",
        ],
        "predeclaration": {
            "path": PREDECLARATION.relative_to(ROOT).as_posix(),
            "sha256": sha256_file(PREDECLARATION),
        },
        "resource_measurement": resources,
        "runtime_identity": _runtime_identity(),
        "socket_deny_guard": socket_guard,
        "schema": "arc3.build-001.stage-06-rule-change-reopening.v0.1",
        "source_identity": source_identity,
        "source_identity_end": source_identity_end,
        "source_identity_stability": source_identity_stability,
        "started_at": started_at,
        "static_action_semantics": static_scan,
        "stationary_noise_control_suite": noise,
        "status": status,
        "verification_receipts": verification,
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
    report = measure_rule_change_reopening(work_root=args.work_root, command=command)
    atomic_write_json(args.output, report)
    sys.stdout.write(
        canonical_json_bytes(
            cast(
                dict[str, JSONValue],
                {
                    "artifact_core_hash": report["artifact_core_hash"],
                    "output": str(args.output.resolve()),
                    "schema": report["schema"],
                    "status": report["status"],
                },
            )
        ).decode("utf-8")
    )
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
