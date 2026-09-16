# ADR 0003: Approval-first multi-platform publishing and feedback

- Status: accepted (v1 beta)
- Date: 2026-09-15

## Decision

Use official platform APIs only.  YouTube remains resumable and idempotent;
TikTok uses Content Posting API file upload; Instagram Reels uses Meta's media
container flow and requires a public HTTPS video URL.  OAuth/access tokens are
process-memory-only.  Every upload requires an explicit confirmation and is
recorded in the project audit list.  Analytics observations are append-only,
validated, and compared per A/B variant.

## Rationale

Platform policies and media requirements differ, so a provider-neutral manual
plan is retained as a safe fallback.  The feedback loop must remain explainable
and must not silently rewrite a creator's future selections.
