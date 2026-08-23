"""Opaque-holdout Build 001 competition-integrity authority.

The authority is deliberately narrower than a full public-identifier scan.  It
combines a fresh complete static package scan, direct scans for only the already
exposed Stage 09 development identifiers, the sealed holdout nonconsumption
receipt, and the verified Stage 09 terminal.  It never opens or resolves the
public manifest, and it records the static/dynamic/native limitation explicitly.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import json
import os
import platform
import subprocess
import sys
import tomllib
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, cast

from arc3.errors import EvaluationError
from arc3.evaluation.artifacts import (
    canonical_json_bytes,
    seal_object,
    sha256_bytes,
    sha256_file,
    verify_object_hash,
)
from arc3.evaluation.development_recovery import validate_predeclaration_bytes
from arc3.integrity import (
    INTEGRITY_SCHEMA,
    IntegrityReceipt,
    discover_candidate_files,
    discover_policy_files,
    discover_reachable_policy_files,
    scan_policy_files,
)
from arc3.types import JSONValue

COMPOSITE_INTEGRITY_SCHEMA = "arc3.build-001.competition-integrity-composite.v0.1"
COMPOSITE_INTEGRITY_HASH_FIELD = "artifact_core_hash"
OPAQUE_PUBLIC_MANIFEST_SHA256 = (
    "sha256:682d5891c2aface54803d9bd1173c55ed21e89856e13b8a478fb9276ee963f2f"
)
COMPETITION_CONFIG_PATH = "src/arc3/competition-runtime.v0.1.json"
DEPENDENCY_LOCK_PATH = "uv.lock"
UPSTREAM_LOCK_PATH = "upstream.lock.json"

_REQUIRED_CHECKS = frozenset(
    {
        "archive_static",
        "policy_static",
        "secret_scan",
        "source_identity",
        "supply_chain",
    }
)
_RUNTIME_DISTRIBUTIONS = (
    ("arc-agi", "arc_agi/"),
    ("arcengine", "arcengine/"),
)
_SCORER_DISTRIBUTION = "arc-agi"
_SCORER_MODULE = "arc_agi/scorecard.py"
_PRODUCTION_POLICY_ENTRY_POINTS = ["agent/my_agent.py"]
_STAGE09_VERIFICATION_SCHEMA = "arc3.build-001.stage-09-terminal-verification.v0.2"
_STAGE09_ACCEPTANCE_SCHEMA = "arc3.build-001.stage-09-development-recovery-acceptance.v0.1"
_STAGE09_ACCEPTANCE_FILE_SHA256 = (
    "sha256:e44473f2335fee5ccf8bd4f911a0d615caf92f9696375ebe6e57697e5622b3b8"
)
_STAGE09_ACCEPTANCE_EVIDENCE_HASH = (
    "sha256:29d1961ae7b30e50222806a066b4d1d4a51c7255391a06a0b87ed9d1e8140b23"
)
_STAGE09_AGGREGATE_SCHEMA = "arc3.build-001.stage-09-aggregate.v0.4"
_STAGE09_PREFLIGHT_SCHEMA = "arc3.build-001.stage-09-preflight.v0.5"
_STAGE09_HARNESS_BINDING_SCHEMA = "arc3.build-001.stage-09-harness-source-binding.v0.2"
_STAGE09_HARNESS_OBSERVATION_SCHEMA = "arc3.build-001.stage-09-harness-source-observation.v0.2"
_STAGE09_PRIOR_AUTHORITY_SCHEMA = "arc3.build-001.stage-09-prior-authority.v0.3"
_STAGE09_FINALIZATION_SCHEMA = "arc3.build-001.stage-09-terminal-finalization.v0.3"
_STAGE09_WORKER_SPEC_SCHEMA = "arc3.build-001.stage-09-worker-spec.v0.4"
_STAGE09_PROCESS_LAUNCH_SCHEMA = "arc3.build-001.stage-09-process-launch.v0.1"
_STAGE09_LAUNCH_AUTHORIZATION_SCHEMA = "arc3.build-001.stage-09-launch-authorization.v0.1"
_STAGE09_WORKER_ABORT_SCHEMA = "arc3.build-001.stage-09-worker-abort.v0.1"
_STAGE09_FAILED_INFRASTRUCTURE = "FAILED_INFRASTRUCTURE"
_STAGE09_ACCEPTANCE_CLAIM = "NO_LOCAL_PUBLIC_RECOVERY_OR_GENERALIZATION_CLAIM"
_STAGE09_ACCEPTANCE_CLAIM_BOUNDARY = (
    "The unique predeclared attempt exposed one development cell but aborted before "
    "opening its environment. It supplies infrastructure and evidence-integrity "
    "observations only, not gameplay, baseline, recovery, action-efficiency, holdout, "
    "private-platform, or hidden-game performance evidence."
)
_STAGE09_AGGREGATE_CLAIM_BOUNDARY = (
    "development recovery only; no public-holdout or hidden-game generalization claim"
)
_STAGE09_SEALED_HOLDOUT: dict[str, JSONValue] = {
    "identities_loaded": 0,
    "manifest_loaded_as_metadata": False,
    "public_holdout_gameplay_events": 0,
    "status": "SEALED_UNCONSUMED",
}
_STAGE09_ACCEPTANCE_FIELDS = {
    "attempt",
    "claim",
    "claim_boundary",
    "decision",
    "evidence_hash",
    "evidence_label",
    "failure_diagnosis",
    "frozen_identity",
    "integrity",
    "key_artifact_sha256",
    "protocol",
    "recorded_at",
    "resources",
    "schema",
    "status",
    "terminal",
    "validation",
}
_STAGE09_VERIFICATION_FIELDS = {
    "attempt_root",
    "competition_integrity",
    "evidence_integrity",
    "execution_complete",
    "exposure",
    "gate",
    "output",
    "passed",
    "prior_authority",
    "schema",
    "source_end",
    "source_root",
    "source_stable",
    "status",
    "terminal_finalization",
    "verification_hash",
    "work_authority",
}
_STAGE09_PRIOR_AUTHORITY_FIELDS = {
    "assurance_limitation",
    "build_001_package_only",
    "development_scans",
    "full_public_integrity_status",
    "holdout",
    "predeclaration",
    "prior_authority_hash",
}
_STAGE09_HOLDOUT_FIELDS = {
    "file_sha256",
    "identities_loaded",
    "manifest_loaded_as_metadata",
    "pinned_manifest_sha256",
    "public_holdout_gameplay_events",
    "status",
}
_STAGE09_ASSURANCE_LIMITATION = (
    "Package and development scans are static; dynamic-import and native-extension "
    "containment are not proven; Build 001 public identifiers were not fully evaluated."
)
_STATIC_LIMITATION = (
    "Static first-party import reachability does not prove runtime dynamic-import "
    "or native-extension containment."
)

_STAGE09_HARNESS_FILES = frozenset(
    {
        "scripts/_stage09_development_worker.py",
        "scripts/_stage09_supervisor_bootstrap.py",
        "scripts/measure_development_recovery.py",
        "src/arc3/evaluation/development_recovery.py",
    }
)
_STAGE09_KEY_ARTIFACT_DIRECTORIES = {
    "cell_finalization": "cell-finalizations",
    "launch_authorization": "launch-authorizations",
    "parent_evidence": "parent-evidence",
    "parent_receipt": "parent-receipts",
    "process_launch": "process-launches",
    "supervision_receipt": "supervision-receipts",
    "worker_abort": "worker-aborts",
    "worker_spec": "specs",
}
_STAGE09_PARTIAL_GRAPH_SENTINEL = b"ARC3_STAGE09_PARTIAL_GRAPH_OK\n"
_STAGE09_PARTIAL_GRAPH_PROBE = r"""
import json
import sys
from pathlib import Path

config = json.loads(sys.stdin.read())
root = Path(config["harness_root"]).resolve()
script = (root / "scripts/measure_development_recovery.py").resolve()
protocol = (root / "src/arc3/evaluation/development_recovery.py").resolve()
sys.path.insert(0, str(root))
import scripts.measure_development_recovery as stage09


def exact_origin(function, expected):
    code = getattr(function, "__code__", None)
    return code is not None and Path(code.co_filename).resolve() == expected


if Path(stage09.__file__).resolve() != script or stage09.ROOT.resolve() != root:
    raise RuntimeError("Stage 09 partial verifier module origin changed")
for name in (
    "verify_complete_terminal",
    "preflight",
    "_attach_run_clock",
    "_load_existing_terminal",
    "_load_receipt_prefix",
    "_load_finalization_prefix",
    "_reconstruct_cell_receipt",
    "_reconstruct_cell_finalization",
    "_validate_exposures",
    "_validate_terminal_finalization",
    "_load_canonical_sealed",
):
    if not exact_origin(getattr(stage09, name, None), script):
        raise RuntimeError(f"Stage 09 partial verifier helper origin changed: {name}")
if not exact_origin(stage09.build_matrix, protocol):
    raise RuntimeError("Stage 09 partial verifier protocol origin changed")

output = Path(config["output"])
work_root = Path(config["work_root"])
exposure = Path(config["exposure"])
recordings = Path(config["recordings"])
environments = Path(config["environments"])
build_000_root = Path(config["build_000_root"])
build_001_root = Path(config["build_001_root"])
candidate = stage09._load_canonical_sealed(
    output,
    schema=stage09.AGGREGATE_SCHEMA,
    hash_field="artifact_core_hash",
    label="terminal output",
)
if candidate.get("artifact_core_hash") != config["artifact_core_hash"]:
    raise RuntimeError("Stage 09 partial verifier aggregate core changed")
embedded = candidate.get("preflight")
harness = embedded.get("harness_source") if isinstance(embedded, dict) else None
expected = harness.get("expected") if isinstance(harness, dict) else None
if not isinstance(expected, dict):
    raise RuntimeError("Stage 09 partial verifier harness binding is absent")
check = stage09.preflight(
    harness_source_expected=expected,
    output=output,
    work_root=work_root,
    exposure=exposure,
    recordings=recordings,
    environments=environments,
    build_000_root=build_000_root,
    build_001_root=build_001_root,
    prior_integrity_receipt=Path(config["prior_integrity_receipt"]),
    build_000_integrity_receipt=Path(config["build_000_integrity_receipt"]),
    enforce_official_paths=False,
)
if check.get("status") != "READY_NOT_EXECUTED":
    raise RuntimeError("Stage 09 partial verifier live preflight is not ready")
live_harness = check.get("harness_source")
live_expected = live_harness.get("expected") if isinstance(live_harness, dict) else None
binding_hash = live_expected.get("binding_hash") if isinstance(live_expected, dict) else None
check = stage09._attach_run_clock(
    check,
    work_root=work_root,
    harness_binding_hash=binding_hash,
    create_missing=False,
)
arguments = {
    "output": output,
    "work_root": work_root,
    "exposure": exposure,
    "check": check,
    "recordings": recordings,
    "environments": environments,
    "build_000_root": build_000_root,
    "build_001_root": build_001_root,
}
try:
    stage09._load_existing_terminal(**arguments, allow_recovery=False)
except stage09.EvaluationError as error:
    if str(error) != "Stage 09 read-only verifier requires complete execution":
        raise
else:
    raise RuntimeError("Stage 09 strict verifier unexpectedly accepted partial execution")


def forbidden_side_effect(*_args, **_kwargs):
    raise RuntimeError("Stage 09 partial verifier attempted a side effect")


stage09._atomic_create = forbidden_side_effect
stage09._atomic_create_or_verify = forbidden_side_effect
stage09._seal_orphan_boundary = forbidden_side_effect
stage09._terminate_orphan_exact = forbidden_side_effect
reconstructed = stage09._load_existing_terminal(**arguments, allow_recovery=True)
if reconstructed != candidate:
    raise RuntimeError("Stage 09 partial terminal differs from official reconstruction")
