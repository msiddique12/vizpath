"""Tests for trace ingestion and retrieval endpoints."""

from datetime import datetime, timedelta, timezone

from app.auth import hash_api_key
from app.models import Project


class TestTraceIngestionAuth:
    """Tests for auth behavior on the ingestion endpoint."""

    def test_ingest_no_key_creates_default_project_when_fallback_enabled(self, client, test_db):
        """With dev fallback enabled, unauthenticated ingestion uses default project."""
        payload = [
            {
                "span_id": "span-auth-1",
                "trace_id": "trace-auth-1",
                "name": "test",
                "start_time": datetime.now(timezone.utc).isoformat(),
            }
        ]
        response = client.post("/api/v1/traces/spans/batch", json=payload)

        assert response.status_code == 201
        project = test_db.query(Project).filter(Project.api_key_hash == "default").first()
        assert project is not None

    def test_ingest_no_key_rejected_when_fallback_disabled(self, client, monkeypatch):
        """Missing API key is rejected by default when fallback mode is disabled."""
        from app.config import settings

        monkeypatch.setattr(settings, "allow_unauthenticated_dev_fallback", False)
        payload = [
            {
                "span_id": "span-auth-missing-key",
                "trace_id": "trace-auth-missing-key",
                "name": "test",
                "start_time": datetime.now(timezone.utc).isoformat(),
            }
        ]
        response = client.post("/api/v1/traces/spans/batch", json=payload)

        assert response.status_code == 401
        assert "Missing API key" in response.json()["detail"]

    def test_ingest_valid_key(self, client, test_db):
        """With a valid API key, spans are linked to that project."""
        api_key = "vp_test_valid_key"
        project = Project(name="test-project", api_key_hash=hash_api_key(api_key))
        test_db.add(project)
        test_db.commit()

        payload = [
            {
                "span_id": "span-auth-2",
                "trace_id": "trace-auth-2",
                "name": "test",
                "start_time": datetime.now(timezone.utc).isoformat(),
            }
        ]
        response = client.post(
            "/api/v1/traces/spans/batch",
            json=payload,
            headers={"X-API-Key": api_key},
        )

        assert response.status_code == 201
        assert response.json()["ingested"] == 1

    def test_ingest_invalid_key_rejected(self, client, test_db):
        """With an invalid API key, request is rejected with 401."""
        payload = [
            {
                "span_id": "span-auth-3",
                "trace_id": "trace-auth-3",
                "name": "test",
                "start_time": datetime.now(timezone.utc).isoformat(),
            }
        ]
        response = client.post(
            "/api/v1/traces/spans/batch",
            json=payload,
            headers={"X-API-Key": "vp_totally_bogus_key"},
        )

        assert response.status_code == 401
        assert "Invalid API key" in response.json()["detail"]


