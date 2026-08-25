"""Budgeted four-variant observation-only curriculum runner."""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import cast

from arc3.adapters import Observation
from arc3.evaluation.build003_results import FAMILIES, CurriculumResultRow
from arc3.mechanics import CHANNEL_ORDER, CompositionMode
from arc3.types import ActionName, ActionRequest, Coordinate, GameStateName

from .broker import PolicyProcess, observation_from_bytes, observation_to_bytes
from .engine import CurriculumSession
from .models import CurriculumSpec, CurriculumVariant
from .protocol import (
    PROTOCOL_V0_1,
    ProtocolBudgets,
    ProtocolDefinition,
    SourceIdentity,
    protocol_definition,
)

# Legacy aliases remain explicit for v0.1 evidence readers. Protocol v0.2 resolves
# its own Stage 01 identity from ``ProtocolDefinition`` and never uses these defaults.
BUILD002_COMMIT = PROTOCOL_V0_1.baseline.commit
BUILD002_TREE = PROTOCOL_V0_1.baseline.tree


@dataclass(frozen=True, slots=True)
class SequenceBudgets:
    max_environment_actions: int = 1500
    max_environment_actions_per_level: int | None = None
    max_resets: int = 10
    max_wall_clock_seconds: float = 120.0
    max_peak_memory_bytes: int = 1_073_741_824
    policy_cycle_seconds: float = 10.0

    def __post_init__(self) -> None:
        integer_bounds = (
            self.max_environment_actions,
            self.max_resets,
            self.max_peak_memory_bytes,
        )
        if any(isinstance(value, bool) or value <= 0 for value in integer_bounds):
            raise ValueError("sequence integer budgets must be positive")
        if self.max_environment_actions_per_level is not None and (
            isinstance(self.max_environment_actions_per_level, bool)
            or self.max_environment_actions_per_level <= 0
        ):
            raise ValueError("per-level action budget must be positive when present")
        if self.max_wall_clock_seconds <= 0 or self.policy_cycle_seconds <= 0:
            raise ValueError("sequence time budgets must be positive")


def _sequence_budgets(values: ProtocolBudgets) -> SequenceBudgets:
    return SequenceBudgets(
        max_environment_actions=values.max_environment_actions,
        max_environment_actions_per_level=values.max_environment_actions_per_level,
        max_resets=values.max_resets,
        max_wall_clock_seconds=values.max_wall_clock_seconds,
        max_peak_memory_bytes=values.max_peak_memory_bytes,
        policy_cycle_seconds=values.policy_cycle_seconds,
    )


def budgets_for_protocol(protocol: ProtocolDefinition | str) -> SequenceBudgets:
    """Return the immutable executable bounds for an explicit protocol."""

    return _sequence_budgets(protocol_definition(protocol).budgets)


DEFAULT_SEQUENCE_BUDGETS = budgets_for_protocol(PROTOCOL_V0_1)


@dataclass(frozen=True, slots=True)
class SequenceExecution:
    rows: tuple[CurriculumResultRow, ...]
    receipt: dict[str, object]


class FrozenBuild002Error(RuntimeError):
    """Exact frozen worker rejected or could not execute one request."""


def _action_from_object(value: object) -> ActionRequest:
    if not isinstance(value, dict):
        raise FrozenBuild002Error("frozen worker action is not an object")
    name = value.get("name")
    if not isinstance(name, str):
        raise FrozenBuild002Error("frozen worker action name is invalid")
    raw_coordinate = value.get("coordinate")
    coordinate = None
    if raw_coordinate is not None:
        if not isinstance(raw_coordinate, dict):
            raise FrozenBuild002Error("frozen worker coordinate is invalid")
        x, y = raw_coordinate.get("x"), raw_coordinate.get("y")
        if not isinstance(x, int) or isinstance(x, bool):
            raise FrozenBuild002Error("frozen worker x coordinate is invalid")
        if not isinstance(y, int) or isinstance(y, bool):
            raise FrozenBuild002Error("frozen worker y coordinate is invalid")
        coordinate = Coordinate(x, y)
    return ActionRequest(ActionName(name), coordinate)


