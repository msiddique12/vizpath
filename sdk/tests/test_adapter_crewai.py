"""Tests for the CrewAI adapter."""

from unittest.mock import MagicMock, patch

import pytest

from vizpath.adapters.crewai import CrewAIAdapter, TracedCrew, VizpathCrewCallback


class TestVizpathCrewCallback:
    """Unit tests for VizpathCrewCallback."""

    def test_creates_trace_on_crew_start(self):
        """on_crew_start should create a trace."""
        callback = VizpathCrewCallback()
        callback.on_crew_start("my-crew")
        assert callback._trace is not None

    def test_sets_crew_metadata(self):
        """on_crew_start should set framework and crew metadata."""
        mock_tracer = MagicMock()
        mock_trace = MagicMock()
        mock_tracer.trace.return_value.__enter__ = MagicMock(return_value=mock_trace)
        mock_tracer.trace.return_value.__exit__ = MagicMock(return_value=False)

        callback = VizpathCrewCallback(tracer=mock_tracer)
        callback.on_crew_start("research-crew", inputs={"topic": "AI"})

        mock_tracer.trace.assert_called_once_with("crewai-research-crew")

    def test_ends_trace_on_crew_end(self):
        """on_crew_end should finalize the trace."""
        callback = VizpathCrewCallback()
        callback.on_crew_start("crew")
        assert callback._trace is not None
        callback.on_crew_end()
        assert callback._trace is None

    def test_task_span_created_on_task_start(self):
        """on_task_start should create a span tracked by task_id."""
        callback = VizpathCrewCallback()
        callback.on_crew_start("crew")
        callback.on_task_start("t1", "Research about AI safety", agent_name="researcher")
        assert "t1" in callback._task_spans

    def test_task_span_removed_on_task_end(self):
        """on_task_end should close and remove the task span."""
        callback = VizpathCrewCallback()
        callback.on_crew_start("crew")
        callback.on_task_start("t1", "Do research")
        callback.on_task_end("t1", output="Research done")
        assert "t1" not in callback._task_spans

    def test_task_span_removed_on_task_error(self):
        """on_task_error should close the task span with an error."""
        callback = VizpathCrewCallback()
        callback.on_crew_start("crew")
        callback.on_task_start("t1", "Do research")
        callback.on_task_error("t1", error="Connection timeout")
        assert "t1" not in callback._task_spans

    def test_agent_action_creates_tool_span(self):
        """on_agent_action with tool_name should create a TOOL span."""
        callback = VizpathCrewCallback()
        callback.on_crew_start("crew")
        action_id = callback.on_agent_action(
            "researcher",
            "use_tool",
            tool_name="web_search",
            tool_input={"query": "AI safety papers"},
        )
        assert action_id in callback._action_spans

    def test_agent_action_creates_agent_span_when_no_tool(self):
        """on_agent_action without tool_name should create an AGENT span."""
        callback = VizpathCrewCallback()
        callback.on_crew_start("crew")
        action_id = callback.on_agent_action("researcher", "think")
        assert action_id in callback._action_spans

    def test_agent_action_end_removes_span(self):
        """on_agent_action_end should close and remove the action span."""
        callback = VizpathCrewCallback()
        callback.on_crew_start("crew")
        action_id = callback.on_agent_action("researcher", "think")
        callback.on_agent_action_end(action_id, output="Insight gained")
        assert action_id not in callback._action_spans

    def test_agent_action_end_with_error(self):
        """on_agent_action_end with error should mark span as errored."""
        callback = VizpathCrewCallback()
        callback.on_crew_start("crew")
        action_id = callback.on_agent_action(
            "researcher", "use_tool", tool_name="web_search"
        )
        callback.on_agent_action_end(action_id, error="HTTP 429")
        assert action_id not in callback._action_spans

    def test_end_trace_clears_all_spans(self):
        """_end_trace should close all open spans and clear state."""
        callback = VizpathCrewCallback()
        callback.on_crew_start("crew")
        callback.on_task_start("t1", "Task one")
        callback.on_agent_action("agent", "think")
        callback._end_trace()
        assert callback._trace is None
        assert len(callback._task_spans) == 0
        assert len(callback._action_spans) == 0

    def test_unknown_task_id_is_safe(self):
        """on_task_end with an unknown task_id should not raise."""
        callback = VizpathCrewCallback()
        callback.on_task_end("nonexistent", output="result")  # should not raise

    def test_task_description_truncated_to_80_chars(self):
        """Task span name is truncated to 80 characters."""
        callback = VizpathCrewCallback()
        callback.on_crew_start("crew")
        long_desc = "A" * 200
        callback.on_task_start("t1", long_desc)
        span = callback._task_spans["t1"]
        assert len(span._name) <= 80


