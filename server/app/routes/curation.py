"""Curation endpoints for trace labeling and export."""

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import CuratedLabel, Trace, Span


router = APIRouter(prefix="/curation", tags=["curation"])


class LabelCreate(BaseModel):
    trace_id: UUID
    label: Optional[str] = None
    quality_score: Optional[float] = None
    notes: Optional[str] = None


class LabelUpdate(BaseModel):
    label: Optional[str] = None
    quality_score: Optional[float] = None
    notes: Optional[str] = None
    exported: Optional[bool] = None


class LabelResponse(BaseModel):
    id: UUID
    trace_id: UUID
    label: Optional[str]
    quality_score: Optional[float]
    notes: Optional[str]
    exported: bool
    created_at: str
    updated_at: Optional[str]

    class Config:
        from_attributes = True


class CuratedTraceResponse(BaseModel):
    trace_id: UUID
    trace_name: str
    label: Optional[str]
    quality_score: Optional[float]
    notes: Optional[str]
    exported: bool
    span_count: int
    total_tokens: Optional[int]
    duration_ms: Optional[float]


class ExportRequest(BaseModel):
    trace_ids: List[UUID]
    format: str = "jsonl"
    include_input_output: bool = True


@router.post("/labels", response_model=LabelResponse)
def create_or_update_label(
    data: LabelCreate,
    db: Session = Depends(get_db),
) -> LabelResponse:
    """Create or update a label for a trace."""
    trace = db.execute(
        select(Trace).where(Trace.id == data.trace_id)
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


@router.get("/labels/{trace_id}", response_model=Optional[LabelResponse])
def get_label(
    trace_id: UUID,
    db: Session = Depends(get_db),
) -> Optional[LabelResponse]:
    """Get the label for a specific trace."""
    label = db.execute(
        select(CuratedLabel).where(CuratedLabel.trace_id == trace_id)
    ).scalar_one_or_none()

    if not label:
        return None

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


@router.delete("/labels/{trace_id}")
def delete_label(
    trace_id: UUID,
    db: Session = Depends(get_db),
) -> dict:
    """Delete a label for a trace."""
    label = db.execute(
        select(CuratedLabel).where(CuratedLabel.trace_id == trace_id)
    ).scalar_one_or_none()

    if not label:
        raise HTTPException(status_code=404, detail="Label not found")

    db.delete(label)
    db.commit()
    return {"status": "deleted"}


@router.get("/traces", response_model=List[CuratedTraceResponse])
def list_curated_traces(
    label: Optional[str] = Query(None, description="Filter by label"),
    exported: Optional[bool] = Query(None, description="Filter by export status"),
    min_score: Optional[float] = Query(None, description="Minimum quality score"),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> List[CuratedTraceResponse]:
    """List traces with curation labels."""
    query = (
        select(Trace, CuratedLabel)
        .outerjoin(CuratedLabel, Trace.id == CuratedLabel.trace_id)
        .where(CuratedLabel.id.isnot(None))
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
def get_curation_stats(db: Session = Depends(get_db)) -> dict:
    """Get curation statistics."""
    from sqlalchemy import func

    total_labeled = db.execute(
        select(func.count(CuratedLabel.id))
    ).scalar() or 0

    exported_count = db.execute(
        select(func.count(CuratedLabel.id)).where(CuratedLabel.exported == True)
    ).scalar() or 0

    label_counts = db.execute(
        select(CuratedLabel.label, func.count(CuratedLabel.id))
        .where(CuratedLabel.label.isnot(None))
        .group_by(CuratedLabel.label)
    ).all()

    avg_score = db.execute(
        select(func.avg(CuratedLabel.quality_score))
        .where(CuratedLabel.quality_score.isnot(None))
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
    db: Session = Depends(get_db),
) -> dict:
    """Export curated traces in specified format."""
    traces_data = []

    for trace_id in data.trace_ids:
        trace = db.execute(
            select(Trace).where(Trace.id == trace_id)
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

    return {
        "format": data.format,
        "count": len(traces_data),
        "traces": traces_data,
    }
