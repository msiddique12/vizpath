"""Tests for Tracer class."""

from unittest.mock import MagicMock, patch

import pytest

from vizpath.config import Config
from vizpath.span import SpanStatus, SpanType
from vizpath.tracer import Tracer


class TestTracer:
    def test_tracer_creation_with_api_key(self):
        tracer = Tracer(api_key="test-key")

        assert tracer._config.api_key == "test-key"

    def test_tracer_creation_with_config(self):
        config = Config(api_key="config-key", buffer_size=100)
        tracer = Tracer(config=config)

        assert tracer._config.api_key == "config-key"
        assert tracer._config.buffer_size == 100

    def test_create_trace(self):
        tracer = Tracer(api_key="test-key")
        trace = tracer.trace("test-task")

        assert trace._context._name == "test-task"
        assert trace.trace_id is not None

    def test_trace_context_manager(self):
        tracer = Tracer(api_key="test-key")

        with tracer.trace("test-task") as trace:
            assert trace._context._status == SpanStatus.RUNNING

        assert trace._context._status == SpanStatus.SUCCESS

    def test_trace_with_spans(self):
        tracer = Tracer(api_key="test-key")

        with tracer.trace("test-task") as trace:
            with trace.span("step-1", span_type=SpanType.LLM) as span:
                span.set_tokens(100)

            with trace.span("step-2", span_type=SpanType.TOOL) as span:
                span.set_output({"result": "success"})

        assert len(trace._context._spans) == 2

    def test_trace_metadata(self):
        tracer = Tracer(api_key="test-key")

        with tracer.trace("test-task") as trace:
            trace.set_metadata(user_id="123", version="1.0")

        assert trace._context._metadata["user_id"] == "123"
        assert trace._context._metadata["version"] == "1.0"

    def test_trace_error_propagation(self):
        tracer = Tracer(api_key="test-key")

        with pytest.raises(ValueError):
            with tracer.trace("test-task") as trace:
                raise ValueError("Test error")

        assert trace._context._status == SpanStatus.ERROR

    def test_tracer_context_manager(self):
        with Tracer(api_key="test-key") as tracer:
            trace = tracer.trace("test")
            assert trace is not None


class TestTraceContext:
    def test_span_registration(self):
        tracer = Tracer(api_key="test-key")

        with tracer.trace("test") as trace:
            span = trace.span("test-span")
            span.end()

        assert len(trace._context._spans) == 1
        assert trace._context._root_span is not None

    def test_nested_span_registration(self):
        tracer = Tracer(api_key="test-key")

        with tracer.trace("test") as trace:
            with trace.span("parent") as parent:
                with parent.span("child") as child:
                    pass

        assert len(trace._context._spans) == 2
