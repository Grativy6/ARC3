"""Required Stage 13 command-surface integration tests."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from arc3.cli import main


def test_evaluate_compare_report_and_verify_commands(tmp_path: Path, capsys: object) -> None:
    root = str(tmp_path)
    assert (
        main(
            [
                "evaluate",
                "--partition",
                "smoke",
                "--agents",
                "random,cycle,full",
                "--seeds",
                "7,11",
                "--max-actions",
                "1",
                "--timeout-seconds",
                "20",
                "--output-root",
                root,
                "--evaluation-id",
                "cli-smoke",
            ]
        )
        == 0
    )
    evaluation = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert evaluation["successful_policy_count"] >= 2
    assert evaluation["status"] == ("PASS" if evaluation["failure_count"] == 0 else "PARTIAL")

    reproduce = json.loads((tmp_path / "cli-smoke" / "reproduce.json").read_text())
    assert Path(reproduce["argv"][0]).resolve() == Path(sys.executable).resolve()
    assert reproduce["argv"][1:4] == ["-m", "arc3", "evaluate"]
    assert "--evaluation-id" not in reproduce["argv"]
    assert Path(reproduce["argv"][-1]).is_absolute()

    assert main(["compare", "--evaluation", "cli-smoke", "--output-root", root]) == 0
    comparison = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert comparison["evaluation_ids"] == ["cli-smoke"]
    assert {row["baseline_id"] for row in comparison["rows"]} == {"B0", "B1", "B2", "B3", "B4"}

    assert main(["report", "--evaluation", "cli-smoke", "--output-root", root]) == 0
    report = capsys.readouterr().out  # type: ignore[attr-defined]
    assert "NO_GENERALIZATION_CLAIM" in report
    assert "B4 full" in report

    assert main(["verify-artifacts", "--evaluation", "cli-smoke", "--output-root", root]) == 0
    verification = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert verification["verified"] is True

    (tmp_path / "cli-smoke" / "reproduce.json").unlink()
    assert main(["report", "--evaluation", "cli-smoke", "--output-root", root]) == 2
    assert "failed verification" in capsys.readouterr().err  # type: ignore[attr-defined]
    assert main(["compare", "--evaluation", "cli-smoke", "--output-root", root]) == 2
    assert "not sealed" in capsys.readouterr().err  # type: ignore[attr-defined]
