"""Intelligence API endpoints for Nemotron-powered trace analysis."""

import logging
from math import isfinite
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


def _safe_number(value: Any) -> float:
    """Convert nullable numeric values to finite float."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not isfinite(number):
        return 0.0
    return number


def _pct_change(previous: float, current: float) -> float:
    """Return percent change from previous -> current."""
    if previous == 0:
        return 100.0 if current > 0 else 0.0
    return ((current - previous) / previous) * 100.0


def _compare_trace_metrics(
    baseline_trace: Trace,
    baseline_spans: list[Span],
    candidate_trace: Trace,
    candidate_spans: list[Span],
) -> dict[str, Any]:
    """Build deterministic metrics + regression signals between two traces."""
    llm_calls_a = sum(1 for span in baseline_spans if span.span_type == "llm")
    llm_calls_b = sum(1 for span in candidate_spans if span.span_type == "llm")
    tool_calls_a = sum(1 for span in baseline_spans if span.span_type == "tool")
    tool_calls_b = sum(1 for span in candidate_spans if span.span_type == "tool")

    metrics = [
        {
            "name": "duration_ms",
            "label": "Duration",
            "a": _safe_number(baseline_trace.duration_ms),
            "b": _safe_number(candidate_trace.duration_ms),
            "higher_is_better": False,
        },
        {
            "name": "error_count",
            "label": "Errors",
            "a": _safe_number(baseline_trace.error_count),
            "b": _safe_number(candidate_trace.error_count),
            "higher_is_better": False,
        },
        {
            "name": "total_tokens",
            "label": "Tokens",
            "a": _safe_number(baseline_trace.total_tokens),
            "b": _safe_number(candidate_trace.total_tokens),
            "higher_is_better": False,
        },
        {
            "name": "total_cost",
            "label": "Cost",
            "a": _safe_number(baseline_trace.total_cost),
            "b": _safe_number(candidate_trace.total_cost),
            "higher_is_better": False,
        },
        {
            "name": "span_count",
            "label": "Span Count",
            "a": _safe_number(baseline_trace.span_count),
            "b": _safe_number(candidate_trace.span_count),
            "higher_is_better": False,
        },
        {
            "name": "llm_calls",
            "label": "LLM Calls",
            "a": float(llm_calls_a),
            "b": float(llm_calls_b),
            "higher_is_better": False,
        },
        {
            "name": "tool_calls",
            "label": "Tool Calls",
            "a": float(tool_calls_a),
            "b": float(tool_calls_b),
            "higher_is_better": False,
        },
    ]

    enriched_metrics: list[dict[str, Any]] = []
    for metric in metrics:
        delta = metric["b"] - metric["a"]
        delta_pct = _pct_change(metric["a"], metric["b"])
        direction = "unchanged"
        if abs(delta) > 0:
            improved = delta > 0 if metric["higher_is_better"] else delta < 0
            direction = "improved" if improved else "regressed"
        enriched_metrics.append(
            {
                "name": metric["name"],
                "label": metric["label"],
                "trace_a": metric["a"],
                "trace_b": metric["b"],
                "delta": delta,
                "delta_pct": delta_pct,
                "direction": direction,
            }
        )

    signals: list[dict[str, Any]] = []
    actions: list[str] = []
    severity_weight = {"critical": 35, "high": 25, "medium": 15, "low": 8}
    score = 0

    duration_pct = _pct_change(_safe_number(baseline_trace.duration_ms), _safe_number(candidate_trace.duration_ms))
    if duration_pct >= 25:
        signals.append(
            {
                "id": "latency-regression",
                "title": "Latency Regression",
                "severity": "high",
                "kind": "performance",
                "detail": f"Trace B is {duration_pct:.1f}% slower than Trace A.",
                "recommendation": "Inspect the slowest span deltas and reduce redundant calls.",
            }
        )
        actions.append("Profile top slow spans and remove duplicated steps.")
        score += severity_weight["high"]
    elif duration_pct <= -20:
        signals.append(
            {
                "id": "latency-improvement",
                "title": "Latency Improvement",
                "severity": "low",
                "kind": "performance",
                "detail": f"Trace B is {-duration_pct:.1f}% faster than Trace A.",
                "recommendation": "Promote this execution pattern as a default path.",
            }
        )

    error_delta = int(_safe_number(candidate_trace.error_count) - _safe_number(baseline_trace.error_count))
    if error_delta > 0:
        signals.append(
            {
                "id": "error-regression",
                "title": "Reliability Regression",
                "severity": "critical",
                "kind": "reliability",
                "detail": f"Trace B has {error_delta} more error spans than Trace A.",
                "recommendation": "Review erroring spans first; add retries/fallbacks only where deterministic.",
            }
        )
        actions.append("Fix newly introduced erroring spans before optimizing for speed.")
        score += severity_weight["critical"]

    token_pct = _pct_change(_safe_number(baseline_trace.total_tokens), _safe_number(candidate_trace.total_tokens))
    if token_pct >= 30 and duration_pct > -5:
        signals.append(
            {
                "id": "token-inefficiency",
                "title": "Token Inefficiency",
                "severity": "medium",
                "kind": "efficiency",
                "detail": f"Trace B uses {token_pct:.1f}% more tokens with limited latency improvement.",
                "recommendation": "Tighten prompts and reduce repeated context in LLM calls.",
            }
        )
        actions.append("Reduce prompt/context size and cache repeatable intermediate results.")
        score += severity_weight["medium"]

    cost_pct = _pct_change(_safe_number(baseline_trace.total_cost), _safe_number(candidate_trace.total_cost))
    if cost_pct >= 30:
        signals.append(
            {
                "id": "cost-regression",
                "title": "Cost Regression",
                "severity": "medium",
                "kind": "cost",
                "detail": f"Trace B increases cost by {cost_pct:.1f}%.",
                "recommendation": "Use cheaper models/tools on non-critical steps and trim excess calls.",
            }
        )
        actions.append("Downshift model/tool usage for low-risk substeps.")
        score += severity_weight["medium"]

    tool_pct = _pct_change(float(tool_calls_a), float(tool_calls_b))
    if tool_pct >= 40 and duration_pct >= 10:
        signals.append(
            {
                "id": "tool-overhead",
                "title": "Tooling Overhead",
                "severity": "medium",
                "kind": "complexity",
                "detail": f"Trace B has {tool_pct:.1f}% more tool calls and is slower.",
                "recommendation": "Batch or parallelize tool calls where ordering is not required.",
            }
        )
        actions.append("Batch/parallelize tool calls to reduce serial overhead.")
        score += severity_weight["medium"]

    if not signals:
        actions.append("No major regressions detected. Keep this trace as a baseline candidate.")

    if score >= 55:
        status = "regressed"
    elif score == 0:
        status = "improved" if duration_pct < 0 and error_delta <= 0 else "neutral"
    else:
        status = "mixed"

    deduped_actions = list(dict.fromkeys(actions))[:3]
    regression_score = max(0, min(100, score))

    return {
        "trace_a_id": str(baseline_trace.id),
        "trace_b_id": str(candidate_trace.id),
        "summary": {
            "status": status,
            "regression_score": regression_score,
            "signal_count": len(signals),
        },
        "metrics": enriched_metrics,
        "signals": signals,
        "top_actions": deduped_actions,
    }


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


def _suggest_curation_from_analysis(analysis_result: dict[str, Any], trace_id: str) -> dict[str, Any]:
    """Build a deterministic curation suggestion from normalized analysis output."""
    quality = int(analysis_result.get("quality_score", 0))
    summary = str(analysis_result.get("analysis", {}).get("summary", "")).strip()
    suggestions = analysis_result.get("suggestions", []) or []
    labels = analysis_result.get("analysis", {}).get("labels", []) or []

    if quality >= 85:
        label = "excellent"
    elif quality >= 70:
        label = "good"
    elif quality >= 50:
        label = "needs_improvement"
    else:
        label = "failure"

    quality_score_1_5 = max(1, min(5, int(round(quality / 20))))
    top_suggestions = [str(s).strip() for s in suggestions[:2] if str(s).strip()]
    notes_parts = []
    if summary:
        notes_parts.append(f"AI Summary: {summary}")
    if top_suggestions:
        notes_parts.append("Top suggestions: " + "; ".join(top_suggestions))
    if labels:
        notes_parts.append("Detected labels: " + ", ".join(str(label_name) for label_name in labels[:3]))

    return {
        "trace_id": trace_id,
        "label": label,
        "quality_score": quality_score_1_5,
        "notes": " | ".join(notes_parts) if notes_parts else None,
        "source_quality_score": quality,
    }


# --- Request/Response schemas ---


class AnalyzeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trace_id: str = Field(min_length=1, max_length=128, pattern=ID_PATTERN)


class SelfAnalyzeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trace_id: str = Field(min_length=1, max_length=128, pattern=ID_PATTERN)


class SuggestCurationRequest(BaseModel):
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


class CompareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trace_a_id: str = Field(min_length=1, max_length=128, pattern=ID_PATTERN)
    trace_b_id: str = Field(min_length=1, max_length=128, pattern=ID_PATTERN)


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


@router.post("/compare")
async def compare_traces(
    req: CompareRequest,
    project: Project = Depends(verify_api_key),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Compare two traces and return deterministic regression signals."""
    trace_a = db.query(Trace).filter(Trace.id == req.trace_a_id, Trace.project_id == project.id).first()
    trace_b = db.query(Trace).filter(Trace.id == req.trace_b_id, Trace.project_id == project.id).first()
    if not trace_a or not trace_b:
        raise HTTPException(status_code=404, detail="Trace not found")

    spans_a = db.query(Span).filter(Span.trace_id == req.trace_a_id).all()
    spans_b = db.query(Span).filter(Span.trace_id == req.trace_b_id).all()
    return _compare_trace_metrics(trace_a, spans_a, trace_b, spans_b)


@router.get("/status")
async def intelligence_status(
    _project: Project = Depends(verify_api_key),
) -> dict[str, Any]:
    """Return intelligence setup status for dashboard/demo checks."""
    return {
        "nvidia_api_key_configured": bool(settings.nvidia_api_key),
        "model": settings.nvidia_llm_model,
        "base_url": settings.nvidia_base_url,
    }


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


@router.post("/suggest-curation")
async def suggest_curation(
    req: SuggestCurationRequest,
    project: Project = Depends(verify_api_key),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Generate a curation suggestion (label/score/notes) from AI trace analysis."""
    _require_nvidia_key()

    from app.intelligence.llm import LLMLabeler

    trace_data = _get_trace_data(req.trace_id, project.id, db)
    labeler = LLMLabeler()
    result = await labeler.analyze_trace(trace_data)
    normalized = _normalize_analyze_result(result, req.trace_id)
    return _suggest_curation_from_analysis(normalized, req.trace_id)


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
