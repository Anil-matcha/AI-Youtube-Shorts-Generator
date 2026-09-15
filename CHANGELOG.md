# Changelog

All notable Shorts Studio changes are recorded here. Dates use ISO 8601.

## [Unreleased]

- Continue polishing the editor, provider integrations, and packaging based on
  user feedback.

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

[Unreleased]: https://github.com/wiifhub/AI-Youtube-Shorts-Generator/compare/v0.10.0...HEAD
[0.10.0]: https://github.com/wiifhub/AI-Youtube-Shorts-Generator/compare/v0.9.5...v0.10.0
[0.9.5]: https://github.com/wiifhub/AI-Youtube-Shorts-Generator/releases/tag/v0.9.5
