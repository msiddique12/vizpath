"""Project management endpoints."""

import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from app.auth import (
    api_key_fingerprint,
    generate_api_key,
    hash_api_key,
    normalize_api_key_scopes,
    verify_api_key,
)
from app.budgeting import (
    DEFAULT_ALERT_THRESHOLD_PERCENT,
    get_month_window,
    get_project_budget,
    get_project_month_usage,
)
from app.database import get_db
from app.models import Project, ProjectApiKey, ProjectBudget, ProjectRedactionPolicy
from app.redaction import default_redaction_policy, normalize_redaction_mode
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


class ProjectApiKeyCreateRequest(BaseModel):
    """Request for creating an additional scoped API key."""

    name: str = Field(min_length=1, max_length=100)
    scopes: list[str] = Field(
        default_factory=lambda: ["read", "ingest", "curate"],
        min_length=1,
        max_length=4,
    )


class ProjectApiKeyResponse(BaseModel):
    """Metadata response for scoped API keys."""

    id: str
    name: str
    scopes: list[str]
    key_fingerprint: str
    is_active: bool
    created_at: str
    revoked_at: str | None
    last_used_at: str | None


class ProjectApiKeyCreateResponse(ProjectApiKeyResponse):
    """Scoped key response that includes the plaintext key exactly once."""

    api_key: str


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


class RedactionPolicyResponse(BaseModel):
    """Response schema for project redaction policy."""

    enabled: bool
    mode: str
    rules: dict
    created_at: str | None
    updated_at: str | None


class RedactionPolicyUpdateRequest(BaseModel):
    """Request schema for project redaction policy updates."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    mode: str | None = Field(default=None)
    rules: dict | None = Field(default=None, max_length=50)

    @field_validator("mode")
    @classmethod
    def validate_mode(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_redaction_mode(value)


def _default_policy_rules() -> dict:
    return dict(default_redaction_policy()["rules"])


def _get_or_create_redaction_policy(db: Session, project_id) -> ProjectRedactionPolicy:
    policy = (
        db.query(ProjectRedactionPolicy)
        .filter(ProjectRedactionPolicy.project_id == project_id)
        .first()
    )
    if policy:
        return policy
    policy = ProjectRedactionPolicy(
        project_id=project_id,
        enabled=True,
        mode="audit_only",
        rules=_default_policy_rules(),
    )
    db.add(policy)
    db.commit()
    db.refresh(policy)
    return policy


def _to_redaction_policy_response(policy: ProjectRedactionPolicy) -> RedactionPolicyResponse:
    return RedactionPolicyResponse(
        enabled=bool(policy.enabled),
        mode=policy.mode,
        rules=policy.rules or {},
        created_at=policy.created_at.isoformat() if policy.created_at else None,
        updated_at=policy.updated_at.isoformat() if policy.updated_at else None,
    )


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


def _to_project_api_key_response(key: ProjectApiKey) -> ProjectApiKeyResponse:
    """Serialize API key metadata consistently."""
    return ProjectApiKeyResponse(
        id=str(key.id),
        name=key.name,
        scopes=sorted(normalize_api_key_scopes(key.scopes or [])),
        key_fingerprint=key.key_fingerprint,
        is_active=key.is_active,
        created_at=key.created_at.isoformat(),
        revoked_at=key.revoked_at.isoformat() if key.revoked_at else None,
        last_used_at=key.last_used_at.isoformat() if key.last_used_at else None,
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
    project: Project = Depends(verify_api_key),
) -> list[ProjectResponse]:
    """List projects visible to the current API key (tenant-scoped)."""
    return [
        ProjectResponse(
            id=str(project.id),
            name=project.name,
            created_at=project.created_at.isoformat(),
        )
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


@router.get("/me/redaction-policy", response_model=RedactionPolicyResponse)
async def get_redaction_policy(
    project: Project = Depends(verify_api_key),
    db: Session = Depends(get_db),
) -> RedactionPolicyResponse:
    """Get the current project's centralized redaction policy."""
    policy = _get_or_create_redaction_policy(db, project.id)
    return _to_redaction_policy_response(policy)


