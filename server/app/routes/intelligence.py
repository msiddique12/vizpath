"""Intelligence API endpoints for Nemotron-powered trace analysis."""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.orm import Session

from app.auth import verify_api_key
from app.config import settings
from app.database import get_db
from app.models import Project, Span, Trace
from app.validation import ID_PATTERN

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/intelligence", tags=["Intelligence"])


def _require_nvidia_key() -> None:
    """Raise 503 if NVIDIA API key is not configured."""
    if not settings.nvidia_api_key:
        raise HTTPException(
            status_code=503,
            detail="NVIDIA API key not configured. Set NVIDIA_API_KEY env var.",
        )


def _get_trace_data(trace_id: str, project_id: Any, db: Session) -> dict[str, Any]:
    """Load trace + spans as a dict, or raise 404."""
    trace = db.query(Trace).filter(Trace.id == trace_id, Trace.project_id == project_id).first()
    if not trace:
        raise HTTPException(status_code=404, detail="Trace not found")

    spans = db.query(Span).filter(Span.trace_id == trace_id).all()
    data = trace.to_dict()
    data["spans"] = [s.to_dict() for s in spans]
    return data


def _normalize_analyze_result(result: dict[str, Any], trace_id: str) -> dict[str, Any]:
    """Return response with both flat and nested analysis fields."""
    analysis = result.get("analysis")
    if not isinstance(analysis, dict):
        analysis = {
            "quality_score": result.get("quality_score", 0),
            "labels": result.get("labels", []),
            "suggestions": result.get("suggestions", []),
            "summary": result.get("summary", result.get("error_analysis", "")),
        }

    return {
        "trace_id": result.get("trace_id", trace_id),
        "quality_score": result.get("quality_score", analysis.get("quality_score", 0)),
        "efficiency_score": result.get("efficiency_score", 0),
        "error_analysis": result.get("error_analysis", analysis.get("summary", "")),
        "suggestions": result.get("suggestions", analysis.get("suggestions", [])),
        "analysis": analysis,
        "cached": result.get("cached", False),
    }


def _normalize_self_analyze_result(result: dict[str, Any], trace_id: str) -> dict[str, Any]:
    """Return response with both flat and nested self-analysis fields."""
    analysis = result.get("analysis")
    if not isinstance(analysis, dict):
        analysis = {
            "effectiveness": result.get("effectiveness", result.get("quality", 0)),
            "reasoning_quality": result.get("reasoning_quality", result.get("completeness", 0)),
            "tool_usage": result.get("tool_usage", result.get("efficiency", 0)),
            "overall_score": result.get("overall_score", 0),
            "strengths": result.get("strengths", []),
            "weaknesses": result.get("weaknesses", []),
            "improvements": result.get("improvements", result.get("suggestions", [])),
            "summary": result.get("summary", ""),
        }

    return {
        "trace_id": result.get("trace_id", trace_id),
        "quality": result.get("quality", analysis.get("effectiveness", 0)),
        "efficiency": result.get("efficiency", analysis.get("tool_usage", 0)),
        "completeness": result.get("completeness", analysis.get("reasoning_quality", 0)),
        "overall_score": result.get("overall_score", analysis.get("overall_score", 0)),
        "redundant_steps": result.get("redundant_steps", []),
        "suggestions": result.get("suggestions", analysis.get("improvements", [])),
        "summary": result.get("summary", analysis.get("summary", "")),
        "analysis": analysis,
        "cached": result.get("cached", False),
    }


# --- Request/Response schemas ---


class AnalyzeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trace_id: str = Field(min_length=1, max_length=128, pattern=ID_PATTERN)


class SelfAnalyzeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trace_id: str = Field(min_length=1, max_length=128, pattern=ID_PATTERN)


class EmbedRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trace_id: str = Field(min_length=1, max_length=128, pattern=ID_PATTERN)


class SyntheticRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trace_id: str = Field(min_length=1, max_length=128, pattern=ID_PATTERN)
    mode: str = Field(default="variations", pattern="^(variations|corrections)$")
    n: int = Field(default=5, ge=1, le=20)
    type: str | None = Field(default=None, pattern="^(variations|corrections)$")
    count: int | None = Field(default=None, ge=1, le=20)

    @model_validator(mode="after")
    def normalize_legacy_fields(self) -> "SyntheticRequest":
        if self.type is not None:
            self.mode = self.type
        if self.count is not None:
            self.n = self.count
        return self