class TestCrewAIAdapter:
    """Unit tests for CrewAIAdapter."""

    def test_wrap_returns_traced_crew(self):
        """wrap() should return a TracedCrew instance."""
        mock_crew = MagicMock()
        adapter = CrewAIAdapter()
        result = adapter.wrap(mock_crew)
        assert isinstance(result, TracedCrew)

    def test_wrap_uses_provided_tracer(self):
        """wrap() should use the provided tracer."""
        mock_tracer = MagicMock()
        adapter = CrewAIAdapter(tracer=mock_tracer)
        mock_crew = MagicMock()
        traced = adapter.wrap(mock_crew)
        assert traced._callback._tracer is mock_tracer


class TestTracedCrew:
    """Unit tests for TracedCrew."""

    def test_kickoff_calls_crew_kickoff(self):
        """kickoff() should call the underlying crew's kickoff."""
        mock_crew = MagicMock()
        mock_crew.name = "test-crew"
        mock_crew.kickoff.return_value = "Final answer"

        callback = VizpathCrewCallback()
        traced = TracedCrew(mock_crew, callback)
        result = traced.kickoff(inputs={"topic": "AI"})

        mock_crew.kickoff.assert_called_once_with(inputs={"topic": "AI"})
        assert result == "Final answer"

    def test_kickoff_creates_and_ends_trace(self):
        """kickoff() should create a trace that is ended after completion."""
        mock_crew = MagicMock()
        mock_crew.name = "my-crew"
        mock_crew.kickoff.return_value = "done"

        callback = VizpathCrewCallback()
        traced = TracedCrew(mock_crew, callback)
        traced.kickoff()

        assert callback._trace is None

    def test_kickoff_ends_trace_on_exception(self):
        """kickoff() should end trace even when crew raises."""
        mock_crew = MagicMock()
        mock_crew.name = "failing-crew"
        mock_crew.kickoff.side_effect = RuntimeError("crew crashed")

        callback = VizpathCrewCallback()
        traced = TracedCrew(mock_crew, callback)

        with pytest.raises(RuntimeError):
            traced.kickoff()

        assert callback._trace is None

    def test_delegates_unknown_attributes(self):
        """Unknown attribute access should be forwarded to the underlying crew."""
        mock_crew = MagicMock()
        mock_crew.agents = ["agent1", "agent2"]

        callback = VizpathCrewCallback()
        traced = TracedCrew(mock_crew, callback)

        assert traced.agents == ["agent1", "agent2"]

    @pytest.mark.asyncio
    async def test_kickoff_async_calls_crew_kickoff_async(self):
        """kickoff_async() should await the underlying crew's kickoff_async."""
        import asyncio

        async def fake_kickoff_async(inputs=None, **kwargs):
            return "async result"

        mock_crew = MagicMock()
        mock_crew.name = "async-crew"
        mock_crew.kickoff_async = fake_kickoff_async

        callback = VizpathCrewCallback()
        traced = TracedCrew(mock_crew, callback)
        result = await traced.kickoff_async(inputs={"x": 1})
        assert result == "async result"
        assert callback._trace is None
