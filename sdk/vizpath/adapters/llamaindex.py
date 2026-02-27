"""LlamaIndex adapter for automatic tracing of query and retrieval pipelines."""

from __future__ import annotations

from typing import Any, Optional

from vizpath.span import SpanType
from vizpath.tracer import Tracer

# Attempt to import LlamaIndex callback types
try:
    from llama_index.core.callbacks.base_handler import BaseCallbackHandler
    from llama_index.core.callbacks.schema import CBEventType
    _LLAMA_AVAILABLE = True
except ImportError:
    try:
        from llama_index.callbacks.base_handler import BaseCallbackHandler  # type: ignore[no-redef]
        from llama_index.callbacks.schema import CBEventType  # type: ignore[no-redef]
        _LLAMA_AVAILABLE = True
    except ImportError:
        _LLAMA_AVAILABLE = False

        class BaseCallbackHandler:  # type: ignore[no-redef]
            """Fallback base class when LlamaIndex is not installed."""

            event_starts_to_ignore: list = []
            event_ends_to_ignore: list = []

            def __init__(
                self,
                event_starts_to_ignore: list | None = None,
                event_ends_to_ignore: list | None = None,
            ) -> None:
                self.event_starts_to_ignore = event_starts_to_ignore or []
                self.event_ends_to_ignore = event_ends_to_ignore or []

        class CBEventType:  # type: ignore[no-redef]
            """Fallback CBEventType when LlamaIndex is not installed."""

            LLM = "llm"
            QUERY = "query"
            RETRIEVE = "retrieve"
            EMBEDDING = "embedding"
            CHUNKING = "chunking"
            NODE_PARSING = "node_parsing"
            FUNCTION_CALL = "function_call"
            RERANKING = "reranking"
            SYNTHESIZE = "synthesize"
            AGENT_STEP = "agent_step"
            SUB_QUESTION = "sub_question"


# Map LlamaIndex event types to Vizpath span types
_EVENT_TO_SPAN_TYPE: dict[str, SpanType] = {
    "llm": SpanType.LLM,
    "query": SpanType.CHAIN,
    "retrieve": SpanType.RETRIEVAL,
    "embedding": SpanType.RETRIEVAL,
    "function_call": SpanType.TOOL,
    "agent_step": SpanType.AGENT,
    "synthesize": SpanType.CHAIN,
    "reranking": SpanType.RETRIEVAL,
    "sub_question": SpanType.CHAIN,
    "chunking": SpanType.CUSTOM,
    "node_parsing": SpanType.CUSTOM,
}


class VizpathLlamaIndexCallback(BaseCallbackHandler):  # type: ignore[misc]
    """
    LlamaIndex callback handler for automatic tracing.

    Captures LLM calls, query pipelines, retrieval, embedding, and agent steps.

    Usage:
        from llama_index.core import Settings
        from llama_index.core.callbacks import CallbackManager
        from vizpath.adapters.llamaindex import VizpathLlamaIndexCallback

        handler = VizpathLlamaIndexCallback(api_key="your-key")
        Settings.callback_manager = CallbackManager([handler])

        # Queries are now automatically traced
        response = index.query("What is reinforcement learning?")
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        tracer: Tracer | None = None,
        event_starts_to_ignore: list | None = None,
        event_ends_to_ignore: list | None = None,
    ) -> None:
        super().__init__(
            event_starts_to_ignore=event_starts_to_ignore or [],
            event_ends_to_ignore=event_ends_to_ignore or [],
        )
        self._tracer = tracer or Tracer(api_key=api_key, base_url=base_url)
        self._trace: Any = None
        self._spans: dict[str, Any] = {}
        self._root_event_id: str | None = None

    def _get_or_create_trace(self, name: str = "llamaindex") -> Any:
        if self._trace is None:
            self._trace = self._tracer.trace(name)
            self._trace.__enter__()
        return self._trace

    def _close_all_spans(self) -> None:
        for span in list(self._spans.values()):
            try:
                span.__exit__(None, None, None)
            except Exception:
                pass
        self._spans.clear()

    def _end_trace_context(self) -> None:
        self._close_all_spans()
        if self._trace is not None:
            self._trace.__exit__(None, None, None)
            self._trace = None
        self._root_event_id = None

    def on_event_start(
        self,
        event_type: Any,
        payload: dict[str, Any] | None = None,
        event_id: str = "",
        parent_id: str = "",
        **kwargs: Any,
    ) -> str:
        """Called when a traced event starts. Returns the event_id."""
        event_str = event_type.value if hasattr(event_type, "value") else str(event_type)
        span_type = _EVENT_TO_SPAN_TYPE.get(event_str, SpanType.CUSTOM)

        trace = self._get_or_create_trace(f"llamaindex-{event_str}")

        # Track root event for trace lifecycle
        if self._root_event_id is None:
            self._root_event_id = event_id
            trace.set_metadata(framework="llamaindex", root_event=event_str)

        # Nest span under parent if present
        parent = self._spans.get(parent_id) if parent_id else None
        if parent:
            span = parent.span(event_str, span_type=span_type)
        else:
            span = trace.span(event_str, span_type=span_type)

        if payload:
            span.set_input(payload)

            if event_str == "llm":
                model = payload.get("model") or (
                    payload.get("serialized", {}) or {}
                ).get("model_name")
                if model:
                    span.set_attributes(model=str(model))

            elif event_str in ("query", "retrieve"):
                query = payload.get("query_str") or payload.get("query")
                if query:
                    span.set_attributes(query=str(query)[:500])

            elif event_str == "function_call":
                func_name = payload.get("function_name") or payload.get("tool_name")
                if func_name:
                    span.set_attributes(function=str(func_name))

        span.__enter__()
        self._spans[event_id] = span
        return event_id

    def on_event_end(
        self,
        event_type: Any,
        payload: dict[str, Any] | None = None,
        event_id: str = "",
        **kwargs: Any,
    ) -> None:
        """Called when a traced event ends."""
        event_str = event_type.value if hasattr(event_type, "value") else str(event_type)
        span = self._spans.pop(event_id, None)

        if span and payload:
            if event_str == "llm":
                response = payload.get("response")
                if response is not None:
                    text = getattr(response, "text", None) or str(response)
                    span.set_output(text[:2000])
                usage = payload.get("usage")
                if usage is not None:
                    total = getattr(usage, "total_tokens", None)
                    if total:
                        span.set_tokens(int(total))

            elif event_str == "retrieve":
                nodes = payload.get("nodes", [])
                span.set_output({"document_count": len(nodes)})
                span.set_attributes(document_count=len(nodes))

            elif event_str == "embedding":
                chunks = payload.get("chunks", [])
                span.set_attributes(chunk_count=len(chunks))
                span.set_output({"chunk_count": len(chunks)})

            else:
                span.set_output(payload)

        if span:
            span.__exit__(None, None, None)

        # End trace when the root event closes
        if event_id == self._root_event_id:
            self._end_trace_context()

    def start_trace(self, trace_id: str | None = None) -> None:
        """Called by LlamaIndex's CallbackManager at trace start (no-op here)."""

    def end_trace(
        self,
        trace_id: str | None = None,
        trace_map: dict[str, list[str]] | None = None,
    ) -> None:
        """Called by LlamaIndex's CallbackManager at trace end."""
        if self._trace is not None:
            self._end_trace_context()
