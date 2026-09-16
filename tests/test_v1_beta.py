"""Regression coverage for the v1.0.0 beta foundations."""

from __future__ import annotations

from io import BytesIO
import threading
import time
from pathlib import Path

from fastapi.testclient import TestClient

import web.app as studio
from shorts_generator.local import clipper
from shorts_generator.local import transcriber
from web import publishing
from web.analytics import aggregate
from web.migrations import CURRENT_SCHEMA_VERSION, migrate_job_record


def _client() -> TestClient:
    with studio._lock:
        studio._jobs.clear()
        studio._job_store.clear()
    studio._clear_response_cache()
    return TestClient(studio.app)


def test_v1_alias_error_catalog_and_legacy_deprecation() -> None:
    with _client() as client:
        versioned = client.get("/api/v1/jobs/missing")
        assert versioned.status_code == 404
        assert versioned.json()["code"] == "job_not_found"
        assert versioned.headers["x-api-version"] == "v1"

        legacy = client.get("/api/jobs/missing")
        assert legacy.status_code == 404
        assert legacy.json()["code"] == "http_404"
        assert legacy.headers["deprecation"] == "true"
        assert legacy.headers["sunset"] == "2027-09-15"
        assert "/api/v1/jobs/missing" in legacy.headers["link"]

        catalog = client.get("/api/v1/errors")
        assert catalog.status_code == 200
        assert "publish_failed" in catalog.json()["errors"]
        schema = client.get("/openapi.json").json()
        assert "/api/v1/jobs/{job_id}/variants" in schema["paths"]
        assert schema["info"]["x-api-version"] == "v1"


def test_response_cache_keeps_legacy_and_v1_headers_separate() -> None:
    with _client() as client:
        legacy = client.get("/api/provider-costs")
        versioned = client.get("/api/v1/provider-costs")
        assert legacy.status_code == 200
        assert legacy.headers["deprecation"] == "true"
        assert versioned.status_code == 200
        assert versioned.headers["x-api-version"] == "v1"
        assert "deprecation" not in versioned.headers


def test_project_migration_is_pure_and_records_history() -> None:
    original = {"id": "legacy", "request": {"video_url": "source.mp4"}, "result": {"shorts": []}}
    migrated, steps = migrate_job_record(original)
    assert original["request"] == {"video_url": "source.mp4"}
    assert migrated["schema_version"] == CURRENT_SCHEMA_VERSION
    assert migrated["request"]["url"] == "source.mp4"
    assert migrated["variants"] == []
    assert migrated["analytics"] == []
    assert steps == ["v0_to_v1", "v1_to_v2", "v2_to_v3", "v3_to_v4"]
    assert len(migrated["migration_history"]) == 4
    migrated_again, steps_again = migrate_job_record(original)
    assert migrated_again == migrated
    assert steps_again == steps


def test_analytics_aggregate_weights_watch_time_and_bounds_rates() -> None:
    summary = aggregate(
        [
            {"platform": "tiktok", "views": 100, "impressions": 50, "average_watch_time_seconds": 4},
            {"platform": "tiktok", "views": 300, "impressions": 300, "average_watch_time_seconds": 8},
        ]
    )
    assert summary["average_watch_time_seconds"] == 7
    assert summary["view_rate"] == 1


def test_variants_and_analytics_feedback_are_durable() -> None:
    with _client() as client:
        with studio._lock:
            studio._jobs["beta-job"] = {
                "id": "beta-job",
                "name": "Beta",
                "status": "done",
                "stage": "done",
                "request": {"url": "source.mp4", "mode": "local"},
                "raw_shorts": [{"title": "Base hook", "hook_sentence": "Base", "start_time": 0, "end_time": 8, "clip_url": None}],
                "raw_transcript": {},
                "result": {"shorts": []},
                "logs": [],
                "created_at": time.time(),
            }
            studio._persist_job_locked(studio._jobs["beta-job"])
        created = client.post("/api/v1/jobs/beta-job/variants", json={"clip_index": 0, "name": "Hook B", "hook": "Try this"})
        assert created.status_code == 200
        variant_id = created.json()["variant"]["id"]
        metric = {
            "platform": "tiktok",
            "variant_id": variant_id,
            "views": 1000,
            "likes": 80,
            "comments": 10,
            "shares": 10,
            "completion_rate": 0.8,
        }
        recorded = client.post("/api/v1/jobs/beta-job/analytics", json=metric)
        assert recorded.status_code == 200
        assert recorded.json()["summary"]["views"] == 1000
        assert client.get("/api/v1/jobs/beta-job/variants").json()["variants"][0]["id"] == variant_id
        feedback = client.get("/api/v1/jobs/beta-job/analytics").json()["feedback"]
        assert feedback["variants"][0]["variant_id"] == variant_id
        with studio._lock:
            assert studio._jobs["beta-job"]["analytics"][0]["variant_id"] == variant_id


