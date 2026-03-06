"""Tests for demo helper endpoints."""

from unittest.mock import patch

from app.models import Span, Trace


class TestStoryModeEndpoint:
    def test_story_mode_seeds_traces_and_returns_flow(self, client, test_db):
        response = client.post("/api/v1/demo/story-mode", json={"scenario": "agent_regression"})
        assert response.status_code == 200

        data = response.json()
        assert data["scenario"] == "agent_regression"
        assert data["seeded"] == 3
        assert len(data["trace_ids"]) == 3
        assert data["recommended_flow"]["compare"].startswith("/compare?traceA=")
        assert data["recommended_flow"]["curation"] == "/curation"

        traces = test_db.query(Trace).all()
        spans = test_db.query(Span).all()
        assert len(traces) == 3
        assert len(spans) > 0
        assert all((trace.trace_metadata or {}).get("story_mode") is True for trace in traces)

    def test_story_mode_rejects_unknown_scenario(self, client):
        response = client.post("/api/v1/demo/story-mode", json={"scenario": "anything_else"})
        assert response.status_code == 422


class TestDemoPreflight:
    def test_preflight_reports_required_checks(self, client):
        with (
            patch("app.routes.demo.check_db_connection", return_value=True),
            patch("app.routes.demo.redis.from_url") as mock_redis,
        ):
            mock_redis.return_value.ping.return_value = True

            response = client.get("/api/v1/demo/preflight")

        assert response.status_code == 200
        data = response.json()
        assert data["ready"] is True
        assert data["can_seed"] is True
        assert data["blockers"] == []
        check_map = {item["component"]: item for item in data["checks"]}
        assert check_map["database"]["status"] == "ok"
        assert check_map["database"]["required"] is True
        assert check_map["redis"]["required"] is False


class TestLatestStoryMode:
    def test_latest_story_mode_returns_last_run(self, client, test_db):
        seed_response = client.post(
            "/api/v1/demo/story-mode",
            json={"scenario": "agent_regression"},
        )
        assert seed_response.status_code == 200

        response = client.get("/api/v1/demo/story-mode/latest")
        assert response.status_code == 200

        data = response.json()
        assert data["found"] is True
        assert data["seeded"] == 3
        assert data["scenario"] == "agent_regression"
        assert data["trace_ids"] == seed_response.json()["trace_ids"]
        assert data["recommended_flow"]["compare"].startswith("/compare?traceA=")

    def test_latest_story_mode_returns_not_found_when_empty(self, client):
        response = client.get("/api/v1/demo/story-mode/latest")
        assert response.status_code == 200

        data = response.json()
        assert data["found"] is False
        assert data["seeded"] == 0
        assert data["trace_ids"] == []
