# v1.0.0 Beta release-gate evidence

Last updated: 2026-09-15

This document records beta validation only. It does not authorize or create a
`v1.0.0` tag, GitHub release, or public artifact publication.

## Artifacts

The artifacts were rebuilt from the beta implementation tree after the final
source hardening changes:

| Artifact | SHA-256 |
| --- | --- |
| `ShortsStudio-v1.0.0-beta-windows.zip` | `2399ABECAB1E90C605680D9DB2032E276218D45C1FB36C5E53218E91A8CBC0DF` |
| `ShortsStudio-Setup-v1.0.0-beta.exe` | `D11D31985FB5C43B64098D28C8AFCFCB915112CEF35A21E72F3CE4CDF655CDE9` |

The ZIP opens successfully and contains 3,928 entries, including the
self-contained executable, `.env.example`, bundled media runtime, and
`_internal/web/factory.py`.

## Packaged-runtime smoke

Fresh portable EXE: `dist/ShortsStudio/ShortsStudio.exe`.

- Temporary API token authentication was enabled; no real credentials were
  used.
- `/api/v1/health`: 200.
- Anonymous `/api/v1/system`: 401.
- Authenticated `/api/v1/system`: 200, `X-API-Version: v1`, 2 render workers,
  10-second response-cache TTL.
- Authenticated `/api/v1/youtube/oauth/status`: 200.
- Authenticated `/api/v1/errors`: 200, `X-API-Version: v1`.
- Authenticated `POST /api/shutdown`: 200; the packaged process exited.
- Temporary data and process state were removed after the smoke.

## Signing decision

`WINDOWS_CODESIGN_CERT` was not configured and `signtool` was not available on
the validation host. `scripts/sign_artifacts.py` was run against the beta
installer and portable EXE and produced `status: unsigned`; both files report
`NotSigned` through `Get-AuthenticodeSignature`.

Decision: keep this beta artifact explicitly unsigned and distribute/verify it
only by the recorded SHA-256 values. A certificate-backed signed build remains
opt-in and must be produced by the owner-controlled signed-build workflow before
any signed public release.

## Local validation

- Ruff: pass.
- strict mypy: pass (36 source files).
- Bandit: no medium/high issues.
- Python compileall and Node syntax checks: pass.
- Pytest: 89 passed, 4 browser-only tests skipped because `RUN_BROWSER_E2E=1`
  was not enabled locally.

## Final remote/repository gates

- Remote Quality Checks run `35046196358`: success. The four Python versions,
  Windows packaged-runtime smoke, Docker runtime, Compose, Helm, arm64
  dependency, and Playwright/accessibility jobs all passed.
- The final beta branch commit tested by that run is `b56be82`.
- At the time of that run, the local and remote `beta/v1.0.0` branch SHA matched
  `b56be82`; the worktree was clean.
- The tracking-doc update that follows is documentation-only and does not
  change packaged runtime code or the recorded artifact hashes.
- No `v1.0.0` tag or public release is permitted by this beta gate.
