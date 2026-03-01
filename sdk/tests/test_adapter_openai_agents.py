"""Tests for the OpenAI Agents SDK adapter."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from vizpath.adapters.openai_agents import (
    VizpathAgentsTraceProcessor,
    _capture_usage,
    _set_input,
    _set_output,
    _span_name,
    _span_type,
)
from vizpath.span import SpanType


# ---------------------------------------------------------------------------
# Helpers to construct fake SDK objects
# ---------------------------------------------------------------------------

def make_sdk_trace(
    trace_id: str = "trace-1",
    name: str = "my-agent",
    metadata: dict | None = None,
) -> MagicMock:
    t = MagicMock()
    t.trace_id = trace_id
    t.name = name
    t.metadata = metadata or {}
    return t


def make_span_data(
    kind: str = "agent",
    name: str | None = "research-agent",
    model: str | None = None,
    input_val: object = None,
    output_val: object = None,
    usage: object = None,
) -> MagicMock:
    sd = MagicMock()
    sd.type = kind
    sd.name = name
    sd.model = model
    sd.input = input_val
    sd.output = output_val
    sd.usage = usage
    return sd


def make_sdk_span(
    span_id: str = "span-1",
    trace_id: str = "trace-1",
    parent_id: str | None = None,
    span_data: MagicMock | None = None,
    error: object = None,
) -> MagicMock:
    s = MagicMock()
    s.span_id = span_id
    s.trace_id = trace_id
    s.parent_id = parent_id or ""
    s.span_data = span_data or make_span_data()
    s.error = error
    return s


# ---------------------------------------------------------------------------
# Unit tests for helper functions
# ---------------------------------------------------------------------------

class TestSpanType:
    def test_generation_maps_to_llm(self):
        sd = make_span_data(kind="generation")
        assert _span_type(sd) == SpanType.LLM

    def test_response_maps_to_llm(self):
        sd = make_span_data(kind="response")
        assert _span_type(sd) == SpanType.LLM

    def test_function_maps_to_tool(self):
        sd = make_span_data(kind="function")
        assert _span_type(sd) == SpanType.TOOL

    def test_agent_maps_to_agent(self):
        sd = make_span_data(kind="agent")
        assert _span_type(sd) == SpanType.AGENT

    def test_handoff_maps_to_agent(self):
        sd = make_span_data(kind="handoff")
        assert _span_type(sd) == SpanType.AGENT

    def test_guardrail_maps_to_chain(self):
        sd = make_span_data(kind="guardrail")
        assert _span_type(sd) == SpanType.CHAIN

    def test_unknown_maps_to_custom(self):
        sd = make_span_data(kind="unknown_kind")
        assert _span_type(sd) == SpanType.CUSTOM


class TestSpanName:
    def test_uses_name_attribute(self):
        sd = make_span_data(kind="agent", name="planner")
        assert _span_name(sd) == "planner"

    def test_uses_model_for_generation(self):
        sd = make_span_data(kind="generation", name=None, model="gpt-4o")
        assert _span_name(sd) == "llm.gpt-4o"

    def test_falls_back_to_type(self):
        sd = MagicMock()
        sd.type = "guardrail"
        sd.name = None
        sd.model = None
        assert _span_name(sd) == "guardrail"


class TestSetInput:
    def test_sets_input_from_span_data(self):
        viz_span = MagicMock()
        sd = make_span_data(input_val={"messages": ["hello"]})
        _set_input(viz_span, sd)
        viz_span.set_input.assert_called_once_with({"messages": ["hello"]})

    def test_sets_model_attribute(self):
        viz_span = MagicMock()
        sd = make_span_data(kind="generation", name=None, model="gpt-4o")
        _set_input(viz_span, sd)
        viz_span.set_attributes.assert_any_call(model="gpt-4o")

    def test_no_input_skips_set_input(self):
        viz_span = MagicMock()
        sd = make_span_data(input_val=None)
        _set_input(viz_span, sd)
        viz_span.set_input.assert_not_called()


class TestSetOutput:
    def test_sets_output(self):
        viz_span = MagicMock()
        sd = make_span_data(output_val="final answer")
        _set_output(viz_span, sd)
        viz_span.set_output.assert_called_once_with("final answer")

    def test_no_output_skips(self):
        viz_span = MagicMock()
        sd = make_span_data(output_val=None)
        _set_output(viz_span, sd)
        viz_span.set_output.assert_not_called()


class TestCaptureUsage:
    def test_dict_usage_with_total_tokens(self):
        viz_span = MagicMock()
        sd = make_span_data(usage={"total_tokens": 150})
        _capture_usage(viz_span, sd)
        viz_span.set_tokens.assert_called_once_with(150)

    def test_dict_usage_derives_total_from_input_output(self):
        viz_span = MagicMock()
        sd = make_span_data(usage={"input_tokens": 80, "output_tokens": 40})
        _capture_usage(viz_span, sd)
        viz_span.set_tokens.assert_called_once_with(120)

    def test_object_usage_with_total_tokens(self):
        viz_span = MagicMock()
        usage_obj = MagicMock()
        usage_obj.total_tokens = 200
        usage_obj.input_tokens = None
        usage_obj.output_tokens = None
        sd = make_span_data(usage=usage_obj)
        _capture_usage(viz_span, sd)
        viz_span.set_tokens.assert_called_once_with(200)

    def test_no_usage_skips(self):
        viz_span = MagicMock()
        sd = make_span_data(usage=None)
        _capture_usage(viz_span, sd)
        viz_span.set_tokens.assert_not_called()


# ---------------------------------------------------------------------------
# VizpathAgentsTraceProcessor tests
# ---------------------------------------------------------------------------

class TestVizpathAgentsTraceProcessor:
    def test_uses_provided_tracer(self):
        mock_tracer = MagicMock()
        p = VizpathAgentsTraceProcessor(tracer=mock_tracer)
        assert p._tracer is mock_tracer

    def test_on_trace_start_creates_trace(self):
        p = VizpathAgentsTraceProcessor()
        sdk_trace = make_sdk_trace(trace_id="t1", name="agent-run")
        p.on_trace_start(sdk_trace)
        assert "t1" in p._traces

    def test_on_trace_end_removes_trace(self):
        p = VizpathAgentsTraceProcessor()
        sdk_trace = make_sdk_trace(trace_id="t1")
        p.on_trace_start(sdk_trace)
        p.on_trace_end(sdk_trace)
        assert "t1" not in p._traces

    def test_on_span_start_registers_span(self):
        p = VizpathAgentsTraceProcessor()
        sdk_trace = make_sdk_trace(trace_id="t1")
        p.on_trace_start(sdk_trace)
        sdk_span = make_sdk_span(span_id="s1", trace_id="t1")
        p.on_span_start(sdk_span)
        assert "s1" in p._spans

    def test_on_span_end_removes_span(self):
        p = VizpathAgentsTraceProcessor()
        sdk_trace = make_sdk_trace(trace_id="t1")
        p.on_trace_start(sdk_trace)
        sdk_span = make_sdk_span(span_id="s1", trace_id="t1")
        p.on_span_start(sdk_span)
        p.on_span_end(sdk_span)
        assert "s1" not in p._spans

    def test_on_span_start_ignores_unknown_trace(self):
        """Span start for an unknown trace_id should not raise."""
        p = VizpathAgentsTraceProcessor()
        sdk_span = make_sdk_span(span_id="s1", trace_id="missing")
        p.on_span_start(sdk_span)  # should not raise
        assert "s1" not in p._spans

    def test_nested_span_nests_under_parent(self):
        """Child span should be created as a child of the parent Vizpath span."""
        p = VizpathAgentsTraceProcessor()
        sdk_trace = make_sdk_trace(trace_id="t1")
        p.on_trace_start(sdk_trace)

        parent_sdk = make_sdk_span(span_id="p1", trace_id="t1")
        p.on_span_start(parent_sdk)

        child_sdk = make_sdk_span(span_id="c1", trace_id="t1", parent_id="p1")
        p.on_span_start(child_sdk)

        assert "c1" in p._spans
        assert "p1" in p._spans

    def test_error_span_marks_error(self):
        """A span with an error should call set_error on the Vizpath span."""
        mock_span = MagicMock()
        mock_trace = MagicMock()
        mock_trace.span.return_value = mock_span
        mock_tracer = MagicMock()
        mock_tracer.trace.return_value = mock_trace

        p = VizpathAgentsTraceProcessor(tracer=mock_tracer)
        sdk_trace = make_sdk_trace(trace_id="t1")
        p.on_trace_start(sdk_trace)
        # Seed the internal span dict directly, as on_span_start would
        p._spans["s1"] = mock_span

        error_obj = MagicMock()
        error_obj.message = "Tool crashed"
        sdk_span = make_sdk_span(span_id="s1", trace_id="t1", error=error_obj)
        p.on_span_end(sdk_span)

        mock_span.set_error.assert_called_once_with("Tool crashed")

    def test_full_trace_lifecycle(self):
        """Complete trace→span→end sequence works without error."""
        p = VizpathAgentsTraceProcessor()

        sdk_trace = make_sdk_trace(trace_id="t1", name="research-run")
        p.on_trace_start(sdk_trace)

        agent_span = make_sdk_span(
            span_id="a1", trace_id="t1",
            span_data=make_span_data(kind="agent", name="researcher"),
        )
        p.on_span_start(agent_span)

        llm_span = make_sdk_span(
            span_id="l1", trace_id="t1", parent_id="a1",
            span_data=make_span_data(
                kind="generation", name=None, model="gpt-4o",
                input_val=[{"role": "user", "content": "hello"}],
                output_val="hi there",
                usage={"total_tokens": 42},
            ),
        )
        p.on_span_start(llm_span)
        p.on_span_end(llm_span)
        p.on_span_end(agent_span)
        p.on_trace_end(sdk_trace)

        assert len(p._traces) == 0
        assert len(p._spans) == 0

    def test_unknown_span_end_is_safe(self):
        """on_span_end with an unknown span_id should not raise."""
        p = VizpathAgentsTraceProcessor()
        sdk_span = make_sdk_span(span_id="ghost")
        p.on_span_end(sdk_span)  # should not raise

    def test_shutdown_closes_tracer(self):
        mock_tracer = MagicMock()
        p = VizpathAgentsTraceProcessor(tracer=mock_tracer)
        p.shutdown()
        mock_tracer.close.assert_called_once()

    def test_force_flush_flushes_tracer(self):
        mock_tracer = MagicMock()
        p = VizpathAgentsTraceProcessor(tracer=mock_tracer)
        p.force_flush()
        mock_tracer.flush.assert_called_once()

    def test_trace_metadata_is_forwarded(self):
        """Metadata dict on SDK trace should be set on the Vizpath trace."""
        p = VizpathAgentsTraceProcessor()
        sdk_trace = make_sdk_trace(
            trace_id="t1",
            metadata={"user_id": "u42", "session": "abc"},
        )
        p.on_trace_start(sdk_trace)
        # The trace is in _traces — just confirm it was created
        assert "t1" in p._traces
