> status: paused | one-liner: local mode verified end to end on a 64 minute source | next: upstream PR 63 is still open, and four files sit uncommitted on the fix/chunked-highlight-timestamps branch. Burned-in captions are absent by design, rig short does those.

# HANDOFF — AI-Youtube-Shorts-Generator

Upstream: https://github.com/Anil-matcha/AI-Youtube-Shorts-Generator (cloned 2026-08-09, `--depth 1`)

## State

Installed and verified end to end in **local mode**, on both a 5-minute source and a
full 64-minute one. The long run produced 23 highlight candidates across 4 chunks and
rendered the top 3 as 270x480 (9:16) mp4s with AAC audio and a face-tracked crop.
Verified by transcribing the rendered clips back: all three open on exactly the hook
sentence the model claimed, so the cut points are real and not just plausible.

Carries one patch to upstream code (see "The long-video bug" below), committed on branch
`fix/chunked-highlight-timestamps` and sent upstream as
[PR #63](https://github.com/Anil-matcha/AI-Youtube-Shorts-Generator/pull/63).
Fork lives at github.com/wretcher207/AI-Youtube-Shorts-Generator, remote name `fork`.
If the PR is merged, drop the branch and track upstream `main`. If it is ignored, keep
running off this branch.

Not using API mode. API mode routes everything through MuAPI, a paid pay-per-generation
aggregator, and the repo's README is partly a funnel for it. Local mode does the same job
with faster-whisper on CPU (free) plus one cheap Gemini call per video.

## Run it

```powershell
cd C:\Users\wretc\workspace\AI-Youtube-Shorts-Generator
.\.venv\Scripts\python.exe main.py "<youtube url or local file path>" --mode local --num-clips 3 --language en
```

Output lands in `output/`. `--output-json result.json` dumps the full highlight data.
`main.py` accepts a local file path, not just a URL, so it works on David's own footage.

## Environment

- venv is **Python 3.11.15** (uv's copy at `~\AppData\Roaming\uv\python\cpython-3.11.15-...`),
  not the system 3.14. Built on 3.11 because the wheel situation on 3.14 is still thin.
- `.env` holds `LLM_PROVIDER=gemini` and the Gemini key from `workspace/api-keys.md`.
  `.env` is gitignored.
- Whisper model `base`, device `cpu`. This box has no useful CUDA.
- ffmpeg comes from the winget Gyan build already on PATH.

## Traps hit, and what fixed them

**OpenCV 5 breaks the face crop.** `requirements-local.txt` says `opencv-python>=4.8.0`,
which now resolves to 5.0.0.93. OpenCV 5 removed `cv2.CascadeClassifier` from the top-level
namespace, so `_reframe_vertical` dies on every clip. Fixed by pinning to
`opencv-python<5` (installed 4.14.0.94). **Any future `pip install -r requirements-local.txt`
will silently re-break this** — re-pin after upgrading.

**The clipper hides its own errors.** `crop_clip_local` in `shorts_generator/local/clipper.py`
deletes the intermediate `.cut.mp4` in a `finally` block. When `_reframe_vertical` throws,
the OpenCV capture handle is still open, so the delete fails with `WinError 32` and that
exception *replaces* the real one. Every failure reports as a file-lock error regardless of
cause. If a clip fails, call `_cut_subclip` and `_reframe_vertical` by hand to see the truth.

**The long-video bug — every source over 30 minutes silently produced nothing.** This is a
genuine upstream bug, patched locally in `shorts_generator/highlights.py`.

`chunk_transcript` splits anything past 30 minutes into 20-minute chunks, but it left the
segments carrying **absolute** timestamps while setting `chunk["duration"]` to the chunk's
own length. `build_transcript_text` then fed the model absolute times, the model correctly
answered in absolute times, and `_sanitize_highlights` validated them against 1200 seconds,
clamped every one to the ceiling, and dropped them all for `end <= start`. Three retries,
then `Highlight generator produced invalid output after 3 attempts`.

Chunk 1 always worked because at offset 0 absolute and relative are identical, which made
the failure look intermittent. It is not. Confirmed directly: chunk 3 of the test video
returned 7 well-formed highlights and 0 survived the sanitizer.

The patch rebases each chunk's segments to 0 before building the prompt, which is what the
rest of the code already assumed — `get_highlights` adds `_offset` back on the way out, so
without the rebase the offset was being added to an already-absolute number anyway. It also
sets `chunk["duration"]` from the last rebased segment rather than `end - start`, so
highlights landing in the 60-second overlap tail stop being clamped away.

Sent upstream as PR #63. The OpenCV pin and the error-masking `finally` block were
flagged in that PR's description but not fixed in it, offered as a follow-up if the
maintainer wants them.

**Long sources sit near the memory ceiling.** faster-whisper computes the STFT for the whole
file in one shot and numpy's `rfft` returns complex128, so a 64-minute source needs roughly
3 to 4 GB of transient allocation. One attempt died with
`Unable to allocate 1.14 GiB for an array with shape (1, 382232, 201)` while free commit was
around 7 GB. The same file transcribed fine on the next two runs. Headroom, not a ceiling.
If an hour-plus video dies there, close other apps, drop to the `tiny` Whisper model, or cut
the source in half with ffmpeg first.

## The cutting tools moved out (2026-08-09)

`build_short.py`, `sync_camera.py` and the OBS scripts that used to sit in this
folder now live in `workspace/video-rig`, on PATH as `rig`. They were loose files
inside a clone of somebody else's repo, which is the wrong home for the actual
recording pipeline. Nothing here depends on them.

What this repo still owns: the download, transcription and LLM highlight-ranking
pipeline via `main.py --mode local`. Use it to find WHERE the good moments are.
Use `rig short` to actually cut and caption one.

## Not done

- No captions burned in. This pipeline cuts and crops, it does not subtitle.
  `rig short` does the captions.
