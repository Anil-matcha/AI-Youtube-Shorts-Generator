import json
import logging
import math
import os
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

from dotenv import load_dotenv

load_dotenv()

MUAPI_API_KEY = os.getenv("MUAPI_API_KEY", "").strip()
MUAPI_BASE_URL = (
    os.getenv("MUAPI_BASE_URL", "https://api.muapi.ai/api/v1").strip() or "https://api.muapi.ai/api/v1"
).rstrip("/")


def _positive_float_env(name: str, default: float) -> float:
    """Read a positive finite float without letting a bad .env crash startup."""
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return value if math.isfinite(value) and value > 0 else default


def _positive_int_env(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError, OverflowError):
        return default
    return max(1, value)


def _nonnegative_float_env(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError, OverflowError):
        return default
    return value if math.isfinite(value) and value >= 0 else default


POLL_INTERVAL_SECONDS = _positive_float_env("MUAPI_POLL_INTERVAL", 5.0)
POLL_TIMEOUT_SECONDS = _positive_float_env("MUAPI_POLL_TIMEOUT", 600.0)

# Local-mode (--mode local) settings — only consulted when running offline.
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip() or "gemini-2.5-flash"
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai").strip().lower()
LOCAL_WHISPER_MODEL = os.getenv("LOCAL_WHISPER_MODEL", "base").strip() or "base"
LOCAL_AUTO_SELECT_WHISPER_MODEL = os.getenv("LOCAL_AUTO_SELECT_WHISPER_MODEL", "false").strip().lower() in {
    "1", "true", "yes", "on"
}
LOCAL_WHISPER_DEVICE = os.getenv("LOCAL_WHISPER_DEVICE", "auto").strip().lower() or "auto"  # auto / cpu / cuda
LOCAL_OUTPUT_DIR = os.getenv("LOCAL_OUTPUT_DIR", "output").strip() or "output"
LOCAL_BURN_CAPTIONS = os.getenv("LOCAL_BURN_CAPTIONS", "true").strip().lower() == "true"
LOCAL_HEURISTIC_FALLBACK = os.getenv("LOCAL_HEURISTIC_FALLBACK", "true").strip().lower() == "true"
LOCAL_ENCODE_PRESET = os.getenv("LOCAL_ENCODE_PRESET", "fast").strip() or "fast"
LOCAL_CRF = _positive_float_env("LOCAL_CRF", 20.0)
LOCAL_AUDIO_BITRATE = os.getenv("LOCAL_AUDIO_BITRATE", "128k").strip() or "128k"
LOCAL_OUTPUT_TEMPLATE = os.getenv("LOCAL_OUTPUT_TEMPLATE", "short_{index:02d}.mp4").strip() or "short_{index:02d}.mp4"
# ``LOCAL_MAX_FFMPEG_PROCS`` is the historical name. Keep it as the shared
# internal value while allowing the beta-facing ``SHORTS_RENDER_WORKERS``
# setting to take precedence when both names are present.
_legacy_ffmpeg_processes = _positive_int_env("LOCAL_MAX_FFMPEG_PROCS", 2)
LOCAL_MAX_FFMPEG_PROCS = _positive_int_env("SHORTS_RENDER_WORKERS", _legacy_ffmpeg_processes)
LOCAL_LOG_LEVEL = os.getenv("LOCAL_LOG_LEVEL", "INFO").strip().upper() or "INFO"
LOCAL_LOG_FILE = os.getenv("LOCAL_LOG_FILE", "").strip()
LOCAL_TEMP_DIR = os.getenv("LOCAL_TEMP_DIR", "").strip()
LOCAL_THUMBNAIL_POSITION = min(1.0, max(0.0, _nonnegative_float_env("LOCAL_THUMBNAIL_POSITION", 0.5)))
LOCAL_RANGE_MERGE_TOLERANCE = _positive_float_env("LOCAL_RANGE_MERGE_TOLERANCE", 0.35)
LOCAL_FFMPEG_REMOVE_RETRY_ATTEMPTS = _positive_int_env("LOCAL_FFMPEG_REMOVE_RETRY_ATTEMPTS", 8)
LOCAL_FFMPEG_REMOVE_RETRY_DELAY = _positive_float_env("LOCAL_FFMPEG_REMOVE_RETRY_DELAY", 0.5)
LOCAL_CAPTION_PRESETS_FILE = os.getenv("LOCAL_CAPTION_PRESETS_FILE", "").strip()
LOCAL_VIRALITY_PROMPT_FILE = os.getenv("LOCAL_VIRALITY_PROMPT_FILE", "").strip()
LOCAL_VIRALITY_PROMPT = os.getenv("LOCAL_VIRALITY_PROMPT", "").strip()
LOCAL_MUSIC_DUCKING = os.getenv("LOCAL_MUSIC_DUCKING", "false").strip().lower() in {"1", "true", "yes", "on"}
LOCAL_DUCKING_STRENGTH = min(1.0, max(0.0, _nonnegative_float_env("LOCAL_DUCKING_STRENGTH", 0.65)))
LOCAL_TRANSITION = os.getenv("LOCAL_TRANSITION", "none").strip().lower() or "none"
LOCAL_TRANSITION_DURATION = min(2.0, max(0.0, _nonnegative_float_env("LOCAL_TRANSITION_DURATION", 0.25)))
LOCAL_AUDIO_SILENCE_FILTER = os.getenv(
    "LOCAL_AUDIO_SILENCE_FILTER",
    "silenceremove=stop_periods=1:stop_duration=0.35:stop_threshold=-40dB",
).strip()
LOCAL_AUDIO_NORMALIZE_FILTER = os.getenv("LOCAL_AUDIO_NORMALIZE_FILTER", "loudnorm=I=-14:TP=-1.5:LRA=11").strip()
LOCAL_AUDIO_DENOISE_FILTER = os.getenv("LOCAL_AUDIO_DENOISE_FILTER", "afftdn=nf=-25").strip()
HIGHLIGHT_MIN_DURATION_SECONDS = _positive_float_env("HIGHLIGHT_MIN_DURATION_SECONDS", 2.0)
HIGHLIGHT_MAX_DURATION_SECONDS = _positive_float_env("HIGHLIGHT_MAX_DURATION_SECONDS", 180.0)
HIGHLIGHT_CHUNK_SIZE_SECONDS = _positive_float_env("HIGHLIGHT_CHUNK_SIZE_SECONDS", 1200.0)
HIGHLIGHT_CHUNK_OVERLAP_SECONDS = _positive_float_env("HIGHLIGHT_CHUNK_OVERLAP_SECONDS", 60.0)
HIGHLIGHT_DEDUPE_OVERLAP = min(0.99, max(0.0, _positive_float_env("HIGHLIGHT_DEDUPE_OVERLAP", 0.5)))
HIGHLIGHT_MAX_CLIPS = _positive_int_env("HIGHLIGHT_MAX_CLIPS", 12)
HIGHLIGHT_MAX_API_ATTEMPTS = _positive_int_env("HIGHLIGHT_MAX_API_ATTEMPTS", 3)
LOCAL_LLM_MAX_RETRIES = max(0, _positive_int_env("LOCAL_LLM_MAX_RETRIES", 5))
LOCAL_LLM_RETRY_DELAY_SECONDS = _positive_float_env("LOCAL_LLM_RETRY_DELAY_SECONDS", 30.0)
LOCAL_LLM_MAX_OUTPUT_TOKENS = max(256, _positive_int_env("LOCAL_LLM_MAX_OUTPUT_TOKENS", 32768))
LOCAL_LLM_TIMEOUT_SECONDS = _positive_float_env("LOCAL_LLM_TIMEOUT_SECONDS", 300.0)
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").strip().rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2").strip() or "llama3.2"
MUAPI_RETRY_DELAY_SECONDS = _positive_float_env("MUAPI_RETRY_DELAY_SECONDS", 5.0)
# Face tracking defaults to ``auto``: use the OpenCV DNN model when the optional
# files are present, otherwise retain the lightweight Haar fallback.  Set this
# to ``dnn`` to require the modern detector, or ``haar`` to force the fallback.
FACE_DETECTOR = os.getenv("SHORTS_FACE_DETECTOR", "auto").strip().lower() or "auto"
FACE_DNN_MODEL = os.getenv("SHORTS_FACE_DNN_MODEL", "").strip()
FACE_DNN_CONFIG = os.getenv("SHORTS_FACE_DNN_CONFIG", "").strip()
FACE_HAAR_SCALE_FACTOR = _positive_float_env("SHORTS_FACE_HAAR_SCALE_FACTOR", 1.1)
FACE_HAAR_MIN_NEIGHBORS = _positive_int_env("SHORTS_FACE_HAAR_MIN_NEIGHBORS", 5)
FACE_HAAR_MIN_SIZE = _positive_int_env("SHORTS_FACE_HAAR_MIN_SIZE", 40)
FACE_DNN_CONFIDENCE = min(0.99, max(0.01, _positive_float_env("SHORTS_FACE_DNN_CONFIDENCE", 0.45)))
FACE_DETECTOR_PLUGIN = os.getenv("SHORTS_FACE_DETECTOR_PLUGIN", "").strip()
FACE_SMOOTHING = min(1.0, max(0.0, _positive_float_env("SHORTS_FACE_SMOOTHING", 0.15)))


