"""JSONL bridge to the exact Build 002 policy checkout.

The module imports no ARC3 code until the caller-provided, commit-verified
source root is placed first on ``sys.path``.  It never imports evaluator
generation, engine, rule, truth, or oracle modules.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any, cast

EXPECTED_COMMIT = "753b0e007222a973a2c8a6d7ce14a395135d3c5f"
EXPECTED_TREE = "d07e72716a1f918ed04a6892adb1e3f46259e345"


def _git(source_root: Path, *arguments: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(source_root), *arguments],
        text=True,
        encoding="utf-8",
        stderr=subprocess.STDOUT,
    ).strip()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--storage-root", type=Path, required=True)
    return parser


def _emit(value: object) -> None:
    print(json.dumps(value, sort_keys=True, separators=(",", ":")), flush=True)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    source_root = args.source_root.resolve()
    commit = _git(source_root, "rev-parse", "HEAD")
    tree = _git(source_root, "show", "-s", "--format=%T", "HEAD")
    if commit != EXPECTED_COMMIT or tree != EXPECTED_TREE:
        raise SystemExit("Build 002 source identity mismatch")
    sys.path.insert(0, str(source_root / "src"))

    from arc3.adapters import GridFrame, Observation
    from arc3.competition_runtime import FROZEN_COMPETITION_RUNTIME
    from arc3.config import ARC3Config
    from arc3.policy.controller import ARC3Controller
    from arc3.policy.models import ControllerPreset, RunContext
    from arc3.types import (
        ActionName,
        ActionRequest,
        Coordinate,
        EnvironmentMode,
        ExecutionMode,
        GameId,
        GameStateName,
    )

    def action_from(value: dict[str, object] | None) -> ActionRequest | None:
        if value is None:
            return None
        name = ActionName(str(value["name"]))
        raw_coordinate = value.get("coordinate")
        coordinate = None
        if isinstance(raw_coordinate, dict):
            coordinate = Coordinate(int(raw_coordinate["x"]), int(raw_coordinate["y"]))
        return ActionRequest(name, coordinate)

    def action_to(action: ActionRequest) -> dict[str, object]:
        coordinate = action.coordinate
        return {
            "name": action.name.value,
            "coordinate": (None if coordinate is None else {"x": coordinate.x, "y": coordinate.y}),
        }

    def observation_from(value: dict[str, object]) -> Observation:
        raw = cast(dict[str, Any], value)
        return Observation(
            game_id=GameId(str(raw["game_id"])),
            frames=tuple(GridFrame.from_rows(frame) for frame in raw["frames"]),
            state=GameStateName(str(raw["state"])),
            levels_completed=int(raw["levels_completed"]),
            win_levels=int(raw["win_levels"]),
            available_actions=tuple(
                ActionName(str(item)) for item in raw["available_actions"]
            ),
            full_reset=bool(raw["full_reset"]),
            returned_action=action_from(raw.get("returned_action")),
            upstream_metadata=tuple(
                (str(item[0]), item[1]) for item in raw["metadata"]
            ),
        )

    storage_root = args.storage_root.resolve()
    storage_root.mkdir(parents=True, exist_ok=True)
    controller: ARC3Controller | None = None
    pending_level: int | None = None
    pending_action: ActionRequest | None = None
    levels: list[dict[str, Any]] = [
        {
            "environment_actions": 0,
            "resets": 0,
            "exploratory_actions": 0,
            "progress_actions": 0,
            "redundant_probes": 0,
            "actions_to_stable": None,
            "movement_prediction_errors": 0,
            "resource_prediction_errors": 0,
            "access_prediction_errors": 0,
            "hazard_prediction_errors": 0,
            "residuals_observed": 0,
            "residuals_localized": 0,
            "residuals_resolved": 0,
            "base_mechanics_retained": False,
            "erroneous_global_reopenings": 0,
            "unresolved_ledger_count": 0,
            "active_ledger_pressure": 0,
            "receipt_count": 0,
            "complete_receipt_count": 0,
            "completed": False,
        }
        for _ in range(10)
    ]
    repetitions: Counter[tuple[int, str, str]] = Counter()

    def close_controller() -> None:
        nonlocal controller
        if controller is not None:
            controller.close()
            controller = None

    def initialize(observation: Observation) -> None:
        nonlocal controller
        close_controller()
        trace_root = (
            storage_root / f"attempt-{dict(observation.upstream_metadata).get('attempt', 0)}"
        )
        checkpoint_root = trace_root / "checkpoints"
        config = ARC3Config(
            mode=EnvironmentMode.COMPETITION,
            execution_mode=ExecutionMode.COMPETITION_BOUNDED,
            seed=20260824,
            network_enabled=False,
            artifact_root=str(storage_root / "artifacts"),
            trace_root=str(trace_root),
            budgets=FROZEN_COMPETITION_RUNTIME.budgets(),
            runtime_policy=FROZEN_COMPETITION_RUNTIME.runtime_policy(),
        )
        controller = ARC3Controller(ControllerPreset.COMPETITION)
        controller.reset(
            RunContext(
                run_id=f"build003-{observation.game_id}",
                episode_id=f"attempt-{dict(observation.upstream_metadata).get('attempt', 0)}",
                game_id=str(observation.game_id),
                trace_root=trace_root,
                checkpoint_root=checkpoint_root,
                config=config,
                git_commit=commit,
                source_kind="build003-synthetic-observation",
                source_version="build002-frozen-753b0e0",
            )
        )
        controller.observe(observation)

    def consume(observation: Observation) -> None:
        nonlocal pending_action, pending_level
        if observation.full_reset or controller is None:
            initialize(observation)
            pending_action = None
            pending_level = None
            return
        if pending_action is None or pending_level is None:
            return
        receipt = controller.apply_consequence(observation)
        metric = levels[pending_level]
        metric["receipt_count"] += 1
        metric["complete_receipt_count"] += 1
        if receipt.matched_prediction is False:
            metric["residuals_observed"] += 1
            metric["residuals_localized"] += 1
        if receipt.reopened_model_ids:
            metric["residuals_resolved"] += 1
            metric["erroneous_global_reopenings"] += len(receipt.reopened_model_ids)
        metric["completed"] = bool(
            observation.levels_completed > pending_level or observation.state is GameStateName.WIN
        )
        snapshot = controller.snapshot
        pressure = len(snapshot.active_hypothesis_ids) + len(snapshot.active_world_model_ids)
        metric["active_ledger_pressure"] = max(metric["active_ledger_pressure"], pressure)
        metric["unresolved_ledger_count"] = max(
            metric["unresolved_ledger_count"], len(snapshot.active_hypothesis_ids)
        )
        if observation.levels_completed > pending_level:
            metric["base_mechanics_retained"] = bool(snapshot.active_world_model_ids)
        pending_action = None
        pending_level = None

    def summary(observation: Observation) -> dict[str, object]:
        return {
            "schema": "arc3.build003.worker-summary.v0.1",
            "variant": "BUILD002_FROZEN",
            "levels": levels,
            "receipt_count": sum(int(item["receipt_count"]) for item in levels),
            "receipt_digest": "sha256:" + "0" * 64,
            "final_state": observation.state.value,
            "levels_completed": observation.levels_completed,
            "win_levels": observation.win_levels,
            "source_commit": commit,
            "source_tree": tree,
            "arc3_file": str(sys.modules["arc3"].__file__),
        }

    _emit(
        {
            "schema": "arc3.build003.frozen-build002-ready.v0.1",
            "source_commit": commit,
            "source_tree": tree,
            "arc3_file": str(sys.modules["arc3"].__file__),
        }
    )
    try:
        for line in sys.stdin:
            try:
                request = json.loads(line)
                observation = observation_from(request["observation"])
                command = request["command"]
                consume(observation)
                if command == "finalize":
                    _emit(summary(observation))
                    continue
                if observation.state is GameStateName.GAME_OVER:
                    level = min(observation.levels_completed, 9)
                    levels[level]["resets"] += 1
                    levels[level]["receipt_count"] += 1
                    levels[level]["complete_receipt_count"] += 1
                    action = ActionRequest(ActionName.RESET)
                    _emit(
                        {
                            "schema": "arc3.build003.frozen-build002-action.v0.1",
                            "action": action_to(action),
                            "rationale": "mandatory_reset",
                        }
                    )
                    continue
                if observation.state is GameStateName.WIN:
                    raise RuntimeError("WIN is terminal")
                if controller is None:
                    raise RuntimeError("controller initialization failed")
                decision = controller.choose_action()
                action = decision.action
                level = min(observation.levels_completed, 9)
                metric = levels[level]
                metric["environment_actions"] += 1
                rationale = decision.rationale_category.value
                if rationale == "follow_plan":
                    metric["progress_actions"] += 1
                else:
                    metric["exploratory_actions"] += 1
                signature = (level, str(observation.frames[-1].digest), action.name.value)
                repetitions[signature] += 1
                if repetitions[signature] > 1:
                    metric["redundant_probes"] += 1
                pending_level = level
                pending_action = action
                _emit(
                    {
                        "schema": "arc3.build003.frozen-build002-action.v0.1",
                        "action": action_to(action),
                        "rationale": rationale,
                    }
                )
            except Exception as error:  # preserve bounded policy failure as data
                _emit(
                    {
                        "schema": "arc3.build003.frozen-build002-error.v0.1",
                        "error_type": type(error).__name__,
                        "message": str(error),
                    }
                )
    finally:
        close_controller()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