def test_direct_tiktok_and_instagram_adapters(monkeypatch, tmp_path: Path) -> None:
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"video")
    monkeypatch.setenv("TIKTOK_ACCESS_TOKEN", "tiktok-token")
    monkeypatch.setenv("INSTAGRAM_ACCESS_TOKEN", "instagram-token")
    monkeypatch.setenv("INSTAGRAM_USER_ID", "ig-user")
    publishing._upload_results.clear()
    calls = []

    class Response:
        def __init__(self, payload: dict) -> None:
            self.status_code = 200
            self.headers = {}
            self._payload = payload

        def json(self) -> dict:
            return self._payload

        def raise_for_status(self) -> None:
            return None

    def fake_request(method: str, url: str, **kwargs):
        calls.append((method, url, kwargs))
        if "tiktok" in url and method == "POST":
            return Response({"data": {"upload_url": "https://upload.tiktok.test", "publish_id": "p1"}})
        if "tiktok" in url:
            return Response({})
        if url.endswith("/media"):
            return Response({"id": "container-1"})
        if url.endswith("/container-1"):
            return Response({"status_code": "FINISHED"})
        return Response({"id": "media-1"})

    monkeypatch.setattr(publishing, "_social_request_with_retry", fake_request)
    tiktok = publishing.publish_tiktok_video(media, title="Test")
    assert tiktok["publish_id"] == "p1"
    instagram = publishing.publish_instagram_reel("https://cdn.test/clip.mp4", caption="Test", poll_interval=0)
    assert instagram["media_id"] == "media-1"
    assert [item[0] for item in calls] == ["POST", "PUT", "POST", "GET", "POST"]


def test_social_upload_retry_rewinds_stream(monkeypatch) -> None:
    attempts: list[bytes] = []

    class Response:
        def __init__(self, status_code: int) -> None:
            self.status_code = status_code

    def fake_request(_method: str, _url: str, **kwargs):
        body = kwargs["data"]
        attempts.append(body.read())
        return Response(500 if len(attempts) == 1 else 200)

    monkeypatch.setattr(publishing.requests, "request", fake_request)
    response = publishing._social_request_with_retry("PUT", "https://upload.test", data=BytesIO(b"payload"))
    assert response.status_code == 200
    assert attempts == [b"payload", b"payload"]


def test_direct_publish_requires_authorized_provider(monkeypatch) -> None:
    monkeypatch.delenv("TIKTOK_ACCESS_TOKEN", raising=False)
    publishing._tiktok_tokens.clear()
    with _client() as client:
        with studio._lock:
            studio._jobs["publish-gate"] = {
                "id": "publish-gate",
                "status": "done",
                "stage": "done",
                "request": {"url": "source.mp4", "mode": "local"},
                "raw_shorts": [{"title": "Hook", "start_time": 0, "end_time": 4, "clip_url": None}],
                "logs": [],
            }
        response = client.post(
            "/api/v1/jobs/publish-gate/publish",
            json={"platform": "tiktok", "clip_index": 0, "confirm": True},
        )
        assert response.status_code == 400
        assert response.json()["code"] == "credentials_required"


def test_parallel_local_render_preserves_order(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    lock = threading.Lock()
    active = {"count": 0, "maximum": 0}

    def fake_render(*args, **kwargs):
        with lock:
            active["count"] += 1
            active["maximum"] = max(active["maximum"], active["count"])
        time.sleep(0.04)
        Path(args[4]).write_bytes(b"clip")
        with lock:
            active["count"] -= 1
        return args[4]

    monkeypatch.setattr(clipper, "crop_clip_local", fake_render)
    monkeypatch.setattr(clipper, "LOCAL_THUMBNAIL_POSITION", 0.5)
    highlights = [
        {"title": "one", "start_time": 0, "end_time": 2},
        {"title": "two", "start_time": 2, "end_time": 4},
        {"title": "three", "start_time": 4, "end_time": 6},
    ]
    results = clipper.crop_highlights_local(str(source), highlights, out_dir=str(tmp_path / "clips"), burn_captions=False, max_workers=3)
    assert [item["title"] for item in results] == ["one", "two", "three"]
    assert active["maximum"] > 1


def test_streaming_transcription_reports_segments(monkeypatch, tmp_path: Path) -> None:
    media = tmp_path / "audio.mp4"
    media.write_bytes(b"audio")

    class Segment:
        def __init__(self, start: float, end: float, text: str) -> None:
            self.start, self.end, self.text, self.words = start, end, text, []

    class Info:
        duration = 4.0
        language = "en"
        language_probability = 0.9

    class Model:
        def transcribe(self, **kwargs):
            return iter([Segment(0, 2, "hello"), Segment(2, 4, "world")]), Info()

    monkeypatch.setattr(transcriber, "_resolve_device", lambda _value: "cpu")
    monkeypatch.setattr(transcriber, "_resolve_model_name", lambda _value, _device: "tiny")
    monkeypatch.setattr(transcriber, "_load_whisper_model", lambda _model, _device: Model())
    messages: list[str] = []
    result = transcriber.transcribe_local(str(media), cache_dir=str(tmp_path / "cache"), progress=messages.append)
    assert len(result["segments"]) == 2
    assert any("Transcribed 1" in message for message in messages)
