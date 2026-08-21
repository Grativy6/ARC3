"""Canonical evaluation artifact writing, sealing, and verification."""

from __future__ import annotations

import hashlib
import json
import math
import os
import shlex
import subprocess
import uuid
from pathlib import Path
from typing import Any, TypeGuard

from arc3.errors import EvaluationError, TraceError
from arc3.trace import EventJournal, ReplayEngine

_MANIFEST_SCHEMA = "arc3.evaluation.manifest.v0.1"
_RUN_SCHEMA = "arc3.evaluation.run.v0.1"
_TERMINAL_STATUSES = {"PASS", "PARTIAL", "FAILED_INFRASTRUCTURE"}
_RUN_STATUSES = {"success", "failure", "timeout", "crash", "unsupported"}
_BASE_REQUIRED_ARTIFACTS = {
    "results.jsonl",
    "summary.json",
    "report.md",
    "reproduce.json",
    "reproduce.txt",
}
_IDENTITY_FIELDS = (
    "git_commit",
    "dirty_worktree",
    "dirty_worktree_reason",
    "first_party_source_hash",
    "upstream_lock_hash",
    "upstream_lock_reason",
    "public_partition_manifest_hash",
    "public_partition_manifest_note",
    "performance_threshold_hash",
    "python_version",
    "platform",
    "hardware",
    "agent_config",
    "config_hash",
    "games",
    "seeds",
    "action_budget",
    "wall_clock_budget_seconds",
    "budgets",
    "network_mode",
    "identity_hash",
)


def canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode()


