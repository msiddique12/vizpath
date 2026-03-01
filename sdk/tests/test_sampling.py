"""Tests for trace sampling (sample_rate in Config and Tracer)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from vizpath import Tracer
from vizpath.config import Config
from vizpath.tracer import NoopSpan, NoopTrace, Trace


class TestConfig:
    """sample_rate validation in Config."""

    def test_default_sample_rate_is_one(self):
        config = Config()
        assert config.sample_rate == 1.0

    def test_explicit_sample_rate(self):
        config = Config(sample_rate=0.5)
        assert config.sample_rate == 0.5

    def test_zero_sample_rate_is_valid(self):
        config = Config(sample_rate=0.0)
        assert config.sample_rate == 0.0

    def test_sample_rate_above_one_raises(self):
        with pytest.raises(ValueError, match="sample_rate"):
            Config(sample_rate=1.1)

    def test_sample_rate_below_zero_raises(self):
        with pytest.raises(ValueError, match="sample_rate"):
            Config(sample_rate=-0.1)

    def test_env_var_sets_sample_rate(self, monkeypatch):
        monkeypatch.setenv("VIZPATH_SAMPLE_RATE", "0.25")
        config = Config()
        assert config.sample_rate == 0.25


class TestNoopSpan:
    """NoopSpan should silently absorb all calls and return self."""

    def test_span_returns_noop_span(self):
        s = NoopSpan()
        child = s.span("child")
        assert isinstance(child, NoopSpan)

    def test_set_input_returns_self(self):
        s = NoopSpan()
        assert s.set_input({"x": 1}) is s

    def test_set_output_returns_self(self):
        s = NoopSpan()
        assert s.set_output("result") is s

    def test_set_attributes_returns_self(self):
        s = NoopSpan()
        assert s.set_attributes(model="gpt-4") is s

    def test_set_tokens_returns_self(self):
        s = NoopSpan()
        assert s.set_tokens(100, cost=0.01) is s

    def test_set_error_returns_self(self):
        s = NoopSpan()
        assert s.set_error("oops") is s

    def test_add_event_returns_self(self):
        s = NoopSpan()
        assert s.add_event("tick", ts=0) is s

    def test_end_does_not_raise(self):
        NoopSpan().end()

    def test_context_manager_protocol(self):
        with NoopSpan() as s:
            assert isinstance(s, NoopSpan)


class TestNoopTrace:
    """NoopTrace should silently absorb all calls and return self."""

    def test_trace_id_is_empty_string(self):
        assert NoopTrace().trace_id == ""

    def test_span_returns_noop_span(self):
        t = NoopTrace()
        assert isinstance(t.span("op"), NoopSpan)

    def test_set_metadata_returns_self(self):
        t = NoopTrace()
        assert t.set_metadata(framework="test") is t

    def test_end_does_not_raise(self):
        NoopTrace().end()

    def test_context_manager_protocol(self):
        with NoopTrace() as t:
            assert isinstance(t, NoopTrace)

    def test_nested_noop_spans(self):
        """A noop trace should support full span nesting without error."""
        with NoopTrace() as trace:
            with trace.span("outer") as outer:
                with outer.span("inner") as inner:
                    inner.set_input({"q": "hello"}).set_output("world")


class TestTracerSampling:
    """Tracer.trace() respects sample_rate."""

    def test_full_rate_always_returns_real_trace(self):
        tracer = Tracer(config=Config(sample_rate=1.0))
        for _ in range(20):
            assert isinstance(tracer.trace("t"), Trace)

    def test_zero_rate_always_returns_noop(self):
        tracer = Tracer(config=Config(sample_rate=0.0))
        for _ in range(20):
            assert isinstance(tracer.trace("t"), NoopTrace)

    def test_partial_rate_returns_mix(self):
        """At 50% sample rate over many calls, both types should appear."""
        tracer = Tracer(config=Config(sample_rate=0.5))
        results = [type(tracer.trace("t")) for _ in range(200)]
        assert Trace in results
        assert NoopTrace in results

    def test_sampled_trace_is_real_trace(self):
        """When random says yes, we get a real Trace."""
        tracer = Tracer(config=Config(sample_rate=0.1))
        with patch("vizpath.tracer.random.random", return_value=0.05):
            assert isinstance(tracer.trace("t"), Trace)

    def test_dropped_trace_is_noop(self):
        """When random says no, we get a NoopTrace."""
        tracer = Tracer(config=Config(sample_rate=0.1))
        with patch("vizpath.tracer.random.random", return_value=0.95):
            assert isinstance(tracer.trace("t"), NoopTrace)

    def test_adapters_work_with_noop_trace(self):
        """
        Ensure adapter-style usage (enter/exit, span nesting) works on NoopTrace
        without raising, so sampling is transparent to adapter code.
        """
        tracer = Tracer(config=Config(sample_rate=0.0))  # always noop

        trace = tracer.trace("task")
        trace.__enter__()
        span = trace.span("op")
        span.__enter__()
        span.set_input({"x": 1})
        nested = span.span("nested")
        nested.__enter__()
        nested.set_output("done")
        nested.__exit__(None, None, None)
        span.__exit__(None, None, None)
        trace.__exit__(None, None, None)
        # No exceptions → adapters are unaffected by sampling
