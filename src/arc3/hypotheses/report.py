"""Structured and human-readable views derived from hypothesis state."""

from __future__ import annotations

from typing import cast

from arc3.types import HypothesisStatus, JSONValue

from .registry import HypothesisRecord, HypothesisRegistry


def structured_hypothesis_report(
    registry: HypothesisRegistry, *, include_rejected: bool = True
) -> dict[str, JSONValue]:
    """Build a deterministic report containing pointers, not narrative authority."""

    records = [
        record
        for record in registry.ranked(include_rejected=include_rejected)
        if include_rejected or record.status is not HypothesisStatus.REJECTED
    ]
    status_counts: dict[str, int] = {}
    for record in records:
        status_counts[record.status.value] = status_counts.get(record.status.value, 0) + 1
    return {
        "schema": "arc3.hypothesis.report.v0.1",
        "weight_semantics": "uncalibrated deterministic rank; not probability or proof",
        "record_count": len(records),
        "status_counts": dict(sorted(status_counts.items())),
        "records": [_report_record(record) for record in records],
        "invalidations": [signal.to_dict() for signal in registry.invalidations],
    }


def render_hypothesis_report(registry: HypothesisRegistry, *, include_rejected: bool = True) -> str:
    """Render concise Markdown solely from structured registry fields."""

    report = structured_hypothesis_report(registry, include_rejected=include_rejected)
    lines = [
        "# Hypothesis registry",
        "",
        "Weights are uncalibrated deterministic ranking aids, not probabilities or proof.",
        "",
        f"Records: {report['record_count']}",
        "",
    ]
    records = report["records"]
    assert isinstance(records, list)
    for raw_record in records:
        assert isinstance(raw_record, dict)
        identifier = raw_record["hypothesis_id"]
        family = raw_record["family"]
        status = raw_record["status"]
        lines.extend(
            [
                f"## {identifier}",
                "",
                f"- Family: `{family}`",
                f"- Status: `{status}`",
                f"- Scope: `{raw_record['scope']}`",
                f"- Rank weight: {raw_record['rank_weight']} (uncalibrated)",
                f"- Support receipts: {raw_record['support_count']}",
                f"- Contradiction receipts: {raw_record['contradiction_count']}",
                f"- Residual receipts: {raw_record['residual_count']}",
                f"- Parents: {_display_ids(raw_record['parent_ids'])}",
                f"- Narrowed forms: {_display_ids(raw_record['narrowed_to_ids'])}",
                f"- Superseded by: {raw_record['superseded_by'] or 'none'}",
                f"- Source events: {_display_ids(raw_record['source_event_ids'])}",
                "",
            ]
        )
    invalidations = report["invalidations"]
    assert isinstance(invalidations, list)
    if invalidations:
        lines.extend(["## Plan invalidations", ""])
        for raw_signal in invalidations:
            assert isinstance(raw_signal, dict)
            lines.append(
                f"- {raw_signal['event_id']}: {raw_signal['hypothesis_id']} invalidated "
                f"{_display_ids(raw_signal['plan_ids'])}"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _report_record(record: HypothesisRecord) -> dict[str, JSONValue]:
    return {
        "hypothesis_id": record.hypothesis_id,
        "family": record.family.value,
        "status": record.status.value,
        "scope": record.scope.value,
        "scope_ref": record.scope_ref,
        "rank_weight": record.rank_weight,
        "statement": record.statement.to_dict(),
        "support_count": len(record.support_receipts),
        "contradiction_count": len(record.contradiction_receipts),
        "residual_count": len(record.residual_receipts),
        "parent_ids": list(record.parent_ids),
        "narrowed_to_ids": list(record.narrowed_to_ids),
        "superseded_by": record.superseded_by,
        "source_event_ids": cast(
            list[JSONValue],
            sorted(
                {
                    *record.created_from_event_ids,
                    *record.support_event_ids,
                    *record.contradiction_event_ids,
                    *record.residual_event_ids,
                }
            ),
        ),
        "last_tested_step": record.last_tested_step,
        "version": record.version,
    }


def _display_ids(value: JSONValue) -> str:
    if not isinstance(value, list) or not value:
        return "none"
    return ", ".join(f"`{item}`" for item in value)
