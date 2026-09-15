"""Fast, network-free API and static-asset regression tests."""

from __future__ import annotations

import io
import json
import math
import os
import threading
import time
import zipfile
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import web.app as studio


@pytest.fixture()
def client() -> TestClient:
    with studio._lock:
        studio._jobs.clear()
        studio._job_credentials.clear()
        studio._cancel_events.clear()
        studio._job_futures.clear()
    with TestClient(studio.app) as test_client:
        yield test_client
    with studio._lock:
        studio._jobs.clear()
        studio._job_credentials.clear()
        studio._cancel_events.clear()
        studio._job_futures.clear()


def _job(job_id: str = "test-job") -> dict:
    return {
        "id": job_id,
        "name": "Smoke project",
        "request": {"url": "local.mp4"},
        "logs": [
            {"t": 1.0, "stage": "queued", "message": "Queued"},
            {"t": 2.0, "stage": "error", "message": "provider key mu_secretSECRET1234"},
            {"t": math.inf, "stage": "error", "message": "token sk-abcdefgh123456", "metadata": {"key": "mu_secretSECRET1234"}},
        ],
    }


def test_health_and_static_assets(client: TestClient) -> None:
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"

    page = client.get("/")
    assert page.status_code == 200
    assert "charset=utf-8" in page.headers["content-type"].lower()
    assert 'href="/static/styles.css"' in page.text
    assert 'src="/static/app.js"' in page.text
    assert "Logs" in page.text
    assert "charset=utf-8" in client.get("/static/styles.css").headers["content-type"].lower()
    assert "charset=utf-8" in client.get("/static/app.js").headers["content-type"].lower()
    assert "charset=utf-8" in client.get("/static/modules/state.js").headers["content-type"].lower()
    assert client.get("/static/theme-init.js").status_code == 200


