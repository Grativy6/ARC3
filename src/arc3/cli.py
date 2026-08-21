"""ARC3 command-line dispatch."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from arc3 import __version__
from arc3.adapters import EnvironmentAdapter, EnvironmentDescriptor, ScoreSummary
from arc3.adapters.arc_agi import ArcAGIAdapter
from arc3.adapters.synthetic import SYNTHETIC_GAME_ID, SyntheticAdapter
from arc3.baseline_runner import BaselineEpisodeResult, run_baseline_episode
from arc3.config import ARC3Config, default_config
from arc3.doctor import format_doctor_report, run_doctor
from arc3.errors import ARC3Error
from arc3.evaluation import (
    EvaluationConfig,
    compare_evaluations,
    resolve_evaluation,
    run_evaluation,
    verify_evaluation_artifacts,
)
from arc3.policy.baselines import make_baseline
from arc3.types import EnvironmentMode

CommandHandler = Callable[[argparse.Namespace], int]

_RESERVED_COMMANDS: dict[str, str] = {
    "replay": "Stage 03 immutable trace replay",
}


def _adapter_from_args(args: argparse.Namespace) -> EnvironmentAdapter:
    mode = EnvironmentMode(args.mode)
    if mode is EnvironmentMode.SYNTHETIC:
        return SyntheticAdapter(seed=args.seed)
    config = ARC3Config.for_mode(mode, seed=args.seed)
    return ArcAGIAdapter(
        config,
        environments_dir=Path(args.environments_dir),
        recordings_dir=Path(args.recordings_dir),
    )


def _descriptor_dict(descriptor: EnvironmentDescriptor) -> dict[str, Any]:
    return {
        "game_id": str(descriptor.game_id),
        "title": descriptor.title,
        "tags": list(descriptor.tags),
        "baseline_actions": list(descriptor.baseline_actions),
        "locally_available": descriptor.locally_available,
    }


def _scorecard_dict(scorecard: ScoreSummary | None) -> dict[str, Any] | None:
    if scorecard is None:
        return None
    return {
        "surface": scorecard.surface.value,
        "verified": scorecard.verified,
        "scorer": scorecard.scorer,
        "score": scorecard.score,
        "total_actions": scorecard.total_actions,
        "total_resets": scorecard.total_resets,
        "runs": [
            {
                "game_id": str(run.game_id),
                "score": run.score,
                "levels_completed": run.levels_completed,
                "actions": run.actions,
                "resets": run.resets,
                "state": run.state.value,
                "completed": run.completed,
            }
            for run in scorecard.runs
        ],
    }


def _episode_dict(result: BaselineEpisodeResult) -> dict[str, Any]:
    return {
        "stop_reason": result.stop_reason.value,
        "environment_actions": result.environment_actions,
        "resets": result.resets,
        "final_state": result.final_observation.state.value,
        "receipt_count": len(result.receipts),
        "scorecard": _scorecard_dict(result.scorecard),
    }


def _games_list_command(args: argparse.Namespace) -> int:
    games = _adapter_from_args(args).list_games()
    payload = {
        "schema": "arc3.games.v0.1",
        "mode": args.mode,
        "count": len(games),
        "games": [_descriptor_dict(game) for game in games],
    }
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    return 0


def _play_command(args: argparse.Namespace) -> int:
    adapter = _adapter_from_args(args)
    game_id = args.game or (SYNTHETIC_GAME_ID if args.mode == "synthetic" else None)
    if game_id is None:
        raise ValueError("--game is required outside synthetic mode")
    session = adapter.open(game_id, seed=args.seed)
    policy = make_baseline(args.agent, seed=args.seed)
    result = run_baseline_episode(
        session,
        policy,
        max_actions=args.max_actions,
        max_resets=args.max_resets,
    )
    payload = {
        "schema": "arc3.play.v0.1",
        "mode": args.mode,
        "agent": args.agent,
        "seed": args.seed,
        "game_id": game_id,
        "result": _episode_dict(result),
    }
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    return 0


def _parse_seeds(value: str) -> tuple[int, ...]:
    try:
        seeds = tuple(int(item.strip()) for item in value.split(",") if item.strip())
    except ValueError as error:
        raise ValueError("--seeds must be a comma-separated integer list") from error
    if not seeds:
        raise ValueError("--seeds must contain at least one integer")
    return seeds


def _parse_agents(value: str) -> tuple[str, ...]:
    agents = tuple(item.strip().lower() for item in value.split(",") if item.strip())
    if not agents:
        raise ValueError("--agents must contain at least one policy name")
    if len(set(agents)) != len(agents):
        raise ValueError("--agents must not contain duplicate policy names")
    return agents


def _evaluate_command(args: argparse.Namespace) -> int:
    if args.agents is not None:
        outcome = run_evaluation(
            EvaluationConfig(
                partition=args.partition,
                agents=_parse_agents(args.agents),
                seeds=_parse_seeds(args.seeds),
                max_actions=args.max_actions,
                max_resets=args.max_resets,
                timeout_seconds=args.timeout_seconds,
                output_root=Path(args.output_root),
                evaluation_id=args.evaluation_id,
            )
        )
        print(
            json.dumps(
                {
                    "schema": "arc3.evaluation.command.v0.1",
                    "evaluation_id": outcome.evaluation_id,
                    "evaluation_path": str(outcome.directory),
                    "status": outcome.status,
                    "result_count": outcome.summary["result_count"],
                    "failure_count": outcome.summary["failure_count"],
                    "successful_policy_count": outcome.summary["successful_policy_count"],
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 0 if outcome.status == "PASS" else 1

    # Backward-compatible Stage 02 single-agent output has no wall-clock fields and
    # remains byte-for-byte deterministic for its established tests and receipts.
    if args.partition != "smoke":
        raise ValueError("Stage 02 supports only the synthetic smoke partition")
    seeds = _parse_seeds(args.seeds)
    results: list[dict[str, Any]] = []
    for seed in seeds:
        adapter = SyntheticAdapter(seed=seed)
        session = adapter.open(SYNTHETIC_GAME_ID, seed=seed)
        result = run_baseline_episode(
            session,
            make_baseline(args.agent, seed=seed),
            max_actions=args.max_actions,
            max_resets=args.max_resets,
        )
        results.append({"seed": seed, **_episode_dict(result)})
    scores = [
        float(result["scorecard"]["score"]) for result in results if result["scorecard"] is not None
    ]
    payload = {
        "schema": "arc3.evaluation.smoke.v0.1",
        "label": "synthetic",
        "partition": args.partition,
        "agent": args.agent,
        "seeds": list(seeds),
        "mean_score": sum(scores) / len(scores) if scores else 0.0,
        "runs": results,
    }
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    return 0


def _compare_command(args: argparse.Namespace) -> int:
    payload = compare_evaluations(
        list(args.evaluation),
        output_root=Path(args.output_root),
    )
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    return 0


def _report_command(args: argparse.Namespace) -> int:
    directory = resolve_evaluation(args.evaluation, output_root=Path(args.output_root))
    verification = verify_evaluation_artifacts(directory)
    if not verification["verified"]:
        raw_errors = verification.get("errors")
        error_items = raw_errors if isinstance(raw_errors, list) else [raw_errors]
        details = "; ".join(str(item) for item in error_items)
        raise ValueError(f"evaluation artifacts failed verification: {details}")
    report_path = directory / "report.md"
    if not report_path.is_file():
        raise ValueError(f"evaluation report is missing: {report_path}")
    print(report_path.read_text(encoding="utf-8"), end="")
    return 0


def _verify_artifacts_command(args: argparse.Namespace) -> int:
    directory = resolve_evaluation(args.evaluation, output_root=Path(args.output_root))
    payload = verify_evaluation_artifacts(directory)
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    return 0 if payload["verified"] else 1


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

    games_parser = subparsers.add_parser("games", help="discover normalized ARC environments")
    games_subparsers = games_parser.add_subparsers(dest="games_command", required=True)
    games_list = games_subparsers.add_parser("list", help="list available environments")
    games_list.add_argument(
        "--mode",
        choices=[mode.value for mode in EnvironmentMode],
        default=EnvironmentMode.LOCAL.value,
    )
    games_list.add_argument("--seed", type=int, default=0)
    games_list.add_argument("--environments-dir", default="environment_files")
    games_list.add_argument("--recordings-dir", default="recordings")
    games_list.set_defaults(handler=_games_list_command)

    play_parser = subparsers.add_parser("play", help="run a bounded deterministic baseline")
    play_parser.add_argument("--agent", choices=("random", "cycle", "sweep"), default="cycle")
    play_parser.add_argument("--game")
    play_parser.add_argument(
        "--mode",
        choices=[mode.value for mode in EnvironmentMode],
        default=EnvironmentMode.SYNTHETIC.value,
    )
    play_parser.add_argument("--seed", type=int, default=0)
    play_parser.add_argument("--max-actions", type=int, default=100)
    play_parser.add_argument("--max-resets", type=int, default=8)
    play_parser.add_argument("--environments-dir", default="environment_files")
    play_parser.add_argument("--recordings-dir", default="recordings")
    play_parser.set_defaults(handler=_play_command)

    evaluate_parser = subparsers.add_parser(
        "evaluate", help="run a deterministic synthetic evaluation or legacy single baseline"
    )
    evaluate_parser.add_argument("--agent", choices=("random", "cycle"), default="cycle")
    evaluate_parser.add_argument(
        "--agents",
        help="comma-separated Stage 13 policies: random,cycle,novelty,trace,full",
    )
    evaluate_parser.add_argument("--partition", default="smoke")
    evaluate_parser.add_argument("--seeds", default="0,1,2,3")
    evaluate_parser.add_argument("--max-actions", type=int, default=100)
    evaluate_parser.add_argument("--max-resets", type=int, default=8)
    evaluate_parser.add_argument("--timeout-seconds", type=float, default=30.0)
    evaluate_parser.add_argument("--output-root", default="artifacts/evaluations")
    evaluate_parser.add_argument("--evaluation-id")
    evaluate_parser.set_defaults(handler=_evaluate_command)

    compare_parser = subparsers.add_parser(
        "compare", help="compare policies within one or more sealed evaluations"
    )
    compare_parser.add_argument("--evaluation", action="append", required=True)
    compare_parser.add_argument("--output-root", default="artifacts/evaluations")
    compare_parser.set_defaults(handler=_compare_command)

    report_parser = subparsers.add_parser("report", help="render an evaluation Markdown report")
    report_parser.add_argument("--evaluation", required=True)
    report_parser.add_argument("--output-root", default="artifacts/evaluations")
    report_parser.set_defaults(handler=_report_command)

    verify_parser = subparsers.add_parser(
        "verify-artifacts", help="verify every hash sealed by an evaluation manifest"
    )
    verify_parser.add_argument("--evaluation", required=True)
    verify_parser.add_argument("--output-root", default="artifacts/evaluations")
    verify_parser.set_defaults(handler=_verify_artifacts_command)

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
    except (ARC3Error, ValueError) as error:
        print(f"arc3: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
