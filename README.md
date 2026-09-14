# HookFlow

Reliable webhook and event delivery infrastructure.

## Problem

Customer webhook endpoints are flaky: timeouts, 5xx, deploys. Producers need accept-then-deliver with retries instead of fire-and-forget POSTs.

## Solution

Persist-first ingest, signed async delivery, exponential-backoff retries, idempotency, per-endpoint rate limits, and a dead-letter state with full delivery history.

## Architecture

```text
Client
  ↓
FastAPI
  ↓
PostgreSQL
  ↓
Redis Queue
  ↓
Worker
  ↓
Webhook Endpoint
```

See `docs/architecture.md`, `docs/database.md`, `docs/performance.md`, `docs/security.md`, `docs/deployment.md`.

## Key Engineering Decisions

1. Persist before enqueue — never lose an accepted event.
2. At-least-once + idempotency keys instead of exactly-once claims.
3. HMAC per endpoint so receivers can verify.
4. Backoff 1m → 5m → 30m → 2h → 12h, then DLQ.
5. Redis optional with honest single-replica memory fallback.

## Tech Stack

Python · FastAPI · PostgreSQL · Redis · Docker · pytest

## Features

1. Webhook registration with per-endpoint secret + rate limit
2. Event ingestion with size validation + idempotency race protection (DB UNIQUE)
3. Async signed delivery with timeout
4. Retries with exponential backoff + DLQ + replay endpoint
5. Delivery history with pagination + filters
6. Health/ready checks (DB + Redis) + `/metrics` + `/v1/stats` + request IDs
7. Docker Compose (app, worker, db, redis)

## Running Locally

```bash
python3.11 -m venv venv && source venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env
uvicorn app.main:app --reload  # /docs, /health, /ready
python -m app.worker            # delivery worker (separate terminal)
docker compose -f docker/docker-compose.yml up --build  # full stack
```

Verify a receiver sees `X-Hookflow-Signature: sha256=...` computed over the raw JSON body with the endpoint secret.

## Testing

```bash
python -m pytest -q   # 17 tests: API, worker, HMAC, backoff, replay/stats/metrics
python scripts/load_test.py --events 500 --payload-kb 1
```

Isolated SQLite per test; Redis not required (memory fallback); worker HTTP mocked with `httpx.MockTransport`.

## Performance

Measured 2026-09-14 via `scripts/load_test.py` (TestClient + SQLite, single process):

- 500 events × 1KB: **38.6 rps, p50 25.5ms, p95 28.8ms**
- 200 events × 10KB: **37.7 rps, p50 25.8ms, p95 29.0ms**

Cost is the transaction, not payload size at these sizes. See `docs/performance.md`.
Postgres + concurrent + worker-delivery numbers not yet measured — do not cite them.

## Limitations

Memory fallback is single-replica only; no multi-tenant auth (endpoint secrets only);
backoff schedule fixed via config; `create_all` instead of Alembic (see `docs/database.md`);
secrets stored plaintext; no TLS in Compose (terminate at LB).

## Future Improvements

Per-tenant API keys, Alembic migrations, k6 concurrent + worker-throughput benchmarks,
Grafana dashboard, hosted demo.
