"""Pipeline mode dispatch tests with rendering/network boundaries mocked."""

from __future__ import annotations

import pytest

from shorts_generator import pipeline


def test_generate_shorts_dispatches_api_options(monkeypatch) -> None:
    captured = {}

    def fake_api(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return {"mode": "api"}

    monkeypatch.setattr(pipeline, "_run_api", fake_api)
    result = pipeline.generate_shorts("https://example.com/video", mode="api", llm_model="custom", llm_temperature=0.7)

    assert result["mode"] == "api"
    assert captured["args"][-2:] == ("custom", 0.7)


def test_generate_shorts_rejects_local_path_in_api_mode() -> None:
    with pytest.raises(ValueError, match=r"API mode requires an http\(s\) video URL"):
        pipeline.generate_shorts("C:/Videos/source.mp4", mode="api")


def test_generate_shorts_dispatches_local_editor_options(monkeypatch) -> None:
    captured = {}

    def fake_local(*args, **kwargs):
        captured["args"] = args
        return {"mode": "local"}

    monkeypatch.setattr(pipeline, "_run_local", fake_local)
    result = pipeline.generate_shorts(
        "source.mp4",
        mode="local",
        cuts=[{"start_time": 1, "end_time": 3}],
        music_volume=0.4,
        music_fade_in=1.0,
        music_fade_out=2.0,
        llm_model="local-model",
        llm_temperature=0.5,
    )

    assert result["mode"] == "local"
    assert captured["args"][-7:] == (None, "local-model", 0.5, 0.4, 1.0, 2.0, [{"start_time": 1, "end_time": 3}])
