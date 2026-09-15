"""Optional Playwright smoke and accessibility coverage for the creator flow.

The suite is opt-in because normal unit tests must remain network-free and do
not require a browser binary. CI enables ``RUN_BROWSER_E2E=1`` and installs
Chromium before running it.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict

import pytest

playwright = pytest.importorskip("playwright.sync_api")
from playwright.sync_api import Page, sync_playwright  # noqa: E402


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_BROWSER_E2E", "0") != "1",
    reason="set RUN_BROWSER_E2E=1 to run browser coverage",
)


def _json_response(route: Any, payload: Dict[str, Any], status: int = 200) -> None:
    route.fulfill(status=status, content_type="application/json", body=json.dumps(payload))


@pytest.fixture()
def browser_page(tmp_path: Path):
    root = Path(__file__).resolve().parents[2]
    data_root = tmp_path / "data"
    env = os.environ.copy()
    env.update(
        {
            "SHORTS_STUDIO_HEADLESS": "true",
            "SHORTS_AUTO_RESUME": "false",
            "SHORTS_STUDIO_DATA_DIR": str(data_root),
            "LOCAL_OUTPUT_DIR": str(data_root / "output"),
            "SHORTS_API_TOKEN": "",
        }
    )
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "web.app:app", "--host", "127.0.0.1", "--port", "18760"],
        cwd=str(root),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.time() + 25
    while time.time() < deadline:
        try:
            import urllib.request

            urllib.request.urlopen("http://127.0.0.1:18760/api/health", timeout=1).read()
            break
        except Exception:
            time.sleep(0.25)
    else:
        server.kill()
        pytest.fail("browser test server did not start")

    state = {"job_polls": 0}

    def route_api(route: Any) -> None:
        request = route.request
        path = request.url.split("/api", 1)[-1].split("?", 1)[0]
        method = request.method
        if path == "/auth/status":
            _json_response(route, {"enabled": False, "authenticated": True})
        elif path in {"/system", "/setup"}:
            _json_response(
                route,
                {
                    "ffmpeg": True,
                    "ffprobe": True,
                    "whisper_model": "base",
                    "whisper_device": "cpu",
                    "gpu": {"cuda_available": False, "reason": "test"},
                    "free_disk_gb": 50,
                    "max_concurrent_jobs": 2,
                    "keys": {"offline_fallback": True},
                    "storage": {"output_root": str(data_root), "free_disk_gb": 50},
                    "ready_for_local": True,
                    "warnings": [],
                    "first_run": False,
                },
            )
        elif path == "/provider-costs":
            _json_response(route, {"rates": {}, "currency": "USD", "unit": "per_million_tokens"})
        elif path == "/brand-presets":
            _json_response(route, {"presets": []})
        elif path == "/jobs" and method == "GET":
            _json_response(route, {"jobs": [], "total": 0})
        elif path == "/uploads" and method == "POST":
            _json_response(route, {"name": "fixture.mp4", "path": str(data_root / "uploads" / "fixture.mp4"), "size": 4})
        elif path == "/jobs" and method == "POST":
            _json_response(route, {"id": "e2e-job", "status": "queued", "stage": "queued", "progress": 0, "request": {"mode": "local"}})
        elif path == "/jobs/e2e-job" and method == "GET":
            state["job_polls"] += 1
            _json_response(
                route,
                {
                    "id": "e2e-job",
                    "status": "done",
                    "stage": "done",
                    "progress": 100,
                    "message": "Rendered 1 short",
                    "request": {"mode": "local", "aspect_ratio": "9:16"},
                    "result": {
                        "mode": "local",
                        "shorts": [
                            {
                                "title": "Test highlight",
                                "hook_sentence": "A useful hook",
                                "start_time": 0,
                                "end_time": 4,
                                "clip_url": "/api/jobs/e2e-job/clip/0",
                                "play_url": "/api/jobs/e2e-job/clip/0",
                                "thumbnail_url": "/api/jobs/e2e-job/thumbnail/0",
                            }
                        ],
                    },
                },
            )
        elif path == "/jobs/e2e-job/timeline":
            _json_response(route, {"duration": 4, "segments": [{"start": 0, "end": 4, "text": "A useful hook"}]})
        elif path == "/jobs/e2e-job/waveform":
            _json_response(route, {"duration": 4, "peaks": [0.2, 0.8], "available": True})
        elif path == "/jobs/e2e-job/clips/0" and method == "POST":
            _json_response(route, {"id": "e2e-job", "status": "done", "stage": "done", "progress": 100, "result": {"mode": "local", "shorts": [{"title": "Edited", "start_time": 0, "end_time": 3, "clip_url": "/api/jobs/e2e-job/clip/0", "play_url": "/api/jobs/e2e-job/clip/0"}]}})
        elif path == "/jobs/e2e-job/preview" and method == "POST":
            _json_response(route, {"preview_url": "/api/jobs/e2e-job/preview.mp4", "cached": False})
        elif path == "/jobs/e2e-job/export":
            route.fulfill(status=200, content_type="application/zip", body=b"PK\x03\x04test")
        elif path.startswith("/jobs/e2e-job/clip/") or path.startswith("/jobs/e2e-job/thumbnail/") or path.endswith("/preview.mp4"):
            route.fulfill(status=200, content_type="video/mp4", body=b"fixture")
        elif path == "/jobs/e2e-job/transcript" and method == "PATCH":
            _json_response(route, {"id": "e2e-job", "status": "done", "result": {"mode": "local", "shorts": []}})
        else:
            _json_response(route, {})

    with sync_playwright() as playwright_instance:
        browser = playwright_instance.chromium.launch(headless=True)
        page = browser.new_page()
        page.route("**/api/**", route_api)
        page.goto("http://127.0.0.1:18760/", wait_until="networkidle")
        yield page
        browser.close()
    server.terminate()
    try:
        server.wait(timeout=5)
    except subprocess.TimeoutExpired:
        server.kill()


def test_upload_render_edit_preview_export(browser_page: Page, tmp_path: Path) -> None:
    page = browser_page
    page.locator("#newProjectButton").click()
    page.locator("#workspaceView").wait_for(state="visible")
    fixture = tmp_path / "fixture.mp4"
    fixture.write_bytes(b"test")
    page.set_input_files("#fileInput", str(fixture))
    assert page.locator("#sourceInput").input_value().endswith("fixture.mp4")
    page.locator("#generateButton").click()
    page.locator('[data-clip-card="0"]').wait_for(state="visible", timeout=10000)
    page.locator('[data-card-end="0"]').fill("3")
    page.locator('[data-regenerate="0"]').click()
    page.locator('[data-preview="0"]').click()
    page.locator("#previewBadge").wait_for(state="visible")
    page.locator('[data-tab="exportTab"]').click()
    page.locator("#exportButton").wait_for(state="visible")
    with page.expect_download(timeout=5000) as download_info:
        page.locator("#exportButton").click()
    assert download_info.value.suggested_filename


def test_workspace_has_basic_accessibility_names(browser_page: Page) -> None:
    page = browser_page
    page.locator("#newProjectButton").click()
    page.locator("#workspaceView").wait_for(state="visible")
    violations = page.evaluate(
        """
        () => {
          const unnamed = [];
          document.querySelectorAll('button, input, select, textarea').forEach((el) => {
            if (el.disabled || el.hidden) return;
            const labelled = el.getAttribute('aria-label') || el.getAttribute('aria-labelledby') ||
              (el.id && document.querySelector(`label[for="${CSS.escape(el.id)}"]`)) ||
              el.closest('label') ||
              (el.tagName === 'BUTTON' && (el.innerText || el.title));
            if (!labelled) unnamed.push(el.outerHTML.slice(0, 160));
          });
          document.querySelectorAll('img').forEach((el) => { if (!el.hasAttribute('alt')) unnamed.push('img without alt'); });
          return unnamed;
        }
        """
    )
    assert violations == []


def test_v0102_frontend_modules_progress_and_keyboard_tabs(browser_page: Page) -> None:
    page = browser_page
    page.locator("#newProjectButton").click()
    page.locator("#workspaceView").wait_for(state="visible")
    assert page.locator('meta[name="shorts-studio-version"]').get_attribute("content") == "0.11.3"
    resources = page.evaluate("""() => performance.getEntriesByType('resource').map(entry => entry.name)""")
    for module in ("state.js", "ui.js", "api.js", "editor.js", "timeline.js"):
        assert any(f"/static/modules/{module}" in resource for resource in resources)
    assert page.locator("#jobProgress").count() == 1
    page.locator('[data-tab="clipTab"]').focus()
    page.keyboard.press("ArrowRight")
    assert page.locator('[data-tab="captionTab"]').get_attribute("aria-selected") == "true"
    page.locator('[data-tab="captionTab"]').press("End")
    assert page.locator('[data-tab="exportTab"]').get_attribute("aria-selected") == "true"


def test_browser_can_reach_real_health_endpoint(browser_page: Page) -> None:
    """Keep one browser check on the actual server instead of mocked API routes."""
    response = browser_page.request.get("http://127.0.0.1:18760/api/health")
    assert response.ok
    assert response.json()["status"] == "ok"
