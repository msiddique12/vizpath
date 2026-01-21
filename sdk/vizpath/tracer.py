"""Core tracer implementation for vizpath."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Callable, TypeVar

from pydantic import BaseModel, Field

from vizpath.client import Client
from vizpath.config import Config
from vizpath.span import Span, SpanStatus, SpanType

T = TypeVar("T")


class TraceData(BaseModel):
    """Serializable trace data for API transmission."""

    trace_id: str
    name: str
    status: SpanStatus = SpanStatus.RUNNING
    start_time: datetime
    end_time: datetime | None = None
    duration_ms: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    root_span_id: str | None = None
    span_count: int = 0
    error_count: int = 0
    total_tokens: int | None = None
    total_cost: float | None = None


class TraceContext:
    """
    Context object that tracks spans within a single trace.

    This is the internal representation passed to spans for registration
    and lifecycle management.
    """

    def __init__(self, trace_id: str, name: str, client: Client) -> None:
        self._trace_id = trace_id
        self._name = name
        self._client = client
        self._spans: list[Span] = []
        self._root_span: Span | None = None
        self._start_time = datetime.now(timezone.utc)
        self._end_time: datetime | None = None
        self._metadata: dict[str, Any] = {}
        self._status = SpanStatus.RUNNING

    @property
    def trace_id(self) -> str:
        return self._trace_id

    def _register_span(self, span: Span) -> None:
        """Register a span with this trace context."""
        self._spans.append(span)
        if self._root_span is None:
            self._root_span = span

    def _on_span_end(self, span: Span) -> None:
        """Called when a span ends - sends it to the server."""
        self._client.send(span.to_data())


class Trace:
    """
    Represents a complete execution trace.

    Use as a context manager to automatically handle lifecycle:

        with tracer.trace("my-task") as trace:
            with trace.span("step-1") as span:
                ...
    """

    def __init__(self, context: TraceContext) -> None:
        self._context = context

    @property
    def trace_id(self) -> str:
        return self._context.trace_id

    def span(
        self,
        name: str,
        span_type: SpanType = SpanType.CUSTOM,
    ) -> Span:
        """Create a root-level span within this trace."""
        span = Span(
            name=name,
            trace_context=self._context,
            parent=None,
            span_type=span_type,
        )
        self._context._register_span(span)
        return span

    def set_metadata(self, **kwargs: Any) -> Trace:
        """Set metadata on this trace."""
        self._context._metadata.update(kwargs)
        return self

    def end(self, status: SpanStatus | None = None) -> None:
        """End this trace."""
        self._context._end_time = datetime.now(timezone.utc)
        if status:
            self._context._status = status
        elif self._context._status == SpanStatus.RUNNING:
            has_errors = any(s._status == SpanStatus.ERROR for s in self._context._spans)
            self._context._status = SpanStatus.ERROR if has_errors else SpanStatus.SUCCESS

    def __enter__(self) -> Trace:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if exc_val is not None:
            self._context._status = SpanStatus.ERROR
        self.end()


class Tracer:
    """
    Main entry point for tracing agent executions.

    Initialize with an API key and use to create traces:

        tracer = Tracer(api_key="your-key")

        with tracer.trace("research-task") as trace:
            with trace.span("search", span_type=SpanType.TOOL) as span:
                result = search(query)
                span.set_output(result)
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        config: Config | None = None,
    ) -> None:
        if config:
            self._config = config
        else:
            self._config = Config(
                api_key=api_key,
                base_url=base_url if base_url else Config().base_url,
            )

        self._client = Client(self._config)

    def trace(self, name: str) -> Trace:
        """Create a new trace with the given name."""
        trace_id = str(uuid.uuid4())
        context = TraceContext(
            trace_id=trace_id,
            name=name,
            client=self._client,
        )
        return Trace(context)

    def flush(self) -> None:
        """Force flush all pending spans to the server."""
        self._client._flush()

    def close(self) -> None:
        """Shutdown the tracer and flush remaining data."""
        self._client.close()

    def __enter__(self) -> Tracer:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


def trace(name: str) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """
    Decorator to trace a function execution.

    Requires a global tracer to be configured:

        @trace("my-function")
        def my_function():
            ...
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        def wrapper(*args: Any, **kwargs: Any) -> T:
            return func(*args, **kwargs)
        return wrapper
    return decorator
