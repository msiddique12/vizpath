"""Alert evaluation and delivery services."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

import httpx
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import (
    Project,
    ProjectAlertDestination,
    ProjectAlertEvent,
    ProjectAlertRule,
    Trace,
)

logger = logging.getLogger(__name__)

ALERT_METRICS = (
    "error_rate_percent",
    "avg_duration_ms",
    "avg_tokens",
    "avg_cost",
    "trace_count",
    "total_tokens",
    "total_cost",
)
ALERT_OPERATORS = ("gt", "gte", "lt", "lte")
ALERT_DESTINATION_KINDS = ("webhook",)
ALERT_EVENT_TYPES = ("breach", "notification_sent", "notification_failed")


@dataclass(frozen=True)
class AlertWindowMetrics:
    """Computed rolling metrics for a time window."""

    window_days: int
    trace_count: int
    error_rate_percent: float
    avg_duration_ms: float
    avg_tokens: float
    avg_cost: float
    total_tokens: int
    total_cost: float


@dataclass
class AlertRuleEvaluationResult:
    """Evaluation result for a single alert rule."""

    rule: ProjectAlertRule
    current_value: float
    breached: bool
    notification_sent: bool = False


@dataclass(frozen=True)
class AlertEvaluationResult:
    """Project alert evaluation summary."""

    generated_at: datetime
    alert_count: int
    rule_results: list[AlertRuleEvaluationResult]
    window_metrics: list[AlertWindowMetrics]
    notifications_sent: int
    notifications_failed: int


@dataclass(frozen=True)
class AlertDestinationDeliveryResult:
    """Result of attempting delivery to one destination."""

    destination: ProjectAlertDestination
    delivered: bool


def evaluate_operator(operator: str, value: float, threshold: float) -> bool:
    """Compare value with threshold using a supported operator."""
    if operator == "gt":
        return value > threshold
    if operator == "gte":
        return value >= threshold
    if operator == "lt":
        return value < threshold
    if operator == "lte":
        return value <= threshold
    raise ValueError(f"Unsupported operator: {operator}")


def compute_window_metrics(db: Session, project_id: UUID, window_days: int) -> AlertWindowMetrics:
    """Compute project trace metrics for the requested rolling window."""
    window_start = datetime.now(timezone.utc) - timedelta(days=window_days)
    traces = (
        db.query(Trace)
        .filter(Trace.project_id == project_id, Trace.created_at >= window_start)
        .all()
    )

    trace_count = len(traces)
    error_trace_count = sum(
        1
        for trace in traces
        if trace.status == "error" or (trace.error_count or 0) > 0
    )
    durations = [float(trace.duration_ms) for trace in traces if trace.duration_ms is not None]
    tokens = [int(trace.total_tokens) for trace in traces if trace.total_tokens is not None]
    costs = [float(trace.total_cost) for trace in traces if trace.total_cost is not None]

    avg_duration_ms = (sum(durations) / len(durations)) if durations else 0.0
    avg_tokens = (sum(tokens) / len(tokens)) if tokens else 0.0
    avg_cost = (sum(costs) / len(costs)) if costs else 0.0
    error_rate_percent = (error_trace_count / trace_count) * 100 if trace_count else 0.0

    return AlertWindowMetrics(
        window_days=window_days,
        trace_count=trace_count,
        error_rate_percent=error_rate_percent,
        avg_duration_ms=avg_duration_ms,
        avg_tokens=avg_tokens,
        avg_cost=avg_cost,
        total_tokens=sum(tokens),
        total_cost=sum(costs),
    )


def metric_value(metrics: AlertWindowMetrics, metric: str) -> float:
    """Get metric value by key from computed window metrics."""
    if metric == "trace_count":
        return float(metrics.trace_count)
    if metric == "total_tokens":
        return float(metrics.total_tokens)
    if metric == "total_cost":
        return float(metrics.total_cost)
    if metric == "error_rate_percent":
        return float(metrics.error_rate_percent)
    if metric == "avg_duration_ms":
        return float(metrics.avg_duration_ms)
    if metric == "avg_tokens":
        return float(metrics.avg_tokens)
    if metric == "avg_cost":
        return float(metrics.avg_cost)
    raise ValueError(f"Unsupported metric: {metric}")


def _to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _is_notification_in_cooldown(rule: ProjectAlertRule, now: datetime) -> bool:
    cooldown = max(int(rule.notification_cooldown_minutes or 0), 0)
    if cooldown == 0 or rule.last_notified_at is None:
        return False
    return (now - _to_utc(rule.last_notified_at)) < timedelta(minutes=cooldown)


def _post_webhook_json(
    target_url: str,
    payload: dict[str, object],
    secret_token: str | None = None,
) -> bool:
    headers: dict[str, str] = {}
    if secret_token:
        headers["Authorization"] = f"Bearer {secret_token}"
    try:
        response = httpx.post(
            target_url,
            json=payload,
            headers=headers or None,
            timeout=5.0,
            follow_redirects=False,
        )
        return 200 <= response.status_code < 300
    except Exception:
        logger.warning("Alert webhook delivery failed", exc_info=True)
        return False


def _notify_destinations(
    destinations: list[ProjectAlertDestination],
    payload: dict[str, object],
) -> list[AlertDestinationDeliveryResult]:
    results: list[AlertDestinationDeliveryResult] = []
    for destination in destinations:
        if destination.kind != "webhook":
            results.append(
                AlertDestinationDeliveryResult(destination=destination, delivered=False)
            )
            continue
        results.append(
            AlertDestinationDeliveryResult(
                destination=destination,
                delivered=_post_webhook_json(
                    destination.target_url,
                    payload,
                    destination.secret_token,
                ),
            )
        )
    return results


def evaluate_project_alerts(
    db: Session,
    project: Project,
    *,
    persist: bool = False,
    notify: bool = False,
    now: datetime | None = None,
) -> AlertEvaluationResult:
    """Evaluate alert rules for one project and optionally notify destinations."""
    evaluated_at = now or datetime.now(timezone.utc)
    rules = (
        db.query(ProjectAlertRule)
        .filter(ProjectAlertRule.project_id == project.id)
        .order_by(ProjectAlertRule.created_at.asc())
        .all()
    )
    destinations = []
    if notify:
        destinations = (
            db.query(ProjectAlertDestination)
            .filter(
                ProjectAlertDestination.project_id == project.id,
                ProjectAlertDestination.is_active.is_(True),
            )
            .order_by(ProjectAlertDestination.created_at.asc())
            .all()
        )

    window_cache: dict[int, AlertWindowMetrics] = {}
    rule_results: list[AlertRuleEvaluationResult] = []
    breached_count = 0
    notifications_sent = 0
    notifications_failed = 0
    touched_db_state = False
    should_record_events = persist or notify
    latest_breach_event_by_rule: dict[UUID, datetime] = {}

    if should_record_events and rules:
        rule_ids = [rule.id for rule in rules]
        latest_breach_rows = (
            db.query(
                ProjectAlertEvent.rule_id,
                func.max(ProjectAlertEvent.created_at),
            )
            .filter(
                ProjectAlertEvent.project_id == project.id,
                ProjectAlertEvent.event_type == "breach",
                ProjectAlertEvent.rule_id.in_(rule_ids),
            )
            .group_by(ProjectAlertEvent.rule_id)
            .all()
        )
        latest_breach_event_by_rule = {
            rule_id: created_at
            for rule_id, created_at in latest_breach_rows
            if rule_id is not None and created_at is not None
        }

    for rule in rules:
        metrics = window_cache.get(rule.window_days)
        if metrics is None:
            metrics = compute_window_metrics(db, project.id, rule.window_days)
            window_cache[rule.window_days] = metrics

        current_value = metric_value(metrics, rule.metric)
        breached = rule.is_active and evaluate_operator(rule.operator, current_value, rule.threshold)
        notification_sent = False

        if breached:
            breached_count += 1
            if persist:
                rule.last_triggered_at = evaluated_at
                touched_db_state = True

            if should_record_events:
                breach_event_cooldown = timedelta(
                    minutes=max(int(rule.notification_cooldown_minutes or 0), 1)
                )
                last_breach_event_at = latest_breach_event_by_rule.get(rule.id)
                should_emit_breach_event = (
                    last_breach_event_at is None
                    or (evaluated_at - _to_utc(last_breach_event_at)) >= breach_event_cooldown
                )
                if should_emit_breach_event:
                    db.add(
                        ProjectAlertEvent(
                            project_id=project.id,
                            rule_id=rule.id,
                            event_type="breach",
                            rule_name=rule.name,
                            metric=rule.metric,
                            operator=rule.operator,
                            threshold=rule.threshold,
                            current_value=current_value,
                            message=(
                                f"Rule breached: {rule.metric} {rule.operator} {rule.threshold}, "
                                f"current={current_value}"
                            ),
                        )
                    )
                    touched_db_state = True
                    latest_breach_event_by_rule[rule.id] = evaluated_at

            if notify and destinations and not _is_notification_in_cooldown(rule, evaluated_at):
                payload = {
                    "type": "alert_breach",
                    "generated_at": evaluated_at.isoformat(),
                    "project_id": str(project.id),
                    "rule": {
                        "id": str(rule.id),
                        "name": rule.name,
                        "metric": rule.metric,
                        "operator": rule.operator,
                        "threshold": rule.threshold,
                        "window_days": rule.window_days,
                    },
                    "current_value": current_value,
                }
                delivery_results = _notify_destinations(destinations, payload)
                sent = sum(1 for result in delivery_results if result.delivered)
                failed = len(delivery_results) - sent
                notifications_sent += sent
                notifications_failed += failed

                for result in delivery_results:
                    if should_record_events:
                        db.add(
                            ProjectAlertEvent(
                                project_id=project.id,
                                rule_id=rule.id,
                                destination_id=result.destination.id,
                                event_type=(
                                    "notification_sent"
                                    if result.delivered
                                    else "notification_failed"
                                ),
                                rule_name=rule.name,
                                metric=rule.metric,
                                operator=rule.operator,
                                threshold=rule.threshold,
                                current_value=current_value,
                                message=(
                                    f"Alert delivery to {result.destination.kind} "
                                    f"{'succeeded' if result.delivered else 'failed'}"
                                ),
                            )
                        )
                        touched_db_state = True

                if sent > 0:
                    rule.last_notified_at = evaluated_at
                    touched_db_state = True
                    notification_sent = True

        rule_results.append(
            AlertRuleEvaluationResult(
                rule=rule,
                current_value=current_value,
                breached=breached,
                notification_sent=notification_sent,
            )
        )

    if touched_db_state:
        db.commit()

    return AlertEvaluationResult(
        generated_at=evaluated_at,
        alert_count=breached_count,
        rule_results=rule_results,
        window_metrics=sorted(window_cache.values(), key=lambda item: item.window_days),
        notifications_sent=notifications_sent,
        notifications_failed=notifications_failed,
    )
