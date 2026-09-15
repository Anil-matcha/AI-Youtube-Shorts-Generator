"""v0.10.1 configuration, parser, and security coverage."""

from __future__ import annotations

from shorts_generator.config import PipelineConfig, validate_config
from shorts_generator.highlights import _parse_json_loose, _sanitize_highlights
from shorts_generator.local import llm
from web.security import sign_webhook_payload


def test_highlight_parser_accepts_array_and_duration_bounds() -> None:
    parsed = _parse_json_loose('[{"title":"A","start_time":0,"end_time":8,"score":90}]')
    assert parsed["highlights"][0]["title"] == "A"
    assert _sanitize_highlights(
        [{"start_time": 0, "end_time": 1}, {"start_time": 0, "end_time": 600}], duration=600
    ) == [{
        "title": "Untitled Highlight",
        "start_time": 0.0,
        "end_time": 180.0,
        "score": 0,
        "hook_sentence": "",
        "virality_reason": "",
    }]


def test_pipeline_config_is_typed_and_webhook_signatures_are_stable() -> None:
    config = PipelineConfig.from_environment().with_overrides(max_clips=99, crf=100)
    assert config.max_clips == 12
    assert config.crf == 51
    assert validate_config() == []
    assert sign_webhook_payload("payload", "secret") == sign_webhook_payload(b"payload", "secret")


def test_ollama_backend_supports_structured_streaming(monkeypatch) -> None:
    class Response:
        def raise_for_status(self) -> None:
            return None

        def iter_lines(self, decode_unicode: bool = False):
            assert decode_unicode is True
            return [
                '{"response":"{\\"highlights\\":[", "done": false}',
                '{"response":" ]}", "done": true}',
            ]

    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs))
        return Response()

    monkeypatch.setattr(llm.requests, "post", post)
    assert llm.call_ollama_llm("return JSON", model="llama3.2", stream=True) == '{"highlights":[ ]}'
    assert calls[0][1]["json"]["stream"] is True
