"""Triad unit tests for dynamic viral zoom planning and mathematical easing filtergraphs."""

import subprocess
import pytest

from shorts_generator.diversity_types import (
    CandidateHighlight,
    HighlightArchetype,
    WhisperWord,
    ZoomEventType,
    ZoomPlan,
)
from shorts_generator.local.clipper import build_ffmpeg_filtergraph
from shorts_generator.viral_zoom_analyzer import (
    ViralZoomAnalyzer,
    find_hook_window,
    find_impact_moments,
)


def test_find_hook_window_with_terminal_punctuation():
    """Verify that the hook window terminates at the end of the opening sentence."""
    words = [
        WhisperWord(word="You", start=10.0, end=10.3),
        WhisperWord(word="won't", start=10.3, end=10.6),
        WhisperWord(word="believe", start=10.6, end=11.1),
        WhisperWord(word="this!", start=11.1, end=11.8),
        WhisperWord(word="Look", start=12.0, end=12.4),
        WhisperWord(word="here.", start=12.4, end=12.9),
    ]

    rel_s, rel_e = find_hook_window(words, clip_start=10.0, max_hook_duration=3.0)

    assert rel_s == 0.0
    assert pytest.approx(rel_e, abs=0.05) == 1.8


def test_find_hook_window_empty_words():
    """Verify default fallback hook window when no word-level timings are provided."""
    rel_s, rel_e = find_hook_window([], clip_start=0.0, max_hook_duration=2.5)

    assert rel_s == 0.0
    assert rel_e == 2.5


def test_find_impact_moments_with_exclamations():
    """Verify detection of punchlines marked by exclamations with proper separation."""
    words = [
        WhisperWord(word="Opening", start=0.0, end=0.8),
        WhisperWord(word="sentence.", start=0.8, end=1.5),
        WhisperWord(word="And", start=5.0, end=5.2),
        WhisperWord(word="then", start=5.2, end=5.5),
        WhisperWord(word="BOOM!", start=5.5, end=6.0),
        WhisperWord(word="It", start=6.1, end=6.3),
        WhisperWord(word="EXPLODED!", start=6.3, end=6.8),
        WhisperWord(word="Ten", start=12.0, end=12.3),
        WhisperWord(word="seconds", start=12.3, end=12.6),
        WhisperWord(word="later!", start=12.6, end=13.0),
    ]

    impacts = find_impact_moments(words, clip_start=0.0, clip_end=20.0, hook_end_rel=2.0)

    assert len(impacts) >= 2
    first_imp = impacts[0]
    assert first_imp[0] <= 5.5 and first_imp[1] >= 6.5
    second_imp = impacts[1]
    assert second_imp[0] >= 11.5


def test_plan_zooms_generates_hook_and_impact_events():
    """Verify that a candidate highlight receives both hook punch and impact zoom events."""
    analyzer = ViralZoomAnalyzer()
    highlight = CandidateHighlight(
        title="Dramatic Heist Escape",
        raw_start=100.0,
        raw_end=125.0,
        score=94,
        archetype=HighlightArchetype.ACTION_HEIST,
    )
    words = [
        WhisperWord(word="Stop", start=100.0, end=100.4),
        WhisperWord(word="right", start=100.4, end=100.8),
        WhisperWord(word="now!", start=100.8, end=101.5),
        WhisperWord(word="They", start=108.0, end=108.3),
        WhisperWord(word="found", start=108.3, end=108.6),
        WhisperWord(word="us!", start=108.6, end=109.2),
    ]

    plan = analyzer.plan_zooms(highlight, words=words)

    assert len(plan.events) == 2
    assert plan.events[0].event_type == ZoomEventType.HOOK_PUNCH
    assert plan.events[0].target_zoom == pytest.approx(1.15)
    assert plan.events[1].event_type == ZoomEventType.IMPACT_PUNCH
    assert plan.events[1].target_zoom == pytest.approx(1.24)


