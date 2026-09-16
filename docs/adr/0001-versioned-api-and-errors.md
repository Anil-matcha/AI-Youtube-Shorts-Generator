# ADR 0001: Versioned API and stable errors

- Status: accepted (v1 beta)
- Date: 2026-09-15

## Decision

Expose `/api/v1` as the supported integration surface while routing it through
the existing handlers.  Keep `/api` for compatibility and emit a deprecation
header with a fixed sunset date.  Errors use `{error, code}` with a published
catalog; legacy clients retain their existing `http_<status>` fallback.

## Rationale

The desktop UI and older scripts should not break during beta development, but
new clients need a stable path and machine-readable failures.  A routing alias
avoids two implementations drifting while OpenAPI lists the versioned paths.
