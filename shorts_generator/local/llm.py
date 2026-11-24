"""Local LLM backend — Intel Arc Models Runner, OpenAI, or Gemini, selected by LLM_PROVIDER."""
import json
import urllib.error
import urllib.request
from typing import Dict, Any

from ..config import (
    ARC_RUNNER_BASE_URL,
    ARC_RUNNER_MODEL,
    ARC_RUNNER_TIMEOUT,
    GEMINI_MODEL,
    LLM_PROVIDER,
    OPENAI_MODEL,
    require_gemini_key,
    require_openai_key,
)


def call_arc_runner_llm(prompt: str) -> str:
    """Hardware-accelerated local LLM backend via Intel Arc Models Runner.

    Connects to the native Intel Arc GPU / Level Zero / OpenVINO GenAI runner
    via its OpenAI-compatible /v1/chat/completions endpoint using standard library urllib.

    Args:
        prompt: User instructions or transcript payload.

    Returns:
        Generated text response from the model.

    Raises:
        RuntimeError: If connection fails or the runner returns an error status.
    """
    url = f"{ARC_RUNNER_BASE_URL}/v1/chat/completions"
    payload = {
        "model": ARC_RUNNER_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "User-Agent": "AI-Shorts-Generator/IntelArc"},
    )

    try:
        with urllib.request.urlopen(req, timeout=ARC_RUNNER_TIMEOUT) as response:
            body = response.read().decode("utf-8")
            res_json = json.loads(body)
            choices = res_json.get("choices", [])
            if not choices:
                return ""
            msg = choices[0].get("message", {})
            return msg.get("content", "") or ""
    except urllib.error.URLError as err:
        raise RuntimeError(
            f"Failed to connect to Intel Arc Models Runner at {ARC_RUNNER_BASE_URL} (error: {err}).\n"
            "Ensure the runner is active. You can start it from intel-arc-models-runner with:\n"
            "    python -m arc_runner.server --port 11434"
        ) from err
    except (json.JSONDecodeError, KeyError) as err:
        raise RuntimeError(
            f"Invalid response payload received from Intel Arc Models Runner: {err}"
        ) from err


def call_openai_llm(prompt: str) -> str:
    """OpenAI Chat Completions backend used by --mode local.

    Args:
        prompt: User instructions or transcript payload.

    Returns:
        Generated text response from OpenAI.

    Raises:
        RuntimeError: If the openai package is not installed.
    """
    try:
        from openai import OpenAI
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
    """Gemini backend used by --mode local when LLM_PROVIDER=gemini.

    Args:
        prompt: User instructions or transcript payload.

    Returns:
        Generated text response from Gemini.

    Raises:
        RuntimeError: If the google-genai package is not installed.
    """
    try:
        from google import genai
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


def call_local_llm(prompt: str) -> str:
    """Dispatch to the configured local LLM provider.

    Args:
        prompt: User instructions or transcript payload.

    Returns:
        Generated response string.

    Raises:
        RuntimeError: If an unsupported LLM provider is specified.
    """
    provider = (LLM_PROVIDER or "openai").strip().lower()
    if provider in ("arc_runner", "intel_arc", "arc"):
        return call_arc_runner_llm(prompt)
    if provider == "openai":
        return call_openai_llm(prompt)
    if provider == "gemini":
        return call_gemini_llm(prompt)
    raise RuntimeError(
        f"Unknown LLM_PROVIDER={provider!r}. Use 'arc_runner', 'openai', or 'gemini'."
    )
