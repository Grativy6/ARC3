"""Cross-platform path and special-file checks for packaged ZIP members."""

from __future__ import annotations

import io
import stat
import zipfile

import pytest

from arc3.packaging import candidate as candidate_module
from arc3.packaging.models import PackagingError


def _member_archive(
    name: str,
    *,
    external_attr: int | None = None,
    create_system: int = 3,
) -> zipfile.ZipFile:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
        info.filename = name
        info.create_system = create_system
        if external_attr is not None:
            info.external_attr = external_attr
        archive.writestr(info, b"fixture")
    return zipfile.ZipFile(io.BytesIO(buffer.getvalue()))


@pytest.mark.competition
@pytest.mark.parametrize(
    ("member_name", "external_attr", "create_system"),
    (
        ("C:/escape.py", None, 3),
        ("C:escape.py", None, 3),
        ("agent/cache:stream.py", None, 3),
        ("//server/share/escape.py", None, 3),
        (r"agent\shadow.py", None, 3),
        ("src/arc3/../escape.py", None, 3),
        ("agent/./shadow.py", None, 3),
        ("agent/link.py", (stat.S_IFLNK | 0o777) << 16, 3),
        ("agent/fifo.py", (stat.S_IFIFO | 0o600) << 16, 3),
        ("agent/reparse.py", 0x400, 0),
    ),
)
def test_candidate_member_guard_rejects_cross_platform_unsafe_members(
    member_name: str,
    external_attr: int | None,
    create_system: int,
) -> None:
    with _member_archive(
        member_name,
        external_attr=external_attr,
        create_system=create_system,
    ) as archive:
        with pytest.raises(PackagingError, match=r"unsafe member|link or special member"):
            candidate_module._safe_unique_names(archive, label="fixture")


@pytest.mark.competition
def test_candidate_member_guard_accepts_canonical_regular_member() -> None:
    with _member_archive("src/arc3/__init__.py") as archive:
        assert candidate_module._safe_unique_names(archive, label="fixture") == (
            "src/arc3/__init__.py",
        )