def test_plan_zooms_tension_creep_on_long_lore():
    """Verify that long lore clips receive slow tension creep."""
    analyzer = ViralZoomAnalyzer()
    highlight = CandidateHighlight(
        title="Secret Hidden Room Easter Egg",
        raw_start=50.0,
        raw_end=75.0,
        score=84,
        archetype=HighlightArchetype.LORE_BACKSTORY,
    )

    plan = analyzer.plan_zooms(highlight, words=[])

    creep_events = [e for e in plan.events if e.event_type == ZoomEventType.TENSION_CREEP]
    assert len(creep_events) == 1
    assert creep_events[0].target_zoom == pytest.approx(1.16)
    assert creep_events[0].ease_in_sec >= 2.0


def test_build_zoom_expression_syntax():
    """Verify that the generated zoom expression is syntactically well-formed."""
    analyzer = ViralZoomAnalyzer()
    highlight = CandidateHighlight(
        title="Sample Moment",
        raw_start=0.0,
        raw_end=15.0,
        score=80,
    )
    plan = analyzer.plan_zooms(highlight)

    expr = ViralZoomAnalyzer.build_zoom_expression(plan)

    assert expr.startswith("(1.0+")
    assert "min(max((t-" in expr
    assert "*min(" in expr


def test_build_crop_filter_with_zoom_stationary_fallback():
    """Verify that an empty zoom plan produces standard static crop filter syntax."""
    empty_plan = ZoomPlan(events=[])

    filter_str = ViralZoomAnalyzer.build_crop_filter_with_zoom(
        base_w=1215,
        base_h=2160,
        base_x=1312,
        base_y=0,
        zoom_plan=empty_plan,
    )

    assert filter_str == "crop=1215:2160:1312:0"


def test_build_crop_filter_with_dynamic_zoom():
    """Verify that active zoom events produce parameterized crop expressions with exact=1."""
    analyzer = ViralZoomAnalyzer()
    highlight = CandidateHighlight(
        title="Sample Moment",
        raw_start=0.0,
        raw_end=15.0,
        score=80,
    )
    plan = analyzer.plan_zooms(highlight)

    filter_str = ViralZoomAnalyzer.build_crop_filter_with_zoom(
        base_w=1215,
        base_h=2160,
        base_x=1312,
        base_y=0,
        zoom_plan=plan,
        focal_x=0.5,
        focal_y=0.45,
    )

    assert filter_str.startswith("crop=w='1215/(1.0+")
    assert "h='2160/(1.0+" in filter_str
    assert "x='1312+(1215-1215/(1.0+" in filter_str
    assert "exact=1" in filter_str


def test_build_ffmpeg_filtergraph_with_zoom_plan():
    """Verify that clipper build_ffmpeg_filtergraph integrates dynamic zoom plans cleanly."""
    analyzer = ViralZoomAnalyzer()
    highlight = CandidateHighlight(
        title="Test Clip",
        raw_start=0.0,
        raw_end=10.0,
        score=90,
    )
    plan = analyzer.plan_zooms(highlight)

    filtergraph = build_ffmpeg_filtergraph(
        src_w=3840,
        src_h=2160,
        framing="smart_focus",
        resolution="4k",
        framing_params={"zoom_plan": plan, "x_ratio": 0.33},
    )

    assert "crop=w=" in filtergraph
    assert "scale=2160:3840:flags=lanczos" in filtergraph
    assert "format=nv12" in filtergraph


def test_ffmpeg_execution_with_generated_filter():
    """Verify that FFmpeg actually parses and executes the generated zoom filter without error."""
    analyzer = ViralZoomAnalyzer()
    highlight = CandidateHighlight(
        title="Execution Test",
        raw_start=0.0,
        raw_end=2.0,
        score=90,
    )
    plan = analyzer.plan_zooms(highlight)

    crop_filter = ViralZoomAnalyzer.build_crop_filter_with_zoom(
        base_w=360,
        base_h=640,
        base_x=140,
        base_y=0,
        zoom_plan=plan,
    )
    vf_string = f"{crop_filter},scale=540:960"

    cmd = [
        "ffmpeg", "-v", "error",
        "-f", "lavfi",
        "-i", "testsrc=duration=1:size=640x640:rate=10",
        "-vf", vf_string,
        "-t", "0.5",
        "-f", "null", "-"
    ]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    assert res.returncode == 0
    assert res.stderr.strip() == ""
