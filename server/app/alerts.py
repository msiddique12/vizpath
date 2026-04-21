"""Alert evaluation and delivery services."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

import httpx
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.alert_dispatcher import AlertNotificationJob, enqueue_alert_notification_job
from app.budgeting import get_month_window, get_project_budget, get_project_month_usage
from app.config import settings
from app.models import (
    Project,
    ProjectAlertDestination,
    ProjectAlertEvent,
    ProjectAlertRule,
    Trace,
)
from app.secret_crypto import decrypt_secret_token
from app.webhook_security import validate_webhook_target_url

logger = logging.getLogger(__name__)

ALERT_METRICS = (
    "error_rate_percent",
    "avg_duration_ms",
    "avg_tokens",
    "avg_cost",
    "trace_count",
    "total_tokens",
    "total_cost",
    "active_incident_count",
    "max_incident_risk_score",
    "budget_token_usage_percent",
    "budget_cost_usage_percent",
    "budget_usage_percent",
)
ALERT_OPERATORS = ("gt", "gte", "lt", "lte")
ALERT_DESTINATION_KINDS = ("webhook", "slack_webhook")
ALERT_EVENT_TYPES = (
    "breach",
    "notification_queued",
    "notification_sent",
    "notification_failed",
    "notification_replayed",
    "notification_replay_failed",
)


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
    active_incident_count: int
    max_incident_risk_score: float
    budget_token_usage_percent: float
    budget_cost_usage_percent: float
    budget_usage_percent: float


@dataclass
class AlertRuleEvaluationResult:
    """Evaluation result for a single alert rule."""

    rule: ProjectAlertRule
    current_value: float
    breached: bool
    notification_sent: bool = False
    notification_queued: bool = False


@dataclass(frozen=True)
class AlertEvaluationResult:
    """Project alert evaluation summary."""

    generated_at: datetime
    alert_count: int
    rule_results: list[AlertRuleEvaluationResult]
    window_metrics: list[AlertWindowMetrics]
    notifications_queued: int
    notifications_sent: int
    notifications_failed: int


@dataclass(frozen=True)
class AlertDestinationDeliveryResult:
    """Result of attempting delivery to one destination."""

    destination: ProjectAlertDestination
    delivered: bool


@dataclass(frozen=True)
class AlertReplayResult:
    """Result of replaying a dead-letter alert event."""

    replayed: bool
    queued: bool
    delivered: bool
    message: str


def replay_source_event_id_for(event: ProjectAlertEvent) -> UUID:
    """Return canonical source event id for replay tracking."""
    return event.replay_source_event_id or event.id


def replay_attempt_state(
    db: Session,
    *,
    project_id: UUID,
    source_event_id: UUID,
) -> tuple[int, datetime | None]:
    """Return replay attempt count and most recent attempt timestamp for source event."""
    attempt_rows = (
        db.query(ProjectAlertEvent.created_at)
        .filter(
            ProjectAlertEvent.project_id == project_id,
            ProjectAlertEvent.replay_source_event_id == source_event_id,
            ProjectAlertEvent.event_type.in_(
                ("notification_replayed", "notification_replay_failed")
            ),
        )
        .order_by(ProjectAlertEvent.created_at.desc())
        .all()
    )
    attempts = len(attempt_rows)
    latest = attempt_rows[0][0] if attempts > 0 else None
    return attempts, latest


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
    active_incident_count = 0
    max_incident_risk_score = 0.0
    for trace in traces:
        metadata = trace.trace_metadata if isinstance(trace.trace_metadata, dict) else {}
        guardrail = metadata.get("regression_guardrail")
        if not isinstance(guardrail, dict):
            continue
        if guardrail.get("status") != "risk_detected":
            continue
        workflow = guardrail.get("workflow")
        workflow_status = None
        if isinstance(workflow, dict):
            status_value = workflow.get("status")
            if isinstance(status_value, str):
                workflow_status = status_value.strip().lower()
        if workflow_status == "resolved":
            continue
        risk_score = float(guardrail.get("risk_score") or 0.0)
        active_incident_count += 1
        if risk_score > max_incident_risk_score:
            max_incident_risk_score = risk_score

    budget = get_project_budget(db, project_id)
    month_start, month_end = get_month_window()
    tokens_used, cost_used = get_project_month_usage(db, project_id, month_start, month_end)
    budget_token_usage_percent = 0.0
    budget_cost_usage_percent = 0.0
    if budget and budget.monthly_token_limit:
        budget_token_usage_percent = (tokens_used / float(budget.monthly_token_limit)) * 100.0
    if budget and budget.monthly_cost_limit:
        budget_cost_usage_percent = (cost_used / float(budget.monthly_cost_limit)) * 100.0
    budget_usage_percent = max(budget_token_usage_percent, budget_cost_usage_percent)

    return AlertWindowMetrics(
        window_days=window_days,
        trace_count=trace_count,
        error_rate_percent=error_rate_percent,
        avg_duration_ms=avg_duration_ms,
        avg_tokens=avg_tokens,
        avg_cost=avg_cost,
        total_tokens=sum(tokens),
        total_cost=sum(costs),
        active_incident_count=active_incident_count,
        max_incident_risk_score=max_incident_risk_score,
        budget_token_usage_percent=budget_token_usage_percent,
        budget_cost_usage_percent=budget_cost_usage_percent,
        budget_usage_percent=budget_usage_percent,
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
    if metric == "active_incident_count":
        return float(metrics.active_incident_count)
    if metric == "max_incident_risk_score":
        return float(metrics.max_incident_risk_score)
    if metric == "budget_token_usage_percent":
        return float(metrics.budget_token_usage_percent)
    if metric == "budget_cost_usage_percent":
        return float(metrics.budget_cost_usage_percent)
    if metric == "budget_usage_percent":
        return float(metrics.budget_usage_percent)
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
    try:
        safe_target_url = validate_webhook_target_url(
            target_url,
            allow_private_targets=settings.alert_webhook_allow_private_targets,
            resolve_dns=True,
        )
    except ValueError:
        logger.warning("Alert webhook target rejected by security policy")
        return False

    headers: dict[str, str] = {}
    if secret_token:
        headers["Authorization"] = f"Bearer {secret_token}"
    try:
        response = httpx.post(
            safe_target_url,
            json=payload,
            headers=headers or None,
            timeout=5.0,
            follow_redirects=False,
            trust_env=False,
        )
        return 200 <= response.status_code < 300
    except Exception:
        logger.warning("Alert webhook delivery failed", exc_info=True)
        return False


def _slack_payload_from_alert_payload(payload: dict[str, object]) -> dict[str, object]:
    rule = payload.get("rule")
    rule_name = "unknown-rule"
    metric = "metric"
    operator = "op"
    threshold = "?"
    if isinstance(rule, dict):
        rule_name = str(rule.get("name") or rule_name)
        metric = str(rule.get("metric") or metric)
        operator = str(rule.get("operator") or operator)
        threshold = str(rule.get("threshold") or threshold)
    current_value = str(payload.get("current_value") or "?")
    generated_at = str(payload.get("generated_at") or "")
    project_id = str(payload.get("project_id") or "")

    summary = (
        f"Vizpath alert breached: {rule_name} ({metric} {operator} {threshold}, "
        f"current={current_value})"
    )
    return {
        "text": summary,
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*{summary}*",
                },
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"project_id={project_id} • generated_at={generated_at}",
                    }
                ],
            },
        ],
    }


def _payload_for_destination_kind(
    destination_kind: str,
    payload: dict[str, object],
) -> dict[str, object] | None:
    if destination_kind == "webhook":
        return payload
    if destination_kind == "slack_webhook":
        return _slack_payload_from_alert_payload(payload)
    return None


def _notify_destinations(
    destinations: list[ProjectAlertDestination],
    payload: dict[str, object],
) -> list[AlertDestinationDeliveryResult]:
    results: list[AlertDestinationDeliveryResult] = []
    for destination in destinations:
        destination_payload = _payload_for_destination_kind(destination.kind, payload)
        if destination_payload is None:
            results.append(
                AlertDestinationDeliveryResult(destination=destination, delivered=False)
            )
            continue
        try:
            secret_token = decrypt_secret_token(destination.secret_token)
        except ValueError:
            logger.warning(
                "Alert destination secret token is invalid for destination=%s",
                destination.id,
            )
            results.append(
                AlertDestinationDeliveryResult(destination=destination, delivered=False)
            )
            continue
        results.append(
            AlertDestinationDeliveryResult(
                destination=destination,
                delivered=_post_webhook_json(
                    destination.target_url,
                    destination_payload,
                    secret_token,
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
    notifications_queued = 0
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
        notification_queued = False

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
                if settings.alert_notification_async_enabled:
                    for destination in destinations:
                        try:
                            secret_token = decrypt_secret_token(destination.secret_token)
                        except ValueError:
                            notifications_failed += 1
                            if should_record_events:
                                db.add(
                                    ProjectAlertEvent(
                                        project_id=project.id,
                                        rule_id=rule.id,
                                        destination_id=destination.id,
                                        event_type="notification_failed",
                                        rule_name=rule.name,
                                        metric=rule.metric,
                                        operator=rule.operator,
                                        threshold=rule.threshold,
                                        current_value=current_value,
                                        message="Destination secret token could not be decrypted",
                                    )
                                )
                                touched_db_state = True
                            continue
                        job = AlertNotificationJob(
                            project_id=str(project.id),
                            rule_id=str(rule.id),
                            destination_id=str(destination.id),
                            destination_kind=destination.kind,
                            target_url=destination.target_url,
                            secret_token=secret_token,
                            rule_name=rule.name,
                            metric=rule.metric,
                            operator=rule.operator,
                            threshold=rule.threshold,
                            current_value=current_value,
                            generated_at=evaluated_at.isoformat(),
                        )
                        queued = enqueue_alert_notification_job(job)
                        if queued:
                            notifications_queued += 1
                            notification_queued = True
                            if should_record_events:
                                db.add(
                                    ProjectAlertEvent(
                                        project_id=project.id,
                                        rule_id=rule.id,
                                        destination_id=destination.id,
                                        event_type="notification_queued",
                                        rule_name=rule.name,
                                        metric=rule.metric,
                                        operator=rule.operator,
                                        threshold=rule.threshold,
                                        current_value=current_value,
                                        message=(
                                            f"Alert delivery queued for {destination.kind}"
                                        ),
                                    )
                                )
                                touched_db_state = True
                        else:
                            notifications_failed += 1
                            if should_record_events:
                                db.add(
                                    ProjectAlertEvent(
                                        project_id=project.id,
                                        rule_id=rule.id,
                                        destination_id=destination.id,
                                        event_type="notification_failed",
                                        rule_name=rule.name,
                                        metric=rule.metric,
                                        operator=rule.operator,
                                        threshold=rule.threshold,
                                        current_value=current_value,
                                        message="Alert notification queue is unavailable or full",
                                    )
                                )
                                touched_db_state = True
                else:
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
                notification_queued=notification_queued,
            )
        )

    if touched_db_state:
        db.commit()

    return AlertEvaluationResult(
        generated_at=evaluated_at,
        alert_count=breached_count,
        rule_results=rule_results,
        window_metrics=sorted(window_cache.values(), key=lambda item: item.window_days),
        notifications_queued=notifications_queued,
        notifications_sent=notifications_sent,
        notifications_failed=notifications_failed,
    )


def replay_failed_alert_event(
    db: Session,
    *,
    project: Project,
    failed_event: ProjectAlertEvent,
    source_event_id: UUID | None = None,
    now: datetime | None = None,
) -> AlertReplayResult:
    """Replay a failed alert notification event safely."""
    replayed_at = now or datetime.now(timezone.utc)
    canonical_source_event_id = source_event_id or replay_source_event_id_for(failed_event)

    replay_attempts, latest_attempt_at = replay_attempt_state(
        db,
        project_id=project.id,
        source_event_id=canonical_source_event_id,
    )
    if replay_attempts >= settings.alert_dead_letter_replay_max_attempts:
        return AlertReplayResult(
            replayed=False,
            queued=False,
            delivered=False,
            message=(
                "Replay blocked: maximum replay attempts reached for this dead-letter event."
            ),
        )
    replay_cooldown_seconds = max(
        int(settings.alert_dead_letter_replay_cooldown_seconds or 0),
        0,
    )
    if latest_attempt_at is not None and replay_cooldown_seconds > 0:
        remaining_seconds = replay_cooldown_seconds - int(
            (replayed_at - _to_utc(latest_attempt_at)).total_seconds()
        )
        if remaining_seconds > 0:
            return AlertReplayResult(
                replayed=False,
                queued=False,
                delivered=False,
                message=(
                    "Replay blocked by cooldown. "
                    f"Try again in {remaining_seconds}s."
                ),
            )

    if failed_event.destination_id is None or failed_event.rule_id is None:
        return AlertReplayResult(
            replayed=False,
            queued=False,
            delivered=False,
            message="Failed event is missing destination or rule context.",
        )

    destination = (
        db.query(ProjectAlertDestination)
        .filter(
            ProjectAlertDestination.id == failed_event.destination_id,
            ProjectAlertDestination.project_id == project.id,
        )
        .first()
    )
    if destination is None:
        return AlertReplayResult(
            replayed=False,
            queued=False,
            delivered=False,
            message="Destination no longer exists for replay.",
        )
    if not destination.is_active:
        return AlertReplayResult(
            replayed=False,
            queued=False,
            delivered=False,
            message="Destination is inactive; enable it before replay.",
        )
    if destination.kind not in {"webhook", "slack_webhook"}:
        return AlertReplayResult(
            replayed=False,
            queued=False,
            delivered=False,
            message="Only webhook and Slack webhook destinations are replayable.",
        )

    rule = (
        db.query(ProjectAlertRule)
        .filter(
            ProjectAlertRule.id == failed_event.rule_id,
            ProjectAlertRule.project_id == project.id,
        )
        .first()
    )
    if rule is None:
        return AlertReplayResult(
            replayed=False,
            queued=False,
            delivered=False,
            message="Alert rule no longer exists for replay.",
        )

    try:
        secret_token = decrypt_secret_token(destination.secret_token)
    except ValueError:
        db.add(
            ProjectAlertEvent(
                project_id=project.id,
                rule_id=rule.id,
                destination_id=destination.id,
                replay_source_event_id=canonical_source_event_id,
                event_type="notification_replay_failed",
                rule_name=rule.name,
                metric=rule.metric,
                operator=rule.operator,
                threshold=rule.threshold,
                current_value=failed_event.current_value,
                message="Destination secret token could not be decrypted during replay",
            )
        )
        db.commit()
        return AlertReplayResult(
            replayed=False,
            queued=False,
            delivered=False,
            message="Destination secret token could not be decrypted.",
        )

    current_value = float(
        failed_event.current_value
        if failed_event.current_value is not None
        else rule.threshold
    )
    payload = {
        "type": "alert_breach",
        "generated_at": replayed_at.isoformat(),
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

    if settings.alert_notification_async_enabled:
        queued = enqueue_alert_notification_job(
            AlertNotificationJob(
                project_id=str(project.id),
                rule_id=str(rule.id),
                destination_id=str(destination.id),
                destination_kind=destination.kind,
                target_url=destination.target_url,
                secret_token=secret_token,
                rule_name=rule.name,
                metric=rule.metric,
                operator=rule.operator,
                threshold=rule.threshold,
                current_value=current_value,
                generated_at=replayed_at.isoformat(),
            )
        )
        if queued:
            db.add(
                ProjectAlertEvent(
                    project_id=project.id,
                    rule_id=rule.id,
                    destination_id=destination.id,
                    replay_source_event_id=canonical_source_event_id,
                    event_type="notification_replayed",
                    rule_name=rule.name,
                    metric=rule.metric,
                    operator=rule.operator,
                    threshold=rule.threshold,
                    current_value=current_value,
                    message="Failed alert notification queued for replay",
                )
            )
            db.add(
                ProjectAlertEvent(
                    project_id=project.id,
                    rule_id=rule.id,
                    destination_id=destination.id,
                    replay_source_event_id=canonical_source_event_id,
                    event_type="notification_queued",
                    rule_name=rule.name,
                    metric=rule.metric,
                    operator=rule.operator,
                    threshold=rule.threshold,
                    current_value=current_value,
                    message="Replay delivery queued for webhook destination",
                )
            )
            db.commit()
            return AlertReplayResult(
                replayed=True,
                queued=True,
                delivered=False,
                message="Replay queued for asynchronous delivery.",
            )

        db.add(
            ProjectAlertEvent(
                project_id=project.id,
                rule_id=rule.id,
                destination_id=destination.id,
                replay_source_event_id=canonical_source_event_id,
                event_type="notification_replay_failed",
                rule_name=rule.name,
                metric=rule.metric,
                operator=rule.operator,
                threshold=rule.threshold,
                current_value=current_value,
                message="Replay queue unavailable or full",
            )
        )
        db.commit()
        return AlertReplayResult(
            replayed=False,
            queued=False,
            delivered=False,
            message="Replay queue unavailable or full.",
        )

    delivered = _post_webhook_json(
        destination.target_url,
        payload,
        secret_token,
    )
    db.add(
        ProjectAlertEvent(
            project_id=project.id,
            rule_id=rule.id,
            destination_id=destination.id,
            replay_source_event_id=canonical_source_event_id,
            event_type="notification_replayed" if delivered else "notification_replay_failed",
            rule_name=rule.name,
            metric=rule.metric,
            operator=rule.operator,
            threshold=rule.threshold,
            current_value=current_value,
            message=(
                "Replay delivered successfully"
                if delivered
                else "Replay delivery failed"
            ),
        )
    )
    if delivered:
        db.add(
            ProjectAlertEvent(
                project_id=project.id,
                rule_id=rule.id,
                destination_id=destination.id,
                replay_source_event_id=canonical_source_event_id,
                event_type="notification_sent",
                rule_name=rule.name,
                metric=rule.metric,
                operator=rule.operator,
                threshold=rule.threshold,
                current_value=current_value,
                message="Replay delivery to webhook succeeded",
            )
        )
        rule.last_notified_at = replayed_at
    db.commit()

    return AlertReplayResult(
        replayed=delivered,
        queued=False,
        delivered=delivered,
        message=(
            "Replay delivered successfully."
            if delivered
            else "Replay delivery failed."
        ),
    )