def test_logs_are_filtered_normalised_and_redacted(client: TestClient) -> None:
    with studio._lock:
        studio._jobs["test-job"] = _job()
        studio._job_credentials["test-job"] = {"muapi": "mu_secretSECRET1234"}

    response = client.get("/api/logs", params={"job_id": "test-job", "level": "error"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 2
    assert all(entry["stage"] == "error" for entry in payload["logs"])
    messages = " ".join(entry["message"] for entry in payload["logs"])
    assert "mu_secretSECRET1234" not in messages
    assert "sk-abcdefgh123456" not in messages
    assert "[redacted]" in messages
    assert all(entry["timestamp"] for entry in payload["logs"])

    snapshot = client.get("/api/jobs/test-job")
    assert snapshot.status_code == 200
    assert snapshot.json()["logs"][-1]["metadata"]["key"] == "[redacted]"

    download = client.get("/api/logs/download", params={"job_id": "test-job"})
    assert download.status_code == 200
    assert "[redacted]" in download.text
    assert "mu_secretSECRET1234" not in download.text


def test_errors_use_one_json_shape(client: TestClient) -> None:
    invalid_filter = client.get("/api/logs", params={"level": "not-a-level"})
    assert invalid_filter.status_code == 400
    assert set((invalid_filter.json() or {}).keys()) >= {"error", "code"}

    missing_url = client.post("/api/jobs", json={})
    assert missing_url.status_code == 422
    assert missing_url.json()["code"] == "validation_error"
    assert isinstance(missing_url.json()["details"], list)

    malformed = client.post(
        "/api/jobs",
        content=b"{",
        headers={"content-type": "application/json"},
    )
    assert malformed.status_code == 422
    assert malformed.json()["code"] == "validation_error"


def test_json_size_guard(client: TestClient) -> None:
    response = client.post("/api/jobs", json={"url": "x" * (2 * 1024 * 1024)})
    assert response.status_code == 413
    assert response.json()["code"] == "request_too_large"


def test_authentication_can_protect_api_and_issue_session_cookie(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHORTS_API_TOKEN", "test-access-token")

    assert client.get("/api/auth/status").json() == {"enabled": True, "authenticated": False}
    blocked = client.get("/api/storage")
    assert blocked.status_code == 401
    assert blocked.json()["code"] == "auth_required"

    invalid = client.post("/api/auth/login", json={"token": "wrong-token"})
    assert invalid.status_code == 401
    assert invalid.json()["code"] == "auth_invalid"

    login = client.post("/api/auth/login", json={"token": "test-access-token"})
    assert login.status_code == 200
    assert "shorts_token" in login.headers.get("set-cookie", "")
    assert client.get("/api/storage").status_code == 200
    assert client.get("/api/auth/status").json()["authenticated"] is True


def test_rate_limit_returns_retry_after(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(studio, "_rate_limiter", studio.SlidingWindowLimiter(limit=1, window_seconds=60))

    assert client.get("/api/system").status_code == 200
    limited = client.get("/api/system")
    assert limited.status_code == 429
    assert limited.json()["code"] == "rate_limited"
    assert int(limited.headers["retry-after"]) >= 1


def test_queued_cancellation_cancels_future_and_releases_event(client: TestClient) -> None:
    class PendingFuture:
        def __init__(self) -> None:
            self.cancelled = False

        def cancel(self) -> bool:
            self.cancelled = True
            return True

    pending = PendingFuture()
    with studio._lock:
        studio._jobs["queued-cancel"] = {
            "id": "queued-cancel",
            "name": "Queued cancellation",
            "status": "queued",
            "stage": "queued",
            "message": "Queued",
            "request": {"url": "https://example.com/video.mp4", "mode": "api"},
            "logs": [],
            "created_at": time.time(),
        }
        studio._cancel_events["queued-cancel"] = threading.Event()
        studio._job_futures["queued-cancel"] = pending  # type: ignore[assignment]
        studio._persist_job_locked(studio._jobs["queued-cancel"])

    response = client.post("/api/jobs/queued-cancel/cancel")
    assert response.status_code == 200
    assert pending.cancelled is True
    with studio._lock:
        assert "queued-cancel" not in studio._cancel_events
        assert "queued-cancel" not in studio._job_futures


def test_shutdown_persists_interrupted_jobs_and_stops_bound_server(client: TestClient) -> None:
    server = SimpleNamespace(should_exit=False)
    studio.bind_server(server)
    with studio._lock:
        studio._jobs["shutdown-job"] = {
            "id": "shutdown-job",
            "name": "Shutdown recovery",
            "status": "running",
            "stage": "transcribe",
            "progress": 45,
            "message": "Transcribing",
            "request": {"url": "https://example.com/video.mp4", "mode": "api"},
            "logs": [],
            "created_at": time.time(),
        }
        studio._cancel_events["shutdown-job"] = threading.Event()
        studio._persist_job_locked(studio._jobs["shutdown-job"])

    response = client.post("/api/shutdown")

    assert response.status_code == 200
    assert response.json()["interrupted_jobs"] == 1
    assert server.should_exit is True
    with studio._lock:
        assert studio._jobs["shutdown-job"]["status"] == "interrupted"
        assert studio._cancel_events["shutdown-job"].is_set()
    studio.bind_server(None)
    studio._shutdown_requested.clear()


def test_api_mode_rejects_local_only_controls_before_queueing(client: TestClient) -> None:
    response = client.post(
        "/api/jobs",
        json={
            "url": "https://example.com/video.mp4",
            "mode": "api",
            "remove_silence": True,
        },
    )

    assert response.status_code == 400
    assert response.json()["code"] == "http_400"
    assert "remove_silence" in response.json()["error"]


def test_api_clip_edit_rejects_unsupported_caption_controls(client: TestClient) -> None:
    with studio._lock:
        studio._jobs["api-editor-job"] = {
            "id": "api-editor-job",
            "name": "API editor project",
            "status": "done",
            "request": {"url": "https://example.com/video.mp4", "mode": "api", "aspect_ratio": "9:16"},
            "result": {"mode": "api", "shorts": []},
            "raw_shorts": [{"title": "Hook", "start_time": 0, "end_time": 8, "clip_url": "https://cdn.example/clip.mp4"}],
            "raw_transcript": {"duration": 8, "segments": []},
            "raw_source_video_url": "https://cdn.example/source.mp4",
            "logs": [],
            "created_at": time.time(),
        }
        studio._persist_job_locked(studio._jobs["api-editor-job"])

    response = client.post(
        "/api/jobs/api-editor-job/clips/0",
        json={"start_time": 0, "end_time": 5, "caption_position": "top"},
    )
    assert response.status_code == 400
    assert "only start/end timestamps" in response.json()["error"]


def test_local_clip_edit_supports_durable_multi_level_undo_and_redo(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setattr(studio, "_output_root", tmp_path)
    monkeypatch.setattr(studio, "_jobs_dir", tmp_path / "jobs")
    monkeypatch.setattr(studio, "_allow_external_paths", False)
    source = tmp_path / "source.mp4"
    output_dir = tmp_path / "jobs" / "history-job"
    clip = output_dir / "clip-01.mp4"
    source.write_bytes(b"source")
    output_dir.mkdir(parents=True)
    clip.write_bytes(b"old")

    with studio._lock:
        studio._jobs["history-job"] = {
            "id": "history-job",
            "name": "History project",
            "status": "done",
            "request": {"url": str(source), "mode": "local", "aspect_ratio": "9:16"},
            "result": {"mode": "local", "shorts": []},
            "raw_shorts": [{"title": "Hook", "start_time": 0, "end_time": 4, "clip_url": str(clip)}],
            "raw_transcript": {"duration": 8, "segments": []},
            "raw_source_video_url": str(source),
            "output_dir": str(output_dir),
            "logs": [],
            "created_at": time.time(),
        }
        studio._persist_job_locked(studio._jobs["history-job"])

    render_count = {"value": 0}

    def fake_render(*args, **kwargs):
        render_count["value"] += 1
        args[4]  # output path
        with open(args[4], "wb") as rendered:
            rendered.write(f"new-{render_count['value']}".encode("ascii"))
        return args[4]

    monkeypatch.setattr("shorts_generator.local.clipper.crop_clip_local", fake_render)
    monkeypatch.setattr("shorts_generator.local.clipper._media_duration", lambda _path: 0.0)

    update = {"start_time": 0, "end_time": 5}
    first = client.post("/api/jobs/history-job/clips/0", json=update)
    assert first.status_code == 200
    assert clip.read_bytes() == b"new-1"
    assert first.json()["result"]["shorts"][0]["history_depth"] == 1

    second = client.post("/api/jobs/history-job/clips/0", json={"start_time": 1, "end_time": 6})
    assert second.status_code == 200
    assert clip.read_bytes() == b"new-2"
    assert second.json()["result"]["shorts"][0]["history_depth"] == 2

    undone = client.post("/api/jobs/history-job/clips/0/undo")
    assert undone.status_code == 200
    assert clip.read_bytes() == b"new-1"
    assert undone.json()["result"]["shorts"][0]["history_depth"] == 1
    assert undone.json()["result"]["shorts"][0]["redo_depth"] == 1

    redone = client.post("/api/jobs/history-job/clips/0/redo")
    assert redone.status_code == 200
    assert clip.read_bytes() == b"new-2"
    assert redone.json()["result"]["shorts"][0]["history_depth"] == 2
    assert redone.json()["result"]["shorts"][0]["redo_depth"] == 0


def test_legacy_one_level_undo_snapshot_is_migrated(client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(studio, "_output_root", tmp_path)
    monkeypatch.setattr(studio, "_jobs_dir", tmp_path / "jobs")
    output_dir = tmp_path / "jobs" / "legacy-job"
    output_dir.mkdir(parents=True)
    clip = output_dir / "short_01.mp4"
    undo = output_dir / "short_01.mp4.undo.mp4"
    clip.write_bytes(b"new")
    undo.write_bytes(b"old")
    with studio._lock:
        studio._jobs["legacy-job"] = {
            "id": "legacy-job",
            "status": "done",
            "request": {"url": "https://example.com/source.mp4", "mode": "local"},
            "result": {"mode": "local", "shorts": []},
            "raw_shorts": [
                {
                    "title": "Legacy",
                    "start_time": 0,
                    "end_time": 4,
                    "clip_url": str(clip),
                    "undo_path": str(undo),
                    "undo_metadata": {"title": "Original", "start_time": 0, "end_time": 3, "clip_url": str(clip)},
                }
            ],
            "raw_transcript": {"duration": 8, "segments": []},
            "raw_source_video_url": "https://example.com/source.mp4",
            "output_dir": str(output_dir),
            "logs": [],
            "created_at": time.time(),
        }
        studio._persist_job_locked(studio._jobs["legacy-job"])

    response = client.post("/api/jobs/legacy-job/clips/0/undo")
    assert response.status_code == 200
    assert clip.read_bytes() == b"old"
    short = response.json()["result"]["shorts"][0]
    assert short["title"] == "Original"
    assert short["history_depth"] == 0
    assert short["redo_depth"] == 1


def test_backup_restore_and_storage_cleanup_are_scoped(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setattr(studio, "_min_free_gb", 0)
    monkeypatch.setattr(studio, "_allow_external_paths", True)
    media_root = tmp_path / "test-backup-media"
    media_root.mkdir(parents=True, exist_ok=True)
    (media_root / "clip.mp4").write_bytes(b"backup-media")
    with studio._lock:
        studio._jobs["backup-source"] = {
            "id": "backup-source",
            "name": "Backup source",
            "status": "done",
            "request": {"url": "source.mp4"},
            "raw_shorts": [{"title": "Backup clip", "clip_url": str(media_root / "clip.mp4")}],
            "logs": [],
            "created_at": time.time(),
            "credentials": {"muapi": "should-not-export"},
            "output_dir": str(media_root),
        }
        studio._persist_job_locked(studio._jobs["backup-source"])

    backup = client.get("/api/backup")
    assert backup.status_code == 200
    with zipfile.ZipFile(io.BytesIO(backup.content)) as archive:
        assert {"backup.json", "jobs.json", "studio_state.json", "brand_presets.json"}.issubset(archive.namelist())
        assert "should-not-export" not in archive.read("jobs.json").decode("utf-8")
        assert str(media_root).encode() not in archive.read("jobs.json")

    media_backup = client.get("/api/backup", params={"include_media": "true"})
    assert media_backup.status_code == 200
    with zipfile.ZipFile(io.BytesIO(media_backup.content)) as archive:
        assert "media/backup-source/clip.mp4" in archive.namelist()
        manifest = json.loads(archive.read("media_manifest.json"))
        assert manifest["count"] == 1
        assert archive.read("media/backup-source/clip.mp4") == b"backup-media"

    with studio._lock:
        studio._jobs.pop("backup-source", None)
    restored_media = client.post(
        "/api/restore?confirm=true",
        files={"file": ("media-backup.zip", media_backup.content, "application/zip")},
    )
    assert restored_media.status_code == 200
    assert restored_media.json()["restored_media_files"] == 1
    restored_clip = studio._jobs["backup-source"]["raw_shorts"][0]["clip_url"]
    assert os.path.isfile(restored_clip)
    with open(restored_clip, "rb") as restored_file:
        assert restored_file.read() == b"backup-media"

    imported_job = {
        "id": "restored-job",
        "status": "running",
        "request": {"url": "restored.mp4"},
        "output_dir": "C:/outside/should-not-be-trusted",
        "logs": [],
        "created_at": time.time(),
    }
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("jobs.json", json.dumps([imported_job]))
    restored = client.post(
        "/api/restore?confirm=true",
        files={"file": ("backup.zip", payload.getvalue(), "application/zip")},
    )
    assert restored.status_code == 200
    assert restored.json()["imported_jobs"] == 1
    assert studio._jobs["restored-job"]["status"] == "interrupted"
    assert studio._jobs["restored-job"]["output_dir"].endswith("restored-job")

    old_preview = studio._output_root / "jobs" / "backup-source" / "previews"
    old_preview.mkdir(parents=True, exist_ok=True)
    preview_file = old_preview / "old.json"
    preview_file.write_text("{}", encoding="utf-8")
    old_time = time.time() - 40 * 86400
    os.utime(preview_file, (old_time, old_time))
    cleaned = client.post("/api/storage/cleanup", json={"confirm": True, "older_than_days": 30})
    assert cleaned.status_code == 200
    assert not preview_file.exists()


def test_transcript_brand_and_publishing_endpoints(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(studio, "_min_free_gb", 0)
    with studio._lock:
        studio._jobs["editor-job"] = {
            "id": "editor-job",
            "name": "Editor project",
            "status": "done",
            "request": {"url": "source.mp4", "mode": "local"},
            "result": {"mode": "local", "shorts": []},
            "raw_shorts": [{"title": "Hook", "start_time": 0, "end_time": 8, "clip_url": None}],
            "raw_transcript": {"duration": 8, "segments": [{"start": 0, "end": 2, "text": "Old text"}]},
            "logs": [],
            "created_at": time.time(),
        }
        studio._persist_job_locked(studio._jobs["editor-job"])

    updated = client.patch(
        "/api/jobs/editor-job/transcript",
        json={"duration": 8, "segments": [{"start": 0, "end": 2, "text": "Edited text"}]},
    )
    assert updated.status_code == 200
    assert studio._jobs["editor-job"]["raw_transcript"]["segments"][0]["text"] == "Edited text"

    preset = client.post("/api/brand-presets", json={"name": "Demo", "caption_color": "#123456"})
    assert preset.status_code == 200
    assert client.get("/api/brand-presets").json()["presets"][0]["name"] == "Demo"
    assert client.delete("/api/brand-presets/Demo").status_code == 200

    publishing = client.get("/api/jobs/editor-job/publishing", params={"platform": "tiktok"})
    assert publishing.status_code == 200
    assert "tiktok" in publishing.json()["items"]
    invalid_platform = client.get("/api/jobs/editor-job/publishing", params={"platform": "facebook"})
    assert invalid_platform.status_code == 400
    events = client.get("/api/jobs/editor-job/events")
    assert events.status_code == 200
    assert events.headers["content-type"].startswith("text/event-stream")
    assert '"status": "done"' in events.text


def test_provider_costs_and_publishing_catalog(client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(studio, "_cost_rates_path", tmp_path / "provider_costs.json")
    initial = client.get("/api/provider-costs")
    assert initial.status_code == 200
    saved = client.put(
        "/api/provider-costs",
        json={
            "openai_input_usd_per_million": 1.0,
            "openai_output_usd_per_million": 2.0,
            "gemini_input_usd_per_million": 0,
            "gemini_output_usd_per_million": 0,
            "muapi_input_usd_per_million": 0,
            "muapi_output_usd_per_million": 0,
        },
    )
    assert saved.status_code == 200
    assert saved.json()["rates"]["openai_output_usd_per_million"] == 2.0
    platforms = client.get("/api/publishing/platforms")
    assert platforms.status_code == 200
    assert {item["key"] for item in platforms.json()["platforms"]} == {
        "youtube_shorts",
        "tiktok",
        "instagram_reels",
    }


def test_external_local_paths_are_rejected_without_explicit_opt_in(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "outside.mp4"
    source.write_bytes(b"fixture")
    request = studio.JobRequest.model_validate({"url": str(source), "mode": "local"})
    monkeypatch.setattr(studio, "_allow_external_paths", False)
    with pytest.raises(Exception, match="inside the configured output folder"):
        studio._validate_local_paths(request)


def test_persisted_media_resolvers_do_not_trust_external_job_state(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    source = outside / "source.mp4"
    source.write_bytes(b"fixture")
    job = {"id": "resolver-job", "output_dir": str(outside)}
    monkeypatch.setattr(studio, "_allow_external_paths", False)

    assert studio._job_output_dir(job) == (studio._jobs_dir / "resolver-job").resolve()
    assert studio._job_source_path(job, source) is None


def test_project_library_supports_more_than_twenty_records_and_search(client: TestClient) -> None:
    with studio._lock:
        for index in range(25):
            job_id = f"library-page-{index:02d}"
            studio._jobs[job_id] = {
                "id": job_id,
                "name": f"Library pagination {index}",
                "status": "draft",
                "request": {"url": f"https://example.com/library-pagination-{index}"},
                "logs": [],
                "created_at": time.time() + index,
            }
            studio._persist_job_locked(studio._jobs[job_id])

    page = client.get("/api/jobs", params={"limit": 100})
    assert page.status_code == 200
    assert page.json()["total"] >= 25
    assert len(page.json()["jobs"]) >= 25

    search = client.get("/api/jobs", params={"q": "library-pagination-17", "limit": 100})
    assert search.status_code == 200
    assert [job["id"] for job in search.json()["jobs"]] == ["library-page-17"]
