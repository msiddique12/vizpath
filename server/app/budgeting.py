"""Shared helpers for project budget calculations."""

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import ProjectBudget, Trace

DEFAULT_ALERT_THRESHOLD_PERCENT = 80.0


def get_month_window(reference: datetime | None = None) -> tuple[datetime, datetime]:
    """Return [start, end) boundaries for the current UTC calendar month."""
    now = reference or datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if month_start.month == 12:
        next_month = month_start.replace(year=month_start.year + 1, month=1)
    else:
        next_month = month_start.replace(month=month_start.month + 1)
    return month_start, next_month


def get_project_budget(db: Session, project_id: Any) -> ProjectBudget | None:
    """Fetch budget settings for a project, if configured."""
    return db.query(ProjectBudget).filter(ProjectBudget.project_id == project_id).first()


def get_project_month_usage(
    db: Session,
    project_id: Any,
    month_start: datetime,
    month_end: datetime,
) -> tuple[int, float]:
    """Return aggregate tokens/cost usage for traces in the month window."""
    tokens, cost = (
        db.query(
            func.coalesce(func.sum(Trace.total_tokens), 0),
            func.coalesce(func.sum(Trace.total_cost), 0.0),
        )
        .filter(
            Trace.project_id == project_id,
            Trace.created_at >= month_start,
            Trace.created_at < month_end,
        )
        .first()
    )
    return int(tokens or 0), float(cost or 0.0)
