"""Intelligence API endpoints for Nemotron-powered trace analysis."""

import json
import logging
import re
import statistics
import time
from datetime import datetime, timezone
from math import isfinite
from threading import Lock
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.orm import Session

from app.auth import verify_api_key
from app.config import settings
from app.database import get_db
from app.intelligence.budget import (
    IntelligenceBudgetStatus,
    consume_intelligence_budget_call,
    get_intelligence_budget_status,
)
from app.models import Project, Span, Trace
from app.validation import ID_PATTERN

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/intelligence", tags=["Intelligence"])

_SEVERITY_WEIGHT = {"low": 10, "medium": 20, "high": 35, "critical": 50}
_RISK_SUMMARY = {
    "low": {
        "threshold": 25,
        "label": "low",
    },
    "medium": {
        "threshold": 55,
        "label": "medium",
    },
    "high": {
        "threshold": 75,
        "label": "high",
    },
    "critical": {
        "threshold": 100,
        "label": "critical",
    },
}
_SENSITIVE_RULES = [
    {
        "id": "pii-email",
        "category": "pii",
        "severity": "low",
        "title": "Potential email address",
        "description": "Email-like text was found in trace metadata or span payload.",
        "pattern": re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", re.IGNORECASE),
    },
    {
        "id": "pii-ssn",
        "category": "pii",
        "severity": "high",
        "title": "Potential social security number",
        "description": "SSN-like numbers were detected; this is highly sensitive.",
        "pattern": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    },
    {
        "id": "pii-phone",
        "category": "pii",
        "severity": "low",
        "title": "Potential phone number",
        "description": "Phone-number-like text was found.",
        "pattern": re.compile(r"\b\+?1?[ -.]?\(?\d{3}\)?[ -.]?\d{3}[ -.]?\d{4}\b"),
    },
    {
        "id": "secret-openai-key",
        "category": "secrets",
        "severity": "critical",
        "title": "Possible OpenAI API key",
        "description": "A token with OpenAI key structure was found.",
        "pattern": re.compile(r"sk-[A-Za-z0-9]{20,}"),
    },
    {
        "id": "secret-openai-alt-key",
        "category": "secrets",
        "severity": "critical",
        "title": "Possible OpenAI API key",
        "description": "A token with OpenAI key structure was found.",
        "pattern": re.compile(r"sk_live_[A-Za-z0-9]{20,}"),
    },
    {
        "id": "secret-aws-key",
        "category": "secrets",
        "severity": "critical",
        "title": "Possible AWS key",
        "description": "An AWS-style access key pattern was detected.",
        "pattern": re.compile(r"AKIA[0-9A-Z]{16}"),
    },
    {
        "id": "secret-github-token",
        "category": "secrets",
        "severity": "high",
        "title": "Possible GitHub token",
        "description": "A GitHub token pattern was detected.",
        "pattern": re.compile(r"ghp_[A-Za-z0-9]{36}"),
    },
    {
        "id": "secret-bearer",
        "category": "secrets",
        "severity": "critical",
        "title": "Bearer authorization token",
        "description": "Bearer authorization token format was detected.",
        "pattern": re.compile(r"\bbearer\s+[A-Za-z0-9._-]{12,}", re.IGNORECASE),
    },
    {
        "id": "secret-private-key",
        "category": "secrets",
        "severity": "critical",
        "title": "Private key header",
        "description": "Private key block detected in trace payload.",
        "pattern": re.compile(r"-----BEGIN (?:RSA )?PRIVATE KEY-----"),
    },
    {
        "id": "policy-instruction-hijack",
        "category": "policy",
        "severity": "medium",
        "title": "Potential instruction override",
        "description": "Language that attempts to override system instructions was found.",
        "pattern": re.compile(
            r"(?i)\b(ignore|disregard|override)\s+(all|previous)\s+(instructions|prompts|system)\b"
        ),
    },
    {
        "id": "policy-destructive-action",
        "category": "policy",
        "severity": "high",
        "title": "Potential destructive action",
        "description": "Potentially destructive shell-style command text was found.",
        "pattern": re.compile(r"(?i)\b(rm\s+-rf|drop\s+table|delete\s+from|format\s+\S+|shutdown\s+now)\b"),
    },
]
_FAILURE_MODES = ("infra", "llm", "tool", "policy", "data")
_FAILURE_SIGNAL_RULES = [
    {
        "mode": "infra",
        "weight": 24,
        "pattern": re.compile(
            r"(?i)\b(timeout|timed out|connection refused|dns|econnreset|socket|network|503|429|service unavailable|rate limit)\b"
        ),
        "label": "Network or service instability",
        "recommendation": "Add retries with backoff and verify upstream service health.",
    },
    {
        "mode": "llm",
        "weight": 22,
        "pattern": re.compile(
            r"(?i)\b(context length|max tokens|token limit|invalid json|output parser|refusal|unable to comply|hallucinat)\b"
        ),
        "label": "LLM output or prompt failure",
        "recommendation": "Harden prompts/output parsing and reduce oversized context windows.",
    },
    {
        "mode": "tool",
        "weight": 20,
        "pattern": re.compile(
            r"(?i)\b(command failed|exit code|tool not found|permission denied|subprocess|no such file|invalid tool)\b"
        ),
        "label": "Tool execution failure",
        "recommendation": "Validate tool inputs, permissions, and fallback behavior.",
    },
    {
        "mode": "data",
        "weight": 20,
        "pattern": re.compile(
            r"(?i)\b(schema|validation|malformed|missing field|parse error|jsondecodeerror|keyerror|indexerror|empty dataset)\b"
        ),
        "label": "Data quality or schema mismatch",
        "recommendation": "Add strict schema validation and sanitize upstream data before use.",
    },
    {
        "mode": "policy",
        "weight": 24,
        "pattern": re.compile(
            r"(?i)\b(prompt injection|jailbreak|unsafe|forbidden|policy violation|exposed secret|pii)\b"
        ),
        "label": "Policy or safety violation",
        "recommendation": "Block unsafe instructions and enforce policy filters before tool calls.",
    },
]
_FAILURE_MODE_BASE_RECOMMENDATIONS = {
    "infra": "Monitor infra dependencies and add circuit-breaker style fallbacks.",
    "llm": "Version prompts and add deterministic response validation.",
    "tool": "Constrain tool execution paths and validate arguments before invocation.",
    "policy": "Apply pre-execution safety checks and redact sensitive outputs.",
    "data": "Validate payload schemas and reject malformed records early.",
}
_INTELLIGENCE_SUMMARY_CACHE_TTL_SECONDS = 120
_intelligence_summary_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_intelligence_summary_cache_lock = Lock()


def _clear_intelligence_summary_cache() -> None:
    """Clear in-process intelligence summary cache (used by tests)."""
    with _intelligence_summary_cache_lock:
        _intelligence_summary_cache.clear()


