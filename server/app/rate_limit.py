"""Rate limiting middleware with Redis backend and in-memory fallback."""

import hashlib
import logging
import threading
import time
from dataclasses import dataclass
from math import ceil
from typing import Protocol

import redis
from fastapi import Request
from fastapi.responses import JSONResponse

from app.config import settings

logger = logging.getLogger(__name__)

WINDOW_SECONDS = 60


class RateLimitBackend(Protocol):
    """Interface for rate limiter counters."""

    def increment(self, key: str, window_seconds: int) -> tuple[int, int]:
        """Increment key and return (count, seconds_until_reset)."""


class RedisRateLimitBackend:
    """Redis-backed fixed-window rate limiting counters."""

    def __init__(self, redis_url: str):
        self.client = redis.from_url(redis_url, decode_responses=True)

    def increment(self, key: str, window_seconds: int) -> tuple[int, int]:
        count = int(self.client.incr(key))
        if count == 1:
            self.client.expire(key, window_seconds)
            return count, window_seconds

        ttl = int(self.client.ttl(key))
        if ttl <= 0:
            self.client.expire(key, window_seconds)
            ttl = window_seconds
        return count, ttl


class InMemoryRateLimitBackend:
    """In-memory fixed-window fallback for environments without Redis."""

    def __init__(self):
        self._lock = threading.Lock()
        self._counters: dict[str, tuple[int, int]] = {}

    def increment(self, key: str, window_seconds: int) -> tuple[int, int]:
        now = int(time.time())
        current_window = now // window_seconds

        with self._lock:
            stored = self._counters.get(key)
            if stored and stored[0] == current_window:
                count = stored[1] + 1
            else:
                count = 1

            self._counters[key] = (current_window, count)

        expires_at = (current_window + 1) * window_seconds
        retry_after = max(expires_at - now, 1)
        return count, retry_after


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    scope: str
    retry_after_seconds: int


class RateLimiter:
    """Rate limiter that evaluates per-scope requests."""

    def __init__(self, backend: RateLimitBackend):
        self.backend = backend

    def check(self, *, scope: str, identifier: str, rpm_limit: int) -> RateLimitResult:
        effective_limit = max(1, ceil(rpm_limit * settings.rate_limit_burst_multiplier))
        key = f"rate_limit:{scope}:{identifier}"
        count, retry_after = self.backend.increment(key, WINDOW_SECONDS)
        if count > effective_limit:
            return RateLimitResult(
                allowed=False,
                scope=scope,
                retry_after_seconds=retry_after,
            )

        return RateLimitResult(allowed=True, scope=scope, retry_after_seconds=0)


def _resolve_backend() -> RateLimitBackend:
    try:
        backend = RedisRateLimitBackend(settings.redis_url)
        backend.client.ping()
        return backend
    except Exception as exc:
        logger.warning("Redis unavailable for rate limiting, using in-memory fallback: %s", exc)
        return InMemoryRateLimitBackend()


_limiter = RateLimiter(_resolve_backend())


def get_limiter() -> RateLimiter:
    return _limiter


def _build_rate_limit_response(
    *,
    request_id: str | None,
    scope: str,
    retry_after_seconds: int,
) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={
            "detail": "Rate limit exceeded",
            "error": {
                "code": "rate_limited",
                "message": "Rate limit exceeded",
                "request_id": request_id,
            },
            "retry_after_seconds": retry_after_seconds,
            "scope": scope,
            "request_id": request_id,
        },
        headers={"Retry-After": str(retry_after_seconds)},
    )


async def rate_limit_middleware(request: Request, call_next):
    """Apply IP and project/anonymous rate limits."""
    if not settings.rate_limit_enabled:
        return await call_next(request)

    limiter = get_limiter()
    request_id = getattr(request.state, "request_id", None)
    client_ip = request.client.host if request.client and request.client.host else "unknown"

    ip_result = limiter.check(scope="ip", identifier=client_ip, rpm_limit=settings.rate_limit_ip_rpm)
    if not ip_result.allowed:
        return _build_rate_limit_response(
            request_id=request_id,
            scope=ip_result.scope,
            retry_after_seconds=ip_result.retry_after_seconds,
        )

    api_key = request.headers.get("X-API-Key")
    if api_key:
        key_identifier = hashlib.sha256(api_key.encode()).hexdigest()
        scoped_result = limiter.check(
            scope="project",
            identifier=key_identifier,
            rpm_limit=settings.rate_limit_user_rpm,
        )
    else:
        scoped_result = limiter.check(
            scope="anonymous",
            identifier=client_ip,
            rpm_limit=settings.rate_limit_user_rpm,
        )

    if not scoped_result.allowed:
        return _build_rate_limit_response(
            request_id=request_id,
            scope=scoped_result.scope,
            retry_after_seconds=scoped_result.retry_after_seconds,
        )

    return await call_next(request)
