"""Local LLM backend - OpenAI, Gemini, or Ollama, selected by LLM_PROVIDER."""

import json
import re
import time
from functools import lru_cache
from importlib import import_module

import requests

from ..config import (
    GEMINI_MODEL,
    OPENAI_MODEL,
    current_llm_provider,
    current_llm_model,
    current_llm_temperature,
    require_gemini_key,
    require_openai_key,
    record_llm_usage,
    LOCAL_LLM_MAX_OUTPUT_TOKENS,
    LOCAL_LLM_MAX_RETRIES,
    LOCAL_LLM_RETRY_DELAY_SECONDS,
    LOCAL_LLM_TIMEOUT_SECONDS,
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
    cancellation_requested,
)

# Free-tier Gemini often returns 429s; retry a few times with backoff.
_MAX_LLM_RETRIES = max(1, LOCAL_LLM_MAX_RETRIES)
_DEFAULT_RETRY_DELAY_SECONDS = LOCAL_LLM_RETRY_DELAY_SECONDS


def _retry_delay_seconds(error: Exception, attempt: int) -> float:
    """Parse Gemini's 'Please retry in Xs' hint, else exponential backoff."""
    message = str(error)
    match = re.search(r"retry in\s+([0-9]+(?:\.[0-9]+)?)\s*s", message, re.I)
    if match:
        return float(match.group(1)) + 1.0
    return min(_DEFAULT_RETRY_DELAY_SECONDS * (2 ** (attempt - 1)), 120.0)


def _is_rate_limit_error(error: Exception) -> bool:
    text = str(error).upper()
    return (
        any(code in text for code in ("429", "500", "502", "503", "504"))
        or "RESOURCE_EXHAUSTED" in text
        or ("RATE" in text and "LIMIT" in text)
        or "TIMEOUT" in text
        or "TEMPORARY" in text
    )


def _sleep_with_cancel(delay: float) -> None:
    deadline = time.monotonic() + max(0.0, float(delay))
    while time.monotonic() < deadline:
        if cancellation_requested():
            raise RuntimeError("Job cancelled")
        time.sleep(min(0.25, max(0.01, deadline - time.monotonic())))


@lru_cache(maxsize=4)
def _openai_client(api_key: str):
    openai = import_module("openai")
    return openai.OpenAI(api_key=api_key)


@lru_cache(maxsize=4)
def _gemini_client(api_key: str):
    genai = import_module("google.genai")
    return genai.Client(api_key=api_key)


def _collect_openai_stream(response: object) -> str:
    pieces: list[str] = []
    try:
        chunks = iter(response)
    except TypeError:
        return ""
    for chunk in chunks:
        if cancellation_requested():
            raise RuntimeError("Job cancelled")
        choices = getattr(chunk, "choices", None) or []
        if not choices:
            continue
        delta = getattr(choices[0], "delta", None)
        content = getattr(delta, "content", None)
        if content:
            pieces.append(str(content))
    return "".join(pieces)


def call_openai_llm(
    prompt: str,
    model: str | None = None,
    temperature: float | None = None,
    *,
    stream: bool = False,
) -> str:
    """OpenAI Chat Completions backend used by --mode local."""
    try:
        import_module("openai")
    except ImportError as e:
        raise RuntimeError(
            "openai is required for --mode local. Install it with:\n    pip install -r requirements-local.txt"
        ) from e

    api_key = require_openai_key()
    client = _openai_client(api_key)
    last_error: Exception | None = None
    for attempt in range(1, _MAX_LLM_RETRIES + 1):
        try:
            response = client.chat.completions.create(
                model=model or current_llm_model("openai") or OPENAI_MODEL,
                temperature=current_llm_temperature(0.7) if temperature is None else temperature,
                max_tokens=LOCAL_LLM_MAX_OUTPUT_TOKENS,
                response_format={"type": "json_object"},
                messages=[{"role": "user", "content": prompt}],
                stream=bool(stream),
            )
            selected_model = model or current_llm_model("openai") or OPENAI_MODEL
            record_llm_usage("openai", selected_model, getattr(response, "usage", None))
            if stream:
                text = _collect_openai_stream(response)
                if not text.strip():
                    raise RuntimeError("OpenAI returned an empty response")
                return text
            return response.choices[0].message.content or ""
        except Exception as e:
            last_error = e
            if not _is_rate_limit_error(e) or attempt >= max(1, _MAX_LLM_RETRIES):
                raise
            delay = _retry_delay_seconds(e, attempt)
            print(
                f"[llm/openai] rate limited (attempt {attempt}/{_MAX_LLM_RETRIES}); retrying in {delay:.0f}s",
                flush=True,
            )
            _sleep_with_cancel(delay)
    raise RuntimeError(f"OpenAI call failed after retries: {last_error}")


