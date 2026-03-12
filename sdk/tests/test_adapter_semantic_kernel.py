"""Tests for the Semantic Kernel adapter."""

import asyncio
from unittest.mock import MagicMock

import pytest

from vizpath.adapters.semantic_kernel import (
    SemanticKernelAdapter,
    VizpathKernelFilter,
    _capture_token_usage,
    _ConversationContext,
    _extract_arguments,
    _extract_function_name,
    _extract_result,
    _infer_span_type,
    _safe_str,
)
from vizpath.span import SpanType

# ---------------------------------------------------------------------------
# Helpers to build fake SK context objects
# ---------------------------------------------------------------------------

def make_context(
    plugin: str = "MyPlugin",
    name: str = "my_function",
    args: dict | None = None,
    result_value: str | None = "output",
    token_usage: dict | None = None,
) -> MagicMock:
    ctx = MagicMock()
    ctx.function.plugin_name = plugin
    ctx.function.name = name
    ctx.function.description = "A test function."
    ctx.arguments = args or {}
    ctx.result.value = result_value

    if token_usage is not None:
        ctx.result.metadata = {"usage": token_usage}
    else:
        ctx.result.metadata = {}
    return ctx


# ---------------------------------------------------------------------------
# Helper extraction tests
# ---------------------------------------------------------------------------

class TestExtractFunctionName:
    def test_returns_plugin_dot_name(self):
        ctx = make_context(plugin="Search", name="web_search")
        assert _extract_function_name(ctx) == "Search.web_search"

    def test_returns_name_only_when_no_plugin(self):
        ctx = make_context(plugin="", name="summarise")
        assert _extract_function_name(ctx) == "summarise"

    def test_fallback_on_exception(self):
        ctx = MagicMock(spec=[])  # no attributes
        assert _extract_function_name(ctx) == "sk-function"


class TestExtractArguments:
    def test_dict_args(self):
        ctx = make_context(args={"input": "hello"})
        result = _extract_arguments(ctx)
        assert result == {"input": "hello"}

    def test_none_args(self):
        ctx = MagicMock()
        ctx.arguments = None
        assert _extract_arguments(ctx) is None


class TestExtractResult:
    def test_extracts_value(self):
        ctx = make_context(result_value="The answer.")
        assert _extract_result(ctx) == "The answer."

    def test_none_result(self):
        ctx = MagicMock()
        ctx.result = None
        assert _extract_result(ctx) is None


class TestInferSpanType:
    def test_llm_function(self):
        ctx = make_context(plugin="", name="complete_prompt")
        assert _infer_span_type(ctx) == SpanType.LLM

    def test_retrieval_function(self):
        ctx = make_context(plugin="", name="search_retrieve")
        assert _infer_span_type(ctx) == SpanType.RETRIEVAL

    def test_tool_function(self):
        ctx = make_context(plugin="", name="execute_tool")
        assert _infer_span_type(ctx) == SpanType.TOOL

    def test_agent_function(self):
        ctx = make_context(plugin="", name="run_agent")
        assert _infer_span_type(ctx) == SpanType.AGENT

    def test_default_chain(self):
        ctx = make_context(plugin="", name="format_output")
        assert _infer_span_type(ctx) == SpanType.CHAIN


class TestCaptureTokenUsage:
    def test_dict_usage(self):
        span = MagicMock()
        ctx = make_context(token_usage={"total_tokens": 42})
        _capture_token_usage(span, ctx)
        span.set_tokens.assert_called_once_with(42)

    def test_zero_dict_usage(self):
        span = MagicMock()
        ctx = make_context(token_usage={"total_tokens": 0})
        _capture_token_usage(span, ctx)
        span.set_tokens.assert_called_once_with(0)

    def test_object_usage(self):
        span = MagicMock()
        usage = MagicMock()
        usage.total_tokens = 100
        ctx = make_context()
        ctx.result.metadata = {"usage": usage}
        _capture_token_usage(span, ctx)
        span.set_tokens.assert_called_once_with(100)

    def test_no_usage_does_not_set_tokens(self):
        span = MagicMock()
        ctx = make_context(token_usage=None)
        _capture_token_usage(span, ctx)
        span.set_tokens.assert_not_called()

    def test_no_result_does_not_raise(self):
        span = MagicMock()
        ctx = MagicMock()
        ctx.result = None
        _capture_token_usage(span, ctx)  # should not raise


