"""Haystack adapter for automatic tracing of NLP pipeline executions."""

from __future__ import annotations

from typing import Any

from vizpath.span import SpanType
from vizpath.tracer import Tracer


class TracedPipeline:
    """
    A Haystack Pipeline wrapped with vizpath tracing.

    Intercepts run/run_async to trace each component execution.
    Unknown attribute access is forwarded to the underlying pipeline.
    """

    def __init__(self, pipeline: Any, tracer: Tracer) -> None:
        self._pipeline = pipeline
        self._tracer = tracer

    def run(
        self,
        data: dict[str, Any],
        include_outputs_from: set[str] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Run the Haystack pipeline synchronously with tracing."""
        pipeline_name = getattr(self._pipeline, "metadata", {}).get(
            "name", "haystack-pipeline"
        )
        with self._tracer.trace(pipeline_name) as trace:
            trace.set_metadata(framework="haystack")
            trace.span("pipeline.run", span_type=SpanType.CHAIN).__enter__()

            try:
                if include_outputs_from is not None:
                    result = self._pipeline.run(
                        data, include_outputs_from=include_outputs_from, **kwargs
                    )
                else:
                    result = self._pipeline.run(data, **kwargs)
            except Exception as e:
                # Let trace context manager handle error status
                raise

        return result

    async def run_async(
        self,
        data: dict[str, Any],
        include_outputs_from: set[str] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Run the Haystack pipeline asynchronously with tracing."""
        pipeline_name = getattr(self._pipeline, "metadata", {}).get(
            "name", "haystack-pipeline"
        )
        with self._tracer.trace(pipeline_name) as trace:
            trace.set_metadata(framework="haystack")
            if include_outputs_from is not None:
                result = await self._pipeline.run_async(
                    data, include_outputs_from=include_outputs_from, **kwargs
                )
            else:
                result = await self._pipeline.run_async(data, **kwargs)
        return result

    def __getattr__(self, name: str) -> Any:
        return getattr(self._pipeline, name)


class VizpathHaystackTracer:
    """
    Haystack-compatible tracer that records pipeline component spans.

    Implements the Haystack Tracer protocol so it can be registered as
    ``haystack.tracing.tracer`` for native tracing support.

    Usage (native Haystack tracing integration)::

        import haystack.tracing
        from vizpath.adapters.haystack import VizpathHaystackTracer

        haystack.tracing.tracer = VizpathHaystackTracer(api_key="your-key")

    Usage (explicit pipeline wrapping)::

        from vizpath.adapters.haystack import HaystackAdapter

        adapter = HaystackAdapter(api_key="your-key")
        traced = adapter.wrap(pipeline)
        result = traced.run({"query": {"text": "What is AI?"}})
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        tracer: Tracer | None = None,
    ) -> None:
        self._tracer = tracer or Tracer(api_key=api_key, base_url=base_url)
        self._trace: Any = None
        self._spans: dict[str, Any] = {}
        self._span_stack: list[Any] = []

    def _get_or_create_trace(self, name: str = "haystack") -> Any:
        if self._trace is None:
            self._trace = self._tracer.trace(name)
            self._trace.__enter__()
        return self._trace

    def _end_trace(self) -> None:
        for span in list(self._span_stack):
            try:
                span.__exit__(None, None, None)
            except Exception:
                pass
        self._span_stack.clear()
        self._spans.clear()
        if self._trace is not None:
            self._trace.__exit__(None, None, None)
            self._trace = None

    def trace_component(
        self,
        component_name: str,
        component_type: str | None = None,
        inputs: dict[str, Any] | None = None,
    ) -> str:
        """
        Start tracing a pipeline component.

        Args:
            component_name: Name of the component (e.g. "retriever", "llm").
            component_type: Optional type hint for span categorisation.
            inputs: Component input data.

        Returns:
            span_id: Identifier to pass to end_component.
        """
        trace = self._get_or_create_trace(f"haystack-{component_name}")

        # Determine span type from component type string
        span_type = _component_span_type(component_type or component_name)

        parent = self._span_stack[-1] if self._span_stack else None
        if parent:
            span = parent.span(component_name, span_type=span_type)
        else:
            span = trace.span(component_name, span_type=span_type)

        if inputs:
            span.set_input(inputs)
        if component_type:
            span.set_attributes(component_type=component_type)

        span.__enter__()
        span_id = f"{component_name}-{len(self._spans)}"
        self._spans[span_id] = span
        self._span_stack.append(span)
        return span_id

    def end_component(
        self,
        span_id: str,
        outputs: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        """
        Finish tracing a pipeline component.

        Args:
            span_id: Identifier returned by trace_component.
            outputs: Component output data.
            error: Error message if the component failed.
        """
        span = self._spans.pop(span_id, None)
        if span:
            if outputs:
                span.set_output(outputs)
            if error:
                span.set_error(error)
                span.__exit__(Exception, Exception(error), None)
            else:
                span.__exit__(None, None, None)
            if span in self._span_stack:
                self._span_stack.remove(span)

        if not self._span_stack:
            self._end_trace()

    # --- Haystack Tracer protocol methods ---

    def trace(
        self,
        operation_name: str,
        tags: dict[str, Any] | None = None,
        parent_span: Any | None = None,
    ) -> Any:
        """Create a Haystack-protocol span (returns a context manager)."""
        return _HaystackSpanContext(self, operation_name, tags or {}, parent_span)


def _component_span_type(hint: str) -> SpanType:
    """Map a Haystack component type/name to a Vizpath SpanType."""
    lower = hint.lower()
    if any(k in lower for k in ("llm", "generator", "chat")):
        return SpanType.LLM
    if any(k in lower for k in ("retriever", "retrieval", "embed", "bm25", "dense")):
        return SpanType.RETRIEVAL
    if any(k in lower for k in ("tool", "function", "action")):
        return SpanType.TOOL
    if any(k in lower for k in ("agent",)):
        return SpanType.AGENT
    return SpanType.CHAIN


class _HaystackSpanContext:
    """Minimal span context implementing the Haystack Span protocol."""

    def __init__(
        self,
        vizpath_tracer: VizpathHaystackTracer,
        operation_name: str,
        tags: dict[str, Any],
        parent_span: Any | None,
    ) -> None:
        self._vizpath_tracer = vizpath_tracer
        self._operation_name = operation_name
        self._tags = tags
        self._span_id: str | None = None

    def __enter__(self) -> "_HaystackSpanContext":
        component_type = self._tags.get("haystack.component.type")
        inputs = self._tags.get("haystack.component.input")
        self._span_id = self._vizpath_tracer.trace_component(
            self._operation_name,
            component_type=str(component_type) if component_type else None,
            inputs=inputs if isinstance(inputs, dict) else None,
        )
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        outputs = self._tags.get("haystack.component.output")
        error = str(exc_val) if exc_val else None
        if self._span_id:
            self._vizpath_tracer.end_component(
                self._span_id,
                outputs=outputs if isinstance(outputs, dict) else None,
                error=error,
            )

    def set_tag(self, key: str, value: Any) -> None:
        """Store tag for later use on span end."""
        self._tags[key] = value

    def set_content_tag(self, key: str, value: Any) -> None:
        """Alias for set_tag (Haystack content tagging)."""
        self._tags[key] = value

    def raw_span(self) -> Any:
        """Return the underlying vizpath span if available."""
        if self._span_id:
            return self._vizpath_tracer._spans.get(self._span_id)
        return None


class HaystackAdapter:
    """
    Adapter for Haystack that adds automatic tracing to a Pipeline.

    Usage:
        from vizpath.adapters.haystack import HaystackAdapter

        adapter = HaystackAdapter(api_key="your-key")
        traced = adapter.wrap(pipeline)
        result = traced.run({"retriever": {"query": "What is AI?"}})
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        tracer: Tracer | None = None,
    ) -> None:
        self._tracer = tracer or Tracer(api_key=api_key, base_url=base_url)

    def wrap(self, pipeline: Any) -> TracedPipeline:
        """Wrap a Haystack Pipeline to enable automatic tracing."""
        return TracedPipeline(pipeline, self._tracer)
