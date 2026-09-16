"""Platform export presets and validation shared by API and local rendering."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class ExportPreset:
    key: str
    label: str
    aspect_ratio: str
    width: int
    height: int
    fps: int
    max_duration_seconds: int
    description: str


EXPORT_PRESETS: Dict[str, ExportPreset] = {
    "youtube_shorts": ExportPreset(
        "youtube_shorts", "YouTube Shorts", "9:16", 1080, 1920, 30, 180,
        "Vertical H.264/AAC, 1080x1920, up to 3 minutes.",
    ),
    "tiktok": ExportPreset(
        "tiktok", "TikTok", "9:16", 1080, 1920, 30, 600,
        "Vertical H.264/AAC, 1080x1920, up to 10 minutes.",
    ),
    "instagram_reels": ExportPreset(
        "instagram_reels", "Instagram Reels", "9:16", 1080, 1920, 30, 90,
        "Vertical H.264/AAC, 1080x1920, up to 90 seconds.",
    ),
    "instagram_feed": ExportPreset(
        "instagram_feed", "Instagram feed portrait", "4:5", 1080, 1350, 30, 90,
        "Portrait H.264/AAC, 1080x1350, up to 90 seconds.",
    ),
    "youtube_landscape": ExportPreset(
        "youtube_landscape", "YouTube landscape", "16:9", 1920, 1080, 30, 180,
        "Landscape H.264/AAC, 1920x1080, up to 3 minutes.",
    ),
    "landscape_hd": ExportPreset(
        "landscape_hd", "Landscape HD", "16:9", 1280, 720, 30, 600,
        "Landscape H.264/AAC, 1280x720.",
    ),
}


def export_preset_specs() -> list[Dict[str, Any]]:
    """Return JSON-safe preset metadata for the editor."""
    return [asdict(item) for item in EXPORT_PRESETS.values()]


def validate_export_settings(
    aspect_ratio: str,
    output_height: int,
    duration_seconds: Optional[float] = None,
    preset: Optional[str] = None,
) -> ExportPreset | None:
    """Validate requested dimensions and optionally return the selected preset.

    A preset owns its aspect ratio and canvas height. Without one, the editor
    still accepts custom heights while restricting ratios to the supported
    9:16, 1:1, 4:5, and 16:9 canvases.
    """
    ratio = str(aspect_ratio or "9:16").strip()
    if ratio not in {"9:16", "1:1", "4:5", "16:9"}:
        raise ValueError("aspect_ratio must be one of 9:16, 1:1, 4:5, or 16:9")
    try:
        height = int(output_height)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("output_height must be an integer") from exc
    if height and (height < 240 or height > 4320):
        raise ValueError("output_height must be between 240 and 4320 pixels")
    selected: ExportPreset | None = None
    if preset:
        selected = EXPORT_PRESETS.get(str(preset).strip().lower())
        if selected is None:
            raise ValueError(f"unknown export preset: {preset}")
        if ratio != selected.aspect_ratio:
            raise ValueError(f"preset {selected.key} requires aspect_ratio={selected.aspect_ratio}")
        if height and height != selected.height:
            raise ValueError(f"preset {selected.key} requires output_height={selected.height}")
        if duration_seconds is not None and duration_seconds > selected.max_duration_seconds + 0.01:
            raise ValueError(
                f"preset {selected.key} supports clips up to {selected.max_duration_seconds} seconds"
            )
    return selected


def resolve_export_dimensions(aspect_ratio: str, output_height: int, preset: Optional[str] = None) -> tuple[str, int, int]:
    """Return (aspect ratio, height, even width) for a render."""
    selected = validate_export_settings(aspect_ratio, output_height, preset=preset)
    if selected:
        return selected.aspect_ratio, selected.height, selected.width
    try:
        height = int(output_height)
    except (TypeError, ValueError, OverflowError):
        height = 1920
    height = max(240, min(4320, height or 1920))
    numerator, denominator = (int(part) for part in str(aspect_ratio).split(":", 1))
    width = max(2, int(round(height * numerator / denominator)))
    return str(aspect_ratio), height, width - (width % 2)
