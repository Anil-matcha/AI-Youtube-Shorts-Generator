"""Browser guards for opt-in local evidence and explicit provider dispatch."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urlparse

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import Page, expect, sync_playwright  # noqa: E402


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_BROWSER_E2E", "0") != "1",
    reason="set RUN_BROWSER_E2E=1 to run browser coverage",
)


@pytest.fixture()
def phase_browser() -> Iterator[tuple[Page, dict[str, Any]]]:
    root = Path(__file__).resolve().parents[2]
    fixture: dict[str, Any] = {
        "requests": [],
        "authorized": False,
        "ocr_available": True,
        "evidence": {},
        "hold_analysis": False,
        "analysis_route": None,
        "entries": [],
        "provider_next_status": "provider_scheduled",
        "provider_refresh_error": False,
    }

    def fulfill(route: Any, payload: Any, status: int = 200) -> None:
        route.fulfill(status=status, content_type="application/json", body=json.dumps(payload))

    def handle(route: Any) -> None:
        request = route.request
        path = urlparse(request.url).path
        if path == "/":
            route.fulfill(
                content_type="text/html",
                body='<html><body><button data-tab="audioTab">Audio</button>'
                '<button data-tab="exportTab">Export</button><span id="jobBadge"></span>'
                '<span id="jobIdBadge"></span><div id="clipGrid"></div>'
                '<div id="audioTab"></div><div id="exportTab"></div></body></html>',
            )
            return
        body = request.post_data_json if request.post_data else None
        fixture["requests"].append((request.method, path, body))
        if path == "/api/v1/story/models":
            fulfill(
                route,
                {
                    "models": [
                        {"id": "tesseract", "kind": "ocr", "available": fixture["ocr_available"], "label": "Tesseract", "notice": "Local executable required"},
                        {"id": "silero-vad", "kind": "audio", "available": True, "label": "Silero VAD"},
                    ],
                    "budgets": {"max_duration_seconds": 120, "max_frames": 8, "timeout_seconds": 90},
                },
            )
        elif path.endswith("/story/analyze"):
            job = path.split("/")[4]
            if request.method == "GET":
                fulfill(route, {"evidence": fixture["evidence"].get(job), "running": False})
            elif request.method == "POST":
                if fixture["hold_analysis"]:
                    fixture["analysis_route"] = route
                    return
                evidence = {
                    "ocr": [{"start_time": 2, "text": '<img src=x onerror="window.unsafe=true">', "model": "tesseract"}],
                    "audio": [{"start_time": 3, "end_time": 6, "label": "Speech activity", "model": "silero-vad"}],
                }
                fixture["evidence"][job] = evidence
                fulfill(route, {"evidence": evidence})
            elif request.method == "DELETE":
                fixture["evidence"].pop(job, None)
                analysis_route = fixture.get("analysis_route")
                if analysis_route:
                    fulfill(analysis_route, {"error": "Analysis cancelled"}, 409)
                    fixture["analysis_route"] = None
                fulfill(route, {"running": False, "message": "Stored evidence cleared."})
        elif path == "/api/v1/scheduler/capabilities":
            fulfill(route, {"platforms": {"youtube_shorts": {"provider_scheduling": True, "authorized": fixture["authorized"]}}, "notice": "Dispatch requires explicit approval."})
        elif path == "/api/v1/scheduler":
            if request.method == "POST":
                entry = schedule_entry()
                entry.update({"job_id": body["job_id"], "clip_index": body["clip_index"], "publish_at": body["publish_at"], "request": body})
                fixture["entries"].append(entry)
                fulfill(route, {"status": "pending_review", "entry": entry})
            else:
                fulfill(route, {"entries": fixture["entries"]})
        elif path == "/api/v1/youtube/oauth/status":
            fulfill(route, {"authorized": fixture["authorized"], "privacy_default": "private"})
        elif path.startswith("/api/v1/scheduler/"):
            entry = next(item for item in fixture["entries"] if item["id"] == path.split("/")[4])
            if path.endswith("/decision"):
                entry["status"] = "approved_pending_publish" if body["decision"] == "approved" else "rejected"
            elif path.endswith("/dispatch") or path.endswith("/reconcile"):
                entry["status"] = "provider_scheduled"
            elif path.endswith("/refresh"):
                if fixture["provider_refresh_error"]:
                    fulfill(route, {"error": "YouTube state could not be verified; reconnect the account.", "code": "provider_refresh_unverified"}, 409)
                    return
                entry["status"] = fixture["provider_next_status"]
            elif request.method == "DELETE":
                entry["status"] = "cancelled"
            fulfill(route, {"entry": entry})
        else:
            fulfill(route, {})

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.route("http://shorts.test/**", handle)
        page.goto("http://shorts.test/")
        for name in ("state.js", "api.js", "features.js", "evidence.js", "scheduler.js"):
            page.add_script_tag(path=str(root / "web" / "static" / "modules" / name))
        expect(page.locator("#storyOcrEnabled")).to_be_enabled()
        yield page, fixture
        browser.close()


def open_project(page: Page, job: str = "project-one") -> None:
    page.evaluate(
        """job => {
          window.ShortsStudioState.state.activeJobId = job;
          document.getElementById('jobIdBadge').textContent = job;
        }""",
        job,
    )


def schedule_entry(status: str = "pending_review") -> dict[str, Any]:
    return {
        "id": "abcdef1234567890",
        "job_id": "project-one",
        "clip_index": 0,
        "publish_at": "2099-10-01T12:00:00Z",
        "status": status,
        "request": {"platform": "youtube_shorts", "privacy_status": "private"},
        "policy": {"status": "passed"},
    }


def test_evidence_requires_selection_and_keeps_text_safe(phase_browser: tuple[Page, dict[str, Any]]) -> None:
    page, fixture = phase_browser
    expect(page.locator("#storyOcrEnabled")).not_to_be_checked()
    expect(page.locator("#storyAudioEnabled")).not_to_be_checked()
    expect(page.locator("#storyAnalyzeButton")).to_be_disabled()
    open_project(page)
    expect(page.locator("#storyAnalyzeButton")).to_be_disabled()
    assert not any(method == "POST" for method, _, _ in fixture["requests"])
    page.locator("#storyOcrEnabled").check()
    page.locator("#storyAudioEnabled").check()
    page.locator("#storyEvidenceStart").fill("2")
    page.locator("#storyEvidenceDuration").fill("30")
    page.locator("#storyAnalyzeButton").click()
    expect(page.locator("#storyEvidenceStatus")).to_contain_text("saved locally")
    expect(page.locator("#storyEvidenceResults")).to_contain_text("<img src=x")
    assert page.locator("#storyEvidenceResults img").count() == 0
    assert page.evaluate("Boolean(window.unsafe)") is False
    request = next(body for method, path, body in fixture["requests"] if method == "POST" and path.endswith("/story/analyze"))
    assert request == {"ocr_model": "tesseract", "audio_model": "silero-vad", "language": "eng", "start_time": 2, "duration_seconds": 30, "max_frames": 4}
    expect(page.locator("#storyAnalyzeButton")).to_be_enabled()
    page.locator("#storyClearButton").click()
    expect(page.locator("#storyEvidenceResults")).to_contain_text("Analyze a source range")


def test_unavailable_model_and_active_cancel(phase_browser: tuple[Page, dict[str, Any]]) -> None:
    page, fixture = phase_browser
    fixture["ocr_available"] = False
    fixture["hold_analysis"] = True
    page.locator("#storyModelsRefresh").click()
    expect(page.locator("#storyOcrEnabled")).to_be_disabled()
    expect(page.locator("#storyOcrEnabledNotice")).to_contain_text("unavailable")
    open_project(page)
    page.locator("#storyAudioEnabled").check()
    page.locator("#storyAnalyzeButton").click()
    expect(page.locator("#storyCancelButton")).to_be_visible()
    expect(page.locator("#storyAnalyzeButton")).to_be_disabled()
    page.locator("#storyCancelButton").click()
    expect(page.locator("#storyCancelButton")).to_be_hidden()
    assert any(method == "DELETE" and path.endswith("/story/analyze") for method, path, _ in fixture["requests"])


def test_analysis_result_does_not_leak_into_another_project(phase_browser: tuple[Page, dict[str, Any]]) -> None:
    page, fixture = phase_browser
    fixture["hold_analysis"] = True
    open_project(page)
    page.locator("#storyOcrEnabled").check()
    page.locator("#storyAnalyzeButton").click()
    expect(page.locator("#storyCancelButton")).to_be_visible()
    fixture["evidence"]["project-two"] = {"ocr": [{"start_time": 1, "text": "Project two evidence"}]}
    open_project(page, "project-two")
    expect(page.locator("#storyEvidenceResults")).to_contain_text("Project two evidence")
    fixture["analysis_route"].fulfill(content_type="application/json", body=json.dumps({"evidence": {"ocr": [{"text": "Private project one evidence"}]}}))
    expect(page.locator("#storyEvidenceResults")).not_to_contain_text("Private project one evidence")
    expect(page.locator("#storyEvidenceResults")).to_contain_text("Project two evidence")


def test_schedule_approval_requires_separate_authorized_dispatch(phase_browser: tuple[Page, dict[str, Any]]) -> None:
    page, fixture = phase_browser
    fixture["entries"] = [schedule_entry()]
    open_project(page)
    page.get_by_role("button", name="Approve review", exact=True).click()
    expect(page.get_by_role("button", name="Dispatch to YouTube", exact=True)).to_be_disabled()
    warning = page.get_by_label("I approve this upload and its future public publication on YouTube")
    expect(warning).to_be_disabled()
    assert not any(path.endswith("/dispatch") for _, path, _ in fixture["requests"])
    fixture["authorized"] = True
    page.locator("#scheduleReviewRefresh").click()
    expect(warning).to_be_enabled()
    expect(page.locator("#scheduleReviewList")).to_contain_text("YouTube will make this video public")
    expect(page.get_by_role("button", name="Dispatch to YouTube", exact=True)).to_be_disabled()
    warning.check()
    page.get_by_role("button", name="Dispatch to YouTube", exact=True).click()
    expect(page.locator("#scheduleReviewList")).to_contain_text("provider scheduled")
    assert page.get_by_role("button", name="Cancel local intent", exact=True).count() == 0
    assert page.get_by_role("button", name="Dispatch to YouTube", exact=True).count() == 0
    dispatch = next(body for _, path, body in fixture["requests"] if path.endswith("/dispatch"))
    assert dispatch == {"confirm": True, "acknowledge_public_publish": True}
    assert page.get_by_role("link", name="Open YouTube Studio").get_attribute("href") == "https://studio.youtube.com/"


def test_unknown_schedule_requires_provider_reconciliation(phase_browser: tuple[Page, dict[str, Any]]) -> None:
    page, fixture = phase_browser
    fixture["entries"] = [schedule_entry("provider_unknown")]
    fixture["authorized"] = True
    open_project(page)
    expect(page.get_by_role("button", name="Verify uploaded video", exact=True)).to_be_visible()
    assert page.get_by_role("button", name="Dispatch to YouTube", exact=True).count() == 0
    assert page.get_by_role("button", name="Cancel local intent", exact=True).count() == 0
    page.get_by_label("Uploaded YouTube video ID").fill("abcDEF12345")
    page.get_by_role("button", name="Verify uploaded video", exact=True).click()
    expect(page.locator("#scheduleReviewList")).to_contain_text("provider scheduled")
    request = next(body for _, path, body in fixture["requests"] if path.endswith("/reconcile"))
    assert request == {"confirm": True, "video_id": "abcDEF12345"}


@pytest.mark.parametrize("provider_state", ["provider_published", "provider_unscheduled", "provider_rejected", "provider_removed", "provider_scheduled"])
def test_provider_refresh_is_manual_and_observes_terminal_state(
    phase_browser: tuple[Page, dict[str, Any]], provider_state: str,
) -> None:
    page, fixture = phase_browser
    fixture["entries"] = [schedule_entry("provider_scheduled")]
    fixture["provider_next_status"] = provider_state
    open_project(page)
    button = page.get_by_role("button", name="Refresh provider status", exact=True)
    expect(button).to_be_disabled()
    assert not any(path.endswith("/refresh") for _, path, _ in fixture["requests"])
    fixture["authorized"] = True
    page.locator("#scheduleReviewRefresh").click()
    expect(button).to_be_enabled()
    assert not any(path.endswith("/refresh") for _, path, _ in fixture["requests"])
    button.click()
    expect(page.locator("#scheduleReviewList")).to_contain_text(provider_state.replace("_", " "))
    assert page.get_by_role("button", name="Dispatch to YouTube", exact=True).count() == 0
    assert page.get_by_role("button", name="Cancel local intent", exact=True).count() == 0
    requests = [(method, body) for method, path, body in fixture["requests"] if path.endswith("/refresh")]
    assert requests == [("POST", {"confirm": True})]
    if provider_state != "provider_scheduled":
        expect(button).to_have_count(0)


def test_unverified_provider_refresh_preserves_active_schedule(phase_browser: tuple[Page, dict[str, Any]]) -> None:
    page, fixture = phase_browser
    fixture["entries"] = [schedule_entry("provider_scheduled")]
    fixture["authorized"] = True
    fixture["provider_refresh_error"] = True
    open_project(page)
    page.get_by_role("button", name="Refresh provider status", exact=True).click()
    expect(page.locator("#scheduleReviewStatus")).to_contain_text("could not be verified")
    expect(page.locator("#scheduleReviewList")).to_contain_text("provider scheduled")
    assert page.get_by_role("button", name="Cancel local intent", exact=True).count() == 0
    assert fixture["entries"][0]["status"] == "provider_scheduled"


def test_future_youtube_date_queues_review_and_blocks_direct_upload(phase_browser: tuple[Page, dict[str, Any]]) -> None:
    """Exercise the existing controls so their scheduling guard cannot block queueing."""
    page, fixture = phase_browser
    assert not any(method == "POST" for method, _, _ in fixture["requests"])
    open_project(page)
    page.evaluate("window.ShortsStudioState.state.selectedClip = 2")
    page.locator("#youtubePublishAt").fill("2099-10-01T12:00")
    page.locator("#youtubeConfirm").check()
    expected_time = page.locator("#youtubePublishAt").evaluate("input => new Date(input.value).toISOString()")
    page.locator("#youtubePublishButton").click()
    expect(page.locator("#youtubePublishStatus")).to_contain_text("YouTube will publish it publicly at the selected time")
    assert not any(path.endswith("/youtube/publish") for _, path, _ in fixture["requests"])
    page.locator("#youtubeScheduleButton").click()
    expect(page.locator("#youtubePublishStatus")).to_contain_text("Private review intent queued")
    queued = [(method, body) for method, path, body in fixture["requests"] if path == "/api/v1/scheduler" and method == "POST"]
    assert queued == [
        (
            "POST",
            {
                "job_id": "project-one",
                "platform": "youtube_shorts",
                "clip_index": 2,
                "publish_at": expected_time,
                "privacy_status": "private",
                "note": "Queued from the Shorts Studio review panel",
            },
        )
    ]
    assert not any(path.endswith("/youtube/publish") or path.endswith("/dispatch") for _, path, _ in fixture["requests"])
    page.locator("#scheduleReviewRefresh").click()
    expect(page.locator("#scheduleReviewList")).to_contain_text("pending review")
    expect(page.locator("#scheduleReviewList")).to_contain_text("clip 3")
