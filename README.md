# AI YouTube Shorts Generator (Enterprise Edition)

[![GitHub Fork](https://img.shields.io/badge/GitHub-piyushmakhija28%2FAI--Youtube--Shorts--Generator-blue?logo=github&style=flat-square)](https://github.com/piyushmakhija28/AI-Youtube-Shorts-Generator)
[![Python Version](https://img.shields.io/badge/Python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.13-blue?style=flat-square&logo=python)](https://www.python.org/)
[![Hardware Acceleration](https://img.shields.io/badge/Hardware%20Acceleration-Intel%20Arc%20QSV%20%2F%20Level%20Zero-0071C5?style=flat-square&logo=intel)](https://github.com/piyushmakhija28/AI-Youtube-Shorts-Generator)
[![Video Engine](https://img.shields.io/badge/FFmpeg-4K%2060FPS%20%7C%20Lanczos-007808?style=flat-square&logo=ffmpeg)](https://ffmpeg.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=flat-square)](LICENSE)

**The leading, actively maintained open-source alternative to Opus Clip, Vidyo.ai, Klap, SubMagic, and 2short.ai.**

Drop in any long-form YouTube video or local media file and automatically generate viral, high-retention 9:16 vertical shorts — 100% free, with no minute caps, no watermarks, full 4K 60FPS broadcast encoding, dynamic animated viral zooms, and complete offline hardware execution.

---

## 🌟 Why This Fork?

While upstream clipping tools remain unmaintained and locked to cloud APIs, this production fork provides an end-to-end studio pipeline with zero cloud lock-in:

| Feature | This Fork (`piyushmakhija28`) | Upstream / Generic SaaS |
|:---|:---|:---|
| **Local GPU LLM** | **Intel Arc Models Runner** (Level Zero, GPU/NPU native) | Cloud LLMs only or slow unoptimized CPU |
| **YouTube 403 Bypass** | **Android player client + cookie support** (#60 resolved) | Broken / HTTP 403 Forbidden failure |
| **Podcast Face Tracking** | **8% Deadband filter + 2.5s Hysteresis hold** (#81 resolved) | Violent camera jitter / rapid flip-flopping |
| **Framing Modes** | `split_stack`, `smart_focus`, `center`, `fit_blur`, `zoom_blur` | Basic centered crop only |
| **Dynamic Viral Zoom** | **0–3s hook punch + punctuation exclamation spikes** | Static stationary crop |
| **Long Video Handling** | **1800s+ timeout & live telemetry** (#55 resolved) | Times out after 10 minutes |
| **Live Stream Ingest** | **Native YouTube `/live/` with `--live-from-start`** (#92) | Fails on live URLs |
| **Output Quality** | **4K (2160x3840) @ 35M bitrate** with Lanczos & QSV | 720p / 1080p compressed |
| **Audio Mastering** | **EBU R128 (-14 LUFS) broadcast mastering** + 3.2kHz boost | Flat unmodified audio |

---

## 🚀 Core Engine Capabilities

### 1. Hardware-Accelerated Offline Local Mode (Intel Arc Models Runner)
Run the entire pipeline **100% offline** on your local machine with zero external cloud API expenses:
- Direct integration with **`intel-arc-models-runner`** via native Intel Level Zero, Intel Arc GPUs (A770, A750, B580, Core Ultra), and OpenVINO GenAI.
- Uses OpenAI-compatible HTTP protocol (`/v1/chat/completions`) over standard library sockets (zero extra dependencies).
- Fallback support for cloud LLMs (OpenAI `gpt-4o-mini` or Google `gemini-2.5-flash`).

### 2. Studio Vertical Framing Engine
Multi-mode intelligent reframing tailored to every content archetype:
- **`split_stack`**: Dual-speaker podcast and interview layout. Stacks host and guest vertically with a crisp broadcast separator line.
- **`smart_focus`**: Rule-of-thirds adaptive framing. Automatically detects and strips 2.39:1 anamorphic letterbox black bars.
- **`center`**: Climax centered focus for physics stunts, crashes, and gaming highlights.
- **`fit_blur` / `zoom_blur`**: Ambient blurred canvas background for panoramic landscapes and wide lore shots.

### 3. Automated Dynamic Viral Zoom Engine
Applies retention-maximizing camera motion matching top content creators:
- **0–3s Hook Punch**: Immediate +15% focal punch-in during the opening hook with smooth cosine-like ease-in/ease-out.
- **Climax Impact Punches**: Detects exclamation marks, shout peaks, and laughter spikes, punching in +25% for 1.8 seconds.
- **Tension Creep**: Smooth continuous zoom-in (+12%) on suspenseful monologues.

### 4. Two-Person Podcast Stability Engine (Issue #81 Fix)
- **Spatial Deadband Filter ($\pm 8\%$)**: Ignores subtle subject sway and head nods. The camera crop remains rock steady unless the speaker intentionally repositions.
- **Hysteresis Hold (2.5s)**: Eliminates nausea-inducing whip-pan switching during back-and-forth banter by requiring a speaker transition to persist for at least 2.5 seconds.

### 5. Anti-Throttling YouTube Downloader (Issue #60 & #92 Fixes)
- Integrates `extractor_args={'youtube': {'player_client': ['android', 'web']}}` to completely bypass YouTube's SABR bot blocks.
- Automatic multi-client fallback retry (`['ios', 'mweb']`) if any format encounters an HTTP 403 Forbidden.
- Full support for Netscape cookie files (`--cookies cookies.txt`).
- Full support for YouTube `/live/` streams with `live_from_start` streaming.

---

## 📦 Installation

### Prerequisites
- Python 3.10+
- `ffmpeg` on your system `PATH`
- (Optional for Local GPU Mode): Intel Arc GPU with Level Zero drivers / `intel-arc-models-runner`

### Setup Steps

```bash
# 1. Clone this fork
git clone https://github.com/piyushmakhija28/AI-Youtube-Shorts-Generator.git
cd AI-Youtube-Shorts-Generator

# 2. Create virtual environment
python -m venv venv
# Windows:
venv\Scripts\activate
# Linux/macOS:
source venv/bin/activate

# 3. Install core dependencies
pip install -r requirements.txt

# 4. Install local processing dependencies (Whisper, OpenCV, PyTorch)
pip install -r requirements-local.txt
```

### Configuration (`.env`)

Copy `.env.example` to `.env` and set your preferred execution mode:

```bash
# =======================================================
# OPTION A: 100% OFFLINE LOCAL GPU (RECOMMENDED)
# =======================================================
LLM_PROVIDER=arc_runner
ARC_RUNNER_BASE_URL=http://127.0.0.1:11434
ARC_RUNNER_MODEL=llama-3.2-3b
ARC_RUNNER_TIMEOUT=120.0
LOCAL_WHISPER_MODEL=base
LOCAL_WHISPER_DEVICE=auto

# =======================================================
# OPTION B: CLOUD LLM FOR HIGHLIGHT RANKING
# =======================================================
# LLM_PROVIDER=openai
# OPENAI_API_KEY=sk-...
# OPENAI_MODEL=gpt-4o-mini

# =======================================================
# OPTION C: REMOTE API MODE (MuAPI CLOUD PROXY)
# =======================================================
# MUAPI_API_KEY=your_key_here
# MUAPI_POLL_TIMEOUT=1800
```

---

## 💻 CLI Usage

### 1. Local Offline Mode with 4K Render & Dynamic Viral Zoom
```bash
python main.py "https://www.youtube.com/watch?v=dQw4w9WgXcQ" \
    --mode local \
    --resolution 4k \
    --framing split_stack \
    --num-clips 3
```

### 2. Processing Podcasts with Automatic Framing & Cookies
```bash
python main.py "https://www.youtube.com/watch?v=4jwUXV4QaTw" \
    --mode local \
    --framing smart_focus \
    --cookies cookies.txt \
    --num-clips 5
```

### 3. Processing YouTube Live Broadcasts
```bash
python main.py "https://www.youtube.com/live/45r3OyaxvFE" \
    --mode local \
    --resolution 1080p
```

### 4. Full Result JSON Export
```bash
python main.py "https://www.youtube.com/watch?v=VIDEO_ID" \
    --mode local \
    --output-json ./output/results.json
```

---

## ⚙️ CLI Parameter Reference

| Flag | Default | Description |
|:---|:---|:---|
| `url` | *Required* | YouTube URL (`/watch`, `/shorts`, `/live`), `file://` URI, or local filepath. |
| `--mode` | `local` | `local` (offline Intel Arc / GPU + faster-whisper) or `api` (MuAPI). |
| `--num-clips` | `3` | Number of top viral highlights to render. |
| `--resolution` | `4k` | Output vertical resolution: `4k` (2160x3840 @ 35M) or `1080p` (1080x1920 @ 15M). |
| `--framing` | `split_stack` | `split_stack`, `smart_focus`, `center`, `fit_blur`, `zoom_blur`. |
| `--no-zoom` | `False` | Disable automated dynamic viral zoom punches. |
| `--cookies` | `None` | Path to Netscape cookie file to bypass YouTube 403 Forbidden. |
| `--timeout` | `1800.0` | Polling and download timeout in seconds for long videos. |
| `--guard-band`| `45.0` | Minimum separation gap between clips in seconds. |
| `--format` | `2160` | Ingest quality selector (`720`, `1080`, `2160`, `4k`). |
| `--output-json` | `None` | Filepath to write structured output metadata. |

---

## 🐍 Python Library Usage

```python
from shorts_generator import generate_shorts

result = generate_shorts(
    youtube_url="https://www.youtube.com/watch?v=4jwUXV4QaTw",
    mode="local",
    num_clips=3,
    resolution="4k",
    framing="split_stack",
    burn_subtitles=True,
    master_audio=True
)

for short in result["shorts"]:
    print(f"Clip: {short['clip_url']} | Score: {short['score']}")
    print(f"Hook: {short['hook_sentence']}")
```

---

## 🛡️ Security Advisory & Safe Service Deployment (Issue #78)

When embedding this repository as a backend service or multi-user web application:
1. **Origin Allowlist**: Remote video downloads strictly enforce an origin allowlist (`youtube.com`, `youtu.be`) in `url_validation.py`.
2. **SSRF & Private Network Mitigation**: Private IP ranges (`10.0.0.0/8`, `192.168.0.0/16`, `127.0.0.0/8`) and link-local cloud metadata endpoints (`169.254.169.254`) must be blocked at your network gateway.
3. **Local File Ingestion**: In multi-tenant environments, restrict `_resolve_local_path` or sanitize `file://` URLs to prevent unauthorized local file access.
4. **HTTPS Enforcement**: `MUAPI_BASE_URL` strictly validates HTTPS protocol and rejects credential embedding in URLs.

---

## 🧪 Running Tests

The test suite includes comprehensive triad unit tests (Positive, Negative, Edge-Case):

```powershell
pytest tests/ -v
```

All 58+ tests pass cleanly covering framing, viral zooms, Intel Arc runner, yt-dlp 403 bypass, podcast tracking, and live streams.

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
Feel free to fork, customize, and deploy commercially!
