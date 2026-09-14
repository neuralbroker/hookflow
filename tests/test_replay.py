"""Replay, stats, metrics, request-ID, idempotency-constraint."""

import httpx

from app.db import Delivery


def _register(client, url="https://example.com/wh", rate=60):
    r = client.post("/v1/endpoints", json={"url": url, "rate_limit_per_minute": rate})
    assert r.status_code == 201, r.text
    return r.json()


def _fail_client(status=500):
    def handler(request):
        return httpx.Response(status, json={"err": True})

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_requeue_dlq_resets_to_queued(client):
    from app import main as main_module
    from app.config import Settings
    from app.db import Endpoint, Event, init_db, make_engine, make_session_factory
    from app.worker import process_due_deliveries
    from app.ratelimit import RateLimiter

    ep = _register(client)
    r = client.post(
        "/v1/events", json={"endpoint_id": ep["id"], "payload": {"a": 1}}
    )
    delivery_id = r.json()["delivery_id"]

    # Drive the delivery to DLQ via the worker path against the test DB.
    # Reuse the file-backed test DB through the API session is complex;
    # instead assert the replay contract on a delivery we force to dlq.
    # Simplest honest path: fetch delivery, manually mark dlq via API-visible state.
    # Here we exercise the endpoint's validation: unknown id 404, success not requeueable.
    assert client.post("/v1/deliveries/nope/requeue").status_code == 404

    # Force the delivery row to dlq using the app's session factory.
    session = next(main_module.get_db())
    try:
        row = session.get(Delivery, delivery_id)
        assert row is not None
        row.status = "dlq"
        row.attempts = 5
        row.last_error = "unexpected status 500"
        session.add(row)
        session.commit()
    finally:
        session.close()

    r = client.post(f"/v1/deliveries/{delivery_id}/requeue")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "queued"
    assert body["attempts"] == 0

    # Success deliveries must NOT be requeueable (would duplicate side effects).
    session = next(main_module.get_db())
    try:
        row = session.get(Delivery, delivery_id)
        row.status = "success"
        session.add(row)
        session.commit()
    finally:
        session.close()
    assert client.post(f"/v1/deliveries/{delivery_id}/requeue").status_code == 409


def test_stats_and_metrics(client):
    ep = _register(client)
    client.post("/v1/events", json={"endpoint_id": ep["id"], "payload": {"n": 1}})
    stats = client.get("/v1/stats").json()
    assert stats["queue_depth"] >= 1
    assert "queued" in stats["by_status"]

    metrics = client.get("/metrics")
    assert metrics.status_code == 200
    assert "hookflow_events_ingested_total" in metrics.text
    assert metrics.headers["content-type"].startswith("text/plain")


def test_request_id_header(client):
    r = client.get("/health")
    assert "X-Request-ID" in r.headers
    assert len(r.headers["X-Request-ID"]) >= 8
    # Server honors caller-supplied IDs for trace correlation.
    r2 = client.get("/health", headers={"X-Request-ID": "trace-123"})
    assert r2.headers["X-Request-ID"] == "trace-123"


def test_idempotency_unique_constraint_enforced_at_db():
    """The UNIQUE(endpoint_id, idempotency_key) must exist, not just app logic."""
    from sqlalchemy import inspect

    from app.db import Base

    table = Base.metadata.tables["events"]
    unique_cols = set()
    for c in table.constraints:
        if c.__class__.__name__ == "UniqueConstraint" and set(
            col.name for col in c.columns
        ) == {"endpoint_id", "idempotency_key"}:
            unique_cols = {"endpoint_id", "idempotency_key"}
    assert unique_cols == {"endpoint_id", "idempotency_key"}, (
        "missing UNIQUE(endpoint_id, idempotency_key) — race window is open"
    )

    deliveries = Base.metadata.tables["deliveries"]
    index_cols = {tuple(i.columns.keys()) for i in deliveries.indexes}
    assert ("status", "next_attempt_at") in index_cols, "worker poll index missing"
