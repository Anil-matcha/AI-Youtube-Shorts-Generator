"""Local LLM backend - OpenAI or Gemini, selected by LLM_PROVIDER."""
import re
import time

from ..config import (
    GEMINI_MODEL,
    OPENAI_MODEL,
    current_llm_provider,
    require_gemini_key,
    require_openai_key,
)

# Free-tier Gemini often returns 429s; retry a few times with backoff.
_MAX_LLM_RETRIES = 5
_DEFAULT_RETRY_DELAY_SECONDS = 30.0


def _retry_delay_seconds(error: Exception, attempt: int) -> float:
    """Parse Gemini's 'Please retry in Xs' hint, else exponential backoff."""
    message = str(error)
    match = re.search(r"retry in\s+([0-9]+(?:\.[0-9]+)?)\s*s", message, re.I)
    if match:
        return float(match.group(1)) + 1.0
    return min(_DEFAULT_RETRY_DELAY_SECONDS * (2 ** (attempt - 1)), 120.0)


def _is_rate_limit_error(error: Exception) -> bool:
    text = str(error).upper()
    return "429" in text or "RESOURCE_EXHAUSTED" in text or "RATE" in text and "LIMIT" in text


def call_openai_llm(prompt: str) -> str:
    """OpenAI Chat Completions backend used by --mode local."""
    try:
        from openai import OpenAI  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            "openai is required for --mode local. Install it with:\n"
            "    pip install -r requirements-local.txt"
        ) from e

    client = OpenAI(api_key=require_openai_key())
    last_error: Exception | None = None
    for attempt in range(1, _MAX_LLM_RETRIES + 1):
        try:
            response = client.chat.completions.create(
                model=OPENAI_MODEL,
                temperature=0.7,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            last_error = e
            if not _is_rate_limit_error(e) or attempt >= _MAX_LLM_RETRIES:
                raise
            delay = _retry_delay_seconds(e, attempt)
            print(
                f"[llm/openai] rate limited (attempt {attempt}/{_MAX_LLM_RETRIES}); "
                f"retrying in {delay:.0f}s",
                flush=True,
            )
            time.sleep(delay)
    raise RuntimeError(f"OpenAI call failed after retries: {last_error}")


def call_gemini_llm(prompt: str) -> str:
    """Gemini backend used by --mode local when LLM_PROVIDER=gemini."""
    try:
        from google import genai  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            "google-genai is required for LLM_PROVIDER=gemini. Install it with:\n"
            "    pip install -r requirements-local.txt"
        ) from e

    client = genai.Client(api_key=require_gemini_key())
    last_error: Exception | None = None

    for attempt in range(1, _MAX_LLM_RETRIES + 1):
        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
                config={
                    "temperature": 0.2,
                    "response_mime_type": "application/json",
                    "max_output_tokens": 32768,
                },
            )

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
            if not _is_rate_limit_error(e) or attempt >= _MAX_LLM_RETRIES:
                raise
            delay = _retry_delay_seconds(e, attempt)
            print(
                f"[llm/gemini] rate limited (attempt {attempt}/{_MAX_LLM_RETRIES}); "
                f"retrying in {delay:.0f}s",
                flush=True,
            )
            time.sleep(delay)

    raise RuntimeError(f"Gemini call failed after retries: {last_error}")


def call_local_llm(prompt: str) -> str:
    """Dispatch to the configured local LLM provider."""
    provider = current_llm_provider()
    if provider == "openai":
        return call_openai_llm(prompt)
    if provider == "gemini":
        return call_gemini_llm(prompt)
    raise RuntimeError(
        f"Unknown LLM_PROVIDER={provider!r}. Use 'openai' or 'gemini'."
    )
