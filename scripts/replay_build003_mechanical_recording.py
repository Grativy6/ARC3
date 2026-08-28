"""Emit a clean-source, read-only Build 003 mechanical recording replay receipt."""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import subprocess
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, cast

_BYTECODE_DISABLED_AT_STARTUP = sys.dont_write_bytecode
_DIRECT_SCRIPT_INVOCATION = __spec__ is None
sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "src"
for import_root in (ROOT, SOURCE_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

import arc3  # noqa: E402
import arc3.evaluation.mechanical_replay as replay_module  # noqa: E402
from arc3.errors import ARC3Error  # noqa: E402
from arc3.evaluation.artifacts import (  # noqa: E402
    canonical_json_bytes,
    seal_object,
    sha256_bytes,
    sha256_file,
    verify_object_hash,
)
from arc3.evaluation.mechanical_replay import (  # noqa: E402
    replay_unfinished_mechanical_recording,
    replay_unfinished_mechanical_trace,
)
from arc3.integrity import read_bounded_regular_snapshot  # noqa: E402
from arc3.types import ActionName, GameStateName, JSONValue  # noqa: E402
from scripts.check_competition_integrity import (  # noqa: E402
    package_only_candidate_files,
)

SCHEMA = "arc3.build003.mechanical-recording-replay.v0.1"
TRACE_SCHEMA = "arc3.build003.mechanical-sealed-trace-replay.v0.1"
TRACE_REOPENING_SCHEMA = "arc3.build003.mechanical-sealed-trace-prefix-reopening.v0.1"
POLICY_PROFILE = "build003-mechanical-v0.1"
MAX_COORDINATE_CANDIDATES = 8
LEGACY_CAMPAIGN_AUDIT_SCHEMA = "arc3.build003.campaign28-integrity-replay-audit.v0.1"
CAMPAIGN_AUDIT_SCHEMA = "arc3.build003.mechanical-campaign-integrity-replay-audit.v0.2"
_SUPPORTED_CAMPAIGN_AUDIT_SCHEMAS = {
    LEGACY_CAMPAIGN_AUDIT_SCHEMA,
    CAMPAIGN_AUDIT_SCHEMA,
}
_FULL_OBJECT_ID = re.compile(r"[0-9a-f]{40}")
_SOURCE_PATHS = (
    "scripts/replay_build003_mechanical_recording.py",
    "src/arc3/adapters/__init__.py",
    "src/arc3/evaluation/artifacts.py",
    "src/arc3/evaluation/mechanical_replay.py",
    "src/arc3/mechanics/visual_causal.py",
    "src/arc3/types.py",
    "upstream.lock.json",
    "uv.lock",
)


def _git_environment() -> dict[str, str]:
    environment = {
        key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")
    }
    environment["GIT_NO_REPLACE_OBJECTS"] = "1"
    return environment


def _git_text(*arguments: str) -> str:
    completed = subprocess.run(
        ("git", "--no-replace-objects", "-C", str(ROOT), *arguments),
        check=False,
        capture_output=True,
        env=_git_environment(),
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(arguments)} failed with exit {completed.returncode}: "
            f"{completed.stderr.strip()}"
        )
    return completed.stdout.strip()


def _full_object_id(value: str, *, field: str) -> str:
    normalized = value.lower()
    if _FULL_OBJECT_ID.fullmatch(normalized) is None:
        raise ValueError(f"{field} must be a full 40-character lowercase Git object ID")
    return normalized


def _normalized_sha256(value: str, *, field: str) -> str:
    normalized = value.lower()
    if not normalized.startswith("sha256:"):
        normalized = f"sha256:{normalized}"
    digest = normalized.removeprefix("sha256:")
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise ValueError(f"{field} must be a full SHA-256 digest")
    return normalized


def _object(value: object, *, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"campaign audit field {field} must be an object")
    return cast(dict[str, Any], value)


def _string(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"campaign audit field {field} must be a non-empty string")
    return value


def _nonnegative_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"campaign audit field {field} must be a non-negative integer")
    return value


