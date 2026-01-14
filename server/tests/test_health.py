"""Tests for health check endpoints."""


class TestHealthEndpoints:
    def test_root_endpoint(self, client):
        response = client.get("/")

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "vizpath"
        assert data["status"] == "ok"
        assert "version" in data

    def test_health_endpoint(self, client):
        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "timestamp" in data

    def test_health_detailed_endpoint(self, client):
        response = client.get("/health/detailed")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ["healthy", "degraded"]
        assert "version" in data
        assert "checks" in data
        assert "database" in data["checks"]
