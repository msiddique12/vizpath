"""Authentication utilities for API key validation."""

import hashlib
import logging
import os
import secrets

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Project

logger = logging.getLogger(__name__)

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def hash_api_key(api_key: str) -> str:
    """Create a SHA-256 hash of an API key."""
    return hashlib.sha256(api_key.encode()).hexdigest()


def generate_api_key() -> str:
    """Generate a new API key."""
    return f"vp_{secrets.token_urlsafe(32)}"


def get_project_by_api_key(db: Session, api_key: str) -> Project | None:
    """Look up a project by API key hash."""
    key_hash = hash_api_key(api_key)
    return db.query(Project).filter(Project.api_key_hash == key_hash).first()


def _get_or_create_default_project(db: Session) -> Project:
    """Get or create the default project for unauthenticated dev requests.

    In production mode, blocks unauthenticated requests once real projects exist.
    In dev mode, always creates/returns a default project.
    """
    is_production = os.environ.get("ENVIRONMENT", "development").lower() == "production"

    if is_production:
        real_project_count = (
            db.query(Project).filter(Project.api_key_hash != "default").count()
        )
        if real_project_count > 0:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing API key. Include X-API-Key header.",
            )

    default_project = db.query(Project).filter(Project.api_key_hash == "default").first()
    if default_project:
        return default_project

    try:
        default_project = Project(name="default", api_key_hash="default")
        db.add(default_project)
        db.commit()
        return default_project
    except IntegrityError:
        db.rollback()
        default_project = db.query(Project).filter(Project.api_key_hash == "default").first()
        if default_project:
            return default_project
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create default project.",
        )


async def verify_api_key(
    api_key: str | None = Security(api_key_header),
    db: Session = Depends(get_db),
) -> Project:
    """
    Verify the API key and return the associated project.

    - If a key is provided, it must be valid (fail-fast).
    - If no key is provided, fall back to default project (dev mode)
      or reject in production when real projects exist.
    """
    if api_key:
        project = get_project_by_api_key(db, api_key)
        if not project:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid API key.",
            )
        return project

    return _get_or_create_default_project(db)


async def optional_api_key(
    api_key: str | None = Security(api_key_header),
    db: Session = Depends(get_db),
) -> Project | None:
    """
    Optionally verify API key. Returns None if not provided.

    Useful for public endpoints that behave differently when authenticated.
    """
    if not api_key:
        return None

    return get_project_by_api_key(db, api_key)
