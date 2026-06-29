"""Regression Watch product endpoints."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from sqlalchemy.orm import Session

from app.auth import verify_api_key
from app.database import get_db
from app.models import Project, RegressionWatchResult, Span, Trace
from app.regression_watch import (
    evaluate_and_persist_regression_watch,
    serialize_regression_watch_result,
)
from app.security import audit_log
from app.validation import ID_PATTERN

router = APIRouter(prefix="/regressions/watch", tags=["Regression Watch"])


@router.get("")
async def list_regression_watch_results(
    project: Project = Depends(verify_api_key),
    db: Session = Depends(get_db),
    risk_level: str | None = Query(default=None, pattern="^(none|low|medium|high|critical)$"),
    status: str | None = Query(default=None, max_length=40),
    group_key: str | None = Query(default=None, max_length=80),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    """List durable Regression Watch results for the current project."""
    query = db.query(RegressionWatchResult).filter(RegressionWatchResult.project_id == project.id)
    if risk_level:
        query = query.filter(RegressionWatchResult.risk_level == risk_level)
    if status:
        query = query.filter(RegressionWatchResult.status == status)
    if group_key:
        query = query.filter(RegressionWatchResult.group_key == group_key)
    total = query.count()
    rows = (
        query.order_by(RegressionWatchResult.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return {
        "results": [serialize_regression_watch_result(row) for row in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/{trace_id}")
async def get_regression_watch_result(
    trace_id: str = Path(min_length=1, max_length=128, pattern=ID_PATTERN),
    project: Project = Depends(verify_api_key),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Get a Regression Watch result for one trace."""
    row = (
        db.query(RegressionWatchResult)
        .filter(
            RegressionWatchResult.project_id == project.id,
            RegressionWatchResult.trace_id == trace_id,
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Regression watch result not found")
    return serialize_regression_watch_result(row)


@router.post("/{trace_id}/rerun")
async def rerun_regression_watch(
    request: Request,
    trace_id: str = Path(min_length=1, max_length=128, pattern=ID_PATTERN),
    project: Project = Depends(verify_api_key),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Re-evaluate Regression Watch for one trace."""
    trace = (
        db.query(Trace)
        .filter(Trace.id == trace_id, Trace.project_id == project.id)
        .first()
    )
    if trace is None:
        raise HTTPException(status_code=404, detail="Trace not found")
    spans = db.query(Span).filter(Span.trace_id == trace.id).all()
    row = evaluate_and_persist_regression_watch(db, trace, spans)
    if row is None:
        raise HTTPException(status_code=422, detail="Running traces cannot be evaluated")
    db.commit()
    db.refresh(row)
    audit_log(
        "regression_watch_rerun",
        request_id=getattr(request.state, "request_id", None),
        project_id=str(project.id),
        trace_id=trace.id,
        result_id=str(row.id),
        risk_level=row.risk_level,
        risk_score=row.risk_score,
    )
    return serialize_regression_watch_result(row)