class FrozenBuild002Process:
    """Line-delimited subprocess whose imports resolve from the exact frozen tree."""

    def __init__(
        self,
        *,
        source_root: Path,
        storage_root: Path,
        source_identity: SourceIdentity,
        python_executable: Path | None = None,
    ) -> None:
        worker = Path(__file__).with_name("frozen_build002_worker.py")
        self._process = subprocess.Popen(
            [
                str(python_executable or Path(sys.executable)),
                str(worker),
                "--source-root",
                str(source_root),
                "--storage-root",
                str(storage_root),
                "--expected-commit",
                source_identity.commit,
                "--expected-tree",
                source_identity.tree,
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )
        ready = self._receive()
        if (
            ready.get("schema") != "arc3.build003.frozen-build002-ready.v0.1"
            or ready.get("source_commit") != source_identity.commit
            or ready.get("source_tree") != source_identity.tree
            or ready.get("source_clean") is not True
        ):
            self.close()
            raise FrozenBuild002Error("frozen worker source identity receipt mismatch")
        arc3_file = ready.get("arc3_file")
        if not isinstance(arc3_file, str) or not Path(arc3_file).resolve().is_relative_to(
            (source_root / "src").resolve()
        ):
            self.close()
            raise FrozenBuild002Error("frozen worker imported ARC3 outside the frozen source root")
        self.ready_receipt = ready

    @property
    def process_id(self) -> int:
        return self._process.pid

    def _receive(self) -> dict[str, object]:
        if self._process.stdout is None:
            raise FrozenBuild002Error("frozen worker stdout is unavailable")
        line = self._process.stdout.readline()
        if not line:
            stderr = ""
            if self._process.stderr is not None:
                stderr = self._process.stderr.read().strip()
            raise FrozenBuild002Error(f"frozen worker exited without a receipt: {stderr}")
        value = json.loads(line)
        if not isinstance(value, dict):
            raise FrozenBuild002Error("frozen worker response is not an object")
        return cast(dict[str, object], value)

    def _request(self, command: str, observation: Observation) -> dict[str, object]:
        if self._process.stdin is None:
            raise FrozenBuild002Error("frozen worker stdin is unavailable")
        value = json.loads(observation_to_bytes(observation))
        self._process.stdin.write(
            json.dumps(
                {"command": command, "observation": value},
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        )
        self._process.stdin.flush()
        response = self._receive()
        if response.get("schema") == "arc3.build003.frozen-build002-error.v0.1":
            raise FrozenBuild002Error(
                f"{response.get('error_type', 'Error')}: {response.get('message', '')}"
            )
        return response

    def request_action(self, observation: Observation) -> ActionRequest:
        response = self._request("act", observation)
        if response.get("schema") != "arc3.build003.frozen-build002-action.v0.1":
            raise FrozenBuild002Error("frozen worker returned an invalid action receipt")
        return _action_from_object(response.get("action"))

    def finalize(self, observation: Observation) -> dict[str, object]:
        response = self._request("finalize", observation)
        if response.get("schema") != "arc3.build003.worker-summary.v0.1":
            raise FrozenBuild002Error("frozen worker returned an invalid summary receipt")
        return response

    def close(self) -> None:
        if self._process.stdin is not None:
            try:
                self._process.stdin.close()
            except OSError:
                pass
        try:
            self._process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=5)

    def __enter__(self) -> FrozenBuild002Process:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()


def _rss_bytes(process_id: int | None) -> int:
    if process_id is None:
        return 0
    if sys.platform.startswith("linux"):
        try:
            for line in Path(f"/proc/{process_id}/status").read_text(encoding="utf-8").splitlines():
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) * 1024
        except (OSError, ValueError, IndexError):
            return 0
        return 0
    if os.name != "nt":
        return 0

    class _Counters(ctypes.Structure):
        _fields_ = [
            ("cb", ctypes.c_ulong),
            ("PageFaultCount", ctypes.c_ulong),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    query_information = 0x0400
    process = ctypes.windll.kernel32.OpenProcess(query_information, False, process_id)
    if not process:
        return 0
    counters = _Counters()
    counters.cb = ctypes.sizeof(_Counters)
    try:
        ok = ctypes.windll.psapi.GetProcessMemoryInfo(process, ctypes.byref(counters), counters.cb)
        return int(counters.PeakWorkingSetSize) if ok else 0
    finally:
        ctypes.windll.kernel32.CloseHandle(process)


def _action_value(action: ActionRequest) -> dict[str, object]:
    coordinate = action.coordinate
    return {
        "name": action.name.value,
        "coordinate": None if coordinate is None else {"x": coordinate.x, "y": coordinate.y},
    }


def _transcript_digest(transcript: list[tuple[ActionRequest, bytes]]) -> str:
    payload = [
        {
            "action": _action_value(action),
            "observation_sha256": hashlib.sha256(observation).hexdigest(),
        }
        for action, observation in transcript
    ]
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def _replay(spec: CurriculumSpec, transcript: list[tuple[ActionRequest, bytes]]) -> bool:
    session = CurriculumSession(spec)
    try:
        for action, expected in transcript:
            returned = session.step(action)
            if observation_to_bytes(returned) != expected:
                return False
    except Exception:
        return False
    return True


def _integer(value: object, default: int = 0) -> int:
    return (
        value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else default
    )


def _boolean(value: object) -> bool:
    return value if isinstance(value, bool) else False


def _nullable_integer(value: object) -> int | None:
    return None if value is None else _integer(value)


def _counter_pairs(value: object, names: tuple[str, ...]) -> tuple[tuple[str, int], ...]:
    source = cast(dict[str, object], value) if isinstance(value, dict) else {}
    return tuple((name, _integer(source.get(name))) for name in names)


def _observation_ref(observation: Observation) -> str:
    value = {
        "frames": [
            {"digest": str(frame.digest), "width": frame.width, "height": frame.height}
            for frame in observation.frames
        ],
        "state": observation.state.value,
        "levels_completed": observation.levels_completed,
        "win_levels": observation.win_levels,
        "available_actions": [action.value for action in observation.available_actions],
        "full_reset": observation.full_reset,
        "returned_action": (
            None
            if observation.returned_action is None
            else _action_value(observation.returned_action)
        ),
        "metadata": list(observation.upstream_metadata),
    }
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _is_digest(value: object) -> bool:
    if not isinstance(value, str) or not value.startswith("sha256:"):
        return False
    digest = value.removeprefix("sha256:")
    return len(digest) == 64 and all(character in "0123456789abcdef" for character in digest)


def _receipt_link_audit(
    summary: dict[str, object],
    initial: Observation,
    transcript: list[tuple[ActionRequest, bytes]],
    *,
    require_prediction_links: bool,
) -> tuple[bool, ...]:
    """Independently tie every worker receipt to the replayed public transition."""

    valid = [True for _ in FAMILIES]
    counts = [0 for _ in FAMILIES]
    raw_links = summary.get("action_links")
    if require_prediction_links and (
        not isinstance(raw_links, list) or len(raw_links) != len(transcript)
    ):
        return tuple(False for _ in FAMILIES)
    links = raw_links if isinstance(raw_links, list) else [None for _ in transcript]
    before = initial
    for step, ((action, payload), raw_link) in enumerate(
        zip(transcript, links, strict=True), start=1
    ):
        level_index = min(before.levels_completed, len(FAMILIES) - 1)
        counts[level_index] += 1
        after = observation_from_bytes(payload)
        returned_action_matches = after.returned_action == action
        if not require_prediction_links:
            valid[level_index] &= returned_action_matches
            before = after
            continue
        if not isinstance(raw_link, dict):
            valid[level_index] = False
            before = after
            continue
        link = cast(dict[str, object], raw_link)
        expected_action = _action_value(action)
        valid[level_index] &= (
            returned_action_matches
            and link.get("step") == step
            and link.get("level_index") == level_index
            and link.get("action") == expected_action
            and link.get("before_ref") == _observation_ref(before)
            and link.get("after_ref") == _observation_ref(after)
            and isinstance(link.get("prediction_id"), str)
            and bool(link.get("prediction_id"))
            and _is_digest(link.get("prediction_digest"))
            and _is_digest(link.get("learning_digest"))
            and _is_digest(link.get("causal_receipt_digest"))
            and link.get("complete") is True
        )
        before = after
    for index in range(len(FAMILIES)):
        metric = _level_metrics(summary, index)
        expected = _integer(metric.get("receipt_count"))
        complete = _integer(_level_metrics(summary, index).get("complete_receipt_count"))
        submissions = _integer(metric.get("environment_actions")) + _integer(metric.get("resets"))
        attempted_or_completed = submissions > 0 or _boolean(metric.get("completed"))
        valid[index] &= (
            attempted_or_completed and counts[index] == submissions == expected == complete
        )
    return tuple(valid)


def _level_metrics(summary: dict[str, object], index: int) -> dict[str, object]:
    raw_levels = summary.get("levels")
    if not isinstance(raw_levels, list) or index >= len(raw_levels):
        return {}
    value = raw_levels[index]
    return cast(dict[str, object], value) if isinstance(value, dict) else {}


def _sequence_counter_audit(
    summary: dict[str, object],
    *,
    environment_actions: int,
    resets: int,
    transcript_count: int,
) -> tuple[bool, int, int]:
    """Reconcile worker rows with runner-owned submitted-action counters."""

    reported_environment_actions = sum(
        _integer(_level_metrics(summary, index).get("environment_actions"))
        for index in range(len(FAMILIES))
    )
    reported_resets = sum(
        _integer(_level_metrics(summary, index).get("resets")) for index in range(len(FAMILIES))
    )
    reconciled = (
        reported_environment_actions == environment_actions
        and reported_resets == resets
        and environment_actions + resets == transcript_count
    )
    return reconciled, reported_environment_actions, reported_resets


def _rows(
    *,
    spec: CurriculumSpec,
    variant: str,
    summary: dict[str, object],
    final_state: GameStateName,
    final_levels_completed: int,
    run_status: str,
    failure_reason: str | None,
    wall_time_seconds: float,
    peak_memory_bytes: int,
    replay_digest: str,
    replay_deterministic: bool,
    receipt_links_complete: tuple[bool, ...],
    sequence_counts_reconciled: bool,
) -> tuple[CurriculumResultRow, ...]:
    total_actions = sum(
        _integer(_level_metrics(summary, index).get("environment_actions"))
        for index in range(len(FAMILIES))
    )
    rows: list[CurriculumResultRow] = []
    for index, family in enumerate(FAMILIES):
        metric = _level_metrics(summary, index)
        completed = _boolean(metric.get("completed"))
        if completed:
            state = GameStateName.WIN if index + 1 == len(FAMILIES) else GameStateName.NOT_FINISHED
            levels_completed = index + 1
        elif index == final_levels_completed:
            state = final_state
            levels_completed = final_levels_completed
        else:
            state = GameStateName.NOT_PLAYED
            levels_completed = final_levels_completed
        actions = _integer(metric.get("environment_actions"))
        exploratory = _integer(metric.get("exploratory_actions"))
        progress = _integer(metric.get("progress_actions"))
        if exploratory + progress != actions:
            exploratory = actions
            progress = 0
        stable = metric.get("actions_to_stable")
        actions_to_stable = _integer(stable) if stable is not None else None
        receipt_count = _integer(metric.get("receipt_count"))
        complete_receipts = _integer(metric.get("complete_receipt_count"))
        allocated_wall = wall_time_seconds * actions / total_actions if total_actions else 0.0
        rows.append(
            CurriculumResultRow(
                case_id=spec.case.case_id,
                seed=spec.case.seed,
                variant=variant,
                family=family,
                level_index=index + 1,
                state=state,
                completed=completed,
                levels_completed=levels_completed,
                environment_actions=actions,
                resets=_integer(metric.get("resets")),
                exploratory_actions=exploratory,
                progress_actions=progress,
                redundant_probes=min(exploratory, _integer(metric.get("redundant_probes"))),
                actions_to_stable=actions_to_stable,
                movement_prediction_errors=_integer(metric.get("movement_prediction_errors")),
                resource_prediction_errors=_integer(metric.get("resource_prediction_errors")),
                access_prediction_errors=_integer(metric.get("access_prediction_errors")),
                hazard_prediction_errors=_integer(metric.get("hazard_prediction_errors")),
                prediction_errors_by_channel=_counter_pairs(
                    metric.get("prediction_errors_by_channel"),
                    tuple(channel.value for channel in CHANNEL_ORDER),
                ),
                residuals_observed=_integer(metric.get("residuals_observed")),
                residuals_localized=min(
                    _integer(metric.get("residuals_observed")),
                    _integer(metric.get("residuals_localized")),
                ),
                residuals_resolved=min(
                    _integer(metric.get("residuals_localized")),
                    _integer(metric.get("residuals_resolved")),
                ),
                base_mechanics_retained=_boolean(metric.get("base_mechanics_retained")),
                observed_retained_matches=_integer(metric.get("observed_retained_matches")),
                erroneous_global_reopenings=_nullable_integer(
                    metric.get("erroneous_global_reopenings")
                ),
                passive_confirmations=_integer(metric.get("passive_confirmations")),
                transfer_confirmations=_integer(metric.get("transfer_confirmations")),
                local_repair_candidates_opened=_integer(
                    metric.get("local_repair_candidates_opened")
                ),
                local_repairs_confirmed=_integer(metric.get("local_repairs_confirmed")),
                local_repair_failures=_integer(metric.get("local_repair_failures")),
                base_reopenings=_integer(metric.get("base_reopenings")),
                composition_events=_counter_pairs(
                    metric.get("composition_events"),
                    tuple(mode.value for mode in CompositionMode),
                ),
                clef_promotions=_integer(metric.get("clef_promotions")),
                clef_parks=_integer(metric.get("clef_parks")),
                clef_stops=_integer(metric.get("clef_stops")),
                other_object_effects_observed=_integer(metric.get("other_object_effects_observed")),
                topology_changes_confirmed=_integer(metric.get("topology_changes_confirmed")),
                delayed_candidates_confirmed=_integer(metric.get("delayed_candidates_confirmed")),
                unresolved_ledger_count=_integer(metric.get("unresolved_ledger_count")),
                active_ledger_pressure=_integer(metric.get("active_ledger_pressure")),
                wall_time_seconds=allocated_wall,
                peak_memory_bytes=peak_memory_bytes,
                replay_digest=replay_digest,
                replay_deterministic=replay_deterministic,
                receipt_complete=(
                    run_status != "FAILED_INFRASTRUCTURE"
                    and receipt_count == complete_receipts
                    and receipt_links_complete[index]
                    and sequence_counts_reconciled
                ),
                run_status=run_status,
                failure_reason=failure_reason,
            )
        )
    return tuple(rows)


def run_sequence(
    spec: CurriculumSpec,
    variant: CurriculumVariant | str,
    *,
    budgets: SequenceBudgets | None = None,
    build002_source_root: Path | None = None,
    storage_root: Path | None = None,
) -> SequenceExecution:
    """Run one opaque seed/variant sequence until WIN or an explicit bound."""

    definition = protocol_definition(spec.protocol_id)
    effective_budgets = budgets or budgets_for_protocol(definition)
    variant_name = variant.value if isinstance(variant, CurriculumVariant) else variant
    started = time.perf_counter()
    session = CurriculumSession(spec)
    initial_observation = session.observation
    transcript: list[tuple[ActionRequest, bytes]] = []
    environment_actions = 0
    level_attempt_actions = 0
    active_level = 0
    resets = 0
    peak_memory = 0
    status = "SUCCESS"
    failure_reason: str | None = None
    summary: dict[str, object] = {
        "schema": "arc3.build003.worker-summary.v0.1",
        "levels": [{} for _ in FAMILIES],
    }
    process: PolicyProcess | FrozenBuild002Process | None = None
    try:
        if variant_name == CurriculumVariant.BUILD002_FROZEN.value:
            if build002_source_root is None:
                raise FrozenBuild002Error("exact Build 002 source root was not supplied")
            root = storage_root or Path("artifacts/build003/frozen-build002")
            process = FrozenBuild002Process(
                source_root=build002_source_root,
                storage_root=root / spec.case.case_id,
                source_identity=definition.baseline,
            )
        else:
            process = PolicyProcess(
                variant=variant_name,
                timeout_seconds=effective_budgets.policy_cycle_seconds,
            )
        while session.observation.state is not GameStateName.WIN:
            elapsed = time.perf_counter() - started
            if elapsed >= effective_budgets.max_wall_clock_seconds:
                status = "WALL_CLOCK_BUDGET"
                failure_reason = (
                    "sequence exceeded "
                    f"{effective_budgets.max_wall_clock_seconds:.3f}s wall-clock budget"
                )
                break
            if peak_memory > effective_budgets.max_peak_memory_bytes:
                status = "MEMORY_BUDGET"
                failure_reason = (
                    f"worker peak memory {peak_memory} exceeded "
                    f"{effective_budgets.max_peak_memory_bytes} bytes"
                )
                break
            if session.observation.state is GameStateName.GAME_OVER:
                if resets >= effective_budgets.max_resets:
                    status = "RESET_BUDGET"
                    failure_reason = (
                        f"sequence exhausted {effective_budgets.max_resets} resets without WIN"
                    )
                    break
            else:
                if environment_actions >= effective_budgets.max_environment_actions:
                    status = "ACTION_BUDGET"
                    failure_reason = (
                        "sequence exhausted "
                        f"{effective_budgets.max_environment_actions} actions without WIN"
                    )
                    break
                per_level = effective_budgets.max_environment_actions_per_level
                if per_level is not None and level_attempt_actions >= per_level:
                    status = "ACTION_BUDGET"
                    failure_reason = (
                        f"level {active_level + 1} attempt exhausted {per_level} actions without "
                        "completion or GAME_OVER"
                    )
                    break
            action = process.request_action(session.observation)
            returned = session.step(action)
            transcript.append((action, observation_to_bytes(returned)))
            if action.name is ActionName.RESET:
                resets += 1
                active_level = 0
                level_attempt_actions = 0
            else:
                environment_actions += 1
                level_attempt_actions += 1
                if returned.levels_completed > active_level:
                    active_level = returned.levels_completed
                    level_attempt_actions = 0
            peak_memory = max(peak_memory, _rss_bytes(process.process_id))
        summary = process.finalize(session.observation)
        if session.observation.state is not GameStateName.WIN and status == "SUCCESS":
            status = "POLICY_ERROR"
            failure_reason = "policy stopped without authoritative WIN"
    except FrozenBuild002Error as error:
        status = "FAILED_INFRASTRUCTURE" if not transcript else "POLICY_ERROR"
        failure_reason = str(error)
        if process is not None:
            try:
                summary = process.finalize(session.observation)
            except Exception:
                pass
    except (RuntimeError, TimeoutError, ValueError) as error:
        status = "POLICY_ERROR"
        failure_reason = f"{type(error).__name__}: {error}"
        if process is not None:
            try:
                summary = process.finalize(session.observation)
            except Exception:
                pass
    finally:
        if process is not None:
            process.close()
    elapsed = time.perf_counter() - started
    digest = _transcript_digest(transcript)
    deterministic = _replay(spec, transcript) and not (
        status == "FAILED_INFRASTRUCTURE" and not transcript
    )
    receipt_links_complete = _receipt_link_audit(
        summary,
        initial_observation,
        transcript,
        require_prediction_links=variant_name != CurriculumVariant.BUILD002_FROZEN.value,
    )
    (
        sequence_counts_reconciled,
        reported_environment_actions,
        reported_resets,
    ) = _sequence_counter_audit(
        summary,
        environment_actions=environment_actions,
        resets=resets,
        transcript_count=len(transcript),
    )
    rows = _rows(
        spec=spec,
        variant=variant_name,
        summary=summary,
        final_state=session.observation.state,
        final_levels_completed=session.observation.levels_completed,
        run_status=status,
        failure_reason=failure_reason,
        wall_time_seconds=elapsed,
        peak_memory_bytes=peak_memory,
        replay_digest=digest,
        replay_deterministic=deterministic,
        receipt_links_complete=receipt_links_complete,
        sequence_counts_reconciled=sequence_counts_reconciled,
    )
    receipt: dict[str, object] = {
        "schema": definition.sequence_receipt_schema,
        "surface": "synthetic",
        "protocol_version": definition.version.value,
        "protocol_id": definition.protocol_id,
        "protocol_path": definition.protocol_path,
        "manifest_path": definition.manifest_path,
        "budgets": asdict(effective_budgets),
        "build002_baseline_identity": asdict(definition.baseline),
        "case_id": spec.case.case_id,
        "seed": spec.case.seed,
        "variant": variant_name,
        "run_status": status,
        "failure_reason": failure_reason,
        "final_state": session.observation.state.value,
        "levels_completed": session.observation.levels_completed,
        "win_levels": session.observation.win_levels,
        "environment_actions": environment_actions,
        "resets": resets,
        "wall_time_seconds": elapsed,
        "peak_memory_bytes": peak_memory,
        "replay_digest": digest,
        "replay_deterministic": deterministic,
        "receipt_links_complete": all(receipt_links_complete),
        "sequence_counts_reconciled": sequence_counts_reconciled,
        "reported_environment_actions": reported_environment_actions,
        "reported_resets": reported_resets,
        "worker_summary": summary,
        "claim_boundary": "No public, holdout, or official target game was opened.",
    }
    return SequenceExecution(rows, receipt)


def execution_to_dict(execution: SequenceExecution) -> dict[str, object]:
    """Return a JSON-ready sequence result without weakening enum identity."""

    rows: list[dict[str, object]] = []
    for row in execution.rows:
        value = asdict(row)
        value["state"] = row.state.value
        rows.append(value)
    return {"receipt": execution.receipt, "rows": rows}


__all__ = [
    "BUILD002_COMMIT",
    "BUILD002_TREE",
    "FrozenBuild002Error",
    "FrozenBuild002Process",
    "SequenceBudgets",
    "SequenceExecution",
    "budgets_for_protocol",
    "execution_to_dict",
    "run_sequence",
]
