"""Decorator-based tracing API for vizpath.

This module provides a global tracer instance and decorator-based API
for tracing functions without explicit context management.

Usage:
    from vizpath import tracer

    @tracer.trace(name="my-task")
    def main_task():
        ...

    @tracer.span(name="sub-task", span_type="tool")
    def sub_task():
        tracer.set_span_attributes({"key": "value"})
        ...
"""

from __future__ import annotations

import contextvars
import functools
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, TypeVar

from vizpath.client import Client
from vizpath.config import Config
from vizpath.span import Span, SpanStatus, SpanType

T = TypeVar("T")

# Context variables for tracking current trace and span
_current_trace: contextvars.ContextVar[_TraceContext | None] = contextvars.ContextVar(
    "_current_trace", default=None
)
_current_span: contextvars.ContextVar[Span | None] = contextvars.ContextVar(
    "_current_span", default=None
)


class _TraceContext:
    """Internal trace context for decorator-based tracing.

    This class implements the interface expected by Span:
    - trace_id property
    - _register_span(span) method
    - _on_span_end(span) method
    """

    def __init__(self, trace_id: str, name: str, client: Client) -> None:
        self.trace_id = trace_id
        self.name = name
        self.client = client
        self.start_time = datetime.now(timezone.utc)
        self.attributes: dict[str, Any] = {}
        self.spans: list[Span] = []
        self.root_span: Span | None = None

    def _register_span(self, span: Span) -> None:
        """Register a span with this trace context."""
        self.spans.append(span)
        if self.root_span is None:
            self.root_span = span

    def _on_span_end(self, span: Span) -> None:
        """Called when a span ends - sends it to the server."""
        self.client.send(span.to_data())


class GlobalTracer:
    """Global tracer with decorator-based API.

    This class provides a singleton-like interface for tracing
    without explicitly passing tracer instances around.
    """

    def __init__(self) -> None:
        self._config: Config | None = None
        self._client: Client | None = None

    def configure(
        self,
        api_url: str | None = None,
        api_key: str | None = None,
        project_id: str | None = None,
    ) -> None:
        """Configure the global tracer.

        Args:
            api_url: The vizpath server URL.
            api_key: API key for authentication (optional).
            project_id: Project ID to associate traces with.
        """
        self._config = Config(
            base_url=api_url or "http://localhost:8000",
            api_key=api_key,
            project_id=project_id,
        )
        self._client = Client(self._config)

    def _ensure_configured(self) -> Client:
        """Ensure tracer is configured and return client."""
        if self._client is None:
            # Auto-configure with defaults
            self.configure()
        return self._client  # type: ignore

    def trace(
        self,
        name: str | None = None,
    ) -> Callable[[Callable[..., T]], Callable[..., T]]:
        """Decorator to create a new trace for a function.

        Args:
            name: Name for the trace. Defaults to function name.
        """
        def decorator(func: Callable[..., T]) -> Callable[..., T]:
            @functools.wraps(func)
            def wrapper(*args: Any, **kwargs: Any) -> T:
                trace_name = name or func.__name__
                client = self._ensure_configured()

                # Create trace context
                trace_id = str(uuid.uuid4())
                context = _TraceContext(trace_id, trace_name, client)

                # Set as current trace
                token = _current_trace.set(context)

                try:
                    result = func(*args, **kwargs)
                    return result
                except Exception as e:
                    context.attributes["error"] = str(e)
                    raise
                finally:
                    _current_trace.reset(token)

            return wrapper
        return decorator

    def span(
        self,
        name: str | None = None,
        span_type: str = "custom",
    ) -> Callable[[Callable[..., T]], Callable[..., T]]:
        """Decorator to create a span within the current trace.

        Args:
            name: Name for the span. Defaults to function name.
            span_type: Type of span (llm, tool, agent, custom).
        """
        def decorator(func: Callable[..., T]) -> Callable[..., T]:
            @functools.wraps(func)
            def wrapper(*args: Any, **kwargs: Any) -> T:
                span_name = name or func.__name__
                trace_ctx = _current_trace.get()

                if trace_ctx is None:
                    # No active trace, just run function
                    return func(*args, **kwargs)

                # Map string span_type to SpanType enum
                st = SpanType(span_type) if span_type in [e.value for e in SpanType] else SpanType.CUSTOM

                # Get parent span if any
                parent = _current_span.get()

                # Create span
                span = Span(
                    name=span_name,
                    trace_context=trace_ctx,  # type: ignore
                    parent=parent,
                    span_type=st,
                )
                trace_ctx._register_span(span)

                # Set as current span
                span_token = _current_span.set(span)

                try:
                    span.__enter__()
                    result = func(*args, **kwargs)
                    span.__exit__(None, None, None)
                    return result
                except Exception as e:
                    span.set_error(str(e))
                    span.__exit__(type(e), e, e.__traceback__)
                    raise
                finally:
                    _current_span.reset(span_token)

            return wrapper
        return decorator

    def tool(
        self,
        name: str | None = None,
    ) -> Callable[[Callable[..., T]], Callable[..., T]]:
        """Decorator for tool functions. Shorthand for span(span_type="tool")."""
        return self.span(name=name, span_type="tool")

    def llm(
        self,
        name: str | None = None,
    ) -> Callable[[Callable[..., T]], Callable[..., T]]:
        """Decorator for LLM calls. Shorthand for span(span_type="llm")."""
        return self.span(name=name, span_type="llm")

    def set_span_attributes(self, attributes: dict[str, Any]) -> None:
        """Set attributes on the current span."""
        span = _current_span.get()
        if span is not None:
            span.set_attributes(**attributes)

    def set_span_tokens(
        self,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
    ) -> None:
        """Set token counts on the current span."""
        span = _current_span.get()
        if span is not None:
            total = (prompt_tokens or 0) + (completion_tokens or 0)
            span.set_attributes(
                **{
                    "tokens.prompt": prompt_tokens,
                    "tokens.completion": completion_tokens,
                    "tokens.total": total,
                }
            )
            span._tokens = total

    def set_span_cost(self, cost: float) -> None:
        """Set cost on the current span."""
        span = _current_span.get()
        if span is not None:
            span.set_attributes(cost=cost)
            span._cost = cost

    def set_trace_attributes(self, attributes: dict[str, Any]) -> None:
        """Set attributes on the current trace."""
        trace_ctx = _current_trace.get()
        if trace_ctx is not None:
            trace_ctx.attributes.update(attributes)


# Global tracer instance
tracer = GlobalTracer()


def configure(
    api_url: str | None = None,
    api_key: str | None = None,
    project_id: str | None = None,
) -> None:
    """Configure the global tracer.

    This is a convenience function that calls tracer.configure().
    """
    tracer.configure(api_url=api_url, api_key=api_key, project_id=project_id)