def call_gemini_llm(
    prompt: str,
    model: str | None = None,
    temperature: float | None = None,
    *,
    stream: bool = False,
) -> str:
    """Gemini backend used by --mode local when LLM_PROVIDER=gemini."""
    try:
        import_module("google.genai")
    except ImportError as e:
        raise RuntimeError(
            "google-genai is required for LLM_PROVIDER=gemini. Install it with:\n"
            "    pip install -r requirements-local.txt"
        ) from e

    api_key = require_gemini_key()
    client = _gemini_client(api_key)
    last_error: Exception | None = None

    for attempt in range(1, _MAX_LLM_RETRIES + 1):
        try:
            request = {
                "model": model or current_llm_model("gemini") or GEMINI_MODEL,
                "contents": prompt,
                "config": {
                    "temperature": current_llm_temperature(0.2) if temperature is None else temperature,
                    "response_mime_type": "application/json",
                    "max_output_tokens": LOCAL_LLM_MAX_OUTPUT_TOKENS,
                },
            }
            response = (
                client.models.generate_content_stream(**request)
                if stream
                else client.models.generate_content(**request)
            )

            selected_model = model or current_llm_model("gemini") or GEMINI_MODEL
            usage = getattr(response, "usage_metadata", None) if not stream else None
            record_llm_usage("gemini", selected_model, usage)
            if stream:
                chunks: list[str] = []
                for item in response:
                    if cancellation_requested():
                        raise RuntimeError("Job cancelled")
                    text_part = getattr(item, "text", None)
                    if text_part:
                        chunks.append(str(text_part))
                text = "".join(chunks)
            else:
                text = response.text or ""
            if not text.strip():
                # Surface *why* it came back empty instead of a generic JSON error
                # downstream. Usually this is MAX_TOKENS truncation or a safety
                # filter, both visible on the first candidate's finish_reason.
                reason = "unknown"
                try:
                    candidates = getattr(response, "candidates", None) or []
                    if candidates:
                        reason = getattr(candidates[0], "finish_reason", "unknown")
                except Exception:
                    pass
                raise RuntimeError(f"Gemini returned an empty response (finish_reason={reason})")
            return text
        except Exception as e:
            last_error = e
            if not _is_rate_limit_error(e) or attempt >= max(1, _MAX_LLM_RETRIES):
                raise
            delay = _retry_delay_seconds(e, attempt)
            print(
                f"[llm/gemini] rate limited (attempt {attempt}/{_MAX_LLM_RETRIES}); retrying in {delay:.0f}s",
                flush=True,
            )
            _sleep_with_cancel(delay)

    raise RuntimeError(f"Gemini call failed after retries: {last_error}")


def call_ollama_llm(prompt: str, model: str | None = None, *, stream: bool = False) -> str:
    """Call an Ollama-compatible local endpoint without requiring a cloud key."""
    selected_model = model or current_llm_model("ollama") or OLLAMA_MODEL
    if cancellation_requested():
        raise RuntimeError("Job cancelled")
    data: dict[str, object] | None = None
    last_error: Exception | None = None
    for attempt in range(1, _MAX_LLM_RETRIES + 1):
        try:
            request_kwargs = {
                "json": {"model": selected_model, "prompt": prompt, "stream": bool(stream), "format": "json"},
            }
            if stream:
                request_kwargs["stream"] = True
            response = requests.post(
                f"{OLLAMA_BASE_URL}/api/generate",
                timeout=LOCAL_LLM_TIMEOUT_SECONDS,
                **request_kwargs,
            )
            response.raise_for_status()
            if stream:
                pieces: list[str] = []
                for line in response.iter_lines(decode_unicode=True):
                    if cancellation_requested():
                        raise RuntimeError("Job cancelled")
                    if not line:
                        continue
                    try:
                        chunk = json.loads(line)
                    except (TypeError, ValueError) as exc:
                        raise RuntimeError("Ollama returned invalid streaming JSON") from exc
                    if isinstance(chunk, dict):
                        piece = chunk.get("response")
                        if piece:
                            pieces.append(str(piece))
                        message = chunk.get("message")
                        if isinstance(message, dict) and message.get("content"):
                            pieces.append(str(message["content"]))
                        if chunk.get("done"):
                            break
                data = {"response": "".join(pieces)}
            else:
                candidate = response.json()
                if not isinstance(candidate, dict):
                    raise RuntimeError("Ollama returned an invalid response")
                data = candidate
            break
        except RuntimeError:
            raise
        except requests.RequestException as exc:
            last_error = exc
            retryable = isinstance(exc, (requests.Timeout, requests.ConnectionError)) or _is_rate_limit_error(exc)
            if not retryable or attempt >= _MAX_LLM_RETRIES:
                raise RuntimeError(f"Ollama request failed: {exc}") from exc
            _sleep_with_cancel(_retry_delay_seconds(exc, attempt))
        except (TypeError, ValueError) as exc:
            raise RuntimeError("Ollama returned invalid JSON") from exc
    if data is None:
        raise RuntimeError(f"Ollama request failed after retries: {last_error}")
    record_llm_usage("ollama", selected_model, {key: data.get(key) for key in ("prompt_eval_count", "eval_count") if key in data})
    text = data.get("response")
    if not text and isinstance(data.get("message"), dict):
        text = data["message"].get("content")
    if not str(text or "").strip():
        raise RuntimeError("Ollama returned an empty response")
    return str(text)


def call_local_llm(prompt: str) -> str:
    """Dispatch to the configured local LLM provider."""
    provider = current_llm_provider()
    if provider == "openai":
        return call_openai_llm(prompt)
    if provider == "gemini":
        return call_gemini_llm(prompt)
    if provider == "ollama":
        return call_ollama_llm(prompt)
    raise RuntimeError(f"Unknown LLM_PROVIDER={provider!r}. Use 'openai', 'gemini', or 'ollama'.")
