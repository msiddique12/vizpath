"""Tests for framework adapters."""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock

from vizpath.adapters.langchain import VizpathCallbackHandler
from vizpath.adapters.langgraph import LangGraphAdapter, TracedGraph
from vizpath.adapters.autogen import VizpathAutoGenCallback, wrap_autogen_agent, AutoGenTracer


class TestLangChainAdapter:
    """Tests for LangChain callback handler."""

    def test_inherits_from_base_handler(self):
        """VizpathCallbackHandler should inherit from LangChain's BaseCallbackHandler."""
        handler = VizpathCallbackHandler()
        # The class should have BaseCallbackHandler in its MRO
        base_class_names = [c.__name__ for c in type(handler).__mro__]
        assert "BaseCallbackHandler" in base_class_names

    def test_creates_trace_on_chain_start(self):
        """Chain start should create a trace context."""
        handler = VizpathCallbackHandler()

        from uuid import UUID
        run_id = UUID("12345678-1234-1234-1234-123456789abc")

        handler.on_chain_start(
            serialized={"name": "test-chain"},
            inputs={"query": "hello"},
            run_id=run_id,
        )

        assert handler._trace is not None
        assert str(run_id) in handler._spans

    def test_ends_trace_when_stack_empty(self):
        """Chain end should end trace when no spans remain."""
        handler = VizpathCallbackHandler()

        from uuid import UUID
        run_id = UUID("12345678-1234-1234-1234-123456789abc")

        handler.on_chain_start(
            serialized={"name": "test-chain"},
            inputs={},
            run_id=run_id,
        )

        handler.on_chain_end(outputs={"result": "done"}, run_id=run_id)

        assert handler._trace is None
        assert len(handler._span_stack) == 0

    def test_creates_llm_span(self):
        """LLM start should create an LLM span."""
        handler = VizpathCallbackHandler()

        from uuid import UUID
        chain_id = UUID("11111111-1111-1111-1111-111111111111")
        llm_id = UUID("22222222-2222-2222-2222-222222222222")

        handler.on_chain_start(
            serialized={"name": "chain"},
            inputs={},
            run_id=chain_id,
        )

        handler.on_llm_start(
            serialized={"name": "gpt-4"},
            prompts=["Hello, world!"],
            run_id=llm_id,
            parent_run_id=chain_id,
        )

        assert str(llm_id) in handler._spans
        span = handler._spans[str(llm_id)]
        assert span._span_type.value == "llm"


class TestLangGraphAdapter:
    """Tests for LangGraph adapter."""

    def test_adapter_wraps_graph(self):
        """Adapter should wrap graph in TracedGraph."""
        mock_graph = MagicMock()
        adapter = LangGraphAdapter()
        result = adapter.wrap(mock_graph)

        assert isinstance(result, TracedGraph)

    def test_traced_graph_delegates_unknown_attrs(self):
        """TracedGraph should delegate unknown attributes to wrapped graph."""
        mock_graph = MagicMock()
        mock_graph.some_method = MagicMock(return_value="test")

        adapter = LangGraphAdapter()
        traced = adapter.wrap(mock_graph)

        result = traced.some_method()
        assert result == "test"


class TestAutoGenAdapter:
    """Tests for AutoGen adapter."""

    def test_callback_creates_trace(self):
        """Callback should create trace on conversation start."""
        callback = VizpathAutoGenCallback()

        callback.on_conversation_start("agent1", "agent2", message="hello")

        assert callback._trace is not None

    def test_callback_ends_trace(self):
        """Callback should end trace on conversation end."""
        callback = VizpathAutoGenCallback()

        callback.on_conversation_start("agent1", "agent2")
        callback.on_conversation_end()

        assert callback._trace is None

    def test_callback_creates_agent_span(self):
        """Agent message should create agent span."""
        callback = VizpathAutoGenCallback()

        callback.on_conversation_start("agent1", "agent2")
        callback.on_agent_message("agent1", {"content": "Hello"})

        assert "agent1" in callback._agent_spans

    def test_wrap_agent_adds_tracing(self):
        """wrap_autogen_agent should add tracing methods."""
        mock_agent = MagicMock()
        mock_agent.name = "test_agent"
        mock_agent.generate_reply = MagicMock(return_value="response")

        callback = VizpathAutoGenCallback()
        wrapped = wrap_autogen_agent(mock_agent, callback)

        # The wrapped agent should have a traced generate_reply
        assert wrapped.generate_reply is not mock_agent.generate_reply.__self__

    def test_autogen_tracer_context_manager(self):
        """AutoGenTracer should work as context manager."""
        with AutoGenTracer(name="test-conv") as callback:
            assert isinstance(callback, VizpathAutoGenCallback)
            assert callback._trace is not None


class TestAdapterIntegration:
    """Integration tests for adapters with mocked Tracer."""

    @patch("vizpath.adapters.langchain.Tracer")
    def test_langchain_uses_provided_tracer(self, mock_tracer_class):
        """LangChain adapter should use provided tracer."""
        mock_tracer = MagicMock()
        handler = VizpathCallbackHandler(tracer=mock_tracer)

        assert handler._tracer is mock_tracer

    @patch("vizpath.adapters.langgraph.Tracer")
    def test_langgraph_uses_provided_tracer(self, mock_tracer_class):
        """LangGraph adapter should use provided tracer."""
        mock_tracer = MagicMock()
        adapter = LangGraphAdapter(tracer=mock_tracer)

        assert adapter._tracer is mock_tracer

    @patch("vizpath.adapters.autogen.Tracer")
    def test_autogen_uses_provided_tracer(self, mock_tracer_class):
        """AutoGen adapter should use provided tracer."""
        mock_tracer = MagicMock()
        callback = VizpathAutoGenCallback(tracer=mock_tracer)

        assert callback._tracer is mock_tracer
