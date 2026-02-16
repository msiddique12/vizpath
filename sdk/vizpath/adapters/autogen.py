"""AutoGen adapter for automatic tracing of multi-agent conversations."""

from __future__ import annotations

import types
from typing import TYPE_CHECKING, Any

from vizpath.span import SpanType
from vizpath.tracer import Tracer

if TYPE_CHECKING:
    pass


class VizpathAutoGenCallback:
    """
    AutoGen callback handler for automatic tracing.

    Captures agent conversations, tool executions, and LLM calls.

    Usage:
        from vizpath.adapters.autogen import VizpathAutoGenCallback, wrap_autogen_agent

        callback = VizpathAutoGenCallback(api_key="your-key")
        agent = wrap_autogen_agent(your_agent, callback)

        # Use agent normally - tracing is automatic
        agent.initiate_chat(...)
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        tracer: Tracer | None = None,
    ) -> None:
        self._tracer = tracer or Tracer(api_key=api_key, base_url=base_url)
        self._trace = None
        self._spans: dict[str, Any] = {}
        self._agent_spans: dict[str, Any] = {}

    def _get_or_create_trace(self, name: str = "autogen-conversation") -> Any:
        """Get or create the current trace context."""
        if self._trace is None:
            self._trace = self._tracer.trace(name)
            self._trace.__enter__()
        return self._trace

    def _end_trace(self) -> None:
        """End the current trace context."""
        if self._trace is not None:
            self._trace.__exit__(None, None, None)
            self._trace = None
            self._spans.clear()
            self._agent_spans.clear()

    def on_conversation_start(
        self,
        sender: str,
        recipient: str,
        message: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Called when a conversation starts."""
        trace_name = f"autogen-{sender}-{recipient}"
        trace = self._get_or_create_trace(trace_name)
        trace.set_metadata(
            framework="autogen",
            sender=sender,
            recipient=recipient,
        )

    def on_conversation_end(self, **kwargs: Any) -> None:
        """Called when a conversation ends."""
        self._end_trace()

    def on_agent_message(
        self,
        agent_name: str,
        message: dict[str, Any],
        **kwargs: Any,
    ) -> None:
        """Called when an agent sends a message."""
        trace = self._get_or_create_trace()

        # Create or get agent span
        if agent_name not in self._agent_spans:
            span = trace.span(agent_name, span_type=SpanType.AGENT)
            span.__enter__()
            self._agent_spans[agent_name] = span

        # Add message as event
        span = self._agent_spans[agent_name]
        content = message.get("content", "") if isinstance(message, dict) else str(message)
        span.add_event("message", content=content[:500])

    def on_llm_call_start(
        self,
        agent_name: str,
        model: str | None = None,
        messages: list[dict] | None = None,
        **kwargs: Any,
    ) -> None:
        """Called when an LLM call starts."""
        trace = self._get_or_create_trace()

        span_id = f"llm-{agent_name}-{len(self._spans)}"
        parent = self._agent_spans.get(agent_name)

        if parent:
            span = parent.span(f"llm-{agent_name}", span_type=SpanType.LLM)
        else:
            span = trace.span(f"llm-{agent_name}", span_type=SpanType.LLM)

        span.set_input(messages)
        if model:
            span.set_attributes(model=model)
        span.__enter__()
        self._spans[span_id] = span

    def on_llm_call_end(
        self,
        agent_name: str,
        response: Any = None,
        token_usage: dict[str, int] | None = None,
        **kwargs: Any,
    ) -> None:
        """Called when an LLM call ends."""
        span_id = f"llm-{agent_name}-{len(self._spans) - 1}"
        span = self._spans.get(span_id)

        if span:
            if response:
                span.set_output(response)
            if token_usage:
                total_tokens = token_usage.get("total_tokens", 0)
                if total_tokens:
                    span.set_tokens(total_tokens)
                span.set_attributes(**token_usage)
            span.__exit__(None, None, None)

    def on_tool_call_start(
        self,
        agent_name: str,
        tool_name: str,
        tool_input: Any = None,
        **kwargs: Any,
    ) -> None:
        """Called when a tool call starts."""
        trace = self._get_or_create_trace()

        span_id = f"tool-{agent_name}-{tool_name}-{len(self._spans)}"
        parent = self._agent_spans.get(agent_name)

        if parent:
            span = parent.span(tool_name, span_type=SpanType.TOOL)
        else:
            span = trace.span(tool_name, span_type=SpanType.TOOL)

        span.set_input(tool_input)
        span.__enter__()
        self._spans[span_id] = span

    def on_tool_call_end(
        self,
        agent_name: str,
        tool_name: str,
        tool_output: Any = None,
        error: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Called when a tool call ends."""
        span_id = f"tool-{agent_name}-{tool_name}-{len(self._spans) - 1}"
        span = self._spans.get(span_id)

        if span:
            if tool_output:
                span.set_output(tool_output)
            if error:
                span.set_error(error)
                span.__exit__(ValueError, ValueError(error), None)
            else:
                span.__exit__(None, None, None)


def wrap_autogen_agent(agent: Any, callback: VizpathAutoGenCallback) -> Any:
    """
    Wrap an AutoGen agent to enable automatic tracing.

    This adds hooks to the agent's messaging and LLM calls.

    Args:
        agent: An AutoGen agent (AssistantAgent, UserProxyAgent, etc.)
        callback: VizpathAutoGenCallback instance

    Returns:
        The same agent with tracing enabled
    """
    original_generate_reply = getattr(agent, "generate_reply", None)
    original_execute_function = getattr(agent, "execute_function", None)

    if original_generate_reply:
        def traced_generate_reply(self_ref: Any, *args: Any, **kwargs: Any) -> Any:
            agent_name = getattr(agent, "name", "agent")
            messages = kwargs.get("messages") or (args[0] if args else None)

            callback.on_llm_call_start(agent_name, messages=messages)
            try:
                result = original_generate_reply(*args, **kwargs)
                callback.on_llm_call_end(agent_name, response=result)
                return result
            except Exception:
                callback.on_llm_call_end(agent_name, response=None)
                raise

        # Bind as an instance method to preserve method-like behavior in tests/integrations.
        agent.generate_reply = types.MethodType(traced_generate_reply, agent)

    if original_execute_function:
        def traced_execute_function(func_call: dict, **kwargs: Any) -> Any:
            agent_name = getattr(agent, "name", "agent")
            func_name = func_call.get("name", "unknown")
            func_args = func_call.get("arguments", {})

            callback.on_tool_call_start(agent_name, func_name, func_args)
            try:
                result = original_execute_function(func_call, **kwargs)
                callback.on_tool_call_end(agent_name, func_name, result)
                return result
            except Exception as e:
                callback.on_tool_call_end(agent_name, func_name, error=str(e))
                raise

        agent.execute_function = traced_execute_function

    return agent


class AutoGenTracer:
    """
    Context manager for tracing AutoGen conversations.

    Usage:
        from vizpath.adapters.autogen import AutoGenTracer

        with AutoGenTracer(api_key="your-key") as tracer:
            # Run AutoGen conversation
            agent.initiate_chat(other_agent, message="Hello")
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        name: str = "autogen-conversation",
    ) -> None:
        self._tracer = Tracer(api_key=api_key, base_url=base_url)
        self._name = name
        self._trace = None
        self._callback: VizpathAutoGenCallback | None = None

    def __enter__(self) -> VizpathAutoGenCallback:
        self._callback = VizpathAutoGenCallback(tracer=self._tracer)
        self._callback.on_conversation_start("system", "system", message=self._name)
        return self._callback

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if self._callback:
            self._callback.on_conversation_end()
