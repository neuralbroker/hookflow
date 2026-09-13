"""Delivery queue. Redis list when configured, DB-poll fallback otherwise.

Design: ingest always persists Event + Delivery rows first (never lose an
accepted event). When Redis is configured the delivery id is also LPUSHed for
fast wake-up; the worker additionally polls due rows so no delivery is lost if
Redis drops a message. Without Redis the worker polls the DB only.
"""

from __future__ import annotations

QUEUE_KEY = "hookflow:deliveries"


class DeliveryQueue:
    def __init__(self, redis_url: str = "") -> None:
        self._redis = None
        if redis_url:
            import redis

            self._redis = redis.Redis.from_url(redis_url, decode_responses=True)

    @property
    def has_redis(self) -> bool:
        return self._redis is not None

    def enqueue(self, delivery_id: str) -> None:
        if self._redis is None:
            return
        self._redis.lpush(QUEUE_KEY, delivery_id)

    def dequeue(self, timeout: int = 5) -> str | None:
        if self._redis is None:
            return None
        item = self._redis.brpop(QUEUE_KEY, timeout=timeout)
        if not item:
            return None
        return item[1]
