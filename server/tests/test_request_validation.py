"""Regression tests for request validation and sanitization."""

from datetime import datetime, timezone


def test_traces_reject_unknown_field(client):
    payload = [
        {
            "span_id": "span-v-1",
            "trace_id": "trace-v-1",
            "name": "valid",
            "start_time": datetime.now(timezone.utc).isoformat(),
            "unexpected": "boom",
        }
    ]

    response = client.post("/api/v1/traces/spans/batch", json=payload)

    assert response.status_code == 422


def test_traces_reject_invalid_bounds(client):
    payload = [
        {
            "span_id": "span-v-2",
            "trace_id": "trace-v-2",
            "name": "valid",
            "start_time": datetime.now(timezone.utc).isoformat(),
            "tokens": -1,
        }
    ]

    response = client.post("/api/v1/traces/spans/batch", json=payload)

    assert response.status_code == 422


def test_traces_reject_invalid_enum_and_pattern(client):
    payload = [
        {
            "span_id": "span@bad",
            "trace_id": "trace-v-3",
            "name": "valid",
            "start_time": datetime.now(timezone.utc).isoformat(),
            "status": "done",
        }
    ]

    response = client.post("/api/v1/traces/spans/batch", json=payload)

    assert response.status_code == 422


def test_curation_rejects_invalid_quality_score(client):
    payload = {
        "trace_id": "trace-score-1",
        "label": "good",
        "quality_score": 101,
    }

    response = client.post("/api/v1/curation/labels", json=payload)

    assert response.status_code == 422


def test_intelligence_rejects_invalid_mode(client):
    payload = {
        "trace_id": "trace-1",
        "mode": "bad-mode",
        "n": 5,
    }

    response = client.post("/api/v1/intelligence/generate-synthetic", json=payload)

    assert response.status_code == 422


def test_intelligence_rejects_control_chars(client):
    payload = {
        "trace_id": "trace-\u0007bad",
    }

    response = client.post("/api/v1/intelligence/analyze", json=payload)

    assert response.status_code == 422


def test_valid_payload_behavior_unchanged(client):
    payload = [
        {
            "span_id": "span-valid-1",
            "trace_id": "trace-valid-1",
            "name": "test-span",
            "span_type": "llm",
            "status": "success",
            "start_time": datetime.now(timezone.utc).isoformat(),
        }
    ]

    response = client.post("/api/v1/traces/spans/batch", json=payload)

    assert response.status_code == 201
    assert response.json()["ingested"] == 1
