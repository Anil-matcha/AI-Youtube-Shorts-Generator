# ADR 0004: Bounded parallel rendering, streaming progress, and caching

- Status: accepted (v1 beta)
- Date: 2026-09-15

## Decision

Render independent highlights with a bounded thread pool while retaining the
FFmpeg process semaphore and deterministic result order.  Whisper emits segment
progress into the existing SSE job stream.  Small read-only JSON catalogs use a
short process-local TTL cache, cleared after mutations.

## Rationale

Parallel clips improve throughput without allowing unbounded FFmpeg children.
Progress callbacks provide real-time feedback without a second transport, and
short caching reduces repeated UI calls without making project state stale.