def _count_map(
    value: object,
    *,
    field: str,
    allowed_keys: frozenset[str],
) -> dict[str, int]:
    raw = _object(value, field=field)
    counts: dict[str, int] = {}
    for key, count in raw.items():
        if key not in allowed_keys:
            raise ValueError(f"campaign audit field {field} contains unsupported key {key!r}")
        counts[key] = _nonnegative_int(count, field=f"{field}.{key}")
    return counts


def _source_snapshot(
    *, expected_commit: str, expected_tree: str
) -> tuple[dict[str, JSONValue], dict[str, bytes]]:
    commit = _full_object_id(expected_commit, field="expected commit")
    tree = _full_object_id(expected_tree, field="expected tree")
    if Path(_git_text("rev-parse", "--show-toplevel")).resolve() != ROOT:
        raise RuntimeError("replay script is not located at the exact Git top level")
    actual_commit = _git_text("rev-parse", "HEAD")
    if actual_commit != commit:
        raise RuntimeError(f"source commit {actual_commit} != expected commit {commit}")
    if _git_text("status", "--porcelain=v1", "--untracked-files=all"):
        raise RuntimeError("replay source repository is not clean")
    actual_tree = _git_text("rev-parse", "HEAD^{tree}")
    if actual_tree != tree:
        raise RuntimeError(f"source tree {actual_tree} != expected tree {tree}")

    snapshots: dict[str, bytes] = {}
    selected = package_only_candidate_files(
        ROOT,
        commit,
        candidate_snapshots=snapshots,
    )
    imported_arc3 = Path(arc3.__file__).resolve()
    imported_replay = Path(replay_module.__file__).resolve()
    if not imported_arc3.is_relative_to((SOURCE_ROOT / "arc3").resolve()):
        raise RuntimeError("replay imported arc3 outside the named source root")
    if imported_replay != (SOURCE_ROOT / "arc3/evaluation/mechanical_replay.py").resolve():
        raise RuntimeError("replay imported its engine outside the named source root")
    missing = sorted(set(_SOURCE_PATHS) - set(snapshots))
    if missing:
        raise RuntimeError(f"source projection omits required replay files: {missing!r}")
    projection: list[JSONValue] = [
        {"path": relative, "sha256": sha256_bytes(snapshots[relative])}
        for relative in sorted(snapshots)
    ]
    return (
        {
            "clean": True,
            "commit": commit,
            "detached_head": _git_text("branch", "--show-current") == "",
            "imported_arc3": str(imported_arc3),
            "imported_replay_engine": str(imported_replay),
            "package_source_file_count": len(selected),
            "package_source_projection_sha256": sha256_bytes(canonical_json_bytes(projection)),
            "repository_path": str(ROOT),
            "source_hashes": {
                relative: sha256_bytes(snapshots[relative]) for relative in _SOURCE_PATHS
            },
            "tree": actual_tree,
        },
        snapshots,
    )


def _repository_file_projection() -> dict[str, str]:
    """Hash every non-Git file so the no-repository-write claim is measured."""

    projection: dict[str, str] = {}
    for path in sorted(ROOT.rglob("*")):
        relative = path.relative_to(ROOT)
        if relative.parts and relative.parts[0] == ".git":
            continue
        if path.is_symlink() or path.is_junction():
            raise RuntimeError(
                f"repository projection found an alias or junction: {relative.as_posix()}"
            )
        if path.is_dir():
            continue
        label = relative.as_posix()
        if not path.is_file():
            raise RuntimeError(f"repository projection found a non-regular path: {label}")
        raw = read_bounded_regular_snapshot(
            root=ROOT,
            path=path,
            max_bytes=128 * 1024 * 1024,
            path_label=label,
        )
        projection[label] = sha256_bytes(raw)
    if not projection or len(projection) > 20_000:
        raise RuntimeError("repository file projection is empty or exceeds its bound")
    return projection


