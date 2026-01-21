"""Trace ingestion and retrieval endpoints."""

import logging
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Project, Span, Trace
from app.routes.ws import notify_span_ingested

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/traces", tags=["Traces"])


class SpanCreate(BaseModel):
    """Schema for creating a span."""

    span_id: str
    trace_id: str
    parent_id: str | None = None
    name: str
    span_type: str = "custom"
    status: str = "success"
    start_time: datetime
    end_time: datetime | None = None
    duration_ms: float | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    events: list[dict[str, Any]] = Field(default_factory=list)
    input: Any | None = None
    output: Any | None = None
    error: str | None = None
    tokens: int | None = None
    cost: float | None = None


class SpanBatchCreate(BaseModel):
    """Schema for batch span creation."""

    spans: list[SpanCreate]


class TraceResponse(BaseModel):
    """Response schema for trace details."""

    id: str
    name: str
    status: str
    start_time: datetime
    end_time: datetime | None
    duration_ms: float | None
    metadata: dict[str, Any]
    total_tokens: int | None
    total_cost: float | None
    span_count: int
    error_count: int


class TraceListResponse(BaseModel):
    """Response schema for trace list."""

    traces: list[TraceResponse]
    total: int
    limit: int
    offset: int


class SpanResponse(BaseModel):
    """Response schema for span details."""

    id: str
    trace_id: str
    parent_id: str | None
    name: str
    span_type: str
    status: str
    start_time: datetime
    end_time: datetime | None
    duration_ms: float | None
    attributes: dict[str, Any]
    input: Any | None
    output: Any | None
    error: str | None
    tokens: int | None
    cost: float | None


def get_or_create_trace(db: Session, trace_id: str, project_id: UUID, span: SpanCreate) -> Trace:
    """Get existing trace or create a new one."""
    trace = db.query(Trace).filter(Trace.id == trace_id).first()

    if not trace:
        trace = Trace(
            id=trace_id,
            project_id=project_id,
            name=span.name.split(".")[0] if span.parent_id is None else "trace",
            status="running",
            start_time=span.start_time,
        )
        db.add(trace)

    return trace


@router.post("/spans/batch", status_code=201)
async def ingest_spans(
    payload: list[SpanCreate],
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Ingest a batch of spans.

    Creates traces automatically if they don't exist.
    """
    if not payload:
        return {"ingested": 0}

    project = db.query(Project).first()
    if not project:
        project = Project(name="default", api_key_hash="default")
        db.add(project)
        db.flush()

    traces_updated = set()

    for span_data in payload:
        trace = get_or_create_trace(db, span_data.trace_id, project.id, span_data)
        traces_updated.add(trace.id)

        span = Span(
            id=span_data.span_id,
            trace_id=span_data.trace_id,
            parent_id=span_data.parent_id if span_data.parent_id else None,
            name=span_data.name,
            span_type=span_data.span_type,
            status=span_data.status,
            start_time=span_data.start_time,
            end_time=span_data.end_time,
            duration_ms=span_data.duration_ms,
            attributes=span_data.attributes,
            events=span_data.events,
            input=span_data.input,
            output=span_data.output,
            error=span_data.error,
            tokens=span_data.tokens,
            cost=span_data.cost,
        )
        db.add(span)

    for trace_id in traces_updated:
        trace = db.query(Trace).filter(Trace.id == trace_id).first()
        if trace:
            stats = (
                db.query(
                    func.count(Span.id).label("count"),
                    func.sum(Span.tokens).label("tokens"),
                    func.sum(Span.cost).label("cost"),
                    func.sum(func.cast(Span.error.isnot(None), db.bind.dialect.name == 'postgresql' and 'INTEGER' or None)).label("errors"),
                )
                .filter(Span.trace_id == trace_id)
                .first()
            )
            trace.span_count = stats.count or 0
            trace.total_tokens = stats.tokens
            trace.total_cost = stats.cost

    db.commit()

    for trace_id in traces_updated:
        notify_span_ingested(str(trace_id), len(payload))

    return {"ingested": len(payload), "traces": len(traces_updated)}


@router.get("/", response_model=TraceListResponse)
async def list_traces(
    db: Session = Depends(get_db),
    limit: int = Query(default=20, le=100),
    offset: int = Query(default=0, ge=0),
    status: str | None = None,
) -> TraceListResponse:
    """List traces with pagination."""
    query = db.query(Trace)

    if status:
        query = query.filter(Trace.status == status)

    total = query.count()
    traces = query.order_by(Trace.created_at.desc()).offset(offset).limit(limit).all()

    return TraceListResponse(
        traces=[
            TraceResponse(
                id=str(t.id),
                name=t.name,
                status=t.status,
                start_time=t.start_time,
                end_time=t.end_time,
                duration_ms=t.duration_ms,
                metadata=t.metadata or {},
                total_tokens=t.total_tokens,
                total_cost=t.total_cost,
                span_count=t.span_count,
                error_count=t.error_count,
            )
            for t in traces
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{trace_id}")
async def get_trace(
    trace_id: UUID,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Get trace details with all spans."""
    trace = db.query(Trace).filter(Trace.id == trace_id).first()

    if not trace:
        raise HTTPException(status_code=404, detail="Trace not found")

    spans = db.query(Span).filter(Span.trace_id == trace_id).all()

    return {
        "trace": trace.to_dict(),
        "spans": [s.to_dict() for s in spans],
    }


@router.get("/{trace_id}/spans")
async def get_trace_spans(
    trace_id: UUID,
    db: Session = Depends(get_db),
) -> list[SpanResponse]:
    """Get all spans for a trace."""
    spans = db.query(Span).filter(Span.trace_id == trace_id).all()

    return [
        SpanResponse(
            id=str(s.id),
            trace_id=str(s.trace_id),
            parent_id=str(s.parent_id) if s.parent_id else None,
            name=s.name,
            span_type=s.span_type,
            status=s.status,
            start_time=s.start_time,
            end_time=s.end_time,
            duration_ms=s.duration_ms,
            attributes=s.attributes or {},
            input=s.input,
            output=s.output,
            error=s.error,
            tokens=s.tokens,
            cost=s.cost,
        )
        for s in spans
    ]