sys.stdout.buffer.write(b"ARC3_STAGE09_PARTIAL_GRAPH_OK\n")
"""


def _mapping(value: object, *, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise EvaluationError(f"{field} must be an object")
    return cast(Mapping[str, object], value)


def _json_without_duplicate_keys(raw: bytes) -> object:
    def object_hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError(f"duplicate JSON key: {key}")
            value[key] = item
        return value

    return json.loads(raw, object_pairs_hook=object_hook)


def _sha256(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        raise EvaluationError(f"{field} must be a sha256 identity")
    digest = value.removeprefix("sha256:")
    if (
        not value.startswith("sha256:")
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise EvaluationError(f"{field} must be a sha256 identity")
    return value


def _git_hash(value: object, *, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 40
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise EvaluationError(f"{field} must be a full lowercase git identity")
    return value


def _git(root: Path, *arguments: str) -> str:
    repository = root.resolve()
    environment = {
        key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")
    }
    environment["GIT_NO_REPLACE_OBJECTS"] = "1"
    try:
        completed = subprocess.run(
            ("git", "--no-replace-objects", "-C", str(repository), *arguments),
            cwd=repository,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise EvaluationError("composite integrity source identity is unavailable") from error
    return completed.stdout.strip()


def _source_identity(root: Path) -> dict[str, JSONValue]:
    repository = root.resolve()
    top_level = Path(_git(repository, "rev-parse", "--show-toplevel")).resolve()
    if top_level != repository:
        raise EvaluationError("composite integrity Git root differs from execution source")
    commit = _git(repository, "rev-parse", "HEAD")
    tree = _git(repository, "rev-parse", "HEAD^{tree}")
    dirty = bool(_git(repository, "status", "--porcelain=v1", "--untracked-files=all"))
    _git_hash(commit, field="execution source commit")
    _git_hash(tree, field="execution source tree")
    return {"clean_worktree": not dirty, "commit": commit, "tree": tree}


def _detached_source_identity(
    root: Path,
    *,
    expected_commit: object,
    expected_tree: object,
    field: str,
) -> dict[str, JSONValue]:
    repository = root.resolve()
    commit_expected = _git_hash(expected_commit, field=f"{field} commit")
    tree_expected = _git_hash(expected_tree, field=f"{field} tree")
    top_level = Path(_git(repository, "rev-parse", "--show-toplevel")).resolve()
    commit = _git(repository, "rev-parse", "HEAD^{commit}")
    tree = _git(repository, "rev-parse", "HEAD^{tree}")
    branch = _git(repository, "branch", "--show-current")
    dirty = bool(_git(repository, "status", "--porcelain=v1", "--untracked-files=all"))
    if (
        top_level != repository
        or commit != commit_expected
        or tree != tree_expected
        or branch
        or dirty
    ):
        raise EvaluationError(f"{field} must be the exact clean detached Git source")
    return {
        "clean_worktree": True,
        "commit": commit,
        "detached": True,
        "root": repository.as_posix(),
        "tree": tree,
    }


def _absolute_artifact_path(value: object, *, field: str) -> Path:
    if not isinstance(value, str):
        raise EvaluationError(f"{field} must be an absolute path")
    candidate = Path(value)
    if not candidate.is_absolute() or candidate.is_symlink():
        raise EvaluationError(f"{field} must be an absolute non-symlink path")
    return candidate.resolve()


def _read_canonical_sealed_artifact(
    path: Path,
    *,
    schema: str,
    hash_field: str,
    field: str,
) -> tuple[bytes, dict[str, object]]:
    if path.is_symlink() or not path.is_file():
        raise EvaluationError(f"{field} is unavailable")
    try:
        raw = path.read_bytes()
        value = _json_without_duplicate_keys(raw)
    except (OSError, UnicodeDecodeError, ValueError) as error:
        raise EvaluationError(f"{field} is unreadable") from error
    if (
        not isinstance(value, dict)
        or canonical_json_bytes(value) != raw
        or value.get("schema") != schema
        or not verify_object_hash(value, hash_field=hash_field)
    ):
        raise EvaluationError(f"{field} is not the expected canonical sealed artifact")
    return raw, cast(dict[str, object], value)


def _stage09_partial_evidence_inventory(
    *,
    aggregate_path: Path,
    finalization_path: Path,
    exposure_path: Path,
    work_root: Path,
    cell_ordinal: int,
    cell_id: str,
) -> tuple[dict[str, dict[str, JSONValue]], dict[str, Path]]:
    """Hash the exact 16-file partial-terminal evidence inventory."""

    stage_root = aggregate_path.resolve().parent
    finalization = finalization_path.resolve()
    exposure = exposure_path.resolve()
    work = work_root.resolve()
    if (
        finalization != Path(f"{aggregate_path.resolve()}.finalization.json")
        or exposure.parent != stage_root
        or work.parent != stage_root
        or work.is_symlink()
        or not work.is_dir()
        or not cell_id
        or any(character not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for character in cell_id)
    ):
        raise EvaluationError("Stage 09 partial evidence paths changed")
    prefix = f"{cell_ordinal:02d}-{cell_id}"
    filename = f"{prefix}.json"
    key_paths = {
        key: work / directory / filename
        for key, directory in _STAGE09_KEY_ARTIFACT_DIRECTORIES.items()
    }
    key_paths["run_clock"] = work / "run-clock.json"
    expected_paths = {
        aggregate_path.resolve(),
        finalization,
        exposure,
        work / "active-cell-segments" / filename,
        work / "spawn-intents" / filename,
        work / "parent-streams" / prefix / "stderr.bin",
        work / "parent-streams" / prefix / "stdout.bin",
        *key_paths.values(),
    }
    try:
        entries = tuple(work.rglob("*"))
    except OSError as error:
        raise EvaluationError("Stage 09 partial evidence inventory is unreadable") from error
    if any(entry.is_symlink() for entry in entries):
        raise EvaluationError("Stage 09 partial evidence inventory contains a symlink")
    actual_paths = {
        aggregate_path.resolve(),
        finalization,
        exposure,
        *(entry.resolve() for entry in entries if entry.is_file()),
    }
    if actual_paths != expected_paths or len(expected_paths) != 16:
        raise EvaluationError("Stage 09 partial evidence inventory changed")

    inventory: dict[str, dict[str, JSONValue]] = {}
    try:
        for artifact_path in sorted(expected_paths, key=lambda item: item.as_posix()):
            if artifact_path.is_symlink() or not artifact_path.is_file():
                raise EvaluationError("Stage 09 partial evidence artifact is unavailable")
            label = artifact_path.relative_to(stage_root).as_posix()
            inventory[label] = {
                "bytes": artifact_path.stat().st_size,
                "sha256": sha256_file(artifact_path),
            }
    except (OSError, ValueError) as error:
        raise EvaluationError("Stage 09 partial evidence inventory is unreadable") from error
    return inventory, key_paths


def _validated_stage09_partial_evidence_inventory(
    *,
    aggregate_path: Path,
    finalization_path: Path,
    exposure_path: Path,
    work_root: Path,
    cell_ordinal: int,
    cell_id: str,
    expected_file_count: object,
    expected_total_bytes: object,
    expected_manifest_sha256: object,
    expected_key_artifacts: Mapping[str, object],
) -> tuple[dict[str, dict[str, JSONValue]], dict[str, Path]]:
    inventory, key_paths = _stage09_partial_evidence_inventory(
        aggregate_path=aggregate_path,
        finalization_path=finalization_path,
        exposure_path=exposure_path,
        work_root=work_root,
        cell_ordinal=cell_ordinal,
        cell_id=cell_id,
    )
    total_bytes = sum(cast(int, item["bytes"]) for item in inventory.values())
    manifest_sha256 = sha256_bytes(canonical_json_bytes(inventory))
    if (
        not _exact_integer(expected_file_count, 16)
        or not _exact_integer(expected_total_bytes, total_bytes)
        or _sha256(
            expected_manifest_sha256,
            field="Stage 09 partial evidence manifest hash",
        )
        != manifest_sha256
    ):
        raise EvaluationError("Stage 09 partial evidence inventory authority changed")
    if set(expected_key_artifacts) != set(key_paths):
        raise EvaluationError("Stage 09 key artifact inventory changed")
    for label, artifact_path in key_paths.items():
        expected_sha256 = _sha256(
            expected_key_artifacts.get(label),
            field=f"Stage 09 {label} file hash",
        )
        if sha256_file(artifact_path) != expected_sha256:
            raise EvaluationError(f"Stage 09 {label} file hash changed")
    return inventory, key_paths


def _stage09_authorization_predicate_audit(
    *,
    key_paths: Mapping[str, Path],
    work_root: Path,
    cell_prefix: str,
    harness_root: Path,
    runtime_executable: Path,
    diagnosis: Mapping[str, object],
) -> None:
    """Re-evaluate the worker's exact 19 launch-authorization clauses."""

    _spec_raw, spec = _read_canonical_sealed_artifact(
        key_paths["worker_spec"],
        schema=_STAGE09_WORKER_SPEC_SCHEMA,
        hash_field="worker_spec_hash",
        field="Stage 09 worker spec",
    )
    _launch_raw, launch = _read_canonical_sealed_artifact(
        key_paths["process_launch"],
        schema=_STAGE09_PROCESS_LAUNCH_SCHEMA,
        hash_field="launch_receipt_hash",
        field="Stage 09 process launch",
    )
    _authorization_raw, authorization = _read_canonical_sealed_artifact(
        key_paths["launch_authorization"],
        schema=_STAGE09_LAUNCH_AUTHORIZATION_SCHEMA,
        hash_field="authorization_hash",
        field="Stage 09 launch authorization",
    )
    _abort_raw, abort = _read_canonical_sealed_artifact(
        key_paths["worker_abort"],
        schema=_STAGE09_WORKER_ABORT_SCHEMA,
        hash_field="worker_abort_hash",
        field="Stage 09 worker abort",
    )
    launch_token = launch.get("launch_token")
    if not isinstance(launch_token, str):
        raise EvaluationError("Stage 09 launch token is absent")
    result_path = work_root / "cells" / cell_prefix / "raw-worker-result.json"
    worker_script = harness_root / "scripts/_stage09_development_worker.py"
    expected_command = [
        str(runtime_executable.resolve()),
        "-I",
        str(worker_script.resolve()),
        "--spec",
        str(key_paths["worker_spec"].resolve()),
        "--result",
        str(result_path.resolve()),
        "--launch-receipt",
        str(key_paths["process_launch"].resolve()),
        "--authorization",
        str(key_paths["launch_authorization"].resolve()),
        "--abort-receipt",
        str(key_paths["worker_abort"].resolve()),
        "--launch-token",
        launch_token,
    ]
    worker_pid = abort.get("pid")
    spec_sha256 = sha256_file(key_paths["worker_spec"])
    predicates = {
        "launch_schema": launch.get("schema") == _STAGE09_PROCESS_LAUNCH_SCHEMA,
        "launch_self_hash": verify_object_hash(launch, hash_field="launch_receipt_hash"),
        "authorization_schema": (
            authorization.get("schema") == _STAGE09_LAUNCH_AUTHORIZATION_SCHEMA
        ),
        "authorization_self_hash": verify_object_hash(
            authorization,
            hash_field="authorization_hash",
        ),
        "launch_pid_matches_worker": launch.get("pid") == worker_pid,
        "launch_token_matches_argument": launch.get("launch_token") == launch_token,
        "launch_authorization_path_matches_argument": (
            launch.get("authorization_path")
            == key_paths["launch_authorization"].resolve().as_posix()
        ),
        "launch_command_matches_expected": launch.get("command") == expected_command,
        "launch_worker_spec_hash_matches_spec": (
            launch.get("worker_spec_hash") == spec.get("worker_spec_hash")
        ),
        "launch_worker_spec_sha256_matches_file": (launch.get("worker_spec_sha256") == spec_sha256),
        "authorization_pid_matches_worker": authorization.get("pid") == worker_pid,
        "authorization_launch_token_matches_argument": (
            authorization.get("launch_token") == launch_token
        ),
        "authorization_launch_receipt_hash_matches_launch": (
            authorization.get("launch_receipt_hash") == launch.get("launch_receipt_hash")
        ),
        "authorization_process_creation_token_matches_launch": (
            authorization.get("process_creation_token") == launch.get("process_creation_token")
        ),
        "authorization_command_matches_expected": (
            authorization.get("command") == expected_command
        ),
        "authorization_worker_spec_hash_matches_spec": (
            authorization.get("worker_spec_hash") == spec.get("worker_spec_hash")
        ),
        "authorization_worker_spec_sha256_matches_file": (
            authorization.get("worker_spec_sha256") == spec_sha256
        ),
        "authorization_raw_path_matches_argument": (
            authorization.get("raw_path") == result_path.resolve().as_posix()
        ),
        "authorization_abort_path_matches_argument": (
            authorization.get("abort_path") == key_paths["worker_abort"].resolve().as_posix()
        ),
    }
    false_predicates = [name for name, passed in predicates.items() if not passed]
    launcher_pid = launch.get("pid")
    if (
        len(predicates) != 19
        or sum(predicates.values()) != 17
        or false_predicates != ["launch_pid_matches_worker", "authorization_pid_matches_worker"]
        or diagnosis.get("false_authorization_predicates") != false_predicates
        or not _exact_integer(diagnosis.get("authorization_predicate_count"), 19)
        or not _exact_integer(diagnosis.get("authorization_predicates_passed"), 17)
        or not isinstance(launcher_pid, int)
        or isinstance(launcher_pid, bool)
        or not isinstance(worker_pid, int)
        or isinstance(worker_pid, bool)
        or launcher_pid == worker_pid
        or diagnosis.get("authorized_launcher_pid") != launcher_pid
        or diagnosis.get("worker_interpreter_pid") != worker_pid
        or authorization.get("pid") != launcher_pid
        or abort.get("environment_opened") is not False
        or abort.get("reason") != "launch-authorization-unavailable-or-invalid"
        or diagnosis.get("environment_opened") is not False
        or diagnosis.get("worker_abort_reason") != "launch-authorization-unavailable-or-invalid"
        or not _exact_integer(diagnosis.get("worker_exit_code"), 73)
    ):
        raise EvaluationError("Stage 09 authorization predicate audit changed")


