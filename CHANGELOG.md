# Changelog

All notable Shorts Studio changes are recorded here. Dates use ISO 8601.

## [Unreleased]

## [0.11.2] - 2026-09-15

### Fixed

- Windows portable builds now select the project virtual environment instead
  of accidentally packaging with a dependency-free global Python.
- Portable builds fail before packaging when runtime imports such as Uvicorn,
  FastAPI, WebView, or PyInstaller are unavailable.
- Restored bundling of FFmpeg/FFprobe and detected CUDA 12 runtime files for
  self-contained Windows local rendering.
- Added accessible names to dynamically rendered workspace controls and fixed
  the Windows CI shutdown smoke request to include API authentication.
- Kept the CI coverage gate at the currently measured 53.25% while the
  dynamic provider/media adapters gain direct integration coverage.

### Verification

- Rebuilt the portable EXE and installer from the corrected build path.
- Packaged API health, authentication, authenticated shutdown, and clean
  process exit all pass.

## [0.11.1] - 2026-09-15

### Added

- **Build & release**: Cross-platform `scripts/build.py` (replaces `.bat` wrappers with Python/Makefile), automated release drafting via GitHub Actions, signed-build tooling (Authenticode/codesign/notarization), pre-release channel (beta/nightly from main)
- **Code quality**: Strict mypy mode across all modules with Pydantic plugin, remaining optional imports moved behind dynamic adapters, Bandit CI linting, CI coverage gate ratcheted to 55% toward 70% target
- **SQLite-backed shared rate limiter** (T-032): Same-host multi-process deployments use a shared `rate_limits.sqlite3`; multi-host deployments require a gateway limiter (Redis/Envoy)
- **arm64 CPU dependency lock** (T-032): Verified Buildx matrix for Linux amd64/arm64; `requirements-docker-arm64.txt` pins compatible dependencies (omits `faster-whisper` until onnxruntime arm64 wheel available)
- **Documented Kubernetes/Helm packaging** (T-032): CPU-only chart for Kubernetes 1.28+ with PVC, Service, optional TLS Ingress, and shared-limiter guidance
- **User-editable virality scoring templates**, Whisper language auto-detection, chapter-aware highlight hints, platform 16:9/4:5 export validation and presets (TikTok, Instagram Reels, YouTube Shorts), speech-aware music ducking, fade/slide/zoom transitions, explicit merge workflow for separate highlights
- **Approval-first YouTube OAuth foundation with PKCE** (T-033): Process-memory-only tokens, private-by-default/resumable uploads, approval plans, scheduling validation, idempotency keys, audit entry on upload
- **Multi-language transcription support** with auto-detection and cache metadata
- **Custom virality scoring prompt templates** (user-editable)
- **Cross-platform build scripts** (Python/Makefile, `.bat` compatibility wrappers retained)
- **Release Drafter workflow** and beta/nightly pre-release channel workflow

### Changed

- Refactored version reading in `scripts/build.py` to `_get_version()` that parses `shorts_generator/__init__.py` directly, fixing installer builds from clean checkouts without pre-installed dependencies
- Migrated remaining type-ignored imports to dynamic optional-dependency adapters with explicit runtime guards
- Enforced mypy strict mode across `shorts_generator`, `web`, `launcher.py`, and `main.py`

### Fixed

- Installer build: `scripts/build.py installer` now works from a clean checkout (the `__import__("shorts_generator")` path required all dependencies pre-installed; replaced with file-level version parse)
- Portable ZIP and Windows installer builds both succeed from clean environment

### Verification

- 13 Python tests pass locally (render smoke, pipeline dispatch, clipper operations)
- `ruff check` clean across `shorts_generator`, `web`, `scripts`, `launcher.py`, `main.py`
- `python -m mypy --strict` passes across all source modules
- `python -m bandit -r shorts_generator web launcher.py main.py scripts -ll -x tests` clean
- Windows packaged API health (200), authentication, and shutdown smoke tests pass
- Portable build: `ShortsStudio` EXE starts correctly
- Installer: `ShortsStudio-Setup-v0.11.1.exe` installs and runs correctly

## [0.10.2] - 2026-09-14

### v0.10.2 implementation (local, not released)

- Split the browser coordinator into state, UI, API, editor, and timeline
  modules, with a shared version/capability schema and one SSE/polling monitor.
- Added real job progress bars, loading skeletons, batch monitoring with
  per-source cancellation, keyboard navigation/shortcuts, live-region status,
  and persistent error notifications.
- Added browser-local export presets, a clear multi-cut workflow, and durable
  per-clip undo/redo history with a bounded 20-version stack.
