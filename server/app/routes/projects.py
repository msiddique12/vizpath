"""Project management endpoints."""

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import generate_api_key, hash_api_key, verify_api_key
from app.database import get_db
from app.models import Project
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
