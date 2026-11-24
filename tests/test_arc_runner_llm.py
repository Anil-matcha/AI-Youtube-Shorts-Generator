"""Triad unit tests for Intel Arc Models Runner local LLM integration."""
import io
import json
import urllib.error
import urllib.request
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

from shorts_generator.config import ARC_RUNNER_BASE_URL, ARC_RUNNER_MODEL
from shorts_generator.local.llm import (
    call_arc_runner_llm,
    call_local_llm,
)
from shorts_generator.pipeline import generate_shorts


class MockHTTPResponse:
    """Mock context manager mimicking urllib.request.urlopen response."""

    def __init__(self, data: Dict[str, Any], status: int = 200) -> None:
        """Initialize mock response with payload and status code."""
        self._data = json.dumps(data).encode("utf-8")
        self.status = status

    def read(self) -> bytes:
        """Return raw encoded byte response."""
        return self._data

    def __enter__(self) -> "MockHTTPResponse":
        """Enter response context."""
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Exit response context."""
        pass


def test_call_arc_runner_llm_success_parses_content() -> None:
    """Positive: Verify valid OpenAI-compatible JSON response is parsed cleanly."""
    mock_payload = {
        "id": "chatcmpl-arc-101",
        "object": "chat.completion",
        "created": 1732439000,
        "model": ARC_RUNNER_MODEL,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": '[{"start": 10.0, "end": 45.0, "score": 95, "title": "Arc Punch"}]',
                },
                "finish_reason": "stop",
            }
        ],
    }

    with patch("urllib.request.urlopen", return_value=MockHTTPResponse(mock_payload)):
        result = call_arc_runner_llm("Analyze this transcript")
        assert result == '[{"start": 10.0, "end": 45.0, "score": 95, "title": "Arc Punch"}]'


def test_call_local_llm_dispatches_to_arc_runner() -> None:
    """Positive: Verify call_local_llm routes to call_arc_runner_llm when provider is set."""
    with patch("shorts_generator.local.llm.LLM_PROVIDER", "arc_runner"):
        with patch("shorts_generator.local.llm.call_arc_runner_llm", return_value="mock_arc_output") as mock_fn:
            output = call_local_llm("test prompt")
            assert output == "mock_arc_output"
            mock_fn.assert_called_once_with("test prompt")

    with patch("shorts_generator.local.llm.LLM_PROVIDER", "intel_arc"):
        with patch("shorts_generator.local.llm.call_arc_runner_llm", return_value="mock_arc_output_2") as mock_fn:
            output = call_local_llm("test prompt 2")
            assert output == "mock_arc_output_2"
            mock_fn.assert_called_once_with("test prompt 2")


def test_pipeline_local_allows_arc_runner_without_api_keys() -> None:
    """Positive: Verify generate_shorts runs locally with arc_runner without requiring OpenAI or Gemini keys."""
    with patch("shorts_generator.pipeline.LLM_PROVIDER", "arc_runner"):
        with patch("shorts_generator.pipeline._run_local", return_value={"status": "ok"}) as mock_run:
            res = generate_shorts("https://www.youtube.com/watch?v=dQw4w9WgXcQ", mode="local")
            assert res == {"status": "ok"}
            mock_run.assert_called_once()


def test_call_arc_runner_llm_connection_error_raises_clear_guidance() -> None:
    """Negative: Verify connection refusal raises a descriptive exception mentioning arc_runner server."""
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("Connection refused")):
        with pytest.raises(RuntimeError) as exc_info:
            call_arc_runner_llm("Analyze transcript")
        err_msg = str(exc_info.value)
        assert "Failed to connect to Intel Arc Models Runner" in err_msg
        assert "python -m arc_runner.server --port 11434" in err_msg


def test_call_arc_runner_llm_empty_choices_returns_empty_string() -> None:
    """Edge Case: Verify response with empty choices array returns empty string safely."""
    mock_payload = {
        "id": "chatcmpl-empty",
        "choices": [],
    }
    with patch("urllib.request.urlopen", return_value=MockHTTPResponse(mock_payload)):
        result = call_arc_runner_llm("test")
        assert result == ""


def test_call_arc_runner_llm_malformed_json_raises_runtime_error() -> None:
    """Edge Case: Verify non-JSON response payload raises RuntimeError with diagnostics."""
    raw_mock = MagicMock()
    raw_mock.read.return_value = b"<html><head><title>502 Bad Gateway</title></head></html>"
    raw_mock.__enter__.return_value = raw_mock
    raw_mock.__exit__.return_value = None

    with patch("urllib.request.urlopen", return_value=raw_mock):
        with pytest.raises(RuntimeError) as exc_info:
            call_arc_runner_llm("test")
        assert "Invalid response payload" in str(exc_info.value)
