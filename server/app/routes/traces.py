"""Trace ingestion and retrieval endpoints."""

import logging
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import case, desc, func, nullslast
from sqlalchemy.orm import Session

from app.auth import verify_api_key
from app.budgeting import get_month_window, get_project_budget, get_project_month_usage
from app.database import get_db
from app.intelligence.guardrail import (
    build_insufficient_baseline_guardrail,
    build_regression_guardrail,
)
from app.models import Project, Span, Trace
from app.routes.ws import notify_span_ingested
from app.validation import ID_PATTERN, SPAN_TYPE_PATTERN, STATUS_PATTERN, normalize_text

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/traces", tags=["Traces"])


def _to_utc(dt: datetime) -> datetime:
    """Normalize DB datetime values to UTC-aware for safe arithmetic."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class SpanCreate(BaseModel):
    """Schema for creating a span."""

    model_config = ConfigDict(extra="forbid")

    span_id: str = Field(min_length=1, max_length=128, pattern=ID_PATTERN)
    trace_id: str = Field(min_length=1, max_length=128, pattern=ID_PATTERN)
    parent_id: str | None = Field(default=None, min_length=1, max_length=128, pattern=ID_PATTERN)
    name: str = Field(min_length=1, max_length=256)
    span_type: str = Field(default="custom", pattern=SPAN_TYPE_PATTERN)
    status: str = Field(default="success", pattern=STATUS_PATTERN)
    start_time: datetime
    end_time: datetime | None = None
    duration_ms: float | None = Field(default=None, ge=0, le=86400000)
    attributes: dict[str, Any] = Field(default_factory=dict, max_length=200)
    events: list[dict[str, Any]] = Field(default_factory=list, max_length=1000)
    input: Any | None = None
    output: Any | None = None
    error: str | None = Field(default=None, max_length=4096)
    tokens: int | None = Field(default=None, ge=0, le=10000000)
    cost: float | None = Field(default=None, ge=0, le=1000000)
    trace_name: str | None = Field(default=None, min_length=1, max_length=256)
    trace_status: str | None = Field(default=None, pattern=STATUS_PATTERN)
    trace_start_time: datetime | None = None
    trace_end_time: datetime | None = None
    trace_duration_ms: float | None = Field(default=None, ge=0, le=86400000)
    trace_metadata: dict[str, Any] = Field(default_factory=dict, max_length=100)

    @field_validator("name", "error", "trace_name", mode="before")
    @classmethod
    def normalize_text_fields(cls, value: str | None, info) -> str | None:
        limits = {"name": 256, "error": 4096, "trace_name": 256}
        return normalize_text(
            value,
            field_name=info.field_name,
            max_length=limits[info.field_name],
            allow_empty=info.field_name == "error",
        )


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
    created_at: datetime


class TraceListResponse(BaseModel):
    """Response schema for trace list."""

    traces: list[TraceResponse]
    total: int
    limit: int
    offset: int


class ExperimentSummaryResponse(BaseModel):
    """Summary for an experiment group (run/model/prompt version)."""

    experiment_id: str
    trace_count: int
    latest_trace_id: str
    latest_trace_name: str
    latest_created_at: datetime
    statuses: dict[str, int]
    avg_duration_ms: float | None
    total_tokens: int | None
    total_cost: float | None
    error_rate: float
    sample_compare_pair: dict[str, str] | None


class ExperimentListResponse(BaseModel):
    """Response schema for experiment list."""

    field: str
    experiments: list[ExperimentSummaryResponse]
    total: int


class TraceSummaryResponse(BaseModel):
    """High-level KPIs for a time window."""

    window_days: int
    trace_count: int
    success_rate: float
    running_count: int
    error_count: int
    p50_duration_ms: float | None
    p95_duration_ms: float | None
    avg_tokens: float | None
    avg_cost: float | None


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
    events: list[dict[str, Any]]
    input: Any | None
    output: Any | None
    error: str | None
    tokens: int | None
    cost: float | None


def get_or_create_trace(db: Session, trace_id: str, project_id: Any, span: SpanCreate) -> Trace:
    """Get existing trace or create a new one."""
    trace = (
        db.query(Trace)
        .filter(Trace.id == trace_id, Trace.project_id == project_id)
        .first()
    )
    foreign_trace = (
        db.query(Trace.id)
        .filter(Trace.id == trace_id, Trace.project_id != project_id)
        .first()
    )
    if foreign_trace:
        raise HTTPException(
            status_code=409,
            detail="Trace ID already exists for another project.",
        )

    trace_name = (
        span.trace_name
        if span.trace_name
        else span.name.split(".")[0] if span.parent_id is None else "trace"
    )
    trace_start_time = span.trace_start_time or span.start_time

    if not trace:
        trace = Trace(
            id=trace_id,
            project_id=project_id,
            name=trace_name,
            status=span.trace_status or "running",
            start_time=trace_start_time,
            end_time=span.trace_end_time,
            duration_ms=span.trace_duration_ms,
            trace_metadata=span.trace_metadata or {},
        )
        db.add(trace)
        db.flush()  # Make visible for subsequent queries in same transaction
        return trace

    if span.trace_name:
        trace.name = span.trace_name
    if span.trace_metadata:
        trace.trace_metadata = {**(trace.trace_metadata or {}), **span.trace_metadata}
    if span.trace_start_time and span.trace_start_time < trace.start_time:
        trace.start_time = span.trace_start_time
    if span.trace_end_time and (trace.end_time is None or span.trace_end_time > trace.end_time):
        trace.end_time = span.trace_end_time
    if span.trace_duration_ms is not None:
        trace.duration_ms = span.trace_duration_ms
    if span.trace_status in {"success", "error"}:
        trace.status = span.trace_status

    return trace


def _upsert_span(db: Session, project_id: Any, span_data: SpanCreate) -> bool:
    """Insert a span or update the same project's existing span idempotently."""
    existing = db.query(Span).filter(Span.id == span_data.span_id).first()
    if existing is None:
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
        return True

    trace = (
        db.query(Trace)
        .filter(Trace.id == existing.trace_id, Trace.project_id == project_id)
        .first()
    )
    if trace is None or existing.trace_id != span_data.trace_id:
        raise HTTPException(
            status_code=409,
            detail="Span ID already exists for another trace or project.",
        )

    existing.parent_id = span_data.parent_id if span_data.parent_id else None
    existing.name = span_data.name
    existing.span_type = span_data.span_type
    existing.status = span_data.status
    existing.start_time = span_data.start_time
    existing.end_time = span_data.end_time
    existing.duration_ms = span_data.duration_ms
    existing.attributes = span_data.attributes
    existing.events = span_data.events
    existing.input = span_data.input
    existing.output = span_data.output
    existing.error = span_data.error
    existing.tokens = span_data.tokens
    existing.cost = span_data.cost
    return False


