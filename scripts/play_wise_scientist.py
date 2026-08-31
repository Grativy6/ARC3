"""Interactive, evidence-gated runner for one authorized public development game."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from arc3.adapters.arc_agi import ArcAGIAdapter
from arc3.config import ARC3Config
from arc3.errors import ARC3Error, ARC3ValidationError
from arc3.evaluation.artifacts import atomic_write_json
from arc3.evaluation.public import acquire_local_public_asset
from arc3.trace.canonical import normalize_json, sha256_json
from arc3.types import EnvironmentMode, JSONValue
from arc3.wise_scientist import (
    ActCommand,
    AssessCommand,
    ScanCommand,
    WiseRunPhase,
    WiseScientistRun,
)

ROOT = Path(__file__).resolve().parents[1]
_AUTHORIZATION_SCHEMA = "arc3.wise-scientist.development-authorization.v0.1"


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _inside_checkout(value: str | Path, *, field: str) -> Path:
    resolved = (ROOT / value).resolve() if not Path(value).is_absolute() else Path(value).resolve()
    if not resolved.is_relative_to(ROOT):
        raise ARC3ValidationError(f"{field} must remain inside the repository checkout")
    return resolved


def _load_object(path: Path, *, field: str) -> dict[str, JSONValue]:
    try:
        raw: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ARC3ValidationError(f"cannot read {field}: {error}") from error
    normalized = normalize_json(raw)
    if not isinstance(normalized, dict):
        raise ARC3ValidationError(f"{field} must contain a JSON object")
    return normalized


def _validate_authorization(path: Path, *, game_id: str) -> dict[str, JSONValue]:
    receipt = _load_object(path, field="development authorization")
    required = {
        "schema",
        "game_id",
        "partition",
        "surface",
        "official_public",
        "public_holdout_eligible",
        "gameplay_authorized",
        "authority",
        "provenance",
        "authorization_hash",
    }
    if set(receipt) != required:
        raise ARC3ValidationError("development authorization has invalid fields")
    unsigned = {key: value for key, value in receipt.items() if key != "authorization_hash"}
    if receipt["authorization_hash"] != sha256_json(unsigned):
        raise ARC3ValidationError("development authorization hash mismatch")
    if (
        receipt["schema"] != _AUTHORIZATION_SCHEMA
        or receipt["game_id"] != game_id
        or receipt["partition"] != "development"
        or receipt["surface"] != "local-public"
        or receipt["official_public"] is not True
        or receipt["public_holdout_eligible"] is not False
        or receipt["gameplay_authorized"] is not True
    ):
        raise ARC3ValidationError(
            "game is not authorized as official public non-holdout development play"
        )
    return receipt


def _git_head() -> str:
    completed = subprocess.run(
        ("git", "rev-parse", "HEAD"),
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return completed.stdout.strip()


def _require_frozen_source(expected_commit: str) -> None:
    if _git_head() != expected_commit:
        raise ARC3ValidationError("current HEAD differs from --frozen-commit")
    completed = subprocess.run(
        ("git", "status", "--porcelain", "--untracked-files=all"),
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if completed.stdout.strip():
        raise ARC3ValidationError("tracked or untracked source tree is not clean")


def _acquire(
    *,
    game_id: str,
    seed: int,
    environment_dir: Path,
    recordings_dir: Path,
    artifact_dir: Path,
    authorization_hash: str,
) -> None:
    if "ARC_API_KEY" in os.environ:
        raise ARC3ValidationError(
            "credential use is outside this experiment authority; unset ARC_API_KEY"
        )
    intent: dict[str, JSONValue] = {
        "schema": "arc3.wise-scientist.acquisition-intent.v0.1",
        "game_id": game_id,
        "seed": seed,
        "surface": "official-public-acquisition",
        "partition": "development",
        "gameplay_exposure": True,
        "environment_actions": 0,
        "authorization_hash": authorization_hash,
        "started_at": _utc_now(),
    }
    intent_hash = sha256_json(intent)
    atomic_write_json(
        artifact_dir / "acquisition-intent.json", {**intent, "intent_hash": intent_hash}
    )
    try:
        acquire_local_public_asset(
            game_id,
            seed=seed,
            environments_dir=environment_dir,
            recordings_dir=recordings_dir,
        )
    except Exception as error:
        failure: dict[str, JSONValue] = {
            "schema": "arc3.wise-scientist.acquisition-receipt.v0.1",
            "status": "BLOCKED_EXTERNAL",
            "game_id": game_id,
            "partition": "development",
            "surface": "local-public",
            "gameplay_exposure": True,
            "environment_actions": 0,
            "intent_hash": intent_hash,
            "completed_at": _utc_now(),
            "failure_type": type(error).__name__,
        }
        atomic_write_json(
            artifact_dir / "acquisition-receipt.json",
            {**failure, "receipt_hash": sha256_json(failure)},
        )
        raise
    success: dict[str, JSONValue] = {
        "schema": "arc3.wise-scientist.acquisition-receipt.v0.1",
        "status": "PASS",
        "game_id": game_id,
        "partition": "development",
        "surface": "local-public",
        "gameplay_exposure": True,
        "environment_actions": 0,
        "intent_hash": intent_hash,
        "completed_at": _utc_now(),
        "network_used_for_acquisition": True,
        "evaluation_network_mode": "offline",
        "game_source_read_by_policy": False,
    }
    atomic_write_json(
        artifact_dir / "acquisition-receipt.json",
        {**success, "receipt_hash": sha256_json(success)},
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Play one authorized official public development game as Wise Scientist."
    )
    parser.add_argument("--game", required=True)
    parser.add_argument("--seed", required=True, type=int)
    parser.add_argument("--frozen-commit", required=True)
    parser.add_argument("--authorization-receipt", required=True, type=Path)
    parser.add_argument("--artifact-dir", required=True, type=Path)
    parser.add_argument("--environments-dir", required=True, type=Path)
    parser.add_argument("--recordings-dir", required=True, type=Path)
    parser.add_argument("--acquire-missing", action="store_true")
    parser.add_argument(
        "--resume",
        action="store_true",
        help="resume an existing artifact journal by verified deterministic local replay",
    )
    parser.add_argument(
        "--extend-wall-clock-on-resume",
        action="store_true",
        help=(
            "explicitly allow --wall-clock-seconds to increase during --resume; "
            "requires --wall-clock-extension-reason"
        ),
    )
    parser.add_argument(
        "--wall-clock-extension-reason",
        help="bounded reason recorded immutably when extending a resumed run",
    )
    parser.add_argument(
        "--extend-max-actions-on-resume",
        action="store_true",
        help=(
            "explicitly allow --max-actions to increase during --resume; "
            "requires --max-actions-extension-reason"
        ),
    )
    parser.add_argument(
        "--max-actions-extension-reason",
        help="bounded reason recorded immutably when extending physical actions",
    )
    parser.add_argument("--max-actions", type=int, default=1_000)
    parser.add_argument("--max-resets", type=int, default=20)
    parser.add_argument("--wall-clock-seconds", type=float, default=14_400.0)
    return parser


def _resume_wall_clock_extension_reason(args: argparse.Namespace) -> str | None:
    requested = cast(bool, args.extend_wall_clock_on_resume)
    supplied = cast(str | None, args.wall_clock_extension_reason)
    if not requested:
        if supplied is not None:
            raise ARC3ValidationError(
                "--wall-clock-extension-reason requires --extend-wall-clock-on-resume"
            )
        return None
    if not cast(bool, args.resume):
        raise ARC3ValidationError("--extend-wall-clock-on-resume requires --resume")
    return WiseScientistRun.normalize_wall_clock_extension_reason(supplied)


def _resume_environment_action_extension_reason(args: argparse.Namespace) -> str | None:
    requested = cast(bool, args.extend_max_actions_on_resume)
    supplied = cast(str | None, args.max_actions_extension_reason)
    if not requested:
        if supplied is not None:
            raise ARC3ValidationError(
                "--max-actions-extension-reason requires --extend-max-actions-on-resume"
            )
        return None
    if not cast(bool, args.resume):
        raise ARC3ValidationError("--extend-max-actions-on-resume requires --resume")
    return WiseScientistRun.normalize_environment_action_extension_reason(supplied)


def _emit(value: object) -> None:
    print(json.dumps(normalize_json(value), sort_keys=True, separators=(",", ":")), flush=True)


def _interactive_loop(run: WiseScientistRun) -> int:
    _emit({"ok": True, "event": "ready", "status": run.status()})
    if run.phase is WiseRunPhase.COMPLETE:
        return 0
    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        try:
            raw: object = json.loads(line)
            normalized = normalize_json(raw)
            if not isinstance(normalized, dict):
                raise ARC3ValidationError("interactive command must be a JSON object")
            command_name = normalized.get("command")
            payload = normalized.get("payload")
            if command_name == "status":
                response = run.status()
            elif command_name == "scan":
                response = run.scan(ScanCommand.from_dict(payload))
            elif command_name == "act":
                response = run.act(ActCommand.from_dict(payload))
            elif command_name == "assess":
                response = run.assess(AssessCommand.from_dict(payload))
            else:
                raise ARC3ValidationError("command must be status, scan, act, or assess")
            _emit({"ok": True, "event": command_name, "status": response})
            if run.status()["phase"] == WiseRunPhase.COMPLETE.value:
                return 0
        except (ARC3Error, ValueError, json.JSONDecodeError) as error:
            _emit(
                {
                    "ok": False,
                    "error_type": type(error).__name__,
                    "message": str(error),
                    "status": run.status(),
                }
            )
    _emit(
        {
            "ok": False,
            "error_type": "UnexpectedEOF",
            "message": "stdin closed before observed WIN; run is not complete",
            "status": run.status(),
        }
    )
    return 3


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    exposure_status = "not-attempted"
    try:
        wall_clock_extension_reason = _resume_wall_clock_extension_reason(args)
        environment_action_extension_reason = _resume_environment_action_extension_reason(args)
        artifact_dir = _inside_checkout(args.artifact_dir, field="artifact directory")
        environment_dir = _inside_checkout(args.environments_dir, field="environment directory")
        recordings_dir = _inside_checkout(args.recordings_dir, field="recordings directory")
        authorization_path = _inside_checkout(
            args.authorization_receipt, field="authorization receipt"
        )
        game_id = cast(str, args.game).strip()
        if not game_id:
            raise ARC3ValidationError("--game must be non-empty")
        authorization = _validate_authorization(authorization_path, game_id=game_id)
        _require_frozen_source(cast(str, args.frozen_commit))
        artifact_dir.mkdir(parents=True, exist_ok=True)
        environment_dir.mkdir(parents=True, exist_ok=True)
        recordings_dir.mkdir(parents=True, exist_ok=True)
        authorization_hash = authorization["authorization_hash"]
        assert isinstance(authorization_hash, str)
        if args.acquire_missing:
            exposure_status = "acquisition-attempted"
            _acquire(
                game_id=game_id,
                seed=cast(int, args.seed),
                environment_dir=environment_dir,
                recordings_dir=recordings_dir,
                artifact_dir=artifact_dir,
                authorization_hash=authorization_hash,
            )
            exposure_status = "acquisition-opened-and-closed"
        config = ARC3Config.for_mode(
            EnvironmentMode.LOCAL,
            seed=cast(int, args.seed),
            network_enabled=False,
            profile="wise-scientist-003w",
        )
        adapter = ArcAGIAdapter(
            config,
            environments_dir=environment_dir,
            recordings_dir=recordings_dir,
            api_key="",
            save_recording=True,
        )
        exposure_status = "local-run-open-attempted"
        session = adapter.open(game_id, seed=cast(int, args.seed))
        exposure_status = "local-run-opened"
        if args.resume:
            if args.acquire_missing:
                raise ARC3ValidationError("--resume cannot be combined with --acquire-missing")
            run = WiseScientistRun.resume(
                session,
                artifact_dir,
                recovery_source_commit=cast(str, args.frozen_commit),
                authorization_hash=authorization_hash,
                max_environment_actions=cast(int, args.max_actions),
                max_resets=cast(int, args.max_resets),
                wall_clock_seconds=cast(float, args.wall_clock_seconds),
                allow_environment_action_extension=cast(bool, args.extend_max_actions_on_resume),
                environment_action_extension_reason=environment_action_extension_reason,
                allow_wall_clock_extension=cast(bool, args.extend_wall_clock_on_resume),
                wall_clock_extension_reason=wall_clock_extension_reason,
            )
        else:
            run = WiseScientistRun(
                session,
                artifact_dir,
                source_commit=cast(str, args.frozen_commit),
                authorization_hash=authorization_hash,
                max_environment_actions=cast(int, args.max_actions),
                max_resets=cast(int, args.max_resets),
                wall_clock_seconds=cast(float, args.wall_clock_seconds),
            )
        return _interactive_loop(run)
    except (ARC3Error, OSError, subprocess.SubprocessError, ValueError) as error:
        _emit(
            {
                "ok": False,
                "error_type": type(error).__name__,
                "message": str(error),
                "official_environment_exposure_status": exposure_status,
            }
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
