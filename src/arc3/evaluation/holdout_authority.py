"""Opaque, hash-only authority for a still-sealed public holdout.

This module deliberately does not parse the public partition manifest or any
exposure ledger.  It hashes those byte streams and validates already-sealed
nonconsumption anchors.  No public game identity or asset path is accepted as
an input or emitted in the resulting receipt.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from arc3.evaluation.artifacts import seal_object, sha256_file
from arc3.types import JSONValue

OPAQUE_HOLDOUT_AUTHORITY_SCHEMA = "arc3.holdout.opaque-authority.v0.1"
PUBLIC_PARTITION_MANIFEST_SHA256 = (
    "sha256:682d5891c2aface54803d9bd1173c55ed21e89856e13b8a478fb9276ee963f2f"
)


@dataclass(frozen=True, slots=True)
class JsonAssertion:
    """One exact assertion over a previously sealed metadata anchor."""

    path: tuple[str, ...]
    expected: JSONValue


@dataclass(frozen=True, slots=True)
class NonconsumptionAnchor:
    """A frozen metadata artifact that already established nonconsumption."""

    role: str
    path: Path
    expected_sha256: str
    assertions: tuple[JsonAssertion, ...]


@dataclass(frozen=True, slots=True)
class OpaqueExposureBinding:
    """A ledger bound only by bytes; its rows are never loaded here."""

    role: str
    path: Path
    expected_sha256: str


@dataclass(frozen=True, slots=True)
class OpaqueHoldoutInputs:
    """All byte identities needed to establish the opaque authority."""

    expected_manifest_sha256: str
    anchors: tuple[NonconsumptionAnchor, ...]
    exposures: tuple[OpaqueExposureBinding, ...]


def _lookup(value: object, path: Sequence[str]) -> object:
    current = value
    for component in path:
        if not isinstance(current, Mapping):
            return None
        current = current.get(component)
    return current


def _anchor_receipt(anchor: NonconsumptionAnchor) -> dict[str, JSONValue]:
    measured: str | None = None
    assertions_passed = False
    error: str | None = None
    try:
        measured = sha256_file(anchor.path)
        raw: object = json.loads(anchor.path.read_text(encoding="utf-8"))
        assertions_passed = isinstance(raw, Mapping) and all(
            _lookup(raw, assertion.path) == assertion.expected for assertion in anchor.assertions
        )
    except (OSError, json.JSONDecodeError) as caught:
        error = type(caught).__name__
    return {
        "assertions_passed": assertions_passed,
        "error": error,
        "expected_sha256": anchor.expected_sha256,
        "role": anchor.role,
        "sha256": measured,
        "verified": measured == anchor.expected_sha256 and assertions_passed,
    }


def _exposure_receipt(binding: OpaqueExposureBinding) -> dict[str, JSONValue]:
    measured: str | None = None
    error: str | None = None
    try:
        measured = sha256_file(binding.path)
    except OSError as caught:
        error = type(caught).__name__
    return {
        "error": error,
        "expected_sha256": binding.expected_sha256,
        "role": binding.role,
        "sha256": measured,
        "verified": measured == binding.expected_sha256,
    }


def default_opaque_holdout_inputs(root: Path) -> OpaqueHoldoutInputs:
    """Return the frozen Build 001 nonconsumption chain without opening it."""

    build000_hash = "sha256:cd9af42ed3a5ef9fa0dc201ddb10e32d2bcccee9df729aa0c7d53077c04c9ad4"
    stage03_hash = "sha256:e02a9fa71206170a6fe2aeefb6935ae25141e2759937657475cead4389bb17aa"
    stage07_hash = "sha256:4f924df44b11decb392022a927b3296e0248a02edac2c87c53899d374045f0c7"
    stage08_hash = "sha256:be73b837805a66ed172b20573aa31c41fe6ba16ced4d471929b6018e22a5d52e"
    return OpaqueHoldoutInputs(
        expected_manifest_sha256=PUBLIC_PARTITION_MANIFEST_SHA256,
        anchors=(
            NonconsumptionAnchor(
                role="build-001-stage-00",
                path=root / "docs/evidence/001-00-preflight-acceptance.json",
                expected_sha256=(
                    "sha256:65eb293aff43fb50f7ab5b52bef3af99331fd5f02f8b5197e1f8a10e2a2a68ff"
                ),
                assertions=(
                    JsonAssertion(("status",), "PASS"),
                    JsonAssertion(("holdout", "status"), "SEALED_UNCONSUMED"),
                    JsonAssertion(("holdout", "manifest_sha256"), PUBLIC_PARTITION_MANIFEST_SHA256),
                    JsonAssertion(("holdout", "exposure_ledger_sha256"), build000_hash),
                    JsonAssertion(("holdout", "holdout_events"), 0),
                    JsonAssertion(("holdout", "holdout_asset_directories_present"), 0),
                    JsonAssertion(("holdout", "episode_source_or_gameplay_opened"), False),
                ),
            ),
            NonconsumptionAnchor(
                role="build-001-stage-05",
                path=root / "docs/evidence/001-05-action-equivariance.json",
                expected_sha256=(
                    "sha256:7d9a72d9e222944a60cf92cb2b3bd5db2e33f46d5a64be4d22f91df224adf85a"
                ),
                assertions=(
                    JsonAssertion(("status",), "PASS"),
                    JsonAssertion(("holdout", "status"), "SEALED_UNCONSUMED"),
                    JsonAssertion(
                        ("holdout", "public_partition_manifest_sha256"),
                        PUBLIC_PARTITION_MANIFEST_SHA256,
                    ),
                    JsonAssertion(("holdout", "build_000_exposure_ledger_sha256"), build000_hash),
                    JsonAssertion(("holdout", "stage_03_exposure_ledger_sha256"), stage03_hash),
                    JsonAssertion(("holdout", "public_holdout_gameplay_events"), 0),
                    JsonAssertion(("holdout", "locally_acquired_holdout_assets"), 0),
                ),
            ),
            NonconsumptionAnchor(
                role="build-001-stage-07",
                path=root / "docs/evidence/001-07-retrodiction-decision.json",
                expected_sha256=(
                    "sha256:35555cc69e9f35091dd3a18ead1822b0b2afde5847f045d4901b7491227425e4"
                ),
                assertions=(
                    JsonAssertion(("holdout", "status"), "SEALED_UNCONSUMED"),
                    JsonAssertion(("holdout", "development_exposure_ledger_sha256"), stage07_hash),
                    JsonAssertion(("holdout", "public_holdout_gameplay_events"), 0),
                    JsonAssertion(("holdout", "locally_acquired_holdout_assets"), 0),
                ),
            ),
            NonconsumptionAnchor(
                role="build-001-stage-08",
                path=root / "docs/evidence/001-08-two-speed-controller.json",
                expected_sha256=(
                    "sha256:0134c9e5b7acea716f790088cb59109eded7857ce83fda004ea1b88be2eb92ac"
                ),
                assertions=(
                    JsonAssertion(("integrity", "holdout_sealed"), True),
                    JsonAssertion(("integrity", "public_holdout_game_ids_selected"), 0),
                    JsonAssertion(("integrity", "public_holdout_gameplay_events"), 0),
                    JsonAssertion(
                        ("integrity", "holdout_manifest_loaded_as_gameplay_metadata"), False
                    ),
                    JsonAssertion(
                        ("integrity", "holdout_manifest_sha256"),
                        PUBLIC_PARTITION_MANIFEST_SHA256,
                    ),
                    JsonAssertion(
                        ("artifact_receipts", "exposure_ledger", "file_sha256"), stage08_hash
                    ),
                ),
            ),
        ),
        exposures=(
            OpaqueExposureBinding(
                "build-000",
                Path("C:/a/arc3-s15-6a0f6e5/artifacts/stage15/public-exposure.jsonl"),
                build000_hash,
            ),
            OpaqueExposureBinding(
                "build-001-stage-03",
                Path("C:/a/arc3-b001/artifacts/stage03/public-exposure.jsonl"),
                stage03_hash,
            ),
            OpaqueExposureBinding(
                "build-001-stage-07",
                Path("C:/a/arc3-b001/artifacts/stage07/public-exposure.jsonl"),
                stage07_hash,
            ),
            OpaqueExposureBinding(
                "build-001-stage-08",
                Path("C:/a/arc3-b001/artifacts/stage08/public-exposure.jsonl"),
                stage08_hash,
            ),
        ),
    )


def build_opaque_holdout_authority(
    root: Path,
    *,
    inputs: OpaqueHoldoutInputs | None = None,
) -> dict[str, object]:
    """Build a sealed receipt without semantic manifest/ledger or asset access."""

    selected = inputs or default_opaque_holdout_inputs(root)
    anchors = [_anchor_receipt(anchor) for anchor in selected.anchors]
    exposures = [_exposure_receipt(binding) for binding in selected.exposures]
    manifest_anchor_count = sum(
        any(
            assertion.expected == selected.expected_manifest_sha256
            for assertion in anchor.assertions
        )
        for anchor in selected.anchors
    )
    predicates = {
        "anchors_verified": bool(anchors) and all(item["verified"] is True for item in anchors),
        "exposure_bytes_verified": bool(exposures)
        and all(item["verified"] is True for item in exposures),
        "manifest_hash_linked": manifest_anchor_count >= 2,
    }
    report: dict[str, object] = {
        "anchors": anchors,
        "constraints": {
            "asset_path_accesses": 0,
            "exposure_ledger_semantics_loaded": False,
            "holdout_path_accesses": 0,
            "identity_values_emitted": 0,
            "manifest_bytes_accessed": False,
            "manifest_loaded_as_metadata": False,
        },
        "exposures": exposures,
        "manifest": {
            "anchor_count": manifest_anchor_count,
            "sha256": selected.expected_manifest_sha256,
            "source": "hash-linked-nonconsumption-anchors",
            "verified": predicates["manifest_hash_linked"],
        },
        "predicates": predicates,
        "schema": OPAQUE_HOLDOUT_AUTHORITY_SCHEMA,
        "status": "SEALED_UNCONSUMED" if all(predicates.values()) else "INTEGRITY_FAILURE",
    }
    return cast(
        dict[str, object],
        seal_object(report, hash_field="authority_sha256"),
    )


__all__ = [
    "OPAQUE_HOLDOUT_AUTHORITY_SCHEMA",
    "PUBLIC_PARTITION_MANIFEST_SHA256",
    "JsonAssertion",
    "NonconsumptionAnchor",
    "OpaqueExposureBinding",
    "OpaqueHoldoutInputs",
    "build_opaque_holdout_authority",
    "default_opaque_holdout_inputs",
]
