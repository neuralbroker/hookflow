# HookFlow architecture

```text
Client
  ↓ POST /v1/events (validate, Idempotency-Key)
FastAPI (register endpoints, ingest, history)
  ↓ persist first
PostgreSQL (endpoints, events, deliveries) — SQLite for local/tests
  ↓ notify
Redis list (fast wake-up; optional) ──→ Worker (poll due rows regardless)
  ↓ sign + POST + timeout
Customer webhook (verifies X-Hookflow-Signature)
  ↓
Delivery history (/v1/deliveries) + /health + /ready
```

Key decisions:
1. Persist-first ingest: an accepted event is never lost even if Redis drops the wake-up, because the worker polls due DB rows.
2. At-least-once delivery: retries with backoff (60s, 5m, 30m, 2h, 12h; 5 attempts) then DLQ with replay-by-requeue potential.
3. Idempotency keys scoped per endpoint (body or `Idempotency-Key` header) dedupe retries safely.
4. HMAC-SHA256 per-endpoint secret; verification docs in README.
5. Fixed-window per-endpoint rate limits; Redis when configured, memory fallback single-replica only.
