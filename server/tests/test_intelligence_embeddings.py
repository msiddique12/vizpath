"""Tests for intelligence embeddings module."""

from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from app.intelligence.embeddings import (
    EMBEDDING_DIM,
    embed_trace,
    get_trace_embeddings,
    trace_to_text,
)


SAMPLE_TRACE = {
    "id": "trace-001",
    "name": "research_session",
    "status": "success",
    "duration_ms": 5000,
    "total_tokens": 1500,
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

SAMPLE_TRACE_WITH_ERROR = {
    "id": "trace-002",
    "name": "failed_task",
    "status": "error",
    "duration_ms": 3000,
    "total_tokens": None,
    "spans": [
        {
            "name": "bad_call",
            "span_type": "llm",
            "duration_ms": 1000,
            "tokens": 100,
            "error": "timeout",
        },
    ],
}


class TestTraceToText:
    def test_basic_trace(self):
        text = trace_to_text(SAMPLE_TRACE)
        assert "research_session" in text
        assert "success" in text
        assert "5000ms" in text
        assert "llm_call" in text
        assert "web_search" in text

    def test_trace_with_error(self):
        text = trace_to_text(SAMPLE_TRACE_WITH_ERROR)
        assert "failed_task" in text
        assert "error" in text
        assert "timeout" in text

    def test_empty_trace(self):
        text = trace_to_text({"name": "empty", "status": "success"})
        assert "empty" in text
        assert "no spans" in text

    def test_deterministic(self):
        """Same input should always produce same text."""
        text1 = trace_to_text(SAMPLE_TRACE)
        text2 = trace_to_text(SAMPLE_TRACE)
        assert text1 == text2


def _mock_embedding_response(dim=EMBEDDING_DIM):
    """Create a mock NIM embedding response."""
    mock_data = MagicMock()
    mock_data.embedding = list(np.random.randn(dim).astype(np.float32))
    mock_response = MagicMock()
    mock_response.data = [mock_data]
    return mock_response


class TestEmbedTrace:
    @pytest.mark.asyncio
    async def test_embed_trace_no_cache(self):
        """Test embedding generation with no Redis available."""
        with (
            patch("app.intelligence.embeddings._get_redis", return_value=None),
            patch("app.intelligence.embeddings._get_client") as mock_get_client,
        ):
            mock_client = AsyncMock()
            mock_client.embeddings.create = AsyncMock(
                return_value=_mock_embedding_response()
            )
            mock_get_client.return_value = mock_client

            result = await embed_trace("trace-001", "some text")

            assert isinstance(result, np.ndarray)
            assert result.shape == (EMBEDDING_DIM,)
            assert result.dtype == np.float32
            mock_client.embeddings.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_embed_trace_cache_hit(self):
        """Test that cached embeddings are returned without API call."""
        import pickle

        cached_embedding = np.ones(EMBEDDING_DIM, dtype=np.float32)
        mock_redis = MagicMock()
        mock_redis.get.return_value = pickle.dumps(cached_embedding)

        with (
            patch("app.intelligence.embeddings._get_redis", return_value=mock_redis),
            patch("app.intelligence.embeddings._get_client") as mock_get_client,
        ):
            mock_client = AsyncMock()
            mock_get_client.return_value = mock_client

            result = await embed_trace("trace-001", "some text")

            assert np.array_equal(result, cached_embedding)
            mock_client.embeddings.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_embed_trace_api_failure_returns_zero(self):
        """Test zero-vector fallback on API failure."""
        with (
            patch("app.intelligence.embeddings._get_redis", return_value=None),
            patch("app.intelligence.embeddings._get_client") as mock_get_client,
        ):
            mock_client = AsyncMock()
            mock_client.embeddings.create = AsyncMock(
                side_effect=Exception("API error")
            )
            mock_get_client.return_value = mock_client

            result = await embed_trace("trace-001", "some text")

            assert isinstance(result, np.ndarray)
            assert result.shape == (EMBEDDING_DIM,)
            assert np.all(result == 0)


class TestGetTraceEmbeddings:
    @pytest.mark.asyncio
    async def test_batch_embeddings(self):
        """Test batch embedding generation."""
        traces = {
            "trace-001": "text for trace 1",
            "trace-002": "text for trace 2",
        }

        mock_data_1 = MagicMock()
        mock_data_1.embedding = list(np.random.randn(EMBEDDING_DIM).astype(np.float32))
        mock_data_2 = MagicMock()
        mock_data_2.embedding = list(np.random.randn(EMBEDDING_DIM).astype(np.float32))

        mock_response = MagicMock()
        mock_response.data = [mock_data_1, mock_data_2]

        with (
            patch("app.intelligence.embeddings._get_redis", return_value=None),
            patch("app.intelligence.embeddings._get_client") as mock_get_client,
        ):
            mock_client = AsyncMock()
            mock_client.embeddings.create = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_client

            result = await get_trace_embeddings(traces)

            assert len(result) == 2
            assert "trace-001" in result
            assert "trace-002" in result
            assert result["trace-001"].shape == (EMBEDDING_DIM,)

    @pytest.mark.asyncio
    async def test_empty_input(self):
        result = await get_trace_embeddings({})
        assert result == {}
