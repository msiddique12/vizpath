"""Tests for project management endpoints."""



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
