"""Competition-contract checks for the generated offline package."""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tomllib
import zipfile
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlparse

import pytest
from packaging.tags import compatible_tags, cpython_tags
from packaging.utils import parse_wheel_filename
from scripts.package_only_pytest import BUILD001_BOUNDARY_EXCLUSIONS, build001_test_selection

from arc3.packaging import builder as packaging_builder
from arc3.packaging import runtime_launcher as launcher_module
from arc3.packaging import sandbox as sandbox_module
from arc3.packaging import sbom as sbom_module
from arc3.packaging import submission as submission_module
from arc3.packaging.builder import build_kaggle_candidate, scan_payload_for_secrets
from arc3.packaging.candidate import validate_candidate_archive
from arc3.packaging.models import PYTHON_NETWORK_ENFORCEMENT, PackagingError
from arc3.packaging.notebook import build_notebook, validate_kernel_metadata, validate_notebook
from arc3.packaging.requirements import (
    TARGET_ABI,
    TARGET_IMPLEMENTATION,
    TARGET_PIP_PLATFORMS,
    TARGET_PYTHON_VERSION,
    LockedWheel,
    build_linux_runtime_requirements,
    pip_target_arguments,
    verify_runtime_wheelhouse,
)
from arc3.packaging.runtime_launcher import launch_competition_framework
from arc3.packaging.sbom import verify_wheelhouse_license_evidence
from arc3.packaging.submission import SUBMISSION_COLUMNS, validate_submission_parquet
from arc3.packaging.util import deterministic_zip_bytes, sha256_bytes

REPOSITORY = Path(__file__).resolve().parents[2]


def _git_fixture(repository: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ("git", *arguments),
        cwd=repository,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    return completed.stdout.strip()


@pytest.mark.competition
@pytest.mark.parametrize("mutation", ("extra-cell", "hosted-import", "hosted-runtime-call"))
def test_generated_notebook_rejects_any_added_executable_policy(mutation: str) -> None:
    notebook = build_notebook(
        payload=b"payload",
        payload_sha256=sha256_bytes(b"payload"),
        runtime_requirements=b"requirements",
        requirements_sha256=sha256_bytes(b"requirements"),
        validation_parquet=b"parquet",
        source_commit="a" * 40,
    )
    cells = notebook["cells"]
    assert isinstance(cells, list)
    if mutation == "extra-cell":
        cells.append(
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {"tags": ["unexpected"]},
                "outputs": [],
                "source": "VALUE = 1\n",
            }
        )
    else:
        launch_cell = cells[3]
        assert isinstance(launch_cell, dict)
        source = launch_cell["source"]
        assert isinstance(source, str)
        launch_cell["source"] = source + (
            "\nimport openai\n" if mutation == "hosted-import" else "\nopenai.Client()\n"
        )

    with pytest.raises(PackagingError, match=r"strict generated|exactly four"):
        validate_notebook(notebook)


@pytest.mark.competition
def test_stage17_offline_runner_canonicalizes_argv_roots_before_path_checks() -> None:
    assert "notebook_path = Path(sys.argv[1]).resolve()" in sandbox_module._RUNNER
    assert "working_root = Path(sys.argv[2]).resolve()" in sandbox_module._RUNNER
    assert "input_root = Path(sys.argv[3]).resolve()" in sandbox_module._RUNNER
    assert "requirements_path = Path(sys.argv[4]).resolve()" in sandbox_module._RUNNER


