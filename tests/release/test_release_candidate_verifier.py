"""Focused contract tests for the Stage 18 release-candidate verifier."""

from __future__ import annotations

import hashlib
import io
import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
import scripts.release_candidate_verifier as verifier
from scripts.release_candidate_verifier import (
    EXPECTATION_HASH_FIELD,
    EXPECTATION_SCHEMA,
    SCHEMA,
    CommandSpec,
    _complete_artifact_set,
    _receipt_bytes,
    _sanitized_environment,
    benchmark_basis_identity,
    build_plan,
    canonical_json_bytes,
    compare_benchmark,
    compare_packages,
    discover_uv_command,
    load_benchmark_expectation,
    official_smoke_available,
    package_projection,
    prepare_fresh_output_root,
    prepare_fresh_transient_root,
    run_command,
    scan_generated_logs,
    sha256_bytes,
    sha256_file,
    verify_release_receipt,
)

from arc3.evaluation.artifacts import canonical_json_bytes as evaluation_canonical_json_bytes
from arc3.evaluation.public import PublicGameEntry, local_asset_identity
from arc3.packaging.builder import build_kaggle_candidate
from arc3.packaging.util import canonical_json_bytes as package_canonical_json_bytes


def _write_self_hashed(path: Path, body: dict[str, object], hash_field: str) -> None:
    document = dict(body)
    document[hash_field] = sha256_bytes(canonical_json_bytes(body))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(document))


def _expectation() -> dict[str, object]:
    return {
        "schema": EXPECTATION_SCHEMA,
        "basis": {"surface": "synthetic"},
        "configuration": {
            "agents": ["cycle"],
            "max_actions": 4,
            "max_resets": 1,
            "partition": "smoke",
            "seeds": [7],
            "timeout_seconds": 30.0,
        },
        "public_partition_manifest_sha256": f"sha256:{'1' * 64}",
        "expected_projection": {
            "configuration": {
                "agents": ["cycle"],
                "max_actions": 4,
                "max_resets": 1,
                "network_mode": "offline",
                "partition": "smoke",
                "seeds": [7],
                "surface": "synthetic",
                "timeout_seconds": 30.0,
            },
            "runs": [
                {
                    "actions": 3,
                    "agent": "cycle",
                    "baseline_id": "B1",
                    "completed": True,
                    "levels_completed": 1,
                    "score": 1.0,
                    "seed": 7,
                    "status": "success",
                }
            ],
            "summary": {
                "failure_count": 0,
                "result_count": 1,
                "status": "PASS",
                "successful_policy_count": 1,
                "surface": "synthetic",
            },
        },
        "permitted_nondeterminism": ["timestamps vary"],
    }


def _write_evaluation(directory: Path, *, actions: int = 3) -> None:
    directory.mkdir(parents=True)
    (directory / "manifest.json").write_text(
        json.dumps(
            {
                "agent_config": {
                    "agents": ["cycle"],
                    "max_actions": 4,
                    "max_resets": 1,
                    "network_mode": "offline",
                    "partition": "smoke",
                    "seeds": [7],
                    "surface": "synthetic",
                    "timeout_seconds": 30.0,
                }
            }
        ),
        encoding="utf-8",
    )
    (directory / "summary.json").write_text(
        json.dumps(
            {
                "failure_count": 0,
                "result_count": 1,
                "status": "PASS",
                "successful_policy_count": 1,
                "surface": "synthetic",
                "wall_clock_seconds": 999.0,
            }
        ),
        encoding="utf-8",
    )
    (directory / "results.jsonl").write_text(
        json.dumps(
            {
                "agent": "cycle",
                "baseline_id": "B1",
                "metrics": {"environment_actions": actions, "total_wall_clock_seconds": 5.0},
                "score": {"completed": True, "levels_completed": 1, "score": 1.0},
                "seed": 7,
                "status": "success",
            }
        )
        + "\n",
        encoding="utf-8",
    )


