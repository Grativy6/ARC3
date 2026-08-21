"""ARC3 command-line dispatch."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence

from arc3 import __version__
from arc3.config import default_config
from arc3.doctor import format_doctor_report, run_doctor
from arc3.errors import ARC3Error
from arc3.types import EnvironmentMode

CommandHandler = Callable[[argparse.Namespace], int]

_RESERVED_COMMANDS: dict[str, str] = {
    "games": "Stage 02 official SDK game discovery",
    "play": "Stage 02 environment play loop",
    "evaluate": "Stage 13 evaluation harness",
    "compare": "Stage 13 evaluation comparison",
    "report": "Stage 13 measured report generation",
    "replay": "Stage 03 immutable trace replay",
    "verify-artifacts": "Stage 13 artifact verification",
}


def _doctor_command(args: argparse.Namespace) -> int:
    config = default_config(EnvironmentMode(args.mode), seed=args.seed)
    report = run_doctor(config)
    if args.output == "json":
        print(json.dumps(report.to_dict(), sort_keys=True, separators=(",", ":")))
    else:
        print(format_doctor_report(report))
    return 0 if report.passed else 1


def _reserved_command(args: argparse.Namespace) -> int:
    command = str(args.command)
    stage = _RESERVED_COMMANDS[command]
    print(
        f"arc3 {command}: reserved for {stage}; this workflow checkpoint "
        "does not implement it yet.",
        file=sys.stderr,
    )
    return 2


def build_parser() -> argparse.ArgumentParser:
    """Build the parser separately so help and dispatch can be tested."""

    parser = argparse.ArgumentParser(
        prog="arc3",
        description="Offline-first ARC-AGI-3 research agent tooling.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")

    doctor_parser = subparsers.add_parser(
        "doctor", help="check the local Python, configuration, and optional SDK"
    )
    doctor_parser.add_argument(
        "--mode",
        choices=[mode.value for mode in EnvironmentMode],
        default=EnvironmentMode.SYNTHETIC.value,
    )
    doctor_parser.add_argument("--seed", type=int, default=0)
    doctor_parser.add_argument("--output", choices=("text", "json"), default="text")
    doctor_parser.add_argument("--json", action="store_const", const="json", dest="output")
    doctor_parser.set_defaults(handler=_doctor_command)

    for command, stage in _RESERVED_COMMANDS.items():
        reserved = subparsers.add_parser(command, help=f"reserved: {stage}")
        reserved.add_argument("arguments", nargs=argparse.REMAINDER)
        reserved.set_defaults(handler=_reserved_command)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Dispatch a command and return a process-compatible status code."""

    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return 0
    try:
        return int(handler(args))
    except ARC3Error as error:
        print(f"arc3: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
