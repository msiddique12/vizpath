"""Tests for curation endpoints."""

from datetime import datetime, timezone

from app.models import CuratedLabel, Project, Trace


class TestCurationLabels:
    def _seed_trace(self, test_db, trace_id="trace-curation-1", name="test-trace"):
        """Create a project and trace for label tests."""
        project = test_db.query(Project).filter(Project.api_key_hash == "default").first()
        if not project:
            project = Project(name="default", api_key_hash="default")
            test_db.add(project)
            test_db.flush()

        trace = Trace(
            id=trace_id,
            project_id=project.id,
            name=name,
            status="success",
            start_time=datetime.now(timezone.utc),
        )
        test_db.add(trace)
        test_db.commit()
        return trace, project

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

    def test_delete_label(self, client, test_db):
        """DELETE /labels/{trace_id} removes the label."""
        self._seed_trace(test_db)

        # Create label first
        client.post(
            "/api/v1/curation/labels",
            json={"trace_id": "trace-curation-1", "label": "good"},
        )

        # Delete it
        delete_response = client.delete("/api/v1/curation/labels/trace-curation-1")
        assert delete_response.status_code == 204

        # Should be gone now
        get_response = client.get("/api/v1/curation/labels/trace-curation-1")
        assert get_response.status_code == 404

    def test_delete_nonexistent_label(self, client, test_db):
        """DELETE /labels/{trace_id} returns 404 for non-existent label."""
        response = client.delete("/api/v1/curation/labels/nonexistent")
        assert response.status_code == 404


class TestCurationTraces:
    def _seed_curated_traces(self, test_db):
        """Create project with multiple curated traces."""
        project = Project(name="default", api_key_hash="default")
        test_db.add(project)
        test_db.flush()

        for i in range(3):
            trace = Trace(
                id=f"trace-list-{i}",
                project_id=project.id,
                name=f"trace-{i}",
                status="success",
                start_time=datetime.now(timezone.utc),
            )
            test_db.add(trace)

            label = CuratedLabel(
                trace_id=f"trace-list-{i}",
                label="good" if i % 2 == 0 else "excellent",
                quality_score=0.8 + (i * 0.05),
                exported=(i == 2),
            )
            test_db.add(label)

        test_db.commit()
        return project

    def test_list_curated_traces(self, client, test_db):
        """GET /traces returns list of curated traces."""
        self._seed_curated_traces(test_db)

        response = client.get("/api/v1/curation/traces")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 3

    def test_list_curated_traces_filter_by_label(self, client, test_db):
        """GET /traces?label=good filters by label."""
        self._seed_curated_traces(test_db)

        response = client.get("/api/v1/curation/traces?label=good")
        assert response.status_code == 200
        data = response.json()
        assert all(t["label"] == "good" for t in data)

    def test_list_curated_traces_filter_by_exported(self, client, test_db):
        """GET /traces?exported=true filters by export status."""
        self._seed_curated_traces(test_db)

        response = client.get("/api/v1/curation/traces?exported=true")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["exported"] is True


class TestCurationStats:
    def _seed_for_stats(self, test_db):
        """Create data for stats tests."""
        project = Project(name="default", api_key_hash="default")
        test_db.add(project)
        test_db.flush()

        for i in range(5):
            trace = Trace(
                id=f"trace-stats-{i}",
                project_id=project.id,
                name=f"trace-{i}",
                status="success",
                start_time=datetime.now(timezone.utc),
            )
            test_db.add(trace)

            label = CuratedLabel(
                trace_id=f"trace-stats-{i}",
                label="good" if i < 3 else "excellent",
                quality_score=0.7 + (i * 0.05),
                exported=(i >= 3),
            )
            test_db.add(label)

        test_db.commit()

    def test_get_stats(self, client, test_db):
        """GET /stats returns curation statistics."""
        self._seed_for_stats(test_db)

        response = client.get("/api/v1/curation/stats")
        assert response.status_code == 200
        data = response.json()

        assert data["total_labeled"] == 5
        assert data["exported_count"] == 2
        assert "labels" in data
        assert data["labels"]["good"] == 3
        assert data["labels"]["excellent"] == 2


class TestCurationExport:
    def _seed_for_export(self, test_db):
        """Create data for export tests."""
        project = Project(name="default", api_key_hash="default")
        test_db.add(project)
        test_db.flush()

        for i in range(2):
            trace = Trace(
                id=f"trace-export-{i}",
                project_id=project.id,
                name=f"export-trace-{i}",
                status="success",
                start_time=datetime.now(timezone.utc),
            )
            test_db.add(trace)

            label = CuratedLabel(
                trace_id=f"trace-export-{i}",
                label="good",
                quality_score=0.9,
            )
            test_db.add(label)

        test_db.commit()

    def test_export_traces(self, client, test_db):
        """POST /export exports selected traces."""
        self._seed_for_export(test_db)

        response = client.post(
            "/api/v1/curation/export",
            json={
                "trace_ids": ["trace-export-0", "trace-export-1"],
                "format": "jsonl",
            },
        )
        assert response.status_code == 200
        data = response.json()

        assert data["format"] == "jsonl"
        assert data["count"] == 2
        assert "traces" in data

    def test_export_marks_as_exported(self, client, test_db):
        """Export should mark traces as exported."""
        self._seed_for_export(test_db)

        client.post(
            "/api/v1/curation/export",
            json={"trace_ids": ["trace-export-0"]},
        )

        # Check that trace is now marked as exported
        response = client.get("/api/v1/curation/traces?exported=true")
        data = response.json()
        assert any(t["trace_id"] == "trace-export-0" for t in data)
