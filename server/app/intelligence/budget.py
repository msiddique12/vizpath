"""Daily per-project intelligence call budget guardrails."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Any, cast

import redis

from app.config import settings

logger = logging.getLogger(__name__)

_BUDGET_KEY_PREFIX = "vizpath:intelligence:daily_budget"
_REDIS_CLIENT: redis.Redis | None = None
_REDIS_INITIALIZED = False

_fallback_lock = Lock()
_fallback_usage_by_day: dict[str, dict[str, int]] = {}

_RESERVE_BUDGET_LUA = """
local current = redis.call('GET', KEYS[1])
local limit = tonumber(ARGV[1])
local ttl_seconds = tonumber(ARGV[2])

if not current then
  redis.call('SET', KEYS[1], 1, 'EX', ttl_seconds)
  return {1, 1}
end

current = tonumber(current)
if current >= limit then
  return {0, current}
end

local updated = redis.call('INCR', KEYS[1])
if redis.call('TTL', KEYS[1]) < 0 then
  redis.call('EXPIRE', KEYS[1], ttl_seconds)
end
return {1, updated}
"""


@dataclass
class IntelligenceBudgetStatus:
    """Current per-project intelligence budget status."""

    enforced: bool
    limit: int | None
    used: int
    remaining: int | None
    resets_at: str
    allowed: bool
    retry_after_seconds: int | None


def _coerce_limit(raw: Any) -> int:
    if isinstance(raw, bool):
        return int(raw)
    if isinstance(raw, int):
        return max(0, raw)
    if isinstance(raw, float):
        return max(0, int(raw))
    if isinstance(raw, str):
        try:
            return max(0, int(raw.strip()))
        except ValueError:
            return 0
    return 0


def _now_utc(now: datetime | None = None) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc)


def _day_key(now: datetime) -> str:
    return now.strftime("%Y-%m-%d")


def _next_reset(now: datetime) -> datetime:
    return datetime.combine(
        now.date() + timedelta(days=1),
        datetime.min.time(),
        tzinfo=timezone.utc,
    )


def _seconds_until_reset(now: datetime) -> int:
    seconds = int((_next_reset(now) - now).total_seconds())
    return max(1, seconds)


def _counter_key(project_id: str, now: datetime) -> str:
    return f"{_BUDGET_KEY_PREFIX}:{_day_key(now)}:{project_id}"


def _get_redis_client() -> redis.Redis | None:
    global _REDIS_CLIENT, _REDIS_INITIALIZED
    if _REDIS_INITIALIZED:
        return _REDIS_CLIENT

    _REDIS_INITIALIZED = True
    try:
        client = redis.from_url(settings.redis_url, decode_responses=True)
        client.ping()
        _REDIS_CLIENT = client
    except Exception as exc:  # pragma: no cover - depends on environment
        logger.warning("Intelligence budget Redis unavailable, using in-memory fallback: %s", exc)
        _REDIS_CLIENT = None
    return _REDIS_CLIENT


def _cleanup_fallback_days(current_day: str) -> None:
    for day in list(_fallback_usage_by_day.keys()):
        if day != current_day:
            _fallback_usage_by_day.pop(day, None)


def _fallback_read_usage(project_id: str, now: datetime) -> int:
    day = _day_key(now)
    with _fallback_lock:
        _cleanup_fallback_days(day)
        return _fallback_usage_by_day.get(day, {}).get(project_id, 0)


def _fallback_reserve(project_id: str, limit: int, now: datetime) -> tuple[bool, int]:
    day = _day_key(now)
    with _fallback_lock:
        _cleanup_fallback_days(day)
        day_usage = _fallback_usage_by_day.setdefault(day, {})
        current = day_usage.get(project_id, 0)
        if current >= limit:
            return False, current
        updated = current + 1
        day_usage[project_id] = updated
        return True, updated


def _read_usage(project_id: str, now: datetime) -> int:
    redis_client = _get_redis_client()
    if redis_client is None:
        return _fallback_read_usage(project_id, now)

    try:
        raw = redis_client.get(_counter_key(project_id, now))
        if raw is None:
            return 0
        if hasattr(raw, "__await__"):
            raise TypeError("Async Redis client not supported in sync budget path")
        raw_value = cast(Any, raw)
        if isinstance(raw_value, (bytes, bytearray)):
            raw_value = raw_value.decode("utf-8", errors="ignore")
        return int(raw_value)
    except Exception as exc:  # pragma: no cover - depends on environment
        logger.warning("Intelligence budget read failed, using fallback: %s", exc)
        return _fallback_read_usage(project_id, now)


def _reserve_usage(project_id: str, limit: int, now: datetime) -> tuple[bool, int]:
    redis_client = _get_redis_client()
    if redis_client is None:
        return _fallback_reserve(project_id, limit, now)

    key = _counter_key(project_id, now)
    ttl = _seconds_until_reset(now)
    try:
        result = redis_client.eval(_RESERVE_BUDGET_LUA, 1, key, limit, ttl)
        if hasattr(result, "__await__"):
            raise TypeError("Async Redis client not supported in sync budget path")
        parsed_result = cast(Any, result)
        if not isinstance(parsed_result, (list, tuple)) or len(parsed_result) < 2:
            raise ValueError("Unexpected Redis LUA response for budget reservation")
        allowed = bool(int(parsed_result[0]))
        used = int(parsed_result[1])
        return allowed, used
    except Exception as exc:  # pragma: no cover - depends on environment
        logger.warning("Intelligence budget reserve failed, using fallback: %s", exc)
        return _fallback_reserve(project_id, limit, now)


def get_intelligence_budget_status(
    project_id: str,
    *,
    now: datetime | None = None,
) -> IntelligenceBudgetStatus:
    """Read current budget status without consuming budget."""
    current = _now_utc(now)
    limit = _coerce_limit(getattr(settings, "intelligence_daily_call_limit_per_project", 0))
    enforced = limit > 0
    used = _read_usage(project_id, current)
    remaining = max(0, limit - used) if enforced else None
    retry_after_seconds = _seconds_until_reset(current) if enforced and used >= limit else None

    return IntelligenceBudgetStatus(
        enforced=enforced,
        limit=limit if enforced else None,
        used=used,
        remaining=remaining,
        resets_at=_next_reset(current).isoformat(),
        allowed=(not enforced) or used < limit,
        retry_after_seconds=retry_after_seconds,
    )


def consume_intelligence_budget_call(
    project_id: str,
    *,
    now: datetime | None = None,
) -> IntelligenceBudgetStatus:
    """Consume one intelligence call from the daily project budget if enabled."""
    current = _now_utc(now)
    limit = _coerce_limit(getattr(settings, "intelligence_daily_call_limit_per_project", 0))
    enforced = limit > 0
    if not enforced:
        return IntelligenceBudgetStatus(
            enforced=False,
            limit=None,
            used=_read_usage(project_id, current),
            remaining=None,
            resets_at=_next_reset(current).isoformat(),
            allowed=True,
            retry_after_seconds=None,
        )

    allowed, used = _reserve_usage(project_id, limit, current)
    remaining = max(0, limit - used)
    retry_after_seconds = _seconds_until_reset(current) if not allowed else None
    return IntelligenceBudgetStatus(
        enforced=True,
        limit=limit,
        used=used,
        remaining=remaining,
        resets_at=_next_reset(current).isoformat(),
        allowed=allowed,
        retry_after_seconds=retry_after_seconds,
    )


def _reset_intelligence_budget_state_for_tests() -> None:
    """Reset module state for deterministic tests."""
    global _REDIS_CLIENT, _REDIS_INITIALIZED
    with _fallback_lock:
        _fallback_usage_by_day.clear()
    _REDIS_CLIENT = None
    _REDIS_INITIALIZED = False
