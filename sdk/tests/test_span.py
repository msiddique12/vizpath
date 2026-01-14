"""Tests for Span class."""

import time
from unittest.mock import MagicMock

import pytest

from vizpath.span import Span, SpanStatus, SpanType


class TestSpan:
    def setup_method(self):
        self.mock_context = MagicMock()
        self.mock_context.trace_id = "test-trace-id"

    def test_span_creation(self):
        span = Span(
            name="test-span",
            trace_context=self.mock_context,
            span_type=SpanType.LLM,
        )

        assert span.name == "test-span"
        assert span._span_type == SpanType.LLM
        assert span._status == SpanStatus.RUNNING
        assert span.trace_id == "test-trace-id"
        assert span.parent_id is None

    def test_span_with_parent(self):
        parent = Span(name="parent", trace_context=self.mock_context)
        child = Span(
            name="child",
            trace_context=self.mock_context,
            parent=parent,
        )

        assert child.parent_id == parent.id
        assert child.trace_id == parent.trace_id

    def test_set_input_output(self):
        span = Span(name="test", trace_context=self.mock_context)

        span.set_input({"prompt": "hello"})
        span.set_output({"response": "world"})

        assert span._input == {"prompt": "hello"}
        assert span._output == {"response": "world"}

    def test_set_attributes(self):
        span = Span(name="test", trace_context=self.mock_context)

        span.set_attributes(model="gpt-4", temperature=0.7)

        assert span._attributes["model"] == "gpt-4"
        assert span._attributes["temperature"] == 0.7

    def test_set_tokens(self):
        span = Span(name="test", trace_context=self.mock_context)

        span.set_tokens(100, cost=0.002)

        assert span._tokens == 100
        assert span._cost == 0.002

    def test_add_event(self):
        span = Span(name="test", trace_context=self.mock_context)

        span.add_event("retry", attempt=2)

        assert len(span._events) == 1
        assert span._events[0].name == "retry"
        assert span._events[0].attributes["attempt"] == 2

    def test_set_error(self):
        span = Span(name="test", trace_context=self.mock_context)

        span.set_error("Connection failed")

        assert span._error == "Connection failed"
        assert span._status == SpanStatus.ERROR

    def test_span_end(self):
        span = Span(name="test", trace_context=self.mock_context)
        time.sleep(0.01)

        span.end()

        assert span._status == SpanStatus.SUCCESS
        assert span._end_time is not None
        assert span._duration_ms is not None
        assert span._duration_ms >= 10

    def test_span_end_with_status(self):
        span = Span(name="test", trace_context=self.mock_context)

        span.end(status=SpanStatus.ERROR)

        assert span._status == SpanStatus.ERROR

    def test_span_context_manager(self):
        span = Span(name="test", trace_context=self.mock_context)

        with span:
            time.sleep(0.01)

        assert span._status == SpanStatus.SUCCESS
        assert span._duration_ms >= 10

    def test_span_context_manager_with_exception(self):
        span = Span(name="test", trace_context=self.mock_context)

        with pytest.raises(ValueError):
            with span:
                raise ValueError("Test error")

        assert span._status == SpanStatus.ERROR
        assert span._error == "Test error"

    def test_nested_spans(self):
        parent = Span(name="parent", trace_context=self.mock_context)

        child = parent.span("child", span_type=SpanType.TOOL)

        assert child.parent_id == parent.id
        assert len(parent._children) == 1
        self.mock_context._register_span.assert_called_once_with(child)

    def test_to_data(self):
        span = Span(
            name="test",
            trace_context=self.mock_context,
            span_type=SpanType.LLM,
        )
        span.set_input("prompt")
        span.set_output("response")
        span.set_tokens(100)
        span.end()

        data = span.to_data()

        assert data.span_id == span.id
        assert data.trace_id == "test-trace-id"
        assert data.name == "test"
        assert data.span_type == SpanType.LLM
        assert data.status == SpanStatus.SUCCESS
        assert data.input == "prompt"
        assert data.output == "response"
        assert data.tokens == 100
