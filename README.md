# Shorts Studio

<p align="center">
  <img src="web/static/logo.svg" alt="Shorts Studio" width="112">
</p>

<p align="center"><strong>A local-first workspace for turning long videos into polished short-form clips.</strong></p>

<p align="center">
  <a href="https://github.com/wiifhub/AI-Youtube-Shorts-Generator/releases/tag/v0.8.1">Latest release: v0.8.1</a>
  &nbsp; | &nbsp;
  <a href="https://github.com/wiifhub/AI-Youtube-Shorts-Generator/releases">Downloads</a>
  &nbsp; | &nbsp;
  <a href="https://github.com/wiifhub/AI-Youtube-Shorts-Generator/issues">Support</a>
</p>

Shorts Studio is an independent desktop and web workspace maintained by **wiifhub**. It takes a YouTube URL or a local video, finds strong moments, gives you control over the framing and captions, and renders ready-to-publish clips. Local mode keeps source media and rendered files on your computer; API mode is available when you prefer hosted processing.

## Screenshots

These screenshots are captured from the Shorts Studio application itself.

| Dashboard | Editing workspace |
| --- | --- |
| ![Shorts Studio dashboard](docs/screenshots/dashboard.png) | ![Shorts Studio editing workspace](docs/screenshots/workspace.png) |

The theme switch applies to the entire interface. The light Settings view is shown here as well:

![Shorts Studio light theme and update control](docs/screenshots/system-light.png)

## What you can do

- **Find highlights** with Whisper transcription, sentence-aware boundaries, virality scoring, hook text, and an explanation for every selected moment.
- **Edit the frame** with a face-framing toggle, manual drag positioning, crop-to-fill, fit plus blurred background, and foreground zoom.
- **Design captions** with Bold, Clean, Boxed, and Karaoke presets, custom font, size, color, safe position, word timing, SRT/VTT downloads, and optional filler-word cleanup.
- **Clean and shape audio** with silence trimming, real silent-section jump cuts, loudness normalization, background-noise reduction, and optional music.
- **Choose layouts** with a single frame or a two-panel speaker layout, plus watermark, intro, outro, and automatic thumbnails.
- **Review before committing** with a low-resolution preview that uses the same crop, captions, layout, and timestamps as the final render.
- **Manage projects** with persistent jobs, batch sources, cancellation, retry, resume-after-restart, rename, duplicate, archive, recoverable delete, and Undo last delete.
- **Export creator assets** as a ZIP containing clips, thumbnails, caption files, `metadata.json`, publishing text, and a manifest.
- **Use GPU controls** to choose Whisper model and Auto/CPU/CUDA device. CUDA is detected at runtime and safely falls back to CPU.
- **Use dark or light mode** from the top-bar switch. Your choice is saved locally and applies to panels, forms, previews, captions, timelines, dialogs, status states, and the closed screen.
- **Update in place** from the Settings view. Packaged Windows builds can download the newest release from this repository and restart without a reinstall.
- **Run without a browser** in the packaged desktop build through an embedded WebView2 window. A browser fallback remains available when WebView2 is unavailable.

## Windows installation

### Recommended: installer

