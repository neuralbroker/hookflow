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

See `docs/architecture.md`.

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
2. Event ingestion with size validation
3. Idempotency keys (body or header, per endpoint)
4. Async signed delivery with timeout
5. Retries with exponential backoff + DLQ
6. Delivery history with pagination + filters
7. Health/ready checks (DB + Redis)
8. Docker Compose (app, worker, db, redis)

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
python -m pytest -q
```

Isolated SQLite per test; Redis not required (memory fallback); worker HTTP mocked with `httpx.MockTransport`.

## Performance

No published benchmarks yet. Measure before citing: sustained ingest RPS, delivery success rate, p95 ingest + delivery latency, worker throughput, Redis hit behavior.

## Limitations

Memory fallback is single-replica only; no multi-tenant auth (endpoint secrets only); no replay API for DLQ yet (requeue by resetting status); no Prometheus metrics yet; backoff schedule fixed via config.

## Future Improvements

DLQ replay endpoint, Prometheus metrics + Grafana, per-tenant API keys, Alembic migrations, load-test script, hosted demo.
