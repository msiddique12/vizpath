"""OpenAI Agents SDK adapter for automatic tracing of agent runs."""

from __future__ import annotations

import uuid
from typing import Any

from vizpath.span import SpanType
from vizpath.tracer import Tracer

# Span type classification by the span_data.type string used by the SDK
_SPAN_TYPE_MAP: dict[str, SpanType] = {
    "generation": SpanType.LLM,
    "response": SpanType.LLM,
    "function": SpanType.TOOL,
    "agent": SpanType.AGENT,
    "handoff": SpanType.AGENT,
    "guardrail": SpanType.CHAIN,
    "custom": SpanType.CUSTOM,
}


def _span_type(span_data: Any) -> SpanType:
    kind = getattr(span_data, "type", "") or ""
    return _SPAN_TYPE_MAP.get(kind, SpanType.CUSTOM)


def _span_name(span_data: Any) -> str:
    """Derive a human-readable name from an OpenAI Agents span_data object."""
    kind = getattr(span_data, "type", "") or "span"
    # function/tool spans expose a .name attribute
    name = getattr(span_data, "name", None)
    if name:
        return str(name)
    # agent spans have a .name too; generation spans use model
    model = getattr(span_data, "model", None)
    if model:
        return f"llm.{model}"
    return kind


def _set_input(span: Any, span_data: Any) -> None:
    """Copy span_data input fields onto a Vizpath span."""
    # GenerationSpanData: .input (list of messages)
    # FunctionSpanData: .input (str / dict)
    inp = getattr(span_data, "input", None)
    if inp is not None:
        span.set_input(inp)

    model = getattr(span_data, "model", None)
    if model:
        span.set_attributes(model=str(model))

    func_name = getattr(span_data, "name", None)
    if func_name and getattr(span_data, "type", "") in ("function", "agent", "handoff"):
        span.set_attributes(name=str(func_name))


def _set_output(span: Any, span_data: Any) -> None:
    """Copy span_data output fields onto a Vizpath span."""
    out = getattr(span_data, "output", None)
    if out is not None:
        out_str = str(out)[:2000] if not isinstance(out, (dict, list)) else out
        span.set_output(out_str)


def _capture_usage(span: Any, span_data: Any) -> None:
    """Extract token usage from a generation or response span."""
    usage = getattr(span_data, "usage", None)
    if usage is None:
        return
    if isinstance(usage, dict):
        total = usage.get("total_tokens") or (
            (usage.get("input_tokens") or 0) + (usage.get("output_tokens") or 0)
        )
        if total:
            span.set_tokens(int(total))
    else:
        total = getattr(usage, "total_tokens", None) or (
            (getattr(usage, "input_tokens", 0) or 0)
            + (getattr(usage, "output_tokens", 0) or 0)
        )
        if total:
            span.set_tokens(int(total))


class VizpathAgentsTraceProcessor:
    """
    OpenAI Agents SDK trace processor that forwards agent runs to Vizpath.

    Implements the ``TracingProcessor`` protocol used by the openai-agents
    package so it can be registered via ``agents.add_trace_processor()``.
    No hard dependency on the openai-agents package is required.

    Usage::

        import openai.agents as agents
        from vizpath.adapters.openai_agents import VizpathAgentsTraceProcessor

        processor = VizpathAgentsTraceProcessor(api_key="your-key")
        agents.add_trace_processor(processor)

        # All agent runs are now automatically traced
        result = await agents.Runner.run(my_agent, "What is AI?")

    Each SDK ``Trace`` maps to a Vizpath trace.  Each SDK ``Span`` maps to a
    Vizpath span with the appropriate SpanType (LLM, TOOL, AGENT, etc.).
    Parent–child relationships are preserved using the span's ``parent_id``.
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        tracer: Tracer | None = None,
    ) -> None:
        self._tracer = tracer or Tracer(api_key=api_key, base_url=base_url)
        # trace_id (str) -> Vizpath Trace
        self._traces: dict[str, Any] = {}
        # span_id (str) -> Vizpath Span
        self._spans: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # TracingProcessor protocol
    # ------------------------------------------------------------------

    def on_trace_start(self, trace: Any) -> None:
        """Called by the SDK when a new agent run begins."""
        trace_id = str(getattr(trace, "trace_id", None) or uuid.uuid4())
        name = str(getattr(trace, "name", None) or "openai-agents")

        viz_trace = self._tracer.trace(name)
        viz_trace.__enter__()
        viz_trace.set_metadata(
            framework="openai-agents",
            sdk_trace_id=trace_id,
        )

        metadata = getattr(trace, "metadata", None)
        if isinstance(metadata, dict) and metadata:
            viz_trace.set_metadata(**{k: str(v) for k, v in metadata.items()})

        self._traces[trace_id] = viz_trace

    def on_trace_end(self, trace: Any) -> None:
        """Called by the SDK when an agent run completes."""
        trace_id = str(getattr(trace, "trace_id", None) or "")
        viz_trace = self._traces.pop(trace_id, None)
        if viz_trace:
            viz_trace.__exit__(None, None, None)

    def on_span_start(self, span: Any) -> None:
        """Called by the SDK when a span begins."""
        span_id = str(getattr(span, "span_id", None) or uuid.uuid4())
        trace_id = str(getattr(span, "trace_id", None) or "")
        parent_id = str(getattr(span, "parent_id", None) or "")

        viz_trace = self._traces.get(trace_id)
        if viz_trace is None:
            return

        span_data = getattr(span, "span_data", None)
        name = _span_name(span_data)
        stype = _span_type(span_data)

        parent_span = self._spans.get(parent_id) if parent_id else None
        if parent_span:
            viz_span = parent_span.span(name, span_type=stype)
        else:
            viz_span = viz_trace.span(name, span_type=stype)

        if span_data:
            _set_input(viz_span, span_data)

        viz_span.__enter__()
        self._spans[span_id] = viz_span

    def on_span_end(self, span: Any) -> None:
        """Called by the SDK when a span completes."""
        span_id = str(getattr(span, "span_id", None) or "")
        viz_span = self._spans.pop(span_id, None)
        if viz_span is None:
            return

        span_data = getattr(span, "span_data", None)
        if span_data:
            _set_output(viz_span, span_data)
            _capture_usage(viz_span, span_data)

        error = getattr(span, "error", None)
        if error:
            msg = getattr(error, "message", None) or str(error)
            viz_span.set_error(str(msg))
            viz_span.__exit__(Exception, Exception(str(msg)), None)
        else:
            viz_span.__exit__(None, None, None)

    def shutdown(self) -> None:
        """Called when the SDK shuts down. Flushes and closes the tracer."""
        self._tracer.close()

    def force_flush(self, timeout_millis: int = 30_000) -> None:
        """Force-flush all buffered spans to the server."""
        self._tracer.flush()
