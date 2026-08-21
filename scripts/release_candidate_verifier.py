"""Run and seal the Stage 18 clean-clone release-candidate checks.

The verifier is intentionally a repository-side orchestrator. A caller creates a
fresh clone, follows the documented bootstrap, and then invokes this script with
the literal candidate commit. The script does not clone, install, authenticate,
accept terms, upload, submit, or mutate tracked repository files.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from arc3.evaluation.artifacts import canonical_json_bytes as evaluation_canonical_json_bytes
from arc3.packaging.util import canonical_json_bytes as package_canonical_json_bytes

SCHEMA = "arc3.release-candidate-verification.v0.1"
PLAN_SCHEMA = "arc3.release-candidate-plan.v0.1"
EXPECTATION_SCHEMA = "arc3.release-benchmark-expectation.v0.1"
RECEIPT_HASH_FIELD = "receipt_sha256"
EXPECTATION_HASH_FIELD = "expectation_sha256"
REPOSITORY = Path(__file__).resolve().parents[1]
DEFAULT_EXPECTATION = Path(__file__).with_name("release_candidate_benchmark.v0.1.json")

_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_SAFE_CHECK_ID = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_SENSITIVE_ENV_FRAGMENTS = (
    "API_KEY",
    "AUTH",
    "CREDENTIAL",
    "KAGGLE",
    "PASSWORD",
    "SECRET",
    "TOKEN",
)
_PASSTHROUGH_ENVIRONMENT = frozenset(
    {
        "COMSPEC",
        "LANG",
        "LC_ALL",
        "PATH",
        "PATHEXT",
        "SYSTEMDRIVE",
        "SYSTEMROOT",
        "WINDIR",
    }
)
_SECRET_PATTERNS = (
    re.compile(rb"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----"),
    re.compile(rb"(?i)\b(?:sk-[a-z0-9_-]{16,}|gh[oprsu]_[a-z0-9]{16,})\b"),
    re.compile(rb"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(rb"\bAIza[0-9A-Za-z_-]{30,}\b"),
    re.compile(rb"\beyJ[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\b"),
    re.compile(
        rb"(?i)\b(?:api[_-]?key|authorization|credential|password|secret|token)"
        rb"\s*[:=]\s*['\"]?[^\s'\"]{8,}"
    ),
)
_TRANSIENT_OUTPUT_PREFIXES = ("cache/", "coverage/", "home/", "hypothesis/", "tmp/")
_RECEIPT_WRAPPERS = frozenset(
    {"release-verification-evidence.json", "release-verification-receipt.json"}
)
_INTERNAL_CHECKS = (
    "benchmark-basis-validation",
    "benchmark-semantic-reproduction",
    "generated-log-secret-scan",
    "interpreter-source-identity",
    "offline-package-determinism",
    "integrity-receipt-validation",
    "official-availability",
    "repository-clean-after",
    "sealed-artifact-set",
)


def canonical_json_bytes(value: object) -> bytes:
    """Encode a JSON value deterministically, rejecting non-finite floats."""

    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    """Return the repository's qualified SHA-256 spelling."""

    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def sha256_file(path: Path) -> str:
    """Hash one regular file without following a replacement during the read."""

    if not path.is_file() or path.is_symlink():
        raise ValueError(f"artifact must be a regular non-symlink file: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def write_bytes_atomic(path: Path, content: bytes) -> None:
    """Write one evidence file atomically on the destination filesystem."""

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _json_object(path: Path) -> dict[str, Any]:
    try:
        loaded: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read JSON object {path}: {error}") from error
    if not isinstance(loaded, dict):
        raise ValueError(f"JSON artifact must contain an object: {path}")
    return cast(dict[str, Any], loaded)


def _verified_self_hashed_object(path: Path, *, hash_field: str) -> dict[str, Any]:
    document = _json_object(path)
    claimed = document.pop(hash_field, None)
    if not isinstance(claimed, str):
        raise ValueError(f"{path} has no string {hash_field}")
    actual = sha256_bytes(canonical_json_bytes(document))
    if claimed != actual:
        raise ValueError(f"{path} {hash_field} mismatch: expected {claimed}, computed {actual}")
    return document


def _package_receipt_bytes(body: Mapping[str, Any]) -> bytes:
    """Encode a Stage 17 package receipt with its producer's LF-terminated contract."""

    document = dict(body)
    document[RECEIPT_HASH_FIELD] = sha256_bytes(package_canonical_json_bytes(body))
    return package_canonical_json_bytes(document)


def _verified_package_receipt(path: Path) -> dict[str, Any]:
    """Verify a Stage 17 package receipt without changing Stage 18 canonical JSON."""

    document = _json_object(path)
    claimed = document.pop(RECEIPT_HASH_FIELD, None)
    if not isinstance(claimed, str):
        raise ValueError(f"{path} has no string {RECEIPT_HASH_FIELD}")
    actual = sha256_bytes(package_canonical_json_bytes(document))
    if claimed != actual:
        raise ValueError(
            f"{path} {RECEIPT_HASH_FIELD} mismatch: expected {claimed}, computed {actual}"
        )
    if _package_receipt_bytes(document) != path.read_bytes():
        raise ValueError(f"package receipt is not canonical JSON: {path}")
    return document


def load_benchmark_expectation(path: Path) -> dict[str, Any]:
    """Load and self-verify the frozen semantic benchmark expectation."""

    document = _verified_self_hashed_object(path, hash_field=EXPECTATION_HASH_FIELD)
    if document.get("schema") != EXPECTATION_SCHEMA:
        raise ValueError(f"unsupported benchmark expectation schema in {path}")
    configuration = document.get("configuration")
    projection = document.get("expected_projection")
    if not isinstance(configuration, dict) or not isinstance(projection, dict):
        raise ValueError("benchmark expectation must contain configuration and projection objects")
    return document


@dataclass(frozen=True, slots=True)
class CommandSpec:
    """One exact process declaration in the release verification plan."""

    check_id: str
    category: str
    argv: tuple[str, ...]
    timeout_seconds: float
    required: bool = True
    dependencies: tuple[str, ...] = ()
    failure_status: str = "FAILED_MECHANISM"
    nondeterminism: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not _SAFE_CHECK_ID.fullmatch(self.check_id):
            raise ValueError(f"invalid check id: {self.check_id!r}")
        if not self.argv or not all(self.argv):
            raise ValueError(f"check {self.check_id} has an empty command")
        if self.timeout_seconds <= 0:
            raise ValueError(f"check {self.check_id} has a non-positive timeout")
        if self.failure_status not in {"FAILED_MECHANISM", "FAILED_INFRASTRUCTURE"}:
            raise ValueError(f"check {self.check_id} has an invalid failure status")

    def to_dict(self) -> dict[str, object]:
        return {
            "argv": list(self.argv),
            "category": self.category,
            "dependencies": list(self.dependencies),
            "failure_status": self.failure_status,
            "id": self.check_id,
            "nondeterminism": list(self.nondeterminism),
            "required": self.required,
            "timeout_seconds": self.timeout_seconds,
        }


@dataclass(frozen=True, slots=True)
class CheckResult:
    """One process or internal verification result."""

    check_id: str
    category: str
    kind: str
    required: bool
    status: str
    started_at: str | None
    completed_at: str | None
    duration_seconds: float | None
    argv: tuple[str, ...]
    exit_code: int | None
    stdout_log: str | None
    stdout_sha256: str | None
    stderr_log: str | None
    stderr_sha256: str | None
    reason: str | None
    details: Mapping[str, object]

    def to_dict(self) -> dict[str, object]:
        return {
            "argv": list(self.argv),
            "category": self.category,
            "completed_at": self.completed_at,
            "details": dict(self.details),
            "duration_seconds": self.duration_seconds,
            "exit_code": self.exit_code,
            "id": self.check_id,
            "kind": self.kind,
            "reason": self.reason,
            "required": self.required,
            "started_at": self.started_at,
            "status": self.status,
            "stderr_log": self.stderr_log,
            "stderr_sha256": self.stderr_sha256,
            "stdout_log": self.stdout_log,
            "stdout_sha256": self.stdout_sha256,
        }


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _path_for_receipt(path: Path, base: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(base.resolve()).as_posix()
    except ValueError:
        return str(resolved)


def _display_command(argv: Sequence[str]) -> str:
    if os.name == "nt":
        return subprocess.list2cmdline(list(argv))
    return shlex.join(argv)


def _sensitive_environment_values() -> tuple[bytes, ...]:
    values = {
        value.encode("utf-8", errors="ignore")
        for name, value in os.environ.items()
        if any(fragment in name.upper() for fragment in _SENSITIVE_ENV_FRAGMENTS)
        and len(value) >= 8
    }
    return tuple(sorted(values, key=len, reverse=True))


def _redact_generated_log(content: bytes) -> tuple[bytes, int]:
    """Remove inherited credential values and recognizable token assignments before writing."""

    redacted = content
    replacements = 0
    for value in _sensitive_environment_values():
        count = redacted.count(value)
        if count:
            redacted = redacted.replace(value, b"[REDACTED_ENV_VALUE]")
            replacements += count
    for pattern in _SECRET_PATTERNS:
        redacted, count = pattern.subn(b"[REDACTED_SECRET_PATTERN]", redacted)
        replacements += count
    return redacted, replacements


def _sanitized_environment(output_root: Path, check_id: str) -> tuple[dict[str, str], int]:
    environment = {
        name: value
        for name, value in os.environ.items()
        if name.upper() in _PASSTHROUGH_ENVIRONMENT
    }
    removed = len(os.environ) - len(environment)
    temporary = output_root / "tmp" / check_id
    coverage = output_root / "coverage"
    hypothesis = output_root / "hypothesis" / check_id
    mypy_cache = output_root / "cache" / "mypy" / check_id
    ruff_cache = output_root / "cache" / "ruff" / check_id
    isolated_home = output_root / "home" / check_id
    uv_cache = output_root / "cache" / "uv" / check_id
    for directory in (
        temporary,
        coverage,
        hypothesis,
        mypy_cache,
        ruff_cache,
        isolated_home,
        uv_cache,
    ):
        directory.mkdir(parents=True, exist_ok=True)
    environment.update(
        {
            "COVERAGE_FILE": str(coverage / f".{check_id}.coverage"),
            "HYPOTHESIS_STORAGE_DIRECTORY": str(hypothesis),
            "MYPY_CACHE_DIR": str(mypy_cache),
            "NO_PROXY": "*",
            "PIP_NO_INDEX": "1",
            "PYTHONHASHSEED": "0",
            "PYTHONNOUSERSITE": "1",
            "RUFF_CACHE_DIR": str(ruff_cache),
            "HOME": str(isolated_home),
            "TEMP": str(temporary),
            "TMP": str(temporary),
            "USERPROFILE": str(isolated_home),
            "UV_CACHE_DIR": str(uv_cache),
            "UV_OFFLINE": "1",
            "XDG_CACHE_HOME": str(output_root / "cache" / "xdg" / check_id),
        }
    )
    return environment, removed


def _blocked_result(spec: CommandSpec, reason: str, *, status: str) -> CheckResult:
    return CheckResult(
        check_id=spec.check_id,
        category=spec.category,
        kind="command",
        required=spec.required,
        status=status,
        started_at=None,
        completed_at=None,
        duration_seconds=None,
        argv=spec.argv,
        exit_code=None,
        stdout_log=None,
        stdout_sha256=None,
        stderr_log=None,
        stderr_sha256=None,
        reason=reason,
        details={"command": _display_command(spec.argv)},
    )


def run_command(
    spec: CommandSpec,
    *,
    repository: Path,
    output_root: Path,
    prior: Mapping[str, CheckResult],
) -> CheckResult:
    """Run one command without a shell and seal both byte streams."""

    failed_dependencies = [
        dependency
        for dependency in spec.dependencies
        if dependency not in prior or prior[dependency].status != "PASS"
    ]
    if failed_dependencies:
        return _blocked_result(
            spec,
            f"dependency checks did not pass: {', '.join(failed_dependencies)}",
            status=spec.failure_status,
        )

    environment, removed_sensitive_variables = _sanitized_environment(output_root, spec.check_id)
    log_root = output_root / "logs"
    stdout_path = log_root / f"{spec.check_id}.stdout.log"
    stderr_path = log_root / f"{spec.check_id}.stderr.log"
    started_at = _utc_now()
    started = time.perf_counter()
    return_code: int | None = None
    stdout = b""
    stderr = b""
    status = spec.failure_status
    reason: str | None = None
    try:
        completed = subprocess.run(
            list(spec.argv),
            cwd=repository,
            env=environment,
            check=False,
            capture_output=True,
            timeout=spec.timeout_seconds,
        )
        return_code = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr
        if return_code == 0:
            status = "PASS"
        else:
            reason = f"command returned exit code {return_code}"
    except subprocess.TimeoutExpired as error:
        status = "FAILED_INFRASTRUCTURE"
        reason = f"command exceeded {spec.timeout_seconds} seconds"
        stdout = error.stdout or b""
        stderr = error.stderr or b""
    except OSError as error:
        status = "FAILED_INFRASTRUCTURE"
        reason = f"command could not start: {type(error).__name__}: {error}"
        stderr = reason.encode("utf-8", errors="replace")
    completed_at = _utc_now()
    duration = time.perf_counter() - started
    stdout, stdout_redactions = _redact_generated_log(stdout)
    stderr, stderr_redactions = _redact_generated_log(stderr)
    write_bytes_atomic(stdout_path, stdout)
    write_bytes_atomic(stderr_path, stderr)
    return CheckResult(
        check_id=spec.check_id,
        category=spec.category,
        kind="command",
        required=spec.required,
        status=status,
        started_at=started_at,
        completed_at=completed_at,
        duration_seconds=duration,
        argv=spec.argv,
        exit_code=return_code,
        stdout_log=_path_for_receipt(stdout_path, output_root),
        stdout_sha256=sha256_bytes(stdout),
        stderr_log=_path_for_receipt(stderr_path, output_root),
        stderr_sha256=sha256_bytes(stderr),
        reason=reason,
        details={
            "command": _display_command(spec.argv),
            "environment_policy": "strict allowlist plus isolated writable homes and caches",
            "generated_log_redactions": stdout_redactions + stderr_redactions,
            "nondeterminism": list(spec.nondeterminism),
            "non_allowlisted_environment_variables_removed": removed_sensitive_variables,
        },
    )


def internal_result(
    check_id: str,
    category: str,
    *,
    status: str,
    reason: str | None = None,
    details: Mapping[str, object] | None = None,
    required: bool = True,
) -> CheckResult:
    """Create a typed result for a deterministic in-process comparison."""

    if not _SAFE_CHECK_ID.fullmatch(check_id):
        raise ValueError(f"invalid check id: {check_id!r}")
    moment = _utc_now()
    return CheckResult(
        check_id=check_id,
        category=category,
        kind="internal",
        required=required,
        status=status,
        started_at=moment,
        completed_at=moment,
        duration_seconds=0.0,
        argv=(),
        exit_code=None,
        stdout_log=None,
        stdout_sha256=None,
        stderr_log=None,
        stderr_sha256=None,
        reason=reason,
        details=details or {},
    )


def _git(repository: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ("git", *arguments),
        cwd=repository,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if completed.returncode != 0:
        raise ValueError(
            f"git {' '.join(arguments)} failed with exit {completed.returncode}: "
            f"{completed.stderr.strip()}"
        )
    return completed.stdout.strip()


def repository_identity(repository: Path, expected_commit: str) -> dict[str, object]:
    """Require the literal clean candidate commit before running any checks."""

    if not _COMMIT.fullmatch(expected_commit):
        raise ValueError("--expected-commit must be a lowercase full 40-character SHA")
    repository = repository.resolve()
    top_level = Path(_git(repository, "rev-parse", "--show-toplevel")).resolve()
    if top_level != repository:
        raise ValueError(f"--root is not the Git top level: {repository} != {top_level}")
    actual_commit = _git(repository, "rev-parse", "HEAD")
    if actual_commit != expected_commit:
        raise ValueError(
            f"candidate commit mismatch: expected {expected_commit}, found {actual_commit}"
        )
    status = _git(repository, "status", "--porcelain=v1", "--untracked-files=normal")
    if status:
        raise ValueError(
            "candidate worktree is not clean; status bytes "
            f"{sha256_bytes(status.encode('utf-8'))} contain {len(status.splitlines())} entries"
        )
    return {
        "clean": True,
        "git_commit": actual_commit,
        "git_status_sha256": sha256_bytes(status.encode("utf-8")),
        "repository": "Grativy6/ARC3",
    }


def prepare_fresh_output_root(repository: Path, output_root: Path) -> None:
    """Create a new ignored/out-of-tree evidence root and refuse every reused path."""

    repository = repository.resolve()
    output_root = output_root.resolve()
    if output_root == repository:
        raise ValueError("--output-root cannot be the repository root")
    if output_root.exists():
        raise ValueError(f"--output-root must not already exist: {output_root}")
    if repository in output_root.parents:
        relative = output_root.relative_to(repository).as_posix()
        ignored = subprocess.run(
            ("git", "check-ignore", "--quiet", "--", relative),
            cwd=repository,
            check=False,
            capture_output=True,
            timeout=30,
        )
        if ignored.returncode != 0:
            raise ValueError("an in-repository --output-root must be covered by .gitignore")
    output_root.mkdir(parents=True, exist_ok=False)


def interpreter_source_identity(repository: Path, output_root: Path) -> dict[str, object]:
    """Prove the verifier and its isolated subprocess import ARC3 from this clone."""

    repository = repository.resolve()
    expected_prefix = (repository / ".venv").resolve()
    executable = Path(sys.executable).resolve()
    prefix = Path(sys.prefix).resolve()
    if prefix != expected_prefix:
        raise ValueError(
            f"release verifier must run from the clone-local .venv: {prefix} != {expected_prefix}"
        )
    expected_origin = (repository / "src" / "arc3" / "__init__.py").resolve()
    spec = importlib.util.find_spec("arc3")
    if spec is None or spec.origin is None:
        raise ValueError("arc3 is not importable from the release interpreter")
    in_process_origin = Path(spec.origin).resolve()
    if in_process_origin != expected_origin:
        raise ValueError(f"arc3 import origin is outside the candidate source: {in_process_origin}")
    environment, removed = _sanitized_environment(output_root, "interpreter-origin")
    probe = subprocess.run(
        (
            str(executable),
            "-I",
            "-c",
            (
                "import arc3,json,sys;"
                "print(json.dumps({'executable':sys.executable,'prefix':sys.prefix,"
                "'arc3_origin':arc3.__file__},sort_keys=True))"
            ),
        ),
        cwd=repository,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if probe.returncode != 0:
        _stderr, _ = _redact_generated_log(probe.stderr.encode("utf-8", errors="replace"))
        raise ValueError(
            "isolated interpreter origin probe failed: "
            + _stderr.decode("utf-8", errors="replace").strip()
        )
    try:
        payload = _required_mapping(json.loads(probe.stdout), name="interpreter origin probe")
    except json.JSONDecodeError as error:
        raise ValueError(f"interpreter origin probe did not return JSON: {error}") from error
    probed_executable = Path(str(payload.get("executable"))).resolve()
    probed_prefix = Path(str(payload.get("prefix"))).resolve()
    probed_origin = Path(str(payload.get("arc3_origin"))).resolve()
    if (probed_executable, probed_prefix, probed_origin) != (
        executable,
        expected_prefix,
        expected_origin,
    ):
        raise ValueError("isolated interpreter origin disagrees with the candidate runtime")
    return {
        "arc3_origin": expected_origin.relative_to(repository).as_posix(),
        "arc3_origin_sha256": sha256_file(expected_origin),
        "clone_local_virtual_environment": True,
        "isolated_probe": True,
        "non_allowlisted_environment_variables_removed": removed,
        "python_executable": _path_for_receipt(executable, repository),
        "python_executable_sha256": sha256_file(executable),
        "python_prefix": _path_for_receipt(expected_prefix, repository),
    }


def _probe_command(argv: Sequence[str], *, environment: Mapping[str, str] | None = None) -> bool:
    try:
        completed = subprocess.run(
            list(argv),
            check=False,
            capture_output=True,
            env=None if environment is None else dict(environment),
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0


def _python_command_candidates() -> tuple[tuple[str, ...], ...]:
    """Return installed interpreter commands that may own a uv entry point."""

    candidates: list[tuple[str, ...]] = [(sys.executable,)]
    python_launcher = shutil.which("py")
    if python_launcher:
        candidates.extend(
            (
                (python_launcher, "-3.13"),
                (python_launcher, "-3.12"),
                (python_launcher, "-3"),
            )
        )
    for name in ("python3", "python"):
        candidate = shutil.which(name)
        if candidate:
            candidates.append((candidate,))
    return tuple(dict.fromkeys(candidates))


def _installed_uv_entrypoints(python_command: Sequence[str]) -> tuple[tuple[str, ...], ...]:
    """Locate pip-created uv executables without importing uv in the release child."""

    discovery = (
        "import json,os,sysconfig;"
        "from pathlib import Path;"
        "name='uv.exe' if os.name=='nt' else 'uv';"
        "user_scheme=sysconfig.get_preferred_scheme('user');"
        "paths=(Path(sysconfig.get_path('scripts'))/name,"
        "Path(sysconfig.get_path('scripts',scheme=user_scheme))/name);"
        "print(json.dumps([str(path.resolve()) for path in paths if path.is_file()]))"
    )
    try:
        completed = subprocess.run(
            (*python_command, "-c", discovery),
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ()
    if completed.returncode != 0:
        return ()
    try:
        loaded: object = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return ()
    if not isinstance(loaded, list) or not all(isinstance(item, str) for item in loaded):
        return ()
    return tuple((item,) for item in cast(list[str], loaded))


def discover_uv_command(
    *, uv_executable: Path | None = None, uv_python: Path | None = None
) -> tuple[str, ...]:
    """Find an installed uv command that survives the release environment policy."""

    if uv_executable is not None and uv_python is not None:
        raise ValueError("--uv-executable and --uv-python are mutually exclusive")
    candidates: list[tuple[str, ...]] = []
    if uv_executable is not None:
        candidates.append((str(uv_executable.resolve()),))
    elif uv_python is not None:
        candidates.append((str(uv_python.resolve()), "-m", "uv"))
    else:
        executable = shutil.which("uv")
        if executable:
            candidates.append((executable,))
        python_commands = _python_command_candidates()
        for python_command in python_commands:
            candidates.extend(_installed_uv_entrypoints(python_command))
        candidates.extend((*python_command, "-m", "uv") for python_command in python_commands)

    unique_candidates = tuple(dict.fromkeys(candidates))
    with tempfile.TemporaryDirectory(prefix="arc3-uv-discovery-") as temporary:
        environment, _removed = _sanitized_environment(Path(temporary), "uv-probe")
        command = next(
            (
                candidate
                for candidate in unique_candidates
                if _probe_command((*candidate, "--version"), environment=environment)
            ),
            (),
        )
    if not command:
        if uv_executable is not None or uv_python is not None:
            configured = unique_candidates[0] if unique_candidates else ()
            raise ValueError(
                "configured uv command is not executable under the sanitized release "
                f"environment: {_display_command(configured)}"
            )
        raise ValueError(
            "the pinned uv bootstrap executable is unavailable under the sanitized release "
            "environment; pass --uv-executable"
        )
    return command


def _expectation_configuration(expectation: Mapping[str, Any]) -> dict[str, Any]:
    raw = expectation.get("configuration")
    if not isinstance(raw, dict):
        raise ValueError("benchmark expectation configuration is missing")
    configuration = cast(dict[str, Any], raw)
    agents = configuration.get("agents")
    seeds = configuration.get("seeds")
    if not isinstance(agents, list) or not all(isinstance(item, str) for item in agents):
        raise ValueError("benchmark configuration field 'agents' has the wrong type")
    if not isinstance(seeds, list) or not all(isinstance(item, int) for item in seeds):
        raise ValueError("benchmark configuration field 'seeds' has the wrong type")
    for key in ("max_actions", "max_resets"):
        value = configuration.get(key)
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"benchmark configuration field {key!r} has the wrong type")
    if not isinstance(configuration.get("partition"), str):
        raise ValueError("benchmark configuration field 'partition' has the wrong type")
    timeout = configuration.get("timeout_seconds")
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
        raise ValueError("benchmark configuration field 'timeout_seconds' has the wrong type")
    return configuration


def build_plan(
    *,
    repository: Path,
    output_root: Path,
    expectation: Mapping[str, Any],
    uv_command: tuple[str, ...],
    official_environments: Path,
) -> tuple[CommandSpec, ...]:
    """Declare every Stage 18 command before execution."""

    repository = repository.resolve()
    output_root = output_root.resolve()
    official_environments = official_environments.resolve()
    python = sys.executable
    configuration = _expectation_configuration(expectation)
    agents = ",".join(cast(list[str], configuration["agents"]))
    seeds = ",".join(str(value) for value in cast(list[int], configuration["seeds"]))
    evaluation_root = output_root / "evaluations"
    evaluation_id = "stage18-benchmark-reproduction"
    package_a = output_root / "package-a"
    package_b = output_root / "package-b"
    official_root = output_root / "official-evaluations"
    official_id = "stage18-official-smoke"
    manifest_sha256 = expectation.get("public_partition_manifest_sha256")
    if not isinstance(manifest_sha256, str):
        raise ValueError("benchmark expectation has no public partition manifest identity")
    return (
        CommandSpec(
            "dependency-lock",
            "dependency-lock",
            (*uv_command, "lock", "--check", "--offline"),
            120.0,
            failure_status="FAILED_INFRASTRUCTURE",
        ),
        CommandSpec(
            "ruff-lint",
            "quality",
            (python, "-m", "ruff", "check", "--no-cache", "."),
            300.0,
        ),
        CommandSpec(
            "ruff-format",
            "quality",
            (python, "-m", "ruff", "format", "--check", "--no-cache", "."),
            300.0,
        ),
        CommandSpec(
            "mypy-strict",
            "quality",
            (
                python,
                "-m",
                "mypy",
                "--strict",
                "--cache-dir",
                str(output_root / "cache" / "mypy" / "full"),
                "src",
                "agent",
                "scripts",
            ),
            900.0,
        ),
        CommandSpec(
            "full-test-suite",
            "tests",
            (
                python,
                "-m",
                "pytest",
                "-q",
                "--basetemp",
                str(output_root / "tmp" / "pytest-full"),
            ),
            2400.0,
            nondeterminism=("test durations and coverage percentages may vary by host",),
        ),
        CommandSpec(
            "trace-replay-tamper",
            "trace-replay",
            (
                python,
                "-m",
                "pytest",
                "-q",
                "--no-cov",
                "--basetemp",
                str(output_root / "tmp" / "pytest-replay"),
                "tests/replay",
                "tests/property/test_trace_properties.py",
            ),
            900.0,
        ),
        CommandSpec(
            "synthetic-benchmark",
            "synthetic",
            (
                python,
                "-m",
                "arc3",
                "evaluate",
                "--partition",
                str(configuration["partition"]),
                "--agents",
                agents,
                "--seeds",
                seeds,
                "--max-actions",
                str(configuration["max_actions"]),
                "--max-resets",
                str(configuration["max_resets"]),
                "--timeout-seconds",
                str(configuration["timeout_seconds"]),
                "--output-root",
                str(evaluation_root),
                "--evaluation-id",
                evaluation_id,
            ),
            900.0,
            nondeterminism=(
                "timestamps, runtime metrics, source identity, and sealed artifact hashes change",
                "the separately compared completion/action/score projection must remain exact",
            ),
        ),
        CommandSpec(
            "synthetic-artifact-verification",
            "synthetic",
            (
                python,
                "-m",
                "arc3",
                "verify-artifacts",
                "--evaluation",
                evaluation_id,
                "--output-root",
                str(evaluation_root),
            ),
            300.0,
            dependencies=("synthetic-benchmark",),
        ),
        CommandSpec(
            "offline-package-a",
            "offline-package",
            (
                python,
                "-m",
                "scripts.prepare_kaggle_submission",
                "--output",
                str(package_a),
                "--sandbox-timeout",
                "120",
            ),
            900.0,
        ),
        CommandSpec(
            "offline-package-b",
            "offline-package",
            (
                python,
                "-m",
                "scripts.prepare_kaggle_submission",
                "--output",
                str(package_b),
                "--sandbox-timeout",
                "120",
            ),
            900.0,
        ),
        CommandSpec(
            "competition-integrity",
            "integrity",
            (
                python,
                "-m",
                "scripts.check_competition_integrity",
                "--root",
                str(repository),
                "--expected-manifest-sha256",
                manifest_sha256,
                "--archive",
                str(package_a / "arc3-kaggle-candidate.zip"),
                "--output",
                str(output_root / "integrity-receipt.json"),
            ),
            900.0,
            dependencies=("offline-package-a",),
            nondeterminism=(
                "installed distribution metadata may differ by platform while lock identity stays fixed",
            ),
        ),
        CommandSpec(
            "official-inventory",
            "official-smoke",
            (
                python,
                "-m",
                "scripts.evaluate_public",
                "--partition",
                "smoke",
                "--manifest",
                str(repository / "docs/evaluation/public-game-partitions.v0.1.json"),
                "--environments-dir",
                str(official_environments),
                "--recordings-dir",
                str(output_root / "official-recordings"),
                "--inventory-only",
            ),
            180.0,
            failure_status="FAILED_INFRASTRUCTURE",
        ),
        CommandSpec(
            "official-smoke",
            "official-smoke",
            (
                python,
                "-m",
                "scripts.evaluate_public",
                "--partition",
                "smoke",
                "--agents",
                "random,cycle,full",
                "--seeds",
                "7,11",
                "--max-actions",
                "80",
                "--max-resets",
                "8",
                "--timeout-seconds",
                "120",
                "--frozen-commit",
                "{CANDIDATE_COMMIT}",
                "--manifest",
                str(repository / "docs/evaluation/public-game-partitions.v0.1.json"),
                "--environments-dir",
                str(official_environments),
                "--recordings-dir",
                str(output_root / "official-recordings"),
                "--output-root",
                str(official_root),
                "--exposure-ledger",
                str(output_root / "official-exposure.jsonl"),
                "--evaluation-id",
                official_id,
                "--milestone-id",
                "build-000-stage18-release-candidate",
            ),
            3000.0,
            required=False,
            dependencies=("official-inventory",),
        ),
        CommandSpec(
            "official-artifact-verification",
            "official-smoke",
            (
                python,
                "-m",
                "scripts.evaluate_public",
                "--verify",
                str(official_root / official_id),
            ),
            300.0,
            required=False,
            dependencies=("official-smoke",),
        ),
    )


def _replace_candidate_commit(spec: CommandSpec, commit: str) -> CommandSpec:
    return CommandSpec(
        check_id=spec.check_id,
        category=spec.category,
        argv=tuple(commit if item == "{CANDIDATE_COMMIT}" else item for item in spec.argv),
        timeout_seconds=spec.timeout_seconds,
        required=spec.required,
        dependencies=spec.dependencies,
        failure_status=spec.failure_status,
        nondeterminism=spec.nondeterminism,
    )


def _required_mapping(value: object, *, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    return cast(dict[str, Any], value)


def evaluation_projection(directory: Path) -> dict[str, object]:
    """Extract only deterministic score/action semantics from an evaluation."""

    manifest = _json_object(directory / "manifest.json")
    summary = _json_object(directory / "summary.json")
    agent_config = _required_mapping(manifest.get("agent_config"), name="agent_config")
    runs: list[dict[str, object]] = []
    try:
        lines = (directory / "results.jsonl").read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as error:
        raise ValueError(f"cannot read evaluation results: {error}") from error
    for line_number, line in enumerate(lines, start=1):
        if not line:
            continue
        try:
            raw: object = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"results line {line_number} is invalid JSON: {error}") from error
        result = _required_mapping(raw, name=f"results line {line_number}")
        score = _required_mapping(result.get("score"), name=f"results line {line_number} score")
        metrics = _required_mapping(
            result.get("metrics"), name=f"results line {line_number} metrics"
        )
        runs.append(
            {
                "actions": metrics.get("environment_actions"),
                "agent": result.get("agent"),
                "baseline_id": result.get("baseline_id"),
                "completed": score.get("completed"),
                "levels_completed": score.get("levels_completed"),
                "score": score.get("score"),
                "seed": result.get("seed"),
                "status": result.get("status"),
            }
        )
    runs.sort(key=lambda item: (str(item["baseline_id"]), int(cast(int, item["seed"]))))
    return {
        "configuration": {
            "agents": agent_config.get("agents"),
            "max_actions": agent_config.get("max_actions"),
            "max_resets": agent_config.get("max_resets"),
            "network_mode": agent_config.get("network_mode"),
            "partition": agent_config.get("partition"),
            "seeds": agent_config.get("seeds"),
            "surface": agent_config.get("surface"),
            "timeout_seconds": agent_config.get("timeout_seconds"),
        },
        "runs": runs,
        "summary": {
            "failure_count": summary.get("failure_count"),
            "result_count": summary.get("result_count"),
            "status": summary.get("status"),
            "successful_policy_count": summary.get("successful_policy_count"),
            "surface": summary.get("surface"),
        },
    }


def _stage_evidence_projection(evidence: Mapping[str, Any]) -> dict[str, object]:
    controlled = _required_mapping(
        evidence.get("controlled_comparison"), name="benchmark evidence controlled comparison"
    )
    runtime = _required_mapping(evidence.get("runtime"), name="benchmark evidence runtime")
    raw_policies = controlled.get("policies")
    if not isinstance(raw_policies, list):
        raise ValueError("benchmark evidence policies must be a list")
    runs: list[dict[str, object]] = []
    agents: list[str] = []
    for raw_policy in raw_policies:
        policy = _required_mapping(raw_policy, name="benchmark evidence policy")
        agent = policy.get("agent")
        baseline_id = policy.get("baseline_id")
        per_seed = policy.get("per_seed")
        if not isinstance(agent, str) or not isinstance(baseline_id, str):
            raise ValueError("benchmark evidence policy identity is invalid")
        if not isinstance(per_seed, list):
            raise ValueError("benchmark evidence per-seed records must be a list")
        agents.append(agent)
        for raw_seed in per_seed:
            seed = _required_mapping(raw_seed, name="benchmark evidence seed result")
            completed = seed.get("completed")
            if not isinstance(completed, int) or isinstance(completed, bool):
                raise ValueError("benchmark evidence completion count is invalid")
            runs.append(
                {
                    "actions": seed.get("actions"),
                    "agent": agent,
                    "baseline_id": baseline_id,
                    "completed": completed == 1,
                    "levels_completed": completed,
                    "score": seed.get("score"),
                    "seed": seed.get("seed"),
                    "status": "success",
                }
            )
    runs.sort(key=lambda item: (str(item["baseline_id"]), int(cast(int, item["seed"]))))
    return {
        "configuration": {
            "agents": agents,
            "max_actions": controlled.get("action_budget_per_run"),
            "max_resets": controlled.get("reset_budget_per_run"),
            "network_mode": runtime.get("network_mode"),
            "partition": controlled.get("partition"),
            "seeds": controlled.get("seeds"),
            "surface": controlled.get("surface"),
            "timeout_seconds": controlled.get("wall_clock_budget_seconds"),
        },
        "runs": runs,
        "summary": {
            "failure_count": controlled.get("failure_count"),
            "result_count": controlled.get("result_count"),
            "status": evidence.get("status"),
            "successful_policy_count": controlled.get("successful_policy_count"),
            "surface": controlled.get("surface"),
        },
    }


def benchmark_basis_identity(
    expectation: Mapping[str, Any], repository: Path, candidate_commit: str
) -> dict[str, object]:
    """Bind the frozen expectation to committed measured evidence and ancestry."""

    repository = repository.resolve()
    basis = _required_mapping(expectation.get("basis"), name="benchmark expectation basis")
    evidence_relative = basis.get("evidence")
    evidence_sha256 = basis.get("evidence_sha256")
    evidence_commit = basis.get("evidence_commit")
    measured_commit = basis.get("measured_commit")
    measured_configuration_hash = basis.get("measured_configuration_hash")
    measured_manifest_sha256 = basis.get("measured_manifest_sha256")
    measured_projection_sha256 = basis.get("measured_projection_sha256")
    required_strings = {
        "evidence": evidence_relative,
        "evidence_sha256": evidence_sha256,
        "evidence_commit": evidence_commit,
        "measured_commit": measured_commit,
        "measured_configuration_hash": measured_configuration_hash,
        "measured_manifest_sha256": measured_manifest_sha256,
        "measured_projection_sha256": measured_projection_sha256,
    }
    if not all(isinstance(value, str) and value for value in required_strings.values()):
        raise ValueError("benchmark expectation basis is incomplete")
    assert isinstance(evidence_relative, str)
    assert isinstance(evidence_sha256, str)
    assert isinstance(evidence_commit, str)
    assert isinstance(measured_commit, str)
    assert isinstance(measured_configuration_hash, str)
    assert isinstance(measured_manifest_sha256, str)
    assert isinstance(measured_projection_sha256, str)
    if not _COMMIT.fullmatch(evidence_commit) or not _COMMIT.fullmatch(measured_commit):
        raise ValueError("benchmark evidence commits must be full lowercase SHAs")
    evidence_path = (repository / evidence_relative).resolve()
    try:
        evidence_path.relative_to(repository)
    except ValueError as error:
        raise ValueError("benchmark evidence path escapes the repository") from error
    if sha256_file(evidence_path) != evidence_sha256:
        raise ValueError("benchmark evidence file hash does not match the expectation")
    evidence = _json_object(evidence_path)
    if evidence.get("measured_repository_commit") != measured_commit:
        raise ValueError("benchmark evidence measured commit disagrees with the expectation")
    if evidence.get("status") != "PASS" or evidence.get("label") != "synthetic":
        raise ValueError("benchmark evidence is not a passing synthetic receipt")
    identity = _required_mapping(evidence.get("identity"), name="benchmark evidence identity")
    if identity.get("git_commit") != measured_commit:
        raise ValueError("benchmark evidence identity commit is inconsistent")
    if identity.get("configuration_hash") != measured_configuration_hash:
        raise ValueError("benchmark evidence configuration hash is inconsistent")
    controlled = _required_mapping(
        evidence.get("controlled_comparison"), name="benchmark controlled comparison"
    )
    sealed = _required_mapping(
        controlled.get("sealed_artifacts"), name="benchmark sealed artifacts"
    )
    if (
        sealed.get("manifest_sha256") != measured_manifest_sha256
        or sealed.get("verified") is not True
    ):
        raise ValueError("benchmark measured manifest is not the frozen verified artifact")
    expected_projection = expectation.get("expected_projection")
    if not isinstance(expected_projection, dict):
        raise ValueError("benchmark expectation has no expected projection")
    evidence_projection = _stage_evidence_projection(evidence)
    projection_sha256 = sha256_bytes(canonical_json_bytes(evidence_projection))
    if projection_sha256 != measured_projection_sha256:
        raise ValueError("benchmark evidence projection hash changed")
    if canonical_json_bytes(evidence_projection) != canonical_json_bytes(expected_projection):
        raise ValueError("benchmark evidence semantics disagree with the frozen projection")
    for older, newer, label in (
        (measured_commit, evidence_commit, "measured commit to evidence commit"),
        (evidence_commit, candidate_commit, "evidence commit to candidate commit"),
        (measured_commit, candidate_commit, "measured commit to candidate commit"),
    ):
        if not _COMMIT.fullmatch(newer):
            raise ValueError(f"{label} uses an invalid commit")
        ancestor = subprocess.run(
            ("git", "merge-base", "--is-ancestor", older, newer),
            cwd=repository,
            check=False,
            capture_output=True,
            timeout=30,
        )
        if ancestor.returncode != 0:
            raise ValueError(f"benchmark ancestry check failed: {label}")
    committed = subprocess.run(
        ("git", "show", f"{evidence_commit}:{evidence_relative}"),
        cwd=repository,
        check=False,
        capture_output=True,
        timeout=30,
    )
    if committed.returncode != 0 or sha256_bytes(committed.stdout) != evidence_sha256:
        raise ValueError("benchmark evidence commit does not contain the frozen evidence bytes")
    return {
        "configuration_hash": measured_configuration_hash,
        "evidence_commit": evidence_commit,
        "evidence_path": evidence_relative,
        "evidence_sha256": evidence_sha256,
        "measured_commit": measured_commit,
        "measured_commit_is_ancestor": True,
        "measured_manifest_sha256": measured_manifest_sha256,
        "measured_projection_sha256": measured_projection_sha256,
    }


def compare_benchmark(
    expectation: Mapping[str, Any], evaluation_directory: Path
) -> tuple[bool, dict[str, object]]:
    """Compare exact deterministic semantics and explain excluded byte drift."""

    expected = expectation.get("expected_projection")
    if not isinstance(expected, dict):
        raise ValueError("benchmark expectation has no expected_projection object")
    actual = evaluation_projection(evaluation_directory)
    expected_bytes = canonical_json_bytes(expected)
    actual_bytes = canonical_json_bytes(actual)
    permitted = expectation.get("permitted_nondeterminism")
    if not isinstance(permitted, list) or not all(isinstance(item, str) for item in permitted):
        raise ValueError("benchmark expectation has invalid permitted_nondeterminism")
    return expected_bytes == actual_bytes, {
        "actual_projection": actual,
        "actual_projection_sha256": sha256_bytes(actual_bytes),
        "expected_projection_sha256": sha256_bytes(expected_bytes),
        "permitted_nondeterminism": cast(list[str], permitted),
        "semantic_projection_equal": expected_bytes == actual_bytes,
    }


_PACKAGE_FIELDS = (
    "candidate_sha256",
    "manifest_sha256",
    "notebook_sha256",
    "payload_sha256",
    "runtime_requirements_sha256",
    "sbom_sha256",
    "wheel_manifest_sha256",
)

_PACKAGE_FILE_FIELDS = {
    "candidate_sha256": "arc3-kaggle-candidate.zip",
    "manifest_sha256": "package-manifest.json",
    "notebook_sha256": "arc3-submission.ipynb",
    "payload_sha256": "arc3-first-party.zip",
    "runtime_requirements_sha256": "runtime-requirements-linux-cp312.txt",
    "sbom_sha256": "sbom.spdx.json",
    "wheel_manifest_sha256": "runtime-wheels-linux-cp312.json",
}
_CANDIDATE_MEMBERS = frozenset(
    {
        "arc3-first-party.zip",
        "arc3-submission.ipynb",
        "kernel-metadata.json",
        "package-manifest.json",
        "runtime-requirements-linux-cp312.txt",
        "runtime-wheels-linux-cp312.json",
        "sbom.spdx.json",
        "submission-schema.v0.1.json",
    }
)


def _candidate_member_hashes(path: Path) -> dict[str, str]:
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            if (
                len(names) != len(set(names))
                or set(names) != _CANDIDATE_MEMBERS
                or any(
                    info.is_dir()
                    or info.filename.startswith("/")
                    or ".." in Path(info.filename).parts
                    for info in infos
                )
            ):
                raise ValueError("candidate archive member set is not the fixed release contract")
            return {name: sha256_bytes(archive.read(name)) for name in sorted(names)}
    except (OSError, KeyError, zipfile.BadZipFile) as error:
        raise ValueError(f"candidate archive cannot be independently decoded: {error}") from error


def _manifest_artifact_hashes(manifest: Mapping[str, Any]) -> dict[str, tuple[str, int]]:
    records = manifest.get("artifacts")
    if not isinstance(records, list):
        raise ValueError("package manifest has no artifact records")
    result: dict[str, tuple[str, int]] = {}
    for raw in records:
        record = _required_mapping(raw, name="package manifest artifact")
        path = record.get("path")
        digest = record.get("sha256")
        size = record.get("size_bytes")
        if (
            not isinstance(path, str)
            or path in result
            or path not in _CANDIDATE_MEMBERS - {"package-manifest.json"}
            or not isinstance(digest, str)
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest)
            or isinstance(size, bool)
            or not isinstance(size, int)
            or size < 0
        ):
            raise ValueError("package manifest artifact record is invalid")
        result[path] = (digest, size)
    if set(result) != _CANDIDATE_MEMBERS - {"package-manifest.json"}:
        raise ValueError("package manifest artifact set is incomplete")
    return result


def _validate_package_formats(package_root: Path) -> dict[str, object]:
    for name in (
        "arc3-submission.ipynb",
        "kernel-metadata.json",
        "runtime-wheels-linux-cp312.json",
        "sbom.spdx.json",
        "submission-schema.v0.1.json",
    ):
        _json_object(package_root / name)
    requirements = (package_root / "runtime-requirements-linux-cp312.txt").read_text(
        encoding="utf-8"
    )
    lines = [line for line in requirements.splitlines() if line and not line.startswith("#")]
    if not lines or any("--hash=sha256:" not in line for line in lines):
        raise ValueError("runtime requirements are not an exact hash-locked declaration")
    payload_path = package_root / "arc3-first-party.zip"
    try:
        with zipfile.ZipFile(payload_path) as payload:
            names = [info.filename for info in payload.infolist()]
            if (
                len(names) != len(set(names))
                or not {"agent/my_agent.py", "src/arc3/__init__.py"} <= set(names)
                or any(
                    info.is_dir()
                    or info.filename.startswith("/")
                    or ".." in Path(info.filename).parts
                    for info in payload.infolist()
                )
            ):
                raise ValueError("first-party payload member set is unsafe or incomplete")
    except (OSError, zipfile.BadZipFile) as error:
        raise ValueError(f"first-party payload cannot be independently decoded: {error}") from error
    return {
        "candidate_member_count": len(_CANDIDATE_MEMBERS),
        "payload_member_count": len(names),
        "runtime_requirement_count": len(lines),
    }


def package_projection(
    receipt_path: Path, *, expected_commit: str | None = None
) -> dict[str, object]:
    """Validate and project one package receipt to deterministic artifact identities."""

    receipt = _verified_package_receipt(receipt_path)
    if receipt.get("schema") != "arc3.kaggle-build-receipt.v0.1":
        raise ValueError(f"unsupported package receipt schema: {receipt_path}")
    if receipt.get("status") != "PACKAGING_PASS":
        raise ValueError(f"package receipt does not claim PACKAGING_PASS: {receipt_path}")
    if receipt.get("official_submission_performed") is not False:
        raise ValueError(f"package receipt has an invalid submission boundary: {receipt_path}")
    package_root = receipt_path.resolve().parent
    actual_hashes: dict[str, str] = {}
    for field, relative in _PACKAGE_FILE_FIELDS.items():
        claimed = receipt.get(field)
        artifact = package_root / relative
        if not isinstance(claimed, str):
            raise ValueError(f"package receipt is missing {field}: {receipt_path}")
        actual = sha256_file(artifact)
        if claimed != actual:
            raise ValueError(f"package artifact {relative} disagrees with {field}")
        actual_hashes[field] = actual
    sandbox = _required_mapping(receipt.get("sandbox"), name="package sandbox")
    validation = _required_mapping(receipt.get("validation"), name="package validation")
    candidate_validation = _required_mapping(
        receipt.get("candidate_validation"), name="package candidate validation"
    )
    if candidate_validation.get("status") != "PASS":
        raise ValueError("package candidate validation did not pass")
    if candidate_validation.get("candidate_sha256") != actual_hashes["candidate_sha256"]:
        raise ValueError("package candidate validation is not linked to the candidate bytes")
    if sandbox.get("status") != "PASS" or validation.get("status") != "PASS":
        raise ValueError("package sandbox or schema validation did not pass")
    sandbox_sha256 = sha256_bytes(package_canonical_json_bytes(sandbox))
    if receipt.get("sandbox_receipt_sha256") != sandbox_sha256:
        raise ValueError("package sandbox receipt hash is not linked to the receipt")
    sandbox_output = package_root / "offline-sandbox" / "submission.parquet"
    actual_output_sha256 = sha256_file(sandbox_output)
    if not (
        receipt.get("sandbox_output_sha256")
        == sandbox.get("output_sha256")
        == validation.get("artifact_sha256")
        == actual_output_sha256
    ):
        raise ValueError("package sandbox output identities do not agree")
    if sandbox.get("notebook_sha256") != actual_hashes["notebook_sha256"]:
        raise ValueError("package sandbox is not linked to the notebook")
    if sandbox.get("payload_sha256") != actual_hashes["payload_sha256"]:
        raise ValueError("package sandbox is not linked to the first-party payload")
    if sandbox.get("requirements_sha256") != actual_hashes["runtime_requirements_sha256"]:
        raise ValueError("package sandbox is not linked to the runtime requirements")
    if sandbox.get("secret_scan_status") != "PASS":
        raise ValueError("package sandbox secret rescan did not pass")
    if sandbox.get("network_attempts") != 0 or sandbox.get("credentials_present") != []:
        raise ValueError("package sandbox crossed the offline or credential boundary")
    manifest = _json_object(package_root / "package-manifest.json")
    source = _required_mapping(manifest.get("source"), name="package manifest source")
    if manifest.get("build_status") != "PACKAGING_PASS" or source.get("git_dirty") is not False:
        raise ValueError("package manifest does not bind PACKAGING_PASS to a clean source")
    if expected_commit is not None and source.get("git_commit") != expected_commit:
        raise ValueError("package manifest source commit differs from the release candidate")
    runtime_lock = _required_mapping(
        manifest.get("runtime_lock"), name="package manifest runtime lock"
    )
    if (
        runtime_lock.get("requirements_sha256") != actual_hashes["runtime_requirements_sha256"]
        or runtime_lock.get("wheel_manifest_sha256") != actual_hashes["wheel_manifest_sha256"]
    ):
        raise ValueError("package manifest is not linked to the runtime lock files")
    secret_scan = _required_mapping(manifest.get("secret_scan"), name="package secret scan")
    if secret_scan.get("status") != "PASS" or secret_scan.get("findings") != []:
        raise ValueError("package manifest secret scan did not pass cleanly")
    manifest_records = _manifest_artifact_hashes(manifest)
    candidate_members = _candidate_member_hashes(package_root / "arc3-kaggle-candidate.zip")
    format_validation = _validate_package_formats(package_root)
    for relative in sorted(_CANDIDATE_MEMBERS):
        top_level = package_root / relative
        actual = sha256_file(top_level)
        if candidate_members[relative] != actual:
            raise ValueError(f"candidate member differs from top-level package file: {relative}")
        if relative != "package-manifest.json":
            recorded_digest, recorded_size = manifest_records[relative]
            if recorded_digest != actual or recorded_size != top_level.stat().st_size:
                raise ValueError(f"package manifest artifact identity changed: {relative}")
    if not (
        sandbox.get("dependency_install_status") == "PASS"
        and sandbox.get("production_rerun_exercised") is True
        and sandbox.get("framework_fixture") is True
        and sandbox.get("imported_arc3_path") == "arc3_submission/src/arc3/__init__.py"
        and sandbox.get("gateway_connections") in range(2, 2**31)
    ):
        raise ValueError("package sandbox receipt is not linked to the production rerun path")
    projection: dict[str, object] = {field: actual_hashes[field] for field in _PACKAGE_FIELDS}
    projection.update(
        {
            "sandbox_output_sha256": actual_output_sha256,
            "sandbox_receipt_sha256": sandbox_sha256,
            "status": "PACKAGING_PASS",
            "validation_artifact_sha256": actual_output_sha256,
            "validated_formats": format_validation,
        }
    )
    return projection


def compare_packages(
    first: Path, second: Path, *, expected_commit: str | None = None
) -> tuple[bool, dict[str, object]]:
    """Require two fresh offline builds to produce byte-identical identities."""

    first_projection = package_projection(first, expected_commit=expected_commit)
    second_projection = package_projection(second, expected_commit=expected_commit)
    first_bytes = canonical_json_bytes(first_projection)
    second_bytes = canonical_json_bytes(second_projection)
    return first_bytes == second_bytes, {
        "first": first_projection,
        "first_projection_sha256": sha256_bytes(first_bytes),
        "second": second_projection,
        "second_projection_sha256": sha256_bytes(second_bytes),
        "projections_equal": first_bytes == second_bytes,
    }


def _last_json_log(path: Path) -> dict[str, Any]:
    try:
        lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line]
    except (OSError, UnicodeDecodeError) as error:
        raise ValueError(f"cannot read command JSON log {path}: {error}") from error
    if not lines:
        raise ValueError(f"command JSON log is empty: {path}")
    try:
        loaded: object = json.loads(lines[-1])
    except json.JSONDecodeError as error:
        raise ValueError(f"last command output line is not JSON: {error}") from error
    return _required_mapping(loaded, name="command JSON output")


def official_smoke_available(
    inventory: Mapping[str, Any], manifest_path: Path
) -> tuple[bool, dict[str, object]]:
    """Decide availability from identities only, without parsing game source."""

    manifest = _json_object(manifest_path)
    games = manifest.get("games")
    assignment = manifest.get("assignment")
    local_assets = inventory.get("local_assets")
    if (
        manifest.get("schema") != "arc3.public-game-partitions.v0.1"
        or not isinstance(assignment, dict)
        or not isinstance(assignment.get("salt"), str)
        or not assignment["salt"]
        or not isinstance(games, list)
        or not isinstance(local_assets, dict)
    ):
        raise ValueError("public manifest or inventory has the wrong shape")
    salt = cast(str, assignment["salt"])
    if inventory.get("schema") != "arc3.public-inventory.v0.1":
        raise ValueError("official inventory schema is unsupported")
    manifest_sha256 = sha256_file(manifest_path)
    if inventory.get("manifest_sha256") != manifest_sha256:
        raise ValueError("official inventory is not bound to the frozen partition manifest")
    if inventory.get("gameplay_opened") is not False:
        raise ValueError("official inventory crossed the metadata-only gameplay boundary")
    if inventory.get("online_metadata_revalidation") is not None:
        raise ValueError("release inventory unexpectedly performed online metadata revalidation")
    all_ids: set[str] = set()
    partition_ids: dict[str, set[str]] = {
        "development": set(),
        "public-holdout": set(),
        "smoke": set(),
    }
    for raw in games:
        entry = _required_mapping(raw, name="public game entry")
        game_id = entry.get("game_id")
        partition = entry.get("partition")
        stable_name = entry.get("stable_name")
        assignment_hash = entry.get("assignment_hash")
        if (
            not isinstance(game_id, str)
            or not re.fullmatch(r"[a-z0-9]+-[0-9a-f]{8}", game_id)
            or not isinstance(stable_name, str)
            or not game_id.startswith(f"{stable_name}-")
            or partition not in partition_ids
            or not isinstance(assignment_hash, str)
            or not re.fullmatch(r"[0-9a-f]{64}", assignment_hash)
            or assignment_hash != hashlib.sha256(f"{salt}\0{stable_name}".encode()).hexdigest()
        ):
            raise ValueError("public partition manifest has an invalid game identity")
        if game_id in all_ids:
            raise ValueError(f"public partition manifest repeats game ID {game_id}")
        all_ids.add(game_id)
        partition_ids[cast(str, partition)].add(game_id)
    counts = inventory.get("partition_counts")
    if not isinstance(counts, dict) or counts != {
        partition: len(partition_ids[partition]) for partition in partition_ids
    }:
        raise ValueError("official inventory partition counts disagree with the manifest")
    local_ids = {str(value) for value in local_assets}
    if not local_ids <= all_ids:
        raise ValueError("official inventory contains game IDs outside the frozen manifest")
    asset_hashes: dict[str, str] = {}
    for game_id, raw_asset in local_assets.items():
        asset = _required_mapping(raw_asset, name=f"official asset {game_id}")
        files = asset.get("files")
        if (
            asset.get("game_id") != game_id
            or asset.get("source_semantically_inspected") is not False
            or not isinstance(files, list)
            or not files
        ):
            raise ValueError(f"official asset identity is invalid for {game_id}")
        normalized_files: list[tuple[str, int, str]] = []
        names: set[str] = set()
        for raw_file in files:
            file = _required_mapping(raw_file, name=f"official asset file {game_id}")
            name = file.get("name")
            length = file.get("bytes")
            digest = file.get("sha256")
            if (
                not isinstance(name, str)
                or not name
                or name.startswith("/")
                or ".." in Path(name).parts
                or name in names
                or isinstance(length, bool)
                or not isinstance(length, int)
                or length < 0
                or not isinstance(digest, str)
                or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest)
            ):
                raise ValueError(f"official asset file identity is invalid for {game_id}")
            names.add(name)
            normalized_files.append((name, length, digest))
        normalized_files.sort()
        aggregate = sha256_bytes(evaluation_canonical_json_bytes(normalized_files))
        if asset.get("aggregate_sha256") != aggregate:
            raise ValueError(f"official asset aggregate identity changed for {game_id}")
        asset_hashes[str(game_id)] = aggregate
    smoke_ids = partition_ids["smoke"]
    available = smoke_ids & local_ids
    missing = smoke_ids - local_ids
    return not missing and bool(smoke_ids), {
        "available_count": len(available),
        "available_game_ids": sorted(available),
        "availability_basis": "metadata and content identities only; game source not inspected",
        "game_asset_sha256": {game_id: asset_hashes[game_id] for game_id in sorted(available)},
        "gameplay_opened_by_inventory": inventory.get("gameplay_opened"),
        "manifest_sha256": manifest_sha256,
        "missing_count": len(missing),
        "missing_game_ids": sorted(missing),
        "required_count": len(smoke_ids),
        "required_game_ids": sorted(smoke_ids),
    }


def scan_generated_logs(
    output_root: Path, results: Sequence[CheckResult]
) -> tuple[bool, dict[str, object]]:
    """Verify only redacted streams were persisted and report any emission boundary crossing."""

    log_root = output_root / "logs"
    residual_findings: list[dict[str, object]] = []
    log_hashes: dict[str, str] = {}
    for path in sorted(log_root.glob("*.log")):
        if path.is_symlink() or not path.is_file():
            residual_findings.append({"file": path.name, "reason": "non-regular log"})
            continue
        content = path.read_bytes()
        labels = [
            f"pattern-{index}"
            for index, pattern in enumerate(_SECRET_PATTERNS, start=1)
            if pattern.search(content)
        ]
        if labels:
            residual_findings.append({"file": path.name, "patterns": labels})
        log_hashes[path.name] = sha256_bytes(content)
    redaction_count = 0
    for result in results:
        count = result.details.get("generated_log_redactions", 0)
        if isinstance(count, int) and not isinstance(count, bool):
            redaction_count += count
    passed = not residual_findings and redaction_count == 0
    return passed, {
        "log_count": len(log_hashes),
        "log_hashes": log_hashes,
        "persisted_streams": "redacted stdout/stderr only; pre-redaction bytes are never written",
        "redaction_count": redaction_count,
        "residual_finding_count": len(residual_findings),
        "residual_findings": residual_findings,
    }


def _complete_artifact_set(output_root: Path, *, sealed: bool) -> dict[str, object]:
    """Hash the complete non-transient output set, excluding self-referential wrappers."""

    files: dict[str, str] = {}
    total_bytes = 0
    for path in sorted(output_root.rglob("*")):
        relative = path.relative_to(output_root).as_posix()
        if relative in _RECEIPT_WRAPPERS or relative.startswith(_TRANSIENT_OUTPUT_PREFIXES):
            continue
        if path.is_symlink():
            raise ValueError(f"release artifact set contains a symlink: {relative}")
        if path.is_file():
            files[relative] = sha256_file(path)
            total_bytes += path.stat().st_size
    if sealed and not files:
        raise ValueError("a passing release verification cannot seal an empty artifact set")
    return {
        "complete": sealed,
        "excluded_prefixes": list(_TRANSIENT_OUTPUT_PREFIXES),
        "excluded_wrappers": sorted(_RECEIPT_WRAPPERS),
        "file_count": len(files),
        "files": files,
        "set_sha256": sha256_bytes(canonical_json_bytes(files)),
        "total_bytes": total_bytes,
    }


def verify_sealed_artifact_set(document: Mapping[str, Any], output_root: Path) -> None:
    """Rehash every declared release artifact and reject missing, extra, or changed files."""

    sealed = _required_mapping(
        document.get("sealed_artifact_set"), name="release sealed artifact set"
    )
    if document.get("status") == "PASS" and sealed.get("complete") is not True:
        raise ValueError("passing release receipt does not seal a complete artifact set")
    expected_files = sealed.get("files")
    if not isinstance(expected_files, dict) or not all(
        isinstance(name, str) and isinstance(digest, str) for name, digest in expected_files.items()
    ):
        raise ValueError("release sealed artifact file map is invalid")
    actual = _complete_artifact_set(output_root, sealed=document.get("status") == "PASS")
    for field in (
        "complete",
        "excluded_prefixes",
        "excluded_wrappers",
        "file_count",
        "files",
        "set_sha256",
        "total_bytes",
    ):
        if sealed.get(field) != actual.get(field):
            raise ValueError(f"release sealed artifact set {field} mismatch")


def _curated_evidence_bytes(body: Mapping[str, object], raw_receipt_sha256: str) -> bytes:
    checks = body.get("checks")
    check_statuses: dict[str, object] = {}
    if isinstance(checks, list):
        for raw in checks:
            if isinstance(raw, dict) and isinstance(raw.get("id"), str):
                check_statuses[cast(str, raw["id"])] = raw.get("status")
    identity = body.get("identity")
    candidate_commit = identity.get("git_commit") if isinstance(identity, dict) else None
    document: dict[str, object] = {
        "absolute_paths_included": False,
        "candidate_commit": candidate_commit,
        "check_statuses": check_statuses,
        "claim": body.get("claim"),
        "human_gates": body.get("human_gates"),
        "raw_receipt_sha256": raw_receipt_sha256,
        "result_labels": body.get("result_labels"),
        "schema": "arc3.release-candidate-curated-evidence.v0.1",
        "sealed_artifact_set": body.get("sealed_artifact_set"),
        "status": body.get("status"),
        "verification_boundary": body.get("verification_boundary"),
    }
    document["evidence_sha256"] = sha256_bytes(canonical_json_bytes(document))
    return canonical_json_bytes(document)


def _plan_document(specs: Sequence[CommandSpec]) -> dict[str, object]:
    body: dict[str, object] = {
        "checks": [spec.to_dict() for spec in specs],
        "internal_checks": list(_INTERNAL_CHECKS),
        "schema": PLAN_SCHEMA,
    }
    body["plan_sha256"] = sha256_bytes(canonical_json_bytes(body))
    return body


def _overall_status(results: Sequence[CheckResult]) -> str:
    required = [result for result in results if result.required]
    if any(result.status == "FAILED_INFRASTRUCTURE" for result in required):
        return "FAILED_INFRASTRUCTURE"
    if any(result.status != "PASS" for result in required):
        return "FAILED_MECHANISM"
    return "PASS"


def _receipt_bytes(body: Mapping[str, object]) -> bytes:
    document = dict(body)
    document[RECEIPT_HASH_FIELD] = sha256_bytes(canonical_json_bytes(body))
    return canonical_json_bytes(document)


def _runtime_identity() -> dict[str, object]:
    return {
        "gpu": None,
        "gpu_reason": "the symbolic release verifier neither requires nor queries a GPU",
        "logical_cpu_count": os.cpu_count(),
        "machine": platform.machine() or None,
        "operating_system": platform.platform(),
        "processor": platform.processor() or platform.machine() or None,
        "python_executable": sys.executable,
        "python_version": platform.python_version(),
        "ram_gb": None,
        "ram_reason": "Stage 16 carries measured whole-process memory; this verifier does not infer it",
    }


def verify_release_receipt(path: Path) -> dict[str, Any]:
    """Parse, self-hash, and require canonical bytes for a release receipt."""

    raw = path.read_bytes()
    document = _verified_self_hashed_object(path, hash_field=RECEIPT_HASH_FIELD)
    if document.get("schema") != SCHEMA:
        raise ValueError("unsupported release verification receipt schema")
    if _receipt_bytes(document) != raw:
        raise ValueError("release verification receipt is not canonical JSON")
    verify_sealed_artifact_set(document, path.resolve().parent)
    return document


def run_release_verification(
    *,
    repository: Path,
    output_root: Path,
    expected_commit: str,
    expectation_path: Path,
    uv_command: tuple[str, ...],
    official_environments: Path,
) -> dict[str, object]:
    """Run every achievable Stage 18 check and write one sealed receipt."""

    repository = repository.resolve()
    output_root = output_root.resolve()
    expectation_path = expectation_path.resolve()
    started_at = _utc_now()
    identity = repository_identity(repository, expected_commit)
    prepare_fresh_output_root(repository, output_root)
    interpreter_identity = interpreter_source_identity(repository, output_root)
    identity["interpreter"] = interpreter_identity
    expectation = load_benchmark_expectation(expectation_path)
    benchmark_basis = benchmark_basis_identity(expectation, repository, expected_commit)
    raw_specs = build_plan(
        repository=repository,
        output_root=output_root,
        expectation=expectation,
        uv_command=uv_command,
        official_environments=official_environments,
    )
    specs = tuple(_replace_candidate_commit(spec, expected_commit) for spec in raw_specs)
    by_id = {spec.check_id: spec for spec in specs}
    results: list[CheckResult] = [
        internal_result(
            "interpreter-source-identity",
            "source-identity",
            status="PASS",
            details=interpreter_identity,
        ),
        internal_result(
            "benchmark-basis-validation",
            "synthetic",
            status="PASS",
            details=benchmark_basis,
        ),
    ]
    prior: dict[str, CheckResult] = {result.check_id: result for result in results}

    core_ids = (
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
    )
    for check_id in core_ids:
        result = run_command(
            by_id[check_id], repository=repository, output_root=output_root, prior=prior
        )
        results.append(result)
        prior[check_id] = result

    evaluation_directory = output_root / "evaluations" / "stage18-benchmark-reproduction"
    if prior["synthetic-artifact-verification"].status == "PASS":
        try:
            equal, details = compare_benchmark(expectation, evaluation_directory)
            benchmark_result = internal_result(
                "benchmark-semantic-reproduction",
                "synthetic",
                status="PASS" if equal else "FAILED_MECHANISM",
                reason=None if equal else "deterministic benchmark projection changed",
                details=details,
            )
        except (OSError, ValueError) as error:
            benchmark_result = internal_result(
                "benchmark-semantic-reproduction",
                "synthetic",
                status="FAILED_INFRASTRUCTURE",
                reason=f"benchmark comparison failed: {error}",
            )
    else:
        benchmark_result = internal_result(
            "benchmark-semantic-reproduction",
            "synthetic",
            status="FAILED_MECHANISM",
            reason="synthetic artifact verification did not pass",
        )
    results.append(benchmark_result)
    prior[benchmark_result.check_id] = benchmark_result

    if prior["offline-package-a"].status == "PASS" and prior["offline-package-b"].status == "PASS":
        try:
            equal, details = compare_packages(
                output_root / "package-a" / "build-receipt.json",
                output_root / "package-b" / "build-receipt.json",
                expected_commit=expected_commit,
            )
            package_result = internal_result(
                "offline-package-determinism",
                "offline-package",
                status="PASS" if equal else "FAILED_MECHANISM",
                reason=None if equal else "two fresh package builds have different identities",
                details=details,
            )
        except (OSError, ValueError) as error:
            package_result = internal_result(
                "offline-package-determinism",
                "offline-package",
                status="FAILED_INFRASTRUCTURE",
                reason=f"package receipt comparison failed: {error}",
            )
    else:
        package_result = internal_result(
            "offline-package-determinism",
            "offline-package",
            status="FAILED_MECHANISM",
            reason="one or both offline package builds failed",
        )
    results.append(package_result)
    prior[package_result.check_id] = package_result

    if prior["competition-integrity"].status == "PASS":
        try:
            integrity = _verified_self_hashed_object(
                output_root / "integrity-receipt.json", hash_field=RECEIPT_HASH_FIELD
            )
            integrity_passed = integrity.get("passed") is True
            integrity_result = internal_result(
                "integrity-receipt-validation",
                "integrity",
                status="PASS" if integrity_passed else "FAILED_MECHANISM",
                reason=None if integrity_passed else "integrity receipt did not pass",
                details={
                    "finding_count": integrity.get("finding_count"),
                    "passed": integrity.get("passed"),
                    "schema": integrity.get("schema"),
                },
            )
        except (OSError, ValueError) as error:
            integrity_result = internal_result(
                "integrity-receipt-validation",
                "integrity",
                status="FAILED_INFRASTRUCTURE",
                reason=f"integrity receipt validation failed: {error}",
            )
    else:
        integrity_result = internal_result(
            "integrity-receipt-validation",
            "integrity",
            status="FAILED_MECHANISM",
            reason="competition integrity command did not pass",
        )
    results.append(integrity_result)
    prior[integrity_result.check_id] = integrity_result

    official_available = False
    official_details: dict[str, object] = {}
    availability_error: str | None = None
    if prior["official-inventory"].status == "PASS":
        try:
            inventory_log = output_root / "logs" / "official-inventory.stdout.log"
            inventory = _last_json_log(inventory_log)
            official_available, official_details = official_smoke_available(
                inventory,
                repository / "docs/evaluation/public-game-partitions.v0.1.json",
            )
        except (OSError, ValueError) as error:
            availability_error = str(error)
            official_details = {"inventory_interpretation_error": str(error)}
    else:
        availability_error = "official inventory command did not pass"
    availability_result = internal_result(
        "official-availability",
        "official-smoke",
        status="PASS" if availability_error is None else "FAILED_INFRASTRUCTURE",
        reason=availability_error,
        details=official_details,
    )
    results.append(availability_result)
    prior[availability_result.check_id] = availability_result
    if official_available:
        official_result = run_command(
            replace(by_id["official-smoke"], required=True),
            repository=repository,
            output_root=output_root,
            prior=prior,
        )
        results.append(official_result)
        prior[official_result.check_id] = official_result
        official_verify = run_command(
            replace(by_id["official-artifact-verification"], required=True),
            repository=repository,
            output_root=output_root,
            prior=prior,
        )
        results.append(official_verify)
        prior[official_verify.check_id] = official_verify
    else:
        reason = (
            "the frozen official smoke assets are not all present; no acquisition or gameplay "
            "was attempted"
            if prior["official-inventory"].status == "PASS"
            else "official inventory failed before local availability could be established"
        )
        for check_id in ("official-smoke", "official-artifact-verification"):
            blocked = _blocked_result(by_id[check_id], reason, status="BLOCKED_EXTERNAL")
            blocked = replace(blocked, details={**blocked.details, **official_details})
            results.append(blocked)
            prior[check_id] = blocked

    try:
        final_identity = repository_identity(repository, expected_commit)
        final_clean = internal_result(
            "repository-clean-after",
            "source-identity",
            status="PASS",
            details=final_identity,
        )
    except ValueError as error:
        final_clean = internal_result(
            "repository-clean-after",
            "source-identity",
            status="FAILED_INFRASTRUCTURE",
            reason=str(error),
        )
    results.append(final_clean)

    logs_passed, log_details = scan_generated_logs(output_root, results)
    log_scan = internal_result(
        "generated-log-secret-scan",
        "secret-scan",
        status="PASS" if logs_passed else "FAILED_MECHANISM",
        reason=None
        if logs_passed
        else "generated output required redaction or retained a secret pattern",
        details=log_details,
    )
    results.append(log_scan)

    result_labels = ["synthetic"]
    if prior["official-smoke"].status == "PASS":
        result_labels.append("local-public")
    plan = _plan_document(specs)
    completed_at = _utc_now()
    status = _overall_status(results)
    sealed_artifact_set = _complete_artifact_set(output_root, sealed=status == "PASS")
    seal_result = internal_result(
        "sealed-artifact-set",
        "artifacts",
        status="PASS",
        details={
            "complete": sealed_artifact_set["complete"],
            "file_count": sealed_artifact_set["file_count"],
            "set_sha256": sealed_artifact_set["set_sha256"],
            "total_bytes": sealed_artifact_set["total_bytes"],
        },
    )
    results.append(seal_result)
    body: dict[str, object] = {
        "artifact_hashes": sealed_artifact_set["files"],
        "checks": [result.to_dict() for result in results],
        "claim": "NO_GENERALIZATION_CLAIM",
        "completed_at": completed_at,
        "human_gates": {
            "license_granted": False,
            "official_submission_performed": False,
            "terms_accepted_by_verifier": False,
        },
        "identity": identity,
        "official_smoke": {
            "availability": official_details,
            "available": official_available,
            "surface": "local-public" if official_available else None,
            "status": prior["official-smoke"].status,
        },
        "output_root": str(output_root),
        "plan": plan,
        "result_labels": result_labels,
        "runtime": _runtime_identity(),
        "schema": SCHEMA,
        "sealed_artifact_set": sealed_artifact_set,
        "started_at": started_at,
        "status": status,
        "verification_boundary": {
            "command_environment": (
                "strict host-variable allowlist; isolated HOME, USERPROFILE, temporary, and caches"
            ),
            "dependency_resolution": "uv lock check uses offline mode",
            "game_source_inspected": False,
            "generated_logs": (
                "credential values and token-like assignments are redacted before persistence; "
                "any redaction fails the required generated-log scan"
            ),
            "network_claim": (
                "No hosted inference is used. The package rehearsal blocks Python sockets. "
                "The verifier does not claim operating-system-level egress denial."
            ),
        },
    }
    receipt_path = output_root / "release-verification-receipt.json"
    write_bytes_atomic(receipt_path, _receipt_bytes(body))
    verify_release_receipt(receipt_path)
    curated_path = output_root / "release-verification-evidence.json"
    write_bytes_atomic(
        curated_path,
        _curated_evidence_bytes(body, sha256_file(receipt_path)),
    )
    verify_release_receipt(receipt_path)
    return body


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=REPOSITORY)
    parser.add_argument("--output-root", type=Path, default=Path("artifacts/stage18/rc"))
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--expectation", type=Path, default=DEFAULT_EXPECTATION)
    uv_group = parser.add_mutually_exclusive_group()
    uv_group.add_argument("--uv-executable", type=Path)
    uv_group.add_argument("--uv-python", type=Path)
    parser.add_argument(
        "--official-environments-dir",
        type=Path,
        default=Path("artifacts/stage15/public-environments"),
    )
    parser.add_argument(
        "--plan-only",
        action="store_true",
        help="print the fully rendered deterministic command plan without running it",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    repository = args.root.resolve()
    output_root = (
        args.output_root if args.output_root.is_absolute() else repository / args.output_root
    ).resolve()
    expectation_path = (
        args.expectation if args.expectation.is_absolute() else repository / args.expectation
    ).resolve()
    official_environments = (
        args.official_environments_dir
        if args.official_environments_dir.is_absolute()
        else repository / args.official_environments_dir
    ).resolve()
    try:
        if not _COMMIT.fullmatch(args.expected_commit):
            raise ValueError("--expected-commit must be a lowercase full 40-character SHA")
        expectation = load_benchmark_expectation(expectation_path)
        uv_command = discover_uv_command(
            uv_executable=args.uv_executable,
            uv_python=args.uv_python,
        )
        specs = tuple(
            _replace_candidate_commit(spec, args.expected_commit)
            for spec in build_plan(
                repository=repository,
                output_root=output_root,
                expectation=expectation,
                uv_command=uv_command,
                official_environments=official_environments,
            )
        )
        if args.plan_only:
            print(json.dumps(_plan_document(specs), indent=2, sort_keys=True))
            return 0
        body = run_release_verification(
            repository=repository,
            output_root=output_root,
            expected_commit=args.expected_commit,
            expectation_path=expectation_path,
            uv_command=uv_command,
            official_environments=official_environments,
        )
    except (OSError, ValueError) as error:
        print(f"release verification refused: {error}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "receipt": str(output_root / "release-verification-receipt.json"),
                "schema": SCHEMA,
                "status": body["status"],
            },
            sort_keys=True,
        )
    )
    return 0 if body["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
