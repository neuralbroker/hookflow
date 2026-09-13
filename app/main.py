"""HookFlow API: event ingestion, webhook registration, delivery history."""

from __future__ import annotations

import json
from datetime import datetime

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from .config import Settings, get_settings
from .db import Delivery, Endpoint, Event, init_db, utcnow
from .queue import DeliveryQueue
from .ratelimit import RateLimiter
from .schemas import (
    DeliveryOut,
    EndpointCreate,
    EndpointOut,
    EventCreate,
    EventOut,
)
from .security import generate_secret

rate_limiter = RateLimiter()
delivery_queue = DeliveryQueue()
engine = None
SessionLocal = None


def get_settings_dep() -> Settings:
    return get_settings()


def init_state(settings: Settings | None = None) -> None:
    global engine, SessionLocal, rate_limiter, delivery_queue
    settings = settings or get_settings()
    global_kwargs: dict = {}
    if settings.database_url.startswith("sqlite"):
        global_kwargs = {"connect_args": {"check_same_thread": False}}
        engine = create_engine(settings.database_url, **global_kwargs)
    else:
        from .db import make_engine

        engine = make_engine(settings.database_url)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    init_db(engine)
    # Rebind helpers to current settings (tests override redis_url="").
    rate_limiter = RateLimiter(settings.redis_url)
    delivery_queue = DeliveryQueue(settings.redis_url)


def get_db():
    assert SessionLocal is not None, "call init_state() first"
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def to_delivery_out(d: Delivery) -> DeliveryOut:
    return DeliveryOut(
        id=d.id,
        event_id=d.event_id,
        endpoint_id=d.endpoint_id,
        status=d.status,
        attempts=d.attempts,
        next_attempt_at=d.next_attempt_at.isoformat() if d.next_attempt_at else None,
        last_status_code=d.last_status_code,
        last_error=d.last_error,
        latency_ms=d.latency_ms,
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    init_state(settings or get_settings())
    app = FastAPI(title="HookFlow", version="0.1.0")

    @app.get("/health")
    def health():
        return {"status": "ok", "service": "hookflow"}

    @app.get("/ready")
    def ready(db: Session = Depends(get_db)):
        # DB check.
        db.query(Endpoint.id).limit(1).all()
        checks: dict = {"database": "ok"}
        # Redis check (optional dependency).
        if delivery_queue.has_redis:
            try:
                delivery_queue._redis.ping()  # type: ignore[union-attr]
                checks["redis"] = "ok"
            except Exception as exc:
                raise HTTPException(status_code=503, detail=f"redis unreachable: {exc}")
        else:
            checks["redis"] = "not-configured"
        return {"status": "ok", **checks}

    @app.post("/v1/endpoints", status_code=201, response_model=EndpointOut)
    def register_endpoint(
        payload: EndpointCreate, db: Session = Depends(get_db)
    ):
        settings = get_settings()
        body_len = len(payload.url.encode())
        if body_len > 2000:
            raise HTTPException(status_code=413, detail="url too long")
        endpoint = Endpoint(
            url=payload.url,
            secret=payload.secret or generate_secret(),
            rate_limit_per_minute=payload.rate_limit_per_minute,
        )
        db.add(endpoint)
        db.commit()
        db.refresh(endpoint)
        return EndpointOut(
            id=endpoint.id,
            url=endpoint.url,
            rate_limit_per_minute=endpoint.rate_limit_per_minute,
            created_at=endpoint.created_at.isoformat(),
        )

    @app.get("/v1/endpoints")
    def list_endpoints(
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
        db: Session = Depends(get_db),
    ):
        rows = (
            db.query(Endpoint).order_by(Endpoint.created_at).offset(offset).limit(limit).all()
        )
        return {
            "items": [
                {
                    "id": e.id,
                    "url": e.url,
                    "rate_limit_per_minute": e.rate_limit_per_minute,
                    "created_at": e.created_at.isoformat(),
                }
                for e in rows
            ]
        }

    @app.post("/v1/events", status_code=201, response_model=EventOut)
    def ingest_event(
        payload: EventCreate,
        db: Session = Depends(get_db),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ):
        settings = get_settings()
        key = payload.idempotency_key or idempotency_key
        endpoint = db.get(Endpoint, payload.endpoint_id)
        if endpoint is None:
            raise HTTPException(status_code=404, detail="endpoint not found")
        try:
            raw = json.dumps(payload.payload, separators=(",", ":"))
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail="payload must be JSON-serializable")
        if len(raw.encode()) > settings.max_body_bytes:
            raise HTTPException(status_code=413, detail="payload too large")
        if key:
            existing = (
                db.query(Event)
                .filter(Event.endpoint_id == endpoint.id, Event.idempotency_key == key)
                .order_by(Event.created_at)
                .first()
            )
            if existing is not None:
                delivery = (
                    db.query(Delivery)
                    .filter(Delivery.event_id == existing.id)
                    .order_by(Delivery.created_at)
                    .first()
                )
                return EventOut(
                    id=existing.id,
                    endpoint_id=endpoint.id,
                    delivery_id=delivery.id if delivery else "",
                    deduplicated=True,
                )
        event = Event(endpoint_id=endpoint.id, idempotency_key=key, payload=raw)
        db.add(event)
        db.flush()
        delivery = Delivery(
            event_id=event.id,
            endpoint_id=endpoint.id,
            status="queued",
            attempts=0,
            next_attempt_at=None,
        )
        db.add(delivery)
        db.commit()
        db.refresh(event)
        db.refresh(delivery)
        delivery_queue.enqueue(delivery.id)
        return EventOut(
            id=event.id,
            endpoint_id=endpoint.id,
            delivery_id=delivery.id,
            deduplicated=False,
        )

    @app.get("/v1/events/{event_id}")
    def get_event(event_id: str, db: Session = Depends(get_db)):
        event = db.get(Event, event_id)
        if event is None:
            raise HTTPException(status_code=404, detail="event not found")
        deliveries = (
            db.query(Delivery).filter(Delivery.event_id == event.id).order_by(
                Delivery.created_at
            ).all()
        )
        return {
            "id": event.id,
            "endpoint_id": event.endpoint_id,
            "payload": json.loads(event.payload),
            "created_at": event.created_at.isoformat(),
            "deliveries": [to_delivery_out(d).model_dump() for d in deliveries],
        }

    @app.get("/v1/deliveries")
    def list_deliveries(
        status: str | None = Query(default=None),
        endpoint_id: str | None = Query(default=None),
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
        db: Session = Depends(get_db),
    ):
        q = db.query(Delivery)
        if status:
            if status not in ("queued", "success", "retrying", "dlq"):
                raise HTTPException(status_code=422, detail="invalid status")
            q = q.filter(Delivery.status == status)
        if endpoint_id:
            q = q.filter(Delivery.endpoint_id == endpoint_id)
        rows = q.order_by(Delivery.created_at.desc()).offset(offset).limit(limit).all()
        return {"items": [to_delivery_out(d).model_dump() for d in rows]}

    return app


app = create_app()