def _collect_text_blocks(trace_data: dict[str, Any]) -> list[tuple[str, str, str]]:
    """Build a deterministic list of searchable trace text fields."""
    blocks: list[tuple[str, str, str]] = []

    def _add_block(scope: str, field: str, value: Any) -> None:
        if value is None:
            return
        if isinstance(value, str):
            text = value
        else:
            text = str(value)
        text = text.strip()
        if text:
            blocks.append((scope, field, text))

    _add_block("trace", "name", trace_data.get("name"))
    _add_block("trace", "status", trace_data.get("status"))
    _add_block("trace", "metadata", trace_data.get("metadata"))
    _add_block("trace", "trace_error", trace_data.get("error"))

    for span in trace_data.get("spans", []):
        if not isinstance(span, dict):
            continue
        scope = f"span:{span.get('id') or span.get('trace_id') or 'unknown'}"
        _add_block(scope, "name", span.get("name"))
        _add_block(scope, "type", span.get("span_type"))
        _add_block(scope, "status", span.get("status"))
        _add_block(scope, "error", span.get("error"))
        _add_block(scope, "input", span.get("input"))
        _add_block(scope, "output", span.get("output"))
        _add_block(scope, "attributes", span.get("attributes"))
        _add_block(scope, "events", span.get("events"))

    return blocks


def _redact_match(value: str) -> str:
    """Redact matched text for safe output."""
    value = value.strip()
    if len(value) <= 4:
        return "*" * len(value)
    if len(value) <= 12:
        return value[:1] + "*" * (len(value) - 1)
    return f"{value[:4]}...{value[-4:]}"


def _build_risk_level(score: int) -> str:
    if score >= _RISK_SUMMARY["critical"]["threshold"]:
        return "critical"
    if score >= _RISK_SUMMARY["high"]["threshold"]:
        return "high"
    if score >= _RISK_SUMMARY["medium"]["threshold"]:
        return "medium"
    return _RISK_SUMMARY["low"]["label"]


def _scan_trace_for_risk(trace_data: dict[str, Any]) -> dict[str, Any]:
    """Run deterministic local safety/privacy risk checks on trace content."""
    findings: list[dict[str, Any]] = []
    seen_keys = set[str]()
    for scope, field, text in _collect_text_blocks(trace_data):
        for rule in _SENSITIVE_RULES:
            match_count = 0
            for match in rule["pattern"].finditer(text):
                match_count += 1
                if match_count > 2:
                    break
                matched_text = match.group(0)
                sample_key = f"{scope}:{field}:{rule['id']}:{matched_text[:8]}"
                if sample_key in seen_keys:
                    continue
                seen_keys.add(sample_key)
                findings.append(
                    {
                        "rule_id": rule["id"],
                        "category": rule["category"],
                        "severity": rule["severity"],
                        "title": rule["title"],
                        "detail": rule["description"],
                        "location": f"{scope}.{field}",
                        "sample": _redact_match(matched_text),
                    }
                )

    findings.sort(
        key=lambda item: (_SEVERITY_WEIGHT.get(item["severity"], 0), item["rule_id"]),
        reverse=True,
    )

    score = 0
    for finding in findings:
        score += _SEVERITY_WEIGHT.get(finding["severity"], 0)
    score = min(100, score)
    risk_level = _build_risk_level(score)

    category_counts: dict[str, int] = {}
    for finding in findings:
        category_counts[finding["category"]] = category_counts.get(finding["category"], 0) + 1

    recommendations = []
    if category_counts.get("secrets", 0) > 0:
        recommendations.append("Rotate exposed secrets immediately and reissue new keys.")
    if category_counts.get("pii", 0) > 0:
        recommendations.append("Reduce collection of PII and apply tokenization/masking.")
    if category_counts.get("policy", 0) > 0:
        recommendations.append("Validate user-controlled instructions before tool execution.")
    if not recommendations:
        recommendations.append("Keep tracing sanitized; no immediate security risks detected.")

    summary = (
        "Potentially sensitive or policy-risk content detected."
        if findings
        else "No high-confidence sensitive or policy-risk content detected."
    )

    return {
        "risk_score": score,
        "risk_level": risk_level,
        "findings": findings[:12],
        "category_counts": category_counts,
        "recommendations": recommendations[:3],
        "summary": summary,
    }


def _failure_severity(score: int) -> str:
    if score >= 50:
        return "high"
    if score >= 25:
        return "medium"
    if score > 0:
        return "low"
    return "none"


def _classify_failure_modes(trace_data: dict[str, Any]) -> dict[str, Any]:
    """Classify likely failure domains from trace/span signals."""
    buckets: dict[str, dict[str, Any]] = {
        mode: {"score": 0, "evidence": [], "recommendations": set()}
        for mode in _FAILURE_MODES
    }

    def _add_signal(
        mode: str,
        *,
        weight: int,
        label: str,
        location: str,
        recommendation: str | None = None,
    ) -> None:
        bucket = buckets[mode]
        bucket["score"] += max(weight, 0)
        if len(bucket["evidence"]) < 8:
            bucket["evidence"].append(
                {
                    "label": label,
                    "location": location,
                    "weight": weight,
                }
            )
        if recommendation:
            bucket["recommendations"].add(recommendation)

    spans = trace_data.get("spans", [])
    llm_calls = 0
    tool_calls = 0
    error_span_count = 0
    for span in spans:
        if not isinstance(span, dict):
            continue
        span_type = str(span.get("span_type", "custom")).lower()
        span_status = str(span.get("status", "unknown")).lower()
        location = f"span:{span.get('id') or span.get('trace_id') or 'unknown'}"

        if span_type == "llm":
            llm_calls += 1
        elif span_type == "tool":
            tool_calls += 1

        if span_status == "error":
            error_span_count += 1
            mode_from_span = "infra"
            if span_type == "llm":
                mode_from_span = "llm"
            elif span_type == "tool":
                mode_from_span = "tool"
            elif span_type == "retrieval":
                mode_from_span = "data"

            _add_signal(
                mode_from_span,
                weight=12,
                label="Span ended with error status",
                location=location,
                recommendation=_FAILURE_MODE_BASE_RECOMMENDATIONS[mode_from_span],
            )

        error_text = str(span.get("error") or "")
        combined_text = " ".join(
            [
                error_text,
                str(span.get("input") or ""),
                str(span.get("output") or ""),
                str(span.get("attributes") or ""),
                str(span.get("events") or ""),
            ]
        )
        if not combined_text.strip():
            continue

        for rule in _FAILURE_SIGNAL_RULES:
            if rule["pattern"].search(combined_text):
                _add_signal(
                    rule["mode"],
                    weight=int(rule["weight"]),
                    label=str(rule["label"]),
                    location=location,
                    recommendation=str(rule["recommendation"]),
                )

    if llm_calls >= 8:
        _add_signal(
            "llm",
            weight=8,
            label="High LLM call volume may indicate prompt churn",
            location="trace",
            recommendation="Cache repeated context and consolidate prompt calls.",
        )
    if tool_calls >= 10:
        _add_signal(
            "tool",
            weight=8,
            label="High tool-call fanout may increase operational fragility",
            location="trace",
            recommendation="Batch or parallelize tools where dependency ordering is not required.",
        )

    trace_status = str(trace_data.get("status") or "").lower()
    if trace_status == "error" and error_span_count == 0:
        _add_signal(
            "infra",
            weight=10,
            label="Trace failed without explicit failing spans",
            location="trace.status",
            recommendation=_FAILURE_MODE_BASE_RECOMMENDATIONS["infra"],
        )

    safety = _scan_trace_for_risk(trace_data)
    policy_count = int(safety.get("category_counts", {}).get("policy", 0))
    pii_count = int(safety.get("category_counts", {}).get("pii", 0))
    secret_count = int(safety.get("category_counts", {}).get("secrets", 0))
    if policy_count > 0 or pii_count > 0 or secret_count > 0:
        policy_weight = min(40, policy_count * 12 + pii_count * 8 + secret_count * 12)
        _add_signal(
            "policy",
            weight=policy_weight,
            label="Safety scan detected policy/PII/secret risk indicators",
            location="trace.safety-scan",
            recommendation="Use guardrails and redact sensitive data before persistence.",
        )
        for recommendation in safety.get("recommendations", []):
            buckets["policy"]["recommendations"].add(str(recommendation))

    mode_results = []
    for mode, bucket in buckets.items():
        score = min(100, int(bucket["score"]))
        if score <= 0:
            continue
        mode_results.append(
            {
                "mode": mode,
                "score": score,
                "severity": _failure_severity(score),
                "evidence_count": len(bucket["evidence"]),
                "evidence": bucket["evidence"],
                "recommendations": list(bucket["recommendations"])[:3],
            }
        )

    mode_results.sort(key=lambda item: (item["score"], item["mode"]), reverse=True)
    if not mode_results:
        return {
            "status": "no_major_failure_signals",
            "primary_mode": "none",
            "confidence": 0.0,
            "modes": [],
            "summary": "No high-confidence failure signals detected in this trace.",
        }

    total_score = sum(mode["score"] for mode in mode_results)
    primary = mode_results[0]
    confidence = 0.0
    if total_score > 0:
        confidence = round(primary["score"] / total_score, 4)

    return {
        "status": "issue_detected",
        "primary_mode": primary["mode"],
        "confidence": confidence,
        "modes": mode_results,
        "summary": f"Primary failure mode is '{primary['mode']}' with {primary['severity']} severity signals.",
    }