# --- Endpoints ---


@router.post("/analyze")
async def analyze_trace(
    req: AnalyzeRequest,
    project: Project = Depends(verify_api_key),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Analyze a trace for quality and efficiency."""
    _require_nvidia_key()

    from app.intelligence.llm import LLMLabeler

    trace_data = _get_trace_data(req.trace_id, project.id, db)
    labeler = LLMLabeler()
    result = await labeler.analyze_trace(trace_data)
    return _normalize_analyze_result(result, req.trace_id)


@router.post("/self-analyze")
async def self_analyze_trace(
    req: SelfAnalyzeRequest,
    project: Project = Depends(verify_api_key),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Deep evaluation of agent decision-making quality."""
    _require_nvidia_key()

    from app.intelligence.llm import LLMLabeler

    trace_data = _get_trace_data(req.trace_id, project.id, db)
    labeler = LLMLabeler()
    result = await labeler.self_analyze(trace_data)
    return _normalize_self_analyze_result(result, req.trace_id)


@router.post("/embed")
async def embed_trace_endpoint(
    req: EmbedRequest,
    project: Project = Depends(verify_api_key),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Generate an embedding for a trace."""
    _require_nvidia_key()

    from app.intelligence.embeddings import embed_trace, trace_to_text

    trace_data = _get_trace_data(req.trace_id, project.id, db)
    text = trace_to_text(trace_data)
    embedding = await embed_trace(req.trace_id, text)
    return {
        "trace_id": req.trace_id,
        "embedding_dim": len(embedding),
        "embedding": embedding.tolist(),
    }


@router.post("/generate-synthetic")
async def generate_synthetic(
    req: SyntheticRequest,
    project: Project = Depends(verify_api_key),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Generate synthetic training data from a trace."""
    _require_nvidia_key()

    from app.intelligence.synthetic import SyntheticDataGenerator

    trace_data = _get_trace_data(req.trace_id, project.id, db)
    generator = SyntheticDataGenerator()

    if req.mode == "variations":
        results = await generator.generate_variations(trace_data, n=req.n)
    else:
        results = await generator.generate_corrections(trace_data, n=req.n)

    return {
        "trace_id": req.trace_id,
        "mode": req.mode,
        "count": len(results),
        "results": results,
        "type": req.mode,
        "variations": results,
    }


@router.get("/clusters")
async def get_clusters(
    project: Project = Depends(verify_api_key),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Get trace clusters for the current project."""
    _require_nvidia_key()

    from app.intelligence.clustering import cluster_traces, get_cluster_summary
    from app.intelligence.embeddings import get_trace_embeddings, trace_to_text

    # Get traces for the current project only
    traces = (
        db.query(Trace)
        .filter(Trace.project_id == project.id)
        .order_by(Trace.created_at.desc())
        .limit(500)
        .all()
    )
    if len(traces) < 2:
        return {"clusters": [], "message": "Not enough traces to cluster"}

    # Build text representations
    trace_texts: dict[str, str] = {}
    for t in traces:
        spans = db.query(Span).filter(Span.trace_id == t.id).all()
        data = t.to_dict()
        data["spans"] = [s.to_dict() for s in spans]
        trace_texts[str(t.id)] = trace_to_text(data)

    # Get embeddings
    embeddings = await get_trace_embeddings(trace_texts)

    # Cluster
    result = cluster_traces(embeddings, project_id=str(project.id))
    if not result:
        return {"clusters": [], "message": "Clustering did not produce results"}

    # Build per-cluster ID lists
    cluster_map = result["clusters"]
    ids_per_cluster: dict[int, list[str]] = {}
    for tid, cid in cluster_map.items():
        ids_per_cluster.setdefault(cid, []).append(tid)

    summaries = get_cluster_summary(ids_per_cluster, embeddings, result["centroids"], db)

    return {
        "cluster_count": len(summaries),
        "clusters": list(summaries.values()),
    }
