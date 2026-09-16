"""Transcript parsing and cache invalidation tests without Whisper installed."""

from __future__ import annotations

import json
import os
from pathlib import Path

from shorts_generator.local import transcriber
from shorts_generator import transcriber as api_transcriber


def test_srt_timestamp_round_trip_and_parser(tmp_path: Path) -> None:
    assert transcriber._format_srt_timestamp(3661.234) == "01:01:01,234"
    assert transcriber._parse_srt_timestamp("01:01:01,234") == 3661.234

    media = tmp_path / "source.mp4"
    media.write_bytes(b"media")
    transcript = {"duration": 3.5, "segments": [{"start": 0.25, "end": 3.5, "text": "Hello"}]}
    cache = transcriber._write_srt_cache(str(media), transcript, str(tmp_path), signature="sig-1")
    loaded = transcriber._load_srt_cache(cache)

    assert loaded["duration"] == 3.5
    assert loaded["segments"][0]["text"] == "Hello"
    metadata = json.loads(transcriber._cache_metadata_path(str(media), str(tmp_path)).read_text(encoding="utf-8"))
    assert metadata["signature"] == "sig-1"


def test_cache_signature_changes_when_media_or_settings_change(tmp_path: Path) -> None:
    media = tmp_path / "source.mp4"
    media.write_bytes(b"one")
    first = transcriber._cache_signature(str(media), "en", "base", "cpu")
    second = transcriber._cache_signature(str(media), "fr", "base", "cpu")
    assert first != second

    with media.open("ab") as stream:
        stream.write(b"two")
    os.utime(media, None)
    assert transcriber._cache_signature(str(media), "en", "base", "cpu") != first


def test_cache_paths_use_content_signature_for_same_named_sources(tmp_path: Path) -> None:
    left_dir = tmp_path / "left"
    right_dir = tmp_path / "right"
    left_dir.mkdir()
    right_dir.mkdir()
    first = left_dir / "recording.mp4"
    second = right_dir / "recording.mp4"
    first.write_bytes(b"first source")
    second.write_bytes(b"second source")
    first_key = transcriber._cache_signature(str(first), "en", "base", "cpu")[:32]
    second_key = transcriber._cache_signature(str(second), "en", "base", "cpu")[:32]
    assert first_key != second_key
    assert transcriber._transcript_cache_path(str(first), str(tmp_path), cache_key=first_key) != transcriber._transcript_cache_path(
        str(second), str(tmp_path), cache_key=second_key
    )


def test_api_transcriber_uses_provider_auto_detection(monkeypatch) -> None:
    calls = []

    def fake_run(_task, payload, **kwargs):
        calls.append(payload)
        return {"segments": [{"start": 0, "end": 2, "text": "Bonjour"}], "duration": 2, "language": "fr"}

    monkeypatch.setattr(api_transcriber.muapi, "run", fake_run)
    result = api_transcriber.transcribe("https://cdn.example/source.mp4", language="auto")

    assert "language" not in calls[0]
    assert result["language"] == "fr"
    assert result["language_requested"] == "auto"
