"""Tests for the Haystack adapter."""

import pytest
from unittest.mock import MagicMock, AsyncMock

from vizpath.adapters.haystack import (
    HaystackAdapter,
    TracedPipeline,
    VizpathHaystackTracer,
    _HaystackSpanContext,
    _component_span_type,
)
from vizpath.span import SpanType


class TestComponentSpanType:
    """Unit tests for the component type -> SpanType mapping."""

    def test_llm_maps_to_llm(self):
        assert _component_span_type("OpenAIGenerator") == SpanType.LLM

    def test_chat_maps_to_llm(self):
        assert _component_span_type("ChatOpenAI") == SpanType.LLM

    def test_retriever_maps_to_retrieval(self):
        assert _component_span_type("BM25Retriever") == SpanType.RETRIEVAL

    def test_embedder_maps_to_retrieval(self):
        assert _component_span_type("SentenceTransformersDocumentEmbedder") == SpanType.RETRIEVAL

    def test_tool_maps_to_tool(self):
        assert _component_span_type("tool_runner") == SpanType.TOOL

    def test_agent_maps_to_agent(self):
        assert _component_span_type("agent") == SpanType.AGENT

    def test_unknown_maps_to_chain(self):
        assert _component_span_type("PromptBuilder") == SpanType.CHAIN


class TestVizpathHaystackTracer:
    """Unit tests for VizpathHaystackTracer."""

    def test_uses_provided_tracer(self):
        """Should use the injected Tracer."""
        mock_tracer = MagicMock()
        hs_tracer = VizpathHaystackTracer(tracer=mock_tracer)
        assert hs_tracer._tracer is mock_tracer

    def test_trace_component_creates_trace(self):
        """trace_component should lazily create a trace."""
        hs_tracer = VizpathHaystackTracer()
        hs_tracer.trace_component("retriever")
        assert hs_tracer._trace is not None

    def test_trace_component_returns_span_id(self):
        """trace_component should return a non-empty span_id."""
        hs_tracer = VizpathHaystackTracer()
        span_id = hs_tracer.trace_component("llm")
        assert span_id
        assert "llm" in span_id

    def test_trace_component_registers_span(self):
        """trace_component should add span to internal tracking."""
        hs_tracer = VizpathHaystackTracer()
        span_id = hs_tracer.trace_component("retriever")
        assert span_id in hs_tracer._spans

    def test_end_component_removes_span(self):
        """end_component should remove span and close it."""
        hs_tracer = VizpathHaystackTracer()
        span_id = hs_tracer.trace_component("retriever")
        hs_tracer.end_component(span_id, outputs={"documents": []})
        assert span_id not in hs_tracer._spans

    def test_end_component_clears_trace_when_last_span(self):
        """Ending the last component should finalize the trace."""
        hs_tracer = VizpathHaystackTracer()
        span_id = hs_tracer.trace_component("llm")
        hs_tracer.end_component(span_id)
        assert hs_tracer._trace is None

    def test_end_component_keeps_trace_when_siblings_remain(self):
        """Trace should stay open while other spans are still active."""
        hs_tracer = VizpathHaystackTracer()
        s1 = hs_tracer.trace_component("retriever")
        s2 = hs_tracer.trace_component("llm")
        hs_tracer.end_component(s1)
        assert hs_tracer._trace is not None

    def test_end_component_with_error_marks_span(self):
        """end_component with error should mark span as errored without raising."""
        hs_tracer = VizpathHaystackTracer()
        span_id = hs_tracer.trace_component("llm")
        hs_tracer.end_component(span_id, error="API timeout")
        assert span_id not in hs_tracer._spans

    def test_unknown_span_id_is_safe(self):
        """end_component with an unknown span_id should not raise."""
        hs_tracer = VizpathHaystackTracer()
        hs_tracer.end_component("nonexistent")  # should not raise

    def test_nested_components_stack_correctly(self):
        """Nested trace_component calls should build a span stack."""
        hs_tracer = VizpathHaystackTracer()
        s1 = hs_tracer.trace_component("pipeline")
        s2 = hs_tracer.trace_component("retriever")
        assert len(hs_tracer._span_stack) == 2
        hs_tracer.end_component(s2)
        assert len(hs_tracer._span_stack) == 1
        hs_tracer.end_component(s1)
        assert len(hs_tracer._span_stack) == 0

    def test_trace_method_returns_span_context(self):
        """trace() should return a _HaystackSpanContext."""
        hs_tracer = VizpathHaystackTracer()
        ctx = hs_tracer.trace("my-op", tags={"key": "value"})
        assert isinstance(ctx, _HaystackSpanContext)

    def test_span_context_enter_exit(self):
        """_HaystackSpanContext should enter and exit without error."""
        hs_tracer = VizpathHaystackTracer()
        with hs_tracer.trace("retriever", tags={"haystack.component.type": "BM25Retriever"}):
            pass  # should not raise


