"""CrewAI adapter for automatic tracing of multi-agent crew executions."""

from __future__ import annotations

from typing import Any

from vizpath.span import SpanType
from vizpath.tracer import Tracer


class VizpathCrewCallback:
    """
    CrewAI callback handler for automatic tracing.

    Captures crew kickoffs, tasks, agent actions, and tool calls.

    Usage:
        from vizpath.adapters.crewai import CrewAIAdapter

        adapter = CrewAIAdapter(api_key="your-key")
        traced_crew = adapter.wrap(your_crew)
        result = traced_crew.kickoff(inputs={"topic": "AI safety"})
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        tracer: Tracer | None = None,
    ) -> None:
        self._tracer = tracer or Tracer(api_key=api_key, base_url=base_url)
        self._trace: Any = None
        self._task_spans: dict[str, Any] = {}
        self._action_spans: dict[str, Any] = {}

    def _get_or_create_trace(self, name: str = "crewai") -> Any:
        if self._trace is None:
            self._trace = self._tracer.trace(name)
            self._trace.__enter__()
        return self._trace

    def _end_trace(self) -> None:
        for span in list(self._action_spans.values()):
            try:
                span.__exit__(None, None, None)
            except Exception:
                pass
        for span in list(self._task_spans.values()):
            try:
                span.__exit__(None, None, None)
            except Exception:
                pass
        if self._trace is not None:
            self._trace.__exit__(None, None, None)
            self._trace = None
        self._task_spans.clear()
        self._action_spans.clear()

    def on_crew_start(
        self,
        crew_name: str,
        inputs: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """Called when a crew kickoff begins."""
        trace = self._get_or_create_trace(f"crewai-{crew_name}")
        trace.set_metadata(framework="crewai", crew=crew_name)
        if inputs:
            trace.set_metadata(inputs=inputs)

    def on_crew_end(self, output: Any = None, **kwargs: Any) -> None:
        """Called when a crew kickoff completes."""
        self._end_trace()

    def on_task_start(
        self,
        task_id: str,
        task_description: str,
        agent_name: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Called when a task begins execution."""
        trace = self._get_or_create_trace()
        span = trace.span(task_description[:80], span_type=SpanType.AGENT)
        span.set_input({"task": task_description})
        if agent_name:
            span.set_attributes(agent=agent_name)
        span.__enter__()
        self._task_spans[task_id] = span

    def on_task_end(
        self,
        task_id: str,
        output: Any = None,
        **kwargs: Any,
    ) -> None:
        """Called when a task completes successfully."""
        span = self._task_spans.pop(task_id, None)
        if span:
            if output is not None:
                span.set_output(output)
            span.__exit__(None, None, None)

    def on_task_error(
        self,
        task_id: str,
        error: str,
        **kwargs: Any,
    ) -> None:
        """Called when a task fails."""
        span = self._task_spans.pop(task_id, None)
        if span:
            span.set_error(error)
            span.__exit__(Exception, Exception(error), None)

    def on_agent_action(
        self,
        agent_name: str,
        action: str,
        tool_name: str | None = None,
        tool_input: Any = None,
        **kwargs: Any,
    ) -> str:
        """
        Called when an agent takes an action (typically a tool call).

        Returns:
            action_id: Identifier to pass to on_agent_action_end.
        """
        trace = self._get_or_create_trace()
        action_id = f"{agent_name}-{action}-{len(self._action_spans)}"

        # Nest under active task span if one exists
        parent = next(iter(self._task_spans.values()), None)

        if tool_name:
            span = (parent or trace).span(tool_name, span_type=SpanType.TOOL)
            span.set_input(tool_input)
            span.set_attributes(agent=agent_name, action=action)
        else:
            span = (parent or trace).span(action, span_type=SpanType.AGENT)
            span.set_attributes(agent=agent_name)

        span.__enter__()
        self._action_spans[action_id] = span
        return action_id

    def on_agent_action_end(
        self,
        action_id: str,
        output: Any = None,
        error: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Called when an agent action completes."""
        span = self._action_spans.pop(action_id, None)
        if span:
            if output is not None:
                span.set_output(output)
            if error:
                span.set_error(error)
                span.__exit__(Exception, Exception(error), None)
            else:
                span.__exit__(None, None, None)


class TracedCrew:
    """
    A CrewAI Crew wrapped with vizpath tracing.

    Intercepts kickoff/kickoff_async to trace full crew execution.
    Unknown attribute access is forwarded to the underlying crew.
    """

    def __init__(self, crew: Any, callback: VizpathCrewCallback) -> None:
        self._crew = crew
        self._callback = callback

    def kickoff(self, inputs: dict[str, Any] | None = None, **kwargs: Any) -> Any:
        """Run the crew synchronously with tracing."""
        crew_name = getattr(self._crew, "name", None) or "crew"
        self._callback.on_crew_start(crew_name, inputs=inputs)
        try:
            result = self._crew.kickoff(inputs=inputs, **kwargs)
            self._callback.on_crew_end(output=str(result) if result is not None else None)
            return result
        except Exception:
            self._callback._end_trace()
            raise

    async def kickoff_async(
        self, inputs: dict[str, Any] | None = None, **kwargs: Any
    ) -> Any:
        """Run the crew asynchronously with tracing."""
        crew_name = getattr(self._crew, "name", None) or "crew"
        self._callback.on_crew_start(crew_name, inputs=inputs)
        try:
            result = await self._crew.kickoff_async(inputs=inputs, **kwargs)
            self._callback.on_crew_end(output=str(result) if result is not None else None)
            return result
        except Exception:
            self._callback._end_trace()
            raise

    def __getattr__(self, name: str) -> Any:
        return getattr(self._crew, name)


class CrewAIAdapter:
    """
    Adapter for CrewAI that adds automatic tracing to a Crew.

    Usage:
        from vizpath.adapters.crewai import CrewAIAdapter

        adapter = CrewAIAdapter(api_key="your-key")
        traced_crew = adapter.wrap(your_crew)
        result = traced_crew.kickoff(inputs={"topic": "AI safety"})
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        tracer: Tracer | None = None,
    ) -> None:
        self._tracer = tracer or Tracer(api_key=api_key, base_url=base_url)

    def wrap(self, crew: Any) -> TracedCrew:
        """Wrap a CrewAI Crew to enable automatic tracing."""
        callback = VizpathCrewCallback(tracer=self._tracer)
        return TracedCrew(crew, callback)
