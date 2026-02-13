"""Intelligence API endpoints for Nemotron-powered trace analysis."""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
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
    return await labeler.analyze_trace(trace_data)


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
    return await labeler.self_analyze(trace_data)


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
    }


@router.get("/clusters")
async def get_clusters(
    project: Project = Depends(verify_api_key),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Get trace clusters for the current project."""
    _require_nvidia_key()
    _ = project

    from app.intelligence.clustering import cluster_traces, get_cluster_summary
    from app.intelligence.embeddings import get_trace_embeddings, trace_to_text

    # Get all traces
    traces = db.query(Trace).order_by(Trace.created_at.desc()).limit(500).all()
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
    result = cluster_traces(embeddings, project_id="default")
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
