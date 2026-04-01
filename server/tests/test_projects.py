"""Tests for project management endpoints."""

from datetime import datetime, timezone


class TestProjectCreate:
    """Tests for project creation endpoint."""

    def test_create_project(self, client, test_db):
        """POST /projects creates a new project with API key."""
        response = client.post(
            "/api/v1/projects/",
            json={"name": "test-project"},
        )

        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "test-project"
        assert "api_key" in data
        assert data["api_key"].startswith("vp_")
        assert "id" in data
        assert "created_at" in data

    def test_create_project_duplicate_name_allowed(self, client, test_db):
        """Projects with same name are allowed (different IDs)."""
        client.post("/api/v1/projects/", json={"name": "duplicate"})
        response = client.post("/api/v1/projects/", json={"name": "duplicate"})

        assert response.status_code == 201


class TestProjectList:
    """Tests for project listing endpoint."""

    def test_list_projects_empty(self, client, test_db):
        """GET /projects returns empty list when no projects exist."""
        response = client.get("/api/v1/projects/")

        assert response.status_code == 200
        assert response.json() == []

    def test_list_projects(self, client, test_db):
        """GET /projects returns all projects."""
        client.post("/api/v1/projects/", json={"name": "project-1"})
        client.post("/api/v1/projects/", json={"name": "project-2"})

        response = client.get("/api/v1/projects/")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        names = {p["name"] for p in data}
        assert names == {"project-1", "project-2"}

    def test_list_projects_does_not_include_api_key(self, client, test_db):
        """GET /projects should not include API keys."""
        client.post("/api/v1/projects/", json={"name": "secret-project"})

        response = client.get("/api/v1/projects/")

        data = response.json()
        assert "api_key" not in data[0]