def sha256_bytes(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def canonical_object_hash(value: dict[str, Any], *, hash_field: str) -> str:
    unsigned = {key: item for key, item in value.items() if key != hash_field}
    return sha256_bytes(canonical_json_bytes(unsigned))


def seal_object(value: dict[str, Any], *, hash_field: str) -> dict[str, Any]:
    sealed = {key: item for key, item in value.items() if key != hash_field}
    sealed[hash_field] = canonical_object_hash(sealed, hash_field=hash_field)
    return sealed


def verify_object_hash(value: dict[str, Any], *, hash_field: str) -> bool:
    expected = value.get(hash_field)
    try:
        actual = canonical_object_hash(value, hash_field=hash_field)
    except (TypeError, ValueError):
        return False
    return isinstance(expected, str) and expected == actual


def atomic_write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_write_text(path: Path, content: str) -> None:
    atomic_write_bytes(path, content.encode("utf-8"))


def atomic_write_json(path: Path, value: object) -> None:
    atomic_write_bytes(path, canonical_json_bytes(value))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def resolve_evaluation(
    value: str | Path, *, output_root: Path = Path("artifacts/evaluations")
) -> Path:
    candidate = Path(value)
    if candidate.is_dir():
        return candidate.resolve()
    located = output_root / str(value)
    if located.is_dir():
        return located.resolve()
    raise EvaluationError(f"evaluation {value!s} was not found")


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise EvaluationError(f"{path.name} must contain a JSON object")
    return value


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            raise EvaluationError(f"{path.name}:{line_number} is invalid JSON") from error
        if not isinstance(value, dict):
            raise EvaluationError(f"{path.name}:{line_number} must contain a JSON object")
        values.append(value)
    return values


def _safe_artifact_path(directory: Path, relative: str) -> Path:
    parts = relative.split("/")
    if (
        not relative
        or Path(relative).is_absolute()
        or "\\" in relative
        or any(not part or part in {".", ".."} or ":" in part for part in parts)
    ):
        raise EvaluationError(f"unsafe artifact path: {relative!r}")
    try:
        root = directory.resolve()
        candidate = (root / relative).resolve()
    except (OSError, ValueError) as error:
        raise EvaluationError(f"invalid artifact path: {relative!r}") from error
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise EvaluationError(f"artifact path escapes evaluation root: {relative!r}") from error
    if candidate.relative_to(root).as_posix() != relative:
        raise EvaluationError(f"artifact path is not canonical: {relative!r}")
    return candidate


def _actual_artifacts(directory: Path) -> set[str]:
    return {
        path.relative_to(directory).as_posix()
        for path in directory.rglob("*")
        if path.is_file() and path.relative_to(directory).as_posix() != "manifest.json"
    }


def _expected_run_map(manifest: dict[str, Any], errors: list[str]) -> dict[str, dict[str, Any]]:
    raw = manifest.get("expected_runs")
    if not isinstance(raw, list) or not raw:
        errors.append("manifest expected_runs is missing or empty")
        return {}
    expected: dict[str, dict[str, Any]] = {}
    for item in raw:
        if not isinstance(item, dict):
            errors.append("manifest expected_runs contains a non-object")
            continue
        run_id = item.get("run_id")
        if not isinstance(run_id, str) or not run_id:
            errors.append("manifest expected run has no run_id")
            continue
        if run_id in expected:
            errors.append(f"manifest expected run is duplicated: {run_id}")
            continue
        expected[run_id] = item
    return expected


def _manifest_identity(manifest: dict[str, Any]) -> dict[str, Any]:
    return {field: manifest.get(field) for field in _IDENTITY_FIELDS}


def _verify_trace(
    directory: Path,
    result: dict[str, Any],
    errors: list[str],
) -> None:
    run_id = str(result.get("run_id", ""))
    metrics = result.get("metrics")
    action_count = 0
    if isinstance(metrics, dict):
        environment_actions = metrics.get("environment_actions", 0)
        resets = metrics.get("resets", 0)
        if isinstance(environment_actions, int) and isinstance(resets, int):
            action_count = environment_actions + resets
    trace = result.get("trace")
    if trace is None:
        if result.get("status") == "success" or action_count:
            errors.append(f"run {run_id} has actions/success without an immutable trace")
        return
    if not isinstance(trace, dict):
        errors.append(f"run {run_id} trace receipt is not an object")
        return
    relative = trace.get("path")
    if not isinstance(relative, str):
        errors.append(f"run {run_id} trace path is missing")
        return
    try:
        trace_root = _safe_artifact_path(directory, relative)
        if not trace_root.is_dir():
            errors.append(f"run {run_id} trace directory is missing")
            return
        active_path = trace_root / "active.jsonl"
        if not active_path.is_file():
            errors.append(f"run {run_id} active trace file is missing")
            return
        if active_path.stat().st_size:
            errors.append(f"run {run_id} trace has unsealed active events")
            return
        journal = EventJournal(trace_root, run_id=run_id, fsync_on_flush=False)
        try:
            replay = ReplayEngine(journal)
            events = replay.verify_integrity(verify_blobs=True)
            replayed_frames = replay.replay_frames()
            manifest_hash = journal.manifest.manifest_hash
        finally:
            journal.close()
    except (OSError, EvaluationError, TraceError, ValueError) as error:
        errors.append(f"run {run_id} trace verification failed: {type(error).__name__}: {error}")
        return
    if trace.get("event_count") != len(events):
        errors.append(f"run {run_id} trace event count disagrees with replay")
    if trace.get("replayed_frame_count") != len(replayed_frames):
        errors.append(f"run {run_id} replayed frame count disagrees with replay")
    consequences = sum(event.event_type == "consequence.received" for event in events)
    submitted = sum(event.event_type == "action.submitted" for event in events)
    event_type_counts: dict[str, int] = {}
    environment_actions = 0
    resets = 0
    pending_submission_id: str | None = None
    pending_action: object = None
    for event in events:
        event_type_counts[event.event_type] = event_type_counts.get(event.event_type, 0) + 1
        if event.event_type == "action.submitted":
            if pending_submission_id is not None:
                errors.append(
                    f"run {run_id} traces multiple actions without an intervening consequence"
                )
            pending_submission_id = event.event_id
            pending_action = event.payload.get("action")
        if event.event_type == "consequence.received":
            action = event.payload.get("action")
            if pending_submission_id is None:
                errors.append(f"run {run_id} traces a consequence without a submitted action")
            else:
                submitted_event_id = event.payload.get("submitted_event_id")
                if submitted_event_id is not None and submitted_event_id != pending_submission_id:
                    errors.append(f"run {run_id} consequence links to the wrong submitted action")
                if action != pending_action:
                    errors.append(f"run {run_id} consequence action differs from its submission")
            pending_submission_id = None
            pending_action = None
            name = action.get("name") if isinstance(action, dict) else None
            if name == "RESET":
                resets += 1
            else:
                environment_actions += 1
    if result.get("status") == "success" and pending_submission_id is not None:
        errors.append(f"run {run_id} successful trace ends with an unclosed submitted action")
    if result.get("status") == "success" and submitted != consequences:
        errors.append(f"run {run_id} successful trace does not pair every submitted action")
    if trace.get("schema") != "arc3.evaluation.trace-receipt.v0.1":
        errors.append(f"run {run_id} trace receipt has the wrong schema")
    if trace.get("run_id") != run_id:
        errors.append(f"run {run_id} trace receipt has the wrong run_id")
    if trace.get("replay_verified") is not True:
        errors.append(f"run {run_id} trace receipt is not marked replay-verified")
    if trace.get("trace_manifest_hash") != manifest_hash:
        errors.append(f"run {run_id} trace manifest hash disagrees with replay")
    tail_hash = events[-1].event_hash if events else None
    if trace.get("tail_event_hash") != tail_hash:
        errors.append(f"run {run_id} trace tail hash disagrees with replay")
    if trace.get("event_type_counts") != event_type_counts:
        errors.append(f"run {run_id} trace event-type counts disagree with replay")
    if trace.get("submitted_action_count") != submitted:
        errors.append(f"run {run_id} submitted-action trace count disagrees")
    if trace.get("consequence_count") != consequences:
        errors.append(f"run {run_id} consequence trace count disagrees")
    if action_count != consequences:
        errors.append(
            f"run {run_id} reports {action_count} actions/resets but traces {consequences} consequences"
        )
    if trace.get("environment_action_count") != environment_actions:
        errors.append(f"run {run_id} environment-action trace count disagrees")
    if trace.get("reset_count") != resets:
        errors.append(f"run {run_id} reset trace count disagrees")
    byte_length = sum(path.stat().st_size for path in trace_root.rglob("*") if path.is_file())
    if trace.get("byte_length") != byte_length:
        errors.append(f"run {run_id} trace byte length disagrees with sealed files")
    recovery = trace.get("recovery")
    if recovery is not None:
        if not isinstance(recovery, dict):
            errors.append(f"run {run_id} trace recovery receipt is not an object")
        else:
            recovery_relative = recovery.get("path")
            if not isinstance(recovery_relative, str):
                errors.append(f"run {run_id} trace recovery path is unsafe")
            else:
                try:
                    recovery_path = _safe_artifact_path(trace_root, recovery_relative)
                except EvaluationError:
                    errors.append(f"run {run_id} trace recovery path is unsafe")
                else:
                    if not recovery_path.is_file():
                        errors.append(f"run {run_id} preserved recovery bytes are missing")
                    else:
                        original_length = recovery.get("original_byte_length")
                        recovered_length = recovery.get("recovered_byte_length")
                        discarded_length = recovery.get("discarded_byte_length")
                        if recovery.get("sha256") != sha256_file(recovery_path):
                            errors.append(f"run {run_id} preserved recovery hash disagrees")
                        if original_length != recovery_path.stat().st_size:
                            errors.append(f"run {run_id} preserved recovery length disagrees")
                        if (
                            isinstance(original_length, bool)
                            or not isinstance(original_length, int)
                            or isinstance(recovered_length, bool)
                            or not isinstance(recovered_length, int)
                            or isinstance(discarded_length, bool)
                            or not isinstance(discarded_length, int)
                            or recovered_length + discarded_length != original_length
                        ):
                            errors.append(f"run {run_id} trace recovery lengths disagree")


def _is_finite_number(value: object) -> TypeGuard[int | float]:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def _verify_score_and_metrics(
    receipt: dict[str, Any], specification: dict[str, Any], errors: list[str]
) -> None:
    run_id = str(receipt.get("run_id", ""))
    score = receipt.get("score")
    metrics = receipt.get("metrics")
    if not isinstance(score, dict) or not isinstance(metrics, dict):
        errors.append(f"run {run_id} score or metrics is not an object")
        return
    for field in ("score", "total_score"):
        if not _is_finite_number(score.get(field)):
            errors.append(f"run {run_id} score field {field} is not finite")
    if score.get("score") != score.get("total_score"):
        errors.append(f"run {run_id} score and total_score disagree")
    if score.get("official_rhae") is not None:
        errors.append(f"run {run_id} synthetic score must not claim official RHAE")
    if score.get("human_baselines_available") is not False:
        errors.append(f"run {run_id} synthetic score claims unavailable human baselines")
    if score.get("level_human_baseline_actions") != []:
        errors.append(f"run {run_id} synthetic score contains human baseline actions")
    levels_completed = score.get("levels_completed")
    if isinstance(levels_completed, bool) or not isinstance(levels_completed, int):
        errors.append(f"run {run_id} levels_completed is not an integer")
    status = receipt.get("status")
    failure = receipt.get("failure")
    if status == "success":
        if failure is not None:
            errors.append(f"run {run_id} success has a failure payload")
        if score.get("verified") is not True or score.get("scorer") != "arc3.synthetic.v1":
            errors.append(f"run {run_id} success lacks the synthetic scorer receipt")
        game_score = score.get("game_score")
        if not _is_finite_number(game_score) or game_score != score.get("score"):
            errors.append(f"run {run_id} game score disagrees with total score")
        if score.get("level_scores") != [game_score]:
            errors.append(f"run {run_id} level scores disagree with the synthetic scorecard")
        completed = score.get("completed")
        if not isinstance(completed, bool) or completed != bool(levels_completed):
            errors.append(f"run {run_id} completion fields disagree")
    else:
        if not isinstance(failure, dict) or not isinstance(failure.get("kind"), str):
            errors.append(f"run {run_id} failure status lacks a typed failure payload")
        if score.get("verified") is not False or score.get("game_score") is not None:
            errors.append(f"run {run_id} failed run claims a verified game score")
    environment_actions = metrics.get("environment_actions")
    resets = metrics.get("resets")
    if (
        isinstance(environment_actions, bool)
        or not isinstance(environment_actions, int)
        or environment_actions < 0
        or environment_actions > specification.get("max_actions", -1)
    ):
        errors.append(f"run {run_id} environment action count violates its budget")
    if (
        isinstance(resets, bool)
        or not isinstance(resets, int)
        or resets < 0
        or resets > specification.get("max_resets", -1)
    ):
        errors.append(f"run {run_id} reset count violates its budget")
    if status == "success" and score.get("level_actions") != [environment_actions]:
        errors.append(f"run {run_id} level action count disagrees with metrics")
    wall_clock = metrics.get("total_wall_clock_seconds")
    if not _is_finite_number(wall_clock) or float(wall_clock) < 0:
        errors.append(f"run {run_id} wall-clock measurement is invalid")
    peak_ram = metrics.get("peak_ram_bytes")
    if peak_ram is not None and (
        isinstance(peak_ram, bool) or not isinstance(peak_ram, int) or peak_ram < 0
    ):
        errors.append(f"run {run_id} peak Python allocation measurement is invalid")
    for field in (
        "repeated_no_op_rate",
        "invalid_action_rate",
        "coordinate_action_hit_rate",
        "state_revisitation_rate",
        "transitions_explained_fraction",
        "retrodiction_contradiction_rate",
        "planner_success_rate",
    ):
        value = metrics.get(field)
        if value is not None and (not _is_finite_number(value) or not 0.0 <= float(value) <= 1.0):
            errors.append(f"run {run_id} metric {field} is outside [0, 1]")
    latency = metrics.get("decision_latency_seconds")
    if not isinstance(latency, dict):
        errors.append(f"run {run_id} decision latency receipt is not an object")
    else:
        ordered_latency: list[float] = []
        for quantile in ("p50", "p95", "p99"):
            value = latency.get(quantile)
            if value is None:
                continue
            if not _is_finite_number(value) or float(value) < 0:
                errors.append(f"run {run_id} decision latency {quantile} is invalid")
            else:
                ordered_latency.append(float(value))
        if ordered_latency != sorted(ordered_latency):
            errors.append(f"run {run_id} decision latency quantiles are not monotonic")


def _verify_reproduction(directory: Path, manifest: dict[str, Any], errors: list[str]) -> None:
    try:
        reproduction = load_json(directory / "reproduce.json")
    except (OSError, EvaluationError, json.JSONDecodeError) as error:
        errors.append(f"reproduce.json is invalid: {type(error).__name__}")
        return
    argv = reproduction.get("argv")
    declaration = manifest.get("agent_config")
    if (
        reproduction.get("schema") != "arc3.evaluation.reproduction.v0.1"
        or not isinstance(argv, list)
        or not argv
        or not all(isinstance(item, str) and item for item in argv)
        or not isinstance(declaration, dict)
    ):
        errors.append("reproduce.json has an invalid envelope")
        return
    executable = Path(argv[0])
    if not executable.is_absolute() or "python" not in executable.name.lower():
        errors.append("reproduce argv does not pin an absolute Python interpreter")
    agents = declaration.get("agents")
    seeds = declaration.get("seeds")
    expected_tail = [
        "-m",
        "arc3",
        "evaluate",
        "--partition",
        str(declaration.get("partition")),
        "--agents",
        ",".join(str(item) for item in agents) if isinstance(agents, list) else "",
        "--seeds",
        ",".join(str(item) for item in seeds) if isinstance(seeds, list) else "",
        "--max-actions",
        str(declaration.get("max_actions")),
        "--max-resets",
        str(declaration.get("max_resets")),
        "--timeout-seconds",
        str(declaration.get("timeout_seconds")),
        "--output-root",
    ]
    if argv[1:-1] != expected_tail or "--evaluation-id" in argv:
        errors.append("reproduce argv disagrees with the sealed evaluation declaration")
    if not Path(argv[-1]).is_absolute():
        errors.append("reproduce output root is not absolute")
    working_directory = reproduction.get("working_directory")
    if not isinstance(working_directory, str) or not Path(working_directory).is_absolute():
        errors.append("reproduce working_directory is not absolute")
    quoted = (
        subprocess.list2cmdline(argv)
        if str(manifest.get("platform", "")).startswith("Windows")
        else shlex.join(argv)
    )
    try:
        reproduce_text = (directory / "reproduce.txt").read_text(encoding="utf-8")
    except OSError as error:
        errors.append(f"reproduce.txt is unreadable: {type(error).__name__}")
    else:
        if reproduce_text != quoted + "\n":
            errors.append("reproduce.txt does not quote the sealed argv exactly")


def run_receipt_errors(
    directory: Path,
    receipt: dict[str, Any],
    specification: dict[str, Any],
    identity: dict[str, Any],
    *,
    verify_trace: bool = True,
) -> list[str]:
    """Return semantic/self-hash errors that make a run receipt unsafe to resume."""

    errors: list[str] = []
    run_id = str(specification.get("run_id", ""))
    if receipt.get("schema") != _RUN_SCHEMA:
        errors.append(f"run {run_id} has the wrong schema")
    if not verify_object_hash(receipt, hash_field="receipt_hash"):
        errors.append(f"run {run_id} receipt hash mismatch")
    for field in ("evaluation_id", "run_id", "agent", "seed", "baseline_id", "run_spec_hash"):
        if receipt.get(field) != specification.get(field):
            errors.append(f"run {run_id} {field} disagrees with its declaration")
    if receipt.get("surface") != "synthetic" or receipt.get("partition") != "smoke":
        errors.append(f"run {run_id} evaluation surface is not synthetic smoke")
    if receipt.get("status") not in _RUN_STATUSES:
        errors.append(f"run {run_id} has a non-terminal status")
    embedded_identity = receipt.get("identity")
    if not isinstance(embedded_identity, dict) or embedded_identity != identity:
        errors.append(f"run {run_id} identity disagrees with its evaluation")
    elif not verify_object_hash(embedded_identity, hash_field="identity_hash"):
        errors.append(f"run {run_id} embedded identity hash mismatch")
    _verify_score_and_metrics(receipt, specification, errors)
    if verify_trace:
        _verify_trace(directory, receipt, errors)
    return errors


def _verify_semantics(
    directory: Path,
    manifest: dict[str, Any],
    expected: dict[str, dict[str, Any]],
    errors: list[str],
) -> None:
    try:
        results = load_jsonl(directory / "results.jsonl")
        summary = load_json(directory / "summary.json")
    except (OSError, EvaluationError, json.JSONDecodeError) as error:
        errors.append(f"result aggregate is invalid: {type(error).__name__}: {error}")
        return
    receipts: list[dict[str, Any]] = []
    reference_identity: dict[str, Any] | None = None
    for run_id, specification in sorted(expected.items()):
        path = directory / "runs" / f"{run_id}.json"
        try:
            receipt = load_json(path)
        except (OSError, EvaluationError, json.JSONDecodeError) as error:
            errors.append(f"run receipt {run_id} is invalid: {type(error).__name__}")
            continue
        receipts.append(receipt)
        raw_identity = receipt.get("identity")
        expected_identity = _manifest_identity(manifest)
        errors.extend(run_receipt_errors(directory, receipt, specification, expected_identity))
        if isinstance(raw_identity, dict):
            if reference_identity is None:
                reference_identity = raw_identity
            elif raw_identity != reference_identity:
                errors.append(f"run {run_id} embedded identity differs across run receipts")
        failure_copy = directory / "failures" / f"{run_id}.json"
        if receipt.get("status") == "success":
            if failure_copy.exists():
                errors.append(f"run {run_id} success has a terminal failure copy")
        elif not failure_copy.is_file():
            errors.append(f"run {run_id} failure receipt was not retained")
        else:
            try:
                retained = load_json(failure_copy)
            except (OSError, EvaluationError, json.JSONDecodeError) as error:
                errors.append(f"run {run_id} retained failure is invalid: {type(error).__name__}")
            else:
                if retained != receipt:
                    errors.append(f"run {run_id} retained failure differs from its run receipt")
    ordered_receipts = sorted(receipts, key=lambda item: str(item.get("run_id", "")))
    ordered_results = sorted(results, key=lambda item: str(item.get("run_id", "")))
    if ordered_results != ordered_receipts:
        errors.append("results.jsonl is not an exact aggregate of declared run receipts")
    if len(results) != len(expected):
        errors.append("results.jsonl row count disagrees with expected_runs")
    result_ids = [str(item.get("run_id", "")) for item in results]
    if len(result_ids) != len(set(result_ids)):
        errors.append("results.jsonl contains duplicate run IDs")
    if set(result_ids) != set(expected):
        errors.append("results.jsonl run IDs disagree with expected_runs")
    if summary.get("evaluation_id") != manifest.get("evaluation_id"):
        errors.append("summary evaluation_id disagrees with the manifest")
    if summary.get("status") != manifest.get("status"):
        errors.append("summary status disagrees with the manifest")
    if summary.get("result_count") != len(results):
        errors.append("summary result_count disagrees with results.jsonl")
    failure_count = sum(item.get("status") != "success" for item in results)
    if summary.get("failure_count") != failure_count:
        errors.append("summary failure_count disagrees with results.jsonl")
    from .reports import build_summary

    rebuilt_summary = build_summary(str(manifest.get("evaluation_id", "")), ordered_receipts)
    for key, value in rebuilt_summary.items():
        if key != "status" and summary.get(key) != value:
            errors.append(f"summary field {key} disagrees with declared run receipts")
    regression = summary.get("performance_regression")
    regression_status: object = None
    if not isinstance(regression, dict):
        errors.append("summary performance_regression is missing or invalid")
    else:
        regression_status = regression.get("status")
        checks = regression.get("checks")
        if regression_status not in {"PASS", "FAIL", "NOT_APPLICABLE"} or not isinstance(
            checks, list
        ):
            errors.append("summary performance_regression has invalid status/checks")
        elif regression_status == "PASS" and (
            not checks
            or not all(isinstance(item, dict) and item.get("passed") is True for item in checks)
        ):
            errors.append("summary performance_regression PASS is not supported by its checks")
        elif regression_status == "FAIL" and not any(
            isinstance(item, dict) and item.get("passed") is False for item in checks
        ):
            errors.append("summary performance_regression FAIL has no failed check")
        elif regression_status == "NOT_APPLICABLE" and checks:
            errors.append("summary non-applicable performance threshold contains checks")
    from .thresholds import evaluate_performance_thresholds

    declaration = manifest.get("agent_config")
    recomputed_regression = evaluate_performance_thresholds(
        ordered_receipts,
        declaration=declaration if isinstance(declaration, dict) else None,
    )
    if regression != recomputed_regression:
        errors.append("summary performance_regression disagrees with recomputed thresholds")
    expected_status = (
        "FAILED_INFRASTRUCTURE" if regression_status == "FAIL" else rebuilt_summary["status"]
    )
    if summary.get("status") != expected_status:
        errors.append("summary status is inconsistent with run and threshold outcomes")
    _verify_reproduction(directory, manifest, errors)
    try:
        rendered_report = (directory / "report.md").read_text(encoding="utf-8")
    except OSError as error:
        errors.append(f"report.md is unreadable: {type(error).__name__}")
    else:
        required_report_values = (
            f"# Evaluation {manifest.get('evaluation_id')}",
            f"Status: **{summary.get('status')}**",
            "NO_GENERALIZATION_CLAIM",
            str(manifest.get("first_party_source_hash")),
            str(manifest.get("config_hash")),
        )
        if any(value not in rendered_report for value in required_report_values):
            errors.append("report.md disagrees with the sealed evaluation envelope")


def verify_evaluation_artifacts(directory: Path) -> dict[str, object]:
    """Verify a closed artifact set, self-seals, semantics, and trace replay."""

    directory = directory.resolve()
    manifest_path = directory / "manifest.json"
    errors: list[str] = []
    checked: dict[str, str] = {}
    if not manifest_path.is_file():
        return {
            "schema": "arc3.evaluation.verification.v0.1",
            "verified": False,
            "evaluation": str(directory),
            "checked": checked,
            "errors": ["manifest.json is missing"],
        }
    try:
        manifest = load_json(manifest_path)
    except (OSError, EvaluationError, json.JSONDecodeError) as error:
        return {
            "schema": "arc3.evaluation.verification.v0.1",
            "verified": False,
            "evaluation": str(directory),
            "checked": checked,
            "errors": [f"manifest.json is invalid: {type(error).__name__}"],
        }
    if manifest.get("schema") != _MANIFEST_SCHEMA:
        errors.append(f"manifest schema is not {_MANIFEST_SCHEMA}")
    if manifest.get("status") not in _TERMINAL_STATUSES:
        errors.append("manifest status is not terminal")
    if not verify_object_hash(manifest, hash_field="manifest_hash"):
        errors.append("manifest self-hash mismatch")
    missing_identity_fields = [field for field in _IDENTITY_FIELDS if field not in manifest]
    if missing_identity_fields:
        errors.append(f"manifest identity fields are missing: {missing_identity_fields}")
    elif not verify_object_hash(_manifest_identity(manifest), hash_field="identity_hash"):
        errors.append("manifest deterministic identity hash mismatch")
    expected = _expected_run_map(manifest, errors)
    declaration = manifest.get("agent_config")
    if not isinstance(declaration, dict):
        errors.append("manifest agent_config is missing or invalid")
    else:
        if manifest.get("config_hash") != sha256_bytes(canonical_json_bytes(declaration)):
            errors.append("manifest config_hash disagrees with agent_config")
        if declaration.get("surface") != manifest.get("surface"):
            errors.append("manifest surface disagrees with agent_config")
        if declaration.get("partition") != manifest.get("partition"):
            errors.append("manifest partition disagrees with agent_config")
        budgets = manifest.get("budgets")
        budget_map = budgets if isinstance(budgets, dict) else {}
        for identity_field, declaration_field in {
            "seeds": "seeds",
            "action_budget": "max_actions",
            "wall_clock_budget_seconds": "timeout_seconds",
            "network_mode": "network_mode",
        }.items():
            if manifest.get(identity_field) != declaration.get(declaration_field):
                errors.append(
                    f"manifest {identity_field} disagrees with agent_config {declaration_field}"
                )
        for budget_field, declaration_field in {
            "maximum_actions": "max_actions",
            "maximum_resets": "max_resets",
            "maximum_wall_clock_seconds": "timeout_seconds",
        }.items():
            if budget_map.get(budget_field) != declaration.get(declaration_field):
                errors.append(
                    f"manifest budget {budget_field} disagrees with agent_config {declaration_field}"
                )
        agents = declaration.get("agents")
        seeds = declaration.get("seeds")
        if (
            isinstance(agents, list)
            and bool(agents)
            and all(isinstance(agent, str) and agent for agent in agents)
            and isinstance(seeds, list)
            and bool(seeds)
            and all(not isinstance(seed, bool) and isinstance(seed, int) for seed in seeds)
        ):
            declared_pairs = {(str(agent), int(seed)) for agent in agents for seed in seeds}
        else:
            declared_pairs = set()
        valid_expected = all(
            isinstance(item.get("agent"), str)
            and not isinstance(item.get("seed"), bool)
            and isinstance(item.get("seed"), int)
            for item in expected.values()
        )
        expected_pairs = (
            {(str(item["agent"]), int(item["seed"])) for item in expected.values()}
            if valid_expected
            else set()
        )
        if not declared_pairs or expected_pairs != declared_pairs:
            errors.append("manifest expected_runs disagrees with declared agents and seeds")
        for run_id, specification in expected.items():
            if not verify_object_hash(specification, hash_field="run_spec_hash"):
                errors.append(f"manifest run specification hash mismatch: {run_id}")
            for field, value in {
                "evaluation_id": manifest.get("evaluation_id"),
                "identity_hash": manifest.get("identity_hash"),
                "max_actions": declaration.get("max_actions"),
                "max_resets": declaration.get("max_resets"),
                "timeout_seconds": declaration.get("timeout_seconds"),
            }.items():
                if specification.get(field) != value:
                    errors.append(f"manifest run {run_id} {field} disagrees with its declaration")
    hashes = manifest.get("artifact_hashes")
    required = manifest.get("required_artifacts")
    if not isinstance(required, list) or not all(isinstance(item, str) for item in required):
        errors.append("manifest required_artifacts is missing or invalid")
        required_set: set[str] = set()
    else:
        required_set = set(required)
    expected_required = _BASE_REQUIRED_ARTIFACTS | {f"runs/{run_id}.json" for run_id in expected}
    if required != sorted(required_set):
        errors.append("manifest required_artifacts is not a sorted unique list")
    if expected_required != required_set:
        missing = sorted(expected_required - required_set)
        unexpected = sorted(required_set - expected_required)
        if missing:
            errors.append(f"manifest omits required artifacts: {missing}")
        if unexpected:
            errors.append(f"manifest has unexpected required artifacts: {unexpected}")
    if not isinstance(hashes, dict) or not hashes:
        errors.append("manifest artifact_hashes is missing or empty")
        hash_map: dict[str, str] = {}
    else:
        hash_map = {}
        for relative, expected_hash in hashes.items():
            if not isinstance(relative, str) or not isinstance(expected_hash, str):
                errors.append("artifact hash entry has a non-string key or value")
                continue
            hash_map[relative] = expected_hash
    actual = _actual_artifacts(directory)
    if set(hash_map) != actual:
        missing_hashes = sorted(actual - set(hash_map))
        missing_files = sorted(set(hash_map) - actual)
        if missing_hashes:
            errors.append(f"unsealed artifact files: {missing_hashes}")
        if missing_files:
            errors.append(f"declared artifacts are missing: {missing_files}")
    if not required_set.issubset(actual):
        errors.append(f"required artifacts are missing: {sorted(required_set - actual)}")
    for relative, expected_hash in sorted(hash_map.items()):
        try:
            path = _safe_artifact_path(directory, relative)
        except EvaluationError as error:
            errors.append(str(error))
            continue
        if not path.is_file():
            continue
        actual_hash = sha256_file(path)
        checked[relative] = actual_hash
        if actual_hash != expected_hash:
            errors.append(f"hash mismatch: {relative}")
    if not errors:
        _verify_semantics(directory, manifest, expected, errors)
    return {
        "schema": "arc3.evaluation.verification.v0.1",
        "verified": not errors,
        "evaluation": str(directory),
        "manifest_hash": sha256_file(manifest_path),
        "checked": checked,
        "errors": errors,
    }


__all__ = [
    "atomic_write_bytes",
    "atomic_write_json",
    "atomic_write_text",
    "canonical_json_bytes",
    "canonical_object_hash",
    "load_json",
    "load_jsonl",
    "resolve_evaluation",
    "run_receipt_errors",
    "seal_object",
    "sha256_bytes",
    "sha256_file",
    "verify_evaluation_artifacts",
    "verify_object_hash",
]