class TestSafeStr:
    def test_str_passthrough(self):
        assert _safe_str("hello") == "hello"

    def test_int_passthrough(self):
        assert _safe_str(42) == 42

    def test_none_passthrough(self):
        assert _safe_str(None) is None

    def test_object_converted(self):
        class Obj:
            def __str__(self):
                return "obj-str"
        assert _safe_str(Obj()) == "obj-str"


# ---------------------------------------------------------------------------
# VizpathKernelFilter tests
# ---------------------------------------------------------------------------

class TestVizpathKernelFilter:
    def test_uses_provided_tracer(self):
        mock_tracer = MagicMock()
        f = VizpathKernelFilter(tracer=mock_tracer)
        assert f._tracer is mock_tracer

    def test_call_creates_trace(self):
        async def run():
            f = VizpathKernelFilter()
            ctx = make_context()
            called = []

            async def next_fn(c):
                called.append(True)

            await f(ctx, next_fn)
            return called

        result = asyncio.get_event_loop().run_until_complete(run())
        assert result == [True]

    def test_call_invokes_next(self):
        async def run():
            f = VizpathKernelFilter()
            ctx = make_context()
            invoked = []

            async def next_fn(c):
                invoked.append(c)

            await f(ctx, next_fn)
            return invoked

        result = asyncio.get_event_loop().run_until_complete(run())
        assert len(result) == 1

    def test_call_ends_span_after_next(self):
        async def run():
            f = VizpathKernelFilter()
            ctx = make_context()

            async def next_fn(c):
                pass

            await f(ctx, next_fn)
            return f._spans

        spans = asyncio.get_event_loop().run_until_complete(run())
        assert len(spans) == 0  # span cleaned up after invocation

    def test_call_marks_error_on_exception(self):
        async def run():
            f = VizpathKernelFilter()
            ctx = make_context()

            async def failing_next(c):
                raise ValueError("SK error")

            try:
                await f(ctx, failing_next)
            except ValueError:
                pass
            return f._spans

        spans = asyncio.get_event_loop().run_until_complete(run())
        assert len(spans) == 0  # span cleaned up even on error

    def test_end_trace_clears_state(self):
        f = VizpathKernelFilter()
        f._get_or_create_trace("test")
        assert f._trace is not None
        f._end_trace()
        assert f._trace is None

    def test_trace_conversation_returns_context(self):
        f = VizpathKernelFilter()
        ctx = f.trace_conversation("chat")
        assert isinstance(ctx, _ConversationContext)

    @pytest.mark.asyncio
    async def test_conversation_context_opens_trace(self):
        f = VizpathKernelFilter()
        async with f.trace_conversation("my-chat") as returned_filter:
            assert returned_filter is f
            assert f._trace is not None
        assert f._trace is None


# ---------------------------------------------------------------------------
# SemanticKernelAdapter tests
# ---------------------------------------------------------------------------

class TestSemanticKernelAdapter:
    def test_uses_provided_tracer(self):
        mock_tracer = MagicMock()
        adapter = SemanticKernelAdapter(tracer=mock_tracer)
        assert adapter._tracer is mock_tracer

    def test_filter_is_none_before_attach(self):
        adapter = SemanticKernelAdapter()
        assert adapter.filter is None

    def test_attach_registers_filter_via_add_filter(self):
        mock_kernel = MagicMock()
        adapter = SemanticKernelAdapter()
        result = adapter.attach(mock_kernel)

        assert isinstance(result, VizpathKernelFilter)
        mock_kernel.add_filter.assert_called_once_with(
            "function_invocation", result
        )

    def test_attach_uses_list_append_for_legacy_kernel(self):
        """Kernels without add_filter use function_invocation_filters list."""
        mock_kernel = MagicMock(spec=["function_invocation_filters"])
        mock_kernel.function_invocation_filters = []
        adapter = SemanticKernelAdapter()
        result = adapter.attach(mock_kernel)
        assert result in mock_kernel.function_invocation_filters

    def test_attach_returns_filter(self):
        mock_kernel = MagicMock()
        adapter = SemanticKernelAdapter()
        filt = adapter.attach(mock_kernel)
        assert adapter.filter is filt
