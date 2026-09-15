"""Deterministic MuAPI client safety tests."""

from __future__ import annotations

import requests

from shorts_generator.muapi import _safe_response_text, _transient_status


def test_provider_error_redaction_handles_key_value_messages() -> None:
    response = requests.Response()
    response._content = b"token=super-secret-value; detail=try again"

    message = _safe_response_text(response)

    assert "super-secret-value" not in message
    assert "[redacted]" in message


def test_transient_status_policy() -> None:
    assert _transient_status(429)
    assert _transient_status(503)
    assert not _transient_status(400)
