"""Project alert rule and destination endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from app.alerts import (
    ALERT_DESTINATION_KINDS,
    ALERT_EVENT_TYPES,
    ALERT_METRICS,
    ALERT_OPERATORS,
    AlertWindowMetrics,
    evaluate_project_alerts,
)
from app.auth import verify_api_key
from app.config import settings
from app.database import get_db
from app.models import Project, ProjectAlertDestination, ProjectAlertEvent, ProjectAlertRule
from app.secret_crypto import encrypt_secret_token
from app.security import audit_log
from app.validation import normalize_text
from app.webhook_security import validate_webhook_target_url

router = APIRouter(prefix="/projects/me/alerts", tags=["Alerts"])

ALERT_METRIC_PATTERN = f"^({'|'.join(ALERT_METRICS)})$"
ALERT_OPERATOR_PATTERN = f"^({'|'.join(ALERT_OPERATORS)})$"
ALERT_DESTINATION_KIND_PATTERN = f"^({'|'.join(ALERT_DESTINATION_KINDS)})$"
ALERT_EVENT_TYPE_PATTERN = f"^({'|'.join(ALERT_EVENT_TYPES)})$"


class AlertRuleCreate(BaseModel):
    """Request schema for creating a project alert rule."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    metric: str = Field(pattern=ALERT_METRIC_PATTERN)
    operator: str = Field(pattern=ALERT_OPERATOR_PATTERN)
    threshold: float
    window_days: int = Field(default=7, ge=1, le=90)
    is_active: bool = True
    notification_cooldown_minutes: int = Field(default=60, ge=0, le=10080)

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
    notification_cooldown_minutes: int | None = Field(default=None, ge=0, le=10080)

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
    notification_cooldown_minutes: int
    last_triggered_at: str | None
    last_notified_at: str | None
    created_at: str
    updated_at: str | None


class AlertRuleEvaluationResponse(AlertRuleResponse):
    """Alert rule with computed evaluation state."""

    current_value: float
    breached: bool
    notification_sent: bool = False


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
    notifications_sent: int
    notifications_failed: int
    rules: list[AlertRuleEvaluationResponse]
    window_metrics: list[AlertWindowMetricsResponse]