def _topological_sort_spans(spans: list[SpanCreate]) -> list[SpanCreate]:
    """Sort spans so parents come before children when possible.

    Falls back to input order for unresolved spans to preserve ingestion over strict
    graph correctness when malformed parent relationships are provided.
    """
    # Build lookup and find root spans (no parent or parent not in batch)
    span_ids = {s.span_id for s in spans}
    span_by_id = {s.span_id: s for s in spans}

    children: dict[str | None, list[str]] = {None: []}
    indegree: dict[str, int] = {}

    for s in spans:
        parent = s.parent_id if s.parent_id in span_ids else None
        indegree[s.span_id] = 0
        if parent not in children:
            children[parent] = []
        children[parent].append(s.span_id)
        if parent is not None:
            indegree[s.span_id] += 1

    queue = deque([span_id for span_id in span_ids if indegree[span_id] == 0])
    sorted_spans: list[SpanCreate] = []
    sorted_span_ids: set[str] = set()

    while queue:
        span_id = queue.popleft()
        sorted_spans.append(span_by_id[span_id])
        sorted_span_ids.add(span_id)
        for child_id in children.get(span_id, []):
            indegree[child_id] -= 1
            if indegree[child_id] == 0:
                queue.append(child_id)

    if len(sorted_spans) < len(spans):
        unresolved = [sid for sid in span_ids if sid not in sorted_span_ids]
        logger.warning(
            "Topological sort could not fully resolve span order; fallback preserving input order for %s spans",
            unresolved,
        )
        for span in spans:
            if span.span_id in unresolved and span.span_id not in sorted_span_ids:
                sorted_spans.append(span)
                sorted_span_ids.add(span.span_id)

    return sorted_spans