def _trace_metric_vector(trace: Trace, spans: list[Span]) -> dict[str, float]:
    """Build a deterministic numeric metric vector for a trace."""
    llm_calls = float(sum(1 for span in spans if span.span_type == "llm"))
    tool_calls = float(sum(1 for span in spans if span.span_type == "tool"))
    span_count = float(len(spans))
    sum_duration = _safe_number(sum(_safe_number(s.duration_ms) for s in spans))
    sum_tokens = _safe_number(sum(_safe_number(s.tokens) for s in spans))
    sum_cost = _safe_number(sum(_safe_number(s.cost) for s in spans))
    error_count = float(
        sum(1 for span in spans if (span.status or "").lower() == "error")
    )

    return {
        "duration_ms": _safe_number(trace.duration_ms) or sum_duration,
        "error_count": (
            float(trace.error_count)
            if isinstance(trace.error_count, int)
            else error_count
        ),
        "total_tokens": (
            _safe_number(trace.total_tokens)
            if trace.total_tokens is not None
            else sum_tokens
        ),
        "total_cost": (
            _safe_number(trace.total_cost) if trace.total_cost is not None else sum_cost
        ),
        "span_count": (
            _safe_number(trace.span_count)
            if trace.span_count not in (None, 0)
            else span_count
        ),
        "llm_calls": llm_calls,
        "tool_calls": tool_calls,
    }


def _analyze_anomaly(
    trace: Trace,
    spans: list[Span],
    historical_traces: list[Trace],
    historical_spans: list[list[Span]],
    z_threshold: float,
) -> dict[str, Any]:
    """Compute outlier score versus recent historical traces."""
    current = _trace_metric_vector(trace, spans)
    history_metrics = [
        _trace_metric_vector(t, s)
        for t, s in zip(historical_traces, historical_spans, strict=False)
    ]

    if len(history_metrics) < 3:
        return {
            "anomaly_score": 0,
            "status": "insufficient_history",
            "anomaly_count": 0,
            "outlier_metrics": [],
            "summary": "Insufficient historical traces for anomaly detection.",
            "recommendations": ["Collect at least 3 historical traces before auto-detecting anomalies."],
        }

    findings: list[dict[str, Any]] = []
    for metric, current_value in current.items():
        values = [history[metric] for history in history_metrics]
        mean_value = statistics.mean(values)
        stdev_value = statistics.pstdev(values) if len(values) >= 2 else 0.0
        if stdev_value == 0:
            continue

        z_score = (current_value - mean_value) / stdev_value
        abs_z = abs(z_score)
        severity = "low"
        direction = "normal"
        if abs_z >= 3.0:
            severity = "high"
        elif abs_z >= 2.0:
            severity = "medium"
        elif abs_z >= 1.3:
            severity = "low"
        else:
            continue

        if z_score > 0:
            direction = "higher_than_baseline"
        elif z_score < 0:
            direction = "lower_than_baseline"

        details = {
            "metric": metric,
            "current": current_value,
            "baseline_mean": mean_value,
            "baseline_std": stdev_value,
            "z_score": round(z_score, 4),
            "abs_z_score": round(abs_z, 4),
            "direction": direction,
            "severity": severity,
        }
        findings.append(details)

    findings.sort(
        key=lambda item: (item["abs_z_score"], item["metric"]),
        reverse=True,
    )

    anomaly_score = 0
    for finding in findings:
        if finding["severity"] == "high":
            anomaly_score += 35
        elif finding["severity"] == "medium":
            anomaly_score += 18
        else:
            anomaly_score += 8
    anomaly_score = min(100, anomaly_score)

    status = "normal"
    if anomaly_score >= 35:
        status = "outlier"
    elif anomaly_score >= 25:
        status = "degraded"
    elif anomaly_score > 0:
        status = "watch"

    recommendations = []
    for item in findings:
        if item["metric"] in {"duration_ms", "span_count"}:
            recommendations.append("Inspect slower spans and cut redundant chain steps.")
        elif item["metric"] in {"total_cost", "total_tokens"}:
            recommendations.append("Profile prompt/context and reduce token-heavy operations.")
        elif item["metric"] in {"error_count", "tool_calls", "llm_calls"}:
            recommendations.append("Review recent retries/fallbacks and tool strategy before rollout.")
    if not recommendations:
        recommendations.append("No strong behavioral anomalies detected.")

    findings = [finding for finding in findings if finding["abs_z_score"] >= z_threshold]

    return {
        "anomaly_score": anomaly_score,
        "status": status,
        "anomaly_count": len(findings),
        "outlier_metrics": findings,
        "summary": "Statistical anomaly signal computed against recent trace history.",
        "recommendations": list(dict.fromkeys(recommendations))[:3],
    }


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