class TestHaystackSpanContext:
    """Unit tests for _HaystackSpanContext."""

    def test_set_tag_stores_value(self):
        """set_tag should update internal tags dict."""
        hs_tracer = VizpathHaystackTracer()
        ctx = _HaystackSpanContext(hs_tracer, "op", {}, None)
        ctx.set_tag("key", "value")
        assert ctx._tags["key"] == "value"

    def test_set_content_tag_stores_value(self):
        """set_content_tag is an alias for set_tag."""
        hs_tracer = VizpathHaystackTracer()
        ctx = _HaystackSpanContext(hs_tracer, "op", {}, None)
        ctx.set_content_tag("content", "hello")
        assert ctx._tags["content"] == "hello"

    def test_raw_span_returns_none_before_enter(self):
        """raw_span should return None before context is entered."""
        hs_tracer = VizpathHaystackTracer()
        ctx = _HaystackSpanContext(hs_tracer, "op", {}, None)
        assert ctx.raw_span() is None


class TestHaystackAdapter:
    """Unit tests for HaystackAdapter."""

    def test_wrap_returns_traced_pipeline(self):
        """wrap() should return a TracedPipeline."""
        mock_pipeline = MagicMock()
        adapter = HaystackAdapter()
        result = adapter.wrap(mock_pipeline)
        assert isinstance(result, TracedPipeline)

    def test_wrap_uses_provided_tracer(self):
        """wrap() should pass the injected tracer to TracedPipeline."""
        mock_tracer = MagicMock()
        adapter = HaystackAdapter(tracer=mock_tracer)
        traced = adapter.wrap(MagicMock())
        assert traced._tracer is mock_tracer


class TestTracedPipeline:
    """Unit tests for TracedPipeline."""

    def test_run_calls_pipeline_run(self):
        """run() should call the underlying pipeline's run."""
        mock_pipeline = MagicMock()
        mock_pipeline.metadata = {"name": "test-pipe"}
        mock_pipeline.run.return_value = {"output": "result"}

        from vizpath import Tracer
        traced = TracedPipeline(mock_pipeline, Tracer())
        result = traced.run({"query": "hello"})

        mock_pipeline.run.assert_called_once()
        assert result == {"output": "result"}

    def test_run_propagates_exception(self):
        """run() should propagate pipeline exceptions."""
        mock_pipeline = MagicMock()
        mock_pipeline.metadata = {}
        mock_pipeline.run.side_effect = ValueError("pipeline error")

        from vizpath import Tracer
        traced = TracedPipeline(mock_pipeline, Tracer())
        with pytest.raises(ValueError, match="pipeline error"):
            traced.run({"query": "hello"})

    def test_delegates_unknown_attributes(self):
        """Unknown attributes should forward to the underlying pipeline."""
        mock_pipeline = MagicMock()
        mock_pipeline.graph = {"nodes": []}

        from vizpath import Tracer
        traced = TracedPipeline(mock_pipeline, Tracer())
        assert traced.graph == {"nodes": []}

    @pytest.mark.asyncio
    async def test_run_async_calls_pipeline_run_async(self):
        """run_async() should await the pipeline's run_async."""
        mock_pipeline = MagicMock()
        mock_pipeline.metadata = {}
        mock_pipeline.run_async = AsyncMock(return_value={"out": "done"})

        from vizpath import Tracer
        traced = TracedPipeline(mock_pipeline, Tracer())
        result = await traced.run_async({"query": "hello"})
        assert result == {"out": "done"}