def _campaign_binding(
    *,
    campaign_audit: Path,
    expected_file_sha256: str,
    expected_object_hash: str,
    expected_evaluation_id: str,
) -> tuple[dict[str, JSONValue], Path, dict[str, object]]:
    audit_path = campaign_audit.resolve(strict=True)
    raw = read_bounded_regular_snapshot(
        root=audit_path.parent,
        path=campaign_audit,
        max_bytes=1024 * 1024,
        path_label=audit_path.name,
    )
    file_sha256 = sha256_bytes(raw)
    named_file_sha256 = _normalized_sha256(
        expected_file_sha256,
        field="expected campaign audit file SHA-256",
    )
    if file_sha256 != named_file_sha256:
        raise ValueError(
            f"campaign audit file SHA-256 {file_sha256} != expected {named_file_sha256}"
        )
    try:
        value: object = json.loads(raw.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("campaign audit is not UTF-8 JSON") from error
    audit = _object(value, field="root")
    named_object_hash = _normalized_sha256(
        expected_object_hash,
        field="expected campaign audit object hash",
    )
    audit_schema = audit.get("schema")
    if not isinstance(audit_schema, str) or audit_schema not in _SUPPORTED_CAMPAIGN_AUDIT_SCHEMAS:
        raise ValueError("campaign audit schema is not a supported sealed replay-audit schema")
    reset_aware_v2 = audit_schema == CAMPAIGN_AUDIT_SCHEMA
    if audit.get("audit_receipt_hash") != named_object_hash or not verify_object_hash(
        audit,
        hash_field="audit_receipt_hash",
    ):
        raise ValueError("campaign audit object hash is absent, mismatched, or invalid")

    campaign = _object(audit.get("campaign"), field="campaign")
    completion = _object(audit.get("completion"), field="completion")
    conclusion = _object(audit.get("audit_conclusion"), field="audit_conclusion")
    recording = _object(audit.get("recording"), field="recording")
    scope = _object(audit.get("scope"), field="scope")
    verification = _object(audit.get("verification"), field="verification")
    public_verifier = _object(
        verification.get("authoritative_public_evaluation_verifier"),
        field="verification.authoritative_public_evaluation_verifier",
    )
    hashes_and_seals = _object(audit.get("hashes_and_seals"), field="hashes_and_seals")

    evaluation_id = _string(campaign.get("evaluation_id"), field="campaign.evaluation_id")
    if (
        evaluation_id != expected_evaluation_id
        or public_verifier.get("evaluation_id") != evaluation_id
    ):
        raise ValueError("campaign audit evaluation identity does not match the named campaign")
    if public_verifier.get("verified") is not True or public_verifier.get("errors") != []:
        raise ValueError("campaign audit authoritative public verifier did not pass")
    if conclusion.get("integrity_verified") is not True:
        raise ValueError("campaign audit does not claim verified integrity")
    if conclusion.get("completion_genuinely_observed") is not False:
        raise ValueError("campaign audit completion boundary is inconsistent")
    if campaign.get("partition") != "development" or campaign.get("surface") != "local-public":
        raise ValueError("campaign audit is not authorized local-public development evidence")
    if (
        campaign.get("holdout_consumed") is not False
        or campaign.get("source_semantically_inspected") is not False
    ):
        raise ValueError("campaign audit crossed a holdout or source-inspection boundary")
    if (
        scope.get("holdout_accessed") is not False
        or scope.get("target_game_source_inspected") is not False
    ):
        raise ValueError("campaign audit scope crossed a protected boundary")
    if scope.get("read_only_campaign_audit") is not True:
        raise ValueError("campaign audit was not declared read-only")

    authoritative_completion_state = _string(
        completion.get("authoritative_completion_state"),
        field="completion.authoritative_completion_state",
    )
    final_state = (
        _string(
            completion.get("raw_final_state"),
            field="completion.raw_final_state",
        )
        if reset_aware_v2
        else authoritative_completion_state
    )
    levels_completed = _nonnegative_int(
        completion.get("levels_completed"),
        field="completion.levels_completed",
    )
    win_levels = _nonnegative_int(
        completion.get("win_levels"),
        field="completion.win_levels",
    )
    submission_count = _nonnegative_int(
        completion.get("submission_count"),
        field="completion.submission_count",
    )
    official_run_state = _string(
        completion.get("official_run_state"),
        field="completion.official_run_state",
    )
    if (
        final_state != GameStateName.NOT_FINISHED.value
        or authoritative_completion_state != final_state
        or conclusion.get("final_environment_state") != final_state
        or completion.get("raw_final_state") != final_state
        or completion.get("metric_final_state") != final_state
        or completion.get("completion_observed") is not False
        or completion.get("score_completed") is not False
    ):
        raise ValueError("campaign audit does not preserve the authoritative NOT_FINISHED boundary")

    official_run_action_count = _nonnegative_int(
        completion.get("official_run_action_count"),
        field="completion.official_run_action_count",
    )
    non_reset_action_count = _nonnegative_int(
        completion.get("non_reset_environment_action_count"),
        field="completion.non_reset_environment_action_count",
    )
    consequence_count = _nonnegative_int(
        recording.get("consequence_count_excluding_initial_observation"),
        field="recording.consequence_count_excluding_initial_observation",
    )
    reset_count = (
        _nonnegative_int(
            completion.get("reset_count"),
            field="completion.reset_count",
        )
        if reset_aware_v2
        else 0
    )
    if reset_aware_v2:
        if completion.get("score_boundary_consistent") is not True:
            raise ValueError("campaign audit score boundary is not declared consistent")
        if (
            official_run_action_count != submission_count
            or consequence_count != submission_count
            or non_reset_action_count + reset_count != submission_count
        ):
            raise ValueError("campaign audit reset-aware action-accounting fields disagree")

        submitted_action_counts = _count_map(
            recording.get("submitted_action_id_counts"),
            field="recording.submitted_action_id_counts",
            allowed_keys=frozenset(action.value for action in ActionName),
        )
        if (
            sum(submitted_action_counts.values()) != submission_count
            or submitted_action_counts.get(ActionName.RESET.value, 0) != reset_count
            or sum(
                count
                for action, count in submitted_action_counts.items()
                if action != ActionName.RESET.value
            )
            != non_reset_action_count
        ):
            raise ValueError("campaign audit submitted-action counts disagree")

        game_over_events = _nonnegative_int(
            recording.get("game_over_events"),
            field="recording.game_over_events",
        )
        win_events = _nonnegative_int(
            recording.get("win_events"),
            field="recording.win_events",
        )
        consequence_state_counts = _count_map(
            recording.get("consequence_state_counts"),
            field="recording.consequence_state_counts",
            allowed_keys=frozenset(
                {
                    GameStateName.NOT_FINISHED.value,
                    GameStateName.GAME_OVER.value,
                    GameStateName.WIN.value,
                }
            ),
        )
        if (
            sum(consequence_state_counts.values()) != submission_count
            or consequence_state_counts.get(GameStateName.GAME_OVER.value, 0) != game_over_events
            or consequence_state_counts.get(GameStateName.WIN.value, 0) != win_events
            or consequence_state_counts.get(final_state, 0) == 0
            or win_events != 0
        ):
            raise ValueError("campaign audit consequence-state counts disagree")
        expected_official_run_state = (
            GameStateName.GAME_OVER.value if game_over_events else GameStateName.NOT_FINISHED.value
        )
        if official_run_state != expected_official_run_state:
            raise ValueError(
                "campaign audit official score-boundary state disagrees with recorded consequences"
            )
    elif (
        official_run_state != final_state
        or official_run_action_count != submission_count
        or non_reset_action_count != submission_count
        or consequence_count != submission_count
    ):
        raise ValueError("campaign audit action-accounting fields disagree")
    row_count = _nonnegative_int(
        recording.get("event_count_including_initial_reset_observation"),
        field="recording.event_count_including_initial_reset_observation",
    )
    if row_count != submission_count + 1 or recording.get("initial_action") != "RESET":
        raise ValueError("campaign audit recording cardinality is inconsistent")
    final_observation = _object(
        recording.get("final_observation"),
        field="recording.final_observation",
    )
    if final_observation != {
        "levels_completed": levels_completed,
        "state": final_state,
        "win_levels": win_levels,
    }:
        raise ValueError("campaign audit final recording observation disagrees with completion")

    evaluation_root = Path(
        _string(scope.get("evaluation_root"), field="scope.evaluation_root")
    ).resolve(strict=True)
    relative_text = _string(recording.get("path"), field="recording.path")
    relative = PurePosixPath(relative_text)
    if (
        relative.is_absolute()
        or "\\" in relative_text
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise ValueError("campaign audit recording path is unsafe")
    recording_path = evaluation_root.joinpath(*relative.parts).resolve(strict=True)
    try:
        recording_path.relative_to(evaluation_root)
    except ValueError as error:
        raise ValueError("campaign audit recording path escapes the evaluation root") from error

    recording_sha256 = _normalized_sha256(
        _string(recording.get("sha256"), field="recording.sha256"),
        field="recording SHA-256",
    )
    byte_length = _nonnegative_int(
        recording.get("byte_length"),
        field="recording.byte_length",
    )
    trace_manifest_verified = hashes_and_seals.get("trace_manifest_object_hash_verified")
    if not isinstance(trace_manifest_verified, bool):
        raise ValueError("campaign audit trace-manifest verification flag is not boolean")
    game_id = _string(campaign.get("game_id"), field="campaign.game_id")
    binding: dict[str, JSONValue] = {
        "audit_file_sha256": file_sha256,
        "audit_object_hash": named_object_hash,
        "audit_path": str(audit_path),
        "audit_schema": audit_schema,
        "authoritative_public_verifier": True,
        "evaluation_id": evaluation_id,
        "historical_frozen_commit": _string(
            campaign.get("frozen_git_commit"), field="campaign.frozen_git_commit"
        ),
        "integrity_verified": True,
        "non_reset_environment_action_count": non_reset_action_count,
        "official_run_state": official_run_state,
        "replay_final_state": final_state,
        "reset_count": reset_count,
        "trace_manifest_object_hash": hashes_and_seals.get("trace_manifest_object_hash"),
        "trace_manifest_object_hash_verified": trace_manifest_verified,
    }
    derived: dict[str, object] = {
        "byte_length": byte_length,
        "final_state": final_state,
        "game_id": game_id,
        "levels_completed": levels_completed,
        "recording_sha256": recording_sha256,
        "row_count": row_count,
        "submission_count": submission_count,
        "win_levels": win_levels,
    }
    return binding, recording_path, derived


def _write_exclusive(path: Path, value: object) -> None:
    if path.is_symlink() or path.exists():
        raise RuntimeError("replay receipt output already exists and cannot be overwritten")
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = canonical_json_bytes(value)
    with path.open("xb") as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())


def _sealed_trace_binding(
    replay: Mapping[str, object],
    *,
    generator_commit: str,
    replay_mode: str = "sealed-trace",
) -> dict[str, JSONValue]:
    trace_summary = _object(replay.get("trace"), field="trace")
    game_id = trace_summary.get("game_id")
    if not isinstance(game_id, str) or not game_id:
        raise ValueError("sealed trace replay result omits its validated game identity")
    binding: dict[str, JSONValue] = {
        "event_count": trace_summary.get("event_count"),
        "game_id": game_id,
        "generator_commit": generator_commit,
        "manifest_hash": trace_summary.get("manifest_hash"),
        "mode": replay_mode,
        "recording_reconstructed": False,
        "root": trace_summary.get("path"),
        "run_id": trace_summary.get("run_id"),
        "submission_count": trace_summary.get("submission_count"),
        "tail_event_hash": trace_summary.get("tail_event_hash"),
    }
    if replay_mode == "sealed-trace-prefix-reopening":
        reopening = _object(replay.get("reopening_boundary"), field="reopening_boundary")
        binding["reopening_consequence_event_hash"] = reopening.get("consequence_event_hash")
        binding["reopening_consequence_event_id"] = reopening.get("consequence_event_id")
        binding["reopening_submission_count"] = reopening.get("submission_count")
        binding["reopening_candidate_plan_prefix"] = reopening.get("candidate_plan_prefix")
        binding["reopening_candidate_plan_signature"] = reopening.get("candidate_plan_signature")
    return binding


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    evidence = parser.add_mutually_exclusive_group(required=True)
    evidence.add_argument("--campaign-audit", type=Path)
    evidence.add_argument("--sealed-trace-root", type=Path)
    parser.add_argument("--expected-campaign-audit-file-sha256")
    parser.add_argument("--expected-campaign-audit-object-hash")
    parser.add_argument("--expected-evaluation-id")
    parser.add_argument("--expected-trace-run-id")
    parser.add_argument("--expected-trace-game-id")
    parser.add_argument("--expected-trace-generator-commit")
    parser.add_argument("--expected-trace-manifest-hash")
    parser.add_argument("--expected-trace-tail-event-hash")
    parser.add_argument("--expected-trace-event-count", type=int)
    parser.add_argument("--expected-trace-submission-count", type=int)
    parser.add_argument(
        "--expected-trace-final-state",
        choices=(GameStateName.NOT_FINISHED.value,),
    )
    parser.add_argument("--expected-trace-levels-completed", type=int)
    parser.add_argument("--expected-trace-win-levels", type=int)
    parser.add_argument("--expected-trace-reopening-submission", type=int)
    parser.add_argument("--expected-trace-reopening-consequence-event-id")
    parser.add_argument("--expected-trace-reopening-consequence-event-hash")
    parser.add_argument(
        "--expected-trace-reopening-state",
        choices=(GameStateName.NOT_FINISHED.value,),
    )
    parser.add_argument("--expected-trace-reopening-levels-completed", type=int)
    parser.add_argument("--expected-trace-reopening-win-levels", type=int)
    parser.add_argument("--expected-trace-reopening-candidate-plan-prefix")
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--expected-tree", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--policy-profile", choices=(POLICY_PROFILE,), required=True)
    return parser


