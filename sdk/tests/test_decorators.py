"""Tests for global decorator-based tracer behavior."""

from unittest.mock import patch

import pytest

from vizpath.decorators import GlobalTracer, _current_span


def test_span_decorator_works_without_active_trace():
    """Span decorator should execute normally when no trace context exists."""
    tracer = GlobalTracer()

    @tracer.span("standalone")
    def _no_trace(value: int) -> int:
        assert _current_span.get() is None
        return value * 2

    assert _no_trace(3) == 6
    assert _current_span.get() is None


@pytest.mark.asyncio
async def test_async_span_decorator_works_without_active_trace():
    """Async span decorator should execute normally when no trace context exists."""
    tracer = GlobalTracer()

    @tracer.span("standalone-async")
    async def _no_trace_async(value: int) -> int:
        assert _current_span.get() is None
        return value * 3

    assert await _no_trace_async(4) == 12
    assert _current_span.get() is None


def test_configure_closes_previous_client():
    """Reconfiguring should close old client to avoid leaked flush threads."""
    tracer = GlobalTracer()

    with patch("vizpath.decorators.Client.close") as mock_close:
        tracer.configure(api_url="http://localhost:8000")
        tracer.configure(api_url="http://localhost:8001")

        assert mock_close.call_count == 1
