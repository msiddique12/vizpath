"""Tests for durable triage workflow APIs."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _create_project(client, name: str) -> str:
    response = client.post("/api/v1/projects/", json={"name": name})
    assert response.status_code == 201
    return str(response.json()["api_key"])


def _headers(api_key: str) -> dict[str, str]:
    return {"X-API-Key": api_key}


def _ingest_trace(client, api_key: str, trace_id: str, *, status: str = "error") -> None:
    now = datetime.now(timezone.utc).isoformat()
    response = client.post(
        "/api/v1/traces/spans/batch",
        headers=_headers(api_key),
        json=[
            {
                "span_id": f"span-{trace_id}",
                "trace_id": trace_id,
                "name": f"trace {trace_id}",
                "status": status,
                "start_time": now,
                "end_time": now,
                "error": "tool timeout" if status == "error" else None,
            }
        ],
    )
    assert response.status_code == 201


def _create_triage_item(client, api_key: str, trace_id: str) -> dict[str, Any]:
    response = client.post(
        "/api/v1/triage/items",
        headers=_headers(api_key),
        json={
            "trace_id": trace_id,
            "priority": "high",
            "failure_mode": "tool timeout",
            "title": "Investigate tool timeout",
            "notes": "Timeout started after deploy.",
        },
    )
    assert response.status_code == 201
    return response.json()


def test_triage_item_lifecycle_and_links(client):
    api_key = _create_project(client, "triage-project")
    _ingest_trace(client, api_key, "triage-primary")
    _ingest_trace(client, api_key, "triage-linked")

    item = _create_triage_item(client, api_key, "triage-primary")
    assert item["trace_id"] == "triage-primary"
    assert item["status"] == "open"
    assert item["priority"] == "high"
    assert item["failure_mode"] == "tool timeout"

    list_response = client.get("/api/v1/triage/items", headers=_headers(api_key))
    assert list_response.status_code == 200
    assert list_response.json()["total"] == 1

    update_response = client.patch(
        f"/api/v1/triage/items/{item['id']}",
        headers=_headers(api_key),
        json={"status": "investigating", "owner": "ops@example.com", "priority": "critical"},
    )
    assert update_response.status_code == 200
    updated = update_response.json()
    assert updated["status"] == "investigating"
    assert updated["owner"] == "ops@example.com"
    assert updated["priority"] == "critical"

    links_response = client.post(
        f"/api/v1/triage/items/{item['id']}/links",
        headers=_headers(api_key),
        json={"linked_trace_ids": ["triage-linked"]},
    )
    assert links_response.status_code == 200
    assert links_response.json()["linked_trace_ids"] == ["triage-linked"]


def test_triage_items_are_project_isolated(client):
    api_key_a = _create_project(client, "triage-a")
    api_key_b = _create_project(client, "triage-b")
    _ingest_trace(client, api_key_a, "triage-a-trace")
    _ingest_trace(client, api_key_b, "triage-b-trace")
    item = _create_triage_item(client, api_key_a, "triage-a-trace")

    foreign_list = client.get("/api/v1/triage/items", headers=_headers(api_key_b))
    assert foreign_list.status_code == 200
    assert foreign_list.json()["total"] == 0

    foreign_update = client.patch(
        f"/api/v1/triage/items/{item['id']}",
        headers=_headers(api_key_b),
        json={"status": "resolved"},
    )
    assert foreign_update.status_code == 404

    foreign_link = client.post(
        f"/api/v1/triage/items/{item['id']}/links",
        headers=_headers(api_key_a),
        json={"linked_trace_ids": ["triage-b-trace"]},
    )
    assert foreign_link.status_code == 404