@router.put("/me/redaction-policy", response_model=RedactionPolicyResponse)
async def update_redaction_policy(
    payload: RedactionPolicyUpdateRequest,
    request: Request,
    project: Project = Depends(verify_api_key),
    db: Session = Depends(get_db),
) -> RedactionPolicyResponse:
    """Update the current project's centralized redaction policy."""
    policy = _get_or_create_redaction_policy(db, project.id)

    if "enabled" in payload.model_fields_set and payload.enabled is not None:
        policy.enabled = payload.enabled
    if "mode" in payload.model_fields_set and payload.mode is not None:
        policy.mode = normalize_redaction_mode(payload.mode)
    if "rules" in payload.model_fields_set and payload.rules is not None:
        policy.rules = payload.rules
    policy.updated_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(policy)

    audit_log(
        "redaction_policy_updated",
        request_id=getattr(request.state, "request_id", None),
        project_id=str(project.id),
        enabled=policy.enabled,
        mode=policy.mode,
        disabled_rule_count=len((policy.rules or {}).get("disabled_rule_ids") or []),
    )
    return _to_redaction_policy_response(policy)


@router.get("/me/keys", response_model=list[ProjectApiKeyResponse])
async def list_project_api_keys(
    project: Project = Depends(verify_api_key),
    db: Session = Depends(get_db),
) -> list[ProjectApiKeyResponse]:
    """List scoped API keys for the current project."""
    keys = (
        db.query(ProjectApiKey)
        .filter(ProjectApiKey.project_id == project.id)
        .order_by(ProjectApiKey.created_at.desc())
        .all()
    )
    return [_to_project_api_key_response(key) for key in keys]


@router.post("/me/keys", response_model=ProjectApiKeyCreateResponse, status_code=201)
async def create_project_api_key(
    payload: ProjectApiKeyCreateRequest,
    request: Request,
    project: Project = Depends(verify_api_key),
    db: Session = Depends(get_db),
) -> ProjectApiKeyCreateResponse:
    """Create a new scoped API key for the current project."""
    try:
        scopes = sorted(normalize_api_key_scopes(payload.scopes))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not scopes:
        raise HTTPException(status_code=422, detail="At least one scope must be specified.")

    plaintext_key = generate_api_key()
    scoped_key = ProjectApiKey(
        project_id=project.id,
        name=payload.name.strip(),
        key_hash=hash_api_key(plaintext_key),
        key_fingerprint=api_key_fingerprint(plaintext_key),
        scopes=scopes,
        is_active=True,
    )
    db.add(scoped_key)
    db.commit()
    db.refresh(scoped_key)

    audit_log(
        "project_scoped_api_key_created",
        request_id=getattr(request.state, "request_id", None),
        project_id=str(project.id),
        key_id=str(scoped_key.id),
        key_fingerprint=scoped_key.key_fingerprint,
        scopes=scopes,
    )

    metadata = _to_project_api_key_response(scoped_key)
    return ProjectApiKeyCreateResponse(
        **metadata.model_dump(),
        api_key=plaintext_key,
    )


@router.post("/me/keys/{key_id}/revoke", response_model=ProjectApiKeyResponse)
async def revoke_project_api_key(
    key_id: UUID,
    request: Request,
    project: Project = Depends(verify_api_key),
    db: Session = Depends(get_db),
) -> ProjectApiKeyResponse:
    """Revoke a scoped API key for the current project."""
    scoped_key = (
        db.query(ProjectApiKey)
        .filter(
            ProjectApiKey.id == key_id,
            ProjectApiKey.project_id == project.id,
        )
        .first()
    )
    if not scoped_key:
        raise HTTPException(status_code=404, detail="API key not found.")

    if scoped_key.is_active:
        scoped_key.is_active = False
        scoped_key.revoked_at = datetime.now(timezone.utc)
        scoped_key.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(scoped_key)

    audit_log(
        "project_scoped_api_key_revoked",
        request_id=getattr(request.state, "request_id", None),
        project_id=str(project.id),
        key_id=str(scoped_key.id),
        key_fingerprint=scoped_key.key_fingerprint,
    )
    return _to_project_api_key_response(scoped_key)


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
