"""Durable triage workflow endpoints."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from app.auth import verify_api_key
from app.database import get_db
from app.models import Project, Trace, TriageItem
from app.security import audit_log
from app.validation import ID_PATTERN, TAG_PATTERN, normalize_text

router = APIRouter(prefix="/triage", tags=["Triage"])

TRIAGE_STATUSES = {"open", "investigating", "resolved"}
TRIAGE_PRIORITIES = {"low", "medium", "high", "critical"}


class TriageItemCreate(BaseModel):
    """Create a durable triage item for a project trace."""

    model_config = ConfigDict(extra="forbid")

    trace_id: str = Field(min_length=1, max_length=128, pattern=ID_PATTERN)
    status: str = Field(default="open", pattern="^(open|investigating|resolved)$")
    priority: str = Field(default="medium", pattern="^(low|medium|high|critical)$")
    owner: str | None = Field(default=None, max_length=120)
    failure_mode: str | None = Field(default=None, max_length=120, pattern=TAG_PATTERN)
    title: str | None = Field(default=None, max_length=255)
    notes: str | None = Field(default=None, max_length=4000)
    linked_trace_ids: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("owner", "failure_mode", "title", "notes", mode="before")
    @classmethod
    def normalize_text_fields(cls, value: str | None, info) -> str | None:
        limits = {"owner": 120, "failure_mode": 120, "title": 255, "notes": 4000}
        return normalize_text(
            value,
            field_name=info.field_name,
            max_length=limits[info.field_name],
            allow_empty=info.field_name in {"owner", "failure_mode", "notes"},
        )

    @field_validator("linked_trace_ids")
    @classmethod
    def validate_linked_trace_ids(cls, value: list[str]) -> list[str]:
        return _normalize_trace_ids(value, field_name="linked_trace_ids")


class TriageItemUpdate(BaseModel):
    """Update a durable triage item."""

    model_config = ConfigDict(extra="forbid")

    status: str | None = Field(default=None, pattern="^(open|investigating|resolved)$")
    priority: str | None = Field(default=None, pattern="^(low|medium|high|critical)$")
    owner: str | None = Field(default=None, max_length=120)
    failure_mode: str | None = Field(default=None, max_length=120, pattern=TAG_PATTERN)
    title: str | None = Field(default=None, max_length=255)
    notes: str | None = Field(default=None, max_length=4000)
    resolved_by: str | None = Field(default=None, max_length=120)

    @field_validator("owner", "failure_mode", "title", "notes", "resolved_by", mode="before")
    @classmethod
    def normalize_text_fields(cls, value: str | None, info) -> str | None:
        limits = {
            "owner": 120,
            "failure_mode": 120,
            "title": 255,
            "notes": 4000,
            "resolved_by": 120,
        }
        return normalize_text(
            value,
            field_name=info.field_name,
            max_length=limits[info.field_name],
            allow_empty=info.field_name in {"owner", "failure_mode", "notes", "resolved_by"},
        )


class TriageLinksRequest(BaseModel):
    """Set linked traces for a triage item."""

    model_config = ConfigDict(extra="forbid")

    linked_trace_ids: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("linked_trace_ids")
    @classmethod
    def validate_linked_trace_ids(cls, value: list[str]) -> list[str]:
        return _normalize_trace_ids(value, field_name="linked_trace_ids")


def _normalize_trace_ids(value: list[str], *, field_name: str) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for trace_id in value:
        normalized_trace_id = normalize_text(trace_id, field_name=field_name, max_length=128)
        if normalized_trace_id is None:
            continue
        if normalized_trace_id not in seen:
            normalized.append(normalized_trace_id)
            seen.add(normalized_trace_id)
    return normalized


def _trace_or_404(db: Session, project_id: Any, trace_id: str) -> Trace:
    trace = db.query(Trace).filter(Trace.id == trace_id, Trace.project_id == project_id).first()
    if not trace:
        raise HTTPException(status_code=404, detail="Trace not found")
    return trace


def _validate_linked_traces(db: Session, project_id: Any, linked_trace_ids: list[str]) -> None:
    if not linked_trace_ids:
        return
    count = (
        db.query(Trace.id)
        .filter(Trace.project_id == project_id, Trace.id.in_(linked_trace_ids))
        .count()
    )
    if count != len(linked_trace_ids):
        raise HTTPException(status_code=404, detail="Linked trace not found")


def _serialize_item(item: TriageItem) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "trace_id": str(item.trace_id),
        "trace_name": item.trace.name if item.trace else None,
        "trace_status": item.trace.status if item.trace else None,
        "status": item.status,
        "priority": item.priority,
        "owner": item.owner,
        "failure_mode": item.failure_mode,
        "title": item.title,
        "notes": item.notes,
        "linked_trace_ids": item.linked_trace_ids or [],
        "resolved_at": item.resolved_at.isoformat() if item.resolved_at else None,
        "resolved_by": item.resolved_by,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    }


@router.get("/items")
async def list_triage_items(
    project: Project = Depends(verify_api_key),
    db: Session = Depends(get_db),
    status: str | None = Query(default=None, pattern="^(open|investigating|resolved)$"),
    priority: str | None = Query(default=None, pattern="^(low|medium|high|critical)$"),
    owner: str | None = Query(default=None, max_length=120),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    """List project-scoped triage workflow items."""
    query = db.query(TriageItem).filter(TriageItem.project_id == project.id)
    if status:
        query = query.filter(TriageItem.status == status)
    if priority:
        query = query.filter(TriageItem.priority == priority)
    if owner:
        query = query.filter(TriageItem.owner == owner)

    total = query.count()
    items = (
        query.order_by(TriageItem.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return {
        "items": [_serialize_item(item) for item in items],
        "total": total,
        "limit": limit,
        "offset": offset,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.post("/items", status_code=201)
async def create_triage_item(
    payload: TriageItemCreate,
    request: Request,
    project: Project = Depends(verify_api_key),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Create or update the triage item for a trace."""
    trace = _trace_or_404(db, project.id, payload.trace_id)
    _validate_linked_traces(db, project.id, payload.linked_trace_ids)
    item = (
        db.query(TriageItem)
        .filter(TriageItem.project_id == project.id, TriageItem.trace_id == payload.trace_id)
        .first()
    )
    now = datetime.now(timezone.utc)
    if item is None:
        item = TriageItem(
            project_id=project.id,
            trace_id=payload.trace_id,
            status=payload.status,
            priority=payload.priority,
            owner=payload.owner,
            failure_mode=payload.failure_mode,
            title=payload.title or trace.name,
            notes=payload.notes,
            linked_trace_ids=payload.linked_trace_ids,
            resolved_at=now if payload.status == "resolved" else None,
        )
        db.add(item)
    else:
        item.status = payload.status
        item.priority = payload.priority
        item.owner = payload.owner
        item.failure_mode = payload.failure_mode
        item.title = payload.title or item.title
        item.notes = payload.notes
        item.linked_trace_ids = payload.linked_trace_ids
        item.resolved_at = now if payload.status == "resolved" else None

    db.commit()
    db.refresh(item)
    audit_log(
        "triage_item_upserted",
        request_id=getattr(request.state, "request_id", None),
        project_id=str(project.id),
        trace_id=payload.trace_id,
        triage_item_id=str(item.id),
        status=item.status,
        priority=item.priority,
    )
    return _serialize_item(item)


