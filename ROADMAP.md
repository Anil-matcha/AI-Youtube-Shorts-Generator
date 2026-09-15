# Shorts Studio Upgrade Roadmap

**Current local tag:** v0.10.2 (not pushed or publicly released)
**Next implementation target:** v0.10.3 (security and production hardening)
**Last updated:** 2026-09-15

The actionable implementation list now lives in [TODO.md](TODO.md). This
roadmap tracks release milestones and verified state; it is not a second
unordered TODO list.

---

## Completed (v0.10.0)

- [x] Modularize `web/app.py` into route modules (`editor_routes.py`, `feature_routes.py`, `job_routes.py`, `system_routes.py`)
- [x] Add security module (`web/security.py`)
- [x] Add typed models (`web/models.py`)
- [x] Add dedicated job store (`web/job_store.py`)
- [x] Add cost tracking (`shorts_generator/costs.py`)
- [x] Add publishing module (`web/publishing.py`)
- [x] Add update service (`web/update_service.py`)
- [x] Expand test suite (clipper, costs, highlights, job control, models, muapi, pipeline, publishing, security, transcriber, update service)
- [x] Add `docker-compose.yml` with CPU/GPU profiles
- [x] Add `CHANGELOG.md`
- [x] Add API-token authentication and in-process rate limiting
- [x] Add durable jobs/checkpoints, restart recovery, SSE progress, and active
      process cancellation
- [x] Add editor, captions, multi-range editing, backup/restore metadata,
      storage, brand, cost, and publishing controls
- [x] Publish Windows installer/portable artifacts with SHA-256 checksums
- [x] Publish the public GitHub release and pass Quality Checks/Docker Publish

---

## v0.10.1 — Quality, Safety & Stability (tagged locally)

The v0.10.1 code and validation work is complete in this checkout and is
tagged locally. No push, GitHub release, asset upload, or public version switch
has been performed.

### Release gates
- [x] Complete TODO items T-001 through T-005 (cancellation, SSRF, graceful
      shutdown, bounded media work, and backup/cleanup boundaries)
- [x] Complete the implementation portions of TODO items T-010 through T-021
- [x] Add deterministic mocked local-pipeline, route, security, backup,
      shutdown, and render-smoke tests; run the Playwright creator flow
- [x] Re-run local compile, Ruff, mypy, pytest, browser, package, JavaScript,
      dependency, and pip-audit validation
- [ ] Cut the release only after a fresh authenticated packaged-runtime smoke
      test, certificate-backed signing decision, and clean repository state

### Already corrected in this area
- [x] MuAPI polling and retry limits are finite; remove the old indefinite-
      retry wording from future planning
- [x] API-token authentication and rate limiting are implemented; remaining
      work is remote-deployment hardening, not initial auth support
- [x] Local Ollama ranking, optional provider streaming, structured output,
      and configurable retries are implemented in the local provider path

---

## v0.10.2 — Frontend Refresh & Maintainability (tagged locally)

The v0.10.2 implementation is complete in this checkout and is tagged locally.
No push, GitHub release, or asset upload has been performed.

### Verified in v0.10.0
- [x] Persist dark/light/system theme and accent choices in the browser
- [x] Drag-and-drop local video upload
- [x] SSE job progress with polling fallback
- [x] Toasts, timeline pointer editing, and update progress feedback

### Remaining UX work
- [x] Add the Cancel action and cancelled-state rendering (TODO T-001)
- [x] Add real progress bars and skeleton states for long operations
- [x] Monitor every job in a batch instead of only the first job
- [x] Add keyboard shortcuts and persistent error notifications
- [x] Improve mobile layout and accessibility with automated checks
- [x] Evaluate WebSocket/pub-sub only if SSE scaling measurements justify it;
      the v0.10.2 probe supports retaining SSE (see
      `docs/performance/sse-scaling-v0.10.2.md`)

### Maintainability
- [x] Fix UTF-8 response handling at the server level (remove DOM workaround)
- [x] Split `app.js` into state, API, UI, editor, and timeline modules
- [x] Centralize the UI version and form/capability schema
- [x] Unify the SSE and polling connection manager

