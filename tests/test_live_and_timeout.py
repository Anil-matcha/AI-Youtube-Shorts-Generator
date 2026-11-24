"""Triad unit tests for YouTube live stream support, timeout resilience, and CLI extensions."""
import os
import sys
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

from shorts_generator.local.downloader import (
    _extract_youtube_video_id,
    download_youtube_local,
)
from shorts_generator.muapi import MuAPIError, poll
from main import main


def test_downloader_extracts_youtube_live_video_id() -> None:
    """Positive: Verify YouTube /live/ URL variations cleanly extract the 11-char video ID."""
    live_url_1 = "https://www.youtube.com/live/45r3OyaxvFE?si=6JRD0txoiywvRBb4"
    assert _extract_youtube_video_id(live_url_1) == "45r3OyaxvFE"

    live_url_2 = "https://www.youtube.com/live/irNhWMG560k"
    assert _extract_youtube_video_id(live_url_2) == "irNhWMG560k"


def test_downloader_includes_live_from_start(tmp_path: Any) -> None:
    """Positive: Verify live_from_start flag is injected into yt-dlp download options."""
    mock_ydl = MagicMock()
    mock_ydl.extract_info.return_value = {"id": "live_video"}
    mock_ydl.prepare_filename.return_value = str(tmp_path / "source_live_video.mp4")

    dummy_file = tmp_path / "source_live_video.mp4"
    dummy_file.write_text("data", encoding="utf-8")

    captured_opts: Dict[str, Any] = {}

    def mock_init(opts: Dict[str, Any]) -> MagicMock:
        nonlocal captured_opts
        captured_opts = opts
        return mock_ydl

    with patch("yt_dlp.YoutubeDL", side_effect=mock_init):
        with patch("shorts_generator.local.downloader._existing_download", return_value=None):
            path = download_youtube_local(
                "https://www.youtube.com/live/45r3OyaxvFE",
                out_dir=str(tmp_path)
            )
            assert os.path.exists(path)
            assert captured_opts.get("live_from_start") is True


def test_muapi_poll_elapsed_telemetry_and_completion(capsys: Any) -> None:
    """Positive: Verify poll logs elapsed time telemetry and returns finished payload."""
    poll_calls = 0

    def mock_fetch(req_id: str) -> Dict[str, Any]:
        nonlocal poll_calls
        poll_calls += 1
        if poll_calls == 1:
            return {"status": "processing"}
        return {"status": "completed", "output": "ready"}

    with patch("shorts_generator.muapi.fetch_result", side_effect=mock_fetch):
        res = poll("job-123", interval=0.01, timeout=5.0, label="transcription")
        assert res["status"] == "completed"
        captured = capsys.readouterr().out
        assert "[muapi] transcription: processing" in captured
        assert "elapsed:" in captured
        assert "timeout: 5s" in captured


def test_muapi_poll_timeout_raises_actionable_guidance() -> None:
    """Negative: Verify exceeding timeout raises MuAPIError with mode local recommendations."""
    with patch("shorts_generator.muapi.fetch_result", return_value={"status": "processing"}):
        with pytest.raises(MuAPIError) as exc_info:
            poll("job-stall", interval=0.01, timeout=0.05, label="long-video")
        err_msg = str(exc_info.value)
        assert "timed out after 0s" in err_msg
        assert "--mode local" in err_msg
        assert "MUAPI_POLL_TIMEOUT" in err_msg


def test_main_cli_parses_timeout_no_zoom_and_cookies(tmp_path: Any) -> None:
    """Edge Case: Verify CLI properly parses --timeout, --no-zoom, and --cookies flags."""
    test_cookies = str(tmp_path / "test_cookies.txt")
    test_args = [
        "main.py",
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "--timeout", "2400",
        "--no-zoom",
        "--cookies", test_cookies,
    ]

    with patch.object(sys, "argv", test_args):
        with patch("main.generate_shorts", return_value={
            "mode": "api",
            "source_video_url": "test",
            "highlights": [],
            "shorts": [],
        }) as mock_gen:
            exit_code = main()
            assert exit_code == 0
            assert os.environ.get("YTDLP_COOKIES_PATH") == test_cookies
            mock_gen.assert_called_once()
            _, kwargs = mock_gen.call_args
            assert kwargs["timeout"] == 2400.0
            assert kwargs["auto_zoom"] is False
