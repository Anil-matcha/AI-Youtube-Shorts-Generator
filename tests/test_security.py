"""Network-free tests for authentication primitives and throttling."""

from __future__ import annotations

from pathlib import Path

from web.security import SQLiteRateLimiter, SlidingWindowLimiter, redact_structure, redact_text


def test_redact_text_removes_provider_and_session_secrets(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "env-openai-secret")
    result = redact_text("token=sk-abcdefgh123456 session-secret", {"muapi": "session-secret"})

    assert "sk-abcdefgh123456" not in result
    assert "session-secret" not in result
    assert redact_text("provider failed with env-openai-secret") == "provider failed with [redacted]"
    assert result.count("[redacted]") >= 2


def test_redact_structure_handles_nested_error_payloads() -> None:
    payload = {"details": [{"msg": "token=session-secret"}], "value": "session-secret"}

    redacted = redact_structure(payload, {"session": "session-secret"})

    assert redacted["details"][0]["msg"] == "[redacted]"
    assert redacted["value"] == "[redacted]"


def test_sliding_window_limiter_returns_retry_hint() -> None:
    limiter = SlidingWindowLimiter(limit=2, window_seconds=60)

    assert limiter.allow("client") == (True, 0)
    assert limiter.allow("client") == (True, 0)
    allowed, retry_after = limiter.allow("client")

    assert allowed is False
    assert retry_after >= 1
    assert limiter.allow("other-client")[0] is True


def test_sqlite_rate_limiter_shares_counters_between_instances(tmp_path: Path) -> None:
    store = tmp_path / "shared" / "rate-limits.sqlite3"
    first = SQLiteRateLimiter(store, limit=2, window_seconds=60)
    second = SQLiteRateLimiter(store, limit=2, window_seconds=60)

    assert first.allow("client") == (True, 0)
    assert second.allow("client") == (True, 0)
    allowed, retry_after = first.allow("client")

    assert allowed is False
    assert retry_after >= 1
    assert second.allow("other-client") == (True, 0)