### v0.10.2 workflow additions

- [x] Optional generated-media backup with safe restore/relinking
- [x] Browser-local export presets
- [x] Bounded multi-level clip undo/redo with legacy one-level migration
- [x] Clear multi-cut ranges with adjacent/overlap merge guidance

---

## v0.10.3 — Security & Production Hardening (after v0.10.2)

### Already implemented
- [x] Optional API-token authentication via `.env`
- [x] In-process rate limiting on protected/public routes
- [x] Authenticated settings, update, and shutdown workflows

### Remaining hardening
- [x] Add CORS origin allowlists, CSP, and same-origin CSRF protection for
      cookie-authenticated mutations (TODO T-020)
- [x] Add login backoff/lockout, trusted-proxy validation, structured request
      logging, and broader provider-secret redaction
- [x] Add a non-disclosing `/healthz` endpoint and avoid absolute path details
      in public health responses
- [x] Replace abrupt shutdown with SIGTERM/Windows graceful drain and durable
      job-store closure (TODO T-003)
- [ ] Document or implement shared rate limiting for multi-process deployments

### Deployment
- [x] Add a real local render smoke test; keep packaged Windows/Docker smoke as
      a release-gate follow-up
- [ ] Add Docker multi-architecture builds only after arm64 dependency support
      is verified
- [ ] Publish Helm packaging only for a documented Kubernetes deployment target

---

## v0.11.0 — Feature Expansion

### AI/LLM Enhancements
- [x] Support the local Ollama backend for offline ranking; LM Studio remains
      an open adapter
- [ ] Add custom virality scoring prompt templates (user-editable)
- [ ] Add multi-language transcription support (auto-detect language)
- [ ] Add chapter-aware highlight detection (use YouTube chapters as hints)

### Video Processing
- [x] Expose 9:16, 1:1, and 4:5 framing choices in the workspace
- [ ] Add platform-specific 16:9/4:5 export validation and presets
- [x] Save and reuse batch watermark/branding presets
- [ ] Add background music volume auto-mixing (duck speech under music)
- [ ] Add transition effects between clips (fade, slide, zoom)

### Workflow
- [x] Persist jobs/checkpoints and restore project metadata
- [x] Add a user-facing project bundle with optional generated media and safe
      portable restore/relinking (base workflow delivered in v0.10.2)
- [ ] Add export presets (TikTok, Instagram Reels, YouTube Shorts quality settings)
- [ ] Add YouTube OAuth publishing foundation with approval-first, private-by-
      default, resumable, and scheduled uploads (TODO T-033; future G-010)
- [ ] Add explicit merge workflow for separate highlights (multi-cut ranges
      already cover several ranges within one clip)
- [x] Expand the current one-level undo to a bounded full undo/redo history

---

## v0.11.1 — Developer Experience

### Build & Release
- [ ] Add cross-platform build scripts (replace `.bat` with Python/Makefile)
- [ ] Add automated release drafting via GitHub Actions (changelog → release notes)
- [ ] Add signed builds (Windows Authenticode, macOS notarization)
- [ ] Add pre-release channel (beta/nightly builds from main)

### Code Quality
- [ ] Enforce `mypy` strict mode across all modules
- [x] Publish `pytest-cov` coverage reporting in CI (current gate: 35%)
- [ ] Raise the CI coverage gate from 35% toward 70% after the v0.10.1
      implementation baseline (currently 49% locally)
- [ ] Add `bandit` security linting to CI
- [ ] Refactor remaining type-ignored imports to proper abstractions

---

## v1.0.0 — Production Ready

### Stability
- [ ] Complete API versioning (`/api/v1/`) with deprecation policy
- [ ] Add comprehensive error codes and user-facing error messages
- [ ] Add data migration tooling (project file format upgrades)
- [x] Add metadata backup/restore for projects and settings
- [ ] Add optional media-inclusive backup/restore with versioned migrations

