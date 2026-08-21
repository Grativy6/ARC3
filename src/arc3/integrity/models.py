"""Typed, non-secret result records for competition-integrity scans."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import cast

from arc3.integrity.hashes import canonical_json_bytes, sha256_bytes
from arc3.types import JSONValue


class FindingSeverity(StrEnum):
    """Whether a finding blocks the competition-integrity gate."""

    ERROR = "error"
    WARNING = "warning"


class FindingCategory(StrEnum):
    """Static finding families emitted by the scanner."""

    PUBLIC_GAME_IDENTIFIER = "public_game_identifier"
    GAME_SPECIFIC_LOGIC = "game_specific_logic"
    FORBIDDEN_NETWORK_CLIENT = "forbidden_network_client"
    LIKELY_SECRET = "likely_secret"
    SOURCE_IDENTITY = "source_identity"
    SUPPLY_CHAIN = "supply_chain"
    UNSAFE_ARCHIVE = "unsafe_archive"
    UNSCANNABLE_CANDIDATE = "unscannable_candidate"
    UNREADABLE_SOURCE = "unreadable_source"
    UNPARSEABLE_SOURCE = "unparseable_source"


@dataclass(frozen=True, slots=True, order=True)
class IntegrityFinding:
    """A redacted source-linked finding.

    ``evidence_sha256`` commits to the matched text without copying a potential
    credential into logs or receipts.
    """

    path: str
    line: int
    category: FindingCategory
    rule_id: str
    severity: FindingSeverity
    evidence_sha256: str
    message: str

    def to_dict(self) -> dict[str, JSONValue]:
        """Return a deterministic JSON-compatible representation."""

        return {
            "category": self.category.value,
            "evidence_sha256": self.evidence_sha256,
            "line": self.line,
            "message": self.message,
            "path": self.path,
            "rule_id": self.rule_id,
            "severity": self.severity.value,
        }


@dataclass(frozen=True, slots=True, order=True)
class DependencyRecord:
    """Offline metadata for one dependency pinned in ``uv.lock``."""

    name: str
    locked_version: str
    source_kind: str
    installed_version: str | None
    license_status: str
    license_evidence: tuple[str, ...]
    metadata_sha256: str | None

    def to_dict(self) -> dict[str, JSONValue]:
        """Return a deterministic JSON-compatible representation."""

        return {
            "installed_version": self.installed_version,
            "license_evidence": list(self.license_evidence),
            "license_status": self.license_status,
            "locked_version": self.locked_version,
            "metadata_sha256": self.metadata_sha256,
            "name": self.name,
            "source_kind": self.source_kind,
        }


@dataclass(frozen=True, slots=True)
class IntegrityReceipt:
    """A self-hashed canonical receipt whose body contains no implicit clock."""

    body: Mapping[str, JSONValue]

    @property
    def receipt_sha256(self) -> str:
        """Return the digest over the receipt body, excluding the digest field."""

        return sha256_bytes(canonical_json_bytes(self.body))

    @property
    def passed(self) -> bool:
        """Return the stored blocking-gate result."""

        value = self.body.get("passed")
        return value is True

    def to_dict(self) -> dict[str, JSONValue]:
        """Return the body plus its verifiable self-hash."""

        result = dict(self.body)
        result["receipt_sha256"] = self.receipt_sha256
        return result

    def canonical_bytes(self) -> bytes:
        """Return canonical bytes suitable for exact artifact comparison."""

        return canonical_json_bytes(self.to_dict())

    @classmethod
    def from_bytes(cls, raw: bytes) -> IntegrityReceipt:
        """Parse and verify canonical receipt bytes."""

        loaded = json.loads(raw)
        if not isinstance(loaded, dict):
            raise ValueError("integrity receipt must contain a JSON object")
        data = cast(dict[str, JSONValue], loaded)
        claimed = data.pop("receipt_sha256", None)
        if not isinstance(claimed, str):
            raise ValueError("integrity receipt has no receipt_sha256")
        receipt = cls(body=data)
        if receipt.receipt_sha256 != claimed:
            raise ValueError("integrity receipt hash does not match its body")
        if receipt.canonical_bytes() != raw:
            raise ValueError("integrity receipt is not canonical JSON")
        return receipt


__all__ = [
    "DependencyRecord",
    "FindingCategory",
    "FindingSeverity",
    "IntegrityFinding",
    "IntegrityReceipt",
]
