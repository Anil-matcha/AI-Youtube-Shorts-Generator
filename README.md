# AI YouTube Shorts Generator

[![Powered by MuAPI](https://img.shields.io/badge/Powered%20by-MuAPI-6366f1?style=flat-square&logo=data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAyNCAyNCI+PHBhdGggZmlsbD0id2hpdGUiIGQ9Ik0xMiAyQzYuNDggMiAyIDYuNDggMiAxMnM0LjQ4IDEwIDEwIDEwIDEwLTQuNDggMTAtMTBTMTcuNTIgMiAxMiAyem0tMSAxNHYtNGgtMnYtMmg0djZoLTJ6bTAtOFY2aDJ2MmgtMnoiLz48L3N2Zz4=)](https://muapi.ai?utm_source=github&utm_medium=badge&utm_campaign=ai-youtube-shorts-generator)


**The open-source alternative to Opus Clip, Vidyo.ai, Klap, SubMagic, 2short.ai, and other AI clipping tools.** Drop in any long-form YouTube video and get back ranked, viral-ready 9:16 shorts — for free, with no per-clip credits, no watermarks, and full control over the highlight algorithm.

Built for creators, agencies, and developers who don't want to pay $20–$300/month or be capped on minutes processed. Uses GPT-class LLM highlight detection and Whisper transcription to extract the most viral-worthy moments and auto-crop them vertically for TikTok, Reels, and Shorts.

<p align="center"><a href="https://www.youtube.com/watch?v=kT1CO4BYV3A"><img src="https://i.ytimg.com/vi/kT1CO4BYV3A/maxresdefault.jpg" width="720"></a></p>
<p align="center"><a href="https://www.youtube.com/watch?v=kT1CO4BYV3A"><b>▶ Watch: Free Unlimited AI Image Generator (Truly no limits, Open Source, No Watermark) </b></a></p>

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
   LLM_PROVIDER=openai         # openai, gemini, or ollama
   OPENAI_API_KEY=your_openai_key_here
   OPENAI_MODEL=gpt-4o-mini          # optional, default gpt-4o-mini
   GEMINI_API_KEY=your_gemini_key_here
   GEMINI_MODEL=gemini-2.5-flash      # optional, default gemini-2.5-flash
   # Ollama settings (when LLM_PROVIDER=ollama)
   OLLAMA_BASE_URL=http://localhost:11434   # local or remote Ollama endpoint
   OLLAMA_MODEL=llama3.2                    # any model pulled in Ollama
   # OLLAMA_NUM_CTX=32768                   # context window size in tokens (default 32768)
   # CLIP_LENGTH=45                         # optional: target clip length in seconds (±5s tolerance)
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

### Shot-aware cropping (local mode)

When your video has distinct camera cuts or angle changes (e.g. switching between wide shots, close-ups, and different subjects), the default face-tracking crop can drift or shake as it adjusts mid-shot. Use `--crop-mode shot` to detect shot boundaries and lock the crop center to the main action area within each shot:

```bash
python main.py "https://www.youtube.com/watch?v=VIDEO_ID" --mode local --crop-mode shot
```

This analyzes motion per shot, finds where the most activity happens, and keeps the crop locked there until the next cut. No mid-shot drift — ideal for stationary shots where you want the action centered per scene.

### Captions (local mode)

Burn transcript captions directly into the output clips. White text with a black outline, bottom-centered, sized automatically to the video height. Default is off.

```bash
python main.py "https://www.youtube.com/watch?v=VIDEO_ID" --mode local --captions
```

Combine with other options:

```bash
python main.py "https://www.youtube.com/watch?v=VIDEO_ID" --mode local --crop-mode shot --captions
```

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
| `--clip-length` | — | Optional: target clip length in seconds (±5s tolerance). Default behavior is 45–90s sweet spot |
| `--aspect-ratio` | `9:16` | Any ratio; `9:16` for TikTok/Reels, `1:1` for square |
| `--format` | `720` | Source download resolution: `360` / `480` / `720` / `1080` |
| `--language` | auto | Force Whisper language code (e.g. `en`) |
| `--crop-mode` | `face` | Local mode only: `face` (face-tracking) or `shot` (shot-aware action centering) |
| `--captions` | off | Local mode only: burn transcript captions into the output clips |
| `--generate-metadata` | off | Generate YouTube + TikTok titles, descriptions, and hashtags for each short |
| `--output-json` | — | Dump the full result (transcript + all candidates) to a file |

### API mode vs Local mode

| Step | API mode (`--mode api`) | Local mode (`--mode local`) |
|---|---|---|
| Download | MuAPI `/youtube-download` | `yt-dlp` for remote URLs, direct file path for local inputs |
| Transcription | MuAPI `/openai-whisper` | `faster-whisper` (CPU or CUDA) |
| Highlight LLM | MuAPI `gpt-5-mini` | `LLM_PROVIDER=openai` uses OpenAI (`gpt-4o-mini` by default), `LLM_PROVIDER=gemini` uses Gemini (`gemini-2.5-flash` by default), `LLM_PROVIDER=ollama` uses any Ollama model (local or remote) |
| Vertical crop | MuAPI `/autocrop` | `ffmpeg` + OpenCV face tracking |
| Output | hosted URLs | local mp4 paths |
| Required keys | `MUAPI_API_KEY` | `OPENAI_API_KEY`, `GEMINI_API_KEY`, or Ollama endpoint (+ `ffmpeg` on PATH) |

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

### Ollama (fully local / self-hosted LLM)

Set `LLM_PROVIDER=ollama` to run highlight ranking through any Ollama-compatible endpoint — your laptop, a LAN server, or a cloud GPU instance (RunPod, Vast.ai, etc.).

1. **Install Ollama** (if running locally): https://ollama.com/download
2. **Pull a model** (see model recommendations below):
   ```bash
   ollama pull llama3.2
   ```
3. **Configure `.env`**:
   ```bash
   LLM_PROVIDER=ollama
   OLLAMA_BASE_URL=http://localhost:11434
   OLLAMA_MODEL=llama3.2
   ```
4. **Run**:
   ```bash
   python main.py "https://www.youtube.com/watch?v=VIDEO_ID" --mode local
   ```

**Context window (`OLLAMA_NUM_CTX`)**

By default the context window is set to **32768 tokens** (the maximum for Qwen 2.5 and most modern models). If you run into VRAM limits, set a lower value in `.env`:

```bash
OLLAMA_NUM_CTX=16384   # or 8192, 4096, etc.
```

The value is passed as `num_ctx` in the Ollama `/api/chat` options. You can also set it per-run:

```bash
OLLAMA_NUM_CTX=8192 python main.py "..." --mode local
```

**Remote Ollama example** (e.g. on a cloud GPU):
```bash
OLLAMA_BASE_URL=http://192.168.1.50:11434 OLLAMA_MODEL=phi4 python main.py "..." --mode local
```

**Recommended models for an 8 GB GPU**

| Model | Size | Notes |
|-------|------|-------|
| `llama3.2` | 3B | Fast, good instruction following, fits easily on 8 GB |
| `phi4` | ~14B (Q4_K_M ≈ 8.5 GB) | Strong reasoning; may need `--num_gpu 1` on 8 GB |
| `qwen2.5` | 7B (Q4 ≈ 4.5 GB) | Excellent multilingual, great JSON adherence |
| `gemma3` | 4B (Q4 ≈ 3 GB) | Google's lightweight model, solid quality |
| `mistral` | 7B (Q4 ≈ 4.1 GB) | Good general performance, fast inference |
| `deepseek-r1:7b` | 7B (Q4 ≈ 4.5 GB) | Reasoning-focused, slower but thorough |

**Cloud / hosted Ollama options**

If you don't have a local GPU, you can point `OLLAMA_BASE_URL` at:
- **RunPod** Serverless or Pod with Ollama pre-installed
- **Vast.ai** — rent an RTX 3090/4090 by the hour (~$0.30–$0.60/hr)
- **AnyScale Endpoints** or **Together AI** — OpenAI-compatible APIs that serve open-weight models (set `LLM_PROVIDER=openai` and point `OPENAI_BASE_URL` at their endpoint)

### Clip length

By default the LLM uses a **45–90 second** sweet spot for highlights, which works well for most content. If you want tighter control, set `CLIP_LENGTH` (in seconds) and the LLM will aim for that length with a ±5-second tolerance. A value of `30` produces 25–35s clips and `10` produces 5–15s clips.

```bash
# .env
CLIP_LENGTH=30
```

Or pass it per-run:

```bash
python main.py "..." --mode local --clip-length 30
```

Shorter values (10–20) are great for quick hooks; longer values (60–90) suit tutorials or story arcs. Leave it unset to keep the original 45–90s behavior.

### Metadata generation

Generate platform-specific titles and descriptions for each short by passing `--generate-metadata`:

```bash
python main.py "..." --mode local --generate-metadata
```

This produces a `shorts_metadata.txt` file alongside the clips with:
- **YouTube title** (max 60 chars)
- **YouTube description** (2–3 sentences + hashtags)
- **TikTok caption** (max 100 chars, emoji-friendly)
- **TikTok hashtags** (5–8 relevant tags)

The metadata is grounded in the clip's actual transcript, hook sentence, and virality reason. Default is off to save LLM tokens and time.

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
        ├── llm.py                OpenAI / Gemini / Ollama client selector
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
