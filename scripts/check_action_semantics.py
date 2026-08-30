"""Reject unjustified raw-action semantics in ARC3 production policy code.

The official action names are wire handles, not gameplay meanings.  This
scanner is deliberately separate from the broader competition-integrity scan:
it looks for fixed cardinal maps, name-based undo/selection assumptions, and
game-keyed action scripts while narrowly excluding adapter and evaluator
machinery.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from arc3.evaluation.artifacts import canonical_json_bytes, seal_object, sha256_file
from arc3.integrity import load_public_identifiers

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "docs" / "evaluation" / "public-game-partitions.v0.1.json"
PRODUCTION_DIRECTORIES = (
    "policy",
    "exploration",
    "mechanics",
    "planning",
    "hypotheses",
    "goals",
    "perception",
    "world_model",
)
ALLOWLISTED_FIXTURE_PATHS = frozenset(
    {
        "src/arc3/goals/evaluation.py",
        "src/arc3/perception/benchmark.py",
        "src/arc3/planning/evaluation.py",
        "src/arc3/world_model/benchmark.py",
    }
)

_ACTION_RE = re.compile(r"\b(?:ACTION[1-7])\b", re.IGNORECASE)
_DIRECTION_RE = re.compile(
    r"\b(?:up|down|left|right|north|south|east|west|directional)\b",
    re.IGNORECASE,
)
_UNDO_RE = re.compile(r"\b(?:undo|restore|revert)\w*\b", re.IGNORECASE)
_COORDINATE_SEMANTIC_RE = re.compile(
    r"\b(?:select|attach|toggle|transform|target|progress)\w*\b",
    re.IGNORECASE,
)
_SCRIPT_TARGET_RE = re.compile(
    r"(?:solution|walkthrough|game[_-]?plan|game[_-]?script|"
    r"known(?:[_-]?game)?[_-]?(?:plan|actions)|"
    r"action[_-]?sequence|public[_-]?plan|level[_-]?plan)",
    re.IGNORECASE,
)
_GAME_ID_SHAPE = re.compile(r"\b[a-z0-9]{2,16}-[0-9a-f]{8}\b", re.ASCII)
_CARDINAL_VECTORS = frozenset({(-1, 0), (1, 0), (0, -1), (0, 1)})


@dataclass(frozen=True, slots=True, order=True)
class ActionSemanticFinding:
    """One deterministic, non-secret static finding."""

    path: str
    line: int
    column: int
    rule_id: str
    message: str
    evidence_hash: str

    def to_dict(self) -> dict[str, object]:
        return {
            "column": self.column,
            "evidence_hash": self.evidence_hash,
            "line": self.line,
            "message": self.message,
            "path": self.path,
            "rule_id": self.rule_id,
        }


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def discover_action_semantic_files(root: Path) -> tuple[Path, ...]:
    """Return the frozen production scope, excluding named evaluator fixtures."""

    repository = root.resolve()
    files: list[Path] = []
    for directory in PRODUCTION_DIRECTORIES:
        candidate = repository / "src" / "arc3" / directory
        if not candidate.is_dir():
            continue
        files.extend(path for path in candidate.rglob("*.py") if path.is_file())
    return tuple(
        path
        for path in sorted(set(files))
        if _relative(repository, path) not in ALLOWLISTED_FIXTURE_PATHS
        and "__pycache__" not in path.parts
    )


def _source_segment(source: str, node: ast.AST) -> str:
    return ast.get_source_segment(source, node) or ""


def _local_statement_segment(source: str, node: ast.stmt) -> str:
    """Return only the statement-local expression, excluding nested bodies.

    ``ast.get_source_segment`` on a compound statement includes every nested
    statement.  That made an ACTION6 availability check inherit unrelated
    words such as ``target`` from a large observation-driven body.  Child
    statements are visited independently, so scanning only the header keeps
    direct name-based assumptions visible without manufacturing parent-body
    findings.
    """

    if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
        if isinstance(node.value.value, str):
            return ""
    if isinstance(node, (ast.If, ast.While, ast.Assert)):
        return _source_segment(source, node.test)
    if isinstance(node, (ast.For, ast.AsyncFor)):
        return " ".join((_source_segment(source, node.target), _source_segment(source, node.iter)))
    if isinstance(node, (ast.With, ast.AsyncWith)):
        return " ".join(_source_segment(source, item.context_expr) for item in node.items)
    if isinstance(node, ast.Match):
        return _source_segment(source, node.subject)
    if isinstance(node, (ast.Try, ast.TryStar)):
        return ""
    return _source_segment(source, node)


def _action_tokens(node: ast.AST) -> tuple[str, ...]:
    tokens: set[str] = set()
    for item in ast.walk(node):
        if isinstance(item, ast.Attribute) and _ACTION_RE.fullmatch(item.attr):
            tokens.add(item.attr.upper())
        elif isinstance(item, ast.Constant) and isinstance(item.value, str):
            tokens.update(match.group(0).upper() for match in _ACTION_RE.finditer(item.value))
    return tuple(sorted(tokens))


def _literal_vector(node: ast.AST) -> tuple[int, int] | None:
    if not isinstance(node, (ast.Tuple, ast.List)) or len(node.elts) != 2:
        return None
    values: list[int] = []
    for item in node.elts:
        try:
            value = ast.literal_eval(item)
        except (ValueError, TypeError):
            return None
        if isinstance(value, bool) or not isinstance(value, int):
            return None
        values.append(value)
    return values[0], values[1]


def _is_action_node(node: ast.AST) -> bool:
    return bool(_action_tokens(node))


def _target_names(node: ast.AST) -> tuple[str, ...]:
    names: set[str] = set()
    for item in ast.walk(node):
        if isinstance(item, ast.Name):
            names.add(item.id)
        elif isinstance(item, ast.Attribute):
            names.add(item.attr)
    return tuple(sorted(names))


def _finding(
    *,
    root: Path,
    path: Path,
    node: ast.AST,
    rule_id: str,
    message: str,
    source: str,
) -> ActionSemanticFinding:
    evidence = _source_segment(source, node).strip().encode("utf-8")
    return ActionSemanticFinding(
        path=_relative(root, path),
        line=max(1, getattr(node, "lineno", 1)),
        column=max(0, getattr(node, "col_offset", 0)),
        rule_id=rule_id,
        message=message,
        evidence_hash=f"sha256:{hashlib.sha256(evidence).hexdigest()}",
    )


def _scan_tree(
    *,
    root: Path,
    path: Path,
    source: str,
    public_identifiers: frozenset[str],
) -> tuple[ActionSemanticFinding, ...]:
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as error:
        pseudo = ast.Pass(lineno=max(1, error.lineno or 1), col_offset=max(0, error.offset or 1))
        return (
            _finding(
                root=root,
                path=path,
                node=pseudo,
                rule_id="unparseable-production-source",
                message="production source cannot be parsed for action-semantic assurance",
                source=source,
            ),
        )

    findings: set[ActionSemanticFinding] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values, strict=True):
                if key is None:
                    continue
                if _is_action_node(key) and _literal_vector(value) in _CARDINAL_VECTORS:
                    findings.add(
                        _finding(
                            root=root,
                            path=path,
                            node=node,
                            rule_id="raw-action-to-cardinal-vector",
                            message="raw action handle is assigned a fixed cardinal vector",
                            source=source,
                        )
                    )
                if _literal_vector(key) in _CARDINAL_VECTORS and _is_action_node(value):
                    findings.add(
                        _finding(
                            root=root,
                            path=path,
                            node=node,
                            rule_id="cardinal-vector-to-raw-action",
                            message="cardinal vector is resolved through a fixed raw action handle",
                            source=source,
                        )
                    )
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    if key.value in public_identifiers and len(_action_tokens(value)) >= 2:
                        findings.add(
                            _finding(
                                root=root,
                                path=path,
                                node=node,
                                rule_id="public-game-action-table",
                                message="public game identity keys an action sequence or table",
                                source=source,
                            )
                        )

        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.NamedExpr)):
            targets: Iterable[ast.AST]
            if isinstance(node, ast.Assign):
                targets = node.targets
            else:
                targets = (node.target,)
            target_text = " ".join(name for target in targets for name in _target_names(target))
            if _SCRIPT_TARGET_RE.search(target_text) and len(_action_tokens(node)) >= 2:
                findings.add(
                    _finding(
                        root=root,
                        path=path,
                        node=node,
                        rule_id="game-specific-action-table",
                        message="solution-shaped production variable contains a raw action sequence",
                        source=source,
                    )
                )

        if isinstance(node, ast.stmt) and not isinstance(
            node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef, ast.Module)
        ):
            segment = _local_statement_segment(source, node)
            local_tree: ast.AST
            try:
                local_tree = ast.parse(segment) if segment else ast.Module(body=[], type_ignores=[])
            except SyntaxError:
                local_tree = node
            tokens = set(_action_tokens(local_tree))
            if tokens and _DIRECTION_RE.search(segment.replace("_", " ")):
                findings.add(
                    _finding(
                        root=root,
                        path=path,
                        node=node,
                        rule_id="raw-action-direction-label",
                        message="raw action handle is paired with a named cardinal direction",
                        source=source,
                    )
                )
            if "ACTION7" in tokens and _UNDO_RE.search(segment):
                findings.add(
                    _finding(
                        root=root,
                        path=path,
                        node=node,
                        rule_id="action7-name-based-undo",
                        message="ACTION7 is coupled to undo or restore semantics by identifier",
                        source=source,
                    )
                )
            if "ACTION6" in tokens and _COORDINATE_SEMANTIC_RE.search(segment):
                findings.add(
                    _finding(
                        root=root,
                        path=path,
                        node=node,
                        rule_id="action6-name-based-interaction",
                        message="ACTION6 is coupled to gameplay semantics beyond coordinate arity",
                        source=source,
                    )
                )

        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            constant_value = node.value
            if constant_value in public_identifiers or _GAME_ID_SHAPE.fullmatch(constant_value):
                findings.add(
                    _finding(
                        root=root,
                        path=path,
                        node=node,
                        rule_id="game-identifier-in-production-policy",
                        message="game-shaped or manifest-listed identity appears in production policy",
                        source=source,
                    )
                )
    return tuple(sorted(findings))


def scan_action_semantics(
    root: Path,
    *,
    files: Sequence[Path] | None = None,
    manifest: Path | None = None,
) -> tuple[ActionSemanticFinding, ...]:
    """Scan production source using only local static inputs."""

    repository = root.resolve()
    selected = discover_action_semantic_files(repository) if files is None else tuple(files)
    manifest_path = (manifest or repository / DEFAULT_MANIFEST.relative_to(ROOT)).resolve()
    public = load_public_identifiers(manifest_path)
    findings: list[ActionSemanticFinding] = []
    for path in sorted(set(item.resolve() for item in selected)):
        findings.extend(
            _scan_tree(
                root=repository,
                path=path,
                source=path.read_text(encoding="utf-8"),
                public_identifiers=frozenset(public.identifiers),
            )
        )
    return tuple(sorted(set(findings)))


def build_action_semantics_receipt(
    root: Path,
    *,
    files: Sequence[Path] | None = None,
    manifest: Path | None = None,
) -> dict[str, object]:
    repository = root.resolve()
    selected = discover_action_semantic_files(repository) if files is None else tuple(files)
    manifest_path = (manifest or repository / DEFAULT_MANIFEST.relative_to(ROOT)).resolve()
    findings = scan_action_semantics(repository, files=selected, manifest=manifest_path)
    body: dict[str, object] = {
        "allowlisted_fixture_paths": sorted(ALLOWLISTED_FIXTURE_PATHS),
        "checks": {
            "action6_identity_assumption_absent": not any(
                item.rule_id == "action6-name-based-interaction" for item in findings
            ),
            "action7_identity_assumption_absent": not any(
                item.rule_id == "action7-name-based-undo" for item in findings
            ),
            "fixed_cardinal_semantics_absent": not any(
                item.rule_id
                in {
                    "raw-action-to-cardinal-vector",
                    "cardinal-vector-to-raw-action",
                    "raw-action-direction-label",
                }
                for item in findings
            ),
            "game_specific_tables_absent": not any(
                item.rule_id
                in {
                    "public-game-action-table",
                    "game-specific-action-table",
                    "game-identifier-in-production-policy",
                }
                for item in findings
            ),
        },
        "finding_count": len(findings),
        "findings": [item.to_dict() for item in findings],
        "manifest": {
            "path": _relative(repository, manifest_path),
            "sha256": sha256_file(manifest_path),
        },
        "network_enabled": False,
        "passed": not findings,
        "scope": [_relative(repository, path) for path in sorted(set(selected))],
        "schema": "arc3.build-001.action-semantics-static.v0.1",
    }
    return seal_object(body, hash_field="receipt_hash")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    try:
        receipt = build_action_semantics_receipt(
            args.root,
            manifest=args.manifest,
        )
    except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError) as error:
        print(f"action semantics scan refused: {type(error).__name__}: {error}", file=sys.stderr)
        return 2
    raw = canonical_json_bytes(receipt)
    if args.output is not None:
        from arc3.evaluation.artifacts import atomic_write_json

        atomic_write_json(args.output, receipt)
    sys.stdout.buffer.write(raw + b"\n")
    return 0 if receipt["passed"] is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
