"""Local LLM backend — OpenAI, Gemini, or OrcaRouter, selected by LLM_PROVIDER."""
from ..config import (
    GEMINI_MODEL,
    LLM_PROVIDER,
    OPENAI_MODEL,
    ORCAROUTER_API_BASE_URL,
    ORCAROUTER_MODEL,
    require_gemini_key,
    require_openai_key,
    require_orcarouter_key,
)


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
    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        temperature=0.7,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content or ""


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
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config={
            "temperature": 0.2,
            "response_mime_type": "application/json",
            "max_output_tokens": 8192,
        },
    )
    return response.text or ""


def call_orcarouter_llm(prompt: str) -> str:
    """OrcaRouter backend used by --mode local when LLM_PROVIDER=orcarouter.

    OrcaRouter is an OpenAI-compatible gateway, so it reuses the OpenAI SDK with
    a custom base URL and model namespace (e.g. ``orcarouter/auto``).
    """
    try:
        from openai import OpenAI  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            "openai is required for LLM_PROVIDER=orcarouter. Install it with:\n"
            "    pip install -r requirements-local.txt"
        ) from e

    client = OpenAI(
        api_key=require_orcarouter_key(),
        base_url=ORCAROUTER_API_BASE_URL,
    )
    response = client.chat.completions.create(
        model=ORCAROUTER_MODEL,
        temperature=0.7,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content or ""


def call_local_llm(prompt: str) -> str:
    """Dispatch to the configured local LLM provider."""
    provider = (LLM_PROVIDER or "openai").strip().lower()
    if provider == "openai":
        return call_openai_llm(prompt)
    if provider == "gemini":
        return call_gemini_llm(prompt)
    if provider == "orcarouter":
        return call_orcarouter_llm(prompt)
    raise RuntimeError(
        f"Unknown LLM_PROVIDER={provider!r}. Use 'openai', 'gemini', or 'orcarouter'."
    )
