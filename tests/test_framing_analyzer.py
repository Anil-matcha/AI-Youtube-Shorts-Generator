"""Triad unit tests for automated framing analysis and spatial reframing recommendations."""

from PIL import Image
import pytest

from shorts_generator.diversity_types import (
    CandidateHighlight,
    FramingMode,
    HighlightArchetype,
)
from shorts_generator.framing_analyzer import (
    FramingAnalyzer,
    analyze_dialogue_exchanges,
    analyze_spatial_distribution,
    detect_letterbox_borders,
)


def test_detect_letterbox_borders_with_cinema_scope():
    """Verify detection of letterbox black bars on a synthetic 2.39:1 frame."""
    w, h = 3840, 2160
    img = Image.new("RGB", (w, h), color=(0, 0, 0))
    active_top = 280
    active_bot = 280
    active_img = Image.new("RGB", (w, h - active_top - active_bot), color=(180, 180, 180))
    img.paste(active_img, (0, active_top))

    has_lb, top_b, bot_b, active_h = detect_letterbox_borders(img)

    assert has_lb is True
    assert top_b >= 275 and top_b <= 285
    assert bot_b >= 275 and bot_b <= 285
    assert active_h == h - top_b - bot_b


def test_detect_letterbox_borders_clean_frame():
    """Verify that full-bleed images without black borders report has_letterbox False."""
    img = Image.new("RGB", (640, 360), color=(140, 150, 160))

    has_lb, top_b, bot_b, active_h = detect_letterbox_borders(img)

    assert has_lb is False
    assert top_b == 0
    assert bot_b == 0
    assert active_h == 360


def test_analyze_spatial_distribution_left_heavy():
    """Verify spatial gradient energy detection when visual content is biased to the left."""
    img = Image.new("RGB", (300, 150), color=(50, 50, 50))
    for y in range(150):
        for x in range(100):
            if (x + y) % 2 == 0:
                img.putpixel((x, y), (255, 255, 255))

    energy = analyze_spatial_distribution(img)

    assert energy["left"] > energy["center"]
    assert energy["left"] > energy["right"]
    assert energy["left"] > 0.60


def test_analyze_dialogue_exchanges_turn_counting():
    """Verify counting and average duration calculation of conversational dialogue turns."""
    segments = [
        {"start": 10.0, "end": 13.5, "text": "Are you serious right now?"},
        {"start": 14.0, "end": 16.5, "text": "Dead serious, look at this."},
        {"start": 17.0, "end": 19.5, "text": "No way, that makes no sense."},
        {"start": 20.0, "end": 22.0, "text": "Believe what you want."},
    ]

    turns, avg_turn = analyze_dialogue_exchanges(segments, start_time=10.0, end_time=22.0)

    assert turns == 4
    assert pytest.approx(avg_turn, rel=0.05) == 3.0


def test_recommend_split_stack_for_dense_dialogue_banter():
    """Verify that high conversational turn-taking triggers the split_stack recommendation."""
    analyzer = FramingAnalyzer(target_resolution="4k")
    highlight = CandidateHighlight(
        title="Heated Kitchen Argument",
        raw_start=50.0,
        raw_end=70.0,
        score=95,
        archetype=HighlightArchetype.DIALOGUE_BANTER,
        hook_sentence="Wait until you hear what he said.",
    )
    segments = [
        {"start": 50.5, "end": 53.0, "text": "Turn 1"},
        {"start": 53.2, "end": 56.0, "text": "Turn 2"},
        {"start": 56.5, "end": 60.0, "text": "Turn 3"},
        {"start": 60.5, "end": 64.0, "text": "Turn 4"},
        {"start": 64.5, "end": 69.0, "text": "Turn 5"},
    ]

    rec = analyzer.recommend_framing(highlight, transcript_segments=segments)

    assert rec.mode == FramingMode.SPLIT_STACK.value
    assert rec.confidence >= 0.90
    assert "sub_h_ratio" in rec.params
    assert "x_top" in rec.params
    assert "x_bot" in rec.params
    assert rec.params["margin_v"] == 940


def test_recommend_smart_focus_for_action_heist():
    """Verify that action scenes default to smart_focus framing with rule-of-thirds parameters."""
    analyzer = FramingAnalyzer(target_resolution="1080p")
    highlight = CandidateHighlight(
        title="High Speed Motorcycle Chase",
        raw_start=120.0,
        raw_end=150.0,
        score=90,
        archetype=HighlightArchetype.ACTION_HEIST,
    )

    rec = analyzer.recommend_framing(highlight)

    assert rec.mode == FramingMode.SMART_FOCUS.value
    assert rec.confidence >= 0.80
    assert "x_ratio" in rec.params
    assert rec.params["margin_v"] == 260


def test_recommend_center_for_stunt_fail():
    """Verify that physics stunts and fail clips are framed centered for impact."""
    analyzer = FramingAnalyzer(target_resolution="4k")
    highlight = CandidateHighlight(
        title="Skateboard Rail Catastrophe",
        raw_start=30.0,
        raw_end=45.0,
        score=88,
        archetype=HighlightArchetype.STUNT_FAIL,
    )

    rec = analyzer.recommend_framing(highlight)

    assert rec.mode == FramingMode.CENTER.value
    assert rec.confidence >= 0.85


def test_recommend_fit_blur_for_panoramic_lore():
    """Verify that wide lore scenes with low center energy receive fit_blur canvas framing."""
    analyzer = FramingAnalyzer(target_resolution="4k")
    highlight = CandidateHighlight(
        title="Ancient Castle Architecture Secret",
        raw_start=200.0,
        raw_end=230.0,
        score=82,
        archetype=HighlightArchetype.LORE_BACKSTORY,
    )
    img = Image.new("RGB", (300, 150), color=(20, 20, 20))
    for y in range(150):
        for x in list(range(30)) + list(range(270, 300)):
            img.putpixel((x, y), (240, 240, 240))

    rec = analyzer.recommend_framing(highlight, keyframe=img)

    assert rec.mode == FramingMode.FIT_BLUR.value
    assert rec.confidence >= 0.80


def test_recommend_framing_with_letterbox_stripping():
    """Verify that letterboxed footage forces smart_focus with strip_letterbox active height."""
    analyzer = FramingAnalyzer(target_resolution="4k")
    highlight = CandidateHighlight(
        title="Cinematic Drama Clip",
        raw_start=10.0,
        raw_end=35.0,
        score=85,
        archetype=HighlightArchetype.SATIRE_COMMERCIAL,
    )
    img = Image.new("RGB", (1920, 1080), color=(0, 0, 0))
    active = Image.new("RGB", (1920, 800), color=(120, 130, 140))
    img.paste(active, (0, 140))

    rec = analyzer.recommend_framing(highlight, keyframe=img, source_dimensions=(1920, 1080))

    assert rec.mode == FramingMode.SMART_FOCUS.value
    assert rec.params.get("strip_letterbox") is True
    assert rec.params.get("active_h") == pytest.approx(800, abs=10)
    assert rec.params.get("y_offset") == pytest.approx(140, abs=10)


def test_recommend_framing_empty_segments_edge_case():
    """Verify graceful fallback when transcript segments list is empty."""
    analyzer = FramingAnalyzer()
    highlight = CandidateHighlight(
        title="Silent Scene",
        raw_start=0.0,
        raw_end=15.0,
        score=70,
        archetype=HighlightArchetype.DIALOGUE_BANTER,
    )

    rec = analyzer.recommend_framing(highlight, transcript_segments=[])

    assert rec.mode in (FramingMode.SMART_FOCUS.value, FramingMode.CENTER.value)
    assert rec.confidence > 0.0
