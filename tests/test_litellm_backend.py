"""Unit tests for the LiteLLM local backend (LLM_PROVIDER=litellm).

Runs without the real `litellm` package installed: a lightweight stub is
injected into sys.modules so the tests exercise the dispatch + call shaping
in shorts_generator/local/llm.py in isolation.

    python -m unittest tests.test_litellm_backend
"""
import sys
import types
import unittest
from unittest import mock

# Inject a stub `litellm` before importing the backend so `import litellm`
# inside call_litellm_llm resolves to this stub (hermetic — never the real dep).
_litellm_stub = types.ModuleType("litellm")
_litellm_stub.completion = mock.MagicMock(name="litellm.completion")  # type: ignore[attr-defined]
sys.modules["litellm"] = _litellm_stub

from shorts_generator.local import llm  # noqa: E402


def _fake_response(text: str):
    """Mimic the ModelResponse.choices[0].message.content shape."""
    message = types.SimpleNamespace(content=text)
    choice = types.SimpleNamespace(message=message)
    return types.SimpleNamespace(choices=[choice])


class LiteLLMBackendTest(unittest.TestCase):
    def setUp(self):
        self.completion = _litellm_stub.completion
        self.completion.reset_mock()
        self.completion.return_value = _fake_response('{"ok": true}')

    def test_call_litellm_llm_shapes_the_request(self):
        with mock.patch.object(llm, "LITELLM_MODEL", "anthropic/claude-sonnet-4-5"), \
                mock.patch.object(llm, "LITELLM_API_KEY", ""), \
                mock.patch.object(llm, "LITELLM_BASE_URL", ""):
            out = llm.call_litellm_llm("hello")

        self.assertEqual(out, '{"ok": true}')
        self.completion.assert_called_once()
        kwargs = self.completion.call_args.kwargs
        self.assertEqual(kwargs["model"], "anthropic/claude-sonnet-4-5")
        self.assertEqual(kwargs["messages"], [{"role": "user", "content": "hello"}])
        # drop_params keeps one call portable across providers.
        self.assertTrue(kwargs["drop_params"])
        # Blank creds must be OMITTED so LiteLLM falls back to the upstream env var.
        self.assertNotIn("api_key", kwargs)
        self.assertNotIn("api_base", kwargs)

    def test_credentials_forwarded_when_set(self):
        with mock.patch.object(llm, "LITELLM_MODEL", "gpt-4o-mini"), \
                mock.patch.object(llm, "LITELLM_API_KEY", "sk-proxy"), \
                mock.patch.object(llm, "LITELLM_BASE_URL", "http://localhost:4000/v1"):
            llm.call_litellm_llm("hi")

        kwargs = self.completion.call_args.kwargs
        self.assertEqual(kwargs["api_key"], "sk-proxy")
        self.assertEqual(kwargs["api_base"], "http://localhost:4000/v1")

    def test_dispatch_routes_litellm_provider(self):
        with mock.patch.object(llm, "LLM_PROVIDER", "litellm"), \
                mock.patch.object(llm, "call_litellm_llm", return_value="ROUTED") as routed:
            self.assertEqual(llm.call_local_llm("p"), "ROUTED")
            routed.assert_called_once_with("p")

    def test_dispatch_rejects_unknown_provider(self):
        with mock.patch.object(llm, "LLM_PROVIDER", "bogus"):
            with self.assertRaises(RuntimeError) as ctx:
                llm.call_local_llm("p")
        self.assertIn("litellm", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
