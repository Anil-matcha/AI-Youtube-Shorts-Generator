# Shorts Studio TODO

**Current local tag:** v0.10.1 (not pushed or publicly released)
**Implementation target:** v0.10.2 (next; planning only)
**Last reviewed:** 2026-09-15

This is the canonical implementation backlog. Inline `TODO` comments should
point to an item here; completed capabilities belong in `ROADMAP.md` rather
than remaining as open TODOs.

## v0.10.1 completion record

- [x] **T-001 Cancellation UX and semantics** - Added queued/running Cancel
  controls, a distinct cancelled state, cancellation-aware worker admission,
  active-process termination, and API/UI regression coverage.
- [x] **T-002 SSRF and egress controls** - Added YouTube/administrator host
  allowlists, DNS answer validation for private/reserved networks, redirect
  filtering, and invalid-host/security tests.
- [x] **T-003 Graceful shutdown** - `/api/shutdown` now coordinates worker
  cancellation, persists interrupted checkpoints, closes/reopens SQLite safely,
  and signals the bound Uvicorn server; packaged smoke remains a release gate.
- [x] **T-004 Bounded media work** - Preview and waveform rendering now share
  cancellation, tracked child processes, timeouts, and a media semaphore; SSE
  polling is an async generator.
- [x] **T-005 Backup and cleanup boundaries** - Backups/export manifests redact
  media URLs, cleanup is limited to inactive job-owned caches, and archive
  validation closes its ZipFile on every explicit rejection path.

## P1 - quality, security, and release confidence

- [x] **T-010 Integration coverage** - Added deterministic mocked local-pipeline,
  security, quality, render-smoke, route, backup, and shutdown tests plus the
  Playwright creator flow (60 Python tests pass; local coverage is 49%). The
  70% ratchet remains a v0.11 quality target rather than a release blocker.
- [x] **T-011 Test-client dependency** - Validated the pinned FastAPI/Starlette
  and developer client set across the supported Python matrix; the test suite
  runs without the prior client warning.
- [x] **T-012 Provider retry reliability** - Retry counts/delays are configurable
  for OpenAI, Gemini, Ollama, and MuAPI, with transient HTTP handling and
  cancellation-aware backoff/polling.
- [x] **T-013 Highlight quality controls** - Array-first JSON, duration bounds,
  chunk/overlap/dedupe controls, and clip-count limits are configurable and
  covered by tests.
- [x] **T-014 Pipeline configuration** - Added typed `PipelineConfig`, safe
  environment validation/profile selection, and shared encoding, output,
  FFmpeg, logging, and temporary-directory settings.
- [x] **T-015 Local model portability** - Added conservative hardware-aware
  Whisper selection and explicit guidance/errors for unsupported DirectML,
  ROCm, and MPS paths.
- [x] **T-016 Visual detection quality** - Added configurable Haar/DNN
  thresholds, profile cascades, invalid-mode warnings, and a detector plugin
  hook with smoothing controls.
- [x] **T-017 Clipper configuration** - Added configurable retries, caption
  presets, smoothing, encoding/audio filters, thumbnail position, output names,
  and multi-range merge tolerance.
- [x] **T-018 LLM provider ergonomics** - Added cached clients, structured JSON
  responses, optional streaming, token limits, and a local Ollama backend.
- [x] **T-020 Remote-deployment hardening** - Added explicit CORS origins, CSP,
  same-origin CSRF checks for cookie mutations, login backoff, trusted-proxy
  handling, structured request logs, broader redaction, and `/healthz`.
- [x] **T-021 Packaging reproducibility** - Centralized the version, pinned the
  GPU installer, expanded FFmpeg discovery, added a real render smoke test,
  and enabled CI SBOM/provenance generation. Authenticode signing remains an
  opt-in release operation requiring the owner's certificate.

## P2 - v0.10.2 UX and maintainability

This is the active v0.10.2 scope. Implement these items with code, tests, and
the relevant runtime smoke check before marking them complete.

- [ ] **T-030 Frontend modularization** - Split `web/static/app.js` into state,
  API, UI, editor, and timeline modules; fix response encoding at the server;
  add progress bars, skeletons, toasts, keyboard navigation, and batch-job
  monitoring.
