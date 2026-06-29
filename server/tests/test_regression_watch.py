"""Tests for durable Regression Watch workflows."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


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


def _span(
    trace_id: str,
    span_id: str,
    *,
    status: str = "success",
    duration_ms: float = 100.0,
    cost: float = 0.01,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "span_id": span_id,
        "trace_id": trace_id,
        "name": "tool.checkout",
        "span_type": "tool",
        "status": status,
        "start_time": now,
        "end_time": now,
        "duration_ms": duration_ms,
        "tokens": 100,
        "cost": cost,
        "input": {"route": "checkout"},
        "output": {"status": status},
        "trace_name": "Checkout route",
        "trace_metadata": metadata or {"route": "/checkout", "prompt_version": "v1"},
    }


def _ingest_trace(
    client,
    api_key: str,
    trace_id: str,
    *,
    status: str = "success",
    duration_ms: float = 100.0,
    cost: float = 0.01,
    metadata: dict[str, Any] | None = None,
) -> None:
    response = client.post(
        "/api/v1/traces/spans/batch",
        headers=_headers(api_key),
        json=[
            _span(
                trace_id,
                f"{trace_id}-tool",
                status=status,
                duration_ms=duration_ms,
                cost=cost,
                metadata=metadata,
            )
        ],
    )
    assert response.status_code == 201


def test_regression_watch_persists_same_group_results_and_reruns(client):
    api_key = _create_project(client, "regression-watch")
    _ingest_trace(client, api_key, "watch-baseline", cost=0.01)
    _ingest_trace(client, api_key, "watch-candidate", status="error", cost=0.20)

    list_response = client.get("/api/v1/regressions/watch", headers=_headers(api_key))
    assert list_response.status_code == 200
    results = list_response.json()["results"]
    candidate = next(row for row in results if row["trace_id"] == "watch-candidate")
    assert candidate["baseline_trace_id"] == "watch-baseline"
    assert candidate["group_key"] == "route"
    assert candidate["group_value"] == "/checkout"
    assert candidate["risk_level"] in {"medium", "high", "critical"}
    assert {signal["id"] for signal in candidate["signals"]} >= {
        "error-regression",
        "cost-regression",
    }

    detail = client.get("/api/v1/regressions/watch/watch-candidate", headers=_headers(api_key))
    assert detail.status_code == 200
    assert detail.json()["trace_id"] == "watch-candidate"

    read_key = _create_scoped_key(client, api_key, "reader", ["read"])
    curate_key = _create_scoped_key(client, api_key, "curator", ["curate"])
    denied_rerun = client.post(
        "/api/v1/regressions/watch/watch-candidate/rerun",
        headers=_headers(read_key),
    )
    assert denied_rerun.status_code == 403

    rerun = client.post(
        "/api/v1/regressions/watch/watch-candidate/rerun",
        headers=_headers(curate_key),
    )
    assert rerun.status_code == 200
    assert rerun.json()["baseline_trace_id"] == "watch-baseline"


def test_regression_watch_is_project_isolated(client):
    key_a = _create_project(client, "regression-watch-a")
    key_b = _create_project(client, "regression-watch-b")
    _ingest_trace(client, key_a, "watch-a-baseline", cost=0.01)
    _ingest_trace(client, key_a, "watch-a-candidate", status="error", cost=0.20)

    own = client.get("/api/v1/regressions/watch", headers=_headers(key_a))
    assert own.status_code == 200
    assert own.json()["total"] >= 1

    foreign_list = client.get("/api/v1/regressions/watch", headers=_headers(key_b))
    assert foreign_list.status_code == 200
    assert foreign_list.json()["total"] == 0

    foreign_detail = client.get(
        "/api/v1/regressions/watch/watch-a-candidate",
        headers=_headers(key_b),
    )
    assert foreign_detail.status_code == 404
