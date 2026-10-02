"""Browser checks for model download status, privacy, and explicit retries."""

import os
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright

pytestmark = pytest.mark.skipif(os.getenv("RUN_BROWSER_E2E") != "1", reason="set RUN_BROWSER_E2E=1 to run browser coverage")


def test_model_status_and_retry_are_accessible_and_explicit():
    script = Path(__file__).resolve().parents[2] / "web/static/modules/dashboard.js"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page()
            page.set_content('<div id="localModelList"></div><p id="styleProfileStatus"></p>')
            page.evaluate("""() => {
              window.modelCalls = [];
              window.modelFixture = {models: [{name: 'base', label: 'Base', size_gb: .15,
                state: {status: 'downloading', phase: 'validating', progress: 15,
                  message: 'Checking offline cache completeness', elapsed_seconds: 12.5, download_workers: 4}}]};
              window.ShortsStudioAPI = {json: async (url, options = {}) => {
                window.modelCalls.push([url, options.method || 'GET']);
                return window.modelFixture;
              }};
            }""")
            page.add_script_tag(content=script.read_text(encoding="utf-8"))
            page.evaluate("window.ShortsStudioDashboard.refreshModels()")
            progress = page.get_by_role("progressbar", name="Base model download in progress")
            assert progress.count() == 1
            assert progress.get_attribute("value") is None
            assert page.get_by_role("button", name="Downloading…").is_disabled()
            assert "12.5s elapsed" in page.locator("[data-model-detail]").inner_text()
            assert "4 file workers" in page.locator("[data-model-detail]").inner_text()
            assert page.locator(".model-card").get_attribute("aria-busy") == "true"

            page.evaluate("""() => {
              window.modelFixture.models[0].state = {status: 'error', phase: 'error', retryable: true,
                error: '<img src=x onerror="window.unsafe=true">', elapsed_seconds: 14};
            }""")
            page.evaluate("window.ShortsStudioDashboard.refreshModels()")
            assert page.get_by_role("alert").inner_text().startswith("<img")
            assert page.locator("img").count() == 0
            assert page.evaluate("window.modelCalls.every(call => call[1] === 'GET')")
            page.get_by_role("button", name="Retry download").click()
            page.wait_for_function("window.modelCalls.some(call => call[1] === 'POST')")
            assert page.evaluate("window.modelCalls.filter(call => call[1] === 'POST').length") == 1

            page.evaluate("""() => {
              window.modelFixture.models[0].installed = true;
              window.modelFixture.models[0].state = {status: 'ready', phase: 'ready', cached_bytes: 1048576,
                cache_hit: true, elapsed_seconds: 0, message: 'Already installed'};
            }""")
            page.evaluate("window.ShortsStudioDashboard.refreshModels()")
            assert page.get_by_role("progressbar").count() == 0
            detail = page.locator("[data-model-detail]").inner_text()
            assert "1 MiB cached" in detail and "Reused local cache" in detail
            assert page.get_by_role("button", name="Remove").is_enabled()
        finally:
            browser.close()
