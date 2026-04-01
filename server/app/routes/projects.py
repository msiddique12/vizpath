"""Project management endpoints."""

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import generate_api_key, hash_api_key, verify_api_key
from app.budgeting import (
    DEFAULT_ALERT_THRESHOLD_PERCENT,
    get_month_window,
    get_project_budget,
    get_project_month_usage,
)
from app.database import get_db
from app.models import Project, ProjectBudget
from app.security import audit_log

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects", tags=["Projects"])


class ProjectCreate(BaseModel):
    """Schema for creating a project."""

    name: str


class ProjectResponse(BaseModel):
    """Response schema for project details."""

    id: str
    name: str
    created_at: str


class ProjectWithKeyResponse(BaseModel):
    """Response with API key (only shown once on creation)."""

    id: str
    name: str
    api_key: str
    created_at: str


class RotateKeyRequest(BaseModel):
    """Request model for key rotation options."""

    grace_period_minutes: int = Field(default=60, ge=1, le=1440)


class RotateKeyResponse(BaseModel):
    """Response returned after key rotation."""

    project_id: str
    api_key: str
    grace_expires_at: str


class RevokeKeyRequest(BaseModel):
    """Request model for key revocation."""

    key_type: str = Field(default="previous", pattern="^(previous|current)$")


class ProjectBudgetResponse(BaseModel):
    """Response schema for project budget configuration."""

    monthly_token_limit: int | None
    monthly_cost_limit: float | None
    alert_threshold_percent: float
    hard_stop_enabled: bool


class ProjectBudgetUpdateRequest(BaseModel):
    """Request schema for project budget updates."""

    monthly_token_limit: int | None = Field(default=None, ge=1, le=1_000_000_000)
    monthly_cost_limit: float | None = Field(default=None, ge=0, le=10_000_000)
    alert_threshold_percent: float | None = Field(default=None, ge=1, le=100)
    hard_stop_enabled: bool | None = None


class ProjectBudgetStatusResponse(BaseModel):
    """Response schema for current budget status and usage."""

    month_start: str
    month_end: str
    tokens_used: int
    cost_used: float
    monthly_token_limit: int | None
    monthly_cost_limit: float | None
    token_usage_percent: float | None
    cost_usage_percent: float | None
    alert_threshold_percent: float
    token_alert_triggered: bool
    cost_alert_triggered: bool
    alert_triggered: bool
    hard_stop_enabled: bool


def _to_budget_response(budget: ProjectBudget | None) -> ProjectBudgetResponse:
    """Serialize a project budget with sensible defaults when unset."""
    if budget is None:
        return ProjectBudgetResponse(
            monthly_token_limit=None,
            monthly_cost_limit=None,
            alert_threshold_percent=DEFAULT_ALERT_THRESHOLD_PERCENT,
            hard_stop_enabled=False,
        )

    return ProjectBudgetResponse(
        monthly_token_limit=budget.monthly_token_limit,
        monthly_cost_limit=budget.monthly_cost_limit,
        alert_threshold_percent=budget.alert_threshold_percent,
        hard_stop_enabled=budget.hard_stop_enabled,
    )


@router.post("/", response_model=ProjectWithKeyResponse, status_code=201)
async def create_project(
    payload: ProjectCreate,
    request: Request,
    db: Session = Depends(get_db),
) -> ProjectWithKeyResponse:
    """
    Create a new project and return its API key.

    The API key is only shown once. Store it securely.
    """
    api_key = generate_api_key()
    key_hash = hash_api_key(api_key)

    project = Project(name=payload.name, api_key_hash=key_hash)
    db.add(project)
    db.commit()
    db.refresh(project)

    logger.info(f"Created project: {project.name} (id={project.id})")
    audit_log(
        "project_created",
        request_id=getattr(request.state, "request_id", None),
        project_id=str(project.id),
        project_name=project.name,
    )

    return ProjectWithKeyResponse(
        id=str(project.id),
        name=project.name,
        api_key=api_key,
        created_at=project.created_at.isoformat(),
    )


@router.get("/", response_model=list[ProjectResponse])
async def list_projects(
    db: Session = Depends(get_db),
) -> list[ProjectResponse]:
    """List all projects."""
    projects = db.query(Project).order_by(Project.created_at.desc()).all()

    return [
        ProjectResponse(
            id=str(p.id),
            name=p.name,
            created_at=p.created_at.isoformat(),
        )
        for p in projects
    ]


@router.get("/me", response_model=ProjectResponse)
async def get_current_project(
    project: Project = Depends(verify_api_key),
) -> ProjectResponse:
    """Get the current project based on API key."""
    return ProjectResponse(
        id=str(project.id),
        name=project.name,
        created_at=project.created_at.isoformat(),
    )


@router.get("/me/budget", response_model=ProjectBudgetResponse)
async def get_project_budget_config(
    project: Project = Depends(verify_api_key),
    db: Session = Depends(get_db),
) -> ProjectBudgetResponse:
    """Get budget settings for the current project."""
    budget = get_project_budget(db, project.id)
    return _to_budget_response(budget)