class TestProjectGetMe:
    """Tests for /projects/me endpoint."""

    def test_get_current_project_with_api_key(self, client, test_db):
        """GET /projects/me returns current project based on API key."""
        # Create a project
        create_response = client.post(
            "/api/v1/projects/",
            json={"name": "my-project"},
        )
        api_key = create_response.json()["api_key"]

        # Get current project using the API key
        response = client.get(
            "/api/v1/projects/me",
            headers={"X-API-Key": api_key},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "my-project"

    def test_get_current_project_invalid_key(self, client, test_db):
        """GET /projects/me returns 401 for invalid API key."""
        response = client.get(
            "/api/v1/projects/me",
            headers={"X-API-Key": "invalid-key"},
        )

        assert response.status_code == 401


class TestProjectKeyRotation:
    """Tests for API key rotation endpoint."""

    def test_rotate_api_key(self, client, test_db):
        """POST /projects/me/api-key/rotate generates new key."""
        # Create project
        create_response = client.post(
            "/api/v1/projects/",
            json={"name": "rotation-test"},
        )
        old_key = create_response.json()["api_key"]

        # Rotate key
        rotate_response = client.post(
            "/api/v1/projects/me/api-key/rotate",
            json={"grace_period_minutes": 60},
            headers={"X-API-Key": old_key},
        )

        assert rotate_response.status_code == 200
        data = rotate_response.json()
        new_key = data["api_key"]

        assert new_key != old_key
        assert new_key.startswith("vp_")
        assert "grace_expires_at" in data

    def test_old_key_works_during_grace_period(self, client, test_db):
        """Old key should work during grace period."""
        # Create project
        create_response = client.post(
            "/api/v1/projects/",
            json={"name": "grace-test"},
        )
        old_key = create_response.json()["api_key"]

        # Rotate key
        client.post(
            "/api/v1/projects/me/api-key/rotate",
            json={"grace_period_minutes": 60},
            headers={"X-API-Key": old_key},
        )

        # Old key should still work
        response = client.get(
            "/api/v1/projects/me",
            headers={"X-API-Key": old_key},
        )

        assert response.status_code == 200


class TestProjectKeyRevocation:
    """Tests for API key revocation endpoint."""

    def test_revoke_previous_key(self, client, test_db):
        """POST /projects/me/api-key/revoke removes previous key."""
        # Create and rotate
        create_response = client.post(
            "/api/v1/projects/",
            json={"name": "revoke-test"},
        )
        old_key = create_response.json()["api_key"]

        rotate_response = client.post(
            "/api/v1/projects/me/api-key/rotate",
            json={"grace_period_minutes": 60},
            headers={"X-API-Key": old_key},
        )
        new_key = rotate_response.json()["api_key"]

        # Revoke previous key
        revoke_response = client.post(
            "/api/v1/projects/me/api-key/revoke",
            json={"key_type": "previous"},
            headers={"X-API-Key": new_key},
        )

        assert revoke_response.status_code == 200
        assert revoke_response.json()["status"] == "revoked"

        # Old key should no longer work
        check_response = client.get(
            "/api/v1/projects/me",
            headers={"X-API-Key": old_key},
        )
        assert check_response.status_code == 401

    def test_revoke_no_previous_key(self, client, test_db):
        """Revoking non-existent previous key returns 404."""
        create_response = client.post(
            "/api/v1/projects/",
            json={"name": "no-prev-test"},
        )
        api_key = create_response.json()["api_key"]

        response = client.post(
            "/api/v1/projects/me/api-key/revoke",
            json={"key_type": "previous"},
            headers={"X-API-Key": api_key},
        )

        assert response.status_code == 404


class TestProjectBudget:
    """Tests for project budget configuration and status endpoints."""

    def test_get_budget_defaults_when_unset(self, client, test_db):
        """GET /projects/me/budget returns defaults when no budget is configured."""
        create_response = client.post("/api/v1/projects/", json={"name": "budget-defaults"})
        api_key = create_response.json()["api_key"]

        response = client.get(
            "/api/v1/projects/me/budget",
            headers={"X-API-Key": api_key},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["monthly_token_limit"] is None
        assert data["monthly_cost_limit"] is None
        assert data["alert_threshold_percent"] == 80.0
        assert data["hard_stop_enabled"] is False

    def test_update_budget_and_read_back(self, client, test_db):
        """PUT /projects/me/budget upserts budget settings."""
        create_response = client.post("/api/v1/projects/", json={"name": "budget-update"})
        api_key = create_response.json()["api_key"]

        update_response = client.put(
            "/api/v1/projects/me/budget",
            json={
                "monthly_token_limit": 10000,
                "monthly_cost_limit": 25.0,
                "alert_threshold_percent": 75,
                "hard_stop_enabled": True,
            },
            headers={"X-API-Key": api_key},
        )
        assert update_response.status_code == 200

        get_response = client.get(
            "/api/v1/projects/me/budget",
            headers={"X-API-Key": api_key},
        )
        assert get_response.status_code == 200
        data = get_response.json()
        assert data["monthly_token_limit"] == 10000
        assert data["monthly_cost_limit"] == 25.0
        assert data["alert_threshold_percent"] == 75.0
        assert data["hard_stop_enabled"] is True

    def test_update_budget_allows_clearing_limits_and_resetting_defaults(self, client, test_db):
        """Explicit null values should clear limits and reset optional toggles."""
        create_response = client.post("/api/v1/projects/", json={"name": "budget-reset"})
        api_key = create_response.json()["api_key"]

        first_update = client.put(
            "/api/v1/projects/me/budget",
            json={
                "monthly_token_limit": 1000,
                "monthly_cost_limit": 9.5,
                "alert_threshold_percent": 70,
                "hard_stop_enabled": True,
            },
            headers={"X-API-Key": api_key},
        )
        assert first_update.status_code == 200

        reset_update = client.put(
            "/api/v1/projects/me/budget",
            json={
                "monthly_token_limit": None,
                "monthly_cost_limit": None,
                "alert_threshold_percent": None,
                "hard_stop_enabled": None,
            },
            headers={"X-API-Key": api_key},
        )
        assert reset_update.status_code == 200
        data = reset_update.json()
        assert data["monthly_token_limit"] is None
        assert data["monthly_cost_limit"] is None
        assert data["alert_threshold_percent"] == 80.0
        assert data["hard_stop_enabled"] is False

    def test_budget_status_reports_usage_and_alert(self, client, test_db):
        """Status endpoint reports usage percentages and threshold alerts."""
        create_response = client.post("/api/v1/projects/", json={"name": "budget-status"})
        api_key = create_response.json()["api_key"]
        now = datetime.now(timezone.utc).isoformat()

        budget_response = client.put(
            "/api/v1/projects/me/budget",
            json={
                "monthly_token_limit": 100,
                "monthly_cost_limit": 1.0,
                "alert_threshold_percent": 50,
                "hard_stop_enabled": False,
            },
            headers={"X-API-Key": api_key},
        )
        assert budget_response.status_code == 200

        ingest_response = client.post(
            "/api/v1/traces/spans/batch",
            json=[
                {
                    "span_id": "span-budget-status-1",
                    "trace_id": "trace-budget-status-1",
                    "name": "budget-status",
                    "tokens": 60,
                    "cost": 0.6,
                    "start_time": now,
                }
            ],
            headers={"X-API-Key": api_key},
        )
        assert ingest_response.status_code == 201

        status_response = client.get(
            "/api/v1/projects/me/budget/status",
            headers={"X-API-Key": api_key},
        )

        assert status_response.status_code == 200
        data = status_response.json()
        assert data["tokens_used"] == 60
        assert data["cost_used"] == 0.6
        assert data["token_usage_percent"] == 60.0
        assert data["cost_usage_percent"] == 60.0
        assert data["token_alert_triggered"] is True
        assert data["cost_alert_triggered"] is True
        assert data["alert_triggered"] is True
