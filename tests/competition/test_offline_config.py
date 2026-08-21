"""Competition-mode tests for the non-negotiable offline boundary."""

from __future__ import annotations

import pytest

from arc3.config import ARC3Config, config_from_mapping, default_config, load_config
from arc3.errors import CompetitionIntegrityError
from arc3.types import EnvironmentMode


@pytest.mark.competition
def test_competition_mode_defaults_to_network_disabled() -> None:
    config = default_config(EnvironmentMode.COMPETITION, seed=2026)

    assert config.mode is EnvironmentMode.COMPETITION
    assert config.network_enabled is False
    assert config.seed == 2026


@pytest.mark.competition
@pytest.mark.parametrize(
    "factory",
    [
        lambda: ARC3Config(mode=EnvironmentMode.COMPETITION, network_enabled=True),
        lambda: ARC3Config.for_mode("competition", network_enabled=True),
        lambda: config_from_mapping({"mode": "competition", "network_enabled": True}),
        lambda: load_config(environ={"ARC3_MODE": "competition", "ARC3_NETWORK_ENABLED": "true"}),
    ],
)
def test_every_config_entrypoint_rejects_networked_competition_mode(factory: object) -> None:
    with pytest.raises(CompetitionIntegrityError, match="competition mode forbids network"):
        factory()  # type: ignore[operator]


@pytest.mark.competition
def test_online_network_default_does_not_backflow_into_competition() -> None:
    online = ARC3Config.for_mode(EnvironmentMode.ONLINE)
    competition = ARC3Config.for_mode(EnvironmentMode.COMPETITION)

    assert online.network_enabled is True
    assert competition.network_enabled is False
    assert online.mode is not competition.mode
