"""TwelveLabs Pegasus highlight backend for --mode local.

Unlike the OpenAI / Gemini backends (which rank the *transcript text*), Pegasus
is a video-understanding model: it watches the actual video and answers the
same virality prompt with knowledge of what's on screen — pacing, reactions,
visual gags, on-screen text — not just the words that were spoken. That makes
it a multimodal upgrade to the highlight selection step.

Selected by setting ``LLM_PROVIDER=twelvelabs`` in ``--mode local``. Because
Pegasus needs the video (not just a prompt string), the pipeline binds the
source video path with ``functools.partial`` before handing the resulting
``(prompt) -> str`` callable to ``get_highlights``.

Index reuse: the source video is uploaded once and cached on disk next to the
mp4 as ``<video>.tlvideo`` (the TwelveLabs video id), so re-running the
pipeline on the same file skips the (slow) re-index.
"""
import os
from pathlib import Path

from ..config import (
    TWELVELABS_INDEX_ID,
    TWELVELABS_PEGASUS_MODEL,
    TWELVELABS_MAX_TOKENS,
    require_twelvelabs_key,
)


def _import_sdk():
    try:
        from twelvelabs import TwelveLabs  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            "twelvelabs is required for LLM_PROVIDER=twelvelabs. Install it with:\n"
            "    pip install -r requirements-local.txt"
        ) from e
    return TwelveLabs


def _ensure_index(client) -> str:
    """Return a Pegasus-enabled index id, creating one if not configured."""
    if TWELVELABS_INDEX_ID:
        return TWELVELABS_INDEX_ID
    index = client.indexes.create(
        index_name="ai-youtube-shorts-generator",
        models=[{"model_name": TWELVELABS_PEGASUS_MODEL, "model_options": ["visual", "audio"]}],
    )
    return index.id


def _cached_video_id(video_path: str) -> str:
    """Index the video once; cache the resulting video id beside the file."""
    cache = Path(f"{video_path}.tlvideo")
    if cache.exists():
        cached = cache.read_text().strip()
        if cached:
            print(f"[twelvelabs] reusing indexed video {cached}", flush=True)
            return cached

    TwelveLabs = _import_sdk()
    client = TwelveLabs(api_key=require_twelvelabs_key())
    index_id = _ensure_index(client)

    print(f"[twelvelabs] indexing {os.path.basename(video_path)} (index {index_id})", flush=True)
    with open(video_path, "rb") as f:
        task = client.tasks.create(index_id=index_id, video_file=f)
    task = client.tasks.wait_for_done(task_id=task.id)
    if task.status != "ready":
        raise RuntimeError(f"TwelveLabs indexing failed (status={task.status})")

    video_id = task.video_id
    cache.write_text(video_id)
    print(f"[twelvelabs] indexed → video {video_id}", flush=True)
    return video_id


def call_twelvelabs_llm(prompt: str, *, video_path: str) -> str:
    """Pegasus backend: analyze the video with the highlight prompt.

    ``get_highlights`` calls this as a ``(prompt) -> str`` function; the
    ``video_path`` is bound by the pipeline via ``functools.partial``.
    """
    video_id = _cached_video_id(video_path)

    TwelveLabs = _import_sdk()
    client = TwelveLabs(api_key=require_twelvelabs_key())
    result = client.analyze(
        model_name=TWELVELABS_PEGASUS_MODEL,
        video_id=video_id,
        prompt=prompt,
        max_tokens=TWELVELABS_MAX_TOKENS,
    )
    return result.data or ""
