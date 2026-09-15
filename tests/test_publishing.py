"""Publishing adapter contracts are deterministic and credential-free."""

from __future__ import annotations

from pathlib import Path

from web import publishing
from web.publishing import PLATFORMS, build_publish_plan


def test_platform_plans_include_official_handoff_links_and_limits() -> None:
    item = {
        "title": "A" * 200,
        "description": "B" * 6000,
        "hashtags": "#Shorts",
        "thumbnail_text": "Hook",
        "start_time": 1.0,
        "end_time": 8.0,
        "clip_url": "/api/jobs/j/clip/0",
    }
    for key, spec in PLATFORMS.items():
        plan = build_publish_plan(key, [item])
        assert plan["upload_url"].startswith("https://")
        assert plan["requires_manual_upload"] is True
        assert plan["token_storage"] == "disabled"
        assert len(plan["items"][0]["title"]) <= spec.title_limit
        assert len(plan["items"][0]["description"]) <= spec.description_limit


def test_youtube_oauth_is_pkce_and_process_memory_only(monkeypatch) -> None:
    publishing._oauth_states.clear()
    publishing._youtube_tokens.clear()
    monkeypatch.setenv("YOUTUBE_CLIENT_ID", "client-id")
    monkeypatch.setenv("YOUTUBE_CLIENT_SECRET", "client-secret")

    started = publishing.start_youtube_oauth()
    assert "code_challenge=" in started["authorization_url"]
    assert started["state"] in publishing._oauth_states

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"access_token": "access", "refresh_token": "refresh", "expires_in": 3600}

    monkeypatch.setattr(publishing.requests, "post", lambda *args, **kwargs: Response())
    status = publishing.complete_youtube_oauth("code", started["state"])

    assert status["authorized"] is True
    assert status["token_storage"] == "process_memory_only"


def test_resumable_upload_honors_idempotency_key(monkeypatch, tmp_path: Path) -> None:
    publishing._upload_results.clear()
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"video-bytes")
    monkeypatch.setattr(publishing, "_youtube_access_token", lambda: "access")
    calls = []

    class Response:
        def __init__(self, status_code: int, payload: dict | None = None, location: str = "") -> None:
            self.status_code = status_code
            self.headers = {"Location": location} if location else {}
            self._payload = payload or {}

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return self._payload

    def fake_request(method: str, url: str, **kwargs):
        calls.append(method)
        if method == "POST":
            return Response(200, location="https://upload.example/session")
        return Response(200, {"id": "video-1"})

    monkeypatch.setattr(publishing, "_upload_request_with_retry", fake_request)
    first = publishing.upload_youtube_video(media, title="Title", description="Description", idempotency_key="same")
    second = publishing.upload_youtube_video(media, title="Title", description="Description", idempotency_key="same")

    assert first["video_id"] == second["video_id"] == "video-1"
    assert calls == ["POST", "PUT"]


def test_youtube_refresh_and_resumable_308_resume(monkeypatch, tmp_path: Path) -> None:
    publishing._upload_results.clear()
    publishing._youtube_tokens.clear()
    monkeypatch.setenv("YOUTUBE_CLIENT_ID", "client-id")
    monkeypatch.setenv("YOUTUBE_CLIENT_SECRET", "client-secret")
    publishing._youtube_tokens.update({"refresh_token": "refresh", "expires_at": 0})

    class TokenResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"access_token": "refreshed", "expires_in": 3600}

    monkeypatch.setattr(publishing.requests, "post", lambda *args, **kwargs: TokenResponse())
    assert publishing._youtube_access_token() == "refreshed"

    media = tmp_path / "clip.mp4"
    media.write_bytes(b"0123456789")
    calls = []

    class UploadResponse:
        def __init__(self, status_code: int, payload: dict | None = None, headers: dict | None = None) -> None:
            self.status_code = status_code
            self._payload = payload or {}
            self.headers = headers or {}

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return self._payload

    def resumable(method: str, url: str, **kwargs):
        calls.append((method, kwargs.get("headers", {})))
        if method == "POST":
            return UploadResponse(200, headers={"Location": "https://upload.example/session"})
        if len([item for item in calls if item[0] == "PUT"]) == 1:
            return UploadResponse(308, headers={"Range": "bytes=0-4"})
        return UploadResponse(200, {"id": "video-2"})

    monkeypatch.setattr(publishing, "_upload_request_with_retry", resumable)
    result = publishing.upload_youtube_video(media, title="Title", description="Description")

    assert result["video_id"] == "video-2"
    assert [item[0] for item in calls] == ["POST", "PUT", "PUT"]
