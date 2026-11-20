"""Whisper microsecond audio and sentence boundary snapping engine.

Snaps coarse LLM timestamps to natural silence gaps and sentence boundaries,
preventing phoneme mutilation, mid-syllable clipping, and unresolved dialogue endings.
"""

from typing import List, Optional, Tuple

from .diversity_types import CandidateHighlight, WhisperWord


class AudioBoundarySnapper:
    """Acoustic and syntactic boundary optimizer for video highlights."""

    def __init__(
        self,
        words: List[WhisperWord],
        min_silence_gap: float = 0.250,
        max_search_window: float = 3.500,
        lead_in_pad: float = 0.080,
        tail_ring_out: float = 0.150,
        min_duration: float = 20.0,
        max_duration: float = 90.0,
    ):
        """Initialize boundary snapper with word events and timing parameters.

        Args:
            words: Ordered list of WhisperWord events.
            min_silence_gap: Minimum inter-word pause in seconds considered silence.
            max_search_window: Maximum search horizon around coarse timestamps.
            lead_in_pad: Audio pre-roll buffer in seconds before first spoken word.
            tail_ring_out: Audio room decay buffer in seconds after last spoken word.
            min_duration: Minimum allowed clip duration in seconds.
            max_duration: Maximum allowed clip duration in seconds.
        """
        self.words = sorted(words, key=lambda w: w.start)
        self.min_silence_gap = min_silence_gap
        self.max_search_window = max_search_window
        self.lead_in_pad = lead_in_pad
        self.tail_ring_out = tail_ring_out
        self.min_duration = min_duration
        self.max_duration = max_duration

    def snap_start_boundary(self, raw_start: float) -> float:
        """Snap coarse start timestamp to nearest preceding silence or sentence start.

        Args:
            raw_start: Coarse start timestamp in seconds from LLM.

        Returns:
            Acoustically aligned start timestamp in seconds.
        """
        if not self.words:
            return max(0.0, raw_start)

        window_start = max(0.0, raw_start - self.max_search_window)
        window_end = raw_start + self.max_search_window
        candidates: List[Tuple[float, float]] = []

        for i, w in enumerate(self.words):
            if w.start < window_start:
                continue
            if w.start > window_end:
                break

            prev_w = self.words[i - 1] if i > 0 else None
            gap = (w.start - prev_w.end) if prev_w else 1.0

            dist_cost = abs(w.start - raw_start)
            terminal_bonus = 3.0 if (prev_w and prev_w.has_terminal_punct) else 0.0
            clause_bonus = 1.5 if (prev_w and prev_w.has_clause_punct) else 0.0
            gap_bonus = 2.5 if gap >= self.min_silence_gap else 0.0
            gap_magnitude = min(max(0.0, gap), 1.0) * 1.5

            total_cost = dist_cost - terminal_bonus - clause_bonus - gap_bonus - gap_magnitude
            safe_lead = min(self.lead_in_pad, (gap / 2.0) if prev_w else self.lead_in_pad)
            snapped_time = max(0.0, w.start - safe_lead)
            candidates.append((total_cost, snapped_time))

        if not candidates:
            return max(0.0, raw_start)

        candidates.sort(key=lambda x: x[0])
        return candidates[0][1]

    def snap_end_boundary(self, raw_end: float) -> float:
        """Snap coarse end timestamp to complete sentence ending followed by silence.

        Args:
            raw_end: Coarse end timestamp in seconds from LLM.

        Returns:
            Acoustically aligned end timestamp in seconds.
        """
        if not self.words:
            return raw_end

        window_start = max(0.0, raw_end - self.max_search_window)
        window_end = raw_end + self.max_search_window
        candidates: List[Tuple[float, float]] = []

        for i, w in enumerate(self.words):
            if w.end < window_start:
                continue
            if w.end > window_end:
                break

            next_w = self.words[i + 1] if i + 1 < len(self.words) else None
            gap = (next_w.start - w.end) if next_w else 1.0

            dist_cost = abs(w.end - raw_end)
            terminal_bonus = 4.0 if w.has_terminal_punct else 0.0
            clause_bonus = 1.0 if w.has_clause_punct else 0.0
            gap_bonus = 2.5 if gap >= self.min_silence_gap else 0.0
            gap_magnitude = min(max(0.0, gap), 1.0) * 1.5

            total_cost = dist_cost - terminal_bonus - clause_bonus - gap_bonus - gap_magnitude
            safe_tail = min(self.tail_ring_out, (gap / 2.0) if next_w else self.tail_ring_out)
            snapped_time = w.end + safe_tail
            candidates.append((total_cost, snapped_time))

        if not candidates:
            return raw_end

        candidates.sort(key=lambda x: x[0])
        return candidates[0][1]

    def snap_highlight(self, highlight: CandidateHighlight) -> CandidateHighlight:
        """Perform end-to-end snapping and enforce valid duration bounds.

        Args:
            highlight: CandidateHighlight object to optimize.

        Returns:
            Updated CandidateHighlight with snapped start and end timestamps.
        """
        s = self.snap_start_boundary(highlight.raw_start)
        e = self.snap_end_boundary(highlight.raw_end)

        dur = e - s
        if dur < self.min_duration:
            e = s + self.min_duration
        elif dur > self.max_duration:
            e = s + self.max_duration

        highlight.snapped_start = round(s, 3)
        highlight.snapped_end = round(e, 3)
        highlight.is_snapped = True
        return highlight
