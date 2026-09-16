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

- Remote Quality Checks dispatch and conclusion: pending after the beta commit
  is pushed.
- Final branch SHA, remote branch SHA, and clean worktree: pending after the
  remote run and evidence update.
- No `v1.0.0` tag or public release is permitted by this beta gate.
