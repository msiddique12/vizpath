"""Tests for trace ingestion and retrieval endpoints."""

from datetime import datetime, timezone

from app.auth import hash_api_key
from app.models import Project


class TestTraceIngestionAuth:
    """Tests for auth behavior on the ingestion endpoint."""

    def test_ingest_no_key_creates_default_project(self, client, test_db):
        """Without API key in dev mode, a default project is created."""
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
