"""Focused tests for rate limit internals."""

from app.config import settings
from app.rate_limit import InMemoryRateLimitBackend, RateLimiter


def test_inmemory_backend_increments_within_window():
    backend = InMemoryRateLimitBackend()

    count_1, retry_1 = backend.increment("test-key", 60)
    count_2, retry_2 = backend.increment("test-key", 60)

    assert count_1 == 1
    assert count_2 == 2
    assert retry_1 > 0
    assert retry_2 > 0


def test_rate_limiter_blocks_when_limit_exceeded(monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_burst_multiplier", 1.0)
    limiter = RateLimiter(InMemoryRateLimitBackend())

    allowed = limiter.check(scope="ip", identifier="127.0.0.1", rpm_limit=1)
    blocked = limiter.check(scope="ip", identifier="127.0.0.1", rpm_limit=1)

    assert allowed.allowed is True
    assert blocked.allowed is False
    assert blocked.scope == "ip"
    assert blocked.retry_after_seconds > 0
