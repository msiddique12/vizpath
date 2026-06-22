"""Tests for product feature APIs built from trace data."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _create_project(client, name: str = "product-project") -> str:
    response = client.post("/api/v1/projects/", json={"name": name})
    assert response.status_code == 201
    return str(response.json()["api_key"])


def _headers(api_key: str) -> dict[str, str]:
    return {"X-API-Key": api_key}


def _span(
    trace_id: str,
    span_id: str,
    name: str,
    span_type: str,
    *,
    status: str = "success",
    duration_ms: float = 100.0,
    tokens: int | None = None,
    cost: float | None = None,
    input_value: Any | None = None,
    output_value: Any | None = None,
    error: str | None = None,
    trace_name: str | None = None,
    trace_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "span_id": span_id,
        "trace_id": trace_id,
        "name": name,
        "span_type": span_type,
        "status": status,
        "start_time": now,
        "end_time": now,
        "duration_ms": duration_ms,
        "tokens": tokens,
        "cost": cost,
        "input": input_value,
        "output": output_value,
        "error": error,
        "trace_name": trace_name or trace_id,
        "trace_metadata": trace_metadata or {},
    }


def _ingest_trace(
    client,
    api_key: str,
    trace_id: str,
    *,
    status: str = "success",
    tool_status: str = "success",
    error: str | None = None,
    trace_name: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    payload = [
        _span(
            trace_id,
            f"{trace_id}-agent",
            "agent.plan",
            "agent",
            status=status,
            duration_ms=250.0,
            input_value={"task": f"Investigate {trace_id}"},
            output_value={"plan": "search then answer"},
            trace_name=trace_name,
            trace_metadata=metadata,
        ),
        _span(
            trace_id,
            f"{trace_id}-tool",
            "tool.search",
            "tool",
            status=tool_status,
            duration_ms=500.0,
            input_value={"query": "pricing documents"},
            output_value={"result": "pricing found"},
            error=error,
            trace_name=trace_name,
            trace_metadata=metadata,
        ),
        _span(
            trace_id,
            f"{trace_id}-llm",
            "llm.answer",
            "llm",
            status=status,
            duration_ms=700.0,
            tokens=600,
            cost=0.03,
            input_value={"prompt": "Summarize pricing"},
            output_value={"answer": "The plan costs $10."},
            trace_name=trace_name,
            trace_metadata=metadata,
        ),
    ]
    response = client.post(
        "/api/v1/traces/spans/batch",
        headers=_headers(api_key),
        json=payload,
    )
    assert response.status_code == 201


def _label_trace(
    client,
    api_key: str,
    trace_id: str,
    *,
    label: str = "good",
    quality_score: float = 91,
) -> None:
    response = client.post(
        "/api/v1/curation/labels",
        headers=_headers(api_key),
        json={
            "trace_id": trace_id,
            "label": label,
            "quality_score": quality_score,
            "notes": "verified",
        },
    )
    assert response.status_code == 200


def test_scorecard_and_tool_analytics(client):
    api_key = _create_project(client)
    _ingest_trace(client, api_key, "prod-success", trace_name="Successful pricing agent")
    _ingest_trace(
        client,
        api_key,
        "prod-failure",
        status="error",
        tool_status="error",
        error="tool timeout while fetching pricing",
        trace_name="Failed pricing agent",
    )

    scorecard = client.get("/api/v1/analytics/scorecard", headers=_headers(api_key))
    assert scorecard.status_code == 200
    scorecard_data = scorecard.json()
    assert scorecard_data["trace_count"] == 2
    assert scorecard_data["success_count"] == 1
    assert scorecard_data["error_count"] == 1
    assert scorecard_data["reliability_score"] == 50.0
    assert scorecard_data["llm_call_count"] == 2
    assert scorecard_data["tool_call_count"] == 2
    assert scorecard_data["tool_success_rate"] == 50.0

    tools = client.get("/api/v1/analytics/tools", headers=_headers(api_key))
    assert tools.status_code == 200
    tool_data = tools.json()
    assert tool_data["tool_count"] == 1
    assert tool_data["tools"][0]["name"] == "tool.search"
    assert tool_data["tools"][0]["call_count"] == 2
    assert tool_data["tools"][0]["error_count"] == 1


def test_dataset_builder_filters_and_formats_records(client):
    api_key = _create_project(client)
    _ingest_trace(client, api_key, "dataset-good", trace_name="Dataset good")
    _ingest_trace(
        client,
        api_key,
        "dataset-error",
        status="error",
        tool_status="error",
        error="tool timeout",
        trace_name="Dataset error",
    )
    _label_trace(client, api_key, "dataset-good", label="excellent", quality_score=95)
    _label_trace(client, api_key, "dataset-error", label="failure", quality_score=20)

    response = client.post(
        "/api/v1/datasets/build",
        headers=_headers(api_key),
        json={
            "trace_ids": ["dataset-good", "dataset-error"],
            "format": "chat",
            "min_quality_score": 80,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["record_count"] == 1
    assert data["skipped_count"] == 1
    record = data["records"][0]
    assert record["trace_id"] == "dataset-good"
    assert record["label"] == "excellent"
    assert record["messages"][0]["role"] == "user"
    assert record["messages"][1]["role"] == "assistant"

    tool_response = client.post(
        "/api/v1/datasets/build",
        headers=_headers(api_key),
        json={
            "trace_ids": ["dataset-good"],
            "format": "tool_calls",
            "include_failed": True,
        },
    )
    assert tool_response.status_code == 200
    assert tool_response.json()["records"][0]["steps"][0]["name"] == "agent.plan"


def test_saved_dataset_build_redacts_by_default_and_downloads_jsonl(client):
    api_key = _create_project(client, "saved-dataset-project")
    now = datetime.now(timezone.utc).isoformat()
    response = client.post(
        "/api/v1/traces/spans/batch",
        headers=_headers(api_key),
        json=[
            {
                "span_id": "dataset-redact-span",
                "trace_id": "dataset-redact-trace",
                "name": "tool.secret",
                "span_type": "tool",
                "status": "success",
                "start_time": now,
                "end_time": now,
                "input": {"query": "pricing", "api_key": "secret-key"},
                "output": {"result": "ok", "access_token": "secret-token"},
                "trace_name": "Dataset redaction trace",
            }
        ],
    )
    assert response.status_code == 201

    build_response = client.post(
        "/api/v1/datasets/builds",
        headers=_headers(api_key),
        json={
            "trace_ids": ["dataset-redact-trace"],
            "name": "Redacted build",
            "format": "tool_calls",
            "include_raw": False,
        },
    )
    assert build_response.status_code == 201
    build = build_response.json()
    assert build["redaction_mode"] == "redacted"
    assert build["record_count"] == 1
    step = build["artifact"]["records"][0]["steps"][0]
    assert step["input"]["api_key"] == "[REDACTED]"
    assert step["output"]["access_token"] == "[REDACTED]"

    list_response = client.get("/api/v1/datasets/builds", headers=_headers(api_key))
    assert list_response.status_code == 200
    assert list_response.json()["total"] == 1

    download_response = client.get(
        f"/api/v1/datasets/builds/{build['id']}/download?format=jsonl",
        headers=_headers(api_key),
    )
    assert download_response.status_code == 200
    assert "dataset-redact-trace" in download_response.text


def test_saved_dataset_build_include_raw_is_explicit(client):
    api_key = _create_project(client, "saved-dataset-raw")
    now = datetime.now(timezone.utc).isoformat()
    response = client.post(
        "/api/v1/traces/spans/batch",
        headers=_headers(api_key),
        json=[
            {
                "span_id": "dataset-raw-span",
                "trace_id": "dataset-raw-trace",
                "name": "tool.raw",
                "span_type": "tool",
                "status": "success",
                "start_time": now,
                "end_time": now,
                "input": {"api_key": "secret-key"},
                "output": {"access_token": "secret-token"},
                "trace_name": "Dataset raw trace",
            }
        ],
    )
    assert response.status_code == 201

    build_response = client.post(
        "/api/v1/datasets/builds",
        headers=_headers(api_key),
        json={
            "trace_ids": ["dataset-raw-trace"],
            "name": "Raw build",
            "format": "tool_calls",
            "include_raw": True,
        },
    )
    assert build_response.status_code == 201
    build = build_response.json()
    assert build["redaction_mode"] == "raw"
    assert build["options"]["include_raw"] is True
    step = build["artifact"]["records"][0]["steps"][0]
    assert step["input"]["api_key"] == "secret-key"
    assert step["output"]["access_token"] == "secret-token"


def test_saved_dataset_builds_are_project_isolated(client):
    api_key_a = _create_project(client, "dataset-a")
    api_key_b = _create_project(client, "dataset-b")
    _ingest_trace(client, api_key_a, "dataset-a-trace")
    _ingest_trace(client, api_key_b, "dataset-b-trace")

    build_response = client.post(
        "/api/v1/datasets/builds",
        headers=_headers(api_key_a),
        json={"trace_ids": ["dataset-a-trace"], "name": "A build"},
    )
    assert build_response.status_code == 201
    build_id = build_response.json()["id"]

    foreign_detail = client.get(f"/api/v1/datasets/builds/{build_id}", headers=_headers(api_key_b))
    assert foreign_detail.status_code == 404

    foreign_download = client.get(
        f"/api/v1/datasets/builds/{build_id}/download",
        headers=_headers(api_key_b),
    )
    assert foreign_download.status_code == 404


def test_eval_suite_generates_assertions_from_trace_metrics(client):
    api_key = _create_project(client)
    _ingest_trace(client, api_key, "eval-source", trace_name="Eval source")

    response = client.post(
        "/api/v1/evals/suite",
        headers=_headers(api_key),
        json={
            "trace_ids": ["eval-source"],
            "name": "Pricing regression",
            "assertion_profile": "strict",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Pricing regression"
    assert data["case_count"] == 1
    case = data["cases"][0]
    assert case["source_trace_id"] == "eval-source"
    assert case["input"] == {"task": "Investigate eval-source"}
    assertion_metrics = {assertion["metric"] for assertion in case["assertions"]}
    assert {"error_count", "span_count", "duration_ms", "total_cost", "tool_calls"}.issubset(
        assertion_metrics
    )


def test_saved_eval_suite_and_run_results_are_persisted(client):
    api_key = _create_project(client, "saved-eval-project")
    _ingest_trace(
        client,
        api_key,
        "eval-baseline",
        trace_name="Eval baseline",
        metadata={"api_key": "metadata-secret"},
    )
    _ingest_trace(client, api_key, "eval-candidate-ok", trace_name="Eval candidate ok")
    _ingest_trace(
        client,
        api_key,
        "eval-candidate-fail",
        status="error",
        tool_status="error",
        error="tool timeout",
        trace_name="Eval candidate fail",
    )

    suite_response = client.post(
        "/api/v1/evals/suites",
        headers=_headers(api_key),
        json={
            "trace_ids": ["eval-baseline"],
            "name": "Saved pricing regression",
            "assertion_profile": "strict",
        },
    )
    assert suite_response.status_code == 201
    suite = suite_response.json()
    assert suite["name"] == "Saved pricing regression"
    assert suite["case_count"] == 1
    assert suite["cases"][0]["input"] == {"task": "Investigate eval-baseline"}

    list_response = client.get("/api/v1/evals/suites", headers=_headers(api_key))
    assert list_response.status_code == 200
    assert list_response.json()["total"] == 1

    run_response = client.post(
        f"/api/v1/evals/suites/{suite['id']}/runs",
        headers=_headers(api_key),
        json={
            "name": "Candidate run",
            "candidate_trace_ids": ["eval-candidate-ok", "eval-candidate-fail"],
        },
    )
    assert run_response.status_code == 201
    run = run_response.json()
    assert run["suite_id"] == suite["id"]
    assert run["pass_count"] == 1
    assert run["fail_count"] == 1
    assert run["passed"] is False
    assert len(run["results"]) == 2

    detail_response = client.get(f"/api/v1/evals/runs/{run['id']}", headers=_headers(api_key))
    assert detail_response.status_code == 200
    assert detail_response.json()["fail_count"] == 1


def test_saved_eval_suites_are_project_isolated(client):
    api_key_a = _create_project(client, "saved-eval-a")
    api_key_b = _create_project(client, "saved-eval-b")
    _ingest_trace(client, api_key_a, "eval-a")
    _ingest_trace(client, api_key_b, "eval-b")

    suite_response = client.post(
        "/api/v1/evals/suites",
        headers=_headers(api_key_a),
        json={"trace_ids": ["eval-a"], "name": "A suite"},
    )
    assert suite_response.status_code == 201
    suite_id = suite_response.json()["id"]

    foreign_detail = client.get(f"/api/v1/evals/suites/{suite_id}", headers=_headers(api_key_b))
    assert foreign_detail.status_code == 404

    foreign_run = client.post(
        f"/api/v1/evals/suites/{suite_id}/runs",
        headers=_headers(api_key_b),
        json={"candidate_trace_ids": ["eval-b"]},
    )
    assert foreign_run.status_code == 404


def test_saved_eval_suite_redacts_sensitive_case_payloads(client):
    api_key = _create_project(client, "saved-eval-redaction")
    now = datetime.now(timezone.utc).isoformat()
    response = client.post(
        "/api/v1/traces/spans/batch",
        headers=_headers(api_key),
        json=[
            {
                "span_id": "eval-redact-span",
                "trace_id": "eval-redact-trace",
                "name": "llm.redact",
                "span_type": "llm",
                "status": "success",
                "start_time": now,
                "end_time": now,
                "input": {"prompt": "hello", "api_key": "secret-key"},
                "output": {"answer": "ok", "access_token": "secret-token"},
                "trace_name": "Eval redaction trace",
            }
        ],
    )
    assert response.status_code == 201

    suite_response = client.post(
        "/api/v1/evals/suites",
        headers=_headers(api_key),
        json={"trace_ids": ["eval-redact-trace"], "name": "Redacted suite"},
    )
    assert suite_response.status_code == 201
    case = suite_response.json()["cases"][0]
    assert case["input"]["api_key"] == "[REDACTED]"
    assert case["expected_output"]["access_token"] == "[REDACTED]"


def test_trace_search_ranks_matches_and_preserves_project_isolation(client):
    api_key = _create_project(client, "search-project")
    other_api_key = _create_project(client, "other-search-project")
    _ingest_trace(
        client,
        api_key,
        "search-visible",
        trace_name="Visible pricing trace",
        metadata={"topic": "pricing"},
    )
    _ingest_trace(
        client,
        other_api_key,
        "search-hidden",
        trace_name="Hidden pricing trace",
        metadata={"topic": "pricing"},
    )

    response = client.post(
        "/api/v1/search/traces",
        headers=_headers(api_key),
        json={"query": "pricing", "limit": 10, "include_spans": True},
    )
    assert response.status_code == 200
    data = response.json()
    ids = [item["trace"]["id"] for item in data["results"]]
    assert "search-visible" in ids
    assert "search-hidden" not in ids
    assert data["results"][0]["matched_spans"]


def test_guardrail_defaults_and_custom_evaluation(client):
    api_key = _create_project(client)
    _ingest_trace(
        client,
        api_key,
        "guardrail-error",
        status="error",
        tool_status="error",
        error="tool timeout",
        trace_name="Guardrail error",
    )

    defaults = client.get("/api/v1/guardrails/defaults", headers=_headers(api_key))
    assert defaults.status_code == 200
    assert len(defaults.json()["policies"]) >= 3

    response = client.post(
        "/api/v1/guardrails/evaluate",
        headers=_headers(api_key),
        json={
            "trace_id": "guardrail-error",
            "policies": [
                {
                    "id": "no-errors",
                    "name": "No errors",
                    "metric": "error_count",
                    "operator": "eq",
                    "threshold": 0,
                    "severity": "critical",
                },
                {
                    "id": "cost-ok",
                    "name": "Cost acceptable",
                    "metric": "total_cost",
                    "operator": "lte",
                    "threshold": 1,
                    "severity": "low",
                },
            ],
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["trace_count"] == 1
    assert data["policy_count"] == 2
    assert data["breach_count"] == 1
    result = data["results"][0]
    assert result["passed"] is False
    policy_results = {policy["policy_id"]: policy for policy in result["policies"]}
    assert policy_results["no-errors"]["passed"] is False
    assert policy_results["cost-ok"]["passed"] is True
