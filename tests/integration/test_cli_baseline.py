"""CLI integration coverage for the Stage 02 synthetic path."""

from __future__ import annotations

import json

from arc3.cli import main


def test_games_list_synthetic_is_normalized_and_deterministic(capsys: object) -> None:
    assert main(["games", "list", "--mode", "synthetic", "--seed", "7"]) == 0

    output = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert output["schema"] == "arc3.games.v0.1"
    assert output["count"] == 1
    assert output["games"][0]["tags"] == ["synthetic", "deterministic"]


def test_play_cycle_emits_bounded_synthetic_scorecard(capsys: object) -> None:
    assert (
        main(
            [
                "play",
                "--mode",
                "synthetic",
                "--agent",
                "cycle",
                "--seed",
                "3",
                "--max-actions",
                "12",
            ]
        )
        == 0
    )

    output = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert output["schema"] == "arc3.play.v0.1"
    assert output["result"]["environment_actions"] <= 12
    assert output["result"]["receipt_count"] >= output["result"]["environment_actions"]
    assert output["result"]["scorecard"]["surface"] == "synthetic"


def test_smoke_evaluation_is_repeatable(capsys: object) -> None:
    arguments = [
        "evaluate",
        "--agent",
        "random",
        "--partition",
        "smoke",
        "--seeds",
        "2,5",
        "--max-actions",
        "20",
    ]
    assert main(arguments) == 0
    first = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert main(arguments) == 0
    second = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]

    assert first == second
    assert first["label"] == "synthetic"
    assert first["seeds"] == [2, 5]
