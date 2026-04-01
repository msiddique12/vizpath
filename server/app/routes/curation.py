"""Curation endpoints for trace labeling and export."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import verify_api_key
from app.database import get_db
from app.models import CuratedLabel, Project, Span, Trace
from app.security import audit_log
from app.validation import ID_PATTERN, TAG_PATTERN, normalize_text

router = APIRouter(prefix="/curation", tags=["curation"])


class LabelCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trace_id: str = Field(min_length=1, max_length=128, pattern=ID_PATTERN)
    label: str | None = Field(default=None, min_length=1, max_length=100, pattern=TAG_PATTERN)
    quality_score: float | None = Field(default=None, ge=0, le=100)
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("label", "notes", mode="before")
    @classmethod
    def normalize_text_fields(cls, value: str | None, info) -> str | None:
        limits = {"label": 100, "notes": 2000}
        return normalize_text(
            value,
            field_name=info.field_name,
            max_length=limits[info.field_name],
            allow_empty=info.field_name == "notes",
        )


class LabelUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str | None = Field(default=None, min_length=1, max_length=100, pattern=TAG_PATTERN)
    quality_score: float | None = Field(default=None, ge=0, le=100)
    notes: str | None = Field(default=None, max_length=2000)
    exported: bool | None = None

    @field_validator("label", "notes", mode="before")
    @classmethod
    def normalize_text_fields(cls, value: str | None, info) -> str | None:
        limits = {"label": 100, "notes": 2000}
        return normalize_text(
            value,
            field_name=info.field_name,
            max_length=limits[info.field_name],
            allow_empty=info.field_name == "notes",
        )


class LabelResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    trace_id: str
    label: str | None
    quality_score: float | None
    notes: str | None
    exported: bool
    created_at: str
    updated_at: str | None


class CuratedTraceResponse(BaseModel):
    trace_id: str
    trace_name: str
    label: str | None
    quality_score: float | None
    notes: str | None
    exported: bool
    span_count: int
    total_tokens: int | None
    duration_ms: float | None


class ExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trace_ids: list[str] = Field(min_length=1, max_length=1000)
    format: str = Field(default="jsonl", pattern="^(jsonl|json)$")
    include_input_output: bool = True

    @field_validator("trace_ids")
    @classmethod
    def validate_trace_ids(cls, value: list[str]) -> list[str]:
        normalized = []
        for trace_id in value:
            normalized_trace_id = normalize_text(
                trace_id,
                field_name="trace_id",
                max_length=128,
            )
            if normalized_trace_id is None:
                raise ValueError("trace_id cannot be null")
            normalized.append(normalized_trace_id)
        return normalized


@router.post("/labels", response_model=LabelResponse)
def create_or_update_label(
    data: LabelCreate,
    request: Request,
    project: Project = Depends(verify_api_key),
    db: Session = Depends(get_db),
) -> LabelResponse:
    """Create or update a label for a trace."""
    trace = db.execute(
        select(Trace).where(Trace.id == data.trace_id, Trace.project_id == project.id)
    ).scalar_one_or_none()

    if not trace:
        raise HTTPException(status_code=404, detail="Trace not found")

    existing = db.execute(
        select(CuratedLabel).where(CuratedLabel.trace_id == data.trace_id)
    ).scalar_one_or_none()

    if existing:
        if data.label is not None:
            existing.label = data.label
        if data.quality_score is not None:
            existing.quality_score = data.quality_score
        if data.notes is not None:
            existing.notes = data.notes
        db.commit()
        db.refresh(existing)
        label = existing
    else:
        label = CuratedLabel(
            trace_id=data.trace_id,
            label=data.label,
            quality_score=data.quality_score,
            notes=data.notes,
        )
        db.add(label)
        db.commit()
        db.refresh(label)

    audit_log(
        "curation_label_upserted",
        request_id=getattr(request.state, "request_id", None),
        project_id=str(project.id),
        trace_id=data.trace_id,
        label=label.label,
    )

    return LabelResponse(
        id=label.id,
        trace_id=label.trace_id,
        label=label.label,
        quality_score=label.quality_score,
        notes=label.notes,
        exported=label.exported,
        created_at=label.created_at.isoformat(),
        updated_at=label.updated_at.isoformat() if label.updated_at else None,
    )


@router.get("/labels/{trace_id}", response_model=LabelResponse)
def get_label(
    trace_id: str,
    project: Project = Depends(verify_api_key),
    db: Session = Depends(get_db),
) -> LabelResponse:
    """Get the label for a specific trace."""
    label = db.execute(
        select(CuratedLabel)
        .join(Trace, Trace.id == CuratedLabel.trace_id)
        .where(CuratedLabel.trace_id == trace_id, Trace.project_id == project.id)
    ).scalar_one_or_none()

    if not label:
        raise HTTPException(status_code=404, detail="Label not found")

    return LabelResponse(
        id=label.id,
        trace_id=label.trace_id,
        label=label.label,
        quality_score=label.quality_score,
        notes=label.notes,
        exported=label.exported,
        created_at=label.created_at.isoformat(),
        updated_at=label.updated_at.isoformat() if label.updated_at else None,
    )


@router.delete(
    "/labels/{trace_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_label(
    trace_id: str,
    request: Request,
    project: Project = Depends(verify_api_key),
    db: Session = Depends(get_db),
) -> Response:
    """Delete a label for a trace."""
    label = db.execute(
        select(CuratedLabel)
        .join(Trace, Trace.id == CuratedLabel.trace_id)
        .where(CuratedLabel.trace_id == trace_id, Trace.project_id == project.id)
    ).scalar_one_or_none()

    if not label:
        raise HTTPException(status_code=404, detail="Label not found")

    db.delete(label)
    db.commit()
    audit_log(
        "curation_label_deleted",
        request_id=getattr(request.state, "request_id", None),
        project_id=str(project.id),
        trace_id=trace_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/traces", response_model=list[CuratedTraceResponse])
def list_curated_traces(
    project: Project = Depends(verify_api_key),
    label: str | None = Query(None, description="Filter by label"),
    exported: bool | None = Query(None, description="Filter by export status"),
    min_score: float | None = Query(None, description="Minimum quality score"),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> list[CuratedTraceResponse]:
    """List traces with curation labels."""
    query = (
        select(Trace, CuratedLabel)
        .outerjoin(CuratedLabel, Trace.id == CuratedLabel.trace_id)
        .where(CuratedLabel.id.isnot(None), Trace.project_id == project.id)
    )

    if label:
        query = query.where(CuratedLabel.label == label)
    if exported is not None:
        query = query.where(CuratedLabel.exported == exported)
    if min_score is not None:
        query = query.where(CuratedLabel.quality_score >= min_score)

    query = query.order_by(Trace.created_at.desc()).offset(offset).limit(limit)

    results = db.execute(query).all()

    return [
        CuratedTraceResponse(
            trace_id=trace.id,
            trace_name=trace.name,
            label=curation.label if curation else None,
            quality_score=curation.quality_score if curation else None,
            notes=curation.notes if curation else None,
            exported=curation.exported if curation else False,
            span_count=trace.span_count,
            total_tokens=trace.total_tokens,
            duration_ms=trace.duration_ms,
        )
        for trace, curation in results
    ]


@router.get("/stats")
def get_curation_stats(
    project: Project = Depends(verify_api_key),
    db: Session = Depends(get_db),
) -> dict:
    """Get curation statistics."""
    from sqlalchemy import func

    total_labeled = db.execute(
        select(func.count(CuratedLabel.id))
        .join(Trace, Trace.id == CuratedLabel.trace_id)
        .where(Trace.project_id == project.id)
    ).scalar() or 0

    exported_count = db.execute(
        select(func.count(CuratedLabel.id))
        .join(Trace, Trace.id == CuratedLabel.trace_id)
        .where(CuratedLabel.exported.is_(True), Trace.project_id == project.id)
    ).scalar() or 0

    label_counts = db.execute(
        select(CuratedLabel.label, func.count(CuratedLabel.id))
        .join(Trace, Trace.id == CuratedLabel.trace_id)
        .where(CuratedLabel.label.isnot(None), Trace.project_id == project.id)
        .group_by(CuratedLabel.label)
    ).all()

    avg_score = db.execute(
        select(func.avg(CuratedLabel.quality_score))
        .join(Trace, Trace.id == CuratedLabel.trace_id)
        .where(CuratedLabel.quality_score.isnot(None), Trace.project_id == project.id)
    ).scalar()

    return {
        "total_labeled": total_labeled,
        "exported_count": exported_count,
        "labels": {label: count for label, count in label_counts},
        "average_quality_score": round(avg_score, 2) if avg_score else None,
    }


@router.post("/export")
def export_traces(
    data: ExportRequest,
    request: Request,
    project: Project = Depends(verify_api_key),
    db: Session = Depends(get_db),
) -> dict:
    """Export curated traces in specified format."""
    traces_data = []

    for trace_id in data.trace_ids:
        trace = db.execute(
            select(Trace).where(Trace.id == trace_id, Trace.project_id == project.id)
        ).scalar_one_or_none()

        if not trace:
            continue

        spans = db.execute(
            select(Span).where(Span.trace_id == trace_id).order_by(Span.start_time)
        ).scalars().all()

        label = db.execute(
            select(CuratedLabel).where(CuratedLabel.trace_id == trace_id)
        ).scalar_one_or_none()

        trace_export = {
            "trace": trace.to_dict(),
            "spans": [span.to_dict() for span in spans],
            "curation": {
                "label": label.label if label else None,
                "quality_score": label.quality_score if label else None,
                "notes": label.notes if label else None,
            } if label else None,
        }

        if not data.include_input_output:
            for span in trace_export["spans"]:
                span.pop("input", None)
                span.pop("output", None)

        traces_data.append(trace_export)

        if label and not label.exported:
            label.exported = True

    db.commit()
    audit_log(
        "curation_export_created",
        request_id=getattr(request.state, "request_id", None),
        project_id=str(project.id),
        trace_count=len(traces_data),
        format=data.format,
        include_input_output=data.include_input_output,
    )

    return {
        "format": data.format,
        "count": len(traces_data),
        "traces": traces_data,
    }
