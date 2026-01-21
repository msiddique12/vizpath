"""Project management endpoints."""

import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import generate_api_key, hash_api_key, verify_api_key
from app.database import get_db
from app.models import Project

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


@router.post("/", response_model=ProjectWithKeyResponse, status_code=201)
async def create_project(
    payload: ProjectCreate,
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