class TestTraceIngestion:
    def test_ingest_single_span(self, client):
        payload = [
            {
                "span_id": "span-1",
                "trace_id": "trace-1",
                "name": "test-span",
                "span_type": "llm",
                "status": "success",
                "start_time": datetime.now(timezone.utc).isoformat(),
                "duration_ms": 100,
            }
        ]

        response = client.post("/api/v1/traces/spans/batch", json=payload)

        assert response.status_code == 201
        assert response.json()["ingested"] == 1
        assert response.json()["traces"] == 1

    def test_ingest_multiple_spans(self, client):
        now = datetime.now(timezone.utc).isoformat()
        payload = [
            {
                "span_id": "span-1",
                "trace_id": "trace-1",
                "name": "parent",
                "span_type": "agent",
                "start_time": now,
            },
            {
                "span_id": "span-2",
                "trace_id": "trace-1",
                "parent_id": "span-1",
                "name": "child",
                "span_type": "llm",
                "start_time": now,
            },
        ]

        response = client.post("/api/v1/traces/spans/batch", json=payload)

        assert response.status_code == 201
        assert response.json()["ingested"] == 2
        assert response.json()["traces"] == 1

    def test_ingest_empty_batch(self, client):
        response = client.post("/api/v1/traces/spans/batch", json=[])

        assert response.status_code == 201
        assert response.json()["ingested"] == 0

    def test_ingest_cyclic_parent_references(self, client):
        now = datetime.now(timezone.utc).isoformat()
        payload = [
            {
                "span_id": "span-cycle-a",
                "trace_id": "trace-cycle-1",
                "parent_id": "span-cycle-b",
                "name": "first-cycle-step",
                "start_time": now,
            },
            {
                "span_id": "span-cycle-b",
                "trace_id": "trace-cycle-1",
                "parent_id": "span-cycle-a",
                "name": "second-cycle-step",
                "start_time": now,
            },
        ]
        response = client.post("/api/v1/traces/spans/batch", json=payload)

        assert response.status_code == 201
        assert response.json()["ingested"] == 2

    def test_ingest_with_attributes(self, client):
        payload = [
            {
                "span_id": "span-1",
                "trace_id": "trace-1",
                "name": "llm-call",
                "span_type": "llm",
                "start_time": datetime.now(timezone.utc).isoformat(),
                "attributes": {"model": "gpt-4", "temperature": 0.7},
                "tokens": 150,
                "cost": 0.003,
            }
        ]

        response = client.post("/api/v1/traces/spans/batch", json=payload)

        assert response.status_code == 201

    def test_trace_level_payload_preserves_metadata_and_name(self, client):
        now = datetime.now(timezone.utc).isoformat()
        payload = [
            {
                "span_id": "span-meta-1",
                "trace_id": "trace-meta-1",
                "name": "first-step",
                "start_time": now,
                "trace_name": "agent-workflow",
                "trace_status": "running",
                "trace_start_time": now,
                "trace_metadata": {"session_id": "s-123", "env": "test"},
            }
        ]
        response = client.post("/api/v1/traces/spans/batch", json=payload)
        assert response.status_code == 201

        detail = client.get("/api/v1/traces/trace-meta-1")
        assert detail.status_code == 200
        assert detail.json()["trace"]["name"] == "agent-workflow"
        assert detail.json()["trace"]["metadata"]["session_id"] == "s-123"

    def test_out_of_order_spans_use_explicit_trace_identity(self, client):
        now = datetime.now(timezone.utc).isoformat()
        payload = [
            {
                "span_id": "span-child-first",
                "trace_id": "trace-oop-1",
                "parent_id": "span-parent-late",
                "name": "child-step",
                "start_time": now,
                "trace_name": "ordered-trace-name",
                "trace_start_time": now,
                "trace_metadata": {"source": "explicit"},
            },
            {
                "span_id": "span-parent-late",
                "trace_id": "trace-oop-1",
                "name": "parent-step",
                "start_time": now,
                "trace_name": "ordered-trace-name",
                "trace_start_time": now,
                "trace_metadata": {"source": "explicit"},
            },
        ]
        response = client.post("/api/v1/traces/spans/batch", json=payload)
        assert response.status_code == 201

        detail = client.get("/api/v1/traces/trace-oop-1")
        assert detail.status_code == 200
        assert detail.json()["trace"]["name"] == "ordered-trace-name"
        assert detail.json()["trace"]["metadata"]["source"] == "explicit"

    def test_legacy_span_only_ingestion_still_works(self, client):
        payload = [
            {
                "span_id": "span-legacy-1",
                "trace_id": "trace-legacy-1",
                "name": "legacy-step",
                "start_time": datetime.now(timezone.utc).isoformat(),
            }
        ]
        response = client.post("/api/v1/traces/spans/batch", json=payload)

        assert response.status_code == 201
        assert response.json()["ingested"] == 1

    def test_ingestion_sets_regression_guardrail_metadata(self, client):
        now = datetime.now(timezone.utc).isoformat()

        baseline_response = client.post(
            "/api/v1/traces/spans/batch",
            json=[
                {
                    "span_id": "span-reg-baseline-1",
                    "trace_id": "trace-reg-baseline",
                    "name": "baseline-llm",
                    "span_type": "llm",
                    "status": "success",
                    "start_time": now,
                    "end_time": now,
                    "duration_ms": 300,
                    "tokens": 100,
                    "cost": 0.01,
                }
            ],
        )
        assert baseline_response.status_code == 201

        candidate_response = client.post(
            "/api/v1/traces/spans/batch",
            json=[
                {
                    "span_id": "span-reg-candidate-1",
                    "trace_id": "trace-reg-candidate",
                    "name": "candidate-llm",
                    "span_type": "llm",
                    "status": "error",
                    "start_time": now,
                    "end_time": now,
                    "duration_ms": 900,
                    "tokens": 260,
                    "cost": 0.05,
                    "error": "tool timeout",
                },
                {
                    "span_id": "span-reg-candidate-2",
                    "trace_id": "trace-reg-candidate",
                    "name": "candidate-tool",
                    "span_type": "tool",
                    "status": "success",
                    "start_time": now,
                    "end_time": now,
                    "duration_ms": 400,
                },
            ],
        )
        assert candidate_response.status_code == 201

        candidate_detail = client.get("/api/v1/traces/trace-reg-candidate")
        assert candidate_detail.status_code == 200
        metadata = candidate_detail.json()["trace"]["metadata"]
        assert "regression_guardrail" in metadata

        guardrail = metadata["regression_guardrail"]
        assert guardrail["status"] == "risk_detected"
        assert guardrail["baseline_trace_id"] == "trace-reg-baseline"
        assert guardrail["risk_score"] > 0
        assert guardrail["signal_count"] >= 1
        assert len(guardrail["top_actions"]) >= 1


