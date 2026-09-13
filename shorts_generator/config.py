import json
import math
import os
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator, Optional

from dotenv import load_dotenv

load_dotenv()

MUAPI_API_KEY = os.getenv("MUAPI_API_KEY", "").strip()
MUAPI_BASE_URL = (os.getenv("MUAPI_BASE_URL", "https://api.muapi.ai/api/v1").strip() or "https://api.muapi.ai/api/v1").rstrip("/")



def _positive_float_env(name: str, default: float) -> float:
    """Read a positive finite float without letting a bad .env crash startup."""
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return value if math.isfinite(value) and value > 0 else default


POLL_INTERVAL_SECONDS = _positive_float_env("MUAPI_POLL_INTERVAL", 5.0)
POLL_TIMEOUT_SECONDS = _positive_float_env("MUAPI_POLL_TIMEOUT", 600.0)

# Local-mode (--mode local) settings — only consulted when running offline.
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip() or "gemini-2.5-flash"
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai").strip().lower()
LOCAL_WHISPER_MODEL = os.getenv("LOCAL_WHISPER_MODEL", "base").strip() or "base"
LOCAL_WHISPER_DEVICE = os.getenv("LOCAL_WHISPER_DEVICE", "auto").strip().lower() or "auto"  # auto / cpu / cuda
LOCAL_OUTPUT_DIR = os.getenv("LOCAL_OUTPUT_DIR", "output").strip() or "output"
LOCAL_BURN_CAPTIONS = os.getenv("LOCAL_BURN_CAPTIONS", "true").strip().lower() == "true"
LOCAL_HEURISTIC_FALLBACK = os.getenv("LOCAL_HEURISTIC_FALLBACK", "true").strip().lower() == "true"


# The web editor can accept credentials for the current session without writing
# them to job metadata, .env files, or the repository.  Context-local values
# are isolated per worker thread so two queued jobs never share a submitted
# key accidentally.  A missing override falls back to the normal environment
# variable, preserving CLI and .env behavior.
_RUNTIME_CREDENTIALS: ContextVar[dict[str, str]] = ContextVar(
    "shorts_studio_runtime_credentials", default={}
)


def current_api_key(name: str) -> str:
    """Return a runtime credential override or its environment fallback."""
    key_name = str(name or "").strip().lower()
    configured = {
        "muapi": MUAPI_API_KEY,
        "openai": OPENAI_API_KEY,
        "gemini": GEMINI_API_KEY,
    }.get(key_name, "")
    values = _RUNTIME_CREDENTIALS.get()
    return str(values.get(key_name, configured) or "").strip()


def current_llm_provider() -> str:
    """Return the session-selected local ranking provider."""
    values = _RUNTIME_CREDENTIALS.get()
    return str(values.get("llm_provider", LLM_PROVIDER) or "openai").strip().lower()


@contextmanager
def runtime_credentials(
    *,
    muapi_api_key: Optional[str] = None,
    openai_api_key: Optional[str] = None,
    gemini_api_key: Optional[str] = None,
    llm_provider: Optional[str] = None,
) -> Iterator[None]:
    """Temporarily apply credentials supplied by the local UI.

    Values are intentionally context-local and never persisted. ``None``
    leaves the environment fallback active; an empty value removes a previous
    override in the current context.
    """
    values = dict(_RUNTIME_CREDENTIALS.get())
    for name, value in (
        ("muapi", muapi_api_key),
        ("openai", openai_api_key),
        ("gemini", gemini_api_key),
        ("llm_provider", llm_provider),
    ):
        if value is None:
            continue
        cleaned = str(value).strip()
        if cleaned:
            values[name] = cleaned
        else:
            values.pop(name, None)
    token = _RUNTIME_CREDENTIALS.set(values)
    try:
        yield
    finally:
        _RUNTIME_CREDENTIALS.reset(token)


def gpu_status() -> dict:
    """Return safe CUDA availability details for the UI."""
    status = {"cuda_available": False, "device_name": None, "reason": "CUDA runtime unavailable"}
    try:
        import torch  # type: ignore
        if torch.cuda.is_available():
            status.update(cuda_available=True, device_name=torch.cuda.get_device_name(0), reason="ready")
        else:
            status["reason"] = "PyTorch CUDA unavailable"
    except Exception:
        status["reason"] = "PyTorch not installed"
    if not status["cuda_available"]:
        try:
            import ctranslate2  # type: ignore
            count = int(ctranslate2.get_cuda_device_count())
            if count > 0:
                status.update(
                    cuda_available=True,
                    device_name=f"CUDA device ({count} available)",
                    reason="ready via CTranslate2",
                )
            elif status["reason"] == "PyTorch not installed":
                status["reason"] = "No CUDA device detected"
        except Exception as exc:
            if status["reason"] == "PyTorch not installed":
                status["reason"] = str(exc)
    return status

# VAD (Voice Activity Detection) settings for faster-whisper
# Default threshold is 0.5; lower = more sensitive, higher = less sensitive
# Default min_speech_duration_ms is 250ms; increase to avoid tiny false positives
# Default min_silence_duration_ms is 2000ms; increase to avoid splitting mid-sentence
# DISABLED by default because VAD is too aggressive on mixed speech/music content
LOCAL_WHISPER_VAD_FILTER = os.getenv("LOCAL_WHISPER_VAD_FILTER", "false").strip().lower() == "true"
_vad_params_env = os.getenv("LOCAL_WHISPER_VAD_PARAMETERS", "")
if _vad_params_env:
    try:
        parsed_vad = json.loads(_vad_params_env)
    except (TypeError, ValueError):
        parsed_vad = None
    LOCAL_WHISPER_VAD_PARAMETERS = parsed_vad if isinstance(parsed_vad, dict) else {
        "threshold": 0.5,
        "min_speech_duration_ms": 250,
        "max_speech_duration_s": float("inf"),
        "min_silence_duration_ms": 2000,
        "speech_pad_ms": 400,
    }
else:
    # Match faster-whisper defaults when VAD is enabled
    LOCAL_WHISPER_VAD_PARAMETERS = {
        "threshold": 0.5,
        "min_speech_duration_ms": 250,
        "max_speech_duration_s": float("inf"),
        "min_silence_duration_ms": 2000,
        "speech_pad_ms": 400,
    }


def require_api_key() -> str:
    key = current_api_key("muapi")
    if not key:
        raise RuntimeError(
            "MUAPI_API_KEY is not set. Add it to your .env file or export it as an env var."
        )
    return key


def require_openai_key() -> str:
    key = current_api_key("openai")
    if not key:
        raise RuntimeError(
            "OPENAI_API_KEY is not set. Local mode needs an OpenAI key for highlight ranking. "
            "Add it to your .env or export it, or switch back to --mode api."
        )
    return key


def require_gemini_key() -> str:
    key = current_api_key("gemini")
    if not key:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. Local mode needs a Gemini key when LLM_PROVIDER=gemini. "
            "Add it to your .env or export it, or switch LLM_PROVIDER back to openai."
        )
    return key
