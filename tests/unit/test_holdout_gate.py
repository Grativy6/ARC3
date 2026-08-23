from __future__ import annotations

import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

import pytest

from arc3.errors import EvaluationError
from arc3.evaluation import holdout_gate as holdout_gate_module
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
from arc3.evaluation.integrity_authority import COMPOSITE_INTEGRITY_SCHEMA
from arc3.evaluation.public import PublicEvaluationConfig
from arc3.evaluation.public_runner import _worker_holdout_authorization, run_public_evaluation
from arc3.evaluation.stage10_regression import PREDECLARATION_SHA256, STAGE10_RESULT_SCHEMA

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


def test_holdout_source_identity_ignores_inherited_git_redirection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = _init_source(tmp_path / "source", evaluation_marker="expected")
    monkeypatch.setenv("GIT_DIR", str(tmp_path / "redirected.git"))
    monkeypatch.setenv("git_index_file", str(tmp_path / "redirected.index"))

    observed = source_identity(tmp_path / "source")

    assert observed == expected


def test_holdout_source_identity_ignores_local_replace_refs(tmp_path: Path) -> None:
    source = tmp_path / "source"
    original = _init_source(source, evaluation_marker="original")
    marker = source / "src/arc3/evaluation/infrastructure.py"
    marker.write_text("MARKER = 'replacement'\n", encoding="utf-8")
    _run_git(source, "add", marker.relative_to(source).as_posix())
    _run_git(source, "commit", "--quiet", "-m", "replacement")
    replacement_commit = _run_git(source, "rev-parse", "HEAD")
    _run_git(source, "config", "core.autocrlf", "false")
    subprocess.run(
        (
            "git",
            "-C",
            str(source),
            "--no-replace-objects",
            "checkout",
            "--quiet",
            "--force",
            "--detach",
            original.commit,
        ),
        check=True,
        timeout=30,
    )
    _run_git(source, "replace", original.commit, replacement_commit)

    observed = source_identity(source)

    assert observed == original


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


def _stage10(
    identity: SourceIdentity,
    *,
    composite_file_sha256: str,
    composite_core_hash: str,
    invocation_ledger: dict[str, object],
    status: str = "PASS",
) -> dict[str, Any]:
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
        "invocation_ledger": invocation_ledger,
        "plan_hash": sha256_bytes(b"synthetic-stage10-plan"),
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
                "measurements": (
                    {
                        "composite_integrity_core_hash": composite_core_hash,
                        "composite_integrity_file_sha256": composite_file_sha256,
                        "composite_integrity_schema": COMPOSITE_INTEGRITY_SCHEMA,
                    }
                    if suite == "competition-integrity"
                    else {}
                ),
                "predicates": {"accepted": status == "PASS"},
                "suite_id": suite,
            }
            for suite in SUITES
        ],
    }
    return seal_object(payload, hash_field="artifact_core_hash")


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
        self.stage09_attempt_root = root / "stage09-attempt"
        self.stage09_exposure = root / "stage09-exposure.jsonl"
        self.stage09_finalization_file = "sha256:" + "a" * 64
        self.stage09_finalization_core = "sha256:" + "b" * 64
        self.stage10 = root / "stage10.json"
        self.stage10_attempt_root = root / "stage10-attempt"
        ledger_path = self.stage10_attempt_root / "invocations.jsonl"
        _write(ledger_path, b"{}\n")
        self.stage10_ledger: dict[str, object] = {
            "byte_length": ledger_path.stat().st_size,
            "path": ledger_path.resolve().as_posix(),
            "sha256": sha256_file(ledger_path),
        }
        self.integrity = root / "integrity.json"
        self.stage09_file, self.stage09_core = _artifact(
            self.stage09,
            _stage09(self.development, manifest_sha256=self.manifest_sha256),
        )
        integrity = seal_object(
            {
                "assurance_limitation": (
                    "Package and development scans are static; dynamic-import and native-extension "
                    "containment are not proven; Build 001 public identifiers were not fully evaluated."
                ),
                "claim": "BOUNDED_STATIC_COMPETITION_INTEGRITY_WITH_OPAQUE_HOLDOUT",
                "full_public_integrity_status": ("NOT_EVALUATED_BUILD_001_PUBLIC_IDENTIFIERS"),
                "opaque_public_manifest_sha256": self.manifest_sha256,
                "schema": COMPOSITE_INTEGRITY_SCHEMA,
                "semantic_public_manifest_access": False,
                "status": "PASS",
            },
            hash_field="artifact_core_hash",
        )
        self.integrity_file, self.integrity_core = _artifact(self.integrity, integrity)
        self.stage10_file, self.stage10_core = _artifact(
            self.stage10,
            _stage10(
                self.execution,
                composite_file_sha256=self.integrity_file,
                composite_core_hash=self.integrity_core,
                invocation_ledger=self.stage10_ledger,
            ),
        )
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
            "stage09_attempt_root": self.stage09_attempt_root,
            "stage09_exposure_path": self.stage09_exposure,
            "stage09_file_sha256": self.stage09_file,
            "stage09_core_hash": self.stage09_core,
            "stage09_terminal_finalization_sha256": self.stage09_finalization_file,
            "stage09_terminal_finalization_hash": self.stage09_finalization_core,
            "stage10_path": self.stage10,
            "stage10_attempt_root": self.stage10_attempt_root,
            "stage10_file_sha256": self.stage10_file,
            "stage10_core_hash": self.stage10_core,
            "integrity_path": self.integrity,
            "integrity_file_sha256": self.integrity_file,
            "integrity_core_hash": self.integrity_core,
            "development_source_root": self.development_root,
            "execution_source_root": self.execution_root,
            "expected_execution_commit": self.execution.commit,
            "expected_manifest_sha256": self.manifest_sha256,
            "evaluation": self.evaluation,
            "generated_at": NOW,
        }
        arguments.update(overrides)
        return create_holdout_gate_receipt(**arguments)  # type: ignore[arg-type]


