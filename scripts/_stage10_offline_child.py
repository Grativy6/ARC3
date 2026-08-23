"""Run one Stage 10 target after installing process-local socket denial."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import runpy
import socket
import subprocess
import sys
import time
import traceback
import uuid
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, NoReturn, cast

SCHEMA = "arc3.build-001.stage-10-socket-denial.v0.3"
AUTHORITY_SCHEMA = "arc3.build-001.stage-10-child-authority.v0.3"
PREDECLARATION_SHA256 = "sha256:e056eea0d4a6664996ae9078e15b4cdddb5f6c40d5b770540b8e9068cc224613"
PREDECLARATION_AMENDMENT_SHA256 = (
    "sha256:6eb1a9f5fba2ce02fbe601ffa123d5f9fb8a9ecc44c0a7db5c91fefdaf5bf2a6"
)
COMPOSITE_INTEGRITY_SCHEMA = "arc3.build-001.competition-integrity-composite.v0.1"
LAUNCH_SCHEMA = "arc3.build-001.stage-10-process-launch.v0.1"
AUTHORIZATION_SCHEMA = "arc3.build-001.stage-10-launch-authorization.v0.1"
ABORT_SCHEMA = "arc3.build-001.stage-10-worker-abort.v0.1"
_OPERATIONS = (
    "create_connection",
    "getaddrinfo",
    "connect",
    "connect_ex",
    "send",
    "sendall",
    "sendto",
)
_AUTHORIZED_SUITES = (
    "stage13-evaluate",
    "stage13-verify",
    "stage14-ablations",
    "palette-equivariance",
    "action-equivariance",
    "rule-change",
    "checkpoint-replay",
    "resource-profile",
)


def _canonical(value: dict[str, object]) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _seal(value: dict[str, object]) -> dict[str, object]:
    unsigned = {key: item for key, item in value.items() if key != "receipt_sha256"}
    digest = hashlib.sha256(_canonical(unsigned)).hexdigest()
    return {**unsigned, "receipt_sha256": f"sha256:{digest}"}


def _seal_field(value: Mapping[str, object], field: str) -> dict[str, object]:
    unsigned = {key: item for key, item in value.items() if key != field}
    digest = hashlib.sha256(_canonical(unsigned)).hexdigest()
    return {**unsigned, field: f"sha256:{digest}"}


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return f"sha256:{digest.hexdigest()}"


def _argv_hash(value: Sequence[str]) -> str:
    raw = (
        json.dumps(
            list(value),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(raw).hexdigest()}"


def _is_sha256(value: object) -> bool:
    return bool(
        isinstance(value, str)
        and value.startswith("sha256:")
        and len(value) == 71
        and all(character in "0123456789abcdef" for character in value[7:])
    )


def _load_authority(
    path: Path | None,
    *,
    suite_id: str,
    frozen_commit: str,
    expected_integrity_inputs_hash: str,
) -> tuple[dict[str, object] | None, object]:
    if path is None:
        return None, None
    raw = path.resolve().read_bytes()
    value: object = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("Stage 10 child authority is not an object")
    authority = cast(dict[str, object], value)
    unsigned = {key: item for key, item in authority.items() if key != "authority_sha256"}
    expected = authority.get("authority_sha256")
    actual = f"sha256:{hashlib.sha256(_canonical(unsigned)).hexdigest()}"
    profile = authority.get("profile")
    composition = authority.get("integrity_composition")
    expected_fields = {
        "authority_sha256",
        "authorized_suites",
        "frozen_commit",
        "integrity_inputs_hash",
        "integrity_composition",
        "integrity_parent_receipt_sha256",
        "plan_hash",
        "predeclaration_amendment_sha256",
        "predeclaration_sha256",
        "profile",
        "runtime_identity_sha256",
        "runtime_surface",
        "schema",
        "source_commit",
        "source_tree",
        "supervisor_import_identity_sha256",
    }
    expected_authority_hash = os.environ.get("ARC3_STAGE10_EXPECTED_AUTHORITY_SHA256")
    expected_file_hash = os.environ.get("ARC3_STAGE10_EXPECTED_AUTHORITY_FILE_SHA256")
    expected_parent_hash = os.environ.get("ARC3_STAGE10_EXPECTED_PARENT_RECEIPT_SHA256")
    file_hash = f"sha256:{hashlib.sha256(raw).hexdigest()}"
    if (
        set(authority) != expected_fields
        or raw != _canonical(authority)
        or authority.get("schema") != AUTHORITY_SCHEMA
        or not isinstance(expected, str)
        or expected != actual
        or expected != expected_authority_hash
        or file_hash != expected_file_hash
        or authority.get("frozen_commit") != frozen_commit
        or authority.get("source_commit") != frozen_commit
        or authority.get("authorized_suites") != list(_AUTHORIZED_SUITES)
        or suite_id not in _AUTHORIZED_SUITES
        or authority.get("predeclaration_sha256") != PREDECLARATION_SHA256
        or authority.get("predeclaration_amendment_sha256") != PREDECLARATION_AMENDMENT_SHA256
        or profile
        != {
            "authorized_surface": "synthetic-no-semantic-public-manifest",
            "public_identifier_values_available": 0,
            "public_manifest_paths_available": 0,
            "semantic_public_manifest_access": False,
        }
        or not isinstance(composition, dict)
        or not isinstance(authority.get("runtime_surface"), dict)
        or set(composition)
        != {
            "composite_integrity_core_hash",
            "composite_integrity_file_sha256",
            "composite_integrity_schema",
            "assurance_limitation",
            "dynamic_or_native_containment",
            "full_public_integrity_status",
            "integrity_inputs_file_sha256",
            "integrity_inputs_hash",
            "integrity_inputs_schema",
            "semantic_holdout_identifier_scan",
            "static_authority_claim",
        }
        or composition.get("composite_integrity_schema") != COMPOSITE_INTEGRITY_SCHEMA
        or composition.get("integrity_inputs_schema")
        != "arc3.build-001.stage-10-integrity-authority-inputs.v0.1"
        or composition.get("static_authority_claim")
        != "BOUNDED_STATIC_COMPETITION_INTEGRITY_WITH_OPAQUE_HOLDOUT"
        or composition.get("full_public_integrity_status")
        != "NOT_EVALUATED_BUILD_001_PUBLIC_IDENTIFIERS"
        or composition.get("assurance_limitation")
        != (
            "Package and development scans are static; dynamic-import and native-extension "
            "containment are not proven; Build 001 public identifiers were not fully evaluated."
        )
        or composition.get("semantic_holdout_identifier_scan")
        != "NOT_EVALUATED_SEALED_HOLDOUT_IDENTIFIERS"
        or composition.get("dynamic_or_native_containment")
        != "NOT_PROVEN_BY_STATIC_IMPORT_REACHABILITY"
        or not _is_sha256(authority.get("integrity_inputs_hash"))
        or authority.get("integrity_inputs_hash") != composition.get("integrity_inputs_hash")
        or authority.get("integrity_inputs_hash") != expected_integrity_inputs_hash
        or not _is_sha256(authority.get("supervisor_import_identity_sha256"))
        or not _is_sha256(composition.get("composite_integrity_core_hash"))
        or not _is_sha256(composition.get("composite_integrity_file_sha256"))
        or not _is_sha256(composition.get("integrity_inputs_file_sha256"))
        or not _is_sha256(composition.get("integrity_inputs_hash"))
    ):
        raise ValueError("Stage 10 child authority failed closed validation")
    parent_hash = authority.get("integrity_parent_receipt_sha256")
    if not isinstance(parent_hash, str) or parent_hash != expected_parent_hash:
        raise ValueError("Stage 10 child authority has no parent receipt hash")
    projection = {
        "authority_sha256": expected,
        "file_sha256": file_hash,
        "integrity_inputs_hash": authority.get("integrity_inputs_hash"),
        "integrity_composition": composition,
        "integrity_parent_receipt_sha256": parent_hash,
        "profile": profile,
    }
    return authority, projection


def _validate_live_authority(authority: Mapping[str, object] | None) -> None:
    """Revalidate source/interpreter/package/scorer bytes before target import."""

    if authority is None:
        return
    source_root = Path.cwd().resolve()
    completed = subprocess.run(
        (
            "git",
            "rev-parse",
            "--show-toplevel",
            "HEAD",
            "HEAD^{tree}",
        ),
        cwd=source_root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    status = subprocess.run(
        ("git", "status", "--porcelain=v1", "--untracked-files=all"),
        cwd=source_root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    lines = completed.stdout.splitlines()
    if (
        completed.returncode != 0
        or status.returncode != 0
        or status.stdout != ""
        or len(lines) != 3
        or Path(lines[0]).resolve() != source_root
        or lines[1] != authority.get("source_commit")
        or lines[2] != authority.get("source_tree")
    ):
        raise ValueError("Stage 10 child source identity changed before target import")
    from arc3.evaluation.integrity_authority import runtime_surface_identity

    expected_runtime = authority.get("runtime_surface")
    if (
        Path(runtime_surface_identity.__code__.co_filename).resolve()
        != source_root / "src/arc3/evaluation/integrity_authority.py"
        or not isinstance(expected_runtime, Mapping)
        or runtime_surface_identity(source_root) != dict(expected_runtime)
    ):
        raise ValueError("Stage 10 child runtime identity changed before target import")


def _atomic_create(path: Path, value: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    if path.exists():
        raise FileExistsError(f"refusing to overwrite immutable Stage 10 receipt {path}")
    try:
        with temporary.open("xb") as stream:
            stream.write(_canonical(dict(value)))
            stream.flush()
            os.fsync(stream.fileno())
        if path.exists():
            raise FileExistsError(f"refusing to overwrite immutable Stage 10 receipt {path}")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _install_denial() -> tuple[dict[str, int], tuple[str, ...]]:
    attempts = {operation: 0 for operation in _OPERATIONS}

    def denier(operation: str) -> Callable[..., NoReturn]:
        def deny(*_args: object, **_kwargs: object) -> NoReturn:
            attempts[operation] += 1
            raise OSError(f"Stage 10 offline guard denied socket operation {operation}")

        return deny

    socket.create_connection = denier("create_connection")
    socket.getaddrinfo = denier("getaddrinfo")
    socket_class = cast(Any, socket.socket)
    socket_class.connect = denier("connect")
    socket_class.connect_ex = denier("connect_ex")
    socket_class.send = denier("send")
    socket_class.sendall = denier("sendall")
    socket_class.sendto = denier("sendto")
    return attempts, _OPERATIONS


def _process_creation_token(pid: int) -> str | None:
    """Return a restart-comparable operating-system process identity."""

    if isinstance(pid, bool) or pid <= 0:
        return None
    if os.name == "nt":
        try:
            probe = subprocess.run(
                (
                    "powershell.exe",
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    (
                        "$p=Get-CimInstance Win32_Process -Filter 'ProcessId = "
                        f"{pid}';if($null -ne $p){{$p.CreationDate.ToUniversalTime().Ticks}}"
                    ),
                ),
                check=False,
                capture_output=True,
                text=True,
                timeout=5.0,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        value = probe.stdout.strip()
        return f"windows-cim:{value}" if probe.returncode == 0 and value.isdigit() else None
    stat_path = Path(f"/proc/{pid}/stat")
    command_path = Path(f"/proc/{pid}/cmdline")
    if stat_path.is_file() and command_path.is_file():
        try:
            stat = stat_path.read_text(encoding="utf-8")
            suffix = stat[stat.rfind(")") + 2 :].split()
            start_ticks = suffix[19]
            command_hash = hashlib.sha256(command_path.read_bytes()).hexdigest()
        except (OSError, IndexError):
            return None
        return f"linux-proc:{start_ticks}:sha256:{command_hash}"
    return None


def _expected_command(args: argparse.Namespace) -> list[str]:
    launcher = os.environ.get("ARC3_STAGE10_LEXICAL_LAUNCHER")
    if not launcher:
        raise ValueError("Stage 10 lexical interpreter launcher is absent")
    command = [
        launcher,
        str(Path(__file__).resolve()),
        "--receipt",
        str(args.receipt.resolve()),
        "--suite-id",
        str(args.suite_id),
        "--frozen-commit",
        str(args.frozen_commit),
    ]
    if args.authority is not None:
        command.extend(("--authority", str(args.authority.resolve())))
    command.extend(
        (
            "--launch-receipt",
            str(args.launch_receipt.resolve()),
            "--authorization",
            str(args.authorization.resolve()),
            "--abort-receipt",
            str(args.abort_receipt.resolve()),
            "--launch-token",
            str(args.launch_token),
        )
    )
    if args.module is not None:
        command.extend(("--module", str(args.module)))
    else:
        command.extend(("--script", str(args.script.resolve())))
    command.append("--")
    arguments = list(args.target_arguments)
    if arguments[:1] == ["--"]:
        arguments = arguments[1:]
    command.extend(arguments)
    return command


def _launch_payload(
    args: argparse.Namespace,
    *,
    installed: Sequence[str],
) -> dict[str, object]:
    token = _process_creation_token(os.getpid())
    if token is None:
        raise ValueError("Stage 10 worker process creation identity is unavailable")
    command = _expected_command(args)
    target_kind = "module" if args.module is not None else "script"
    target_value = str(args.module if args.module is not None else args.script.resolve())
    return _seal_field(
        {
            "abort_path": args.abort_receipt.resolve().as_posix(),
            "authorization_path": args.authorization.resolve().as_posix(),
            "authority_path": (
                args.authority.resolve().as_posix() if args.authority is not None else None
            ),
            "command": command,
            "command_sha256": _argv_hash(command),
            "cwd": Path.cwd().resolve().as_posix(),
            "frozen_commit": args.frozen_commit,
            "launch_token": args.launch_token,
            "network_receipt_path": args.receipt.resolve().as_posix(),
            "parent_pid": os.getppid(),
            "pid": os.getpid(),
            "process_creation_token": token,
            "schema": LAUNCH_SCHEMA,
            "socket_denial_installed": list(installed) == list(_OPERATIONS),
            "suite_id": args.suite_id,
            "target_imported": False,
            "target_kind": target_kind,
            "target_sha256": f"sha256:{hashlib.sha256(target_value.encode('utf-8')).hexdigest()}",
        },
        "launch_receipt_hash",
    )


def _authorization_valid(
    args: argparse.Namespace,
    *,
    launch: Mapping[str, object],
) -> dict[str, object] | None:
    try:
        raw = args.authorization.resolve().read_bytes()
        value: object = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict):
        return None
    authorization = cast(dict[str, object], value)
    expected_fields = {
        "abort_path",
        "authorization_hash",
        "command_sha256",
        "containment",
        "frozen_commit",
        "integrity_inputs_hash",
        "launch_receipt_hash",
        "launch_receipt_sha256",
        "launch_token",
        "network_receipt_path",
        "pid",
        "plan_hash",
        "process_creation_token",
        "runtime_identity_sha256",
        "runtime_surface",
        "schema",
        "source_commit",
        "source_root",
        "source_tree",
        "suite_id",
        "suite_spec_sha256",
        "supervisor_import_identity_sha256",
        "target_import_authorized",
    }
    if (
        set(authorization) != expected_fields
        or raw != _canonical(authorization)
        or authorization.get("schema") != AUTHORIZATION_SCHEMA
        or authorization.get("authorization_hash")
        != _seal_field(authorization, "authorization_hash").get("authorization_hash")
        or authorization.get("launch_receipt_hash") != launch.get("launch_receipt_hash")
        or authorization.get("launch_receipt_sha256") != _file_sha256(args.launch_receipt.resolve())
        or authorization.get("launch_token") != args.launch_token
        or authorization.get("pid") != os.getpid()
        or authorization.get("process_creation_token") != launch.get("process_creation_token")
        or authorization.get("command_sha256") != launch.get("command_sha256")
        or not isinstance(authorization.get("containment"), Mapping)
        or authorization.get("suite_id") != args.suite_id
        or authorization.get("frozen_commit") != args.frozen_commit
        or authorization.get("source_root") != Path.cwd().resolve().as_posix()
        or authorization.get("abort_path") != args.abort_receipt.resolve().as_posix()
        or authorization.get("network_receipt_path") != args.receipt.resolve().as_posix()
        or authorization.get("target_import_authorized") is not True
        or not _is_sha256(authorization.get("plan_hash"))
        or not _is_sha256(authorization.get("integrity_inputs_hash"))
        or not _is_sha256(authorization.get("suite_spec_sha256"))
        or not _is_sha256(authorization.get("runtime_identity_sha256"))
        or not _is_sha256(authorization.get("supervisor_import_identity_sha256"))
        or not isinstance(authorization.get("runtime_surface"), Mapping)
    ):
        return None
    return authorization


def _await_authorization(
    args: argparse.Namespace,
    *,
    launch: Mapping[str, object],
) -> dict[str, object] | None:
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        authorization = _authorization_valid(args, launch=launch)
        if authorization is not None:
            return authorization
        time.sleep(0.02)
    abort = _seal_field(
        {
            "authorization_path": args.authorization.resolve().as_posix(),
            "launch_receipt_hash": launch.get("launch_receipt_hash"),
            "launch_receipt_path": args.launch_receipt.resolve().as_posix(),
            "launch_token": args.launch_token,
            "pid": os.getpid(),
            "process_creation_token": launch.get("process_creation_token"),
            "reason": "launch-authorization-unavailable-or-invalid",
            "schema": ABORT_SCHEMA,
            "socket_denial_installed": True,
            "suite_id": args.suite_id,
            "target_imported": False,
        },
        "worker_abort_hash",
    )
    try:
        _atomic_create(args.abort_receipt.resolve(), abort)
    except FileExistsError:
        if args.abort_receipt.resolve().read_bytes() != _canonical(abort):
            raise ValueError("existing Stage 10 worker abort receipt changed") from None
    return None


def _exit_code(value: object) -> int:
    if value is None:
        return 0
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--suite-id", required=True)
    parser.add_argument("--frozen-commit", required=True)
    parser.add_argument("--authority", type=Path)
    parser.add_argument("--launch-receipt", type=Path, required=True)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--abort-receipt", type=Path, required=True)
    parser.add_argument("--launch-token", required=True)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--module")
    target.add_argument("--script", type=Path)
    parser.add_argument("target_arguments", nargs=argparse.REMAINDER)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    target_kind = "module" if args.module is not None else "script"
    target_value = str(args.module if args.module is not None else args.script.resolve())
    target_arguments = list(args.target_arguments)
    if target_arguments[:1] == ["--"]:
        target_arguments = target_arguments[1:]
    attempts, installed = _install_denial()
    authority: object = None
    authorization_projection: object = None
    exit_code = 0
    failure_kind: str | None = None
    try:
        launch = _launch_payload(args, installed=installed)
        _atomic_create(args.launch_receipt.resolve(), launch)
        authorization = _await_authorization(args, launch=launch)
        if authorization is None:
            exit_code = 72
            failure_kind = "LaunchAuthorizationUnavailable"
            return 72
        authorization_projection = {
            "authorization_hash": authorization.get("authorization_hash"),
            "integrity_inputs_hash": authorization.get("integrity_inputs_hash"),
            "launch_receipt_hash": authorization.get("launch_receipt_hash"),
            "plan_hash": authorization.get("plan_hash"),
            "runtime_identity_sha256": authorization.get("runtime_identity_sha256"),
            "suite_spec_sha256": authorization.get("suite_spec_sha256"),
            "supervisor_import_identity_sha256": authorization.get(
                "supervisor_import_identity_sha256"
            ),
        }
        _validate_live_authority(authorization)
        full_authority, authority = _load_authority(
            args.authority,
            suite_id=args.suite_id,
            frozen_commit=args.frozen_commit,
            expected_integrity_inputs_hash=cast(str, authorization["integrity_inputs_hash"]),
        )
        _validate_live_authority(full_authority)
        sys.argv = [target_value, *target_arguments]
        if args.module is not None:
            runpy.run_module(args.module, run_name="__main__", alter_sys=True)
        else:
            runpy.run_path(str(args.script.resolve()), run_name="__main__")
    except SystemExit as caught:
        exit_code = _exit_code(caught.code)
    except BaseException as caught:
        exit_code = 70
        failure_kind = type(caught).__name__
        traceback.print_exc()
    finally:
        report = _seal(
            {
                "attempts": attempts,
                "authority": authority,
                "failure_kind": failure_kind,
                "frozen_commit": args.frozen_commit,
                "installed_operations": list(installed),
                "launch_authorization": authorization_projection,
                "network_attempt_count": sum(attempts.values()),
                "process_id": os.getpid(),
                "schema": SCHEMA,
                "suite_id": args.suite_id,
                "target_kind": target_kind,
                "target_argv_sha256": _argv_hash((target_value, *target_arguments)),
                "target_sha256": f"sha256:{hashlib.sha256(target_value.encode('utf-8')).hexdigest()}",
                "target_exit_code": exit_code,
            }
        )
        _atomic_create(args.receipt.resolve(), report)
    return exit_code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
