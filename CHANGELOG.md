# Changelog

All notable Shorts Studio changes are recorded here. Dates use ISO 8601.

## [Unreleased]

## [2.1.0] - 2026-10-02

Opt-in local evidence and manual YouTube scheduling are development-preview
capabilities in this release. Real OCR is required in CI; representative creator
footage, connected-account provider behavior, and larger-model accuracy are
not yet fully verified. Authenticode signing remains intentionally deferred.

### Added

- Improved local model cards with explicit download/validation stages, live
  monotonic elapsed time, cache size and reuse details, file-worker settings,
  accessible indeterminate progress, and an explicit retry action. Active
  downloads no longer show an invented transfer percentage.
- Added explicit anonymous cold-download benchmarks using disposable Hub/Xet
  caches, immutable model revisions, bounded workers/repetitions, and child
  process deadlines. Reports separate effective artifact throughput from
  offline completeness-validation time; tokens and local paths are excluded.
- Added opt-in offline transcription benchmarks with a timeout-isolated worker,
  full lazy-decoder timing, real-time factor, and first/warm samples. Local media
  is bounded to its first 30 seconds; reports omit paths and transcript text.
  An explicit CUDA library directory can be supplied to the worker without
  changing the app or machine environment. Missing requested stages now fail
  the benchmark command instead of silently returning success.
- Added an isolated v2.1 runtime verification harness with generated footage,
  real speech analysis, searchable OCR when installed, authentication,
  evidence clearing, and clean shutdown checks. CI requires real Tesseract OCR
  on Linux and runs the speech check against the fresh Windows executable.
- Started the v2.1.0 multimodal slice with explicitly selected local Tesseract
  OCR and bundled Silero speech-activity evidence. Analysis is bounded to
  120 seconds and eight sampled frames, supports cancellation and clear,
  preserves previous evidence on failure, and makes redacted evidence searchable.
- Added a manual YouTube provider-scheduling adapter: separately approve an
  immutable clip/metadata snapshot, then acknowledge public publication and
  dispatch its initially private upload. Durable state, stale-approval checks,
  bounded retries, and read-only reconciliation prevent blind duplicate uploads
  after uncertain outcomes. Provider cancellation uses YouTube Studio.
- Added local evidence and provider-schedule review controls in the Export
  panel, including unavailable-model messages and explicit upload confirmation.
- Extended the local benchmark to 1-10 repetitions with timing summaries and
  cached-only model loading by default; network downloads require an explicit
  `--allow-download` flag.

### Changed

- Download only immutable revisions of supported public Whisper runtime files, with 1-8 bounded file
  workers and at most two simultaneous models. Cache readiness now requires a
  complete current snapshot, and download state exposes duration/cache metrics.
  Transcription reuses the discovered cache path; ONNX runtime is explicitly
  probed and collected for the packaged speech worker.

### Fixed

- Return private actionable model-download failure codes for missing
  dependencies, cache permissions, disk space, and network failures; clear
  stale failure details when retrying or removing a cache.
- Validate a model download in its actual destination instead of allowing a
  complete snapshot in another cache root to mask an incomplete target.
- Preserve active provider upload records across restart, prevent clip edits
  during dispatch, and keep unresolved provider schedules in the project library.
- Isolate VAD inference in a tracked child process to enforce cancellation and
  operation deadlines; reserve edit and upload locks before acquisition to
  prevent eviction races, and freeze publishing assets for scheduled uploads.
- Refresh owner-verified YouTube video state to resolve published/unscheduled
  entries, and route legacy scheduled confirmations through the review queue.
- Return JSON validation errors for non-finite numeric inputs instead of 500.

### Development gates

- OCR requires an existing local Tesseract installation and language data.
  Broader sound-event classification, live credentialed provider verification,
  cold-download performance measurements, and packaged release checks remain
  follow-ups. These changes are not part of the published v2.0.0 artifacts.

### Verification

- Model-download UX follow-up: 333 Python tests passed (17 browser tests
  skipped by default), then all 17 opt-in browser tests passed. Ruff, strict
  mypy, JavaScript syntax, and diff checks passed; model-manager security lint
  reported no findings. Browser coverage checks indeterminate progress,
  validation messaging, escaped errors, explicit retry, and cache-reuse details.