_CAMPAIGN_MODE_ARGUMENTS = (
    ("expected_campaign_audit_file_sha256", "--expected-campaign-audit-file-sha256"),
    ("expected_campaign_audit_object_hash", "--expected-campaign-audit-object-hash"),
    ("expected_evaluation_id", "--expected-evaluation-id"),
)
_TRACE_MODE_ARGUMENTS = (
    ("expected_trace_run_id", "--expected-trace-run-id"),
    ("expected_trace_game_id", "--expected-trace-game-id"),
    ("expected_trace_generator_commit", "--expected-trace-generator-commit"),
    ("expected_trace_manifest_hash", "--expected-trace-manifest-hash"),
    ("expected_trace_tail_event_hash", "--expected-trace-tail-event-hash"),
    ("expected_trace_event_count", "--expected-trace-event-count"),
    ("expected_trace_submission_count", "--expected-trace-submission-count"),
    ("expected_trace_final_state", "--expected-trace-final-state"),
    ("expected_trace_levels_completed", "--expected-trace-levels-completed"),
    ("expected_trace_win_levels", "--expected-trace-win-levels"),
)
_TRACE_REOPENING_MODE_ARGUMENTS = (
    ("expected_trace_reopening_submission", "--expected-trace-reopening-submission"),
    (
        "expected_trace_reopening_consequence_event_id",
        "--expected-trace-reopening-consequence-event-id",
    ),
    (
        "expected_trace_reopening_consequence_event_hash",
        "--expected-trace-reopening-consequence-event-hash",
    ),
    ("expected_trace_reopening_state", "--expected-trace-reopening-state"),
    (
        "expected_trace_reopening_levels_completed",
        "--expected-trace-reopening-levels-completed",
    ),
    ("expected_trace_reopening_win_levels", "--expected-trace-reopening-win-levels"),
    (
        "expected_trace_reopening_candidate_plan_prefix",
        "--expected-trace-reopening-candidate-plan-prefix",
    ),
)


