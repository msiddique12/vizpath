"""LangGraph adapter for automatic tracing of graph executions."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Dict, Optional

from vizpath.span import SpanType
from vizpath.tracer import Tracer

if TYPE_CHECKING:
    from langgraph.graph import CompiledGraph


class LangGraphAdapter:
    """
    Adapter for tracing LangGraph executions.

    Wraps a LangGraph compiled graph to automatically trace node executions,
    tool calls, and LLM invocations.

    Usage:
        from vizpath.adapters import LangGraphAdapter

        adapter = LangGraphAdapter(api_key="your-key")
        traced_app = adapter.wrap(your_graph)
        result = traced_app.invoke({"input": "hello"})
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        tracer: Optional[Tracer] = None,
    ) -> None:
        self._tracer = tracer or Tracer(api_key=api_key, base_url=base_url)

    def wrap(self, graph: CompiledGraph) -> TracedGraph:
        """Wrap a compiled LangGraph for tracing."""
        return TracedGraph(graph, self._tracer)


class TracedGraph:
    """Wrapper around a LangGraph that traces all executions."""

    def __init__(self, graph: CompiledGraph, tracer: Tracer) -> None:
        self._graph = graph
        self._tracer = tracer

    def invoke(
        self,
        input: Dict[str, Any],
        config: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """
        Invoke the graph with tracing.

        Creates a trace for the entire invocation and spans for each node.
        """
        trace_name = config.get("run_name", "langgraph") if config else "langgraph"

        with self._tracer.trace(trace_name) as trace:
            trace.set_metadata(framework="langgraph", input_keys=list(input.keys()))

            original_invoke = self._graph.invoke

            def traced_invoke(inp: Dict[str, Any], cfg: Optional[Dict[str, Any]] = None, **kw: Any) -> Dict[str, Any]:
                return original_invoke(inp, cfg, **kw)

            result = traced_invoke(input, config, **kwargs)

            return result

    async def ainvoke(
        self,
        input: Dict[str, Any],
        config: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Async version of invoke with tracing."""
        trace_name = config.get("run_name", "langgraph") if config else "langgraph"

        with self._tracer.trace(trace_name) as trace:
            trace.set_metadata(framework="langgraph", input_keys=list(input.keys()))

            result = await self._graph.ainvoke(input, config, **kwargs)

            return result

    def stream(
        self,
        input: Dict[str, Any],
        config: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ):
        """Stream graph execution with tracing."""
        trace_name = config.get("run_name", "langgraph-stream") if config else "langgraph-stream"

        with self._tracer.trace(trace_name) as trace:
            trace.set_metadata(framework="langgraph", mode="stream")

            for chunk in self._graph.stream(input, config, **kwargs):
                yield chunk

    def __getattr__(self, name: str) -> Any:
        """Delegate unknown attributes to the wrapped graph."""
        return getattr(self._graph, name)
