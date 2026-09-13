"""Fast, network-free API and static-asset regression tests."""

from __future__ import annotations

import math

import pytest
from fastapi.testclient import TestClient

import web.app as studio


@pytest.fixture()
def client() -> TestClient:
    with studio._lock:
        studio._jobs.clear()
        studio._job_credentials.clear()
        studio._cancel_events.clear()
    with TestClient(studio.app) as test_client:
        yield test_client
    with studio._lock:
        studio._jobs.clear()
        studio._job_credentials.clear()
        studio._cancel_events.clear()


def _job(job_id: str = "test-job") -> dict:
    return {
        "id": job_id,
        "name": "Smoke project",
        "request": {"url": "local.mp4"},
        "logs": [
            {"t": 1.0, "stage": "queued", "message": "Queued"},
            {"t": 2.0, "stage": "error", "message": "provider key mu_secretSECRET1234"},
            {"t": math.inf, "stage": "error", "message": "token sk-abcdefgh123456"},
        ],
    }


def test_health_and_static_assets(client: TestClient) -> None:
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"

    page = client.get("/")
    assert page.status_code == 200
    assert 'href="/static/styles.css"' in page.text
    assert 'src="/static/app.js"' in page.text
    assert "Logs" in page.text
    assert client.get("/static/styles.css").status_code == 200
    assert client.get("/static/app.js").status_code == 200
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
