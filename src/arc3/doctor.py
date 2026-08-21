"""Cross-platform, non-networking diagnostics for an ARC3 checkout."""

from __future__ import annotations

import importlib.util
import json
import platform
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from arc3.config import ARC3Config, config_hash, default_config
from arc3.types import EnvironmentMode, JSONValue


@dataclass(frozen=True, slots=True)
class DoctorCheck:
    """One bounded diagnostic with explicit required/optional status."""

    name: str
    passed: bool
    required: bool
    summary: str
    details: dict[str, JSONValue]

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "name": self.name,
            "passed": self.passed,
            "required": self.required,
            "summary": self.summary,
            "details": self.details,
        }


@dataclass(frozen=True, slots=True)
class DoctorReport:
    """Complete diagnostics without environment variables or secret values."""

    checks: tuple[DoctorCheck, ...]
    mode: EnvironmentMode
    config_hash: str

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks if check.required)

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "schema": "arc3.doctor.v0.1",
            "passed": self.passed,
            "mode": self.mode.value,
            "config_hash": self.config_hash,
            "checks": [check.to_dict() for check in self.checks],
        }


def _python_check() -> DoctorCheck:
    actual = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    passed = sys.version_info[:2] == (3, 12)
    return DoctorCheck(
        name="python",
        passed=passed,
        required=True,
        summary=("Python 3.12 active" if passed else f"Python 3.12 required; found {actual}"),
        details={"actual": actual, "required": "3.12.x"},
    )


def _config_check(config: ARC3Config) -> DoctorCheck:
    digest = str(config_hash(config))
    passed = digest.startswith("sha256:") and len(digest) == 71
    return DoctorCheck(
        name="configuration",
        passed=passed,
        required=True,
        summary="configuration canonicalized" if passed else "configuration hash invalid",
        details={"schema": config.schema, "hash": digest, "profile": config.profile},
    )


def _network_check(config: ARC3Config) -> DoctorCheck:
    passed = not (config.mode is EnvironmentMode.COMPETITION and config.network_enabled)
    status = "disabled" if not config.network_enabled else "enabled"
    return DoctorCheck(
        name="network-policy",
        passed=passed,
        required=True,
        summary=f"networking is {status} for {config.mode.value} mode",
        details={"network_enabled": config.network_enabled},
    )


def _filesystem_check() -> DoctorCheck:
    working_directory = Path.cwd()
    passed = working_directory.exists() and working_directory.is_dir()
    return DoctorCheck(
        name="working-directory",
        passed=passed,
        required=True,
        summary="working directory is readable" if passed else "working directory unavailable",
        details={"path": str(working_directory), "platform": platform.platform()},
    )


def _dependency_check(module: str, display_name: str) -> DoctorCheck:
    try:
        available = importlib.util.find_spec(module) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        available = False
    return DoctorCheck(
        name=f"optional-dependency:{module}",
        passed=available,
        required=False,
        summary=f"{display_name} {'available' if available else 'not installed'}",
        details={"module": module},
    )


def run_doctor(config: ARC3Config | None = None) -> DoctorReport:
    """Run local checks only; this function never probes the network."""

    selected = config or default_config()
    checks = (
        _python_check(),
        _config_check(selected),
        _network_check(selected),
        _filesystem_check(),
        _dependency_check("arc_agi", "official arc-agi toolkit"),
        _dependency_check("arcengine", "official arcengine models"),
        _dependency_check("agents", "official Agents framework"),
    )
    return DoctorReport(
        checks=checks,
        mode=selected.mode,
        config_hash=str(config_hash(selected)),
    )


def format_doctor_report(report: DoctorReport) -> str:
    """Render a compact human-readable report."""

    lines = [f"ARC3 doctor: {'PASS' if report.passed else 'FAIL'}"]
    for check in report.checks:
        if check.required:
            marker = "PASS" if check.passed else "FAIL"
        else:
            marker = "FOUND" if check.passed else "OPTIONAL"
        lines.append(f"[{marker}] {check.name}: {check.summary}")
    lines.append(f"config: {report.config_hash}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    """Standalone doctor entry point used by packaging and bootstrap scripts."""

    import argparse

    parser = argparse.ArgumentParser(prog="arc3-doctor", description=__doc__)
    parser.add_argument(
        "--mode", choices=[mode.value for mode in EnvironmentMode], default="synthetic"
    )
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(list(argv) if argv is not None else None)
    config = default_config(EnvironmentMode(args.mode), seed=args.seed)
    report = run_doctor(config)
    if args.as_json:
        print(json.dumps(report.to_dict(), sort_keys=True, separators=(",", ":")))
    else:
        print(format_doctor_report(report))
    return 0 if report.passed else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