def _enforce_intelligence_call_budget(project: Project) -> IntelligenceBudgetStatus:
    """Consume project intelligence call budget and fail fast when exhausted."""
    budget_status = consume_intelligence_budget_call(str(project.id))
    headers = _intelligence_budget_headers(budget_status)
    if budget_status.allowed:
        return budget_status

    if budget_status.retry_after_seconds is not None:
        headers["Retry-After"] = str(budget_status.retry_after_seconds)

    raise HTTPException(
        status_code=429,
        detail={
            "code": "intelligence_daily_budget_exceeded",
            "message": "Daily intelligence call budget exhausted for this project.",
            "limit": budget_status.limit,
            "used": budget_status.used,
            "remaining": budget_status.remaining,
            "resets_at": budget_status.resets_at,
            "retry_after_seconds": budget_status.retry_after_seconds,
        },
        headers=headers,
    )


def _intelligence_budget_headers(budget_status: IntelligenceBudgetStatus) -> dict[str, str]:
    headers = {
        "X-Intelligence-Budget-Enforced": str(bool(budget_status.enforced)).lower(),
        "X-Intelligence-Budget-Used": str(int(budget_status.used)),
        "X-Intelligence-Budget-Resets-At": str(budget_status.resets_at),
    }
    if budget_status.limit is not None:
        headers["X-Intelligence-Budget-Limit"] = str(int(budget_status.limit))
    if budget_status.remaining is not None:
        headers["X-Intelligence-Budget-Remaining"] = str(int(budget_status.remaining))
    return headers


def _set_intelligence_budget_headers(response: Response, budget_status: IntelligenceBudgetStatus) -> None:
    for key, value in _intelligence_budget_headers(budget_status).items():
        response.headers[key] = value


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


def _trace_to_data(trace: Trace, spans: list[Span]) -> dict[str, Any]:
    """Convert trace + spans models into the dict format used by intelligence helpers."""
    data = trace.to_dict()
    data["spans"] = [span.to_dict() for span in spans]
    return data


def _summary_cache_key(
    project_id: Any,
    trace_id: str,
    baseline_trace_id: str | None,
    history_limit: int,
) -> str:
    baseline = baseline_trace_id or "-"
    return f"{project_id}:{trace_id}:{baseline}:{history_limit}"


def _copilot_cache_key(
    project_id: Any,
    trace_id: str,
    baseline_trace_id: str | None,
    history_limit: int,
) -> str:
    """Cache key namespace for trace copilot responses."""
    return f"copilot:{_summary_cache_key(project_id, trace_id, baseline_trace_id, history_limit)}"


def _get_cached_intelligence_summary(cache_key: str) -> dict[str, Any] | None:
    now_ts = time.time()
    with _intelligence_summary_cache_lock:
        cached = _intelligence_summary_cache.get(cache_key)
        if not cached:
            return None
        expires_at, payload = cached
        if expires_at <= now_ts:
            _intelligence_summary_cache.pop(cache_key, None)
            return None
        return json.loads(json.dumps(payload))


def _set_cached_intelligence_summary(cache_key: str, payload: dict[str, Any]) -> None:
    cache_payload = json.loads(json.dumps(payload))
    expires_at = time.time() + _INTELLIGENCE_SUMMARY_CACHE_TTL_SECONDS
    with _intelligence_summary_cache_lock:
        _intelligence_summary_cache[cache_key] = (expires_at, cache_payload)


def _extract_span_ids_from_failure_result(failure_result: dict[str, Any]) -> list[str]:
    """Extract referenced span IDs from failure evidence locations."""
    span_ids: list[str] = []
    for mode in failure_result.get("modes", []):
        for evidence in mode.get("evidence", []):
            location = str(evidence.get("location", ""))
            if not location.startswith("span:"):
                continue
            span_id = location.split(":", 1)[1].strip()
            if span_id:
                span_ids.append(span_id)
    return span_ids


