"""Explicit Strongwiz/Codex operator boundary for the clean-room experiment.

This module is deliberately not an autonomous competition policy.  A repository-local
JSONL broker supplies one proposal at a time; Strongwiz validates and receipts that
proposal, and the ordinary ARC3 public runner remains the sole environment actuator.
"""

from __future__ import annotations

import importlib
import json
import os
import queue
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Literal, Protocol, TextIO, cast

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, model_validator

from arc3.adapters import GridFrame, Observation, validate_action_request
from arc3.errors import DependencyUnavailableError, EvaluationError, InvalidActionError, PolicyError
from arc3.trace.canonical import canonical_bytes, canonical_json, normalize_json, sha256_json
from arc3.types import ActionName, ActionRequest, Coordinate, JSONValue

OPERATOR_REQUEST_SCHEMA = "arc3.strongwiz-operator-request.v0.1"
OPERATOR_RESPONSE_SCHEMA = "arc3.strongwiz-operator-response.v0.1"
OPERATOR_RECEIPT_SCHEMA = "arc3.strongwiz-operator-receipt.v0.1"

STRONGWIZ_COMMIT = "6944642da7f4f3e6428a597587038c3b365074a5"
STRONGWIZ_TREE = "f9097631fa5c6fb1dcce7756baaa290d76d22d92"
STRONGWIZ_ARCHIVE_SHA256 = "c4f84efa59840b1f77c24a7a0c087bf20665bb6897d7c520264133964a27ef6a"
STRONGWIZ_LICENSE_SHA256 = "2fd30bc85bad18a075a1413785471b245f82cbd5a3d27bf5aecf9edc4eff8138"
STRONGWIZ_DRIVER_ID = "codex-operator-clean-room"

_PROHIBITED_KEYS = frozenset(
    {
        "analysis",
        "chain_of_thought",
        "chain-of-thought",
        "hidden_reasoning",
        "private_reasoning",
        "scratchpad",
    }
)
_MAX_RESPONSE_BYTES = 64 * 1024


class _ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class OperatorCoordinate(_ClosedModel):
    x: StrictInt = Field(ge=0, le=63)
    y: StrictInt = Field(ge=0, le=63)


class OperatorAction(_ClosedModel):
    name: StrictStr
    coordinate: OperatorCoordinate | None = None

    @model_validator(mode="after")
    def validate_coordinate_shape(self) -> OperatorAction:
        requires = self.name == ActionName.ACTION6.value
        if requires != (self.coordinate is not None):
            raise ValueError("ACTION6 alone requires a coordinate")
        return self


class OperatorDistinction(_ClosedModel):
    statement: StrictStr = Field(min_length=1, max_length=512)
    candidate_resolutions: tuple[StrictStr, ...] = Field(min_length=2, max_length=8)
    competing_predictions: tuple[StrictStr, ...] = Field(min_length=2, max_length=8)
    decision_effects: tuple[StrictStr, ...] = Field(min_length=1, max_length=6)
    decision_that_could_change: StrictStr = Field(min_length=1, max_length=512)
    relevance_summary: StrictStr = Field(min_length=1, max_length=512)
    smallest_discriminating_test: StrictStr | None = Field(default=None, max_length=512)
    reopening_condition: StrictStr = Field(min_length=1, max_length=512)


class OperatorPrediction(_ClosedModel):
    expected_consequences: tuple[StrictStr, ...] = Field(min_length=1, max_length=8)
    falsified_by: tuple[StrictStr, ...] = Field(min_length=1, max_length=8)
    alternatives: tuple[StrictStr, ...] = Field(default=(), max_length=8)
    expected_frame_change: StrictBool | None = None
    expected_state: StrictStr | None = None
    expected_level_delta: StrictInt | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def require_machine_checkable_prediction(self) -> OperatorPrediction:
        if (
            self.expected_frame_change is None
            and self.expected_state is None
            and self.expected_level_delta is None
        ):
            raise ValueError("at least one machine-checkable prediction is required")
        return self


class OperatorHypothesis(_ClosedModel):
    hypothesis_id: StrictStr = Field(min_length=1, max_length=128)
    claim: StrictStr = Field(min_length=1, max_length=512)
    components: tuple[StrictStr, ...] = Field(min_length=1, max_length=12)
    status: StrictStr = "candidate"
    evidence_refs: tuple[StrictStr, ...] = Field(default=(), max_length=32)
    conflicting_refs: tuple[StrictStr, ...] = Field(default=(), max_length=32)
    parent_hypothesis_id: StrictStr | None = Field(default=None, max_length=128)
    revision_reason: StrictStr | None = Field(default=None, max_length=512)


class OperatorResponse(_ClosedModel):
    schema_id: StrictStr = Field(alias="schema")
    request_sha256: StrictStr
    sequence: StrictInt = Field(ge=0)
    action: OperatorAction
    distinction: OperatorDistinction
    prediction: OperatorPrediction
    hypotheses: tuple[OperatorHypothesis, ...] = Field(default=(), max_length=24)
    evidence_refs: tuple[StrictStr, ...] = Field(default=(), max_length=64)
    trace_refs: tuple[StrictStr, ...] = Field(default=(), max_length=64)
    residual_refs: tuple[StrictStr, ...] = Field(default=(), max_length=64)
    concise_rationale: StrictStr = Field(min_length=1, max_length=512)
    reversible: StrictBool
    expected_progress_rank: StrictInt = Field(ge=1, le=100)
    information_gain_rank: StrictInt = Field(ge=1, le=100)
    risk_rank: StrictInt = Field(ge=0, le=100)

    @model_validator(mode="after")
    def validate_schema(self) -> OperatorResponse:
        if self.schema_id != OPERATOR_RESPONSE_SCHEMA:
            raise ValueError("unsupported operator response schema")
        return self


class OperatorProvider(Protocol):
    """Return one untrusted operator response for one immutable request."""

    def __call__(self, request: Mapping[str, JSONValue]) -> Mapping[str, object]: ...


@dataclass(frozen=True, slots=True)
class StrongwizSourceIdentity:
    source_root: Path
    archive_path: Path
    commit: str = STRONGWIZ_COMMIT
    tree: str = STRONGWIZ_TREE
    archive_sha256: str = STRONGWIZ_ARCHIVE_SHA256
    license_sha256: str = STRONGWIZ_LICENSE_SHA256


