"""Acquire or play the frozen Strongwiz clean-room public target.

The play subcommand is interactive JSONL: stdout emits one immutable request and
stdin accepts one response.  No operator code receives an SDK session or calls
the environment directly.
"""

from __future__ import annotations

import argparse
import ctypes
import importlib
import json
import os
import re
import socket
import sys
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any, cast

from arc3.adapters import EnvironmentSession, Observation, ScoreSummary
from arc3.adapters.arc_agi import ArcAGIAdapter
from arc3.config import ARC3Config, BudgetConfig
from arc3.errors import ARC3Error, EvaluationError
from arc3.evaluation.public import (
    PublicExposureLedger,
    PublicPartitionManifest,
    acquire_local_public_asset,
    run_public_episode,
    validate_frozen_source,
)
from arc3.evaluation.strongwiz_operator import (
    JsonlOperatorProvider,
    StrongwizOperatorConfig,
    StrongwizOperatorPolicy,
    StrongwizSourceIdentity,
    verify_strongwiz_source,
)
from arc3.trace import BaselineTraceSink, EventJournal
from arc3.trace.canonical import canonical_json, normalize_json, sha256_bytes
from arc3.trace.schema import CodeIdentity, SourceIdentity
from arc3.types import EnvironmentMode, JSONValue, RationaleCategory

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TARGET = "ls20-9607627b"
FROZEN_SEED = 0
FROZEN_PROTOCOL_SHA256 = "9a75b29a73d4b0cf4549c2d083838c27cf7a7b90cc532a376a55f6bcb3d8df56"
FROZEN_MAX_ACTIONS = 4096
FROZEN_MAX_RESETS = 64
DEFAULT_PROTOCOL = ROOT / "docs" / "experiments" / "strongwiz-clean-room-protocol.v0.1.md"
DEFAULT_MANIFEST = ROOT / "docs" / "evaluation" / "public-game-partitions.v0.1.json"
DEFAULT_SOURCE = ROOT / "playground" / "vendor" / "strongwiz"
DEFAULT_ARCHIVE = ROOT / "playground" / "tmp" / "strongwiz-6944642.tar"
DEFAULT_ENVIRONMENTS = ROOT / "artifacts" / "strongwiz-clean-room" / "public-environments"
DEFAULT_RECORDINGS = ROOT / "artifacts" / "strongwiz-clean-room" / "official-recordings"
DEFAULT_EXPOSURE = ROOT / "artifacts" / "strongwiz-clean-room" / "public-exposure.jsonl"
DEFAULT_OUTPUT = ROOT / "artifacts" / "strongwiz-clean-room"
MAX_EVIDENCE_BYTES = 256 * 1024 * 1024
RESULT_EVIDENCE_RESERVE_BYTES = 64 * 1024
COMPLETION_RECEIPT_RESERVE_BYTES = 16 * 1024
RESULT_EVIDENCE_MAX_BYTES = RESULT_EVIDENCE_RESERVE_BYTES - COMPLETION_RECEIPT_RESERVE_BYTES
MAX_WALL_CLOCK_SECONDS = 9 * 60 * 60
MAX_MEMORY_BYTES = 2048 * 1024 * 1024
POLICY_NETWORK_MODE = "external-hosted-codex-operator"
ACQUISITION_NETWORK_MODE = "official-public-normal"
RUNTIME_NETWORK_MODE = "offline-local"
_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class _OfflineSocketGuard:
    """Deny and count common Python socket paths in the environment process."""

    def __init__(self) -> None:
        self.attempt_count = 0
        self._originals: dict[tuple[object, str], object] = {}

    def install(self) -> None:
        if self._originals:
            return

        def deny(*_args: object, **_kwargs: object) -> Any:
            self.attempt_count += 1
            raise EvaluationError("Strongwiz local-public runtime blocked a network attempt")

        try:
            for owner, name in (
                (socket, "create_connection"),
                (socket, "getaddrinfo"),
                (socket, "gethostbyname"),
                (socket, "gethostbyname_ex"),
                (socket, "gethostbyaddr"),
                (socket, "getnameinfo"),
                (socket.socket, "connect"),
                (socket.socket, "connect_ex"),
                (socket.socket, "send"),
                (socket.socket, "sendall"),
                (socket.socket, "sendto"),
            ):
                self._originals[(owner, name)] = getattr(owner, name)
                setattr(owner, name, deny)
        except Exception:
            self.restore()
            raise

    def restore(self) -> None:
        for (owner, name), original in self._originals.items():
            setattr(owner, name, original)
        self._originals.clear()


