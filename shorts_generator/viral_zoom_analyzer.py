"""Dynamic viral zoom analysis and automated impact punch scheduler for vertical video.

Detects high-retention moments (hook punches, punchlines, emotional spikes, tension creeps)
and compiles mathematical easing expressions for FFmpeg hardware-accelerated rendering.
"""

from typing import Any, Dict, List, Optional, Tuple
from .diversity_types import (
    CandidateHighlight,
    HighlightArchetype,
    WhisperWord,
    ZoomEvent,
    ZoomEventType,
    ZoomPlan,
)


def find_hook_window(
    words: List[WhisperWord],
    clip_start: float,
    max_hook_duration: float = 2.8,
) -> Tuple[float, float]:
    """Calculate the relative start and end timestamps for the initial hook window.

    Args:
        words: Microsecond-precision Whisper word events.
        clip_start: Absolute start timestamp of the clip in seconds.
        max_hook_duration: Maximum allowed hook punch duration in seconds.

    Returns:
        Tuple of (relative_start_sec, relative_end_sec).
    """
    rel_start = 0.0
    rel_end = min(2.5, max_hook_duration)

    if words:
        first_sentence_words: List[WhisperWord] = []
        for w in words:
            if w.start < clip_start:
                continue
            first_sentence_words.append(w)
            if w.has_terminal_punct or (w.end - clip_start) >= max_hook_duration:
                break

        if first_sentence_words:
            dur = first_sentence_words[-1].end - clip_start
            rel_end = max(1.2, min(dur, max_hook_duration))

    return rel_start, rel_end


def find_impact_moments(
    words: List[WhisperWord],
    clip_start: float,
    clip_end: float,
    hook_end_rel: float,
) -> List[Tuple[float, float, str]]:
    """Scan transcript words to locate punchline climaxes and exclamations.

    Args:
        words: Microsecond-precision Whisper word events.
        clip_start: Absolute start timestamp of the clip in seconds.
        clip_end: Absolute end timestamp of the clip in seconds.
        hook_end_rel: Relative end timestamp of the hook punch to prevent overlap.

    Returns:
        List of tuples: (relative_start_sec, relative_end_sec, trigger_word).
    """
    impacts: List[Tuple[float, float, str]] = []
    min_separation_sec = 4.0

    for w in words:
        if w.start < clip_start or w.end > clip_end:
            continue
        rel_w_start = max(0.0, w.start - clip_start)
        rel_w_end = max(rel_w_start + 0.1, w.end - clip_start)

        if rel_w_start <= (hook_end_rel + 0.5):
            continue

        is_exclamation = "!" in w.word or "?" in w.word
        is_shout = w.clean_word.isupper() and len(w.clean_word) > 2
        is_high_conf_peak = is_exclamation or is_shout

        if is_high_conf_peak:
            impact_start = max(0.0, rel_w_start - 0.2)
            impact_end = min(clip_end - clip_start, rel_w_end + 1.2)
            if impact_end - impact_start < 1.4:
                impact_end = min(clip_end - clip_start, impact_start + 1.6)

            if not impacts:
                impacts.append((impact_start, impact_end, w.clean_word))
            else:
                last_end = impacts[-1][1]
                if impact_start >= (last_end + min_separation_sec):
                    impacts.append((impact_start, impact_end, w.clean_word))

    return impacts