@dataclass(frozen=True, slots=True)
class StrongwizOperatorConfig:
    repository_root: Path
    source: StrongwizSourceIdentity
    run_id: str
    game_id: str
    artifact_root: Path
    protocol_sha256: str
    bridge_commit: str = "synthetic-test-bridge"
    max_actions: int = 4096
    max_resets: int = 64
    checkpoint_actions: int = 80
    checkpoint_resets: int = 8

    def __post_init__(self) -> None:
        root = self.repository_root.resolve()
        source = self.source.source_root.resolve()
        archive = self.source.archive_path.resolve()
        artifacts = self.artifact_root.resolve()
        for label, path in {
            "Strongwiz source": source,
            "Strongwiz archive": archive,
            "artifact root": artifacts,
        }.items():
            if root not in path.parents and path != root:
                raise EvaluationError(f"{label} must remain inside the clean-room checkout")
        if not self.run_id.strip() or not self.game_id.strip() or not self.bridge_commit.strip():
            raise EvaluationError("operator run, game, and bridge identities are required")
        for label, value in {
            "max_actions": self.max_actions,
            "max_resets": self.max_resets,
            "checkpoint_actions": self.checkpoint_actions,
            "checkpoint_resets": self.checkpoint_resets,
        }.items():
            if isinstance(value, bool) or value <= 0:
                raise EvaluationError(f"{label} must be positive")


@dataclass(slots=True)
class _PendingDecision:
    request: dict[str, JSONValue]
    response: OperatorResponse
    action: ActionRequest
    before: Observation
    proposal: Any
    route: Any
    request_receipt_ref: str
    decision_receipt_ref: str


@dataclass(frozen=True, slots=True)
class _ReturnedAuthority:
    observation: Observation
    after_frames: tuple[dict[str, JSONValue], ...]
    raw_payload: dict[str, object]
    raw_ref: str
    raw_receipt_ref: str


@dataclass(frozen=True, slots=True)
class _StrongwizBindings:
    canonical: ModuleType
    contracts: ModuleType
    lab_policy: ModuleType
    ledger: ModuleType
    policy: ModuleType
    routing: ModuleType


def _run_git(source_root: Path, *args: str) -> str:
    completed = subprocess.run(
        ("git", "-C", str(source_root), *args),
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
    )
    return completed.stdout.strip()


def _sha256_file(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_strongwiz_source(identity: StrongwizSourceIdentity) -> dict[str, str]:
    """Fail closed unless the acquired source and archive match the public pin."""

    source = identity.source_root.resolve()
    if not source.is_dir() or not identity.archive_path.is_file():
        raise DependencyUnavailableError("pinned Strongwiz source/archive is unavailable")
    try:
        commit = _run_git(source, "rev-parse", "HEAD^{commit}")
        tree = _run_git(source, "rev-parse", "HEAD^{tree}")
        status = _run_git(source, "status", "--porcelain", "--untracked-files=all")
    except (OSError, subprocess.SubprocessError) as error:
        raise DependencyUnavailableError("cannot verify pinned Strongwiz git identity") from error
    archive_sha256 = _sha256_file(identity.archive_path)
    license_sha256 = _sha256_file(source / "LICENSE")
    if (
        commit != identity.commit
        or tree != identity.tree
        or status
        or archive_sha256 != identity.archive_sha256
        or license_sha256 != identity.license_sha256
    ):
        raise DependencyUnavailableError("pinned Strongwiz source identity changed")
    return {
        "archive_sha256": archive_sha256,
        "commit": commit,
        "license_sha256": license_sha256,
        "tree": tree,
    }


def load_strongwiz(identity: StrongwizSourceIdentity) -> _StrongwizBindings:
    """Load only the verified repository-local Strongwiz implementation."""

    verify_strongwiz_source(identity)
    source_path = str((identity.source_root / "src").resolve())
    if source_path not in sys.path:
        sys.path.insert(0, source_path)
    try:
        package = importlib.import_module("strongwiz")
        package_path = Path(cast(str, package.__file__)).resolve()
        expected = identity.source_root.resolve()
        if expected not in package_path.parents:
            raise DependencyUnavailableError("Strongwiz imported from outside the pinned source")
        return _StrongwizBindings(
            canonical=importlib.import_module("strongwiz.canonical"),
            contracts=importlib.import_module("strongwiz.contracts"),
            lab_policy=importlib.import_module("strongwiz.lab_policy"),
            ledger=importlib.import_module("strongwiz.ledger"),
            policy=importlib.import_module("strongwiz.policy"),
            routing=importlib.import_module("strongwiz.routing"),
        )
    except (ImportError, AttributeError) as error:
        raise DependencyUnavailableError("pinned Strongwiz API is unavailable") from error


class JsonlOperatorProvider:
    """Repository-local JSONL transport with an optional measured-run deadline."""

    def __init__(
        self,
        input_stream: TextIO,
        output_stream: TextIO,
        *,
        deadline_monotonic: float | None = None,
        watchdog: Callable[[], object] | None = None,
        poll_seconds: float = 1.0,
    ) -> None:
        if poll_seconds <= 0:
            raise ValueError("operator transport poll interval must be positive")
        self._input = input_stream
        self._output = output_stream
        self._deadline_monotonic = deadline_monotonic
        self._watchdog = watchdog
        self._poll_seconds = poll_seconds

    def _readline(self) -> str:
        if self._deadline_monotonic is None:
            return self._input.readline(_MAX_RESPONSE_BYTES + 1)

        responses: queue.Queue[tuple[str | None, Exception | None]] = queue.Queue(maxsize=1)

        def read_once() -> None:
            try:
                responses.put((self._input.readline(_MAX_RESPONSE_BYTES + 1), None))
            except Exception as error:
                responses.put((None, error))

        threading.Thread(
            target=read_once,
            name="strongwiz-jsonl-operator-read",
            daemon=True,
        ).start()
        while True:
            if self._watchdog is not None:
                self._watchdog()
            remaining = self._deadline_monotonic - time.monotonic()
            if remaining <= 0:
                raise PolicyError("operator response exhausted the measured-run wall deadline")
            try:
                line, error = responses.get(timeout=min(self._poll_seconds, remaining))
            except queue.Empty:
                continue
            if error is not None:
                raise PolicyError("operator transport failed while reading a response") from error
            if line is None:
                raise PolicyError("operator transport returned no response payload")
            return line

    def __call__(self, request: Mapping[str, JSONValue]) -> Mapping[str, object]:
        self._output.write(canonical_json(request) + "\n")
        self._output.flush()
        line = self._readline()
        if not line:
            raise PolicyError("operator transport closed before a response")
        if len(line.encode("utf-8")) > _MAX_RESPONSE_BYTES:
            raise PolicyError("operator response exceeds the declared byte ceiling")
        try:
            value: object = json.loads(line)
        except json.JSONDecodeError as error:
            raise PolicyError("operator response is not valid JSON") from error
        if not isinstance(value, dict):
            raise PolicyError("operator response must be a JSON object")
        return cast(dict[str, object], value)


def _reject_hidden_reasoning(value: object, *, path: str = "response") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).strip().lower()
            if normalized in _PROHIBITED_KEYS:
                raise PolicyError(f"{path} contains prohibited hidden-reasoning field")
            _reject_hidden_reasoning(item, path=f"{path}.{key}")
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, item in enumerate(value):
            _reject_hidden_reasoning(item, path=f"{path}[{index}]")


