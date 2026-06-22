"""Product feature endpoints built on top of trace and span data."""

from __future__ import annotations

import math
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.auth import verify_api_key
from app.database import get_db
from app.models import CuratedLabel, EvalCase, EvalCaseResult, EvalRun, EvalSuite, Project, Span, Trace
from app.security import audit_log

router = APIRouter(tags=["Product"])


class DatasetBuildRequest(BaseModel):
    """Build a training/eval dataset from selected traces."""

    model_config = ConfigDict(extra="forbid")

    trace_ids: list[str] = Field(min_length=1, max_length=500)
    format: str = Field(default="chat", pattern="^(chat|tool_calls|preference)$")
    include_failed: bool = False
    min_quality_score: float | None = Field(default=None, ge=0, le=100)


class EvalSuiteRequest(BaseModel):
    """Generate eval cases from selected traces."""

    model_config = ConfigDict(extra="forbid")

    trace_ids: list[str] = Field(min_length=1, max_length=500)
    name: str = Field(default="Trace regression suite", min_length=1, max_length=120)
    assertion_profile: str = Field(
        default="balanced",
        pattern="^(balanced|strict|latency|cost|tooling)$",
    )


class EvalRunCreateRequest(BaseModel):
    """Record a deterministic eval run against candidate traces."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(default="Candidate eval run", min_length=1, max_length=120)
    candidate_trace_ids: list[str] = Field(min_length=1, max_length=500)


class TraceSearchRequest(BaseModel):
    """Search traces across names, metadata, span inputs/outputs, and errors."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=300)
    limit: int = Field(default=10, ge=1, le=50)
    include_spans: bool = True


