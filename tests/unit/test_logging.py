"""Tests for structured JSON logs and recursive secret redaction."""

from __future__ import annotations

import io
import json
import re

from arc3.logging import REDACTED, configure_structured_logger, log_event, redact


def test_redact_recurses_through_keys_values_and_cycles() -> None:
    cyclic: list[object] = []
    cyclic.append(cyclic)
    value = {
        "api_key": "plain-api-value",
        "nested": {
            "Authorization": "Bearer abcdefghijklmnop",
            "message": "token sk-proj-abcdefghijklmnop leaked",
            "url": "https://person:password@example.test/path",
            "explicit": "prefix custom-secret suffix",
        },
        "bytes": b"not printable",
        "cycle": cyclic,
    }

    result = redact(value, extra_secrets=("custom-secret",))
    serialized = json.dumps(result, sort_keys=True)

    assert isinstance(result, dict)
    assert result["api_key"] == REDACTED
    assert result["bytes"] == "<bytes:13>"
    assert result["cycle"] == ["<cycle>"]
    for secret in (
        "plain-api-value",
        "abcdefghijklmnop",
        "password",
        "custom-secret",
    ):
        assert secret not in serialized


def test_structured_logger_emits_one_canonical_json_object_with_redacted_fields() -> None:
    stream = io.StringIO()
    logger = configure_structured_logger(
        "arc3.tests.structured",
        stream=stream,
        extra_secrets=("sentinel-secret",),
    )

    log_event(
        logger,
        "adapter.ready sentinel-secret",
        run_id="run-1",
        auth_token="sentinel-secret",
        observation={"shape": [64, 64]},
    )

    lines = stream.getvalue().splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["schema"] == "arc3.log.v0.1"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "arc3.tests.structured"
    assert payload["event"] == f"adapter.ready {REDACTED}"
    assert payload["fields"] == {
        "auth_token": REDACTED,
        "observation": {"shape": [64, 64]},
        "run_id": "run-1",
    }
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z", payload["timestamp"])
    assert "sentinel-secret" not in lines[0]


def test_logger_reconfiguration_is_idempotent_and_does_not_propagate() -> None:
    first_stream = io.StringIO()
    second_stream = io.StringIO()
    logger = configure_structured_logger("arc3.tests.idempotent", stream=first_stream)
    logger = configure_structured_logger("arc3.tests.idempotent", stream=second_stream)

    log_event(logger, "single.event")

    assert first_stream.getvalue() == ""
    assert len(second_stream.getvalue().splitlines()) == 1
    assert logger.propagate is False
