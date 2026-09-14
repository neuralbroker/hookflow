"""SQLAlchemy models. PostgreSQL in production, SQLite for local dev/tests."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


def new_id() -> str:
    return uuid.uuid4().hex


class Endpoint(Base):
    __tablename__ = "endpoints"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    secret: Mapped[str] = mapped_column(String(128), nullable=False)
    rate_limit_per_minute: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    deliveries: Mapped[list["Delivery"]] = relationship(
        back_populates="endpoint", cascade="all, delete-orphan"
    )


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (
        # Idempotency keys are scoped per endpoint. The app checks for an
        # existing row first; this constraint closes the race where two
        # concurrent ingests with the same key would both insert.
        # NULL keys (no dedupe requested) are exempt — SQLite and Postgres
        # both allow multiple NULLs in a UNIQUE constraint.
        UniqueConstraint("endpoint_id", "idempotency_key", name="uq_events_endpoint_key"),
        Index("ix_events_endpoint_created", "endpoint_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    endpoint_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("endpoints.id", ondelete="CASCADE"), nullable=False
    )
    # Client-supplied idempotency key, scoped per endpoint. NULL = no dedupe requested.
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    payload: Mapped[str] = mapped_column(Text, nullable=False)  # raw JSON text
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    endpoint: Mapped[Endpoint] = relationship()
    deliveries: Mapped[list["Delivery"]] = relationship(
        back_populates="event", cascade="all, delete-orphan"
    )


class Delivery(Base):
    __tablename__ = "deliveries"
    __table_args__ = (
        # Hot path for the worker: "what is due now?" Must be indexed or
        # every poll is a full-table scan.
        Index("ix_deliveries_status_next", "status", "next_attempt_at"),
        Index("ix_deliveries_endpoint_created", "endpoint_id", "created_at"),
        Index("ix_deliveries_event", "event_id"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    event_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("events.id", ondelete="CASCADE"), nullable=False
    )
    endpoint_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("endpoints.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued")
    # queued | success | retrying | dlq
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )

    event: Mapped[Event] = relationship(back_populates="deliveries")
    endpoint: Mapped[Endpoint] = relationship(back_populates="deliveries")


def make_engine(database_url: str):
    kwargs: dict = {"pool_pre_ping": True}
    if database_url.startswith("sqlite"):
        kwargs = {"connect_args": {"check_same_thread": False}}
    return create_engine(database_url, **kwargs)


def make_session_factory(engine):
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db(engine) -> None:
    Base.metadata.create_all(bind=engine)
