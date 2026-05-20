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
