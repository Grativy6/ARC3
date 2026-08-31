from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest
from scripts.play_wise_scientist import (
    ROOT,
    _inside_checkout,
    _resume_wall_clock_extension_reason,
    _validate_authorization,
    build_parser,
)

from arc3.errors import ARC3ValidationError


def test_committed_development_authorization_is_valid_and_non_holdout() -> None:
    path = ROOT / "docs" / "evidence" / "003w-01-development-play-authorization.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    receipt = _validate_authorization(path, game_id=raw["game_id"])

    assert receipt["partition"] == "development"
    assert receipt["surface"] == "local-public"
    assert receipt["public_holdout_eligible"] is False
    assert receipt["gameplay_authorized"] is True


def test_development_authorization_tampering_fails_closed(tmp_path: Path) -> None:
    source = ROOT / "docs" / "evidence" / "003w-01-development-play-authorization.json"
    raw = json.loads(source.read_text(encoding="utf-8"))
    raw["partition"] = "public-holdout"
    path = tmp_path / "tampered.json"
    path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(ARC3ValidationError, match="hash mismatch"):
        _validate_authorization(path, game_id=raw["game_id"])


def test_runner_paths_must_remain_inside_checkout() -> None:
    with pytest.raises(ARC3ValidationError, match="inside the repository"):
        _inside_checkout(Path(ROOT.anchor), field="test path")


def test_runner_source_contains_no_selected_game_identity() -> None:
    source = (ROOT / "scripts" / "play_wise_scientist.py").read_text(encoding="utf-8")

    assert "ls20-" not in source
    assert "9607627b" not in source


def _parse_runner_arguments(*extra: str) -> argparse.Namespace:
    return build_parser().parse_args(
        [
            "--game",
            "test-game",
            "--seed",
            "1",
            "--frozen-commit",
            "1" * 40,
            "--authorization-receipt",
            "authorization.json",
            "--artifact-dir",
            "artifacts/test",
            "--environments-dir",
            "environments",
            "--recordings-dir",
            "recordings",
            *extra,
        ]
    )


def test_runner_accepts_explicit_resume_only_wall_clock_extension_reason() -> None:
    arguments = _parse_runner_arguments(
        "--resume",
        "--extend-wall-clock-on-resume",
        "--wall-clock-extension-reason",
        "  Continue a bounded observed-WIN attempt.  ",
        "--wall-clock-seconds",
        "86400",
    )

    assert _resume_wall_clock_extension_reason(arguments) == (
        "Continue a bounded observed-WIN attempt."
    )


@pytest.mark.parametrize(
    ("extra", "expected"),
    [
        (
            ("--wall-clock-extension-reason", "reason without opt-in"),
            "requires --extend-wall-clock-on-resume",
        ),
        (
            (
                "--extend-wall-clock-on-resume",
                "--wall-clock-extension-reason",
                "reason without resume",
            ),
            "requires --resume",
        ),
        (
            (
                "--resume",
                "--extend-wall-clock-on-resume",
            ),
            "nonempty reason",
        ),
        (
            (
                "--resume",
                "--extend-wall-clock-on-resume",
                "--wall-clock-extension-reason",
                "   ",
            ),
            "nonempty reason",
        ),
        (
            (
                "--resume",
                "--extend-wall-clock-on-resume",
                "--wall-clock-extension-reason",
                "x" * 501,
            ),
            "exceeds 500 characters",
        ),
    ],
)
def test_runner_rejects_implicit_or_unbounded_wall_clock_extension(
    extra: tuple[str, ...],
    expected: str,
) -> None:
    arguments = _parse_runner_arguments(*extra)

    with pytest.raises(ARC3ValidationError, match=expected):
        _resume_wall_clock_extension_reason(arguments)
