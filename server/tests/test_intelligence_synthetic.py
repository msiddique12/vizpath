"""Tests for intelligence synthetic data module."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.intelligence.synthetic import SyntheticDataGenerator

SAMPLE_TRACE = {
    "id": "trace-001",
    "name": "research_session",
    "status": "success",
    "duration_ms": 5000,
    "total_tokens": 1500,
    "metadata": {"research.topic": "AI agents"},
    "spans": [
        {"name": "llm_call", "span_type": "llm", "output": "response text"},
        {"name": "web_search", "span_type": "tool", "output": {"results": []}},
    ],
}

FAILED_TRACE = {
    "id": "trace-002",
    "name": "failed_task",
    "status": "error",
    "error": "Tool execution timeout",
    "spans": [
        {"name": "bad_call", "span_type": "tool", "error": "timeout"},
    ],
}


def _mock_chat_response(content: str):
    mock_message = MagicMock()
    mock_message.content = content
    mock_choice = MagicMock()
    mock_choice.message = mock_message
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    return mock_response


@pytest.fixture
def generator():
    with patch("app.intelligence.synthetic.AsyncOpenAI") as mock_cls:
        mock_cls.return_value = AsyncMock()
        gen = SyntheticDataGenerator()
    gen.client = AsyncMock()
    return gen


class TestGenerateVariations:
    @pytest.mark.asyncio
    async def test_generate_variations_success(self, generator):
        response_json = json.dumps({
            "variations": [
                {
                    "name": "Alternative approach",
                    "steps": [{"action": "search", "tool": "web", "reasoning": "faster"}],
                    "approach": "Direct search instead of browse",
                },
                {
                    "name": "Cached approach",
                    "steps": [{"action": "cache_lookup", "tool": "cache", "reasoning": "reuse"}],
                    "approach": "Use cached results",
                },
            ]
        })
        generator.client.chat.completions.create = AsyncMock(
            return_value=_mock_chat_response(response_json)
        )

        result = await generator.generate_variations(SAMPLE_TRACE, n=2)

        assert len(result) == 2
        assert result[0]["name"] == "Alternative approach"
        assert "steps" in result[0]

    @pytest.mark.asyncio
    async def test_generate_variations_respects_n(self, generator):
        response_json = json.dumps({
            "variations": [
                {"name": f"v{i}", "steps": [], "approach": f"approach {i}"}
                for i in range(10)
            ]
        })
        generator.client.chat.completions.create = AsyncMock(
            return_value=_mock_chat_response(response_json)
        )

        result = await generator.generate_variations(SAMPLE_TRACE, n=3)
        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_generate_variations_api_failure(self, generator):
        generator.client.chat.completions.create = AsyncMock(
            side_effect=Exception("API error")
        )
        result = await generator.generate_variations(SAMPLE_TRACE)
        assert result == []


class TestGenerateCorrections:
    @pytest.mark.asyncio
    async def test_generate_corrections_success(self, generator):
        response_json = json.dumps({
            "corrections": [
                {
                    "name": "Fixed timeout handling",
                    "failure_analysis": "Tool call timed out due to large payload",
                    "steps": [
                        {"action": "chunk_request", "tool": "web", "reasoning": "smaller payloads"}
                    ],
                },
            ]
        })
        generator.client.chat.completions.create = AsyncMock(
            return_value=_mock_chat_response(response_json)
        )

        result = await generator.generate_corrections(FAILED_TRACE, n=1)

        assert len(result) == 1
        assert "failure_analysis" in result[0]

    @pytest.mark.asyncio
    async def test_generate_corrections_api_failure(self, generator):
        generator.client.chat.completions.create = AsyncMock(
            side_effect=Exception("API error")
        )
        result = await generator.generate_corrections(FAILED_TRACE)
        assert result == []


class TestExportTrainingPairs:
    @pytest.mark.asyncio
    async def test_export_jsonl(self, generator):
        traces = [SAMPLE_TRACE, FAILED_TRACE]
        result = await generator.export_training_pairs(traces)

        lines = result.strip().split("\n")
        assert len(lines) == 2

        pair1 = json.loads(lines[0])
        assert pair1["input"] == "Research: AI agents"
        assert "metadata" in pair1
        assert pair1["metadata"]["source_trace"] == "trace-001"
        assert pair1["metadata"]["success"] is True

        pair2 = json.loads(lines[1])
        assert pair2["input"] == "Task: failed_task"
        assert pair2["metadata"]["success"] is False

    @pytest.mark.asyncio
    async def test_export_empty(self, generator):
        result = await generator.export_training_pairs([])
        assert result == ""
