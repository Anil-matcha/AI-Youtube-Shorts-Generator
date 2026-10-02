"""Benchmark CLI stays offline by default and reports repeated measurements."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from scripts import benchmark_v2 as benchmark


def test_missing_cache_is_reported_without_import_or_download(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(benchmark, "cached_snapshot", lambda name: None)
    monkeypatch.setattr(benchmark, "_download_snapshot", lambda name: pytest.fail("default triggered a download"))
    result = benchmark._model_benchmark("base", "cpu", "int8")
    assert result["status"] == "unavailable"
    assert result["network_allowed"] is False
    assert result["cache_hit"] is False


def test_repeated_model_loads_use_complete_local_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def model(path: str, **kwargs: Any) -> object:
        calls.append((path, kwargs))
        return object()

    monkeypatch.setattr(benchmark, "cached_snapshot", lambda name: tmp_path)
    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=model))
    result = benchmark._model_benchmark("base", "cpu", "int8", repetitions=3)
    assert result["status"] == "measured"
    assert result["cache_hit"] is True
    assert result["summary"]["count"] == 3
    assert len(result["samples_seconds"]) == 3
    assert len(calls) == 3
    assert all(path == str(tmp_path) and kwargs["local_files_only"] is True for path, kwargs in calls)


def test_download_requires_explicit_opt_in(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    requests = []
    monkeypatch.setattr(benchmark, "cached_snapshot", lambda name: None)
    monkeypatch.setattr(benchmark, "_download_snapshot", lambda name: requests.append(name) or tmp_path)
    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=lambda *args, **kwargs: object()))
    result = benchmark._model_benchmark("tiny", "cpu", "int8", repetitions=2, allow_download=True)
    assert requests == ["tiny"]
    assert result["status"] == "measured"
    assert result["cache_hit"] is False
    assert result["download_seconds"] >= 0


@pytest.mark.parametrize("value", ["0", "11", "-1"])
def test_repetition_limit(value: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        benchmark._repetitions(value)


def test_timing_summary_keeps_first_and_warm_samples(monkeypatch: pytest.MonkeyPatch) -> None:
    durations = iter([3.0, 1.0, 2.0])
    monkeypatch.setattr(benchmark, "_render_benchmark", lambda *args: {
        "status": "measured", "first_render_seconds": next(durations), "output_bytes": 123,
    })
    result = benchmark._render_samples("ffmpeg", 20, 3)
    assert result["first_render_seconds"] == 3.0
    assert result["samples_seconds"] == [3.0, 1.0, 2.0]
    assert result["summary"] == {
        "count": 3, "min_seconds": 1.0, "max_seconds": 3.0, "mean_seconds": 2.0,
        "median_seconds": 2.0, "p95_seconds": 3.0,
    }


def test_cli_defaults_are_cached_only_and_repeated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    destination = tmp_path / "report.json"
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(sys, "argv", ["benchmark_v2.py", "--device", "cpu", "--output", str(destination)])
    monkeypatch.setattr(benchmark, "_model_benchmark", lambda *args, **kwargs: calls.append(kwargs) or {"status": "measured"})
    monkeypatch.setattr(benchmark, "_resolve_ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr(benchmark, "_render_samples", lambda *args: {"status": "measured"})
    assert benchmark.main() == 0
    report = json.loads(destination.read_text(encoding="utf-8"))
    assert report["network_allowed"] is False
    assert report["repetitions"] == 3
    assert calls == [{"repetitions": 3, "allow_download": False}]


def test_error_report_does_not_echo_signed_urls() -> None:
    assert "secret" not in benchmark._error(RuntimeError("https://host.invalid/?signature=secret"))


def test_inference_exhausts_lazy_decoder_without_reporting_text(monkeypatch, tmp_path):
    decoded = []

    class Model:
        def __init__(self, path, **kwargs):
            assert kwargs["local_files_only"] is True

        def transcribe(self, audio, **kwargs):
            assert kwargs["vad_filter"] is False

            def segments():
                decoded.append(True)
                yield SimpleNamespace(text="private transcript")

            return segments(), SimpleNamespace(duration=2.0)

    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=Model))
    report = benchmark._inference_worker({"snapshot": str(tmp_path), "audio": "sample.wav",
                                          "device": "cpu", "compute_type": "int8", "repetitions": 3})
    assert len(decoded) == 3
    assert report["segment_counts"] == [1, 1, 1]
    assert "private" not in json.dumps(report)


def test_inference_worker_timeout_is_redacted_and_temp_media_removed(monkeypatch, tmp_path):
    import subprocess

    monkeypatch.setattr(benchmark, "cached_snapshot", lambda _: tmp_path)
    paths = []

    def run(command, **kwargs):
        if command[0] == "ffmpeg":
            paths.append(Path(command[-1]))
            paths[-1].touch()
            return SimpleNamespace(returncode=0)
        assert kwargs["timeout"] == 10
        assert kwargs["env"]["HF_HUB_OFFLINE"] == "1"
        raise subprocess.TimeoutExpired("private/path", 10)

    monkeypatch.setattr(benchmark.subprocess, "run", run)
    report = benchmark._inference_benchmark("tiny", "cpu", "int8", "ffmpeg", 10, 1)
    assert report["status"] == "failed"
    assert "private" not in json.dumps(report)
    assert not paths[0].exists()


def test_inference_missing_cache_does_not_download(monkeypatch):
    monkeypatch.setattr(benchmark, "cached_snapshot", lambda _: None)
    monkeypatch.setattr(benchmark, "_download_snapshot", lambda _: pytest.fail("Unexpected download"))
    assert benchmark._inference_benchmark("base", "cpu", "int8", "ffmpeg", 10, 1)["status"] == "unavailable"


def test_unavailable_requested_stage_fails_cli(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "argv", ["benchmark", "--output", str(tmp_path / "report.json")])
    monkeypatch.setattr(benchmark, "_model_benchmark", lambda *args, **kwargs: {"status": "unavailable"})
    monkeypatch.setattr(benchmark, "_render_samples", lambda *args: {"status": "measured"})
    assert benchmark.main() == 1


def test_cuda_library_override_only_reaches_child(monkeypatch, tmp_path):
    import os

    original = os.environ.get("PATH", "")
    monkeypatch.setattr(benchmark, "cached_snapshot", lambda _: tmp_path)

    def run(command, **kwargs):
        if command[0] == "ffmpeg":
            return SimpleNamespace(returncode=0)
        assert kwargs["env"]["PATH"].startswith(str(tmp_path.resolve()) + os.pathsep)
        return SimpleNamespace(stdout=json.dumps({"status": "measured"}))

    monkeypatch.setattr(benchmark.subprocess, "run", run)
    report = benchmark._inference_benchmark("tiny", "cuda", "float16", "ffmpeg", 10, 1, cuda_library_dir=tmp_path)
    assert report["status"] == "measured"
    assert os.environ.get("PATH", "") == original
    assert str(tmp_path) not in json.dumps(report)