class AlertDestinationCreate(BaseModel):
    """Request schema for creating an alert destination."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    kind: str = Field(default="webhook", pattern=ALERT_DESTINATION_KIND_PATTERN)
    target_url: str = Field(min_length=1, max_length=512)
    secret_token: str | None = Field(default=None, max_length=255)
    is_active: bool = True

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value: str | None) -> str:
        normalized = normalize_text(value, field_name="name", max_length=120)
        if normalized is None:
            raise ValueError("name cannot be null")
        return normalized

    @field_validator("target_url")
    @classmethod
    def validate_target_url(cls, value: str) -> str:
        return validate_webhook_target_url(
            value,
            allow_private_targets=settings.alert_webhook_allow_private_targets,
            resolve_dns=False,
        )

    @field_validator("secret_token", mode="before")
    @classmethod
    def normalize_secret_token(cls, value: str | None) -> str | None:
        return normalize_text(value, field_name="secret_token", max_length=255)


class AlertDestinationUpdate(BaseModel):
    """Request schema for updating an alert destination."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    kind: str | None = Field(default=None, pattern=ALERT_DESTINATION_KIND_PATTERN)
    target_url: str | None = Field(default=None, min_length=1, max_length=512)
    secret_token: str | None = Field(default=None, max_length=255)
    is_active: bool | None = None

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        return normalize_text(value, field_name="name", max_length=120)

    @field_validator("target_url")
    @classmethod
    def validate_target_url(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return validate_webhook_target_url(
            value,
            allow_private_targets=settings.alert_webhook_allow_private_targets,
            resolve_dns=False,
        )

    @field_validator("secret_token", mode="before")
    @classmethod
    def normalize_secret_token(cls, value: str | None) -> str | None:
        return normalize_text(value, field_name="secret_token", max_length=255)


class AlertDestinationResponse(BaseModel):
    """Serialized project alert destination."""

    id: str
    name: str
    kind: str
    target_url: str
    is_active: bool
    created_at: str
    updated_at: str | None


class AlertEventResponse(BaseModel):
    """Serialized project alert event."""

    id: str
    event_type: str
    rule_id: str | None
    destination_id: str | None
    rule_name: str | None
    metric: str | None
    operator: str | None
    threshold: float | None
    current_value: float | None
    message: str | None
    created_at: str


def _to_rule_response(rule: ProjectAlertRule) -> AlertRuleResponse:
    return AlertRuleResponse(
        id=str(rule.id),
        name=rule.name,
        metric=rule.metric,
        operator=rule.operator,
        threshold=rule.threshold,
        window_days=rule.window_days,
        is_active=rule.is_active,
        notification_cooldown_minutes=rule.notification_cooldown_minutes,
        last_triggered_at=rule.last_triggered_at.isoformat() if rule.last_triggered_at else None,
        last_notified_at=rule.last_notified_at.isoformat() if rule.last_notified_at else None,
        created_at=rule.created_at.isoformat() if rule.created_at else "",
        updated_at=rule.updated_at.isoformat() if rule.updated_at else None,
    )


def _to_destination_response(destination: ProjectAlertDestination) -> AlertDestinationResponse:
    return AlertDestinationResponse(
        id=str(destination.id),
        name=destination.name,
        kind=destination.kind,
        target_url=destination.target_url,
        is_active=destination.is_active,
        created_at=destination.created_at.isoformat() if destination.created_at else "",
        updated_at=destination.updated_at.isoformat() if destination.updated_at else None,
    )


def _to_window_metrics_response(metrics: AlertWindowMetrics) -> AlertWindowMetricsResponse:
    return AlertWindowMetricsResponse(
        window_days=metrics.window_days,
        trace_count=metrics.trace_count,
        error_rate_percent=metrics.error_rate_percent,
        avg_duration_ms=metrics.avg_duration_ms,
        avg_tokens=metrics.avg_tokens,
        avg_cost=metrics.avg_cost,
        total_tokens=metrics.total_tokens,
        total_cost=metrics.total_cost,
    )


def _to_event_response(event: ProjectAlertEvent) -> AlertEventResponse:
    return AlertEventResponse(
        id=str(event.id),
        event_type=event.event_type,
        rule_id=str(event.rule_id) if event.rule_id else None,
        destination_id=str(event.destination_id) if event.destination_id else None,
        rule_name=event.rule_name,
        metric=event.metric,
        operator=event.operator,
        threshold=event.threshold,
        current_value=event.current_value,
        message=event.message,
        created_at=event.created_at.isoformat() if event.created_at else "",
    )


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


def _get_project_destination_or_404(
    db: Session,
    *,
    project_id: UUID,
    destination_id: UUID,
) -> ProjectAlertDestination:
    destination = (
        db.query(ProjectAlertDestination)
        .filter(
            ProjectAlertDestination.id == destination_id,
            ProjectAlertDestination.project_id == project_id,
        )
        .first()
    )
    if not destination:
        raise HTTPException(status_code=404, detail="Alert destination not found")
    return destination


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
        notification_cooldown_minutes=payload.notification_cooldown_minutes,
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

    if "name" in payload.model_fields_set and payload.name is not None:
        rule.name = payload.name
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
    if (
        "notification_cooldown_minutes" in payload.model_fields_set
        and payload.notification_cooldown_minutes is not None
    ):
        rule.notification_cooldown_minutes = payload.notification_cooldown_minutes

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


@router.get("/destinations", response_model=list[AlertDestinationResponse])
def list_alert_destinations(
    project: Project = Depends(verify_api_key),
    db: Session = Depends(get_db),
) -> list[AlertDestinationResponse]:
    """List alert delivery destinations for the current project."""
    destinations = (
        db.query(ProjectAlertDestination)
        .filter(ProjectAlertDestination.project_id == project.id)
        .order_by(ProjectAlertDestination.created_at.desc())
        .all()
    )
    return [_to_destination_response(destination) for destination in destinations]


@router.post(
    "/destinations",
    response_model=AlertDestinationResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_alert_destination(
    payload: AlertDestinationCreate,
    request: Request,
    project: Project = Depends(verify_api_key),
    db: Session = Depends(get_db),
) -> AlertDestinationResponse:
    """Create a new alert delivery destination for the current project."""
    try:
        encrypted_secret_token = encrypt_secret_token(payload.secret_token)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    destination = ProjectAlertDestination(
        project_id=project.id,
        name=payload.name,
        kind=payload.kind,
        target_url=payload.target_url,
        secret_token=encrypted_secret_token,
        is_active=payload.is_active,
    )
    db.add(destination)
    db.commit()
    db.refresh(destination)

    audit_log(
        "project_alert_destination_created",
        request_id=getattr(request.state, "request_id", None),
        project_id=str(project.id),
        destination_id=str(destination.id),
        kind=destination.kind,
    )
    return _to_destination_response(destination)


@router.put("/destinations/{destination_id}", response_model=AlertDestinationResponse)
def update_alert_destination(
    destination_id: UUID,
    payload: AlertDestinationUpdate,
    request: Request,
    project: Project = Depends(verify_api_key),
    db: Session = Depends(get_db),
) -> AlertDestinationResponse:
    """Update an existing alert delivery destination."""
    destination = _get_project_destination_or_404(
        db,
        project_id=project.id,
        destination_id=destination_id,
    )

    if "name" in payload.model_fields_set and payload.name is not None:
        destination.name = payload.name
    if "kind" in payload.model_fields_set and payload.kind is not None:
        destination.kind = payload.kind
    if "target_url" in payload.model_fields_set and payload.target_url is not None:
        destination.target_url = payload.target_url
    if "secret_token" in payload.model_fields_set:
        if payload.secret_token is None:
            destination.secret_token = None
        else:
            try:
                destination.secret_token = encrypt_secret_token(payload.secret_token)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
    if "is_active" in payload.model_fields_set and payload.is_active is not None:
        destination.is_active = payload.is_active

    db.commit()
    db.refresh(destination)

    audit_log(
        "project_alert_destination_updated",
        request_id=getattr(request.state, "request_id", None),
        project_id=str(project.id),
        destination_id=str(destination.id),
        is_active=destination.is_active,
    )
    return _to_destination_response(destination)


@router.delete("/destinations/{destination_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_alert_destination(
    destination_id: UUID,
    request: Request,
    project: Project = Depends(verify_api_key),
    db: Session = Depends(get_db),
) -> Response:
    """Delete an alert destination."""
    destination = _get_project_destination_or_404(
        db,
        project_id=project.id,
        destination_id=destination_id,
    )
    db.delete(destination)
    db.commit()
    audit_log(
        "project_alert_destination_deleted",
        request_id=getattr(request.state, "request_id", None),
        project_id=str(project.id),
        destination_id=str(destination_id),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/events", response_model=list[AlertEventResponse])
def list_alert_events(
    event_type: str | None = Query(default=None, pattern=ALERT_EVENT_TYPE_PATTERN),
    rule_id: UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    project: Project = Depends(verify_api_key),
    db: Session = Depends(get_db),
) -> list[AlertEventResponse]:
    """List alert event history for the current project."""
    query = db.query(ProjectAlertEvent).filter(ProjectAlertEvent.project_id == project.id)
    if event_type:
        query = query.filter(ProjectAlertEvent.event_type == event_type)
    if rule_id:
        query = query.filter(ProjectAlertEvent.rule_id == rule_id)

    events = (
        query.order_by(ProjectAlertEvent.created_at.desc())
        .limit(limit)
        .offset(offset)
        .all()
    )
    return [_to_event_response(event) for event in events]


@router.get("/evaluate", response_model=AlertEvaluationResponse)
def evaluate_alert_rules(
    request: Request,
    persist: bool = Query(default=False),
    notify: bool = Query(default=False),
    project: Project = Depends(verify_api_key),
    db: Session = Depends(get_db),
) -> AlertEvaluationResponse:
    """Evaluate all active rules against rolling trace-window metrics."""
    evaluation = evaluate_project_alerts(
        db,
        project,
        persist=persist,
        notify=notify,
    )

    audit_log(
        "project_alert_rules_evaluated",
        request_id=getattr(request.state, "request_id", None),
        project_id=str(project.id),
        rule_count=len(evaluation.rule_results),
        breached_count=evaluation.alert_count,
        persist=persist,
        notify=notify,
        notifications_sent=evaluation.notifications_sent,
        notifications_failed=evaluation.notifications_failed,
    )

    return AlertEvaluationResponse(
        generated_at=evaluation.generated_at.isoformat(),
        alert_count=evaluation.alert_count,
        notifications_sent=evaluation.notifications_sent,
        notifications_failed=evaluation.notifications_failed,
        rules=[
            AlertRuleEvaluationResponse(
                **_to_rule_response(result.rule).model_dump(),
                current_value=result.current_value,
                breached=result.breached,
                notification_sent=result.notification_sent,
            )
            for result in evaluation.rule_results
        ],
        window_metrics=[
            _to_window_metrics_response(item) for item in evaluation.window_metrics
        ],
    )