def _write_immutable(path: Path, payload: object) -> None:
    encoded = canonical_bytes(payload) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError:
        if path.read_bytes() != encoded:
            raise EvaluationError(f"immutable artifact changed at {path}") from None


def _frame_hex(observation: Observation) -> str:
    return str(observation.frames[-1].digest).removeprefix("sha256:")


def _frame_vector(observation: Observation) -> tuple[str, ...]:
    return tuple(str(frame.digest) for frame in observation.frames)


def _allowed_actions(observation: Observation) -> tuple[ActionName, ...]:
    if observation.state.value in {"GAME_OVER", "NOT_PLAYED"}:
        return (ActionName.RESET,) if ActionName.RESET in observation.available_actions else ()
    if observation.state.value == "WIN":
        return ()
    return observation.available_actions


def _request_frame_ref(request: Mapping[str, JSONValue]) -> str:
    raw_frames = request.get("runtime_frames")
    if not isinstance(raw_frames, list) or not raw_frames:
        raise EvaluationError("Strongwiz observation has no bound runtime frame")
    latest = raw_frames[-1]
    if not isinstance(latest, dict):
        raise EvaluationError("Strongwiz runtime frame projection is malformed")
    raw_ref = latest.get("evidence_ref")
    if (
        not isinstance(raw_ref, str)
        or len(raw_ref) != 64
        or any(character not in "0123456789abcdef" for character in raw_ref)
    ):
        raise EvaluationError("Strongwiz runtime frame has no valid evidence identity")
    return raw_ref


def _action_request(action: OperatorAction) -> ActionRequest:
    try:
        name = ActionName(action.name)
    except ValueError as error:
        raise PolicyError(f"unsupported operator action {action.name!r}") from error
    coordinate = (
        None if action.coordinate is None else Coordinate(action.coordinate.x, action.coordinate.y)
    )
    return ActionRequest(name=name, coordinate=coordinate)


def _model_payload(value: Any) -> dict[str, object]:
    payload = value.model_dump(mode="json", by_alias=True)
    if not isinstance(payload, dict):
        raise EvaluationError("Strongwiz contract did not serialize to an object")
    return cast(dict[str, object], payload)