def _run_stage09_partial_graph_reconstruction(
    *,
    runtime_executable: Path,
    harness_root: Path,
    aggregate_path: Path,
    aggregate_core_hash: str,
    work_root: Path,
    exposure_path: Path,
    recordings_path: Path,
    environments_path: Path,
    build_000_root: Path,
    build_001_root: Path,
    prior_integrity_path: Path,
    build_000_integrity_path: Path,
) -> None:
    """Run the exact H verifier in its recorded Python 3.12 environment."""

    configuration = {
        "artifact_core_hash": aggregate_core_hash,
        "build_000_integrity_receipt": build_000_integrity_path.resolve().as_posix(),
        "build_000_root": build_000_root.resolve().as_posix(),
        "build_001_root": build_001_root.resolve().as_posix(),
        "environments": environments_path.resolve().as_posix(),
        "exposure": exposure_path.resolve().as_posix(),
        "harness_root": harness_root.resolve().as_posix(),
        "output": aggregate_path.resolve().as_posix(),
        "prior_integrity_receipt": prior_integrity_path.resolve().as_posix(),
        "recordings": recordings_path.resolve().as_posix(),
        "work_root": work_root.resolve().as_posix(),
    }
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.upper().startswith(("GIT_", "PYTHON"))
    }
    environment.update(
        {
            "GIT_NO_REPLACE_OBJECTS": "1",
            "NO_PROXY": "*",
            "PIP_NO_INDEX": "1",
        }
    )
    try:
        completed = subprocess.run(
            (
                str(runtime_executable.resolve()),
                "-I",
                "-B",
                "-c",
                _STAGE09_PARTIAL_GRAPH_PROBE,
            ),
            cwd=harness_root.resolve(),
            env=environment,
            input=canonical_json_bytes(configuration),
            check=False,
            capture_output=True,
            timeout=240,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise EvaluationError("Stage 09 partial graph verifier failed to run") from error
    if (
        completed.returncode != 0
        or completed.stdout != _STAGE09_PARTIAL_GRAPH_SENTINEL
        or completed.stderr
    ):
        stdout = completed.stdout.decode("utf-8", errors="replace")[-1000:]
        stderr = completed.stderr.decode("utf-8", errors="replace")[-2000:]
        raise EvaluationError(
            "Stage 09 partial graph failed official reconstruction: "
            f"returncode={completed.returncode}; stdout={stdout!r}; stderr={stderr!r}"
        )


def _stage09_partial_graph_authority(
    *,
    aggregate_path: Path,
    finalization_path: Path,
    build_000_root: Path,
    build_001_root: Path,
    harness_root: Path,
    harness_expected: Mapping[str, object],
    preflight: Mapping[str, object],
    aggregate: Mapping[str, object],
    diagnosis: Mapping[str, object],
    key_artifacts: Mapping[str, object],
    validation: Mapping[str, object],
    resources: Mapping[str, object],
) -> None:
    """Authenticate the complete live raw graph without opening an environment."""

    preflight_paths = _mapping(preflight.get("paths"), field="Stage 09 preflight paths")
    output_path = _absolute_artifact_path(
        preflight_paths.get("output"),
        field="Stage 09 preflight output path",
    )
    exposure_path = _absolute_artifact_path(
        preflight_paths.get("exposure"),
        field="Stage 09 preflight exposure path",
    )
    work_root = _absolute_artifact_path(
        preflight_paths.get("work_root"),
        field="Stage 09 preflight work root",
    )
    recordings_path = _absolute_artifact_path(
        preflight_paths.get("recordings"),
        field="Stage 09 preflight recordings path",
    )
    environments_path = _absolute_artifact_path(
        preflight_paths.get("environments"),
        field="Stage 09 preflight environments path",
    )
    if (
        output_path != aggregate_path.resolve()
        or _absolute_artifact_path(
            preflight_paths.get("build_000_root"),
            field="Stage 09 preflight Build 000 root",
        )
        != build_000_root.resolve()
        or _absolute_artifact_path(
            preflight_paths.get("build_001_root"),
            field="Stage 09 preflight Build 001 root",
        )
        != build_001_root.resolve()
    ):
        raise EvaluationError("Stage 09 partial graph paths changed")
    failure = _mapping(aggregate.get("failure"), field="Stage 09 aggregate failure")
    cell_id = failure.get("cell_id")
    cell_ordinal = failure.get("cell_ordinal")
    if not isinstance(cell_id, str) or not _exact_integer(cell_ordinal, 0):
        raise EvaluationError("Stage 09 partial failure cell identity changed")
    cell_ordinal_int = cast(int, cell_ordinal)
    inventory_before, key_paths = _validated_stage09_partial_evidence_inventory(
        aggregate_path=aggregate_path,
        finalization_path=finalization_path,
        exposure_path=exposure_path,
        work_root=work_root,
        cell_ordinal=cell_ordinal_int,
        cell_id=cell_id,
        expected_file_count=validation.get("reconstruction_evidence_file_count"),
        expected_total_bytes=validation.get("artifact_total_bytes"),
        expected_manifest_sha256=validation.get("artifact_manifest_sha256"),
        expected_key_artifacts=key_artifacts,
    )
    _sha256(
        validation.get("live_reconstruction_preflight_hash"),
        field="Stage 09 live reconstruction preflight hash",
    )
    if (
        set(validation)
        != {
            "artifact_manifest_sha256",
            "artifact_total_bytes",
            "authorization_predicate_audit",
            "evidence_inventory_unchanged",
            "independent_read_only_audit",
            "live_reconstruction_preflight_hash",
            "live_reconstruction_preflight_status",
            "official_reconstruction_loader",
            "official_reconstruction_source",
            "reconstruction_evidence_file_count",
            "source_worktrees",
            "strict_complete_terminal_verifier",
        }
        or validation.get("evidence_inventory_unchanged") is not True
        or validation.get("strict_complete_terminal_verifier")
        != "EXPECTED_REFUSAL:Stage 09 read-only verifier requires complete execution"
        or validation.get("official_reconstruction_loader")
        != "PASS:existing-partial-terminal-reconstructed-exactly"
        or validation.get("live_reconstruction_preflight_status") != "READY_NOT_EXECUTED"
        or validation.get("authorization_predicate_audit")
        != "PASS:19-evaluated+17-true+2-pid-mismatch"
        or validation.get("independent_read_only_audit")
        != "PASS:same-terminal-reconstruction+same-two-false-predicates+zero-mutations"
        or validation.get("source_worktrees")
        != "PASS:detached-clean-H+detached-clean-P+detached-clean-Build-000"
    ):
        raise EvaluationError("Stage 09 partial evidence inventory authority changed")
    if sha256_file(exposure_path) != aggregate.get("exposure_ledger_sha256"):
        raise EvaluationError("Stage 09 live exposure ledger hash changed")

    harness_files = _mapping(
        harness_expected.get("files"),
        field="Stage 09 harness file binding",
    )
    if set(harness_files) != _STAGE09_HARNESS_FILES:
        raise EvaluationError("Stage 09 harness verifier file set changed")
    for label in _STAGE09_HARNESS_FILES:
        expected_sha256 = _sha256(
            harness_files.get(label),
            field=f"Stage 09 harness {label} hash",
        )
        file_path = harness_root / label
        if (
            file_path.is_symlink()
            or not file_path.is_file()
            or sha256_file(file_path) != expected_sha256
        ):
            raise EvaluationError(f"Stage 09 harness {label} bytes changed")
    if (
        _absolute_artifact_path(
            validation.get("official_reconstruction_source"),
            field="Stage 09 official reconstruction source",
        )
        != (harness_root / "scripts/measure_development_recovery.py").resolve()
    ):
        raise EvaluationError("Stage 09 official reconstruction source changed")

    runtime_environment = _mapping(
        preflight.get("runtime_environment"),
        field="Stage 09 runtime environment",
    )
    runtime_expected = _mapping(
        runtime_environment.get("expected"),
        field="Stage 09 expected runtime environment",
    )
    runtime = _mapping(resources.get("runtime"), field="Stage 09 recorded runtime")
    runtime_executable = _absolute_artifact_path(
        runtime_expected.get("executable"),
        field="Stage 09 runtime executable",
    )
    runtime_executable_sha256 = _sha256(
        runtime_expected.get("executable_sha256"),
        field="Stage 09 runtime executable hash",
    )
    if (
        runtime_expected.get("schema") != "arc3.build-001.stage-09-runtime-environment.v0.2"
        or runtime.get("executable") != runtime_executable.as_posix()
        or runtime_executable.is_symlink()
        or not runtime_executable.is_file()
        or sha256_file(runtime_executable) != runtime_executable_sha256
    ):
        raise EvaluationError("Stage 09 recorded runtime identity changed")

    _stage09_authorization_predicate_audit(
        key_paths=key_paths,
        work_root=work_root,
        cell_prefix=f"{cell_ordinal_int:02d}-{cell_id}",
        harness_root=harness_root,
        runtime_executable=runtime_executable,
        diagnosis=diagnosis,
    )
    prior = _mapping(preflight.get("prior_authority"), field="Stage 09 prior authority")
    prior_integrity = _mapping(
        prior.get("integrity"),
        field="Stage 09 prior integrity",
    )
    package = _mapping(
        prior_integrity.get("build_001_package_only"),
        field="Stage 09 prior Build 001 integrity",
    )
    build_000 = _mapping(
        prior_integrity.get("build_000_full"),
        field="Stage 09 prior Build 000 integrity",
    )
    prior_integrity_path = _absolute_artifact_path(
        package.get("path"),
        field="Stage 09 prior Build 001 integrity path",
    )
    build_000_integrity_path = _absolute_artifact_path(
        build_000.get("path"),
        field="Stage 09 prior Build 000 integrity path",
    )
    _run_stage09_partial_graph_reconstruction(
        runtime_executable=runtime_executable,
        harness_root=harness_root,
        aggregate_path=aggregate_path,
        aggregate_core_hash=_sha256(
            aggregate.get("artifact_core_hash"),
            field="Stage 09 aggregate core hash",
        ),
        work_root=work_root,
        exposure_path=exposure_path,
        recordings_path=recordings_path,
        environments_path=environments_path,
        build_000_root=build_000_root,
        build_001_root=build_001_root,
        prior_integrity_path=prior_integrity_path,
        build_000_integrity_path=build_000_integrity_path,
    )
    inventory_after, _key_paths_after = _stage09_partial_evidence_inventory(
        aggregate_path=aggregate_path,
        finalization_path=finalization_path,
        exposure_path=exposure_path,
        work_root=work_root,
        cell_ordinal=cell_ordinal_int,
        cell_id=cell_id,
    )
    if (
        inventory_after != inventory_before
        or sha256_file(runtime_executable) != runtime_executable_sha256
    ):
        raise EvaluationError("Stage 09 official reconstruction mutated its evidence")
    _detached_source_identity(
        harness_root,
        expected_commit=harness_expected.get("git_commit"),
        expected_tree=harness_expected.get("git_tree"),
        field="Stage 09 harness source after reconstruction",
    )


def reachable_policy_projection(root: Path) -> dict[str, str]:
    """Return the exact current production-policy import closure."""

    repository = root.resolve()
    candidates = discover_candidate_files(repository)
    reachable = discover_reachable_policy_files(repository, candidate_files=candidates)
    return {path.relative_to(repository).as_posix(): sha256_file(path) for path in reachable}


def _package_candidate_callable(root: Path) -> Callable[[Path], object]:
    repository = root.resolve()
    expected_script = repository / "scripts/check_competition_integrity.py"
    try:
        module = importlib.import_module("scripts.check_competition_integrity")
    except (ImportError, OSError, RuntimeError, ValueError) as error:
        raise EvaluationError("package-only candidate authority failed to load") from error
    function = getattr(module, "package_only_candidate_files", None)
    origin = getattr(module, "__file__", None)
    code = getattr(function, "__code__", None)
    if (
        not isinstance(origin, str)
        or Path(origin).resolve() != expected_script.resolve()
        or code is None
        or Path(code.co_filename).resolve() != expected_script.resolve()
    ):
        raise EvaluationError("package-only candidate authority has mixed origin")
    return cast(Callable[[Path], object], function)


def _package_candidate_projection(root: Path) -> dict[str, str]:
    repository = root.resolve()
    function = _package_candidate_callable(repository)
    try:
        paths = function(repository)
    except (OSError, RuntimeError, TypeError, ValueError) as error:
        raise EvaluationError("package-only candidate authority failed") from error
    if not isinstance(paths, tuple) or not paths:
        raise EvaluationError("package-only candidate authority returned no files")
    projection: dict[str, str] = {}
    for path in paths:
        if not isinstance(path, Path) or not path.is_file():
            raise EvaluationError("package-only candidate file is unavailable")
        try:
            label = path.resolve().relative_to(repository).as_posix()
        except ValueError as error:
            raise EvaluationError("package-only candidate escaped execution source") from error
        if label in projection:
            raise EvaluationError("package-only candidate authority returned a duplicate")
        projection[label] = sha256_file(path)
    return dict(sorted(projection.items()))


def _stage09_terminal_verifier(source_root: Path) -> Callable[..., object]:
    root = source_root.resolve()
    expected_script = root / "scripts/measure_development_recovery.py"
    try:
        module = importlib.import_module("scripts.measure_development_recovery")
    except (ImportError, OSError, RuntimeError, ValueError) as error:
        raise EvaluationError("Stage 09 terminal verifier failed to load") from error
    verifier = getattr(module, "verify_complete_terminal", None)
    origin = getattr(module, "__file__", None)
    code = getattr(verifier, "__code__", None)
    if (
        not isinstance(origin, str)
        or Path(origin).resolve() != expected_script
        or code is None
        or Path(code.co_filename).resolve() != expected_script
    ):
        raise EvaluationError("Stage 09 terminal verifier has mixed origin")
    return cast(Callable[..., object], verifier)


def _projection_summary(projection: Mapping[str, str]) -> dict[str, JSONValue]:
    return {
        "file_count": len(projection),
        "projection_sha256": sha256_bytes(canonical_json_bytes(dict(projection))),
    }


def _locked_versions(path: Path) -> dict[str, str]:
    try:
        document = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise EvaluationError("uv.lock is unreadable") from error
    packages = document.get("package")
    if not isinstance(packages, list):
        raise EvaluationError("uv.lock has no package inventory")
    versions: dict[str, str] = {}
    for item in packages:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        version = item.get("version")
        if isinstance(name, str) and isinstance(version, str):
            versions[name] = version
    return versions


def _distribution_source_identity(name: str, package_prefix: str) -> dict[str, JSONValue]:
    try:
        distribution = importlib.metadata.distribution(name)
    except importlib.metadata.PackageNotFoundError:
        return {"file_count": 0, "source_sha256": None, "version": None}
    rows: list[tuple[str, int, str]] = []
    for item in sorted(distribution.files or (), key=lambda value: str(value).replace("\\", "/")):
        relative = str(item).replace("\\", "/")
        path = Path(str(distribution.locate_file(item))).resolve()
        if (
            relative.startswith(package_prefix)
            and path.is_file()
            and "__pycache__" not in path.parts
            and path.suffix != ".pyc"
        ):
            rows.append((relative, path.stat().st_size, sha256_file(path)))
    return {
        "file_count": len(rows),
        "source_sha256": sha256_bytes(canonical_json_bytes(rows)),
        "version": distribution.version,
    }


def runtime_surface_identity(root: Path) -> dict[str, Any]:
    """Bind the live interpreter, locked SDK distributions, and scorer bytes.

    This is import-free with respect to the ARC environment SDK.  Distribution
    files are located and hashed as bytes, so the function is safe to call
    before the first holdout authorization.
    """

    repository = root.resolve()
    executable = Path(sys.executable).resolve()
    lock_path = repository / DEPENDENCY_LOCK_PATH
    upstream_path = repository / UPSTREAM_LOCK_PATH
    locked = _locked_versions(lock_path)
    distributions = {
        name: _distribution_source_identity(name, prefix) for name, prefix in _RUNTIME_DISTRIBUTIONS
    }
    try:
        scorer_distribution = importlib.metadata.distribution(_SCORER_DISTRIBUTION)
        scorer_path = Path(str(scorer_distribution.locate_file(_SCORER_MODULE))).resolve()
        scorer_hash = sha256_file(scorer_path) if scorer_path.is_file() else None
    except importlib.metadata.PackageNotFoundError:
        scorer_hash = None
    versions_match_lock = all(
        isinstance(identity.get("version"), str) and identity.get("version") == locked.get(name)
        for name, identity in distributions.items()
    )
    payload: dict[str, Any] = {
        "cache_tag": sys.implementation.cache_tag,
        "distributions": distributions,
        "executable": executable.as_posix(),
        "executable_sha256": sha256_file(executable) if executable.is_file() else None,
        "implementation": platform.python_implementation(),
        "python_version": platform.python_version(),
        "schema": "arc3.build-001.runtime-surface.v0.1",
        "scorer": {
            "distribution": _SCORER_DISTRIBUTION,
            "module": _SCORER_MODULE,
            "sha256": scorer_hash,
        },
        "upstream_lock_sha256": (sha256_file(upstream_path) if upstream_path.is_file() else None),
        "uv_lock_sha256": sha256_file(lock_path) if lock_path.is_file() else None,
        "verified": bool(
            executable.is_file()
            and sys.version_info[:2] == (3, 12)
            and versions_match_lock
            and all(
                isinstance(identity.get("source_sha256"), str)
                and isinstance(identity.get("file_count"), int)
                and cast(int, identity["file_count"]) > 0
                for identity in distributions.values()
            )
            and isinstance(scorer_hash, str)
            and lock_path.is_file()
            and upstream_path.is_file()
        ),
        "versions_match_lock": versions_match_lock,
    }
    return seal_object(payload, hash_field="runtime_surface_sha256")


def _competition_config_identity(root: Path) -> dict[str, JSONValue]:
    path = root.resolve() / COMPETITION_CONFIG_PATH
    try:
        raw = path.read_bytes()
        value: object = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise EvaluationError("competition config is unreadable") from error
    if not isinstance(value, dict):
        raise EvaluationError("competition config is not an object")
    document = cast(dict[str, object], value)
    claimed = _sha256(document.get("configuration_sha256"), field="competition config")
    unsigned = {key: item for key, item in document.items() if key != "configuration_sha256"}
    encoded = json.dumps(
        unsigned,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    if sha256_bytes(encoded) != claimed:
        raise EvaluationError("competition config self-hash changed")
    return {
        "configuration_sha256": claimed,
        "file_sha256": sha256_bytes(raw),
        "path": COMPETITION_CONFIG_PATH,
    }


def _read_integrity(path: Path, *, field: str) -> tuple[bytes, IntegrityReceipt]:
    try:
        raw = path.resolve().read_bytes()
        receipt = IntegrityReceipt.from_bytes(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise EvaluationError(f"{field} is not a canonical integrity receipt") from error
    return raw, receipt


def _checks_clear(body: Mapping[str, JSONValue]) -> bool:
    checks = body.get("checks")
    counts = body.get("finding_counts")
    findings = body.get("findings")
    return bool(
        isinstance(checks, Mapping)
        and set(checks) == _REQUIRED_CHECKS
        and all(
            isinstance(checks[name], Mapping)
            and cast(Mapping[str, object], checks[name]).get("passed") is True
            for name in _REQUIRED_CHECKS
        )
        and cast(Mapping[str, object], checks["supply_chain"]).get("status") == "PASS"
        and isinstance(counts, Mapping)
        and set(counts) == {"blocking", "total", "warnings"}
        and all(
            isinstance(counts.get(name), int)
            and not isinstance(counts.get(name), bool)
            and counts.get(name) == 0
            for name in ("blocking", "total", "warnings")
        )
        and counts.get("blocking") == 0
        and counts.get("total") == 0
        and counts.get("warnings") == 0
        and findings == []
    )


def _development_identifiers(
    predeclaration_path: Path,
    *,
    expected_file_sha256: str,
    expected_core_hash: str,
    expected_sha256: str,
) -> tuple[tuple[str, ...], dict[str, JSONValue]]:
    """Parse only the frozen, already-exposed Stage 09 declaration."""

    _sha256(expected_file_sha256, field="development predeclaration file hash")
    _sha256(expected_core_hash, field="development predeclaration core hash")
    _sha256(expected_sha256, field="development identifier list hash")
    try:
        raw = predeclaration_path.resolve().read_bytes()
        declaration = validate_predeclaration_bytes(
            raw,
            expected_file_sha256=expected_file_sha256,
        )
    except (OSError, EvaluationError) as error:
        raise EvaluationError("Stage 09 development declaration failed validation") from error
    games = declaration.get("development_games")
    bindings = declaration.get("bindings")
    if (
        declaration.get("predeclaration_core_hash") != expected_core_hash
        or not isinstance(games, list)
        or len(games) != 12
        or not isinstance(bindings, Mapping)
        or not isinstance(bindings.get("build_000_commit"), str)
        or not isinstance(bindings.get("build_000_tree"), str)
    ):
        raise EvaluationError("Stage 09 development identity authority changed")
    values: list[str] = []
    for game in games:
        if not isinstance(game, Mapping):
            raise EvaluationError("Stage 09 development identity entry changed")
        game_id = game.get("game_id")
        stable_name = game.get("stable_name")
        if (
            set(game) != {"asset_sha256", "game_id", "stable_name"}
            or not isinstance(game_id, str)
            or not isinstance(stable_name, str)
            or not isinstance(game.get("asset_sha256"), str)
        ):
            raise EvaluationError("Stage 09 development identifier source changed")
        values.extend((game_id, stable_name))
    identifiers = tuple(sorted(set(values)))
    actual = sha256_bytes(canonical_json_bytes(list(identifiers)))
    if len(identifiers) != 24 or actual != expected_sha256:
        raise EvaluationError("Stage 09 development identifier authority changed")
    return identifiers, {
        "development_identity_count": len(games),
        "identifier_string_count": len(identifiers),
        "identifier_list_sha256": actual,
        "build_000_commit": cast(str, bindings["build_000_commit"]),
        "build_000_tree": cast(str, bindings["build_000_tree"]),
        "predeclaration_core_hash": expected_core_hash,
        "predeclaration_file_sha256": expected_file_sha256,
        "source_path": predeclaration_path.resolve().as_posix(),
    }


def _development_scan(
    root: Path,
    *,
    identifiers: tuple[str, ...],
    expected_commit: str,
    expected_tree: str,
) -> dict[str, JSONValue]:
    source = _source_identity(root)
    if (
        source.get("clean_worktree") is not True
        or source.get("commit") != _git_hash(expected_commit, field="development source commit")
        or source.get("tree") != _git_hash(expected_tree, field="development source tree")
    ):
        raise EvaluationError("development policy scan source identity changed")
    files = discover_policy_files(root.resolve())
    findings = scan_policy_files(
        root=root.resolve(),
        files=files,
        public_identifiers=identifiers,
    )
    if findings:
        raise EvaluationError("development-identifier policy scan has blocking findings")
    projection = {
        path.resolve().relative_to(root.resolve()).as_posix(): sha256_file(path) for path in files
    }
    return {
        "finding_count": 0,
        "passed": True,
        "policy_file_count": len(files),
        "policy_projection_sha256": sha256_bytes(canonical_json_bytes(projection)),
        "source": {**source, "root": root.resolve().as_posix()},
    }


def _holdout_nonconsumption_summary(
    path: Path,
    *,
    expected_file_sha256: str,
) -> dict[str, JSONValue]:
    _sha256(expected_file_sha256, field="holdout nonconsumption file hash")
    try:
        raw = path.resolve().read_bytes()
        value: object = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise EvaluationError("holdout nonconsumption receipt is unreadable") from error
    if not isinstance(value, dict) or sha256_bytes(raw) != expected_file_sha256:
        raise EvaluationError("holdout nonconsumption receipt identity changed")
    document = cast(dict[str, object], value)
    projection_raw = document.get("integrity", document.get("holdout"))
    projection = _mapping(projection_raw, field="holdout nonconsumption projection")
    metadata_flag = projection.get(
        "manifest_loaded_as_metadata",
        projection.get("holdout_manifest_loaded_as_gameplay_metadata"),
    )
    manifest_hash = projection.get("holdout_manifest_sha256", projection.get("manifest_sha256"))
    if (
        projection.get("holdout_sealed") is not True
        or isinstance(projection.get("public_holdout_game_ids_selected"), bool)
        or projection.get("public_holdout_game_ids_selected") != 0
        or isinstance(projection.get("public_holdout_gameplay_events"), bool)
        or projection.get("public_holdout_gameplay_events") != 0
        or metadata_flag is not False
        or manifest_hash != OPAQUE_PUBLIC_MANIFEST_SHA256
    ):
        raise EvaluationError("holdout nonconsumption receipt is not sealed and opaque")
    return {
        "file_sha256": expected_file_sha256,
        "manifest_loaded_as_metadata": False,
        "manifest_sha256": OPAQUE_PUBLIC_MANIFEST_SHA256,
        "path": path.resolve().as_posix(),
        "public_holdout_game_ids_selected": 0,
        "public_holdout_gameplay_events": 0,
        "sealed": True,
    }


def _exact_integer(value: object, expected: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value == expected


def _is_sealed_holdout(value: Mapping[str, object]) -> bool:
    return (
        set(value) == set(_STAGE09_SEALED_HOLDOUT)
        and _exact_integer(value.get("identities_loaded"), 0)
        and value.get("manifest_loaded_as_metadata") is False
        and _exact_integer(value.get("public_holdout_gameplay_events"), 0)
        and value.get("status") == "SEALED_UNCONSUMED"
    )


def _recorded_detached_source(
    value: object,
    *,
    expected_root: Path,
    expected_commit: object,
    expected_tree: object,
    expected_source_sha256: object,
    field: str,
) -> dict[str, JSONValue]:
    source = _mapping(value, field=field)
    predicates = _mapping(source.get("predicates"), field=f"{field} predicates")
    source_root = _absolute_artifact_path(source.get("root"), field=f"{field} root")
    commit = _git_hash(expected_commit, field=f"{field} expected commit")
    tree = _git_hash(expected_tree, field=f"{field} expected tree")
    source_sha256 = _sha256(
        expected_source_sha256,
        field=f"{field} expected first-party source hash",
    )
    if (
        set(source)
        != {
            "branch",
            "dirty_worktree",
            "first_party_source_sha256",
            "git_commit",
            "git_tree",
            "passed",
            "predicates",
            "probe_returncode",
            "probe_stderr_sha256",
            "root",
        }
        or set(predicates) != {"clean", "commit", "detached", "import_root", "source_bytes", "tree"}
        or any(item is not True for item in predicates.values())
        or source_root != expected_root.resolve()
        or source.get("git_commit") != commit
        or source.get("git_tree") != tree
        or source.get("first_party_source_sha256") != source_sha256
        or source.get("branch") != ""
        or source.get("dirty_worktree") is not False
        or source.get("passed") is not True
        or not _exact_integer(source.get("probe_returncode"), 0)
    ):
        raise EvaluationError(f"{field} recorded identity is not exact and detached")
    _sha256(source.get("probe_stderr_sha256"), field=f"{field} probe stderr hash")
    return _detached_source_identity(
        source_root,
        expected_commit=commit,
        expected_tree=tree,
        field=field,
    )


def _stage09_failed_infrastructure_summary(
    path: Path,
    *,
    raw: bytes,
    receipt: dict[str, object],
    expected_file_sha256: str,
    expected_evidence_hash: str,
    source_root: Path,
    expected_holdout_nonconsumption_sha256: str,
    expected_development_identifier_sha256: str,
    expected_development_predeclaration_file_sha256: str,
    expected_development_predeclaration_core_hash: str,
    expected_build_000_root: Path | None,
    expected_build_000_commit: str | None,
    expected_build_000_tree: str | None,
) -> dict[str, JSONValue]:
    """Authenticate the one committed Stage 09 infrastructure-failure graph."""

    if expected_build_000_commit is None or expected_build_000_tree is None:
        raise EvaluationError("Stage 09 infrastructure acceptance lacks Build 000 authority")
    build_000_commit = _git_hash(
        expected_build_000_commit,
        field="Stage 09 expected Build 000 commit",
    )
    build_000_tree = _git_hash(
        expected_build_000_tree,
        field="Stage 09 expected Build 000 tree",
    )
    _sha256(
        expected_holdout_nonconsumption_sha256,
        field="Stage 09 holdout nonconsumption file hash",
    )

    # The committed acceptance is intentionally human-readable JSON. Its exact
    # external file hash and self-hash authenticate those bytes; child artifacts
    # below are machine-canonical and therefore also require byte canonicality.
    if (
        expected_file_sha256 != _STAGE09_ACCEPTANCE_FILE_SHA256
        or expected_evidence_hash != _STAGE09_ACCEPTANCE_EVIDENCE_HASH
        or sha256_bytes(raw) != expected_file_sha256
        or set(receipt) != _STAGE09_ACCEPTANCE_FIELDS
        or receipt.get("schema") != _STAGE09_ACCEPTANCE_SCHEMA
        or receipt.get("evidence_hash") != expected_evidence_hash
        or not verify_object_hash(receipt, hash_field="evidence_hash")
    ):
        raise EvaluationError("Stage 09 infrastructure acceptance identity changed")

    frozen = _mapping(receipt.get("frozen_identity"), field="Stage 09 frozen identity")
    protocol = _mapping(receipt.get("protocol"), field="Stage 09 protocol")
    attempt = _mapping(receipt.get("attempt"), field="Stage 09 attempt")
    terminal = _mapping(receipt.get("terminal"), field="Stage 09 terminal")
    terminal_binding = _mapping(
        terminal.get("terminal_finalization"),
        field="Stage 09 terminal finalization binding",
    )
    diagnosis = _mapping(
        receipt.get("failure_diagnosis"),
        field="Stage 09 failure diagnosis",
    )
    integrity = _mapping(receipt.get("integrity"), field="Stage 09 acceptance integrity")
    decision = _mapping(receipt.get("decision"), field="Stage 09 acceptance decision")
    key_artifacts = _mapping(
        receipt.get("key_artifact_sha256"),
        field="Stage 09 key artifact hashes",
    )
    resources = _mapping(receipt.get("resources"), field="Stage 09 acceptance resources")
    validation = _mapping(receipt.get("validation"), field="Stage 09 acceptance validation")

    expected_cells = protocol.get("expected_cells")
    if (
        receipt.get("status") != _STAGE09_FAILED_INFRASTRUCTURE
        or receipt.get("evidence_label") != "local-public"
        or receipt.get("claim") != _STAGE09_ACCEPTANCE_CLAIM
        or receipt.get("claim_boundary") != _STAGE09_ACCEPTANCE_CLAIM_BOUNDARY
        or not isinstance(receipt.get("recorded_at"), str)
        or set(protocol)
        != {
            "attempt_limit",
            "attempts_consumed",
            "development_identity_count",
            "expected_cells",
            "matrix_hash",
            "maximum_actions_per_cell",
            "maximum_resets_per_cell",
            "overall_active_wall_seconds",
            "rerun_allowed",
            "seeds",
            "worker_wall_seconds",
        }
        or not _exact_integer(expected_cells, 96)
        or not _exact_integer(protocol.get("development_identity_count"), 12)
        or not _exact_integer(protocol.get("attempt_limit"), 1)
        or not _exact_integer(protocol.get("attempts_consumed"), 1)
        or protocol.get("rerun_allowed") is not False
        or not _exact_integer(attempt.get("exposed_cell_count"), 1)
        or not _exact_integer(attempt.get("terminal_cell_receipt_count"), 1)
        or not _exact_integer(attempt.get("environment_opened_cell_count"), 0)
        or not _exact_integer(attempt.get("gameplay_action_count"), 0)
        or not _exact_integer(attempt.get("scheduled_cells_not_started"), 95)
        or not _exact_integer(attempt.get("exit_code"), 1)
        or attempt.get("execution_complete") is not False
        or diagnosis.get("environment_opened") is not False
        or terminal.get("schema") != _STAGE09_AGGREGATE_SCHEMA
        or terminal.get("status") != _STAGE09_FAILED_INFRASTRUCTURE
        or terminal.get("execution_complete") is not False
        or terminal.get("failure_kind") != "terminal-cell-infrastructure-failure"
        or not _exact_integer(terminal.get("failed_cell_ordinal"), 0)
        or not _exact_integer(integrity.get("production_static_findings"), 0)
        or not _exact_integer(integrity.get("build_000_blocking_comparator_findings"), 0)
        or not _exact_integer(integrity.get("hosted_inference_calls"), 0)
        or integrity.get("public_holdout_status") != "SEALED_UNCONSUMED"
        or not _exact_integer(integrity.get("public_holdout_identities_loaded"), 0)
        or integrity.get("public_holdout_manifest_loaded_as_metadata") is not False
        or not _exact_integer(integrity.get("public_holdout_gameplay_events"), 0)
        or integrity.get("official_submission") is not False
        or decision.get("stage_status") != _STAGE09_FAILED_INFRASTRUCTURE
        or decision.get("stage_acceptance_satisfied") is not False
        or decision.get("development_recovery_gate") != "NOT_EVALUATED_DUE_INFRASTRUCTURE_FAILURE"
        or decision.get("baseline_or_ablation_comparison_available") is not False
        or decision.get("local_public_recovery_observed") is not False
        or decision.get("holdout_opening_predicate_stage_09_pass") is not False
        or decision.get("attempt_will_not_be_rerun") is not True
    ):
        raise EvaluationError("Stage 09 infrastructure acceptance is not fail-closed")

    matrix_hash = _sha256(protocol.get("matrix_hash"), field="Stage 09 matrix hash")
    aggregate_path = _absolute_artifact_path(terminal.get("path"), field="Stage 09 aggregate path")
    aggregate_raw, aggregate = _read_canonical_sealed_artifact(
        aggregate_path,
        schema=_STAGE09_AGGREGATE_SCHEMA,
        hash_field="artifact_core_hash",
        field="Stage 09 aggregate",
    )
    aggregate_file_hash = _sha256(
        terminal.get("file_sha256"),
        field="Stage 09 aggregate file hash",
    )
    aggregate_core_hash = _sha256(
        terminal.get("artifact_core_hash"),
        field="Stage 09 aggregate core hash",
    )
    cell_receipt_hash = _sha256(
        terminal.get("cell_receipt_hash"),
        field="Stage 09 cell receipt hash",
    )
    cell_finalization_hash = _sha256(
        terminal.get("cell_finalization_hash"),
        field="Stage 09 cell finalization hash",
    )
    exposure_event_hash = _sha256(
        terminal.get("exposure_event_hash"),
        field="Stage 09 exposure event hash",
    )
    exposure_ledger_hash = _sha256(
        terminal.get("exposure_ledger_sha256"),
        field="Stage 09 exposure ledger hash",
    )
    aggregate_failure = _mapping(aggregate.get("failure"), field="Stage 09 aggregate failure")
    aggregate_holdout = _mapping(aggregate.get("holdout"), field="Stage 09 aggregate holdout")
    aggregate_receipts = aggregate.get("cell_receipt_hashes")
    aggregate_finalizations = aggregate.get("cell_finalization_hashes")
    if (
        sha256_bytes(aggregate_raw) != aggregate_file_hash
        or len(aggregate_raw) != terminal.get("file_bytes")
        or aggregate.get("artifact_core_hash") != aggregate_core_hash
        or aggregate.get("status") != _STAGE09_FAILED_INFRASTRUCTURE
        or aggregate.get("execution_complete") is not False
        or aggregate.get("evidence_label") != "local-public"
        or aggregate.get("claim_boundary") != _STAGE09_AGGREGATE_CLAIM_BOUNDARY
        or aggregate.get("matrix_hash") != matrix_hash
        or not _exact_integer(aggregate.get("expected_cell_count"), 96)
        or not _exact_integer(aggregate.get("cell_count"), 1)
        or aggregate_receipts != [cell_receipt_hash]
        or aggregate_finalizations != [cell_finalization_hash]
        or set(aggregate_failure) != {"cell_id", "cell_ordinal", "exposure_event_hash", "kind"}
        or not _exact_integer(aggregate_failure.get("cell_ordinal"), 0)
        or aggregate_failure.get("kind") != "terminal-cell-infrastructure-failure"
        or aggregate_failure.get("exposure_event_hash") != exposure_event_hash
        or aggregate.get("exposure_ledger_sha256") != exposure_ledger_hash
        or not _is_sealed_holdout(aggregate_holdout)
        or aggregate.get("orphan_process") is not None
    ):
        raise EvaluationError("Stage 09 aggregate is not the accepted partial terminal")

    preflight = _mapping(aggregate.get("preflight"), field="Stage 09 embedded preflight")
    preflight_document = dict(preflight)
    preflight_holdout = _mapping(preflight.get("holdout"), field="Stage 09 preflight holdout")
    public_manifest = _mapping(
        preflight.get("public_manifest_identity"),
        field="Stage 09 public manifest identity",
    )
    preflight_paths = _mapping(preflight.get("paths"), field="Stage 09 preflight paths")
    sources = _mapping(preflight.get("sources"), field="Stage 09 preflight sources")
    harness = _mapping(preflight.get("harness_source"), field="Stage 09 harness source")
    harness_expected = _mapping(harness.get("expected"), field="Stage 09 harness binding")
    harness_start = _mapping(harness.get("start"), field="Stage 09 harness observation")
    prior = _mapping(preflight.get("prior_authority"), field="Stage 09 prior authority")
    if (
        preflight.get("schema") != _STAGE09_PREFLIGHT_SCHEMA
        or preflight.get("status") != "READY_NOT_EXECUTED"
        or preflight.get("gameplay_opened") is not False
        or preflight.get("matrix_hash") != matrix_hash
        or not _exact_integer(preflight.get("stage09_exposure_event_count"), 0)
        or not _is_sealed_holdout(preflight_holdout)
        or public_manifest.get("pinned_sha256") != OPAQUE_PUBLIC_MANIFEST_SHA256
        or public_manifest.get("semantic_access") is not False
        or public_manifest.get("verified_by_prior_authority") is not True
        or not verify_object_hash(preflight_document, hash_field="preflight_hash")
        or preflight.get("predeclaration_sha256") != expected_development_predeclaration_file_sha256
        or preflight.get("predeclaration_core_hash")
        != expected_development_predeclaration_core_hash
    ):
        raise EvaluationError("Stage 09 embedded preflight is not sealed and unopened")

    frozen_build_000_commit = _git_hash(
        frozen.get("build_000_comparator_commit"),
        field="Stage 09 frozen Build 000 commit",
    )
    frozen_build_000_tree = _git_hash(
        frozen.get("build_000_comparator_tree"),
        field="Stage 09 frozen Build 000 tree",
    )
    production_commit = _git_hash(
        frozen.get("production_policy_commit"),
        field="Stage 09 frozen production commit",
    )
    production_tree = _git_hash(
        frozen.get("production_policy_tree"),
        field="Stage 09 frozen production tree",
    )
    production_source_hash = _sha256(
        frozen.get("production_policy_source_sha256"),
        field="Stage 09 frozen production source hash",
    )
    harness_commit = _git_hash(
        frozen.get("harness_commit"),
        field="Stage 09 frozen harness commit",
    )
    harness_tree = _git_hash(frozen.get("harness_tree"), field="Stage 09 frozen harness tree")
    harness_binding_hash = _sha256(
        frozen.get("harness_binding_hash"),
        field="Stage 09 frozen harness binding hash",
    )
    _sha256(
        frozen.get("runtime_binding_file_sha256"),
        field="Stage 09 frozen runtime binding file hash",
    )
    _sha256(
        frozen.get("preflight_hash_before_execution"),
        field="Stage 09 frozen preflight hash",
    )
    if frozen_build_000_commit != build_000_commit or frozen_build_000_tree != build_000_tree:
        raise EvaluationError("Stage 09 acceptance changed the frozen Build 000 identity")

    harness_root = _absolute_artifact_path(
        frozen.get("harness_root"),
        field="Stage 09 frozen harness root",
    )
    build_000_root = _absolute_artifact_path(
        preflight_paths.get("build_000_root"),
        field="Stage 09 Build 000 root",
    )
    if expected_build_000_root is not None and build_000_root != expected_build_000_root.resolve():
        raise EvaluationError("Stage 09 acceptance changed the supplied Build 000 root")
    production_root = _absolute_artifact_path(
        preflight_paths.get("build_001_root"),
        field="Stage 09 production root",
    )
    build_000_source = _recorded_detached_source(
        sources.get("build_000"),
        expected_root=build_000_root,
        expected_commit=build_000_commit,
        expected_tree=build_000_tree,
        expected_source_sha256=_mapping(
            sources.get("build_000"), field="Stage 09 Build 000 source"
        ).get("first_party_source_sha256"),
        field="Stage 09 Build 000 source",
    )
    production_source = _recorded_detached_source(
        sources.get("build_001"),
        expected_root=production_root,
        expected_commit=production_commit,
        expected_tree=production_tree,
        expected_source_sha256=production_source_hash,
        field="Stage 09 production source",
    )

    harness_expected_document = dict(harness_expected)
    harness_start_document = dict(harness_start)
    harness_predicates = _mapping(
        harness_start.get("predicates"),
        field="Stage 09 harness predicates",
    )
    if (
        harness_expected.get("schema") != _STAGE09_HARNESS_BINDING_SCHEMA
        or harness_expected.get("binding_hash") != harness_binding_hash
        or harness_expected.get("git_commit") != harness_commit
        or harness_expected.get("git_tree") != harness_tree
        or harness_expected.get("git_object_format") != "sha1"
        or not verify_object_hash(harness_expected_document, hash_field="binding_hash")
        or harness_start.get("schema") != _STAGE09_HARNESS_OBSERVATION_SCHEMA
        or harness_start.get("binding_hash") != harness_binding_hash
        or harness_start.get("git_commit") != harness_commit
        or harness_start.get("git_tree") != harness_tree
        or harness_start.get("git_object_format") != "sha1"
        or harness_start.get("branch") != ""
        or harness_start.get("dirty_worktree") is not False
        or harness_start.get("passed") is not True
        or _absolute_artifact_path(
            harness_start.get("root"),
            field="Stage 09 harness observation root",
        )
        != harness_root
        or set(harness_predicates)
        != {
            "clean",
            "commit",
            "detached",
            "extra_files",
            "files",
            "index_flags",
            "object_format",
            "projection",
            "root",
            "tree",
        }
        or any(item is not True for item in harness_predicates.values())
        or not verify_object_hash(harness_start_document, hash_field="observation_hash")
    ):
        raise EvaluationError("Stage 09 harness binding is not exact and detached")
    harness_source = _detached_source_identity(
        harness_root,
        expected_commit=harness_commit,
        expected_tree=harness_tree,
        field="Stage 09 harness source",
    )

    prior_document = dict(prior)
    prior_holdout = _mapping(prior.get("holdout"), field="Stage 09 prior holdout")
    prior_integrity = _mapping(prior.get("integrity"), field="Stage 09 prior integrity")
    prior_scans = _mapping(
        prior_integrity.get("development_scans"),
        field="Stage 09 prior development scans",
    )
    if (
        prior.get("schema") != _STAGE09_PRIOR_AUTHORITY_SCHEMA
        or prior.get("passed") is not True
        or not verify_object_hash(prior_document, hash_field="authority_hash")
        or prior_holdout.get("file_sha256") != expected_holdout_nonconsumption_sha256
        or prior_holdout.get("pinned_manifest_sha256") != OPAQUE_PUBLIC_MANIFEST_SHA256
        or prior_holdout.get("status") != "SEALED_UNCONSUMED"
        or not _exact_integer(prior_holdout.get("identities_loaded"), 0)
        or prior_holdout.get("manifest_loaded_as_metadata") is not False
        or not _exact_integer(prior_holdout.get("public_holdout_gameplay_events"), 0)
        or prior_scans.get("identifier_list_hash") != expected_development_identifier_sha256
    ):
        raise EvaluationError("Stage 09 prior authority is not exact and sealed")

    finalization_path = _absolute_artifact_path(
        terminal_binding.get("path"),
        field="Stage 09 finalization path",
    )
    finalization_raw, finalization = _read_canonical_sealed_artifact(
        finalization_path,
        schema=_STAGE09_FINALIZATION_SCHEMA,
        hash_field="terminal_finalization_hash",
        field="Stage 09 terminal finalization",
    )
    finalization_file_hash = _sha256(
        terminal_binding.get("file_sha256"),
        field="Stage 09 finalization file hash",
    )
    finalization_hash = _sha256(
        terminal_binding.get("terminal_finalization_hash"),
        field="Stage 09 terminal finalization core hash",
    )
    final_evidence = _mapping(
        finalization.get("evidence_authority"),
        field="Stage 09 final evidence authority",
    )
    final_holdout = _mapping(final_evidence.get("holdout"), field="Stage 09 final holdout")
    final_scans = _mapping(
        final_evidence.get("development_scans"),
        field="Stage 09 final development scans",
    )
    final_predeclaration = _mapping(
        final_evidence.get("predeclaration"),
        field="Stage 09 final predeclaration",
    )
    final_original = _mapping(
        final_predeclaration.get("original"),
        field="Stage 09 final original predeclaration",
    )
    if (
        sha256_bytes(finalization_raw) != finalization_file_hash
        or finalization.get("terminal_finalization_hash") != finalization_hash
        or finalization.get("artifact_core_hash") != aggregate_core_hash
        or finalization.get("output_sha256") != aggregate_file_hash
        or _absolute_artifact_path(
            finalization.get("output_path"),
            field="Stage 09 finalization output path",
        )
        != aggregate_path
        or finalization.get("terminal_authority_passed") is not True
        or finalization.get("within_overall_active_wall") is not True
        or finalization.get("timing_measurement_available") is not True
        or finalization.get("recovery_kind") is not None
        or terminal_binding.get("terminal_authority_passed") is not True
        or terminal_binding.get("within_overall_active_wall") is not True
        or terminal_binding.get("timing_measurement_available") is not True
        or terminal_binding.get("recovery_kind") is not None
        or final_holdout.get("file_sha256") != expected_holdout_nonconsumption_sha256
        or final_holdout.get("pinned_manifest_sha256") != OPAQUE_PUBLIC_MANIFEST_SHA256
        or final_holdout.get("status") != "SEALED_UNCONSUMED"
        or not _exact_integer(final_holdout.get("identities_loaded"), 0)
        or final_holdout.get("manifest_loaded_as_metadata") is not False
        or not _exact_integer(final_holdout.get("public_holdout_gameplay_events"), 0)
        or final_scans.get("identifier_list_hash") != expected_development_identifier_sha256
        or final_original.get("file_sha256") != expected_development_predeclaration_file_sha256
        or final_original.get("core_hash") != expected_development_predeclaration_core_hash
        or final_predeclaration.get("effective_build_001_commit") != production_commit
        or final_predeclaration.get("effective_build_001_tree") != production_tree
        or final_predeclaration.get("effective_build_001_source_sha256") != production_source_hash
    ):
        raise EvaluationError("Stage 09 terminal finalization authority changed")

    _stage09_partial_graph_authority(
        aggregate_path=aggregate_path,
        finalization_path=finalization_path,
        build_000_root=build_000_root,
        build_001_root=production_root,
        harness_root=harness_root,
        harness_expected=harness_expected,
        preflight=preflight,
        aggregate=aggregate,
        diagnosis=diagnosis,
        key_artifacts=key_artifacts,
        validation=validation,
        resources=resources,
    )

    return {
        "authority_scope": "EVIDENCE_INTEGRITY_ONLY",
        "evidence_hash": expected_evidence_hash,
        "evidence_integrity": True,
        "execution_complete": False,
        "file_sha256": expected_file_sha256,
        "output_artifact_core_hash": aggregate_core_hash,
        "output_file_sha256": aggregate_file_hash,
        "path": path.resolve().as_posix(),
        "performance_claim": False,
        "schema": _STAGE09_ACCEPTANCE_SCHEMA,
        "source_identities": {
            "build_000": build_000_source,
            "harness": harness_source,
            "production": production_source,
        },
        "source_root": source_root.resolve().as_posix(),
        "stage09_acceptance_satisfied": False,
        "stage09_pass": False,
        "status": _STAGE09_FAILED_INFRASTRUCTURE,
        "terminal_finalization_hash": finalization_hash,
        "terminal_finalization_sha256": finalization_file_hash,
        # Retain the composite reconstruction key used by complete terminals.
        "verification_hash": expected_evidence_hash,
    }


def _stage09_verification_summary(
    path: Path,
    *,
    expected_file_sha256: str,
    expected_verification_hash: str,
    source_root: Path,
    expected_holdout_nonconsumption_sha256: str,
    expected_development_identifier_sha256: str,
    expected_development_predeclaration_file_sha256: str,
    expected_development_predeclaration_core_hash: str,
    expected_build_000_root: Path | None = None,
    expected_build_000_commit: str | None = None,
    expected_build_000_tree: str | None = None,
) -> dict[str, JSONValue]:
    _sha256(expected_file_sha256, field="Stage 09 verification file hash")
    _sha256(expected_verification_hash, field="Stage 09 verification core hash")
    _sha256(
        expected_development_identifier_sha256,
        field="Stage 09 development identifier list hash",
    )
    _sha256(
        expected_development_predeclaration_file_sha256,
        field="Stage 09 original predeclaration file hash",
    )
    _sha256(
        expected_development_predeclaration_core_hash,
        field="Stage 09 original predeclaration core hash",
    )
    try:
        raw = path.resolve().read_bytes()
        value = _json_without_duplicate_keys(raw)
    except (OSError, UnicodeDecodeError, ValueError) as error:
        raise EvaluationError("Stage 09 terminal verification is unreadable") from error
    if not isinstance(value, dict):
        raise EvaluationError("Stage 09 terminal verification is not an object")
    receipt = cast(dict[str, object], value)
    if receipt.get("schema") == _STAGE09_ACCEPTANCE_SCHEMA:
        return _stage09_failed_infrastructure_summary(
            path,
            raw=raw,
            receipt=receipt,
            expected_file_sha256=expected_file_sha256,
            expected_evidence_hash=expected_verification_hash,
            source_root=source_root,
            expected_holdout_nonconsumption_sha256=expected_holdout_nonconsumption_sha256,
            expected_development_identifier_sha256=expected_development_identifier_sha256,
            expected_development_predeclaration_file_sha256=(
                expected_development_predeclaration_file_sha256
            ),
            expected_development_predeclaration_core_hash=(
                expected_development_predeclaration_core_hash
            ),
            expected_build_000_root=expected_build_000_root,
            expected_build_000_commit=expected_build_000_commit,
            expected_build_000_tree=expected_build_000_tree,
        )
    output = receipt.get("output")
    exposure = receipt.get("exposure")
    finalization = receipt.get("terminal_finalization")
    prior_authority = receipt.get("prior_authority")
    work_authority = receipt.get("work_authority")
    stage09_source_root = receipt.get("source_root")
    attempt_root = receipt.get("attempt_root")
    holdout: Mapping[str, object] | None = None
    predeclaration: Mapping[str, object] | None = None
    package: Mapping[str, object] | None = None
    development_scans: Mapping[str, object] | None = None
    if isinstance(prior_authority, Mapping) and isinstance(prior_authority.get("holdout"), Mapping):
        holdout = cast(Mapping[str, object], prior_authority["holdout"])
    if isinstance(prior_authority, Mapping) and isinstance(
        prior_authority.get("predeclaration"), Mapping
    ):
        predeclaration = cast(Mapping[str, object], prior_authority["predeclaration"])
    if isinstance(prior_authority, Mapping) and isinstance(
        prior_authority.get("build_001_package_only"), Mapping
    ):
        package = cast(Mapping[str, object], prior_authority["build_001_package_only"])
    if isinstance(prior_authority, Mapping) and isinstance(
        prior_authority.get("development_scans"), Mapping
    ):
        development_scans = cast(Mapping[str, object], prior_authority["development_scans"])
    original = (
        cast(Mapping[str, object], predeclaration["original"])
        if isinstance(predeclaration, Mapping)
        and isinstance(predeclaration.get("original"), Mapping)
        else None
    )
    if (
        sha256_bytes(raw) != expected_file_sha256
        or canonical_json_bytes(receipt) != raw
        or set(receipt) != _STAGE09_VERIFICATION_FIELDS
        or receipt.get("schema") != _STAGE09_VERIFICATION_SCHEMA
        or receipt.get("verification_hash") != expected_verification_hash
        or not verify_object_hash(receipt, hash_field="verification_hash")
        or receipt.get("passed") is not True
        or receipt.get("status") not in {"PASS", "FAILED_MECHANISM"}
        or receipt.get("execution_complete") is not True
        or receipt.get("evidence_integrity") is not True
        or receipt.get("competition_integrity") is not True
        or receipt.get("source_stable") is not True
        or not isinstance(stage09_source_root, str)
        or Path(stage09_source_root).resolve() != source_root.resolve()
        or not isinstance(attempt_root, str)
        or not Path(attempt_root).is_absolute()
        or not isinstance(output, Mapping)
        or set(output) != {"artifact_core_hash", "path", "sha256"}
        or not isinstance(exposure, Mapping)
        or set(exposure) != {"path", "sha256"}
        or not isinstance(finalization, Mapping)
        or set(finalization) != {"path", "sha256", "terminal_finalization_hash"}
        or not isinstance(prior_authority, Mapping)
        or set(prior_authority) != _STAGE09_PRIOR_AUTHORITY_FIELDS
        or prior_authority.get("full_public_integrity_status")
        != "NOT_EVALUATED_BUILD_001_PUBLIC_IDENTIFIERS"
        or prior_authority.get("assurance_limitation") != _STAGE09_ASSURANCE_LIMITATION
        or predeclaration is None
        or set(predeclaration)
        != {
            "amendment",
            "effective_build_001_commit",
            "effective_build_001_source_sha256",
            "effective_build_001_tree",
            "effective_matrix_hash",
            "live_validated",
            "original",
        }
        or predeclaration.get("live_validated") is not True
        or not isinstance(predeclaration.get("original"), Mapping)
        or set(cast(Mapping[str, object], predeclaration["original"]))
        != {"core_hash", "file_sha256", "path", "preserved_unchanged"}
        or cast(Mapping[str, object], predeclaration["original"]).get("preserved_unchanged")
        is not True
        or original is None
        or original.get("file_sha256") != expected_development_predeclaration_file_sha256
        or original.get("core_hash") != expected_development_predeclaration_core_hash
        or not isinstance(original.get("path"), str)
        or Path(cast(str, original["path"])).resolve()
        != source_root.resolve() / "docs/evidence/001-09-development-recovery-predeclaration.json"
        or not isinstance(predeclaration.get("amendment"), Mapping)
        or set(cast(Mapping[str, object], predeclaration["amendment"]))
        != {"core_hash", "file_sha256", "path", "result_state"}
        or cast(Mapping[str, object], predeclaration["amendment"]).get("result_state")
        != "READY_NOT_EXECUTED"
        or holdout is None
        or set(holdout) != _STAGE09_HOLDOUT_FIELDS
        or holdout.get("file_sha256") != expected_holdout_nonconsumption_sha256
        or holdout.get("pinned_manifest_sha256") != OPAQUE_PUBLIC_MANIFEST_SHA256
        or isinstance(holdout.get("identities_loaded"), bool)
        or holdout.get("identities_loaded") != 0
        or holdout.get("manifest_loaded_as_metadata") is not False
        or isinstance(holdout.get("public_holdout_gameplay_events"), bool)
        or holdout.get("public_holdout_gameplay_events") != 0
        or holdout.get("status") != "SEALED_UNCONSUMED"
        or package is None
        or set(package)
        != {
            "candidate_set_recomputed",
            "file_sha256",
            "git_commit",
            "live_source_hashes_match",
            "package_only_passed",
            "policy_scan_covers_reachable_paths",
            "reachable_paths_recomputed",
            "receipt_sha256",
            "status",
        }
        or package.get("status") != "PASS"
        or package.get("package_only_passed") is not True
        or package.get("candidate_set_recomputed") is not True
        or package.get("reachable_paths_recomputed") is not True
        or package.get("live_source_hashes_match") is not True
        or package.get("policy_scan_covers_reachable_paths") is not True
        or development_scans is None
        or set(development_scans)
        != {
            "build_000_finding_count",
            "build_000_passed",
            "build_001_finding_count",
            "build_001_passed",
            "development_identity_count",
            "identifier_list_hash",
            "identifier_string_count",
            "identity_values_disclosed",
        }
        or development_scans.get("identifier_list_hash") != expected_development_identifier_sha256
        or isinstance(development_scans.get("development_identity_count"), bool)
        or development_scans.get("development_identity_count") != 12
        or isinstance(development_scans.get("identifier_string_count"), bool)
        or development_scans.get("identifier_string_count") != 24
        or development_scans.get("identity_values_disclosed") is not False
        or isinstance(development_scans.get("build_000_finding_count"), bool)
        or development_scans.get("build_000_finding_count") != 0
        or isinstance(development_scans.get("build_001_finding_count"), bool)
        or development_scans.get("build_001_finding_count") != 0
        or development_scans.get("build_000_passed") is not True
        or development_scans.get("build_001_passed") is not True
        or not isinstance(work_authority, Mapping)
        or set(work_authority)
        != {
            "cell_count",
            "cell_finalization_hashes",
            "cell_receipt_hashes",
            "matrix_hash",
        }
        or work_authority.get("cell_count") != 96
        or not isinstance(work_authority.get("cell_receipt_hashes"), list)
        or not isinstance(work_authority.get("cell_finalization_hashes"), list)
        or len(cast(list[object], work_authority["cell_receipt_hashes"])) != 96
        or len(cast(list[object], work_authority["cell_finalization_hashes"])) != 96
        or not all(
            isinstance(item, str)
            for item in (
                output.get("path"),
                output.get("artifact_core_hash"),
                output.get("sha256"),
                exposure.get("path"),
                exposure.get("sha256"),
                finalization.get("path"),
                finalization.get("terminal_finalization_hash"),
                finalization.get("sha256"),
            )
        )
    ):
        raise EvaluationError("Stage 09 terminal verification is not exact and passing")
    for label, value in {
        "Stage 09 output hash": output["sha256"],
        "Stage 09 output core hash": output["artifact_core_hash"],
        "Stage 09 exposure hash": exposure["sha256"],
        "Stage 09 finalization hash": finalization["sha256"],
        "Stage 09 finalization core hash": finalization["terminal_finalization_hash"],
        "Stage 09 prior authority hash": prior_authority["prior_authority_hash"],
    }.items():
        _sha256(value, field=label)
    _git_hash(
        predeclaration["effective_build_001_commit"],
        field="Stage 09 effective source commit",
    )
    _git_hash(
        predeclaration["effective_build_001_tree"],
        field="Stage 09 effective source tree",
    )
    for label, value in {
        "Stage 09 effective source hash": predeclaration["effective_build_001_source_sha256"],
        "Stage 09 effective matrix hash": predeclaration["effective_matrix_hash"],
        "Stage 09 work matrix hash": work_authority["matrix_hash"],
    }.items():
        _sha256(value, field=label)
    for label, item in {
        "Stage 09 package receipt file hash": package["file_sha256"],
        "Stage 09 package receipt self hash": package["receipt_sha256"],
    }.items():
        _sha256(item, field=label)
    _git_hash(package["git_commit"], field="Stage 09 package source commit")
    verifier = _stage09_terminal_verifier(source_root)
    try:
        reconstructed = verifier(
            source_root=source_root.resolve(),
            attempt_root=Path(attempt_root),
            output=Path(cast(str, output["path"])),
            exposure=Path(cast(str, exposure["path"])),
            expected_output_sha256=cast(str, output["sha256"]),
            expected_artifact_core_hash=cast(str, output["artifact_core_hash"]),
            expected_terminal_finalization_sha256=cast(str, finalization["sha256"]),
            expected_terminal_finalization_hash=cast(
                str, finalization["terminal_finalization_hash"]
            ),
        )
    except (OSError, RuntimeError, TypeError, ValueError, EvaluationError) as error:
        raise EvaluationError("Stage 09 terminal graph failed live verification") from error
    if reconstructed != receipt:
        raise EvaluationError("Stage 09 terminal verification differs from live graph")
    return {
        "file_sha256": expected_file_sha256,
        "output_artifact_core_hash": cast(str, output["artifact_core_hash"]),
        "output_file_sha256": cast(str, output["sha256"]),
        "path": path.resolve().as_posix(),
        "schema": _STAGE09_VERIFICATION_SCHEMA,
        "source_root": stage09_source_root,
        "status": cast(str, receipt.get("status", "")),
        "terminal_finalization_hash": cast(str, finalization["terminal_finalization_hash"]),
        "terminal_finalization_sha256": cast(str, finalization["sha256"]),
        "verification_hash": expected_verification_hash,
    }


def _package_only_summary(
    root: Path,
    path: Path,
    *,
    current_source: Mapping[str, JSONValue],
    projection: Mapping[str, str],
) -> tuple[IntegrityReceipt, dict[str, JSONValue]]:
    raw, receipt = _read_integrity(path, field="package-only integrity authority")
    body = receipt.body
    inputs = body.get("inputs")
    assurance = body.get("assurance_scope")
    git = body.get("git")
    source_hashes = body.get("source_hashes")
    reachable_hashes = body.get("reachable_policy_source_hashes")
    coverage = body.get("production_policy_static_coverage")
    license_summary = body.get("license_summary")
    candidate_projection = _package_candidate_projection(root)
    expected_binding = {
        "declaration": "disabled-package-only",
        "expected_sha256": None,
        "issue": "semantic public-manifest access is prohibited in this profile",
    }
    if (
        body.get("schema") != INTEGRITY_SCHEMA
        or body.get("passed") is not False
        or body.get("package_only_passed") is not True
        or body.get("integrity_scope") != "package-only-no-public-identifiers"
        or body.get("full_competition_integrity_status") != "NOT_EVALUATED_PUBLIC_IDENTIFIERS"
        or not _checks_clear(body)
        or not isinstance(inputs, Mapping)
        or inputs.get("manifest") is not None
        or inputs.get("manifest_sha256") is not None
        or inputs.get("run_state") is not None
        or inputs.get("public_identifier_count") != 0
        or isinstance(inputs.get("public_identifier_count"), bool)
        or inputs.get("public_identifier_mode") != "disabled-package-only"
        or inputs.get("manifest_binding") != expected_binding
        or inputs.get("candidate_mode") != "caller-supplied"
        or inputs.get("candidate_paths") != list(candidate_projection)
        or inputs.get("candidate_file_count") != len(candidate_projection)
        or isinstance(inputs.get("candidate_file_count"), bool)
        or inputs.get("reachable_policy_paths") != sorted(projection)
        or inputs.get("reachable_policy_file_count") != len(projection)
        or isinstance(inputs.get("reachable_policy_file_count"), bool)
        or not isinstance(reachable_hashes, Mapping)
        or dict(reachable_hashes) != dict(projection)
        or not isinstance(coverage, Mapping)
        or set(coverage)
        != {
            "algorithm",
            "entry_points",
            "entry_points_reached",
            "limitations",
            "policy_scan_covers_reachable_paths",
            "reachable_file_count",
            "reachable_paths_hashed",
            "status",
        }
        or coverage.get("algorithm") != "static-first-party-import-closure-v0.1"
        or coverage.get("status") != "PASS"
        or coverage.get("limitations") != _STATIC_LIMITATION
        or inputs.get("entry_points") != _PRODUCTION_POLICY_ENTRY_POINTS
        or coverage.get("entry_points") != _PRODUCTION_POLICY_ENTRY_POINTS
        or coverage.get("entry_points_reached") != coverage.get("entry_points")
        or coverage.get("policy_scan_covers_reachable_paths") is not True
        or coverage.get("reachable_paths_hashed") is not True
        or coverage.get("reachable_file_count") != len(projection)
        or isinstance(coverage.get("reachable_file_count"), bool)
        or len(projection) <= 0
        or not isinstance(assurance, Mapping)
        or assurance.get("kind") != "static-only"
        or assurance.get("public_identifier_scan")
        != "NOT_EVALUATED_PACKAGE_ONLY_NO_SEMANTIC_MANIFEST_ACCESS"
        or assurance.get("scanner_network_mode") != "offline-by-construction"
        or not isinstance(git, Mapping)
        or git.get("commit") != current_source.get("commit")
        or git.get("dirty_worktree") is not False
        or not isinstance(source_hashes, Mapping)
        or dict(source_hashes) != candidate_projection
        or any(source_hashes.get(label) != digest for label, digest in projection.items())
        or source_hashes.get(DEPENDENCY_LOCK_PATH)
        != sha256_file(root.resolve() / DEPENDENCY_LOCK_PATH)
        or source_hashes.get(COMPETITION_CONFIG_PATH)
        != sha256_file(root.resolve() / COMPETITION_CONFIG_PATH)
        or not isinstance(license_summary, Mapping)
        or license_summary.get("first_party_license_status") != "MIT-0"
        or license_summary.get("status") != "PASS"
        or any(
            isinstance(license_summary.get(name), bool) or license_summary.get(name) != 0
            for name in (
                "installed_version_mismatch_count",
                "not_evaluated_count",
                "unknown_or_missing_metadata_count",
            )
        )
    ):
        raise EvaluationError("package-only integrity authority is not clear and exact")
    return receipt, {
        "file_sha256": sha256_bytes(raw),
        "production_policy_static_coverage": "PASS",
        "receipt_sha256": receipt.receipt_sha256,
    }


def create_composite_integrity_authority(
    *,
    source_root: Path,
    package_only_path: Path,
    build_000_root: Path,
    expected_build_000_commit: str,
    expected_build_000_tree: str,
    expected_development_identifier_sha256: str,
    development_predeclaration_path: Path,
    expected_development_predeclaration_file_sha256: str,
    expected_development_predeclaration_core_hash: str,
    holdout_nonconsumption_path: Path,
    expected_holdout_nonconsumption_sha256: str,
    stage09_verification_path: Path,
    expected_stage09_verification_file_sha256: str,
    expected_stage09_verification_hash: str,
    expected_runtime_surface: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    """Construct the deterministic composite authority without manifest access."""

    root = source_root.resolve()
    source = _source_identity(root)
    if source.get("clean_worktree") is not True:
        raise EvaluationError("composite integrity requires a clean execution source")
    projection = reachable_policy_projection(root)
    package, package_summary = _package_only_summary(
        root,
        package_only_path,
        current_source=source,
        projection=projection,
    )
    runtime = runtime_surface_identity(root)
    if runtime.get("verified") is not True:
        raise EvaluationError("composite integrity runtime surface is not verified")
    if expected_runtime_surface is not None and runtime != dict(expected_runtime_surface):
        raise EvaluationError("composite integrity runtime differs from Stage 10 preflight")
    config = _competition_config_identity(root)
    lock_hash = sha256_file(root / DEPENDENCY_LOCK_PATH)
    identifiers, identifier_authority = _development_identifiers(
        development_predeclaration_path,
        expected_file_sha256=expected_development_predeclaration_file_sha256,
        expected_core_hash=expected_development_predeclaration_core_hash,
        expected_sha256=expected_development_identifier_sha256,
    )
    if (
        identifier_authority.get("build_000_commit") != expected_build_000_commit
        or identifier_authority.get("build_000_tree") != expected_build_000_tree
    ):
        raise EvaluationError("Build 000 scan source is not the frozen Stage 09 baseline")
    current_commit = _git_hash(source.get("commit"), field="execution source commit")
    current_tree = _git_hash(source.get("tree"), field="execution source tree")
    development_scans = {
        "build_000": _development_scan(
            build_000_root,
            identifiers=identifiers,
            expected_commit=expected_build_000_commit,
            expected_tree=expected_build_000_tree,
        ),
        "build_001": _development_scan(
            root,
            identifiers=identifiers,
            expected_commit=current_commit,
            expected_tree=current_tree,
        ),
    }
    holdout = _holdout_nonconsumption_summary(
        holdout_nonconsumption_path,
        expected_file_sha256=expected_holdout_nonconsumption_sha256,
    )
    stage09 = _stage09_verification_summary(
        stage09_verification_path,
        expected_file_sha256=expected_stage09_verification_file_sha256,
        expected_verification_hash=expected_stage09_verification_hash,
        source_root=root,
        expected_holdout_nonconsumption_sha256=expected_holdout_nonconsumption_sha256,
        expected_development_identifier_sha256=expected_development_identifier_sha256,
        expected_development_predeclaration_file_sha256=(
            expected_development_predeclaration_file_sha256
        ),
        expected_development_predeclaration_core_hash=(
            expected_development_predeclaration_core_hash
        ),
        expected_build_000_root=build_000_root,
        expected_build_000_commit=expected_build_000_commit,
        expected_build_000_tree=expected_build_000_tree,
    )
    payload: dict[str, Any] = {
        "checks": {
            "current_package_only_clear": True,
            "development_identifier_scans_clear": True,
            "execution_config_lock_exact": True,
            "execution_runtime_exact": True,
            "execution_source_clean": True,
            "holdout_nonconsumption_exact": True,
            "stage09_terminal_verification_exact": True,
        },
        "assurance_limitation": _STAGE09_ASSURANCE_LIMITATION,
        "claim": "BOUNDED_STATIC_COMPETITION_INTEGRITY_WITH_OPAQUE_HOLDOUT",
        "development_identifier_authority": identifier_authority,
        "development_policy_scans": development_scans,
        "evidence_label": "synthetic",
        "full_public_integrity_status": "NOT_EVALUATED_BUILD_001_PUBLIC_IDENTIFIERS",
        "execution": {
            "competition_config": config,
            "dependency_lock": {
                "path": DEPENDENCY_LOCK_PATH,
                "sha256": lock_hash,
            },
            "runtime_surface": runtime,
            "source": {**source, "root": root.as_posix()},
        },
        "holdout_nonconsumption": holdout,
        "limitations": {
            "dynamic_or_native_containment": _STATIC_LIMITATION,
            "semantic_holdout_identifier_scan": "NOT_EVALUATED_SEALED_HOLDOUT_IDENTIFIERS",
        },
        "opaque_public_manifest_sha256": OPAQUE_PUBLIC_MANIFEST_SHA256,
        "package_only_authority": {
            "file_sha256": package_summary["file_sha256"],
            "integrity_scope": "package-only-no-public-identifiers",
            "path": package_only_path.resolve().as_posix(),
            "receipt_sha256": package.receipt_sha256,
            "schema": INTEGRITY_SCHEMA,
        },
        "production_policy_projection": {
            **_projection_summary(projection),
            "static_coverage_status": package_summary["production_policy_static_coverage"],
        },
        "schema": COMPOSITE_INTEGRITY_SCHEMA,
        "semantic_public_manifest_access": False,
        "stage09_terminal_verification": stage09,
        "status": "PASS",
    }
    return seal_object(payload, hash_field=COMPOSITE_INTEGRITY_HASH_FIELD)


def validate_composite_integrity_authority(
    path: Path,
    *,
    expected_file_sha256: str,
    expected_core_hash: str,
    source_root: Path,
) -> dict[str, Any]:
    """Rebuild an externally anchored composite authority from live bytes."""

    _sha256(expected_file_sha256, field="composite integrity file hash")
    _sha256(expected_core_hash, field="composite integrity core hash")
    try:
        raw = path.resolve().read_bytes()
        value: object = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise EvaluationError("composite integrity artifact is unreadable") from error
    if not isinstance(value, dict):
        raise EvaluationError("composite integrity artifact is not an object")
    document = cast(dict[str, Any], value)
    if (
        sha256_bytes(raw) != expected_file_sha256
        or canonical_json_bytes(document) != raw
        or document.get("schema") != COMPOSITE_INTEGRITY_SCHEMA
        or document.get(COMPOSITE_INTEGRITY_HASH_FIELD) != expected_core_hash
        or not verify_object_hash(document, hash_field=COMPOSITE_INTEGRITY_HASH_FIELD)
    ):
        raise EvaluationError("composite integrity artifact identity changed")
    package_binding = _mapping(
        document.get("package_only_authority"), field="package-only authority"
    )
    package_path_value = package_binding.get("path")
    development = _mapping(document.get("development_policy_scans"), field="development scans")
    build_000 = _mapping(development.get("build_000"), field="Build 000 development scan")
    build_000_source = _mapping(build_000.get("source"), field="Build 000 source")
    identifier_authority = _mapping(
        document.get("development_identifier_authority"),
        field="development identifier authority",
    )
    holdout = _mapping(document.get("holdout_nonconsumption"), field="holdout nonconsumption")
    stage09 = _mapping(document.get("stage09_terminal_verification"), field="Stage 09 verification")
    execution = _mapping(document.get("execution"), field="execution")
    current_source = _mapping(execution.get("source"), field="execution source")
    package_path_value = package_binding.get("path")
    values = (
        package_path_value,
        build_000_source.get("root"),
        build_000_source.get("commit"),
        build_000_source.get("tree"),
        identifier_authority.get("identifier_list_sha256"),
        identifier_authority.get("source_path"),
        identifier_authority.get("predeclaration_file_sha256"),
        identifier_authority.get("predeclaration_core_hash"),
        holdout.get("path"),
        holdout.get("file_sha256"),
        stage09.get("path"),
        stage09.get("file_sha256"),
        stage09.get("verification_hash"),
        current_source.get("commit"),
        current_source.get("tree"),
        current_source.get("root"),
    )
    if not all(isinstance(item, str) for item in values):
        raise EvaluationError("composite integrity authority paths are absent")
    if Path(cast(str, current_source["root"])).resolve() != source_root.resolve():
        raise EvaluationError("composite integrity execution source root changed")
    reconstructed = create_composite_integrity_authority(
        source_root=source_root,
        package_only_path=Path(cast(str, package_path_value)),
        build_000_root=Path(cast(str, build_000_source["root"])),
        expected_build_000_commit=cast(str, build_000_source["commit"]),
        expected_build_000_tree=cast(str, build_000_source["tree"]),
        expected_development_identifier_sha256=cast(
            str, identifier_authority["identifier_list_sha256"]
        ),
        development_predeclaration_path=Path(cast(str, identifier_authority["source_path"])),
        expected_development_predeclaration_file_sha256=cast(
            str, identifier_authority["predeclaration_file_sha256"]
        ),
        expected_development_predeclaration_core_hash=cast(
            str, identifier_authority["predeclaration_core_hash"]
        ),
        holdout_nonconsumption_path=Path(cast(str, holdout["path"])),
        expected_holdout_nonconsumption_sha256=cast(str, holdout["file_sha256"]),
        stage09_verification_path=Path(cast(str, stage09["path"])),
        expected_stage09_verification_file_sha256=cast(str, stage09["file_sha256"]),
        expected_stage09_verification_hash=cast(str, stage09["verification_hash"]),
    )
    if reconstructed != document:
        raise EvaluationError("composite integrity artifact does not match live authority")
    return document


def composite_binding(document: Mapping[str, Any], *, path: Path) -> dict[str, JSONValue]:
    """Return the safe external binding projected into parent/gate receipts."""

    if document.get("schema") != COMPOSITE_INTEGRITY_SCHEMA or not verify_object_hash(
        dict(document), hash_field=COMPOSITE_INTEGRITY_HASH_FIELD
    ):
        raise EvaluationError("composite integrity document is not sealed")
    return {
        "artifact_core_hash": cast(str, document[COMPOSITE_INTEGRITY_HASH_FIELD]),
        "file_sha256": sha256_file(path.resolve()),
        "schema": COMPOSITE_INTEGRITY_SCHEMA,
    }


def authority_callable_origins(source_root: Path) -> dict[str, str]:
    """Fail closed if an imported authority callable was rebound across trees."""

    root = source_root.resolve()
    package_candidates = _package_candidate_callable(root)
    stage09_verifier = _stage09_terminal_verifier(root)
    expected = {
        "canonical_json_bytes": (canonical_json_bytes, "src/arc3/evaluation/artifacts.py"),
        "discover_candidate_files": (
            discover_candidate_files,
            "src/arc3/integrity/scanner.py",
        ),
        "discover_policy_files": (discover_policy_files, "src/arc3/integrity/scanner.py"),
        "discover_reachable_policy_files": (
            discover_reachable_policy_files,
            "src/arc3/integrity/scanner.py",
        ),
        "scan_policy_files": (scan_policy_files, "src/arc3/integrity/scanner.py"),
        "seal_object": (seal_object, "src/arc3/evaluation/artifacts.py"),
        "sha256_bytes": (sha256_bytes, "src/arc3/evaluation/artifacts.py"),
        "sha256_file": (sha256_file, "src/arc3/evaluation/artifacts.py"),
        "validate_predeclaration_bytes": (
            validate_predeclaration_bytes,
            "src/arc3/evaluation/development_recovery.py",
        ),
        "verify_object_hash": (verify_object_hash, "src/arc3/evaluation/artifacts.py"),
        "package_only_candidate_files": (
            package_candidates,
            "scripts/check_competition_integrity.py",
        ),
        "verify_complete_terminal": (
            stage09_verifier,
            "scripts/measure_development_recovery.py",
        ),
    }
    origins: dict[str, str] = {}
    for name, (function, relative) in expected.items():
        code = getattr(function, "__code__", None)
        expected_path = (root / relative).resolve()
        if code is None or Path(code.co_filename).resolve() != expected_path:
            raise EvaluationError(f"composite integrity callable origin changed: {name}")
        origins[name] = relative
    return origins


__all__ = [
    "COMPETITION_CONFIG_PATH",
    "COMPOSITE_INTEGRITY_HASH_FIELD",
    "COMPOSITE_INTEGRITY_SCHEMA",
    "DEPENDENCY_LOCK_PATH",
    "OPAQUE_PUBLIC_MANIFEST_SHA256",
    "UPSTREAM_LOCK_PATH",
    "authority_callable_origins",
    "composite_binding",
    "create_composite_integrity_authority",
    "reachable_policy_projection",
    "runtime_surface_identity",
    "validate_composite_integrity_authority",
]
