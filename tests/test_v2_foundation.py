"""Coverage for the v2 story-search, policy, scheduler, and telemetry seams."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import web.app as studio


@pytest.fixture()
def v2_foundation_client() -> TestClient:
    with studio._lock:
        studio._jobs.clear()
        studio._job_credentials.clear()
        studio._cancel_events.clear()
    with TestClient(studio.app, base_url="http://127.0.0.1") as test_client:
        yield test_client
    with studio._lock:
        studio._jobs.clear()
        studio._job_credentials.clear()
        studio._cancel_events.clear()


def _foundation_job(job_id: str = "v2-foundation-job") -> dict:
    return {
        "id": job_id,
        "name": "Foundation demo",
        "status": "done",
        "raw_transcript": {
            "segments": [
                {
                    "start": 4,
                    "end": 12,
                    "text": "The reaction is the useful part. C:\\private\\source.mp4 https://media.example/clip?access_token=do-not-leak",
                }
            ],
            "chapters": [{"title": "The useful reaction", "start_time": 4, "end_time": 12}],
            "visual_events": [{"time": 7, "type": "speaker_visible", "score": 0.8}],
        },
        "raw_shorts": [
            {
                "title": "The useful reaction",
                "hook_sentence": "The reaction is the useful part.",
                "start_time": 4,
                "end_time": 12,
            }
        ],
        "factory": {"enabled": False, "approvals": []},
        "variants": [],
        "analytics": [],
        "publishing": [],
        "logs": [],
    }


def test_story_search_returns_bounded_transcript_and_visual_hits_without_urls(
    v2_foundation_client: TestClient,
) -> None:
    with studio._lock:
        studio._jobs["v2-foundation-job"] = _foundation_job()

    response = v2_foundation_client.post("/api/story/search", json={"query": "reaction", "limit": 10})
    assert response.status_code == 200
    payload = response.json()
    assert payload["result_count"] >= 2
    assert {item["kind"] for item in payload["results"]} >= {"transcript", "highlight"}
    assert any(item["visual_signals"] for item in payload["results"])
    assert "do-not-leak" not in response.text
    assert "private\\source.mp4" not in response.text


def test_policy_preflight_blocks_an_overlong_clip_and_publish_plan_exposes_policy(
    v2_foundation_client: TestClient,
) -> None:
    job = _foundation_job()
    job["raw_shorts"][0]["end_time"] = 400
    with studio._lock:
        studio._jobs[job["id"]] = job

    response = v2_foundation_client.post(
        "/api/policy/check",
        json={"job_id": job["id"], "clip_index": 0, "platform": "youtube_shorts"},
    )
    assert response.status_code == 200
    policy = response.json()["policy"]
    assert policy["status"] == "blocked"
    assert any(item["code"] == "clip_too_long" for item in policy["checks"])

    plan = v2_foundation_client.post(
        f"/api/jobs/{job['id']}/publish",
        json={"platform": "youtube_shorts", "clip_index": 0},
    )
    assert plan.status_code == 200
    assert plan.json()["policy"]["status"] == "blocked"

    youtube_plan = v2_foundation_client.post(
        f"/api/jobs/{job['id']}/youtube/publish",
        json={"platform": "youtube_shorts", "clip_index": 0},
    )
    assert youtube_plan.status_code == 200
    assert youtube_plan.json()["plan"]["policy"]["status"] == "blocked"


def test_scheduler_is_review_only_and_decisions_are_durable(v2_foundation_client: TestClient) -> None:
    with studio._lock:
        studio._jobs["v2-foundation-job"] = _foundation_job()
    publish_at = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    request = {
        "job_id": "v2-foundation-job",
        "platform": "youtube_shorts",
        "clip_index": 0,
        "publish_at": publish_at,
        "note": "Review before release",
        "thumbnail_path": "C:\\private\\thumbnail.png",
    }
    created = v2_foundation_client.post("/api/scheduler", json=request)
    assert created.status_code == 200
    entry = created.json()["entry"]
    assert entry["status"] == "pending_review"
    assert "automatically" not in created.text
    assert "thumbnail_path" not in created.text
    assert "private\\thumbnail.png" not in created.text

    listed = v2_foundation_client.get("/api/scheduler?status=pending_review")
    assert listed.status_code == 200
    assert listed.json()["count"] == 1
    schedule_id = entry["id"]
    decided = v2_foundation_client.post(
        f"/api/scheduler/{schedule_id}/decision",
        json={"decision": "approved", "note": "Human reviewed"},
    )
    assert decided.status_code == 200
    assert decided.json()["status"] == "approved_pending_publish"

    cancelled = v2_foundation_client.delete(f"/api/scheduler/{schedule_id}")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"


def test_publishing_telemetry_is_bounded_and_tolerates_malformed_timestamps(
    v2_foundation_client: TestClient,
) -> None:
    job = _foundation_job()
    job["publishing"] = [{"platform": "youtube_shorts", "completed_at": "not-a-number"}]
    job["publishing_errors"] = [
        {"platform": "youtube_shorts", "code": "quota_exceeded", "at": "also-not-a-number"}
    ]
    with studio._lock:
        studio._jobs[job["id"]] = job
    response = v2_foundation_client.get("/api/publishing/telemetry")
    assert response.status_code == 200
    youtube = response.json()["platforms"]["youtube_shorts"]
    assert youtube["attempts"] == 2
    assert youtube["quota_errors"] == 1
    assert youtube["quota_status"] == "throttled"
