"""Triad unit tests for yt-dlp downloader anti-throttling and 403 Forbidden resilience."""
import os
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

from shorts_generator.local.downloader import (
    download_youtube_local,
    download_youtube_slice,
)


def test_downloader_includes_android_extractor_args(tmp_path: Any) -> None:
    """Positive: Verify standard download initializes with Android and Web player clients."""
    mock_ydl = MagicMock()
    mock_ydl.extract_info.return_value = {"id": "test_id"}
    mock_ydl.prepare_filename.return_value = str(tmp_path / "source_test_id.mp4")

    dummy_file = tmp_path / "source_test_id.mp4"
    dummy_file.write_text("content", encoding="utf-8")

    captured_opts: Dict[str, Any] = {}

    def mock_init(opts: Dict[str, Any]) -> MagicMock:
        nonlocal captured_opts
        captured_opts = opts
        return mock_ydl

    with patch("yt_dlp.YoutubeDL", side_effect=mock_init):
        with patch("shorts_generator.local.downloader._existing_download", return_value=None):
            path = download_youtube_local(
                "https://www.youtube.com/watch?v=4jwUXV4QaTw",
                out_dir=str(tmp_path)
            )
            assert os.path.exists(path)
            assert captured_opts["extractor_args"]["youtube"]["player_client"] == ["android", "web"]
            assert captured_opts["socket_timeout"] == 30


def test_downloader_uses_cookiefile_when_present(tmp_path: Any) -> None:
    """Positive: Verify cookiefile is forwarded to yt-dlp when the configured path exists."""
    cookie_file = tmp_path / "cookies.txt"
    cookie_file.write_text("# Netscape HTTP Cookie File", encoding="utf-8")

    mock_ydl = MagicMock()
    mock_ydl.extract_info.return_value = {"id": "cookie_test"}
    mock_ydl.prepare_filename.return_value = str(tmp_path / "source_cookie_test.mp4")

    dummy_file = tmp_path / "source_cookie_test.mp4"
    dummy_file.write_text("content", encoding="utf-8")

    captured_opts: Dict[str, Any] = {}

    def mock_init(opts: Dict[str, Any]) -> MagicMock:
        nonlocal captured_opts
        captured_opts = opts
        return mock_ydl

    with patch("yt_dlp.YoutubeDL", side_effect=mock_init):
        with patch("shorts_generator.local.downloader.YTDLP_COOKIES_PATH", str(cookie_file)):
            with patch("shorts_generator.local.downloader._existing_download", return_value=None):
                download_youtube_local(
                    "https://www.youtube.com/watch?v=4jwUXV4QaTw",
                    out_dir=str(tmp_path)
                )
                assert captured_opts.get("cookiefile") == str(cookie_file)


def test_downloader_ignores_nonexistent_cookiefile(tmp_path: Any) -> None:
    """Edge Case: Verify non-existent cookie file path is ignored without error."""
    mock_ydl = MagicMock()
    mock_ydl.extract_info.return_value = {"id": "nocookie"}
    mock_ydl.prepare_filename.return_value = str(tmp_path / "source_nocookie.mp4")

    dummy_file = tmp_path / "source_nocookie.mp4"
    dummy_file.write_text("content", encoding="utf-8")

    captured_opts: Dict[str, Any] = {}

    def mock_init(opts: Dict[str, Any]) -> MagicMock:
        nonlocal captured_opts
        captured_opts = opts
        return mock_ydl

    with patch("yt_dlp.YoutubeDL", side_effect=mock_init):
        with patch("shorts_generator.local.downloader.YTDLP_COOKIES_PATH", "/missing/path/cookies.txt"):
            with patch("shorts_generator.local.downloader._existing_download", return_value=None):
                download_youtube_local(
                    "https://www.youtube.com/watch?v=4jwUXV4QaTw",
                    out_dir=str(tmp_path)
                )
                assert "cookiefile" not in captured_opts


def test_downloader_retries_on_403_forbidden_with_ios_fallback(tmp_path: Any) -> None:
    """Negative / Recovery: Verify 403 Forbidden triggers fallback retry with iOS client."""
    call_count = 0
    captured_client_list = []

    out_file = tmp_path / "source_403_recovery.mp4"
    out_file.write_text("recovered", encoding="utf-8")

    class MockYDLContext:
        def __init__(self, opts: Dict[str, Any]) -> None:
            nonlocal captured_client_list
            captured_client_list.append(opts.get("extractor_args", {}).get("youtube", {}).get("player_client"))

        def __enter__(self) -> "MockYDLContext":
            return self

        def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
            pass

        def extract_info(self, url: str, download: bool = True) -> Dict[str, Any]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("ERROR: unable to download video data: HTTP Error 403: Forbidden")
            return {"id": "403_recovery"}

        def prepare_filename(self, info: Dict[str, Any]) -> str:
            return str(out_file)

    with patch("yt_dlp.YoutubeDL", side_effect=MockYDLContext):
        with patch("shorts_generator.local.downloader._existing_download", return_value=None):
            result = download_youtube_local(
                "https://www.youtube.com/watch?v=4jwUXV4QaTw",
                out_dir=str(tmp_path)
            )
            assert result == str(out_file)
            assert call_count == 2
            assert captured_client_list[0] == ["android", "web"]
            assert captured_client_list[1] == ["ios", "mweb"]


def test_downloader_slice_includes_anti_throttling(tmp_path: Any) -> None:
    """Positive: Verify download_youtube_slice sets up Android client and socket timeout."""
    slice_out = str(tmp_path / "slice.mp4")
    captured_opts: Dict[str, Any] = {}

    class MockSliceYDL:
        def __init__(self, opts: Dict[str, Any]) -> None:
            nonlocal captured_opts
            captured_opts = opts

        def __enter__(self) -> "MockSliceYDL":
            return self

        def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
            pass

        def download(self, urls: Any) -> None:
            pass

    with patch("yt_dlp.YoutubeDL", side_effect=MockSliceYDL):
        res = download_youtube_slice(
            "https://www.youtube.com/watch?v=4jwUXV4QaTw",
            start_seconds=10.0,
            end_seconds=20.0,
            out_path=slice_out
        )
        assert res == slice_out
        assert captured_opts["extractor_args"]["youtube"]["player_client"] == ["android", "web"]
        assert captured_opts["socket_timeout"] == 30