class GuardrailPolicy(BaseModel):
    """A deterministic guardrail policy evaluated against trace metrics."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=120)
    metric: str = Field(
        pattern="^(total_cost|total_tokens|duration_ms|error_count|llm_calls|tool_calls|span_count)$"
    )
    operator: str = Field(pattern="^(gt|gte|lt|lte|eq)$")
    threshold: float
    severity: str = Field(default="medium", pattern="^(low|medium|high|critical)$")


class GuardrailEvaluateRequest(BaseModel):
    """Evaluate guardrail policies against one trace or recent traces."""

    model_config = ConfigDict(extra="forbid")

    trace_id: str | None = Field(default=None, max_length=128)
    policies: list[GuardrailPolicy] = Field(default_factory=list, max_length=50)
    window_days: int = Field(default=7, ge=1, le=90)
    limit: int = Field(default=50, ge=1, le=200)


def _cutoff(window_days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=window_days)


def _safe_number(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number if math.isfinite(number) else 0.0


def _serialize(value: Any, limit: int = 1200) -> str:
    if value is None:
        return ""
    text = str(value)
    return text[:limit]


_SENSITIVE_KEYS = {
    "authorization",
    "api_key",
    "apikey",
    "password",
    "access_token",
    "refresh_token",
    "secret",
    "private_key",
    "token",
}


def _redact_sensitive_value(value: Any) -> Any:
    """Redact sensitive fields in persisted eval and dataset artifacts."""
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, nested in value.items():
            if isinstance(key, str) and key.lower() in _SENSITIVE_KEYS:
                redacted[key] = "[REDACTED]"
            else:
                redacted[key] = _redact_sensitive_value(nested)
        return redacted
    if isinstance(value, list):
        return [_redact_sensitive_value(item) for item in value]
    if isinstance(value, tuple):
        return [_redact_sensitive_value(item) for item in value]
    return value


def _load_trace_bundle(db: Session, project_id: Any, trace_id: str) -> tuple[Trace, list[Span]]:
    trace = db.query(Trace).filter(Trace.id == trace_id, Trace.project_id == project_id).first()
    if not trace:
        raise HTTPException(status_code=404, detail="Trace not found")
    spans = (
        db.query(Span)
        .filter(Span.trace_id == trace_id)
        .order_by(Span.start_time.asc(), Span.created_at.asc())
        .all()
    )
    return trace, spans


def _trace_text(trace: Trace, spans: list[Span]) -> str:
    parts = [
        trace.name,
        trace.status,
        _serialize(trace.trace_metadata),
    ]
    for span in spans:
        parts.extend(
            [
                span.name,
                span.span_type,
                span.status,
                _serialize(span.attributes),
                _serialize(span.input),
                _serialize(span.output),
                _serialize(span.error),
            ]
        )
    return " ".join(part for part in parts if part).lower()


def _span_text(span: Span) -> str:
    parts = [
        span.name,
        span.span_type,
        span.status,
        _serialize(span.attributes),
        _serialize(span.input),
        _serialize(span.output),
        _serialize(span.error),
    ]
    return " ".join(part for part in parts if part).lower()


def _trace_metrics(trace: Trace, spans: list[Span]) -> dict[str, float]:
    span_duration_total = sum(_safe_number(span.duration_ms) for span in spans)
    span_token_total = sum(_safe_number(span.tokens) for span in spans)
    span_cost_total = sum(_safe_number(span.cost) for span in spans)
    duration_ms = _safe_number(trace.duration_ms)
    total_tokens = _safe_number(trace.total_tokens)
    total_cost = _safe_number(trace.total_cost)
    return {
        "duration_ms": duration_ms if duration_ms > 0 else span_duration_total,
        "error_count": _safe_number(trace.error_count),
        "total_tokens": total_tokens if total_tokens > 0 else span_token_total,
        "total_cost": total_cost if total_cost > 0 else span_cost_total,
        "span_count": _safe_number(trace.span_count or len(spans)),
        "llm_calls": float(sum(1 for span in spans if span.span_type == "llm")),
        "tool_calls": float(sum(1 for span in spans if span.span_type == "tool")),
    }


def _first_meaningful_input(spans: list[Span]) -> Any:
    for span in spans:
        if span.input is not None:
            return span.input
    return None


def _last_meaningful_output(spans: list[Span]) -> Any:
    for span in reversed(spans):
        if span.output is not None:
            return span.output
    return None


def _label_for_trace(db: Session, trace_id: str) -> CuratedLabel | None:
    return db.query(CuratedLabel).filter(CuratedLabel.trace_id == trace_id).first()


def _compare(operator: str, value: float, threshold: float) -> bool:
    if operator == "gt":
        return value > threshold
    if operator == "gte":
        return value >= threshold
    if operator == "lt":
        return value < threshold
    if operator == "lte":
        return value <= threshold
    return value == threshold


def _build_eval_case_payload(
    trace_id: str,
    trace: Trace,
    spans: list[Span],
    assertion_profile: str,
) -> dict[str, Any]:
    metrics = _trace_metrics(trace, spans)
    assertions = [
        {"metric": "error_count", "operator": "eq", "threshold": 0},
        {"metric": "span_count", "operator": "lte", "threshold": max(metrics["span_count"] + 2, 3)},
    ]
    if assertion_profile in {"balanced", "strict", "latency"} and metrics["duration_ms"] > 0:
        multiplier = 1.1 if assertion_profile == "strict" else 1.5
        assertions.append(
            {
                "metric": "duration_ms",
                "operator": "lte",
                "threshold": round(metrics["duration_ms"] * multiplier, 2),
            }
        )
    if assertion_profile in {"balanced", "strict", "cost"} and metrics["total_cost"] > 0:
        assertions.append(
            {
                "metric": "total_cost",
                "operator": "lte",
                "threshold": round(metrics["total_cost"] * 1.25, 6),
            }
        )
    if assertion_profile in {"strict", "tooling"}:
        assertions.append(
            {
                "metric": "tool_calls",
                "operator": "lte",
                "threshold": max(metrics["tool_calls"] + 1, 1),
            }
        )

    return {
        "id": f"eval-{trace_id}",
        "source_trace_id": trace_id,
        "name": trace.name,
        "input": _redact_sensitive_value(_first_meaningful_input(spans)),
        "expected_output": _redact_sensitive_value(_last_meaningful_output(spans)),
        "baseline_metrics": metrics,
        "assertions": assertions,
    }


def _serialize_eval_suite(suite: EvalSuite, *, include_cases: bool = False) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": str(suite.id),
        "name": suite.name,
        "assertion_profile": suite.assertion_profile,
        "source_trace_ids": suite.source_trace_ids or [],
        "case_count": len(suite.cases),
        "run_count": len(suite.runs),
        "created_at": suite.created_at.isoformat() if suite.created_at else None,
        "updated_at": suite.updated_at.isoformat() if suite.updated_at else None,
    }
    if include_cases:
        payload["cases"] = [
            {
                "id": str(case.id),
                "source_trace_id": case.source_trace_id,
                "name": case.name,
                "input": case.input,
                "expected_output": case.expected_output,
                "baseline_metrics": case.baseline_metrics,
                "assertions": case.assertions,
            }
            for case in suite.cases
        ]
        payload["runs"] = [_serialize_eval_run(run, include_results=False) for run in suite.runs]
    return payload


def _serialize_eval_run(run: EvalRun, *, include_results: bool = True) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": str(run.id),
        "suite_id": str(run.suite_id),
        "name": run.name,
        "candidate_trace_ids": run.candidate_trace_ids or [],
        "passed": run.passed,
        "pass_count": run.pass_count,
        "fail_count": run.fail_count,
        "created_at": run.created_at.isoformat() if run.created_at else None,
    }
    if include_results:
        payload["results"] = [
            {
                "id": str(result.id),
                "case_id": str(result.case_id),
                "candidate_trace_id": result.candidate_trace_id,
                "passed": result.passed,
                "metrics": result.metrics,
                "assertion_results": result.assertion_results,
            }
            for result in run.results
        ]
    return payload


def _evaluate_case_against_trace(case: EvalCase, trace: Trace, spans: list[Span]) -> dict[str, Any]:
    metrics = _trace_metrics(trace, spans)
    assertion_results = []
    for assertion in case.assertions or []:
        metric = str(assertion.get("metric", ""))
        value = metrics.get(metric, 0.0)
        operator = str(assertion.get("operator", "eq"))
        threshold = float(assertion.get("threshold", 0.0))
        passed = _compare(operator, float(value), threshold)
        assertion_results.append(
            {
                "metric": metric,
                "operator": operator,
                "threshold": threshold,
                "current_value": value,
                "passed": passed,
            }
        )
    return {
        "metrics": metrics,
        "assertion_results": assertion_results,
        "passed": all(item["passed"] for item in assertion_results),
    }


def _default_guardrail_policies() -> list[GuardrailPolicy]:
    return [
        GuardrailPolicy(
            id="trace-errors",
            name="No error spans",
            metric="error_count",
            operator="eq",
            threshold=0,
            severity="critical",
        ),
        GuardrailPolicy(
            id="cost-cap",
            name="Trace cost below $0.25",
            metric="total_cost",
            operator="lte",
            threshold=0.25,
            severity="medium",
        ),
        GuardrailPolicy(
            id="llm-call-cap",
            name="LLM calls below 8",
            metric="llm_calls",
            operator="lte",
            threshold=8,
            severity="medium",
        ),
        GuardrailPolicy(
            id="latency-cap",
            name="Trace latency below 30s",
            metric="duration_ms",
            operator="lte",
            threshold=30000,
            severity="high",
        ),
    ]


@router.get("/analytics/scorecard")
async def agent_scorecard(
    project: Project = Depends(verify_api_key),
    db: Session = Depends(get_db),
    window_days: int = Query(default=7, ge=1, le=90),
) -> dict[str, Any]:
    """Return project-level agent reliability, latency, cost, and efficiency KPIs."""
    traces = (
        db.query(Trace)
        .filter(Trace.project_id == project.id, Trace.created_at >= _cutoff(window_days))
        .order_by(Trace.created_at.desc())
        .limit(5000)
        .all()
    )
    trace_ids = [trace.id for trace in traces]
    span_rows = db.query(Span).filter(Span.trace_id.in_(trace_ids)).all() if trace_ids else []

    count = len(traces)
    success_count = sum(1 for trace in traces if trace.status == "success")
    error_count = sum(1 for trace in traces if trace.status == "error")
    running_count = sum(1 for trace in traces if trace.status == "running")
    durations = sorted(_safe_number(trace.duration_ms) for trace in traces if trace.duration_ms is not None)
    total_tokens = int(sum(_safe_number(trace.total_tokens) for trace in traces))
    total_cost = sum(_safe_number(trace.total_cost) for trace in traces)
    tool_spans = [span for span in span_rows if span.span_type == "tool"]
    llm_spans = [span for span in span_rows if span.span_type == "llm"]
    tool_success = sum(1 for span in tool_spans if span.status == "success")

    def percentile(values: list[float], pct: float) -> float | None:
        if not values:
            return None
        index = min(len(values) - 1, max(0, round((pct / 100) * (len(values) - 1))))
        return values[index]

    reliability = (success_count / count * 100) if count else 0.0
    tool_success_rate = (tool_success / len(tool_spans) * 100) if tool_spans else None
    avg_cost = (total_cost / count) if count else None
    avg_tokens = (total_tokens / count) if count else None

    return {
        "window_days": window_days,
        "trace_count": count,
        "success_count": success_count,
        "error_count": error_count,
        "running_count": running_count,
        "reliability_score": round(reliability, 2),
        "p50_duration_ms": percentile(durations, 50),
        "p95_duration_ms": percentile(durations, 95),
        "total_tokens": total_tokens,
        "total_cost": round(total_cost, 6),
        "avg_tokens_per_trace": round(avg_tokens, 2) if avg_tokens is not None else None,
        "avg_cost_per_trace": round(avg_cost, 6) if avg_cost is not None else None,
        "tool_success_rate": round(tool_success_rate, 2) if tool_success_rate is not None else None,
        "llm_call_count": len(llm_spans),
        "tool_call_count": len(tool_spans),
    }


@router.get("/analytics/tools")
async def tool_analytics(
    project: Project = Depends(verify_api_key),
    db: Session = Depends(get_db),
    window_days: int = Query(default=7, ge=1, le=90),
) -> dict[str, Any]:
    """Return reliability, latency, errors, and token/cost impact per tool span name."""
    traces = (
        db.query(Trace.id)
        .filter(Trace.project_id == project.id, Trace.created_at >= _cutoff(window_days))
        .subquery()
    )
    rows = (
        db.query(
            Span.name,
            func.count(Span.id),
            func.sum(case((Span.status == "success", 1), else_=0)),
            func.sum(case((Span.status == "error", 1), else_=0)),
            func.avg(Span.duration_ms),
            func.sum(Span.tokens),
            func.sum(Span.cost),
        )
        .join(traces, traces.c.id == Span.trace_id)
        .filter(Span.span_type == "tool")
        .group_by(Span.name)
        .order_by(func.count(Span.id).desc())
        .all()
    )

    tools = []
    for name, count, success, errors, avg_duration, tokens, cost in rows:
        count_value = int(count or 0)
        success_value = int(success or 0)
        error_value = int(errors or 0)
        tools.append(
            {
                "name": name,
                "call_count": count_value,
                "success_count": success_value,
                "error_count": error_value,
                "success_rate": round((success_value / count_value * 100), 2) if count_value else 0,
                "avg_duration_ms": round(float(avg_duration), 2) if avg_duration is not None else None,
                "total_tokens": int(tokens or 0),
                "total_cost": round(float(cost or 0), 6),
            }
        )

    return {
        "window_days": window_days,
        "tool_count": len(tools),
        "tools": tools,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.post("/datasets/build")
async def build_dataset(
    payload: DatasetBuildRequest,
    project: Project = Depends(verify_api_key),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Build dataset records from curated or selected traces."""
    records = []
    skipped = []
    for trace_id in payload.trace_ids:
        trace, spans = _load_trace_bundle(db, project.id, trace_id)
        label = _label_for_trace(db, trace_id)
        if not payload.include_failed and trace.status == "error":
            skipped.append({"trace_id": trace_id, "reason": "failed_trace"})
            continue
        if (
            payload.min_quality_score is not None
            and (label is None or label.quality_score is None or label.quality_score < payload.min_quality_score)
        ):
            skipped.append({"trace_id": trace_id, "reason": "below_quality_threshold"})
            continue

        item = {
            "trace_id": trace_id,
            "trace_name": trace.name,
            "label": label.label if label else None,
            "quality_score": label.quality_score if label else None,
            "metadata": trace.trace_metadata or {},
        }
        if payload.format == "chat":
            item["messages"] = [
                {"role": "user", "content": _serialize(_first_meaningful_input(spans), 4000)},
                {"role": "assistant", "content": _serialize(_last_meaningful_output(spans), 4000)},
            ]
        elif payload.format == "tool_calls":
            item["steps"] = [
                {
                    "span_id": span.id,
                    "name": span.name,
                    "type": span.span_type,
                    "input": span.input,
                    "output": span.output,
                    "error": span.error,
                }
                for span in spans
            ]
        else:
            item["prompt"] = _serialize(_first_meaningful_input(spans), 4000)
            item["chosen"] = _serialize(_last_meaningful_output(spans), 4000)
            item["rejected"] = ""
        records.append(item)

    return {
        "format": payload.format,
        "record_count": len(records),
        "skipped_count": len(skipped),
        "records": records,
        "skipped": skipped,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.post("/evals/suite")
async def build_eval_suite(
    payload: EvalSuiteRequest,
    project: Project = Depends(verify_api_key),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Generate executable eval case specs from traces."""
    cases = []
    for trace_id in payload.trace_ids:
        trace, spans = _load_trace_bundle(db, project.id, trace_id)
        cases.append(_build_eval_case_payload(trace_id, trace, spans, payload.assertion_profile))

    return {
        "name": payload.name,
        "assertion_profile": payload.assertion_profile,
        "case_count": len(cases),
        "cases": cases,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.post("/evals/suites", status_code=201)
async def create_saved_eval_suite(
    payload: EvalSuiteRequest,
    request: Request,
    project: Project = Depends(verify_api_key),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Persist an eval suite and its deterministic cases."""
    suite = EvalSuite(
        project_id=project.id,
        name=payload.name.strip(),
        assertion_profile=payload.assertion_profile,
        source_trace_ids=payload.trace_ids,
    )
    db.add(suite)
    db.flush()

    for trace_id in payload.trace_ids:
        trace, spans = _load_trace_bundle(db, project.id, trace_id)
        case_payload = _build_eval_case_payload(trace_id, trace, spans, payload.assertion_profile)
        db.add(
            EvalCase(
                suite_id=suite.id,
                source_trace_id=trace_id,
                name=case_payload["name"],
                input=case_payload["input"],
                expected_output=case_payload["expected_output"],
                baseline_metrics=case_payload["baseline_metrics"],
                assertions=case_payload["assertions"],
            )
        )

    db.commit()
    db.refresh(suite)
    audit_log(
        "eval_suite_created",
        request_id=getattr(request.state, "request_id", None),
        project_id=str(project.id),
        suite_id=str(suite.id),
        case_count=len(suite.cases),
        assertion_profile=suite.assertion_profile,
    )
    return _serialize_eval_suite(suite, include_cases=True)


@router.get("/evals/suites")
async def list_saved_eval_suites(
    project: Project = Depends(verify_api_key),
    db: Session = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    """List saved eval suites for the current project."""
    query = db.query(EvalSuite).filter(EvalSuite.project_id == project.id)
    total = query.count()
    suites = query.order_by(EvalSuite.created_at.desc()).offset(offset).limit(limit).all()
    return {
        "suites": [_serialize_eval_suite(suite) for suite in suites],
        "total": total,
        "limit": limit,
        "offset": offset,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/evals/suites/{suite_id}")
async def get_saved_eval_suite(
    suite_id: UUID,
    project: Project = Depends(verify_api_key),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Get a saved eval suite with cases and recent runs."""
    suite = (
        db.query(EvalSuite)
        .filter(EvalSuite.id == suite_id, EvalSuite.project_id == project.id)
        .first()
    )
    if not suite:
        raise HTTPException(status_code=404, detail="Eval suite not found")
    return _serialize_eval_suite(suite, include_cases=True)


@router.post("/evals/suites/{suite_id}/runs", status_code=201)
async def create_eval_run(
    payload: EvalRunCreateRequest,
    request: Request,
    suite_id: UUID,
    project: Project = Depends(verify_api_key),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Record a deterministic eval run against existing candidate traces."""
    suite = (
        db.query(EvalSuite)
        .filter(EvalSuite.id == suite_id, EvalSuite.project_id == project.id)
        .first()
    )
    if not suite:
        raise HTTPException(status_code=404, detail="Eval suite not found")

    candidate_bundles: dict[str, tuple[Trace, list[Span]]] = {}
    for trace_id in payload.candidate_trace_ids:
        candidate_bundles[trace_id] = _load_trace_bundle(db, project.id, trace_id)

    run = EvalRun(
        suite_id=suite.id,
        project_id=project.id,
        name=payload.name.strip(),
        candidate_trace_ids=payload.candidate_trace_ids,
        passed=False,
        pass_count=0,
        fail_count=0,
    )
    db.add(run)
    db.flush()

    pass_count = 0
    fail_count = 0
    for case in suite.cases:
        for candidate_trace_id, (candidate_trace, candidate_spans) in candidate_bundles.items():
            evaluation = _evaluate_case_against_trace(case, candidate_trace, candidate_spans)
            if evaluation["passed"]:
                pass_count += 1
            else:
                fail_count += 1
            db.add(
                EvalCaseResult(
                    run_id=run.id,
                    case_id=case.id,
                    candidate_trace_id=candidate_trace_id,
                    passed=evaluation["passed"],
                    metrics=evaluation["metrics"],
                    assertion_results=evaluation["assertion_results"],
                )
            )

    run.pass_count = pass_count
    run.fail_count = fail_count
    run.passed = fail_count == 0
    db.commit()
    db.refresh(run)
    audit_log(
        "eval_run_created",
        request_id=getattr(request.state, "request_id", None),
        project_id=str(project.id),
        suite_id=str(suite.id),
        run_id=str(run.id),
        candidate_trace_count=len(payload.candidate_trace_ids),
        pass_count=pass_count,
        fail_count=fail_count,
    )
    return _serialize_eval_run(run)


@router.get("/evals/runs/{run_id}")
async def get_eval_run(
    run_id: UUID,
    project: Project = Depends(verify_api_key),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Get a saved eval run and its case results."""
    run = (
        db.query(EvalRun)
        .filter(EvalRun.id == run_id, EvalRun.project_id == project.id)
        .first()
    )
    if not run:
        raise HTTPException(status_code=404, detail="Eval run not found")
    return _serialize_eval_run(run)


@router.post("/search/traces")
async def search_traces(
    payload: TraceSearchRequest,
    project: Project = Depends(verify_api_key),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Rank traces by matched query terms across trace and span payload text."""
    terms = list(
        dict.fromkeys(
            term.lower()
            for term in re.findall(r"[A-Za-z0-9_.:-]+", payload.query)
            if len(term) > 1
        )
    )
    if not terms:
        raise HTTPException(status_code=422, detail="Search query must contain searchable terms.")

    traces = (
        db.query(Trace)
        .filter(Trace.project_id == project.id)
        .order_by(Trace.created_at.desc())
        .limit(1000)
        .all()
    )
    results = []
    for trace in traces:
        spans = db.query(Span).filter(Span.trace_id == trace.id).all()
        text = _trace_text(trace, spans)
        counts = Counter(term for term in terms if term in text)
        if not counts:
            continue
        score = sum(text.count(term) for term in counts)
        matched_spans = []
        if payload.include_spans:
            for span in spans:
                span_text = _span_text(span)
                span_hits = [term for term in terms if term in span_text]
                if span_hits:
                    matched_spans.append(
                        {
                            "span_id": span.id,
                            "name": span.name,
                            "span_type": span.span_type,
                            "matched_terms": span_hits[:8],
                        }
                    )
        results.append(
            {
                "trace": trace.to_dict(),
                "score": score,
                "matched_terms": sorted(counts),
                "matched_spans": matched_spans[:10],
            }
        )

    results.sort(key=lambda item: (item["score"], item["trace"]["created_at"] or ""), reverse=True)
    limited_results = results[: payload.limit]
    return {
        "query": payload.query,
        "result_count": len(limited_results),
        "results": limited_results,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/guardrails/defaults")
async def default_guardrails(
    project: Project = Depends(verify_api_key),
) -> dict[str, Any]:
    """Return the built-in deterministic guardrail policy set."""
    return {"policies": [policy.model_dump() for policy in _default_guardrail_policies()]}


@router.post("/guardrails/evaluate")
async def evaluate_guardrails(
    payload: GuardrailEvaluateRequest,
    project: Project = Depends(verify_api_key),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Evaluate deterministic guardrail policies against traces."""
    policies = payload.policies or _default_guardrail_policies()
    if payload.trace_id:
        traces = [_load_trace_bundle(db, project.id, payload.trace_id)[0]]
    else:
        traces = (
            db.query(Trace)
            .filter(Trace.project_id == project.id, Trace.created_at >= _cutoff(payload.window_days))
            .order_by(Trace.created_at.desc())
            .limit(payload.limit)
            .all()
        )

    evaluated = []
    breach_count = 0
    for trace in traces:
        spans = db.query(Span).filter(Span.trace_id == trace.id).all()
        metrics = _trace_metrics(trace, spans)
        policy_results = []
        for policy in policies:
            value = metrics[policy.metric]
            passed = _compare(policy.operator, value, policy.threshold)
            if not passed:
                breach_count += 1
            policy_results.append(
                {
                    "policy_id": policy.id,
                    "name": policy.name,
                    "metric": policy.metric,
                    "operator": policy.operator,
                    "threshold": policy.threshold,
                    "current_value": value,
                    "passed": passed,
                    "severity": policy.severity,
                }
            )
        evaluated.append(
            {
                "trace_id": trace.id,
                "trace_name": trace.name,
                "status": trace.status,
                "metrics": metrics,
                "passed": all(item["passed"] for item in policy_results),
                "policies": policy_results,
            }
        )

    return {
        "trace_count": len(evaluated),
        "policy_count": len(policies),
        "breach_count": breach_count,
        "results": evaluated,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
