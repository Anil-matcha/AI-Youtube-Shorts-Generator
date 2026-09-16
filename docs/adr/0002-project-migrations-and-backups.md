# ADR 0002: Pure project migrations and bounded backups

- Status: accepted (v1 beta)
- Date: 2026-09-15

## Decision

Project records carry a schema version and a separate project-format version.
`web.migrations.migrate_job_record` performs deterministic v0 -> v4 upgrades and
records a bounded migration history.  Startup applies safe migrations, while
`scripts/migrate_data.py` provides dry-run and backup-before-apply operations.
Metadata backups are always credential-free; media inclusion is explicit and
bounded to 512 MB.

## Rationale

SQLite and JSON mirrors must recover consistently across desktop upgrades.
Keeping migrations pure lets the application, CLI, and restore path share the
same safety checks.
