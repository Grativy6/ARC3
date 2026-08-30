"""Independent, fail-closed audit of a frozen Build 003 v0.2 matrix.

The auditor reads an already-complete matrix and writes its own evidence into a
different, initially empty directory.  It never imports the curriculum runner
or mutates the source matrix.  Tests may inject fabricated expected cases and a
Build 002 identity probe; the command-line entry point always derives the exact
v0.2 held-out identities and probes the recorded checkout directly.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import cast

from arc3.evaluation.build003_results import (
    FAMILIES,
    RUN_STATUSES,
    VARIANTS,
    Build003ResultLedger,
    CurriculumResultRow,
    FrozenCase,
)
from arc3.mechanics import CHANNEL_ORDER, CompositionMode
from arc3.types import GameStateName

AUDIT_SCHEMA = "arc3.build003.curriculum-matrix-audit.v0.1"
MATRIX_SCHEMA = "arc3.build003.curriculum-matrix-receipt.v0.2"
SEQUENCE_SCHEMA = "arc3.build003.sequence-run.v0.2"
PROTOCOL_VERSION = "v0.2"
PROTOCOL_ID = "arc3.build003.curriculum.v0.2"
PROTOCOL_PATH = "docs/evaluation/build-003-curriculum-protocol.v0.2.json"
MANIFEST_PATH = "docs/evaluation/build-003-heldout-seeds.v0.2.json"
PREREGISTRATION_PATH = "docs/evaluation/build-003-preregistration-amendment.v0.2.json"
BUILD002_COMMIT = "5448c53f3b7e08f606cf292e6068f3f9c9db16d4"
BUILD002_TREE = "700718c09c2a1532cea16526b290f57be0120371"
HELDOUT_DOMAIN = "arc3-build003-curriculum-v0.2-heldout"
CASE_PREFIX = "b003v2-"
EXPECTED_CASES = 30
EXPECTED_SEQUENCES = 120
EXPECTED_ROWS = 1200

EXPECTED_BUDGETS: dict[str, object] = {
    "max_environment_actions": 192,
    "max_environment_actions_per_level": 48,
    "max_resets": 10,
    "max_wall_clock_seconds": 10.0,
    "max_peak_memory_bytes": 1_073_741_824,
    "policy_cycle_seconds": 10.0,
}
EXPECTED_BASELINE = {"commit": BUILD002_COMMIT, "tree": BUILD002_TREE}

_REQUIRED_TOP_LEVEL = {
    "REPORT.md",
    "matrix-receipt.json",
    "rows.jsonl",
    "sequence-receipts.jsonl",
    "worker-storage",
}
_MATRIX_KEYS = {
    "schema",
    "surface",
    "status",
    "status_reason",
    "matrix_structure_status",
    "complete_preregistered_matrix",
    "protocol_version",
    "protocol_id",
    "protocol_path",
    "protocol_sha256",
    "manifest_path",
    "manifest_sha256",
    "preregistration_path",
    "preregistration_sha256",
    "seed_set",
    "case_count",
    "variant_count",
    "sequence_count",
    "row_count",
    "expected_selected_row_count",
    "expected_full_row_count",
    "authoritative_win_sequences",
    "run_status_counts",
    "wall_time_seconds",
    "rows_path",
    "rows_sha256",
    "sequence_receipts_path",
    "sequence_receipts_sha256",
    "worker_storage_root",
    "budgets",
    "build002_baseline_identity",
    "build003_source_identity",
    "build003_source_files",
    "paired_summary",
    "build002_source_root",
    "claim_boundary",
}
_SEQUENCE_KEYS = {
    "schema",
    "surface",
    "protocol_version",
    "protocol_id",
    "protocol_path",
    "manifest_path",
    "budgets",
    "build002_baseline_identity",
    "case_id",
    "seed",
    "variant",
    "run_status",
    "failure_reason",
    "final_state",
    "levels_completed",
    "win_levels",
    "environment_actions",
    "resets",
    "wall_time_seconds",
    "peak_memory_bytes",
    "replay_digest",
    "replay_deterministic",
    "receipt_links_complete",
    "sequence_counts_reconciled",
    "reported_environment_actions",
    "reported_resets",
    "worker_summary",
    "claim_boundary",
}
_ACTION_LINK_KEYS = {
    "step",
    "level_index",
    "action",
    "prediction_id",
    "prediction_digest",
    "before_ref",
    "after_ref",
    "learning_digest",
    "causal_receipt_digest",
    "complete",
}
_ACTION_NAMES = {"ACTION1", "ACTION2", "ACTION3", "ACTION4", "ACTION5", "RESET"}
_LEVEL_REQUIRED_FIELDS = {
    "environment_actions",
    "resets",
    "receipt_count",
    "complete_receipt_count",
    "completed",
}
_LEVEL_BOOLEAN_FIELDS = {"completed", "base_mechanics_retained"}
_LEVEL_NULLABLE_INTEGER_FIELDS = {"actions_to_stable", "erroneous_global_reopenings"}
_LEVEL_COUNTER_FIELDS = {
    "environment_actions",
    "resets",
    "exploratory_actions",
    "progress_actions",
    "redundant_probes",
    "movement_prediction_errors",
    "resource_prediction_errors",
    "resource_discrimination_actions",
    "restoration_ambiguities_resolved",
    "access_prediction_errors",
    "hazard_prediction_errors",
    "residuals_observed",
    "residuals_localized",
    "residuals_resolved",
    "observed_retained_matches",
    "passive_confirmations",
    "transfer_confirmations",
    "local_repair_candidates_opened",
    "local_repairs_confirmed",
    "local_repair_failures",
    "base_reopenings",
    "clef_promotions",
    "clef_parks",
    "clef_stops",
    "other_object_effects_observed",
    "topology_changes_confirmed",
    "delayed_candidates_confirmed",
    "unresolved_ledger_count",
    "active_ledger_pressure",
    "receipt_count",
    "complete_receipt_count",
}
_LEVEL_MAPPING_FIELDS = {"prediction_errors_by_channel", "composition_events"}
_LEVEL_KNOWN_FIELDS = (
    _LEVEL_BOOLEAN_FIELDS
    | _LEVEL_NULLABLE_INTEGER_FIELDS
    | _LEVEL_COUNTER_FIELDS
    | _LEVEL_MAPPING_FIELDS
)

Build002Probe = Callable[[Path], tuple[str, str, bool]]
Build003Probe = Callable[[Path], tuple[str, str, bool]]


class MatrixAuditError(RuntimeError):
    """The audit input cannot be interpreted as frozen JSON evidence."""


@dataclass(frozen=True, slots=True)
class MatrixAuditOutcome:
    """Paths and status for one independently sealed audit."""

    passed: bool
    receipt_path: Path
    report_path: Path
    errors: tuple[str, ...]


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _is_digest(value: object) -> bool:
    if not isinstance(value, str) or not value.startswith("sha256:"):
        return False
    digest = value.removeprefix("sha256:")
    return len(digest) == 64 and all(character in "0123456789abcdef" for character in digest)


def _is_nonnegative_integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _integer(value: object) -> int:
    return cast(int, value) if _is_nonnegative_integer(value) else 0


def _boolean(value: object) -> bool:
    return value if isinstance(value, bool) else False


def _mapping(value: object) -> dict[str, object]:
    return cast(dict[str, object], value) if isinstance(value, dict) else {}


def _load_object(path: Path) -> dict[str, object]:
    try:
        raw = path.read_bytes()
        value = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise MatrixAuditError(f"cannot read canonical JSON object {path.name}: {error}") from error
    if not isinstance(value, dict):
        raise MatrixAuditError(f"{path.name} must contain one JSON object")
    document = cast(dict[str, object], value)
    if raw != _canonical_bytes(document) + b"\n":
        raise MatrixAuditError(f"{path.name} is not canonical JSON with one LF terminator")
    return document


def _load_jsonl(path: Path) -> list[dict[str, object]]:
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise MatrixAuditError(f"cannot read {path.name}: {error}") from error
    if not raw or not raw.endswith(b"\n") or b"\r" in raw:
        raise MatrixAuditError(f"{path.name} must be non-empty LF-terminated canonical JSONL")
    documents: list[dict[str, object]] = []
    for line_number, line in enumerate(raw.splitlines(), start=1):
        try:
            value = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise MatrixAuditError(
                f"{path.name}:{line_number} is not valid UTF-8 JSON: {error}"
            ) from error
        if not isinstance(value, dict):
            raise MatrixAuditError(f"{path.name}:{line_number} must be a JSON object")
        document = cast(dict[str, object], value)
        if line != _canonical_bytes(document):
            raise MatrixAuditError(f"{path.name}:{line_number} is not canonical JSON")
        documents.append(document)
    return documents


def _root_manifest(root: Path) -> tuple[list[dict[str, object]], str]:
    if not root.is_dir():
        raise MatrixAuditError(f"matrix root is not a directory: {root}")
    actual_top_level = {path.name for path in root.iterdir()}
    if actual_top_level != _REQUIRED_TOP_LEVEL:
        raise MatrixAuditError(
            "matrix root top-level contents differ: "
            f"expected {sorted(_REQUIRED_TOP_LEVEL)}, observed {sorted(actual_top_level)}"
        )
    entries: list[dict[str, object]] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise MatrixAuditError(f"matrix root contains a symbolic link: {relative}")
        if path.is_dir():
            entries.append({"path": relative, "type": "directory"})
        elif path.is_file():
            entries.append(
                {
                    "path": relative,
                    "type": "file",
                    "size": path.stat().st_size,
                    "sha256": _sha256_file(path),
                }
            )
        else:
            raise MatrixAuditError(f"matrix root contains a non-file entry: {relative}")
    return entries, _sha256_bytes(_canonical_bytes(entries))


def _derive_v02_cases() -> tuple[FrozenCase, ...]:
    cases: list[FrozenCase] = []
    for index in range(EXPECTED_CASES):
        payload = HELDOUT_DOMAIN.encode("utf-8") + b"\0" + str(index).encode("ascii")
        seed = int.from_bytes(hashlib.sha256(payload).digest()[:8], "big") % (2**63)
        identity = PROTOCOL_ID.encode("utf-8") + b"\0" + str(seed).encode("ascii")
        case_id = CASE_PREFIX + hashlib.sha256(identity).hexdigest()[:16]
        cases.append(FrozenCase(case_id=case_id, seed=seed))
    return tuple(cases)


def _default_git_probe(root: Path) -> tuple[str, str, bool]:
    def git(*arguments: str) -> str:
        return subprocess.check_output(
            ["git", "-C", str(root), *arguments],
            text=True,
            encoding="utf-8",
            stderr=subprocess.STDOUT,
        ).strip()

    try:
        commit = git("rev-parse", "HEAD")
        tree = git("show", "-s", "--format=%T", "HEAD")
        clean = not bool(git("status", "--porcelain=v1"))
    except (OSError, subprocess.CalledProcessError) as error:
        raise MatrixAuditError(f"cannot probe Git source identity: {error}") from error
    return commit, tree, clean


def _source_file_receipt(path: Path) -> dict[str, object]:
    return {"path": str(path.resolve()), "sha256": _sha256_file(path.resolve())}


def _validate_exact_keys(
    value: Mapping[str, object], expected: set[str], label: str, errors: list[str]
) -> None:
    observed = set(value)
    if observed != expected:
        errors.append(
            f"{label} keys differ: missing={sorted(expected - observed)} "
            f"unexpected={sorted(observed - expected)}"
        )


def _validate_level_metric(metric: Mapping[str, object], label: str, errors: list[str]) -> None:
    missing = _LEVEL_REQUIRED_FIELDS - set(metric)
    unknown = set(metric) - _LEVEL_KNOWN_FIELDS
    if missing:
        errors.append(f"{label} is missing required fields {sorted(missing)}")
    if unknown:
        errors.append(f"{label} has unknown fields {sorted(unknown)}")
    for name in _LEVEL_BOOLEAN_FIELDS & set(metric):
        if not isinstance(metric[name], bool):
            errors.append(f"{label}.{name} is not a boolean")
    for name in _LEVEL_COUNTER_FIELDS & set(metric):
        if not _is_nonnegative_integer(metric[name]):
            errors.append(f"{label}.{name} is not a non-negative integer")
    for name in _LEVEL_NULLABLE_INTEGER_FIELDS & set(metric):
        value = metric[name]
        if value is not None and not _is_nonnegative_integer(value):
            errors.append(f"{label}.{name} is not null or a non-negative integer")
    factors = {
        "prediction_errors_by_channel": tuple(channel.value for channel in CHANNEL_ORDER),
        "composition_events": tuple(mode.value for mode in CompositionMode),
    }
    for name, expected_names in factors.items():
        if name not in metric:
            continue
        counter = metric[name]
        if not isinstance(counter, dict) or set(counter) != set(expected_names):
            errors.append(f"{label}.{name} has the wrong factor names")
            continue
        if any(not _is_nonnegative_integer(item) for item in counter.values()):
            errors.append(f"{label}.{name} has a non-integer count")


def _counter_pairs(value: object, names: tuple[str, ...]) -> tuple[tuple[str, int], ...]:
    source = _mapping(value)
    return tuple((name, _integer(source.get(name))) for name in names)


def _parse_row(raw: dict[str, object], label: str, errors: list[str]) -> CurriculumResultRow | None:
    expected = {field.name for field in fields(CurriculumResultRow)}
    _validate_exact_keys(raw, expected, label, errors)
    if set(raw) != expected:
        return None
    normalized = dict(raw)
    try:
        normalized["state"] = GameStateName(str(raw["state"]))
        normalized["prediction_errors_by_channel"] = tuple(
            (str(pair[0]), pair[1])
            for pair in cast(Sequence[Sequence[object]], raw["prediction_errors_by_channel"])
        )
        normalized["composition_events"] = tuple(
            (str(pair[0]), pair[1])
            for pair in cast(Sequence[Sequence[object]], raw["composition_events"])
        )
        return CurriculumResultRow(**normalized)  # type: ignore[arg-type]
    except (IndexError, KeyError, TypeError, ValueError) as error:
        errors.append(f"{label} violates CurriculumResultRow: {error}")
        return None


def _validate_action(action: object, label: str, errors: list[str]) -> str | None:
    if not isinstance(action, dict) or set(action) != {"name", "coordinate"}:
        errors.append(f"{label} has an invalid action object")
        return None
    name = action.get("name")
    if name not in _ACTION_NAMES:
        errors.append(f"{label} has an undeclared action name")
        return None
    coordinate = action.get("coordinate")
    if coordinate is not None:
        if (
            not isinstance(coordinate, dict)
            or set(coordinate) != {"x", "y"}
            or not _is_nonnegative_integer(coordinate.get("x"))
            or not _is_nonnegative_integer(coordinate.get("y"))
        ):
            errors.append(f"{label} has an invalid coordinate")
    if name == "ACTION6" and coordinate is None:
        errors.append(f"{label} coordinate action omits its coordinate")
    return cast(str, name)


def _validate_links(
    summary: Mapping[str, object],
    variant: str,
    metrics: Sequence[Mapping[str, object]],
    receipt: Mapping[str, object],
    label: str,
    errors: list[str],
) -> tuple[bool, ...]:
    level_valid = [True] * len(FAMILIES)
    expected_by_level = [
        _integer(metric.get("environment_actions")) + _integer(metric.get("resets"))
        for metric in metrics
    ]
    for index, metric in enumerate(metrics):
        submitted = expected_by_level[index]
        receipt_count = _integer(metric.get("receipt_count"))
        complete = _integer(metric.get("complete_receipt_count"))
        attempted_or_completed = submitted > 0 or _boolean(metric.get("completed"))
        level_valid[index] &= attempted_or_completed
        level_valid[index] &= submitted == receipt_count == complete
        if not level_valid[index]:
            errors.append(f"{label}.level[{index}] action/receipt counts do not reconcile")

    if receipt.get("receipt_links_complete") is not True:
        errors.append(f"{label} does not attest complete action/receipt links")

    raw_links = summary.get("action_links")
    if variant == "BUILD002_FROZEN":
        if raw_links is not None:
            errors.append(f"{label} frozen baseline unexpectedly contains learner action links")
        return tuple(level_valid)

    expected_total = sum(expected_by_level)
    if not isinstance(raw_links, list) or len(raw_links) != expected_total:
        errors.append(f"{label} action link count does not equal submitted consequences")
        return tuple(False for _ in FAMILIES)
    observed_by_level = [0] * len(FAMILIES)
    reset_count = 0
    previous_after_ref: object = None
    for expected_step, raw_link in enumerate(raw_links, start=1):
        link_label = f"{label}.action_links[{expected_step - 1}]"
        if not isinstance(raw_link, dict):
            errors.append(f"{link_label} is not an object")
            continue
        link = cast(dict[str, object], raw_link)
        _validate_exact_keys(link, _ACTION_LINK_KEYS, link_label, errors)
        level_index = link.get("level_index")
        if not _is_nonnegative_integer(level_index) or cast(int, level_index) >= len(FAMILIES):
            errors.append(f"{link_label}.level_index is invalid")
            continue
        index = cast(int, level_index)
        observed_by_level[index] += 1
        if link.get("step") != expected_step:
            errors.append(f"{link_label}.step is not consecutive")
        action_name = _validate_action(link.get("action"), f"{link_label}.action", errors)
        reset_count += action_name == "RESET"
        if not isinstance(link.get("prediction_id"), str) or not link.get("prediction_id"):
            errors.append(f"{link_label}.prediction_id is empty")
        for digest_name in (
            "prediction_digest",
            "before_ref",
            "after_ref",
            "learning_digest",
            "causal_receipt_digest",
        ):
            if not _is_digest(link.get(digest_name)):
                errors.append(f"{link_label}.{digest_name} is not a SHA-256 digest")
        if previous_after_ref is not None and link.get("before_ref") != previous_after_ref:
            errors.append(f"{link_label}.before_ref breaks the observation-link chain")
        previous_after_ref = link.get("after_ref")
        if link.get("complete") is not True:
            errors.append(f"{link_label} is not complete")
    if observed_by_level != expected_by_level:
        errors.append(f"{label} action links do not partition by level receipt counts")
        level_valid = [
            valid and observed == expected
            for valid, observed, expected in zip(
                level_valid, observed_by_level, expected_by_level, strict=True
            )
        ]
    if reset_count != receipt.get("resets"):
        errors.append(f"{label} reset action links do not match the sequence receipt")
    if expected_total - reset_count != receipt.get("environment_actions"):
        errors.append(f"{label} non-reset action links do not match the sequence receipt")
    return tuple(level_valid)


def _expected_row(
    *,
    receipt: Mapping[str, object],
    metric: Mapping[str, object],
    index: int,
    link_valid: bool,
) -> CurriculumResultRow:
    completed = _boolean(metric.get("completed"))
    final_levels = _integer(receipt.get("levels_completed"))
    final_state = GameStateName(str(receipt.get("final_state")))
    if completed:
        state = GameStateName.WIN if index + 1 == len(FAMILIES) else GameStateName.NOT_FINISHED
        levels_completed = index + 1
    elif index == final_levels:
        state = final_state
        levels_completed = final_levels
    else:
        state = GameStateName.NOT_PLAYED
        levels_completed = final_levels
    actions = _integer(metric.get("environment_actions"))
    exploratory = _integer(metric.get("exploratory_actions"))
    progress = _integer(metric.get("progress_actions"))
    if exploratory + progress != actions:
        exploratory, progress = actions, 0
    total_actions = sum(
        _integer(item.get("environment_actions"))
        for item in cast(Sequence[Mapping[str, object]], receipt["_audit_metrics"])
    )
    wall_time = cast(float, receipt["wall_time_seconds"])
    allocated_wall = wall_time * actions / total_actions if total_actions else 0.0
    receipt_count = _integer(metric.get("receipt_count"))
    complete_count = _integer(metric.get("complete_receipt_count"))
    nullable_stable = metric.get("actions_to_stable")
    nullable_reopenings = metric.get("erroneous_global_reopenings")
    return CurriculumResultRow(
        case_id=cast(str, receipt["case_id"]),
        seed=cast(int, receipt["seed"]),
        variant=cast(str, receipt["variant"]),
        family=FAMILIES[index],
        level_index=index + 1,
        state=state,
        completed=completed,
        levels_completed=levels_completed,
        environment_actions=actions,
        resets=_integer(metric.get("resets")),
        exploratory_actions=exploratory,
        progress_actions=progress,
        redundant_probes=min(exploratory, _integer(metric.get("redundant_probes"))),
        actions_to_stable=None if nullable_stable is None else _integer(nullable_stable),
        movement_prediction_errors=_integer(metric.get("movement_prediction_errors")),
        resource_prediction_errors=_integer(metric.get("resource_prediction_errors")),
        access_prediction_errors=_integer(metric.get("access_prediction_errors")),
        hazard_prediction_errors=_integer(metric.get("hazard_prediction_errors")),
        prediction_errors_by_channel=_counter_pairs(
            metric.get("prediction_errors_by_channel"),
            tuple(channel.value for channel in CHANNEL_ORDER),
        ),
        residuals_observed=_integer(metric.get("residuals_observed")),
        residuals_localized=_integer(metric.get("residuals_localized")),
        residuals_resolved=_integer(metric.get("residuals_resolved")),
        base_mechanics_retained=_boolean(metric.get("base_mechanics_retained")),
        observed_retained_matches=_integer(metric.get("observed_retained_matches")),
        erroneous_global_reopenings=(
            None if nullable_reopenings is None else _integer(nullable_reopenings)
        ),
        passive_confirmations=_integer(metric.get("passive_confirmations")),
        transfer_confirmations=_integer(metric.get("transfer_confirmations")),
        local_repair_candidates_opened=_integer(metric.get("local_repair_candidates_opened")),
        local_repairs_confirmed=_integer(metric.get("local_repairs_confirmed")),
        local_repair_failures=_integer(metric.get("local_repair_failures")),
        base_reopenings=_integer(metric.get("base_reopenings")),
        composition_events=_counter_pairs(
            metric.get("composition_events"), tuple(mode.value for mode in CompositionMode)
        ),
        clef_promotions=_integer(metric.get("clef_promotions")),
        clef_parks=_integer(metric.get("clef_parks")),
        clef_stops=_integer(metric.get("clef_stops")),
        other_object_effects_observed=_integer(metric.get("other_object_effects_observed")),
        topology_changes_confirmed=_integer(metric.get("topology_changes_confirmed")),
        delayed_candidates_confirmed=_integer(metric.get("delayed_candidates_confirmed")),
        unresolved_ledger_count=_integer(metric.get("unresolved_ledger_count")),
        active_ledger_pressure=_integer(metric.get("active_ledger_pressure")),
        wall_time_seconds=allocated_wall,
        peak_memory_bytes=cast(int, receipt["peak_memory_bytes"]),
        replay_digest=cast(str, receipt["replay_digest"]),
        replay_deterministic=receipt.get("replay_deterministic") is True,
        receipt_complete=(
            receipt.get("run_status") != "FAILED_INFRASTRUCTURE"
            and receipt_count == complete_count
            and link_valid
            and receipt.get("sequence_counts_reconciled") is True
        ),
        run_status=cast(str, receipt["run_status"]),
        failure_reason=cast(str | None, receipt.get("failure_reason")),
    )


def _row_object(row: CurriculumResultRow) -> dict[str, object]:
    value = asdict(row)
    value["state"] = row.state.value
    return value


def _validate_decisions(summary: Mapping[str, object], errors: list[str]) -> None:
    decisions = summary.get("decisions")
    if not isinstance(decisions, dict):
        errors.append("paired_summary.decisions is absent")
        return
    required = {
        "H1",
        "H2",
        "H3",
        "all_hypotheses_passed",
        "evidence_quality_passed",
        "matrix_passed",
    }
    if set(decisions) != required:
        errors.append("paired_summary.decisions does not contain the exact literal decision set")
        return
    statuses: dict[str, str] = {}
    passed: dict[str, bool] = {}
    for hypothesis in ("H1", "H2", "H3"):
        decision = decisions.get(hypothesis)
        if not isinstance(decision, dict):
            errors.append(f"paired_summary.decisions.{hypothesis} is not an object")
            continue
        status = decision.get("status")
        flag = decision.get("passed")
        allowed = {"PASS", "FAIL"} if hypothesis != "H2" else {"PASS", "FAIL", "NOT_MEASURED"}
        if status not in allowed or not isinstance(flag, bool):
            errors.append(f"paired_summary.decisions.{hypothesis} status/flag is invalid")
            continue
        statuses[hypothesis] = cast(str, status)
        passed[hypothesis] = flag
        if (status == "PASS") != flag:
            errors.append(f"paired_summary.decisions.{hypothesis} status and passed disagree")
    if len(passed) != 3:
        return
    all_hypotheses = all(passed.values())
    if decisions.get("all_hypotheses_passed") is not all_hypotheses:
        errors.append("literal hypothesis aggregate disagrees with H1/H2/H3")
    evidence = decisions.get("evidence_quality_passed")
    matrix_passed = decisions.get("matrix_passed")
    if not isinstance(evidence, bool) or not isinstance(matrix_passed, bool):
        errors.append("paired_summary decision aggregate flags are not booleans")
    elif matrix_passed is not (all_hypotheses and evidence):
        errors.append("matrix_passed disagrees with hypothesis and evidence decisions")


def _exclusive_write(path: Path, content: str) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(content)


def audit_build003_matrix(
    *,
    matrix_root: Path,
    output_root: Path,
    repository_root: Path,
    expected_cases: Sequence[FrozenCase] | None = None,
    build002_probe: Build002Probe | None = None,
    build003_probe: Build003Probe | None = None,
    loaded_result_ledger_path: Path | None = None,
) -> MatrixAuditOutcome:
    """Audit one matrix and seal deterministic evidence outside its source root."""

    matrix_root = matrix_root.resolve()
    output_root = output_root.resolve()
    repository_root = repository_root.resolve()
    if output_root == matrix_root or output_root.is_relative_to(matrix_root):
        raise ValueError("audit output must be outside the immutable matrix root")
    if matrix_root.is_relative_to(output_root):
        raise ValueError("audit output cannot contain the immutable matrix root")
    if output_root.exists() and any(output_root.iterdir()):
        raise FileExistsError(f"audit output root is not empty: {output_root}")

    errors: list[str] = []
    checks: dict[str, bool] = {}
    before_entries: list[dict[str, object]] = []
    before_digest = "sha256:" + "0" * 64
    try:
        before_entries, before_digest = _root_manifest(matrix_root)
        checks["fresh_exact_matrix_root_contents"] = True
    except MatrixAuditError as error:
        errors.append(str(error))
        checks["fresh_exact_matrix_root_contents"] = False

    receipt: dict[str, object] = {}
    raw_rows: list[dict[str, object]] = []
    sequence_receipts: list[dict[str, object]] = []
    if checks["fresh_exact_matrix_root_contents"]:
        try:
            receipt = _load_object(matrix_root / "matrix-receipt.json")
            raw_rows = _load_jsonl(matrix_root / "rows.jsonl")
            sequence_receipts = _load_jsonl(matrix_root / "sequence-receipts.jsonl")
            checks["canonical_source_json"] = True
        except MatrixAuditError as error:
            errors.append(str(error))
            checks["canonical_source_json"] = False
    else:
        checks["canonical_source_json"] = False

    cases = tuple(expected_cases) if expected_cases is not None else _derive_v02_cases()
    if len(cases) != EXPECTED_CASES or len({case.seed for case in cases}) != EXPECTED_CASES:
        raise ValueError("expected case injection must contain 30 unique cases")
    expected_case_by_seed = {case.seed: case.case_id for case in cases}
    independently_observed_build003_identity: dict[str, object] | None = None

    if receipt:
        _validate_exact_keys(receipt, _MATRIX_KEYS, "matrix receipt", errors)
        exact_matrix_values = {
            "schema": MATRIX_SCHEMA,
            "surface": "synthetic",
            "status": receipt.get("status"),
            "status_reason": receipt.get("status_reason"),
            "matrix_structure_status": "COMPLETE_V02",
            "complete_preregistered_matrix": True,
            "protocol_version": PROTOCOL_VERSION,
            "protocol_id": PROTOCOL_ID,
            "seed_set": "heldout",
            "case_count": EXPECTED_CASES,
            "variant_count": len(VARIANTS),
            "sequence_count": EXPECTED_SEQUENCES,
            "row_count": EXPECTED_ROWS,
            "expected_selected_row_count": EXPECTED_ROWS,
            "expected_full_row_count": EXPECTED_ROWS,
            "budgets": EXPECTED_BUDGETS,
            "build002_baseline_identity": EXPECTED_BASELINE,
        }
        for key, expected in exact_matrix_values.items():
            if receipt.get(key) != expected:
                errors.append(f"matrix receipt {key} disagrees with exact v0.2 binding")
        checks["exact_v02_matrix_binding"] = not any(
            message.startswith("matrix receipt") and "v0.2 binding" in message for message in errors
        )

        path_bindings = {
            "rows_path": matrix_root / "rows.jsonl",
            "sequence_receipts_path": matrix_root / "sequence-receipts.jsonl",
            "worker_storage_root": matrix_root / "worker-storage",
            "protocol_path": repository_root / PROTOCOL_PATH,
            "manifest_path": repository_root / MANIFEST_PATH,
            "preregistration_path": repository_root / PREREGISTRATION_PATH,
        }
        for key, expected_path in path_bindings.items():
            raw_path = receipt.get(key)
            if not isinstance(raw_path, str) or Path(raw_path).resolve() != expected_path.resolve():
                errors.append(f"matrix receipt {key} is not bound to the expected path")
        hash_bindings = {
            "rows_sha256": matrix_root / "rows.jsonl",
            "sequence_receipts_sha256": matrix_root / "sequence-receipts.jsonl",
            "protocol_sha256": repository_root / PROTOCOL_PATH,
            "manifest_sha256": repository_root / MANIFEST_PATH,
            "preregistration_sha256": repository_root / PREREGISTRATION_PATH,
        }
        for key, path in hash_bindings.items():
            try:
                observed = _sha256_file(path)
            except OSError as error:
                errors.append(f"cannot hash {key} source: {error}")
                continue
            if receipt.get(key) != observed:
                errors.append(f"matrix receipt {key} does not match its file")
        checks["matrix_and_asset_hashes"] = not any(
            "does not match its file" in message or "cannot hash" in message for message in errors
        )

        baseline_root_value = receipt.get("build002_source_root")
        baseline_identity_ok = isinstance(baseline_root_value, str)
        if baseline_identity_ok:
            baseline_root = Path(cast(str, baseline_root_value)).resolve()
            try:
                commit, tree, clean = (build002_probe or _default_git_probe)(baseline_root)
                baseline_identity_ok = commit == BUILD002_COMMIT and tree == BUILD002_TREE and clean
            except MatrixAuditError as error:
                errors.append(str(error))
                baseline_identity_ok = False
        if not baseline_identity_ok:
            errors.append("frozen Build 002 checkout commit/tree/clean identity is invalid")
        checks["frozen_build002_checkout_identity"] = baseline_identity_ok

        build003_identity = receipt.get("build003_source_identity")
        build003_identity_ok = (
            isinstance(build003_identity, dict)
            and set(build003_identity) == {"commit", "tree", "clean"}
            and build003_identity.get("clean") is True
        )
        if build003_identity_ok:
            try:
                source_commit, source_tree, source_clean = (build003_probe or _default_git_probe)(
                    repository_root
                )
                independently_observed_build003_identity = {
                    "commit": source_commit,
                    "tree": source_tree,
                    "clean": source_clean,
                }
                build003_identity_ok = (
                    build003_identity == independently_observed_build003_identity and source_clean
                )
            except MatrixAuditError as error:
                errors.append(str(error))
                build003_identity_ok = False
        if not build003_identity_ok:
            errors.append(
                "matrix receipt lacks or disagrees with the independently probed clean "
                "Build 003 commit/tree identity"
            )
        checks["build003_commit_tree_clean_identity"] = build003_identity_ok

        result_ledger_path = repository_root / "src/arc3/evaluation/build003_results.py"
        runner_path = repository_root / "scripts/run_build003_curriculum_matrix.py"
        expected_source_files: dict[str, object] = {}
        try:
            expected_source_files = {
                "matrix_runner": _source_file_receipt(runner_path),
                "result_ledger": _source_file_receipt(result_ledger_path),
            }
        except OSError as error:
            errors.append(f"cannot hash Build 003 source files: {error}")
        source_files_ok = receipt.get("build003_source_files") == expected_source_files
        active_ledger_path = (
            loaded_result_ledger_path.resolve()
            if loaded_result_ledger_path is not None
            else Path(__file__).with_name("build003_results.py").resolve()
        )
        if active_ledger_path != result_ledger_path.resolve():
            source_files_ok = False
            errors.append("loaded result-ledger module is outside the recorded Build 003 source")
        if not source_files_ok:
            errors.append("matrix receipt Build 003 runner/result-ledger hashes disagree")
        checks["build003_runner_and_result_ledger_hashes"] = source_files_ok
    else:
        checks["exact_v02_matrix_binding"] = False
        checks["matrix_and_asset_hashes"] = False
        checks["frozen_build002_checkout_identity"] = False
        checks["build003_commit_tree_clean_identity"] = False
        checks["build003_runner_and_result_ledger_hashes"] = False

    parsed_rows: list[CurriculumResultRow] = []
    for index, raw in enumerate(raw_rows):
        row = _parse_row(raw, f"rows[{index}]", errors)
        if row is not None:
            parsed_rows.append(row)
    if len(raw_rows) != EXPECTED_ROWS or len(parsed_rows) != EXPECTED_ROWS:
        errors.append("rows.jsonl does not contain exactly 1200 valid rows")

    row_keys = [row.key for row in parsed_rows]
    if len(set(row_keys)) != len(row_keys):
        errors.append("rows.jsonl contains duplicate/replacement row identities")
    expected_row_order = [
        (case_id, seed, variant, family)
        for variant, seed, case_id in sorted(
            (variant, case.seed, case.case_id) for variant in VARIANTS for case in cases
        )
        for family in FAMILIES
    ]
    if row_keys != expected_row_order:
        errors.append("result rows are not the exact canonical sequence/family order")
    rows_by_sequence: dict[tuple[str, int, str], list[CurriculumResultRow]] = defaultdict(list)
    for row in parsed_rows:
        rows_by_sequence[(row.case_id, row.seed, row.variant)].append(row)

    observed_sequences: set[tuple[str, int, str]] = set()
    observed_cases: set[tuple[str, int]] = set()
    status_counts: Counter[str] = Counter()
    wins = 0
    expected_sequence_order = sorted(
        (variant, case.seed, case.case_id) for variant in VARIANTS for case in cases
    )
    observed_sequence_order: list[tuple[str, int, str]] = []
    for sequence_index, sequence in enumerate(sequence_receipts):
        label = f"sequence_receipts[{sequence_index}]"
        _validate_exact_keys(sequence, _SEQUENCE_KEYS, label, errors)
        variant = sequence.get("variant")
        seed = sequence.get("seed")
        case_id = sequence.get("case_id")
        if not isinstance(variant, str) or variant not in VARIANTS:
            errors.append(f"{label}.variant is not preregistered")
            continue
        if not _is_nonnegative_integer(seed) or not isinstance(case_id, str):
            errors.append(f"{label} case/seed identity is invalid")
            continue
        typed_seed = cast(int, seed)
        if expected_case_by_seed.get(typed_seed) != case_id:
            errors.append(f"{label} is not an exact held-out v0.2 case")
        observed_sequence_order.append((variant, typed_seed, case_id))
        sequence_key = (case_id, typed_seed, variant)
        if sequence_key in observed_sequences:
            errors.append(f"{label} duplicates/replaces a sequence identity")
        observed_sequences.add(sequence_key)
        observed_cases.add((case_id, typed_seed))

        for key, expected in {
            "schema": SEQUENCE_SCHEMA,
            "surface": "synthetic",
            "protocol_version": PROTOCOL_VERSION,
            "protocol_id": PROTOCOL_ID,
            "protocol_path": PROTOCOL_PATH,
            "manifest_path": MANIFEST_PATH,
            "budgets": EXPECTED_BUDGETS,
            "build002_baseline_identity": EXPECTED_BASELINE,
        }.items():
            if sequence.get(key) != expected:
                errors.append(f"{label}.{key} disagrees with protocol v0.2")
        run_status = sequence.get("run_status")
        failure_reason = sequence.get("failure_reason")
        if run_status not in RUN_STATUSES:
            errors.append(f"{label}.run_status is invalid")
            continue
        typed_status = run_status
        status_counts[typed_status] += 1
        if typed_status in {"FAILED_INFRASTRUCTURE", "POLICY_ERROR"}:
            errors.append(f"{label} contains disallowed {typed_status} evidence")
        if (typed_status == "SUCCESS") != (failure_reason is None):
            errors.append(f"{label} run status and failure reason disagree")
        if sequence.get("replay_deterministic") is not True:
            errors.append(f"{label} deterministic replay flag is not true")
        if sequence.get("sequence_counts_reconciled") is not True:
            errors.append(f"{label} sequence counter reconciliation is not true")
        if not _is_digest(sequence.get("replay_digest")):
            errors.append(f"{label}.replay_digest is invalid")
        for name in (
            "levels_completed",
            "win_levels",
            "environment_actions",
            "resets",
            "peak_memory_bytes",
            "reported_environment_actions",
            "reported_resets",
        ):
            if not _is_nonnegative_integer(sequence.get(name)):
                errors.append(f"{label}.{name} is not a non-negative integer")
        wall_time = sequence.get("wall_time_seconds")
        if (
            isinstance(wall_time, bool)
            or not isinstance(wall_time, (int, float))
            or not 0 <= wall_time < float("inf")
        ):
            errors.append(f"{label}.wall_time_seconds is invalid")
            continue
        if _integer(sequence.get("environment_actions")) > 192:
            errors.append(f"{label} exceeds the 192-action sequence budget")
        if _integer(sequence.get("resets")) > 10:
            errors.append(f"{label} exceeds the 10-reset sequence budget")
        if sequence.get("reported_environment_actions") != sequence.get("environment_actions"):
            errors.append(f"{label} reported and runner environment actions disagree")
        if sequence.get("reported_resets") != sequence.get("resets"):
            errors.append(f"{label} reported and runner reset counts disagree")

        final_state = sequence.get("final_state")
        if final_state == GameStateName.WIN.value:
            wins += 1
        if typed_status == "SUCCESS" and (
            final_state != GameStateName.WIN.value
            or sequence.get("levels_completed") != len(FAMILIES)
            or sequence.get("win_levels") != len(FAMILIES)
        ):
            errors.append(f"{label} SUCCESS lacks authoritative synthetic WIN")
        if final_state == GameStateName.WIN.value and typed_status != "SUCCESS":
            errors.append(f"{label} records WIN under a non-success status")

        summary = sequence.get("worker_summary")
        if not isinstance(summary, dict):
            errors.append(f"{label}.worker_summary is not an object")
            continue
        typed_summary = cast(dict[str, object], summary)
        for key, expected in {
            "schema": "arc3.build003.worker-summary.v0.1",
            "variant": variant,
            "final_state": final_state,
            "levels_completed": sequence.get("levels_completed"),
            "win_levels": sequence.get("win_levels"),
        }.items():
            if typed_summary.get(key) != expected:
                errors.append(f"{label}.worker_summary.{key} disagrees with the sequence")
        if not _is_digest(typed_summary.get("receipt_digest")):
            errors.append(f"{label}.worker_summary.receipt_digest is invalid")
        raw_metrics = typed_summary.get("levels")
        if not isinstance(raw_metrics, list) or len(raw_metrics) != len(FAMILIES):
            errors.append(f"{label}.worker_summary.levels is not the ten-level sequence")
            continue
        metrics: list[Mapping[str, object]] = []
        for level_index, raw_metric in enumerate(raw_metrics):
            if not isinstance(raw_metric, dict):
                errors.append(f"{label}.worker_summary.levels[{level_index}] is not an object")
                metrics.append({})
                continue
            metric = cast(dict[str, object], raw_metric)
            _validate_level_metric(metric, f"{label}.worker_summary.levels[{level_index}]", errors)
            metrics.append(metric)
        submitted_actions = sum(_integer(item.get("environment_actions")) for item in metrics)
        submitted_resets = sum(_integer(item.get("resets")) for item in metrics)
        receipt_count = sum(_integer(item.get("receipt_count")) for item in metrics)
        if submitted_actions != sequence.get("environment_actions"):
            errors.append(f"{label} row-level actions do not reconcile to the sequence")
        if submitted_resets != sequence.get("resets"):
            errors.append(f"{label} row-level resets do not reconcile to the sequence")
        if typed_summary.get("receipt_count") != receipt_count:
            errors.append(f"{label} worker receipt count does not reconcile to levels")
        link_valid = _validate_links(typed_summary, variant, metrics, sequence, label, errors)

        sequence_rows = rows_by_sequence.get(sequence_key, [])
        sequence_rows.sort(key=lambda row: row.level_index)
        if len(sequence_rows) != len(FAMILIES):
            errors.append(f"{label} does not bind exactly ten result rows")
            continue
        augmented_receipt = dict(sequence)
        augmented_receipt["_audit_metrics"] = metrics
        for level_index, (actual, row_metric) in enumerate(
            zip(sequence_rows, metrics, strict=True)
        ):
            try:
                expected = _expected_row(
                    receipt=augmented_receipt,
                    metric=row_metric,
                    index=level_index,
                    link_valid=link_valid[level_index],
                )
            except (KeyError, TypeError, ValueError) as error:
                errors.append(f"{label} cannot reconstruct row {level_index}: {error}")
                continue
            if _canonical_bytes(_row_object(actual)) != _canonical_bytes(_row_object(expected)):
                errors.append(f"{label} row {level_index} is not derived from its receipt")

    if len(sequence_receipts) != EXPECTED_SEQUENCES:
        errors.append("sequence-receipts.jsonl does not contain exactly 120 sequences")
    if observed_sequence_order != expected_sequence_order:
        errors.append("sequence receipts are not the exact sorted 30x4 held-out selection")
    if observed_cases != {(case.case_id, case.seed) for case in cases}:
        errors.append("matrix case set differs from the exact 30 held-out v0.2 cases")
    expected_sequence_keys = {
        (case.case_id, case.seed, variant) for case in cases for variant in VARIANTS
    }
    if observed_sequences != expected_sequence_keys:
        errors.append("matrix sequence identities are incomplete or contain replacements")
    if set(rows_by_sequence) != expected_sequence_keys:
        errors.append("result row sequence identities are incomplete or contain replacements")
    checks["exact_unique_case_sequence_row_matrix"] = not any(
        "duplicate/replacement" in message
        or "exact 30" in message
        or "canonical sequence/family order" in message
        or "incomplete or contain replacements" in message
        or "exactly 120" in message
        or "exactly 1200" in message
        for message in errors
    )

    rebuilt_summary: dict[str, object] | None = None
    try:
        ledger = Build003ResultLedger(cases)
        ledger.append_many(parsed_rows)
        ledger.require_complete()
        rebuilt_summary = ledger.preregistered_summary()
    except ValueError as error:
        errors.append(f"Build003ResultLedger reconstruction failed: {error}")
    receipt_summary = receipt.get("paired_summary") if receipt else None
    summary_equal = (
        rebuilt_summary is not None
        and isinstance(receipt_summary, dict)
        and _canonical_bytes(rebuilt_summary) == _canonical_bytes(receipt_summary)
    )
    if not summary_equal:
        errors.append("reconstructed paired summary is not canonically equal to the receipt")
    checks["paired_summary_canonical_reconstruction"] = summary_equal
    if rebuilt_summary is not None:
        _validate_decisions(rebuilt_summary, errors)
    checks["literal_h1_h2_h3_decisions"] = not any(
        message.startswith("paired_summary") or "hypothesis aggregate" in message
        for message in errors
    )

    status_expected: tuple[str, str] | None = None
    if rebuilt_summary is not None:
        decisions = rebuilt_summary.get("decisions")
        if isinstance(decisions, dict):
            if decisions.get("matrix_passed") is True:
                status_expected = (
                    "PASS",
                    "PREREGISTERED_H1_H2_H3_AND_EVIDENCE_QUALITY_PASSED",
                )
            else:
                status_expected = (
                    "FAILED_MECHANISM",
                    "PREREGISTERED_HYPOTHESIS_OR_EVIDENCE_GATE_FAILED",
                )
    if (
        status_expected is None
        or (receipt.get("status"), receipt.get("status_reason")) != status_expected
    ):
        errors.append("matrix status/reason disagrees with literal reconstructed decisions")
    if receipt.get("run_status_counts") != dict(sorted(status_counts.items())):
        errors.append("matrix run_status_counts does not match sequence receipts")
    if receipt.get("authoritative_win_sequences") != wins:
        errors.append("matrix authoritative_win_sequences does not match sequence receipts")
    checks["matrix_status_and_aggregate_consistency"] = not any(
        "matrix status/reason" in message
        or "run_status_counts" in message
        or "authoritative_win_sequences" in message
        for message in errors
    )
    checks["no_infrastructure_or_policy_failure"] = not any(
        "contains disallowed" in message for message in errors
    )
    checks["sequence_replay_links_and_counters"] = not any(
        "replay" in message
        or "action link" in message
        or "receipt count" in message
        or "counter reconciliation" in message
        or "actions do not reconcile" in message
        or "resets do not reconcile" in message
        for message in errors
    )

    after_entries: list[dict[str, object]] = []
    after_digest = "sha256:" + "0" * 64
    try:
        after_entries, after_digest = _root_manifest(matrix_root)
    except MatrixAuditError as error:
        errors.append(f"post-audit matrix manifest failed: {error}")
    source_unchanged = before_entries == after_entries and before_digest == after_digest
    if not source_unchanged:
        errors.append("source matrix contents changed during the read-only audit")
    checks["source_matrix_unchanged"] = source_unchanged

    unique_errors = tuple(dict.fromkeys(errors))
    passed = not unique_errors and all(checks.values())
    paired_summary_digest = (
        _sha256_bytes(_canonical_bytes(rebuilt_summary)) if rebuilt_summary is not None else None
    )
    source_file_hashes: dict[str, object] = {}
    source_paths = {
        "matrix_runner": repository_root / "scripts/run_build003_curriculum_matrix.py",
        "result_ledger": repository_root / "src/arc3/evaluation/build003_results.py",
        "protocol": repository_root / PROTOCOL_PATH,
        "preregistration": repository_root / PREREGISTRATION_PATH,
        "manifest": repository_root / MANIFEST_PATH,
        "matrix_auditor": Path(__file__).resolve(),
    }
    for name, path in source_paths.items():
        try:
            source_file_hashes[name] = _source_file_receipt(path)
        except OSError as error:
            source_file_hashes[name] = {"path": str(path.resolve()), "error": str(error)}
    build003_source_identity = receipt.get("build003_source_identity") if receipt else None
    audit_payload: dict[str, object] = {
        "schema": AUDIT_SCHEMA,
        "status": "PASS" if passed else "FAIL",
        "surface": "synthetic",
        "matrix_root": str(matrix_root),
        "matrix_receipt_path": str(matrix_root / "matrix-receipt.json"),
        "matrix_receipt_sha256": (
            _sha256_file(matrix_root / "matrix-receipt.json")
            if (matrix_root / "matrix-receipt.json").is_file()
            else None
        ),
        "matrix_root_manifest_sha256_before": before_digest,
        "matrix_root_manifest_sha256_after": after_digest,
        "matrix_root_manifest": before_entries,
        "source_matrix_unchanged": source_unchanged,
        "protocol_version": PROTOCOL_VERSION,
        "protocol_id": PROTOCOL_ID,
        "seed_set": "heldout",
        "expected_cases": EXPECTED_CASES,
        "expected_variants": list(VARIANTS),
        "expected_sequences": EXPECTED_SEQUENCES,
        "expected_rows": EXPECTED_ROWS,
        "observed_sequences": len(sequence_receipts),
        "observed_rows": len(raw_rows),
        "frozen_build002_commit": BUILD002_COMMIT,
        "frozen_build002_tree": BUILD002_TREE,
        "build003_source_identity": build003_source_identity,
        "independently_observed_build003_source_identity": (
            independently_observed_build003_identity
        ),
        "source_file_hashes": source_file_hashes,
        "paired_summary_canonical_sha256": paired_summary_digest,
        "checks": checks,
        "errors": list(unique_errors),
        "limitations": [
            "The matrix format stores deterministic-replay and returned-action-link audit "
            "results, not complete observation transcripts; this auditor validates every "
            "stored flag, digest, learner action link, row derivation, and counter relation "
            "but cannot re-simulate environment transitions from these files alone.",
            "Frozen Build 002 rows contain receipt counters and runner link attestations but "
            "not learner-style per-action link objects; the exact clean checkout identity is "
            "independently probed.",
        ],
        "claim_boundary": (
            "This audit covers only synthetic Build 003 v0.2 matrix integrity and literal "
            "H1-H3 decision consistency. It is not public, sealed target-holdout, official "
            "target-game, or GameState.WIN evidence."
        ),
    }
    seal_digest = _sha256_bytes(_canonical_bytes(audit_payload))
    sealed_receipt = {
        **audit_payload,
        "seal": {
            "algorithm": "sha256",
            "payload_sha256": seal_digest,
            "replacement_permitted": False,
        },
    }
    output_root.mkdir(parents=True, exist_ok=True)
    receipt_path = output_root / "audit-receipt.json"
    report_path = output_root / "REPORT.md"
    _exclusive_write(
        receipt_path,
        _canonical_bytes(sealed_receipt).decode("utf-8") + "\n",
    )
    report_lines = [
        "# Build 003 v0.2 matrix audit",
        "",
        f"- Status: `{'PASS' if passed else 'FAIL'}`",
        f"- Matrix receipt SHA-256: `{audit_payload['matrix_receipt_sha256']}`",
        f"- Matrix root manifest SHA-256: `{before_digest}`",
        f"- Sealed payload SHA-256: `{seal_digest}`",
        f"- Sequences: `{len(sequence_receipts)}` / `{EXPECTED_SEQUENCES}`",
        f"- Rows: `{len(raw_rows)}` / `{EXPECTED_ROWS}`",
        f"- Errors: `{len(unique_errors)}`",
        "",
    ]
    if unique_errors:
        report_lines.extend(("## Failures", ""))
        report_lines.extend(f"- {message}" for message in unique_errors)
        report_lines.append("")
    report_lines.extend(
        (
            "The source matrix was hashed before and after the read-only audit and was not "
            "used as the audit output directory.",
            "",
            "This is synthetic integrity evidence only; it is not official target-game WIN "
            "evidence.",
            "",
        )
    )
    _exclusive_write(report_path, "\n".join(report_lines))
    return MatrixAuditOutcome(passed, receipt_path, report_path, unique_errors)


__all__ = [
    "AUDIT_SCHEMA",
    "BUILD002_COMMIT",
    "BUILD002_TREE",
    "EXPECTED_BUDGETS",
    "MatrixAuditError",
    "MatrixAuditOutcome",
    "audit_build003_matrix",
]
