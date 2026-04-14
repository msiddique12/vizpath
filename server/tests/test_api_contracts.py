"""API contract tests for critical endpoints and OpenAPI snapshot locking."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from app.main import app
from app.openapi_contract import extract_critical_openapi_contract

SNAPSHOT_PATH = Path(__file__).resolve().parent / "contracts" / "openapi_critical_snapshot.json"


def _create_project(client) -> dict[str, str]:
    response = client.post("/api/v1/projects/", json={"name": "api-contract-project"})
    assert response.status_code == 201
    payload = response.json()
    return {
        "project_id": payload["id"],
        "api_key": payload["api_key"],
    }


def _ingest_basic_trace(client, api_key: str, trace_id: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    response = client.post(
        "/api/v1/traces/spans/batch",
        headers={"X-API-Key": api_key},
        json=[
            {
                "span_id": f"{trace_id}-span-1",
                "trace_id": trace_id,
                "name": "contract-span",
                "span_type": "llm",
                "status": "success",
                "start_time": now,
                "end_time": now,
                "duration_ms": 150.0,
                "tokens": 50,
            },
        ],
    )
    assert response.status_code == 201


def test_openapi_critical_contract_matches_snapshot():
    """Critical OpenAPI contract should remain stable unless intentionally updated."""
    expected = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    actual = extract_critical_openapi_contract(app.openapi())
    assert actual == expected


class TestRuntimeApiContracts:
    """Runtime response contracts for key client-facing endpoints."""

    def test_intelligence_status_contract_shape(self, client, test_db):
        project = _create_project(client)
        response = client.get(
            "/api/v1/intelligence/status",
            headers={"X-API-Key": project["api_key"]},
        )
        assert response.status_code == 200
        payload = response.json()

        expected_keys = {
            "nvidia_api_key_configured",
            "model",
            "base_url",
            "llm_timeout_seconds",
            "llm_max_tokens",
            "daily_call_budget",
        }
        assert expected_keys.issubset(payload.keys())

        budget = payload["daily_call_budget"]
        budget_keys = {
            "enforced",
            "limit",
            "used",
            "remaining",
            "allowed",
            "resets_at",
            "retry_after_seconds",
        }
        assert budget_keys.issubset(budget.keys())

    def test_project_budget_status_contract_shape(self, client, test_db):
        project = _create_project(client)
        response = client.get(
            "/api/v1/projects/me/budget/status",
            headers={"X-API-Key": project["api_key"]},
        )
        assert response.status_code == 200
        payload = response.json()

        expected_keys = {
            "month_start",
            "month_end",
            "tokens_used",
            "cost_used",
            "monthly_token_limit",
            "monthly_cost_limit",
            "token_usage_percent",
            "cost_usage_percent",
            "alert_threshold_percent",
            "token_alert_triggered",
            "cost_alert_triggered",
            "alert_triggered",
            "hard_stop_enabled",
        }
        assert expected_keys.issubset(payload.keys())

    def test_failure_modes_contract_shape(self, client, test_db):
        project = _create_project(client)
        trace_id = "api-contract-failure-modes-trace"
        _ingest_basic_trace(client, project["api_key"], trace_id)

        response = client.post(
            "/api/v1/intelligence/failure-modes",
            headers={"X-API-Key": project["api_key"]},
            json={"trace_id": trace_id},
        )
        assert response.status_code == 200
        payload = response.json()

        expected_keys = {
            "status",
            "primary_mode",
            "confidence",
            "modes",
            "summary",
            "trace_id",
        }
        assert expected_keys.issubset(payload.keys())
