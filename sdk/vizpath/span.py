"""Span implementation for trace instrumentation."""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from vizpath.tracer import TraceContext


class SpanType(str, Enum):
    """Types of spans for categorization."""

    LLM = "llm"
    TOOL = "tool"
    AGENT = "agent"
    RETRIEVAL = "retrieval"
    CHAIN = "chain"
    CUSTOM = "custom"


class SpanStatus(str, Enum):
    """Span execution status."""

    RUNNING = "running"
    SUCCESS = "success"
    ERROR = "error"


class SpanEvent(BaseModel):
    """Point-in-time event within a span."""

    name: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    attributes: Dict[str, Any] = Field(default_factory=dict)


class SpanData(BaseModel):
    """Serializable span data for API transmission."""

    span_id: str
    trace_id: str
    parent_id: Optional[str] = None
    name: str
    span_type: SpanType = SpanType.CUSTOM
    status: SpanStatus = SpanStatus.RUNNING
    start_time: datetime
    end_time: Optional[datetime] = None
    duration_ms: Optional[float] = None
    attributes: Dict[str, Any] = Field(default_factory=dict)
    events: List[SpanEvent] = Field(default_factory=list)
    input: Optional[Any] = None
    output: Optional[Any] = None
    error: Optional[str] = None
    tokens: Optional[int] = None
    cost: Optional[float] = None


class Span:
    """
    Represents a single operation within a trace.

    Spans can be nested to form a tree structure representing
    the execution flow of an agent.
    """

    def __init__(
        self,
        name: str,
        trace_context: TraceContext,
        parent: Optional[Span] = None,
        span_type: SpanType = SpanType.CUSTOM,
    ) -> None:
        self._id = str(uuid.uuid4())
        self._trace_context = trace_context
        self._parent = parent
        self._name = name
        self._span_type = span_type
        self._status = SpanStatus.RUNNING
        self._start_time = datetime.now(timezone.utc)
        self._start_ts = time.perf_counter()
        self._end_time: Optional[datetime] = None
        self._duration_ms: Optional[float] = None
        self._attributes: Dict[str, Any] = {}
        self._events: List[SpanEvent] = []
        self._input: Optional[Any] = None
        self._output: Optional[Any] = None
        self._error: Optional[str] = None
        self._tokens: Optional[int] = None
        self._cost: Optional[float] = None
        self._children: List[Span] = []

    @property
    def id(self) -> str:
        return self._id

    @property
    def name(self) -> str:
        return self._name

    @property
    def parent_id(self) -> Optional[str]:
        return self._parent._id if self._parent else None

    @property
    def trace_id(self) -> str:
        return self._trace_context.trace_id

    def span(
        self,
        name: str,
        span_type: SpanType = SpanType.CUSTOM,
    ) -> Span:
        """Create a child span."""
        child = Span(
            name=name,
            trace_context=self._trace_context,
            parent=self,
            span_type=span_type,
        )
        self._children.append(child)
        self._trace_context._register_span(child)
        return child

    def set_input(self, value: Any) -> Span:
        """Set the input value for this span."""
        self._input = value
        return self

    def set_output(self, value: Any) -> Span:
        """Set the output value for this span."""
        self._output = value
        return self

    def set_attributes(self, **kwargs: Any) -> Span:
        """Set arbitrary attributes on this span."""
        self._attributes.update(kwargs)
        return self

    def set_tokens(self, count: int, cost: Optional[float] = None) -> Span:
        """Set token count and optional cost for LLM spans."""
        self._tokens = count
        if cost is not None:
            self._cost = cost
        return self

    def add_event(self, name: str, **attributes: Any) -> Span:
        """Add a point-in-time event to this span."""
        self._events.append(SpanEvent(name=name, attributes=attributes))
        return self

    def set_error(self, error: str) -> Span:
        """Mark this span as failed with an error message."""
        self._error = error
        self._status = SpanStatus.ERROR
        return self

    def end(self, status: Optional[SpanStatus] = None) -> None:
        """End this span and record its duration."""
        self._end_time = datetime.now(timezone.utc)
        self._duration_ms = (time.perf_counter() - self._start_ts) * 1000

        if status:
            self._status = status
        elif self._status == SpanStatus.RUNNING:
            self._status = SpanStatus.SUCCESS

        self._trace_context._on_span_end(self)

    def to_data(self) -> SpanData:
        """Convert to serializable data model."""
        return SpanData(
            span_id=self._id,
            trace_id=self.trace_id,
            parent_id=self.parent_id,
            name=self._name,
            span_type=self._span_type,
            status=self._status,
            start_time=self._start_time,
            end_time=self._end_time,
            duration_ms=self._duration_ms,
            attributes=self._attributes,
            events=self._events,
            input=self._input,
            output=self._output,
            error=self._error,
            tokens=self._tokens,
            cost=self._cost,
        )

    def __enter__(self) -> Span:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if exc_val is not None:
            self.set_error(str(exc_val))
        self.end()
