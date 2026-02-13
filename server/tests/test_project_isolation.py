"""Cross-project isolation tests for trace, curation, and intelligence endpoints."""

from datetime import datetime, timezone

import numpy as np

from app.intelligence import clustering as clustering_module
from app.intelligence import embeddings as embeddings_module
from app.routes import intelligence as intelligence_route


def _create_project(client, name: str) -> tuple[str, str]:
    response = client.post("/api/v1/projects/", json={"name": name})
    assert response.status_code == 201
    body = response.json()
    return body["id"], body["api_key"]


def _ingest_trace(client, api_key: str, trace_id: str) -> None:
    payload = [
        {
            "span_id": f"span-{trace_id}",
            "trace_id": trace_id,
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


def test_cannot_read_other_project_traces(client):
    _, key_a = _create_project(client, "project-a")
    _, key_b = _create_project(client, "project-b")

    _ingest_trace(client, key_a, "trace-a-only")

    foreign_detail = client.get(
        "/api/v1/traces/trace-a-only",
        headers={"X-API-Key": key_b},
    )
    list_for_b = client.get("/api/v1/traces/", headers={"X-API-Key": key_b})

    assert foreign_detail.status_code == 404
    assert list_for_b.status_code == 200
    assert list_for_b.json()["total"] == 0


def test_cannot_curate_other_project_trace(client):
    _, key_a = _create_project(client, "project-curation-a")
    _, key_b = _create_project(client, "project-curation-b")

    _ingest_trace(client, key_a, "trace-curation-a")

    response = client.post(
        "/api/v1/curation/labels",
        json={"trace_id": "trace-curation-a", "label": "good", "quality_score": 80},
        headers={"X-API-Key": key_b},
    )

    assert response.status_code == 404


def test_intelligence_rejects_foreign_trace_access(client, monkeypatch):
    monkeypatch.setattr(intelligence_route.settings, "nvidia_api_key", "test-key")

    _, key_a = _create_project(client, "project-intel-a")
    _, key_b = _create_project(client, "project-intel-b")

    _ingest_trace(client, key_a, "trace-intel-a")

    response = client.post(
        "/api/v1/intelligence/analyze",
        json={"trace_id": "trace-intel-a"},
        headers={"X-API-Key": key_b},
    )

    assert response.status_code == 404


def test_clustering_contains_only_project_traces(client, monkeypatch):
    monkeypatch.setattr(intelligence_route.settings, "nvidia_api_key", "test-key")

    _, key_a = _create_project(client, "project-cluster-a")
    _, key_b = _create_project(client, "project-cluster-b")

    _ingest_trace(client, key_a, "trace-a-1")
    _ingest_trace(client, key_a, "trace-a-2")
    _ingest_trace(client, key_b, "trace-b-1")
    _ingest_trace(client, key_b, "trace-b-2")

    async def fake_get_trace_embeddings(trace_texts):
        return {
            trace_id: np.array([idx + 0.1, idx + 0.2])
            for idx, trace_id in enumerate(trace_texts.keys())
        }

    def fake_cluster_traces(embeddings, project_id):
        return {
            "clusters": {trace_id: 0 for trace_id in embeddings.keys()},
            "centroids": np.array([[0.1, 0.2]]),
        }

    def fake_get_cluster_summary(trace_ids_per_cluster, embeddings, centroids, db):
        return {
            cid: {
                "cluster_id": cid,
                "size": len(trace_ids),
                "success_rate": 1.0,
                "most_common_error": None,
                "top_actions": [],
                "representative_trace_id": trace_ids[0],
                "trace_ids": trace_ids,
            }
            for cid, trace_ids in trace_ids_per_cluster.items()
        }

    monkeypatch.setattr(embeddings_module, "get_trace_embeddings", fake_get_trace_embeddings)
    monkeypatch.setattr(clustering_module, "cluster_traces", fake_cluster_traces)
    monkeypatch.setattr(clustering_module, "get_cluster_summary", fake_get_cluster_summary)

    response = client.get("/api/v1/intelligence/clusters", headers={"X-API-Key": key_a})

    assert response.status_code == 200
    for cluster in response.json()["clusters"]:
        for trace_id in cluster["trace_ids"]:
            assert trace_id.startswith("trace-a-")
