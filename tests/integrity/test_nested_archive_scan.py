"""Process-local regressions for the exact nested first-party package payload."""

from __future__ import annotations

import hashlib
import io
import os
import stat
import struct
import zipfile
from pathlib import Path

import pytest
import scripts.release_candidate_verifier as release_verifier

from arc3.integrity import FindingCategory, scan_archive_files


def _zip_bytes(
    members: dict[str, bytes | str],
    *,
    compression: int = zipfile.ZIP_STORED,
    modes: dict[str, int] | None = None,
) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=compression) as handle:
        for name, content in members.items():
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = compression
            if modes is not None and name in modes:
                info.create_system = 3
                info.external_attr = modes[name] << 16
            handle.writestr(info, content)
    raw = buffer.getvalue()
    for name in members:
        if "\\" in name:
            normalized = name.replace("\\", "/").encode("utf-8")
            raw = raw.replace(normalized, name.encode("utf-8"))
    return raw


def _write_candidate(path: Path, payload: bytes) -> None:
    path.write_bytes(_zip_bytes({"arc3-first-party.zip": payload}))


def _write_package_archives(root: Path) -> None:
    root.mkdir(parents=True)
    payload = _zip_bytes({"agent/my_agent.py": "VALUE = 1\n"})
    (root / "arc3-first-party.zip").write_bytes(payload)
    _write_candidate(root / "arc3-kaggle-candidate.zip", payload)


@pytest.mark.competition
def test_actual_candidate_layout_scans_nested_first_party_payload(tmp_path: Path) -> None:
    archive = tmp_path / "arc3-kaggle-candidate.zip"
    _write_candidate(
        archive,
        _zip_bytes({"agent/my_agent.py": "class MyAgent:\n    pass\n"}),
    )

    findings = scan_archive_files(root=tmp_path, archives=(archive,), public_identifiers=())

    assert findings == ()


@pytest.mark.competition
@pytest.mark.parametrize(
    ("source", "category", "rule_id"),
    (
        (
            "import openai\n",
            FindingCategory.FORBIDDEN_NETWORK_CLIENT,
            "forbidden-import",
        ),
        (
            'TARGET = "fixture-1234abcd"\n',
            FindingCategory.GAME_SPECIFIC_LOGIC,
            "game-id-shaped-literal",
        ),
    ),
)
def test_nested_first_party_payload_policy_is_scanned(
    tmp_path: Path,
    source: str,
    category: FindingCategory,
    rule_id: str,
) -> None:
    archive = tmp_path / "candidate.zip"
    _write_candidate(archive, _zip_bytes({"agent/my_agent.py": source}))

    findings = scan_archive_files(root=tmp_path, archives=(archive,), public_identifiers=())

    assert any(
        finding.path == "candidate.zip!/arc3-first-party.zip!/agent/my_agent.py"
        and finding.category is category
        and finding.rule_id == rule_id
        for finding in findings
    )


@pytest.mark.competition
def test_nested_adapter_uses_existing_non_policy_gateway_exception(tmp_path: Path) -> None:
    archive = tmp_path / "candidate.zip"
    _write_candidate(
        archive,
        _zip_bytes(
            {
                "src/arc3/adapters/arc_agi.py": (
                    "import importlib\n"
                    "def load(name: str):\n"
                    "    return importlib.import_module(name)\n"
                )
            }
        ),
    )

    findings = scan_archive_files(root=tmp_path, archives=(archive,), public_identifiers=())

    assert not any(finding.rule_id == "forbidden-dynamic-import" for finding in findings)


@pytest.mark.competition
@pytest.mark.parametrize(
    ("member_name", "modes", "path_suffix", "rule_id"),
    (
        (
            "../escape.py",
            None,
            "arc3-first-party.zip",
            "archive-central-directory-unsafe",
        ),
        (
            "C:/escape.py",
            None,
            "arc3-first-party.zip",
            "archive-central-directory-unsafe",
        ),
        (
            "agent/link.py",
            {"agent/link.py": stat.S_IFLNK | 0o777},
            "agent/link.py",
            "archive-symlink",
        ),
        (
            "agent/fifo.py",
            {"agent/fifo.py": stat.S_IFIFO | 0o600},
            "agent/fifo.py",
            "archive-special-member",
        ),
    ),
)
def test_nested_first_party_payload_rejects_unsafe_members(
    tmp_path: Path,
    member_name: str,
    modes: dict[str, int] | None,
    path_suffix: str,
    rule_id: str,
) -> None:
    archive = tmp_path / "candidate.zip"
    payload = _zip_bytes({member_name: "VALUE = 1\n"}, modes=modes)
    _write_candidate(archive, payload)

    findings = scan_archive_files(root=tmp_path, archives=(archive,), public_identifiers=())

    assert any(
        finding.path.endswith(path_suffix)
        and finding.category is FindingCategory.UNSAFE_ARCHIVE
        and finding.rule_id == rule_id
        for finding in findings
    )


