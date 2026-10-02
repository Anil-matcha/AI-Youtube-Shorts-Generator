"""Explicit provider dispatch, durable idempotency, and uncertain-state safety."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import web.app as studio
import web.provider_schedule as scheduling
import web.publishing as publishing


@pytest.fixture()
def provider_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    def no_network(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("Provider tests must not send real network requests")

    monkeypatch.setattr(publishing.requests, "request", no_network)
    monkeypatch.setattr(publishing.requests, "post", no_network)
    monkeypatch.setattr(scheduling, "youtube_oauth_status", lambda: {"authorized": True})
    monkeypatch.setattr(studio, "_clip_edit_counts", {}, raising=False)
    with studio._lock:
        studio._jobs.clear()
    with TestClient(studio.app, base_url="http://127.0.0.1") as client:
        yield client
    with studio._lock:
        studio._jobs.clear()


def _job() -> dict:
    job_id = "provider-schedule-job"
    job = {
        "id": job_id,
        "name": "Scheduled review",
        "status": "done",
        "raw_shorts": [],
        "raw_transcript": {"segments": []},
        "variants": [],
        "publishing": [],
        "logs": [],
        "factory": {"enabled": False, "approvals": []},
    }
    folder = studio._job_output_dir(job)
    folder.mkdir(parents=True, exist_ok=True)
    clip = folder / "schedule.mp4"
    clip.write_bytes(b"approved clip bytes")
    job["raw_shorts"] = [{"title": "A useful moment", "hook_sentence": "Look at this", "clip_url": str(clip), "start_time": 10, "end_time": 30}]
    with studio._lock:
        studio._jobs[job_id] = job
    return job


def _create(client: TestClient, *, platform: str = "youtube_shorts", minutes: int = 120) -> tuple[dict, dict]:
    job = _job()
    response = client.post(
        "/api/scheduler",
        json={"job_id": job["id"], "clip_index": 0, "platform": platform, "publish_at": (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()},
    )
    assert response.status_code == 200, response.text
    return job, job["schedule"][0]


def _approve(client: TestClient, entry: dict) -> None:
    response = client.post(f"/api/scheduler/{entry['id']}/decision", json={"decision": "approved"})
    assert response.status_code == 200, response.text


def _dispatch(client: TestClient, entry: dict) -> Any:
    return client.post(f"/api/scheduler/{entry['id']}/dispatch", json={"confirm": True, "acknowledge_public_publish": True})


def test_schedule_creation_and_approval_never_upload(provider_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    monkeypatch.setattr(scheduling, "upload_youtube_video", lambda *_a, **_kw: calls.append(True))
    job, entry = _create(provider_client)
    _approve(provider_client, entry)
    assert calls == []
    assert entry["status"] == "approved_pending_publish"
    assert entry["approval_fingerprint"]
    saved = json.loads(studio._job_path(job["id"]).read_text(encoding="utf-8"))
    assert saved["schedule"][0]["approval_fingerprint"] == entry["approval_fingerprint"]
    assert "clip_url" not in entry["approved_payload"]
    capabilities = provider_client.get("/api/scheduler/capabilities").json()
    assert capabilities["platforms"]["youtube_shorts"]["provider_scheduling"] is True
    assert capabilities["platforms"]["tiktok"]["provider_scheduling"] is False
    assert capabilities["platforms"]["instagram_reels"]["provider_scheduling"] is False


@pytest.mark.parametrize("body", [{}, {"confirm": True}, {"acknowledge_public_publish": True}])
def test_dispatch_requires_both_confirmations(provider_client: TestClient, body: dict) -> None:
    _job_record, entry = _create(provider_client)
    _approve(provider_client, entry)
    response = provider_client.post(f"/api/scheduler/{entry['id']}/dispatch", json=body)
    assert response.status_code == 400
    assert response.json()["code"] == "schedule_confirmation_required"
    assert entry["status"] == "approved_pending_publish"


@pytest.mark.parametrize("state", ["pending_review", "rejected", "cancelled"])
def test_unapproved_or_terminal_entries_cannot_dispatch(provider_client: TestClient, state: str) -> None:
    _job_record, entry = _create(provider_client)
    if state == "rejected":
        assert provider_client.post(f"/api/scheduler/{entry['id']}/decision", json={"decision": "rejected"}).status_code == 200
    elif state == "cancelled":
        assert provider_client.delete(f"/api/scheduler/{entry['id']}").status_code == 200
    assert _dispatch(provider_client, entry).status_code == 409


def test_completed_dispatch_is_durable_and_duplicate_replays(provider_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def upload(media: Path, **payload: Any) -> dict:
        calls.append((media, payload))
        # The in-flight claim must already be on disk before bytes leave.
        saved = json.loads(studio._job_path("provider-schedule-job").read_text(encoding="utf-8"))
        assert saved["schedule"][0]["status"] == "provider_dispatching"
        return {"video_id": "abcdefghijk", "url": "https://youtu.be/abcdefghijk", "privacy_status": "private", "status": "uploaded"}

    monkeypatch.setattr(scheduling, "upload_youtube_video", upload)
    job, entry = _create(provider_client)
    _approve(provider_client, entry)
    response = _dispatch(provider_client, entry)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "provider_scheduled"
    assert calls[0][1]["publish_at"] == entry["publish_at"]
    assert calls[0][1]["privacy_status"] == "private"
    assert len(job["publishing"]) == 1
    saved = json.loads(studio._job_path(job["id"]).read_text(encoding="utf-8"))
    # Replay comes from persisted state, not only the adapter's process cache.
    with studio._lock:
        studio._jobs[job["id"]] = saved
    repeated = _dispatch(provider_client, entry)
    assert repeated.status_code == 200
    assert repeated.json()["replayed"] is True
    assert len(calls) == 1
    cancel = provider_client.delete(f"/api/scheduler/{entry['id']}")
    assert cancel.status_code == 409
    assert cancel.json()["code"] == "provider_schedule_active"


def test_dispatch_uploads_immutable_asset_copies_and_cleans_them(provider_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    job, entry = _create(provider_client)
    thumbnail = studio._job_output_dir(job) / "approved-thumbnail.png"
    thumbnail.write_bytes(b"approved thumbnail")
    job["raw_shorts"][0]["thumbnail_path"] = str(thumbnail)
    job["raw_transcript"]["segments"] = [{"start": 10, "end": 20, "text": "Approved caption text"}]
    _approve(provider_client, entry)
    copies = []

    def upload(*_args: Any, **payload: Any) -> dict:
        thumbnail_copy = payload["thumbnail_path"]
        caption_copy = payload["captions_path"]
        copies.extend([thumbnail_copy, caption_copy])
        assert thumbnail_copy != thumbnail
        assert thumbnail_copy.read_bytes() == b"approved thumbnail"
        assert "Approved caption text" in caption_copy.read_text(encoding="utf-8")
        thumbnail.write_bytes(b"changed while uploading")
        # A generic publish can rewrite its deterministic caption file, while
        # transcript editing can change future caption generation.
        (studio._job_output_dir(job) / "youtube_caption_01.srt").write_text("New captions", encoding="utf-8")
        job["raw_transcript"]["segments"][0]["text"] = "Changed caption text"
        assert thumbnail_copy.read_bytes() == b"approved thumbnail"
        assert "Approved caption text" in caption_copy.read_text(encoding="utf-8")
        return {"video_id": "abcdefghijk", "status": "uploaded"}

    monkeypatch.setattr(scheduling, "upload_youtube_video", upload)
    assert _dispatch(provider_client, entry).status_code == 200
    assert len(copies) == 2
    assert all(not path.exists() for path in copies)


@pytest.mark.parametrize("mutation", ["bytes", "metadata", "request", "thumbnail", "captions"])
def test_approval_is_invalidated_by_changed_clip_or_payload(provider_client: TestClient, mutation: str) -> None:
    job, entry = _create(provider_client)
    _approve(provider_client, entry)
    if mutation == "bytes":
        Path(job["raw_shorts"][0]["clip_url"]).write_bytes(b"changed clip bytes!")
    elif mutation == "metadata":
        job["raw_shorts"][0]["hook_sentence"] = "A different story"
    elif mutation == "request":
        entry["request"]["description"] = "New publish metadata"
    elif mutation == "thumbnail":
        thumbnail = studio._job_output_dir(job) / "changed.png"
        thumbnail.write_bytes(b"new thumbnail")
        job["raw_shorts"][0]["thumbnail_path"] = str(thumbnail)
    else:
        job["raw_transcript"]["segments"] = [{"start": 10, "end": 20, "text": "New captions"}]
    response = _dispatch(provider_client, entry)
    assert response.status_code == 409
    assert response.json()["code"] == "approval_stale"
    assert entry["status"] == "pending_review"


def test_factory_revocation_blocks_a_previously_approved_schedule(provider_client: TestClient) -> None:
    job, entry = _create(provider_client)
    job["factory"] = {"enabled": True, "approvals": [{"clip_index": 0, "decision": "approved"}]}
    _approve(provider_client, entry)
    job["factory"]["approvals"].append({"clip_index": 0, "decision": "rejected"})
    response = _dispatch(provider_client, entry)
    assert response.status_code == 409
    assert response.json()["code"] == "factory_approval_required"


def test_provider_scheduling_is_youtube_only(provider_client: TestClient) -> None:
    _job_record, entry = _create(provider_client, platform="tiktok")
    _approve(provider_client, entry)
    response = _dispatch(provider_client, entry)
    assert response.status_code == 400
    assert response.json()["code"] == "provider_schedule_unsupported"


def test_authorization_and_five_minute_lead_required(provider_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _job_record, entry = _create(provider_client, minutes=2)
    _approve(provider_client, entry)
    response = _dispatch(provider_client, entry)
    assert response.status_code == 409
    assert response.json()["code"] == "schedule_too_soon"
    _job_record, entry = _create(provider_client)
    _approve(provider_client, entry)
    monkeypatch.setattr(scheduling, "youtube_oauth_status", lambda: {"authorized": False})
    response = _dispatch(provider_client, entry)
    assert response.status_code == 400
    assert response.json()["code"] == "credentials_required"


@pytest.mark.parametrize("endpoint", ["publish", "youtube/publish"])
def test_legacy_publishing_cannot_bypass_schedule_review(provider_client: TestClient, endpoint: str) -> None:
    job = _job()
    body = {"platform": "youtube_shorts", "clip_index": 0, "publish_at": (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()}
    preview = provider_client.post(f"/api/jobs/{job['id']}/{endpoint}", json=body)
    assert preview.status_code == 200
    dispatched = provider_client.post(f"/api/jobs/{job['id']}/{endpoint}", json={**body, "confirm": True})
    assert dispatched.status_code == 409
    assert dispatched.json()["code"] == "schedule_review_required"


def test_clip_edit_reservation_blocks_schedule_review_and_dispatch(provider_client: TestClient) -> None:
    job, entry = _create(provider_client)
    studio._clip_edit_counts[job["id"]] = 1
    approval = provider_client.post(f"/api/scheduler/{entry['id']}/decision", json={"decision": "approved"})
    assert approval.status_code == 409
    assert approval.json()["code"] == "clip_edit_busy"
    studio._clip_edit_counts.clear()
    _approve(provider_client, entry)
    studio._clip_edit_counts[job["id"]] = 1
    dispatched = _dispatch(provider_client, entry)
    assert dispatched.status_code == 409
    assert dispatched.json()["code"] == "clip_edit_busy"
    assert entry["status"] == "approved_pending_publish"


def test_inflight_duplicate_and_cancellation_cannot_send_twice(provider_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    entered = threading.Event()
    release = threading.Event()
    results = []

    def upload(*_args: Any, **_kwargs: Any) -> dict:
        entered.set()
        assert release.wait(10)
        return {"video_id": "abcdefghijk", "status": "uploaded"}

    monkeypatch.setattr(scheduling, "upload_youtube_video", upload)
    job, entry = _create(provider_client)
    _approve(provider_client, entry)
    worker = threading.Thread(target=lambda: results.append(_dispatch(provider_client, entry)))
    worker.start()
    try:
        assert entered.wait(10)
        assert scheduling.dispatch_inflight(job)
        duplicate = _dispatch(provider_client, entry)
        assert duplicate.status_code == 409
        assert duplicate.json()["code"] == "dispatch_inflight"
        assert provider_client.delete(f"/api/scheduler/{entry['id']}").status_code == 409
        assert provider_client.delete(f"/api/jobs/{job['id']}").status_code == 409
        assert provider_client.post(f"/api/jobs/{job['id']}/retry").status_code == 409
        edit = provider_client.post(f"/api/jobs/{job['id']}/clips/0", json={"start_time": 10, "end_time": 25})
        assert edit.status_code == 409
    finally:
        release.set()
        worker.join(10)
    assert not worker.is_alive()
    assert results[0].status_code == 200
    assert len(job["publishing"]) == 1


def test_cancel_while_waiting_for_media_lock_prevents_upload(provider_client: TestClient) -> None:
    job, entry = _create(provider_client)
    _approve(provider_client, entry)
    results = []
    with studio._artifact_lock(job["raw_shorts"][0]["clip_url"]):
        worker = threading.Thread(target=lambda: results.append(_dispatch(provider_client, entry)))
        worker.start()
        response = provider_client.delete(f"/api/scheduler/{entry['id']}")
        assert response.status_code == 200
    worker.join(10)
    assert not worker.is_alive()
    assert results[0].status_code == 409
    assert entry["status"] == "cancelled"


def test_safe_prebyte_failure_has_bounded_explicit_retries(provider_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def fail(*_args: Any, **_kwargs: Any) -> None:
        calls.append(True)
        raise publishing.YouTubePublishError("Quota exceeded", code="quota_exceeded", status_code=429, external_state="not_created")

    monkeypatch.setattr(scheduling, "upload_youtube_video", fail)
    _job_record, entry = _create(provider_client)
    _approve(provider_client, entry)
    failed = _dispatch(provider_client, entry)
    assert failed.status_code == 429
    assert failed.json()["can_retry"] is True
    assert entry["status"] == "retryable_failed"
    assert _dispatch(provider_client, entry).json()["code"] == "dispatch_backoff"
    assert len(calls) == 1
    entry["retry_after"] = 0
    assert _dispatch(provider_client, entry).status_code == 429
    assert len(calls) == 2
    entry["dispatch_attempts"] = 5
    assert _dispatch(provider_client, entry).json()["code"] == "dispatch_retry_limit"


def test_ambiguous_network_failure_blocks_blind_retry_and_recovers_after_restart(provider_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def fail(*_args: Any, **_kwargs: Any) -> None:
        calls.append(True)
        raise publishing.YouTubePublishError("Lost final upload response access_token=secret", code="dependency_failure")

    monkeypatch.setattr(scheduling, "upload_youtube_video", fail)
    job, entry = _create(provider_client)
    _approve(provider_client, entry)
    failed = _dispatch(provider_client, entry)
    assert failed.status_code == 502
    assert failed.json()["can_retry"] is False
    assert "secret" not in failed.text
    assert entry["status"] == "provider_unknown"
    assert _dispatch(provider_client, entry).json()["code"] == "provider_state_unknown"
    assert len(calls) == 1
    assert provider_client.delete(f"/api/scheduler/{entry['id']}").status_code == 409
    entry["status"] = "provider_dispatching"
    assert scheduling.recover_interrupted_dispatches(job) is True
    assert entry["status"] == "provider_unknown"
    assert scheduling.provider_schedule_active(job) is True
    assert scheduling.recover_interrupted_dispatches(job) is False


def test_reconcile_reads_and_matches_the_approved_provider_schedule(provider_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _job_record, entry = _create(provider_client)
    _approve(provider_client, entry)
    entry["status"] = "provider_unknown"
    entry["dispatch_key"] = "original-attempt"
    approved = entry["approved_payload"]
    actual = {"video_id": "abcdefghijk", "url": "https://youtu.be/abcdefghijk", "privacy_status": "private", "publish_at": approved["publish_at"], "upload_status": "processed", "title": approved["title"], "description": approved["description"], "category_id": approved["category_id"], "tags": approved["tags"]}
    monkeypatch.setattr(scheduling, "youtube_video_schedule", lambda _id: actual)
    actual["privacy_status"] = "public"
    mismatch = provider_client.post(f"/api/scheduler/{entry['id']}/reconcile", json={"confirm": True, "video_id": "abcdefghijk"})
    assert mismatch.status_code == 409
    assert entry["status"] == "provider_unknown"
    actual["privacy_status"] = "private"
    response = provider_client.post(f"/api/scheduler/{entry['id']}/reconcile", json={"confirm": True, "video_id": "abcdefghijk"})
    assert response.status_code == 200
    assert entry["status"] == "provider_scheduled"
    assert entry["provider_result"]["status"] == "reconciled"


@pytest.mark.parametrize("state", ["provider_unknown", "provider_scheduled"])
def test_external_schedule_audit_cannot_be_deleted(provider_client: TestClient, state: str) -> None:
    job, entry = _create(provider_client)
    entry["status"] = state
    response = provider_client.delete(f"/api/jobs/{job['id']}")
    assert response.status_code == 409
    assert response.json()["code"] == "provider_schedule_active"
    assert job["id"] in studio._jobs


@pytest.mark.parametrize(
    "privacy,scheduled,upload_state,expected",
    [
        ("private", True, "processed", "provider_scheduled"),
        ("public", False, "processed", "provider_published"),
        ("private", False, "processed", "provider_unscheduled"),
        ("unlisted", False, "processed", "provider_unscheduled"),
        ("private", False, "rejected", "provider_rejected"),
        ("private", False, "deleted", "provider_removed"),
    ],
)
def test_refresh_observes_owner_verified_completion_or_unscheduling(
    provider_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    privacy: str,
    scheduled: bool,
    upload_state: str,
    expected: str,
) -> None:
    job, entry = _create(provider_client)
    entry["status"] = "provider_scheduled"
    entry["provider_result"] = {"video_id": "abcdefghijk"}
    result = {"video_id": "abcdefghijk", "owner_verified": True, "privacy_status": privacy, "publish_at": entry["publish_at"] if scheduled else "", "upload_status": upload_state}
    monkeypatch.setattr(scheduling, "youtube_video_schedule", lambda _id: result)
    response = provider_client.post(f"/api/scheduler/{entry['id']}/refresh", json={"confirm": True})
    assert response.status_code == 200, response.text
    assert entry["status"] == expected
    assert entry["provider_observation"]["video_id"] == "abcdefghijk"
    assert scheduling.provider_schedule_active(job) is (expected == "provider_scheduled")
    if expected != "provider_scheduled":
        assert provider_client.delete(f"/api/jobs/{job['id']}").status_code == 200


def test_refresh_cannot_treat_missing_or_nonowner_video_as_cancelled(provider_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _job_record, entry = _create(provider_client)
    entry["status"] = "provider_scheduled"
    entry["provider_result"] = {"video_id": "abcdefghijk"}
    monkeypatch.setattr(scheduling, "youtube_video_schedule", lambda _id: {"video_id": "abcdefghijk", "owner_verified": False, "privacy_status": "public"})
    response = provider_client.post(f"/api/scheduler/{entry['id']}/refresh", json={"confirm": True})
    assert response.status_code == 409
    assert response.json()["code"] == "provider_refresh_unverified"
    assert entry["status"] == "provider_scheduled"

    def missing(_id: str) -> dict:
        raise ValueError("video not returned")

    monkeypatch.setattr(scheduling, "youtube_video_schedule", missing)
    response = provider_client.post(f"/api/scheduler/{entry['id']}/refresh", json={"confirm": True})
    assert response.status_code == 409
    assert entry["status"] == "provider_scheduled"


def test_youtube_schedule_lookup_is_a_fixed_read_only_api_query(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    class Response:
        status_code = 200

        def json(self) -> dict:
            return {"items": [{"id": "abcdefghijk", "snippet": {"title": "A title", "description": "A description", "categoryId": "22"}, "status": {"privacyStatus": "private", "publishAt": "2030-01-01T12:00:00Z", "uploadStatus": "uploaded", "selfDeclaredMadeForKids": False}}]}

    def request(method: str, url: str, **kwargs: Any) -> Response:
        calls.append((method, url, kwargs))
        return Response()

    monkeypatch.setattr(publishing.requests, "request", request)
    monkeypatch.setattr(publishing, "_youtube_access_token", lambda: "local-token")
    result = publishing.youtube_video_schedule("abcdefghijk")
    assert result["publish_at"] == "2030-01-01T12:00:00Z"
    assert result["owner_verified"] is True
    assert calls[0][0] == "GET"
    assert calls[0][1] == "https://www.googleapis.com/youtube/v3/videos"
    assert calls[0][2]["params"] == {"id": "abcdefghijk", "part": "snippet,status"}
    with pytest.raises(ValueError):
        publishing.youtube_video_schedule("https://unsafe.test/video")
    assert len(calls) == 1