@contextmanager
def _exclusive_exposure_reservation(exposure_path: Path) -> Iterator[None]:
    """Hold a fail-closed cross-process reservation around check plus intent."""

    lock_path = exposure_path.with_name(f"{exposure_path.name}.reservation.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        handle = lock_path.open("xb")
    except FileExistsError:
        raise EvaluationError(
            "another Strongwiz exposure reservation is active or a stale lock needs audit"
        ) from None
    try:
        handle.write(
            canonical_json(
                {
                    "pid": os.getpid(),
                    "schema": "arc3.strongwiz-exposure-reservation.v0.1",
                }
            ).encode("utf-8")
            + b"\n"
        )
        handle.flush()
        os.fsync(handle.fileno())
        yield
    finally:
        handle.close()
        try:
            lock_path.unlink()
        except FileNotFoundError:
            raise EvaluationError("Strongwiz exposure reservation lock disappeared") from None


def _peak_rss_bytes() -> tuple[int, str]:
    """Return the current process's kernel high-water resident set."""

    if os.name == "nt":

        class _ProcessMemoryCounters(ctypes.Structure):
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

        win_dll = cast(Any, vars(ctypes)["WinDLL"])
        kernel32 = win_dll("kernel32", use_last_error=True)
        psapi = win_dll("psapi", use_last_error=True)
        counters = _ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        get_current_process = kernel32.GetCurrentProcess
        get_current_process.restype = ctypes.c_void_p
        get_process_memory_info = psapi.GetProcessMemoryInfo
        get_process_memory_info.argtypes = (
            ctypes.c_void_p,
            ctypes.POINTER(_ProcessMemoryCounters),
            ctypes.c_ulong,
        )
        get_process_memory_info.restype = ctypes.c_int
        if not get_process_memory_info(
            get_current_process(),
            ctypes.byref(counters),
            counters.cb,
        ):
            raise EvaluationError("Windows peak RSS measurement failed")
        return int(counters.PeakWorkingSetSize), "windows-GetProcessMemoryInfo-peak-working-set"

    try:
        resource_module = importlib.import_module("resource")
        resource_api = cast(Any, resource_module)
        raw = resource_api.getrusage(resource_api.RUSAGE_SELF).ru_maxrss
    except (AttributeError, ImportError, OSError) as error:
        raise EvaluationError("kernel peak RSS measurement is unavailable") from error
    if isinstance(raw, bool) or not isinstance(raw, int | float) or raw < 0:
        raise EvaluationError("kernel peak RSS measurement is invalid")
    value = int(raw if sys.platform == "darwin" else raw * 1024)
    return value, "posix-getrusage-peak-rss"


class _ResourceGuard:
    """Measure and enforce the frozen whole-process and evidence ceilings."""

    def __init__(
        self,
        run_root: Path,
        started: float,
        *,
        external_evidence_files: tuple[Path, ...] = (),
    ) -> None:
        self._run_root = run_root
        self._started = started
        self._peak_rss = 0
        self._memory_source: str | None = None
        self._external_evidence_baselines = tuple(
            (path.resolve(), path.stat().st_size if path.is_file() else 0)
            for path in external_evidence_files
        )

    def evidence_bytes(self) -> tuple[int, int, int]:
        """Return total, run-root, and post-baseline external evidence bytes."""

        run_root_bytes = _directory_bytes(self._run_root)
        external_delta_bytes = 0
        for path, baseline in self._external_evidence_baselines:
            current = path.stat().st_size if path.is_file() else 0
            if current < baseline:
                raise EvaluationError("Strongwiz external evidence shrank during the measured run")
            external_delta_bytes += current - baseline
        return run_root_bytes + external_delta_bytes, run_root_bytes, external_delta_bytes

    def snapshot(self, *, boundary: str) -> dict[str, object]:
        measured_rss, source = _peak_rss_bytes()
        self._peak_rss = max(self._peak_rss, measured_rss)
        self._memory_source = source
        evidence, run_root_evidence, external_evidence = self.evidence_bytes()
        return {
            "boundary": boundary,
            "declared_evidence_limit_bytes": MAX_EVIDENCE_BYTES,
            "declared_memory_limit_bytes": MAX_MEMORY_BYTES,
            "declared_wall_limit_seconds": MAX_WALL_CLOCK_SECONDS,
            "elapsed_seconds": time.monotonic() - self._started,
            "evidence_bytes": evidence,
            "evidence_external_delta_bytes": external_evidence,
            "evidence_result_reserve_bytes": RESULT_EVIDENCE_RESERVE_BYTES,
            "evidence_run_root_bytes": run_root_evidence,
            "memory_measurement_source": self._memory_source,
            "peak_rss_bytes": self._peak_rss,
            "schema": "arc3.strongwiz-resource-snapshot.v0.1",
        }

    def enforce(self, *, boundary: str, finalization: bool = False) -> dict[str, object]:
        snapshot = self.snapshot(boundary=boundary)
        elapsed = cast(float, snapshot["elapsed_seconds"])
        evidence = cast(int, snapshot["evidence_bytes"])
        rss = cast(int, snapshot["peak_rss_bytes"])
        if elapsed >= MAX_WALL_CLOCK_SECONDS:
            raise EvaluationError(
                f"Strongwiz measured run exhausted the wall ceiling at {boundary}"
            )
        evidence_limit = (
            MAX_EVIDENCE_BYTES
            if finalization
            else MAX_EVIDENCE_BYTES - RESULT_EVIDENCE_RESERVE_BYTES
        )
        if evidence > evidence_limit:
            raise EvaluationError(
                f"Strongwiz measured run exhausted the evidence-byte ceiling at {boundary}"
            )
        if rss > MAX_MEMORY_BYTES:
            raise EvaluationError(
                f"Strongwiz measured run exhausted the memory ceiling at {boundary}"
            )
        return snapshot


def _sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes()).removeprefix("sha256:")


