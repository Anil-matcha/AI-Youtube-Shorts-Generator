"""Algorithmic highlight extraction and boundary snapping for Episode 3.

Evaluates candidate moments against the 5 narrative archetypes,
applies AudioBoundarySnapper for speech pause alignment,
and validates temporal separation via GuardedTNMSDiversityEngine.
"""

import json
from pathlib import Path
from typing import Dict, List

from shorts_generator.boundary_snapper import AudioBoundarySnapper
from shorts_generator.diversity_types import (
    CandidateHighlight,
    HighlightArchetype,
    WhisperWord,
)
from shorts_generator.tnms_engine import GuardedTNMSDiversityEngine

TRANSCRIPT_PATH = Path("output/raw/captions/ep3_transcript.json")


def load_transcript_words() -> List[WhisperWord]:
    """Extract ordered WhisperWord objects from the saved transcript.

    Returns:
        List of WhisperWord events.
    """
    with open(TRANSCRIPT_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    words: List[WhisperWord] = []
    for seg in data.get("segments", []):
        for w in seg.get("words", []):
            words.append(
                WhisperWord(
                    word=w["word"],
                    start=float(w["start"]),
                    end=float(w["end"]),
                    probability=float(w.get("probability", 1.0)),
                )
            )
    return sorted(words, key=lambda x: x.start)


def build_candidate_highlights() -> List[CandidateHighlight]:
    """Define curated viral highlight candidates covering all 5 narrative archetypes.

    Returns:
        List of CandidateHighlight instances before acoustic snapping.
    """
    candidates = [
        CandidateHighlight(
            title="Mandy: It's Not Stalking If We Met In Person!",
            raw_start=565.0,
            raw_end=601.0,
            score=98,
            archetype=HighlightArchetype.DIALOGUE_BANTER,
            hook_sentence="I think that's called stalking Mandy. No it's not stalking if you've met in person!",
            virality_reason="Hilarious psycho-stalker ex-girlfriend dialogue and marriage demand.",
        ),
        CandidateHighlight(
            title="GTA 6 Satire: King Gator Adventure Golf Commercial",
            raw_start=2888.0,
            raw_end=2935.0,
            score=96,
            archetype=HighlightArchetype.SATIRE_COMMERCIAL,
            hook_sentence="Look at all them holes ready to be filled by your sweet sweet balls at King Gator!",
            virality_reason="Rockstar's unhinged in-game satire golf commercial with swamp gator humor.",
        ),
        CandidateHighlight(
            title="Bhai Ne Bola Marne Ka: Turf War Execution Confrontation",
            raw_start=1270.0,
            raw_end=1328.0,
            score=97,
            archetype=HighlightArchetype.ACTION_HEIST,
            hook_sentence="We didn't start the turf war, we ended it! Ask to speak to my manager!",
            virality_reason="Title namesake scene where Jason and Brian confront Arnold with extreme tension.",
        ),
        CandidateHighlight(
            title="Mr. Garcia Lawyer Ad: Sued Surgeon After BBL Disaster",
            raw_start=2766.0,
            raw_end=2818.0,
            score=95,
            archetype=HighlightArchetype.SATIRE_COMMERCIAL,
            hook_sentence="I went for a BBL and my ass came out hurting, so Mr. Garcia got me payback!",
            virality_reason="Satirical personal injury lawyer TV ad parodying Miami plastic surgery culture.",
        ),
        CandidateHighlight(
            title="Treasure Hunter Kenny: What 100-Year-Old Gold Feels Like",
            raw_start=1930.0,
            raw_end=1961.0,
            score=92,
            archetype=HighlightArchetype.LORE_BACKSTORY,
            hook_sentence="When you hold hundreds-of-years-old gold in the middle of the ocean, you know how rich you are.",
            virality_reason="Mysterious underwater shipwreck lore setting up the ocean treasure mechanics.",
        ),
        CandidateHighlight(
            title="Scuba Diving Disaster: Drunk Bachelor Party & Death Waiver",
            raw_start=3336.0,
            raw_end=3386.0,
            score=95,
            archetype=HighlightArchetype.STUNT_FAIL,
            hook_sentence="Don't people need to train for scuba diving? This guy skips all that bullshit, sign the waiver!",
            virality_reason="Chaotic comedy of drunk tourists going deep-sea diving without training.",
        ),
        CandidateHighlight(
            title="Boat License Chaos: Bro Do You Even Know How To Drive?!",
            raw_start=3411.0,
            raw_end=3452.0,
            score=93,
            archetype=HighlightArchetype.STUNT_FAIL,
            hook_sentence="Bro do you even have your boat driving license?! Who goes skydiving at 6 AM?!",
            virality_reason="High speed boat mayhem with sea sickness and hilarious argument on open water.",
        ),
        CandidateHighlight(
            title="Secret Shipwreck Heist: Diving Into The Deep Abyss",
            raw_start=3523.0,
            raw_end=3584.0,
            score=94,
            archetype=HighlightArchetype.ACTION_HEIST,
            hook_sentence="Shipwreck dive starts now... remember what you're really doing down there, good luck!",
            virality_reason="The visual centerpiece scuba diving underwater exploration and covert mission.",
        ),
    ]
    return candidates


def main() -> None:
    """Snap candidate timestamps and print diversity evaluation."""
    words = load_transcript_words()
    snapper = AudioBoundarySnapper(words)

    raw_candidates = build_candidate_highlights()
    snapped_candidates: List[CandidateHighlight] = []

    print("=== Snapping Audio Boundaries to Speech Silences ===")
    for cand in raw_candidates:
        snapped = snapper.snap_highlight(cand)
        snapped_candidates.append(snapped)
        print(
            f"[*] '{cand.title}' [{cand.archetype.value}]:\n"
            f"    Raw:     {cand.raw_start:.2f}s -> {cand.raw_end:.2f}s ({cand.raw_end - cand.raw_start:.2f}s)\n"
            f"    Snapped: {snapped.snapped_start:.2f}s -> {snapped.snapped_end:.2f}s ({snapped.duration:.2f}s)"
        )

    engine = GuardedTNMSDiversityEngine(guard_band=45.0)
    selected = engine.select_diverse_highlights(snapped_candidates, target_count=8)

    print(f"\n=== Guarded T-NMS Selected {len(selected)} Diverse Highlights ===")
    for i, s in enumerate(selected, 1):
        print(f"[{i}/8] {s.title} ({s.archetype.value}) - {s.snapped_start:.2f}s -> {s.snapped_end:.2f}s ({s.duration:.2f}s)")

    out_file = Path("output/raw/captions/ep3_selected_highlights.json")
    payload = [
        {
            "id": i,
            "title": s.title,
            "start": round(s.snapped_start, 2),
            "end": round(s.snapped_end, 2),
            "duration": round(s.duration, 2),
            "archetype": s.archetype.value,
            "hook_sentence": s.hook_sentence,
            "virality_reason": s.virality_reason,
            "score": s.score,
        }
        for i, s in enumerate(selected, 1)
    ]
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    print(f"\nSaved {len(selected)} highlights to {out_file}")


if __name__ == "__main__":
    main()