@pytest.mark.competition
def test_stage17_python_socket_guard_blocks_udp_and_dns_bypasses() -> None:
    preamble = r"""
import json
import socket

gateway_connections = []
blocked_attempts = []
real_socket = socket.socket
real_create_connection = socket.create_connection
real_getaddrinfo = socket.getaddrinfo
real_gethostbyname = socket.gethostbyname
real_gethostbyname_ex = socket.gethostbyname_ex
real_gethostbyaddr = socket.gethostbyaddr
real_getnameinfo = socket.getnameinfo
allowed_hosts = {"127.0.0.1", "::1"}
"""
    adversarial_probe = r"""
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
operations = (
    lambda: socket.getaddrinfo("example.invalid", 443),
    lambda: socket.gethostbyname("example.invalid"),
    lambda: socket.gethostbyname_ex("example.invalid"),
    lambda: socket.gethostbyaddr("203.0.113.1"),
    lambda: socket.getnameinfo(("203.0.113.1", 443), 0),
    lambda: sock.sendto(b"fixture", ("203.0.113.1", 9)),
    lambda: sock.sendmsg([b"fixture"], [], 0, ("203.0.113.1", 9)),
    lambda: socket.create_connection(("203.0.113.1", 9)),
    lambda: sock.connect(("203.0.113.1", 9)),
)
for operation in operations:
    try:
        operation()
    except RuntimeError:
        pass
    else:
        raise AssertionError("guarded operation reached an OS network entry point")
if sock.connect_ex(("203.0.113.1", 9)) == 0:
    raise AssertionError("guarded connect_ex reported success")
sock.close()
expected = {
    "connect",
    "connect_ex",
    "create_connection",
    "getaddrinfo",
    "gethostbyaddr",
    "gethostbyname",
    "gethostbyname_ex",
    "getnameinfo",
    "sendmsg",
    "sendto",
}
observed = {item.split(":", 1)[0] for item in blocked_attempts}
if observed != expected or socket.SocketType is not GuardedSocket:
    raise AssertionError(f"incomplete Python socket guard: {observed!r}")
print(json.dumps({"attempt_count": len(blocked_attempts), "operations": sorted(observed)}))
"""
    completed = subprocess.run(
        (
            sys.executable,
            "-I",
            "-c",
            preamble + sandbox_module._PYTHON_SOCKET_GUARD + adversarial_probe,
        ),
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr
    receipt = json.loads(completed.stdout)
    assert receipt["attempt_count"] == 10
    assert set(receipt["operations"]) == {
        "connect",
        "connect_ex",
        "create_connection",
        "getaddrinfo",
        "gethostbyaddr",
        "gethostbyname",
        "gethostbyname_ex",
        "getnameinfo",
        "sendmsg",
        "sendto",
    }


@pytest.mark.competition
def test_stage17_candidate_is_cpu_only_secret_free_and_offline(tmp_path: Path) -> None:
    result = build_kaggle_candidate(
        REPOSITORY, tmp_path / "candidate", allow_dirty_preacceptance=True
    )

    assert result.sandbox.status == "PASS"
    assert result.sandbox.notebook_entrypoint == "exact-generated-notebook-code-cells"
    assert result.sandbox.platform_surface == "safe-loopback-gateway-and-framework-fixture"
    assert result.sandbox.runtime_dependency_surface == "host-assisted-canary"
    assert result.sandbox.exact_generated_code_cells == 4
    assert result.sandbox.exact_production_requirements is False
    assert result.sandbox.host_site_pth_bridge_present is True
    assert result.sandbox.agent_action_cycle_status == "PASS"
    assert result.sandbox.agent_consequence_state == "NOT_FINISHED"
    assert result.sandbox.agent_cycle_actions[0] == "RESET"
    assert result.sandbox.agent_cycle_actions[1].startswith("ACTION")
    assert result.sandbox.network_attempts == 0
    assert result.sandbox.network_enforcement == PYTHON_NETWORK_ENFORCEMENT
    assert result.sandbox.credentials_present == ()
    assert len(result.sandbox.limitations) == 4
    assert any(
        "OS-level network containment is absent" in item for item in result.sandbox.limitations
    )
    assert result.sandbox.production_rerun_exercised is True
    assert result.sandbox.dependency_install_status == "PASS"
    assert result.sandbox.framework_fixture is True
    assert result.sandbox.framework_identity == "arc3.stage17.safe-framework.v0.1"
    assert result.sandbox.agent_count == 1
    assert result.sandbox.worker_count == 1
    assert result.sandbox.max_concurrency == 1
    assert result.sandbox.orchestration == "arc3.sequential-pinned-swarm.v1"
    assert result.sandbox.gateway_connections >= 2
    assert result.sandbox.secret_scan_status == "PASS"
    assert result.sandbox.notebook_sha256 == result.notebook_sha256
    assert result.sandbox.payload_sha256 == result.payload_sha256
    assert result.sandbox.requirements_sha256 == result.runtime_requirements_sha256
    assert result.sandbox.imported_arc3_path == "arc3_submission/src/arc3/__init__.py"
    assert result.validation.status == "PASS"
    assert result.validation.columns == SUBMISSION_COLUMNS
    assert result.validation.rows == 1

    notebook = json.loads(result.notebook.read_text(encoding="utf-8"))
    metadata = json.loads(result.kernel_metadata.read_text(encoding="utf-8"))
    validate_notebook(notebook)
    validate_kernel_metadata(metadata)
    assert notebook["metadata"]["kaggle"]["isInternetEnabled"] is False
    assert notebook["metadata"]["kaggle"]["accelerator"] == "none"
    assert metadata["enable_internet"] is False
    assert metadata["enable_gpu"] is False

    manifest = json.loads(result.package_manifest.read_text(encoding="utf-8"))
    assert manifest["evidence_label"] == "synthetic"
    assert manifest["secret_scan"]["findings"] == []
    assert manifest["secret_scan"]["status"] == "PASS"
    assert manifest["secret_scan"]["scopes"] == [
        "payload-before-archive",
        "candidate-members-before-archive",
    ]
    assert manifest["competition"]["official_submission_performed"] is False
    assert manifest["competition"]["hosted_inference"] is False
    assert manifest["competition"]["credential_requirement"].startswith("none")
    assert manifest["offline_rehearsal"]["competition_gateway_available"] is False

    sbom = json.loads(result.sbom.read_text(encoding="utf-8"))
    packages = {item["name"]: item for item in sbom["packages"]}
    assert sbom["spdxVersion"] == "SPDX-2.3"
    assert sbom["creationInfo"]["creators"][0] == "Person: Christopher D. Pang"
    assert {"arc3", "arc-agi", "arcengine", "numpy", "pydantic"} <= packages.keys()
    assert packages["pyarrow"]["licenseDeclared"] == "Apache-2.0"
    assert packages["ARC-AGI-3-Agents"]["licenseDeclared"] == "MIT"
    assert packages["requests"]["licenseDeclared"] == "Apache-2.0"
    assert packages["arc3"]["licenseDeclared"] == "MIT-0"

    requirements = result.runtime_requirements.read_text(encoding="utf-8")
    assert "arc-agi==0.9.9 --hash=sha256:" in requirements
    assert "numpy==2.5.2 --hash=sha256:" in requirements
    assert "colorama==" not in requirements
    wheel_manifest = json.loads(result.wheel_manifest.read_text(encoding="utf-8"))
    assert wheel_manifest["target"] == "CPython 3.12 / Linux x86_64 / manylinux_2_28"
    assert wheel_manifest["pip_target"] == {
        "abi": "cp312",
        "exact_wheelhouse_required": True,
        "implementation": "cp",
        "single_platform_simulation_supported": False,
        "platforms": list(TARGET_PIP_PLATFORMS),
        "python_version": "312",
    }
    assert wheel_manifest["requirements_sha256"] == result.runtime_requirements_sha256


@pytest.mark.competition
def test_stage17_payload_excludes_build_tools_from_runtime_reachability(tmp_path: Path) -> None:
    result = build_kaggle_candidate(
        REPOSITORY, tmp_path / "candidate", allow_dirty_preacceptance=True
    )
    manifest = json.loads(result.package_manifest.read_text(encoding="utf-8"))
    recorded = {item["path"]: item for item in manifest["payload"]["files"]}

    with zipfile.ZipFile(result.payload_archive) as payload:
        members = set(payload.namelist())
        assert "LICENSE" in members
        assert "agent/my_agent.py" in members
        assert "src/arc3/competition-runtime.v0.1.json" in members
        assert "src/arc3/competition-runtime.v0.2.json" in members
        assert "src/arc3/competition/governor.py" in members
        assert "src/arc3/competition_runtime.py" in members
        assert "src/arc3/policy/controller.py" in members
        assert "src/arc3/mechanics/visual_causal.py" in members
        assert "src/arc3/mechanics/learner.py" in members
        assert "src/arc3/mechanics/ledger.py" in members
        assert "src/arc3/exploration/causal_events.py" in members
        assert "src/arc3/packaging/runtime_launcher.py" in members
        assert "src/arc3/packaging/models.py" in members
        assert "src/arc3/packaging/builder.py" not in members
        assert "src/arc3/packaging/sandbox.py" not in members
        assert "src/arc3/packaging/sbom.py" not in members
        assert "src/arc3/packaging/requirements.py" not in members
        assert "src/arc3/evaluation/runner.py" not in members
        assert "src/arc3/integrity/scanner.py" not in members
        assert "src/arc3/cli.py" not in members

        runtime_sources = b"\n".join(
            payload.read(name) for name in sorted(members) if name.endswith(".py")
        ).lower()
        assert members == recorded.keys()
        for name in members:
            content = payload.read(name)
            assert recorded[name]["sha256"] == f"sha256:{sha256(content).hexdigest()}"
            assert recorded[name]["size_bytes"] == len(content)
    assert b"api.openai.com" not in runtime_sources
    assert b"api.anthropic.com" not in runtime_sources
    assert b"generativelanguage.googleapis.com" not in runtime_sources
    assert b"import subprocess" not in runtime_sources
    assert b"subprocess.run" not in runtime_sources


@pytest.mark.competition
def test_payload_is_projected_from_exact_git_blobs_not_hidden_worktree_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "repository"
    selected_files = {
        "LICENSE": "license\n",
        "THIRD_PARTY_NOTICES.md": "notices\n",
        "agent/my_agent.py": "class MyAgent:\n    pass\n",
        "pyproject.toml": "[project]\nname='fixture'\n",
        "src/arc3/competition-runtime.v0.1.json": "{}\n",
        "src/arc3/competition-runtime.v0.2.json": "{}\n",
        "src/arc3/competition/__init__.py": "\n",
        "src/arc3/competition/governor.py": "GOVERNOR = 'tracked'\n",
        "src/arc3/competition_runtime.py": "RUNTIME = 'tracked'\n",
        "src/arc3/policy/controller.py": "VALUE = 'tracked'\n",
        "upstream.lock.json": "{}\n",
        "uv.lock": "version = 1\n",
    }
    for relative, content in selected_files.items():
        path = repository / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    _git_fixture(repository, "init", "-q")
    _git_fixture(repository, "add", ".")
    _git_fixture(
        repository,
        "-c",
        "user.name=ARC3 Test",
        "-c",
        "user.email=arc3@example.invalid",
        "commit",
        "-q",
        "-m",
        "fixture",
    )
    commit = _git_fixture(repository, "rev-parse", "HEAD")

    hidden_extra = repository / "src" / "arc3" / "policy" / "ignored.py"
    hidden_extra.write_text("HOSTED = 'ignored-extra'\n", encoding="utf-8")
    (repository / ".git" / "info" / "exclude").write_text(
        "src/arc3/policy/ignored.py\n",
        encoding="utf-8",
    )
    hidden_modified = repository / "src" / "arc3" / "policy" / "controller.py"
    hidden_modified.write_text("VALUE = 'hidden-modification'\n", encoding="utf-8")
    _git_fixture(
        repository,
        "update-index",
        "--assume-unchanged",
        hidden_modified.relative_to(repository).as_posix(),
    )
    assert _git_fixture(repository, "status", "--short", "--untracked-files=normal") == ""

    decoy = tmp_path / "decoy"
    decoy.mkdir()
    _git_fixture(decoy, "init", "-q")
    monkeypatch.setenv("GIT_DIR", str(decoy / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(decoy))

    members, records, source_identity = packaging_builder.collect_git_payload(
        repository,
        commit,
    )
    monkeypatch.delenv("GIT_DIR")
    monkeypatch.delenv("GIT_WORK_TREE")
    payload = deterministic_zip_bytes(members)

    assert "src/arc3/policy/ignored.py" not in members
    assert members["src/arc3/policy/controller.py"] == b"VALUE = 'tracked'\n"
    assert source_identity == {
        "exact_git_commit_bound": True,
        "git_commit": commit,
        "member_count": len(records),
        "member_records_sha256": sha256_bytes(
            packaging_builder.canonical_json_bytes(
                {"files": [record.to_dict() for record in records]}
            )
        ),
        "mode": "git-blob-exact",
    }
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        assert set(archive.namelist()) == set(members)
        assert archive.read("src/arc3/policy/controller.py") == b"VALUE = 'tracked'\n"

    _git_fixture(
        repository,
        "update-index",
        "--no-assume-unchanged",
        hidden_modified.relative_to(repository).as_posix(),
    )
    _git_fixture(repository, "add", hidden_modified.relative_to(repository).as_posix())
    _git_fixture(
        repository,
        "-c",
        "user.name=ARC3 Test",
        "-c",
        "user.email=arc3@example.invalid",
        "commit",
        "-q",
        "-m",
        "replacement fixture",
    )
    replacement_commit = _git_fixture(repository, "rev-parse", "HEAD")
    _git_fixture(repository, "replace", commit, replacement_commit)

    replaced_members, _, _ = packaging_builder.collect_git_payload(repository, commit)

    assert replaced_members["src/arc3/policy/controller.py"] == b"VALUE = 'tracked'\n"


@pytest.mark.competition
def test_final_candidate_nonpayload_inputs_derive_from_the_same_exact_git_commit(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "source"
    subprocess.run(
        ("git", "clone", "--quiet", "--no-hardlinks", str(REPOSITORY), str(repository)),
        check=True,
        capture_output=True,
        timeout=60,
    )
    commit = _git_fixture(repository, "rev-parse", "HEAD")
    targets = {
        "uv.lock": b"not valid TOML",
        "upstream.lock.json": b"not valid JSON",
        "src/arc3/packaging/submission-schema.v0.1.json": b"not valid JSON",
    }
    for relative, replacement in targets.items():
        (repository / relative).write_bytes(replacement)
        _git_fixture(repository, "update-index", "--assume-unchanged", relative)
    assert _git_fixture(repository, "status", "--short", "--untracked-files=normal") == ""

    result = build_kaggle_candidate(repository, tmp_path / "package")

    assert result.status == "PACKAGING_PASS"
    with zipfile.ZipFile(result.candidate_archive) as candidate:
        schema_bytes = candidate.read("submission-schema.v0.1.json")
        wheel_manifest = json.loads(candidate.read("runtime-wheels-linux-cp312.json"))
        manifest = json.loads(candidate.read("package-manifest.json"))
    committed_schema = subprocess.run(
        (
            "git",
            "--no-replace-objects",
            "-C",
            str(repository),
            "show",
            f"{commit}:src/arc3/packaging/submission-schema.v0.1.json",
        ),
        check=True,
        capture_output=True,
        timeout=30,
    ).stdout
    committed_lock = subprocess.run(
        ("git", "--no-replace-objects", "-C", str(repository), "show", f"{commit}:uv.lock"),
        check=True,
        capture_output=True,
        timeout=30,
    ).stdout

    assert schema_bytes == committed_schema
    assert wheel_manifest["uv_lock_sha256"] == sha256_bytes(committed_lock)
    assert manifest["source"]["git_commit"] == commit
    assert manifest["source"]["git_commit_timestamp"] == packaging_builder._source_timestamp(
        repository,
        commit,
    )


@pytest.mark.competition
@pytest.mark.parametrize(
    ("attack", "message"),
    (
        ("assume-unchanged", "non-H Git index entry"),
        ("divergent-cached-index", "Git index projection differs"),
    ),
)
def test_guarded_test_projection_rejects_hidden_or_divergent_index_bytes(
    tmp_path: Path,
    attack: str,
    message: str,
) -> None:
    repository = tmp_path / "repository"
    fixture_files = {
        ".github/workflows/ci.yml": "jobs: {}\n",
        "pyproject.toml": "[project]\nname='fixture'\n",
        "scripts/__init__.py": "",
        "scripts/_package_only_bootstrap/sitecustomize.py": "",
        "scripts/package_only_path_guard.py": "VALUE = 1\n",
        "scripts/package_only_pytest.py": "VALUE = 1\n",
        "tests/test_selected.py": "def test_selected():\n    assert True\n",
        "uv.lock": "version = 1\n",
        **{
            relative: "def test_excluded():\n    assert True\n"
            for relative, _ in BUILD001_BOUNDARY_EXCLUSIONS
        },
    }
    for relative, content in fixture_files.items():
        path = repository / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    _git_fixture(repository, "init", "-q")
    _git_fixture(repository, "add", ".")
    _git_fixture(
        repository,
        "-c",
        "user.name=ARC3 Test",
        "-c",
        "user.email=arc3@example.invalid",
        "commit",
        "-q",
        "-m",
        "fixture",
    )
    commit = _git_fixture(repository, "rev-parse", "HEAD")
    selected = repository / "tests" / "test_selected.py"
    selected.write_text("def test_selected():\n    assert False\n", encoding="utf-8")
    if attack == "assume-unchanged":
        _git_fixture(repository, "update-index", "--assume-unchanged", "tests/test_selected.py")
        assert _git_fixture(repository, "status", "--short", "--untracked-files=normal") == ""
    else:
        _git_fixture(repository, "add", "tests/test_selected.py")
        selected.write_text("def test_selected():\n    assert True\n", encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        build001_test_selection(repository, expected_commit=commit)


@pytest.mark.competition
def test_stage17_candidate_archive_has_only_declared_review_artifacts(tmp_path: Path) -> None:
    result = build_kaggle_candidate(
        REPOSITORY, tmp_path / "candidate", allow_dirty_preacceptance=True
    )

    with zipfile.ZipFile(result.candidate_archive) as archive:
        assert archive.namelist() == sorted(
            [
                "arc3-first-party.zip",
                "arc3-submission.ipynb",
                "kernel-metadata.json",
                "package-manifest.json",
                "runtime-requirements-linux-cp312.txt",
                "runtime-wheels-linux-cp312.json",
                "sbom.spdx.json",
                "submission-schema.v0.1.json",
            ]
        )
    receipt = json.loads(result.build_receipt.read_text(encoding="utf-8"))
    manifest = json.loads(result.package_manifest.read_text(encoding="utf-8"))
    expected_status = (
        "PACKAGING_PREACCEPTANCE" if manifest["source"]["git_dirty"] else "PACKAGING_PASS"
    )
    assert result.status == expected_status
    assert receipt["status"] == expected_status
    assert receipt["evidence_label"] == "synthetic"
    assert receipt["official_submission_performed"] is False
    assert validate_candidate_archive(result.candidate_archive)["status"] == "PASS"


@pytest.mark.competition
def test_stage17_schema_validator_rejects_non_parquet(tmp_path: Path) -> None:
    invalid = tmp_path / "submission.parquet"
    invalid.write_bytes(b"not parquet")

    with pytest.raises(PackagingError, match="not a structurally recognizable Parquet"):
        validate_submission_parquet(invalid)


@pytest.mark.competition
def test_stage17_payload_secret_scan_fails_closed() -> None:
    kaggle_token = "KGAT_" + ("Z9" * 20)
    findings = scan_payload_for_secrets(
        {
            "agent/credential.py": b'API_KEY="sk-proj-abcdefghijklmnopqrstuvwxyz012345"',
            "agent/kaggle.py": kaggle_token.encode("ascii"),
            "metadata/kaggle.json": b"{}",
        }
    )

    assert findings == (
        "high-confidence secret pattern in agent/credential.py",
        "high-confidence secret pattern in agent/kaggle.py",
        "forbidden credential-bearing filename: metadata/kaggle.json",
    )
    assert kaggle_token not in str(findings)
    assert not scan_payload_for_secrets({"src/arc3/gateway.py": b'ARC_API_KEY = "test-key-123"'})


@pytest.mark.competition
def test_stage17_dirty_tree_requires_explicit_preacceptance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_git_command = packaging_builder._git_command

    def fake_git_command(repository: Path, *arguments: str) -> str:
        if arguments and arguments[0] == "status":
            return " M first-party.py"
        return real_git_command(repository, *arguments)

    monkeypatch.setattr(packaging_builder, "_git_command", fake_git_command)
    with pytest.raises(PackagingError, match="dirty source tree"):
        build_kaggle_candidate(REPOSITORY, tmp_path / "candidate")


@pytest.mark.competition
def test_stage17_existing_output_is_never_mixed_or_overwritten(tmp_path: Path) -> None:
    output = tmp_path / "candidate"
    output.mkdir()
    stale_candidate = output / "arc3-kaggle-candidate.zip"
    stale_receipt = output / "build-receipt.json"
    stale_candidate.write_bytes(b"stale-candidate")
    stale_receipt.write_bytes(b"stale-receipt")

    with pytest.raises(PackagingError, match="must be fresh"):
        build_kaggle_candidate(REPOSITORY, output, allow_dirty_preacceptance=True)

    assert stale_candidate.read_bytes() == b"stale-candidate"
    assert stale_receipt.read_bytes() == b"stale-receipt"


@pytest.mark.competition
def test_stage17_powershell_wrapper_installs_all_locked_extras() -> None:
    wrapper = (REPOSITORY / "scripts" / "prepare_kaggle_submission.ps1").read_text(encoding="utf-8")

    assert "uv run --frozen --all-extras --dev --link-mode copy python" in wrapper


@pytest.mark.competition
def test_stage17_requires_exact_pyarrow(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(submission_module.importlib.metadata, "version", lambda name: "20.0.0")

    with pytest.raises(PackagingError, match=r"requires exactly pyarrow==21\.0\.0"):
        submission_module._parquet_modules()


@pytest.mark.competition
def test_stage17_linux_runtime_lock_is_exact_and_platform_scoped() -> None:
    requirements, manifest, wheels = build_linux_runtime_requirements(REPOSITORY / "uv.lock")

    assert manifest["target"] == "CPython 3.12 / Linux x86_64 / manylinux_2_28"
    assert len(wheels) >= 20
    assert all(
        b"==" in line and b"--hash=sha256:" in line for line in requirements.splitlines()[2:]
    )
    assert all(
        wheel.filename.endswith("-none-any.whl")
        or ("x86_64" in wheel.filename and "manylinux" in wheel.filename)
        for wheel in wheels
    )


@pytest.mark.competition
def test_stage17_pip_target_models_native_manylinux_2_28_compatibility() -> None:
    assert TARGET_PIP_PLATFORMS[0] == "manylinux_2_28_x86_64"
    pep_600_17 = TARGET_PIP_PLATFORMS.index("manylinux_2_17_x86_64")
    assert TARGET_PIP_PLATFORMS[pep_600_17 + 1] == "manylinux2014_x86_64"
    assert TARGET_PIP_PLATFORMS[-2:] == ("manylinux_2_5_x86_64", "manylinux1_x86_64")

    arguments = pip_target_arguments()
    assert arguments[:6] == (
        "--python-version",
        TARGET_PYTHON_VERSION,
        "--implementation",
        TARGET_IMPLEMENTATION,
        "--abi",
        TARGET_ABI,
    )
    assert arguments[6::2] == ("--platform",) * len(TARGET_PIP_PLATFORMS)
    assert arguments[7::2] == TARGET_PIP_PLATFORMS


@pytest.mark.competition
def test_stage17_selected_wheels_follow_native_cp312_tag_priority() -> None:
    _, _, wheels = build_linux_runtime_requirements(REPOSITORY / "uv.lock")
    selected = {wheel.name: wheel for wheel in wheels}
    fonttools = selected["fonttools"]
    assert fonttools.filename == (
        "fonttools-4.63.0-cp312-cp312-manylinux2014_x86_64.manylinux_2_17_x86_64.whl"
    )
    assert fonttools.sha256 == (
        "sha256:58dc6bb86a78d782f00f9190ca02c119cf5bbe2807536e361e18d42019f877d8"
    )

    supported_ordered = (
        *cpython_tags((3, 12), abis=(TARGET_ABI,), platforms=TARGET_PIP_PLATFORMS),
        *compatible_tags(
            (3, 12),
            interpreter=f"{TARGET_IMPLEMENTATION}{TARGET_PYTHON_VERSION}",
            platforms=TARGET_PIP_PLATFORMS,
        ),
    )
    supported = set(supported_ordered)
    assert all(parse_wheel_filename(wheel.filename)[3] & supported for wheel in wheels)

    lock = tomllib.loads((REPOSITORY / "uv.lock").read_text(encoding="utf-8"))
    locked_fonttools = next(item for item in lock["package"] if item["name"] == "fonttools")
    pure = next(item for item in locked_fonttools["wheels"] if item["url"].endswith("none-any.whl"))
    assert pure["hash"] == (
        "sha256:445af2eab030a16b9171ea8bdda7ebf7d96bda2df88ee182a464252f6e05e20d"
    )
    rank = {tag: index for index, tag in enumerate(supported_ordered)}
    native_rank = min(
        rank[tag] for tag in parse_wheel_filename(fonttools.filename)[3] if tag in rank
    )
    pure_filename = Path(urlparse(pure["url"]).path).name
    pure_rank = min(rank[tag] for tag in parse_wheel_filename(pure_filename)[3] if tag in rank)
    assert native_rank < pure_rank


@pytest.mark.competition
def test_stage17_limited_single_platform_simulation_exposes_fonttools_mismatch() -> None:
    limited_tags = (
        *cpython_tags(
            (3, 12),
            abis=(TARGET_ABI,),
            platforms=("manylinux_2_28_x86_64",),
        ),
        *compatible_tags(
            (3, 12),
            interpreter=f"{TARGET_IMPLEMENTATION}{TARGET_PYTHON_VERSION}",
            platforms=("manylinux_2_28_x86_64",),
        ),
    )
    rank = {tag: index for index, tag in enumerate(limited_tags)}
    lock = tomllib.loads((REPOSITORY / "uv.lock").read_text(encoding="utf-8"))
    fonttools = next(item for item in lock["package"] if item["name"] == "fonttools")
    candidates: list[tuple[int, str, str]] = []
    for wheel in fonttools["wheels"]:
        filename = Path(urlparse(wheel["url"]).path).name
        wheel_ranks = [rank[tag] for tag in parse_wheel_filename(filename)[3] if tag in rank]
        if wheel_ranks:
            candidates.append((min(wheel_ranks), filename, wheel["hash"]))
    _, filename, digest = min(candidates)

    assert filename == "fonttools-4.63.0-py3-none-any.whl"
    assert digest == "sha256:445af2eab030a16b9171ea8bdda7ebf7d96bda2df88ee182a464252f6e05e20d"


@pytest.mark.competition
def test_stage17_runtime_wheelhouse_requires_exact_filenames_and_hashes(tmp_path: Path) -> None:
    content = deterministic_zip_bytes({"fixture.py": b"VALUE = 1\n"})
    selected = LockedWheel(
        name="fixture",
        version="1.0",
        filename="fixture-1.0-py3-none-any.whl",
        sha256=sha256_bytes(content),
        url="https://files.pythonhosted.org/fixture-1.0-py3-none-any.whl",
    )
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    selected_path = wheelhouse / selected.filename
    selected_path.write_bytes(content)

    receipt = verify_runtime_wheelhouse((selected,), wheelhouse)
    assert receipt["status"] == "PASS"
    assert receipt["package_count"] == 1

    extra = wheelhouse / "fixture-1.0-cp312-cp312-manylinux_2_28_x86_64.whl"
    extra.write_bytes(content)
    with pytest.raises(PackagingError, match="wheelhouse inventory mismatch"):
        verify_runtime_wheelhouse((selected,), wheelhouse)
    extra.unlink()

    selected_path.write_bytes(content + b"tampered")
    with pytest.raises(PackagingError, match="wheel hash mismatch"):
        verify_runtime_wheelhouse((selected,), wheelhouse)


@pytest.mark.competition
def test_stage17_selected_linux_wheel_license_evidence_is_exact() -> None:
    _, _, wheels = build_linux_runtime_requirements(REPOSITORY / "uv.lock")
    selected = {wheel.name: wheel.sha256.removeprefix("sha256:") for wheel in wheels}
    expected = {
        "charset-normalizer": (
            "b9af956078716df40d985fb0dfeb2c2120c5ca92ba4ff4b388acfd01cdc14d08",
            "charset_normalizer-3.5.1.dist-info/licenses/LICENSE",
            "6d0d41bfe170ac6c7dc248c9a63e254d0fb45a60d50a8257d0af92c6e249b887",
        ),
        "contourpy": (
            "4d00e655fcef08aba35ec9610536bfe90267d7ab5ba944f7032549c55a146da1",
            "contourpy-1.3.3.dist-info/LICENSE",
            "34170979fc64f4f5e6dfa66ef27dec314ffffc5852000c60f4836ec1dfbf156e",
        ),
        "fonttools": (
            "58dc6bb86a78d782f00f9190ca02c119cf5bbe2807536e361e18d42019f877d8",
            "fonttools-4.63.0.dist-info/licenses/LICENSE",
            "6787208f83f659ccbc2223b2fde952ffa6f7e8aca62f1a8a2bf5bc51bb1b2383",
        ),
        "kiwisolver": (
            "bb5136fb5352d3f422df33f0c879a1b0c204004324150cc3b5e3c4f310c9049f",
            "kiwisolver-1.5.0.dist-info/licenses/LICENSE",
            "529c40e5f67f2f88904657a9f7879ae2f8dc76bc9bfef9cb10d988b48804ed61",
        ),
        "markupsafe": (
            "d6dd0be5b5b189d31db7cda48b91d7e0a9795f31430b7f271219ab30f1d3ac9d",
            "markupsafe-3.0.3.dist-info/licenses/LICENSE.txt",
            "489a8e1108509ed98a37bb983e11e0f7e1d31f0bd8f99a79c8448e7ff37d07ea",
        ),
        "numpy": (
            "3cdec01fa790a186d430433fdd4d4ffb70eed6f0eeb4bf05c8dbe2dce0a9bcb8",
            "numpy-2.5.2.dist-info/licenses/LICENSE.txt",
            "4860083caa0de2ac3292ca98bd074bd8f45d8b32624e37b1e70a240bff61e488",
        ),
        "pillow": (
            "78cb2c6865a35ab8ff8b75fd122f6033b92a62c82801110e48ddd6c936a45d91",
            "pillow-12.3.0.dist-info/licenses/LICENSE",
            "dda12a98c1979cf3d94df1cff45d27a4cb3f04a60c76f76902ac54cac03ec0ce",
        ),
        "pydantic-core": (
            "926c9541b14b12b1681dca8a0b75feb510b06c6341b70a8e500c2fdcff837cce",
            "pydantic_core-2.46.4.dist-info/licenses/LICENSE",
            "2afdd30d54b4d62b6f488a6bcc1546e84ec5061f13f4209c03d012348783795a",
        ),
    }
    for name, (wheel_sha256, member, license_sha256) in expected.items():
        evidence = sbom_module._LICENSE_EVIDENCE[
            f"{name}=={next(wheel.version for wheel in wheels if wheel.name == name)}"
        ]
        assert selected[name] == wheel_sha256
        assert evidence.source == f"wheel:{member}"
        assert evidence.identity == license_sha256
    fonttools = sbom_module._LICENSE_EVIDENCE["fonttools==4.63.0"]
    assert fonttools.additional == (
        (
            "wheel:fonttools-4.63.0.dist-info/licenses/LICENSE.external",
            "94a83aaee0729a0f302d34acc4acecbd9d58366f262429075fe557e4a54b2e69",
        ),
    )

    lock = tomllib.loads((REPOSITORY / "uv.lock").read_text(encoding="utf-8"))
    pyarrow = next(item for item in lock["package"] if item["name"] == "pyarrow")
    linux_wheel = next(item for item in pyarrow["wheels"] if "manylinux_2_28_x86_64" in item["url"])
    assert linux_wheel["hash"] == (
        "sha256:b7ae0bbdc8c6674259b25bef5d2a1d6af5d39d7200c819cf99e07f7dfef1c51e"
    )
    pyarrow_evidence = sbom_module._LICENSE_EVIDENCE["pyarrow==21.0.0"]
    assert pyarrow_evidence.source == "wheel:pyarrow-21.0.0.dist-info/LICENSE.txt"
    assert pyarrow_evidence.identity == (
        "82f5f9b0e6592da7f79022fc930add132a76c56727d29813f94058157a2b2d11"
    )
    assert pyarrow_evidence.additional == (
        (
            "wheel:pyarrow-21.0.0.dist-info/NOTICE.txt",
            "c946470d6b024c77feebdfb686bf92a828402c0ffc27c769bca7d8bef08e1db7",
        ),
    )


@pytest.mark.competition
def test_stage17_wheelhouse_license_verifier_is_offline_and_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    license_bytes = b"fixture license evidence\n"
    member = "fixture-1.0.dist-info/licenses/LICENSE"
    wheel_bytes = deterministic_zip_bytes({member: license_bytes})
    wheel = LockedWheel(
        name="fixture",
        version="1.0",
        filename="fixture-1.0-py3-none-any.whl",
        sha256=sha256_bytes(wheel_bytes),
        url="https://files.pythonhosted.org/fixture-1.0-py3-none-any.whl",
    )
    monkeypatch.setitem(
        sbom_module._LICENSE_EVIDENCE,
        "fixture==1.0",
        sbom_module._LicenseEvidence(
            "MIT", f"wheel:{member}", sha256_bytes(license_bytes).removeprefix("sha256:")
        ),
    )
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    archive = wheelhouse / wheel.filename
    archive.write_bytes(wheel_bytes)

    receipt = verify_wheelhouse_license_evidence((wheel,), wheelhouse)

    assert receipt["status"] == "PASS"
    assert receipt["packages"][0]["wheel_sha256"] == wheel.sha256  # type: ignore[index]
    archive.write_bytes(wheel_bytes + b"tampered")
    with pytest.raises(PackagingError, match="selected wheel hash mismatch"):
        verify_wheelhouse_license_evidence((wheel,), wheelhouse)


@pytest.mark.competition
def test_stage17_framework_identity_uses_raw_pinned_git_lf_hashes() -> None:
    assert launcher_module._PINNED_LF_FILES == {
        "LICENSE": "75c4276c506fd93082b38ad39f67ee97aa859574401ef978e701710c7a40af04",
        "agents/agent.py": ("49f1a349cd5e2123fceb266aec4a3a758d18ef5520e0212e808f695905d9e073"),
        "agents/recorder.py": ("0a08d89f4067a760012767c05d4406bd2bf409f426e29a1193106abfcbb696c8"),
        "agents/swarm.py": ("d9dc48f710f1b90a6552db0921293c7e89c8a925ed00a3faefa07ae19998ad39"),
    }


@pytest.mark.competition
def test_stage17_framework_identity_accepts_only_lf_or_exact_crlf(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    framework = tmp_path / "framework"
    agents = framework / "agents"
    agents.mkdir(parents=True)
    canonical = {
        "LICENSE": b"license line one\nlicense line two\n",
        "agents/agent.py": b"class Agent:\n    pass\n",
        "agents/recorder.py": b"class Recorder:\n    pass\n",
        "agents/swarm.py": b"class Swarm:\n    pass\n",
    }
    expected = {name: sha256(content).hexdigest() for name, content in canonical.items()}
    monkeypatch.setattr(launcher_module, "_PINNED_LF_FILES", expected)

    for relative, content in canonical.items():
        path = framework / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    assert launcher_module._validate_framework(framework, allow_test_fixture=False) == (
        launcher_module.AGENTS_COMMIT,
        f"git:{launcher_module.AGENTS_COMMIT}",
        False,
    )

    for relative, content in canonical.items():
        (framework / relative).write_bytes(content.replace(b"\n", b"\r\n"))
    assert launcher_module._validate_framework(framework, allow_test_fixture=False)[2] is False

    (agents / "swarm.py").write_bytes(b"class Swarm:\r\n    pass\n")
    with pytest.raises(PackagingError, match="differs from pinned"):
        launcher_module._validate_framework(framework, allow_test_fixture=False)

    (agents / "swarm.py").write_bytes(b"class Swarm:\r\n    mutated\r\n")
    with pytest.raises(PackagingError, match="differs from pinned"):
        launcher_module._validate_framework(framework, allow_test_fixture=False)


@pytest.mark.competition
def test_stage17_runtime_launcher_registers_only_first_party_agent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    framework = tmp_path / "framework"
    agents = framework / "agents"
    agents.mkdir(parents=True)
    (agents / "agent.py").write_text(
        "from dotenv import load_dotenv\n"
        "load_dotenv()\n\n"
        "class Agent:\n"
        "    def __init__(self, *, game_id, agent_name, **kwargs):\n"
        "        self.game_id = game_id\n"
        "        self.agent_name = agent_name\n"
        "        self.kwargs = kwargs\n\n"
        "class Playback(Agent):\n"
        "    pass\n",
        encoding="utf-8",
    )
    (framework / ".arc3-safe-fixture").write_text(
        "arc3.stage17.safe-framework.v0.1", encoding="utf-8"
    )
    receipt = tmp_path / "launch-receipt.json"
    (agents / "swarm.py").write_text(
        "import json\n"
        "import os\n"
        "import sys\n"
        "import time\n"
        "from threading import Lock, Thread\n"
        "from types import ModuleType\n"
        "from pathlib import Path\n"
        "class Swarm:\n"
        "    def __init__(self, agent, root_url, games, tags=None):\n"
        "        from agents import AVAILABLE_AGENTS\n"
        "        self.agent, self.root_url, self.games = agent, root_url, games\n"
        "        self.agent_class = AVAILABLE_AGENTS[agent]\n"
        "        self.agents, self.threads = [], []\n"
        "    def main(self):\n"
        "        sys.modules['stage17_native_extension_sentinel'] = ModuleType("
        "'stage17_native_extension_sentinel')\n"
        "        lock = Lock()\n"
        "        state = {'active': 0, 'max_active': 0, 'execution_order': []}\n"
        "        def run(current):\n"
        "            with lock:\n"
        "                state['active'] += 1\n"
        "                state['max_active'] = max(state['max_active'], state['active'])\n"
        "            time.sleep(0.01)\n"
        "            state['execution_order'].append(current.game_id)\n"
        "            with lock:\n"
        "                state['active'] -= 1\n"
        "        for game_id in self.games:\n"
        "            current = self.agent_class(game_id=game_id, agent_name=self.agent, "
        "ROOT_URL=self.root_url, record=True, arc_env=object(), tags=[])\n"
        "            self.agents.append(current)\n"
        "            self.threads.append(Thread(target=run, args=(current,), daemon=True))\n"
        "        for thread in self.threads:\n"
        "            thread.start()\n"
        "        for thread in self.threads:\n"
        "            thread.join()\n"
        f"        Path({str(receipt)!r}).write_text(\n"
        "            json.dumps({'agent': self.agent, 'base_url': self.root_url, "
        "'games': self.games, 'sensitive_visible': sorted(key for key in "
        "('OPENAI_API_KEY', 'AGENTOPS_API_KEY') if key in os.environ), "
        "'working_root': os.environ['ARC3_WORKING_DIR'], "
        "'agent_game_ids': [current.game_id for current in self.agents], "
        "'unique_agent_count': len({id(current) for current in self.agents}), "
        "'max_active': state['max_active'], "
        "'execution_order': state['execution_order']}), "
        "encoding='utf-8')\n",
        encoding="utf-8",
    )
    agent = tmp_path / "my_agent.py"
    agent.write_text(
        "from agents.agent import Agent\n\n"
        "class MyAgent(Agent):\n"
        "    configured_games = ()\n"
        "    @classmethod\n"
        "    def configure_tournament(cls, games, working_root):\n"
        "        del working_root\n"
        "        cls.configured_games = tuple(games)\n"
        "    @classmethod\n"
        "    def finalize_tournament(cls):\n"
        "        return {\n"
        "            'effective_ceiling_respected': True,\n"
        "            'expected_environments': len(cls.configured_games),\n"
        "            'finalized_environments': len(cls.configured_games),\n"
        "            'games': [{'game_id': game} for game in cls.configured_games],\n"
        "            'maximum_total_actions': max(1, 80 * len(cls.configured_games)),\n"
        "            'outcome': 'complete-reserve-preserved',\n"
        "            'reserve_preserved': True,\n"
        "            'total_actions_authorized': 0,\n"
        "        }\n",
        encoding="utf-8",
    )
    discovered_games = ("fixture-game-1", "fixture-game-2", "fixture-game-3")
    monkeypatch.setattr(launcher_module, "_discover_games", lambda host, port: discovered_games)
    prior_key = os.environ.get("ARC_API_KEY")
    prior_dotenv = sys.modules.get("dotenv")
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-reach-framework")
    monkeypatch.setenv("AGENTOPS_API_KEY", "must-not-reach-framework")
    runtime_root = tmp_path / "runtime"

    result = launch_competition_framework(
        framework,
        agent,
        working_root=runtime_root,
        allow_test_fixture=True,
    )

    launched = json.loads(receipt.read_text(encoding="utf-8"))
    assert launched == {
        "agent": "myagent",
        "agent_game_ids": list(discovered_games),
        "base_url": "http://gateway:8001/",
        "execution_order": list(discovered_games),
        "games": list(discovered_games),
        "max_active": 1,
        "sensitive_visible": [],
        "unique_agent_count": 3,
        "working_root": str(runtime_root.resolve()),
    }
    assert result.framework_fixture is True
    assert result.framework_identity == "arc3.stage17.safe-framework.v0.1"
    assert result.agent_count == 3
    assert result.worker_count == 3
    assert result.max_concurrency == 1
    assert result.orchestration == "arc3.sequential-pinned-swarm.v1"
    assert result.dotenv_imported is False
    assert result.telemetry_imported is False
    assert os.environ.get("ARC_API_KEY") == prior_key
    assert os.environ["OPENAI_API_KEY"] == "must-not-reach-framework"
    assert os.environ["AGENTOPS_API_KEY"] == "must-not-reach-framework"
    assert sys.modules.get("dotenv") is prior_dotenv
    assert "stage17_native_extension_sentinel" in sys.modules
    sys.modules.pop("stage17_native_extension_sentinel")

    with pytest.raises(PackagingError, match="gateway host"):
        launch_competition_framework(
            framework,
            agent,
            gateway_host="example.com",
            allow_test_fixture=True,
        )