class ViralZoomAnalyzer:
    """Automated planner for visual punctuation and audience retention zoom dynamics."""

    def __init__(
        self,
        enable_hook_punch: bool = True,
        enable_impact_punch: bool = True,
        enable_tension_creep: bool = True,
    ) -> None:
        """Initialize ViralZoomAnalyzer with configuration toggles.

        Args:
            enable_hook_punch: Whether to schedule opening 0-3s hook zoom-in.
            enable_impact_punch: Whether to schedule climax punchline impact zooms.
            enable_tension_creep: Whether to schedule subtle narrative tension zooms.
        """
        self.enable_hook_punch = enable_hook_punch
        self.enable_impact_punch = enable_impact_punch
        self.enable_tension_creep = enable_tension_creep

    def plan_zooms(
        self,
        highlight: CandidateHighlight,
        words: Optional[List[WhisperWord]] = None,
    ) -> ZoomPlan:
        """Generate a complete chronological schedule of dynamic zoom events for a clip.

        Args:
            highlight: Candidate highlight with archetype, score, and timestamps.
            words: Optional word-level timing events for precise acoustic synchronization.

        Returns:
            ZoomPlan containing ordered ZoomEvents.
        """
        clip_start = highlight.snapped_start if highlight.is_snapped else highlight.raw_start
        clip_end = highlight.snapped_end if highlight.is_snapped else highlight.raw_end
        duration = max(1.0, clip_end - clip_start)

        events: List[ZoomEvent] = []
        hook_end_rel = 0.0

        if self.enable_hook_punch and duration >= 5.0:
            h_start, h_end = find_hook_window(words or [], clip_start)
            hook_end_rel = h_end
            events.append(
                ZoomEvent(
                    event_type=ZoomEventType.HOOK_PUNCH,
                    start_time=h_start,
                    end_time=h_end,
                    target_zoom=1.15,
                    focal_x=0.5,
                    focal_y=0.45,
                    ease_in_sec=0.25,
                    ease_out_sec=0.35,
                )
            )

        impacts: List[Tuple[float, float, str]] = []
        if self.enable_impact_punch and duration >= 10.0 and words:
            impacts = find_impact_moments(words, clip_start, clip_end, hook_end_rel)
            for imp_start, imp_end, _ in impacts[:2]:
                events.append(
                    ZoomEvent(
                        event_type=ZoomEventType.IMPACT_PUNCH,
                        start_time=imp_start,
                        end_time=imp_end,
                        target_zoom=1.24,
                        focal_x=0.5,
                        focal_y=0.40,
                        ease_in_sec=0.15,
                        ease_out_sec=0.30,
                    )
                )

        if self.enable_tension_creep and duration >= 12.0 and not impacts:
            if highlight.archetype in (HighlightArchetype.LORE_BACKSTORY, HighlightArchetype.ACTION_HEIST):
                start_creep = max(3.0, hook_end_rel + 0.5)
                end_creep = duration - 1.0
                if end_creep - start_creep >= 6.0:
                    events.append(
                        ZoomEvent(
                            event_type=ZoomEventType.TENSION_CREEP,
                            start_time=start_creep,
                            end_time=end_creep,
                            target_zoom=1.16,
                            focal_x=0.5,
                            focal_y=0.5,
                            ease_in_sec=2.5,
                            ease_out_sec=0.5,
                        )
                    )

        events.sort(key=lambda ev: ev.start_time)
        return ZoomPlan(events=events, base_zoom=1.0)

    @staticmethod
    def build_zoom_expression(zoom_plan: Optional[ZoomPlan]) -> str:
        """Compile a ZoomPlan into an FFmpeg mathematical time expression for zoom factor Z(t).

        Args:
            zoom_plan: ZoomPlan containing scheduled events.

        Returns:
            FFmpeg mathematical expression string representing instantaneous zoom factor Z(t).
        """
        if not zoom_plan or not zoom_plan.events:
            return "1.0"

        terms: List[str] = []
        for ev in zoom_plan.events:
            delta = ev.target_zoom - 1.0
            st = ev.start_time
            et = ev.end_time
            din = max(0.01, ev.ease_in_sec)
            dout = max(0.01, ev.ease_out_sec)
            term = (
                f"({delta:.3f}*min(max((t-{st:.3f})/{din:.3f},0),"
                f"min(max(({et:.3f}-t)/{dout:.3f},0),1)))"
            )
            terms.append(term)

        if not terms:
            return "1.0"

        combined = "+".join(terms)
        return f"(1.0+{combined})"

    @staticmethod
    def build_crop_filter_with_zoom(
        base_w: int,
        base_h: int,
        base_x: int,
        base_y: int,
        zoom_plan: Optional[ZoomPlan] = None,
        focal_x: float = 0.5,
        focal_y: float = 0.5,
    ) -> str:
        """Construct an FFmpeg crop filter string with continuous dynamic zoom.

        Args:
            base_w: Stationary baseline crop width in pixels.
            base_h: Stationary baseline crop height in pixels.
            base_x: Stationary baseline crop X position in pixels.
            base_y: Stationary baseline crop Y position in pixels.
            zoom_plan: Optional dynamic zoom schedule.
            focal_x: Normalized horizontal focal center point (0.0=left, 0.5=center, 1.0=right).
            focal_y: Normalized vertical focal center point (0.0=top, 0.5=center, 1.0=bottom).

        Returns:
            FFmpeg crop filter string.
        """
        if not zoom_plan or not zoom_plan.events:
            return f"crop={base_w}:{base_h}:{base_x}:{base_y}"

        z_expr = ViralZoomAnalyzer.build_zoom_expression(zoom_plan)
        crop_w_expr = f"{base_w}/{z_expr}"
        crop_h_expr = f"{base_h}/{z_expr}"
        crop_x_expr = f"{base_x}+({base_w}-{base_w}/{z_expr})*{focal_x:.3f}"
        crop_y_expr = f"{base_y}+({base_h}-{base_h}/{z_expr})*{focal_y:.3f}"

        return f"crop=w='{crop_w_expr}':h='{crop_h_expr}':x='{crop_x_expr}':y='{crop_y_expr}':exact=1"