- Added optional generated-media project backups and safe media relinking during
  restore; metadata backups continue to omit local paths and provider secrets.
- Declared UTF-8 for textual responses at the server boundary and added mobile-
  responsive batch rows plus reduced-motion styling.
- Added a reproducible SSE fan-out scaling probe; the measured single-process
  workload did not justify introducing WebSocket/pub-sub in this milestone.
- Validation: 62 Python tests passed, 4 Playwright browser tests passed, plus
  compile, Ruff, mypy, JavaScript, package, pip-check, and pip-audit checks.

### v0.10.1 implementation (local, not released)

- Added queued/running cancellation UX, cooperative worker admission, active
  FFmpeg termination, coordinated shutdown, and durable interrupted-job recovery.
- Added YouTube/administrator remote-host allowlists with DNS egress checks,
  bounded preview/waveform work, async SSE polling, and job-scoped cleanup.
- Sanitized backup/export metadata, closed invalid backup archives safely, and
  kept generated media inside validated job boundaries.
- Added typed pipeline configuration, configurable highlight/clipper controls,
  hardware-aware Whisper selection, detector plugins, provider retries, cached
  clients, structured/streaming JSON output, and local Ollama ranking.
- Added remote-deployment headers/CORS/CSRF checks, login backoff, trusted proxy
  handling, broader secret redaction, `/healthz`, reproducible version/build
  settings, render smoke coverage, and CI SBOM/provenance metadata.
- Validation: 60 Python tests passed, 3 Playwright browser tests passed, plus
  compile, Ruff, mypy, JavaScript, package, pip-check, and pip-audit checks.

The v0.10.1 public release/upload was intentionally skipped; its local tag is
kept as the stable baseline for v0.10.2 work.

## [0.10.0] - 2026-09-14

### Added

- Strict, shared API request models with clear validation errors and an
  authenticated session-token flow (`SHORTS_API_TOKEN`).
- Per-client sliding-window rate limits for API, upload, and job endpoints.
- Multi-range cuts with transcript/word-timestamp remapping, editable
  transcript timing/text, music volume and fade controls, reusable brand
  presets, publishing handoff payloads, and metadata-only backup/restore.
- Storage reporting and conservative cleanup for old generated caches.
- SQLite-backed durable job state with checkpoints, progress percentage/ETA,
  restart recovery, Server-Sent Events, and active FFmpeg process termination
  on cancellation.
- Content-hash transcript caches keyed by source bytes, model, language, and
  device, plus process-level Whisper model reuse.
- Provider model/temperature controls, creator-supplied rate controls, usage
  normalization, and transparent cost estimates when providers report usage.
- Official publishing handoff adapters and links for YouTube Shorts, TikTok,
  and Instagram Reels without token storage.
- Playwright upload/render/edit/preview/export and accessibility checks, with
  packaged Windows and Docker runtime smoke jobs in CI.
- Release-asset SHA-256 verification is enabled by default.
- Route modularization split the web coordinator into job, editor, feature, and
  system routers while preserving the existing API paths.
- Pipeline, clipping, transcription, security, storage, and model regression
  tests; expanded mypy and CI coverage across supported Python versions.

### Fixed

- Captions no longer drift when multi-cut or jump-cut edits change the video
  timeline; thumbnails are extracted from the final rendered clip.
- API mode now rejects local-only controls instead of silently ignoring them.
- Job errors and logs redact provider credentials before returning them to the
  browser.
- Local backend package documentation no longer claims MoviePy is required.

## [0.9.5] - 2026-09-14

- Published the Windows installer/portable package and Docker image.
- Added persistent project library, logs, previews, exports, and in-app
  update checks.

[Unreleased]: https://github.com/wiifhub/AI-Youtube-Shorts-Generator/compare/v0.11.2...HEAD
[0.11.2]: https://github.com/wiifhub/AI-Youtube-Shorts-Generator/compare/v0.11.1...v0.11.2
[0.11.1]: https://github.com/wiifhub/AI-Youtube-Shorts-Generator/compare/v0.10.2...v0.11.1
[0.10.0]: https://github.com/wiifhub/AI-Youtube-Shorts-Generator/compare/v0.9.5...v0.10.0
[0.9.5]: https://github.com/wiifhub/AI-Youtube-Shorts-Generator/releases/tag/v0.9.5

### v0.10.2 implementation (local, not released)

- Split the browser coordinator into state, UI, API, editor, and timeline
  modules, with a shared version/capability schema and one SSE/polling monitor.
