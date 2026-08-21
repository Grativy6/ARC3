"""Measure the integrated controller against the deterministic action cycle.

The output is a machine-readable synthetic result.  Both policies receive the
same seeds, environment parameters, and environment-action budget.  Internal
controller trace/checkpoint work is not counted as an environment action.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import tempfile
import time
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import cast

from arc3.adapters.synthetic import SYNTHETIC_GAME_ID, SyntheticAdapter
from arc3.config import ARC3Config, BudgetConfig
from arc3.policy import ARC3Controller, ControllerPhase, ControllerPreset, RunContext
from arc3.policy.baselines import ActionCyclePolicy
from arc3.trace import EventJournal, TraceEvent, verify_event_chain
from arc3.trace.canonical import sha256_json
from arc3.types import EnvironmentMode, GameStateName, JSONValue

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SEED_COUNT = 32
DEFAULT_ACTION_BUDGET = 16
DEFAULT_GRID_SIZE = 8
DEFAULT_MAX_STEPS = 32


@dataclass(frozen=True, slots=True)
class EpisodeMeasurement:
    """Exact per-episode result used in the aggregate scorecard."""

    seed: int
    completed: bool
    actions: int
    final_state: str
    trace_events: int = 0
    submitted_receipts: int = 0
    consequence_receipts: int = 0
    complete_action_chains: int = 0
    checkpoint_artifact_present: bool = False
    checkpoint_restore_verified: bool = False
    restore_event_duplication_count: int = 0
    controller_faults: int = 0
    hash_chain_verified: bool = False
    trace_tail_hash: str | None = None


def _git_value(*arguments: str) -> str:
    completed = subprocess.run(
        ("git", *arguments),
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return completed.stdout.strip() if completed.returncode == 0 else "unavailable"


def _package_version(package: str) -> str:
    try:
        return version(package)
    except PackageNotFoundError:
        return "not-installed"


def _complete_action_chains(events: tuple[TraceEvent, ...]) -> int:
    """Count decisions with ordered selection, validation, submit, and consequence."""

    positions = {event.event_id: index for index, event in enumerate(events)}
    by_id = {event.event_id: event for event in events}
    consequences = {
        submitted_id: event
        for event in events
        if event.event_type == "consequence.received"
        and isinstance((submitted_id := event.payload.get("submitted_event_id")), str)
    }
    complete = 0
    for submitted in (event for event in events if event.event_type == "action.submitted"):
        selected_id = submitted.payload.get("selected_event_id")
        validated_id = submitted.payload.get("validated_event_id")
        if not isinstance(selected_id, str) or not isinstance(validated_id, str):
            continue
        selected = by_id.get(selected_id)
        validated = by_id.get(validated_id)
        consequence = consequences.get(submitted.event_id)
        if selected is None or validated is None or consequence is None:
            continue
        source_observation = selected.payload.get("source_observation_event_id")
        if not isinstance(source_observation, str) or source_observation not in positions:
            continue
        if not (
            positions[source_observation]
            < positions[selected_id]
            < positions[validated_id]
            < positions[submitted.event_id]
            < positions[consequence.event_id]
        ):
            continue
        complete += 1
    return complete


def _controller_context(
    root: Path,
    *,
    seed: int,
    action_budget: int,
    preset: ControllerPreset,
) -> RunContext:
    mode = (
        EnvironmentMode.COMPETITION
        if preset is ControllerPreset.COMPETITION
        else EnvironmentMode.SYNTHETIC
    )
    label = preset.value
    config = ARC3Config(
        mode=mode,
        seed=seed,
        network_enabled=False,
        profile=f"stage12-measurement-{label}",
        budgets=BudgetConfig(max_actions=action_budget, max_search_nodes=2_048),
    )
    return RunContext(
        run_id=f"stage12-{label}-{seed}",
        episode_id=f"stage12-{label}-episode-{seed}",
        game_id=SYNTHETIC_GAME_ID,
        trace_root=root / label / str(seed) / "trace",
        checkpoint_root=root / label / str(seed) / "checkpoint",
        config=config,
        git_commit=_git_value("rev-parse", "HEAD"),
        source_kind="stage12-controller-measurement",
        source_version="0.1",
    )


def _run_controller(
    root: Path,
    *,
    seed: int,
    action_budget: int,
    grid_size: int,
    max_steps: int,
    preset: ControllerPreset,
) -> EpisodeMeasurement:
    session = SyntheticAdapter(seed=seed, size=grid_size, max_steps=max_steps).open(
        SYNTHETIC_GAME_ID
    )
    controller = ARC3Controller(preset)
    context = _controller_context(root, seed=seed, action_budget=action_budget, preset=preset)
    controller.reset(context)
    controller.observe(session.observation)
    actions = 0
    while controller.phase not in {ControllerPhase.COMPLETE, ControllerPhase.GAME_OVER}:
        if actions >= action_budget:
            break
        decision = controller.choose_action()
        returned = session.step(decision.action)
        controller.apply_consequence(returned)
        actions += 1
    completed = session.observation.state is GameStateName.WIN
    final_state = session.observation.state.value
    expected = controller.snapshot
    expected_closed_event_count = expected.trace_events + (
        0 if expected.phase is ControllerPhase.AWAITING_CONSEQUENCE else 1
    )
    controller.close()
    checkpoint_path = context.checkpoint_root / "latest.json"

    restored = ARC3Controller.restore(context, preset=preset, checkpoint_path=checkpoint_path)
    events_before_restore = restored.journal.verify_manifest()
    verify_event_chain(list(events_before_restore))
    actual = restored.snapshot
    checkpoint_restore_verified = (
        actual.phase is expected.phase
        and actual.step_index == expected.step_index
        and actual.level_index == expected.level_index
        and actual.actions_used == expected.actions_used
        and actual.resets_used == expected.resets_used
        and actual.pending_action == expected.pending_action
        and actual.active_hypothesis_ids == expected.active_hypothesis_ids
        and actual.active_world_model_ids == expected.active_world_model_ids
        and actual.active_goal_ids == expected.active_goal_ids
        and actual.fault_count == expected.fault_count
        and len(events_before_restore) == expected_closed_event_count
    )
    restored.close()
    auditor = EventJournal(context.trace_root, run_id=context.run_id)
    events = auditor.verify_manifest()
    verify_event_chain(list(events))
    auditor.close()
    restore_event_duplication_count = len(events) - len(events_before_restore)
    counts = Counter(event.event_type for event in events)
    measurement = EpisodeMeasurement(
        seed=seed,
        completed=completed,
        actions=actions,
        final_state=final_state,
        trace_events=len(events),
        submitted_receipts=counts["action.submitted"],
        consequence_receipts=counts["consequence.received"],
        complete_action_chains=_complete_action_chains(events),
        checkpoint_artifact_present=checkpoint_path.is_file(),
        checkpoint_restore_verified=checkpoint_restore_verified,
        restore_event_duplication_count=restore_event_duplication_count,
        controller_faults=expected.fault_count,
        hash_chain_verified=True,
        trace_tail_hash=events[-1].event_hash,
    )
    return measurement


def _run_cycle(
    *, seed: int, action_budget: int, grid_size: int, max_steps: int
) -> EpisodeMeasurement:
    session = SyntheticAdapter(seed=seed, size=grid_size, max_steps=max_steps).open(
        SYNTHETIC_GAME_ID
    )
    policy = ActionCyclePolicy()
    actions = 0
    while session.observation.state not in {GameStateName.WIN, GameStateName.GAME_OVER}:
        if actions >= action_budget:
            break
        session.step(policy.select(session.observation))
        actions += 1
    return EpisodeMeasurement(
        seed=seed,
        completed=session.observation.state is GameStateName.WIN,
        actions=actions,
        final_state=session.observation.state.value,
    )


def _aggregate(episodes: list[EpisodeMeasurement]) -> dict[str, JSONValue]:
    completed = sum(item.completed for item in episodes)
    total_actions = sum(item.actions for item in episodes)
    completed_actions = sum(item.actions for item in episodes if item.completed)
    submitted = sum(item.submitted_receipts for item in episodes)
    consequences = sum(item.consequence_receipts for item in episodes)
    chains = sum(item.complete_action_chains for item in episodes)
    return {
        "episodes": len(episodes),
        "completed": completed,
        "completion_rate": completed / len(episodes),
        "total_actions": total_actions,
        "mean_actions_all": total_actions / len(episodes),
        "mean_actions_completed": (completed_actions / completed if completed else None),
        "trace_events": sum(item.trace_events for item in episodes),
        "submitted_receipts": submitted,
        "consequence_receipts": consequences,
        "complete_action_chains": chains,
        "all_submissions_have_consequences": submitted == consequences,
        "all_actions_have_complete_chains": submitted == chains,
        "checkpoint_artifacts_present": sum(item.checkpoint_artifact_present for item in episodes),
        "all_checkpoint_artifacts_present": all(
            item.checkpoint_artifact_present for item in episodes
        ),
        "checkpoint_restores_verified": sum(item.checkpoint_restore_verified for item in episodes),
        "all_checkpoint_restores_verified": all(
            item.checkpoint_restore_verified for item in episodes
        ),
        "restore_event_duplication_count": sum(
            item.restore_event_duplication_count for item in episodes
        ),
        "zero_restore_event_duplication": all(
            item.restore_event_duplication_count == 0 for item in episodes
        ),
        "controller_faults": sum(item.controller_faults for item in episodes),
        "hash_chains_verified": all(item.hash_chain_verified for item in episodes),
        "per_seed": [cast(JSONValue, asdict(item)) for item in episodes],
    }


def _production_static_status() -> dict[str, JSONValue]:
    manifest_raw = json.loads(
        (ROOT / "docs" / "evaluation" / "public-game-partitions.v0.1.json").read_text(
            encoding="utf-8"
        )
    )
    manifest = cast(dict[str, object], manifest_raw)
    games = cast(list[dict[str, object]], manifest["games"])
    known_ids = {
        cast(str, item["game_id"]).lower() for item in games if isinstance(item.get("game_id"), str)
    }
    paths = [
        *sorted((ROOT / "src" / "arc3" / "policy").glob("*.py")),
        ROOT / "agent" / "my_agent.py",
    ]
    combined = "\n".join(path.read_text(encoding="utf-8").lower() for path in paths)
    forbidden_network_tokens = (
        "import requests",
        "import httpx",
        "import socket",
        "urllib.request",
        "openai",
        "anthropic",
        "xai",
    )
    wrapper_source = (ROOT / "agent" / "my_agent.py").read_text(encoding="utf-8")
    duplication_markers = ("def _candidate_actions", "def _plan_action", "def _probe_action")
    return {
        "scanned_paths": [path.relative_to(ROOT).as_posix() for path in paths],
        "public_game_id_hits": [
            cast(JSONValue, item) for item in sorted(item for item in known_ids if item in combined)
        ],
        "forbidden_network_token_hits": [
            cast(JSONValue, item)
            for item in sorted(item for item in forbidden_network_tokens if item in combined)
        ],
        "wrapper_constructs_shared_controller": "ARC3Controller(" in wrapper_source,
        "wrapper_policy_duplication_markers": [
            item for item in duplication_markers if item in wrapper_source
        ],
    }


def measure(
    *, seed_count: int, action_budget: int, grid_size: int, max_steps: int
) -> dict[str, object]:
    """Run the bounded measurement and return its complete scorecard."""

    if seed_count <= 0 or action_budget <= 0 or grid_size < 4 or max_steps <= 0:
        raise ValueError("measurement bounds must be positive and grid size must be at least four")
    started = time.perf_counter()
    seeds = list(range(seed_count))
    with tempfile.TemporaryDirectory(prefix="arc3-stage12-measurement-") as raw_root:
        runtime_root = Path(raw_root)
        full = [
            _run_controller(
                runtime_root,
                seed=seed,
                action_budget=action_budget,
                grid_size=grid_size,
                max_steps=max_steps,
                preset=ControllerPreset.FULL,
            )
            for seed in seeds
        ]
        cycle = [
            _run_cycle(
                seed=seed,
                action_budget=action_budget,
                grid_size=grid_size,
                max_steps=max_steps,
            )
            for seed in seeds
        ]
        competition = _run_controller(
            runtime_root,
            seed=7,
            action_budget=action_budget,
            grid_size=grid_size,
            max_steps=max_steps,
            preset=ControllerPreset.COMPETITION,
        )

    full_aggregate = _aggregate(full)
    cycle_aggregate = _aggregate(cycle)
    static_status = _production_static_status()
    comparison: dict[str, JSONValue] = {
        "completion_delta": cast(int, full_aggregate["completed"])
        - cast(int, cycle_aggregate["completed"]),
        "full_completed_more": cast(int, full_aggregate["completed"])
        > cast(int, cycle_aggregate["completed"]),
        "equal_environment_action_budget": True,
    }
    evidence_core: dict[str, JSONValue] = {
        "schema": "arc3.stage12.controller-measurement.v0.1",
        "evaluation_label": "synthetic",
        "environment": {
            "id": SYNTHETIC_GAME_ID,
            "seed_set": [cast(JSONValue, seed) for seed in seeds],
            "grid_size": grid_size,
            "max_steps": max_steps,
            "environment_action_budget": action_budget,
        },
        "full": full_aggregate,
        "baseline_cycle": cycle_aggregate,
        "comparison": comparison,
        "competition_offline_smoke": {
            **cast(dict[str, JSONValue], asdict(competition)),
            "network_enabled": False,
            "preset": ControllerPreset.COMPETITION.value,
        },
        "production_static_status": static_status,
    }
    pass_status = (
        comparison["full_completed_more"] is True
        and cast(int, full_aggregate["controller_faults"]) == 0
        and full_aggregate["hash_chains_verified"] is True
        and full_aggregate["all_actions_have_complete_chains"] is True
        and full_aggregate["all_checkpoint_artifacts_present"] is True
        and full_aggregate["all_checkpoint_restores_verified"] is True
        and full_aggregate["zero_restore_event_duplication"] is True
        and competition.completed
        and competition.checkpoint_artifact_present
        and competition.checkpoint_restore_verified
        and competition.restore_event_duplication_count == 0
        and static_status["public_game_id_hits"] == []
        and static_status["forbidden_network_token_hits"] == []
        and static_status["wrapper_constructs_shared_controller"] is True
        and static_status["wrapper_policy_duplication_markers"] == []
    )
    return {
        **evidence_core,
        "status": "PASS" if pass_status else "FAILED_MECHANISM",
        "evidence_core_hash": sha256_json(evidence_core),
        "measured_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "runtime_seconds": round(time.perf_counter() - started, 6),
        "runtime": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "processor": platform.processor(),
            "logical_cpu_count": os.cpu_count(),
            "packages": {
                "arc3": _package_version("arc3"),
                "numpy": _package_version("numpy"),
                "pydantic": _package_version("pydantic"),
            },
        },
        "repository": {
            "commit": _git_value("rev-parse", "HEAD"),
            "branch": _git_value("branch", "--show-current"),
            "working_tree_dirty": bool(_git_value("status", "--porcelain")),
        },
        "limitations": [
            "synthetic evidence only; it is not public- or hidden-game generalization evidence",
            "the cycle baseline does not emit controller trace receipts",
            "working-tree measurements must be rerun after the final Stage 12 commit",
        ],
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed-count", type=int, default=DEFAULT_SEED_COUNT)
    parser.add_argument("--action-budget", type=int, default=DEFAULT_ACTION_BUDGET)
    parser.add_argument("--grid-size", type=int, default=DEFAULT_GRID_SIZE)
    parser.add_argument("--max-steps", type=int, default=DEFAULT_MAX_STEPS)
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = measure(
        seed_count=args.seed_count,
        action_budget=args.action_budget,
        grid_size=args.grid_size,
        max_steps=args.max_steps,
    )
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8", newline="\n")
    sys.stdout.write(rendered)
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
