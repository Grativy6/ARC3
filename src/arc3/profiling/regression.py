"""Stage 16 execution of the exact pinned Stage 13 performance basis."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, cast

from arc3.evaluation import EvaluationConfig, run_evaluation, verify_evaluation_artifacts
from arc3.evaluation.artifacts import sha256_file
from arc3.evaluation.thresholds import load_performance_thresholds
from arc3.types import JSONValue

_STAGE13_EVIDENCE_PATH = Path("docs/evidence/013-evaluation-harness-acceptance.json")
_STAGE13_EVIDENCE_SHA256 = "sha256:ab354deec3ef4f7a84d285a8e7603dbe357afcf6c6bbff7862fe94979b94780e"
_STAGE13_MEASURED_COMMIT = "01f7a12e42f50e2899db9d430bcf4d125a81d49f"


def _load_stage13_evidence(repository: Path) -> tuple[dict[str, Any], str]:
    path = repository / _STAGE13_EVIDENCE_PATH
    digest = f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"
    if digest != _STAGE13_EVIDENCE_SHA256:
        raise ValueError("pinned Stage 13 evidence hash mismatch")
    raw: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("pinned Stage 13 evidence is not a JSON object")
    evidence = cast(dict[str, Any], raw)
    regression = evidence.get("performance_regression")
    identity = evidence.get("identity")
    threshold_digest = sha256_file(
        repository / "src" / "arc3" / "evaluation" / "performance-thresholds.v0.1.json"
    )
    if (
        evidence.get("stage") != "13"
        or evidence.get("status") != "PASS"
        or evidence.get("measured_repository_commit") != _STAGE13_MEASURED_COMMIT
        or not isinstance(identity, dict)
        or identity.get("performance_threshold_declaration_hash") != threshold_digest
        or not isinstance(regression, dict)
        or regression.get("status") != "PASS"
        or regression.get("verified") is not True
    ):
        raise ValueError("pinned Stage 13 evidence does not contain its accepted regression")
    return evidence, digest


def validate_stage13_regression_binding(repository: Path) -> dict[str, JSONValue]:
    """Verify the accepted evidence and packaged threshold identities without executing runs."""

    evidence, evidence_digest = _load_stage13_evidence(repository.resolve())
    identity = cast(dict[str, Any], evidence["identity"])
    regression = cast(dict[str, Any], evidence["performance_regression"])
    return {
        "evidence_path": _STAGE13_EVIDENCE_PATH.as_posix(),
        "evidence_sha256": evidence_digest,
        "measured_commit": _STAGE13_MEASURED_COMMIT,
        "performance_threshold_sha256": str(identity["performance_threshold_declaration_hash"]),
        "pinned_regression_manifest_sha256": str(regression["manifest_sha256"]),
        "schema": "arc3.stage16.stage13-regression-binding.v0.1",
        "status": "PASS",
        "verified": True,
    }


def run_stage13_regression(
    repository: Path,
    output_root: Path,
    *,
    git_commit: str,
) -> dict[str, JSONValue]:
    """Rerun and gate the exact packaged Stage 13 threshold declaration."""

    binding = validate_stage13_regression_binding(repository)
    thresholds = load_performance_thresholds()
    basis = cast(dict[str, Any], thresholds["basis"])
    agents = cast(list[str], basis["agents"])
    seeds = cast(list[int], basis["seeds"])
    outcome = run_evaluation(
        EvaluationConfig(
            partition=str(basis["partition"]),
            agents=tuple(agents),
            seeds=tuple(seeds),
            max_actions=int(basis["max_actions"]),
            max_resets=int(basis["max_resets"]),
            timeout_seconds=float(basis["timeout_seconds"]),
            output_root=output_root.resolve(),
            evaluation_id=f"stage16-regression-{git_commit[:12]}",
        )
    )
    artifact_verification = verify_evaluation_artifacts(outcome.directory)
    current = cast(dict[str, Any], outcome.summary.get("performance_regression"))
    verified = (
        outcome.status == "PASS"
        and current.get("status") == "PASS"
        and artifact_verification.get("verified") is True
    )
    return {
        "artifact_verification": cast(dict[str, JSONValue], artifact_verification),
        "current_evaluation_id": outcome.evaluation_id,
        "current_manifest_sha256": sha256_file(outcome.directory / "manifest.json"),
        "current_regression": cast(dict[str, JSONValue], current),
        "label": "synthetic",
        "pinned_evidence_path": binding["evidence_path"],
        "pinned_evidence_sha256": binding["evidence_sha256"],
        "pinned_measured_commit": _STAGE13_MEASURED_COMMIT,
        "pinned_regression_manifest_sha256": binding["pinned_regression_manifest_sha256"],
        "schema": "arc3.stage16.stage13-regression.v0.1",
        "status": "PASS" if verified else "FAILED_MECHANISM",
        "verified": verified,
    }


__all__ = ["run_stage13_regression", "validate_stage13_regression_binding"]
