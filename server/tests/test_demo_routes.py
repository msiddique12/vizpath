"""Tests for demo helper endpoints."""

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
