"""
vizpath: Lightweight tracing SDK for AI agent observability.

Usage with decorators (recommended):

    from vizpath import tracer, configure

    # Configure the tracer
    configure(api_url="http://localhost:8000")

    @tracer.trace(name="my-task")
    def main():
        result = do_work()
        return result

    @tracer.span(name="work", span_type="tool")
    def do_work():
        tracer.set_span_attributes({"key": "value"})
        return "done"

Usage with context managers:

    from vizpath import Tracer

    with Tracer(api_key="...") as t:
        with t.trace("my-task") as trace:
            with trace.span("work") as span:
                span.set_attribute("key", "value")
"""

from vizpath.config import Config
from vizpath.decorators import configure
from vizpath.decorators import tracer as _tracer_instance
from vizpath.span import Span, SpanStatus, SpanType
from vizpath.tracer import Tracer

# Explicit assignment to ensure tracer refers to the GlobalTracer instance
# (not the vizpath.tracer module which would shadow it)
tracer = _tracer_instance

__version__ = "0.1.0"
__all__ = [
    "Config",
    "Span",
    "SpanStatus",
    "SpanType",
    "Tracer",
    "configure",
    "tracer",
]
