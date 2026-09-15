"""Validation tests for the shared API contracts."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from web.models import BrandPreset, ClipUpdate, CutRange, JobRequest, TranscriptUpdate


def test_job_request_normalises_text_and_editor_defaults() -> None:
    request = JobRequest(url="  video.mp4  ", caption_color=" #AABBCC ", music_volume=0)

    assert request.url == "video.mp4"
    assert request.caption_color == "#aabbcc"
    assert request.music_volume == 0
    assert request.cuts == []


def test_models_reject_invalid_editor_values() -> None:
    with pytest.raises(ValidationError):
        CutRange(start_time=4, end_time=4.05)
    with pytest.raises(ValidationError):
        JobRequest(url="video.mp4", caption_color="red")
    with pytest.raises(ValidationError):
        JobRequest(url="video.mp4", llm_model="model with spaces")
    with pytest.raises(ValidationError):
        ClipUpdate(
            start_time=0,
            end_time=10,
            cuts=[{"start_time": 0, "end_time": 5}, {"start_time": 4, "end_time": 8}],
        )


def test_transcript_and_brand_preset_contracts() -> None:
    transcript = TranscriptUpdate(
        duration=8,
        segments=[
            {"start": 0, "end": 2, "text": "Opening", "words": [{"start": 0.2, "end": 0.8, "word": "Opening"}]},
            {"start": 3, "end": 7, "text": "Payoff"},
        ],
    )
    assert transcript.segments[0].words[0].word == "Opening"

    preset = BrandPreset(name="  My Brand  ", caption_color="#123456", music_volume=0)
    assert preset.name == "My Brand"
    assert preset.caption_color == "#123456"
    assert preset.music_volume == 0
