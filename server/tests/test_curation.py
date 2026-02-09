"""Tests for curation endpoints."""

from datetime import datetime, timezone

from app.models import Project, Trace


class TestCurationLabels:
    def _seed_trace(self, test_db):
        """Create a project and trace for label tests."""
        project = Project(name="default", api_key_hash="default")
        test_db.add(project)
        test_db.flush()

        trace = Trace(
            id="trace-curation-1",
            project_id=project.id,
            name="test-trace",
            status="success",
            start_time=datetime.now(timezone.utc),
        )
        test_db.add(trace)
        test_db.commit()
        return trace

    def test_get_label_not_found(self, client, test_db):
        """GET /labels/{trace_id} returns 404 when no label exists."""
        self._seed_trace(test_db)

        response = client.get("/api/v1/curation/labels/trace-curation-1")

        assert response.status_code == 404
        assert "Label not found" in response.json()["detail"]

    def test_get_label_nonexistent_trace(self, client, test_db):
        """GET /labels/{trace_id} returns 404 for a completely unknown trace."""
        response = client.get("/api/v1/curation/labels/nonexistent")

        assert response.status_code == 404

    def test_create_and_get_label(self, client, test_db):
        """Creating a label then fetching it returns the label."""
        self._seed_trace(test_db)

        create_response = client.post(
            "/api/v1/curation/labels",
            json={
                "trace_id": "trace-curation-1",
                "label": "good",
                "quality_score": 0.9,
            },
        )
        assert create_response.status_code == 200

        get_response = client.get("/api/v1/curation/labels/trace-curation-1")
        assert get_response.status_code == 200
        assert get_response.json()["label"] == "good"
        assert get_response.json()["quality_score"] == 0.9
