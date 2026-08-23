"""Generate the single offline notebook used as the Kaggle code artifact."""

from __future__ import annotations

import base64
import binascii
import hashlib
import re
from dataclasses import dataclass

from arc3.packaging.models import PackagingError
from arc3.types import JSONValue

COMPETITION_SLUG = "arc-prize-2026-arc-agi-3"
DEFAULT_INPUT_ROOT = f"/kaggle/input/competitions/{COMPETITION_SLUG}"
REHEARSAL_AUTHORITY = "arc3.stage17.notebook-rehearsal.v0.1"
_EMBEDDED_REQUIREMENTS = re.compile(
    r'embedded_requirements = base64\.b64decode\("([A-Za-z0-9+/=]*)"\)'
)
_EMBEDDED_PAYLOAD = re.compile(r'payload_bytes = base64\.b64decode\("([A-Za-z0-9+/=]*)"\)')
_EMBEDDED_VALIDATION = re.compile(
    r'output_path\.write_bytes\(base64\.b64decode\("([A-Za-z0-9+/=]*)"\)\)'
)
_EMBEDDED_COMMIT = re.compile(r'os\.environ\["ARC3_GIT_COMMIT"\] = "([0-9a-f]{40})"')


@dataclass(frozen=True, slots=True)
class NotebookEmbeddedInputs:
    """Immutable inputs recovered from an exact generated notebook contract."""

    payload: bytes
    requirements: bytes
    source_commit: str
    validation_parquet: bytes


def _code_cell(source: str, tag: str) -> dict[str, JSONValue]:
    return {
        "cell_type": "code",
        "execution_count": None,
        "metadata": {"tags": [tag], "trusted": True},
        "outputs": [],
        "source": source,
    }


def _markdown_cell(source: str) -> dict[str, JSONValue]:
    return {"cell_type": "markdown", "metadata": {}, "source": source}


def build_kernel_metadata(*, owner_username: str = "OWNER_USERNAME") -> dict[str, JSONValue]:
    """Return CPU-only, no-internet Kaggle kernel metadata without credentials."""

    return {
        "code_file": "arc3-submission.ipynb",
        "competition_sources": [COMPETITION_SLUG],
        "dataset_sources": [],
        "enable_gpu": False,
        "enable_internet": False,
        "enable_tpu": False,
        "id": f"{owner_username}/arc3-offline-candidate",
        "is_private": True,
        "kernel_sources": [],
        "kernel_type": "notebook",
        "keywords": ["arc-agi-3", "offline", "symbolic"],
        "language": "python",
        "model_sources": [],
        "title": "ARC3 offline competition candidate",
    }


