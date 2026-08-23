from __future__ import annotations

import subprocess
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

import pytest

from arc3.errors import EvaluationError
from arc3.evaluation.artifacts import canonical_json_bytes, seal_object, sha256_bytes, sha256_file
from arc3.evaluation.development_recovery import AGGREGATE_SCHEMA as STAGE09_SCHEMA
from arc3.evaluation.holdout_gate import (
    COMPETITION_CONFIG_PATH,
    STAGE11_GATE_SCHEMA,
    HoldoutDecision,
    HoldoutEvaluationDeclaration,
    SourceIdentity,
    create_holdout_gate_receipt,
    create_nonconsumption_receipt,
    load_bound_holdout_gate,
    revalidate_earned_holdout_gate,
    source_identity,
    validate_nonconsumption_receipt,
)
from arc3.evaluation.public import PublicEvaluationConfig
from arc3.evaluation.public_runner import run_public_evaluation
from arc3.evaluation.stage10_regression import PREDECLARATION_SHA256, STAGE10_RESULT_SCHEMA
from arc3.integrity import INTEGRITY_SCHEMA, IntegrityReceipt
from arc3.types import JSONValue

ROOT = Path(__file__).resolve().parents[2]
MANIFEST_BYTES = b"opaque-sealed-manifest\n"
NOW = "2026-08-22T12:00:00.000000Z"
SUITES = (
    "action-equivariance",
    "checkpoint-replay",
    "competition-integrity",
    "palette-equivariance",
    "resource-profile",
    "rule-change",
    "stage13-evaluate",
    "stage13-verify",
    "stage14-ablations",
)


