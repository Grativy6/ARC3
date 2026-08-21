"""Compact statistical summaries, controlled comparisons, and Markdown rendering."""

from __future__ import annotations

import statistics
from collections import defaultdict
from itertools import combinations
from pathlib import Path
from typing import Any

from arc3.errors import EvaluationError

from .artifacts import load_json, load_jsonl, resolve_evaluation, verify_evaluation_artifacts
from .baselines import BASELINES


def _distribution(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {
            "mean": None,
            "median": None,
            "minimum": None,
            "maximum": None,
            "population_stddev": None,
        }
    return {
        "mean": statistics.fmean(values),
        "median": statistics.median(values),
        "minimum": min(values),
        "maximum": max(values),
        "population_stddev": statistics.pstdev(values),
    }


def build_summary(evaluation_id: str, results: list[dict[str, Any]]) -> dict[str, object]:
    grouped: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for result in results:
        grouped[str(result["agent"])].append(result)
    rows: list[dict[str, object]] = []
    successful_policy_count = 0
    for descriptor in BASELINES:
        policy_results = grouped.get(descriptor.agent, [])
        successes = [result for result in policy_results if result["status"] == "success"]
        failures = [result for result in policy_results if result["status"] != "success"]
        if successes:
            successful_policy_count += 1
        scores = [float(result["score"]["score"]) for result in successes]
        actions = [float(result["metrics"]["environment_actions"]) for result in successes]
        wall = [float(result["metrics"]["total_wall_clock_seconds"]) for result in successes]
        failure_kinds: set[str] = set()
        for result in failures:
            failure = result.get("failure")
            failure_kinds.add(
                str(failure.get("kind", "unknown")) if isinstance(failure, dict) else "unknown"
            )
        rows.append(
            {
                **descriptor.to_dict(),
                "requested_runs": len(policy_results),
                "successful_runs": len(successes),
                "failed_or_unsupported_runs": len(failures),
                "levels_completed": sum(
                    int(result["score"]["levels_completed"]) for result in successes
                ),
                "environment_actions": sum(
                    int(result["metrics"]["environment_actions"]) for result in successes
                ),
                "completion_rate": (
                    sum(bool(result["score"]["completed"]) for result in successes) / len(successes)
                    if successes
                    else None
                ),
                "score_distribution": _distribution(scores),
                "action_distribution": _distribution(actions),
                "wall_clock_distribution": _distribution(wall),
                "failure_kinds": sorted(failure_kinds),
            }
        )
    failure_count = sum(result["status"] != "success" for result in results)
    if successful_policy_count < 2:
        status = "FAILED_INFRASTRUCTURE"
    elif failure_count:
        status = "PARTIAL"
    else:
        status = "PASS"
    return {
        "schema": "arc3.evaluation.summary.v0.1",
        "evaluation_id": evaluation_id,
        "status": status,
        "surface": "synthetic",
        "claim": "NO_GENERALIZATION_CLAIM",
        "successful_policy_count": successful_policy_count,
        "result_count": len(results),
        "failure_count": failure_count,
        "policies": rows,
        "limitations": [
            "Synthetic results do not establish public or hidden-game generalization.",
            "Official RHAE remains null unless the scorecard identifies raw RHAE semantics.",
            "Peak memory is Python traced allocation, not whole-process resident memory.",
        ],
    }


def render_markdown(
    manifest: dict[str, Any], summary: dict[str, Any], results: list[dict[str, Any]]
) -> str:
    seeds = ", ".join(str(item) for item in manifest["seeds"])
    lines = [
        f"# Evaluation {summary['evaluation_id']}",
        "",
        f"Status: **{summary['status']}** - `NO_GENERALIZATION_CLAIM`",
        "",
        f"Surface: `synthetic`; partition: `{manifest['partition']}`; scorer values are adapter-provided.",
        "",
        "## Reproducibility envelope",
        "",
        f"- Git commit: `{manifest['git_commit']}`",
        f"- First-party source hash: `{manifest['first_party_source_hash']}`",
        f"- Configuration hash: `{manifest['config_hash']}`",
        f"- Upstream lock hash: `{manifest['upstream_lock_hash']}`",
        f"- Public partition manifest hash: `{manifest['public_partition_manifest_hash']}`",
        f"- Seeds: `{seeds}`",
        f"- Action/reset budgets: `{manifest['action_budget']}` / `{manifest['budgets']['maximum_resets']}`",
        f"- Per-run wall-clock budget: `{manifest['wall_clock_budget_seconds']}` seconds",
        f"- Runtime: Python `{manifest['python_version']}` on `{manifest['platform']}`",
        f"- Network mode: `{manifest['network_mode']}`",
        f"- Started/completed: `{manifest['started_at']}` / `{manifest['completed_at']}`",
        "",
        "## Policy comparison",
        "",
        "| policy | status | runs | completed | actions | mean score | mean wall s | notes |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in summary["policies"]:
        score = row["score_distribution"]["mean"]
        wall = row["wall_clock_distribution"]["mean"]
        if row["requested_runs"] == 0:
            notes = "not requested"
        else:
            notes = row["limitation"] or "bounded synthetic measurement"
        lines.append(
            "| {baseline_id} {agent} | {status} | {successful_runs}/{requested_runs} | {levels_completed} | {environment_actions} | {score} | {wall} | {notes} |".format(
                **row,
                score="n/a" if score is None else f"{score:.6f}",
                wall="n/a" if wall is None else f"{wall:.6f}",
                notes=notes.replace("|", "/"),
            )
        )
    lines.extend(
        [
            "",
            "## Raw results",
            "",
            "| agent | seed | status | completed | actions | score | trace events | failure |",
            "|---|---:|---|---:|---:|---:|---:|---|",
        ]
    )
    for result in results:
        failure = result.get("failure") or {}
        trace = result.get("trace") or {}
        lines.append(
            f"| {result['agent']} | {result['seed']} | {result['status']} | "
            f"{result['score']['levels_completed']} | {result['metrics']['environment_actions']} | "
            f"{result['score']['score']} | {trace.get('event_count', 0)} | "
            f"{failure.get('kind', '')} |"
        )
    lines.extend(["", "## Failures and limitations", ""])
    failures = [result for result in results if result["status"] != "success"]
    if failures:
        for result in failures:
            failure = result.get("failure") or {}
            lines.append(
                f"- `{result['run_id']}`: `{failure.get('kind', 'unknown')}` - "
                f"{failure.get('message', 'no message')}"
            )
    else:
        lines.append("- No terminal run failures were observed.")
    hashes = manifest.get("artifact_hashes", {})
    retained_attempts: set[str] = set()
    if isinstance(hashes, dict):
        for relative in hashes:
            if not isinstance(relative, str) or not relative.startswith("failures/"):
                continue
            parts = relative.split("/")
            if len(parts) >= 3 and parts[1] in {"traces", "checkpoints"}:
                retained_attempts.add("/".join(parts[:3]))
            elif ".invalid-" in parts[-1]:
                retained_attempts.add(relative)
    if retained_attempts:
        lines.append("- Retained invalid/interrupted attempt evidence (sealed, never promoted):")
        lines.extend(f"  - `{relative}`" for relative in sorted(retained_attempts))
    for limitation in summary["limitations"]:
        lines.append(f"- {limitation}")
    regression = summary.get("performance_regression")
    if isinstance(regression, dict):
        lines.extend(
            [
                "",
                "## Performance regression",
                "",
                f"Pinned synthetic threshold status: **{regression['status']}**.",
                f"Scope: {regression['scope_note']}",
            ]
        )
    lines.extend(["", "## Sealed artifact hashes", ""])
    if isinstance(hashes, dict):
        for relative, digest in sorted(hashes.items()):
            if relative == "report.md" or relative.startswith(("c/", "t/")):
                continue
            lines.append(f"- `{relative}`: `{digest}`")
    lines.extend(
        [
            "",
            "The report's own hash and the complete closed artifact set are sealed in `manifest.json`.",
            "",
            "## Reproduction",
            "",
            "Use the argv array in `reproduce.json` or the platform-quoted `reproduce.txt` command.",
            "",
        ]
    )
    return "\n".join(lines)


def load_results(directory: Path) -> list[dict[str, Any]]:
    return load_jsonl(directory / "results.jsonl")


def _comparison_identity(manifest: dict[str, Any]) -> dict[str, object]:
    budgets = manifest.get("budgets")
    budget_map = budgets if isinstance(budgets, dict) else {}
    return {
        "surface": manifest.get("surface"),
        "partition": manifest.get("partition"),
        "games": manifest.get("games"),
        "seeds": manifest.get("seeds"),
        "action_budget": manifest.get("action_budget"),
        "maximum_resets": budget_map.get("maximum_resets"),
        "wall_clock_budget_seconds": manifest.get("wall_clock_budget_seconds"),
        "network_mode": manifest.get("network_mode"),
        "python_version": manifest.get("python_version"),
        "platform": manifest.get("platform"),
        "hardware": manifest.get("hardware"),
        "scorer_source_version": manifest.get("scorer_source_version"),
        "human_baselines_available": manifest.get("human_baselines_available"),
        "performance_threshold_hash": manifest.get("performance_threshold_hash"),
        "upstream_lock_hash": manifest.get("upstream_lock_hash"),
        "public_partition_manifest_hash": manifest.get("public_partition_manifest_hash"),
    }


def _paired_observations(
    left_results: list[dict[str, Any]],
    right_results: list[dict[str, Any]],
    *,
    left_evaluation: str,
    right_evaluation: str,
) -> list[dict[str, object]]:
    left_by_agent_seed = {
        (str(result["agent"]), int(result["seed"])): result
        for result in left_results
        if result["status"] == "success"
    }
    right_by_agent_seed = {
        (str(result["agent"]), int(result["seed"])): result
        for result in right_results
        if result["status"] == "success"
    }
    pairs: list[dict[str, object]] = []
    for left_agent in sorted({agent for agent, _seed in left_by_agent_seed}):
        for right_agent in sorted({agent for agent, _seed in right_by_agent_seed}):
            if left_evaluation == right_evaluation and left_agent >= right_agent:
                continue
            shared_seeds = sorted(
                seed
                for agent, seed in left_by_agent_seed
                if agent == left_agent and (right_agent, seed) in right_by_agent_seed
            )
            observations = [
                {
                    "seed": seed,
                    "score_delta_left_minus_right": float(
                        left_by_agent_seed[(left_agent, seed)]["score"]["score"]
                    )
                    - float(right_by_agent_seed[(right_agent, seed)]["score"]["score"]),
                    "action_delta_left_minus_right": int(
                        left_by_agent_seed[(left_agent, seed)]["metrics"]["environment_actions"]
                    )
                    - int(
                        right_by_agent_seed[(right_agent, seed)]["metrics"]["environment_actions"]
                    ),
                }
                for seed in shared_seeds
            ]
            if not observations:
                continue
            pairs.append(
                {
                    "left_evaluation_id": left_evaluation,
                    "right_evaluation_id": right_evaluation,
                    "left_agent": left_agent,
                    "right_agent": right_agent,
                    "shared_seeds": shared_seeds,
                    "observations": observations,
                    "mean_score_delta_left_minus_right": statistics.fmean(
                        float(item["score_delta_left_minus_right"]) for item in observations
                    ),
                    "mean_action_delta_left_minus_right": statistics.fmean(
                        float(item["action_delta_left_minus_right"]) for item in observations
                    ),
                }
            )
    return pairs


def compare_evaluations(
    values: list[str | Path], *, output_root: Path = Path("artifacts/evaluations")
) -> dict[str, object]:
    if not values:
        raise EvaluationError("at least one evaluation is required")
    evaluations: list[tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]] = []
    for value in values:
        directory = resolve_evaluation(value, output_root=output_root)
        verification = verify_evaluation_artifacts(directory)
        if not verification["verified"]:
            raw_errors = verification.get("errors")
            error_items = raw_errors if isinstance(raw_errors, list) else [raw_errors]
            details = "; ".join(str(item) for item in error_items)
            raise EvaluationError(f"evaluation {value!s} is not sealed: {details}")
        evaluations.append(
            (
                load_json(directory / "manifest.json"),
                load_json(directory / "summary.json"),
                load_results(directory),
            )
        )
    comparison_identity = _comparison_identity(evaluations[0][0])
    for manifest, _summary, _results in evaluations[1:]:
        candidate = _comparison_identity(manifest)
        if candidate != comparison_identity:
            differing = sorted(
                key for key in comparison_identity if comparison_identity[key] != candidate[key]
            )
            raise EvaluationError(
                f"evaluations are not controlled-comparable; differing fields: {differing}"
            )
    rows: list[dict[str, object]] = []
    for _manifest, evaluation, _results in evaluations:
        for policy in evaluation["policies"]:
            rows.append(
                {
                    "evaluation_id": evaluation["evaluation_id"],
                    "baseline_id": policy["baseline_id"],
                    "agent": policy["agent"],
                    "successful_runs": policy["successful_runs"],
                    "requested_runs": policy["requested_runs"],
                    "failed_or_unsupported_runs": policy["failed_or_unsupported_runs"],
                    "levels_completed": policy["levels_completed"],
                    "environment_actions": policy["environment_actions"],
                    "mean_score": policy["score_distribution"]["mean"],
                    "mean_wall_clock_seconds": policy["wall_clock_distribution"]["mean"],
                    "status": policy["status"],
                }
            )
    paired_differences: list[dict[str, object]] = []
    if len(evaluations) == 1:
        manifest, _summary, results = evaluations[0]
        paired_differences.extend(
            _paired_observations(
                results,
                results,
                left_evaluation=str(manifest["evaluation_id"]),
                right_evaluation=str(manifest["evaluation_id"]),
            )
        )
    else:
        for left, right in combinations(evaluations, 2):
            paired_differences.extend(
                _paired_observations(
                    left[2],
                    right[2],
                    left_evaluation=str(left[0]["evaluation_id"]),
                    right_evaluation=str(right[0]["evaluation_id"]),
                )
            )
    return {
        "schema": "arc3.evaluation.comparison.v0.1",
        "evaluation_ids": [item[1]["evaluation_id"] for item in evaluations],
        "surface": "synthetic",
        "claim": "NO_GENERALIZATION_CLAIM",
        "controlled_comparison": True,
        "comparison_identity": comparison_identity,
        "treatments": [
            {
                "evaluation_id": manifest["evaluation_id"],
                "git_commit": manifest.get("git_commit"),
                "first_party_source_hash": manifest.get("first_party_source_hash"),
                "config_hash": manifest.get("config_hash"),
                "agents": manifest.get("agent_config", {}).get("agents"),
            }
            for manifest, _summary, _results in evaluations
        ],
        "rows": rows,
        "paired_differences": paired_differences,
    }


__all__ = ["build_summary", "compare_evaluations", "load_results", "render_markdown"]
