"""Tests for project alert rules and evaluation endpoints."""

from datetime import datetime, timezone

import app.alerts as alert_service
from app.config import settings
from app.models import ProjectAlertDestination
from app.secret_crypto import ENCRYPTED_SECRET_PREFIX


def _create_project(client, name: str) -> str:
    response = client.post("/api/v1/projects/", json={"name": name})
    assert response.status_code == 201
    return response.json()["api_key"]


def _create_scoped_key(client, admin_api_key: str, name: str, scopes: list[str]) -> str:
    response = client.post(
        "/api/v1/projects/me/keys",
        json={"name": name, "scopes": scopes},
        headers={"X-API-Key": admin_api_key},
    )
    assert response.status_code == 201
    return response.json()["api_key"]


def _ingest_trace_span(
    client,
    *,
    api_key: str,
    suffix: str,
    status: str,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    response = client.post(
        "/api/v1/traces/spans/batch",
        headers={"X-API-Key": api_key},
        json=[
            {
                "span_id": f"span-alert-{suffix}",
                "trace_id": f"trace-alert-{suffix}",
                "name": "alert-test",
                "status": status,
                "start_time": now,
                "duration_ms": 100,
                "tokens": 250,
                "cost": 0.01,
            }
        ],
    )
    assert response.status_code == 201


def test_alert_rule_crud_lifecycle(client):
    """Project owners can create, update, list, and delete alert rules."""
    api_key = _create_project(client, "alerts-crud")
    headers = {"X-API-Key": api_key}

    create_response = client.post(
        "/api/v1/projects/me/alerts",
        headers=headers,
        json={
            "name": "Error rate guardrail",
            "metric": "error_rate_percent",
            "operator": "gte",
            "threshold": 5,
            "window_days": 7,
            "is_active": True,
        },
    )
    assert create_response.status_code == 201
    rule = create_response.json()
    assert rule["name"] == "Error rate guardrail"
    assert rule["metric"] == "error_rate_percent"
    assert rule["operator"] == "gte"
    assert rule["threshold"] == 5.0
    assert rule["window_days"] == 7
    assert rule["is_active"] is True
    assert rule["last_triggered_at"] is None

    list_response = client.get("/api/v1/projects/me/alerts", headers=headers)
    assert list_response.status_code == 200
    assert len(list_response.json()) == 1

    rule_id = rule["id"]
    update_response = client.put(
        f"/api/v1/projects/me/alerts/{rule_id}",
        headers=headers,
        json={
            "threshold": 12.5,
            "window_days": 14,
            "is_active": False,
        },
    )
    assert update_response.status_code == 200
    updated = update_response.json()
    assert updated["threshold"] == 12.5
    assert updated["window_days"] == 14
    assert updated["is_active"] is False

    delete_response = client.delete(
        f"/api/v1/projects/me/alerts/{rule_id}",
        headers=headers,
    )
    assert delete_response.status_code == 204

    final_list = client.get("/api/v1/projects/me/alerts", headers=headers)
    assert final_list.status_code == 200
    assert final_list.json() == []


def test_alert_evaluation_detects_breach_and_can_persist_trigger_state(client):
    """Evaluation computes SLO metrics and marks breached rules."""
    api_key = _create_project(client, "alerts-evaluate")
    headers = {"X-API-Key": api_key}

    _ingest_trace_span(client, api_key=api_key, suffix="ok", status="success")
    _ingest_trace_span(client, api_key=api_key, suffix="err", status="error")

    create_rule = client.post(
        "/api/v1/projects/me/alerts",
        headers=headers,
        json={
            "name": "Error rate >= 40%",
            "metric": "error_rate_percent",
            "operator": "gte",
            "threshold": 40,
            "window_days": 30,
            "is_active": True,
        },
    )
    assert create_rule.status_code == 201
    rule_id = create_rule.json()["id"]

    evaluate_response = client.get("/api/v1/projects/me/alerts/evaluate", headers=headers)
    assert evaluate_response.status_code == 200
    payload = evaluate_response.json()

    assert payload["alert_count"] == 1
    assert len(payload["rules"]) == 1
    assert payload["rules"][0]["id"] == rule_id
    assert payload["rules"][0]["breached"] is True
    assert payload["rules"][0]["current_value"] == 50.0
    assert payload["rules"][0]["last_triggered_at"] is None

    evaluate_persist = client.get(
        "/api/v1/projects/me/alerts/evaluate",
        headers=headers,
        params={"persist": "true"},
    )
    assert evaluate_persist.status_code == 200
    persisted_payload = evaluate_persist.json()
    assert persisted_payload["alert_count"] == 1
    assert persisted_payload["rules"][0]["last_triggered_at"] is not None

    list_response = client.get("/api/v1/projects/me/alerts", headers=headers)
    assert list_response.status_code == 200
    assert list_response.json()[0]["last_triggered_at"] is not None


def test_alert_scopes_allow_read_but_restrict_mutations(client):
    """Read-scoped keys may evaluate/list alerts but cannot mutate rules."""
    admin_key = _create_project(client, "alerts-scopes")
    read_key = _create_scoped_key(client, admin_key, "alerts-reader", ["read"])

    create_denied = client.post(
        "/api/v1/projects/me/alerts",
        headers={"X-API-Key": read_key},
        json={
            "name": "Should fail",
            "metric": "trace_count",
            "operator": "gte",
            "threshold": 1,
            "window_days": 7,
            "is_active": True,
        },
    )
    assert create_denied.status_code == 403
    assert "required scope: admin" in create_denied.json()["detail"]

    admin_create = client.post(
        "/api/v1/projects/me/alerts",
        headers={"X-API-Key": admin_key},
        json={
            "name": "Trace count floor",
            "metric": "trace_count",
            "operator": "gte",
            "threshold": 1,
            "window_days": 7,
            "is_active": True,
        },
    )
    assert admin_create.status_code == 201

    list_allowed = client.get("/api/v1/projects/me/alerts", headers={"X-API-Key": read_key})
    assert list_allowed.status_code == 200
    assert len(list_allowed.json()) == 1

    evaluate_allowed = client.get(
        "/api/v1/projects/me/alerts/evaluate",
        headers={"X-API-Key": read_key},
    )
    assert evaluate_allowed.status_code == 200

    events_allowed = client.get(
        "/api/v1/projects/me/alerts/events",
        headers={"X-API-Key": read_key},
    )
    assert events_allowed.status_code == 200


def test_alert_destination_crud_and_scope_controls(client):
    """Alert destinations support CRUD and honor key scopes."""
    admin_key = _create_project(client, "alerts-destinations")
    read_key = _create_scoped_key(client, admin_key, "alerts-destinations-reader", ["read"])

    create_response = client.post(
        "/api/v1/projects/me/alerts/destinations",
        headers={"X-API-Key": admin_key},
        json={
            "name": "Primary webhook",
            "kind": "webhook",
            "target_url": "https://example.com/alerts",
            "secret_token": "secret",
            "is_active": True,
        },
    )
    assert create_response.status_code == 201
    destination = create_response.json()
    assert destination["name"] == "Primary webhook"
    assert destination["kind"] == "webhook"

    list_response = client.get(
        "/api/v1/projects/me/alerts/destinations",
        headers={"X-API-Key": read_key},
    )
    assert list_response.status_code == 200
    assert len(list_response.json()) == 1

    create_denied = client.post(
        "/api/v1/projects/me/alerts/destinations",
        headers={"X-API-Key": read_key},
        json={
            "name": "Nope",
            "kind": "webhook",
            "target_url": "https://example.com/blocked",
        },
    )
    assert create_denied.status_code == 403

    destination_id = destination["id"]
    update_response = client.put(
        f"/api/v1/projects/me/alerts/destinations/{destination_id}",
        headers={"X-API-Key": admin_key},
        json={"is_active": False},
    )
    assert update_response.status_code == 200
    assert update_response.json()["is_active"] is False

    delete_response = client.delete(
        f"/api/v1/projects/me/alerts/destinations/{destination_id}",
        headers={"X-API-Key": admin_key},
    )
    assert delete_response.status_code == 204


def test_alert_destination_rejects_disallowed_webhook_targets(client):
    """Webhook destination validation should reject SSRF-prone targets."""
    api_key = _create_project(client, "alerts-destination-security")
    headers = {"X-API-Key": api_key}

    localhost_response = client.post(
        "/api/v1/projects/me/alerts/destinations",
        headers=headers,
        json={
            "name": "Localhost webhook",
            "kind": "webhook",
            "target_url": "http://localhost:8080/hook",
            "is_active": True,
        },
    )
    assert localhost_response.status_code == 422

    credentialed_response = client.post(
        "/api/v1/projects/me/alerts/destinations",
        headers=headers,
        json={
            "name": "Credentialed webhook",
            "kind": "webhook",
            "target_url": "https://user:pass@example.com/hook",
            "is_active": True,
        },
    )
    assert credentialed_response.status_code == 422


def test_alert_destination_secret_is_encrypted_at_rest(client, test_db):
    """Destination secret tokens should be stored encrypted in DB."""
    api_key = _create_project(client, "alerts-destination-encryption")
    headers = {"X-API-Key": api_key}

    create_response = client.post(
        "/api/v1/projects/me/alerts/destinations",
        headers=headers,
        json={
            "name": "Encrypted secret destination",
            "kind": "webhook",
            "target_url": "https://example.com/alerts",
            "secret_token": "very-secret-token",
            "is_active": True,
        },
    )
    assert create_response.status_code == 201
    destination_name = create_response.json()["name"]

    destination = (
        test_db.query(ProjectAlertDestination)
        .filter(ProjectAlertDestination.name == destination_name)
        .first()
    )
    assert destination is not None
    assert destination.secret_token != "very-secret-token"
    assert destination.secret_token.startswith(ENCRYPTED_SECRET_PREFIX)


def test_alert_notify_respects_cooldown_and_does_not_repeat_immediately(client, monkeypatch):
    """Notification delivery should respect per-rule cooldown."""
    api_key = _create_project(client, "alerts-notify")
    headers = {"X-API-Key": api_key}

    _ingest_trace_span(client, api_key=api_key, suffix="notify-err", status="error")
    client.post(
        "/api/v1/projects/me/alerts",
        headers=headers,
        json={
            "name": "Error rate >= 50%",
            "metric": "error_rate_percent",
            "operator": "gte",
            "threshold": 50,
            "window_days": 30,
            "is_active": True,
            "notification_cooldown_minutes": 60,
        },
    )

    create_destination = client.post(
        "/api/v1/projects/me/alerts/destinations",
        headers=headers,
        json={
            "name": "Notify webhook",
            "kind": "webhook",
            "target_url": "https://example.com/alerts",
            "secret_token": "notify-secret-token",
            "is_active": True,
        },
    )
    assert create_destination.status_code == 201

    delivered_payloads = []

    def _mock_post_webhook_json(target_url, payload, secret_token=None):
        delivered_payloads.append((target_url, payload, secret_token))
        return True

    monkeypatch.setattr(alert_service, "_post_webhook_json", _mock_post_webhook_json)

    first_eval = client.get(
        "/api/v1/projects/me/alerts/evaluate",
        headers=headers,
        params={"persist": "true", "notify": "true"},
    )
    assert first_eval.status_code == 200
    first_payload = first_eval.json()
    assert first_payload["alert_count"] == 1
    assert first_payload["notifications_sent"] == 1
    assert first_payload["notifications_failed"] == 0
    assert first_payload["rules"][0]["notification_sent"] is True
    assert first_payload["rules"][0]["last_notified_at"] is not None
    assert len(delivered_payloads) == 1
    assert delivered_payloads[0][2] == "notify-secret-token"

    second_eval = client.get(
        "/api/v1/projects/me/alerts/evaluate",
        headers=headers,
        params={"persist": "true", "notify": "true"},
    )
    assert second_eval.status_code == 200
    second_payload = second_eval.json()
    assert second_payload["alert_count"] == 1
    assert second_payload["notifications_sent"] == 0
    assert second_payload["rules"][0]["notification_sent"] is False
    assert len(delivered_payloads) == 1


def test_alert_notify_async_enqueues_jobs(client, monkeypatch):
    """Async mode should queue notifications instead of sending in-request."""
    api_key = _create_project(client, "alerts-notify-async")
    headers = {"X-API-Key": api_key}

    _ingest_trace_span(client, api_key=api_key, suffix="async-err", status="error")
    client.post(
        "/api/v1/projects/me/alerts",
        headers=headers,
        json={
            "name": "Error rate >= 50%",
            "metric": "error_rate_percent",
            "operator": "gte",
            "threshold": 50,
            "window_days": 30,
            "is_active": True,
            "notification_cooldown_minutes": 60,
        },
    )

    client.post(
        "/api/v1/projects/me/alerts/destinations",
        headers=headers,
        json={
            "name": "Async webhook",
            "kind": "webhook",
            "target_url": "https://example.com/alerts",
            "is_active": True,
        },
    )

    queued_jobs = []

    def _mock_enqueue_alert_notification_job(job):
        queued_jobs.append(job)
        return True

    monkeypatch.setattr(settings, "alert_notification_async_enabled", True)
    monkeypatch.setattr(
        alert_service,
        "enqueue_alert_notification_job",
        _mock_enqueue_alert_notification_job,
    )

    evaluate_response = client.get(
        "/api/v1/projects/me/alerts/evaluate",
        headers=headers,
        params={"persist": "true", "notify": "true"},
    )
    assert evaluate_response.status_code == 200
    payload = evaluate_response.json()
    assert payload["alert_count"] == 1
    assert payload["notifications_queued"] == 1
    assert payload["notifications_sent"] == 0
    assert payload["rules"][0]["notification_queued"] is True
    assert len(queued_jobs) == 1

    queued_events = client.get(
        "/api/v1/projects/me/alerts/events",
        headers=headers,
        params={"event_type": "notification_queued"},
    )
    assert queued_events.status_code == 200
    assert len(queued_events.json()) >= 1


def test_alert_events_endpoint_lists_and_filters_event_history(client, monkeypatch):
    """Events endpoint should expose breach and delivery history."""
    api_key = _create_project(client, "alerts-events")
    headers = {"X-API-Key": api_key}

    _ingest_trace_span(client, api_key=api_key, suffix="events-err", status="error")
    create_rule = client.post(
        "/api/v1/projects/me/alerts",
        headers=headers,
        json={
            "name": "Error rate >= 50%",
            "metric": "error_rate_percent",
            "operator": "gte",
            "threshold": 50,
            "window_days": 30,
            "is_active": True,
            "notification_cooldown_minutes": 60,
        },
    )
    assert create_rule.status_code == 201
    rule_id = create_rule.json()["id"]

    create_destination = client.post(
        "/api/v1/projects/me/alerts/destinations",
        headers=headers,
        json={
            "name": "Events webhook",
            "kind": "webhook",
            "target_url": "https://example.com/alerts",
            "is_active": True,
        },
    )
    assert create_destination.status_code == 201

    monkeypatch.setattr(alert_service, "_post_webhook_json", lambda *_args, **_kwargs: True)

    evaluate_response = client.get(
        "/api/v1/projects/me/alerts/evaluate",
        headers=headers,
        params={"persist": "true", "notify": "true"},
    )
    assert evaluate_response.status_code == 200

    list_events = client.get("/api/v1/projects/me/alerts/events", headers=headers)
    assert list_events.status_code == 200
    events = list_events.json()
    assert len(events) >= 2
    event_types = {event["event_type"] for event in events}
    assert "breach" in event_types
    assert "notification_sent" in event_types
    assert any(event["rule_id"] == rule_id for event in events)

    filtered = client.get(
        "/api/v1/projects/me/alerts/events",
        headers=headers,
        params={"event_type": "notification_sent"},
    )
    assert filtered.status_code == 200
    filtered_events = filtered.json()
    assert filtered_events
    assert all(event["event_type"] == "notification_sent" for event in filtered_events)

    evaluate_again = client.get(
        "/api/v1/projects/me/alerts/evaluate",
        headers=headers,
        params={"persist": "true", "notify": "true"},
    )
    assert evaluate_again.status_code == 200

    events_after_second_eval = client.get(
        "/api/v1/projects/me/alerts/events",
        headers=headers,
        params={"event_type": "breach"},
    )
    assert events_after_second_eval.status_code == 200
    breach_events = events_after_second_eval.json()
    # Breach events are deduplicated within cooldown windows to avoid event spam.
    assert len(breach_events) == 1