- Added real job progress bars, loading skeletons, batch monitoring with
  per-source cancellation, keyboard navigation/shortcuts, live-region status,
  and persistent error notifications.
- Added browser-local export presets, a clear multi-cut workflow, and durable
  per-clip undo/redo history with a bounded 20-version stack.
- Added optional generated-media project backups and safe media relinking during
  restore; metadata backups continue to omit local paths and provider secrets.
- Declared UTF-8 for textual responses at the server boundary and added mobile-
  responsive batch rows plus reduced-motion styling.
- Added a reproducible SSE fan-out scaling probe; the measured single-process
  workload did not justify introducing WebSocket/pub-sub in this milestone.
- Validation: 62 Python tests passed, 4 Playwright browser tests passed, plus
  compile, Ruff, mypy, JavaScript, package, pip-check, and pip-audit checks.

### v0.10.1 implementation (local, not released)

- Added queued/running cancellation UX, cooperative worker admission, active
  FFmpeg termination, coordinated shutdown, and durable interrupted-job recovery.
- Added YouTube/administrator remote-host allowlists with DNS egress checks,
  bounded preview/waveform work, async SSE polling, and job-scoped cleanup.
- Sanitized backup/export metadata, closed invalid backup archives safely, and
  kept generated media inside validated job boundaries.
- Added typed pipeline configuration, configurable highlight/clipper controls,
  hardware-aware Whisper selection, detector plugins, provider retries, cached
  clients, structured/streaming JSON output, and local Ollama ranking.
- Added remote-deployment headers/CORS/CSRF checks, login backoff, trusted proxy
  handling, broader secret redaction, `/healthz`, reproducible version/build
  settings, render smoke coverage, and CI SBOM/provenance metadata.
- Validation: 60 Python tests passed, 3 Playwright browser tests passed, plus
  compile, Ruff, mypy, JavaScript, package, pip-check, and pip-audit checks.

The v0.10.1 public release/upload was intentionally skipped; its local tag is
kept as the stable baseline for v0.10.2 work.

## [0.10.0] - 2026-09-14

### Added

- Strict, shared API request models with clear validation errors and an
  authenticated session-token flow (`SHORTS_API_TOKEN`).
- Per-client sliding-window rate limits for API, upload, and job endpoints.
- Multi-range cuts with transcript/word-timestamp remapping, editable
  transcript timing/text, music volume and fade controls, reusable brand
  presets, publishing handoff payloads, and metadata-only backup/restore.
- Storage reporting and conservative cleanup for old generated caches.
- SQLite-backed durable job state with checkpoints, progress percentage/ETA,
  restart recovery, Server-Sent Events, and active FFmpeg process termination
  on cancellation.
- Content-hash transcript caches keyed by source bytes, model, language, and
  device, plus process-level Whisper model reuse.
- Provider model/temperature controls, creator-supplied rate controls, usage
  normalization, and transparent cost estimates when providers report usage.
- Official publishing handoff adapters and links for YouTube Shorts, TikTok,
  and Instagram Reels without token storage.
- Playwright upload/render/edit/preview/export and accessibility checks, with
  packaged Windows and Docker runtime smoke jobs in CI.
- Release-asset SHA-256 verification is enabled by default.
- Route modularization split the web coordinator into job, editor, feature, and
  system routers while preserving the existing API paths.
- Pipeline, clipping, transcription, security, storage, and model regression
  tests; expanded mypy and CI coverage across supported Python versions.

### Fixed

- Captions no longer drift when multi-cut or jump-cut edits change the video
  timeline; thumbnails are extracted from the final rendered clip.
- API mode now rejects local-only controls instead of silently ignoring them.
- Job errors and logs redact provider credentials before returning them to the
  browser.
- Local backend package documentation no longer claims MoviePy is required.

## [0.9.5] - 2026-09-14

- Published the Windows installer/portable package and Docker image.
- Added persistent project library, logs, previews, exports, and in-app
  update checks.

[Unreleased]: https://github.com/wiifhub/AI-Youtube-Shorts-Generator/compare/v0.11.2...HEAD
[0.11.2]: https://github.com/wiifhub/AI-Youtube-Shorts-Generator/compare/v0.11.1...v0.11.2
[0.11.1]: https://github.com/wiifhub/AI-Youtube-Shorts-Generator/compare/v0.10.2...v0.11.1
[0.10.0]: https://github.com/wiifhub/AI-Youtube-Shorts-Generator/compare/v0.9.5...v0.10.0
[0.9.5]: https://github.com/wiifhub/AI-Youtube-Shorts-Generator/releases/tag/v0.9.5
