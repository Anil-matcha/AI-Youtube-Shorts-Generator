"""Centralized filesystem path resolution for shorts generation pipeline.

Enforces clean architectural separation between:
- Intermediate raw assets: output/raw/{images,audio,video,captions}
- Customer-facing final deliverables: output/
"""

import os
from pathlib import Path
from typing import Union


def get_base_dir() -> Path:
    """Return the absolute base path of the project workspace.

    Returns:
        Path pointing to the ai-shorts-generator root directory.
    """
    return Path(__file__).resolve().parent.parent


def get_output_dir() -> Path:
    """Return the master output directory for finalized shorts.

    Returns:
        Path pointing to the output directory.
    """
    env_dir = os.getenv("LOCAL_OUTPUT_DIR", "output")
    out = Path(env_dir)
    if not out.is_absolute():
        out = get_base_dir() / out
    return out


def get_raw_dir() -> Path:
    """Return the base raw directory for intermediate processing assets.

    Returns:
        Path pointing to output/raw.
    """
    return get_output_dir() / "raw"


def get_raw_images_dir() -> Path:
    """Return the directory for intermediate frames, crops, and thumbnails.

    Returns:
        Path pointing to output/raw/images.
    """
    return get_raw_dir() / "images"


def get_raw_audio_dir() -> Path:
    """Return the directory for extracted audio streams and voice tracks.

    Returns:
        Path pointing to output/raw/audio.
    """
    return get_raw_dir() / "audio"


def get_raw_video_dir() -> Path:
    """Return the directory for raw video slices and benchmark clips.

    Returns:
        Path pointing to output/raw/video.
    """
    return get_raw_dir() / "video"


def get_raw_captions_dir() -> Path:
    """Return the directory for ASS subtitles and Whisper transcripts.

    Returns:
        Path pointing to output/raw/captions.
    """
    return get_raw_dir() / "captions"


def ensure_output_dirs() -> None:
    """Ensure all required output and raw subdirectories exist on disk.

    Creates output/, output/raw/images, output/raw/audio,
    output/raw/video, and output/raw/captions if they do not exist.
    """
    for d in (
        get_output_dir(),
        get_raw_images_dir(),
        get_raw_audio_dir(),
        get_raw_video_dir(),
        get_raw_captions_dir(),
    ):
        d.mkdir(parents=True, exist_ok=True)


def resolve_raw_image_path(filename: Union[str, Path]) -> str:
    """Resolve an image filename to an absolute path inside output/raw/images.

    Args:
        filename: Base filename or relative path.

    Returns:
        Absolute filesystem path as a string.
    """
    ensure_output_dirs()
    return str(get_raw_images_dir() / Path(filename).name)


def resolve_raw_audio_path(filename: Union[str, Path]) -> str:
    """Resolve an audio filename to an absolute path inside output/raw/audio.

    Args:
        filename: Base filename or relative path.

    Returns:
        Absolute filesystem path as a string.
    """
    ensure_output_dirs()
    return str(get_raw_audio_dir() / Path(filename).name)


def resolve_raw_video_path(filename: Union[str, Path]) -> str:
    """Resolve a video filename to an absolute path inside output/raw/video.

    Args:
        filename: Base filename or relative path.

    Returns:
        Absolute filesystem path as a string.
    """
    ensure_output_dirs()
    return str(get_raw_video_dir() / Path(filename).name)


def resolve_raw_caption_path(filename: Union[str, Path]) -> str:
    """Resolve a caption filename to an absolute path inside output/raw/captions.

    Args:
        filename: Base filename or relative path.

    Returns:
        Absolute filesystem path as a string.
    """
    ensure_output_dirs()
    return str(get_raw_captions_dir() / Path(filename).name)


def resolve_final_short_path(filename: Union[str, Path]) -> str:
    """Resolve a finalized master short filename directly inside output/.

    Args:
        filename: Base filename or relative path.

    Returns:
        Absolute filesystem path as a string.
    """
    ensure_output_dirs()
    return str(get_output_dir() / Path(filename).name)
