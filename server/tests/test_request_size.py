"""Request size limit middleware coverage."""

from datetime import datetime, timezone

from app.config import settings


def _create_project_api_key(client):
    response = client.post("/api/v1/projects/", json={"name": "request-size-project"})
    assert response.status_code == 201
    return response.json()["api_key"]


def _build_span_payload(name_suffix: str, attribute_payload: str = "ok") -> list[dict]:
    return [
        {
            "span_id": f"span-{name_suffix}",
            "trace_id": f"trace-{name_suffix}",
            "name": f"node-{name_suffix}",
            "attributes": {
                "large": attribute_payload,
            },
            "start_time": datetime.now(timezone.utc).isoformat(),
        }
    ]


def test_request_size_limit_blocks_oversized_payload(client, monkeypatch):
    api_key = _create_project_api_key(client)
    monkeypatch.setattr(settings, "max_request_body_bytes", 200)

    oversized = _build_span_payload("oversized", attribute_payload="x" * 180)
    response = client.post(
        "/api/v1/traces/spans/batch",
        json=oversized,
        headers={"X-API-Key": api_key},
    )

    assert response.status_code == 413
    body = response.json()
    assert body["error"]["code"] == "payload_too_large"
    assert "exceeds configured limit" in body["detail"]


def test_request_size_limit_allows_payload_within_limit(client, monkeypatch):
    api_key = _create_project_api_key(client)
    monkeypatch.setattr(settings, "max_request_body_bytes", 4096)

    payload = _build_span_payload("allowed", attribute_payload="x" * 20)
    response = client.post(
        "/api/v1/traces/spans/batch",
        json=payload,
        headers={"X-API-Key": api_key},
    )

    assert response.status_code == 201
    assert response.json()["ingested"] == 1
