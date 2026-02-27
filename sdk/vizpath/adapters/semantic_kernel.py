"""Semantic Kernel adapter for automatic tracing of kernel function invocations."""

from __future__ import annotations

from typing import Any, Callable, Awaitable

from vizpath.span import SpanType
from vizpath.tracer import Tracer


class VizpathKernelFilter:
    """
    Semantic Kernel function invocation filter for automatic tracing.

    Hooks into every kernel function call to record inputs, outputs,
    LLM token usage, and errors as Vizpath spans.

    Usage (Semantic Kernel 1.x)::

        from semantic_kernel import Kernel
        from vizpath.adapters.semantic_kernel import VizpathKernelFilter

        kernel = Kernel()
        viz_filter = VizpathKernelFilter(api_key="your-key")
        kernel.add_filter("function_invocation", viz_filter)

        # All kernel function calls are now automatically traced
        result = await kernel.invoke(my_function, input="Hello")

    Usage (explicit context manager for a single conversation)::

        async with VizpathKernelFilter(api_key="your-key").trace_conversation("chat") as f:
            kernel.add_filter("function_invocation", f)
            result = await kernel.invoke(...)
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
        self._call_count: int = 0

    def _get_or_create_trace(self, name: str = "semantic-kernel") -> Any:
        if self._trace is None:
            self._trace = self._tracer.trace(name)
            self._trace.__enter__()
        return self._trace

    def _end_trace(self) -> None:
        for span in list(self._spans.values()):
            try:
                span.__exit__(None, None, None)
            except Exception:
                pass
        self._spans.clear()
        if self._trace is not None:
            self._trace.__exit__(None, None, None)
            self._trace = None

    async def __call__(
        self,
        context: Any,
        next: Callable[[Any], Awaitable[None]],
    ) -> None:
        """
        Semantic Kernel filter entry point.

        Compatible with SK 1.x ``kernel.add_filter("function_invocation", ...)``.
        """
        function_name = _extract_function_name(context)
        span_type = _infer_span_type(context)

        trace = self._get_or_create_trace(f"sk-{function_name}")
        self._call_count += 1
        span_id = f"{function_name}-{self._call_count}"

        span = trace.span(function_name, span_type=span_type)
        span.set_input(_extract_arguments(context))
        _set_function_metadata(span, context)
        span.__enter__()
        self._spans[span_id] = span

        try:
            await next(context)
        except Exception as e:
            span.set_error(str(e))
            span.__exit__(type(e), e, None)
            self._spans.pop(span_id, None)
            raise
        else:
            span.set_output(_extract_result(context))
            _capture_token_usage(span, context)
            span.__exit__(None, None, None)
            self._spans.pop(span_id, None)

    def trace_conversation(self, name: str = "sk-conversation") -> "_ConversationContext":
        """
        Return a context manager that scopes a single multi-turn trace.

        Usage::

            async with filter.trace_conversation("chat") as f:
                kernel.add_filter("function_invocation", f)
                await kernel.invoke(...)
        """
        return _ConversationContext(self, name)


class _ConversationContext:
    """Context manager that opens/closes a named trace around kernel operations."""

    def __init__(self, viz_filter: VizpathKernelFilter, name: str) -> None:
        self._filter = viz_filter
        self._name = name

    async def __aenter__(self) -> VizpathKernelFilter:
        self._filter._get_or_create_trace(self._name)
        return self._filter

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self._filter._end_trace()


class SemanticKernelAdapter:
    """
    Adapter that registers a VizpathKernelFilter on an existing Semantic Kernel.

    Usage::

        from semantic_kernel import Kernel
        from vizpath.adapters.semantic_kernel import SemanticKernelAdapter

        kernel = Kernel()
        adapter = SemanticKernelAdapter(api_key="your-key")
        adapter.attach(kernel)

        result = await kernel.invoke(my_function, input="Hello")
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        tracer: Tracer | None = None,
    ) -> None:
        self._tracer = tracer or Tracer(api_key=api_key, base_url=base_url)
        self._filter: VizpathKernelFilter | None = None

    def attach(self, kernel: Any) -> VizpathKernelFilter:
        """
        Register a VizpathKernelFilter on the kernel and return it.

        Args:
            kernel: A ``semantic_kernel.Kernel`` instance.

        Returns:
            The registered VizpathKernelFilter.
        """
        self._filter = VizpathKernelFilter(tracer=self._tracer)
        # SK 1.x API: kernel.add_filter(filter_type, filter_callable)
        if hasattr(kernel, "add_filter"):
            kernel.add_filter("function_invocation", self._filter)
        # SK 0.x API: kernel.function_invocation_filters
        elif hasattr(kernel, "function_invocation_filters"):
            kernel.function_invocation_filters.append(self._filter)
        return self._filter

    @property
    def filter(self) -> VizpathKernelFilter | None:
        """Return the attached filter (None if attach() not yet called)."""
        return self._filter