@router.put("/me/budget", response_model=ProjectBudgetResponse)
async def update_project_budget_config(
    payload: ProjectBudgetUpdateRequest,
    request: Request,
    project: Project = Depends(verify_api_key),
    db: Session = Depends(get_db),
) -> ProjectBudgetResponse:
    """Create or update budget settings for the current project."""
    budget = get_project_budget(db, project.id)
    if budget is None:
        budget = ProjectBudget(
            project_id=project.id,
            monthly_token_limit=None,
            monthly_cost_limit=None,
            alert_threshold_percent=DEFAULT_ALERT_THRESHOLD_PERCENT,
            hard_stop_enabled=False,
        )
        db.add(budget)

    if "monthly_token_limit" in payload.model_fields_set:
        budget.monthly_token_limit = payload.monthly_token_limit
    if "monthly_cost_limit" in payload.model_fields_set:
        budget.monthly_cost_limit = payload.monthly_cost_limit
    if "alert_threshold_percent" in payload.model_fields_set:
        budget.alert_threshold_percent = (
            payload.alert_threshold_percent or DEFAULT_ALERT_THRESHOLD_PERCENT
        )
    if "hard_stop_enabled" in payload.model_fields_set:
        budget.hard_stop_enabled = bool(payload.hard_stop_enabled)

    db.commit()
    db.refresh(budget)

    audit_log(
        "project_budget_updated",
        request_id=getattr(request.state, "request_id", None),
        project_id=str(project.id),
        monthly_token_limit=budget.monthly_token_limit,
        monthly_cost_limit=budget.monthly_cost_limit,
        alert_threshold_percent=budget.alert_threshold_percent,
        hard_stop_enabled=budget.hard_stop_enabled,
    )
    return _to_budget_response(budget)


@router.get("/me/budget/status", response_model=ProjectBudgetStatusResponse)
async def get_project_budget_status(
    project: Project = Depends(verify_api_key),
    db: Session = Depends(get_db),
) -> ProjectBudgetStatusResponse:
    """Return current month budget usage and alert state for the project."""
    budget = get_project_budget(db, project.id)
    month_start, month_end = get_month_window()
    tokens_used, cost_used = get_project_month_usage(db, project.id, month_start, month_end)

    monthly_token_limit = budget.monthly_token_limit if budget else None
    monthly_cost_limit = budget.monthly_cost_limit if budget else None
    threshold = budget.alert_threshold_percent if budget else DEFAULT_ALERT_THRESHOLD_PERCENT
    hard_stop_enabled = budget.hard_stop_enabled if budget else False

    token_usage_percent = (
        (tokens_used / monthly_token_limit) * 100 if monthly_token_limit else None
    )
    cost_usage_percent = (
        (cost_used / monthly_cost_limit) * 100 if monthly_cost_limit else None
    )

    token_alert_triggered = token_usage_percent is not None and token_usage_percent >= threshold
    cost_alert_triggered = cost_usage_percent is not None and cost_usage_percent >= threshold

    return ProjectBudgetStatusResponse(
        month_start=month_start.isoformat(),
        month_end=month_end.isoformat(),
        tokens_used=tokens_used,
        cost_used=cost_used,
        monthly_token_limit=monthly_token_limit,
        monthly_cost_limit=monthly_cost_limit,
        token_usage_percent=token_usage_percent,
        cost_usage_percent=cost_usage_percent,
        alert_threshold_percent=threshold,
        token_alert_triggered=token_alert_triggered,
        cost_alert_triggered=cost_alert_triggered,
        alert_triggered=token_alert_triggered or cost_alert_triggered,
        hard_stop_enabled=hard_stop_enabled,
    )


@router.post("/me/api-key/rotate", response_model=RotateKeyResponse)
async def rotate_api_key(
    payload: RotateKeyRequest,
    request: Request,
    project: Project = Depends(verify_api_key),
    db: Session = Depends(get_db),
) -> RotateKeyResponse:
    """Rotate API key and keep previous key valid during grace window."""
    new_api_key = generate_api_key()
    new_key_hash = hash_api_key(new_api_key)
    now = datetime.now(timezone.utc)

    project.previous_api_key_hash = project.api_key_hash
    project.api_key_hash = new_key_hash
    project.api_key_grace_expires_at = now + timedelta(minutes=payload.grace_period_minutes)
    project.api_key_revoked_at = None
    project.updated_at = now

    db.commit()
    db.refresh(project)
    audit_log(
        "api_key_rotated",
        request_id=getattr(request.state, "request_id", None),
        project_id=str(project.id),
        grace_period_minutes=payload.grace_period_minutes,
    )

    return RotateKeyResponse(
        project_id=str(project.id),
        api_key=new_api_key,
        grace_expires_at=project.api_key_grace_expires_at.isoformat(),
    )


@router.post("/me/api-key/revoke")
async def revoke_api_key(
    payload: RevokeKeyRequest,
    request: Request,
    project: Project = Depends(verify_api_key),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    """Revoke previous key immediately, or current key if explicitly requested."""
    now = datetime.now(timezone.utc)

    if payload.key_type == "previous":
        if project.previous_api_key_hash is None:
            raise HTTPException(status_code=404, detail="No previous key to revoke.")
        project.previous_api_key_hash = None
        project.api_key_grace_expires_at = None
    else:
        project.api_key_revoked_at = now

    project.updated_at = now
    db.commit()
    audit_log(
        "api_key_revoked",
        request_id=getattr(request.state, "request_id", None),
        project_id=str(project.id),
        key_type=payload.key_type,
    )

    return {"status": "revoked", "key_type": payload.key_type}
