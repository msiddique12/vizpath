"""Durable regression watch evaluation helpers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.intelligence.guardrail import (
    build_insufficient_baseline_guardrail,
    build_regression_guardrail,
)
from app.models import RegressionWatchResult, Span, Trace

_GROUP_KEYS = ("route", "task", "prompt_version", "run_id")


def _metadata_value(trace: Trace, key: str) -> str | None:
    metadata = trace.trace_metadata or {}
    value = metadata.get(key)
    if value is None:
        return None
    text = str(value).strip()
    return text[:255] if text else None


def regression_group_for_trace(trace: Trace) -> tuple[str, str]:
    """Return the grouping key/value used for baseline selection."""
    for key in _GROUP_KEYS:
        value = _metadata_value(trace, key)
        if value:
            return key, value
    return "trace_name", trace.name[:255]


def _same_group_filter(trace: Trace, group_key: str, group_value: str):
    if group_key == "trace_name":
        return Trace.name == group_value
    return Trace.trace_metadata[group_key].as_string() == group_value


def select_regression_baseline(
    db: Session,
    trace: Trace,
    *,
    lookback_days: int = 30,
) -> tuple[Trace | None, str, str]:
    """Select the latest same-group baseline trace for a candidate."""
    group_key, group_value = regression_group_for_trace(trace)
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    query = db.query(Trace).filter(
        Trace.project_id == trace.project_id,
        Trace.id != trace.id,
        Trace.status.in_(("success", "error")),
        Trace.created_at >= cutoff,
        _same_group_filter(trace, group_key, group_value),
    )
    if trace.created_at is not None:
        query = query.filter(Trace.created_at <= trace.created_at)
    baseline = query.order_by(Trace.created_at.desc()).first()
    if baseline is None:
        fallback_query = db.query(Trace).filter(
            Trace.project_id == trace.project_id,
            Trace.id != trace.id,
            Trace.status.in_(("success", "error")),
            Trace.created_at >= cutoff,
        )
        if trace.created_at is not None:
            fallback_query = fallback_query.filter(Trace.created_at <= trace.created_at)
        baseline = fallback_query.order_by(Trace.created_at.desc()).first()
    return baseline, group_key, group_value


def _upsert_result(
    db: Session,
    trace: Trace,
    *,
    baseline_trace_id: str | None,
    group_key: str,
    group_value: str,
    guardrail: dict[str, Any],
) -> RegressionWatchResult:
    row = (
        db.query(RegressionWatchResult)
        .filter(
            RegressionWatchResult.project_id == trace.project_id,
            RegressionWatchResult.trace_id == trace.id,
        )
        .first()
    )
    now = datetime.now(timezone.utc)
    values = {
        "baseline_trace_id": baseline_trace_id,
        "group_key": group_key,
        "group_value": group_value,
        "status": str(guardrail.get("status") or "unknown"),
        "risk_score": int(guardrail.get("risk_score") or 0),
        "risk_level": str(guardrail.get("risk_level") or "none"),
        "signals": guardrail.get("signals") or [],
        "metrics": guardrail.get("metrics") or {},
        "top_actions": guardrail.get("top_actions") or [],
        "updated_at": now,
    }
    if row is None:
        row = RegressionWatchResult(
            project_id=trace.project_id,
            trace_id=trace.id,
            created_at=now,
            **values,
        )
        db.add(row)
        return row
    for key, value in values.items():
        setattr(row, key, value)
    return row


def evaluate_and_persist_regression_watch(
    db: Session,
    trace: Trace,
    trace_spans: list[Span] | None = None,
    *,
    lookback_days: int = 30,
) -> RegressionWatchResult | None:
    """Evaluate a trace against a same-group baseline and persist the result."""
    if trace.status == "running":
        return None
    if trace_spans is None:
        trace_spans = db.query(Span).filter(Span.trace_id == trace.id).all()

    baseline, group_key, group_value = select_regression_baseline(
        db,
        trace,
        lookback_days=lookback_days,
    )
    if baseline is None:
        guardrail = build_insufficient_baseline_guardrail()
        baseline_trace_id = None
    else:
        baseline_spans = db.query(Span).filter(Span.trace_id == baseline.id).all()
        guardrail = build_regression_guardrail(
            baseline,
            baseline_spans,
            trace,
            trace_spans,
        )
        baseline_trace_id = str(baseline.id)

    metadata = dict(trace.trace_metadata or {})
    metadata["regression_guardrail"] = guardrail
    trace.trace_metadata = metadata
    return _upsert_result(
        db,
        trace,
        baseline_trace_id=baseline_trace_id,
        group_key=group_key,
        group_value=group_value,
        guardrail=guardrail,
    )


def serialize_regression_watch_result(row: RegressionWatchResult) -> dict[str, Any]:
    """Serialize a durable regression watch result."""
    return {
        "id": str(row.id),
        "trace_id": row.trace_id,
        "trace_name": row.trace.name if row.trace else None,
        "baseline_trace_id": row.baseline_trace_id,
        "baseline_trace_name": row.baseline_trace.name if row.baseline_trace else None,
        "group_key": row.group_key,
        "group_value": row.group_value,
        "status": row.status,
        "risk_score": row.risk_score,
        "risk_level": row.risk_level,
        "signals": row.signals or [],
        "metrics": row.metrics or {},
        "top_actions": row.top_actions or [],
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }
