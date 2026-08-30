"""Produce a fail-closed, read-only Build 003 public-development prelaunch audit."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import subprocess
import sys
from collections import Counter
from collections.abc import Mapping, Sequence, Set
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

_BYTECODE_DISABLED_AT_STARTUP = sys.dont_write_bytecode
_ENVIRONMENT_NAMES_AT_PROCESS_START = frozenset(os.environ.keys())
ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "src"

SCHEMA = "arc3.build003.prelaunch-audit.v0.1"
_OBJECT_ID = re.compile(r"[0-9a-f]{40}")
_SHA256 = re.compile(r"sha256:[0-9a-f]{64}")
_CREDENTIAL_NAME_MARKERS = (
    "API_KEY",
    "COOKIE",
    "CREDENTIAL",
    "KAGGLE",
    "PASSWORD",
    "SECRET",
    "TOKEN",
)
_UPSTREAM_CONTROL_NAMES = frozenset({"OPERATION_MODE"})
_SOURCE_CONTROL_NAMES = frozenset({"PYTHONHOME"})
_PROHIBITED_EVALUATOR_OPTION_MARKERS = (
    "api-key",
    "credential",
    "password",
    "secret",
    "submission",
    "token",
)
_DEVELOPMENT_PARTITION = "development"
_EXPECTED_MANIFEST_RELATIVE_PATH = Path("docs/evaluation/public-game-partitions.v0.1.json")


class PrelaunchAuditError(RuntimeError):
    """A prelaunch claim could not be established without crossing its boundary."""


@dataclass(frozen=True, slots=True)
class AuditRequest:
    """Independent anchors and the exact prospective evaluator declaration."""

    source_root: Path
    expected_commit: str
    expected_tree: str
    expected_manifest_sha256: str
    expected_game_id: str
    expected_run_root: Path
    neutral_cwd: Path
    output: Path
    evaluator_argv: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SourceIdentity:
    """Validated identity of one exact detached Git source tree."""

    root: Path
    head: str
    tree: str


@dataclass(frozen=True, slots=True)
class ManifestCacheSnapshot:
    """Read-only manifest, SDK inventory, and target-byte projection."""

    manifest: dict[str, object]
    cache: dict[str, object]
    target_identity: dict[str, object]
    game_partitions: dict[str, str]


@dataclass(frozen=True, slots=True)
class ExposureSnapshot:
    """Canonical hash-chain summary and immutable byte identity."""

    receipt: dict[str, object]
    byte_length: int
    sha256: str


def _canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _require_stable_file(
    path: Path,
    *,
    expected_length: int,
    expected_sha256: str,
    label: str,
) -> None:
    content = path.read_bytes()
    if len(content) != expected_length or _sha256_bytes(content) != expected_sha256:
        raise PrelaunchAuditError(f"{label} changed during prelaunch audit")


def _seal(value: Mapping[str, object], *, hash_field: str) -> dict[str, object]:
    unsigned = {key: item for key, item in value.items() if key != hash_field}
    unsigned[hash_field] = _sha256_bytes(_canonical_json_bytes(unsigned))
    return unsigned


def _verify_seal(value: Mapping[str, object], *, hash_field: str) -> bool:
    expected = value.get(hash_field)
    unsigned = {key: item for key, item in value.items() if key != hash_field}
    return isinstance(expected, str) and expected == _sha256_bytes(_canonical_json_bytes(unsigned))


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _environment_names_now() -> frozenset[str]:
    """Return process environment names without reading any associated value."""

    return frozenset(os.environ.keys())


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _require_external(path: Path, *roots: Path, label: str) -> None:
    resolved = path.resolve()
    for root in roots:
        if _is_within(resolved, root.resolve()):
            raise PrelaunchAuditError(f"{label} must be external to {root.resolve()}")


def _classified_environment_names(
    names: Set[str],
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    normalized = {name.upper(): name for name in names}
    credential = tuple(
        sorted(
            original
            for upper, original in normalized.items()
            if any(marker in upper for marker in _CREDENTIAL_NAME_MARKERS)
        )
    )
    upstream = tuple(
        sorted(
            original
            for upper, original in normalized.items()
            if upper.startswith(("ARC_", "ARC3_")) or upper in _UPSTREAM_CONTROL_NAMES
        )
    )
    source_control = tuple(
        sorted(
            original
            for upper, original in normalized.items()
            if upper.startswith("GIT_") or upper in _SOURCE_CONTROL_NAMES
        )
    )
    return credential, upstream, source_control


def _require_sanitized_environment(
    names: Set[str],
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    classified = _classified_environment_names(names)
    if any(classified):
        credential, upstream, source_control = classified
        raise PrelaunchAuditError(
            "prelaunch process environment contains prohibited variable names: "
            f"credential={list(credential)!r}, upstream={list(upstream)!r}, "
            f"source_control={list(source_control)!r}"
        )
    return classified


def _git_text(root: Path, *arguments: str, returncodes: frozenset[int] = frozenset({0})) -> str:
    completed = subprocess.run(
        ("git", "--no-replace-objects", "-C", str(root), *arguments),
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    if completed.returncode not in returncodes:
        raise PrelaunchAuditError(
            f"git {' '.join(arguments)} failed with exit code {completed.returncode}"
        )
    return completed.stdout.strip()


def _source_identity(root: Path, *, expected_commit: str, expected_tree: str) -> SourceIdentity:
    resolved = root.resolve()
    if root.is_symlink() or not resolved.is_dir():
        raise PrelaunchAuditError("source root must be an existing non-symlink directory")
    top = Path(_git_text(resolved, "rev-parse", "--show-toplevel")).resolve()
    head = _git_text(resolved, "rev-parse", "HEAD")
    tree = _git_text(resolved, "rev-parse", "HEAD^{tree}")
    branch = _git_text(resolved, "rev-parse", "--abbrev-ref", "HEAD")
    status = _git_text(resolved, "status", "--porcelain=v1", "--untracked-files=all")
    if top != resolved:
        raise PrelaunchAuditError("source root is not the exact Git top level")
    if head != expected_commit or tree != expected_tree:
        raise PrelaunchAuditError("source HEAD/tree differs from the independently named identity")
    if branch != "HEAD":
        raise PrelaunchAuditError("prelaunch source must be detached")
    if status:
        raise PrelaunchAuditError("prelaunch source must be clean, including untracked files")
    return SourceIdentity(root=resolved, head=head, tree=tree)


def _prepare_exact_imports(source_root: Path) -> None:
    if "arc3" in sys.modules or "scripts.evaluate_public" in sys.modules:
        raise PrelaunchAuditError("ARC3/evaluator modules were imported before source validation")
    for import_root in (source_root, source_root / "src"):
        value = str(import_root)
        while value in sys.path:
            sys.path.remove(value)
    sys.path.insert(0, str(source_root / "src"))
    sys.path.insert(0, str(source_root))
    importlib.invalidate_caches()


def _module_file(module: object, *, label: str) -> Path:
    raw = getattr(module, "__file__", None)
    if not isinstance(raw, str) or not raw:
        raise PrelaunchAuditError(f"{label} does not expose a source file")
    return Path(raw).resolve()


def _import_bindings(source_root: Path) -> tuple[dict[str, object], object]:
    import arc3
    import arc3.evaluation.public as public_module
    import scripts.evaluate_public as evaluator_module
    from arc3.adapters.arc_agi import ARC_AGI_VERSION, ARCENGINE_VERSION

    expected = {
        "arc3": (source_root / "src/arc3/__init__.py").resolve(),
        "arc3.evaluation.public": (source_root / "src/arc3/evaluation/public.py").resolve(),
        "scripts.evaluate_public": (source_root / "scripts/evaluate_public.py").resolve(),
    }
    observed = {
        "arc3": _module_file(arc3, label="arc3"),
        "arc3.evaluation.public": _module_file(public_module, label="arc3.evaluation.public"),
        "scripts.evaluate_public": _module_file(evaluator_module, label="scripts.evaluate_public"),
    }
    if observed != expected or Path(evaluator_module.ROOT).resolve() != source_root:
        raise PrelaunchAuditError("imported ARC3/evaluator modules are not bound to exact source")

    try:
        installed_versions = {
            "arc-agi": importlib.metadata.version("arc-agi"),
            "arcengine": importlib.metadata.version("arcengine"),
        }
    except importlib.metadata.PackageNotFoundError as error:
        raise PrelaunchAuditError("pinned official SDK packages are unavailable") from error
    expected_versions = {"arc-agi": ARC_AGI_VERSION, "arcengine": ARCENGINE_VERSION}
    if installed_versions != expected_versions:
        raise PrelaunchAuditError("installed official SDK versions differ from pinned adapters")
    return (
        {
            "imports": {name: str(path) for name, path in observed.items()},
            "official_package_versions": installed_versions,
        },
        evaluator_module,
    )


def _parser_option_strings(parser: argparse.ArgumentParser) -> tuple[str, ...]:
    return tuple(sorted(option for action in parser._actions for option in action.option_strings))


def _parse_prospective_run(
    evaluator_module: object,
    request: AuditRequest,
) -> tuple[argparse.Namespace, dict[str, object], tuple[str, ...]]:
    build_parser = getattr(evaluator_module, "build_parser", None)
    if not callable(build_parser):
        raise PrelaunchAuditError("scripts.evaluate_public.build_parser is unavailable")
    parser = cast(argparse.ArgumentParser, build_parser())
    option_strings = _parser_option_strings(parser)
    prohibited = tuple(
        option
        for option in option_strings
        if any(marker in option.lower() for marker in _PROHIBITED_EVALUATOR_OPTION_MARKERS)
    )
    if prohibited:
        raise PrelaunchAuditError(
            f"prospective evaluator exposes credential/submission options: {list(prohibited)!r}"
        )
    try:
        args = parser.parse_args(list(request.evaluator_argv))
    except SystemExit as error:
        raise PrelaunchAuditError("prospective evaluator argv does not parse exactly") from error

    from arc3.errors import ARC3Error
    from arc3.evaluation.public import PublicEvaluationConfig

    path_fields = (
        "manifest",
        "environments_dir",
        "recordings_dir",
        "output_root",
        "exposure_ledger",
    )
    if any(not cast(Path, getattr(args, field)).is_absolute() for field in path_fields):
        raise PrelaunchAuditError("prospective evaluator paths must all be absolute")
    forbidden_declarations = (
        args.sealed_development_manifest,
        args.holdout_gate_receipt,
        args.holdout_gate_file_sha256,
        args.holdout_gate_core_hash,
        args.stage09_result,
        args.stage10_result,
        args.competition_integrity_receipt,
        args.verify,
    )
    if any(value is not None for value in forbidden_declarations):
        raise PrelaunchAuditError("development prelaunch cannot carry holdout/verification inputs")
    if (
        args.partition != _DEVELOPMENT_PARTITION
        or tuple(args.agents) != ("mechanical",)
        or tuple(args.game_ids or ()) != (request.expected_game_id,)
        or args.acquire_missing
        or args.allow_public_holdout
        or args.inventory_only
        or args.revalidate_online_metadata
        or args.hot_path_profile
        or args.python_allocation_tracing
        or not args.automatic_checkpointing
        or args.frozen_commit != request.expected_commit
        or args.evaluation_id is None
        or not args.milestone_id.startswith("build-003-")
    ):
        raise PrelaunchAuditError("prospective declaration is not the bounded Build 003 dev run")

    try:
        config = PublicEvaluationConfig(
            partition=args.partition,
            game_ids=args.game_ids,
            hot_path_profile=args.hot_path_profile,
            python_allocation_tracing=args.python_allocation_tracing,
            automatic_checkpointing=args.automatic_checkpointing,
            agents=args.agents,
            seeds=args.seeds,
            frozen_commit=args.frozen_commit,
            max_actions=args.max_actions,
            max_resets=args.max_resets,
            timeout_seconds=args.timeout_seconds,
            manifest_path=args.manifest,
            environments_dir=args.environments_dir,
            recordings_dir=args.recordings_dir,
            output_root=args.output_root,
            exposure_ledger=args.exposure_ledger,
            evaluation_id=args.evaluation_id,
            acquire_missing=args.acquire_missing,
            allow_public_holdout=args.allow_public_holdout,
            milestone_id=args.milestone_id,
        )
    except ARC3Error as error:
        raise PrelaunchAuditError(
            f"prospective evaluator declaration failed closed ({type(error).__name__})"
        ) from None
    run_root = (Path(args.output_root).resolve() / args.evaluation_id).resolve()
    if run_root != request.expected_run_root.resolve():
        raise PrelaunchAuditError("derived evaluator run root differs from expected run root")
    if Path(args.recordings_dir).resolve() != run_root / "official-recordings":
        raise PrelaunchAuditError("recordings directory must be inside the absent run root")
    if (
        Path(args.exposure_ledger).resolve()
        != Path(args.output_root).resolve() / "public-exposure.jsonl"
    ):
        raise PrelaunchAuditError("exposure ledger must be the canonical output-root ledger")
    return args, config.declaration(), prohibited


def _filesystem_cache_ids(environments_dir: Path) -> tuple[str, ...]:
    if environments_dir.is_symlink() or not environments_dir.is_dir():
        raise PrelaunchAuditError("public environment cache must be a non-symlink directory")
    identities: list[str] = []
    for stable_directory in sorted(environments_dir.iterdir(), key=lambda path: path.name):
        if stable_directory.is_symlink() or not stable_directory.is_dir():
            raise PrelaunchAuditError("public environment cache has an unexpected root entry")
        versions = sorted(stable_directory.iterdir(), key=lambda path: path.name)
        if len(versions) != 1 or versions[0].is_symlink() or not versions[0].is_dir():
            raise PrelaunchAuditError("public environment cache version layout is ambiguous")
        if not (versions[0] / "metadata.json").is_file():
            raise PrelaunchAuditError("cached public game is missing metadata.json")
        identities.append(f"{stable_directory.name}-{versions[0].name}")
    return tuple(sorted(identities))


def _manifest_cache_snapshot(
    *,
    manifest_path: Path,
    expected_manifest_sha256: str,
    environments_dir: Path,
    expected_game_id: str,
) -> ManifestCacheSnapshot:
    from arc3.errors import ARC3Error
    from arc3.evaluation.public import PublicPartitionManifest, inventory_local_assets

    try:
        manifest = PublicPartitionManifest.load(manifest_path)
        assets = inventory_local_assets(manifest, environments_dir)
    except (ARC3Error, OSError, ValueError) as error:
        raise PrelaunchAuditError(
            f"manifest/cache inventory failed closed ({type(error).__name__})"
        ) from None
    if manifest.digest != expected_manifest_sha256:
        raise PrelaunchAuditError("public partition manifest hash differs from expected")
    by_id = {entry.game_id: entry for entry in manifest.entries}
    target = by_id.get(expected_game_id)
    if target is None or target.partition != _DEVELOPMENT_PARTITION:
        raise PrelaunchAuditError("target game is not in the frozen development partition")

    expected_cached_ids = tuple(
        sorted(entry.game_id for entry in manifest.entries if entry.partition != "public-holdout")
    )
    actual_cached_ids = tuple(sorted(assets))
    filesystem_ids = _filesystem_cache_ids(environments_dir)
    if actual_cached_ids != expected_cached_ids or filesystem_ids != expected_cached_ids:
        raise PrelaunchAuditError("cache is not the exact frozen smoke/development inventory")
    holdout_ids = {entry.game_id for entry in manifest.games("public-holdout")}
    holdout_cached = tuple(sorted(holdout_ids.intersection(actual_cached_ids)))
    if holdout_cached:
        raise PrelaunchAuditError("public holdout assets are present in the local cache")
    target_identity = assets.get(expected_game_id)
    if target_identity is None:
        raise PrelaunchAuditError("target development asset is not cached")

    partition_counts = {
        partition: len(manifest.games(partition))
        for partition in ("development", "public-holdout", "smoke")
    }
    cache_counts = dict(Counter(by_id[game_id].partition for game_id in actual_cached_ids))
    target_manifest = {
        "assignment_hash": target.assignment_hash,
        "exposure": target.exposure,
        "game_id": target.game_id,
        "original_partition": target.original_partition,
        "partition": target.partition,
        "stable_name": target.stable_name,
    }
    return ManifestCacheSnapshot(
        manifest={
            "bytes": manifest.path.stat().st_size,
            "entry_count": len(manifest.entries),
            "partition_counts": partition_counts,
            "path": str(manifest.path),
            "sha256": manifest.digest,
            "target": target_manifest,
        },
        cache={
            "cached_entry_count": len(actual_cached_ids),
            "filesystem_inventory_matches_manifest_entries": True,
            "holdout_cached_count": 0,
            "partition_counts": cache_counts,
            "root": str(environments_dir.resolve()),
        },
        target_identity=target_identity.to_dict(),
        game_partitions={entry.game_id: entry.partition for entry in manifest.entries},
    )


def _target_identity(
    *, manifest_path: Path, environments_dir: Path, game_id: str
) -> dict[str, object]:
    from arc3.errors import ARC3Error
    from arc3.evaluation.public import PublicPartitionManifest, local_asset_identity

    try:
        manifest = PublicPartitionManifest.load(manifest_path)
        entry = next(
            (candidate for candidate in manifest.entries if candidate.game_id == game_id),
            None,
        )
    except (ARC3Error, OSError, ValueError) as error:
        raise PrelaunchAuditError(
            f"target identity manifest load failed closed ({type(error).__name__})"
        ) from None
    if entry is None:
        raise PrelaunchAuditError("target disappeared from the frozen manifest")
    try:
        identity = local_asset_identity(environments_dir, entry)
    except (ARC3Error, OSError, ValueError) as error:
        raise PrelaunchAuditError(
            f"target identity check failed closed ({type(error).__name__})"
        ) from None
    if identity is None:
        raise PrelaunchAuditError("target asset disappeared during the audit")
    return identity.to_dict()


def _exposure_snapshot(
    path: Path,
    *,
    game_partitions: Mapping[str, str],
) -> ExposureSnapshot:
    from arc3.errors import ARC3Error
    from arc3.evaluation.public import PublicExposureLedger

    if path.is_symlink() or not path.is_file():
        raise PrelaunchAuditError("canonical exposure ledger is unavailable")
    before = path.read_bytes()
    try:
        events = PublicExposureLedger(path).events()
    except (ARC3Error, OSError, ValueError) as error:
        raise PrelaunchAuditError(
            f"exposure ledger chain validation failed closed ({type(error).__name__})"
        ) from None
    if not events:
        raise PrelaunchAuditError("canonical exposure ledger must not be empty")
    partitions: Counter[str] = Counter()
    holdout_count = 0
    for event in events:
        payload = event.get("payload")
        if not isinstance(payload, dict):
            raise PrelaunchAuditError("exposure event payload is not an object")
        partition = payload.get("partition")
        game_id = payload.get("game_id")
        if not isinstance(partition, str) or not isinstance(game_id, str):
            raise PrelaunchAuditError("exposure event omits partition/game identity")
        actual_partition = game_partitions.get(game_id)
        if partition == "public-holdout" or actual_partition == "public-holdout":
            holdout_count += 1
        if partition != _DEVELOPMENT_PARTITION or actual_partition != _DEVELOPMENT_PARTITION:
            raise PrelaunchAuditError("exposure ledger contains a non-development event")
        partitions[partition] += 1
    digest = _sha256_bytes(before)
    return ExposureSnapshot(
        receipt={
            "bytes": len(before),
            "canonical_chain_verified": True,
            "event_count": len(events),
            "holdout_event_count": holdout_count,
            "partition_counts": dict(sorted(partitions.items())),
            "path": str(path.resolve()),
            "sha256": digest,
            "tail_event_hash": events[-1]["event_hash"],
        },
        byte_length=len(before),
        sha256=digest,
    )


def _dotenv_candidates(*roots: Path) -> tuple[str, ...]:
    candidates: list[str] = []
    names = (".env", ".env.development", ".env.local", ".env.production", ".env.test")
    for root in roots:
        for name in names:
            candidate = root / name
            if candidate.exists() or candidate.is_symlink():
                candidates.append(str(candidate.resolve()))
        kaggle = root / ".kaggle" / "kaggle.json"
        if kaggle.exists() or kaggle.is_symlink():
            candidates.append(str(kaggle.resolve()))
    return tuple(sorted(set(candidates)))


def _directory_entries(path: Path) -> tuple[str, ...]:
    return tuple(sorted(entry.name for entry in path.iterdir()))


def _validate_request_paths(request: AuditRequest) -> tuple[Path, Path, Path, Path]:
    source_root = request.source_root.resolve()
    neutral_cwd = request.neutral_cwd.resolve()
    run_root = request.expected_run_root.resolve()
    output = request.output.resolve()
    if Path.cwd().resolve() != neutral_cwd:
        raise PrelaunchAuditError("audit must launch from the declared neutral working directory")
    if request.neutral_cwd.is_symlink() or not neutral_cwd.is_dir():
        raise PrelaunchAuditError(
            "neutral working directory must be an existing non-symlink directory"
        )
    if _directory_entries(neutral_cwd):
        raise PrelaunchAuditError("neutral working directory must be empty before audit")
    if run_root.exists() or run_root.is_symlink():
        raise PrelaunchAuditError("prospective run root must be absent before audit")
    if output.exists() or output.is_symlink():
        raise PrelaunchAuditError("prelaunch audit output already exists")
    _require_external(neutral_cwd, source_root, label="neutral working directory")
    _require_external(run_root, source_root, neutral_cwd, label="prospective run root")
    _require_external(output, source_root, neutral_cwd, run_root, label="audit output")
    return source_root, neutral_cwd, run_root, output


def produce_audit(
    request: AuditRequest,
    *,
    environment_names: Set[str],
    observed_at: str,
) -> dict[str, object]:
    """Produce one receipt without calling an evaluator or constructing a game session."""

    if not _BYTECODE_DISABLED_AT_STARTUP:
        raise PrelaunchAuditError("prelaunch audit requires Python -B at process startup")
    if not _OBJECT_ID.fullmatch(request.expected_commit) or not _OBJECT_ID.fullmatch(
        request.expected_tree
    ):
        raise PrelaunchAuditError("expected commit/tree must be full lowercase Git object IDs")
    if not _SHA256.fullmatch(request.expected_manifest_sha256):
        raise PrelaunchAuditError("expected manifest hash must be canonical sha256")
    if not request.expected_game_id or request.expected_game_id != request.expected_game_id.strip():
        raise PrelaunchAuditError("expected game ID must be non-empty and normalized")
    _require_sanitized_environment(environment_names)
    source_root, neutral_cwd, run_root, _output = _validate_request_paths(request)
    if source_root != ROOT:
        raise PrelaunchAuditError("producer script is not executing from the named source root")

    source_before = _source_identity(
        source_root,
        expected_commit=request.expected_commit,
        expected_tree=request.expected_tree,
    )
    dotenv_candidates = _dotenv_candidates(source_root, neutral_cwd)
    if dotenv_candidates:
        raise PrelaunchAuditError("credential-bearing dotenv/Kaggle candidate path is present")

    _prepare_exact_imports(source_root)
    import_receipt, evaluator_module = _import_bindings(source_root)
    args, declaration, prohibited_options = _parse_prospective_run(evaluator_module, request)
    manifest_path = Path(args.manifest).resolve()
    expected_manifest_path = (source_root / _EXPECTED_MANIFEST_RELATIVE_PATH).resolve()
    if manifest_path != expected_manifest_path:
        raise PrelaunchAuditError("prospective manifest is not the exact checked-in manifest")
    environments_dir = Path(args.environments_dir).resolve()
    exposure_ledger = Path(args.exposure_ledger).resolve()
    _require_external(environments_dir, source_root, neutral_cwd, run_root, label="cache root")
    _require_external(exposure_ledger, source_root, neutral_cwd, run_root, label="exposure ledger")

    inventory = _manifest_cache_snapshot(
        manifest_path=manifest_path,
        expected_manifest_sha256=request.expected_manifest_sha256,
        environments_dir=environments_dir,
        expected_game_id=request.expected_game_id,
    )
    exposure_before = _exposure_snapshot(
        exposure_ledger,
        game_partitions=inventory.game_partitions,
    )
    target_after = _target_identity(
        manifest_path=manifest_path,
        environments_dir=environments_dir,
        game_id=request.expected_game_id,
    )
    if target_after != inventory.target_identity:
        raise PrelaunchAuditError("target cache bytes changed during prelaunch audit")
    _require_stable_file(
        exposure_ledger,
        expected_length=exposure_before.byte_length,
        expected_sha256=exposure_before.sha256,
        label="exposure ledger",
    )
    _require_stable_file(
        manifest_path,
        expected_length=cast(int, inventory.manifest["bytes"]),
        expected_sha256=request.expected_manifest_sha256,
        label="public partition manifest",
    )
    if run_root.exists() or run_root.is_symlink():
        raise PrelaunchAuditError("prospective run root appeared during prelaunch audit")
    if _directory_entries(neutral_cwd):
        raise PrelaunchAuditError("neutral working directory changed during prelaunch audit")
    _require_sanitized_environment(_environment_names_now())
    source_after = _source_identity(
        source_root,
        expected_commit=request.expected_commit,
        expected_tree=request.expected_tree,
    )

    cache = dict(inventory.cache)
    cache["target_identity"] = inventory.target_identity
    cache["target_stable_during_audit"] = True
    exposure = dict(exposure_before.receipt)
    exposure["stable_during_audit"] = True
    manifest_receipt = dict(inventory.manifest)
    manifest_receipt["stable_during_audit"] = True
    receipt: dict[str, object] = {
        "audit_mode": "read-only-parser-sdk-inventory",
        "boundaries": {
            "acquisition_attempts": 0,
            "credential_values_inspected": False,
            "credential_values_used": False,
            "environment_actions_issued": 0,
            "environment_sessions_constructed": 0,
            "evaluator_called": False,
            "game_source_semantically_inspected": False,
            "holdout_accessed": False,
            "network_requests_issued": 0,
            "official_submission_performed": False,
        },
        "cache": cache,
        "exposure_ledger": exposure,
        "manifest": manifest_receipt,
        "observed_at": observed_at,
        "prospective_run": {
            "acquire_missing": False,
            "allow_holdout": False,
            "allow_public_holdout": False,
            "argv": list(request.evaluator_argv),
            "credential_environment_names_at_process_start": [],
            "credential_environment_names_present": [],
            "credential_or_submission_parser_options": list(prohibited_options),
            "credential_values_inspected": False,
            "credential_values_used": False,
            "dotenv_candidate_paths_present": list(dotenv_candidates),
            "environment_actions_issued": 0,
            "evaluation_id": args.evaluation_id,
            "evaluator_called": False,
            "matching_exact_paths": [],
            "module": "scripts.evaluate_public",
            "network_mode": declaration["network_mode"],
            "parsed_declaration": declaration,
            "revalidate_online_metadata": False,
            "run_root": str(run_root),
            "run_root_absent_before_and_after": True,
            "selected_game_ids": [request.expected_game_id],
            "source_control_environment_names_at_process_start": [],
            "submission_requested": False,
            "surface": declaration["surface"],
            "upstream_control_names_at_process_start": [],
            "upstream_control_names_present": [],
            "working_directory": str(neutral_cwd),
            "working_directory_entries_after": [],
            "working_directory_entries_before": [],
            "working_directory_isolated_from_source": True,
        },
        "schema": SCHEMA,
        "source": {
            "bytecode_writes_disabled_at_startup": _BYTECODE_DISABLED_AT_STARTUP,
            "clean_after_import_and_audit": source_after == source_before,
            "clean_before_import": True,
            "clone": str(source_before.root),
            "detached": True,
            "head": source_before.head,
            **import_receipt,
            "python": str(Path(sys.executable).resolve()),
            "python_version": platform.python_version(),
            "tree": source_before.tree,
        },
        "status": "PASS",
    }
    sealed = _seal(receipt, hash_field="receipt_hash")
    if not _verify_seal(sealed, hash_field="receipt_hash"):
        raise PrelaunchAuditError("canonical prelaunch receipt self-hash failed")
    return sealed


def _write_exclusive(path: Path, value: object) -> None:
    if path.exists() or path.is_symlink():
        raise PrelaunchAuditError("prelaunch audit output already exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = _canonical_json_bytes(value)
    with path.open("xb") as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--expected-tree", required=True)
    parser.add_argument("--expected-manifest-sha256", required=True)
    parser.add_argument("--expected-game-id", required=True)
    parser.add_argument("--expected-run-root", type=Path, required=True)
    parser.add_argument("--neutral-cwd", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("evaluator_argv", nargs=argparse.REMAINDER)
    return parser


def _request(namespace: argparse.Namespace) -> AuditRequest:
    evaluator_argv = tuple(cast(list[str], namespace.evaluator_argv))
    if evaluator_argv and evaluator_argv[0] == "--":
        evaluator_argv = evaluator_argv[1:]
    if not evaluator_argv:
        raise PrelaunchAuditError("exact prospective scripts.evaluate_public argv is required")
    return AuditRequest(
        source_root=namespace.source_root,
        expected_commit=namespace.expected_commit,
        expected_tree=namespace.expected_tree,
        expected_manifest_sha256=namespace.expected_manifest_sha256,
        expected_game_id=namespace.expected_game_id,
        expected_run_root=namespace.expected_run_root,
        neutral_cwd=namespace.neutral_cwd,
        output=namespace.output,
        evaluator_argv=evaluator_argv,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    try:
        request = _request(parser.parse_args(argv))
        receipt = produce_audit(
            request,
            environment_names=_ENVIRONMENT_NAMES_AT_PROCESS_START,
            observed_at=_utc_now(),
        )
        _write_exclusive(request.output.resolve(), receipt)
    except (OSError, PrelaunchAuditError, subprocess.SubprocessError, ValueError) as error:
        failure = {
            "schema": "arc3.build003.prelaunch-audit-error.v0.1",
            "status": "FAILED_INFRASTRUCTURE",
            "kind": type(error).__name__,
            "message": str(error)[:500],
        }
        sys.stdout.buffer.write(_canonical_json_bytes(failure))
        return 2
    file_hash = _sha256_file(request.output.resolve())
    sys.stdout.write(f"PASS {request.output.resolve()} {file_hash} {receipt['receipt_hash']}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