@router.patch("/items/{item_id}")
async def update_triage_item(
    payload: TriageItemUpdate,
    request: Request,
    item_id: UUID,
    project: Project = Depends(verify_api_key),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Update workflow fields on a triage item."""
    item = (
        db.query(TriageItem)
        .filter(TriageItem.id == item_id, TriageItem.project_id == project.id)
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Triage item not found")

    now = datetime.now(timezone.utc)
    if "status" in payload.model_fields_set and payload.status is not None:
        item.status = payload.status
        item.resolved_at = now if payload.status == "resolved" else None
        if payload.status != "resolved":
            item.resolved_by = None
    if "priority" in payload.model_fields_set and payload.priority is not None:
        item.priority = payload.priority
    if "owner" in payload.model_fields_set:
        item.owner = payload.owner
    if "failure_mode" in payload.model_fields_set:
        item.failure_mode = payload.failure_mode
    if "title" in payload.model_fields_set and payload.title is not None:
        item.title = payload.title
    if "notes" in payload.model_fields_set:
        item.notes = payload.notes
    if "resolved_by" in payload.model_fields_set:
        item.resolved_by = payload.resolved_by
    item.updated_at = now

    db.commit()
    db.refresh(item)
    audit_log(
        "triage_item_updated",
        request_id=getattr(request.state, "request_id", None),
        project_id=str(project.id),
        trace_id=str(item.trace_id),
        triage_item_id=str(item.id),
        status=item.status,
        priority=item.priority,
    )
    return _serialize_item(item)


@router.post("/items/{item_id}/links")
async def update_triage_links(
    payload: TriageLinksRequest,
    request: Request,
    item_id: UUID,
    project: Project = Depends(verify_api_key),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Replace linked trace references for a triage item."""
    item = (
        db.query(TriageItem)
        .filter(TriageItem.id == item_id, TriageItem.project_id == project.id)
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Triage item not found")

    linked_trace_ids = [
        trace_id for trace_id in payload.linked_trace_ids if trace_id != item.trace_id
    ]
    _validate_linked_traces(db, project.id, linked_trace_ids)
    item.linked_trace_ids = linked_trace_ids
    item.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(item)
    audit_log(
        "triage_item_links_updated",
        request_id=getattr(request.state, "request_id", None),
        project_id=str(project.id),
        trace_id=str(item.trace_id),
        triage_item_id=str(item.id),
        linked_trace_count=len(linked_trace_ids),
    )
    return _serialize_item(item)
