"""Narrow validator for the submission contract visible in pinned public sources."""

from __future__ import annotations

import importlib.metadata
import math
from importlib import import_module
from pathlib import Path
from typing import Protocol, cast

from arc3.packaging.models import PackagingError, ValidationReceipt

SUBMISSION_COLUMNS = ("row_id", "game_id", "end_of_game", "score")
PARQUET_BUILD_REQUIREMENT = "pyarrow==21.0.0"
_PUBLIC_CONTRACT_LIMITATION = (
    "The pinned public starter exposes the four-column example but no standalone official "
    "validator; the competition gateway remains authoritative."
)


class _ArrowSchema(Protocol):
    @property
    def names(self) -> list[str]: ...

    def field(self, name: str) -> object: ...


class _ArrowTable(Protocol):
    @property
    def schema(self) -> _ArrowSchema: ...

    @property
    def num_rows(self) -> int: ...

    def to_pylist(self) -> list[dict[str, object]]: ...


class _ArrowModule(Protocol):
    def array(self, values: list[object], *, type: object) -> object: ...

    def bool_(self) -> object: ...

    def float64(self) -> object: ...

    def string(self) -> object: ...

    def table(self, values: dict[str, object]) -> _ArrowTable: ...


class _ParquetModule(Protocol):
    def read_table(self, where: Path) -> _ArrowTable: ...

    def write_table(
        self,
        table: _ArrowTable,
        where: Path,
        *,
        compression: str,
        use_dictionary: bool,
        write_statistics: bool,
        version: str,
    ) -> None: ...


def _parquet_modules() -> tuple[_ArrowModule, _ParquetModule, str]:
    try:
        arrow = cast(_ArrowModule, import_module("pyarrow"))
        parquet = cast(_ParquetModule, import_module("pyarrow.parquet"))
        version = importlib.metadata.version("pyarrow")
    except (ImportError, ModuleNotFoundError, importlib.metadata.PackageNotFoundError) as error:
        raise PackagingError(
            "Parquet build validation requires "
            f"{PARQUET_BUILD_REQUIREMENT}; run the PowerShell wrapper or use "
            f"`python -m uv run --with {PARQUET_BUILD_REQUIREMENT} python "
            "scripts/prepare_kaggle_submission.py`."
        ) from error
    expected_version = PARQUET_BUILD_REQUIREMENT.partition("==")[2]
    if version != expected_version:
        raise PackagingError(
            "Parquet build validation requires exactly "
            f"{PARQUET_BUILD_REQUIREMENT}; found pyarrow=={version}"
        )
    return arrow, parquet, version


def write_validation_submission(path: Path) -> None:
    """Write a deterministic one-row Parquet artifact for offline package rehearsal."""

    arrow, parquet, _ = _parquet_modules()
    path.parent.mkdir(parents=True, exist_ok=True)
    table = arrow.table(
        {
            "row_id": arrow.array(["1_0"], type=arrow.string()),
            "game_id": arrow.array(["1"], type=arrow.string()),
            "end_of_game": arrow.array([True], type=arrow.bool_()),
            "score": arrow.array([1.0], type=arrow.float64()),
        }
    )
    parquet.write_table(
        table,
        path,
        compression="NONE",
        use_dictionary=False,
        write_statistics=False,
        version="2.6",
    )


def _field_type(schema: _ArrowSchema, name: str) -> str:
    field = schema.field(name)
    return str(getattr(field, "type", "unknown"))


def validate_submission_parquet(path: Path) -> ValidationReceipt:
    """Validate real Parquet structure against the pinned public four-column contract."""

    from arc3.packaging.util import sha256_file

    if not path.is_file():
        raise PackagingError(f"submission artifact does not exist: {path}")
    arrow_bytes = path.read_bytes()
    if len(arrow_bytes) < 12 or arrow_bytes[:4] != b"PAR1" or arrow_bytes[-4:] != b"PAR1":
        raise PackagingError("submission artifact is not a structurally recognizable Parquet file")

    _, parquet, version = _parquet_modules()
    try:
        table = parquet.read_table(path)
    except Exception as error:
        raise PackagingError(f"submission Parquet could not be decoded: {error}") from error

    names = tuple(table.schema.names)
    if names != SUBMISSION_COLUMNS:
        raise PackagingError(
            f"submission columns must be {SUBMISSION_COLUMNS!r} in order; received {names!r}"
        )
    if table.num_rows < 1:
        raise PackagingError("submission must contain at least one row")

    type_by_name = {name: _field_type(table.schema, name) for name in SUBMISSION_COLUMNS}
    if type_by_name["row_id"] not in {"string", "large_string"}:
        raise PackagingError("row_id must be an Arrow string column")
    if type_by_name["game_id"] not in {"string", "large_string"}:
        raise PackagingError("game_id must be an Arrow string column")
    if type_by_name["end_of_game"] not in {"bool", "boolean"}:
        raise PackagingError("end_of_game must be an Arrow boolean column")
    numeric_prefixes = ("int", "uint", "float", "double")
    if not type_by_name["score"].startswith(numeric_prefixes):
        raise PackagingError("score must be an Arrow numeric column")

    rows = table.to_pylist()
    row_ids: set[str] = set()
    for index, row in enumerate(rows):
        row_id = row.get("row_id")
        game_id = row.get("game_id")
        end_of_game = row.get("end_of_game")
        score = row.get("score")
        if not isinstance(row_id, str) or not row_id:
            raise PackagingError(f"row {index} has an invalid row_id")
        if row_id in row_ids:
            raise PackagingError(f"row_id is not unique: {row_id!r}")
        row_ids.add(row_id)
        if not isinstance(game_id, str) or not game_id:
            raise PackagingError(f"row {index} has an invalid game_id")
        if not isinstance(end_of_game, bool):
            raise PackagingError(f"row {index} has an invalid end_of_game")
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            raise PackagingError(f"row {index} has an invalid score")
        if isinstance(score, float) and not math.isfinite(score):
            raise PackagingError(f"row {index} has a non-finite score")

    return ValidationReceipt(
        status="PASS",
        validation_level="pinned-public-schema",
        artifact_sha256=sha256_file(path),
        artifact_size_bytes=path.stat().st_size,
        columns=names,
        rows=table.num_rows,
        parquet_engine=f"pyarrow=={version}",
        limitations=(_PUBLIC_CONTRACT_LIMITATION,),
    )
