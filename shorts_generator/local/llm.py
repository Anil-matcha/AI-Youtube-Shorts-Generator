"""Local LLM backend — OpenAI, Gemini, or LiteLLM, selected by LLM_PROVIDER."""
from ..config import (
    GEMINI_MODEL,
    LITELLM_API_KEY,
    LITELLM_BASE_URL,
    LITELLM_MODEL,
    LLM_PROVIDER,
    OPENAI_MODEL,
    require_gemini_key,
    require_openai_key,
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


def call_litellm_llm(prompt: str) -> str:
    """LiteLLM gateway backend used by --mode local when LLM_PROVIDER=litellm.

    Routes highlight ranking through LiteLLM's unified interface, so the same
    prompt can target 100+ providers (OpenAI, Anthropic, Gemini, Bedrock, Azure,
    self-hosted, ...) or a self-hosted LiteLLM proxy by changing LITELLM_MODEL /
    LITELLM_BASE_URL instead of touching code.
    """
    try:
        import litellm  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            "litellm is required for LLM_PROVIDER=litellm. Install it with:\n"
            "    pip install -r requirements-local.txt"
        ) from e

    kwargs = {
        "model": LITELLM_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7,
        # Silently drop params an upstream provider doesn't accept (e.g. a fixed
        # temperature on some reasoning models) so one call works across providers.
        "drop_params": True,
    }
    # Forward credentials only when set; blank lets LiteLLM fall back to the
    # upstream provider's own env var (OPENAI_API_KEY, ANTHROPIC_API_KEY, ...).
    if LITELLM_API_KEY:
        kwargs["api_key"] = LITELLM_API_KEY
    if LITELLM_BASE_URL:
        kwargs["api_base"] = LITELLM_BASE_URL

    response = litellm.completion(**kwargs)
    return response.choices[0].message.content or ""  # type: ignore[union-attr]


def call_local_llm(prompt: str) -> str:
    """Dispatch to the configured local LLM provider."""
    provider = (LLM_PROVIDER or "openai").strip().lower()
    if provider == "openai":
        return call_openai_llm(prompt)
    if provider == "gemini":
        return call_gemini_llm(prompt)
    if provider == "litellm":
        return call_litellm_llm(prompt)
    raise RuntimeError(
        f"Unknown LLM_PROVIDER={provider!r}. Use 'openai', 'gemini', or 'litellm'."
    )
