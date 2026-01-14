"""Authentication utilities for API key validation."""

import hashlib
import secrets
from typing import Optional

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Project

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def hash_api_key(api_key: str) -> str:
    """Create a SHA-256 hash of an API key."""
    return hashlib.sha256(api_key.encode()).hexdigest()


def generate_api_key() -> str:
    """Generate a new API key."""
    return f"vp_{secrets.token_urlsafe(32)}"


def get_project_by_api_key(db: Session, api_key: str) -> Optional[Project]:
    """Look up a project by API key hash."""
    key_hash = hash_api_key(api_key)
    return db.query(Project).filter(Project.api_key_hash == key_hash).first()


async def verify_api_key(
    api_key: Optional[str] = Security(api_key_header),
    db: Session = Depends(get_db),
) -> Project:
    """
    Verify the API key and return the associated project.

    For development, allows requests without API key if no projects exist.
    """
    if api_key:
        project = get_project_by_api_key(db, api_key)
        if project:
            return project

    project_count = db.query(Project).count()
    if project_count == 0:
        default_project = db.query(Project).filter(Project.api_key_hash == "default").first()
        if default_project:
            return default_project

        default_project = Project(name="default", api_key_hash="default")
        db.add(default_project)
        db.commit()
        return default_project

    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API key. Include X-API-Key header.",
        )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid API key.",
    )


async def optional_api_key(
    api_key: Optional[str] = Security(api_key_header),
    db: Session = Depends(get_db),
) -> Optional[Project]:
    """
    Optionally verify API key. Returns None if not provided.

    Useful for public endpoints that behave differently when authenticated.
    """
    if not api_key:
        return None

    return get_project_by_api_key(db, api_key)
