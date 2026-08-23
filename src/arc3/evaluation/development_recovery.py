"""Frozen Stage 09 local-public development-recovery protocol.

This is a pure declaration/validation layer.  It never imports an environment
adapter and cannot open a game.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, cast

from arc3.errors import EvaluationError
from arc3.evaluation.artifacts import canonical_json_bytes, sha256_bytes, verify_object_hash

PREDECLARATION_SCHEMA = "arc3.build-001.stage-09-predeclaration.v0.2"
PREDECLARATION_AMENDMENT_SCHEMA = "arc3.build-001.stage-09-predeclaration-amendment.v0.1"
PREFLIGHT_SCHEMA = "arc3.build-001.stage-09-preflight.v0.5"
WORKER_SPEC_SCHEMA = "arc3.build-001.stage-09-worker-spec.v0.4"
CELL_RECEIPT_SCHEMA = "arc3.build-001.stage-09-cell-receipt.v0.4"
CELL_FINALIZATION_SCHEMA = "arc3.build-001.stage-09-cell-finalization.v0.1"
MECHANISM_PROVENANCE_SCHEMA = "arc3.build-001.stage-09-mechanism-provenance.v0.1"
AGGREGATE_SCHEMA = "arc3.build-001.stage-09-aggregate.v0.4"
HARNESS_SOURCE_BINDING_SCHEMA = "arc3.build-001.stage-09-harness-source-binding.v0.1"
HARNESS_SOURCE_OBSERVATION_SCHEMA = "arc3.build-001.stage-09-harness-source-observation.v0.1"
RUNTIME_ENVIRONMENT_SCHEMA = "arc3.build-001.stage-09-runtime-environment.v0.2"
RUNTIME_ENVIRONMENT_OBSERVATION_SCHEMA = (
    "arc3.build-001.stage-09-runtime-environment-observation.v0.2"
)
PRIOR_AUTHORITY_SCHEMA = "arc3.build-001.stage-09-prior-authority.v0.2"
ENVIRONMENT_CACHE_SCHEMA = "arc3.build-001.stage-09-environment-cache.v0.1"
HARNESS_SOURCE_PATHS = (
    "scripts/_stage09_supervisor_bootstrap.py",
    "scripts/measure_development_recovery.py",
    "scripts/_stage09_development_worker.py",
    "src/arc3/evaluation/development_recovery.py",
)
PREDECLARATION_CORE_HASH = "sha256:b32f91fa228a7f1f2c2bbfee23e8fafc3a9affc18f9b0d3cbf9e050b0e498f3c"
PREDECLARATION_FILE_SHA256 = (
    "sha256:dce14e30d47aff7ac99551ad462c9202113dcd44c591dacd410b86363ddad348"
)
ORIGINAL_MATRIX_HASH = "sha256:5c4c1d4a1d23bd68822c91a5c82dcbbabad7d0ca9ea0ab298a2df37e149b868b"

ORIGINAL_BUILD_001_COMMIT = "2e78c258cfbee8be62462f61ed08ad04c00a8934"
ORIGINAL_BUILD_001_TREE = "4145356c116944bbd7c0c412771de9179ba22efe"
ORIGINAL_BUILD_001_SOURCE_SHA256 = (
    "sha256:4dc8b7d7802be6b97427e12fe550bd4a6832ef30f6acdc4b509294a5a1add7f1"
)
FROZEN_BUILD_001_COMMIT = "d6d4bac1e33c9837856c08abcee61bcb14afd34e"
FROZEN_BUILD_001_TREE = "dd8e82e4b34337a208110929e3f5f8079d1e0a18"
FROZEN_BUILD_001_SOURCE_SHA256 = (
    "sha256:8f0de1a9c2c88761951ba2bcd69f2612bedfa0cc4226f44f1ed272b54b9023a8"
)
BUILD_001_PACKAGE_INTEGRITY_FILE_SHA256 = (
    "sha256:173c0a6c3aee154df67920227e3b5303c59682186a2254a220e24dd5589269fe"
)
BUILD_001_PACKAGE_INTEGRITY_RECEIPT_SHA256 = (
    "sha256:3e29edd69d7999760c53a80de474d701f9124faed73ccc1b9047adbf9a766702"
)
PREDECLARATION_AMENDMENT_CORE_HASH = (
    "sha256:36104da8f7ea6532ab1ea7cf6f8df16760d1236f8f551d7bef2239f7d1ab93a4"
)
PREDECLARATION_AMENDMENT_FILE_SHA256 = (
    "sha256:137532b196ffcbd6bbeb07c8ca5ef716c0987f04467663efb6ce1da8508d3084"
)
FROZEN_BUILD_000_COMMIT = "90ecf7267d5bb23d751d6f7ce3e8aa75f2f1a130"
FROZEN_BUILD_000_TREE = "0cf6e00b2fcc399e7a99a62c20e91bb84d485f13"
FROZEN_BUILD_000_SOURCE_SHA256 = (
    "sha256:2112c390ac62432270a98fdcf6067b02c968b4139d3ee17c68bcd1d21842109c"
)
PUBLIC_PARTITION_MANIFEST_SHA256 = (
    "sha256:682d5891c2aface54803d9bd1173c55ed21e89856e13b8a478fb9276ee963f2f"
)
UPSTREAM_LOCK_SHA256 = "sha256:67e1d937e213bbcc25783784d04c4fa349b85dc09b94855256916ca6b96e808a"
STAGE08_RESULT_FILE_SHA256 = (
    "sha256:7c39fa77de24bd1925d9dbd489d583118f96d4b7fe860678607f485506ad39d4"
)
STAGE08_RESULT_CORE_HASH = "sha256:e3e078092318882f2c32887c6a223c0396938abba0ca7b30fdcde0eb5b15383f"
STAGE08_EXPOSURE_SHA256 = "sha256:be73b837805a66ed172b20573aa31c41fe6ba16ced4d471929b6018e22a5d52e"
BUILD_000_INTEGRITY_FILE_SHA256 = (
    "sha256:b63ea29913a042930b01ace640c283dd0febce3597b637c3d8433fc981579349"
)
BUILD_000_INTEGRITY_RECEIPT_SHA256 = (
    "sha256:3545f69c786ed8268d2e3948769a976db920f2b2e79851cb6bb5c6e922601643"
)
HOLDOUT_NONCONSUMPTION_FILE_SHA256 = (
    "sha256:0134c9e5b7acea716f790088cb59109eded7857ce83fda004ea1b88be2eb92ac"
)

SEEDS = (7, 11)
MAX_ACTIONS = 80
MAX_RESETS = 8
WORKER_WALL_SECONDS = 120.0
OVERALL_ACTIVE_WALL_SECONDS = 14_400.0
EXPECTED_CELL_COUNT = 96
CELL_ADMISSION_CHARGE_NS = int(OVERALL_ACTIVE_WALL_SECONDS * 1_000_000_000 / EXPECTED_CELL_COUNT)
NORMAL_TERMINATION_DEFINITION = "cell_status_success_only"
GENERIC_MECHANISM_CATEGORIES = frozenset({"hypothesis", "planning", "policy", "world-model"})


def _is_sha256(value: object) -> bool:
    return bool(
        isinstance(value, str)
        and value.startswith("sha256:")
        and len(value) == 71
        and all(character in "0123456789abcdef" for character in value[7:])
    )


def _is_git_oid(value: object) -> bool:
    return bool(
        isinstance(value, str)
        and len(value) == 40
        and all(character in "0123456789abcdef" for character in value)
    )


def validate_harness_source_binding(value: Mapping[str, object]) -> dict[str, object]:
    """Validate the non-circular launch-time identity of the Stage 09 harness."""

    binding = dict(value)
    if set(binding) != {"binding_hash", "files", "git_commit", "git_tree", "schema"}:
        raise EvaluationError("Stage 09 harness source binding fields changed")
    if binding.get("schema") != HARNESS_SOURCE_BINDING_SCHEMA or not verify_object_hash(
        binding, hash_field="binding_hash"
    ):
        raise EvaluationError("Stage 09 harness source binding hash/schema is invalid")
    if not _is_git_oid(binding.get("git_commit")) or not _is_git_oid(binding.get("git_tree")):
        raise EvaluationError("Stage 09 harness source Git identity is malformed")
    files = binding.get("files")
    if not isinstance(files, dict) or set(files) != set(HARNESS_SOURCE_PATHS):
        raise EvaluationError("Stage 09 harness source file set changed")
    if not all(_is_sha256(files[path]) for path in HARNESS_SOURCE_PATHS):
        raise EvaluationError("Stage 09 harness source file hash is malformed")
    return binding


def validate_harness_source_observation(
    value: Mapping[str, object], *, expected: Mapping[str, object]
) -> dict[str, object]:
    """Validate one sealed observation against its external launch binding."""

    binding = validate_harness_source_binding(expected)
    observation = dict(value)
    required = {
        "binding_hash",
        "branch",
        "dirty_worktree",
        "files",
        "git_commit",
        "git_tree",
        "observation_hash",
        "passed",
        "predicates",
        "root",
        "schema",
    }
    if set(observation) != required:
        raise EvaluationError("Stage 09 harness source observation fields changed")
    if observation.get("schema") != HARNESS_SOURCE_OBSERVATION_SCHEMA or not verify_object_hash(
        observation, hash_field="observation_hash"
    ):
        raise EvaluationError("Stage 09 harness source observation hash/schema is invalid")
    predicates = observation.get("predicates")
    if not isinstance(predicates, dict) or set(predicates) != {
        "clean",
        "commit",
        "detached",
        "files",
        "root",
        "tree",
    }:
        raise EvaluationError("Stage 09 harness source predicates changed")
    predicate_pass = all(item is True for item in predicates.values())
    if observation.get("passed") is not predicate_pass:
        raise EvaluationError("Stage 09 harness source predicate summary changed")
    if (
        observation.get("binding_hash") != binding["binding_hash"]
        or observation.get("git_commit") != binding["git_commit"]
        or observation.get("git_tree") != binding["git_tree"]
        or observation.get("files") != binding["files"]
    ) and predicate_pass:
        raise EvaluationError("Stage 09 passing harness source observation changed")
    if not isinstance(observation.get("root"), str):
        raise EvaluationError("Stage 09 harness source root is absent")
    return observation


def harness_source_stable(
    before: Mapping[str, object],
    after: Mapping[str, object],
    *,
    expected: Mapping[str, object],
) -> bool:
    """Return whether two exact, passing launch-source observations agree."""

    left = validate_harness_source_observation(before, expected=expected)
    right = validate_harness_source_observation(after, expected=expected)
    fields = ("binding_hash", "branch", "dirty_worktree", "files", "git_commit", "git_tree", "root")
    return bool(
        left["passed"] is True
        and right["passed"] is True
        and all(left[field] == right[field] for field in fields)
    )


def validate_runtime_environment_binding(value: Mapping[str, object]) -> dict[str, object]:
    """Validate the pinned interpreter, SDK, and scorer declaration."""

    binding = dict(value)
    required = {
        "bootstrap_boundary",
        "cache_tag",
        "critical_versions",
        "distributions",
        "executable",
        "executable_sha256",
        "implementation",
        "installed_distribution_inventory",
        "python_version",
        "python_base",
        "runtime_binding_hash",
        "schema",
        "scorer",
        "sdk_import_probe",
        "sdk_probe_network_denied",
        "upstream_lock_sha256",
        "uv_lock_sha256",
    }
    if set(binding) != required:
        raise EvaluationError("Stage 09 runtime environment binding fields changed")
    if binding.get("schema") != RUNTIME_ENVIRONMENT_SCHEMA or not verify_object_hash(
        binding, hash_field="runtime_binding_hash"
    ):
        raise EvaluationError("Stage 09 runtime environment binding hash/schema is invalid")
    if not all(
        _is_sha256(binding.get(field))
        for field in ("executable_sha256", "upstream_lock_sha256", "uv_lock_sha256")
    ):
        raise EvaluationError("Stage 09 runtime environment hash is malformed")
    if binding.get("bootstrap_boundary") != {
        "residual": None,
        "supervisor_pre_first_party_runtime_validation": True,
        "worker_pre_first_party_runtime_validation": True,
    }:
        raise EvaluationError("Stage 09 runtime bootstrap boundary changed")
    distributions = binding.get("distributions")
    critical_versions = binding.get("critical_versions")
    scorer = binding.get("scorer")
    if not isinstance(distributions, dict) or set(distributions) != {
        "arc-agi",
        "arcengine",
        "numpy",
        "pydantic",
        "pydantic-core",
    }:
        raise EvaluationError("Stage 09 runtime distribution set changed")
    for distribution in distributions.values():
        if (
            not isinstance(distribution, dict)
            or set(distribution)
            != {
                "file_bytes",
                "file_count",
                "files_sha256",
                "hash_entry_count",
                "installed_files_sha256",
                "record_entry_count",
                "record_sha256",
                "record_verification_passed",
                "verified_hash_entry_count",
                "version",
            }
            or not _is_sha256(distribution.get("files_sha256"))
            or not _is_sha256(distribution.get("installed_files_sha256"))
            or not _is_sha256(distribution.get("record_sha256"))
            or any(
                isinstance(distribution.get(field), bool)
                or not isinstance(distribution.get(field), int)
                or cast(int, distribution[field]) < 0
                for field in (
                    "file_bytes",
                    "file_count",
                    "hash_entry_count",
                    "record_entry_count",
                    "verified_hash_entry_count",
                )
            )
            or distribution.get("record_verification_passed") is not True
            or distribution.get("verified_hash_entry_count") != distribution.get("hash_entry_count")
            or not isinstance(distribution.get("version"), str)
        ):
            raise EvaluationError("Stage 09 runtime distribution identity is malformed")
    inventory = binding.get("installed_distribution_inventory")
    if not isinstance(inventory, dict) or set(inventory) != {
        "distribution_count",
        "hash_entry_count",
        "installed_files_sha256",
        "names_and_versions",
        "record_verification_passed",
        "records_sha256",
        "verified_hash_entry_count",
    }:
        raise EvaluationError("Stage 09 installed distribution inventory changed")
    names = inventory.get("names_and_versions")
    if (
        isinstance(inventory.get("distribution_count"), bool)
        or not isinstance(inventory.get("distribution_count"), int)
        or not isinstance(names, list)
        or inventory.get("distribution_count") != len(names)
        or not _is_sha256(inventory.get("installed_files_sha256"))
        or not _is_sha256(inventory.get("records_sha256"))
        or any(
            isinstance(inventory.get(field), bool)
            or not isinstance(inventory.get(field), int)
            or cast(int, inventory[field]) < 0
            for field in ("hash_entry_count", "verified_hash_entry_count")
        )
        or inventory.get("record_verification_passed") is not True
        or inventory.get("verified_hash_entry_count") != inventory.get("hash_entry_count")
        or any(
            not isinstance(item, dict)
            or set(item) != {"name", "version"}
            or not all(isinstance(item.get(field), str) and item.get(field) for field in item)
            for item in names
        )
        or names
        != sorted(
            names,
            key=lambda item: (
                cast(dict[str, str], item)["name"],
                cast(dict[str, str], item)["version"],
            ),
        )
        or len({cast(dict[str, str], item)["name"] for item in names}) != len(names)
    ):
        raise EvaluationError("Stage 09 installed distribution inventory is malformed")
    python_base = binding.get("python_base")
    if not isinstance(python_base, dict) or set(python_base) != {
        "base_executable",
        "base_executable_sha256",
        "base_prefix",
        "dll_file_bytes",
        "dll_file_count",
        "dll_files_sha256",
        "stdlib",
    }:
        raise EvaluationError("Stage 09 Python base identity changed")
    stdlib = python_base.get("stdlib")
    if (
        not isinstance(stdlib, dict)
        or set(stdlib) != {"file_bytes", "file_count", "files_sha256", "root"}
        or not all(
            _is_sha256(item)
            for item in (
                python_base.get("base_executable_sha256"),
                python_base.get("dll_files_sha256"),
                stdlib.get("files_sha256"),
            )
        )
        or any(
            isinstance(item, bool) or not isinstance(item, int) or item < 0
            for item in (
                python_base.get("dll_file_bytes"),
                python_base.get("dll_file_count"),
                stdlib.get("file_bytes"),
                stdlib.get("file_count"),
            )
        )
        or not all(
            isinstance(item, str) and item
            for item in (
                python_base.get("base_executable"),
                python_base.get("base_prefix"),
                stdlib.get("root"),
            )
        )
    ):
        raise EvaluationError("Stage 09 Python base identity is malformed")
    if (
        not isinstance(critical_versions, dict)
        or set(critical_versions)
        != {
            "annotated-types",
            "numpy",
            "pydantic",
            "pydantic-core",
            "typing-extensions",
            "typing-inspection",
        }
        or not all(isinstance(version, str) for version in critical_versions.values())
    ):
        raise EvaluationError("Stage 09 critical runtime version set changed")
    if (
        binding.get("sdk_import_probe") is not True
        or binding.get("sdk_probe_network_denied") is not True
    ):
        raise EvaluationError("Stage 09 official SDK import requirement changed")
    if (
        not isinstance(scorer, dict)
        or set(scorer) != {"distribution", "module", "sha256", "source_version"}
        or not _is_sha256(scorer.get("sha256"))
    ):
        raise EvaluationError("Stage 09 scorer identity is malformed")
    return binding


def validate_runtime_environment_observation(
    value: Mapping[str, object], *, expected: Mapping[str, object]
) -> dict[str, object]:
    """Validate one runtime observation against the exact pinned declaration."""

    binding = validate_runtime_environment_binding(expected)
    observation = dict(value)
    if set(observation) != {
        "actual",
        "binding_hash",
        "observation_hash",
        "passed",
        "predicates",
        "schema",
    }:
        raise EvaluationError("Stage 09 runtime environment observation fields changed")
    if observation.get(
        "schema"
    ) != RUNTIME_ENVIRONMENT_OBSERVATION_SCHEMA or not verify_object_hash(
        observation, hash_field="observation_hash"
    ):
        raise EvaluationError("Stage 09 runtime environment observation hash/schema is invalid")
    predicates = observation.get("predicates")
    if not isinstance(predicates, dict) or set(predicates) != {
        "bootstrap_boundary",
        "cache_tag",
        "critical_versions",
        "distributions",
        "executable",
        "executable_sha256",
        "implementation",
        "installed_distribution_inventory",
        "python_version",
        "python_base",
        "scorer",
        "sdk_import_probe",
        "sdk_probe_network_denied",
        "upstream_lock_sha256",
        "uv_lock_sha256",
    }:
        raise EvaluationError("Stage 09 runtime environment predicates changed")
    passed = all(item is True for item in predicates.values())
    if observation.get("passed") is not passed:
        raise EvaluationError("Stage 09 runtime environment predicate summary changed")
    if observation.get("binding_hash") != binding["runtime_binding_hash"]:
        raise EvaluationError("Stage 09 runtime environment binding changed")
    actual = observation.get("actual")
    if not isinstance(actual, dict) or set(actual) != set(predicates):
        raise EvaluationError("Stage 09 runtime environment observation is absent")
    expected_actual = {
        key: binding[key] for key in binding if key not in {"runtime_binding_hash", "schema"}
    }
    if observation.get("passed") is True and actual != expected_actual:
        raise EvaluationError("Stage 09 passing runtime environment identity changed")
    return observation


def runtime_environment_stable(
    before: Mapping[str, object],
    after: Mapping[str, object],
    *,
    expected: Mapping[str, object],
) -> bool:
    """Return whether the interpreter, SDK, and scorer stayed exactly pinned."""

    left = validate_runtime_environment_observation(before, expected=expected)
    right = validate_runtime_environment_observation(after, expected=expected)
    return bool(
        left["passed"] is True
        and right["passed"] is True
        and left["actual"] == right["actual"]
        and left["binding_hash"] == right["binding_hash"]
    )


def validate_prior_authority_observation(value: Mapping[str, object]) -> dict[str, object]:
    """Validate package-only Build 001 plus development-only static authority."""

    observation = dict(value)
    if set(observation) != {
        "assurance_scope",
        "authority_hash",
        "full_public_integrity_status",
        "holdout",
        "integrity",
        "passed",
        "predicates",
        "schema",
    }:
        raise EvaluationError("Stage 09 prior-authority fields changed")
    if observation.get("schema") != PRIOR_AUTHORITY_SCHEMA or not verify_object_hash(
        observation, hash_field="authority_hash"
    ):
        raise EvaluationError("Stage 09 prior-authority hash/schema is invalid")
    predicates = observation.get("predicates")
    if not isinstance(predicates, dict) or set(predicates) != {
        "build_000_development_scan",
        "build_000_full_integrity",
        "build_001_development_scan",
        "build_001_package_integrity",
        "development_identity",
        "holdout_file_hash",
        "holdout_manifest_hash",
        "holdout_nonconsumption",
    }:
        raise EvaluationError("Stage 09 prior-authority predicates changed")
    if observation.get("passed") is not all(item is True for item in predicates.values()):
        raise EvaluationError("Stage 09 prior-authority predicate summary changed")
    assurance = observation.get("assurance_scope")
    if assurance != {
        "build_000": "historic-full-public-integrity-receipt",
        "build_001": "package-only-plus-frozen-development-identifiers",
        "limitations": (
            "Static-only composite; runtime dynamic-import and native-extension "
            "containment are not proven."
        ),
    } or observation.get("full_public_integrity_status") != (
        "NOT_EVALUATED_BUILD_001_PUBLIC_IDENTIFIERS"
    ):
        raise EvaluationError("Stage 09 prior-authority assurance scope changed")
    integrity = observation.get("integrity")
    if not isinstance(integrity, dict) or set(integrity) != {
        "build_000_full",
        "build_001_package_only",
        "development_scans",
    }:
        raise EvaluationError("Stage 09 prior integrity receipt set changed")
    build_000 = integrity.get("build_000_full")
    if (
        not isinstance(build_000, dict)
        or set(build_000) != {"file_sha256", "git_commit", "path", "receipt_sha256"}
        or not _is_sha256(build_000.get("file_sha256"))
        or not _is_sha256(build_000.get("receipt_sha256"))
        or not _is_git_oid(build_000.get("git_commit"))
        or not isinstance(build_000.get("path"), str)
    ):
        raise EvaluationError("Stage 09 Build 000 integrity identity is malformed")
    build_001 = integrity.get("build_001_package_only")
    package_fields = {
        "assurance_limitation",
        "candidate_file_count",
        "candidate_set_recomputed",
        "entry_point_count",
        "entry_points_reached",
        "file_sha256",
        "full_competition_integrity_status",
        "git_commit",
        "integrity_scope",
        "license_inventory_passed",
        "live_source_hashes_match",
        "package_only_passed",
        "path",
        "policy_scan_covers_reachable_paths",
        "public_identifier_mode",
        "public_identifier_scan",
        "reachable_file_count",
        "reachable_paths_hashed",
        "reachable_paths_recomputed",
        "reachable_source_hashes_sha256",
        "receipt_sha256",
        "status",
    }
    if (
        not isinstance(build_001, dict)
        or set(build_001) != package_fields
        or not _is_sha256(build_001.get("file_sha256"))
        or not _is_sha256(build_001.get("receipt_sha256"))
        or not _is_sha256(build_001.get("reachable_source_hashes_sha256"))
        or not _is_git_oid(build_001.get("git_commit"))
        or not isinstance(build_001.get("path"), str)
        or isinstance(build_001.get("candidate_file_count"), bool)
        or not isinstance(build_001.get("candidate_file_count"), int)
        or cast(int, build_001.get("candidate_file_count")) <= 0
        or isinstance(build_001.get("reachable_file_count"), bool)
        or not isinstance(build_001.get("reachable_file_count"), int)
        or cast(int, build_001.get("reachable_file_count")) <= 0
        or build_001.get("entry_point_count") != build_001.get("entry_points_reached")
        or isinstance(build_001.get("entry_point_count"), bool)
        or not isinstance(build_001.get("entry_point_count"), int)
        or cast(int, build_001.get("entry_point_count")) <= 0
    ):
        raise EvaluationError("Stage 09 Build 001 package identity is malformed")
    scans = integrity.get("development_scans")
    if not isinstance(scans, dict) or set(scans) != {
        "build_000",
        "build_001",
        "development_identity_count",
        "identifier_list_hash",
        "identifier_string_count",
        "identity_values_disclosed",
        "limitations",
        "scope",
    }:
        raise EvaluationError("Stage 09 development integrity projection changed")
    for name in ("build_000", "build_001"):
        scan = scans.get(name)
        if (
            not isinstance(scan, dict)
            or set(scan) != {"finding_count", "findings", "passed", "policy_file_count"}
            or isinstance(scan.get("finding_count"), bool)
            or not isinstance(scan.get("finding_count"), int)
            or cast(int, scan.get("finding_count")) < 0
            or not isinstance(scan.get("findings"), list)
            or len(cast(list[object], scan.get("findings"))) != scan.get("finding_count")
            or scan.get("passed") is not (scan.get("finding_count") == 0)
            or isinstance(scan.get("policy_file_count"), bool)
            or not isinstance(scan.get("policy_file_count"), int)
            or cast(int, scan.get("policy_file_count")) <= 0
        ):
            raise EvaluationError("Stage 09 development integrity scan is malformed")
    if (
        scans.get("development_identity_count") != len(DEVELOPMENT_GAMES)
        or scans.get("identifier_string_count") != len(DEVELOPMENT_GAMES) * 2
        or scans.get("identifier_list_hash") != development_identifier_list_hash()
        or scans.get("identity_values_disclosed") is not False
        or scans.get("scope") != "frozen-exposed-development-game-id-and-stable-name-pairs"
        or scans.get("limitations")
        != "Direct static scan only; dynamic-import and native-extension behavior is not proven."
    ):
        raise EvaluationError("Stage 09 development identifier authority changed")
    holdout = observation.get("holdout")
    if (
        not isinstance(holdout, dict)
        or set(holdout)
        != {
            "file_sha256",
            "identities_loaded",
            "manifest_loaded_as_metadata",
            "path",
            "pinned_manifest_sha256",
            "public_holdout_gameplay_events",
            "receipt_confirms_manifest_sha256",
            "status",
        }
        or not _is_sha256(holdout.get("file_sha256"))
        or holdout.get("identities_loaded") != 0
        or holdout.get("manifest_loaded_as_metadata") is not False
        or holdout.get("public_holdout_gameplay_events") != 0
        or holdout.get("pinned_manifest_sha256") != PUBLIC_PARTITION_MANIFEST_SHA256
        or holdout.get("receipt_confirms_manifest_sha256") != PUBLIC_PARTITION_MANIFEST_SHA256
        or not isinstance(holdout.get("path"), str)
        or holdout.get("status") not in {"SEALED_UNCONSUMED", "UNVERIFIED"}
    ):
        raise EvaluationError("Stage 09 sealed-holdout authority is malformed")
    if observation.get("passed") is True:
        if (
            build_000.get("file_sha256") != BUILD_000_INTEGRITY_FILE_SHA256
            or build_000.get("git_commit") != FROZEN_BUILD_000_COMMIT
            or build_000.get("receipt_sha256") != BUILD_000_INTEGRITY_RECEIPT_SHA256
            or build_001.get("git_commit") != FROZEN_BUILD_001_COMMIT
            or build_001.get("file_sha256") != BUILD_001_PACKAGE_INTEGRITY_FILE_SHA256
            or build_001.get("receipt_sha256") != BUILD_001_PACKAGE_INTEGRITY_RECEIPT_SHA256
            or build_001.get("package_only_passed") is not True
            or build_001.get("status") != "PASS"
            or build_001.get("integrity_scope") != "package-only-no-public-identifiers"
            or build_001.get("full_competition_integrity_status")
            != "NOT_EVALUATED_PUBLIC_IDENTIFIERS"
            or build_001.get("public_identifier_mode") != "disabled-package-only"
            or build_001.get("public_identifier_scan")
            != "NOT_EVALUATED_PACKAGE_ONLY_NO_SEMANTIC_MANIFEST_ACCESS"
            or build_001.get("policy_scan_covers_reachable_paths") is not True
            or build_001.get("candidate_set_recomputed") is not True
            or build_001.get("license_inventory_passed") is not True
            or build_001.get("live_source_hashes_match") is not True
            or build_001.get("reachable_paths_hashed") is not True
            or build_001.get("reachable_paths_recomputed") is not True
            or build_001.get("assurance_limitation")
            != (
                "Static first-party import reachability does not prove runtime dynamic-import "
                "or native-extension containment."
            )
            or cast(dict[str, object], scans["build_000"]).get("passed") is not True
            or cast(dict[str, object], scans["build_001"]).get("passed") is not True
            or holdout.get("file_sha256") != HOLDOUT_NONCONSUMPTION_FILE_SHA256
            or holdout.get("status") != "SEALED_UNCONSUMED"
        ):
            raise EvaluationError("Stage 09 prior integrity receipt identity changed")
    return observation


def prior_authority_stable(before: Mapping[str, object], after: Mapping[str, object]) -> bool:
    """Return whether authoritative integrity/non-consumption receipts stayed exact."""

    left = validate_prior_authority_observation(before)
    right = validate_prior_authority_observation(after)
    return bool(
        left["passed"] is True
        and right["passed"] is True
        and left["authority_hash"] == right["authority_hash"]
    )


def validate_environment_cache_observation(value: Mapping[str, object]) -> dict[str, object]:
    """Validate an opaque full-cache identity without exposing game identifiers."""

    observation = dict(value)
    if set(observation) != {
        "actual",
        "cache_identity_hash",
        "expected",
        "holdout_identities_loaded",
        "passed",
        "predicates",
        "root",
        "schema",
    }:
        raise EvaluationError("Stage 09 environment-cache fields changed")
    if observation.get("schema") != ENVIRONMENT_CACHE_SCHEMA or not verify_object_hash(
        observation, hash_field="cache_identity_hash"
    ):
        raise EvaluationError("Stage 09 environment-cache hash/schema is invalid")
    actual = observation.get("actual")
    expected = observation.get("expected")
    predicates = observation.get("predicates")
    fields = {
        "aggregate_sha256",
        "directory_count",
        "entry_count",
        "recursive_bytes",
        "recursive_file_count",
        "root_file_count",
        "top_level_directory_count",
    }
    if (
        not isinstance(actual, dict)
        or not isinstance(expected, dict)
        or set(actual) != fields
        or set(expected) != fields
        or not _is_sha256(actual.get("aggregate_sha256"))
        or not _is_sha256(expected.get("aggregate_sha256"))
        or any(
            isinstance(item, bool) or not isinstance(item, int) or item < 0
            for key, item in actual.items()
            if key != "aggregate_sha256"
        )
        or any(
            isinstance(item, bool) or not isinstance(item, int) or item < 0
            for key, item in expected.items()
            if key != "aggregate_sha256"
        )
    ):
        raise EvaluationError("Stage 09 environment-cache inventory is malformed")
    if not isinstance(predicates, dict) or set(predicates) != fields | {
        "root_present",
        "symlinks_absent",
    }:
        raise EvaluationError("Stage 09 environment-cache predicates changed")
    if observation.get("passed") is not all(item is True for item in predicates.values()):
        raise EvaluationError("Stage 09 environment-cache predicate summary changed")
    if observation.get("holdout_identities_loaded") != 0 or not isinstance(
        observation.get("root"), str
    ):
        raise EvaluationError("Stage 09 environment-cache boundary is malformed")
    if observation.get("passed") is True and actual != expected:
        raise EvaluationError("Stage 09 passing environment-cache inventory changed")
    return observation


def environment_cache_stable(before: Mapping[str, object], after: Mapping[str, object]) -> bool:
    """Return whether the opaque full public cache stayed exactly pinned."""

    left = validate_environment_cache_observation(before)
    right = validate_environment_cache_observation(after)
    return bool(
        left["passed"] is True
        and right["passed"] is True
        and left["cache_identity_hash"] == right["cache_identity_hash"]
    )


@dataclass(frozen=True, slots=True)
class DevelopmentGame:
    game_id: str
    stable_name: str
    asset_sha256: str

    @property
    def version(self) -> str:
        prefix, separator, version = self.game_id.partition("-")
        if not separator or prefix != self.stable_name or not version:
            raise EvaluationError("Stage 09 development game identity is malformed")
        return version

    def to_dict(self) -> dict[str, str]:
        return {
            "asset_sha256": self.asset_sha256,
            "game_id": self.game_id,
            "stable_name": self.stable_name,
        }


DEVELOPMENT_GAMES = (
    DevelopmentGame(
        "tr87-cd924810",
        "tr87",
        "sha256:dcdcaf14bf6e61564d6b7e9a7503be57d65733fcdd6e5c2b02da746779274181",
    ),
    DevelopmentGame(
        "r11l-495a7899",
        "r11l",
        "sha256:483e583c88e91c2ae58ad1fa7b274d97813993796ce798551a563e1a9a78a7ff",
    ),
    DevelopmentGame(
        "cd82-fb555c5d",
        "cd82",
        "sha256:844d3717dd2bb158e658010d21363ad00b3597d12ebe0cb97c24e5d923196b90",
    ),
    DevelopmentGame(
        "sk48-d8078629",
        "sk48",
        "sha256:b8cf3491d5506a3fae0210f37a20faa7c864d8407dab18459376c9c13dc5ff41",
    ),
    DevelopmentGame(
        "m0r0-492f87ba",
        "m0r0",
        "sha256:9888ae0fce7285f40089749692ad84583b13bf0206287e1678fbfc2d907673de",
    ),
    DevelopmentGame(
        "ka59-38d34dbb",
        "ka59",
        "sha256:fe337174d175c13ae0d6796325ac55bc16261098df7b55226ad6ae3fbbef8555",
    ),
    DevelopmentGame(
        "tu93-0768757b",
        "tu93",
        "sha256:e0e3e9f475ecd6e6101adc080b91a0a05919c2ba8c64a38aba690c44057c29d3",
    ),
    DevelopmentGame(
        "lf52-271a04aa",
        "lf52",
        "sha256:3f77f216e6b97083d8cbcf50d3439b18f6556dea06e7ae2564dcdfbd8f2d8203",
    ),
    DevelopmentGame(
        "g50t-5849a774",
        "g50t",
        "sha256:60ca84c0a65821982fd5119f22f7997620df397f81205fa80882df71496b53e5",
    ),
    DevelopmentGame(
        "lp85-305b61c3",
        "lp85",
        "sha256:cfec302ab60d79cbfdb618674488fc1f733d7617f841127fe8a906da07e12561",
    ),
    DevelopmentGame(
        "ar25-0c556536",
        "ar25",
        "sha256:e796e615d2e10c93b849f9bf150308fbf84d624725deaf995d7ec2d1c2f86b22",
    ),
    DevelopmentGame(
        "ls20-9607627b",
        "ls20",
        "sha256:2c2f3412429bea00ba1173ff069304f028cfd1ba5935d896c5e10044ebbeda5a",
    ),
)


class Variant(StrEnum):
    BUILD_000_RANDOM = "build_000_random"
    BUILD_000_CYCLE = "build_000_cycle"
    BUILD_000_FULL = "build_000_full"
    BUILD_001_FULL = "build_001_full"

    @property
    def agent(self) -> str:
        return {
            Variant.BUILD_000_RANDOM: "random",
            Variant.BUILD_000_CYCLE: "cycle",
            Variant.BUILD_000_FULL: "full",
            Variant.BUILD_001_FULL: "full",
        }[self]

    @property
    def baseline_id(self) -> str:
        return {
            Variant.BUILD_000_RANDOM: "B0",
            Variant.BUILD_000_CYCLE: "B1",
            Variant.BUILD_000_FULL: "B4",
            Variant.BUILD_001_FULL: "B4",
        }[self]

    @property
    def source_commit(self) -> str:
        return (
            FROZEN_BUILD_001_COMMIT if self is Variant.BUILD_001_FULL else FROZEN_BUILD_000_COMMIT
        )

    @property
    def source_tree(self) -> str:
        return FROZEN_BUILD_001_TREE if self is Variant.BUILD_001_FULL else FROZEN_BUILD_000_TREE

    @property
    def source_sha256(self) -> str:
        return (
            FROZEN_BUILD_001_SOURCE_SHA256
            if self is Variant.BUILD_001_FULL
            else FROZEN_BUILD_000_SOURCE_SHA256
        )


VARIANTS = (
    Variant.BUILD_000_RANDOM,
    Variant.BUILD_000_CYCLE,
    Variant.BUILD_000_FULL,
    Variant.BUILD_001_FULL,
)


class CellStatus(StrEnum):
    SUCCESS = "success"
    MECHANISM_FAILURE = "mechanism_failure"
    CONTROLLER_WALL_TIMEOUT = "controller_wall_timeout"
    INFRASTRUCTURE_FAILURE = "infrastructure_failure"


@dataclass(frozen=True, slots=True)
class DevelopmentCell:
    ordinal: int
    game: DevelopmentGame
    seed: int
    variant: Variant

    @property
    def cell_id(self) -> str:
        return (
            f"s09-{self.ordinal:02d}-{self.game.stable_name}-{self.variant.value}-seed-{self.seed}"
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "agent": self.variant.agent,
            "asset_sha256": self.game.asset_sha256,
            "baseline_id": self.variant.baseline_id,
            "cell_id": self.cell_id,
            "game_id": self.game.game_id,
            "max_actions": MAX_ACTIONS,
            "max_resets": MAX_RESETS,
            "ordinal": self.ordinal,
            "partition": "development",
            "seed": self.seed,
            "source_commit": self.variant.source_commit,
            "source_tree": self.variant.source_tree,
            "surface": "local-public",
            "variant": self.variant.value,
            "worker_wall_seconds": WORKER_WALL_SECONDS,
        }

    @property
    def spec_hash(self) -> str:
        return sha256_bytes(canonical_json_bytes(self.to_dict()))


def build_matrix() -> tuple[DevelopmentCell, ...]:
    cells: list[DevelopmentCell] = []
    for game in DEVELOPMENT_GAMES:
        for seed in SEEDS:
            for variant in VARIANTS:
                cells.append(DevelopmentCell(len(cells), game, seed, variant))
    if len(cells) != EXPECTED_CELL_COUNT:
        raise EvaluationError("Stage 09 matrix size changed")
    return tuple(cells)


def matrix_hash() -> str:
    return sha256_bytes(canonical_json_bytes([cell.to_dict() for cell in build_matrix()]))


def development_partition_hash() -> str:
    return sha256_bytes(canonical_json_bytes([game.to_dict() for game in DEVELOPMENT_GAMES]))


def development_identifier_list_hash() -> str:
    """Bind the 12 exposed development identities without projecting their values."""

    return sha256_bytes(
        canonical_json_bytes(
            [
                {"game_id": game.game_id, "stable_name": game.stable_name}
                for game in DEVELOPMENT_GAMES
            ]
        )
    )


def validate_predeclaration_bytes(
    raw: bytes, *, expected_file_sha256: str | None = None
) -> dict[str, Any]:
    if expected_file_sha256 is not None and sha256_bytes(raw) != expected_file_sha256:
        raise EvaluationError("Stage 09 predeclaration file hash changed")
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise EvaluationError("Stage 09 predeclaration is not valid JSON") from error
    if not isinstance(value, dict):
        raise EvaluationError("Stage 09 predeclaration must be an object")
    document = cast(dict[str, Any], value)
    if document.get("schema") != PREDECLARATION_SCHEMA or not verify_object_hash(
        document, hash_field="predeclaration_core_hash"
    ):
        raise EvaluationError("Stage 09 predeclaration schema/self-hash changed")
    if document.get("predeclaration_core_hash") != PREDECLARATION_CORE_HASH:
        raise EvaluationError("Stage 09 predeclaration frozen core identity changed")
    expected = {
        "build_001_commit": ORIGINAL_BUILD_001_COMMIT,
        "build_001_tree": ORIGINAL_BUILD_001_TREE,
        "build_001_first_party_source_sha256": ORIGINAL_BUILD_001_SOURCE_SHA256,
        "build_000_commit": FROZEN_BUILD_000_COMMIT,
        "build_000_tree": FROZEN_BUILD_000_TREE,
        "build_000_first_party_source_sha256": FROZEN_BUILD_000_SOURCE_SHA256,
        "public_partition_manifest_sha256": PUBLIC_PARTITION_MANIFEST_SHA256,
        "upstream_lock_sha256": UPSTREAM_LOCK_SHA256,
        "stage08_result_file_sha256": STAGE08_RESULT_FILE_SHA256,
        "stage08_result_core_hash": STAGE08_RESULT_CORE_HASH,
        "stage08_exposure_sha256": STAGE08_EXPOSURE_SHA256,
        "stage08_status": "FAILED_INFRASTRUCTURE",
        "development_partition_hash": development_partition_hash(),
        "matrix_hash": ORIGINAL_MATRIX_HASH,
        "cell_count": EXPECTED_CELL_COUNT,
        "seeds": list(SEEDS),
        "max_actions": MAX_ACTIONS,
        "max_resets": MAX_RESETS,
        "worker_wall_seconds": WORKER_WALL_SECONDS,
        "overall_active_wall_seconds": OVERALL_ACTIVE_WALL_SECONDS,
    }
    bindings = document.get("bindings")
    if not isinstance(bindings, dict) or bindings != expected:
        raise EvaluationError("Stage 09 predeclaration bindings changed")
    if document.get("development_games") != [game.to_dict() for game in DEVELOPMENT_GAMES]:
        raise EvaluationError("Stage 09 development partition changed")
    original_variant_sources = {
        Variant.BUILD_000_RANDOM: (FROZEN_BUILD_000_COMMIT, FROZEN_BUILD_000_TREE),
        Variant.BUILD_000_CYCLE: (FROZEN_BUILD_000_COMMIT, FROZEN_BUILD_000_TREE),
        Variant.BUILD_000_FULL: (FROZEN_BUILD_000_COMMIT, FROZEN_BUILD_000_TREE),
        Variant.BUILD_001_FULL: (ORIGINAL_BUILD_001_COMMIT, ORIGINAL_BUILD_001_TREE),
    }
    expected_matrix = {
        "expansion_order": ["development_games", "seeds", "variants"],
        "variant_order": [variant.value for variant in VARIANTS],
        "variants": [
            {
                "agent": variant.agent,
                "baseline_id": variant.baseline_id,
                "source_commit": original_variant_sources[variant][0],
                "source_tree": original_variant_sources[variant][1],
                "variant": variant.value,
            }
            for variant in VARIANTS
        ],
    }
    if document.get("measurement_matrix") != expected_matrix:
        raise EvaluationError("Stage 09 cell matrix changed")
    if document.get("result_state") != "READY_NOT_EXECUTED":
        raise EvaluationError("Stage 09 predeclaration contains a result")
    gate = document.get("decision_gate")
    if not isinstance(gate, dict) or set(gate) != {
        "all_evidence_verifies",
        "build_001_full_beats_b0",
        "distinct_new_completed_games_minimum",
        "full_normal_termination_fraction_minimum",
        "integrity_required",
        "status_mapping",
    }:
        raise EvaluationError("Stage 09 decision gate fields changed")
    if (
        gate.get("distinct_new_completed_games_minimum") != 2
        or gate.get("full_normal_termination_fraction_minimum") != 0.5
        or gate.get("all_evidence_verifies") is not True
        or gate.get("integrity_required") is not True
    ):
        raise EvaluationError("Stage 09 decision thresholds changed")
    return document


def validate_predeclaration_amendment_bytes(
    raw: bytes,
    *,
    original: Mapping[str, object],
    expected_file_sha256: str | None = None,
) -> dict[str, Any]:
    """Validate the sole before-results source/integrity amendment.

    The original predeclaration remains byte-for-byte authoritative for the
    partition, order, seeds, budgets, wall limits, decision gate, and holdout
    boundary.  This amendment changes only the Build 001 policy snapshot and
    its package-only integrity receipt.
    """

    if expected_file_sha256 is not None and sha256_bytes(raw) != expected_file_sha256:
        raise EvaluationError("Stage 09 predeclaration amendment file hash changed")
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise EvaluationError("Stage 09 predeclaration amendment is not valid JSON") from error
    if not isinstance(value, dict):
        raise EvaluationError("Stage 09 predeclaration amendment must be an object")
    amendment = cast(dict[str, Any], value)
    if amendment.get("schema") != PREDECLARATION_AMENDMENT_SCHEMA or not verify_object_hash(
        amendment, hash_field="amendment_core_hash"
    ):
        raise EvaluationError("Stage 09 predeclaration amendment schema/self-hash changed")
    if amendment.get("amendment_core_hash") != PREDECLARATION_AMENDMENT_CORE_HASH:
        raise EvaluationError("Stage 09 predeclaration amendment core identity changed")
    original_gate = original.get("decision_gate")
    if not isinstance(original_gate, dict):
        raise EvaluationError("Stage 09 original decision gate is absent")
    original_bindings = original.get("bindings")
    if not isinstance(original_bindings, dict):
        raise EvaluationError("Stage 09 original bindings are absent")
    expected = {
        "schema": PREDECLARATION_AMENDMENT_SCHEMA,
        "recorded_at": "2026-08-23T04:50:00Z",
        "result_state": "READY_NOT_EXECUTED",
        "reason": (
            "Before results, complete reachability invalidated the original Build 001 "
            "package-integrity premise; the premeasurement repair froze a generic "
            "pure-normalization policy."
        ),
        "claim_boundary": (
            "Source-identity and package-integrity repair only; no development result, "
            "public-holdout access, or hidden-game claim."
        ),
        "original_predeclaration": {
            "path": "docs/evidence/001-09-development-recovery-predeclaration.json",
            "file_sha256": PREDECLARATION_FILE_SHA256,
            "predeclaration_core_hash": PREDECLARATION_CORE_HASH,
            "preserved_unchanged": True,
        },
        "override_scope": [
            "build_001_policy_source",
            "build_001_package_integrity_receipt",
        ],
        "build_001_policy_source": {
            "prior_commit": ORIGINAL_BUILD_001_COMMIT,
            "prior_tree": ORIGINAL_BUILD_001_TREE,
            "prior_first_party_source_sha256": ORIGINAL_BUILD_001_SOURCE_SHA256,
            "commit": FROZEN_BUILD_001_COMMIT,
            "tree": FROZEN_BUILD_001_TREE,
            "first_party_source_sha256": FROZEN_BUILD_001_SOURCE_SHA256,
            "policy_characterization": "generic-pure-normalization-no-game-identity-table",
        },
        "build_001_package_integrity_receipt": {
            "schema": "arc3.integrity.receipt.v0.2",
            "integrity_scope": "package-only-no-public-identifiers",
            "full_competition_integrity_status": "NOT_EVALUATED_PUBLIC_IDENTIFIERS",
            "git_commit": FROZEN_BUILD_001_COMMIT,
            "file_sha256": BUILD_001_PACKAGE_INTEGRITY_FILE_SHA256,
            "receipt_sha256": BUILD_001_PACKAGE_INTEGRITY_RECEIPT_SHA256,
        },
        "unchanged_protocol": {
            "development_partition_hash": development_partition_hash(),
            "development_identity_count": len(DEVELOPMENT_GAMES),
            "development_identifier_list_hash": development_identifier_list_hash(),
            "expansion_order": ["development_games", "seeds", "variants"],
            "variant_order": [variant.value for variant in VARIANTS],
            "cell_count": EXPECTED_CELL_COUNT,
            "seeds": list(SEEDS),
            "max_actions": MAX_ACTIONS,
            "max_resets": MAX_RESETS,
            "worker_wall_seconds": WORKER_WALL_SECONDS,
            "overall_active_wall_seconds": OVERALL_ACTIVE_WALL_SECONDS,
            "decision_gate_hash": sha256_bytes(canonical_json_bytes(original_gate)),
            "holdout_status": "SEALED_UNCONSUMED",
            "original_matrix_hash": original_bindings.get("matrix_hash"),
            "effective_matrix_hash": matrix_hash(),
        },
        "prior_execution_state": {
            "attempt_output_existed": False,
            "work_root_existed": False,
            "exposure_ledger_existed": False,
            "stage09_cells_exposed": 0,
            "stage09_gameplay_events": 0,
        },
    }
    unsigned = {key: item for key, item in amendment.items() if key != "amendment_core_hash"}
    if unsigned != expected:
        raise EvaluationError("Stage 09 predeclaration amendment fields changed")
    return amendment


def _nonnegative_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise EvaluationError(f"Stage 09 {field} must be a non-negative integer")
    return value


def _finite_nonnegative(value: object, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EvaluationError(f"Stage 09 {field} must be numeric")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise EvaluationError(f"Stage 09 {field} must be finite and non-negative")
    return result


@dataclass(frozen=True, slots=True)
class Outcome:
    cell: DevelopmentCell
    status: CellStatus
    score_verified: bool
    levels_completed: int
    completed: bool
    environment_actions: int
    receipt_hash: str
    recovered_failure_score_verified: bool
    recovered_failure_levels_completed: int
    recovered_failure_completed: bool
    recovered_failure_environment_actions: int

    @classmethod
    def from_receipt(cls, value: Mapping[str, object], cell: DevelopmentCell) -> Outcome:
        receipt = dict(value)
        if receipt.get("schema") != CELL_RECEIPT_SCHEMA or not verify_object_hash(
            receipt, hash_field="cell_receipt_hash"
        ):
            raise EvaluationError("Stage 09 cell receipt hash/schema is invalid")
        expected = {
            "cell_id": cell.cell_id,
            "cell_spec_hash": cell.spec_hash,
            "game_id": cell.game.game_id,
            "seed": cell.seed,
            "variant": cell.variant.value,
            "asset_sha256": cell.game.asset_sha256,
            "source_commit": cell.variant.source_commit,
            "evidence_label": "local-public",
        }
        if any(receipt.get(key) != item for key, item in expected.items()):
            raise EvaluationError("Stage 09 cell receipt identity changed")
        raw_status = receipt.get("status")
        if not isinstance(raw_status, str):
            raise EvaluationError("Stage 09 cell status is invalid")
        status = CellStatus(raw_status)
        if receipt.get("normal_termination_definition") != NORMAL_TERMINATION_DEFINITION:
            raise EvaluationError("Stage 09 normal-termination definition changed")
        mechanism_provenance = receipt.get("mechanism_provenance")
        if status is CellStatus.MECHANISM_FAILURE:
            if not isinstance(mechanism_provenance, dict) or set(mechanism_provenance) != {
                "category",
                "provenance_hash",
                "raw_receipt_hash",
                "schema",
                "source",
            }:
                raise EvaluationError("Stage 09 mechanism failure lacks typed provenance")
            if (
                mechanism_provenance.get("schema") != MECHANISM_PROVENANCE_SCHEMA
                or not verify_object_hash(mechanism_provenance, hash_field="provenance_hash")
                or mechanism_provenance.get("category") not in GENERIC_MECHANISM_CATEGORIES
                or mechanism_provenance.get("raw_receipt_hash") != receipt.get("raw_receipt_hash")
                or mechanism_provenance.get("source") != "typed-generic-controller-boundary"
            ):
                raise EvaluationError("Stage 09 mechanism provenance changed")
        elif mechanism_provenance is not None:
            raise EvaluationError("Stage 09 non-mechanism cell claims mechanism provenance")
        harness = receipt.get("harness_source")
        if not isinstance(harness, dict) or set(harness) != {
            "after",
            "before",
            "expected",
            "stable",
        }:
            raise EvaluationError("Stage 09 cell harness source receipt is absent")
        expected_harness = harness.get("expected")
        before_harness = harness.get("before")
        after_harness = harness.get("after")
        if not all(
            isinstance(item, dict) for item in (expected_harness, before_harness, after_harness)
        ):
            raise EvaluationError("Stage 09 cell harness source receipt is malformed")
        stable_harness = harness_source_stable(
            cast(dict[str, object], before_harness),
            cast(dict[str, object], after_harness),
            expected=cast(dict[str, object], expected_harness),
        )
        if harness.get("stable") is not stable_harness:
            raise EvaluationError("Stage 09 cell harness source stability changed")
        if status is not CellStatus.INFRASTRUCTURE_FAILURE and not stable_harness:
            raise EvaluationError("Stage 09 evidentiary cell used unstable harness source")
        runtime = receipt.get("runtime_environment")
        if not isinstance(runtime, dict) or set(runtime) != {
            "after",
            "before",
            "expected",
            "stable",
        }:
            raise EvaluationError("Stage 09 cell runtime environment receipt is absent")
        expected_runtime = runtime.get("expected")
        before_runtime = runtime.get("before")
        after_runtime = runtime.get("after")
        if not all(
            isinstance(item, dict) for item in (expected_runtime, before_runtime, after_runtime)
        ):
            raise EvaluationError("Stage 09 cell runtime environment receipt is malformed")
        stable_runtime = runtime_environment_stable(
            cast(dict[str, object], before_runtime),
            cast(dict[str, object], after_runtime),
            expected=cast(dict[str, object], expected_runtime),
        )
        if runtime.get("stable") is not stable_runtime:
            raise EvaluationError("Stage 09 cell runtime environment stability changed")
        if status is not CellStatus.INFRASTRUCTURE_FAILURE and not stable_runtime:
            raise EvaluationError("Stage 09 evidentiary cell used an unpinned runtime")
        authority = receipt.get("prior_authority")
        if not isinstance(authority, dict) or set(authority) != {"after", "before", "stable"}:
            raise EvaluationError("Stage 09 cell prior-authority receipt is absent")
        before_authority = authority.get("before")
        after_authority = authority.get("after")
        if not isinstance(before_authority, dict) or not isinstance(after_authority, dict):
            raise EvaluationError("Stage 09 cell prior-authority receipt is malformed")
        for item in (before_authority, after_authority):
            try:
                validate_prior_authority_observation(item)
            except EvaluationError as error:
                raise EvaluationError(
                    "Stage 09 cell prior-authority observation is invalid"
                ) from error
            if status is not CellStatus.INFRASTRUCTURE_FAILURE and item.get("passed") is not True:
                raise EvaluationError("Stage 09 cell prior-authority observation is invalid")
        stable_authority = bool(
            before_authority.get("passed") is True
            and after_authority.get("passed") is True
            and before_authority.get("authority_hash") == after_authority.get("authority_hash")
        )
        if authority.get("stable") is not stable_authority:
            raise EvaluationError("Stage 09 cell prior-authority stability changed")
        if status is not CellStatus.INFRASTRUCTURE_FAILURE and not stable_authority:
            raise EvaluationError("Stage 09 evidentiary cell lost prior authority")
        cache = receipt.get("environment_cache")
        if not isinstance(cache, dict) or set(cache) != {"after", "before", "stable"}:
            raise EvaluationError("Stage 09 cell environment-cache receipt is absent")
        before_cache = cache.get("before")
        after_cache = cache.get("after")
        if not isinstance(before_cache, dict) or not isinstance(after_cache, dict):
            raise EvaluationError("Stage 09 cell environment-cache receipt is malformed")
        stable_cache = environment_cache_stable(before_cache, after_cache)
        if cache.get("stable") is not stable_cache:
            raise EvaluationError("Stage 09 cell environment-cache stability changed")
        if status is not CellStatus.INFRASTRUCTURE_FAILURE and not stable_cache:
            raise EvaluationError("Stage 09 evidentiary cell used an unpinned public cache")
        result = receipt.get("result")
        if not isinstance(result, dict):
            raise EvaluationError("Stage 09 cell result is missing")
        score_verified = result.get("score_verified")
        completed = result.get("completed")
        if not isinstance(score_verified, bool) or not isinstance(completed, bool):
            raise EvaluationError("Stage 09 score flags are invalid")
        levels = _nonnegative_int(result.get("levels_completed"), field="levels completed")
        actions = _nonnegative_int(result.get("environment_actions"), field="actions")
        if actions > MAX_ACTIONS:
            raise EvaluationError("Stage 09 action count exceeds its frozen budget")
        if status is CellStatus.SUCCESS and not score_verified:
            raise EvaluationError("Stage 09 successful cell lacks a verified score")
        if status is not CellStatus.SUCCESS and (
            score_verified or levels != 0 or completed or actions != 0
        ):
            raise EvaluationError("Stage 09 non-success cell contributes decisive metrics")
        if not score_verified and (levels or completed):
            raise EvaluationError("Stage 09 unverified score claims completion")
        recovered = receipt.get("recovered_failure_result")
        recovered_score_verified = False
        recovered_levels = 0
        recovered_completed = False
        recovered_actions = 0
        if status is CellStatus.SUCCESS:
            if recovered is not None:
                raise EvaluationError("Stage 09 successful cell contains failure-only evidence")
        elif recovered is not None:
            if not isinstance(recovered, dict) or set(recovered) != {
                "claim_status",
                "completed",
                "environment_actions",
                "levels_completed",
                "score_verified",
                "source",
            }:
                raise EvaluationError("Stage 09 recovered failure result is malformed")
            recovered_score_verified = recovered.get("score_verified") is True
            recovered_completed_value = recovered.get("completed")
            if not isinstance(recovered_completed_value, bool):
                raise EvaluationError("Stage 09 recovered completion flag is invalid")
            recovered_completed = recovered_completed_value
            recovered_levels = _nonnegative_int(
                recovered.get("levels_completed"), field="recovered failure levels completed"
            )
            recovered_actions = _nonnegative_int(
                recovered.get("environment_actions"), field="recovered failure actions"
            )
            if (
                recovered.get("claim_status") != "non-claim"
                or recovered.get("source")
                not in {
                    "raw-nondecisive-result",
                    "verified-timeout-trace",
                }
                or recovered_actions > MAX_ACTIONS
                or (not recovered_score_verified and (recovered_levels or recovered_completed))
            ):
                raise EvaluationError("Stage 09 recovered failure result changed")
        receipt_hash = receipt.get("cell_receipt_hash")
        if not isinstance(receipt_hash, str):
            raise EvaluationError("Stage 09 cell receipt hash is absent")
        resources = receipt.get("resources")
        if not isinstance(resources, dict):
            raise EvaluationError("Stage 09 resource receipt is absent")
        _nonnegative_int(resources.get("supervision_wall_ns"), field="supervision wall")
        _nonnegative_int(
            resources.get("pre_receipt_active_wall_ns"), field="pre-receipt active wall"
        )
        cpu = resources.get("child_cpu_seconds")
        rss = resources.get("child_peak_rss_bytes")
        if cpu is not None:
            _finite_nonnegative(cpu, field="child CPU")
        if rss is not None:
            _nonnegative_int(rss, field="child peak RSS")
        return cls(
            cell,
            status,
            score_verified,
            levels,
            completed,
            actions,
            receipt_hash,
            recovered_score_verified,
            recovered_levels,
            recovered_completed,
            recovered_actions,
        )


def _summary(outcomes: Sequence[Outcome], variant: Variant) -> dict[str, object]:
    selected = [outcome for outcome in outcomes if outcome.cell.variant is variant]
    if len(selected) != 24:
        raise EvaluationError(f"Stage 09 {variant.value} does not contain 24 cells")
    controller_wall_timeouts = sum(
        outcome.status is CellStatus.CONTROLLER_WALL_TIMEOUT for outcome in selected
    )
    successful_environment_actions = sum(
        outcome.environment_actions for outcome in selected if outcome.status is CellStatus.SUCCESS
    )
    return {
        "completed_runs": sum(
            outcome.completed for outcome in selected if outcome.status is CellStatus.SUCCESS
        ),
        "controller_wall_timeouts": controller_wall_timeouts,
        "controller_wall_timeout_action_charge_per_run": MAX_ACTIONS,
        "effective_environment_actions_for_efficiency": (
            successful_environment_actions + controller_wall_timeouts * MAX_ACTIONS
        ),
        "environment_actions": successful_environment_actions,
        "infrastructure_failures": sum(
            outcome.status is CellStatus.INFRASTRUCTURE_FAILURE for outcome in selected
        ),
        "levels_completed": sum(
            outcome.levels_completed for outcome in selected if outcome.status is CellStatus.SUCCESS
        ),
        "normal_terminations": sum(outcome.status is CellStatus.SUCCESS for outcome in selected),
        "normal_termination_definition": NORMAL_TERMINATION_DEFINITION,
        "recovered_failure_completed_runs_nonclaim": sum(
            outcome.recovered_failure_completed
            for outcome in selected
            if outcome.status is not CellStatus.SUCCESS
        ),
        "recovered_failure_environment_actions_nonclaim": sum(
            outcome.recovered_failure_environment_actions
            for outcome in selected
            if outcome.status is not CellStatus.SUCCESS
        ),
        "recovered_failure_levels_completed_nonclaim": sum(
            outcome.recovered_failure_levels_completed
            for outcome in selected
            if outcome.status is not CellStatus.SUCCESS
        ),
        "runs": len(selected),
    }


def aggregate(
    receipts: Sequence[Mapping[str, object]],
    *,
    evidence_integrity: bool,
    competition_integrity: bool,
) -> dict[str, object]:
    """Apply the exact predeclared decision rule to all 96 receipts."""

    matrix = build_matrix()
    if len(receipts) != len(matrix):
        raise EvaluationError("Stage 09 aggregate requires exactly 96 cell receipts")
    outcomes = tuple(
        Outcome.from_receipt(receipt, cell) for receipt, cell in zip(receipts, matrix, strict=True)
    )
    summaries = {variant: _summary(outcomes, variant) for variant in VARIANTS}
    old_full_games = {
        outcome.cell.game.game_id
        for outcome in outcomes
        if outcome.cell.variant is Variant.BUILD_000_FULL
        and outcome.status is CellStatus.SUCCESS
        and outcome.levels_completed > 0
    }
    new_full_games = {
        outcome.cell.game.game_id
        for outcome in outcomes
        if outcome.cell.variant is Variant.BUILD_001_FULL
        and outcome.status is CellStatus.SUCCESS
        and outcome.levels_completed > 0
    }
    distinct_new_games = sorted(new_full_games - old_full_games)
    current = summaries[Variant.BUILD_001_FULL]
    random = summaries[Variant.BUILD_000_RANDOM]
    current_levels = cast(int, current["levels_completed"])
    random_levels = cast(int, random["levels_completed"])
    current_actions = cast(int, current["effective_environment_actions_for_efficiency"])
    random_actions = cast(int, random["effective_environment_actions_for_efficiency"])
    completion_count_win = current_levels > random_levels
    efficiency_win = bool(
        current_levels > 0
        and random_levels > 0
        and current_actions / current_levels < random_actions / random_levels
    )
    infrastructure_failures = sum(
        cast(int, summary["infrastructure_failures"]) for summary in summaries.values()
    )
    gate = {
        "all_evidence_verifies": evidence_integrity,
        "build_001_full_beats_b0": completion_count_win or efficiency_win,
        "competition_integrity": competition_integrity,
        "distinct_new_completed_games": len(distinct_new_games) >= 2,
        "normal_termination_fraction": cast(int, current["normal_terminations"]) / 24 >= 0.5,
    }
    status = (
        "FAILED_INFRASTRUCTURE"
        if infrastructure_failures or not evidence_integrity or not competition_integrity
        else "PASS"
        if all(gate.values())
        else "FAILED_MECHANISM"
    )
    return {
        "schema": AGGREGATE_SCHEMA,
        "status": status,
        "evidence_label": "local-public",
        "claim_boundary": "development recovery only; no public-holdout or hidden-game generalization claim",
        "matrix_hash": matrix_hash(),
        "cell_count": len(outcomes),
        "cell_receipt_hashes": [outcome.receipt_hash for outcome in outcomes],
        "normal_termination_definition": NORMAL_TERMINATION_DEFINITION,
        "variants": {variant.value: summaries[variant] for variant in VARIANTS},
        "build_001_full": {
            **current,
            "new_completed_game_ids": distinct_new_games,
            "normal_termination_fraction": cast(int, current["normal_terminations"]) / 24,
        },
        "comparison": {
            "b0_completion_count_win": completion_count_win,
            "b0_completion_normalized_action_efficiency_win": efficiency_win,
            "controller_wall_timeout_action_charge_per_run": MAX_ACTIONS,
            "equal_per_run_action_budget": True,
            "metric_scope": "verified-success-actions-plus-frozen-controller-timeout-charge",
        },
        "gate": gate,
    }


__all__ = [
    "AGGREGATE_SCHEMA",
    "BUILD_000_INTEGRITY_FILE_SHA256",
    "BUILD_000_INTEGRITY_RECEIPT_SHA256",
    "BUILD_001_PACKAGE_INTEGRITY_FILE_SHA256",
    "BUILD_001_PACKAGE_INTEGRITY_RECEIPT_SHA256",
    "CELL_ADMISSION_CHARGE_NS",
    "CELL_FINALIZATION_SCHEMA",
    "CELL_RECEIPT_SCHEMA",
    "DEVELOPMENT_GAMES",
    "ENVIRONMENT_CACHE_SCHEMA",
    "EXPECTED_CELL_COUNT",
    "FROZEN_BUILD_000_COMMIT",
    "FROZEN_BUILD_000_SOURCE_SHA256",
    "FROZEN_BUILD_000_TREE",
    "FROZEN_BUILD_001_COMMIT",
    "FROZEN_BUILD_001_SOURCE_SHA256",
    "FROZEN_BUILD_001_TREE",
    "HARNESS_SOURCE_BINDING_SCHEMA",
    "HARNESS_SOURCE_OBSERVATION_SCHEMA",
    "HARNESS_SOURCE_PATHS",
    "HOLDOUT_NONCONSUMPTION_FILE_SHA256",
    "MAX_ACTIONS",
    "MAX_RESETS",
    "MECHANISM_PROVENANCE_SCHEMA",
    "NORMAL_TERMINATION_DEFINITION",
    "OVERALL_ACTIVE_WALL_SECONDS",
    "PREDECLARATION_AMENDMENT_CORE_HASH",
    "PREDECLARATION_AMENDMENT_FILE_SHA256",
    "PREDECLARATION_AMENDMENT_SCHEMA",
    "PREDECLARATION_CORE_HASH",
    "PREDECLARATION_FILE_SHA256",
    "PREFLIGHT_SCHEMA",
    "PRIOR_AUTHORITY_SCHEMA",
    "PUBLIC_PARTITION_MANIFEST_SHA256",
    "RUNTIME_ENVIRONMENT_OBSERVATION_SCHEMA",
    "RUNTIME_ENVIRONMENT_SCHEMA",
    "SEEDS",
    "STAGE08_EXPOSURE_SHA256",
    "STAGE08_RESULT_CORE_HASH",
    "STAGE08_RESULT_FILE_SHA256",
    "VARIANTS",
    "WORKER_SPEC_SCHEMA",
    "WORKER_WALL_SECONDS",
    "CellStatus",
    "DevelopmentCell",
    "DevelopmentGame",
    "Outcome",
    "Variant",
    "aggregate",
    "build_matrix",
    "development_identifier_list_hash",
    "development_partition_hash",
    "environment_cache_stable",
    "harness_source_stable",
    "matrix_hash",
    "prior_authority_stable",
    "runtime_environment_stable",
    "validate_environment_cache_observation",
    "validate_harness_source_binding",
    "validate_harness_source_observation",
    "validate_predeclaration_amendment_bytes",
    "validate_predeclaration_bytes",
    "validate_prior_authority_observation",
    "validate_runtime_environment_binding",
    "validate_runtime_environment_observation",
]