def _verify_protocol(path: Path, expected_sha256: str) -> None:
    if _sha256_file(path) != expected_sha256:
        raise EvaluationError("frozen Strongwiz protocol hash changed")


def _write_immutable(path: Path, payload: object) -> None:
    encoded = (canonical_json(payload) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError:
        if path.read_bytes() != encoded:
            raise EvaluationError(f"immutable result changed at {path}") from None


def _inside_repository(path: Path, *, label: str) -> Path:
    resolved = path.resolve()
    root = ROOT.resolve()
    if resolved != root and root not in resolved.parents:
        raise EvaluationError(f"{label} must remain inside the clean-room checkout")
    return resolved


def _validate_paths(args: argparse.Namespace) -> None:
    for attribute, label in (
        ("manifest", "partition manifest"),
        ("protocol", "frozen protocol"),
        ("strongwiz_source", "Strongwiz source"),
        ("strongwiz_archive", "Strongwiz archive"),
        ("environments_dir", "environment assets"),
        ("recordings_dir", "official recordings"),
        ("exposure_ledger", "exposure ledger"),
        ("output_root", "run output"),
    ):
        _inside_repository(cast(Path, getattr(args, attribute)), label=label)


def _validate_frozen_arguments(args: argparse.Namespace) -> None:
    """Reject caller-selected apertures that could create a second specimen."""

    _validate_paths(args)
    expected_paths = {
        "manifest": DEFAULT_MANIFEST,
        "protocol": DEFAULT_PROTOCOL,
        "strongwiz_source": DEFAULT_SOURCE,
        "strongwiz_archive": DEFAULT_ARCHIVE,
        "environments_dir": DEFAULT_ENVIRONMENTS,
        "recordings_dir": DEFAULT_RECORDINGS,
        "exposure_ledger": DEFAULT_EXPOSURE,
        "output_root": DEFAULT_OUTPUT,
    }
    for attribute, path_expected in expected_paths.items():
        actual = cast(Path, getattr(args, attribute)).resolve()
        if actual != path_expected.resolve():
            raise EvaluationError(f"{attribute.replace('_', '-')} is frozen for this run")
    frozen_scalars: dict[str, object] = {
        "game_id": DEFAULT_TARGET,
        "seed": FROZEN_SEED,
        "protocol_sha256": FROZEN_PROTOCOL_SHA256,
        "max_actions": FROZEN_MAX_ACTIONS,
        "max_resets": FROZEN_MAX_RESETS,
    }
    for attribute, scalar_expected in frozen_scalars.items():
        if getattr(args, attribute) != scalar_expected:
            raise EvaluationError(f"{attribute.replace('_', '-')} is frozen for this run")


def _directory_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def _target_entry(manifest_path: Path, game_id: str) -> None:
    if game_id != DEFAULT_TARGET:
        raise EvaluationError("Strongwiz clean-room protocol permits only its frozen target")
    manifest = PublicPartitionManifest.load(manifest_path)
    development = {entry.game_id for entry in manifest.games("development")}
    if game_id not in development:
        raise EvaluationError("Strongwiz target must be in the frozen development partition")


def _source_identity(args: argparse.Namespace) -> StrongwizSourceIdentity:
    return StrongwizSourceIdentity(
        source_root=args.strongwiz_source,
        archive_path=args.strongwiz_archive,
    )


def _payload(event: dict[str, Any]) -> dict[str, Any]:
    value = event.get("payload")
    if not isinstance(value, dict):
        raise EvaluationError("Strongwiz exposure event has no object payload")
    return cast(dict[str, Any], value)


def _require_new_acquisition(ledger: PublicExposureLedger) -> None:
    if any(str(event.get("event_type", "")).startswith("strongwiz.") for event in ledger.events()):
        raise EvaluationError("the one permitted Strongwiz setup exposure is already consumed")


def _require_new_measured_run(
    ledger: PublicExposureLedger,
    *,
    game_id: str,
    protocol_sha256: str,
    seed: int,
) -> None:
    events = ledger.events()
    acquisitions = [
        event
        for event in events
        if event.get("event_type") == "strongwiz.asset-acquisition.completed"
    ]
    acquisition_intents = [
        event for event in events if event.get("event_type") == "strongwiz.asset-acquisition.intent"
    ]
    intents = [
        event for event in events if event.get("event_type") == "strongwiz.measured-run.intent"
    ]
    if len(acquisition_intents) != 1 or len(acquisitions) != 1:
        raise EvaluationError("play requires exactly one completed uninspected setup exposure")
    acquisition_intent = _payload(acquisition_intents[0])
    acquisition = _payload(acquisitions[0])
    if (
        acquisition.get("intent_event_hash") != acquisition_intents[0].get("event_hash")
        or acquisition_intent.get("game_id") != game_id
        or acquisition_intent.get("protocol_sha256") != protocol_sha256
        or acquisition_intent.get("seed") != seed
        or acquisition_intent.get("frame_exposed_to_operator") is not False
        or acquisition_intent.get("environment_acquisition_network_mode")
        != ACQUISITION_NETWORK_MODE
        or acquisition_intent.get("setup_network_mode")
        != "official-NORMAL-anonymous-networked-acquisition"
        or acquisition.get("game_id") != game_id
        or acquisition.get("protocol_sha256") != protocol_sha256
        or acquisition.get("seed") != seed
        or acquisition.get("frame_exposed_to_operator") is not False
        or acquisition.get("environment_acquisition_network_mode") != ACQUISITION_NETWORK_MODE
        or acquisition.get("setup_network_mode")
        != "official-NORMAL-anonymous-networked-acquisition"
    ):
        raise EvaluationError("setup exposure does not bind this exact measured run")
    if intents:
        raise EvaluationError("the one permitted Strongwiz measured run is already consumed")


def _acquire(args: argparse.Namespace) -> dict[str, JSONValue]:
    _validate_frozen_arguments(args)
    _target_entry(args.manifest, args.game_id)
    _verify_protocol(args.protocol, args.protocol_sha256)
    verify_strongwiz_source(_source_identity(args))
    ledger = PublicExposureLedger(args.exposure_ledger)
    with _exclusive_exposure_reservation(args.exposure_ledger):
        _require_new_acquisition(ledger)
        intent = ledger.append(
            "strongwiz.asset-acquisition.intent",
            {
                "frame_exposed_to_operator": False,
                "game_id": args.game_id,
                "environment_acquisition_network_mode": ACQUISITION_NETWORK_MODE,
                "partition": "development",
                "protocol_sha256": args.protocol_sha256,
                "seed": args.seed,
                "setup_network_mode": "official-NORMAL-anonymous-networked-acquisition",
            },
        )
    acquire_local_public_asset(
        args.game_id,
        seed=args.seed,
        environments_dir=args.environments_dir,
        recordings_dir=args.recordings_dir,
        api_key="",
    )
    completed = ledger.append(
        "strongwiz.asset-acquisition.completed",
        {
            "frame_exposed_to_operator": False,
            "game_id": args.game_id,
            "environment_acquisition_network_mode": ACQUISITION_NETWORK_MODE,
            "intent_event_hash": intent["event_hash"],
            "partition": "development",
            "protocol_sha256": args.protocol_sha256,
            "seed": args.seed,
            "setup_network_mode": "official-NORMAL-anonymous-networked-acquisition",
        },
    )
    return cast(
        dict[str, JSONValue],
        normalize_json(
            {
                "acquired": True,
                "event_hash": completed["event_hash"],
                "game_id": args.game_id,
                "operator_frame_exposure": False,
                "schema": "arc3.strongwiz-acquisition-result.v0.1",
            }
        ),
    )


def _scorecard_payload(scorecard: ScoreSummary | None) -> JSONValue:
    return normalize_json(scorecard)


def _play(args: argparse.Namespace) -> dict[str, JSONValue]:
    _validate_frozen_arguments(args)
    if not isinstance(args.run_id, str) or _RUN_ID.fullmatch(args.run_id) is None:
        raise EvaluationError("run-id must be a safe 1-128 character repository-local name")
    _target_entry(args.manifest, args.game_id)
    validate_frozen_source(args.frozen_commit)
    _verify_protocol(args.protocol, args.protocol_sha256)
    source_identity = _source_identity(args)
    verify_strongwiz_source(source_identity)
    exposure = PublicExposureLedger(args.exposure_ledger)
    run_root = _inside_repository(
        args.output_root / "runs" / args.run_id,
        label="measured run root",
    )
    if run_root.exists():
        raise EvaluationError("measured run root already exists")
    run_started = time.monotonic()
    resource_guard = _ResourceGuard(
        run_root,
        run_started,
        external_evidence_files=(args.exposure_ledger,),
    )
    resource_snapshot: dict[str, object] | None = None
    with _exclusive_exposure_reservation(args.exposure_ledger):
        _require_new_measured_run(
            exposure,
            game_id=args.game_id,
            protocol_sha256=args.protocol_sha256,
            seed=args.seed,
        )
        intent = exposure.append(
            "strongwiz.measured-run.intent",
            {
                "decision_provider": "external-hosted-codex-operator",
                "environment_acquisition_network_mode": ACQUISITION_NETWORK_MODE,
                "game_id": args.game_id,
                "partition": "development",
                "protocol_sha256": args.protocol_sha256,
                "run_id": args.run_id,
                "seed": args.seed,
                "environment_runtime_network_mode": RUNTIME_NETWORK_MODE,
                "operator_provider_network_mode": ("external-hosted-outside-environment-process"),
                "policy_network_mode": POLICY_NETWORK_MODE,
            },
        )
    run_root.mkdir(parents=True, exist_ok=False)
    resource_snapshot = resource_guard.enforce(boundary="post-intent")

    def enforce_resources(boundary: str) -> dict[str, object]:
        nonlocal resource_snapshot
        resource_snapshot = resource_guard.enforce(boundary=boundary)
        return resource_snapshot

    def pre_action_selection() -> None:
        enforce_resources("pre-selection")

    def watch_operator_wait() -> object:
        return enforce_resources("operator-wait")

    def authorize_exact_source() -> None:
        validate_frozen_source(args.frozen_commit)
        verify_strongwiz_source(source_identity)
        enforce_resources("pre-action")

    budgets = BudgetConfig(
        max_actions=args.max_actions,
        max_resets=args.max_resets,
        decision_seconds=10.0,
        wall_clock_seconds=32400.0,
        memory_megabytes=2048,
        max_coordinate_candidates=24,
        max_search_nodes=10_000,
        max_search_depth=64,
        max_trace_bytes=256 * 1024 * 1024,
    )
    config = ARC3Config.for_mode(
        EnvironmentMode.LOCAL,
        seed=args.seed,
        network_enabled=False,
        profile="strongwiz-clean-room-local-public",
        budgets=budgets,
    )
    measured_recordings = run_root / "official-recordings"
    adapter = ArcAGIAdapter(
        config,
        environments_dir=args.environments_dir,
        recordings_dir=measured_recordings,
        save_recording=True,
        include_frame_data=True,
        environ={"OPERATION_MODE": "offline"},
    )
    policy = StrongwizOperatorPolicy(
        StrongwizOperatorConfig(
            repository_root=ROOT,
            source=source_identity,
            run_id=args.run_id,
            game_id=args.game_id,
            artifact_root=run_root / "strongwiz",
            protocol_sha256=args.protocol_sha256,
            bridge_commit=args.frozen_commit,
            max_actions=args.max_actions,
            max_resets=args.max_resets,
        ),
        JsonlOperatorProvider(
            sys.stdin,
            sys.stdout,
            deadline_monotonic=run_started + MAX_WALL_CLOCK_SECONDS,
            watchdog=watch_operator_wait,
        ),
    )
    journal = EventJournal(run_root / "arc-trace", run_id=args.run_id)
    sink = BaselineTraceSink(
        journal=journal,
        episode_id=f"episode:{args.run_id}",
        source=SourceIdentity(
            "official-local-public",
            "arc-agi==0.9.9+arcengine==0.9.3",
            {"game_id": args.game_id, "partition": "development"},
        ),
        code_identity=CodeIdentity(
            args.frozen_commit,
            str(config.hash),
            {
                "decision_provider": "external-hosted-codex-operator",
                "strongwiz_commit": source_identity.commit,
            },
        ),
        rationale_category=RationaleCategory.DISCRIMINATE_MODELS,
        rationale_summary="Strongwiz-routed external Codex proposal",
        alternative_interpretation="operator-declared alternative; ranking retained in Strongwiz",
        consequence_classification="returned official consequence",
        model_update_summary="Strongwiz assessment and smallest implicated reopening",
    )
    session: EnvironmentSession | None = None
    scorecard: ScoreSummary | None = None
    metrics: dict[str, object] | None = None
    failure: dict[str, JSONValue] | None = None
    socket_guard = _OfflineSocketGuard()
    socket_guard.install()

    def record_environment_returned(observation: Observation) -> None:
        policy.mark_environment_returned(observation)
        enforce_resources("post-return")

    try:
        session = adapter.open(args.game_id, seed=args.seed)
        scorecard, metrics = run_public_episode(
            session,
            policy,
            max_actions=args.max_actions,
            max_resets=args.max_resets,
            trace_sink=sink,
            pre_action_selection=pre_action_selection,
            pre_action_authorization=authorize_exact_source,
            environment_submission_started=policy.mark_submission_started,
            environment_returned=record_environment_returned,
            environment_reasoning={
                "category": "strongwiz-clean-room",
                "summary": "one Strongwiz-routed external Codex proposal; concise receipt only",
            },
        )
        resource_snapshot = resource_guard.enforce(boundary="pre-policy-close")
        policy.close()
        resource_snapshot = resource_guard.enforce(boundary="post-policy-close")
    except Exception as error:
        effect_unknown = policy.environment_effect_unknown
        failure = {
            "exception_type": type(error).__name__,
            "message": str(error),
            "unknown_environment_effect": effect_unknown,
        }
        try:
            policy.abort(
                reason=f"{type(error).__name__}: {error}",
                environment_effect_unknown=effect_unknown,
            )
        except Exception as abort_error:
            failure["abort_exception_type"] = type(abort_error).__name__
            failure["abort_message"] = str(abort_error)
        if session is not None:
            try:
                scorecard = session.close()
            except Exception:
                scorecard = None
    finally:
        try:
            events = journal.verify_manifest(include_active=True)
        except Exception as trace_error:
            events = ()
            if failure is None:
                failure = {
                    "exception_type": type(trace_error).__name__,
                    "message": f"ARC trace verification failed: {trace_error}",
                    "unknown_environment_effect": False,
                }
            else:
                failure["trace_exception_type"] = type(trace_error).__name__
                failure["trace_message"] = str(trace_error)
        finally:
            journal.close()
            socket_guard.restore()
    try:
        resource_snapshot = resource_guard.enforce(boundary="pre-result")
    except Exception as resource_error:
        resource_failure: dict[str, JSONValue] = {
            "exception_type": type(resource_error).__name__,
            "message": str(resource_error),
            "unknown_environment_effect": False,
        }
        if failure is None:
            failure = resource_failure
        else:
            failure["resource_exception_type"] = type(resource_error).__name__
            failure["resource_message"] = str(resource_error)
    result_body: dict[str, object] = {
        "arc_trace_events": len(events),
        "completion_genuinely_observed": policy.completion_genuinely_observed,
        "decision_provider": "external-hosted-codex-operator",
        "decision_provider_claim_ceiling": (
            "Codex model/runtime identity is session-declared, not artifact-hash-bound"
        ),
        "environment_acquisition_network_mode": ACQUISITION_NETWORK_MODE,
        "environment_actions": policy.actions,
        "environment_runtime_network_mode": RUNTIME_NETWORK_MODE,
        "environment_runtime_socket_guard": {
            "attempt_count": socket_guard.attempt_count,
            "enforcement": "Python socket entry-point denial",
            "os_level_denial_claimed": False,
        },
        "failure": failure,
        "game_id": args.game_id,
        "metrics": metrics,
        "policy_network_mode": POLICY_NETWORK_MODE,
        "protocol_sha256": args.protocol_sha256,
        "recording_path": measured_recordings.relative_to(ROOT).as_posix(),
        "resources": resource_snapshot,
        "resets": policy.resets,
        "run_id": args.run_id,
        "schema": "arc3.strongwiz-local-public-result.v0.1",
        "scorecard": _scorecard_payload(scorecard),
        "evidence_path": run_root.relative_to(ROOT).as_posix(),
        "strongwiz_commit": source_identity.commit,
        "strongwiz_integration_scope": "contracts+routing+PEA-PECAN+SQLiteLedger; not full ReasoningSession runtime",
        "surface": "local-public",
        "verified": False,
    }
    result_body["result_sha256"] = sha256_bytes(canonical_json(result_body).encode("utf-8"))
    result = cast(dict[str, JSONValue], normalize_json(result_body))
    result_path = run_root / "result.json"
    encoded_result_bytes = len((canonical_json(result) + "\n").encode("utf-8"))
    if encoded_result_bytes > RESULT_EVIDENCE_MAX_BYTES:
        raise EvaluationError("Strongwiz result exceeded its frozen evidence reserve")
    evidence_before_result, _, _ = resource_guard.evidence_bytes()
    if (
        evidence_before_result + encoded_result_bytes + COMPLETION_RECEIPT_RESERVE_BYTES
        > MAX_EVIDENCE_BYTES
    ):
        raise EvaluationError("Strongwiz final result would cross the evidence-byte ceiling")
    _write_immutable(result_path, result)
    completed = exposure.append(
        "strongwiz.measured-run.completed",
        {
            "completion_genuinely_observed": policy.completion_genuinely_observed,
            "environment_acquisition_network_mode": ACQUISITION_NETWORK_MODE,
            "environment_runtime_network_mode": RUNTIME_NETWORK_MODE,
            "game_id": args.game_id,
            "intent_event_hash": intent["event_hash"],
            "policy_network_mode": POLICY_NETWORK_MODE,
            "result_sha256": result["result_sha256"],
            "run_id": args.run_id,
        },
    )
    completed_bytes = len((canonical_json(completed) + "\n").encode("utf-8"))
    if completed_bytes > COMPLETION_RECEIPT_RESERVE_BYTES:
        raise EvaluationError("Strongwiz completion receipt exceeded its frozen evidence reserve")
    resource_guard.enforce(boundary="post-finalization", finalization=True)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("acquire", "play"))
    parser.add_argument("--game-id", default=DEFAULT_TARGET)
    parser.add_argument("--seed", type=int, default=FROZEN_SEED)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST,
    )
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--protocol-sha256", required=True)
    parser.add_argument("--strongwiz-source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--strongwiz-archive", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--environments-dir", type=Path, default=DEFAULT_ENVIRONMENTS)
    parser.add_argument("--recordings-dir", type=Path, default=DEFAULT_RECORDINGS)
    parser.add_argument("--exposure-ledger", type=Path, default=DEFAULT_EXPOSURE)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT,
    )
    parser.add_argument("--run-id")
    parser.add_argument("--frozen-commit")
    parser.add_argument("--max-actions", type=int, default=FROZEN_MAX_ACTIONS)
    parser.add_argument("--max-resets", type=int, default=FROZEN_MAX_RESETS)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "acquire":
            result = _acquire(args)
        else:
            if args.run_id is None or args.frozen_commit is None:
                raise EvaluationError("play requires --run-id and --frozen-commit")
            result = _play(args)
        print(canonical_json(result))
        return 0 if result.get("failure") is None else 1
    except (ARC3Error, OSError, ValueError) as error:
        print(
            json.dumps(
                {
                    "error": str(error),
                    "exception_type": type(error).__name__,
                    "schema": "arc3.strongwiz-command-failure.v0.1",
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