class TestTraceBudgetGuard:
    """Tests for budget hard-stop behavior on ingestion."""

    def test_hard_stop_budget_blocks_over_limit_ingestion(self, client):
        """Ingestion should fail when hard-stop budget would be exceeded."""
        create_response = client.post("/api/v1/projects/", json={"name": "budget-hard-stop"})
        api_key = create_response.json()["api_key"]
        now = datetime.now(timezone.utc).isoformat()

        set_budget = client.put(
            "/api/v1/projects/me/budget",
            json={"monthly_token_limit": 100, "hard_stop_enabled": True},
            headers={"X-API-Key": api_key},
        )
        assert set_budget.status_code == 200

        first_ingest = client.post(
            "/api/v1/traces/spans/batch",
            json=[
                {
                    "span_id": "span-budget-allow-1",
                    "trace_id": "trace-budget-allow-1",
                    "name": "within-budget",
                    "tokens": 80,
                    "start_time": now,
                }
            ],
            headers={"X-API-Key": api_key},
        )
        assert first_ingest.status_code == 201

        blocked_ingest = client.post(
            "/api/v1/traces/spans/batch",
            json=[
                {
                    "span_id": "span-budget-block-1",
                    "trace_id": "trace-budget-block-1",
                    "name": "over-budget",
                    "tokens": 30,
                    "start_time": now,
                }
            ],
            headers={"X-API-Key": api_key},
        )
        assert blocked_ingest.status_code == 429
        detail = blocked_ingest.json()["detail"]
        assert detail["code"] == "budget_exceeded"
        assert detail["projected_tokens"] == 110

        traces_response = client.get(
            "/api/v1/traces/",
            headers={"X-API-Key": api_key},
        )
        assert traces_response.status_code == 200
        assert traces_response.json()["total"] == 1


