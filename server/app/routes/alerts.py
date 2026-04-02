"""Project alert rule endpoints for SLO-style monitoring."""

from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from app.auth import verify_api_key
from app.database import get_db
from app.models import Project, ProjectAlertRule, Trace
from app.security import audit_log
from app.validation import normalize_text

router = APIRouter(prefix="/projects/me/alerts", tags=["Alerts"])

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
ALERT_METRIC_PATTERN = f"^({'|'.join(ALERT_METRICS)})$"
ALERT_OPERATOR_PATTERN = f"^({'|'.join(ALERT_OPERATORS)})$"


class AlertRuleCreate(BaseModel):
    """Request schema for creating a project alert rule."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    metric: str = Field(pattern=ALERT_METRIC_PATTERN)
    operator: str = Field(pattern=ALERT_OPERATOR_PATTERN)
    threshold: float
    window_days: int = Field(default=7, ge=1, le=90)
    is_active: bool = True

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value: str | None) -> str:
        normalized = normalize_text(value, field_name="name", max_length=120)
        if normalized is None:
            raise ValueError("name cannot be null")
        return normalized


class AlertRuleUpdate(BaseModel):
    """Request schema for updating a project alert rule."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    metric: str | None = Field(default=None, pattern=ALERT_METRIC_PATTERN)
    operator: str | None = Field(default=None, pattern=ALERT_OPERATOR_PATTERN)
    threshold: float | None = None
    window_days: int | None = Field(default=None, ge=1, le=90)
    is_active: bool | None = None

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        return normalize_text(value, field_name="name", max_length=120)


class AlertRuleResponse(BaseModel):
    """Serialized project alert rule."""

    id: str
    name: str
    metric: str
    operator: str
    threshold: float
    window_days: int
    is_active: bool
    last_triggered_at: str | None
    created_at: str
    updated_at: str | None


class AlertRuleEvaluationResponse(AlertRuleResponse):
    """Alert rule with computed evaluation state."""

    current_value: float
    breached: bool


class AlertWindowMetricsResponse(BaseModel):
    """Computed metrics for a rolling window."""

    window_days: int
    trace_count: int
    error_rate_percent: float
    avg_duration_ms: float
    avg_tokens: float
    avg_cost: float
    total_tokens: int
    total_cost: float


class AlertEvaluationResponse(BaseModel):
    """Project alert evaluation payload."""

    generated_at: str
    alert_count: int
    rules: list[AlertRuleEvaluationResponse]
    window_metrics: list[AlertWindowMetricsResponse]


def _to_rule_response(rule: ProjectAlertRule) -> AlertRuleResponse:
    return AlertRuleResponse(
        id=str(rule.id),
        name=rule.name,
        metric=rule.metric,
        operator=rule.operator,
        threshold=rule.threshold,
        window_days=rule.window_days,
        is_active=rule.is_active,
        last_triggered_at=rule.last_triggered_at.isoformat() if rule.last_triggered_at else None,
        created_at=rule.created_at.isoformat() if rule.created_at else "",
        updated_at=rule.updated_at.isoformat() if rule.updated_at else None,
    )


def _evaluate_operator(operator: str, value: float, threshold: float) -> bool:
    if operator == "gt":
        return value > threshold
    if operator == "gte":
        return value >= threshold
    if operator == "lt":
        return value < threshold
    if operator == "lte":
        return value <= threshold
    raise ValueError(f"Unsupported operator: {operator}")


def _compute_window_metrics(
    db: Session,
    project_id: UUID,
    window_days: int,
) -> AlertWindowMetricsResponse:
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

    return AlertWindowMetricsResponse(
        window_days=window_days,
        trace_count=trace_count,
        error_rate_percent=error_rate_percent,
        avg_duration_ms=avg_duration_ms,
        avg_tokens=avg_tokens,
        avg_cost=avg_cost,
        total_tokens=sum(tokens),
        total_cost=sum(costs),
    )


def _metric_value(metrics: AlertWindowMetricsResponse, metric: str) -> float:
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


def _get_project_rule_or_404(
    db: Session,
    *,
    project_id: UUID,
    rule_id: UUID,
) -> ProjectAlertRule:
    rule = (
        db.query(ProjectAlertRule)
        .filter(
            ProjectAlertRule.id == rule_id,
            ProjectAlertRule.project_id == project_id,
        )
        .first()
    )
    if not rule:
        raise HTTPException(status_code=404, detail="Alert rule not found")
    return rule


@router.get("", response_model=list[AlertRuleResponse])
def list_alert_rules(
    project: Project = Depends(verify_api_key),
    db: Session = Depends(get_db),
) -> list[AlertRuleResponse]:
    """List alert rules for the current project."""
    rules = (
        db.query(ProjectAlertRule)
        .filter(ProjectAlertRule.project_id == project.id)
        .order_by(ProjectAlertRule.created_at.desc())
        .all()
    )
    return [_to_rule_response(rule) for rule in rules]


