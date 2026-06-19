"""Trace retention cleanup utilities."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db_session
from app.models import CuratedLabel, Trace

logger = logging.getLogger(__name__)


def prune_expired_traces(
    db: Session,
    *,
    now: datetime | None = None,
    retention_days: int | None = None,
    batch_size: int = 1000,
) -> int:
    """Delete traces older than the configured retention window."""
    effective_days = retention_days if retention_days is not None else settings.trace_retention_days
    effective_now = now or datetime.now(timezone.utc)
    cutoff = effective_now - timedelta(days=effective_days)

    expired_traces = (
        db.query(Trace)
        .filter(Trace.created_at < cutoff)
        .order_by(Trace.created_at.asc())
        .limit(batch_size)
        .all()
    )
    if not expired_traces:
        return 0

    trace_ids = [trace.id for trace in expired_traces]
    db.query(CuratedLabel).filter(CuratedLabel.trace_id.in_(trace_ids)).delete(
        synchronize_session=False
    )
    for trace in expired_traces:
        db.delete(trace)
    db.flush()
    return len(expired_traces)


async def run_trace_retention_sweeper(stop_event: asyncio.Event) -> None:
    """Periodically prune traces beyond the configured retention period."""
    while not stop_event.is_set():
        try:
            with get_db_session() as db:
                deleted = prune_expired_traces(db)
                if deleted:
                    logger.info("Pruned %d expired traces", deleted)
        except Exception:
            logger.warning("Trace retention sweep failed", exc_info=True)

        try:
            await asyncio.wait_for(
                stop_event.wait(),
                timeout=settings.trace_retention_sweep_interval_seconds,
            )
        except asyncio.TimeoutError:
            continue
