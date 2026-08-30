from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts.play_wise_scientist import ROOT, _inside_checkout, _validate_authorization

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
