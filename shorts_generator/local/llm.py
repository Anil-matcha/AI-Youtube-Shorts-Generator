"""Local LLM backend — OpenAI, Gemini, or Ollama, selected by LLM_PROVIDER."""
from ..config import (
    GEMINI_MODEL,
    LLM_PROVIDER,
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
    OLLAMA_NUM_CTX,
    OLLAMA_TIMEOUT,
    OPENAI_MODEL,
    require_gemini_key,
    require_openai_key,
    require_ollama_url,
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


def call_ollama_llm(prompt: str) -> str:
    """Ollama backend used by --mode local when LLM_PROVIDER=ollama.

    Uses the /api/chat endpoint with proper system/user message separation
    so the model understands instructions vs data. Works with any Ollama-
    compatible endpoint (local laptop, LAN server, or cloud instances).
    """
    import json as _json
    import urllib.request
    import urllib.error

    url = f"{require_ollama_url()}/api/chat"

    # Split the prompt into system instructions and user content.
    # The HIGHLIGHT_SYSTEM_PROMPT is everything before "Transcript:" or
    # before the last "\n\nTranscript:\n" separator. If we can't split,
    # fall back to sending it all as a user message.
    system_part = ""
    user_part = prompt
    marker = "\n\nTranscript:\n"
    idx = prompt.find(marker)
    if idx != -1:
        system_part = prompt[:idx]
        user_part = prompt[idx + len(marker):]

    messages = []
    if system_part:
        messages.append({"role": "system", "content": system_part})
    messages.append({"role": "user", "content": user_part})

    payload = _json.dumps({
        "model": OLLAMA_MODEL,
        "messages": messages,
        "stream": False,
        "options": {
            "temperature": 0.7,
            "num_ctx": OLLAMA_NUM_CTX,
        },
    }).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=OLLAMA_TIMEOUT) as resp:
            data = _json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Ollama HTTP {e.code}: {body}") from e
    except Exception as e:
        raise RuntimeError(f"Ollama request failed: {e}") from e

    message = data.get("message", {})
    return message.get("content", "")


def call_local_llm(prompt: str) -> str:
    """Dispatch to the configured local LLM provider."""
    provider = (LLM_PROVIDER or "openai").strip().lower()
    if provider == "openai":
        return call_openai_llm(prompt)
    if provider == "gemini":
        return call_gemini_llm(prompt)
    if provider == "ollama":
        return call_ollama_llm(prompt)
    raise RuntimeError(
        f"Unknown LLM_PROVIDER={provider!r}. Use 'openai', 'gemini', or 'ollama'."
    )
