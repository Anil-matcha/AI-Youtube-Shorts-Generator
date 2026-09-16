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


def test_youtube_upload_includes_category_thumbnail_and_captions(monkeypatch, tmp_path: Path) -> None:
    publishing._upload_results.clear()
    media = tmp_path / "clip.mp4"
    thumbnail = tmp_path / "thumb.png"
    captions = tmp_path / "captions.srt"
    media.write_bytes(b"video-bytes")
    thumbnail.write_bytes(b"png-bytes")
    captions.write_text("1\n00:00:00,000 --> 00:00:01,000\nHello\n", encoding="utf-8")
    monkeypatch.setattr(publishing, "_youtube_access_token", lambda: "access")
    calls = []

    class Response:
        def __init__(self, method: str, url: str) -> None:
            self.status_code = 200
            self.headers = (
                {"Location": "https://upload.example/session"}
                if method == "POST" and ("/videos" in url or "captions" in url)
                else {}
            )
            self._payload = {"id": "caption-1"} if method == "PUT" and len(calls) == 5 else {"id": "video-1"}

        def json(self) -> dict:
            return self._payload

    def fake_request(method: str, url: str, **kwargs):
        calls.append((method, url, kwargs))
        return Response(method, url)

    monkeypatch.setattr(publishing, "_upload_request_with_retry", fake_request)
    result = publishing.upload_youtube_video(
        media,
        title="Title",
        description="Description",
        category_id="27",
        thumbnail_path=thumbnail,
        captions_path=captions,
        caption_language="fr",
        caption_name="French captions",
        captions_draft=True,
    )

    assert result["video_id"] == "video-1"
    assert result["category_id"] == "27"
    assert result["thumbnail"]["status"] == "uploaded"
    assert result["captions"]["caption_id"] == "caption-1"
    assert result["captions"]["draft"] is True
    assert [item[0] for item in calls] == ["POST", "PUT", "POST", "POST", "PUT"]
    assert calls[0][2]["json"]["snippet"]["categoryId"] == "27"
    assert calls[2][2]["headers"]["Content-Type"] == "image/png"
    assert calls[3][2]["json"]["snippet"]["language"] == "fr"