def _to_experiment_summaries(
    traces: list[Trace],
    field: str,
    include_ungrouped: bool,
) -> list[ExperimentSummaryResponse]:
    groups: dict[str, list[Trace]] = {}

    for trace in traces:
        metadata = trace.trace_metadata or {}
        raw_value = metadata.get(field)
        if raw_value is None:
            if not include_ungrouped:
                continue
            value = "ungrouped"
        else:
            value = str(raw_value).strip() or "ungrouped"
            if value == "ungrouped" and not include_ungrouped:
                continue
        groups.setdefault(value, []).append(trace)

    summaries: list[ExperimentSummaryResponse] = []
    for experiment_id, members in groups.items():
        sorted_members = sorted(members, key=lambda t: t.created_at, reverse=True)
        latest = sorted_members[0]
        status_counts = {"running": 0, "success": 0, "error": 0}
        durations: list[float] = []
        total_tokens = 0
        total_cost = 0.0
        total_errors = 0
        for member in members:
            if member.status in status_counts:
                status_counts[member.status] += 1
            if member.duration_ms is not None:
                durations.append(member.duration_ms)
            if member.total_tokens is not None:
                total_tokens += member.total_tokens
            if member.total_cost is not None:
                total_cost += member.total_cost
            total_errors += member.error_count or 0

        sample_compare_pair = None
        if len(sorted_members) >= 2:
            sample_compare_pair = {
                "trace_a_id": str(sorted_members[1].id),
                "trace_b_id": str(sorted_members[0].id),
            }

        summaries.append(
            ExperimentSummaryResponse(
                experiment_id=experiment_id,
                trace_count=len(members),
                latest_trace_id=str(latest.id),
                latest_trace_name=latest.name,
                latest_created_at=latest.created_at,
                statuses=status_counts,
                avg_duration_ms=(sum(durations) / len(durations)) if durations else None,
                total_tokens=total_tokens if total_tokens > 0 else None,
                total_cost=total_cost if total_cost > 0 else None,
                error_rate=(total_errors / len(members)),
                sample_compare_pair=sample_compare_pair,
            )
        )

    summaries.sort(key=lambda exp: exp.latest_created_at, reverse=True)
    return summaries


def _percentile(sorted_values: list[float], percentile: float) -> float | None:
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = (percentile / 100) * (len(sorted_values) - 1)
    lower = int(rank)
    upper = min(lower + 1, len(sorted_values) - 1)
    weight = rank - lower
    return sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight


def _enforce_hard_stop_budget(
    db: Session,
    project: Project,
    payload: list[SpanCreate],
) -> None:
    """Block ingestion when project hard-stop budget would be exceeded."""
    budget = get_project_budget(db, project.id)
    if budget is None or not budget.hard_stop_enabled:
        return

    month_start, month_end = get_month_window()
    month_tokens, month_cost = get_project_month_usage(db, project.id, month_start, month_end)
    batch_tokens = sum(span.tokens or 0 for span in payload)
    batch_cost = sum(float(span.cost or 0.0) for span in payload)

    projected_tokens = month_tokens + batch_tokens
    projected_cost = month_cost + batch_cost

    token_exceeded = (
        budget.monthly_token_limit is not None
        and projected_tokens > budget.monthly_token_limit
    )
    cost_exceeded = (
        budget.monthly_cost_limit is not None
        and projected_cost > budget.monthly_cost_limit
    )

    if token_exceeded or cost_exceeded:
        raise HTTPException(
            status_code=429,
            detail={
                "code": "budget_exceeded",
                "message": "Monthly project budget exceeded. Ingestion blocked by hard stop.",
                "monthly_token_limit": budget.monthly_token_limit,
                "monthly_cost_limit": budget.monthly_cost_limit,
                "month_tokens_used": month_tokens,
                "month_cost_used": month_cost,
                "projected_tokens": projected_tokens,
                "projected_cost": projected_cost,
            },
        )


