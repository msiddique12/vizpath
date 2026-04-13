"""Unit tests for intelligence daily call budget logic."""

from datetime import datetime, timedelta, timezone

from app.intelligence import budget as budget_module


def _force_in_memory_budget_backend(monkeypatch) -> None:
    """Keep tests deterministic and independent of Redis availability."""
    monkeypatch.setattr(budget_module, "_get_redis_client", lambda: None)


def test_budget_disabled_allows_calls_without_limits(monkeypatch):
    _force_in_memory_budget_backend(monkeypatch)
    monkeypatch.setattr(
        budget_module.settings,
        "intelligence_daily_call_limit_per_project",
        0,
    )

    status = budget_module.consume_intelligence_budget_call("project-a")
    assert status.enforced is False
    assert status.allowed is True
    assert status.limit is None
    assert status.remaining is None
    assert status.retry_after_seconds is None


def test_budget_consumes_until_limit_then_blocks(monkeypatch):
    _force_in_memory_budget_backend(monkeypatch)
    monkeypatch.setattr(
        budget_module.settings,
        "intelligence_daily_call_limit_per_project",
        2,
    )

    now = datetime(2026, 4, 13, 10, 30, tzinfo=timezone.utc)
    first = budget_module.consume_intelligence_budget_call("project-b", now=now)
    second = budget_module.consume_intelligence_budget_call("project-b", now=now)
    third = budget_module.consume_intelligence_budget_call("project-b", now=now)

    assert first.allowed is True
    assert first.used == 1
    assert first.remaining == 1

    assert second.allowed is True
    assert second.used == 2
    assert second.remaining == 0

    assert third.allowed is False
    assert third.used == 2
    assert third.remaining == 0
    assert third.retry_after_seconds is not None
    assert third.retry_after_seconds > 0


def test_budget_status_reports_exhausted_state(monkeypatch):
    _force_in_memory_budget_backend(monkeypatch)
    monkeypatch.setattr(
        budget_module.settings,
        "intelligence_daily_call_limit_per_project",
        1,
    )

    now = datetime(2026, 4, 13, 23, 59, 0, tzinfo=timezone.utc)
    budget_module.consume_intelligence_budget_call("project-c", now=now)
    status = budget_module.get_intelligence_budget_status("project-c", now=now)

    assert status.enforced is True
    assert status.limit == 1
    assert status.used == 1
    assert status.allowed is False
    assert status.retry_after_seconds is not None
    assert 1 <= status.retry_after_seconds <= 60


def test_budget_resets_on_new_utc_day(monkeypatch):
    _force_in_memory_budget_backend(monkeypatch)
    monkeypatch.setattr(
        budget_module.settings,
        "intelligence_daily_call_limit_per_project",
        1,
    )

    day_one = datetime(2026, 4, 13, 23, 59, 58, tzinfo=timezone.utc)
    day_two = day_one + timedelta(seconds=3)

    first_day = budget_module.consume_intelligence_budget_call("project-d", now=day_one)
    second_day = budget_module.consume_intelligence_budget_call("project-d", now=day_two)

    assert first_day.allowed is True
    assert first_day.used == 1
    assert second_day.allowed is True
    assert second_day.used == 1
