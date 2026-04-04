"""Tests for alert scheduler tick and loop behavior."""

import asyncio
from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

import app.alert_scheduler as alert_scheduler
from app.alerts import AlertEvaluationResult


class _FakeProjectQuery:
    def __init__(self, projects):
        self._projects = projects

    def all(self):
        return self._projects


class _FakeDB:
    def __init__(self, projects):
        self._projects = projects
        self.rollback_calls = 0

    def query(self, _model):
        return _FakeProjectQuery(self._projects)

    def rollback(self):
        self.rollback_calls += 1


def test_run_alert_scheduler_tick_aggregates_results(monkeypatch):
    """Scheduler tick should aggregate evaluated rule/breach totals."""
    projects = [SimpleNamespace(id=uuid4()), SimpleNamespace(id=uuid4())]
    fake_db = _FakeDB(projects)

    @contextmanager
    def _fake_get_db_session():
        yield fake_db

    def _fake_evaluate(_db, project, *, persist, notify):
        assert persist is True
        assert notify is False
        if project.id == projects[0].id:
            return AlertEvaluationResult(
                generated_at=datetime.now(timezone.utc),
                alert_count=1,
                rule_results=[object(), object()],
                window_metrics=[],
                notifications_sent=0,
                notifications_failed=0,
            )
        return AlertEvaluationResult(
            generated_at=datetime.now(timezone.utc),
            alert_count=2,
            rule_results=[object()],
            window_metrics=[],
            notifications_sent=0,
            notifications_failed=0,
        )

    monkeypatch.setattr(alert_scheduler, "get_db_session", _fake_get_db_session)
    monkeypatch.setattr(alert_scheduler, "evaluate_project_alerts", _fake_evaluate)

    project_count, rule_count, breach_count = alert_scheduler.run_alert_scheduler_tick(
        notify=False
    )
    assert project_count == 2
    assert rule_count == 3
    assert breach_count == 3


def test_run_alert_scheduler_tick_continues_on_project_failure(monkeypatch):
    """Scheduler tick should skip failed projects and continue."""
    projects = [SimpleNamespace(id=uuid4()), SimpleNamespace(id=uuid4())]
    fake_db = _FakeDB(projects)

    @contextmanager
    def _fake_get_db_session():
        yield fake_db

    def _fake_evaluate(_db, project, *, persist, notify):
        if project.id == projects[0].id:
            raise RuntimeError("boom")
        return AlertEvaluationResult(
            generated_at=datetime.now(timezone.utc),
            alert_count=1,
            rule_results=[object()],
            window_metrics=[],
            notifications_sent=0,
            notifications_failed=0,
        )

    monkeypatch.setattr(alert_scheduler, "get_db_session", _fake_get_db_session)
    monkeypatch.setattr(alert_scheduler, "evaluate_project_alerts", _fake_evaluate)

    project_count, rule_count, breach_count = alert_scheduler.run_alert_scheduler_tick(
        notify=False
    )
    assert project_count == 2
    assert rule_count == 1
    assert breach_count == 1
    assert fake_db.rollback_calls == 1


@pytest.mark.asyncio
async def test_run_alert_scheduler_stops_when_event_set(monkeypatch):
    """Scheduler loop should stop cleanly after the stop event is set."""
    stop_event = asyncio.Event()
    tick_calls = 0

    def _fake_tick(*, notify):
        nonlocal tick_calls
        tick_calls += 1
        assert notify is False
        stop_event.set()
        return (0, 0, 0)

    monkeypatch.setattr(alert_scheduler, "run_alert_scheduler_tick", _fake_tick)
    monkeypatch.setattr(alert_scheduler.settings, "alert_scheduler_notify", False)
    monkeypatch.setattr(alert_scheduler.settings, "alert_scheduler_interval_seconds", 1)

    await alert_scheduler.run_alert_scheduler(stop_event)
    assert tick_calls == 1
