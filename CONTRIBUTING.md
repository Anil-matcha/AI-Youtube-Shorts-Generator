# Contributing to Shorts Studio

The `beta/v1.0.0` branch is the production-readiness track.  Keep changes
small, tested, and reversible; never commit credentials, generated media,
model caches, or release artifacts.

## Development setup

```powershell
python -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\venv\Scripts\python.exe -m pytest -q
.\venv\Scripts\python.exe -m ruff check .
.\venv\Scripts\python.exe -m mypy
```

Local rendering dependencies are optional.  Install
`requirements-local.txt` when a test or feature needs yt-dlp, faster-whisper,
OpenCV, or the local LLM adapters.

## API and data changes

- Add new HTTP behavior under `/api/v1` compatibility aliases and keep the
  legacy `/api` contract working until its documented sunset.
- Use a stable error code from `web.api_contract.ERROR_CATALOG` for new errors.
- Any persisted project-field change must add a pure migration in
  `web/migrations.py`, a regression test, and a backup/restore test.
- Never persist API keys, OAuth tokens, cookies, or signed media URLs.

## Tests and review

Run the focused tests first, then the full suite.  Provider integrations must
use mocked HTTP responses in unit tests and preserve approval/idempotency
semantics.  Rendering tests should use small fixtures and clean their output.
Document design trade-offs in `docs/adr/` and update `CHANGELOG.md`,
`ROADMAP.md`, and `TODO.md` for user-visible or workflow changes.

## Pull requests

Describe the user outcome, migration impact, security boundary, and test
commands.  CI must pass before merge.  Release tags are cut only after fresh
packaged-runtime smoke tests, the signing decision, asset hashes, and a clean
repository check.
