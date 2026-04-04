"""Background scheduler for periodic alert evaluation."""

from __future__ import annotations

import asyncio
import logging

from app.alerts import evaluate_project_alerts
from app.config import settings
from app.database import get_db_session
from app.models import Project

logger = logging.getLogger(__name__)


def run_alert_scheduler_tick(*, notify: bool) -> tuple[int, int, int]:
    """Run one scheduler pass across all projects."""
    with get_db_session() as db:
        projects = db.query(Project).all()
        total_rules = 0
        total_breaches = 0

        for project in projects:
            try:
                result = evaluate_project_alerts(db, project, persist=True, notify=notify)
            except Exception:
                db.rollback()
                logger.warning(
                    "Alert scheduler failed for project=%s",
                    project.id,
                    exc_info=True,
                )
                continue
            total_rules += len(result.rule_results)
            total_breaches += result.alert_count

        return len(projects), total_rules, total_breaches


async def run_alert_scheduler(stop_event: asyncio.Event) -> None:
    """Run periodic alert evaluation until stop_event is set."""
    interval_seconds = max(int(settings.alert_scheduler_interval_seconds), 1)
    while not stop_event.is_set():
        try:
            project_count, rule_count, breach_count = run_alert_scheduler_tick(
                notify=settings.alert_scheduler_notify
            )
            if project_count:
                logger.info(
                    "Alert scheduler tick complete: projects=%d rules=%d breaches=%d",
                    project_count,
                    rule_count,
                    breach_count,
                )
        except Exception:
            logger.warning("Alert scheduler tick failed", exc_info=True)

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
        except asyncio.TimeoutError:
            continue
