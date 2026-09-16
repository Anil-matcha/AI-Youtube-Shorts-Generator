"""HTTP hardening checks that should stay cheap enough for every CI run."""

from __future__ import annotations

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


def test_healthz_is_non_disclosing_and_security_headers_are_present(client) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert "output" not in response.json()
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-security-policy"].startswith("default-src 'self'")


def test_cookie_authenticated_cross_site_mutation_is_blocked(client, monkeypatch) -> None:
    monkeypatch.setenv("SHORTS_API_TOKEN", "csrf-test-token")
    assert client.post("/api/auth/login", json={"token": "csrf-test-token"}).status_code == 200
    blocked = client.post(
        "/api/setup/dismiss",
        headers={"Origin": "https://evil.example"},
        json={"dismissed": True},
    )
    assert blocked.status_code == 403
    assert blocked.json()["code"] == "csrf_failed"


def test_backup_safe_url_helper_removes_signed_media_links() -> None:
    from web.feature_routes import _safe_backup_value

    value = _safe_backup_value(
        {
            "raw_source_video_url": "https://cdn.example/source?token=secret",
            "clip_url": "https://cdn.example/clip?signature=secret",
            "request_url": "https://www.youtube.com/watch?v=abc&expires=10",
        }
    )
    assert value["raw_source_video_url"] is None
    assert value["clip_url"] is None
    assert "secret" not in value["request_url"]
