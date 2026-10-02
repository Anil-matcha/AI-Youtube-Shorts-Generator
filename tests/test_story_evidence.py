"""Local evidence budgets, privacy, cancellation, and real audio decoding."""

from __future__ import annotations

import subprocess
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import web.app as studio
import web.evidence_routes as routes
import web.story_evidence as engine


@pytest.fixture()
def evidence_client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    monkeypatch.setattr(studio, "_output_root", tmp_path)
    monkeypatch.setattr(routes, "model_catalog", lambda: {"models": [{"id": "tesseract", "available": True}, {"id": "silero-vad", "available": True}]})
    with studio._lock:
        studio._jobs.clear()
        studio._jobs["evidence-job"] = {"id": "evidence-job", "name": "Demo", "status": "done",
                                       "raw_source_video_url": str(source), "raw_shorts": [], "logs": []}
    with TestClient(studio.app, base_url="http://127.0.0.1") as client:
        yield client, source
    with studio._lock:
        studio._jobs.clear()


def test_evidence_requires_explicit_models_and_bounded_inputs(evidence_client) -> None:
    client, _source = evidence_client
    for values in ({}, {"audio_model": "remote-model"}, {"audio_model": "silero-vad", "duration_seconds": 121},
                   {"ocr_model": "tesseract", "max_frames": 9}, {"ocr_model": "tesseract", "language": "--help"},
                   {"audio_model": "silero-vad", "start_time": float("inf")},
                   {"audio_model": "silero-vad", "path": "C:/private/video.mp4"}):
        # JSON cannot encode non-finite numbers; use raw JSON for that case.
        if values.get("start_time") == float("inf"):
            response = client.post("/api/v1/jobs/evidence-job/story/analyze", content='{"audio_model":"silero-vad","start_time":1e999}', headers={"Content-Type": "application/json"})
        else:
            response = client.post("/api/v1/jobs/evidence-job/story/analyze", json=values)
        assert response.status_code == 422


def test_evidence_uses_only_local_contained_source_and_available_models(evidence_client, monkeypatch: pytest.MonkeyPatch) -> None:
    client, source = evidence_client
    monkeypatch.setattr(routes, "analyze_local", lambda *_args: pytest.fail("must not run"))
    for value in ("https://media.example/video.mp4", str(source.parent.parent / "escape.mp4")):
        studio._jobs["evidence-job"]["raw_source_video_url"] = value
        response = client.post("/api/jobs/evidence-job/story/analyze", json={"audio_model": "silero-vad"})
        assert response.status_code == 409
        assert response.json()["code"] == "local_source_required"
    studio._jobs["evidence-job"]["raw_source_video_url"] = str(source)
    monkeypatch.setattr(routes, "model_catalog", lambda: {"models": []})
    response = client.post("/api/jobs/evidence-job/story/analyze", json={"audio_model": "silero-vad"})
    assert response.json()["code"] == "evidence_model_unavailable"


def test_analysis_persists_searchable_redacted_evidence_and_clear(evidence_client, monkeypatch: pytest.MonkeyPatch) -> None:
    client, _source = evidence_client
    def analyze(source, values, run, check):
        check()
        assert values["ocr_model"] == "tesseract"
        return {"schema": "shorts-studio-evidence-1", "ocr": [{"text": engine.clean_evidence_text("Revenue C:\\private\\video.mp4 https://secret.example/?token=hidden"), "start_time": 4, "end_time": 4}],
                "audio": [{"text": "Speech activity", "start_time": 1, "end_time": 3}]}
    monkeypatch.setattr(routes, "analyze_local", analyze)
    response = client.post("/api/v1/jobs/evidence-job/story/analyze", json={"ocr_model": "tesseract"})
    assert response.status_code == 200
    assert "analyzed_at" in response.json()["evidence"]
    assert "private" not in response.text and "hidden" not in response.text
    search = client.post("/api/v1/story/search", json={"query": "revenue"})
    assert search.json()["results"][0]["kind"] == "ocr"
    speech = client.post("/api/v1/story/search", json={"query": "speech"})
    assert speech.json()["results"][0]["kind"] == "audio"
    assert client.get("/api/v1/jobs/evidence-job/story/analyze").json()["running"] is False
    assert client.delete("/api/v1/jobs/evidence-job/story/analyze").json()["status"] == "cleared"
    assert client.post("/api/v1/story/search", json={"query": "revenue"}).json()["result_count"] == 0


def test_cancel_preserves_previous_evidence_and_does_not_publish_partial_results(evidence_client, monkeypatch: pytest.MonkeyPatch) -> None:
    client, _source = evidence_client
    previous = {"ocr": [{"text": "Original"}], "audio": []}
    studio._jobs["evidence-job"]["story_evidence"] = previous
    entered, proceed = threading.Event(), threading.Event()
    def analyze(*args):
        entered.set()
        assert proceed.wait(5)
        args[-1]()
        return {"ocr": [{"text": "Partial"}]}
    monkeypatch.setattr(routes, "analyze_local", analyze)
    results = []
    worker = threading.Thread(target=lambda: results.append(client.post("/api/jobs/evidence-job/story/analyze", json={"audio_model": "silero-vad"})))
    worker.start()
    try:
        assert entered.wait(5)
        assert client.get("/api/jobs/evidence-job/story/analyze").json()["running"] is True
        busy = client.post("/api/jobs/evidence-job/story/analyze", json={"audio_model": "silero-vad"})
        assert busy.json()["code"] == "evidence_busy"
        assert client.delete("/api/jobs/evidence-job/story/analyze").json()["status"] == "cancelling"
    finally:
        proceed.set()
        worker.join(5)
    assert not worker.is_alive()
    assert results[0].json()["code"] == "evidence_cancelled"
    assert studio._jobs["evidence-job"]["story_evidence"] == previous
    assert not routes._active


