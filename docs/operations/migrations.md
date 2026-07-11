# Runbook — Database Migrations (dry-run & rollback)

Production persistence uses **Alembic-versioned migrations against PostgreSQL**;
`create_all` is limited to the test/offline-demo SQLite path (FR-022/023).
Production startup verifies the schema is at the migration head and fails closed
otherwise (`schema_check.assert_production_schema_ready`).

Migrations:
- `0001_feature_001_baseline` — declarative baseline matching Feature 001's schema.
- `0002_production_hardening` — ArtifactReceipt, JobIntent/JobAttempt, coverage/
  evaluator/evidence_digest columns, audit identity columns, `submitted_by`/
  `registered_by`, with legacy backfill (`legacy:feature-001`).

## Preconditions (MUST)

1. **Back up the database** before any migration touching data:
   ```bash
   pg_dump "$HARNESS_DATABASE_URL" > backup-$(date +%Y%m%dT%H%M%SZ).sql
   ```
2. **Dry-run on a COPY first** — never rehearse on production. Restore the dump
   into a scratch database and run the upgrade there.

## Dry-run on a copy

```bash
# 1. scratch DB from the backup
createdb harness_dryrun
psql harness_dryrun < backup-<stamp>.sql

# 2. inspect the pending SQL WITHOUT applying it (offline mode)
cd backend
HARNESS_DATABASE_URL=postgresql+psycopg://harness:harness@localhost:5432/harness_dryrun \
  alembic upgrade head --sql   # prints the SQL; review it

# 3. apply on the copy and confirm head
HARNESS_DATABASE_URL=postgresql+psycopg://harness:harness@localhost:5432/harness_dryrun \
  alembic upgrade head
HARNESS_DATABASE_URL=...harness_dryrun alembic current   # expect the 0002 head

# 4. smoke the app against the copy: /readyz must report schema "current"
```

The migration test suite (`backend/tests/migration/test_upgrade.py`) exercises the
empty-DB and Feature-001-baseline upgrade paths and runs in CI on PostgreSQL.

## Production upgrade

```bash
cd backend
HARNESS_DATABASE_URL=<prod> alembic current          # note the current revision
HARNESS_DATABASE_URL=<prod> alembic upgrade head
HARNESS_DATABASE_URL=<prod> alembic current          # confirm the new head
# /readyz (auditor token) → {"schema": "current"} and 200
```

The legacy backfill in `0002` sets `submitted_by`/`registered_by` on pre-Feature-002
rows to `legacy:feature-001` and computes receipts where artifacts are accessible;
non-null constraints are enforced only after backfill validation.

## Rollback

```bash
cd backend
# down one revision (0002 -> 0001). 0002's downgrade drops the added columns/
# tables (incl. goldentestset.registered_by + its index).
HARNESS_DATABASE_URL=<prod> alembic downgrade -1
HARNESS_DATABASE_URL=<prod> alembic current           # expect the 0001 baseline
```

If a downgrade would lose data you need (e.g. receipts, job intents), prefer
**restore from the pre-upgrade backup** instead:

```bash
dropdb harness && createdb harness
psql harness < backup-<stamp>.sql
```

After any rollback, the application MUST be pinned to the matching code revision —
running Feature 002 code against the `0001` schema fails the startup schema check
by design.

## Verification checklist

- [ ] Backup taken and its restore verified on a scratch DB.
- [ ] `alembic upgrade head --sql` reviewed.
- [ ] Dry-run upgrade on the copy succeeded + app smoke passed.
- [ ] Production `alembic current` shows the expected head.
- [ ] `/readyz` returns 200 with `schema: current`.