def configure_logging() -> None:
    """Apply one safe logging policy for CLI, web, and packaged workers."""
    level = getattr(logging, LOCAL_LOG_LEVEL, logging.INFO)
    kwargs: dict[str, Any] = {
        "level": level,
        "format": "%(asctime)s %(levelname)s %(name)s %(message)s",
    }
    if LOCAL_LOG_FILE:
        try:
            log_path = Path(LOCAL_LOG_FILE).expanduser()
            log_path.parent.mkdir(parents=True, exist_ok=True)
            kwargs["filename"] = str(log_path)
        except (OSError, RuntimeError, ValueError):
            # A bad optional log path must never prevent the app from starting.
            pass
    logging.basicConfig(**kwargs)


configure_logging()


# The web editor can accept credentials for the current session without writing
# them to job metadata, .env files, or the repository.  Context-local values
# are isolated per worker thread so two queued jobs never share a submitted
# key accidentally.  A missing override falls back to the normal environment
# variable, preserving CLI and .env behavior.
_RUNTIME_CREDENTIALS: ContextVar[dict[str, str]] = ContextVar("shorts_studio_runtime_credentials", default={})
_RUNTIME_LLM_OPTIONS: ContextVar[dict[str, str]] = ContextVar("shorts_studio_runtime_llm_options", default={})
_RUNTIME_CANCEL_CHECK: ContextVar[Optional[Callable[[], bool]]] = ContextVar(
    "shorts_studio_runtime_cancel_check", default=None
)
_RUNTIME_PROCESS_REGISTER: ContextVar[Optional[Callable[[Any], None]]] = ContextVar(
    "shorts_studio_runtime_process_register", default=None
)
_RUNTIME_PROCESS_UNREGISTER: ContextVar[Optional[Callable[[Any], None]]] = ContextVar(
    "shorts_studio_runtime_process_unregister", default=None
)
_RUNTIME_LLM_USAGE: ContextVar[dict[str, Any]] = ContextVar("shorts_studio_runtime_llm_usage", default={})