@router.post("", response_model=AlertRuleResponse, status_code=status.HTTP_201_CREATED)
def create_alert_rule(
    payload: AlertRuleCreate,
    request: Request,
    project: Project = Depends(verify_api_key),
    db: Session = Depends(get_db),
) -> AlertRuleResponse:
    """Create a new alert rule for the current project."""
    rule = ProjectAlertRule(
        project_id=project.id,
        name=payload.name,
        metric=payload.metric,
        operator=payload.operator,
        threshold=payload.threshold,
        window_days=payload.window_days,
        is_active=payload.is_active,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)

    audit_log(
        "project_alert_rule_created",
        request_id=getattr(request.state, "request_id", None),
        project_id=str(project.id),
        rule_id=str(rule.id),
        metric=rule.metric,
        operator=rule.operator,
        threshold=rule.threshold,
        window_days=rule.window_days,
    )
    return _to_rule_response(rule)


@router.put("/{rule_id}", response_model=AlertRuleResponse)
def update_alert_rule(
    rule_id: UUID,
    payload: AlertRuleUpdate,
    request: Request,
    project: Project = Depends(verify_api_key),
    db: Session = Depends(get_db),
) -> AlertRuleResponse:
    """Update an existing alert rule."""
    rule = _get_project_rule_or_404(db, project_id=project.id, rule_id=rule_id)

    if "name" in payload.model_fields_set:
        rule.name = payload.name or rule.name
    if "metric" in payload.model_fields_set and payload.metric is not None:
        rule.metric = payload.metric
    if "operator" in payload.model_fields_set and payload.operator is not None:
        rule.operator = payload.operator
    if "threshold" in payload.model_fields_set and payload.threshold is not None:
        rule.threshold = payload.threshold
    if "window_days" in payload.model_fields_set and payload.window_days is not None:
        rule.window_days = payload.window_days
    if "is_active" in payload.model_fields_set and payload.is_active is not None:
        rule.is_active = payload.is_active

    db.commit()
    db.refresh(rule)

    audit_log(
        "project_alert_rule_updated",
        request_id=getattr(request.state, "request_id", None),
        project_id=str(project.id),
        rule_id=str(rule.id),
        metric=rule.metric,
        operator=rule.operator,
        threshold=rule.threshold,
        window_days=rule.window_days,
        is_active=rule.is_active,
    )
    return _to_rule_response(rule)


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_alert_rule(
    rule_id: UUID,
    request: Request,
    project: Project = Depends(verify_api_key),
    db: Session = Depends(get_db),
) -> Response:
    """Delete an alert rule."""
    rule = _get_project_rule_or_404(db, project_id=project.id, rule_id=rule_id)
    db.delete(rule)
    db.commit()
    audit_log(
        "project_alert_rule_deleted",
        request_id=getattr(request.state, "request_id", None),
        project_id=str(project.id),
        rule_id=str(rule_id),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/evaluate", response_model=AlertEvaluationResponse)
def evaluate_alert_rules(
    request: Request,
    persist: bool = Query(default=False),
    project: Project = Depends(verify_api_key),
    db: Session = Depends(get_db),
) -> AlertEvaluationResponse:
    """Evaluate all active rules against rolling trace-window metrics."""
    rules = (
        db.query(ProjectAlertRule)
        .filter(ProjectAlertRule.project_id == project.id)
        .order_by(ProjectAlertRule.created_at.asc())
        .all()
    )

    window_cache: dict[int, AlertWindowMetricsResponse] = {}
    evaluated_rules: list[AlertRuleEvaluationResponse] = []
    breached_count = 0
    now = datetime.now(timezone.utc)

    for rule in rules:
        metrics = window_cache.get(rule.window_days)
        if metrics is None:
            metrics = _compute_window_metrics(db, project.id, rule.window_days)
            window_cache[rule.window_days] = metrics

        current_value = _metric_value(metrics, rule.metric)
        breached = (
            rule.is_active
            and _evaluate_operator(rule.operator, current_value, rule.threshold)
        )
        if breached:
            breached_count += 1
            if persist:
                rule.last_triggered_at = now

        evaluated_rules.append(
            AlertRuleEvaluationResponse(
                **_to_rule_response(rule).model_dump(),
                current_value=current_value,
                breached=breached,
            )
        )

    if persist:
        db.commit()

    audit_log(
        "project_alert_rules_evaluated",
        request_id=getattr(request.state, "request_id", None),
        project_id=str(project.id),
        rule_count=len(rules),
        breached_count=breached_count,
        persist=persist,
    )

    return AlertEvaluationResponse(
        generated_at=now.isoformat(),
        alert_count=breached_count,
        rules=evaluated_rules,
        window_metrics=sorted(window_cache.values(), key=lambda item: item.window_days),
    )
