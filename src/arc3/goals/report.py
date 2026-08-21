"""Concise, source-linked, non-anthropomorphic goal reports."""

from __future__ import annotations

from arc3.types import JSONValue

from .models import GoalRecord, GoalSelection


def structured_goal_report(
    records: tuple[GoalRecord, ...], selection: GoalSelection | None = None
) -> dict[str, JSONValue]:
    """Return a compact derived view; source event IDs remain explicit."""

    ordered = tuple(sorted(records, key=lambda item: (-item.rank, item.candidate.goal_id)))
    selected: dict[str, JSONValue] | None = None
    if selection is not None:
        selected = {
            "goal_id": selection.goal_id,
            "action": selection.action.name.value if selection.action else None,
            "coordinate": (
                [selection.action.coordinate.x, selection.action.coordinate.y]
                if selection.action and selection.action.coordinate
                else None
            ),
            "desirability_rank": selection.desirability_rank,
            "reachability_rank": selection.reachability_rank,
            "exploration_utility": selection.exploration_utility,
            "novelty_suppressed": selection.novelty_suppressed,
            "rationale": selection.rationale,
        }
    return {
        "schema": "arc3.goal.report.v1",
        "weight_kind": "uncalibrated_rank",
        "selected": selected,
        "candidates": [
            {
                "goal_id": record.candidate.goal_id,
                "kind": record.candidate.kind.value,
                "role": record.candidate.role.value,
                "scope": record.candidate.scope.value,
                "scope_ref": record.candidate.scope_ref,
                "target_state": record.candidate.target_state,
                "status": record.status.value,
                "rank": record.rank,
                "support_levels": list(record.support_levels),
                "contradictions": record.contradiction_count,
                "reopens": record.reopen_count,
                "source_event_ids": list(record.source_event_ids),
            }
            for record in ordered
        ],
    }


def render_goal_report(
    records: tuple[GoalRecord, ...], selection: GoalSelection | None = None
) -> str:
    """Render terse mechanism language without simulated mental states."""

    report = structured_goal_report(records, selection)
    lines = ["Goal acquisition report", "rank_kind=uncalibrated_rank"]
    if selection is None:
        lines.append("selection=none")
    else:
        lines.append(
            "selection="
            f"{selection.goal_id or 'none'}; rationale={selection.rationale}; "
            f"novelty_suppressed={str(selection.novelty_suppressed).lower()}"
        )
    candidates = report["candidates"]
    if isinstance(candidates, list):
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            sources = candidate.get("source_event_ids")
            source_text = (
                ",".join(str(item) for item in sources) if isinstance(sources, list) else ""
            )
            lines.append(
                "candidate="
                f"{candidate.get('goal_id')}; kind={candidate.get('kind')}; "
                f"role={candidate.get('role')}; status={candidate.get('status')}; "
                f"rank={candidate.get('rank')}; sources={source_text}"
            )
    return "\n".join(lines)


__all__ = ["render_goal_report", "structured_goal_report"]