def _replay_mode(args: argparse.Namespace) -> str:
    campaign_mode = args.campaign_audit is not None
    required = _CAMPAIGN_MODE_ARGUMENTS if campaign_mode else _TRACE_MODE_ARGUMENTS
    forbidden = (
        _TRACE_MODE_ARGUMENTS + _TRACE_REOPENING_MODE_ARGUMENTS
        if campaign_mode
        else _CAMPAIGN_MODE_ARGUMENTS
    )
    missing = [option for attribute, option in required if getattr(args, attribute) is None]
    if missing:
        raise ValueError(
            f"selected replay mode is missing required arguments: {', '.join(missing)}"
        )
    supplied_forbidden = [
        option for attribute, option in forbidden if getattr(args, attribute) is not None
    ]
    if supplied_forbidden:
        raise ValueError(
            "selected replay mode received incompatible arguments: " + ", ".join(supplied_forbidden)
        )
    if campaign_mode:
        return "campaign-recording"
    reopening_supplied = [
        getattr(args, attribute) is not None
        for attribute, _option in _TRACE_REOPENING_MODE_ARGUMENTS
    ]
    if any(reopening_supplied) and not all(reopening_supplied):
        missing_reopening = [
            option
            for (attribute, option), supplied in zip(
                _TRACE_REOPENING_MODE_ARGUMENTS,
                reopening_supplied,
                strict=True,
            )
            if not supplied
        ]
        raise ValueError(
            "sealed reopening mode is missing required arguments: " + ", ".join(missing_reopening)
        )
    return "sealed-trace-prefix-reopening" if all(reopening_supplied) else "sealed-trace"


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not _BYTECODE_DISABLED_AT_STARTUP:
        raise SystemExit("invoke the replay verifier with Python -B to prohibit bytecode writes")
    if not _DIRECT_SCRIPT_INVOCATION:
        raise SystemExit("invoke the replay verifier by its script path, not as an imported module")
    output = args.output.resolve()
    if output.is_symlink() or output.exists():
        raise SystemExit("replay receipt output already exists and cannot be overwritten")
    if output.is_relative_to(ROOT):
        raise SystemExit("replay receipt output must remain outside the source repository")
    try:
        replay_mode = _replay_mode(args)
        repository_before = _repository_file_projection()
        source_binding, source_before = _source_snapshot(
            expected_commit=args.expected_commit,
            expected_tree=args.expected_tree,
        )
        campaign_binding: dict[str, JSONValue] | None = None
        trace_binding: dict[str, JSONValue] | None = None
        if replay_mode == "campaign-recording":
            campaign_binding, recording_path, expected = _campaign_binding(
                campaign_audit=args.campaign_audit,
                expected_file_sha256=args.expected_campaign_audit_file_sha256,
                expected_object_hash=args.expected_campaign_audit_object_hash,
                expected_evaluation_id=args.expected_evaluation_id,
            )
            replay = replay_unfinished_mechanical_recording(
                recording_path,
                expected_game_id=cast(str, expected["game_id"]),
                expected_recording_sha256=cast(str, expected["recording_sha256"]),
                expected_byte_length=cast(int, expected["byte_length"]),
                expected_row_count=cast(int, expected["row_count"]),
                expected_final_state=GameStateName(cast(str, expected["final_state"])),
                expected_levels_completed=cast(int, expected["levels_completed"]),
                expected_win_levels=cast(int, expected["win_levels"]),
                max_coordinate_candidates=MAX_COORDINATE_CANDIDATES,
            )
            expected_submission_count = cast(int, expected["submission_count"])
            receipt_status = "PASS_RECORDED_FRAME_REPLAY"
            receipt_schema = SCHEMA
        else:
            trace_generator_commit = _full_object_id(
                args.expected_trace_generator_commit,
                field="expected trace generator commit",
            )
            replay = replay_unfinished_mechanical_trace(
                args.sealed_trace_root,
                expected_run_id=args.expected_trace_run_id,
                expected_game_id=args.expected_trace_game_id,
                expected_git_commit=trace_generator_commit,
                expected_trace_manifest_hash=args.expected_trace_manifest_hash,
                expected_tail_event_hash=args.expected_trace_tail_event_hash,
                expected_event_count=args.expected_trace_event_count,
                expected_submission_count=args.expected_trace_submission_count,
                expected_final_state=GameStateName(args.expected_trace_final_state),
                expected_levels_completed=args.expected_trace_levels_completed,
                expected_win_levels=args.expected_trace_win_levels,
                max_coordinate_candidates=MAX_COORDINATE_CANDIDATES,
                expected_reopening_submission_count=(args.expected_trace_reopening_submission),
                expected_reopening_consequence_event_id=(
                    args.expected_trace_reopening_consequence_event_id
                ),
                expected_reopening_consequence_event_hash=(
                    args.expected_trace_reopening_consequence_event_hash
                ),
                expected_reopening_state=(
                    GameStateName(args.expected_trace_reopening_state)
                    if args.expected_trace_reopening_state is not None
                    else None
                ),
                expected_reopening_levels_completed=(
                    args.expected_trace_reopening_levels_completed
                ),
                expected_reopening_win_levels=(args.expected_trace_reopening_win_levels),
                expected_reopening_candidate_plan_prefix=(
                    args.expected_trace_reopening_candidate_plan_prefix
                ),
            )
            expected_submission_count = (
                args.expected_trace_reopening_submission
                if replay_mode == "sealed-trace-prefix-reopening"
                else args.expected_trace_submission_count
            )
            trace_binding = _sealed_trace_binding(
                replay,
                generator_commit=trace_generator_commit,
                replay_mode=replay_mode,
            )
            if replay_mode == "sealed-trace-prefix-reopening":
                receipt_status = "PASS_SEALED_TRACE_PREFIX_REOPENING"
                receipt_schema = TRACE_REOPENING_SCHEMA
            else:
                receipt_status = "PASS_SEALED_TRACE_REPLAY"
                receipt_schema = TRACE_SCHEMA
        replay_result = _object(replay.get("replay_result"), field="replay_result")
        if replay_mode == "sealed-trace-prefix-reopening":
            reopening_boundary = _object(
                replay.get("reopening_boundary"),
                field="reopening_boundary",
            )
            if (
                replay_result.get("matched_submission_count") != expected_submission_count - 1
                or reopening_boundary.get("matched_action_and_consequence_through_submission")
                != expected_submission_count
            ):
                raise ValueError(
                    "canonical reopening prefix counts disagree with the selected evidence"
                )
        elif replay_result.get("matched_submission_count") != expected_submission_count:
            raise ValueError("canonical replay count disagrees with the selected evidence")
        source_after_binding, source_after = _source_snapshot(
            expected_commit=args.expected_commit,
            expected_tree=args.expected_tree,
        )
        if source_before != source_after or source_binding != source_after_binding:
            raise RuntimeError("source projection changed during replay")
        repository_after = _repository_file_projection()
        if repository_before != repository_after:
            raise RuntimeError("repository file projection changed during replay")
        source_binding["post_replay_projection_verified"] = True
        source_binding["repository_file_count"] = len(repository_after)
        source_binding["repository_file_projection_sha256"] = sha256_bytes(
            canonical_json_bytes(repository_after)
        )
        source_binding["repository_projection_scope"] = (
            "all regular non-.git files from direct Python -B startup through receipt assembly"
        )
        boundaries = _object(replay.get("boundaries"), field="boundaries")
        boundaries["repository_files_modified_by_replay"] = False
        payload: dict[str, JSONValue] = {
            **replay,
            "generated_at": datetime.now(UTC).isoformat(),
            "policy_binding": {
                "class": "arc3.mechanics.visual_causal.VisualCausalPolicy",
                "max_coordinate_candidates": MAX_COORDINATE_CANDIDATES,
                "profile": args.policy_profile,
            },
            "receipt_status": receipt_status,
            "replay_evidence_mode": replay_mode,
            "runtime": {
                "bytecode_writes_disabled_at_startup": _BYTECODE_DISABLED_AT_STARTUP,
                "direct_script_invocation": _DIRECT_SCRIPT_INVOCATION,
                "platform": platform.platform(),
                "python": platform.python_version(),
            },
            "source_binding": source_binding,
        }
        if campaign_binding is not None:
            payload["campaign_audit_binding"] = campaign_binding
        if trace_binding is not None:
            payload["sealed_trace_binding"] = trace_binding
        document: dict[str, JSONValue] = seal_object(
            {
                "payload": payload,
                "payload_sha256": sha256_bytes(canonical_json_bytes(payload)),
                "schema": receipt_schema,
            },
            hash_field="replay_receipt_hash",
        )
        if not verify_object_hash(document, hash_field="replay_receipt_hash"):
            raise RuntimeError("replay receipt self-seal could not be verified")
        _write_exclusive(output, document)
    except (OSError, RuntimeError, ValueError, ARC3Error) as error:
        raise SystemExit(f"mechanical recording replay failed: {error}") from error

    sys.stdout.write(
        f"{receipt_status} {output} {sha256_file(output)} {document['replay_receipt_hash']}\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