### Documentation
- [ ] Add OpenAPI/Swagger documentation for all endpoints
- [ ] Add user guide with screenshots for each feature
- [ ] Add developer contributing guide
- [ ] Add architecture decision records (ADRs) for key design choices

### Performance
- [ ] Add concurrent clip rendering (parallel FFmpeg workers)
- [ ] Add streaming transcription (real-time Whisper output)
- [ ] Add response caching for repeated API calls
- [ ] Optimize Docker image size (multi-stage build, layer caching)

---

## v2.0.0 — The Vision: AI-Native Video Intelligence

### Game-changing bets

These bets define the long-term differentiation of Shorts Studio. They are
future exploration items, not commitments for v0.10.x; each needs a measured
prototype, a clear privacy boundary, and a human approval path before rollout.

- [ ] **G-001 Autonomous Shorts Factory** — From one upload or URL, produce a
      reviewable package of clips, captions, hooks, thumbnails, metadata, and
      platform exports with approval checkpoints.
- [ ] **G-002 Creator Style Memory** — Learn approved pacing, hooks, caption
      language, framing, and brand rules across projects in an exportable local
      profile.
- [ ] **G-003 Performance Feedback Loop** — Import platform analytics, compare
      variants, and use measured retention and engagement to improve selection.
- [ ] **G-004 Multimodal Story Graph** — Index transcript, scenes, faces, OCR,
      sound events, and chapters for semantic search and selection rationale.
- [ ] **G-005 Live Stream Copilot** — Detect, transcribe, and queue reviewable
      clips while a live stream is still running.
- [ ] **G-006 Platform Distribution Mesh** — Create platform-specific variants,
      run compliance checks, schedule, and publish through auditable approvals.
- [ ] **G-007 Private Edge AI** — Make local model installation and fully offline
      processing easy enough that sensitive footage can stay on-device.
- [ ] **G-008 Collaborative Review Studio** — Add shareable review links,
      comments, approvals, roles, and version history without sharing secrets.
- [ ] **G-009 Open Extension Ecosystem** — Ship a versioned, sandboxed plugin
      SDK for pipeline stages, caption packs, exporters, and integrations.
- [ ] **G-010 YouTube Auto-Publish** — Integrate YouTube Data API OAuth for
      approval-first uploads, resumable transfer, metadata/thumbnails/captions,
      privacy and scheduling controls, quota-aware retries, idempotency, and an
      audit log. Public auto-publish must be an explicit opt-in.

### Autonomous Clip Factory
- [ ] **Fully autonomous pipeline** — Upload a video, walk away. The system selects the best clips, applies captions, music, transitions, and branding without human intervention.
- [ ] **A/B variant generation** — Automatically produce 2-3 variants of each clip (different hooks, pacing, music) for performance testing.
- [ ] **Performance feedback loop** — Connect to YouTube/TikTok analytics to learn which clips perform best and refine future selections.
- [ ] **Batch channel processing** — Process an entire YouTube channel's backlog in one go, auto-generating shorts from every video.

### Multi-Modal Understanding
- [ ] **Scene graph analysis** — Go beyond faces: detect objects, actions, text-on-screen, and visual context to make smarter clip selections.
- [ ] **Emotion detection** — Use facial expression analysis + voice tone analysis to find genuine emotional peaks.
- [ ] **Audience engagement prediction** — Pre-score clips using engagement prediction models trained on millions of viral shorts.
- [ ] **Cross-video knowledge** — When processing a channel, learn the creator's style and apply it consistently across all shorts.

### Platform-Aware Output
- [ ] **Platform-specific optimization** — Auto-adjust caption timing, music, pacing, and aspect ratio per platform (TikTok vs Reels vs Shorts).
- [ ] **Trend-aware selection** — Monitor trending sounds, hashtags, and formats to suggest timely clip themes.
- [ ] **Optimal posting scheduler** — Analyze audience activity patterns and recommend the best time to post each clip.
- [ ] **Multi-platform batch publishing** — One click to publish the same short to YouTube, TikTok, Instagram, and X simultaneously.

