"""Data contracts and schemas for video diversity, archetype management, and stateful persistence.

Enforces strict typing and structured representations for:
- 5-Tier narrative archetypes.
- Microsecond-precision Whisper word events.
- Boundary-snapped candidate highlights.
- Dynamic framing modes and intelligent recommendations.
- Timeline-based viral zoom events and plans.
- Persistent registry clip records.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class HighlightArchetype(str, Enum):
    """Canonical narrative archetypes for short-form video diversity."""
    SATIRE_COMMERCIAL = "SATIRE_COMMERCIAL"
    DIALOGUE_BANTER = "DIALOGUE_BANTER"
    ACTION_HEIST = "ACTION_HEIST"
    LORE_BACKSTORY = "LORE_BACKSTORY"
    STUNT_FAIL = "STUNT_FAIL"

    @classmethod
    def from_string(cls, raw: str) -> "HighlightArchetype":
        """Normalize raw string to a valid HighlightArchetype.

        Args:
            raw: Raw input string from LLM response.

        Returns:
            Normalized HighlightArchetype enum value.
        """
        clean = (raw or "").strip().upper().replace(" ", "_").replace("-", "_")
        for member in cls:
            if member.value == clean or member.name == clean:
                return member
            if clean in member.value or member.value in clean:
                return member
        return cls.DIALOGUE_BANTER


class FramingMode(str, Enum):
    """Supported spatial reframing strategies for vertical short video generation."""
    SPLIT_STACK = "split_stack"
    SMART_FOCUS = "smart_focus"
    CENTER = "center"
    LEFT_FOCUS = "left_focus"
    RIGHT_FOCUS = "right_focus"
    FIT_BLUR = "fit_blur"
    ZOOM_BLUR = "zoom_blur"


@dataclass
class FramingRecommendation:
    """Automated recommendation for scene framing mode and spatial parameters.

    Attributes:
        mode: Selected FramingMode identifier string.
        confidence: Prediction confidence score between 0.0 and 1.0.
        reason: Diagnostic explanation of why this framing mode was chosen.
        params: Dictionary of fine-tuned spatial coordinates, crops, and offsets.
    """
    mode: str
    confidence: float
    reason: str
    params: Dict[str, Any] = field(default_factory=dict)


class ZoomEventType(str, Enum):
    """Taxonomy of dynamic zoom events for visual punctuation and audience retention."""
    HOOK_PUNCH = "hook_punch"
    IMPACT_PUNCH = "impact_punch"
    TENSION_CREEP = "tension_creep"
    FOCAL_HOLD = "focal_hold"


@dataclass
class ZoomEvent:
    """A scheduled dynamic zoom transformation window.

    Attributes:
        event_type: Category of zoom event.
        start_time: Clip-relative start timestamp in seconds.
        end_time: Clip-relative end timestamp in seconds.
        target_zoom: Maximum zoom magnification factor (e.g. 1.25 for 1.25x).
        focal_x: Normalized horizontal focal anchor point (0.0=left, 0.5=center, 1.0=right).
        focal_y: Normalized vertical focal anchor point (0.0=top, 0.5=center, 1.0=bottom).
        ease_in_sec: Duration in seconds to ramp up zoom factor.
        ease_out_sec: Duration in seconds to ramp down zoom factor back to baseline.
    """
    event_type: ZoomEventType
    start_time: float
    end_time: float
    target_zoom: float
    focal_x: float = 0.5
    focal_y: float = 0.5
    ease_in_sec: float = 0.3
    ease_out_sec: float = 0.4


@dataclass
class ZoomPlan:
    """Complete temporal schedule of dynamic zoom transformations for a clip.

    Attributes:
        events: Chronologically ordered list of zoom events.
        base_zoom: Base stationary zoom factor (defaults to 1.0).
    """
    events: List[ZoomEvent] = field(default_factory=list)
    base_zoom: float = 1.0


@dataclass(frozen=True)
class WhisperWord:
    """Microsecond-precision word event from faster-whisper.

    Attributes:
        word: Transcribed word text.
        start: Start timestamp in seconds.
        end: End timestamp in seconds.
        probability: Model confidence score (0.0 to 1.0).
    """
    word: str
    start: float
    end: float
    probability: float = 1.0

    @property
    def clean_word(self) -> str:
        """Return word stripped of punctuation and leading/trailing whitespace.

        Returns:
            Clean word string.
        """
        return self.word.strip().strip("\"'()[]{}.,!?:;—-\u0964")

    @property
    def has_terminal_punct(self) -> bool:
        """Check if word ends with sentence-terminal punctuation.

        Returns:
            True if word ends with period, exclamation, question, or ellipsis.
        """
        return any(self.word.rstrip().endswith(p) for p in (".", "!", "?", "...", "\u0964"))

    @property
    def has_clause_punct(self) -> bool:
        """Check if word ends with clause-level punctuation.

        Returns:
            True if word ends with comma, semicolon, colon, or dash.
        """
        return any(self.word.rstrip().endswith(p) for p in (",", ";", ":", "-", "—"))


@dataclass
class CandidateHighlight:
    """Represents a highlight candidate before and after boundary snapping.

    Attributes:
        title: Descriptive title of the moment.
        raw_start: Un-snapped raw start timestamp from LLM.
        raw_end: Un-snapped raw end timestamp from LLM.
        score: Viral rating score (0 to 100).
        archetype: Thematic editorial category.
        hook_sentence: Opening curiosity sentence.
        virality_reason: Explanation of virality driver.
        snapped_start: Acoustically snapped start timestamp.
        snapped_end: Acoustically snapped end timestamp.
        is_snapped: Whether boundary snapping has occurred.
        framing: Recommended or user-specified framing mode string.
        framing_params: Spatial coordinates, offsets, and ratios for reframing.
        zoom_plan: Dynamic zoom timeline schedule.
    """
    title: str
    raw_start: float
    raw_end: float
    score: int
    archetype: HighlightArchetype = HighlightArchetype.DIALOGUE_BANTER
    hook_sentence: str = ""
    virality_reason: str = ""
    snapped_start: float = 0.0
    snapped_end: float = 0.0
    is_snapped: bool = False
    framing: Optional[str] = None
    framing_params: Optional[Dict[str, Any]] = None
    zoom_plan: Optional[ZoomPlan] = None

    @property
    def duration(self) -> float:
        """Calculate effective duration in seconds.

        Returns:
            Duration in seconds.
        """
        if self.is_snapped:
            return max(0.0, self.snapped_end - self.snapped_start)
        return max(0.0, self.raw_end - self.raw_start)


@dataclass
class ClipRecord:
    """Persistent metadata record of an extracted clip stored in registry.

    Attributes:
        clip_id: Unique deterministic identifier.
        seq: Monotonic sequence index.
        start_time: Start timestamp in seconds.
        end_time: End timestamp in seconds.
        exclusion_zone: Temporal tuple of (exclusion_start, exclusion_end).
        archetype: Assigned narrative archetype.
        score: Virality rating score.
        title: Clip title.
        hook_sentence: Opening hook line.
        file_path: Relative or absolute destination media path.
        created_at: ISO-8601 UTC timestamp.
        status: Current pipeline lifecycle status.
    """
    clip_id: str
    seq: int
    start_time: float
    end_time: float
    exclusion_zone: Tuple[float, float]
    archetype: str
    score: int
    title: str
    hook_sentence: str
    file_path: str
    created_at: str
    status: str = "rendered"
