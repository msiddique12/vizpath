"""Tests for project alert rules and evaluation endpoints."""

from datetime import datetime, timezone


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