def _update_trace_regression_guardrail(
    db: Session,
    project_id: Any,
    trace: Trace,
    trace_spans: list[Span],
) -> None:
    """Persist deterministic regression guardrail metadata on non-running traces."""
    if trace.status == "running":
        return

    baseline_trace = (
        db.query(Trace)
        .filter(
            Trace.project_id == project_id,
            Trace.id != trace.id,
            Trace.status.in_(("success", "error")),
        )
        .order_by(Trace.created_at.desc())
        .first()
    )

    metadata = dict(trace.trace_metadata or {})
    if baseline_trace is None:
        metadata["regression_guardrail"] = build_insufficient_baseline_guardrail()
        trace.trace_metadata = metadata
        return

    baseline_spans = db.query(Span).filter(Span.trace_id == baseline_trace.id).all()
    metadata["regression_guardrail"] = build_regression_guardrail(
        baseline_trace,
        baseline_spans,
        trace,
        trace_spans,
    )
    trace.trace_metadata = metadata


@router.post("/spans/batch", status_code=201)
async def ingest_spans(
    payload: list[SpanCreate],
    project: Project = Depends(verify_api_key),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Ingest a batch of spans.

    Creates traces automatically if they don't exist.
    Spans are topologically sorted to ensure parents are inserted before children.
    """
    if not payload:
        return {"ingested": 0}

    _enforce_hard_stop_budget(db, project, payload)

    # Sort spans so parents come before children (prevents FK violations)
    sorted_payload = _topological_sort_spans(payload)

    traces_updated = set()

    for span_data in sorted_payload:
        trace = get_or_create_trace(db, span_data.trace_id, project.id, span_data)
        traces_updated.add(trace.id)
        _upsert_span(db, project.id, span_data)

    # Ensure newly added spans are visible to aggregate queries below.
    db.flush()

    for trace_id in traces_updated:
        trace = db.query(Trace).filter(Trace.id == trace_id).first()
        if trace:
            trace_spans = (
                db.query(Span)
                .join(Trace, Trace.id == Span.trace_id)
                .filter(Span.trace_id == trace_id, Trace.project_id == project.id)
                .all()
            )
            stats = (
                db.query(
                    func.count(Span.id).label("count"),
                    func.sum(Span.tokens).label("tokens"),
                    func.sum(Span.cost).label("cost"),
                    func.sum(case((Span.status == "error", 1), else_=0)).label("errors"),
                    func.max(Span.end_time).label("latest_end"),
                )
                .join(Trace, Trace.id == Span.trace_id)
                .filter(Span.trace_id == trace_id, Trace.project_id == project.id)
                .first()
            )
            trace.span_count = stats.count or 0
            trace.total_tokens = stats.tokens
            trace.total_cost = stats.cost
            trace.error_count = stats.errors or 0

            # Update trace end_time and duration from latest span
            if stats.latest_end:
                trace.end_time = stats.latest_end
                if trace.start_time:
                    delta = (_to_utc(trace.end_time) - _to_utc(trace.start_time)).total_seconds() * 1000
                    trace.duration_ms = delta

            # Update trace status based on span statuses
            has_running = (
                db.query(Span.id)
                .join(Trace, Trace.id == Span.trace_id)
                .filter(
                    Span.trace_id == trace_id,
                    Span.status == "running",
                    Trace.project_id == project.id,
                )
                .first()
            ) is not None
            if has_running:
                trace.status = "running"
            elif trace.error_count > 0:
                trace.status = "error"
            else:
                trace.status = "success"

            _update_trace_regression_guardrail(db, project.id, trace, trace_spans)

    db.commit()

    for trace_id in traces_updated:
        await notify_span_ingested(str(trace_id), len(payload), project_id=str(project.id))

    return {"ingested": len(payload), "traces": len(traces_updated)}


@router.get("/", response_model=TraceListResponse)
async def list_traces(
    project: Project = Depends(verify_api_key),
    db: Session = Depends(get_db),
    limit: int = Query(default=20, le=100),
    offset: int = Query(default=0, ge=0),
    status: str | None = Query(default=None, pattern=STATUS_PATTERN),
    q: str | None = Query(default=None, max_length=256),
    min_tokens: int | None = Query(default=None, ge=0),
    min_cost: float | None = Query(default=None, ge=0),
    has_errors: bool | None = Query(default=None),
    sort_by: str = Query(
        default="created_at",
        pattern="^(created_at|duration_ms|total_tokens|total_cost|span_count|error_count|name)$",
    ),
    sort_order: str = Query(default="desc", pattern="^(asc|desc)$"),
) -> TraceListResponse:
    """List traces with pagination."""
    query = db.query(Trace).filter(Trace.project_id == project.id)

    if status:
        query = query.filter(Trace.status == status)
    if q:
        query = query.filter(Trace.name.ilike(f"%{q}%"))
    if min_tokens is not None:
        query = query.filter(Trace.total_tokens.isnot(None), Trace.total_tokens >= min_tokens)
    if min_cost is not None:
        query = query.filter(Trace.total_cost.isnot(None), Trace.total_cost >= min_cost)
    if has_errors is True:
        query = query.filter(Trace.error_count > 0)
    elif has_errors is False:
        query = query.filter(Trace.error_count == 0)

    sort_column = {
        "created_at": Trace.created_at,
        "duration_ms": Trace.duration_ms,
        "total_tokens": Trace.total_tokens,
        "total_cost": Trace.total_cost,
        "span_count": Trace.span_count,
        "error_count": Trace.error_count,
        "name": Trace.name,
    }[sort_by]

    if sort_order == "asc":
        order_expr = sort_column.asc()
    else:
        order_expr = desc(sort_column)

    total = query.count()
    traces = query.order_by(nullslast(order_expr), Trace.created_at.desc()).offset(offset).limit(limit).all()

    return TraceListResponse(
        traces=[
            TraceResponse(
                id=str(t.id),
                name=t.name,
                status=t.status,
                start_time=t.start_time,
                end_time=t.end_time,
                duration_ms=t.duration_ms,
                metadata=t.trace_metadata or {},
                total_tokens=t.total_tokens,
                total_cost=t.total_cost,
                span_count=t.span_count,
                error_count=t.error_count,
                created_at=t.created_at,
            )
            for t in traces
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/experiments", response_model=ExperimentListResponse)
async def list_experiments(
    project: Project = Depends(verify_api_key),
    db: Session = Depends(get_db),
    field: str = Query(default="run_id", pattern="^(run_id|model|prompt_version)$"),
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    include_ungrouped: bool = Query(default=False),
) -> ExperimentListResponse:
    """Group traces into experiments using metadata fields (run/model/prompt version)."""
    traces = (
        db.query(Trace)
        .filter(Trace.project_id == project.id)
        .order_by(Trace.created_at.desc())
        .limit(5000)
        .all()
    )

    summaries = _to_experiment_summaries(
        traces=traces,
        field=field,
        include_ungrouped=include_ungrouped,
    )

    total = len(summaries)
    paginated = summaries[offset : offset + limit]
    return ExperimentListResponse(
        field=field,
        experiments=paginated,
        total=total,
    )


@router.get("/summary", response_model=TraceSummaryResponse)
async def trace_summary(
    project: Project = Depends(verify_api_key),
    db: Session = Depends(get_db),
    window_days: int = Query(default=7, ge=1, le=90),
) -> TraceSummaryResponse:
    """Return top-level KPIs for traces in the selected time window."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)
    traces = (
        db.query(Trace)
        .filter(Trace.project_id == project.id, Trace.created_at >= cutoff)
        .order_by(Trace.created_at.desc())
        .limit(5000)
        .all()
    )

    if not traces:
        return TraceSummaryResponse(
            window_days=window_days,
            trace_count=0,
            success_rate=0.0,
            running_count=0,
            error_count=0,
            p50_duration_ms=None,
            p95_duration_ms=None,
            avg_tokens=None,
            avg_cost=None,
        )

    trace_count = len(traces)
    success_count = sum(1 for trace in traces if trace.status == "success")
    running_count = sum(1 for trace in traces if trace.status == "running")
    error_count = sum(1 for trace in traces if trace.status == "error")
    durations: list[float] = [trace.duration_ms for trace in traces if trace.duration_ms is not None]
    missing_duration_ids = [trace.id for trace in traces if trace.duration_ms is None]
    if missing_duration_ids:
        fallback_rows = (
            db.query(Span.trace_id, func.sum(Span.duration_ms))
            .filter(Span.trace_id.in_(missing_duration_ids))
            .group_by(Span.trace_id)
            .all()
        )
        durations.extend(
            float(total_duration)
            for _trace_id, total_duration in fallback_rows
            if total_duration is not None
        )
    durations = sorted(durations)
    tokens = [trace.total_tokens for trace in traces if trace.total_tokens is not None]
    costs = [trace.total_cost for trace in traces if trace.total_cost is not None]

    return TraceSummaryResponse(
        window_days=window_days,
        trace_count=trace_count,
        success_rate=(success_count / trace_count) * 100,
        running_count=running_count,
        error_count=error_count,
        p50_duration_ms=_percentile(durations, 50),
        p95_duration_ms=_percentile(durations, 95),
        avg_tokens=(sum(tokens) / len(tokens)) if tokens else None,
        avg_cost=(sum(costs) / len(costs)) if costs else None,
    )


@router.get("/{trace_id}")
async def get_trace(
    trace_id: str,
    project: Project = Depends(verify_api_key),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Get trace details with all spans."""
    trace = (
        db.query(Trace)
        .filter(Trace.id == trace_id, Trace.project_id == project.id)
        .first()
    )

    if not trace:
        raise HTTPException(status_code=404, detail="Trace not found")

    spans = db.query(Span).filter(Span.trace_id == trace_id).all()

    return {
        "trace": trace.to_dict(),
        "spans": [s.to_dict() for s in spans],
    }


@router.get("/{trace_id}/spans")
async def get_trace_spans(
    trace_id: str,
    project: Project = Depends(verify_api_key),
    db: Session = Depends(get_db),
) -> list[SpanResponse]:
    """Get all spans for a trace."""
    trace = (
        db.query(Trace)
        .filter(Trace.id == trace_id, Trace.project_id == project.id)
        .first()
    )
    if not trace:
        raise HTTPException(status_code=404, detail="Trace not found")

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
            events=s.events or [],
            input=s.input,
            output=s.output,
            error=s.error,
            tokens=s.tokens,
            cost=s.cost,
        )
        for s in spans
    ]


@router.delete("/{trace_id}", status_code=204)
async def delete_trace(
    trace_id: str,
    project: Project = Depends(verify_api_key),
    db: Session = Depends(get_db),
) -> None:
    """Delete a trace and all its spans."""
    trace = (
        db.query(Trace)
        .filter(Trace.id == trace_id, Trace.project_id == project.id)
        .first()
    )
    if not trace:
        raise HTTPException(status_code=404, detail="Trace not found")

    # Cascade delete handles spans, but explicit for curated labels
    from app.models import CuratedLabel

    db.query(CuratedLabel).filter(CuratedLabel.trace_id == trace_id).delete()
    db.delete(trace)
    db.commit()
