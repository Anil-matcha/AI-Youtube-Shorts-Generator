# AI YouTube Shorts Generator

[![Powered by MuAPI](https://img.shields.io/badge/Powered%20by-MuAPI-6366f1?style=flat-square&logo=data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAyNCAyNCI+PHBhdGggZmlsbD0id2hpdGUiIGQ9Ik0xMiAyQzYuNDggMiAyIDYuNDggMiAxMnM0LjQ4IDEwIDEwIDEwIDEwLTQuNDggMTAtMTBTMTcuNTIgMiAxMiAyem0tMSAxNHYtNGgtMnYtMmg0djZoLTJ6bTAtOFY2aDJ2MmgtMnoiLz48L3N2Zz4=)](https://muapi.ai?utm_source=github&utm_medium=badge&utm_campaign=ai-youtube-shorts-generator)


**The open-source alternative to Opus Clip, Vidyo.ai, Klap, SubMagic, 2short.ai, and other AI clipping tools.** Drop in any long-form YouTube video and get back ranked, viral-ready 9:16 shorts — for free, with no per-clip credits, no watermarks, and full control over the highlight algorithm.

Built for creators, agencies, and developers who don't want to pay $20–$300/month or be capped on minutes processed. Uses GPT-class LLM highlight detection and Whisper transcription to extract the most viral-worthy moments and auto-crop them vertically for TikTok, Reels, and Shorts.

<p align="center"><a href="https://www.youtube.com/watch?v=10Ep2pmfyVI"><img src="https://i.ytimg.com/vi/10Ep2pmfyVI/maxresdefault.jpg" width="720"></a></p>
<p align="center"><a href="https://www.youtube.com/watch?v=10Ep2pmfyVI"><b>▶ Watch: How to Use the Nano Banana 2.1 API (Step-by-Step Guide) </b></a></p>

> **Building your own Opus Clip–style SaaS?** Skip the infra and ship on the same APIs that power this repo:
> - [AI Clipping API](https://muapi.ai/playground/ai-clipping?utm_source=github&utm_medium=readme&utm_campaign=ai-youtube-shorts-generator) — end-to-end clip selection + render
> - [Auto-Crop API](https://muapi.ai/playground/autocrop?utm_source=github&utm_medium=readme&utm_campaign=ai-youtube-shorts-generator) — vertical reframing only

![longshorts](https://github.com/user-attachments/assets/3f5d1abf-bf3b-475f-8abf-5e253003453a)

<p align="center">
  <a href="https://github.com/Anil-matcha/awesome-generative-ai-apps">
    <img src="https://img.shields.io/badge/Part%20of-Awesome%20Generative%20AI%20Apps-FFD700?style=for-the-badge&logo=github&logoColor=black" alt="Awesome Generative AI Apps">
  </a>
</p>

> 🎨 **[Explore 50+ more open-source AI apps →](https://github.com/Anil-matcha/awesome-generative-ai-apps)**

## Why Use This Instead of Opus Clip / Vidyo.ai / Klap?

| | This repo | Opus Clip / Vidyo.ai / Klap / SubMagic |
|---|---|---|
| **Price** | Free + open source (pay only for API usage) | $20–$300/month subscriptions |
| **Per-clip credits** | None — process unlimited videos | Monthly minute caps, overage fees |
| **Watermarks** | Never | On free tiers |
| **Highlight algorithm** | Fully editable virality framework | Black box |
| **Output format** | Any aspect ratio, any resolution | Locked presets |
| **Batch processing** | `xargs` an entire URL list | Manual upload one-by-one |
| **JSON / API output** | Built-in (`--output-json`) | Limited or paid tier only |
| **Self-hostable** | Yes — runs on your machine or server | SaaS only, your videos sit on their servers |
| **White-label / embeddable** | Yes — MIT licensed, import as Python lib | No |

## Features

- **🎬 YouTube In, Vertical Out**: Hand it any YouTube URL — get back N viral-ready 9:16 mp4s
- **🔀 Two Modes — API (fast) or Local (offline)**: Default `--mode api` uses MuAPI for download/transcription/cropping; `--mode local` runs entirely on your machine with `yt-dlp`, `faster-whisper`, and `ffmpeg`/`opencv`, and lets you pick OpenAI or Gemini for highlight ranking
- **🤖 Virality-Aware Highlight Selection**: Clips ranked on hooks, emotional peaks, opinion bombs, revelation moments, conflict, quotable lines, story peaks, and practical value — not just generic "interesting"
- **📈 Score + Hook + Reason for Every Clip**: Each highlight comes with a viral score, an opening hook line, and a one-sentence explanation of why it works
- **🎤 Whisper Transcription, Your Choice**: Cloud (`/openai-whisper` via MuAPI) or local (`faster-whisper`, CPU or CUDA) — same downstream output shape
- **🧩 Long-Video Aware**: Videos over 30 minutes are auto-chunked with overlap so nothing gets missed
- **♻️ Smart Dedupe**: Overlapping highlights are collapsed by score so you never get two near-duplicate clips
- **🎯 Smart Vertical Crop**: API mode uses MuAPI's auto-crop; local mode runs OpenCV face tracking with motion smoothing
- **📱 Any Aspect Ratio**: 9:16 for TikTok/Reels/Shorts, 1:1 for square, anything else by flag
- **🧰 CLI + Python Library**: Use it from the shell or import `generate_shorts(...)` into your own pipeline
- **📦 JSON Output**: `--output-json` dumps the full result (transcript + every candidate highlight + final clip URLs/paths) for downstream automation

## Quick Start (No Setup)

Don't want to self-host? The [AI Clipping API](https://muapi.ai/playground/ai-clipping?utm_source=github&utm_medium=readme&utm_campaign=ai-youtube-shorts-generator) gives you the same Opus Clip–style pipeline as a single HTTP call — no Python, no dependencies, pay-per-clip instead of monthly subscriptions.

---

## Installation (Self-Hosted)

### Prerequisites

- Python 3.10+
- For **API mode (default)**: a MuAPI key — powers download, transcription, highlight ranking, and clipping in a single dependency
- For **Local mode** (`--mode local`): `ffmpeg` on your PATH and an LLM API key (`OPENAI_API_KEY` or `GEMINI_API_KEY`; only the LLM step is remote)

### Steps

1. **Clone the repository:**
   ```bash
   git clone https://github.com/SamurAIGPT/AI-Youtube-Shorts-Generator.git
   cd AI-Youtube-Shorts-Generator
   ```

2. **Create and activate a virtual environment:**
   ```bash
   python3.10 -m venv venv
   source venv/bin/activate
   ```

3. **Install Python dependencies:**
   ```bash
   pip install -r requirements.txt
   # Only if you plan to use --mode local:
   pip install -r requirements-local.txt
   ```

4. **Set up environment variables:**

   Create a `.env` file in the project root:
   ```bash
   # API mode (default)
   MUAPI_API_KEY=your_muapi_key_here

   # Local mode (--mode local)
   LLM_PROVIDER=openai         # openai or gemini
   OPENAI_API_KEY=your_openai_key_here
   OPENAI_MODEL=gpt-4o-mini          # optional, default gpt-4o-mini
   GEMINI_API_KEY=your_gemini_key_here
   GEMINI_MODEL=gemini-2.5-flash      # optional, default gemini-2.5-flash
   LOCAL_WHISPER_MODEL=base          # tiny / base / small / medium / large-v3
   LOCAL_WHISPER_DEVICE=auto         # auto / cpu / cuda
   LOCAL_OUTPUT_DIR=output           # where local mp4s land
   ```

## Usage

### Single video (API mode — default)

```bash
python main.py "https://www.youtube.com/watch?v=VIDEO_ID"
```

### Single video (Local mode — runs offline except for the LLM call)

```bash
python main.py "https://www.youtube.com/watch?v=VIDEO_ID" --mode local
```

Local mode writes the rendered shorts to `./output/short_01.mp4`, `short_02.mp4`, … (override with `LOCAL_OUTPUT_DIR`).

### With options

```bash
python main.py "https://www.youtube.com/watch?v=VIDEO_ID" \
    --mode api \
    --num-clips 5 \
    --aspect-ratio 9:16 \
    --output-json result.json
```

### Local file or path

In `--mode local`, you can pass a `file://` URL or a direct filesystem path and skip YouTube entirely:

```bash
python main.py "/Users/you/Videos/input.mp4" --mode local
python main.py "file:///Users/you/Videos/input.mp4" --mode local
```

The Python API works the same way:

```python
from shorts_generator import generate_shorts

result = generate_shorts(
    "/Users/you/Videos/input.mp4",
    num_clips=5,
    aspect_ratio="9:16",
    mode="local",
)
for short in result["shorts"]:
    print(short["score"], short["title"], short["clip_url"])
```

Local transcription is cached as an `.srt` file in `LOCAL_OUTPUT_DIR` using the
video's base name. If the cache already exists and is newer than the source
file, the app reuses it instead of running Whisper again.

Local downloads are also cached in `LOCAL_OUTPUT_DIR` as
`source_<youtube_id>.mp4` when the input is a YouTube URL. If that file already
exists, the app skips `yt-dlp` and reuses the cached video.

### Batch processing

Create a `urls.txt` file with one URL per line, then:

```bash
xargs -a urls.txt -I{} python main.py "{}"
```

### CLI flags

| Flag | Default | Notes |
|------|---------|-------|
| `--mode` | `api` | `api` (MuAPI, fast, no setup) or `local` (remote URL, `file://`, or local path + faster-whisper + LLM provider + ffmpeg) |
| `--num-clips` | `3` | How many shorts to render |
| `--aspect-ratio` | `9:16` | Any ratio; `9:16` for TikTok/Reels, `1:1` for square |
| `--format` | `720` | Source download resolution: `360` / `480` / `720` / `1080` |
| `--language` | auto | Force Whisper language code (e.g. `en`) |
| `--output-json` | — | Dump the full result (transcript + all candidates) to a file |

### API mode vs Local mode

| Step | API mode (`--mode api`) | Local mode (`--mode local`) |
|---|---|---|
| Download | MuAPI `/youtube-download` | `yt-dlp` for remote URLs, direct file path for local inputs |
| Transcription | MuAPI `/openai-whisper` | `faster-whisper` (CPU or CUDA) |
| Highlight LLM | MuAPI `gpt-5-mini` | `LLM_PROVIDER=openai` uses OpenAI (`gpt-4o-mini` by default), `LLM_PROVIDER=gemini` uses Gemini (`gemini-2.5-flash` by default) |
| Vertical crop | MuAPI `/autocrop` | `ffmpeg` + OpenCV face tracking |
| Output | hosted URLs | local mp4 paths |
| Required keys | `MUAPI_API_KEY` | `OPENAI_API_KEY` or `GEMINI_API_KEY` (+ `ffmpeg` on PATH) |

## How It Works

1. **Download**: Fetches the source video from YouTube
2. **Transcribe**: MuAPI `/openai-whisper` produces a timestamped transcript (verbose_json segments)
3. **Detect content type**: An LLM classifies the video (podcast, interview, tutorial, vlog, etc.) and density, so the prompt can be tuned per content style
4. **Long-video chunking**: Videos > 30 min are split into 20-min overlapping chunks
5. **Highlight ranking**: An LLM scans the transcript through a virality framework — hook moments, emotional peaks, opinion bombs, revelations, conflict, quotables, story peaks, practical value — and emits ranked candidates with scores 0–100
6. **Dedupe**: Overlapping candidates are collapsed by score (>50% overlap → keep the higher score)
7. **Top-N selection**: The top `--num-clips` candidates are selected
8. **Auto-crop**: Each highlight is rendered as a vertical short at the requested aspect ratio

**Output**: a list of mp4 URLs plus, for each clip, its title, viral score, hook sentence, and a one-line reason explaining why it should perform.

## Viral Highlight Selection

The current selector is transcript-only. It classifies a sample of the opening transcript by content type and density, then asks one LLM call per transcript or long-video chunk to discover moments, choose boundaries, and assign each candidate a 0–100 viral score. Long-video timestamps are made chunk-relative for selection and restored to the global timeline afterward. Candidates are normalized to transcript boundaries within 20–60 seconds, sorted by the LLM's self-reported score, and deduplicated only when their timestamp ranges overlap substantially. The pipeline renders the highest-scoring `--num-clips` candidates.

This design is simple and inexpensive, and its prompt explicitly values hooks, emotional peaks, polarizing opinions, revelations, conflict, quotability, story payoff, practical value, and standalone completeness. Its main limitations are low candidate recall, uncalibrated self-scoring, coupled discovery/scoring/boundary decisions, possible position and topic-clustering bias, timestamp-only deduplication, and no access to delivery, speaker, or visual signals.

### Future Work: Selector V2

> The following architecture is planned work, not currently implemented functionality.

1. **High-recall candidate generation:** collect roughly 10–20 plausible moments across the full source, retaining timestamps, excerpt, proposed hook, and discovery rationale. Candidate count should reflect source length rather than final clip count.
2. **Independent multi-dimensional judge:** score candidates separately from discovery on hook strength, standalone clarity, novelty, emotional intensity, practical value, controversy/tension, payoff, quotability, niche relevance, and shareability. A starting niche score is `18% hook + 15% clarity + 12% novelty + 12% payoff + 12% niche relevance + 8% practical value + 8% emotion/tension + 7% quotability + 8% shareability`. Component scores should be retained for inspection and later calibration.
3. **Niche-aware scoring:** make niche relevance a configurable ranking signal rather than a hard filter. An `ai_business_money` profile would favor concrete money/revenue/cost claims, AI-driven job or workflow change, founder mistakes, contrarian business or investing views, automation, career disruption, unusual startup stories, and strong technology predictions. Other profiles should be data/configuration, not selector code.
4. **Semantic diversity:** after judging, penalize candidates that are temporally close, express the same claim, or cover the same subtopic. Lightweight embeddings are preferred; an LLM pairwise similarity check is a fallback for the small finalist set. Diversity should be a soft penalty so an exceptional section can still contribute more than one clip.
5. **Boundary refinement:** identify the core claim first, then inspect nearby transcript context and independently choose sentence-aligned boundaries that preserve hook → build/context → payoff within 20–60 seconds. The existing transcript-aware normalizer remains the final safety layer.
6. **Lightweight multimodal features:** add cheap signals before heavy video models. Recommended order is audio RMS/energy and pause changes (high benefit, low complexity/CPU), speech-rate change and speaker-turn density (medium-high benefit, low-medium cost), laughter cues (medium benefit/cost), title/topic metadata (medium benefit, very low cost), and sparse sampled-frame scene/reaction changes (medium benefit, medium CPU).
7. **Performance-feedback loop:** log candidate components, topic, duration, platform, and outcomes. With fewer than 100 published clips, inspect errors and tune transparent weights; at 100–500, use shrinkage-aware regressions or pairwise ranking; beyond roughly 500, evaluate learning-to-rank and embeddings against similar successful clips. Raw views are noisy because distribution, account size, posting time, packaging, platform, and randomness confound selector quality; retention, shares, saves, comments, and within-account/platform comparisons are stronger labels.

#### Future Work: Performance-Conditioned Ranking

> This is planned future work, not currently implemented.

The initial component weights are hand-designed. For every published clip, a future system should retain selector features—`hook_strength`, `standalone_clarity`, `novelty`, `payoff`, `niche_relevance`, `practical_value`, `emotional_intensity`, `quotability`, `shareability`, `duration`, `topic`, `source`, and `speaker`—alongside outcomes such as `views_24h`, `views_7d`, `average_watch_time`, `completion_rate`, `shares`, `saves`, `comments`, `follows_generated`, `platform`, and `posting_time`.

Raw views should not be the target by themselves: account size, platform distribution, posting time, source popularity, trends, audience geography, and other confounders can dominate clip quality. A normalized performance objective should emphasize retention/average watch time, completion rate, shares, saves, follows generated, and views normalized within comparable account, platform, and time contexts.

| Published clips | Planned approach |
|---|---|
| **<50** | Keep manual weights, collect clean metadata and outcomes, and do not train a model. |
| **50–150** | Analyze relationships between component scores and performance, then adjust transparent weights based on evidence. |
| **150–500** | Introduce a lightweight ranker such as logistic regression, linear/pairwise ranking, or gradient boosting. Include duration, topic, source, and posting-time context; avoid deep learning. |
| **500+** | Evaluate account-specific weights, pairwise preference models, embeddings, similarity to historically successful clips, and nearest-neighbor performance signals. |

Pairwise ranking asks which of two candidates from comparable contexts is more likely to outperform the other, rather than attempting to predict an exact and highly noisy view count.

```text
Long Video
    ↓
High-Recall Candidate Generator
    ↓
LLM Component Scoring
    ↓
Account-Specific Learned Ranker
    ↓
Semantic Diversity Filter
    ↓
Boundary Refinement
    ↓
Top Clips
    ↓
Publish
    ↓
Observed Performance
    ↓
Training / Calibration Data
    ↺
(calibrates scoring and ranking)
```

The long-term question is not “Is this clip generically viral?” but “How likely is this clip to perform well for this specific account and audience?” A configurable profile such as the following would allow the same source video to produce different finalists for different audiences:

```yaml
selection:
  niche: ai_business_money
  ranking_profile: account_specific
```

Before enough production data exists, evaluate on 3–5 diverse podcasts using blinded top-k versus random or prior-selector clips. Reviewers should score hook strength, standalone clarity, payoff, niche relevance, publishability, and semantic diversity, with pairwise preference used where absolute scores disagree. Track publishable precision@3 and source-level topic coverage. A practical V1 baseline is at least 2 of 3 clips publishable per source. V2 should reach at least 80% publishable precision@3, beat random/baseline clips in at least 70% of blinded pairwise comparisons, and avoid semantic duplicates in at least 90% of final three-clip sets.

## Output

Console output looks like:

```
========================================================================
Highlights:    7 candidates → kept top 3
========================================================================

#1  score=92  124.3s → 187.6s
     title:  The one mistake that cost me $50K
     hook:   "Nobody talks about this, but it killed my first startup..."
     clip:   https://.../short_1.mp4

#2  score=88  ...
```

`--output-json result.json` produces:

```json
{
  "source_video_url": "...",
  "transcript": { "duration": 1873.4, "segments": [...] },
  "highlights": [ {...}, {...}, ... ],
  "shorts": [
    {
      "title": "...",
      "start_time": 124.3,
      "end_time": 187.6,
      "score": 92,
      "hook_sentence": "...",
      "virality_reason": "...",
      "clip_url": "https://.../short_1.mp4"
    }
  ]
}
```

## Configuration

### Highlight selection criteria
Edit `shorts_generator/highlights.py`:
- **Virality framework**: `VIRALITY_CRITERIA` — the ranked list of signals the LLM optimizes for
- **System prompt**: `HIGHLIGHT_SYSTEM_PROMPT` — duration sweet spot, hook rules, JSON schema
- **Chunk size**: `CHUNK_SIZE_SECONDS` (default 1200) — chunk length for long videos
- **Long-video threshold**: `LONG_VIDEO_THRESHOLD` (default 1800) — videos longer than this are chunked
- **Chunk overlap**: `CHUNK_OVERLAP_SECONDS` (default 60) — overlap between chunks so cross-boundary clips aren't missed

### Polling / timeout
Edit `shorts_generator/config.py` (or set env vars):
- `MUAPI_POLL_INTERVAL` (default 5s) — seconds between job-status polls
- `MUAPI_POLL_TIMEOUT` (default 1800s) — give up after this long

### Whisper transcription
Audio is transcribed by MuAPI's `/openai-whisper` endpoint (server-side `whisper-1`). Pass `--language <code>` to lock the recognition to a specific language; otherwise it auto-detects.

## Project Structure

```
AI-Youtube-Shorts-Generator/
├── main.py                       CLI entry point
├── requirements.txt              core deps (api mode)
├── requirements-local.txt        optional deps for --mode local
├── .env.example
└── shorts_generator/
    ├── config.py                 env / settings (MuAPI + local LLM + Whisper)
    ├── muapi.py                  generic submit + poll wrapper
    ├── downloader.py             API mode: YouTube download via MuAPI
    ├── transcriber.py            API mode: MuAPI /openai-whisper client
    ├── highlights.py             shared LLM virality ranking (pluggable backend)
    ├── clipper.py                API mode: MuAPI /autocrop
    ├── pipeline.py               mode dispatcher (api ↔ local)
    └── local/                    --mode local backends (offline)
        ├── downloader.py         yt-dlp download
        ├── transcriber.py        faster-whisper transcription
        ├── llm.py                OpenAI or Gemini client selector
        └── clipper.py            ffmpeg cut + OpenCV vertical crop
```

## Troubleshooting

### Whisper produced no segments
The video may have no detectable speech, or it may be in a language Whisper struggles with. Try passing `--language en` (or the correct ISO-639-1 code) to skip auto-detection.

### Looking for better results?
The [AI Clipping API](https://muapi.ai/playground/ai-clipping?utm_source=github&utm_medium=readme&utm_campaign=ai-youtube-shorts-generator) uses an improved algorithm that produces higher-quality clips with better highlight detection.

## Contributing

Contributions are welcome! Please fork the repository and submit a pull request.

## License

This project is licensed under the MIT License.

## Related Projects

- [awesome-vibecoded-saas](https://github.com/Anil-matcha/awesome-vibecoded-saas) — broader catalog of open-source SaaS alternatives featuring this Shorts workflow.
- [Muapi open-source alternatives](https://muapi.ai/open-source/alternative) — compare the Shorts workflow with the paid creator tools it targets.
- [AI Influencer Generator](https://github.com/SamurAIGPT/AI-Influencer-Generator)
- [Text to Video AI](https://github.com/SamurAIGPT/Text-To-Video-AI)
- [Faceless Video Generator](https://github.com/SamurAIGPT/Faceless-Video-Generator)
- [AI B-roll Generator](https://github.com/Anil-matcha/AI-B-roll)
- [No-code YouTube Shorts Generator](https://www.vadoo.tv/clip-youtube-video)
- [ai-creator-academy](https://github.com/Anil-matcha/ai-creator-academy) — free curriculum teaching creators how to monetize AI-generated shorts and video content
