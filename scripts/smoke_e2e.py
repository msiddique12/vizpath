#!/usr/bin/env python3
"""End-to-end smoke checks for CI runtime wiring."""

from __future__ import annotations

import os
import sys
import time
from typing import Any

import httpx


SERVER_BASE = os.getenv("SMOKE_SERVER_BASE", "http://127.0.0.1:8000").rstrip("/")
DASHBOARD_BASE = os.getenv("SMOKE_DASHBOARD_BASE", "http://127.0.0.1:4173").rstrip("/")
API_BASE = f"{SERVER_BASE}/api/v1"
TIMEOUT_SECONDS = float(os.getenv("SMOKE_TIMEOUT_SECONDS", "10"))
WAIT_ATTEMPTS = int(os.getenv("SMOKE_WAIT_ATTEMPTS", "60"))
WAIT_SLEEP_SECONDS = float(os.getenv("SMOKE_WAIT_SLEEP_SECONDS", "1"))


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _wait_for_health(client: httpx.Client, url: str, name: str) -> None:
    last_error: str | None = None
    for _ in range(WAIT_ATTEMPTS):
        try:
            response = client.get(url)
            if response.status_code == 200:
                return
            last_error = f"unexpected status {response.status_code}"
        except Exception as exc:  # pragma: no cover - exercised in CI
            last_error = str(exc)
        time.sleep(WAIT_SLEEP_SECONDS)
    raise RuntimeError(f"{name} did not become healthy: {last_error}")


def _require_keys(payload: dict[str, Any], keys: set[str], context: str) -> None:
    missing = keys.difference(payload.keys())
    _assert(not missing, f"{context} missing keys: {sorted(missing)}")


def main() -> int:
    with httpx.Client(timeout=TIMEOUT_SECONDS) as client:
        _wait_for_health(client, f"{SERVER_BASE}/health", "server")
        _wait_for_health(client, f"{DASHBOARD_BASE}/", "dashboard")

        create_project = client.post(f"{API_BASE}/projects/", json={"name": "smoke-e2e"})
        _assert(create_project.status_code == 201, f"Project create failed: {create_project.text}")
        project_data = create_project.json()
        _require_keys(project_data, {"id", "name", "api_key"}, "project_create")
        api_key = project_data["api_key"]
        headers = {"X-API-Key": api_key}

        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        trace_id = "smoke-e2e-trace"
        ingest = client.post(
            f"{API_BASE}/traces/spans/batch",
            headers=headers,
            json=[
                {
                    "span_id": "smoke-e2e-span-1",
                    "trace_id": trace_id,
                    "name": "smoke-span",
                    "span_type": "llm",
                    "status": "success",
                    "start_time": now_iso,
                    "end_time": now_iso,
                    "duration_ms": 125.0,
                    "tokens": 42,
                    "cost": 0.001,
                }
            ],
        )
        _assert(ingest.status_code == 201, f"Trace ingest failed: {ingest.text}")

        traces = client.get(f"{API_BASE}/traces?limit=20&offset=0", headers=headers)
        _assert(traces.status_code == 200, f"Trace list failed: {traces.text}")
        trace_payload = traces.json()
        _require_keys(trace_payload, {"traces", "total", "limit", "offset"}, "trace_list")
        _assert(
            any(item.get("id") == trace_id for item in trace_payload["traces"]),
            "Ingested trace not found in trace list",
        )

        failure_modes = client.post(
            f"{API_BASE}/intelligence/failure-modes",
            headers=headers,
            json={"trace_id": trace_id},
        )
        _assert(failure_modes.status_code == 200, f"Failure modes failed: {failure_modes.text}")
        failure_data = failure_modes.json()
        _require_keys(
            failure_data,
            {"status", "primary_mode", "confidence", "modes", "summary", "trace_id"},
            "failure_modes",
        )

        copilot = client.post(
            f"{API_BASE}/intelligence/copilot",
            headers=headers,
            json={"trace_id": trace_id},
        )
        _assert(copilot.status_code == 200, f"Copilot failed: {copilot.text}")
        copilot_data = copilot.json()
        _require_keys(
            copilot_data,
            {"trace_id", "triage_status", "summary", "root_cause", "next_fixes", "generated_at"},
            "copilot",
        )

        intelligence_status = client.get(f"{API_BASE}/intelligence/status", headers=headers)
        _assert(
            intelligence_status.status_code == 200,
            f"Intelligence status failed: {intelligence_status.text}",
        )
        status_data = intelligence_status.json()
        _require_keys(
            status_data,
            {
                "nvidia_api_key_configured",
                "model",
                "base_url",
                "llm_timeout_seconds",
                "llm_max_tokens",
                "daily_call_budget",
            },
            "intelligence_status",
        )

        budget_status = client.get(f"{API_BASE}/projects/me/budget/status", headers=headers)
        _assert(budget_status.status_code == 200, f"Budget status failed: {budget_status.text}")
        budget_payload = budget_status.json()
        _require_keys(
            budget_payload,
            {
                "tokens_used",
                "cost_used",
                "monthly_token_limit",
                "monthly_cost_limit",
                "alert_threshold_percent",
                "hard_stop_enabled",
            },
            "project_budget_status",
        )

        dashboard_home = client.get(f"{DASHBOARD_BASE}/")
        _assert(dashboard_home.status_code == 200, "Dashboard home failed")
        _assert("id=\"root\"" in dashboard_home.text, "Dashboard root element not found")

        print("Smoke E2E checks passed")
        return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Smoke E2E checks failed: {exc}", file=sys.stderr)
        raise
