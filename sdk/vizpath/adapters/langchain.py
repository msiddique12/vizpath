"""LangChain adapter for automatic tracing of chain executions."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional
from uuid import UUID

from vizpath.span import SpanType
from vizpath.tracer import Tracer

if TYPE_CHECKING:
    from langchain.callbacks.base import BaseCallbackHandler


class VizpathCallbackHandler:
    """
    LangChain callback handler for automatic tracing.

    Captures LLM calls, chain runs, tool usage, and retrieval operations.

    Usage:
        from vizpath.adapters.langchain import VizpathCallbackHandler

        handler = VizpathCallbackHandler(api_key="your-key")
        chain.invoke(input, config={"callbacks": [handler]})
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        tracer: Optional[Tracer] = None,
    ) -> None:
        self._tracer = tracer or Tracer(api_key=api_key, base_url=base_url)
        self._trace = None
        self._span_stack: List[Any] = []
        self._spans: Dict[str, Any] = {}

    def _get_or_create_trace(self, name: str = "langchain") -> Any:
        if self._trace is None:
            self._trace = self._tracer.trace(name)
            self._trace.__enter__()
        return self._trace

    def _end_trace(self) -> None:
        if self._trace is not None:
            self._trace.__exit__(None, None, None)
            self._trace = None
            self._spans.clear()
            self._span_stack.clear()

    def on_chain_start(
        self,
        serialized: Dict[str, Any],
        inputs: Dict[str, Any],
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> None:
        """Called when a chain starts running."""
        name = serialized.get("name", serialized.get("id", ["chain"])[-1])
        trace = self._get_or_create_trace(name)

        parent = self._spans.get(str(parent_run_id)) if parent_run_id else None
        if parent:
            span = parent.span(name, span_type=SpanType.CHAIN)
        else:
            span = trace.span(name, span_type=SpanType.CHAIN)

        span.set_input(inputs)
        span.__enter__()
        self._spans[str(run_id)] = span
        self._span_stack.append(span)

    def on_chain_end(
        self,
        outputs: Dict[str, Any],
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        """Called when a chain finishes."""
        span = self._spans.get(str(run_id))
        if span:
            span.set_output(outputs)
            span.__exit__(None, None, None)
            if self._span_stack and self._span_stack[-1] == span:
                self._span_stack.pop()

        if not self._span_stack:
            self._end_trace()

    def on_chain_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        """Called when a chain errors."""
        span = self._spans.get(str(run_id))
        if span:
            span.set_error(str(error))
            span.__exit__(type(error), error, None)
            if self._span_stack and self._span_stack[-1] == span:
                self._span_stack.pop()

        if not self._span_stack:
            self._end_trace()

    def on_llm_start(
        self,
        serialized: Dict[str, Any],
        prompts: List[str],
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> None:
        """Called when an LLM starts generating."""
        name = serialized.get("name", serialized.get("id", ["llm"])[-1])
        trace = self._get_or_create_trace()

        parent = self._spans.get(str(parent_run_id)) if parent_run_id else None
        if parent:
            span = parent.span(name, span_type=SpanType.LLM)
        else:
            span = trace.span(name, span_type=SpanType.LLM)

        span.set_input(prompts)
        span.set_attributes(model=serialized.get("kwargs", {}).get("model_name"))
        span.__enter__()
        self._spans[str(run_id)] = span

    def on_llm_end(
        self,
        response: Any,
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        """Called when an LLM finishes."""
        span = self._spans.get(str(run_id))
        if span:
            output = response.generations if hasattr(response, "generations") else str(response)
            span.set_output(output)

            if hasattr(response, "llm_output") and response.llm_output:
                usage = response.llm_output.get("token_usage", {})
                total_tokens = usage.get("total_tokens")
                if total_tokens:
                    span.set_tokens(total_tokens)

            span.__exit__(None, None, None)

    def on_llm_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        """Called when an LLM errors."""
        span = self._spans.get(str(run_id))
        if span:
            span.set_error(str(error))
            span.__exit__(type(error), error, None)

    def on_tool_start(
        self,
        serialized: Dict[str, Any],
        input_str: str,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> None:
        """Called when a tool starts running."""
        name = serialized.get("name", "tool")
        trace = self._get_or_create_trace()

        parent = self._spans.get(str(parent_run_id)) if parent_run_id else None
        if parent:
            span = parent.span(name, span_type=SpanType.TOOL)
        else:
            span = trace.span(name, span_type=SpanType.TOOL)

        span.set_input(input_str)
        span.__enter__()
        self._spans[str(run_id)] = span

    def on_tool_end(
        self,
        output: str,
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        """Called when a tool finishes."""
        span = self._spans.get(str(run_id))
        if span:
            span.set_output(output)
            span.__exit__(None, None, None)

    def on_tool_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        """Called when a tool errors."""
        span = self._spans.get(str(run_id))
        if span:
            span.set_error(str(error))
            span.__exit__(type(error), error, None)

    def on_retriever_start(
        self,
        serialized: Dict[str, Any],
        query: str,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> None:
        """Called when a retriever starts."""
        name = serialized.get("name", "retriever")
        trace = self._get_or_create_trace()

        parent = self._spans.get(str(parent_run_id)) if parent_run_id else None
        if parent:
            span = parent.span(name, span_type=SpanType.RETRIEVAL)
        else:
            span = trace.span(name, span_type=SpanType.RETRIEVAL)

        span.set_input(query)
        span.__enter__()
        self._spans[str(run_id)] = span

    def on_retriever_end(
        self,
        documents: List[Any],
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        """Called when a retriever finishes."""
        span = self._spans.get(str(run_id))
        if span:
            span.set_output({"document_count": len(documents)})
            span.set_attributes(document_count=len(documents))
            span.__exit__(None, None, None)

    def on_retriever_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        """Called when a retriever errors."""
        span = self._spans.get(str(run_id))
        if span:
            span.set_error(str(error))
            span.__exit__(type(error), error, None)
