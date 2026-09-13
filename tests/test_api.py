"""API: health, endpoint registration, ingest, idempotency, history."""


def _register(client, url="https://example.com/wh", rate=60):
    r = client.post(
        "/v1/endpoints", json={"url": url, "rate_limit_per_minute": rate}
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_health_and_ready(client):
    assert client.get("/health").json()["status"] == "ok"
    body = client.get("/ready").json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"


def test_register_rejects_non_http(client):
    r = client.post("/v1/endpoints", json={"url": "ftp://x/y"})
    assert r.status_code == 422


def test_ingest_creates_delivery_and_history(client):
    ep = _register(client)
    r = client.post(
        "/v1/events",
        json={"endpoint_id": ep["id"], "payload": {"order": 1}},
    )
    assert r.status_code == 201, r.text
    event_id = r.json()["id"]
    delivery_id = r.json()["delivery_id"]
    assert r.json()["deduplicated"] is False

    got = client.get(f"/v1/events/{event_id}").json()
    assert got["payload"] == {"order": 1}
    assert got["deliveries"][0]["id"] == delivery_id
    assert got["deliveries"][0]["status"] == "queued"

    listed = client.get("/v1/deliveries").json()["items"]
    assert any(d["id"] == delivery_id for d in listed)


def test_idempotency_key_dedupes(client):
    ep = _register(client)
    body = {"endpoint_id": ep["id"], "payload": {"n": 1}, "idempotency_key": "k-1"}
    first = client.post("/v1/events", json=body).json()
    second = client.post("/v1/events", json=body).json()
    assert second["deduplicated"] is True
    assert second["id"] == first["id"]

    via_header = client.post(
        "/v1/events",
        json={"endpoint_id": ep["id"], "payload": {"n": 1}},
        headers={"Idempotency-Key": "k-1"},
    ).json()
    assert via_header["id"] == first["id"]


def test_unknown_endpoint_404(client):
    r = client.post("/v1/events", json={"endpoint_id": "nope", "payload": {}})
    assert r.status_code == 404