1. Download [ShortsStudio-Setup-v0.8.1.exe](https://github.com/wiifhub/AI-Youtube-Shorts-Generator/releases/download/v0.8.1/ShortsStudio-Setup-v0.8.1.exe).
2. Run the installer and choose whether to create a desktop shortcut.
3. Start **Shorts Studio** from the Start menu or desktop.

The installer includes the native desktop shell, Python runtime, FFmpeg/FFprobe, CUDA runtime files used by supported builds, the original Shorts Studio icon, and the complete UI. Projects are written to `%LOCALAPPDATA%\ShortsStudio\output` so an install under `Program Files` remains writable.

Windows may show SmartScreen for an unsigned build. Select **More info -> Run anyway** only when the file came from the release link above. A commercial signing certificate is not bundled with this open release.

### Portable ZIP

1. Download [ShortsStudio-v0.8.1-windows.zip](https://github.com/wiifhub/AI-Youtube-Shorts-Generator/releases/download/v0.8.1/ShortsStudio-v0.8.1-windows.zip).
2. Extract the entire ZIP to a folder (do not run the EXE inside the archive).
3. Run `unblock_and_start.bat`, or double-click `ShortsStudio.exe` after Windows has unblocked the files.

The ZIP is self-contained and can be moved to another Windows 10/11 64-bit machine. Keep the folder together; the EXE, `_internal`, FFmpeg, and CUDA DLLs are a single package.

### Updating from inside the app

Open **Settings** in the sidebar (or use the top-bar **Settings** button) and click **Check for updates**. If a newer packaged release is available, the button changes to **Install vX.Y.Z**. Confirm once; Shorts Studio downloads the Windows package, preserves your projects and `.env`, replaces the package, and restarts. If you are running from source, the same control opens the GitHub release page so you can update the source checkout safely.

Settings also includes:

- **Appearance:** Dark, Light, or system theme, plus a reduced-motion preference.
- **Rendering defaults:** Local/API mode, output resolution, caption preset, aspect ratio, face framing, and a default save folder for new projects.
- **Storage & privacy:** The active output path, free space, an **Open output folder** shortcut, and a local-first processing explanation.
- **Runtime diagnostics:** FFmpeg, FFprobe, Whisper, CUDA, disk space, and concurrency status with a refresh action.

## Source setup

Source mode is useful for development or for running on a non-Windows host. Python 3.10 or newer is required.

```powershell
git clone https://github.com/wiifhub/AI-Youtube-Shorts-Generator.git
cd AI-Youtube-Shorts-Generator
.\install_windows.bat
.\start_studio.bat
```

`install_windows.bat` creates `venv`, installs the local dependencies, and copies `.env.example` to `.env` when needed. The launcher opens an embedded WebView2 window when possible. To force the browser fallback:

```powershell
.\venv\Scripts\python.exe launcher.py --browser
```

You can also run the server directly:

```powershell
.\venv\Scripts\python.exe -m web.app
# open http://127.0.0.1:7860
```

Use the **Quit** button in the app to stop the local server. `Ctrl+C` in the terminal also stops a source launch.

## Local and API modes

The workspace defaults to Local mode. Local mode uses `yt-dlp`, `faster-whisper`, OpenCV, and FFmpeg on your machine. Highlight ranking can use OpenAI or Gemini, or the built-in heuristic fallback when no key is configured. Local rendering does not impose a per-clip service limit, but it does use your CPU/GPU, storage, and any provider API you select.

API mode delegates download, transcription, ranking, and auto-crop to the configured MuAPI service. Add `MUAPI_API_KEY` to `.env` before choosing API mode. Provider terms, network availability, and API costs are separate from Shorts Studio.

### Optional CUDA setup

For local Whisper acceleration on a supported NVIDIA GPU:

```powershell
.\install_gpu_windows.bat
```

The script checks for `nvidia-smi`, installs a CUDA-enabled PyTorch wheel, and leaves CPU available as a fallback. In the app, select **Whisper device -> CUDA GPU**. The Settings view reports the detected device and current fallback reason.

## Configuration

Copy `.env.example` to `.env` and edit only the settings you need. Never commit `.env` or paste keys into an issue.

| Setting | Purpose | Default |
| --- | --- | --- |
| `MUAPI_API_KEY` | API mode authentication | empty |
| `LLM_PROVIDER` | Local ranking provider: `openai` or `gemini` | `openai` |
| `OPENAI_API_KEY` / `GEMINI_API_KEY` | Optional local ranking keys | empty |
| `LOCAL_WHISPER_MODEL` | `tiny`, `base`, `small`, `medium`, or `large-v3` | `base` |
| `LOCAL_WHISPER_DEVICE` | `auto`, `cpu`, or `cuda` | `auto` |
| `LOCAL_OUTPUT_DIR` | Source-mode project/output root | `output` |
| `LOCAL_BURN_CAPTIONS` | Burn captions into local MP4 files | `true` |
| `LOCAL_HEURISTIC_FALLBACK` | Rank locally without a provider key | `true` |
| `SHORTS_STUDIO_BROWSER` | Force browser fallback instead of WebView2 | `false` |
| `SHORTS_PORT` | Preferred loopback port | `7860` |
| `SHORTS_AUTO_RESUME` | Recover interrupted projects on start | `true` |
| `SHORTS_MIN_FREE_GB` | Free-space guard before a render | `0.5` |
| `SHORTS_MAX_UPLOAD_MB` | Maximum uploaded source size | `2048` |

Packaged builds keep the optional `.env` beside the executable but place writable project data under `%LOCALAPPDATA%\ShortsStudio`. A custom **Save folder** in the workspace creates named folders such as `20260910_214500_shorts_source_a1b2c3d4`.

## Command line and Python API

The CLI remains available for automation:

```powershell
.\venv\Scripts\python.exe main.py "https://www.youtube.com/watch?v=VIDEO_ID" --mode local --num-clips 3 --aspect-ratio 9:16
.\venv\Scripts\python.exe main.py "C:\Videos\talk.mp4" --mode local --output-json output\result.json
```

The source URL may be a YouTube URL, a `file://` URL, or a local path. The library entry point is `shorts_generator.generate_shorts(...)`; the result contains transcript data, ranked highlights, and rendered clip paths/URLs.

## Local web API

The loopback FastAPI service powers the desktop shell and can be used by local tooling:

| Route | Purpose |
| --- | --- |
| `GET /api/health` | Liveness check |
| `GET /api/system` | FFmpeg, storage, CUDA, model, and setup status |
| `GET /api/jobs` | List saved projects |
| `POST /api/jobs` / `POST /api/jobs/batch` | Start one or many projects |
| `GET /api/jobs/{id}` | Read progress and results |
| `POST /api/jobs/{id}/cancel` | Cancel a running project |
| `POST /api/jobs/{id}/preview` | Render a lightweight draft |
| `POST /api/jobs/{id}/clips/{index}` | Regenerate one clip with editor settings |
| `GET /api/jobs/{id}/export` | Download a project ZIP |
| `GET /api/update` | Check the latest wiifhub release |
| `POST /api/update/apply` | Download and apply a packaged update |
| `POST /api/shutdown` | Stop the local server |

All routes bind to `127.0.0.1` by default. Do not expose the service to a public network without adding your own authentication and deployment controls.

## Project layout

```text
shorts_generator/      Pipeline, ranking, transcription, and renderers
web/                   FastAPI service and Shorts Studio interface
assets/                Original icon and project artwork
installer/             Inno Setup definition
launcher.py            Browser-free desktop launcher
main.py                CLI entry point
install_windows.bat    Source dependency setup
build_portable.bat     PyInstaller portable build
build_installer.bat    Inno Setup installer build
output/                Local projects (ignored by Git)
```

## Building a release

Build from a clean Windows checkout with the local dependencies installed:

```powershell
.\venv\Scripts\python.exe -m pip install -r requirements-local.txt
.\build_portable.bat
.\build_installer.bat
```

The generated `dist`, `build`, and `release` directories are intentionally ignored by Git. Before publishing, verify the EXE starts, `/api/health` returns 200, the theme switch works in both modes, the Quit action stops the listener, and the ZIP/installer hashes match the uploaded files.

## Troubleshooting

- **The window opens in a browser:** install the Microsoft WebView2 Runtime, or set `SHORTS_STUDIO_BROWSER=false` and restart. Browser fallback is expected when WebView2 cannot load.
- **SmartScreen warns about the EXE:** use the release links above and choose `More info -> Run anyway`; the current public binaries are not commercially signed.
- **CUDA DLL or driver errors:** use Settings -> diagnostics, install/update the NVIDIA driver, rerun `install_gpu_windows.bat`, or select CPU. CPU mode remains supported.
- **No provider key:** Local mode can use the built-in heuristic fallback when `LOCAL_HEURISTIC_FALLBACK=true`; API mode requires `MUAPI_API_KEY`.
- **YouTube download errors:** try a local upload or update yt-dlp with `venv\Scripts\python.exe -m pip install --upgrade yt-dlp`.
- **Port 7860 is busy:** launch with `launcher.py --port 7861`; the desktop launcher also chooses a free loopback port automatically.
- **A render stops:** open the project again. Persisted logs, interrupted-job recovery, Retry, and recoverable output folders are designed to preserve completed work.

## Identity and contribution

This repository is the standalone **Shorts Studio** project maintained and released by **wiifhub**. Branding, UI, desktop packaging, release assets, and the creator workflow are owned and versioned here. Please open an issue with the exact release version, operating system, and a redacted log when reporting a problem.

## License

The repository does not include a separate license file yet. If you redistribute or build a commercial edition, add the license and third-party notices that match your intended distribution before publishing it.