@pytest.mark.competition
def test_nested_payload_raw_backslash_name_is_rejected_before_zip_decoding(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "candidate.zip"
    _write_candidate(archive, _zip_bytes({"agent\\escape.py": "VALUE = 1\n"}))

    findings = scan_archive_files(root=tmp_path, archives=(archive,), public_identifiers=())

    assert any(
        finding.path == "candidate.zip!/arc3-first-party.zip"
        and finding.category is FindingCategory.UNSAFE_ARCHIVE
        and finding.rule_id == "archive-central-directory-unsafe"
        for finding in findings
    )


@pytest.mark.competition
def test_nested_archive_limits_are_cumulative(tmp_path: Path) -> None:
    archive = tmp_path / "candidate.zip"
    payload = _zip_bytes(
        {
            "agent/my_agent.py": "VALUE = 1\n",
            "src/arc3/__init__.py": "",
        }
    )
    _write_candidate(archive, payload)

    member_findings = scan_archive_files(
        root=tmp_path,
        archives=(archive,),
        public_identifiers=(),
        max_members=2,
    )
    expanded_findings = scan_archive_files(
        root=tmp_path,
        archives=(archive,),
        public_identifiers=(),
        max_expanded_bytes=len(payload),
    )

    assert any(finding.rule_id == "archive-member-count-limit" for finding in member_findings)
    assert any(finding.rule_id == "archive-expanded-size-limit" for finding in expanded_findings)


@pytest.mark.competition
def test_rejected_archive_is_not_retained_before_cumulative_byte_admission(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first.zip"
    second = tmp_path / "second.zip"
    first.write_bytes(_zip_bytes({"agent/first.py": "VALUE = 1\n"}))
    second.write_bytes(_zip_bytes({"agent/second.py": "VALUE = 2\n"}))
    limit = first.stat().st_size + second.stat().st_size - 1
    scanned_hashes: dict[str, str] = {}
    scanned_snapshots: dict[str, bytes] = {}

    findings = scan_archive_files(
        root=tmp_path,
        archives=(first, second),
        public_identifiers=(),
        max_archive_bytes=limit,
        scanned_hashes=scanned_hashes,
        scanned_snapshots=scanned_snapshots,
    )

    assert any(
        finding.path == "second.zip" and finding.rule_id == "archive-total-size-limit"
        for finding in findings
    )
    assert set(scanned_hashes) == {"first.zip"}
    assert set(scanned_snapshots) == {"first.zip"}


@pytest.mark.competition
def test_nested_first_party_payload_depth_is_bounded(tmp_path: Path) -> None:
    archive = tmp_path / "candidate.zip"
    innermost = _zip_bytes({"agent/my_agent.py": "VALUE = 1\n"})
    payload = _zip_bytes({"arc3-first-party.zip": innermost})
    _write_candidate(archive, payload)

    findings = scan_archive_files(root=tmp_path, archives=(archive,), public_identifiers=())

    assert any(
        finding.path.endswith("!/arc3-first-party.zip!/arc3-first-party.zip")
        and finding.rule_id == "archive-nesting-depth-limit"
        for finding in findings
    )


@pytest.mark.competition
def test_archive_preflight_rejects_zip64_sentinel_before_metadata_materialization(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "candidate.zip"
    raw = bytearray(_zip_bytes({"agent/my_agent.py": "VALUE = 1\n"}))
    end_offset = raw.rfind(b"PK\x05\x06")
    assert end_offset >= 0
    struct.pack_into("<H", raw, end_offset + 10, 0xFFFF)
    archive.write_bytes(raw)

    findings = scan_archive_files(root=tmp_path, archives=(archive,), public_identifiers=())

    assert any(finding.rule_id == "archive-central-directory-unsafe" for finding in findings)


@pytest.mark.competition
def test_archive_preflight_counts_central_records_before_decoder_materialization(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "candidate.zip"
    raw = bytearray(_zip_bytes({f"data/{index:04d}.txt": "x" for index in range(32)}))
    end_offset = raw.rfind(b"PK\x05\x06")
    assert end_offset >= 0
    struct.pack_into("<H", raw, end_offset + 8, 1)
    struct.pack_into("<H", raw, end_offset + 10, 1)
    archive.write_bytes(raw)

    findings = scan_archive_files(
        root=tmp_path,
        archives=(archive,),
        public_identifiers=(),
        max_members=4,
    )

    assert any(finding.rule_id == "archive-central-directory-unsafe" for finding in findings)


@pytest.mark.competition
@pytest.mark.parametrize("compression", (zipfile.ZIP_BZIP2, zipfile.ZIP_LZMA))
def test_nested_payload_rejects_unbounded_compression_before_member_decode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    compression: int,
) -> None:
    archive = tmp_path / "candidate.zip"
    payload = _zip_bytes(
        {"agent/my_agent.py": "VALUE = 1\n"},
        compression=compression,
    )
    _write_candidate(archive, payload)
    decoded_members: list[str] = []
    real_open = zipfile.ZipFile.open

    def record_open(
        handle: zipfile.ZipFile,
        name: str | zipfile.ZipInfo,
        mode: str = "r",
        pwd: bytes | None = None,
        *,
        force_zip64: bool = False,
    ) -> object:
        decoded_members.append(name.filename if isinstance(name, zipfile.ZipInfo) else name)
        return real_open(handle, name, mode, pwd, force_zip64=force_zip64)

    monkeypatch.setattr(zipfile.ZipFile, "open", record_open)

    findings = scan_archive_files(root=tmp_path, archives=(archive,), public_identifiers=())

    assert "agent/my_agent.py" not in decoded_members
    assert any(
        finding.path.endswith("!/agent/my_agent.py")
        and finding.rule_id == "archive-compression-unsupported"
        for finding in findings
    )


@pytest.mark.competition
def test_scanner_hash_and_decoding_use_one_bounded_archive_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = tmp_path / "candidate.zip"
    clean = _zip_bytes({"agent/my_agent.py": "VALUE = 1\n"})
    replaced = _zip_bytes({"agent/my_agent.py": "import openai\n"})
    archive.write_bytes(clean)
    real_is_zipfile = zipfile.is_zipfile

    def replace_after_snapshot(candidate: object) -> bool:
        archive.write_bytes(replaced)
        return real_is_zipfile(candidate)

    monkeypatch.setattr(zipfile, "is_zipfile", replace_after_snapshot)
    scanned_hashes: dict[str, str] = {}

    findings = scan_archive_files(
        root=tmp_path,
        archives=(archive,),
        public_identifiers=(),
        scanned_hashes=scanned_hashes,
    )

    assert findings == ()
    assert scanned_hashes == {"candidate.zip": f"sha256:{hashlib.sha256(clean).hexdigest()}"}


@pytest.mark.competition
@pytest.mark.skipif(os.name == "nt", reason="POSIX permits replacing an open file path")
def test_archive_descriptor_rejects_regular_path_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = tmp_path / "candidate.zip"
    replacement = tmp_path / "replacement.zip"
    retired = tmp_path / "retired.zip"
    _write_candidate(archive, _zip_bytes({"agent/my_agent.py": "VALUE = 1\n"}))
    _write_candidate(replacement, _zip_bytes({"agent/my_agent.py": "import openai\n"}))
    real_open = os.open

    def open_then_replace(
        candidate: str | bytes | os.PathLike[str],
        flags: int,
        mode: int = 0o777,
    ) -> int:
        descriptor = real_open(candidate, flags, mode)
        if os.fspath(candidate) == os.fspath(archive):
            archive.rename(retired)
            replacement.rename(archive)
        return descriptor

    monkeypatch.setattr(os, "open", open_then_replace)

    findings = scan_archive_files(root=tmp_path, archives=(archive,), public_identifiers=())

    assert any(finding.rule_id == "candidate-path-race" for finding in findings)


@pytest.mark.competition
@pytest.mark.skipif(os.name == "nt", reason="POSIX permits replacing an open file path")
def test_archive_descriptor_rejects_oversize_symlink_swap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = tmp_path / "candidate.zip"
    outside = tmp_path / "oversize.zip"
    retired = tmp_path / "retired.zip"
    _write_candidate(archive, _zip_bytes({"agent/my_agent.py": "VALUE = 1\n"}))
    outside.write_bytes(b"x" * 1024)
    real_open = os.open

    def open_then_alias(
        candidate: str | bytes | os.PathLike[str],
        flags: int,
        mode: int = 0o777,
    ) -> int:
        descriptor = real_open(candidate, flags, mode)
        if os.fspath(candidate) == os.fspath(archive):
            archive.rename(retired)
            archive.symlink_to(outside)
        return descriptor

    monkeypatch.setattr(os, "open", open_then_alias)

    findings = scan_archive_files(
        root=tmp_path,
        archives=(archive,),
        public_identifiers=(),
        max_archive_bytes=512,
    )

    assert any(finding.rule_id == "candidate-symlink" for finding in findings)


@pytest.mark.competition
@pytest.mark.parametrize("target_name", ("package-a", "package-b"))
@pytest.mark.parametrize("mechanism", ("central-count", "bzip2"))
def test_compare_preflights_both_candidates_before_projection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    target_name: str,
    mechanism: str,
) -> None:
    first = tmp_path / "package-a"
    second = tmp_path / "package-b"
    _write_package_archives(first)
    _write_package_archives(second)
    target = tmp_path / target_name / "arc3-kaggle-candidate.zip"
    if mechanism == "bzip2":
        target.write_bytes(_zip_bytes({"unsafe.bin": b"x"}, compression=zipfile.ZIP_BZIP2))
    else:
        raw = bytearray(_zip_bytes({f"data/{index:04d}.txt": b"x" for index in range(32)}))
        end_offset = raw.rfind(b"PK\x05\x06")
        assert end_offset >= 0
        struct.pack_into("<H", raw, end_offset + 8, 1)
        struct.pack_into("<H", raw, end_offset + 10, 1)
        target.write_bytes(raw)
    projection_calls: list[str] = []

    def unexpected_projection(*args: object, **kwargs: object) -> dict[str, object]:
        projection_calls.append("called")
        return {}

    monkeypatch.setattr(release_verifier, "package_projection", unexpected_projection)

    with pytest.raises(ValueError, match="bounded package archive preflight"):
        release_verifier.compare_packages(
            first / "build-receipt.json",
            second / "build-receipt.json",
            expected_commit="a" * 40,
        )

    assert projection_calls == []


@pytest.mark.competition
@pytest.mark.parametrize("target_name", ("package-a", "package-b"))
def test_package_projection_rechecks_paths_but_consumes_original_bounded_snapshots(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    target_name: str,
) -> None:
    first = tmp_path / "package-a"
    second = tmp_path / "package-b"
    _write_package_archives(first)
    _write_package_archives(second)
    bounded = release_verifier._bounded_package_archive_preflight((first, second))
    target = tmp_path / target_name / "arc3-kaggle-candidate.zip"
    target.write_bytes(_zip_bytes({"unsafe.bin": b"x"}, compression=zipfile.ZIP_BZIP2))
    legacy_calls: list[str] = []

    def unexpected_consumer(*args: object, **kwargs: object) -> object:
        legacy_calls.append("called")
        raise AssertionError("legacy archive consumer was invoked")

    monkeypatch.setattr(release_verifier, "_verified_package_receipt_bytes", unexpected_consumer)
    monkeypatch.setattr(release_verifier, "decode_candidate_archive_snapshot", unexpected_consumer)
    monkeypatch.setattr(
        release_verifier,
        "validate_candidate_member_snapshots",
        unexpected_consumer,
    )
    monkeypatch.setattr(release_verifier, "_validate_package_formats", unexpected_consumer)

    with pytest.raises(ValueError, match="bounded package archive preflight"):
        release_verifier.package_projection(
            tmp_path / target_name / "build-receipt.json",
            expected_commit="a" * 40,
            bounded_archives=bounded,
        )

    assert legacy_calls == []


@pytest.mark.competition
@pytest.mark.parametrize(
    ("limit_name", "rule_id"),
    (
        ("archive", "archive-total-size-limit"),
        ("central", "archive-central-directory-size-limit"),
    ),
)
def test_package_preflight_limits_are_shared_across_outer_and_nested_archives(
    tmp_path: Path,
    limit_name: str,
    rule_id: str,
) -> None:
    first = tmp_path / "package-a"
    second = tmp_path / "package-b"
    _write_package_archives(first)
    _write_package_archives(second)
    kwargs = (
        {"max_archive_bytes": (first / "arc3-kaggle-candidate.zip").stat().st_size}
        if limit_name == "archive"
        else {"max_central_directory_bytes": 256}
    )

    with pytest.raises(ValueError, match=rule_id):
        release_verifier._bounded_package_archive_preflight((first, second), **kwargs)
