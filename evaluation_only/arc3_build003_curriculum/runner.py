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
from arc3.types import ActionName, ActionRequest, Coordinate, GameStateName

from .broker import PolicyProcess, observation_to_bytes
from .engine import CurriculumSession
from .models import CurriculumSpec, CurriculumVariant

BUILD002_COMMIT = "753b0e007222a973a2c8a6d7ce14a395135d3c5f"
BUILD002_TREE = "d07e72716a1f918ed04a6892adb1e3f46259e345"


@dataclass(frozen=True, slots=True)
class SequenceBudgets:
    max_environment_actions: int = 1500
    max_resets: int = 10
    max_wall_clock_seconds: float = 120.0
    max_peak_memory_bytes: int = 1_073_741_824
    policy_cycle_seconds: float = 10.0


DEFAULT_SEQUENCE_BUDGETS = SequenceBudgets()


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
            or ready.get("source_commit") != BUILD002_COMMIT
            or ready.get("source_tree") != BUILD002_TREE
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


def _level_metrics(summary: dict[str, object], index: int) -> dict[str, object]:
    raw_levels = summary.get("levels")
    if not isinstance(raw_levels, list) or index >= len(raw_levels):
        return {}
    value = raw_levels[index]
    return cast(dict[str, object], value) if isinstance(value, dict) else {}


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
                erroneous_global_reopenings=_integer(metric.get("erroneous_global_reopenings")),
                unresolved_ledger_count=_integer(metric.get("unresolved_ledger_count")),
                active_ledger_pressure=_integer(metric.get("active_ledger_pressure")),
                wall_time_seconds=allocated_wall,
                peak_memory_bytes=peak_memory_bytes,
                replay_digest=replay_digest,
                replay_deterministic=replay_deterministic,
                receipt_complete=(
                    run_status != "FAILED_INFRASTRUCTURE"
                    and receipt_count == complete_receipts
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
    budgets: SequenceBudgets = DEFAULT_SEQUENCE_BUDGETS,
    build002_source_root: Path | None = None,
    storage_root: Path | None = None,
) -> SequenceExecution:
    """Run one opaque seed/variant sequence until WIN or an explicit bound."""

    variant_name = variant.value if isinstance(variant, CurriculumVariant) else variant
    started = time.perf_counter()
    session = CurriculumSession(spec)
    transcript: list[tuple[ActionRequest, bytes]] = []
    environment_actions = 0
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
            )
        else:
            process = PolicyProcess(
                variant=variant_name,
                timeout_seconds=budgets.policy_cycle_seconds,
            )
        while session.observation.state is not GameStateName.WIN:
            elapsed = time.perf_counter() - started
            if elapsed >= budgets.max_wall_clock_seconds:
                status = "WALL_CLOCK_BUDGET"
                failure_reason = (
                    f"sequence exceeded {budgets.max_wall_clock_seconds:.3f}s wall-clock budget"
                )
                break
            if peak_memory > budgets.max_peak_memory_bytes:
                status = "MEMORY_BUDGET"
                failure_reason = (
                    f"worker peak memory {peak_memory} exceeded "
                    f"{budgets.max_peak_memory_bytes} bytes"
                )
                break
            if session.observation.state is GameStateName.GAME_OVER:
                if resets >= budgets.max_resets:
                    status = "RESET_BUDGET"
                    failure_reason = f"sequence exhausted {budgets.max_resets} resets without WIN"
                    break
            elif environment_actions >= budgets.max_environment_actions:
                status = "ACTION_BUDGET"
                failure_reason = (
                    f"sequence exhausted {budgets.max_environment_actions} actions without WIN"
                )
                break
            action = process.request_action(session.observation)
            returned = session.step(action)
            transcript.append((action, observation_to_bytes(returned)))
            if action.name is ActionName.RESET:
                resets += 1
            else:
                environment_actions += 1
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
    )
    receipt = {
        "schema": "arc3.build003.sequence-run.v0.1",
        "surface": "synthetic",
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
    "execution_to_dict",
    "run_sequence",
]