- Cold-download/cache follow-up: 325 Python tests passed (16 opt-in browser
  tests skipped), Ruff and strict mypy passed, and changed download code had
  zero medium/high Bandit findings. Disposable tiny and base samples passed;
  base measured 2.2927s with one file worker and 2.0411s with four. These single
  samples do not establish a concurrency speedup. Normal cache availability
  was unchanged after testing; all temporary benchmark downloads were removed.
- 2026-10-02 benchmark follow-up: 314 Python tests passed (16 opt-in browser
  tests skipped); Ruff and strict mypy passed, with no medium/high Bandit findings
  in the benchmark. Tiny-model synthetic decoding passed CPU and CUDA using
  explicitly supplied existing CUDA DLLs. CPU first/warm timings were
  0.5106s / 0.3070-0.3153s; CUDA first/warm timings were
  30.5364s / 0.1106-0.1646s. These are not accuracy measurements.
- Follow-up verification passed 309 Python tests (16 opt-in browser tests
  skipped), Ruff, strict mypy, workflow YAML parsing, and zero medium/high
  security findings in the new harness. Fresh Windows portable speech,
  authentication, evidence clearing, and clean shutdown passed; OCR was
  unavailable locally and the added remote CI gates have not yet run.
- Source verification passed 302 Python tests with 71.52% coverage; the
  separate opt-in browser run passed all 16 tests. Real local audio decoding,
  bundled Silero inference, process cancellation/deadline checks, and repeated
  cached CPU/CUDA model-load/render benchmarks passed.
- Ruff, strict mypy, Python compile, JavaScript syntax, dependency consistency,
  and diff checks passed. Bandit reported zero medium/high findings after
  model downloads were pinned to reviewed immutable upstream revisions.

## [2.0.0] - 2026-09-30

### Added

- Added the v2 performance loop: a cross-project performance and publishing
  dashboard, bounded analytics JSON import, variant comparison, and explainable
  recommendations based on completion and engagement.
- Added transparent Creator Style Memory. Approved Shorts Factory decisions and
  project settings can be learned into an inspectable, exportable local profile;
  the profile never stores source URLs, credentials, or media paths.
- Added bounded YouTube channel/playlist preview and batch queue controls. A
  creator can inspect up to 50 public videos before queueing separate local or
  API projects, with optional Shorts Factory review packages.
- Added the private Edge AI model manager for the supported faster-whisper
  catalog, including cache discovery, background downloads, status, and
  explicit confirmed removal.
- Added backup/restore coverage for the creator style profile, plus the
  dashboard, channel, style-memory, and model-management UI surfaces.
- Added the private v2 story-search foundation. Creators can search bounded
  transcript, chapter, highlight, and local visual-signal evidence while
  credential-bearing URLs and media paths are excluded from result payloads.
- Added deterministic publishing-policy preflight for platform, duration,
  HTTPS, privacy, sensitive-language, and Shorts Factory approval signals.
  Reviewable scheduler intents are private by default and never upload on their
  own; explicit approve/reject/cancel decisions are durable and auditable.
- Added observed publishing/quota telemetry and durable redacted provider
  errors. The telemetry reports only provider responses and never infers or
  bypasses a quota.
- Added `scripts/benchmark_v2.py` for a bounded model-load and synthetic
  first-render measurement, plus a Performance-view story-search control.

### Security

- Fixed the active environment's known `cryptography` and `pip` advisories by
  upgrading to `cryptography==50.0.1` and `pip==26.2.1`; the supported local,
  Docker, arm64, and package optional-dependency manifests now pin the fixed
  cryptography release.
- Added policy and scheduler bounds, malformed-timestamp tolerance, URL/secret
  redaction on search and telemetry payloads, and bounded durable provider
  error history.

### Verification

- The v2 foundation has focused route/model tests in `tests/test_v2_features.py`
  and `tests/test_v2_foundation.py`; the full release suite remains the gate
  until a new version is cut.
- Final local verification for this update passed: 209 Python tests passed, 4
  browser-only tests were skipped by default, coverage was 69.69%, the
  opt-in Playwright browser flow passed 4/4, and the focused security suite
  passed 92/92.
- Ruff, strict mypy, Python compile, Node syntax, and `git diff --check` passed.
  `pip-audit` reported no known vulnerabilities for the base, dev, local, GPU,
  Docker, arm64, and installed environments; `pip check` was clean. Bandit
  reported zero medium/high issues (the remaining low findings are existing
  intentional subprocess/exception/provider-adapter patterns).