# ---------------------------------------------------------------------------
# Helpers for extracting SK context data without hard-importing SK types
# ---------------------------------------------------------------------------

def _extract_function_name(context: Any) -> str:
    """Best-effort function name from an SK FunctionInvocationContext."""
    try:
        func = getattr(context, "function", None)
        if func is not None:
            plugin = getattr(func, "plugin_name", "") or ""
            name = getattr(func, "name", "") or "function"
            return f"{plugin}.{name}" if plugin else name
    except Exception:
        pass
    return "sk-function"


def _extract_arguments(context: Any) -> dict[str, Any] | None:
    """Extract kernel arguments from context."""
    try:
        args = getattr(context, "arguments", None)
        if args is None:
            return None
        # KernelArguments is dict-like in SK 1.x
        if hasattr(args, "items"):
            return {k: _safe_str(v) for k, v in args.items()}
        return str(args)
    except Exception:
        return None


def _extract_result(context: Any) -> Any:
    """Extract the function result from context."""
    try:
        result = getattr(context, "result", None)
        if result is None:
            return None
        # FunctionResult has a .value property
        value = getattr(result, "value", result)
        return _safe_str(value)
    except Exception:
        return None


def _set_function_metadata(span: Any, context: Any) -> None:
    """Attach plugin/function metadata to a span."""
    try:
        func = getattr(context, "function", None)
        if func is None:
            return
        attrs: dict[str, Any] = {}
        if getattr(func, "plugin_name", None):
            attrs["plugin"] = func.plugin_name
        if getattr(func, "name", None):
            attrs["function"] = func.name
        if getattr(func, "description", None):
            attrs["description"] = str(func.description)[:200]
        if attrs:
            span.set_attributes(**attrs)
    except Exception:
        pass


def _infer_span_type(context: Any) -> SpanType:
    """Infer span type from the function being called."""
    name = _extract_function_name(context).lower()
    if any(k in name for k in ("llm", "chat", "complete", "prompt", "gpt", "claude")):
        return SpanType.LLM
    if any(k in name for k in ("search", "retrieve", "embed", "retrieval")):
        return SpanType.RETRIEVAL
    if any(k in name for k in ("tool", "action", "execute")):
        return SpanType.TOOL
    if any(k in name for k in ("agent", "planner", "plan")):
        return SpanType.AGENT
    return SpanType.CHAIN


def _capture_token_usage(span: Any, context: Any) -> None:
    """Extract token usage from SK result metadata if available."""
    try:
        result = getattr(context, "result", None)
        if result is None:
            return
        metadata = getattr(result, "metadata", None) or {}
        usage = metadata.get("usage")
        if usage is None:
            return
        # OpenAI-style usage dict or object
        if hasattr(usage, "total_tokens"):
            span.set_tokens(usage.total_tokens)
        elif isinstance(usage, dict):
            total = usage.get("total_tokens")
            if total:
                span.set_tokens(int(total))
    except Exception:
        pass


def _safe_str(value: Any) -> Any:
    """Convert a value to a JSON-serialisable type if possible."""
    if value is None or isinstance(value, (str, int, float, bool, dict, list)):
        return value
    try:
        return str(value)[:2000]
    except Exception:
        return "<unserializable>"
