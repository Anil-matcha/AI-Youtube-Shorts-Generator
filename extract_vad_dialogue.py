"""Extract all genuine dialogue segments across Episode 2 using VAD filtering."""

from faster_whisper import WhisperModel

model = WhisperModel("base.en", device="cpu", compute_type="int8")
segments, _ = model.transcribe(
    r"output\ep2_audio.wav",
    condition_on_previous_text=False,
    vad_filter=True,
    beam_size=5
)

lines = []
for s in segments:
    txt = s.text.strip()
    if "thank you" not in txt.lower() and len(txt) > 3:
        m, sec = int(s.start // 60), int(s.start % 60)
        dur = s.end - s.start
        lines.append(f"{m:02d}:{sec:02d} ({s.start:.1f}s - {s.end:.1f}s, {dur:.1f}s): {txt}")

with open(r"output\ep2_vad_dialogue.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(lines))

print(f"Extracted {len(lines)} non-hallucinatory dialogue segments.")