def _build_copilot_span_references(
    spans: list[Span],
    failure_result: dict[str, Any],
    anomaly_result: dict[str, Any],
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Rank and serialize the most relevant spans for diagnostics."""
    if not spans:
        return []

    by_id: dict[str, Span] = {str(span.id): span for span in spans}
    ranked: list[dict[str, Any]] = []
    seen_ids = set[str]()

    def _append(span: Span, reason: str) -> None:
        span_id = str(span.id)
        if span_id in seen_ids:
            return
        seen_ids.add(span_id)
        ranked.append(
            {
                "span_id": span_id,
                "span_name": span.name,
                "span_type": span.span_type or "custom",
                "status": span.status or "unknown",
                "duration_ms": _safe_number(span.duration_ms),
                "tokens": int(span.tokens or 0),
                "reason": reason,
            }
        )

    for span_id in _extract_span_ids_from_failure_result(failure_result):
        span = by_id.get(span_id)
        if span is not None:
            _append(span, "Referenced by failure-mode evidence")
            if len(ranked) >= limit:
                return ranked

    error_spans = sorted(
        [span for span in spans if str(span.status).lower() == "error"],
        key=lambda item: (_safe_number(item.duration_ms), int(item.tokens or 0)),
        reverse=True,
    )
    for span in error_spans:
        _append(span, "Span ended with error status")
        if len(ranked) >= limit:
            return ranked

    outlier_metrics = {
        str(item.get("metric"))
        for item in anomaly_result.get("outlier_metrics", [])
        if isinstance(item, dict)
    }
    if "duration_ms" in outlier_metrics:
        longest = max(spans, key=lambda item: _safe_number(item.duration_ms))
        _append(longest, "Longest span in anomalous duration trace")
    if "total_tokens" in outlier_metrics:
        heaviest = max(spans, key=lambda item: int(item.tokens or 0))
        _append(heaviest, "Highest-token span in anomalous token trace")

    for span in sorted(
        spans,
        key=lambda item: (_safe_number(item.duration_ms), int(item.tokens or 0)),
        reverse=True,
    ):
        _append(span, "High execution cost span")
        if len(ranked) >= limit:
            break

    return ranked[:limit]


def _build_copilot_root_cause(
    explanation: dict[str, Any] | None,
    failure_result: dict[str, Any],
    anomaly_result: dict[str, Any],
    safety_result: dict[str, Any],
) -> dict[str, Any]:
    """Select a primary root-cause hypothesis from deterministic signals."""
    hypotheses = (explanation or {}).get("hypotheses") or []
    if hypotheses:
        top = hypotheses[0]
        detail = str(top.get("recommendation") or "")
        if not detail:
            evidence = top.get("evidence") or []
            detail = str(evidence[0]) if evidence else ""
        return {
            "title": str(top.get("title") or "Likely regression cause identified"),
            "detail": detail or "Top regression hypothesis selected from deterministic signals.",
            "source": "regression_explain",
            "confidence": round(float(top.get("confidence", 0.0)), 4),
        }

    if failure_result.get("status") == "issue_detected":
        primary_mode = str(failure_result.get("primary_mode") or "unknown")
        recommendation = ""
        modes = failure_result.get("modes") or []
        if modes:
            recommendations = modes[0].get("recommendations") or []
            if recommendations:
                recommendation = str(recommendations[0])
        return {
            "title": f"Failure signals point to {primary_mode} instability",
            "detail": recommendation or "Deterministic failure mode classifier detected issue signals.",
            "source": "failure_modes",
            "confidence": round(float(failure_result.get("confidence", 0.0)), 4),
        }

    anomaly_status = str(anomaly_result.get("status") or "normal")
    if anomaly_status in {"outlier", "degraded", "watch"}:
        anomaly_score = int(anomaly_result.get("anomaly_score", 0))
        confidence = max(0.1, min(0.9, anomaly_score / 100))
        return {
            "title": "Behavior drift from recent baseline",
            "detail": str(anomaly_result.get("summary") or "Trace behaves differently than recent runs."),
            "source": "anomaly_detect",
            "confidence": round(confidence, 4),
        }

    safety_score = int(safety_result.get("risk_score", 0))
    if safety_score >= 40:
        return {
            "title": "Safety/policy exposure in trace payloads",
            "detail": str(safety_result.get("summary") or ""),
            "source": "safety_scan",
            "confidence": round(min(0.95, max(0.2, safety_score / 100)), 4),
        }

    return {
        "title": "No strong root-cause signal detected",
        "detail": "This trace looks stable relative to current deterministic checks.",
        "source": "summary",
        "confidence": 0.0,
    }


def _build_copilot_fixes(
    root_cause: dict[str, Any],
    failure_result: dict[str, Any],
    anomaly_result: dict[str, Any],
    safety_result: dict[str, Any],
    explanation: dict[str, Any] | None,
    span_references: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Generate an ordered short list of actionable fixes."""
    fixes: list[dict[str, Any]] = []
    seen_titles = set[str]()
    linked_span_ids = [item["span_id"] for item in span_references[:3] if "span_id" in item]

    def _add_fix(
        title: str,
        rationale: str,
        priority: str,
        expected_gain: str,
    ) -> None:
        normalized_title = title.strip()
        if not normalized_title or normalized_title in seen_titles:
            return
        seen_titles.add(normalized_title)
        fixes.append(
            {
                "id": f"fix-{len(fixes) + 1}",
                "title": normalized_title,
                "priority": priority,
                "rationale": rationale.strip() or "Deterministic diagnostics recommended this action.",
                "expected_gain": expected_gain,
                "linked_span_ids": linked_span_ids,
            }
        )

    if root_cause.get("detail"):
        _add_fix(
            title="Address primary root-cause recommendation",
            rationale=str(root_cause["detail"]),
            priority="high",
            expected_gain="Reduce recurrence of the top failure signal.",
        )

    if failure_result.get("status") == "issue_detected":
        for mode in failure_result.get("modes", [])[:2]:
            recommendations = mode.get("recommendations") or []
            if not recommendations:
                continue
            _add_fix(
                title=f"Mitigate {mode.get('mode', 'system')} failure mode",
                rationale=str(recommendations[0]),
                priority="high" if str(mode.get("severity")) == "high" else "medium",
                expected_gain="Improve trace reliability and reduce failed spans.",
            )

    anomaly_recommendations = anomaly_result.get("recommendations") or []
    if anomaly_recommendations:
        _add_fix(
            title="Stabilize anomalous execution path",
            rationale=str(anomaly_recommendations[0]),
            priority="medium",
            expected_gain="Bring latency/cost behavior closer to historical baseline.",
        )

    safety_recommendations = safety_result.get("recommendations") or []
    if int(safety_result.get("risk_score", 0)) >= 40 and safety_recommendations:
        _add_fix(
            title="Harden safety and secret handling",
            rationale=str(safety_recommendations[0]),
            priority="high",
            expected_gain="Lower policy risk and prevent sensitive data exposure.",
        )

    if explanation and explanation.get("hypotheses"):
        for hypothesis in explanation["hypotheses"][:2]:
            recommendation = str(hypothesis.get("recommendation") or "").strip()
            if not recommendation:
                continue
            _add_fix(
                title=f"Follow hypothesis: {hypothesis.get('title', 'root-cause fix')}",
                rationale=recommendation,
                priority="medium",
                expected_gain="Validate and close likely regression path quickly.",
            )

    if not fixes:
        _add_fix(
            title="Continue monitoring this trace pattern",
            rationale="No high-confidence failure vectors were detected by deterministic checks.",
            priority="low",
            expected_gain="Maintain baseline quality while collecting more data.",
        )

    return fixes[:3]


def _build_trace_copilot(
    trace: Trace,
    spans: list[Span],
    project_id: Any,
    db: Session,
    *,
    baseline_trace_id: str | None,
    history_limit: int,
) -> dict[str, Any]:
    """Build deterministic trace copilot brief used in trace detail UX."""
    trace_data = _trace_to_data(trace, spans)
    failure_result = _classify_failure_modes(trace_data)
    safety_result = _scan_trace_for_risk(trace_data)

    historical_query = db.query(Trace).filter(Trace.id != trace.id, Trace.project_id == project_id)
    if baseline_trace_id:
        historical_query = historical_query.filter(Trace.id != baseline_trace_id)
    historical_traces = (
        historical_query.order_by(Trace.created_at.desc()).limit(history_limit).all()
    )
    historical_spans = [
        db.query(Span).filter(Span.trace_id == historical_trace.id).all()
        for historical_trace in historical_traces
    ]
    anomaly_result = _analyze_anomaly(
        trace,
        spans,
        historical_traces,
        historical_spans,
        z_threshold=1.5,
    )

    compare_summary: dict[str, Any] | None = None
    explanation: dict[str, Any] | None = None
    if baseline_trace_id:
        baseline_trace = (
            db.query(Trace)
            .filter(Trace.id == baseline_trace_id, Trace.project_id == project_id)
            .first()
        )
        if not baseline_trace:
            raise HTTPException(status_code=404, detail="Trace not found")
        baseline_spans = db.query(Span).filter(Span.trace_id == baseline_trace_id).all()
        compare_result = _compare_trace_metrics(baseline_trace, baseline_spans, trace, spans)
        compare_summary = compare_result.get("summary", {})
        explanation = _explain_regression(
            compare_result,
            failure_result,
            anomaly_result,
            safety_result,
        )

    failure_top_score = 0
    if failure_result.get("status") == "issue_detected":
        top_mode = (failure_result.get("modes") or [{}])[0]
        failure_top_score = int(top_mode.get("score", 0))

    compare_regression_score = int((compare_summary or {}).get("regression_score", 0))
    anomaly_score = int(anomaly_result.get("anomaly_score", 0))
    safety_score = int(safety_result.get("risk_score", 0))
    if compare_summary:
        triage_score = min(
            100,
            int(
                compare_regression_score * 0.45
                + anomaly_score * 0.3
                + safety_score * 0.15
                + failure_top_score * 0.1
            ),
        )
    else:
        triage_score = min(
            100,
            int(failure_top_score * 0.5 + anomaly_score * 0.35 + safety_score * 0.15),
        )

    if triage_score >= 70:
        triage_status = "high_risk"
    elif triage_score >= 40:
        triage_status = "review"
    else:
        triage_status = "stable"

    root_cause = _build_copilot_root_cause(
        explanation,
        failure_result,
        anomaly_result,
        safety_result,
    )
    span_references = _build_copilot_span_references(
        spans,
        failure_result,
        anomaly_result,
    )
    next_fixes = _build_copilot_fixes(
        root_cause,
        failure_result,
        anomaly_result,
        safety_result,
        explanation,
        span_references,
    )

    confidence = round(float(root_cause.get("confidence", 0.0)), 4)
    summary = f"{root_cause['title']} ({int(confidence * 100)}% confidence)."

    return {
        "trace_id": str(trace.id),
        "baseline_trace_id": baseline_trace_id,
        "triage_score": triage_score,
        "triage_status": triage_status,
        "confidence": confidence,
        "summary": summary,
        "root_cause": root_cause,
        "next_fixes": next_fixes,
        "span_references": span_references,
        "candidate_failure": {
            "status": failure_result.get("status"),
            "primary_mode": failure_result.get("primary_mode"),
            "confidence": failure_result.get("confidence", 0.0),
        },
        "candidate_anomaly": {
            "status": anomaly_result.get("status"),
            "anomaly_score": anomaly_result.get("anomaly_score"),
            "anomaly_count": anomaly_result.get("anomaly_count"),
        },
        "candidate_safety": {
            "risk_level": safety_result.get("risk_level"),
            "risk_score": safety_result.get("risk_score"),
        },
        "compare_summary": compare_summary,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def _build_intelligence_summary(
    trace: Trace,
    spans: list[Span],
    project_id: Any,
    db: Session,
    baseline_trace_id: str | None,
    history_limit: int,
) -> dict[str, Any]:
    """Build deterministic triage summary combining safety, failure, anomaly, and regression context."""
    trace_data = _trace_to_data(trace, spans)
    failure_result = _classify_failure_modes(trace_data)
    safety_result = _scan_trace_for_risk(trace_data)

    historical_query = (
        db.query(Trace)
        .filter(
            Trace.id != trace.id,
            Trace.project_id == project_id,
        )
    )
    if baseline_trace_id:
        historical_query = historical_query.filter(Trace.id != baseline_trace_id)
    historical_traces = (
        historical_query
        .order_by(Trace.created_at.desc())
        .limit(history_limit)
        .all()
    )
    historical_spans = [
        db.query(Span).filter(Span.trace_id == historical_trace.id).all()
        for historical_trace in historical_traces
    ]
    anomaly_result = _analyze_anomaly(
        trace,
        spans,
        historical_traces,
        historical_spans,
        z_threshold=1.5,
    )

    compare_summary: dict[str, Any] | None = None
    explanation: dict[str, Any] | None = None
    if baseline_trace_id:
        baseline_trace = (
            db.query(Trace)
            .filter(Trace.id == baseline_trace_id, Trace.project_id == project_id)
            .first()
        )
        if not baseline_trace:
            raise HTTPException(status_code=404, detail="Trace not found")
        baseline_spans = db.query(Span).filter(Span.trace_id == baseline_trace_id).all()
        compare_result = _compare_trace_metrics(baseline_trace, baseline_spans, trace, spans)
        compare_summary = compare_result.get("summary", {})
        explanation = _explain_regression(
            compare_result,
            failure_result,
            anomaly_result,
            safety_result,
        )

    failure_top_score = 0
    if failure_result.get("status") == "issue_detected":
        top_mode = (failure_result.get("modes") or [{}])[0]
        failure_top_score = int(top_mode.get("score", 0))

    compare_regression_score = int((compare_summary or {}).get("regression_score", 0))
    anomaly_score = int(anomaly_result.get("anomaly_score", 0))
    safety_score = int(safety_result.get("risk_score", 0))
    if compare_summary:
        triage_score = min(
            100,
            int(compare_regression_score * 0.45 + anomaly_score * 0.3 + safety_score * 0.15 + failure_top_score * 0.1),
        )
    else:
        triage_score = min(
            100,
            int(failure_top_score * 0.5 + anomaly_score * 0.35 + safety_score * 0.15),
        )

    if triage_score >= 70:
        triage_status = "high_risk"
    elif triage_score >= 40:
        triage_status = "review"
    else:
        triage_status = "stable"

    return {
        "trace_id": str(trace.id),
        "baseline_trace_id": baseline_trace_id,
        "triage_score": triage_score,
        "triage_status": triage_status,
        "candidate_failure": {
            "status": failure_result.get("status"),
            "primary_mode": failure_result.get("primary_mode"),
            "confidence": failure_result.get("confidence", 0.0),
        },
        "candidate_anomaly": {
            "status": anomaly_result.get("status"),
            "anomaly_score": anomaly_result.get("anomaly_score"),
            "anomaly_count": anomaly_result.get("anomaly_count"),
        },
        "candidate_safety": {
            "risk_level": safety_result.get("risk_level"),
            "risk_score": safety_result.get("risk_score"),
        },
        "compare_summary": compare_summary,
        "explanation": explanation,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def _explain_regression(
    compare_result: dict[str, Any],
    failure_result: dict[str, Any],
    anomaly_result: dict[str, Any],
    safety_result: dict[str, Any],
) -> dict[str, Any]:
    """Merge deterministic intelligence signals into ranked regression hypotheses."""
    hypotheses: list[dict[str, Any]] = []

    signal_to_hypothesis = {
        "error-regression": {
            "id": "reliability_regression",
            "title": "New reliability failures in candidate trace",
            "confidence": 0.88,
            "severity": "high",
        },
        "latency-regression": {
            "id": "latency_path_expansion",
            "title": "Execution path became slower",
            "confidence": 0.76,
            "severity": "high",
        },
        "token-inefficiency": {
            "id": "prompt_bloat",
            "title": "Prompt or context expansion increased compute cost",
            "confidence": 0.72,
            "severity": "medium",
        },
        "cost-regression": {
            "id": "model_or_tool_cost_spike",
            "title": "Model/tool mix shifted to higher-cost path",
            "confidence": 0.69,
            "severity": "medium",
        },
        "tool-overhead": {
            "id": "tool_orchestration_overhead",
            "title": "Extra tool calls introduced orchestration overhead",
            "confidence": 0.7,
            "severity": "medium",
        },
    }

    for signal in compare_result.get("signals", []):
        hypothesis_base = signal_to_hypothesis.get(signal.get("id"))
        if not hypothesis_base:
            continue
        hypotheses.append(
            {
                "id": hypothesis_base["id"],
                "title": hypothesis_base["title"],
                "confidence": hypothesis_base["confidence"],
                "severity": hypothesis_base["severity"],
                "evidence": [signal.get("detail", "")],
                "recommendation": signal.get("recommendation", ""),
            }
        )

    if failure_result.get("status") == "issue_detected":
        primary_mode = str(failure_result.get("primary_mode", "none"))
        mode_recommendation = ""
        if failure_result.get("modes"):
            mode_recommendation = failure_result["modes"][0].get("recommendations", [""])[0]
        hypotheses.append(
            {
                "id": f"{primary_mode}_failure_domain",
                "title": f"Candidate trace shows {primary_mode} domain failure signals",
                "confidence": min(0.92, 0.55 + float(failure_result.get("confidence", 0.0))),
                "severity": "high" if primary_mode in {"infra", "policy", "tool"} else "medium",
                "evidence": [
                    f"Primary mode: {primary_mode}",
                    f"Classifier confidence: {failure_result.get('confidence', 0.0)}",
                ],
                "recommendation": mode_recommendation,
            }
        )

    if int(safety_result.get("risk_score", 0)) >= 55:
        hypotheses.append(
            {
                "id": "policy_safety_exposure",
                "title": "Candidate trace introduces policy/safety risk indicators",
                "confidence": 0.67,
                "severity": "high",
                "evidence": [safety_result.get("summary", "")],
                "recommendation": "Apply masking/guardrails before writing span data and running tools.",
            }
        )

    if anomaly_result.get("status") in {"outlier", "degraded"}:
        hypotheses.append(
            {
                "id": "behavioral_outlier",
                "title": "Candidate trace behavior is statistically anomalous",
                "confidence": 0.62 if anomaly_result.get("status") == "degraded" else 0.75,
                "severity": "medium",
                "evidence": [
                    f"Anomaly status: {anomaly_result.get('status')}",
                    f"Anomaly score: {anomaly_result.get('anomaly_score')}",
                ],
                "recommendation": "Review the top outlier metrics and compare changed spans first.",
            }
        )

    deduped: dict[str, dict[str, Any]] = {}
    for hypothesis in hypotheses:
        hypothesis_id = str(hypothesis.get("id"))
        if hypothesis_id not in deduped or float(hypothesis["confidence"]) > float(deduped[hypothesis_id]["confidence"]):
            deduped[hypothesis_id] = hypothesis

    ranked = sorted(
        deduped.values(),
        key=lambda item: (float(item.get("confidence", 0)), item.get("id", "")),
        reverse=True,
    )

    if not ranked:
        return {
            "status": "no_clear_regression_cause",
            "hypothesis_count": 0,
            "top_hypothesis_confidence": 0.0,
            "hypotheses": [],
            "summary": "Regression detected no clear deterministic root-cause signals.",
        }

    return {
        "status": "regression_explained" if compare_result.get("summary", {}).get("regression_score", 0) > 0 else "changes_explained",
        "hypothesis_count": len(ranked),
        "top_hypothesis_confidence": ranked[0]["confidence"],
        "hypotheses": ranked[:5],
        "summary": f"Generated {len(ranked)} ranked root-cause hypotheses from deterministic signals.",
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


class SafetyScanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trace_id: str = Field(min_length=1, max_length=128, pattern=ID_PATTERN)


class TraceAnomalyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trace_id: str = Field(min_length=1, max_length=128, pattern=ID_PATTERN)
    history_limit: int = Field(default=20, ge=3, le=100)
    z_threshold: float = Field(default=1.3, ge=0.5, le=8.0)


class FailureModesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trace_id: str = Field(min_length=1, max_length=128, pattern=ID_PATTERN)


class RegressionExplainRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trace_a_id: str = Field(min_length=1, max_length=128, pattern=ID_PATTERN)
    trace_b_id: str = Field(min_length=1, max_length=128, pattern=ID_PATTERN)
    history_limit: int = Field(default=20, ge=3, le=100)


class IntelligenceSummaryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trace_id: str = Field(min_length=1, max_length=128, pattern=ID_PATTERN)
    baseline_trace_id: str | None = Field(default=None, min_length=1, max_length=128, pattern=ID_PATTERN)
    history_limit: int = Field(default=20, ge=3, le=100)
    refresh_cache: bool = False


class TraceCopilotRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trace_id: str = Field(min_length=1, max_length=128, pattern=ID_PATTERN)
    baseline_trace_id: str | None = Field(default=None, min_length=1, max_length=128, pattern=ID_PATTERN)
    history_limit: int = Field(default=20, ge=3, le=100)
    refresh_cache: bool = False


# --- Endpoints ---


@router.post("/analyze")
async def analyze_trace(
    req: AnalyzeRequest,
    response: Response,
    project: Project = Depends(verify_api_key),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Analyze a trace for quality and efficiency."""
    _require_nvidia_key()
    trace_data = _get_trace_data(req.trace_id, project.id, db)
    budget_status = _enforce_intelligence_call_budget(project)
    _set_intelligence_budget_headers(response, budget_status)

    from app.intelligence.llm import LLMLabeler

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


@router.post("/safety-scan")
async def safety_scan(
    req: SafetyScanRequest,
    project: Project = Depends(verify_api_key),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Run deterministic local safety/privacy scan on trace text fields."""
    trace_data = _get_trace_data(req.trace_id, project.id, db)
    result = _scan_trace_for_risk(trace_data)
    result["trace_id"] = req.trace_id
    return result


@router.post("/anomaly-detect")
async def anomaly_detect(
    req: TraceAnomalyRequest,
    project: Project = Depends(verify_api_key),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Detect statistical anomalies by comparing trace against recent project history."""
    trace = (
        db.query(Trace)
        .filter(Trace.id == req.trace_id, Trace.project_id == project.id)
        .first()
    )
    if not trace:
        raise HTTPException(status_code=404, detail="Trace not found")

    current_spans = db.query(Span).filter(Span.trace_id == req.trace_id).all()

    historical_traces = (
        db.query(Trace)
        .filter(Trace.id != req.trace_id, Trace.project_id == project.id)
        .order_by(Trace.created_at.desc())
        .limit(req.history_limit)
        .all()
    )
    historical_spans = [
        db.query(Span).filter(Span.trace_id == historical_trace.id).all()
        for historical_trace in historical_traces
    ]

    result = _analyze_anomaly(
        trace,
        current_spans,
        historical_traces,
        historical_spans,
        req.z_threshold,
    )
    result["trace_id"] = req.trace_id
    return result


@router.post("/failure-modes")
async def failure_modes(
    req: FailureModesRequest,
    project: Project = Depends(verify_api_key),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Classify likely root failure domains using deterministic heuristics."""
    trace_data = _get_trace_data(req.trace_id, project.id, db)
    result = _classify_failure_modes(trace_data)
    result["trace_id"] = req.trace_id
    return result


@router.post("/regression-explain")
async def regression_explain(
    req: RegressionExplainRequest,
    project: Project = Depends(verify_api_key),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Explain likely root causes behind regressions between two traces."""
    trace_a = db.query(Trace).filter(Trace.id == req.trace_a_id, Trace.project_id == project.id).first()
    trace_b = db.query(Trace).filter(Trace.id == req.trace_b_id, Trace.project_id == project.id).first()
    if not trace_a or not trace_b:
        raise HTTPException(status_code=404, detail="Trace not found")

    spans_a = db.query(Span).filter(Span.trace_id == req.trace_a_id).all()
    spans_b = db.query(Span).filter(Span.trace_id == req.trace_b_id).all()
    compare_result = _compare_trace_metrics(trace_a, spans_a, trace_b, spans_b)

    trace_b_data = _trace_to_data(trace_b, spans_b)
    failure_result = _classify_failure_modes(trace_b_data)
    safety_result = _scan_trace_for_risk(trace_b_data)

    historical_traces = (
        db.query(Trace)
        .filter(
            Trace.id != req.trace_b_id,
            Trace.id != req.trace_a_id,
            Trace.project_id == project.id,
        )
        .order_by(Trace.created_at.desc())
        .limit(req.history_limit)
        .all()
    )
    historical_spans = [
        db.query(Span).filter(Span.trace_id == historical_trace.id).all()
        for historical_trace in historical_traces
    ]
    anomaly_result = _analyze_anomaly(
        trace_b,
        spans_b,
        historical_traces,
        historical_spans,
        z_threshold=1.5,
    )
    explanation = _explain_regression(
        compare_result,
        failure_result,
        anomaly_result,
        safety_result,
    )

    return {
        "trace_a_id": req.trace_a_id,
        "trace_b_id": req.trace_b_id,
        "compare_summary": compare_result.get("summary", {}),
        "candidate_failure": {
            "status": failure_result.get("status"),
            "primary_mode": failure_result.get("primary_mode"),
            "confidence": failure_result.get("confidence"),
        },
        "candidate_anomaly": {
            "status": anomaly_result.get("status"),
            "anomaly_score": anomaly_result.get("anomaly_score"),
            "anomaly_count": anomaly_result.get("anomaly_count"),
        },
        "candidate_safety": {
            "risk_level": safety_result.get("risk_level"),
            "risk_score": safety_result.get("risk_score"),
        },
        "explanation": explanation,
    }


@router.post("/summary")
async def intelligence_summary(
    req: IntelligenceSummaryRequest,
    project: Project = Depends(verify_api_key),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Return cached deterministic intelligence summary for triage workflows."""
    trace = (
        db.query(Trace)
        .filter(Trace.id == req.trace_id, Trace.project_id == project.id)
        .first()
    )
    if not trace:
        raise HTTPException(status_code=404, detail="Trace not found")

    spans = db.query(Span).filter(Span.trace_id == req.trace_id).all()
    cache_key = _summary_cache_key(
        project.id,
        req.trace_id,
        req.baseline_trace_id,
        req.history_limit,
    )
    if not req.refresh_cache:
        cached = _get_cached_intelligence_summary(cache_key)
        if cached is not None:
            cached["cached"] = True
            return cached

    result = _build_intelligence_summary(
        trace,
        spans,
        project.id,
        db,
        req.baseline_trace_id,
        req.history_limit,
    )
    result["cache_ttl_seconds"] = _INTELLIGENCE_SUMMARY_CACHE_TTL_SECONDS
    _set_cached_intelligence_summary(cache_key, result)
    result["cached"] = False
    return result


@router.post("/copilot")
async def trace_copilot(
    req: TraceCopilotRequest,
    project: Project = Depends(verify_api_key),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Return deterministic copilot brief for trace detail workflows."""
    trace = (
        db.query(Trace)
        .filter(Trace.id == req.trace_id, Trace.project_id == project.id)
        .first()
    )
    if not trace:
        raise HTTPException(status_code=404, detail="Trace not found")

    spans = db.query(Span).filter(Span.trace_id == req.trace_id).all()
    cache_key = _copilot_cache_key(
        project.id,
        req.trace_id,
        req.baseline_trace_id,
        req.history_limit,
    )
    if not req.refresh_cache:
        cached = _get_cached_intelligence_summary(cache_key)
        if cached is not None:
            cached["cached"] = True
            return cached

    result = _build_trace_copilot(
        trace,
        spans,
        project.id,
        db,
        baseline_trace_id=req.baseline_trace_id,
        history_limit=req.history_limit,
    )
    result["cache_ttl_seconds"] = _INTELLIGENCE_SUMMARY_CACHE_TTL_SECONDS
    _set_cached_intelligence_summary(cache_key, result)
    result["cached"] = False
    return result


@router.get("/status")
async def intelligence_status(
    _project: Project = Depends(verify_api_key),
) -> dict[str, Any]:
    """Return intelligence setup status for dashboard/demo checks."""
    budget_status = get_intelligence_budget_status(str(_project.id))
    return {
        "nvidia_api_key_configured": bool(settings.nvidia_api_key),
        "model": settings.nvidia_llm_model,
        "base_url": settings.nvidia_base_url,
        "llm_timeout_seconds": settings.nvidia_llm_timeout_seconds,
        "llm_max_tokens": settings.nvidia_llm_max_tokens,
        "daily_call_budget": {
            "enforced": budget_status.enforced,
            "limit": budget_status.limit,
            "used": budget_status.used,
            "remaining": budget_status.remaining,
            "allowed": budget_status.allowed,
            "resets_at": budget_status.resets_at,
            "retry_after_seconds": budget_status.retry_after_seconds,
        },
    }


@router.post("/self-analyze")
async def self_analyze_trace(
    req: SelfAnalyzeRequest,
    response: Response,
    project: Project = Depends(verify_api_key),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Deep evaluation of agent decision-making quality."""
    _require_nvidia_key()
    trace_data = _get_trace_data(req.trace_id, project.id, db)
    budget_status = _enforce_intelligence_call_budget(project)
    _set_intelligence_budget_headers(response, budget_status)

    from app.intelligence.llm import LLMLabeler

    labeler = LLMLabeler()
    result = await labeler.self_analyze(trace_data)
    return _normalize_self_analyze_result(result, req.trace_id)


@router.post("/suggest-curation")
async def suggest_curation(
    req: SuggestCurationRequest,
    response: Response,
    project: Project = Depends(verify_api_key),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Generate a curation suggestion (label/score/notes) from AI trace analysis."""
    _require_nvidia_key()
    trace_data = _get_trace_data(req.trace_id, project.id, db)
    budget_status = _enforce_intelligence_call_budget(project)
    _set_intelligence_budget_headers(response, budget_status)

    from app.intelligence.llm import LLMLabeler

    labeler = LLMLabeler()
    result = await labeler.analyze_trace(trace_data)
    normalized = _normalize_analyze_result(result, req.trace_id)
    return _suggest_curation_from_analysis(normalized, req.trace_id)


@router.post("/embed")
async def embed_trace_endpoint(
    req: EmbedRequest,
    response: Response,
    project: Project = Depends(verify_api_key),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Generate an embedding for a trace."""
    _require_nvidia_key()
    trace_data = _get_trace_data(req.trace_id, project.id, db)
    budget_status = _enforce_intelligence_call_budget(project)
    _set_intelligence_budget_headers(response, budget_status)

    from app.intelligence.embeddings import embed_trace, trace_to_text

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
    response: Response,
    project: Project = Depends(verify_api_key),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Generate synthetic training data from a trace."""
    _require_nvidia_key()
    trace_data = _get_trace_data(req.trace_id, project.id, db)
    budget_status = _enforce_intelligence_call_budget(project)
    _set_intelligence_budget_headers(response, budget_status)

    from app.intelligence.synthetic import SyntheticDataGenerator

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
    response: Response,
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

    budget_status = _enforce_intelligence_call_budget(project)
    _set_intelligence_budget_headers(response, budget_status)

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