class TestTraceRetrieval:
    def test_list_traces_empty(self, client):
        response = client.get("/api/v1/traces/")

        assert response.status_code == 200
        assert response.json()["traces"] == []
        assert response.json()["total"] == 0

    def test_list_traces_after_ingestion(self, client):
        payload = [
            {
                "span_id": "span-1",
                "trace_id": "trace-1",
                "name": "test-trace",
                "span_type": "agent",
                "start_time": datetime.now(timezone.utc).isoformat(),
            }
        ]
        client.post("/api/v1/traces/spans/batch", json=payload)

        response = client.get("/api/v1/traces/")

        assert response.status_code == 200
        assert response.json()["total"] == 1
        assert len(response.json()["traces"]) == 1
        assert "created_at" in response.json()["traces"][0]

    def test_list_traces_pagination(self, client):
        now = datetime.now(timezone.utc).isoformat()
        for i in range(5):
            payload = [
                {
                    "span_id": f"span-{i}",
                    "trace_id": f"trace-{i}",
                    "name": f"trace-{i}",
                    "start_time": now,
                }
            ]
            client.post("/api/v1/traces/spans/batch", json=payload)

        response = client.get("/api/v1/traces/?limit=2&offset=0")

        assert response.status_code == 200
        assert response.json()["total"] == 5
        assert len(response.json()["traces"]) == 2
        assert response.json()["limit"] == 2
        assert response.json()["offset"] == 0

    def test_get_trace_detail(self, client):
        payload = [
            {
                "span_id": "span-1",
                "trace_id": "trace-1",
                "name": "parent",
                "start_time": datetime.now(timezone.utc).isoformat(),
            },
            {
                "span_id": "span-2",
                "trace_id": "trace-1",
                "parent_id": "span-1",
                "name": "child",
                "start_time": datetime.now(timezone.utc).isoformat(),
            },
        ]
        client.post("/api/v1/traces/spans/batch", json=payload)

        response = client.get("/api/v1/traces/trace-1")

        assert response.status_code == 200
        assert response.json()["trace"]["name"] == "parent"
        assert len(response.json()["spans"]) == 2

    def test_get_trace_not_found(self, client):
        response = client.get("/api/v1/traces/nonexistent-id")

        assert response.status_code == 404

    def test_get_trace_spans(self, client):
        payload = [
            {
                "span_id": "span-1",
                "trace_id": "trace-1",
                "name": "span-1",
                "span_type": "llm",
                "start_time": datetime.now(timezone.utc).isoformat(),
                "events": [{"name": "token_usage", "value": 12}],
            },
        ]
        client.post("/api/v1/traces/spans/batch", json=payload)

        response = client.get("/api/v1/traces/trace-1/spans")

        assert response.status_code == 200
        assert len(response.json()) == 1
        assert response.json()[0]["name"] == "span-1"
        assert response.json()[0]["events"] == [{"name": "token_usage", "value": 12}]

    def test_error_count_uses_error_status_only(self, client):
        payload = [
            {
                "span_id": "span-1",
                "trace_id": "trace-error-count",
                "name": "span-with-error-text",
                "status": "success",
                "error": "transient warning",
                "start_time": datetime.now(timezone.utc).isoformat(),
            }
        ]
        client.post("/api/v1/traces/spans/batch", json=payload)

        response = client.get("/api/v1/traces/")

        assert response.status_code == 200
        assert response.json()["traces"][0]["error_count"] == 0

    def test_list_traces_supports_query_filters_and_sorting(self, client):
        now = datetime.now(timezone.utc).isoformat()

        client.post(
            "/api/v1/traces/spans/batch",
            json=[
                {
                    "span_id": "span-filter-1",
                    "trace_id": "trace-filter-1",
                    "name": "alpha-trace",
                    "status": "error",
                    "tokens": 10,
                    "cost": 0.01,
                    "start_time": now,
                }
            ],
        )
        client.post(
            "/api/v1/traces/spans/batch",
            json=[
                {
                    "span_id": "span-filter-2",
                    "trace_id": "trace-filter-2",
                    "name": "beta-trace",
                    "status": "success",
                    "tokens": 500,
                    "cost": 0.50,
                    "start_time": now,
                }
            ],
        )

        filtered = client.get("/api/v1/traces/?q=beta&min_tokens=100&has_errors=false")
        assert filtered.status_code == 200
        assert filtered.json()["total"] == 1
        assert filtered.json()["traces"][0]["id"] == "trace-filter-2"

        sorted_resp = client.get("/api/v1/traces/?sort_by=total_tokens&sort_order=desc")
        assert sorted_resp.status_code == 200
        traces = sorted_resp.json()["traces"]
        assert traces[0]["id"] == "trace-filter-2"

    def test_ingestion_updates_trace_aggregate_stats(self, client):
        now = datetime.now(timezone.utc).isoformat()
        payload = [
            {
                "span_id": "span-agg-1",
                "trace_id": "trace-agg-1",
                "name": "step-1",
                "status": "success",
                "tokens": 100,
                "cost": 0.1,
                "start_time": now,
            },
            {
                "span_id": "span-agg-2",
                "trace_id": "trace-agg-1",
                "name": "step-2",
                "status": "error",
                "tokens": 50,
                "cost": 0.05,
                "start_time": now,
            },
        ]
        ingest = client.post("/api/v1/traces/spans/batch", json=payload)
        assert ingest.status_code == 201

        traces = client.get("/api/v1/traces/")
        assert traces.status_code == 200
        trace = traces.json()["traces"][0]
        assert trace["id"] == "trace-agg-1"
        assert trace["span_count"] == 2
        assert trace["total_tokens"] == 150
        assert trace["error_count"] == 1
        assert trace["status"] == "error"

    def test_list_experiments_by_run_id(self, client):
        now = datetime.now(timezone.utc)
        payload = [
            {
                "span_id": "span-exp-1",
                "trace_id": "trace-exp-1",
                "name": "agent.plan",
                "start_time": now.isoformat(),
                "duration_ms": 400,
                "trace_metadata": {"run_id": "exp-alpha", "model": "nemo-a"},
            },
            {
                "span_id": "span-exp-2",
                "trace_id": "trace-exp-2",
                "name": "agent.plan",
                "start_time": (now + timedelta(seconds=1)).isoformat(),
                "duration_ms": 700,
                "status": "error",
                "trace_status": "error",
                "trace_metadata": {"run_id": "exp-alpha", "model": "nemo-a"},
            },
            {
                "span_id": "span-exp-3",
                "trace_id": "trace-exp-3",
                "name": "agent.plan",
                "start_time": (now + timedelta(seconds=2)).isoformat(),
                "duration_ms": 300,
                "trace_metadata": {"run_id": "exp-beta", "model": "nemo-b"},
            },
        ]
        ingest = client.post("/api/v1/traces/spans/batch", json=payload)
        assert ingest.status_code == 201

        response = client.get("/api/v1/traces/experiments?field=run_id")
        assert response.status_code == 200
        data = response.json()
        assert data["field"] == "run_id"
        assert data["total"] == 2

        exp_alpha = next(exp for exp in data["experiments"] if exp["experiment_id"] == "exp-alpha")
        assert exp_alpha["trace_count"] == 2
        assert exp_alpha["statuses"]["error"] == 1
        assert exp_alpha["sample_compare_pair"] is not None

    def test_list_experiments_can_include_ungrouped(self, client):
        payload = [
            {
                "span_id": "span-ungrouped-1",
                "trace_id": "trace-ungrouped-1",
                "name": "agent.plan",
                "start_time": datetime.now(timezone.utc).isoformat(),
            }
        ]
        ingest = client.post("/api/v1/traces/spans/batch", json=payload)
        assert ingest.status_code == 201

        response = client.get("/api/v1/traces/experiments?include_ungrouped=true")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["experiments"][0]["experiment_id"] == "ungrouped"

    def test_trace_summary_empty_window(self, client):
        response = client.get("/api/v1/traces/summary?window_days=7")
        assert response.status_code == 200
        data = response.json()
        assert data["trace_count"] == 0
        assert data["success_rate"] == 0
        assert data["p50_duration_ms"] is None

    def test_trace_summary_with_data(self, client):
        now = datetime.now(timezone.utc).isoformat()
        payload = [
            {
                "span_id": "span-summary-1",
                "trace_id": "trace-summary-1",
                "name": "agent.plan",
                "status": "success",
                "start_time": now,
                "duration_ms": 1000,
                "tokens": 100,
                "cost": 0.01,
            },
            {
                "span_id": "span-summary-2",
                "trace_id": "trace-summary-2",
                "name": "agent.plan",
                "status": "error",
                "trace_status": "error",
                "start_time": now,
                "duration_ms": 2000,
                "tokens": 300,
                "cost": 0.05,
            },
        ]
        ingest = client.post("/api/v1/traces/spans/batch", json=payload)
        assert ingest.status_code == 201

        response = client.get("/api/v1/traces/summary?window_days=7")
        assert response.status_code == 200
        data = response.json()
        assert data["trace_count"] == 2
        assert data["error_count"] == 1
        assert data["success_rate"] == 50.0
        assert data["p50_duration_ms"] is not None
        assert data["avg_tokens"] == 200.0
