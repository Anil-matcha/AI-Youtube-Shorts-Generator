"""Platform export contract tests."""

from __future__ import annotations

import pytest

from shorts_generator.export_profiles import export_preset_specs, resolve_export_dimensions, validate_export_settings


def test_platform_presets_expose_validated_dimensions() -> None:
    specs = export_preset_specs()
    keys = {item["key"] for item in specs}
    assert {"youtube_shorts", "tiktok", "instagram_reels", "instagram_feed", "youtube_landscape"} <= keys
    assert resolve_export_dimensions("4:5", 1350, "instagram_feed") == ("4:5", 1350, 1080)
    assert resolve_export_dimensions("16:9", 1080, "youtube_landscape") == ("16:9", 1080, 1920)


def test_platform_preset_rejects_incompatible_canvas_and_duration() -> None:
    with pytest.raises(ValueError, match="requires aspect_ratio"):
        validate_export_settings("9:16", 1920, preset="instagram_feed")
    with pytest.raises(ValueError, match="up to 90"):
        validate_export_settings("9:16", 1920, duration_seconds=91, preset="instagram_reels")
