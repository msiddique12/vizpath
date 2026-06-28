"""Tests for centralized sensitive data redaction controls."""

from __future__ import annotations

from datetime import datetime, timezone


def _create_project(client, name: str) -> str:
    response = client.post("/api/v1/projects/", json={"name": name})
    assert response.status_code == 201
    return response.json()["api_key"]


def _headers(api_key: str) -> dict[str, str]:
    return {"X-API-Key": api_key}


def _create_scoped_key(client, admin_api_key: str, name: str, scopes: list[str]) -> str:
    response = client.post(
        "/api/v1/projects/me/keys",
        json={"name": name, "scopes": scopes},
        headers=_headers(admin_api_key),
    )
    assert response.status_code == 201
    return response.json()["api_key"]


def _sensitive_span(trace_id: str = "trace-redaction", span_id: str = "span-redaction"):
    now = datetime.now(timezone.utc).isoformat()
    return {
        "span_id": span_id,
        "trace_id": trace_id,
        "name": "llm.call",
        "span_type": "llm",
        "status": "success",
        "start_time": now,
        "end_time": now,
        "attributes": {"model": "gpt-4", "api_key": "sk-secret-value"},
        "input": {"email": "alice@example.com", "password": "super-secret"},
        "output": {"message": "Call Alice at 312-555-1212"},
        "trace_name": "Sensitive trace",
        "trace_metadata": {"run_id": "redaction-run"},
    }


def _ingest(client, api_key: str, span: dict) -> int:
    response = client.post(
        "/api/v1/traces/spans/batch",
        headers=_headers(api_key),
        json=[span],
    )
    return response.status_code


def test_redaction_policy_defaults_and_admin_update(client):
    api_key = _create_project(client, "redaction-policy")
    read_key = _create_scoped_key(client, api_key, "reader", ["read"])

    default_response = client.get(
        "/api/v1/projects/me/redaction-policy",
        headers=_headers(read_key),
    )
    assert default_response.status_code == 200
    assert default_response.json()["enabled"] is True
    assert default_response.json()["mode"] == "audit_only"

    denied_update = client.put(
        "/api/v1/projects/me/redaction-policy",
        headers=_headers(read_key),
        json={"mode": "redact_on_write"},
    )
    assert denied_update.status_code == 403

    admin_key = _create_scoped_key(client, api_key, "admin", ["admin"])
    update = client.put(
        "/api/v1/projects/me/redaction-policy",
        headers=_headers(admin_key),
        json={"mode": "redact_on_write", "rules": {"disabled_rule_ids": []}},
    )
    assert update.status_code == 200
    assert update.json()["mode"] == "redact_on_write"


def test_preview_redacts_payload_without_raw_findings(client):
    api_key = _create_project(client, "redaction-preview")

    response = client.post(
        "/api/v1/redaction/preview",
        headers=_headers(api_key),
        json={
            "payload": {
                "authorization": "Bearer abcdefghijklmnopqrstuvwxyz",
                "email": "alice@example.com",
            }
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["preview"]["authorization"] == "[REDACTED]"
    assert data["preview"]["email"] == "[REDACTED]"
    assert data["findings"]
    assert "alice@example.com" not in str(data["findings"])
    assert all("value_fingerprint" in finding for finding in data["findings"])


def test_audit_only_records_findings_but_preserves_stored_span(client):
    api_key = _create_project(client, "redaction-audit")
    span = _sensitive_span()

    assert _ingest(client, api_key, span) == 201

    spans = client.get(
        f"/api/v1/traces/{span['trace_id']}/spans",
        headers=_headers(api_key),
    )
    assert spans.status_code == 200
    stored = spans.json()[0]
    assert stored["input"]["password"] == "super-secret"
    assert stored["attributes"]["api_key"] == "sk-secret-value"

    findings = client.get("/api/v1/redaction/findings", headers=_headers(api_key))
    assert findings.status_code == 200
    finding_rows = findings.json()["findings"]
    assert {row["rule_id"] for row in finding_rows} >= {"sensitive_key", "email", "phone"}
    assert "super-secret" not in str(finding_rows)


def test_redact_on_write_redacts_stored_span(client):
    api_key = _create_project(client, "redaction-write")
    policy = client.put(
        "/api/v1/projects/me/redaction-policy",
        headers=_headers(api_key),
        json={"mode": "redact_on_write"},
    )
    assert policy.status_code == 200

    span = _sensitive_span("trace-redact-write", "span-redact-write")
    assert _ingest(client, api_key, span) == 201

    spans = client.get(
        f"/api/v1/traces/{span['trace_id']}/spans",
        headers=_headers(api_key),
    )
    assert spans.status_code == 200
    stored = spans.json()[0]
    assert stored["input"]["password"] == "[REDACTED]"
    assert stored["input"]["email"] == "[REDACTED]"
    assert stored["attributes"]["api_key"] == "[REDACTED]"
    assert stored["output"]["message"] == "Call Alice at [REDACTED]"


def test_block_mode_rejects_high_severity_sensitive_data(client):
    api_key = _create_project(client, "redaction-block")
    policy = client.put(
        "/api/v1/projects/me/redaction-policy",
        headers=_headers(api_key),
        json={"mode": "block"},
    )
    assert policy.status_code == 200

    span = _sensitive_span("trace-redact-block", "span-redact-block")
    response = client.post(
        "/api/v1/traces/spans/batch",
        headers=_headers(api_key),
        json=[span],
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "sensitive_data_blocked"

    missing = client.get(
        f"/api/v1/traces/{span['trace_id']}",
        headers=_headers(api_key),
    )
    assert missing.status_code == 404


def test_findings_and_preview_are_project_isolated(client):
    key_a = _create_project(client, "redaction-project-a")
    key_b = _create_project(client, "redaction-project-b")
    span = _sensitive_span("trace-project-a", "span-project-a")
    assert _ingest(client, key_a, span) == 201

    own_findings = client.get("/api/v1/redaction/findings", headers=_headers(key_a))
    assert own_findings.status_code == 200
    assert own_findings.json()["total"] > 0

    foreign_findings = client.get("/api/v1/redaction/findings", headers=_headers(key_b))
    assert foreign_findings.status_code == 200
    assert foreign_findings.json()["total"] == 0

    foreign_preview = client.post(
        "/api/v1/redaction/preview",
        headers=_headers(key_b),
        json={"trace_id": "trace-project-a"},
    )
    assert foreign_preview.status_code == 404