class StrongwizOperatorPolicy:
    """One-use proposal broker backed by the pinned Strongwiz contract and ledger."""

    manages_trace = False

    def __init__(self, config: StrongwizOperatorConfig, provider: OperatorProvider) -> None:
        self.config = config
        self._provider = provider
        self._bindings = load_strongwiz(config.source)
        self._root = config.repository_root.resolve()
        self._artifacts = config.artifact_root.resolve()
        self._artifacts.mkdir(parents=True, exist_ok=True)
        ledger_type = cast(Any, self._bindings.ledger.SQLiteLedger)
        self._ledger = ledger_type(self._artifacts / "strongwiz-ledger.sqlite3")
        self._router_policy = self._bindings.routing.RouterPolicy()
        self._cadence_policy = self._bindings.policy.CadencePolicy()
        self._cadence_fast_streak = 0
        self._next_structural_novelty = False
        self._next_meaningful_contradiction = False
        self._next_repeated_no_progress = False
        self._active_cadence: Any | None = None
        self._active_cadence_ref: str | None = None
        self._sequence = 0
        self._actions = 0
        self._resets = 0
        self._pending: _PendingDecision | None = None
        self._returned: _ReturnedAuthority | None = None
        self._actuator_phase: Literal["idle", "selected", "submission_started", "returned"] = "idle"
        self._last_receipt_ref: str | None = None
        self._last_assessment_summary: dict[str, JSONValue] | None = None
        self._available_evidence_refs: set[str] = set()
        self._available_trace_refs: set[str] = set()
        self._available_residual_refs: set[str] = set()
        self._hypothesis_refs: dict[str, str] = {}
        self._closed = False
        self._completion_observed = False
        driver_identity = {
            "artifact_binding": "session declaration only; external runtime not hash-bound",
            "driver_id": STRONGWIZ_DRIVER_ID,
            "driver_version": "Codex hosted session; exact model/runtime unavailable to bridge",
            "schema": "arc3.strongwiz-model-driver-identity.v0.1",
        }
        domain_identity = {
            "adapter_id": "arc3.official-normalized-observation-boundary",
            "adapter_version": "arc-agi==0.9.9+arcengine==0.9.3",
            "bridge_commit": config.bridge_commit,
            "schema": "arc3.strongwiz-domain-adapter-identity.v0.1",
        }
        executor_identity = {
            "bridge_commit": config.bridge_commit,
            "executor_id": "arc3.run-public-episode.single-writer",
            "executor_version": "strongwiz-clean-room-v0.1",
            "schema": "arc3.strongwiz-executor-identity.v0.1",
        }
        self._driver_artifact_ref = self._put_object(driver_identity)
        self._domain_artifact_ref = self._put_object(domain_identity)
        self._executor_artifact_ref = self._put_object(executor_identity)
        self._router_policy_ref = self._put_object(_model_payload(self._router_policy))
        self._cadence_policy_ref = self._put_object(_model_payload(self._cadence_policy))
        source_receipt = {
            "archive_sha256": config.source.archive_sha256,
            "bridge_commit": config.bridge_commit,
            "cadence_policy_ref": self._cadence_policy_ref,
            "commit": config.source.commit,
            "decision_provider": "external-hosted-codex-operator",
            "decision_provider_claim_ceiling": (
                "the external Codex model/runtime is session-declared and is not bound by a "
                "repository artifact hash"
            ),
            "domain_adapter_artifact_ref": self._domain_artifact_ref,
            "environment_acquisition_network_mode": "official-public-normal",
            "environment_runtime_network_mode": "offline-local",
            "executor_artifact_ref": self._executor_artifact_ref,
            "game_id": config.game_id,
            "model_driver_artifact_ref": self._driver_artifact_ref,
            "policy_network_mode": "external-hosted-codex-operator",
            "protocol_sha256": config.protocol_sha256,
            "router_policy_ref": self._router_policy_ref,
            "run_id": config.run_id,
            "schema": "arc3.strongwiz-runtime-source.v0.1",
            "strongwiz_integration_scope": {
                "used": [
                    "typed contracts",
                    "content identities",
                    "two-speed cadence policy",
                    "PEA-PECAN lab policy",
                    "hard-guard routing",
                    "append-only SQLite ledger",
                ],
                "unused": [
                    "ReasoningSession",
                    "GrantRegistry",
                    "ExecutionCoordinator",
                    "FactStore",
                    "MechanicLedger",
                    "GoalGraph",
                ],
            },
            "tree": config.source.tree,
        }
        source_ref = self._put_object(source_receipt)
        self._append(
            "runtime.source",
            source_receipt,
            object_refs=(
                source_ref,
                self._driver_artifact_ref,
                self._domain_artifact_ref,
                self._executor_artifact_ref,
                self._router_policy_ref,
                self._cadence_policy_ref,
            ),
        )

    @property
    def completion_genuinely_observed(self) -> bool:
        return self._completion_observed

    @property
    def actions(self) -> int:
        return self._actions

    @property
    def resets(self) -> int:
        return self._resets

    @property
    def has_pending_action(self) -> bool:
        return self._pending is not None

    @property
    def actuator_phase(self) -> str:
        return self._actuator_phase

    @property
    def environment_effect_unknown(self) -> bool:
        return self._actuator_phase == "submission_started"

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def ledger_path(self) -> Path:
        return self._artifacts / "strongwiz-ledger.sqlite3"

    def _put_object(self, payload: object) -> str:
        return cast(str, self._ledger.put_object(payload))

    def _append(
        self,
        kind: str,
        payload: Mapping[str, object],
        *,
        object_refs: tuple[str, ...] = (),
    ) -> str:
        parents = () if self._last_receipt_ref is None else (self._last_receipt_ref,)
        envelope = self._ledger.append(
            occurrence_id=f"{self.config.run_id}:{self._sequence:08d}:{kind}",
            kind=kind,
            account_id=self.config.run_id,
            account_version=0,
            payload=payload,
            object_refs=tuple(dict.fromkeys(object_refs)),
            parent_refs=parents,
        )
        receipt_ref = cast(str, envelope.receipt_id)
        self._last_receipt_ref = receipt_ref
        self._available_trace_refs.add(receipt_ref)
        return receipt_ref

    def _frame_payload(self, frame: GridFrame) -> dict[str, object]:
        cells = frame.cells
        digest = str(frame.digest)
        return {
            "cells": [list(row) for row in cells],
            "digest": digest,
            "height": frame.height,
            "palette": list(frame.palette),
            "schema": "arc3.runtime-frame.v0.1",
            "width": frame.width,
        }

    def _store_frames(self, observation: Observation) -> tuple[dict[str, JSONValue], ...]:
        frames: list[dict[str, JSONValue]] = []
        for frame in observation.frames:
            payload = self._frame_payload(frame)
            frame_hex = str(frame.digest).removeprefix("sha256:")
            relative = Path("frames") / f"{frame_hex}.json"
            _write_immutable(self._artifacts / relative, payload)
            object_ref = self._put_object(payload)
            self._available_evidence_refs.add(object_ref)
            normalized = normalize_json(
                {
                    "cells": payload["cells"],
                    "digest": payload["digest"],
                    "evidence_ref": object_ref,
                    "height": payload["height"],
                    "path": relative.as_posix(),
                    "width": payload["width"],
                }
            )
            if not isinstance(normalized, dict):
                raise EvaluationError("frame request projection is not an object")
            frames.append(normalized)
        return tuple(frames)

    def _operator_request(self, observation: Observation) -> dict[str, JSONValue]:
        frames = self._store_frames(observation)
        cadence_signals = self._bindings.policy.CadenceSignals(
            startup_uncertainty=self._sequence == 0,
            structural_novelty=self._next_structural_novelty,
            meaningful_contradiction=self._next_meaningful_contradiction,
            repeated_no_progress=self._next_repeated_no_progress,
            fast_streak=self._cadence_fast_streak,
        )
        cadence = self._cadence_policy.select(cadence_signals)
        self._active_cadence = cadence
        self._active_cadence_ref = self._put_object(_model_payload(cadence))
        self._cadence_fast_streak = cadence.fast_streak_after
        self._next_structural_novelty = False
        self._next_meaningful_contradiction = False
        self._next_repeated_no_progress = False
        raw_body: dict[str, object] = {
            "available_actions": [item.value for item in _allowed_actions(observation)],
            "decision_provider": "external-hosted-codex-operator",
            "game_id": str(observation.game_id),
            "instructions": {
                "completion_authority": "GameState.WIN only",
                "game_over_rule": "RESET only while GAME_OVER is current",
                "hidden_reasoning": "do not provide; use concise auditable fields only",
                "one_action": True,
            },
            "last_assessment": self._last_assessment_summary,
            "levels_completed": observation.levels_completed,
            "operator_response_schema": OPERATOR_RESPONSE_SCHEMA,
            "prior_hypothesis_refs": dict(sorted(self._hypothesis_refs.items())),
            "protocol_sha256": self.config.protocol_sha256,
            "remaining": {
                "actions": max(0, self.config.max_actions - self._actions),
                "resets": max(0, self.config.max_resets - self._resets),
            },
            "response_contract": {
                "action_coordinate_rule": (
                    "coordinate is null except ACTION6, which requires exact integer x and y"
                ),
                "allowed_decision_effects": [
                    "plan",
                    "risk",
                    "candidate_choice",
                    "experiment_choice",
                    "resource",
                    "access",
                    "hazard",
                    "movement",
                    "progress",
                    "output",
                ],
                "allowed_hypothesis_statuses": [
                    "candidate",
                    "supported",
                    "narrowed",
                    "contradicted",
                    "parked",
                    "superseded",
                ],
                "prediction_requirement": (
                    "supply expected consequences and falsifiers plus at least one of "
                    "expected_frame_change, expected_state, or expected_level_delta"
                ),
                "required_top_level_fields": [
                    "schema",
                    "request_sha256",
                    "sequence",
                    "action",
                    "distinction",
                    "prediction",
                    "hypotheses",
                    "evidence_refs",
                    "trace_refs",
                    "residual_refs",
                    "concise_rationale",
                    "reversible",
                    "expected_progress_rank",
                    "information_gain_rank",
                    "risk_rank",
                ],
            },
            "run_id": self.config.run_id,
            "runtime_frames": list(frames),
            "schema": OPERATOR_REQUEST_SCHEMA,
            "sequence": self._sequence,
            "state": observation.state.value,
            "strongwiz": {
                "cadence": _model_payload(cadence),
                "cadence_instruction": (
                    "deep: foreground novel distinctions or prediction residuals; "
                    "fast: use retained mechanics for the shortest credible progress action"
                ),
                "cadence_policy_ref": self._cadence_policy_ref,
                "cadence_selection_ref": self._active_cadence_ref,
                "commit": self.config.source.commit,
                "router_policy_ref": self._router_policy_ref,
                "tree": self.config.source.tree,
            },
            "win_levels": observation.win_levels,
        }
        body = normalize_json(raw_body)
        if not isinstance(body, dict):
            raise EvaluationError("operator request body is not an object")
        body["request_sha256"] = sha256_json(body)
        return body

    def _parse_response(
        self, raw: Mapping[str, object], request: Mapping[str, JSONValue]
    ) -> OperatorResponse:
        _reject_hidden_reasoning(raw)
        try:
            response = OperatorResponse.model_validate(raw)
        except ValueError as error:
            raise PolicyError(f"operator response failed schema validation: {error}") from error
        expected_ref = request.get("request_sha256")
        if response.request_sha256 != expected_ref or response.sequence != self._sequence:
            raise PolicyError("operator response is stale or bound to another request")
        return response

    def _strongwiz_observation(
        self,
        observation: Observation,
        request: Mapping[str, JSONValue],
        *,
        epoch: int | None = None,
    ) -> Any:
        contracts = self._bindings.contracts
        observation_epoch = self._sequence if epoch is None else epoch
        frame_ref = _request_frame_ref(request)
        evidence_ref = contracts.EvidenceRef(
            kind="arc3-runtime-frame",
            digest=frame_ref,
            locator=f"frames/{_frame_hex(observation)}.json",
        )
        return contracts.Observation(
            observation_id=f"{self.config.run_id}:observation:{observation_epoch:08d}",
            domain="ARC-AGI-3-local-public",
            scope_id=(
                f"{self.config.game_id}:level:{observation.levels_completed}:"
                f"epoch:{observation_epoch}"
            ),
            epoch=observation_epoch,
            payload_ref=evidence_ref,
            summary=(
                f"state={observation.state.value}; levels_completed="
                f"{observation.levels_completed}; win_levels={observation.win_levels}; "
                f"frame={_frame_hex(observation)}"
            ),
            available_action_names=tuple(item.value for item in _allowed_actions(observation)),
        )

    def _strongwiz_goal(self, sw_observation: Any) -> tuple[Any, Any]:
        contracts = self._bindings.contracts
        governing = contracts.Goal(
            goal_id=f"{self.config.run_id}:goal:win",
            statement="Reach the environment-authoritative GameState.WIN",
            scope_id=self.config.game_id,
            success_condition="the returned official environment state is WIN",
            reopening_condition="any non-WIN returned state or later contradiction",
        )
        scoped = contracts.Goal(
            goal_id=f"{self.config.run_id}:goal:step:{self._sequence:08d}",
            statement="Choose the next action that best serves authoritative WIN",
            scope_id=sw_observation.scope_id,
            parent_goal_id=governing.goal_id,
            governing_goal_id=governing.goal_id,
            motivating_uncertainty="the next environment consequence is not yet observed",
            decision_that_could_change="the next one-action proposal",
            smallest_sufficient_test="one legal action followed by its returned consequence",
            success_condition="the action yields progress or discriminating evidence",
            abandonment_condition="the environment returns WIN or no legal action exists",
            reopening_condition="a prediction residual changes the implicated model component",
        )
        return governing, scoped

    def _route_response(
        self,
        observation: Observation,
        request: Mapping[str, JSONValue],
        response: OperatorResponse,
        action: ActionRequest,
    ) -> tuple[Any, Any, tuple[str, ...]]:
        contracts = self._bindings.contracts
        sw_observation = self._strongwiz_observation(observation, request)
        governing, scoped = self._strongwiz_goal(sw_observation)
        effects = tuple(
            contracts.DecisionEffect(item) for item in response.distinction.decision_effects
        )
        distinction = contracts.Distinction(
            distinction_id=f"{self.config.run_id}:distinction:{self._sequence:08d}",
            statement=response.distinction.statement,
            scope_id=sw_observation.scope_id,
            parent_goal_id=scoped.goal_id,
            governing_goal_id=governing.goal_id,
            candidate_resolutions=response.distinction.candidate_resolutions,
            competing_predictions=response.distinction.competing_predictions,
            decision_effects=effects,
            decision_that_could_change=response.distinction.decision_that_could_change,
            relevance_summary=response.distinction.relevance_summary,
            smallest_discriminating_test=response.distinction.smallest_discriminating_test,
            reopening_condition=response.distinction.reopening_condition,
        )
        action_parameters: dict[str, object] = {}
        if action.coordinate is not None:
            action_parameters = {"x": action.coordinate.x, "y": action.coordinate.y}
        action_spec = contracts.ActionSpec(name=action.name.value, parameters=action_parameters)
        response_hypothesis_ids = [item.hypothesis_id for item in response.hypotheses]
        if len(response_hypothesis_ids) != len(set(response_hypothesis_ids)):
            raise PolicyError("operator response repeats a hypothesis identity")
        known_hypothesis_ids = set(self._hypothesis_refs)
        response_hypothesis_id_set = set(response_hypothesis_ids)
        hypothesis_refs: list[str] = []
        for item in response.hypotheses:
            if not set(item.evidence_refs).issubset(self._available_evidence_refs):
                raise PolicyError("hypothesis cites evidence outside the current aperture")
            allowed_conflicts = self._available_evidence_refs | self._available_residual_refs
            if not set(item.conflicting_refs).issubset(allowed_conflicts):
                raise PolicyError("hypothesis cites conflicts outside the current aperture")
            if item.parent_hypothesis_id is not None and item.parent_hypothesis_id not in (
                known_hypothesis_ids | response_hypothesis_id_set
            ):
                raise PolicyError("hypothesis revision cites an unknown parent")
            hypothesis = contracts.Hypothesis(
                hypothesis_id=item.hypothesis_id,
                claim=item.claim,
                scope_id=sw_observation.scope_id,
                components=item.components,
                status=item.status,
                evidence_refs=item.evidence_refs,
                conflicting_refs=item.conflicting_refs,
                parent_hypothesis_id=item.parent_hypothesis_id,
                revision_reason=item.revision_reason,
            )
            ref = self._put_object(_model_payload(hypothesis))
            self._hypothesis_refs[item.hypothesis_id] = ref
            self._available_evidence_refs.add(ref)
            hypothesis_refs.append(ref)
        prediction = contracts.Prediction(
            prediction_id=f"{self.config.run_id}:prediction:{self._sequence:08d}",
            hypothesis_refs=tuple(hypothesis_refs),
            expected_consequences=response.prediction.expected_consequences,
            falsified_by=response.prediction.falsified_by,
            alternatives=response.prediction.alternatives,
        )
        requested_evidence = tuple(dict.fromkeys(response.evidence_refs))
        requested_trace = tuple(dict.fromkeys(response.trace_refs))
        requested_residual = tuple(dict.fromkeys(response.residual_refs))
        if not set(requested_evidence).issubset(self._available_evidence_refs):
            raise PolicyError("proposal cites evidence outside the current Strongwiz aperture")
        if not set(requested_trace).issubset(self._available_trace_refs):
            raise PolicyError("proposal cites trace outside the current Strongwiz aperture")
        if not set(requested_residual).issubset(self._available_residual_refs):
            raise PolicyError("proposal cites residuals outside the current Strongwiz aperture")
        observation_ref = sw_observation.digest
        evidence_refs = tuple(
            dict.fromkeys(
                (sw_observation.payload_ref.sha256, *requested_evidence, *hypothesis_refs)
            )
        )
        proposal = contracts.CandidateProposal(
            proposal_id=f"{self.config.run_id}:proposal:{self._sequence:08d}",
            model_driver_id=STRONGWIZ_DRIVER_ID,
            observation_id=sw_observation.observation_id,
            observation_ref=observation_ref,
            scope_id=sw_observation.scope_id,
            goal_id=scoped.goal_id,
            goal_ref=scoped.digest,
            action=action_spec,
            meaningful_distinction=distinction,
            prediction=prediction,
            decision_effects=effects,
            evidence_refs=evidence_refs,
            trace_refs=requested_trace,
            residual_refs=requested_residual,
            concise_rationale=response.concise_rationale,
            reversible=response.reversible,
            expected_progress_rank=response.expected_progress_rank,
            information_gain_rank=response.information_gain_rank,
            risk_rank=response.risk_rank,
            costs=contracts.CostVector(environment_actions=1),
        )
        grant_payload = {
            "action_ref": proposal.action.digest,
            "domain_adapter_artifact_ref": self._domain_artifact_ref,
            "executor_artifact_ref": self._executor_artifact_ref,
            "grantor": "Christopher D. Pang active owner directive",
            "model_driver_artifact_ref": self._driver_artifact_ref,
            "proposal_ref": proposal.digest,
            "scope_id": proposal.scope_id,
            "schema": "arc3.external-execution-grant.v0.1",
        }
        grant_ref = self._put_object(grant_payload)
        lab = self._bindings.lab_policy
        output_destination_ref = self._put_object(
            {
                "destination": "official local-public ARC-AGI-3 session",
                "schema": "arc3.environment-destination.v0.1",
            }
        )
        human_responsibility_ref = self._put_object(
            {
                "responsible_steward": "Christopher D. Pang",
                "schema": "arc3.human-responsibility.v0.1",
            }
        )
        context = lab.LabBoundaryContext(
            grant_ref=grant_ref,
            task_id=self.config.run_id,
            goal_id=scoped.goal_id,
            goal_ref=scoped.digest,
            scope_id=proposal.scope_id,
            observation_id=proposal.observation_id,
            observation_ref=proposal.observation_ref,
            proposal_ref=proposal.digest,
            action_ref=proposal.action.digest,
            output_destination_ref=output_destination_ref,
            attention_budget=0,
        )
        pea_review = lab.PEAReview(
            boundary_context_ref=context.digest,
            external_grant_ref=grant_ref,
            consent=lab.ReviewStatus.NOT_APPLICABLE,
            standing=lab.ReviewStatus.SUPPLIED,
            privacy=lab.ReviewStatus.NOT_APPLICABLE,
            reversibility=lab.ReviewStatus.SUPPLIED,
            remedy=lab.ReviewStatus.SUPPLIED,
            contestability=lab.ReviewStatus.SUPPLIED,
            refusal=lab.ReviewStatus.SUPPLIED,
            human_responsibility_ref=human_responsibility_ref,
        )
        description_ref = self._put_object(
            {
                "description": "submit one exact legal action to the declared public game",
                "schema": "arc3.pecan-description.v0.1",
            }
        )
        recommendation_ref = self._put_object(
            {
                "recommendation": response.concise_rationale,
                "schema": "arc3.pecan-recommendation.v0.1",
            }
        )
        permission_ref = self._put_object(
            {
                "permission": "public non-holdout development play",
                "schema": "arc3.pecan-permission.v0.1",
            }
        )
        crossing = lab.ConsequentialCrossing(
            boundary_context_ref=context.digest,
            subject_ref=proposal.action.digest,
            description_ref=description_ref,
            recommendation_ref=recommendation_ref,
            permission_ref=permission_ref,
            authorization_ref=grant_ref,
            current_stage=lab.CrossingStage.AUTHORIZATION,
            externally_supplied_authorization=True,
        )
        lab_decision = lab.evaluate_lab_rules(
            context=context,
            pea_review=pea_review,
            crossing=crossing,
            seed_release=None,
            external_effect_requested=True,
            release_requested=False,
        )
        if not lab_decision.clears_requested_boundaries:
            raise PolicyError("Strongwiz PEA/PECAN lab policy did not clear the exact action")
        lab_boundary = lab_decision.external_effect_binding
        if lab_boundary is None or lab_boundary.status is not contracts.BoundaryStatus.CLEAR:
            raise PolicyError("Strongwiz lab policy returned no exact clear action binding")
        control = contracts.ControlSnapshot(
            account_id=self.config.run_id,
            account_version=0,
            observation_id=proposal.observation_id,
            observation_ref=proposal.observation_ref,
            scope_id=proposal.scope_id,
            active_goal_ids=(scoped.goal_id,),
            active_goal_refs=(scoped.digest,),
            available_evidence_refs=evidence_refs,
            available_trace_refs=requested_trace,
            available_residual_refs=requested_residual,
            allowed_action_names=tuple(item.value for item in _allowed_actions(observation)),
            allowed_action_refs=(proposal.action.digest,),
            remaining_budget=contracts.CostVector(
                environment_actions=max(0, self.config.max_actions - self._actions),
            ),
            lab_boundary=lab_boundary,
            execution_grant_ref=grant_ref,
            serial_token=cast(str, request["request_sha256"]),
            shadow_only=False,
        )
        route = self._bindings.routing.evaluate_proposal(
            proposal,
            control,
            policy=self._router_policy,
        )
        if route.disposition.value not in {"admit", "reopen"}:
            raise PolicyError(f"Strongwiz route did not admit proposal: {route.disposition.value}")
        if route.selected_proposal_ref != proposal.digest:
            raise PolicyError("Strongwiz route did not bind the exact proposal")
        objects = (
            sw_observation,
            governing,
            scoped,
            distinction,
            prediction,
            action_spec,
            proposal,
            context,
            pea_review,
            crossing,
            lab_decision,
            lab_boundary,
            control,
            route,
        )
        object_refs = tuple(self._put_object(_model_payload(item)) for item in objects)
        return (
            proposal,
            route,
            tuple(
                dict.fromkeys(
                    (
                        *object_refs,
                        grant_ref,
                        output_destination_ref,
                        human_responsibility_ref,
                        description_ref,
                        recommendation_ref,
                        permission_ref,
                    )
                )
            ),
        )

    def select(self, observation: Observation) -> ActionRequest:
        if self._closed:
            raise PolicyError("closed Strongwiz operator policy cannot select")
        if self._pending is not None:
            raise PolicyError("one pending action must be assessed before another selection")
        if self._actions >= self.config.max_actions:
            raise PolicyError("Strongwiz operator action safety ceiling exhausted")
        if self._resets >= self.config.max_resets and observation.state.value == "GAME_OVER":
            raise PolicyError("Strongwiz operator reset safety ceiling exhausted")
        request = self._operator_request(observation)
        request_ref = self._put_object(request)
        request_receipt = self._append(
            "operator.request",
            cast(dict[str, object], request),
            object_refs=(request_ref,),
        )
        raw = self._provider(request)
        response = self._parse_response(raw, request)
        action = _action_request(response.action)
        if action.name not in _allowed_actions(observation):
            advertised = ", ".join(item.value for item in _allowed_actions(observation)) or "none"
            raise InvalidActionError(
                f"{action.name.value} is outside the Strongwiz legal action aperture; "
                f"available actions: {advertised}"
            )
        validate_action_request(observation, action)
        if action.name is ActionName.RESET and self._resets >= self.config.max_resets:
            raise PolicyError("Strongwiz operator reset safety ceiling exhausted")
        proposal, route, route_object_refs = self._route_response(
            observation, request, response, action
        )
        response_payload = response.model_dump(mode="json", by_alias=True)
        response_ref = self._put_object(response_payload)
        self._append(
            "operator.response",
            response_payload,
            object_refs=(response_ref,),
        )
        decision_payload = {
            "action_ref": proposal.action.digest,
            "cadence_ref": self._active_cadence_ref,
            "decision_provider": "external-hosted-codex-operator",
            "domain_adapter_artifact_ref": self._domain_artifact_ref,
            "executor_artifact_ref": self._executor_artifact_ref,
            "model_driver_artifact_ref": self._driver_artifact_ref,
            "proposal_ref": proposal.digest,
            "request_ref": request_ref,
            "route_ref": route.digest,
            "router_policy_ref": self._router_policy_ref,
            "schema": "arc3.strongwiz-decision.v0.1",
            "sequence": self._sequence,
        }
        decision_ref = self._put_object(decision_payload)
        decision_receipt = self._append(
            "strongwiz.decision",
            decision_payload,
            object_refs=tuple(
                dict.fromkeys(
                    (
                        decision_ref,
                        response_ref,
                        *((self._active_cadence_ref,) if self._active_cadence_ref else ()),
                        *route_object_refs,
                    )
                )
            ),
        )
        self._pending = _PendingDecision(
            request=request,
            response=response,
            action=action,
            before=observation,
            proposal=proposal,
            route=route,
            request_receipt_ref=request_receipt,
            decision_receipt_ref=decision_receipt,
        )
        self._actuator_phase = "selected"
        return action

    def _prediction_checks(
        self, pending: _PendingDecision, after: Observation
    ) -> tuple[dict[str, bool], bool]:
        prediction = pending.response.prediction
        level_delta = after.levels_completed - pending.before.levels_completed
        frame_changed = _frame_vector(after) != _frame_vector(pending.before)
        checks: dict[str, bool] = {}
        if prediction.expected_frame_change is not None:
            checks["frame_change"] = frame_changed is prediction.expected_frame_change
        if prediction.expected_state is not None:
            checks["state"] = after.state.value == prediction.expected_state
        if prediction.expected_level_delta is not None:
            checks["level_delta"] = level_delta == prediction.expected_level_delta
        return checks, all(checks.values())

    def mark_submission_started(self) -> None:
        if self._pending is None or self._actuator_phase != "selected":
            raise PolicyError("Strongwiz submission marker has no selected action")
        self._actuator_phase = "submission_started"

    def mark_environment_returned(self, observation: Observation) -> None:
        pending = self._pending
        if pending is None or self._actuator_phase != "submission_started":
            raise PolicyError("Strongwiz returned marker has no submitted action")
        self._actuator_phase = "returned"
        self._completion_observed = self._completion_observed or observation.state.value == "WIN"
        if pending.action.name is ActionName.RESET:
            self._resets += 1
        else:
            self._actions += 1
        after_frames = self._store_frames(observation)
        raw_payload = {
            "action": {
                "coordinate": (
                    None
                    if pending.action.coordinate is None
                    else {
                        "x": pending.action.coordinate.x,
                        "y": pending.action.coordinate.y,
                    }
                ),
                "name": pending.action.name.value,
            },
            "after_frame": _frame_hex(observation),
            "after_frames": list(_frame_vector(observation)),
            "available_actions": [item.value for item in observation.available_actions],
            "before_frame": _frame_hex(pending.before),
            "before_frames": list(_frame_vector(pending.before)),
            "levels_completed": observation.levels_completed,
            "legal_action_aperture": [item.value for item in _allowed_actions(observation)],
            "runtime_frames": list(after_frames),
            "schema": "arc3.returned-consequence.v0.1",
            "sequence": self._sequence,
            "state": observation.state.value,
            "win_levels": observation.win_levels,
        }
        raw_ref = self._put_object(raw_payload)
        self._available_evidence_refs.add(raw_ref)
        raw_receipt = self._append(
            "environment.consequence",
            raw_payload,
            object_refs=(raw_ref,),
        )
        self._returned = _ReturnedAuthority(
            observation=observation,
            after_frames=after_frames,
            raw_payload=raw_payload,
            raw_ref=raw_ref,
            raw_receipt_ref=raw_receipt,
        )

    def accept_consequence(self, observation: Observation) -> None:
        pending = self._pending
        if pending is None:
            raise PolicyError("Strongwiz received a consequence without a pending proposal")
        if self._actuator_phase == "selected":
            self.mark_submission_started()
        if self._actuator_phase == "submission_started":
            self.mark_environment_returned(observation)
        returned = self._returned
        if returned is None or returned.observation != observation:
            raise PolicyError("Strongwiz assessment does not match the returned observation")
        after_frames = returned.after_frames
        raw_ref = returned.raw_ref
        raw_receipt = returned.raw_receipt_ref
        checks, matched = self._prediction_checks(pending, observation)
        residual_ref: str | None = None
        if not matched:
            residual = {
                "checks": checks,
                "implicated_prediction_ref": pending.proposal.prediction.digest,
                "reopening_rule": "revise only the smallest implicated hypothesis component",
                "schema": "arc3.strongwiz-prediction-residual.v0.1",
                "sequence": self._sequence,
            }
            residual_ref = self._put_object(residual)
            self._available_residual_refs.add(residual_ref)
        contracts = self._bindings.contracts
        before_observation = self._strongwiz_observation(
            pending.before,
            pending.request,
            epoch=self._sequence,
        )
        after_projection = normalize_json({"runtime_frames": list(after_frames)})
        if not isinstance(after_projection, dict):
            raise EvaluationError("returned frame projection is not an object")
        sw_after = self._strongwiz_observation(
            observation,
            after_projection,
            epoch=self._sequence + 1,
        )
        sw_after_ref = self._put_object(_model_payload(sw_after))
        if sw_after_ref != sw_after.digest:
            raise EvaluationError("stored returned Strongwiz observation identity changed")
        observed = (
            f"frame_changed={_frame_vector(observation) != _frame_vector(pending.before)}",
            f"state={observation.state.value}",
            (f"level_delta={observation.levels_completed - pending.before.levels_completed}"),
        )
        outcome = contracts.Outcome(
            outcome_id=f"{self.config.run_id}:outcome:{self._sequence:08d}",
            observation_before_id=before_observation.observation_id,
            observation_before_ref=before_observation.digest,
            observation_after_id=sw_after.observation_id,
            observation_after_ref=sw_after.digest,
            action=pending.proposal.action,
            observed_consequences=observed,
            state_label=observation.state.value,
            evidence_refs=(raw_ref,),
            terminal=observation.state.value == "WIN",
        )
        outcome_ref = self._put_object(_model_payload(outcome))
        assessment = {
            "checks": checks,
            "completion_genuinely_observed": observation.state.value == "WIN",
            "consequence_receipt_ref": raw_receipt,
            "matched_prediction": matched,
            "outcome_ref": outcome_ref,
            "proposal_ref": pending.proposal.digest,
            "residual_ref": residual_ref,
            "schema": "arc3.strongwiz-assessment.v0.1",
            "sequence": self._sequence,
        }
        assessment_ref = self._put_object(assessment)
        self._append(
            "strongwiz.assessment",
            assessment,
            object_refs=tuple(
                ref
                for ref in (assessment_ref, outcome_ref, sw_after_ref, residual_ref)
                if ref is not None
            ),
        )
        self._last_assessment_summary = cast(dict[str, JSONValue], normalize_json(assessment))
        self._completion_observed = self._completion_observed or observation.state.value == "WIN"
        was_reset = pending.action.name is ActionName.RESET
        frame_or_level_progress = (
            _frame_vector(observation) != _frame_vector(pending.before)
            or observation.levels_completed > pending.before.levels_completed
        )
        self._next_structural_novelty = (
            observation.levels_completed > pending.before.levels_completed
        )
        self._next_meaningful_contradiction = not matched
        self._next_repeated_no_progress = (
            not was_reset
            and not frame_or_level_progress
            and observation.state.value == pending.before.state.value
        )
        self._sequence += 1
        self._pending = None
        self._returned = None
        self._actuator_phase = "idle"
        checkpoint_due = (
            was_reset and self._resets > 0 and self._resets % self.config.checkpoint_resets == 0
        ) or (
            not was_reset
            and self._actions > 0
            and self._actions % self.config.checkpoint_actions == 0
        )
        if checkpoint_due:
            checkpoint_count, checkpoint_head = self._ledger.verify()
            checkpoint = {
                "actions": self._actions,
                "ledger_head": checkpoint_head,
                "ledger_receipts": checkpoint_count,
                "resets": self._resets,
                "schema": "arc3.strongwiz-runtime-checkpoint.v0.1",
                "sequence": self._sequence,
            }
            checkpoint_ref = self._put_object(checkpoint)
            checkpoint_receipt_ref = self._append(
                "run.checkpoint",
                checkpoint,
                object_refs=(checkpoint_ref,),
            )
            checkpoint["checkpoint_receipt_ref"] = checkpoint_receipt_ref
            _write_immutable(
                self._artifacts / "checkpoints" / f"{self._sequence:08d}.json",
                checkpoint,
            )

    def close(self) -> None:
        if self._closed:
            return
        if self._pending is not None:
            raise PolicyError("cannot close Strongwiz with an unassessed environment action")
        preseal_count, preseal_head = self._ledger.verify()
        final_payload = {
            "actions": self._actions,
            "completion_genuinely_observed": self._completion_observed,
            "preseal_ledger_head": preseal_head,
            "preseal_ledger_receipts": preseal_count,
            "resets": self._resets,
            "schema": "arc3.strongwiz-run-final.v0.1",
        }
        final_ref = self._put_object(final_payload)
        final_receipt_ref = self._append(
            "run.final",
            final_payload,
            object_refs=(final_ref,),
        )
        count, head = self._ledger.verify()
        receipt = {
            "actions": self._actions,
            "cadence_policy_ref": self._cadence_policy_ref,
            "completion_genuinely_observed": self._completion_observed,
            "decision_provider": "external-hosted-codex-operator",
            "domain_adapter_artifact_ref": self._domain_artifact_ref,
            "environment_acquisition_network_mode": "official-public-normal",
            "environment_runtime_network_mode": "offline-local",
            "executor_artifact_ref": self._executor_artifact_ref,
            "game_id": self.config.game_id,
            "final_receipt_ref": final_receipt_ref,
            "ledger_head": head,
            "ledger_receipts": count,
            "model_driver_artifact_ref": self._driver_artifact_ref,
            "policy_network_mode": "external-hosted-codex-operator",
            "protocol_sha256": self.config.protocol_sha256,
            "resets": self._resets,
            "run_id": self.config.run_id,
            "router_policy_ref": self._router_policy_ref,
            "schema": OPERATOR_RECEIPT_SCHEMA,
            "strongwiz_commit": self.config.source.commit,
        }
        receipt["receipt_sha256"] = sha256_json(receipt)
        _write_immutable(self._artifacts / "operator-receipt.json", receipt)
        self._ledger.close()
        self._closed = True

    def abort(self, *, reason: str, environment_effect_unknown: bool) -> None:
        """Seal a failed boundary without pretending a pending effect was assessed."""

        if self._closed:
            return
        payload = {
            "environment_effect_unknown": environment_effect_unknown,
            "actuator_phase": self._actuator_phase,
            "pending_proposal_ref": (
                None if self._pending is None else self._pending.proposal.digest
            ),
            "reason": reason,
            "schema": "arc3.strongwiz-operator-abort.v0.1",
            "sequence": self._sequence,
        }
        payload_ref = self._put_object(payload)
        self._append("run.abort", payload, object_refs=(payload_ref,))
        self._pending = None
        self._returned = None
        self._actuator_phase = "idle"
        self.close()


__all__ = [
    "OPERATOR_REQUEST_SCHEMA",
    "OPERATOR_RESPONSE_SCHEMA",
    "STRONGWIZ_ARCHIVE_SHA256",
    "STRONGWIZ_COMMIT",
    "STRONGWIZ_TREE",
    "JsonlOperatorProvider",
    "StrongwizOperatorConfig",
    "StrongwizOperatorPolicy",
    "StrongwizSourceIdentity",
    "verify_strongwiz_source",
]