def _zip_bytes(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        for name in sorted(members):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            archive.writestr(info, members[name])
    return buffer.getvalue()


def _write_package(
    directory: Path,
    *,
    status: str = "PACKAGING_PASS",
    sandbox_status: str = "PASS",
    expected_commit: str = "a" * 40,
) -> Path:
    files = {
        "arc3-submission.ipynb": b"{}",
        "arc3-first-party.zip": _zip_bytes(
            {"agent/my_agent.py": b"pass\n", "src/arc3/__init__.py": b""}
        ),
        "kernel-metadata.json": b'{"id":"owner/arc3"}',
        "runtime-requirements-linux-cp312.txt": b"package==1 --hash=sha256:abc\n",
        "runtime-wheels-linux-cp312.json": b'{"packages":[{"name":"fixture"}]}',
        "sbom.spdx.json": b'{"spdxVersion":"SPDX-2.3"}',
        "submission-schema.v0.1.json": b'{"required":[]}',
    }
    directory.mkdir(parents=True)
    for name, content in files.items():
        (directory / name).write_bytes(content)
    output = directory / "offline-sandbox" / "submission.parquet"
    output.parent.mkdir()
    output.write_bytes(b"parquet")
    hashes = {name: sha256_file(directory / name) for name in files}
    manifest = {
        "artifacts": [
            {
                "path": name,
                "sha256": hashes[name],
                "size_bytes": len(files[name]),
            }
            for name in sorted(files)
        ],
        "build_status": status,
        "runtime_lock": {
            "requirements_sha256": hashes["runtime-requirements-linux-cp312.txt"],
            "wheel_manifest_sha256": hashes["runtime-wheels-linux-cp312.json"],
        },
        "secret_scan": {"findings": [], "status": "PASS"},
        "source": {
            "git_commit": expected_commit,
            "git_dirty": status != "PACKAGING_PASS",
        },
    }
    (directory / "package-manifest.json").write_bytes(package_canonical_json_bytes(manifest))
    hashes["package-manifest.json"] = sha256_file(directory / "package-manifest.json")
    candidate_members = {
        name: (directory / name).read_bytes() for name in (*files, "package-manifest.json")
    }
    (directory / "arc3-kaggle-candidate.zip").write_bytes(_zip_bytes(candidate_members))
    hashes["arc3-kaggle-candidate.zip"] = sha256_file(directory / "arc3-kaggle-candidate.zip")
    output_hash = sha256_file(output)
    sandbox = {
        "credentials_present": [],
        "dependency_install_status": "PASS",
        "framework_fixture": True,
        "gateway_connections": 2,
        "imported_arc3_path": "arc3_submission/src/arc3/__init__.py",
        "network_attempts": 0,
        "notebook_sha256": hashes["arc3-submission.ipynb"],
        "output_sha256": output_hash,
        "payload_sha256": hashes["arc3-first-party.zip"],
        "requirements_sha256": hashes["runtime-requirements-linux-cp312.txt"],
        "production_rerun_exercised": True,
        "secret_scan_status": "PASS",
        "status": sandbox_status,
    }
    body: dict[str, object] = {
        "candidate_sha256": hashes["arc3-kaggle-candidate.zip"],
        "candidate_validation": {
            "candidate_sha256": hashes["arc3-kaggle-candidate.zip"],
            "status": "PASS",
        },
        "manifest_sha256": hashes["package-manifest.json"],
        "notebook_sha256": hashes["arc3-submission.ipynb"],
        "official_submission_performed": False,
        "payload_sha256": hashes["arc3-first-party.zip"],
        "runtime_requirements_sha256": hashes["runtime-requirements-linux-cp312.txt"],
        "sandbox": sandbox,
        "sandbox_output_sha256": output_hash,
        "sandbox_receipt_sha256": sha256_bytes(package_canonical_json_bytes(sandbox)),
        "sbom_sha256": hashes["sbom.spdx.json"],
        "schema": "arc3.kaggle-build-receipt.v0.1",
        "status": status,
        "validation": {"artifact_sha256": output_hash, "status": "PASS"},
        "wheel_manifest_sha256": hashes["runtime-wheels-linux-cp312.json"],
    }
    receipt = directory / "build-receipt.json"
    receipt_document = dict(body)
    receipt_document["receipt_sha256"] = sha256_bytes(package_canonical_json_bytes(body))
    receipt.write_bytes(package_canonical_json_bytes(receipt_document))
    return receipt


def _asset(game_id: str) -> dict[str, object]:
    digest = f"sha256:{'7' * 64}"
    files = [("metadata.json", 3, digest)]
    return {
        "aggregate_sha256": sha256_bytes(evaluation_canonical_json_bytes(files)),
        "files": [{"bytes": 3, "name": "metadata.json", "sha256": digest}],
        "game_id": game_id,
        "source_semantically_inspected": False,
    }


def _write_public_manifest(path: Path) -> list[dict[str, str]]:
    salt = "test-salt"
    games = [
        {
            "assignment_hash": hashlib.sha256(f"{salt}\0aa11".encode()).hexdigest(),
            "game_id": "aa11-11111111",
            "partition": "smoke",
            "stable_name": "aa11",
        },
        {
            "assignment_hash": hashlib.sha256(f"{salt}\0bb22".encode()).hexdigest(),
            "game_id": "bb22-22222222",
            "partition": "smoke",
            "stable_name": "bb22",
        },
        {
            "assignment_hash": hashlib.sha256(f"{salt}\0cc33".encode()).hexdigest(),
            "game_id": "cc33-33333333",
            "partition": "development",
            "stable_name": "cc33",
        },
    ]
    path.write_text(
        json.dumps(
            {
                "assignment": {"salt": salt},
                "games": games,
                "schema": "arc3.public-game-partitions.v0.1",
            }
        ),
        encoding="utf-8",
    )
    return games


def _inventory(manifest: Path, game_ids: list[str]) -> dict[str, object]:
    return {
        "gameplay_opened": False,
        "local_assets": {game_id: _asset(game_id) for game_id in game_ids},
        "manifest_sha256": sha256_file(manifest),
        "online_metadata_revalidation": None,
        "partition_counts": {"development": 1, "public-holdout": 0, "smoke": 2},
        "schema": "arc3.public-inventory.v0.1",
    }


def test_frozen_benchmark_expectation_is_self_hashed_and_evidence_bound() -> None:
    repository = Path(__file__).resolve().parents[2]
    expectation = load_benchmark_expectation(
        repository / "scripts" / "release_candidate_benchmark.v0.1.json"
    )
    head = subprocess.run(
        ("git", "rev-parse", "HEAD"),
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    basis = benchmark_basis_identity(expectation, repository, head)
    assert expectation["schema"] == EXPECTATION_SCHEMA
    assert basis["measured_commit"] == "01f7a12e42f50e2899db9d430bcf4d125a81d49f"
    assert basis["measured_commit_is_ancestor"] is True


def test_benchmark_comparison_ignores_runtime_fields_and_detects_drift(
    tmp_path: Path,
) -> None:
    evaluation = tmp_path / "evaluation"
    _write_evaluation(evaluation)
    equal, receipt = compare_benchmark(_expectation(), evaluation)
    assert equal is True
    assert receipt["semantic_projection_equal"] is True

    changed = tmp_path / "changed"
    _write_evaluation(changed, actions=4)
    equal, receipt = compare_benchmark(_expectation(), changed)
    assert equal is False
    assert receipt["actual_projection_sha256"] != receipt["expected_projection_sha256"]


def test_package_comparison_hashes_real_files_and_requires_equal_passes(
    tmp_path: Path,
) -> None:
    first = _write_package(tmp_path / "first")
    second = _write_package(tmp_path / "second")
    equal, details = compare_packages(first, second, expected_commit="a" * 40)
    assert equal is True
    assert details["projections_equal"] is True


def test_package_projection_accepts_real_builder_receipt(tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[2]
    source = tmp_path / "source"
    subprocess.run(
        ("git", "clone", "--quiet", "--no-hardlinks", str(repository), str(source)),
        check=True,
        capture_output=True,
        timeout=60,
    )
    commit = subprocess.run(
        ("git", "rev-parse", "HEAD"),
        cwd=source,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    ).stdout.strip()
    result = build_kaggle_candidate(
        source,
        tmp_path / "package",
        sandbox_timeout_seconds=120.0,
    )

    projection = package_projection(result.build_receipt, expected_commit=commit)

    assert result.status == "PACKAGING_PASS"
    assert result.build_receipt.read_bytes().endswith(b"\n")
    assert projection["status"] == "PACKAGING_PASS"
    assert projection["candidate_sha256"] == result.candidate_sha256


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("tamper", "disagrees"),
        ("missing", "regular non-symlink"),
        ("failed-receipt", "PACKAGING_PASS"),
        ("failed-sandbox", "did not pass"),
    ],
)
def test_package_comparison_rejects_tamper_missing_and_equal_failures(
    tmp_path: Path, mutation: str, message: str
) -> None:
    first = _write_package(
        tmp_path / "first",
        status="PACKAGING_PREACCEPTANCE" if mutation == "failed-receipt" else "PACKAGING_PASS",
        sandbox_status="FAILED_MECHANISM" if mutation == "failed-sandbox" else "PASS",
    )
    second = _write_package(
        tmp_path / "second",
        status="PACKAGING_PREACCEPTANCE" if mutation == "failed-receipt" else "PACKAGING_PASS",
        sandbox_status="FAILED_MECHANISM" if mutation == "failed-sandbox" else "PASS",
    )
    if mutation == "tamper":
        (first.parent / "arc3-kaggle-candidate.zip").write_bytes(b"changed")
    elif mutation == "missing":
        (first.parent / "runtime-wheels-linux-cp312.json").unlink()
    with pytest.raises(ValueError, match=message):
        compare_packages(first, second, expected_commit="a" * 40)


def test_official_availability_binds_manifest_games_and_asset_content(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    _write_public_manifest(manifest)
    inventory = _inventory(manifest, ["aa11-11111111", "bb22-22222222", "cc33-33333333"])
    available, details = official_smoke_available(inventory, manifest)
    assert available is True
    assert details["required_game_ids"] == ["aa11-11111111", "bb22-22222222"]

    inventory = _inventory(manifest, ["aa11-11111111"])
    available, details = official_smoke_available(inventory, manifest)
    assert available is False
    assert details["missing_game_ids"] == ["bb22-22222222"]

    tampered = _inventory(manifest, ["aa11-11111111", "bb22-22222222"])
    tampered["local_assets"]["aa11-11111111"]["aggregate_sha256"] = (  # type: ignore[index]
        f"sha256:{'0' * 64}"
    )
    with pytest.raises(ValueError, match="aggregate identity"):
        official_smoke_available(tampered, manifest)


def test_official_availability_accepts_evaluation_module_asset_identities(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "manifest.json"
    games = _write_public_manifest(manifest)
    environments = tmp_path / "environments"
    local_assets: dict[str, object] = {}
    for game in games[:2]:
        _stable, _separator, version = game["game_id"].partition("-")
        directory = environments / game["stable_name"] / version
        directory.mkdir(parents=True)
        (directory / "metadata.json").write_text('{"title":"fixture"}\n', encoding="utf-8")
        (directory / f"{game['stable_name']}.py").write_text("VALUE = 1\n", encoding="utf-8")
        entry = PublicGameEntry(
            game_id=game["game_id"],
            stable_name=game["stable_name"],
            assignment_hash=game["assignment_hash"],
            partition=game["partition"],
            exposure="development",
        )
        identity = local_asset_identity(environments, entry)
        assert identity is not None
        local_assets[entry.game_id] = identity.to_dict()
    inventory = {
        "gameplay_opened": False,
        "local_assets": local_assets,
        "manifest_sha256": sha256_file(manifest),
        "online_metadata_revalidation": None,
        "partition_counts": {"development": 1, "public-holdout": 0, "smoke": 2},
        "schema": "arc3.public-inventory.v0.1",
    }

    available, details = official_smoke_available(inventory, manifest)

    assert available is True
    assert details["available_count"] == 2
    assert details["missing_count"] == 0


def test_plan_declares_every_release_boundary_without_hosted_inference(tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[2]
    specs = build_plan(
        repository=repository,
        output_root=tmp_path,
        transient_root=tmp_path.parent / "transient",
        expectation=_expectation(),
        uv_command=("uv",),
        official_environments=tmp_path / "official",
    )
    by_id = {spec.check_id: spec for spec in specs}
    assert {
        "dependency-lock",
        "ruff-lint",
        "ruff-format",
        "mypy-strict",
        "full-test-suite",
        "trace-replay-tamper",
        "synthetic-benchmark",
        "synthetic-artifact-verification",
        "offline-package-a",
        "offline-package-b",
        "competition-integrity",
        "official-inventory",
        "official-smoke",
        "official-artifact-verification",
    } == set(by_id)
    assert "--offline" in by_id["dependency-lock"].argv
    assert "--acquire-missing" not in by_id["official-smoke"].argv
    assert by_id["official-artifact-verification"].dependencies == ("official-inventory",)
    transient = (tmp_path.parent / "transient").resolve()
    assert str(transient / "tmp" / "pytest-full") in by_id["full-test-suite"].argv
    assert str(transient / "cache" / "mypy" / "full") in by_id["mypy-strict"].argv
    assert str(tmp_path / "package-a") in by_id["offline-package-a"].argv
    rendered = canonical_json_bytes([spec.to_dict() for spec in specs]).lower()
    assert b"measure_peak_rss" not in rendered
    assert b"openai" not in rendered
    assert b"anthropic" not in rendered


def test_discovered_uv_command_survives_release_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_uv = tmp_path / "fake_uv.py"
    fake_uv.write_text(
        "import os, sys\n"
        "if sys.argv[1:] != ['--version'] or os.environ.get('PYTHONNOUSERSITE') != '1':\n"
        "    raise SystemExit(2)\n"
        "print('uv 0.0.0-fixture')\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(verifier.shutil, "which", lambda _name: None)
    monkeypatch.setattr(verifier, "_python_command_candidates", lambda: ((sys.executable,),))
    monkeypatch.setattr(
        verifier,
        "_installed_uv_entrypoints",
        lambda _python_command: ((sys.executable, str(fake_uv)),),
    )
    command = discover_uv_command()
    environment, _removed = _sanitized_environment(tmp_path / "out", "uv-contract")

    completed = subprocess.run(
        (*command, "--version"),
        check=False,
        capture_output=True,
        env=environment,
        timeout=30,
    )

    assert environment["PYTHONNOUSERSITE"] == "1"
    assert completed.returncode == 0
    assert completed.stdout.startswith(b"uv ")


def test_command_runner_allowlists_environment_and_redacts_logs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ARC_API_KEY", "must-not-reach-child")
    monkeypatch.setenv("ARC_UNSAFE_RANDOM", "must-also-not-reach-child")
    token_file = tmp_path / "token.txt"
    token = "sk-proj-abcdefghijklmnopqrstuvwxyz"
    token_file.write_text(token, encoding="utf-8")
    spec = CommandSpec(
        "tiny-command",
        "test",
        (
            sys.executable,
            "-c",
            (
                "import os,pathlib,sys;"
                "print('ARC_API_KEY' in os.environ, 'ARC_UNSAFE_RANDOM' in os.environ);"
                "print(pathlib.Path(sys.argv[1]).read_text())"
            ),
            str(token_file),
        ),
        30.0,
        measure_peak_rss=True,
    )
    output = tmp_path / "out"
    result = run_command(
        spec,
        repository=tmp_path,
        output_root=output,
        transient_root=tmp_path / "transient",
        prior={},
    )
    log = (output / "logs" / "tiny-command.stdout.log").read_text()
    assert result.status == "PASS"
    peak_rss_bytes = result.details["peak_rss_bytes"]
    assert isinstance(peak_rss_bytes, int)
    assert peak_rss_bytes > 0
    assert "False False" in log
    assert token not in log
    assert "[REDACTED_SECRET_PATTERN]" in log
    passed, details = scan_generated_logs(output, [result])
    assert passed is False
    assert details["redaction_count"] == 1


def test_fresh_output_root_refuses_reuse_and_unignored_repository_path(
    tmp_path: Path,
) -> None:
    repository = Path(__file__).resolve().parents[2]
    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(ValueError, match="must not already exist"):
        prepare_fresh_output_root(repository, existing)
    with pytest.raises(ValueError, match=r"covered by \.gitignore"):
        prepare_fresh_output_root(repository, repository / "stage18-unignored-output")


def test_fresh_transient_root_refuses_reuse_repository_and_output_overlap(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    output = tmp_path / "output"
    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(ValueError, match="must not already exist"):
        prepare_fresh_transient_root(repository, output, existing)
    with pytest.raises(ValueError, match="strictly outside"):
        prepare_fresh_transient_root(repository, output, repository / "transient")
    with pytest.raises(ValueError, match="must not overlap"):
        prepare_fresh_transient_root(repository, output, output / "transient")


def test_release_receipt_seals_complete_artifacts_and_detects_tamper(tmp_path: Path) -> None:
    artifact = tmp_path / "logs" / "check.stdout.log"
    artifact.parent.mkdir()
    artifact.write_bytes(b"verified\n")
    sealed = _complete_artifact_set(tmp_path, sealed=True)
    body: dict[str, object] = {
        "schema": SCHEMA,
        "sealed_artifact_set": sealed,
        "status": "PASS",
    }
    path = tmp_path / "release-verification-receipt.json"
    path.write_bytes(_receipt_bytes(body))
    assert verify_release_receipt(path)["status"] == "PASS"

    artifact.write_bytes(b"tampered\n")
    with pytest.raises(ValueError, match="mismatch"):
        verify_release_receipt(path)


def test_release_receipt_rejects_missing_artifact_and_self_hash_drift(tmp_path: Path) -> None:
    artifact = tmp_path / "result.json"
    survivor = tmp_path / "proof.json"
    artifact.write_bytes(b"{}")
    survivor.write_bytes(b"{}")
    body: dict[str, object] = {
        "schema": SCHEMA,
        "sealed_artifact_set": _complete_artifact_set(tmp_path, sealed=True),
        "status": "PASS",
    }
    path = tmp_path / "release-verification-receipt.json"
    path.write_bytes(_receipt_bytes(body))
    artifact.unlink()
    with pytest.raises(ValueError, match="mismatch"):
        verify_release_receipt(path)

    artifact.write_bytes(b"{}")
    path.write_bytes(_receipt_bytes(body))
    document = json.loads(path.read_text(encoding="utf-8"))
    document["status"] = "FAILED_MECHANISM"
    path.write_text(json.dumps(document, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    with pytest.raises(ValueError, match="mismatch"):
        verify_release_receipt(path)


def test_expectation_loader_rejects_hash_drift(tmp_path: Path) -> None:
    path = tmp_path / "expectation.json"
    body = _expectation()
    _write_self_hashed(path, body, EXPECTATION_HASH_FIELD)
    assert load_benchmark_expectation(path)["schema"] == EXPECTATION_SCHEMA

    document = json.loads(path.read_text(encoding="utf-8"))
    document["configuration"]["max_actions"] = 99
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValueError, match=EXPECTATION_HASH_FIELD):
        load_benchmark_expectation(path)
