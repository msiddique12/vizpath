"""Tests for scoped API key creation and enforcement."""

from datetime import datetime, timezone


def _create_project(client, name: str) -> str:
    response = client.post("/api/v1/projects/", json={"name": name})
    assert response.status_code == 201
    return response.json()["api_key"]


def _create_scoped_key(client, admin_api_key: str, name: str, scopes: list[str]) -> str:
    response = client.post(
        "/api/v1/projects/me/keys",
        json={"name": name, "scopes": scopes},
        headers={"X-API-Key": admin_api_key},
    )
    assert response.status_code == 201
    return response.json()["api_key"]


def _ingest_single_span(client, api_key: str, suffix: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    response = client.post(
        "/api/v1/traces/spans/batch",
        headers={"X-API-Key": api_key},
        json=[
            {
                "span_id": f"span-scope-{suffix}",
                "trace_id": f"trace-scope-{suffix}",
                "name": "scope-test",
                "start_time": now,
            }
        ],
    )
    assert response.status_code == 201


def test_read_scope_can_read_but_cannot_ingest(client):
    """A read-scoped key can query traces but cannot ingest new spans."""
    legacy_key = _create_project(client, "scope-read-project")
    _ingest_single_span(client, legacy_key, "legacy-seed")

    read_key = _create_scoped_key(client, legacy_key, "reader", ["read"])

    list_response = client.get("/api/v1/traces/", headers={"X-API-Key": read_key})
    assert list_response.status_code == 200

    now = datetime.now(timezone.utc).isoformat()
    ingest_response = client.post(
        "/api/v1/traces/spans/batch",
        headers={"X-API-Key": read_key},
        json=[
            {
                "span_id": "span-scope-read-denied",
                "trace_id": "trace-scope-read-denied",
                "name": "denied",
                "start_time": now,
            }
        ],
    )
    assert ingest_response.status_code == 403
    assert "required scope: ingest" in ingest_response.json()["detail"]


def test_ingest_scope_cannot_access_curation(client):
    """Ingest-scoped keys should be blocked from curation endpoints."""
    legacy_key = _create_project(client, "scope-ingest-project")
    ingest_key = _create_scoped_key(client, legacy_key, "ingester", ["ingest"])

    _ingest_single_span(client, ingest_key, "ingester-run")

    curation_response = client.get(
        "/api/v1/curation/stats",
        headers={"X-API-Key": ingest_key},
    )
    assert curation_response.status_code == 403
    assert "required scope: curate" in curation_response.json()["detail"]


def test_admin_scope_required_for_key_management(client):
    """Only admin-scoped keys should be able to manage project keys."""
    legacy_key = _create_project(client, "scope-admin-project")
    read_key = _create_scoped_key(client, legacy_key, "readonly", ["read"])

    denied_create = client.post(
        "/api/v1/projects/me/keys",
        json={"name": "attempt", "scopes": ["read"]},
        headers={"X-API-Key": read_key},
    )
    assert denied_create.status_code == 403
    assert "required scope: admin" in denied_create.json()["detail"]

    admin_key = _create_scoped_key(client, legacy_key, "admin", ["admin"])

    list_response = client.get("/api/v1/projects/me/keys", headers={"X-API-Key": admin_key})
    assert list_response.status_code == 200
    key_ids = {row["id"] for row in list_response.json()}
    assert key_ids

    read_key_metadata = next(row for row in list_response.json() if row["name"] == "readonly")
    revoke_response = client.post(
        f"/api/v1/projects/me/keys/{read_key_metadata['id']}/revoke",
        headers={"X-API-Key": admin_key},
    )
    assert revoke_response.status_code == 200
    assert revoke_response.json()["is_active"] is False

    revoked_key_use = client.get("/api/v1/projects/me", headers={"X-API-Key": read_key})
    assert revoked_key_use.status_code == 401


def test_persistent_workflows_require_curate_for_writes_and_read_for_reads(client):
    legacy_key = _create_project(client, "scope-workflow-project")
    _ingest_single_span(client, legacy_key, "workflow")

    read_key = _create_scoped_key(client, legacy_key, "workflow-reader", ["read"])
    curate_key = _create_scoped_key(client, legacy_key, "workflow-curator", ["curate"])

    read_triage = client.get("/api/v1/triage/items", headers={"X-API-Key": read_key})
    assert read_triage.status_code == 200

    denied_triage_write = client.post(
        "/api/v1/triage/items",
        headers={"X-API-Key": read_key},
        json={"trace_id": "trace-scope-workflow", "title": "Needs review"},
    )
    assert denied_triage_write.status_code == 403
    assert "required scope: curate" in denied_triage_write.json()["detail"]

    triage_write = client.post(
        "/api/v1/triage/items",
        headers={"X-API-Key": curate_key},
        json={"trace_id": "trace-scope-workflow", "title": "Needs review"},
    )
    assert triage_write.status_code == 201

    dataset_write = client.post(
        "/api/v1/datasets/builds",
        headers={"X-API-Key": curate_key},
        json={"trace_ids": ["trace-scope-workflow"], "name": "Scoped build"},
    )
    assert dataset_write.status_code == 201
    dataset_id = dataset_write.json()["id"]

    dataset_read = client.get(
        f"/api/v1/datasets/builds/{dataset_id}",
        headers={"X-API-Key": read_key},
    )
    assert dataset_read.status_code == 200

    denied_dataset_write = client.post(
        "/api/v1/datasets/builds",
        headers={"X-API-Key": read_key},
        json={"trace_ids": ["trace-scope-workflow"], "name": "Denied build"},
    )
    assert denied_dataset_write.status_code == 403

    suite_write = client.post(
        "/api/v1/evals/suites",
        headers={"X-API-Key": curate_key},
        json={"trace_ids": ["trace-scope-workflow"], "name": "Scoped suite"},
    )
    assert suite_write.status_code == 201
    suite_id = suite_write.json()["id"]

    suite_read = client.get(f"/api/v1/evals/suites/{suite_id}", headers={"X-API-Key": read_key})
    assert suite_read.status_code == 200

    denied_run_write = client.post(
        f"/api/v1/evals/suites/{suite_id}/runs",
        headers={"X-API-Key": read_key},
        json={"candidate_trace_ids": ["trace-scope-workflow"]},
    )
    assert denied_run_write.status_code == 403