- The fresh v2.0.0 packaged runtime smoke passed health 200, anonymous system
  rejection 401, authenticated system access 200, UI version `2.0.0`,
  authenticated shutdown, and clean process exit.
- The unsigned release artifacts have matching SHA-256 entries in
  `SHA256SUMS-v2.0.0.txt`: installer
  `FEC288BC2CA93EF4375D269D2D5E3BDE03EDE19616F7979F177CC1B3D07DA19C` and
  portable ZIP
  `445CE07E733639B8765500BBFCF6C7F6D0E5BB920760338DC34AD397CFE0DF20`.
- The CPU benchmark on this Windows workstation measured faster-whisper `tiny`
  model load at 2.115s (cached) and the synthetic 9:16 first render at 1.3402s.
  The representative CUDA run on an NVIDIA GeForce RTX 5060 Ti (16 GB,
  driver 617.14) measured tiny FP16 load at 0.9388s and the synthetic 9:16
  first render at 1.3215s. CUDA detection and the environment-selected device
  default remain unchanged; the measurements are release-planning baselines,
  not a forced hardware requirement.
- Closed the fresh v1.0.1 installer maintenance gate from an elevated Windows
  process: the isolated install completed, `/api/health` returned 200,
  anonymous `/api/system` was rejected with 401, authenticated system access
  returned 200, the installed UI reported version `1.0.1`, and authenticated
  shutdown produced a clean process exit.
- Authenticode signing is intentionally deferred. Public Windows artifacts
  remain explicitly unsigned until an owner certificate is supplied; this is
  not a blocker for the current v2 foundation work.

### Documentation

- Added the latest fork comparison's related-project links for the broader
  open-source SaaS catalog and MuAPI alternatives.

## [1.0.1] - 2026-09-25

### Security

- Scrubbed URL credentials, signed query values, basic-auth authorities, and
  session secrets from durable jobs, backups, logs, and factory manifests.
- Hardened authenticated deployments against loopback/host confusion, browser
  requests that reach loopback builds, crafted job identifiers, weak secrets,
  and update downloads that do not come from the verified release asset.

### Fixed

- Made upload idempotency, retry admission, render scratch files, clip
  revisions, and cancellation run generations safe under concurrent requests.
- Escaped hostile media paths through both FFmpeg filter parsing layers and
  kept waveform, preview, backup, and cleanup work inside their intended
  ownership boundaries.
- Derived project names from creator input or the uploaded filename instead of
  leaking a full source path into the project library.

### Verification

- Added focused remediation coverage for credential redaction, route-shaped
  render budgets, path boundaries, update provenance, concurrent writes, and
  cancellation semantics.
- Local release gates passed: 202 tests passed, 4 were skipped, coverage was
  68.46%, and Ruff, strict mypy, Bandit, Node syntax, six-manifest
  `pip-audit`, and `git diff --check` were clean.
- The v1.0.1 portable payload smoke passed health, anonymous rejection,
  authenticated system access, UI version `1.0.1`, authenticated shutdown,
  clean process exit, and bundled FFmpeg/FFprobe checks. The installer was
  compiled successfully; a fresh installer launch requires an elevated UAC
  session and could not be repeated from this non-elevated release shell.
- Main Quality Checks run `36195605900`, main Docker publish run
  `36195605940`, tag Docker publish run `36196233494`, nightly/beta run
  `36195605903`, and draft-release run `36195605951` passed.
- Windows artifact hashes match the attached manifest: installer
  `69D884AC6414E255ABC467A236D13F7B41EEC686137A6949F28E0753112D08BF` and
  portable ZIP `2C21DDE0037339F46B4930B05A536175D7228762A6F53D5A32E7AA1D01F1D259`.
- Authenticode remains intentionally unsigned because the owner certificate is
  not configured; the SHA-256 manifest is included with the release.

## [1.0.0] - 2026-09-15

### Added

- Added the beta Shorts Factory workflow: one upload or URL now creates a
  reviewable package with clip-safe URLs, hooks, captions, thumbnails, creator
  metadata, platform export plans, and durable per-clip approval checkpoints.
