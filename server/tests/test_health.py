"""Tests for health check endpoints."""

from unittest.mock import patch


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
        with patch("app.main.redis.from_url") as mock_redis:
            mock_redis.return_value.ping.return_value = True
            response = client.get("/health/detailed")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ["healthy", "degraded"]
        assert "version" in data
        assert "checks" in data
        assert "database" in data["checks"]
        assert "redis" in data["checks"]
        assert "intelligence" in data["checks"]
