"""Tests for intelligence LLM labeler module."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.intelligence.llm import LLMLabeler, _extract_json

# --- _extract_json tests ---


class TestExtractJson:
    def test_direct_json(self):
        result = _extract_json('{"key": "value"}')
        assert result == {"key": "value"}

    def test_json_in_code_block(self):
        text = 'Some text\n```json\n{"key": "value"}\n```\nMore text'
        result = _extract_json(text)
        assert result == {"key": "value"}

    def test_json_in_code_block_no_lang(self):
        text = 'Some text\n```\n{"key": "value"}\n```'
        result = _extract_json(text)
        assert result == {"key": "value"}

    def test_json_braces_fallback(self):
        text = 'Here is the result: {"score": 42, "label": "good"} done.'
        result = _extract_json(text)
        assert result == {"score": 42, "label": "good"}

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="Empty text"):
            _extract_json("")

    def test_whitespace_raises(self):
        with pytest.raises(ValueError, match="Empty text"):
            _extract_json("   ")

    def test_no_json_raises(self):
        with pytest.raises(ValueError, match="Could not extract JSON"):
            _extract_json("This is just plain text with no JSON at all.")


# --- LLMLabeler tests ---


def _mock_chat_response(content: str):
    """Create a mock OpenAI chat completion response."""
    mock_message = MagicMock()
    mock_message.content = content
    mock_choice = MagicMock()
    mock_choice.message = mock_message
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    return mock_response


SAMPLE_TRACE = {
    "id": "trace-001",
    "name": "research_session",
    "status": "success",
    "duration_ms": 5000,
    "total_tokens": 1500,
    "total_cost": 0.02,
    "spans": [
        {
            "name": "llm_call",
            "span_type": "llm",
            "duration_ms": 2000,
            "tokens": 500,
            "error": None,
        },
        {
            "name": "web_search",
            "span_type": "tool",
            "duration_ms": 1000,
            "tokens": None,
            "error": None,
        },
    ],
}


@pytest.fixture
def labeler():
    """Create an LLMLabeler with mocked dependencies."""
    with (
        patch("app.intelligence.llm.redis") as mock_redis_mod,
        patch("app.intelligence.llm.AsyncOpenAI") as mock_openai_cls,
    ):
        mock_redis_mod.from_url.side_effect = Exception("no redis")
        mock_openai_cls.return_value = AsyncMock()
        labeler = LLMLabeler()
    labeler.client = AsyncMock()
    labeler.redis = None
    return labeler


class TestLabelTrace:
    @pytest.mark.asyncio
    async def test_label_trace_success(self, labeler):
        response_json = json.dumps({
            "success": True,
            "confidence": 0.92,
            "reasoning": "The agent completed all steps successfully.",
        })
        labeler.client.chat.completions.create = AsyncMock(
            return_value=_mock_chat_response(response_json)
        )

        result = await labeler.label_trace(SAMPLE_TRACE)

        assert result is not None
        assert result["success"] is True
        assert result["confidence"] == 0.92
        assert "reasoning" in result

    @pytest.mark.asyncio
    async def test_label_trace_normalizes_confidence(self, labeler):
        response_json = json.dumps({
            "success": True,
            "confidence": 85,
            "reasoning": "Good trace.",
        })
        labeler.client.chat.completions.create = AsyncMock(
            return_value=_mock_chat_response(response_json)
        )

        result = await labeler.label_trace(SAMPLE_TRACE)
        assert result is not None
        assert result["confidence"] == 0.85

    @pytest.mark.asyncio
    async def test_label_trace_missing_id(self, labeler):
        result = await labeler.label_trace({"name": "no-id"})
        assert result is None

    @pytest.mark.asyncio
    async def test_label_trace_coerces_bool_and_percentage_confidence(self, labeler):
        response_json = json.dumps({
            "success": 1,
            "confidence": 72,
            "reasoning": "Trace mostly successful.",
        })
        labeler.client.chat.completions.create = AsyncMock(
            return_value=_mock_chat_response(response_json)
        )

        result = await labeler.label_trace(SAMPLE_TRACE)
        assert result is not None
        assert result["success"] is True
        assert result["confidence"] == 0.72

    @pytest.mark.asyncio
    async def test_label_trace_api_error(self, labeler):
        labeler.client.chat.completions.create = AsyncMock(
            side_effect=Exception("API error")
        )
        result = await labeler.label_trace(SAMPLE_TRACE)
        assert result is None


class TestAnalyzeTrace:
    @pytest.mark.asyncio
    async def test_analyze_trace_success(self, labeler):
        response_json = json.dumps({
            "quality_score": 85,
            "efficiency_score": 70,
            "error_analysis": "No errors found.",
            "suggestions": ["Cache repeated queries"],
        })
        labeler.client.chat.completions.create = AsyncMock(
            return_value=_mock_chat_response(response_json)
        )

        result = await labeler.analyze_trace(SAMPLE_TRACE)
        assert result["quality_score"] == 85
        assert result["efficiency_score"] == 70
        assert len(result["suggestions"]) == 1

    @pytest.mark.asyncio
    async def test_analyze_trace_failure(self, labeler):
        labeler.client.chat.completions.create = AsyncMock(
            side_effect=Exception("API error")
        )
        result = await labeler.analyze_trace(SAMPLE_TRACE)
        assert result["quality_score"] == 0
        assert "Analysis failed" in result["error_analysis"]

    @pytest.mark.asyncio
    async def test_analyze_trace_clamps_scores_and_coerces_fields(self, labeler):
        response_json = json.dumps({
            "quality_score": 150,
            "efficiency_score": -20,
            "labels": ["  good ", None, 42],
            "suggestions": [None, "Cache repeated queries"],
            "summary": "  Strong tracing run  ",
            "error_analysis": 123,
        })
        labeler.client.chat.completions.create = AsyncMock(
            return_value=_mock_chat_response(response_json)
        )

        result = await labeler.analyze_trace(SAMPLE_TRACE)
        assert result["quality_score"] == 100
        assert result["efficiency_score"] == 0
        assert result["analysis"]["labels"] == ["good", "42"]
        assert result["analysis"]["suggestions"] == ["Cache repeated queries"]
        assert result["analysis"]["summary"] == "Strong tracing run"



class TestSelfAnalyze:
    @pytest.mark.asyncio
    async def test_self_analyze_success(self, labeler):
        response_json = json.dumps({
            "quality": 90,
            "efficiency": 80,
            "completeness": 95,
            "overall_score": 88,
            "redundant_steps": [],
            "suggestions": ["Consider parallel tool calls"],
            "summary": "Strong execution with efficient tool use.",
        })
        labeler.client.chat.completions.create = AsyncMock(
            return_value=_mock_chat_response(response_json)
        )

        result = await labeler.self_analyze(SAMPLE_TRACE)
        assert result["overall_score"] == 88
        assert result["quality"] == 90
        assert "Strong execution" in result["summary"]

    @pytest.mark.asyncio
    async def test_self_analyze_failure(self, labeler):
        labeler.client.chat.completions.create = AsyncMock(
            side_effect=Exception("timeout")
        )
        result = await labeler.self_analyze(SAMPLE_TRACE)
        assert result["overall_score"] == 0
        assert "Analysis failed" in result["summary"]

    @pytest.mark.asyncio
    async def test_self_analyze_uses_fallback_and_coerces(self, labeler):
        response_json = json.dumps({
            "quality": 90,
            "tool_usage": 88,
            "reasoning_quality": "95",
            "overall_score": 91.2,
            "strengths": [None, "Good tool orchestration", 7],
            "weaknesses": ["Over-long prompts", 1],
            "improvements": "cleanup",
            "summary": 123,
            "redundant_steps": "step1",
        })
        labeler.client.chat.completions.create = AsyncMock(
            return_value=_mock_chat_response(response_json)
        )

        result = await labeler.self_analyze(SAMPLE_TRACE)
        assert result["analysis"]["effectiveness"] == 90
        assert result["analysis"]["tool_usage"] == 88
        assert result["analysis"]["reasoning_quality"] == 95
        assert result["analysis"]["improvements"] == []
        assert result["analysis"]["strengths"] == ["Good tool orchestration", "7"]
        assert result["analysis"]["weaknesses"] == ["Over-long prompts", "1"]
        assert result["analysis"]["summary"] == "123"
        assert result["redundant_steps"] == []