- Added Google/YouTube sign-in status and disconnect controls, expanded OAuth
  scopes for caption tracks, and YouTube uploads for category metadata,
  thumbnails, SRT/VTT captions, resumable transfer, quota-aware retries, and a
  credential-free audit record.
- Started the `beta/v1.0.0` branch with direct TikTok Content Posting API and
  Instagram Reels Graph API adapters, process-memory OAuth, approval-first
  idempotent uploads, durable A/B metadata variants, and analytics feedback.
- Added the `/api/v1/` contract, stable error catalog, project migrations and
  migration CLI, optional media-inclusive backups, generated OpenAPI aliases,
  beta user guide, contributing guide, and four ADRs.
- Added bounded parallel clip rendering and real-time Whisper progress through
  the existing SSE stream.

### Changed

- Direct YouTube publishing now requires an explicit human confirmation;
  unattended publishing is disabled by default and public unattended uploads
  require a separate deployment opt-in.
- Added short-lived, identity-aware response caching for read-only API
  catalogs; mutations invalidate the cache.
- Rebuilt the CPU Docker image as a cached multi-stage, non-root runtime while
  preserving the existing data volume contract.

### Verification

- Beta regression suite: 89 passed, 4 browser-only skips.
- Ruff, strict mypy, compile checks, and Node syntax checks pass locally.
- Final beta packaged smoke, unsigned signing decision, SHA-256 hashes, and
  remote Quality Checks run `35046498312` were green. The separate `beta`
  prerelease channel was published with the verified ZIP, installer, and hash
  manifest before this production release.
- Production commit `0bbf638` was merged to `main` and tagged `v1.0.0` only
  after main Quality Checks run `35049226780` and Docker publish run
  `35049226814` passed; the tag-triggered Docker publish run `35050190484`
  also passed.
- A fresh production packaged-runtime smoke served UI version `1.0.0` and
  passed health, authenticated system, API-version, YouTube OAuth, error
  catalog, and authenticated shutdown/process-exit checks.
- The production ZIP and installer were rebuilt from `0bbf638`, matched the
  attached SHA-256 manifest, and remain explicitly unsigned because the owner
  certificate is not configured.

## [0.11.3] - 2026-09-15

### Fixed

- Windows portable builds now require and collect the dynamically imported
  Local-mode runtime packages (`faster_whisper`, `ctranslate2`, `yt_dlp`, and
  OpenCV), preventing packaged CPU/GPU renders from failing after launch.
- Setup diagnostics now checks CTranslate2 as part of the CPU Whisper runtime,
  and the UI distinguishes a ready CPU fallback from missing dependencies.
- Added a packaging regression test covering the Local-mode runtime imports.

### Verification

- Fresh packaged-runtime API health, anonymous rejection, authenticated system
  access, Local-mode readiness, and authenticated shutdown all pass.
- A real packaged Local render completed with `Whisper device=cpu`.
- The fresh installer smoke also passed with the same authenticated CPU checks.
- Windows Authenticode was intentionally not applied: the owner-controlled
  certificate is not configured. SHA-256 verification remains available in the
  release manifest, and the opt-in signed-build workflow is preserved.

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
- Updated the amd64 Docker image to security-fixed Pillow 12.3.0; the arm64
  image remains pinned to 12.2.0 until an aarch64 wheel is published.

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

[Unreleased]: https://github.com/wiifhub/AI-Youtube-Shorts-Generator/compare/v2.0.0...HEAD
[2.0.0]: https://github.com/wiifhub/AI-Youtube-Shorts-Generator/compare/v1.0.1...v2.0.0
[1.0.1]: https://github.com/wiifhub/AI-Youtube-Shorts-Generator/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/wiifhub/AI-Youtube-Shorts-Generator/compare/v0.11.3...v1.0.0
[0.11.3]: https://github.com/wiifhub/AI-Youtube-Shorts-Generator/compare/v0.11.2...v0.11.3
[0.11.2]: https://github.com/wiifhub/AI-Youtube-Shorts-Generator/compare/v0.11.1...v0.11.2
[0.11.1]: https://github.com/wiifhub/AI-Youtube-Shorts-Generator/compare/v0.10.2...v0.11.1
[0.10.0]: https://github.com/wiifhub/AI-Youtube-Shorts-Generator/compare/v0.9.5...v0.10.0
[0.9.5]: https://github.com/wiifhub/AI-Youtube-Shorts-Generator/releases/tag/v0.9.5
