"""Deterministic highlight ranking and transcript-window tests."""

from __future__ import annotations

from shorts_generator.highlights import (
    _sanitize_highlights,
    build_transcript_text,
    chunk_transcript,
    dedupe_highlights,
    get_highlights,
    snap_highlight_boundaries,
)


def test_highlight_sanitizing_dedupes_and_snaps_to_speech() -> None:
    raw = [
        {"title": "Best", "start_time": 1.2, "end_time": 9.9, "score": 150},
        {"title": "Overlap", "start_time": 2, "end_time": 8, "score": 20},
        {"start_time": -2, "end_time": 4},
    ]
    cleaned = _sanitize_highlights(raw, duration=10)
    assert cleaned[0]["score"] == 100
    assert len(dedupe_highlights(cleaned)) == 1

    transcript = {"segments": [{"start": 0, "end": 3, "text": "A"}, {"start": 4, "end": 10, "text": "B"}]}
    snapped = snap_highlight_boundaries(cleaned, transcript)
    assert snapped[0]["start_time"] == 0
    assert snapped[0]["end_time"] == 10


def test_chunking_and_transcript_text_include_visual_signals() -> None:
    transcript = {
        "duration": 1900,
        "segments": [
            {"start": 0, "end": 2, "text": "Intro"},
            {"start": 1750, "end": 1760, "text": "Late section"},
        ],
        "visual_events": [{"time": 4, "type": "scene_change"}],
    }
    chunks = chunk_transcript(transcript)
    assert len(chunks) >= 2
    assert chunks[0]["_offset"] == 0
    assert "Visual signals" in build_transcript_text(transcript)


def test_get_highlights_uses_pluggable_llm_without_network() -> None:
    calls = []

    def fake_llm(prompt: str) -> str:
        calls.append(prompt)
        if "classify the content type" in prompt:
            return '{"content_type":"podcast","density":"medium"}'
        return '{"highlights":[{"title":"A","start_time":1,"end_time":8,"score":90,"hook_sentence":"A","virality_reason":"Useful"}]}'

    result = get_highlights(
        {"duration": 12, "segments": [{"start": 0, "end": 12, "text": "A useful story"}]},
        num_clips=1,
        llm_fn=fake_llm,
    )

    assert result["highlights"][0]["title"] == "A"
    assert len(calls) == 2
