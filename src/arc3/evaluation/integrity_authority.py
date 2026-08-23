"""Opaque-holdout Build 001 competition-integrity authority.

The authority is deliberately narrower than a full public-identifier scan.  It
combines a fresh complete static package scan, direct scans for only the already
exposed Stage 09 development identifiers, the sealed holdout nonconsumption
receipt, and the verified Stage 09 terminal.  It never opens or resolves the
public manifest, and it records the static/dynamic/native limitation explicitly.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import json
import os
import platform
import subprocess
import sys
import tomllib
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, cast

from arc3.errors import EvaluationError
from arc3.evaluation.artifacts import (
    canonical_json_bytes,
    seal_object,
    sha256_bytes,
    sha256_file,
    verify_object_hash,
)
from arc3.evaluation.development_recovery import validate_predeclaration_bytes
from arc3.integrity import (
    INTEGRITY_SCHEMA,
    IntegrityReceipt,
    discover_candidate_files,
    discover_policy_files,
    discover_reachable_policy_files,
    scan_policy_files,
)
from arc3.types import JSONValue

COMPOSITE_INTEGRITY_SCHEMA = "arc3.build-001.competition-integrity-composite.v0.1"
COMPOSITE_INTEGRITY_HASH_FIELD = "artifact_core_hash"
OPAQUE_PUBLIC_MANIFEST_SHA256 = (
    "sha256:682d5891c2aface54803d9bd1173c55ed21e89856e13b8a478fb9276ee963f2f"
)
COMPETITION_CONFIG_PATH = "src/arc3/competition-runtime.v0.1.json"
DEPENDENCY_LOCK_PATH = "uv.lock"
UPSTREAM_LOCK_PATH = "upstream.lock.json"

_REQUIRED_CHECKS = frozenset(
    {
        "archive_static",
        "policy_static",
        "secret_scan",
        "source_identity",
        "supply_chain",
    }
)
_RUNTIME_DISTRIBUTIONS = (
    ("arc-agi", "arc_agi/"),
    ("arcengine", "arcengine/"),
)
_SCORER_DISTRIBUTION = "arc-agi"
_SCORER_MODULE = "arc_agi/scorecard.py"
_PRODUCTION_POLICY_ENTRY_POINTS = ["agent/my_agent.py"]
_STAGE09_VERIFICATION_SCHEMA = "arc3.build-001.stage-09-terminal-verification.v0.2"
_STAGE09_VERIFICATION_FIELDS = {
    "attempt_root",
    "competition_integrity",
    "evidence_integrity",
    "execution_complete",
    "exposure",
    "gate",
    "output",
    "passed",
    "prior_authority",
    "schema",
    "source_end",
    "source_root",
    "source_stable",
    "status",
    "terminal_finalization",
    "verification_hash",
    "work_authority",
}
_STAGE09_PRIOR_AUTHORITY_FIELDS = {
    "assurance_limitation",
    "build_001_package_only",
    "development_scans",
    "full_public_integrity_status",
    "holdout",
    "predeclaration",
    "prior_authority_hash",
}
_STAGE09_HOLDOUT_FIELDS = {
    "file_sha256",
    "identities_loaded",
    "manifest_loaded_as_metadata",
    "pinned_manifest_sha256",
    "public_holdout_gameplay_events",
    "status",
}
_STAGE09_ASSURANCE_LIMITATION = (
    "Package and development scans are static; dynamic-import and native-extension "
    "containment are not proven; Build 001 public identifiers were not fully evaluated."
)
_STATIC_LIMITATION = (
    "Static first-party import reachability does not prove runtime dynamic-import "
    "or native-extension containment."
)


def _mapping(value: object, *, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise EvaluationError(f"{field} must be an object")
    return cast(Mapping[str, object], value)


def _sha256(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        raise EvaluationError(f"{field} must be a sha256 identity")
    digest = value.removeprefix("sha256:")
    if (
        not value.startswith("sha256:")
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise EvaluationError(f"{field} must be a sha256 identity")
    return value


def _git_hash(value: object, *, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 40
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise EvaluationError(f"{field} must be a full lowercase git identity")
    return value


def _git(root: Path, *arguments: str) -> str:
    environment = {
        key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")
    }
    try:
        completed = subprocess.run(
            ("git", *arguments),
            cwd=root,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise EvaluationError("composite integrity source identity is unavailable") from error
    return completed.stdout.strip()


def _source_identity(root: Path) -> dict[str, JSONValue]:
    repository = root.resolve()
    top_level = Path(_git(repository, "rev-parse", "--show-toplevel")).resolve()
    if top_level != repository:
        raise EvaluationError("composite integrity Git root differs from execution source")
    commit = _git(repository, "rev-parse", "HEAD")
    tree = _git(repository, "rev-parse", "HEAD^{tree}")
    dirty = bool(_git(repository, "status", "--porcelain=v1", "--untracked-files=all"))
    _git_hash(commit, field="execution source commit")
    _git_hash(tree, field="execution source tree")
    return {"clean_worktree": not dirty, "commit": commit, "tree": tree}


def reachable_policy_projection(root: Path) -> dict[str, str]:
    """Return the exact current production-policy import closure."""

    repository = root.resolve()
    candidates = discover_candidate_files(repository)
    reachable = discover_reachable_policy_files(repository, candidate_files=candidates)
    return {path.relative_to(repository).as_posix(): sha256_file(path) for path in reachable}


def _package_candidate_callable(root: Path) -> Callable[[Path], object]:
    repository = root.resolve()
    expected_script = repository / "scripts/check_competition_integrity.py"
    try:
        module = importlib.import_module("scripts.check_competition_integrity")
    except (ImportError, OSError, RuntimeError, ValueError) as error:
        raise EvaluationError("package-only candidate authority failed to load") from error
    function = getattr(module, "package_only_candidate_files", None)
    origin = getattr(module, "__file__", None)
    code = getattr(function, "__code__", None)
    if (
        not isinstance(origin, str)
        or Path(origin).resolve() != expected_script.resolve()
        or code is None
        or Path(code.co_filename).resolve() != expected_script.resolve()
    ):
        raise EvaluationError("package-only candidate authority has mixed origin")
    return cast(Callable[[Path], object], function)


def _package_candidate_projection(root: Path) -> dict[str, str]:
    repository = root.resolve()
    function = _package_candidate_callable(repository)
    try:
        paths = function(repository)
    except (OSError, RuntimeError, TypeError, ValueError) as error:
        raise EvaluationError("package-only candidate authority failed") from error
    if not isinstance(paths, tuple) or not paths:
        raise EvaluationError("package-only candidate authority returned no files")
    projection: dict[str, str] = {}
    for path in paths:
        if not isinstance(path, Path) or not path.is_file():
            raise EvaluationError("package-only candidate file is unavailable")
        try:
            label = path.resolve().relative_to(repository).as_posix()
        except ValueError as error:
            raise EvaluationError("package-only candidate escaped execution source") from error
        if label in projection:
            raise EvaluationError("package-only candidate authority returned a duplicate")
        projection[label] = sha256_file(path)
    return dict(sorted(projection.items()))


def _stage09_terminal_verifier(source_root: Path) -> Callable[..., object]:
    root = source_root.resolve()
    expected_script = root / "scripts/measure_development_recovery.py"
    try:
        module = importlib.import_module("scripts.measure_development_recovery")
    except (ImportError, OSError, RuntimeError, ValueError) as error:
        raise EvaluationError("Stage 09 terminal verifier failed to load") from error
    verifier = getattr(module, "verify_complete_terminal", None)
    origin = getattr(module, "__file__", None)
    code = getattr(verifier, "__code__", None)
    if (
        not isinstance(origin, str)
        or Path(origin).resolve() != expected_script
        or code is None
        or Path(code.co_filename).resolve() != expected_script
    ):
        raise EvaluationError("Stage 09 terminal verifier has mixed origin")
    return cast(Callable[..., object], verifier)


def _projection_summary(projection: Mapping[str, str]) -> dict[str, JSONValue]:
    return {
        "file_count": len(projection),
        "projection_sha256": sha256_bytes(canonical_json_bytes(dict(projection))),
    }


def _locked_versions(path: Path) -> dict[str, str]:
    try:
        document = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise EvaluationError("uv.lock is unreadable") from error
    packages = document.get("package")
    if not isinstance(packages, list):
        raise EvaluationError("uv.lock has no package inventory")
    versions: dict[str, str] = {}
    for item in packages:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        version = item.get("version")
        if isinstance(name, str) and isinstance(version, str):
            versions[name] = version
    return versions


def _distribution_source_identity(name: str, package_prefix: str) -> dict[str, JSONValue]:
    try:
        distribution = importlib.metadata.distribution(name)
    except importlib.metadata.PackageNotFoundError:
        return {"file_count": 0, "source_sha256": None, "version": None}
    rows: list[tuple[str, int, str]] = []
    for item in sorted(distribution.files or (), key=lambda value: str(value).replace("\\", "/")):
        relative = str(item).replace("\\", "/")
        path = Path(str(distribution.locate_file(item))).resolve()
        if (
            relative.startswith(package_prefix)
            and path.is_file()
            and "__pycache__" not in path.parts
            and path.suffix != ".pyc"
        ):
            rows.append((relative, path.stat().st_size, sha256_file(path)))
    return {
        "file_count": len(rows),
        "source_sha256": sha256_bytes(canonical_json_bytes(rows)),
        "version": distribution.version,
    }


def runtime_surface_identity(root: Path) -> dict[str, Any]:
    """Bind the live interpreter, locked SDK distributions, and scorer bytes.

    This is import-free with respect to the ARC environment SDK.  Distribution
    files are located and hashed as bytes, so the function is safe to call
    before the first holdout authorization.
    """

    repository = root.resolve()
    executable = Path(sys.executable).resolve()
    lock_path = repository / DEPENDENCY_LOCK_PATH
    upstream_path = repository / UPSTREAM_LOCK_PATH
    locked = _locked_versions(lock_path)
    distributions = {
        name: _distribution_source_identity(name, prefix) for name, prefix in _RUNTIME_DISTRIBUTIONS
    }
    try:
        scorer_distribution = importlib.metadata.distribution(_SCORER_DISTRIBUTION)
        scorer_path = Path(str(scorer_distribution.locate_file(_SCORER_MODULE))).resolve()
        scorer_hash = sha256_file(scorer_path) if scorer_path.is_file() else None
    except importlib.metadata.PackageNotFoundError:
        scorer_hash = None
    versions_match_lock = all(
        isinstance(identity.get("version"), str) and identity.get("version") == locked.get(name)
        for name, identity in distributions.items()
    )
    payload: dict[str, Any] = {
        "cache_tag": sys.implementation.cache_tag,
        "distributions": distributions,
        "executable": executable.as_posix(),
        "executable_sha256": sha256_file(executable) if executable.is_file() else None,
        "implementation": platform.python_implementation(),
        "python_version": platform.python_version(),
        "schema": "arc3.build-001.runtime-surface.v0.1",
        "scorer": {
            "distribution": _SCORER_DISTRIBUTION,
            "module": _SCORER_MODULE,
            "sha256": scorer_hash,
        },
        "upstream_lock_sha256": (sha256_file(upstream_path) if upstream_path.is_file() else None),
        "uv_lock_sha256": sha256_file(lock_path) if lock_path.is_file() else None,
        "verified": bool(
            executable.is_file()
            and sys.version_info[:2] == (3, 12)
            and versions_match_lock
            and all(
                isinstance(identity.get("source_sha256"), str)
                and isinstance(identity.get("file_count"), int)
                and cast(int, identity["file_count"]) > 0
                for identity in distributions.values()
            )
            and isinstance(scorer_hash, str)
            and lock_path.is_file()
            and upstream_path.is_file()
        ),
        "versions_match_lock": versions_match_lock,
    }
    return seal_object(payload, hash_field="runtime_surface_sha256")


def _competition_config_identity(root: Path) -> dict[str, JSONValue]:
    path = root.resolve() / COMPETITION_CONFIG_PATH
    try:
        raw = path.read_bytes()
        value: object = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise EvaluationError("competition config is unreadable") from error
    if not isinstance(value, dict):
        raise EvaluationError("competition config is not an object")
    document = cast(dict[str, object], value)
    claimed = _sha256(document.get("configuration_sha256"), field="competition config")
    unsigned = {key: item for key, item in document.items() if key != "configuration_sha256"}
    encoded = json.dumps(
        unsigned,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    if sha256_bytes(encoded) != claimed:
        raise EvaluationError("competition config self-hash changed")
    return {
        "configuration_sha256": claimed,
        "file_sha256": sha256_bytes(raw),
        "path": COMPETITION_CONFIG_PATH,
    }


def _read_integrity(path: Path, *, field: str) -> tuple[bytes, IntegrityReceipt]:
    try:
        raw = path.resolve().read_bytes()
        receipt = IntegrityReceipt.from_bytes(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise EvaluationError(f"{field} is not a canonical integrity receipt") from error
    return raw, receipt


def _checks_clear(body: Mapping[str, JSONValue]) -> bool:
    checks = body.get("checks")
    counts = body.get("finding_counts")
    findings = body.get("findings")
    return bool(
        isinstance(checks, Mapping)
        and set(checks) == _REQUIRED_CHECKS
        and all(
            isinstance(checks[name], Mapping)
            and cast(Mapping[str, object], checks[name]).get("passed") is True
            for name in _REQUIRED_CHECKS
        )
        and cast(Mapping[str, object], checks["supply_chain"]).get("status") == "PASS"
        and isinstance(counts, Mapping)
        and set(counts) == {"blocking", "total", "warnings"}
        and all(
            isinstance(counts.get(name), int)
            and not isinstance(counts.get(name), bool)
            and counts.get(name) == 0
            for name in ("blocking", "total", "warnings")
        )
        and counts.get("blocking") == 0
        and counts.get("total") == 0
        and counts.get("warnings") == 0
        and findings == []
    )


def _development_identifiers(
    predeclaration_path: Path,
    *,
    expected_file_sha256: str,
    expected_core_hash: str,
    expected_sha256: str,
) -> tuple[tuple[str, ...], dict[str, JSONValue]]:
    """Parse only the frozen, already-exposed Stage 09 declaration."""

    _sha256(expected_file_sha256, field="development predeclaration file hash")
    _sha256(expected_core_hash, field="development predeclaration core hash")
    _sha256(expected_sha256, field="development identifier list hash")
    try:
        raw = predeclaration_path.resolve().read_bytes()
        declaration = validate_predeclaration_bytes(
            raw,
            expected_file_sha256=expected_file_sha256,
        )
    except (OSError, EvaluationError) as error:
        raise EvaluationError("Stage 09 development declaration failed validation") from error
    games = declaration.get("development_games")
    bindings = declaration.get("bindings")
    if (
        declaration.get("predeclaration_core_hash") != expected_core_hash
        or not isinstance(games, list)
        or len(games) != 12
        or not isinstance(bindings, Mapping)
        or not isinstance(bindings.get("build_000_commit"), str)
        or not isinstance(bindings.get("build_000_tree"), str)
    ):
        raise EvaluationError("Stage 09 development identity authority changed")
    values: list[str] = []
    for game in games:
        if not isinstance(game, Mapping):
            raise EvaluationError("Stage 09 development identity entry changed")
        game_id = game.get("game_id")
        stable_name = game.get("stable_name")
        if (
            set(game) != {"asset_sha256", "game_id", "stable_name"}
            or not isinstance(game_id, str)
            or not isinstance(stable_name, str)
            or not isinstance(game.get("asset_sha256"), str)
        ):
            raise EvaluationError("Stage 09 development identifier source changed")
        values.extend((game_id, stable_name))
    identifiers = tuple(sorted(set(values)))
    actual = sha256_bytes(canonical_json_bytes(list(identifiers)))
    if len(identifiers) != 24 or actual != expected_sha256:
        raise EvaluationError("Stage 09 development identifier authority changed")
    return identifiers, {
        "development_identity_count": len(games),
        "identifier_string_count": len(identifiers),
        "identifier_list_sha256": actual,
        "build_000_commit": cast(str, bindings["build_000_commit"]),
        "build_000_tree": cast(str, bindings["build_000_tree"]),
        "predeclaration_core_hash": expected_core_hash,
        "predeclaration_file_sha256": expected_file_sha256,
        "source_path": predeclaration_path.resolve().as_posix(),
    }


def _development_scan(
    root: Path,
    *,
    identifiers: tuple[str, ...],
    expected_commit: str,
    expected_tree: str,
) -> dict[str, JSONValue]:
    source = _source_identity(root)
    if (
        source.get("clean_worktree") is not True
        or source.get("commit") != _git_hash(expected_commit, field="development source commit")
        or source.get("tree") != _git_hash(expected_tree, field="development source tree")
    ):
        raise EvaluationError("development policy scan source identity changed")
    files = discover_policy_files(root.resolve())
    findings = scan_policy_files(
        root=root.resolve(),
        files=files,
        public_identifiers=identifiers,
    )
    if findings:
        raise EvaluationError("development-identifier policy scan has blocking findings")
    projection = {
        path.resolve().relative_to(root.resolve()).as_posix(): sha256_file(path) for path in files
    }
    return {
        "finding_count": 0,
        "passed": True,
        "policy_file_count": len(files),
        "policy_projection_sha256": sha256_bytes(canonical_json_bytes(projection)),
        "source": {**source, "root": root.resolve().as_posix()},
    }


def _holdout_nonconsumption_summary(
    path: Path,
    *,
    expected_file_sha256: str,
) -> dict[str, JSONValue]:
    _sha256(expected_file_sha256, field="holdout nonconsumption file hash")
    try:
        raw = path.resolve().read_bytes()
        value: object = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise EvaluationError("holdout nonconsumption receipt is unreadable") from error
    if not isinstance(value, dict) or sha256_bytes(raw) != expected_file_sha256:
        raise EvaluationError("holdout nonconsumption receipt identity changed")
    document = cast(dict[str, object], value)
    projection_raw = document.get("integrity", document.get("holdout"))
    projection = _mapping(projection_raw, field="holdout nonconsumption projection")
    metadata_flag = projection.get(
        "manifest_loaded_as_metadata",
        projection.get("holdout_manifest_loaded_as_gameplay_metadata"),
    )
    manifest_hash = projection.get("holdout_manifest_sha256", projection.get("manifest_sha256"))
    if (
        projection.get("holdout_sealed") is not True
        or isinstance(projection.get("public_holdout_game_ids_selected"), bool)
        or projection.get("public_holdout_game_ids_selected") != 0
        or isinstance(projection.get("public_holdout_gameplay_events"), bool)
        or projection.get("public_holdout_gameplay_events") != 0
        or metadata_flag is not False
        or manifest_hash != OPAQUE_PUBLIC_MANIFEST_SHA256
    ):
        raise EvaluationError("holdout nonconsumption receipt is not sealed and opaque")
    return {
        "file_sha256": expected_file_sha256,
        "manifest_loaded_as_metadata": False,
        "manifest_sha256": OPAQUE_PUBLIC_MANIFEST_SHA256,
        "path": path.resolve().as_posix(),
        "public_holdout_game_ids_selected": 0,
        "public_holdout_gameplay_events": 0,
        "sealed": True,
    }


def _stage09_verification_summary(
    path: Path,
    *,
    expected_file_sha256: str,
    expected_verification_hash: str,
    source_root: Path,
    expected_holdout_nonconsumption_sha256: str,
    expected_development_identifier_sha256: str,
    expected_development_predeclaration_file_sha256: str,
    expected_development_predeclaration_core_hash: str,
) -> dict[str, JSONValue]:
    _sha256(expected_file_sha256, field="Stage 09 verification file hash")
    _sha256(expected_verification_hash, field="Stage 09 verification core hash")
    _sha256(
        expected_development_identifier_sha256,
        field="Stage 09 development identifier list hash",
    )
    _sha256(
        expected_development_predeclaration_file_sha256,
        field="Stage 09 original predeclaration file hash",
    )
    _sha256(
        expected_development_predeclaration_core_hash,
        field="Stage 09 original predeclaration core hash",
    )
    try:
        raw = path.resolve().read_bytes()
        value: object = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise EvaluationError("Stage 09 terminal verification is unreadable") from error
    if not isinstance(value, dict):
        raise EvaluationError("Stage 09 terminal verification is not an object")
    receipt = cast(dict[str, object], value)
    output = receipt.get("output")
    exposure = receipt.get("exposure")
    finalization = receipt.get("terminal_finalization")
    prior_authority = receipt.get("prior_authority")
    work_authority = receipt.get("work_authority")
    stage09_source_root = receipt.get("source_root")
    attempt_root = receipt.get("attempt_root")
    holdout: Mapping[str, object] | None = None
    predeclaration: Mapping[str, object] | None = None
    package: Mapping[str, object] | None = None
    development_scans: Mapping[str, object] | None = None
    if isinstance(prior_authority, Mapping) and isinstance(prior_authority.get("holdout"), Mapping):
        holdout = cast(Mapping[str, object], prior_authority["holdout"])
    if isinstance(prior_authority, Mapping) and isinstance(
        prior_authority.get("predeclaration"), Mapping
    ):
        predeclaration = cast(Mapping[str, object], prior_authority["predeclaration"])
    if isinstance(prior_authority, Mapping) and isinstance(
        prior_authority.get("build_001_package_only"), Mapping
    ):
        package = cast(Mapping[str, object], prior_authority["build_001_package_only"])
    if isinstance(prior_authority, Mapping) and isinstance(
        prior_authority.get("development_scans"), Mapping
    ):
        development_scans = cast(Mapping[str, object], prior_authority["development_scans"])
    original = (
        cast(Mapping[str, object], predeclaration["original"])
        if isinstance(predeclaration, Mapping)
        and isinstance(predeclaration.get("original"), Mapping)
        else None
    )
    if (
        sha256_bytes(raw) != expected_file_sha256
        or canonical_json_bytes(receipt) != raw
        or set(receipt) != _STAGE09_VERIFICATION_FIELDS
        or receipt.get("schema") != _STAGE09_VERIFICATION_SCHEMA
        or receipt.get("verification_hash") != expected_verification_hash
        or not verify_object_hash(receipt, hash_field="verification_hash")
        or receipt.get("passed") is not True
        or receipt.get("status") not in {"PASS", "FAILED_MECHANISM"}
        or receipt.get("execution_complete") is not True
        or receipt.get("evidence_integrity") is not True
        or receipt.get("competition_integrity") is not True
        or receipt.get("source_stable") is not True
        or not isinstance(stage09_source_root, str)
        or Path(stage09_source_root).resolve() != source_root.resolve()
        or not isinstance(attempt_root, str)
        or not Path(attempt_root).is_absolute()
        or not isinstance(output, Mapping)
        or set(output) != {"artifact_core_hash", "path", "sha256"}
        or not isinstance(exposure, Mapping)
        or set(exposure) != {"path", "sha256"}
        or not isinstance(finalization, Mapping)
        or set(finalization) != {"path", "sha256", "terminal_finalization_hash"}
        or not isinstance(prior_authority, Mapping)
        or set(prior_authority) != _STAGE09_PRIOR_AUTHORITY_FIELDS
        or prior_authority.get("full_public_integrity_status")
        != "NOT_EVALUATED_BUILD_001_PUBLIC_IDENTIFIERS"
        or prior_authority.get("assurance_limitation") != _STAGE09_ASSURANCE_LIMITATION
        or predeclaration is None
        or set(predeclaration)
        != {
            "amendment",
            "effective_build_001_commit",
            "effective_build_001_source_sha256",
            "effective_build_001_tree",
            "effective_matrix_hash",
            "live_validated",
            "original",
        }
        or predeclaration.get("live_validated") is not True
        or not isinstance(predeclaration.get("original"), Mapping)
        or set(cast(Mapping[str, object], predeclaration["original"]))
        != {"core_hash", "file_sha256", "path", "preserved_unchanged"}
        or cast(Mapping[str, object], predeclaration["original"]).get("preserved_unchanged")
        is not True
        or original is None
        or original.get("file_sha256") != expected_development_predeclaration_file_sha256
        or original.get("core_hash") != expected_development_predeclaration_core_hash
        or not isinstance(original.get("path"), str)
        or Path(cast(str, original["path"])).resolve()
        != source_root.resolve() / "docs/evidence/001-09-development-recovery-predeclaration.json"
        or not isinstance(predeclaration.get("amendment"), Mapping)
        or set(cast(Mapping[str, object], predeclaration["amendment"]))
        != {"core_hash", "file_sha256", "path", "result_state"}
        or cast(Mapping[str, object], predeclaration["amendment"]).get("result_state")
        != "READY_NOT_EXECUTED"
        or holdout is None
        or set(holdout) != _STAGE09_HOLDOUT_FIELDS
        or holdout.get("file_sha256") != expected_holdout_nonconsumption_sha256
        or holdout.get("pinned_manifest_sha256") != OPAQUE_PUBLIC_MANIFEST_SHA256
        or isinstance(holdout.get("identities_loaded"), bool)
        or holdout.get("identities_loaded") != 0
        or holdout.get("manifest_loaded_as_metadata") is not False
        or isinstance(holdout.get("public_holdout_gameplay_events"), bool)
        or holdout.get("public_holdout_gameplay_events") != 0
        or holdout.get("status") != "SEALED_UNCONSUMED"
        or package is None
        or set(package)
        != {
            "candidate_set_recomputed",
            "file_sha256",
            "git_commit",
            "live_source_hashes_match",
            "package_only_passed",
            "policy_scan_covers_reachable_paths",
            "reachable_paths_recomputed",
            "receipt_sha256",
            "status",
        }
        or package.get("status") != "PASS"
        or package.get("package_only_passed") is not True
        or package.get("candidate_set_recomputed") is not True
        or package.get("reachable_paths_recomputed") is not True
        or package.get("live_source_hashes_match") is not True
        or package.get("policy_scan_covers_reachable_paths") is not True
        or development_scans is None
        or set(development_scans)
        != {
            "build_000_finding_count",
            "build_000_passed",
            "build_001_finding_count",
            "build_001_passed",
            "development_identity_count",
            "identifier_list_hash",
            "identifier_string_count",
            "identity_values_disclosed",
        }
        or development_scans.get("identifier_list_hash") != expected_development_identifier_sha256
        or isinstance(development_scans.get("development_identity_count"), bool)
        or development_scans.get("development_identity_count") != 12
        or isinstance(development_scans.get("identifier_string_count"), bool)
        or development_scans.get("identifier_string_count") != 24
        or development_scans.get("identity_values_disclosed") is not False
        or isinstance(development_scans.get("build_000_finding_count"), bool)
        or development_scans.get("build_000_finding_count") != 0
        or isinstance(development_scans.get("build_001_finding_count"), bool)
        or development_scans.get("build_001_finding_count") != 0
        or development_scans.get("build_000_passed") is not True
        or development_scans.get("build_001_passed") is not True
        or not isinstance(work_authority, Mapping)
        or set(work_authority)
        != {
            "cell_count",
            "cell_finalization_hashes",
            "cell_receipt_hashes",
            "matrix_hash",
        }
        or work_authority.get("cell_count") != 96
        or not isinstance(work_authority.get("cell_receipt_hashes"), list)
        or not isinstance(work_authority.get("cell_finalization_hashes"), list)
        or len(cast(list[object], work_authority["cell_receipt_hashes"])) != 96
        or len(cast(list[object], work_authority["cell_finalization_hashes"])) != 96
        or not all(
            isinstance(item, str)
            for item in (
                output.get("path"),
                output.get("artifact_core_hash"),
                output.get("sha256"),
                exposure.get("path"),
                exposure.get("sha256"),
                finalization.get("path"),
                finalization.get("terminal_finalization_hash"),
                finalization.get("sha256"),
            )
        )
    ):
        raise EvaluationError("Stage 09 terminal verification is not exact and passing")
    for label, value in {
        "Stage 09 output hash": output["sha256"],
        "Stage 09 output core hash": output["artifact_core_hash"],
        "Stage 09 exposure hash": exposure["sha256"],
        "Stage 09 finalization hash": finalization["sha256"],
        "Stage 09 finalization core hash": finalization["terminal_finalization_hash"],
        "Stage 09 prior authority hash": prior_authority["prior_authority_hash"],
    }.items():
        _sha256(value, field=label)
    _git_hash(
        predeclaration["effective_build_001_commit"],
        field="Stage 09 effective source commit",
    )
    _git_hash(
        predeclaration["effective_build_001_tree"],
        field="Stage 09 effective source tree",
    )
    for label, value in {
        "Stage 09 effective source hash": predeclaration["effective_build_001_source_sha256"],
        "Stage 09 effective matrix hash": predeclaration["effective_matrix_hash"],
        "Stage 09 work matrix hash": work_authority["matrix_hash"],
    }.items():
        _sha256(value, field=label)
    for label, item in {
        "Stage 09 package receipt file hash": package["file_sha256"],
        "Stage 09 package receipt self hash": package["receipt_sha256"],
    }.items():
        _sha256(item, field=label)
    _git_hash(package["git_commit"], field="Stage 09 package source commit")
    verifier = _stage09_terminal_verifier(source_root)
    try:
        reconstructed = verifier(
            source_root=source_root.resolve(),
            attempt_root=Path(attempt_root),
            output=Path(cast(str, output["path"])),
            exposure=Path(cast(str, exposure["path"])),
            expected_output_sha256=cast(str, output["sha256"]),
            expected_artifact_core_hash=cast(str, output["artifact_core_hash"]),
            expected_terminal_finalization_sha256=cast(str, finalization["sha256"]),
            expected_terminal_finalization_hash=cast(
                str, finalization["terminal_finalization_hash"]
            ),
        )
    except (OSError, RuntimeError, TypeError, ValueError, EvaluationError) as error:
        raise EvaluationError("Stage 09 terminal graph failed live verification") from error
    if reconstructed != receipt:
        raise EvaluationError("Stage 09 terminal verification differs from live graph")
    return {
        "file_sha256": expected_file_sha256,
        "output_artifact_core_hash": cast(str, output["artifact_core_hash"]),
        "output_file_sha256": cast(str, output["sha256"]),
        "path": path.resolve().as_posix(),
        "schema": _STAGE09_VERIFICATION_SCHEMA,
        "source_root": stage09_source_root,
        "status": cast(str, receipt.get("status", "")),
        "terminal_finalization_hash": cast(str, finalization["terminal_finalization_hash"]),
        "terminal_finalization_sha256": cast(str, finalization["sha256"]),
        "verification_hash": expected_verification_hash,
    }


def _package_only_summary(
    root: Path,
    path: Path,
    *,
    current_source: Mapping[str, JSONValue],
    projection: Mapping[str, str],
) -> tuple[IntegrityReceipt, dict[str, JSONValue]]:
    raw, receipt = _read_integrity(path, field="package-only integrity authority")
    body = receipt.body
    inputs = body.get("inputs")
    assurance = body.get("assurance_scope")
    git = body.get("git")
    source_hashes = body.get("source_hashes")
    reachable_hashes = body.get("reachable_policy_source_hashes")
    coverage = body.get("production_policy_static_coverage")
    license_summary = body.get("license_summary")
    candidate_projection = _package_candidate_projection(root)
    expected_binding = {
        "declaration": "disabled-package-only",
        "expected_sha256": None,
        "issue": "semantic public-manifest access is prohibited in this profile",
    }
    if (
        body.get("schema") != INTEGRITY_SCHEMA
        or body.get("passed") is not False
        or body.get("package_only_passed") is not True
        or body.get("integrity_scope") != "package-only-no-public-identifiers"
        or body.get("full_competition_integrity_status") != "NOT_EVALUATED_PUBLIC_IDENTIFIERS"
        or not _checks_clear(body)
        or not isinstance(inputs, Mapping)
        or inputs.get("manifest") is not None
        or inputs.get("manifest_sha256") is not None
        or inputs.get("run_state") is not None
        or inputs.get("public_identifier_count") != 0
        or isinstance(inputs.get("public_identifier_count"), bool)
        or inputs.get("public_identifier_mode") != "disabled-package-only"
        or inputs.get("manifest_binding") != expected_binding
        or inputs.get("candidate_mode") != "caller-supplied"
        or inputs.get("candidate_paths") != list(candidate_projection)
        or inputs.get("candidate_file_count") != len(candidate_projection)
        or isinstance(inputs.get("candidate_file_count"), bool)
        or inputs.get("reachable_policy_paths") != sorted(projection)
        or inputs.get("reachable_policy_file_count") != len(projection)
        or isinstance(inputs.get("reachable_policy_file_count"), bool)
        or not isinstance(reachable_hashes, Mapping)
        or dict(reachable_hashes) != dict(projection)
        or not isinstance(coverage, Mapping)
        or set(coverage)
        != {
            "algorithm",
            "entry_points",
            "entry_points_reached",
            "limitations",
            "policy_scan_covers_reachable_paths",
            "reachable_file_count",
            "reachable_paths_hashed",
            "status",
        }
        or coverage.get("algorithm") != "static-first-party-import-closure-v0.1"
        or coverage.get("status") != "PASS"
        or coverage.get("limitations") != _STATIC_LIMITATION
        or inputs.get("entry_points") != _PRODUCTION_POLICY_ENTRY_POINTS
        or coverage.get("entry_points") != _PRODUCTION_POLICY_ENTRY_POINTS
        or coverage.get("entry_points_reached") != coverage.get("entry_points")
        or coverage.get("policy_scan_covers_reachable_paths") is not True
        or coverage.get("reachable_paths_hashed") is not True
        or coverage.get("reachable_file_count") != len(projection)
        or isinstance(coverage.get("reachable_file_count"), bool)
        or len(projection) <= 0
        or not isinstance(assurance, Mapping)
        or assurance.get("kind") != "static-only"
        or assurance.get("public_identifier_scan")
        != "NOT_EVALUATED_PACKAGE_ONLY_NO_SEMANTIC_MANIFEST_ACCESS"
        or assurance.get("scanner_network_mode") != "offline-by-construction"
        or not isinstance(git, Mapping)
        or git.get("commit") != current_source.get("commit")
        or git.get("dirty_worktree") is not False
        or not isinstance(source_hashes, Mapping)
        or dict(source_hashes) != candidate_projection
        or any(source_hashes.get(label) != digest for label, digest in projection.items())
        or source_hashes.get(DEPENDENCY_LOCK_PATH)
        != sha256_file(root.resolve() / DEPENDENCY_LOCK_PATH)
        or source_hashes.get(COMPETITION_CONFIG_PATH)
        != sha256_file(root.resolve() / COMPETITION_CONFIG_PATH)
        or not isinstance(license_summary, Mapping)
        or license_summary.get("first_party_license_status") != "MIT-0"
        or license_summary.get("status") != "PASS"
        or any(
            isinstance(license_summary.get(name), bool) or license_summary.get(name) != 0
            for name in (
                "installed_version_mismatch_count",
                "not_evaluated_count",
                "unknown_or_missing_metadata_count",
            )
        )
    ):
        raise EvaluationError("package-only integrity authority is not clear and exact")
    return receipt, {
        "file_sha256": sha256_bytes(raw),
        "production_policy_static_coverage": "PASS",
        "receipt_sha256": receipt.receipt_sha256,
    }


def create_composite_integrity_authority(
    *,
    source_root: Path,
    package_only_path: Path,
    build_000_root: Path,
    expected_build_000_commit: str,
    expected_build_000_tree: str,
    expected_development_identifier_sha256: str,
    development_predeclaration_path: Path,
    expected_development_predeclaration_file_sha256: str,
    expected_development_predeclaration_core_hash: str,
    holdout_nonconsumption_path: Path,
    expected_holdout_nonconsumption_sha256: str,
    stage09_verification_path: Path,
    expected_stage09_verification_file_sha256: str,
    expected_stage09_verification_hash: str,
    expected_runtime_surface: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    """Construct the deterministic composite authority without manifest access."""

    root = source_root.resolve()
    source = _source_identity(root)
    if source.get("clean_worktree") is not True:
        raise EvaluationError("composite integrity requires a clean execution source")
    projection = reachable_policy_projection(root)
    package, package_summary = _package_only_summary(
        root,
        package_only_path,
        current_source=source,
        projection=projection,
    )
    runtime = runtime_surface_identity(root)
    if runtime.get("verified") is not True:
        raise EvaluationError("composite integrity runtime surface is not verified")
    if expected_runtime_surface is not None and runtime != dict(expected_runtime_surface):
        raise EvaluationError("composite integrity runtime differs from Stage 10 preflight")
    config = _competition_config_identity(root)
    lock_hash = sha256_file(root / DEPENDENCY_LOCK_PATH)
    identifiers, identifier_authority = _development_identifiers(
        development_predeclaration_path,
        expected_file_sha256=expected_development_predeclaration_file_sha256,
        expected_core_hash=expected_development_predeclaration_core_hash,
        expected_sha256=expected_development_identifier_sha256,
    )
    if (
        identifier_authority.get("build_000_commit") != expected_build_000_commit
        or identifier_authority.get("build_000_tree") != expected_build_000_tree
    ):
        raise EvaluationError("Build 000 scan source is not the frozen Stage 09 baseline")
    current_commit = _git_hash(source.get("commit"), field="execution source commit")
    current_tree = _git_hash(source.get("tree"), field="execution source tree")
    development_scans = {
        "build_000": _development_scan(
            build_000_root,
            identifiers=identifiers,
            expected_commit=expected_build_000_commit,
            expected_tree=expected_build_000_tree,
        ),
        "build_001": _development_scan(
            root,
            identifiers=identifiers,
            expected_commit=current_commit,
            expected_tree=current_tree,
        ),
    }
    holdout = _holdout_nonconsumption_summary(
        holdout_nonconsumption_path,
        expected_file_sha256=expected_holdout_nonconsumption_sha256,
    )
    stage09 = _stage09_verification_summary(
        stage09_verification_path,
        expected_file_sha256=expected_stage09_verification_file_sha256,
        expected_verification_hash=expected_stage09_verification_hash,
        source_root=root,
        expected_holdout_nonconsumption_sha256=expected_holdout_nonconsumption_sha256,
        expected_development_identifier_sha256=expected_development_identifier_sha256,
        expected_development_predeclaration_file_sha256=(
            expected_development_predeclaration_file_sha256
        ),
        expected_development_predeclaration_core_hash=(
            expected_development_predeclaration_core_hash
        ),
    )
    payload: dict[str, Any] = {
        "checks": {
            "current_package_only_clear": True,
            "development_identifier_scans_clear": True,
            "execution_config_lock_exact": True,
            "execution_runtime_exact": True,
            "execution_source_clean": True,
            "holdout_nonconsumption_exact": True,
            "stage09_terminal_verification_exact": True,
        },
        "assurance_limitation": _STAGE09_ASSURANCE_LIMITATION,
        "claim": "BOUNDED_STATIC_COMPETITION_INTEGRITY_WITH_OPAQUE_HOLDOUT",
        "development_identifier_authority": identifier_authority,
        "development_policy_scans": development_scans,
        "evidence_label": "synthetic",
        "full_public_integrity_status": "NOT_EVALUATED_BUILD_001_PUBLIC_IDENTIFIERS",
        "execution": {
            "competition_config": config,
            "dependency_lock": {
                "path": DEPENDENCY_LOCK_PATH,
                "sha256": lock_hash,
            },
            "runtime_surface": runtime,
            "source": {**source, "root": root.as_posix()},
        },
        "holdout_nonconsumption": holdout,
        "limitations": {
            "dynamic_or_native_containment": _STATIC_LIMITATION,
            "semantic_holdout_identifier_scan": "NOT_EVALUATED_SEALED_HOLDOUT_IDENTIFIERS",
        },
        "opaque_public_manifest_sha256": OPAQUE_PUBLIC_MANIFEST_SHA256,
        "package_only_authority": {
            "file_sha256": package_summary["file_sha256"],
            "integrity_scope": "package-only-no-public-identifiers",
            "path": package_only_path.resolve().as_posix(),
            "receipt_sha256": package.receipt_sha256,
            "schema": INTEGRITY_SCHEMA,
        },
        "production_policy_projection": {
            **_projection_summary(projection),
            "static_coverage_status": package_summary["production_policy_static_coverage"],
        },
        "schema": COMPOSITE_INTEGRITY_SCHEMA,
        "semantic_public_manifest_access": False,
        "stage09_terminal_verification": stage09,
        "status": "PASS",
    }
    return seal_object(payload, hash_field=COMPOSITE_INTEGRITY_HASH_FIELD)


def validate_composite_integrity_authority(
    path: Path,
    *,
    expected_file_sha256: str,
    expected_core_hash: str,
    source_root: Path,
) -> dict[str, Any]:
    """Rebuild an externally anchored composite authority from live bytes."""

    _sha256(expected_file_sha256, field="composite integrity file hash")
    _sha256(expected_core_hash, field="composite integrity core hash")
    try:
        raw = path.resolve().read_bytes()
        value: object = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise EvaluationError("composite integrity artifact is unreadable") from error
    if not isinstance(value, dict):
        raise EvaluationError("composite integrity artifact is not an object")
    document = cast(dict[str, Any], value)
    if (
        sha256_bytes(raw) != expected_file_sha256
        or canonical_json_bytes(document) != raw
        or document.get("schema") != COMPOSITE_INTEGRITY_SCHEMA
        or document.get(COMPOSITE_INTEGRITY_HASH_FIELD) != expected_core_hash
        or not verify_object_hash(document, hash_field=COMPOSITE_INTEGRITY_HASH_FIELD)
    ):
        raise EvaluationError("composite integrity artifact identity changed")
    package_binding = _mapping(
        document.get("package_only_authority"), field="package-only authority"
    )
    package_path_value = package_binding.get("path")
    development = _mapping(document.get("development_policy_scans"), field="development scans")
    build_000 = _mapping(development.get("build_000"), field="Build 000 development scan")
    build_000_source = _mapping(build_000.get("source"), field="Build 000 source")
    identifier_authority = _mapping(
        document.get("development_identifier_authority"),
        field="development identifier authority",
    )
    holdout = _mapping(document.get("holdout_nonconsumption"), field="holdout nonconsumption")
    stage09 = _mapping(document.get("stage09_terminal_verification"), field="Stage 09 verification")
    execution = _mapping(document.get("execution"), field="execution")
    current_source = _mapping(execution.get("source"), field="execution source")
    package_path_value = package_binding.get("path")
    values = (
        package_path_value,
        build_000_source.get("root"),
        build_000_source.get("commit"),
        build_000_source.get("tree"),
        identifier_authority.get("identifier_list_sha256"),
        identifier_authority.get("source_path"),
        identifier_authority.get("predeclaration_file_sha256"),
        identifier_authority.get("predeclaration_core_hash"),
        holdout.get("path"),
        holdout.get("file_sha256"),
        stage09.get("path"),
        stage09.get("file_sha256"),
        stage09.get("verification_hash"),
        current_source.get("commit"),
        current_source.get("tree"),
        current_source.get("root"),
    )
    if not all(isinstance(item, str) for item in values):
        raise EvaluationError("composite integrity authority paths are absent")
    if Path(cast(str, current_source["root"])).resolve() != source_root.resolve():
        raise EvaluationError("composite integrity execution source root changed")
    reconstructed = create_composite_integrity_authority(
        source_root=source_root,
        package_only_path=Path(cast(str, package_path_value)),
        build_000_root=Path(cast(str, build_000_source["root"])),
        expected_build_000_commit=cast(str, build_000_source["commit"]),
        expected_build_000_tree=cast(str, build_000_source["tree"]),
        expected_development_identifier_sha256=cast(
            str, identifier_authority["identifier_list_sha256"]
        ),
        development_predeclaration_path=Path(cast(str, identifier_authority["source_path"])),
        expected_development_predeclaration_file_sha256=cast(
            str, identifier_authority["predeclaration_file_sha256"]
        ),
        expected_development_predeclaration_core_hash=cast(
            str, identifier_authority["predeclaration_core_hash"]
        ),
        holdout_nonconsumption_path=Path(cast(str, holdout["path"])),
        expected_holdout_nonconsumption_sha256=cast(str, holdout["file_sha256"]),
        stage09_verification_path=Path(cast(str, stage09["path"])),
        expected_stage09_verification_file_sha256=cast(str, stage09["file_sha256"]),
        expected_stage09_verification_hash=cast(str, stage09["verification_hash"]),
    )
    if reconstructed != document:
        raise EvaluationError("composite integrity artifact does not match live authority")
    return document


def composite_binding(document: Mapping[str, Any], *, path: Path) -> dict[str, JSONValue]:
    """Return the safe external binding projected into parent/gate receipts."""

    if document.get("schema") != COMPOSITE_INTEGRITY_SCHEMA or not verify_object_hash(
        dict(document), hash_field=COMPOSITE_INTEGRITY_HASH_FIELD
    ):
        raise EvaluationError("composite integrity document is not sealed")
    return {
        "artifact_core_hash": cast(str, document[COMPOSITE_INTEGRITY_HASH_FIELD]),
        "file_sha256": sha256_file(path.resolve()),
        "schema": COMPOSITE_INTEGRITY_SCHEMA,
    }


def authority_callable_origins(source_root: Path) -> dict[str, str]:
    """Fail closed if an imported authority callable was rebound across trees."""

    root = source_root.resolve()
    package_candidates = _package_candidate_callable(root)
    stage09_verifier = _stage09_terminal_verifier(root)
    expected = {
        "canonical_json_bytes": (canonical_json_bytes, "src/arc3/evaluation/artifacts.py"),
        "discover_candidate_files": (
            discover_candidate_files,
            "src/arc3/integrity/scanner.py",
        ),
        "discover_policy_files": (discover_policy_files, "src/arc3/integrity/scanner.py"),
        "discover_reachable_policy_files": (
            discover_reachable_policy_files,
            "src/arc3/integrity/scanner.py",
        ),
        "scan_policy_files": (scan_policy_files, "src/arc3/integrity/scanner.py"),
        "seal_object": (seal_object, "src/arc3/evaluation/artifacts.py"),
        "sha256_bytes": (sha256_bytes, "src/arc3/evaluation/artifacts.py"),
        "sha256_file": (sha256_file, "src/arc3/evaluation/artifacts.py"),
        "validate_predeclaration_bytes": (
            validate_predeclaration_bytes,
            "src/arc3/evaluation/development_recovery.py",
        ),
        "verify_object_hash": (verify_object_hash, "src/arc3/evaluation/artifacts.py"),
        "package_only_candidate_files": (
            package_candidates,
            "scripts/check_competition_integrity.py",
        ),
        "verify_complete_terminal": (
            stage09_verifier,
            "scripts/measure_development_recovery.py",
        ),
    }
    origins: dict[str, str] = {}
    for name, (function, relative) in expected.items():
        code = getattr(function, "__code__", None)
        expected_path = (root / relative).resolve()
        if code is None or Path(code.co_filename).resolve() != expected_path:
            raise EvaluationError(f"composite integrity callable origin changed: {name}")
        origins[name] = relative
    return origins


__all__ = [
    "COMPETITION_CONFIG_PATH",
    "COMPOSITE_INTEGRITY_HASH_FIELD",
    "COMPOSITE_INTEGRITY_SCHEMA",
    "DEPENDENCY_LOCK_PATH",
    "OPAQUE_PUBLIC_MANIFEST_SHA256",
    "UPSTREAM_LOCK_PATH",
    "authority_callable_origins",
    "composite_binding",
    "create_composite_integrity_authority",
    "reachable_policy_projection",
    "runtime_surface_identity",
    "validate_composite_integrity_authority",
]
