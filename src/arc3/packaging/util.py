"""Small deterministic serialization and archive helpers."""

from __future__ import annotations

import hashlib
import json
import zipfile
from collections.abc import Mapping
from pathlib import Path

from arc3.packaging.models import PackagingError
from arc3.types import JSONValue

_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


def sha256_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def canonical_json_bytes(value: Mapping[str, JSONValue]) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def write_bytes_atomic(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(value)
    temporary.replace(path)


def deterministic_zip_bytes(members: Mapping[str, bytes]) -> bytes:
    """Build a byte-identical ZIP for an identical mapping."""

    import io

    buffer = io.BytesIO()
    with zipfile.ZipFile(
        buffer,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
        strict_timestamps=True,
    ) as archive:
        for name in sorted(members):
            path = Path(name)
            if path.is_absolute() or ".." in path.parts or "\\" in name:
                raise PackagingError(f"unsafe archive member: {name!r}")
            info = zipfile.ZipInfo(filename=name, date_time=_ZIP_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(
                info, members[name], compress_type=zipfile.ZIP_DEFLATED, compresslevel=9
            )
    return buffer.getvalue()
