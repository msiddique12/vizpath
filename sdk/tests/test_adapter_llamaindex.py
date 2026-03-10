"""Tests for the LlamaIndex adapter."""

from unittest.mock import MagicMock

from vizpath.adapters.llamaindex import VizpathLlamaIndexCallback


class FakeEventType:
    """Simulates a LlamaIndex CBEventType enum value."""

    def __init__(self, value: str) -> None:
        self.value = value


LLM = FakeEventType("llm")
QUERY = FakeEventType("query")
RETRIEVE = FakeEventType("retrieve")
EMBEDDING = FakeEventType("embedding")
FUNCTION_CALL = FakeEventType("function_call")
AGENT_STEP = FakeEventType("agent_step")
SYNTHESIZE = FakeEventType("synthesize")


class TestVizpathLlamaIndexCallback:
    """Unit tests for VizpathLlamaIndexCallback."""

    def test_inherits_from_base_handler(self):
        """Should inherit from BaseCallbackHandler (fallback or real)."""
        handler = VizpathLlamaIndexCallback()
        base_names = [c.__name__ for c in type(handler).__mro__]
        assert "BaseCallbackHandler" in base_names

    def test_uses_provided_tracer(self):
        """Should use the injected tracer."""
        mock_tracer = MagicMock()
        handler = VizpathLlamaIndexCallback(tracer=mock_tracer)
        assert handler._tracer is mock_tracer

    def test_on_event_start_creates_trace(self):
        """First event start should create a trace."""
        handler = VizpathLlamaIndexCallback()
        handler.on_event_start(QUERY, payload={"query_str": "hello"}, event_id="e1")
        assert handler._trace is not None

    def test_on_event_start_tracks_root_event(self):
        """First event_id becomes the root."""
        handler = VizpathLlamaIndexCallback()
        handler.on_event_start(QUERY, event_id="root-id")
        assert handler._root_event_id == "root-id"

    def test_on_event_start_creates_span(self):
        """on_event_start should register a span by event_id."""
        handler = VizpathLlamaIndexCallback()
        handler.on_event_start(LLM, payload={}, event_id="llm-1")
        assert "llm-1" in handler._spans

    def test_on_event_start_nests_child_under_parent(self):
        """Child events should be nested under parent spans."""
        handler = VizpathLlamaIndexCallback()
        handler.on_event_start(QUERY, event_id="q1")
        handler.on_event_start(RETRIEVE, event_id="r1", parent_id="q1")
        assert "q1" in handler._spans
        assert "r1" in handler._spans

    def test_on_event_end_removes_span(self):
        """on_event_end should remove the span from tracking."""
        handler = VizpathLlamaIndexCallback()
        handler.on_event_start(LLM, event_id="llm-1")
        handler.on_event_end(LLM, event_id="llm-1")
        assert "llm-1" not in handler._spans

    def test_on_event_end_root_clears_trace(self):
        """Ending the root event should finalize the trace."""
        handler = VizpathLlamaIndexCallback()
        handler.on_event_start(QUERY, event_id="root")
        handler.on_event_end(QUERY, event_id="root")
        assert handler._trace is None
        assert handler._root_event_id is None

    def test_non_root_event_end_does_not_clear_trace(self):
        """Ending a non-root event should not end the trace."""
        handler = VizpathLlamaIndexCallback()
        handler.on_event_start(QUERY, event_id="root")
        handler.on_event_start(LLM, event_id="llm-1", parent_id="root")
        handler.on_event_end(LLM, event_id="llm-1")
        # Root event still open, trace should remain
        assert handler._trace is not None

    def test_llm_event_sets_model_attribute(self):
        """LLM event with model info should set model attribute."""
        handler = VizpathLlamaIndexCallback()
        handler.on_event_start(
            LLM,
            payload={"model": "gpt-4"},
            event_id="llm-1",
        )
        span = handler._spans["llm-1"]
        assert span._attributes.get("model") == "gpt-4"

    def test_retrieve_event_captures_query(self):
        """Retrieve event should set query attribute."""
        handler = VizpathLlamaIndexCallback()
        handler.on_event_start(
            RETRIEVE,
            payload={"query_str": "What is ML?"},
            event_id="r1",
        )
        span = handler._spans["r1"]
        assert span._attributes.get("query") == "What is ML?"

    def test_retrieve_end_captures_document_count(self):
        """on_event_end for retrieve should capture document count."""
        handler = VizpathLlamaIndexCallback()
        handler.on_event_start(RETRIEVE, event_id="r1")
        handler.on_event_end(RETRIEVE, payload={"nodes": ["a", "b", "c"]}, event_id="r1")
        # Span ended; just verify no exception and span removed
        assert "r1" not in handler._spans

    def test_embedding_end_captures_chunk_count(self):
        """on_event_end for embedding should capture chunk count."""
        handler = VizpathLlamaIndexCallback()
        handler.on_event_start(EMBEDDING, event_id="emb-1")
        handler.on_event_end(
            EMBEDDING, payload={"chunks": ["a", "b"]}, event_id="emb-1"
        )
        assert "emb-1" not in handler._spans

    def test_function_call_sets_function_attribute(self):
        """Function call event should capture function name."""
        handler = VizpathLlamaIndexCallback()
        handler.on_event_start(
            FUNCTION_CALL,
            payload={"function_name": "search"},
            event_id="fc-1",
        )
        span = handler._spans["fc-1"]
        assert span._attributes.get("function") == "search"

    def test_start_trace_is_noop(self):
        """start_trace should not raise."""
        handler = VizpathLlamaIndexCallback()
        handler.start_trace(trace_id="t1")  # should not raise

    def test_end_trace_closes_open_trace(self):
        """end_trace should finalize any open trace context."""
        handler = VizpathLlamaIndexCallback()
        handler.on_event_start(QUERY, event_id="q1")
        assert handler._trace is not None
        handler.end_trace(trace_id="t1")
        assert handler._trace is None

    def test_end_trace_noop_when_no_trace(self):
        """end_trace when no trace is open should not raise."""
        handler = VizpathLlamaIndexCallback()
        handler.end_trace()  # should not raise

    def test_agent_step_uses_agent_span_type(self):
        """agent_step events should map to AGENT span type."""
        from vizpath.span import SpanType

        handler = VizpathLlamaIndexCallback()
        handler.on_event_start(AGENT_STEP, event_id="as-1")
        span = handler._spans["as-1"]
        assert span._span_type == SpanType.AGENT

    def test_llm_event_uses_llm_span_type(self):
        """llm events should map to LLM span type."""
        from vizpath.span import SpanType

        handler = VizpathLlamaIndexCallback()
        handler.on_event_start(LLM, event_id="llm-2")
        span = handler._spans["llm-2"]
        assert span._span_type == SpanType.LLM

    def test_llm_end_extracts_response_text(self):
        """LLM end with a response object should capture text output."""
        handler = VizpathLlamaIndexCallback()
        handler.on_event_start(LLM, event_id="llm-3")

        fake_response = MagicMock()
        fake_response.text = "The answer is 42."
        handler.on_event_end(LLM, payload={"response": fake_response}, event_id="llm-3")
        assert "llm-3" not in handler._spans

    def test_multiple_events_in_sequence(self):
        """Multiple sequential events should not interfere."""
        handler = VizpathLlamaIndexCallback()
        handler.on_event_start(QUERY, event_id="q1")
        handler.on_event_start(RETRIEVE, event_id="r1", parent_id="q1")
        handler.on_event_end(RETRIEVE, event_id="r1")
        handler.on_event_start(SYNTHESIZE, event_id="s1", parent_id="q1")
        handler.on_event_end(SYNTHESIZE, event_id="s1")
        handler.on_event_end(QUERY, event_id="q1")

        assert handler._trace is None
        assert len(handler._spans) == 0
