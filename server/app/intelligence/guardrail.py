"""Deterministic regression guardrail signals for newly ingested traces."""

from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
from typing import Any

from app.models import Span, Trace

_SEVERITY_WEIGHT = {"critical": 35, "high": 25, "medium": 15, "low": 8}


def _safe_number(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not isfinite(number):
        return 0.0
    return number


def _pct_change(previous: float, current: float) -> float:
    if previous == 0:
        return 100.0 if current > 0 else 0.0
    return ((current - previous) / previous) * 100.0


def _risk_level(score: int) -> str:
    if score >= 70:
        return "critical"
    if score >= 45:
        return "high"
    if score >= 20:
        return "medium"
    if score > 0:
        return "low"
    return "none"


def _span_type_count(spans: list[Span], span_type: str) -> int:
    return sum(1 for span in spans if (span.span_type or "") == span_type)


def build_insufficient_baseline_guardrail() -> dict[str, Any]:
    return {
        "status": "insufficient_baseline",
        "risk_score": 0,
        "risk_level": "none",
        "baseline_trace_id": None,
        "signal_count": 0,
        "signals": [],
        "top_actions": [],
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
    }


def build_regression_guardrail(
    baseline_trace: Trace,
    baseline_spans: list[Span],
    candidate_trace: Trace,
    candidate_spans: list[Span],
) -> dict[str, Any]:
    """Build deterministic regression guardrail metadata."""
    signals: list[dict[str, Any]] = []
    actions: list[str] = []
    score = 0

    baseline_duration = _safe_number(baseline_trace.duration_ms)
    candidate_duration = _safe_number(candidate_trace.duration_ms)
    duration_pct = _pct_change(baseline_duration, candidate_duration)
    if duration_pct >= 25:
        signals.append(
            {
                "id": "latency-regression",
                "title": "Latency regression",
                "severity": "high",
                "kind": "performance",
                "detail": f"Candidate trace is {duration_pct:.1f}% slower than baseline.",
                "recommendation": "Inspect the slowest spans and remove duplicated work.",
            }
        )
        actions.append("Inspect the slowest spans and remove duplicated work.")
        score += _SEVERITY_WEIGHT["high"]

    baseline_errors = int(_safe_number(baseline_trace.error_count))
    candidate_errors = int(_safe_number(candidate_trace.error_count))
    error_delta = candidate_errors - baseline_errors
    if error_delta > 0:
        signals.append(
            {
                "id": "error-regression",
                "title": "Reliability regression",
                "severity": "critical",
                "kind": "reliability",
                "detail": f"Candidate trace has {error_delta} more error spans than baseline.",
                "recommendation": "Fix newly introduced erroring spans before other optimizations.",
            }
        )
        actions.append("Fix newly introduced erroring spans before other optimizations.")
        score += _SEVERITY_WEIGHT["critical"]

    token_pct = _pct_change(
        _safe_number(baseline_trace.total_tokens),
        _safe_number(candidate_trace.total_tokens),
    )
    if token_pct >= 30 and duration_pct > -5:
        signals.append(
            {
                "id": "token-inefficiency",
                "title": "Token inefficiency",
                "severity": "medium",
                "kind": "efficiency",
                "detail": f"Candidate trace uses {token_pct:.1f}% more tokens with limited speed gain.",
                "recommendation": "Reduce repeated context and cache reusable intermediate outputs.",
            }
        )
        actions.append("Reduce repeated context and cache reusable intermediate outputs.")
        score += _SEVERITY_WEIGHT["medium"]

    cost_pct = _pct_change(
        _safe_number(baseline_trace.total_cost),
        _safe_number(candidate_trace.total_cost),
    )
    if cost_pct >= 30:
        signals.append(
            {
                "id": "cost-regression",
                "title": "Cost regression",
                "severity": "medium",
                "kind": "cost",
                "detail": f"Candidate trace increases cost by {cost_pct:.1f}%.",
                "recommendation": "Downshift expensive model/tool calls in low-risk steps.",
            }
        )
        actions.append("Downshift expensive model/tool calls in low-risk steps.")
        score += _SEVERITY_WEIGHT["medium"]

    tool_call_pct = _pct_change(
        float(_span_type_count(baseline_spans, "tool")),
        float(_span_type_count(candidate_spans, "tool")),
    )
    if tool_call_pct >= 40 and duration_pct >= 10:
        signals.append(
            {
                "id": "tool-overhead",
                "title": "Tool overhead increase",
                "severity": "medium",
                "kind": "complexity",
                "detail": f"Candidate trace has {tool_call_pct:.1f}% more tool calls and is slower.",
                "recommendation": "Batch or parallelize tool calls where ordering is not required.",
            }
        )
        actions.append("Batch or parallelize independent tool calls.")
        score += _SEVERITY_WEIGHT["medium"]

    llm_call_pct = _pct_change(
        float(_span_type_count(baseline_spans, "llm")),
        float(_span_type_count(candidate_spans, "llm")),
    )
    if llm_call_pct >= 40 and token_pct >= 25:
        signals.append(
            {
                "id": "llm-call-expansion",
                "title": "LLM call expansion",
                "severity": "low",
                "kind": "efficiency",
                "detail": f"Candidate trace has {llm_call_pct:.1f}% more LLM calls than baseline.",
                "recommendation": "Consolidate repeated prompts and cache deterministic sub-results.",
            }
        )
        actions.append("Consolidate repeated prompts and cache deterministic sub-results.")
        score += _SEVERITY_WEIGHT["low"]

    risk_score = max(0, min(100, score))
    top_actions = list(dict.fromkeys(actions))[:3]
    if not signals:
        top_actions = ["No major regression signals detected. Keep this trace as a healthy candidate baseline."]

    return {
        "status": "risk_detected" if signals else "no_regression_signals",
        "risk_score": risk_score,
        "risk_level": _risk_level(risk_score),
        "baseline_trace_id": str(baseline_trace.id),
        "signal_count": len(signals),
        "signals": signals,
        "top_actions": top_actions,
        "metrics": {
            "duration_pct": round(duration_pct, 2),
            "error_delta": error_delta,
            "token_pct": round(token_pct, 2),
            "cost_pct": round(cost_pct, 2),
            "tool_call_pct": round(tool_call_pct, 2),
            "llm_call_pct": round(llm_call_pct, 2),
        },
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
    }
