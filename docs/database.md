# HookFlow database

SQLite for local dev/tests, PostgreSQL in production (`postgresql+psycopg://...`).
Schema is created with `Base.metadata.create_all` — no Alembic yet (see below).

## Tables

- `endpoints(id, url, secret, rate_limit_per_minute, created_at)`
- `events(id, endpoint_id → endpoints, idempotency_key NULLABLE, payload TEXT raw JSON, created_at)`
- `deliveries(id, event_id → events, endpoint_id → endpoints, status, attempts,
  next_attempt_at, last_status_code, last_error, latency_ms, created_at, updated_at)`

## Constraints & indexes (why they exist)

- `UNIQUE(endpoint_id, idempotency_key)` — closes the race where two concurrent
  ingests with the same key both pass the app-level "does it exist?" check.
  The loser gets `IntegrityError`, we catch it and return the winner (deduplicated=true).
  NULL keys are exempt in both SQLite and Postgres (multiple NULLs allowed).
- `INDEX deliveries(status, next_attempt_at)` — the worker's hot query
  (`WHERE status IN ('queued','retrying') AND (next_attempt_at IS NULL OR <= now)`)
  would otherwise full-scan on every 2s poll.
- `INDEX deliveries(endpoint_id, created_at)`, `INDEX deliveries(event_id)`,
  `INDEX events(endpoint_id, created_at)` — history pagination + filters.

## Migration path

`create_all` is a deliberate MVP choice (3 tables, no alterations yet). When the
first ALTER is needed: introduce Alembic with `alembic revision --autogenerate`,
point it at `app.db:Base.metadata`, and backfill in the same PR. Do not hand-edit
prod tables.