def test_changed_source_cannot_commit_stale_evidence(evidence_client, monkeypatch: pytest.MonkeyPatch) -> None:
    client, source = evidence_client
    def analyze(*_args):
        source.write_bytes(b"a different source")
        return {"ocr": [], "audio": []}
    monkeypatch.setattr(routes, "analyze_local", analyze)
    response = client.post("/api/jobs/evidence-job/story/analyze", json={"audio_model": "silero-vad"})
    assert response.json()["code"] == "evidence_stale"
    assert "story_evidence" not in studio._jobs["evidence-job"]


def test_cancel_terminates_an_actual_registered_inference_process(evidence_client, monkeypatch: pytest.MonkeyPatch) -> None:
    client, _source = evidence_client
    entered = threading.Event()
    processes = []
    register = studio._register_job_process
    def record(job_id, process):
        register(job_id, process)
        processes.append(process)
        entered.set()
    monkeypatch.setattr(studio, "_register_job_process", record)
    def analyze(_source, _values, run, _check):
        run([sys.executable, "-c", "import time; time.sleep(60)"])
        pytest.fail("cancelled subprocess cannot continue")
    monkeypatch.setattr(routes, "analyze_local", analyze)
    results = []
    worker = threading.Thread(target=lambda: results.append(client.post("/api/jobs/evidence-job/story/analyze", json={"audio_model": "silero-vad"})))
    worker.start()
    try:
        assert entered.wait(5)
        assert client.delete("/api/jobs/evidence-job/story/analyze").json()["status"] == "cancelling"
    finally:
        worker.join(5)
    assert not worker.is_alive()
    assert results[0].json()["code"] == "evidence_cancelled"
    assert processes[0].poll() is not None
    assert "evidence-job" not in studio._job_processes


def test_deadline_terminates_an_actual_inference_process(evidence_client, monkeypatch: pytest.MonkeyPatch) -> None:
    client, _source = evidence_client
    monkeypatch.setattr(routes, "TIMEOUT_SECONDS", 0.1)
    def analyze(_source, _values, run, _check):
        run([sys.executable, "-c", "import time; time.sleep(60)"])
        pytest.fail("timed-out subprocess cannot continue")
    monkeypatch.setattr(routes, "analyze_local", analyze)
    response = client.post("/api/jobs/evidence-job/story/analyze", json={"audio_model": "silero-vad"})
    assert response.status_code == 409
    assert "timed out" in response.json()["error"]
    assert "evidence-job" not in studio._job_processes
    assert "story_evidence" not in studio._jobs["evidence-job"]


def test_ocr_tsv_confidence_lines_and_privacy() -> None:
    payload = b"page_num\tblock_num\tpar_num\tline_num\tconf\ttext\n1\t1\t1\t1\t90\tRevenue\n1\t1\t1\t1\t80\tgrowth\n1\t1\t1\t2\t20\tnoise\n1\t1\t1\t2\tnan\tinvalid\n"
    result = engine.parse_ocr_tsv(payload, 5.5)
    assert result == [{"start_time": 5.5, "end_time": 5.5, "text": "Revenue growth", "confidence": 0.85, "model": "tesseract"}]
    assert "private" not in engine.clean_evidence_text("/home/private/media.mov C:\\private\\media.mov https://example.com/?token=secret")
    with pytest.raises(RuntimeError, match="budget"):
        engine.parse_ocr_tsv(b"x" * (1024 * 1024 + 1), 0)


def test_speech_evidence_offsets_bounds_and_no_classification(monkeypatch: pytest.MonkeyPatch) -> None:
    numpy = pytest.importorskip("numpy")
    real_import = engine.importlib.import_module
    vad = SimpleNamespace(VadOptions=lambda **kwargs: kwargs, get_speech_timestamps=lambda *_args, **_kwargs: [{"start": 1600, "end": 3200}])
    monkeypatch.setattr(engine.importlib, "import_module", lambda name: vad if name == "faster_whisper.vad" else real_import(name))
    result = engine.speech_evidence(numpy.zeros(4000, dtype="<f4").tobytes(), 10)
    assert result == [{"start_time": 10.1, "end_time": 10.2, "text": "Speech activity", "type": "speech", "model": "silero-vad"}]
    with pytest.raises(RuntimeError, match="invalid samples"):
        engine.speech_evidence(numpy.array([float("nan")], dtype="<f4").tobytes(), 0)


def test_real_local_audio_analysis_without_model_download(tmp_path: Path) -> None:
    from shorts_generator.local.clipper import _find_ffmpeg
    ffmpeg = _find_ffmpeg()
    if not ffmpeg or not next(item for item in engine.model_catalog()["models"] if item["kind"] == "audio")["available"]:
        pytest.skip("local FFmpeg and bundled Silero runtime required")
    source = tmp_path / "tone.wav"
    subprocess.run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=16000", "-t", "2", str(source)], check=True, capture_output=True, timeout=15)
    def run(args):
        return subprocess.run(args, check=True, capture_output=True, timeout=15).stdout
    result = engine.analyze_local(source, {"audio_model": "silero-vad", "start_time": 0, "duration_seconds": 2}, run, lambda: None)
    assert result["models"] == ["silero-vad"]
    assert result["audio"] == []  # A pure tone is not speech.
    assert not list(tmp_path.glob("*.png"))
