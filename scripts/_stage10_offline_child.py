"""Run one Stage 10 target after installing process-local socket denial."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import runpy
import socket
import sys
import traceback
import uuid
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, NoReturn, cast

SCHEMA = "arc3.build-001.stage-10-socket-denial.v0.1"
_OPERATIONS = (
    "create_connection",
    "getaddrinfo",
    "connect",
    "connect_ex",
    "send",
    "sendall",
    "sendto",
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


def _atomic_create(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    if path.exists():
        raise FileExistsError(f"refusing to overwrite socket-denial receipt {path}")
    try:
        with temporary.open("xb") as stream:
            stream.write(_canonical(value))
            stream.flush()
            os.fsync(stream.fileno())
        if path.exists():
            raise FileExistsError(f"refusing to overwrite socket-denial receipt {path}")
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
    exit_code = 0
    failure_kind: str | None = None
    try:
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
                "failure_kind": failure_kind,
                "frozen_commit": args.frozen_commit,
                "installed_operations": list(installed),
                "network_attempt_count": sum(attempts.values()),
                "process_id": os.getpid(),
                "schema": SCHEMA,
                "suite_id": args.suite_id,
                "target_kind": target_kind,
                "target_sha256": f"sha256:{hashlib.sha256(target_value.encode('utf-8')).hexdigest()}",
                "target_exit_code": exit_code,
            }
        )
        _atomic_create(args.receipt.resolve(), report)
    return exit_code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
