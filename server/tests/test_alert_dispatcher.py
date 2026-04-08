"""Tests for asynchronous alert notification dispatcher."""

import app.alert_dispatcher as dispatcher
from app.alert_dispatcher import AlertNotificationJob


def _make_job() -> AlertNotificationJob:
    return AlertNotificationJob(
        project_id="11111111-1111-1111-1111-111111111111",
        rule_id="22222222-2222-2222-2222-222222222222",
        destination_id="33333333-3333-3333-3333-333333333333",
        destination_kind="webhook",
        target_url="https://example.com/alerts",
        secret_token=None,
        rule_name="error-rate",
        metric="error_rate_percent",
        operator="gte",
        threshold=50.0,
        current_value=100.0,
        generated_at="2026-04-06T00:00:00+00:00",
    )


def test_enqueue_returns_false_when_dispatcher_not_started():
    """Queueing without an active dispatcher should fail closed."""
    dispatcher.stop_alert_notification_dispatcher()
    assert dispatcher.enqueue_alert_notification_job(_make_job()) is False


def test_process_job_retries_and_records_success(monkeypatch):
    """Dispatcher retries failed sends and records the final outcome."""
    send_attempts = {"count": 0}
    outcomes = []

    def _fake_send(_job):
        send_attempts["count"] += 1
        return send_attempts["count"] >= 2

    def _fake_record(_job, delivered):
        outcomes.append(delivered)

    monkeypatch.setattr(dispatcher.settings, "alert_notification_max_retries", 3)
    monkeypatch.setattr(dispatcher.settings, "alert_notification_retry_backoff_seconds", 0.001)
    monkeypatch.setattr(dispatcher, "_post_webhook_json", _fake_send)
    monkeypatch.setattr(dispatcher, "_record_job_outcome", _fake_record)
    monkeypatch.setattr(dispatcher.time, "sleep", lambda *_args, **_kwargs: None)

    dispatcher._process_job(_make_job())

    assert send_attempts["count"] == 2
    assert outcomes == [True]
