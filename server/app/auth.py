"""Authentication utilities for API key validation."""

import hashlib
import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import Project, ProjectApiKey
from app.security import audit_log

logger = logging.getLogger(__name__)

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

API_KEY_SCOPE_READ = "read"
API_KEY_SCOPE_INGEST = "ingest"
API_KEY_SCOPE_CURATE = "curate"
API_KEY_SCOPE_ADMIN = "admin"
ALL_API_KEY_SCOPES = frozenset(
    {
        API_KEY_SCOPE_READ,
        API_KEY_SCOPE_INGEST,
        API_KEY_SCOPE_CURATE,
        API_KEY_SCOPE_ADMIN,
    }
)


@dataclass
class _AuthLookupResult:
    project: Project
    scopes: set[str]
    source: str
    scoped_key: ProjectApiKey | None = None


def hash_api_key(api_key: str) -> str:
    """Create a SHA-256 hash of an API key."""
    return hashlib.sha256(api_key.encode()).hexdigest()


def api_key_fingerprint(api_key: str) -> str:
    """Short non-reversible fingerprint for safe logs."""
    return hash_api_key(api_key)[:12]


def generate_api_key() -> str:
    """Generate a new API key."""
    return f"vp_{secrets.token_urlsafe(32)}"


def _to_utc(dt: datetime) -> datetime:
    """Normalize DB datetimes to UTC-aware for safe comparisons."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def normalize_api_key_scopes(scopes: list[str] | tuple[str, ...] | set[str]) -> set[str]:
    """Normalize and validate API key scopes."""
    normalized = {str(scope).strip().lower() for scope in scopes if str(scope).strip()}
    invalid = normalized - ALL_API_KEY_SCOPES
    if invalid:
        invalid_list = ", ".join(sorted(invalid))
        raise ValueError(f"Invalid scopes: {invalid_list}")
    if API_KEY_SCOPE_ADMIN in normalized:
        return set(ALL_API_KEY_SCOPES)
    return normalized


def _infer_required_scope(request: Request) -> str | None:
    """Infer required scope from route path and HTTP method."""
    method = request.method.upper()
    path = request.url.path

    if path.startswith("/api/v1/curation"):
        return API_KEY_SCOPE_CURATE

    if path.startswith("/api/v1/triage/items"):
        if method == "GET":
            return API_KEY_SCOPE_READ
        return API_KEY_SCOPE_CURATE

    if path.startswith("/api/v1/datasets/builds"):
        if method == "GET":
            return API_KEY_SCOPE_READ
        return API_KEY_SCOPE_CURATE

    if path.startswith("/api/v1/evals/suites"):
        if method == "GET":
            return API_KEY_SCOPE_READ
        return API_KEY_SCOPE_CURATE

    if path.startswith("/api/v1/evals/runs"):
        if method == "GET":
            return API_KEY_SCOPE_READ
        return API_KEY_SCOPE_CURATE

    if path.startswith("/api/v1/traces/spans/batch"):
        return API_KEY_SCOPE_INGEST

    if path.startswith("/api/v1/traces"):
        if method == "GET":
            return API_KEY_SCOPE_READ
        if method == "DELETE":
            return API_KEY_SCOPE_ADMIN
        return API_KEY_SCOPE_INGEST

    if path.startswith("/api/v1/intelligence"):
        return API_KEY_SCOPE_READ

    if path.startswith("/api/v1/projects/me/keys"):
        return API_KEY_SCOPE_ADMIN

    if path.startswith("/api/v1/projects/me/api-key"):
        return API_KEY_SCOPE_ADMIN

    if path.startswith("/api/v1/projects/me/alerts"):
        if method == "GET":
            return API_KEY_SCOPE_READ
        return API_KEY_SCOPE_ADMIN

    if path.startswith("/api/v1/projects/me/budget"):
        if method == "GET":
            return API_KEY_SCOPE_READ
        return API_KEY_SCOPE_ADMIN

    if path.startswith("/api/v1/projects/me/redaction-policy"):
        if method == "GET":
            return API_KEY_SCOPE_READ
        return API_KEY_SCOPE_ADMIN

    if path.startswith("/api/v1/projects/me"):
        if method == "GET":
            return API_KEY_SCOPE_READ
        return API_KEY_SCOPE_ADMIN

    if path.startswith("/api/v1/redaction"):
        return API_KEY_SCOPE_READ

    if path.startswith("/api/v1/projects"):
        if method == "GET":
            return API_KEY_SCOPE_READ

    return None


def _lookup_project_by_key(db: Session, api_key: str) -> _AuthLookupResult | None:
    """Resolve API key to project plus scopes and auth source."""
    key_hash = hash_api_key(api_key)

    scoped_key = (
        db.query(ProjectApiKey)
        .filter(
            ProjectApiKey.key_hash == key_hash,
            ProjectApiKey.is_active.is_(True),
            ProjectApiKey.revoked_at.is_(None),
        )
        .first()
    )
    if scoped_key:
        scopes = normalize_api_key_scopes(scoped_key.scopes or [])
        if not scopes:
            scopes = {API_KEY_SCOPE_READ}
        return _AuthLookupResult(
            project=scoped_key.project,
            scopes=scopes,
            source="scoped_key",
            scoped_key=scoped_key,
        )

    project = (
        db.query(Project)
        .filter(
            or_(
                Project.api_key_hash == key_hash,
                Project.previous_api_key_hash == key_hash,
            )
        )
        .first()
    )
    if not project:
        return None

    if project.api_key_revoked_at is not None:
        return None

    if project.api_key_hash == key_hash:
        return _AuthLookupResult(
            project=project,
            scopes=set(ALL_API_KEY_SCOPES),
            source="legacy_project_key",
        )

    if (
        project.previous_api_key_hash == key_hash
        and project.api_key_grace_expires_at is not None
        and datetime.now(timezone.utc) <= _to_utc(project.api_key_grace_expires_at)
    ):
        return _AuthLookupResult(
            project=project,
            scopes=set(ALL_API_KEY_SCOPES),
            source="legacy_previous_project_key",
        )

    return None


def get_project_by_api_key(db: Session, api_key: str) -> Project | None:
    """Look up a project by current key hash or grace-period previous key hash."""
    resolved = _lookup_project_by_key(db, api_key)
    return resolved.project if resolved else None


def _get_or_create_default_project(db: Session) -> Project:
    """Get or create the default project for unauthenticated dev requests.

    Disabled by default. Enable only for local/demo workflows by setting
    ALLOW_UNAUTHENTICATED_DEV_FALLBACK=true.
    """
    if not settings.allow_unauthenticated_dev_fallback:
        audit_log(
            "missing_api_key_rejected",
            reason="unauthenticated_fallback_disabled",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API key. Include X-API-Key header.",
        )

    default_project = db.query(Project).filter(Project.api_key_hash == "default").first()
    if default_project:
        audit_log("unauthenticated_fallback_project_reused", project_id=str(default_project.id))
        return default_project

    try:
        default_project = Project(name="default", api_key_hash="default")
        db.add(default_project)
        db.commit()
        audit_log(
            "unauthenticated_fallback_project_created",
            project_id=str(default_project.id),
        )
        return default_project
    except IntegrityError:
        db.rollback()
        default_project = db.query(Project).filter(Project.api_key_hash == "default").first()
        if default_project:
            return default_project
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create default project.",
        ) from None


async def verify_api_key(
    request: Request,
    api_key: str | None = Security(api_key_header),
    db: Session = Depends(get_db),
) -> Project:
    """
    Verify the API key and return the associated project.

    - If a key is provided, it must be valid (fail-fast).
    - If no key is provided, fall back to default project only when
      ALLOW_UNAUTHENTICATED_DEV_FALLBACK=true.
    """
    if api_key:
        resolved = _lookup_project_by_key(db, api_key)
        if not resolved:
            logger.warning("Invalid API key attempt: fingerprint=%s", api_key_fingerprint(api_key))
            audit_log(
                "invalid_api_key",
                request_id=getattr(request.state, "request_id", None),
                api_key_fingerprint=api_key_fingerprint(api_key),
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid API key.",
            )
        required_scope = _infer_required_scope(request)
        if required_scope and required_scope not in resolved.scopes:
            audit_log(
                "api_key_scope_denied",
                request_id=getattr(request.state, "request_id", None),
                project_id=str(resolved.project.id),
                required_scope=required_scope,
                api_key_fingerprint=api_key_fingerprint(api_key),
                auth_source=resolved.source,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"API key missing required scope: {required_scope}",
            )

        request.state.api_key_scopes = sorted(resolved.scopes)
        request.state.api_key_auth_source = resolved.source
        return resolved.project

    audit_log("missing_api_key", request_id=getattr(request.state, "request_id", None))
    project = _get_or_create_default_project(db)
    request.state.api_key_scopes = sorted(ALL_API_KEY_SCOPES)
    request.state.api_key_auth_source = "unauthenticated_dev_fallback"
    return project


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