def build_notebook(
    *,
    payload: bytes,
    payload_sha256: str,
    runtime_requirements: bytes,
    requirements_sha256: str,
    validation_parquet: bytes,
    source_commit: str,
) -> dict[str, JSONValue]:
    """Build a deterministic notebook containing the complete first-party payload."""

    payload_b64 = base64.b64encode(payload).decode("ascii")
    requirements_b64 = base64.b64encode(runtime_requirements).decode("ascii")
    parquet_b64 = base64.b64encode(validation_parquet).decode("ascii")
    install_source = f'''import base64
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

if os.environ.get("KAGGLE_IS_COMPETITION_RERUN"):
    fixture = (
        globals().get("_ARC3_REHEARSAL_AUTHORITY") == "{REHEARSAL_AUTHORITY}"
        and os.environ.get("ARC3_REHEARSAL_FIXTURE") == "1"
    )
    working_root = (
        Path(os.environ["ARC3_WORKING_DIR"]) if fixture else Path("/kaggle/working")
    )
    working_root.mkdir(parents=True, exist_ok=True)
    embedded_requirements = base64.b64decode("{requirements_b64}")
    embedded_digest = "sha256:" + hashlib.sha256(embedded_requirements).hexdigest()
    if embedded_digest != "{requirements_sha256}":
        raise RuntimeError("embedded Linux requirements hash mismatch")
    embedded_path = working_root / "arc3-runtime-linux-cp312.txt"
    embedded_path.write_bytes(embedded_requirements)
    if fixture:
        input_root = Path(os.environ["ARC3_COMPETITION_INPUT"])
        requirements_path = Path(os.environ["ARC3_REHEARSAL_REQUIREMENTS"])
    else:
        input_root = Path("{DEFAULT_INPUT_ROOT}")
        requirements_path = embedded_path
    wheel_root = input_root / "arc_agi_3_wheels"
    dependency_root = working_root / "arc3_dependencies"
    dependency_root.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "--no-cache-dir",
        "--no-index",
        "--no-deps",
        "--require-hashes",
        "--only-binary=:all:",
        "--no-compile",
        "--find-links",
        str(wheel_root),
        "--target",
        str(dependency_root),
        "-r",
        str(requirements_path),
    ]
    keep = {{"PATH", "SYSTEMROOT", "TEMP", "TMP", "TMPDIR", "WINDIR"}}
    pip_environment = {{name: value for name, value in os.environ.items() if name in keep}}
    pip_environment.update({{
        "PIP_CONFIG_FILE": os.devnull,
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        "PIP_NO_INDEX": "1",
        "PIP_NO_CACHE_DIR": "1",
        "PYTHONHASHSEED": "0",
        "PYTHONNOUSERSITE": "1",
    }})
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        env=pip_environment,
        text=True,
        timeout=300,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "offline no-index dependency install failed: " + completed.stderr[-2000:]
        )
    sys.path.insert(0, str(dependency_root))
    requirement_bytes = requirements_path.read_bytes()
    wheel_hashes = sorted(
        "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
        for path in wheel_root.glob("*.whl")
    )
    install_receipt = {{
        "dependency_install_status": "PASS",
        "fixture": fixture,
        "no_deps": True,
        "no_index": True,
        "require_hashes": True,
        "requirements_sha256": "sha256:" + hashlib.sha256(requirement_bytes).hexdigest(),
        "wheel_sha256": wheel_hashes,
    }}
    (working_root / "arc3-install-receipt.json").write_text(
        json.dumps(install_receipt, sort_keys=True), encoding="utf-8"
    )
'''
    bootstrap_source = f'''import base64
import hashlib
import os
import sys
import zipfile
from pathlib import Path, PurePosixPath

fixture = (
    globals().get("_ARC3_REHEARSAL_AUTHORITY") == "{REHEARSAL_AUTHORITY}"
    and os.environ.get("ARC3_REHEARSAL_FIXTURE") == "1"
)
working_root = Path(os.environ["ARC3_WORKING_DIR"]) if fixture else Path("/kaggle/working")
bundle_root = working_root / "arc3_submission"
payload_path = working_root / "arc3-first-party.zip"
payload_bytes = base64.b64decode("{payload_b64}")
payload_digest = "sha256:" + hashlib.sha256(payload_bytes).hexdigest()
if payload_digest != "{payload_sha256}":
    raise RuntimeError("embedded ARC3 payload hash mismatch")
working_root.mkdir(parents=True, exist_ok=True)
payload_path.write_bytes(payload_bytes)
with zipfile.ZipFile(payload_path) as archive:
    for member in archive.namelist():
        parsed = PurePosixPath(member)
        if parsed.is_absolute() or ".." in parsed.parts or "\\\\" in member:
            raise RuntimeError("unsafe embedded ARC3 payload member")
    archive.extractall(bundle_root)
sys.path.insert(0, str(bundle_root / "src"))
sys.path.insert(0, str(bundle_root))
os.environ["ARC3_MODE"] = "competition"
os.environ["ARC3_NETWORK_ENABLED"] = "false"
os.environ["ARC3_SEED"] = os.environ.get("ARC3_SEED", "0")
os.environ["ARC3_GIT_COMMIT"] = "{source_commit}"
os.environ["ARC3_WORKING_DIR"] = str(working_root)
'''
    launch_source = f'''import json
import os
import socket
import time
from pathlib import Path

if os.environ.get("KAGGLE_IS_COMPETITION_RERUN"):
    from arc3.packaging.runtime_launcher import launch_competition_framework

    fixture = (
        globals().get("_ARC3_REHEARSAL_AUTHORITY") == "{REHEARSAL_AUTHORITY}"
        and os.environ.get("ARC3_REHEARSAL_FIXTURE") == "1"
    )
    if fixture:
        input_root = Path(os.environ["ARC3_COMPETITION_INPUT"])
        gateway_host = os.environ["ARC3_GATEWAY_HOST"]
        gateway_port = int(os.environ["ARC3_GATEWAY_PORT"])
    else:
        input_root = Path("{DEFAULT_INPUT_ROOT}")
        gateway_host = "gateway"
        gateway_port = 8001
    if gateway_host not in {{"gateway", "localhost", "127.0.0.1", "::1"}}:
        raise RuntimeError("competition gateway host is not platform-local")
    gateway_deadline = time.monotonic() + (30.0 if fixture else 600.0)
    while True:
        try:
            with socket.create_connection((gateway_host, gateway_port), timeout=5.0):
                break
        except OSError:
            if time.monotonic() >= gateway_deadline:
                raise RuntimeError("Kaggle-local gateway did not become ready within 600 seconds")
            time.sleep(5.0)
    launch_receipt = launch_competition_framework(
        input_root / "ARC-AGI-3-Agents",
        bundle_root / "agent" / "my_agent.py",
        gateway_host=gateway_host,
        gateway_port=gateway_port,
        working_root=working_root,
        allow_test_fixture=fixture,
    )
    (working_root / "arc3-launch-receipt.json").write_text(
        json.dumps(launch_receipt.to_dict(), sort_keys=True), encoding="utf-8"
    )
'''
    validation_source = f'''import base64
import os
from pathlib import Path

if not os.environ.get("KAGGLE_IS_COMPETITION_RERUN"):
    fixture = (
        globals().get("_ARC3_REHEARSAL_AUTHORITY") == "{REHEARSAL_AUTHORITY}"
        and os.environ.get("ARC3_REHEARSAL_FIXTURE") == "1"
    )
    working_root = Path(os.environ["ARC3_WORKING_DIR"]) if fixture else Path("/kaggle/working")
    output_path = working_root / "submission.parquet"
    output_path.write_bytes(base64.b64decode("{parquet_b64}"))
'''
    return {
        "cells": [
            _markdown_cell(
                "# ARC3 offline competition candidate\n\n"
                "First-party symbolic controller package prepared for owner review. "
                "The notebook does not submit itself and contains no credential."
            ),
            _code_cell(install_source, "arc3-offline-dependencies"),
            _code_cell(bootstrap_source, "arc3-payload-bootstrap"),
            _code_cell(launch_source, "arc3-competition-launch"),
            _code_cell(validation_source, "arc3-validation-output"),
        ],
        "metadata": {
            "kaggle": {
                "accelerator": "none",
                "isGpuEnabled": False,
                "isInternetEnabled": False,
                "language": "python",
                "sourceType": "notebook",
            },
            "kernelspec": {
                "display_name": "Python 3",
                "language": "python",
                "name": "python3",
            },
            "language_info": {
                "file_extension": ".py",
                "mimetype": "text/x-python",
                "name": "python",
                "pygments_lexer": "ipython3",
            },
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }


def _embedded_bytes(pattern: re.Pattern[str], source: str, *, label: str) -> bytes:
    matches = pattern.findall(source)
    if len(matches) != 1:
        raise PackagingError(f"notebook has no unique generated {label} embedding")
    try:
        return base64.b64decode(matches[0], validate=True)
    except (ValueError, binascii.Error) as error:
        raise PackagingError(f"notebook generated {label} embedding is invalid") from error


def _validated_notebook_embedded_inputs(
    document: dict[str, JSONValue],
) -> NotebookEmbeddedInputs:
    """Fail closed if generated metadata could enable internet or accelerators."""

    metadata = document.get("metadata")
    if not isinstance(metadata, dict):
        raise PackagingError("notebook metadata is missing")
    kaggle = metadata.get("kaggle")
    if not isinstance(kaggle, dict):
        raise PackagingError("notebook Kaggle metadata is missing")
    if kaggle.get("isInternetEnabled") is not False:
        raise PackagingError("notebook must disable internet")
    if kaggle.get("isGpuEnabled") is not False or kaggle.get("accelerator") != "none":
        raise PackagingError("symbolic competition notebook must default to CPU")
    cells = document.get("cells")
    if not isinstance(cells, list) or not cells:
        raise PackagingError("notebook must contain cells")
    code_sources: list[str] = []
    for raw_cell in cells:
        if not isinstance(raw_cell, dict):
            raise PackagingError("notebook cell must be an object")
        if raw_cell.get("cell_type") != "code":
            continue
        outputs = raw_cell.get("outputs")
        execution_count = raw_cell.get("execution_count")
        source = raw_cell.get("source")
        if outputs != [] or execution_count is not None or not isinstance(source, str):
            raise PackagingError("generated code cells must be clean and unexecuted")
        compile(source, "<arc3-generated-notebook-cell>", "exec")
        code_sources.append(source)
    if len(code_sources) != 4:
        raise PackagingError("notebook must contain exactly four generated code cells")
    requirements = _embedded_bytes(
        _EMBEDDED_REQUIREMENTS,
        code_sources[0],
        label="requirements",
    )
    payload = _embedded_bytes(_EMBEDDED_PAYLOAD, code_sources[1], label="payload")
    validation_parquet = _embedded_bytes(
        _EMBEDDED_VALIDATION,
        code_sources[3],
        label="validation output",
    )
    commit_matches = _EMBEDDED_COMMIT.findall(code_sources[1])
    if len(commit_matches) != 1:
        raise PackagingError("notebook has no unique generated source commit")
    expected = build_notebook(
        payload=payload,
        payload_sha256="sha256:" + hashlib.sha256(payload).hexdigest(),
        runtime_requirements=requirements,
        requirements_sha256="sha256:" + hashlib.sha256(requirements).hexdigest(),
        validation_parquet=validation_parquet,
        source_commit=commit_matches[0],
    )
    if document != expected:
        raise PackagingError("notebook differs from the strict generated cell/source contract")
    joined = "\n".join(code_sources).lower()
    if "--no-index" not in joined:
        raise PackagingError("notebook dependency installation must be offline-only")
    if "--require-hashes" not in joined or "--no-deps" not in joined:
        raise PackagingError("notebook dependency installation must enforce the exact lock")
    if 'arc3_network_enabled"] = "false"' not in joined:
        raise PackagingError("notebook must force the first-party network flag off")
    for hosted_domain in (
        "api.openai.com",
        "api.anthropic.com",
        "generativelanguage.googleapis.com",
        "api.x.ai",
    ):
        if hosted_domain in joined:
            raise PackagingError(f"hosted inference endpoint found in notebook: {hosted_domain}")
    for forbidden_runtime in ("load_dotenv", "agentops"):
        if forbidden_runtime in joined:
            raise PackagingError(f"forbidden competition bootstrap found: {forbidden_runtime}")
    for submission_call in (
        "kaggle kernels push",
        "kaggle competitions submit",
        "kaggle api",
    ):
        if submission_call in joined:
            raise PackagingError(f"human-gated Kaggle write found in notebook: {submission_call}")
    return NotebookEmbeddedInputs(
        payload=payload,
        requirements=requirements,
        source_commit=commit_matches[0],
        validation_parquet=validation_parquet,
    )


def validate_notebook(document: dict[str, JSONValue]) -> None:
    """Fail closed unless the notebook is the exact generated executable contract."""

    _validated_notebook_embedded_inputs(document)


def notebook_embedded_inputs(document: dict[str, JSONValue]) -> NotebookEmbeddedInputs:
    """Validate and project the exact executable bytes embedded in a notebook."""

    return _validated_notebook_embedded_inputs(document)


def validate_kernel_metadata(document: dict[str, JSONValue]) -> None:
    if document.get("enable_internet") is not False:
        raise PackagingError("kernel metadata must disable internet")
    if document.get("enable_gpu") is not False or document.get("enable_tpu") is not False:
        raise PackagingError("kernel metadata must select CPU")
    sources = document.get("competition_sources")
    if sources != [COMPETITION_SLUG]:
        raise PackagingError("kernel metadata must name only the ARC-AGI-3 competition input")
    code_file = document.get("code_file")
    if code_file != "arc3-submission.ipynb":
        raise PackagingError("kernel metadata code_file does not match the generated notebook")


def code_sources(document: dict[str, JSONValue]) -> tuple[str, ...]:
    """Return code sources for the sandbox runner after notebook validation."""

    validate_notebook(document)
    raw_cells = document["cells"]
    if not isinstance(raw_cells, list):  # pragma: no cover - established above
        raise PackagingError("notebook cells are missing")
    sources: list[str] = []
    for raw in raw_cells:
        if isinstance(raw, dict) and raw.get("cell_type") == "code":
            source = raw.get("source")
            if isinstance(source, str):
                sources.append(source)
    return tuple(sources)


__all__ = [
    "COMPETITION_SLUG",
    "DEFAULT_INPUT_ROOT",
    "REHEARSAL_AUTHORITY",
    "NotebookEmbeddedInputs",
    "build_kernel_metadata",
    "build_notebook",
    "code_sources",
    "notebook_embedded_inputs",
    "validate_kernel_metadata",
    "validate_notebook",
]