@pytest.fixture
def evidence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Evidence:
    result = Evidence(tmp_path)

    def validate_composite(
        path: Path,
        *,
        expected_file_sha256: str,
        expected_core_hash: str,
        source_root: Path,
    ) -> dict[str, Any]:
        raw = path.read_bytes()
        document = cast(dict[str, Any], json.loads(raw))
        if sha256_bytes(raw) != expected_file_sha256:
            raise EvaluationError("composite integrity artifact file hash changed")
        if document.get("artifact_core_hash") != expected_core_hash:
            raise EvaluationError("composite integrity artifact core hash changed")
        if source_identity(source_root).clean_worktree is not True:
            raise EvaluationError("composite integrity source changed")
        return document

    monkeypatch.setattr(
        holdout_gate_module,
        "validate_composite_integrity_authority",
        validate_composite,
    )
    monkeypatch.setattr(holdout_gate_module, "_require_runtime_import_origin", lambda _root: None)

    def verify_stage09(**arguments: object) -> dict[str, Any]:
        return seal_object(
            {
                "attempt_root": Path(cast(Path, arguments["attempt_root"])).resolve().as_posix(),
                "competition_integrity": True,
                "evidence_integrity": True,
                "execution_complete": True,
                "exposure": {"path": Path(cast(Path, arguments["exposure"])).resolve().as_posix()},
                "gate": {"passed": True},
                "output": {
                    "artifact_core_hash": arguments["expected_artifact_core_hash"],
                    "file_sha256": arguments["expected_output_sha256"],
                    "path": Path(cast(Path, arguments["output"])).resolve().as_posix(),
                },
                "passed": True,
                "prior_authority": {},
                "schema": "arc3.build-001.stage-09-terminal-verification.v0.2",
                "source_end": {"passed": True},
                "source_root": Path(cast(Path, arguments["source_root"])).resolve().as_posix(),
                "source_stable": True,
                "status": "PASS",
                "terminal_finalization": {
                    "artifact_core_hash": arguments["expected_terminal_finalization_hash"],
                    "file_sha256": arguments["expected_terminal_finalization_sha256"],
                },
                "work_authority": {"passed": True},
            },
            hash_field="verification_hash",
        )

    monkeypatch.setattr(holdout_gate_module, "_stage09_graph_verification", verify_stage09)
    monkeypatch.setattr(holdout_gate_module, "_stage10_graph_clear", lambda **_kwargs: True)
    return result


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


