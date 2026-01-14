"""Tests for trace ingestion and retrieval endpoints."""

from datetime import datetime, timezone


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
            },
        ]
        client.post("/api/v1/traces/spans/batch", json=payload)

        response = client.get("/api/v1/traces/trace-1/spans")

        assert response.status_code == 200
        assert len(response.json()) == 1
        assert response.json()[0]["name"] == "span-1"
