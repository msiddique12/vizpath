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


class TestCompareEndpoint:
    def test_compare_success_with_regression_signals(self, client, test_db):
        now = datetime.now(timezone.utc).isoformat()
        payload = [
            {
                "span_id": "span-compare-a-1",
                "trace_id": "trace-compare-a",
                "name": "baseline_agent",
                "span_type": "agent",
                "status": "success",
                "start_time": now,
                "end_time": now,
                "duration_ms": 1000,
            },
            {
                "span_id": "span-compare-a-2",
                "trace_id": "trace-compare-a",
                "name": "baseline_llm",
                "span_type": "llm",
                "status": "success",
                "start_time": now,
                "end_time": now,
                "duration_ms": 300,
                "tokens": 100,
                "cost": 0.01,
            },
            {
                "span_id": "span-compare-b-1",
                "trace_id": "trace-compare-b",
                "name": "candidate_agent",
                "span_type": "agent",
                "status": "error",
                "start_time": now,
                "end_time": now,
                "duration_ms": 1600,
            },
            {
                "span_id": "span-compare-b-2",
                "trace_id": "trace-compare-b",
                "name": "candidate_llm",
                "span_type": "llm",
                "status": "success",
                "start_time": now,
                "end_time": now,
                "duration_ms": 600,
                "tokens": 220,
                "cost": 0.03,
            },
            {
                "span_id": "span-compare-b-3",
                "trace_id": "trace-compare-b",
                "name": "candidate_tool",
                "span_type": "tool",
                "status": "success",
                "start_time": now,
                "end_time": now,
                "duration_ms": 200,
            },
        ]
        ingest = client.post("/api/v1/traces/spans/batch", json=payload)
        assert ingest.status_code == 201

        resp = client.post(
            "/api/v1/intelligence/compare",
            json={"trace_a_id": "trace-compare-a", "trace_b_id": "trace-compare-b"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["summary"]["status"] in {"mixed", "regressed"}
        assert data["summary"]["regression_score"] > 0
        assert any(signal["id"] == "error-regression" for signal in data["signals"])
        assert any(metric["name"] == "duration_ms" for metric in data["metrics"])

    def test_compare_missing_trace_returns_404(self, client, trace_with_spans):
        resp = client.post(
            "/api/v1/intelligence/compare",
            json={"trace_a_id": "test-trace-001", "trace_b_id": "does-not-exist"},
        )
        assert resp.status_code == 404

    def test_compare_rejects_invalid_payload(self, client, test_db):
        resp = client.post(
            "/api/v1/intelligence/compare",
            json={"trace_a_id": "ok-id", "trace_b_id": "bad id with spaces"},
        )
        assert resp.status_code == 422


class TestIntelligenceStatusEndpoint:
    def test_status_reports_missing_key(self, client, test_db):
        with patch("app.routes.intelligence.settings") as mock_settings:
            mock_settings.nvidia_api_key = None
            mock_settings.nvidia_llm_model = "nvidia/model"
            mock_settings.nvidia_base_url = "https://integrate.api.nvidia.com/v1"
            resp = client.get("/api/v1/intelligence/status")
            assert resp.status_code == 200
            data = resp.json()
            assert data["nvidia_api_key_configured"] is False

    def test_status_reports_configured_key(self, client, test_db):
        with patch("app.routes.intelligence.settings") as mock_settings:
            mock_settings.nvidia_api_key = "nvapi-test"
            mock_settings.nvidia_llm_model = "nvidia/model"
            mock_settings.nvidia_base_url = "https://integrate.api.nvidia.com/v1"
            resp = client.get("/api/v1/intelligence/status")
            assert resp.status_code == 200
            data = resp.json()
            assert data["nvidia_api_key_configured"] is True


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


class TestSuggestCurationEndpoint:
    def test_suggest_curation_no_nvidia_key(self, client, test_db):
        with patch("app.routes.intelligence.settings") as mock_settings:
            mock_settings.nvidia_api_key = None
            resp = client.post(
                "/api/v1/intelligence/suggest-curation",
                json={"trace_id": "test-trace-001"},
            )
            assert resp.status_code == 503

    def test_suggest_curation_not_found(self, client, test_db):
        with patch("app.routes.intelligence.settings") as mock_settings:
            mock_settings.nvidia_api_key = "nvapi-test"
            resp = client.post(
                "/api/v1/intelligence/suggest-curation",
                json={"trace_id": "missing-trace"},
            )
            assert resp.status_code == 404

    def test_suggest_curation_success(self, client, trace_with_spans):
        mock_analyze = {
            "quality_score": 92,
            "analysis": {
                "quality_score": 92,
                "labels": ["well_structured"],
                "suggestions": ["Keep caching enabled", "Reduce redundant tool calls"],
                "summary": "Strong execution with efficient tool usage.",
            },
            "suggestions": ["Keep caching enabled", "Reduce redundant tool calls"],
        }

        with (
            patch("app.routes.intelligence.settings") as mock_settings,
            patch("app.intelligence.llm.LLMLabeler") as MockLabeler,
        ):
            mock_settings.nvidia_api_key = "nvapi-test"
            mock_instance = MockLabeler.return_value
            mock_instance.analyze_trace = AsyncMock(return_value=mock_analyze)

            resp = client.post(
                "/api/v1/intelligence/suggest-curation",
                json={"trace_id": "test-trace-001"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["label"] == "excellent"
            assert data["quality_score"] == 5
            assert data["source_quality_score"] == 92
            assert "AI Summary:" in (data["notes"] or "")


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