def cancellation_requested() -> bool:
    """Return whether the current render has received a cancellation request."""
    callback = _RUNTIME_CANCEL_CHECK.get()
    try:
        return bool(callback and callback())
    except Exception:
        return False


def register_runtime_process(process: Any) -> None:
    """Register a child process with the owning job for cooperative shutdown."""
    callback = _RUNTIME_PROCESS_REGISTER.get()
    if callback:
        callback(process)


def unregister_runtime_process(process: Any) -> None:
    """Remove a child process from the owning job's termination registry."""
    callback = _RUNTIME_PROCESS_UNREGISTER.get()
    if callback:
        callback(process)


def record_llm_usage(provider: str, model: str, usage: Any) -> None:
    """Record normalized provider usage in the current job context."""
    values = dict(_RUNTIME_LLM_USAGE.get())
    values[str(provider or "unknown").strip().lower()] = {
        "provider": str(provider or "unknown").strip().lower(),
        "model": str(model or "").strip(),
        "usage": usage,
    }
    _RUNTIME_LLM_USAGE.set(values)


def current_llm_usage() -> dict[str, Any]:
    return dict(_RUNTIME_LLM_USAGE.get())


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


def current_llm_model(provider: Optional[str] = None) -> str:
    """Return a per-job model override, falling back to the configured provider."""
    selected = str(provider or current_llm_provider()).strip().lower()
    values = _RUNTIME_LLM_OPTIONS.get()
    override = str(values.get("llm_model", "") or "").strip()
    if override:
        return override
    if selected == "openai":
        return OPENAI_MODEL
    if selected == "gemini":
        return GEMINI_MODEL
    return OLLAMA_MODEL