### Creative AI Features
- [ ] **AI-generated hooks** — Use LLMs to write multiple hook options for each clip and A/B test them.
- [ ] **Auto-caption styling** — Analyze the video's mood and automatically select the best caption style, font, and color.
- [ ] **Music recommendation** — Suggest royalty-free music that matches the clip's energy and emotional arc.
- [ ] **Thumbnail generation** — AI-select the most compelling frame and overlay text/graphics for platform thumbnails.
- [ ] **Voice cloning for intros** — Generate a branded intro voiceover in the creator's voice.

### Real-Time & Live Features
- [ ] **Live stream clipping** — Monitor a live stream and automatically clip highlight moments in real-time.
- [ ] **Real-time transcription** — Stream Whisper output as the video plays for instant preview.
- [ ] **WebSocket editor** — Collaborative real-time editing where multiple people can work on clips simultaneously.

### Enterprise & Scale
- [ ] **Multi-tenant deployment** — Run one instance serving multiple creators, each with their own workspace, billing, and API keys.
- [ ] **GPU cloud rendering** — Offload FFmpeg/Whisper to cloud GPUs for faster-than-real-time processing.
- [ ] **REST API for integrations** — Let third-party tools trigger shorts generation programmatically.
- [ ] **White-label solution** — Rebrandable version for agencies and media companies.
- [ ] **Usage billing dashboard** — Track rendering minutes, API calls, and storage per user.

### Plugin & Extension System
- [ ] **Pipeline plugins** — Custom processing stages (e.g., add intro animation, apply color grading, insert sponsor segments).
- [ ] **Caption plugins** — Community-contributed caption styles and animations.
- [ ] **Export plugins** — Custom export formats (GIF, WebM, vertical carousel for Instagram).
- [ ] **Integration plugins** — Connect to OBS, DaVinci Resolve, Premiere Pro for round-trip editing.

### Offline-First & Privacy
- [ ] **Fully offline mode** — Every feature works without internet using local Whisper, local LLMs, and local rendering.
- [ ] **On-device processing** — Run on a user's machine without any data leaving their network.
- [ ] **Encrypted project files** — End-to-end encrypted project files for secure collaboration.
- [ ] **GDPR compliance tools** — Automatic PII detection and redaction in transcripts and videos.

---

## Future Ideas (Backlog)

- Browser extension for one-click YouTube → Shorts
- Mobile companion app (React Native / Flutter)
- Cloud rendering mode (offload FFmpeg to GPU cloud)
- Collaborative workspace (multi-user projects)
- AI-generated thumbnail suggestions
- A/B testing for clip variants (upload multiple, track performance)
- Integration with YouTube/TikTok/Instagram APIs for direct publishing
- Plugin system for custom processing pipelines
- AI-powered aspect ratio detection (find the subject, crop intelligently)
- Auto-generate chapter markers for YouTube from transcript
- Multi-cam support (switch between camera angles in the source video)
- Subtitle translation (generate shorts in multiple languages)
- Audio description track generation for accessibility
- Clip remixing (combine clips from different videos into a compilation)
- AI-powered video editing assistant (chat-based editing commands)

---

## Inline TODO Marker Inventory

The canonical backlog is [TODO.md](TODO.md). The source currently contains
**2 inline markers in 1 file**; the count below is a snapshot for cleanup
tracking, not a second backlog.

| File | Count | Focus |
|------|-------|-------|
| `web/static/app.js` | 2 | Encoding fix and module splitting |

---

## Notes

- **Priority:** P0 safety/recovery → P1 quality/security/release confidence → P2 UX/maintainability → P3 features
- **Release cadence:** Aim for monthly minor releases, weekly patches for critical fixes
- **Breaking changes:** Defer to v1.0.0; no API breaks before then
- **Dependency updates:** Review quarterly via `pip-audit`; pin to known-good versions and test the Starlette TestClient dependency warning
- **TODO cleanup:** Close the matching TODO.md item only after code, tests, and the relevant runtime smoke check pass; record release work in `CHANGELOG.md`
