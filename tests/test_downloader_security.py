"""Remote-source allowlist and DNS egress regression tests."""

from __future__ import annotations

import socket

import pytest

from shorts_generator.local.downloader import validate_remote_source


def test_youtube_source_requires_public_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))],
    )
    assert validate_remote_source("https://www.youtube.com/watch?v=abc") == "https://www.youtube.com/watch?v=abc"


def test_private_dns_answer_is_rejected_even_for_allowed_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))],
    )
    with pytest.raises(ValueError, match="private or reserved"):
        validate_remote_source("https://youtu.be/abc")


def test_unlisted_host_and_embedded_credentials_are_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValueError, match="allowlist"):
        validate_remote_source("https://example.com/video.mp4")
    with pytest.raises(ValueError, match="credentials"):
        validate_remote_source("https://user:pass@www.youtube.com/watch?v=abc")
