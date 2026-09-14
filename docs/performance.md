# HookFlow performance

Measured 2026-09-14, commit on `main` after replay/stats/metrics addition.
Method: `python scripts/load_test.py` (FastAPI TestClient, SQLite file,
single process, no Redis, no worker HTTP). This measures the ingest bottleneck
(JSON serialize + 2-row transaction), NOT production Postgres throughput.

## Results

| Workload | RPS | p50 | p95 | mean |
|---|---|---|---|---|
| 500 events, 1KB payload | 38.6 | 25.5ms | 28.8ms | 25.9ms |
| 200 events, 10KB payload | 37.7 | 25.8ms | 29.0ms | 26.5ms |

Payload size (1KB → 10KB) barely moves latency: the cost is the transaction,
not the bytes, at these sizes.

## What this proves / does not prove

- Proves: persist-first ingest is functional and bounded (~26ms locally).
- Does NOT prove: Postgres RPS, worker delivery throughput, p95 under
  concurrent load, Redis wake-up latency. Measure those with
  `docker compose up` + `k6`/locust against `/v1/events` before citing.

## Next measurements

1. Concurrent ingest (20 workers × 100 events) — expect SQLite write
   serialization; Postgres should scale.
2. Worker delivery throughput against a stub receiver (200/500/timeout mix).
3. End-to-end p95: ingest → signed POST → success.