- [ ] **T-031 Editing and export workflow** - Add durable project/media backup
  options, export presets, multi-level undo/redo, and a clear multi-cut/merge
  workflow.
- [ ] **T-032 Deployment targets** - Add multi-architecture Docker support only
  after dependency feasibility is proven, then consider GPU CI and Helm
  packaging for a documented deployment target.

## P3 - feature expansion

- [x] Local Ollama backend and fully offline ranking path (LM Studio remains open)
- [ ] Custom virality prompts, multi-language output, and chapter-aware clips
- [ ] Additional aspect ratios, ducking, transitions, and platform presets
- [ ] Direct publishing integrations, analytics feedback, and A/B variants
- [ ] **T-033 YouTube publishing foundation** - Connect a channel with OAuth,
  keep uploads private or unlisted by default, support resumable upload and
  scheduling, and expose an approval queue before public publishing.
- [ ] Plugin, mobile, collaboration, and cloud-rendering systems

## Game-changing future bets (v2+)

These are deliberately larger than normal feature work. Each bet should have
a measurable creator outcome, a privacy model, and a staged prototype before
it becomes a committed release milestone.

- [ ] **G-001 Autonomous Shorts Factory** - Turn one upload or URL into a
  reviewable package of clips, captions, hooks, thumbnails, metadata, and
  platform exports with human approval checkpoints.
- [ ] **G-002 Creator Style Memory** - Learn a creator's approved pacing, hooks,
  caption language, framing, and brand rules across projects, with transparent
  controls and an exportable local profile.
- [ ] **G-003 Performance Feedback Loop** - Import platform analytics, compare
  clip variants, and use measured retention/engagement to improve future
  highlight selection and packaging instead of relying only on generic scores.
- [ ] **G-004 Multimodal Story Graph** - Index transcript, scenes, faces, OCR,
  sound events, and chapters so creators can search a video semantically and
  see why a moment was selected.
- [ ] **G-005 Live Stream Copilot** - Detect moments during a live stream,
  transcribe with low latency, and produce reviewable clips while the stream
  is still running.
- [ ] **G-006 Platform Distribution Mesh** - Generate platform-specific
  variants, run compliance checks, schedule releases, and publish through
  official APIs with an auditable approval queue.
- [ ] **G-007 Private Edge AI** - Offer a one-click offline model manager and
  fully local pipeline so sensitive footage never needs to leave the creator's
  machine or network.
- [ ] **G-008 Collaborative Review Studio** - Add shareable review links,
  comments, approvals, roles, and version history without exposing source
  media or credentials.
- [ ] **G-009 Open Extension Ecosystem** - Provide a versioned plugin SDK and
  sandbox for pipeline stages, caption packs, exporters, and integrations.
- [ ] **G-010 YouTube Auto-Publish** - Add YouTube Data API OAuth with a safe
  approval-first flow, resumable uploads, title/description/tags/category,
  thumbnails and captions, privacy and publish-time controls, quota-aware
  retries, idempotency, and an audit log. Never auto-publish publicly without
  an explicit user setting and visible confirmation.

## Verified complete or corrected in the v0.10.1 implementation

- Durable SQLite jobs/checkpoints with restart recovery
- SSE progress with a polling fallback
- Active-process cancellation API and route modularization
- API-token authentication and rate limiting
- Editor, captions, multi-range editing, brand/publishing controls
- Metadata backup/restore and storage controls
- MuAPI retry and polling timeouts are finite; the old "retries indefinitely"
  roadmap item is stale
- Windows installer/portable build scripts, checksums, and passing CI workflow
  definitions (the v0.10.1 release itself is intentionally not published)

## Backlog hygiene

- Keep one canonical item ID per open concern and link inline comments to it.
- Mark an item complete only after code, tests, and the relevant packaged or
  deployment smoke check pass; certificate-dependent signing and publishing are
  release-only actions.
- Do not treat a UI test that intercepts every `/api/**` request as endpoint
  integration coverage; the browser test is recorded as creator-flow coverage.
