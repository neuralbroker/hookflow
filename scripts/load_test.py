"""Minimal load probe for HookFlow ingest path.

Uses FastAPI TestClient (no server, no Redis, no network) to measure the
persist-first ingest bottleneck: JSON serialize + SQLite insert + enqueue-noop.

Usage:
    python scripts/load_test.py --events 1000 --payload-kb 1

This is NOT a production benchmark (SQLite, single process, no worker HTTP).
It exists so README numbers are measured, not invented. For Postgres numbers,
run the same script with DATABASE_URL set and the app running under uvicorn.
"""

from __future__ import annotations

import argparse
import os
import statistics
import sys
import tempfile
import time


def run(events: int, payload_kb: int) -> dict:
    import pathlib

    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    os.environ["DATABASE_URL"] = f"sqlite:///{tmp.name}"
    os.environ["REDIS_URL"] = ""

    from fastapi.testclient import TestClient

    from app import main as main_module
    from app.config import Settings, get_settings

    get_settings.cache_clear()
    settings = Settings(database_url=f"sqlite:///{tmp.name}", redis_url="")
    main_module.init_state(settings)
    app = main_module.create_app(settings)

    payload = {"data": "x" * (payload_kb * 1024)}
    latencies: list[float] = []

    with TestClient(app) as client:
        ep = client.post(
            "/v1/endpoints",
            json={"url": "https://example.com/wh", "rate_limit_per_minute": 10000},
        ).json()
        endpoint_id = ep["id"]

        start = time.monotonic()
        for i in range(events):
            t0 = time.monotonic()
            r = client.post(
                "/v1/events",
                json={"endpoint_id": endpoint_id, "payload": payload},
            )
            assert r.status_code == 201, r.text
            latencies.append((time.monotonic() - t0) * 1000)
        total_s = time.monotonic() - start

    os.unlink(tmp.name)
    latencies.sort()
    p50 = latencies[len(latencies) // 2]
    p95 = latencies[int(len(latencies) * 0.95)]
    return {
        "events": events,
        "payload_kb": payload_kb,
        "total_s": round(total_s, 3),
        "rps": round(events / total_s, 1),
        "p50_ms": round(p50, 2),
        "p95_ms": round(p95, 2),
        "mean_ms": round(statistics.mean(latencies), 2),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--events", type=int, default=500)
    parser.add_argument("--payload-kb", type=int, default=1)
    args = parser.parse_args()
    result = run(args.events, args.payload_kb)
    print(
        f"ingest: {result['events']} events, {result['payload_kb']}KB payload | "
        f"{result['rps']} rps | p50 {result['p50_ms']}ms p95 {result['p95_ms']}ms "
        f"mean {result['mean_ms']}ms total {result['total_s']}s "
        f"(SQLite/TestClient, single process)"
    )


if __name__ == "__main__":
    sys.exit(main())