def _run_git(root: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ("git", *arguments),
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return completed.stdout.strip()


def _write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _init_source(root: Path, *, evaluation_marker: str) -> SourceIdentity:
    _write(root / COMPETITION_CONFIG_PATH, (ROOT / COMPETITION_CONFIG_PATH).read_bytes())
    _write(
        root / "docs/workflows/001-local-public-failure-recovery.md",
        (ROOT / "docs/workflows/001-local-public-failure-recovery.md").read_bytes(),
    )
    _write(root / "agent/my_agent.py", b"from arc3.policy.controller import object\n")
    _write(root / "src/arc3/__init__.py", b"\n")
    _write(root / "src/arc3/policy/__init__.py", b"\n")
    _write(root / "src/arc3/policy/controller.py", b"POLICY = 'generic'\n")
    _write(
        root / "src/arc3/evaluation/infrastructure.py",
        f"MARKER = {evaluation_marker!r}\n".encode(),
    )
    _write(root / "pyproject.toml", b"[project]\nname='fixture'\nversion='0'\n")
    _write(root / "uv.lock", b"version = 1\n")
    _run_git(root, "init", "--quiet")
    _run_git(root, "config", "user.email", "fixture@example.invalid")
    _run_git(root, "config", "user.name", "Fixture")
    _run_git(root, "add", ".")
    _run_git(root, "commit", "--quiet", "-m", "fixture")
    return source_identity(root)


def _source_receipt(identity: SourceIdentity) -> dict[str, object]:
    return {
        "dirty_worktree": False,
        "first_party_source_sha256": identity.first_party_source_sha256,
        "git_commit": identity.commit,
        "git_tree": identity.tree,
        "passed": True,
    }


def _stage09(
    identity: SourceIdentity,
    *,
    manifest_sha256: str,
    status: str = "PASS",
) -> dict[str, Any]:
    gate_pass = status == "PASS"
    payload: dict[str, Any] = {
        "asset_end": {"passed": gate_pass},
        "cell_count": 96,
        "evidence_label": "local-public",
        "execution_complete": gate_pass,
        "expected_cell_count": 96,
        "gate": {
            "all_evidence_verifies": gate_pass,
            "build_001_full_beats_b0": gate_pass,
            "competition_integrity": gate_pass,
            "distinct_new_completed_games": gate_pass,
            "normal_termination_fraction": gate_pass,
        },
        "holdout": {
            "identities_loaded": 0,
            "manifest_loaded_as_metadata": False,
            "public_holdout_gameplay_events": 0,
        },
        "preflight": {
            "competition_integrity": {"static": {"passed": gate_pass}},
            "public_manifest_hashes": {
                "build_000": manifest_sha256,
                "build_001": manifest_sha256,
            },
            "sources": {"build_001": _source_receipt(identity)},
        },
        "resources": {
            "wall_measurement_complete": gate_pass,
            "wall_within_limit": gate_pass,
        },
        "schema": STAGE09_SCHEMA,
        "source_end": {"build_001": _source_receipt(identity)},
        "source_stable": gate_pass,
        "status": status,
    }
    return seal_object(payload, hash_field="artifact_core_hash")


def _stage10(identity: SourceIdentity, *, status: str = "PASS") -> dict[str, Any]:
    disposition = "PASS" if status == "PASS" else "FAILED_MECHANISM"
    source = {
        "clean_worktree": True,
        "commit": identity.commit,
        "exact_frozen_commit": True,
        "tree": identity.tree,
        "verified": True,
    }
    payload: dict[str, Any] = {
        "claim": "NO_GENERALIZATION_CLAIM",
        "evidence_label": "synthetic",
        "infrastructure_failure": None,
        "predeclaration_sha256": PREDECLARATION_SHA256,
        "schema": STAGE10_RESULT_SCHEMA,
        "source_identity_end": source,
        "source_identity_start": source,
        "status": status,
        "suite_validations": [
            {
                "artifact_valid": True,
                "disposition": disposition,
                "errors": [],
                "measurements": {},
                "predicates": {"accepted": status == "PASS"},
                "suite_id": suite,
            }
            for suite in SUITES
        ],
    }
    return seal_object(payload, hash_field="artifact_core_hash")


def _integrity(identity: SourceIdentity, manifest_sha256: str) -> IntegrityReceipt:
    checks: dict[str, JSONValue] = {
        name: {"passed": True}
        for name in (
            "archive_static",
            "policy_static",
            "secret_scan",
            "source_identity",
            "supply_chain",
        )
    }
    checks["supply_chain"] = {"passed": True, "status": "PASS"}
    body: dict[str, JSONValue] = {
        "assurance_scope": {
            "kind": "static-only",
            "runtime_socket_denial": "OUT_OF_SCOPE",
            "scanner_network_mode": "offline-by-construction",
        },
        "checks": checks,
        "finding_counts": {"blocking": 0, "total": 0, "warnings": 0},
        "git": {"commit": identity.commit, "dirty_worktree": False},
        "inputs": {"manifest_sha256": manifest_sha256},
        "passed": True,
        "schema": INTEGRITY_SCHEMA,
        "source_hashes": {
            COMPETITION_CONFIG_PATH: identity.competition_config_file_sha256,
            "uv.lock": identity.dependency_lock_sha256,
        },
    }
    return IntegrityReceipt(body=body)


def _artifact(path: Path, document: dict[str, Any]) -> tuple[str, str]:
    _write(path, canonical_json_bytes(document))
    return sha256_file(path), cast(str, document["artifact_core_hash"])


class Evidence:
    def __init__(self, root: Path) -> None:
        self.development_root = root / "development"
        self.execution_root = root / "execution"
        self.development = _init_source(self.development_root, evaluation_marker="development")
        self.execution = _init_source(self.execution_root, evaluation_marker="execution")
        assert self.development.policy_projection_sha256 == self.execution.policy_projection_sha256
        assert (
            self.development.first_party_source_sha256 != self.execution.first_party_source_sha256
        )
        self.manifest = root / "sealed.bin"
        _write(self.manifest, MANIFEST_BYTES)
        self.manifest_sha256 = sha256_bytes(MANIFEST_BYTES)
        self.stage09 = root / "stage09.json"
        self.stage10 = root / "stage10.json"
        self.integrity = root / "integrity.json"
        self.stage09_file, self.stage09_core = _artifact(
            self.stage09,
            _stage09(self.development, manifest_sha256=self.manifest_sha256),
        )
        self.stage10_file, self.stage10_core = _artifact(self.stage10, _stage10(self.execution))
        integrity = _integrity(self.execution, self.manifest_sha256)
        _write(self.integrity, integrity.canonical_bytes())
        self.integrity_file = sha256_file(self.integrity)
        self.integrity_core = integrity.receipt_sha256
        self.evaluation = HoldoutEvaluationDeclaration(
            evaluation_id="build001-stage12-sealed",
            agents=("full",),
            seeds=(7, 11),
            max_actions=80,
            max_resets=8,
            timeout_seconds=120.0,
        )

    def gate(self, **overrides: object) -> dict[str, Any]:
        arguments: dict[str, object] = {
            "stage09_path": self.stage09,
            "stage09_file_sha256": self.stage09_file,
            "stage09_core_hash": self.stage09_core,
            "stage10_path": self.stage10,
            "stage10_file_sha256": self.stage10_file,
            "stage10_core_hash": self.stage10_core,
            "integrity_path": self.integrity,
            "integrity_file_sha256": self.integrity_file,
            "integrity_receipt_sha256": self.integrity_core,
            "development_source_root": self.development_root,
            "execution_source_root": self.execution_root,
            "expected_execution_commit": self.execution.commit,
            "manifest_path": self.manifest,
            "expected_manifest_sha256": self.manifest_sha256,
            "evaluation": self.evaluation,
            "generated_at": NOW,
        }
        arguments.update(overrides)
        return create_holdout_gate_receipt(**arguments)  # type: ignore[arg-type]


@pytest.fixture
def evidence(tmp_path: Path) -> Evidence:
    return Evidence(tmp_path)


def _written_gate(root: Path, document: dict[str, Any]) -> tuple[Path, str, str]:
    path = root / "gate.json"
    file_sha, core = _artifact(path, document)
    return path, file_sha, core


def _public_config(evidence: Evidence, gate: tuple[Path, str, str]) -> PublicEvaluationConfig:
    gate_path, gate_file, gate_core = gate
    return PublicEvaluationConfig(
        partition="public-holdout",
        agents=("full",),
        seeds=(7, 11),
        frozen_commit=evidence.execution.commit,
        max_actions=80,
        max_resets=8,
        timeout_seconds=120.0,
        manifest_path=evidence.manifest,
        evaluation_id=evidence.evaluation.evaluation_id,
        allow_public_holdout=True,
        holdout_gate_receipt=gate_path,
        holdout_gate_file_sha256=gate_file,
        holdout_gate_core_hash=gate_core,
        stage09_result=evidence.stage09,
        stage10_result=evidence.stage10,
        competition_integrity_receipt=evidence.integrity,
        milestone_id=evidence.evaluation.milestone_id,
    )


def test_all_five_criteria_are_required_and_revalidate(evidence: Evidence) -> None:
    document = evidence.gate()
    assert document["schema"] == STAGE11_GATE_SCHEMA
    assert document["decision"] == HoldoutDecision.EARNED.value
    assert all(cast(dict[str, bool], document["criteria"]).values())
    gate_path, gate_file, gate_core = _written_gate(evidence.manifest.parent, document)

    validated = revalidate_earned_holdout_gate(
        gate_path=gate_path,
        gate_file_sha256=gate_file,
        gate_core_hash=gate_core,
        stage09_path=evidence.stage09,
        stage10_path=evidence.stage10,
        integrity_path=evidence.integrity,
        manifest_path=evidence.manifest,
        source_root=evidence.execution_root,
    )
    assert validated.decision is HoldoutDecision.EARNED
    assert validated.opaque_count == 10
    assert validated.receipt["holdout"] == {
        "identities_loaded": 0,
        "manifest_parsed": False,
        "manifest_sha256": evidence.manifest_sha256,
        "opaque_partition_count": 10,
    }


def test_stage09_schema_drift_is_rejected_even_when_resigned(evidence: Evidence) -> None:
    drifted = _stage09(evidence.development, manifest_sha256=evidence.manifest_sha256)
    drifted["schema"] = "arc3.build-001.stage-09-aggregate.v9"
    drifted = seal_object(drifted, hash_field="artifact_core_hash")
    file_sha, core = _artifact(evidence.stage09, drifted)
    with pytest.raises(EvaluationError, match="schema changed"):
        evidence.gate(stage09_file_sha256=file_sha, stage09_core_hash=core)


def test_bound_stage09_and_integrity_resigning_cannot_replace_authority(
    evidence: Evidence,
) -> None:
    original_stage09_file = evidence.stage09_file
    altered = _stage09(
        evidence.development,
        manifest_sha256=evidence.manifest_sha256,
        status="FAILED_MECHANISM",
    )
    _artifact(evidence.stage09, altered)
    with pytest.raises(EvaluationError, match="file hash changed"):
        evidence.gate(stage09_file_sha256=original_stage09_file)

    _artifact(
        evidence.stage09,
        _stage09(evidence.development, manifest_sha256=evidence.manifest_sha256),
    )
    original_integrity_file = evidence.integrity_file
    receipt = _integrity(evidence.execution, evidence.manifest_sha256)
    body = dict(receipt.body)
    body["generated_at"] = NOW
    _write(evidence.integrity, IntegrityReceipt(body=body).canonical_bytes())
    with pytest.raises(EvaluationError, match="file hash changed"):
        evidence.gate(integrity_file_sha256=original_integrity_file)


def test_stage10_failed_result_yields_not_earned_and_nonconsumption(evidence: Evidence) -> None:
    stage10 = _stage10(evidence.execution, status="FAILED_MECHANISM")
    evidence.stage10_file, evidence.stage10_core = _artifact(evidence.stage10, stage10)
    document = evidence.gate()
    assert document["decision"] == HoldoutDecision.NOT_EARNED.value
    assert cast(dict[str, bool], document["criteria"])["stage10_pass"] is False
    gate = _written_gate(evidence.manifest.parent, document)

    receipt = create_nonconsumption_receipt(
        gate_path=gate[0],
        gate_file_sha256=gate[1],
        gate_core_hash=gate[2],
        manifest_path=evidence.manifest,
        generated_at=NOW,
    )
    validate_nonconsumption_receipt(
        receipt,
        gate_path=gate[0],
        manifest_path=evidence.manifest,
    )
    assert receipt["gameplay_opened"] is False
    assert receipt["environment_adapter_loaded"] is False
    assert receipt["environment_actions"] == 0


def test_nonconsumption_is_unreachable_for_an_earned_gate(evidence: Evidence) -> None:
    gate = _written_gate(evidence.manifest.parent, evidence.gate())
    with pytest.raises(EvaluationError, match="only for HOLDOUT_NOT_EARNED"):
        create_nonconsumption_receipt(
            gate_path=gate[0],
            gate_file_sha256=gate[1],
            gate_core_hash=gate[2],
            manifest_path=evidence.manifest,
            generated_at=NOW,
        )


def test_resigned_stage11_tamper_fails_external_hash_anchor(evidence: Evidence) -> None:
    document = evidence.gate()
    gate_path, gate_file, gate_core = _written_gate(evidence.manifest.parent, document)
    tampered = deepcopy(document)
    cast(dict[str, bool], tampered["criteria"])["stage10_pass"] = False
    tampered["decision"] = HoldoutDecision.NOT_EARNED.value
    tampered = seal_object(tampered, hash_field="artifact_core_hash")
    _artifact(gate_path, tampered)

    with pytest.raises(EvaluationError, match="file hash changed"):
        load_bound_holdout_gate(
            gate_path,
            expected_file_sha256=gate_file,
            expected_core_hash=gate_core,
        )


@pytest.mark.parametrize(
    "relative, replacement",
    [
        ("src/arc3/policy/controller.py", b"POLICY = 'drifted'\n"),
        (COMPETITION_CONFIG_PATH, b"{}\n"),
        ("uv.lock", b"version = 99\n"),
    ],
)
def test_policy_config_and_lock_drift_block_earned_revalidation(
    evidence: Evidence,
    relative: str,
    replacement: bytes,
) -> None:
    gate = _written_gate(evidence.manifest.parent, evidence.gate())
    _write(evidence.execution_root / relative, replacement)
    with pytest.raises(EvaluationError):
        revalidate_earned_holdout_gate(
            gate_path=gate[0],
            gate_file_sha256=gate[1],
            gate_core_hash=gate[2],
            stage09_path=evidence.stage09,
            stage10_path=evidence.stage10,
            integrity_path=evidence.integrity,
            manifest_path=evidence.manifest,
            source_root=evidence.execution_root,
        )


def test_bare_boolean_is_not_holdout_authority(
    evidence: Evidence, monkeypatch: pytest.MonkeyPatch
) -> None:
    from arc3.evaluation import public

    monkeypatch.setattr(public, "_repository_root", lambda: evidence.execution_root)
    config = PublicEvaluationConfig(
        partition="public-holdout",
        agents=("full",),
        seeds=(7, 11),
        frozen_commit=evidence.execution.commit,
        evaluation_id="sealed",
        allow_public_holdout=True,
    )
    with pytest.raises(EvaluationError, match="authorization is incomplete"):
        public.validate_holdout_authorization(config)


def test_earned_authorization_fully_revalidates_bound_evidence(
    evidence: Evidence, monkeypatch: pytest.MonkeyPatch
) -> None:
    from arc3.evaluation import public

    gate = _written_gate(evidence.manifest.parent, evidence.gate())
    monkeypatch.setattr(public, "_repository_root", lambda: evidence.execution_root)
    authorization = public.validate_holdout_authorization(_public_config(evidence, gate))
    assert authorization is not None
    assert authorization.decision is HoldoutDecision.EARNED


def test_not_earned_runner_cannot_load_manifest_or_inventory_assets(
    evidence: Evidence, monkeypatch: pytest.MonkeyPatch
) -> None:
    from arc3.evaluation import public, public_runner

    stage10 = _stage10(evidence.execution, status="FAILED_MECHANISM")
    evidence.stage10_file, evidence.stage10_core = _artifact(evidence.stage10, stage10)
    gate = _written_gate(evidence.manifest.parent, evidence.gate())
    config = _public_config(evidence, gate)
    called = {"manifest": False, "inventory": False}

    def forbidden_manifest(*_args: object, **_kwargs: object) -> None:
        called["manifest"] = True
        raise AssertionError("public manifest parsing was reachable")

    def forbidden_inventory(*_args: object, **_kwargs: object) -> None:
        called["inventory"] = True
        raise AssertionError("public asset inventory was reachable")

    monkeypatch.setattr(public, "_repository_root", lambda: evidence.execution_root)
    monkeypatch.setattr(
        public_runner.PublicPartitionManifest,
        "load",
        staticmethod(forbidden_manifest),
    )
    monkeypatch.setattr(public_runner, "inventory_local_assets", forbidden_inventory)

    with pytest.raises(EvaluationError, match="was not earned"):
        run_public_evaluation(config)
    assert called == {"manifest": False, "inventory": False}


def test_nonconsumption_tamper_is_detected(evidence: Evidence) -> None:
    stage10 = _stage10(evidence.execution, status="FAILED_MECHANISM")
    evidence.stage10_file, evidence.stage10_core = _artifact(evidence.stage10, stage10)
    gate = _written_gate(evidence.manifest.parent, evidence.gate())
    receipt = create_nonconsumption_receipt(
        gate_path=gate[0],
        gate_file_sha256=gate[1],
        gate_core_hash=gate[2],
        manifest_path=evidence.manifest,
        generated_at=NOW,
    )
    receipt["gameplay_opened"] = True
    with pytest.raises(EvaluationError, match="invalid"):
        validate_nonconsumption_receipt(
            receipt,
            gate_path=gate[0],
            manifest_path=evidence.manifest,
        )
