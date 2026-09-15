"""Mocked local pipeline integration without network, models, or FFmpeg."""

from __future__ import annotations

from pathlib import Path

from shorts_generator import pipeline


def test_local_pipeline_wires_download_visual_transcription_ranking_and_crop(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"fixture")
    calls: list[str] = []

    monkeypatch.setattr("shorts_generator.local.downloader.download_youtube_local", lambda *args, **kwargs: calls.append("download") or str(source))
    monkeypatch.setattr("shorts_generator.local.visual.analyze_video", lambda *args, **kwargs: calls.append("visual") or [{"time": 1, "type": "scene_change"}])
    monkeypatch.setattr(
        "shorts_generator.local.transcriber.transcribe_local",
        lambda *args, **kwargs: calls.append("transcribe")
        or {"duration": 12, "segments": [{"start": 0, "end": 12, "text": "A useful story"}]},
    )
    monkeypatch.setattr("shorts_generator.local.llm.call_local_llm", lambda prompt: calls.append("llm") or (
        '{"content_type":"podcast","density":"medium"}'
        if "classify the content type" in prompt
        else '{"highlights":[{"title":"A","start_time":1,"end_time":8,"score":90,"hook_sentence":"A","virality_reason":"Useful"}]}'
    ))
    monkeypatch.setattr(
        "shorts_generator.local.clipper.crop_highlights_local",
        lambda *args, **kwargs: calls.append("crop") or [{"title": "A", "clip_url": str(tmp_path / "short_01.mp4")}],
    )
    monkeypatch.setattr(pipeline, "LOCAL_HEURISTIC_FALLBACK", False)

    result = pipeline.generate_shorts(
        "https://www.youtube.com/watch?v=abc",
        mode="local",
        num_clips=1,
        output_dir=str(tmp_path),
        llm_provider="openai",
    )

    assert result["mode"] == "local"
    assert result["shorts"][0]["title"] == "A"
    assert calls == ["download", "visual", "transcribe", "llm", "llm", "crop"]