def current_llm_temperature(default: float = 0.2) -> float:
    """Return a finite per-job temperature override."""
    values = _RUNTIME_LLM_OPTIONS.get()
    try:
        value = float(values.get("llm_temperature", default))
    except (TypeError, ValueError, OverflowError):
        return default
    return value if math.isfinite(value) and 0.0 <= value <= 1.0 else default


@contextmanager
def runtime_credentials(
    *,
    muapi_api_key: Optional[str] = None,
    openai_api_key: Optional[str] = None,
    gemini_api_key: Optional[str] = None,
    llm_provider: Optional[str] = None,
    llm_model: Optional[str] = None,
    llm_temperature: Optional[float] = None,
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
    options = dict(_RUNTIME_LLM_OPTIONS.get())
    if llm_model is not None:
        cleaned_model = str(llm_model).strip()
        if cleaned_model:
            options["llm_model"] = cleaned_model
        else:
            options.pop("llm_model", None)
    if llm_temperature is not None:
        options["llm_temperature"] = str(llm_temperature)
    token = _RUNTIME_CREDENTIALS.set(values)
    options_token = _RUNTIME_LLM_OPTIONS.set(options)
    try:
        yield
    finally:
        _RUNTIME_LLM_OPTIONS.reset(options_token)
        _RUNTIME_CREDENTIALS.reset(token)


@contextmanager
def runtime_job_control(
    *,
    cancel_check: Optional[Callable[[], bool]] = None,
    register_process: Optional[Callable[[Any], None]] = None,
    unregister_process: Optional[Callable[[Any], None]] = None,
) -> Iterator[None]:
    """Bind cancellation and child-process callbacks to the current worker."""
    cancel_token = _RUNTIME_CANCEL_CHECK.set(cancel_check)
    register_token = _RUNTIME_PROCESS_REGISTER.set(register_process)
    unregister_token = _RUNTIME_PROCESS_UNREGISTER.set(unregister_process)
    try:
        yield
    finally:
        _RUNTIME_PROCESS_UNREGISTER.reset(unregister_token)
        _RUNTIME_PROCESS_REGISTER.reset(register_token)
        _RUNTIME_CANCEL_CHECK.reset(cancel_token)


@contextmanager
def runtime_llm_usage() -> Iterator[None]:
    """Reset usage for one pipeline invocation and restore the parent context."""
    token = _RUNTIME_LLM_USAGE.set({})
    try:
        yield
    finally:
        _RUNTIME_LLM_USAGE.reset(token)


def gpu_status() -> dict:
    """Return safe CUDA availability details for the UI."""
    status = {"cuda_available": False, "device_name": None, "reason": "CUDA runtime unavailable"}
    try:
        torch = import_module("torch")

        if torch.cuda.is_available():
            status.update(cuda_available=True, device_name=torch.cuda.get_device_name(0), reason="ready")
        else:
            status["reason"] = "PyTorch CUDA unavailable"
    except Exception:
        status["reason"] = "PyTorch not installed"
    if not status["cuda_available"]:
        try:
            ctranslate2 = import_module("ctranslate2")

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
    LOCAL_WHISPER_VAD_PARAMETERS = (
        parsed_vad
        if isinstance(parsed_vad, dict)
        else {
            "threshold": 0.5,
            "min_speech_duration_ms": 250,
            "max_speech_duration_s": float("inf"),
            "min_silence_duration_ms": 2000,
            "speech_pad_ms": 400,
        }
    )
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
        raise RuntimeError("MUAPI_API_KEY is not set. Add it to your .env file or export it as an env var.")
    return key


def require_openai_key() -> str:
    key = current_api_key("openai")
    if not key:
        raise RuntimeError(
            "OPENAI_API_KEY is not set. Local mode needs an OpenAI key for highlight ranking. "
            "Add it to your .env or export it, or switch back to --mode api."
        )
    return key


@dataclass(frozen=True)
class PipelineConfig:
    """Validated, typed settings shared by CLI, web jobs, and renderers."""

    environment: str = "development"
    max_clips: int = 12
    encode_preset: str = "fast"
    crf: int = 20
    audio_bitrate: str = "128k"
    output_template: str = "short_{index:02d}.mp4"
    max_ffmpeg_processes: int = 2
    temp_dir: Optional[str] = None
    thumbnail_position: float = 0.5
    range_merge_tolerance: float = 0.35

    @classmethod
    def from_environment(cls) -> "PipelineConfig":
        environment = os.getenv("SHORTS_ENVIRONMENT", "development").strip().lower() or "development"
        profiles = {
            "development": {},
            "test": {"max_clips": 12},
            "staging": {},
            "production": {},
        }
        if environment not in profiles:
            environment = "development"
        return cls(
            environment=environment,
            max_clips=max(1, min(12, HIGHLIGHT_MAX_CLIPS)),
            encode_preset=LOCAL_ENCODE_PRESET,
            crf=max(0, min(51, int(LOCAL_CRF))),
            audio_bitrate=LOCAL_AUDIO_BITRATE,
            output_template=LOCAL_OUTPUT_TEMPLATE,
            max_ffmpeg_processes=max(1, LOCAL_MAX_FFMPEG_PROCS),
            temp_dir=LOCAL_TEMP_DIR or None,
            thumbnail_position=LOCAL_THUMBNAIL_POSITION,
            range_merge_tolerance=LOCAL_RANGE_MERGE_TOLERANCE,
        )

    def with_overrides(self, **values: Any) -> "PipelineConfig":
        data = {**self.__dict__, **values}
        data["max_clips"] = max(1, min(12, int(data["max_clips"])))
        data["crf"] = max(0, min(51, int(data["crf"])))
        data["thumbnail_position"] = min(1.0, max(0.0, float(data["thumbnail_position"])))
        return type(self)(**data)


def validate_config() -> list[str]:
    """Return actionable configuration errors without making imports fragile."""
    errors: list[str] = []
    if LLM_PROVIDER not in {"openai", "gemini", "ollama"}:
        errors.append("LLM_PROVIDER must be openai, gemini, or ollama")
    if LOCAL_WHISPER_DEVICE not in {"auto", "cpu", "cuda", "mps", "directml", "rocm"}:
        errors.append("LOCAL_WHISPER_DEVICE must be auto, cpu, cuda, mps, directml, or rocm")
    if HIGHLIGHT_MAX_DURATION_SECONDS < HIGHLIGHT_MIN_DURATION_SECONDS:
        errors.append("HIGHLIGHT_MAX_DURATION_SECONDS must be >= HIGHLIGHT_MIN_DURATION_SECONDS")
    try:
        rendered_template = LOCAL_OUTPUT_TEMPLATE.format(index=1, number=1)
    except (KeyError, IndexError, ValueError, TypeError):
        rendered_template = ""
    if not rendered_template or Path(rendered_template).name != rendered_template or any(
        char in rendered_template for char in "\\/:*?\"<>|"
    ):
        errors.append("LOCAL_OUTPUT_TEMPLATE contains invalid path characters")
    return errors


def require_gemini_key() -> str:
    key = current_api_key("gemini")
    if not key:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. Local mode needs a Gemini key when LLM_PROVIDER=gemini. "
            "Add it to your .env or export it, or switch LLM_PROVIDER back to openai."
        )
    return key
