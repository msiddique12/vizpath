"""LangGraph adapter for automatic tracing of graph executions."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

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
        api_key: str | None = None,
        base_url: str | None = None,
        tracer: Tracer | None = None,
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

    def _wrap_node_fn(self, node_name: str, node_fn: Callable, trace: Any) -> Callable:
        """Wrap a node function to trace its execution."""
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            with trace.span(node_name, span_type=SpanType.AGENT) as span:
                # Capture input (state is usually first positional arg)
                if args:
                    span.set_input(args[0] if len(args) == 1 else args)
                elif kwargs:
                    span.set_input(kwargs)

                try:
                    result = node_fn(*args, **kwargs)
                    span.set_output(result)
                    return result
                except Exception as e:
                    span.set_error(str(e))
                    raise

        return wrapped

    async def _wrap_node_fn_async(self, node_name: str, node_fn: Callable, trace: Any) -> Callable:
        """Wrap an async node function to trace its execution."""
        import asyncio

        async def wrapped(*args: Any, **kwargs: Any) -> Any:
            with trace.span(node_name, span_type=SpanType.AGENT) as span:
                if args:
                    span.set_input(args[0] if len(args) == 1 else args)
                elif kwargs:
                    span.set_input(kwargs)

                try:
                    if asyncio.iscoroutinefunction(node_fn):
                        result = await node_fn(*args, **kwargs)
                    else:
                        result = node_fn(*args, **kwargs)
                    span.set_output(result)
                    return result
                except Exception as e:
                    span.set_error(str(e))
                    raise

        return wrapped

    def invoke(
        self,
        input: dict[str, Any],
        config: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Invoke the graph with tracing.

        Creates a trace for the entire invocation and spans for each node.
        """
        trace_name = config.get("run_name", "langgraph") if config else "langgraph"

        with self._tracer.trace(trace_name) as trace:
            trace.set_metadata(framework="langgraph", input_keys=list(input.keys()))

            # Try to get node execution via stream for better node-level tracing
            try:
                # Use stream_mode="updates" to get node-by-node execution
                final_state = None
                for chunk in self._graph.stream(input, config, stream_mode="updates", **kwargs):
                    # chunk is a dict: {node_name: node_output}
                    for node_name, node_output in chunk.items():
                        with trace.span(node_name, span_type=SpanType.AGENT) as span:
                            span.set_output(node_output)
                            # Update final state with each node's output
                            if final_state is None:
                                final_state = {}
                            if isinstance(node_output, dict):
                                final_state.update(node_output)
                            else:
                                final_state[node_name] = node_output

                return final_state or {}
            except Exception:
                # Fallback to direct invoke if streaming fails
                return self._graph.invoke(input, config, **kwargs)

    async def ainvoke(
        self,
        input: dict[str, Any],
        config: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Async version of invoke with tracing."""
        trace_name = config.get("run_name", "langgraph") if config else "langgraph"

        with self._tracer.trace(trace_name) as trace:
            trace.set_metadata(framework="langgraph", input_keys=list(input.keys()))

            # Try to get node execution via async stream for better tracing
            try:
                final_state = None
                async for chunk in self._graph.astream(input, config, stream_mode="updates", **kwargs):
                    for node_name, node_output in chunk.items():
                        with trace.span(node_name, span_type=SpanType.AGENT) as span:
                            span.set_output(node_output)
                            if final_state is None:
                                final_state = {}
                            if isinstance(node_output, dict):
                                final_state.update(node_output)
                            else:
                                final_state[node_name] = node_output

                return final_state or {}
            except Exception:
                # Fallback to direct ainvoke if streaming fails
                return await self._graph.ainvoke(input, config, **kwargs)

    def stream(
        self,
        input: dict[str, Any],
        config: dict[str, Any] | None = None,
        **kwargs: Any,
    ):
        """Stream graph execution with tracing."""
        trace_name = config.get("run_name", "langgraph-stream") if config else "langgraph-stream"

        with self._tracer.trace(trace_name) as trace:
            trace.set_metadata(framework="langgraph", mode="stream")

            for chunk in self._graph.stream(input, config, **kwargs):
                # Create span for each streamed chunk if it's node output
                if isinstance(chunk, dict):
                    for node_name, output in chunk.items():
                        with trace.span(node_name, span_type=SpanType.AGENT) as span:
                            span.set_output(output)
                yield chunk

    async def astream(
        self,
        input: dict[str, Any],
        config: dict[str, Any] | None = None,
        **kwargs: Any,
    ):
        """Async stream graph execution with tracing."""
        trace_name = config.get("run_name", "langgraph-stream") if config else "langgraph-stream"

        with self._tracer.trace(trace_name) as trace:
            trace.set_metadata(framework="langgraph", mode="stream")

            async for chunk in self._graph.astream(input, config, **kwargs):
                if isinstance(chunk, dict):
                    for node_name, output in chunk.items():
                        with trace.span(node_name, span_type=SpanType.AGENT) as span:
                            span.set_output(output)
                yield chunk

    def __getattr__(self, name: str) -> Any:
        """Delegate unknown attributes to the wrapped graph."""
        return getattr(self._graph, name)