def test_stage10_terminal_graph_failure_cannot_earn_holdout(
    evidence: Evidence, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(holdout_gate_module, "_stage10_graph_clear", lambda **_kwargs: False)
    document = evidence.gate()
    assert document["decision"] == HoldoutDecision.NOT_EARNED.value
    assert cast(dict[str, bool], document["criteria"])["stage10_pass"] is False


def test_stage09_terminal_graph_failure_cannot_earn_holdout(
    evidence: Evidence, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(holdout_gate_module, "_stage09_graph_verification", lambda **_kwargs: None)
    document = evidence.gate()
    assert document["decision"] == HoldoutDecision.NOT_EARNED.value
    assert cast(dict[str, bool], document["criteria"])["stage09_pass"] is False


def test_earned_revalidation_rechecks_stage09_graph_before_manifest(
    evidence: Evidence, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = holdout_gate_module._stage09_graph_verification
    calls = 0

    def graph(**arguments: object) -> dict[str, object] | None:
        nonlocal calls
        calls += 1
        return original(**arguments) if calls == 1 else None

    monkeypatch.setattr(holdout_gate_module, "_stage09_graph_verification", graph)
    gate = _written_gate(evidence.manifest.parent, evidence.gate())
    evidence.manifest.unlink()
    with pytest.raises(EvaluationError, match="Stage 09 complete terminal graph"):
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
    assert calls == 2


def test_earned_revalidation_rechecks_stage10_graph_before_manifest(
    evidence: Evidence, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = 0

    def graph_clear(**_kwargs: object) -> bool:
        nonlocal calls
        calls += 1
        return calls == 1

    monkeypatch.setattr(holdout_gate_module, "_stage10_graph_clear", graph_clear)
    gate = _written_gate(evidence.manifest.parent, evidence.gate())
    evidence.manifest.unlink()
    with pytest.raises(EvaluationError, match="criteria no longer revalidate"):
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
    assert calls == 2


def test_stage10_ledger_path_cannot_be_resigned_into_gate(evidence: Evidence) -> None:
    stage10 = cast(dict[str, Any], json.loads(evidence.stage10.read_bytes()))
    ledger = cast(dict[str, object], stage10["invocation_ledger"])
    ledger["path"] = (evidence.stage10_attempt_root / "other.jsonl").resolve().as_posix()
    stage10 = seal_object(stage10, hash_field="artifact_core_hash")
    file_sha, core = _artifact(evidence.stage10, stage10)
    with pytest.raises(EvaluationError, match="ledger binding is invalid"):
        evidence.gate(stage10_file_sha256=file_sha, stage10_core_hash=core)


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
    body = cast(dict[str, Any], json.loads(evidence.integrity.read_bytes()))
    body["generated_at"] = NOW
    _artifact(evidence.integrity, seal_object(body, hash_field="artifact_core_hash"))
    with pytest.raises(EvaluationError, match="file hash changed"):
        evidence.gate(integrity_file_sha256=original_integrity_file)


def test_stage10_failed_result_yields_not_earned_and_nonconsumption(evidence: Evidence) -> None:
    stage10 = _stage10(
        evidence.execution,
        composite_file_sha256=evidence.integrity_file,
        composite_core_hash=evidence.integrity_core,
        invocation_ledger=evidence.stage10_ledger,
        status="FAILED_MECHANISM",
    )
    evidence.stage10_file, evidence.stage10_core = _artifact(evidence.stage10, stage10)
    document = evidence.gate()
    assert document["decision"] == HoldoutDecision.NOT_EARNED.value
    assert cast(dict[str, bool], document["criteria"])["stage10_pass"] is False
    gate = _written_gate(evidence.manifest.parent, document)

    receipt = create_nonconsumption_receipt(
        gate_path=gate[0],
        gate_file_sha256=gate[1],
        gate_core_hash=gate[2],
        generated_at=NOW,
    )
    validate_nonconsumption_receipt(
        receipt,
        gate_path=gate[0],
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

    stage10 = _stage10(
        evidence.execution,
        composite_file_sha256=evidence.integrity_file,
        composite_core_hash=evidence.integrity_core,
        invocation_ledger=evidence.stage10_ledger,
        status="FAILED_MECHANISM",
    )
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
        public.PublicPartitionManifest,
        "load",
        staticmethod(forbidden_manifest),
    )
    monkeypatch.setattr(public_runner, "inventory_local_assets", forbidden_inventory)

    with pytest.raises(EvaluationError, match="was not earned"):
        run_public_evaluation(config)
    assert called == {"manifest": False, "inventory": False}


def test_nonconsumption_tamper_is_detected(evidence: Evidence) -> None:
    stage10 = _stage10(
        evidence.execution,
        composite_file_sha256=evidence.integrity_file,
        composite_core_hash=evidence.integrity_core,
        invocation_ledger=evidence.stage10_ledger,
        status="FAILED_MECHANISM",
    )
    evidence.stage10_file, evidence.stage10_core = _artifact(evidence.stage10, stage10)
    gate = _written_gate(evidence.manifest.parent, evidence.gate())
    receipt = create_nonconsumption_receipt(
        gate_path=gate[0],
        gate_file_sha256=gate[1],
        gate_core_hash=gate[2],
        generated_at=NOW,
    )
    receipt["gameplay_opened"] = True
    with pytest.raises(EvaluationError, match="invalid"):
        validate_nonconsumption_receipt(
            receipt,
            gate_path=gate[0],
        )


def test_not_earned_nonconsumption_never_needs_manifest_bytes(evidence: Evidence) -> None:
    stage10 = _stage10(
        evidence.execution,
        composite_file_sha256=evidence.integrity_file,
        composite_core_hash=evidence.integrity_core,
        invocation_ledger=evidence.stage10_ledger,
        status="FAILED_MECHANISM",
    )
    evidence.stage10_file, evidence.stage10_core = _artifact(evidence.stage10, stage10)
    gate = _written_gate(evidence.manifest.parent, evidence.gate())
    evidence.manifest.unlink()

    receipt = create_nonconsumption_receipt(
        gate_path=gate[0],
        gate_file_sha256=gate[1],
        gate_core_hash=gate[2],
        generated_at=NOW,
    )
    validate_nonconsumption_receipt(receipt, gate_path=gate[0])
    assert receipt["environment_actions"] == 0
    assert receipt["holdout"]["manifest_parsed"] is False


def test_holdout_worker_cannot_skip_authorization_by_changing_surface() -> None:
    with pytest.raises(EvaluationError, match="surface is not online-public"):
        _worker_holdout_authorization(
            {},
            {"partition": "public-holdout", "surface": "local-public"},
        )


def test_gate_and_runner_imports_do_not_import_environment_adapter() -> None:
    code = (
        "import sys;from pathlib import Path;"
        "sys.path.insert(0,str(Path(sys.argv[1]).resolve()/'src'));"
        "import arc3.evaluation.holdout_gate,arc3.evaluation.public,"
        "arc3.evaluation.public_runner;"
        "assert 'arc3.adapters.arc_agi' not in sys.modules"
    )
    completed = subprocess.run(
        (sys.executable, "-I", "-c", code, str(ROOT)),
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr


def test_runtime_import_origin_must_match_explicit_source_root(tmp_path: Path) -> None:
    holdout_gate_module._require_runtime_import_origin(ROOT)

    with pytest.raises(EvaluationError, match="execution source"):
        holdout_gate_module._require_runtime_import_origin(tmp_path)


@pytest.mark.parametrize(
    "module_name",
    ("arc3.integrity.scanner", "arc3.evaluation.artifacts"),
)
def test_runtime_import_closure_rejects_mixed_validator_module(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    module_name: str,
) -> None:
    module = sys.modules[module_name]
    mixed_origin = tmp_path / module_name.replace(".", "/").replace(
        "/scanner", "/scanner.py"
    ).replace("/artifacts", "/artifacts.py")
    mixed_origin.parent.mkdir(parents=True, exist_ok=True)
    mixed_origin.write_text("# mixed validation tree\n", encoding="utf-8")
    monkeypatch.setattr(module, "__file__", str(mixed_origin))

    with pytest.raises(EvaluationError, match="outside the execution source"):
        holdout_gate_module._require_runtime_import_origin(ROOT)
