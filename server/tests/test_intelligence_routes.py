"""Tests for intelligence API endpoints."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture
def trace_with_spans(client, test_db):
    """Create a trace with spans via the ingestion endpoint."""
    now = datetime.now(timezone.utc).isoformat()
    payload = [
        {
            "span_id": "span-001",
            "trace_id": "test-trace-001",
            "name": "llm_call",
            "span_type": "llm",
            "status": "success",
            "start_time": now,
            "end_time": now,
            "duration_ms": 2000.0,
            "tokens": 500,
            "cost": 0.01,
        },
        {
            "span_id": "span-002",
            "trace_id": "test-trace-001",
            "name": "web_search",
            "span_type": "tool",
            "status": "success",
            "start_time": now,
            "end_time": now,
            "duration_ms": 1000.0,
        },
    ]
    resp = client.post("/api/v1/traces/spans/batch", json=payload)
    assert resp.status_code == 201
    return "test-trace-001"


class TestAnalyzeEndpoint:
    def test_analyze_no_nvidia_key(self, client, test_db):
        """Should return 503 when NVIDIA key is not configured."""
        with patch("app.routes.intelligence.settings") as mock_settings:
            mock_settings.nvidia_api_key = None
            resp = client.post(
                "/api/v1/intelligence/analyze",
                json={"trace_id": "test-trace-001"},
            )
            assert resp.status_code == 503

    def test_analyze_trace_not_found(self, client, test_db):
        """Should return 404 for missing trace."""
        with patch("app.routes.intelligence.settings") as mock_settings:
            mock_settings.nvidia_api_key = "nvapi-test"
            resp = client.post(
                "/api/v1/intelligence/analyze",
                json={"trace_id": "nonexistent"},
            )
            assert resp.status_code == 404

    def test_analyze_success(self, client, trace_with_spans):
        """Should return analysis results for valid trace."""
        mock_result = {
            "quality_score": 85,
            "efficiency_score": 70,
            "error_analysis": "No errors found.",
            "suggestions": ["Cache queries"],
        }

        with (
            patch("app.routes.intelligence.settings") as mock_settings,
            patch("app.intelligence.llm.LLMLabeler") as MockLabeler,
        ):
            mock_settings.nvidia_api_key = "nvapi-test"
            mock_instance = MockLabeler.return_value
            mock_instance.analyze_trace = AsyncMock(return_value=mock_result)

            resp = client.post(
                "/api/v1/intelligence/analyze",
                json={"trace_id": "test-trace-001"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["quality_score"] == 85


class TestSelfAnalyzeEndpoint:
    def test_self_analyze_no_key(self, client, test_db):
        with patch("app.routes.intelligence.settings") as mock_settings:
            mock_settings.nvidia_api_key = None
            resp = client.post(
                "/api/v1/intelligence/self-analyze",
                json={"trace_id": "test-trace-001"},
            )
            assert resp.status_code == 503

    def test_self_analyze_not_found(self, client, test_db):
        with patch("app.routes.intelligence.settings") as mock_settings:
            mock_settings.nvidia_api_key = "nvapi-test"
            resp = client.post(
                "/api/v1/intelligence/self-analyze",
                json={"trace_id": "nonexistent"},
            )
            assert resp.status_code == 404

    def test_self_analyze_success(self, client, trace_with_spans):
        mock_result = {
            "quality": 90,
            "efficiency": 80,
            "completeness": 95,
            "overall_score": 88,
            "redundant_steps": [],
            "suggestions": ["Use parallel calls"],
            "summary": "Good execution.",
        }

        with (
            patch("app.routes.intelligence.settings") as mock_settings,
            patch("app.intelligence.llm.LLMLabeler") as MockLabeler,
        ):
            mock_settings.nvidia_api_key = "nvapi-test"
            mock_instance = MockLabeler.return_value
            mock_instance.self_analyze = AsyncMock(return_value=mock_result)

            resp = client.post(
                "/api/v1/intelligence/self-analyze",
                json={"trace_id": "test-trace-001"},
            )
            assert resp.status_code == 200
            assert resp.json()["overall_score"] == 88


class TestGenerateSyntheticEndpoint:
    def test_synthetic_no_key(self, client, test_db):
        with patch("app.routes.intelligence.settings") as mock_settings:
            mock_settings.nvidia_api_key = None
            resp = client.post(
                "/api/v1/intelligence/generate-synthetic",
                json={"trace_id": "test-trace-001"},
            )
            assert resp.status_code == 503

    def test_synthetic_not_found(self, client, test_db):
        with patch("app.routes.intelligence.settings") as mock_settings:
            mock_settings.nvidia_api_key = "nvapi-test"
            resp = client.post(
                "/api/v1/intelligence/generate-synthetic",
                json={"trace_id": "nonexistent"},
            )
            assert resp.status_code == 404

    def test_synthetic_variations_success(self, client, trace_with_spans):
        mock_variations = [
            {"name": "v1", "steps": [], "approach": "different approach"},
        ]

        with (
            patch("app.routes.intelligence.settings") as mock_settings,
            patch("app.intelligence.synthetic.SyntheticDataGenerator") as MockGen,
        ):
            mock_settings.nvidia_api_key = "nvapi-test"
            mock_instance = MockGen.return_value
            mock_instance.generate_variations = AsyncMock(return_value=mock_variations)

            resp = client.post(
                "/api/v1/intelligence/generate-synthetic",
                json={"trace_id": "test-trace-001", "mode": "variations", "n": 1},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["mode"] == "variations"
            assert data["count"] == 1
            assert data["results"] == mock_variations
            assert data["type"] == "variations"
            assert data["variations"] == mock_variations

    def test_synthetic_legacy_request_fields_still_supported(self, client, trace_with_spans):
        mock_variations = [
            {"name": "v1", "steps": [], "approach": "legacy payload compatibility"},
        ]

        with (
            patch("app.routes.intelligence.settings") as mock_settings,
            patch("app.intelligence.synthetic.SyntheticDataGenerator") as MockGen,
        ):
            mock_settings.nvidia_api_key = "nvapi-test"
            mock_instance = MockGen.return_value
            mock_instance.generate_variations = AsyncMock(return_value=mock_variations)

            resp = client.post(
                "/api/v1/intelligence/generate-synthetic",
                json={"trace_id": "test-trace-001", "type": "variations", "count": 1},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["mode"] == "variations"
            assert data["results"] == mock_variations
