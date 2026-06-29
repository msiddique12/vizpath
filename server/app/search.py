"""Trace search document indexing and matching helpers."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models import Span, Trace, TraceSearchDocument
from app.redaction import scan_and_redact

_TERM_PATTERN = re.compile(r"[A-Za-z0-9_.:-]+")


def tokenize_search_query(query: str | None) -> list[str]:
    """Tokenize a user query into bounded lowercase terms."""
    if not query:
        return []
    return list(
        dict.fromkeys(
            term.lower()
            for term in _TERM_PATTERN.findall(query)
            if len(term) > 1
        )
    )[:40]


def _safe_text(value: Any, limit: int = 2000) -> str:
    if value is None:
        return ""
    try:
        if isinstance(value, (dict, list, tuple)):
            text = json.dumps(value, sort_keys=True, default=str)
        else:
            text = str(value)
    except (TypeError, ValueError):
        text = str(value)
    return text[:limit]


def _redacted_text(value: Any, *, policy_rules: dict[str, Any] | None = None, limit: int = 2000) -> str:
    redacted = scan_and_redact(value, policy_rules=policy_rules, field_path="search").value
    return _safe_text(redacted, limit)


def _string_facet(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text[:120] if text else None


def _unique(values: list[str | None]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def build_trace_search_document(
    trace: Trace,
    spans: list[Span],
    *,
    policy_rules: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    """Build redacted searchable text and facets for a trace."""
    metadata = trace.trace_metadata or {}
    models: list[str | None] = [_string_facet(metadata.get("model"))]
    tools: list[str | None] = []
    span_statuses: list[str | None] = []
    span_types: list[str | None] = []
    span_duration_total = 0.0
    parts = [
        trace.name,
        trace.status,
        _redacted_text(metadata, policy_rules=policy_rules),
    ]

    for span in spans:
        attrs = span.attributes or {}
        try:
            span_duration_total += float(span.duration_ms or 0.0)
        except (TypeError, ValueError):
            pass
        if span.span_type == "llm":
            models.append(_string_facet(attrs.get("model") or attrs.get("model_name")))
        if span.span_type == "tool":
            tools.append(_string_facet(attrs.get("tool") or span.name))
        span_statuses.append(_string_facet(span.status))
        span_types.append(_string_facet(span.span_type))
        parts.extend(
            [
                span.name,
                span.span_type,
                span.status,
                _redacted_text(attrs, policy_rules=policy_rules),
                _redacted_text(span.input, policy_rules=policy_rules),
                _redacted_text(span.output, policy_rules=policy_rules),
                _redacted_text(span.error, policy_rules=policy_rules),
            ]
        )

    metadata_facets = {
        "model": _string_facet(metadata.get("model")),
        "models": _unique(models),
        "run_id": _string_facet(metadata.get("run_id")),
        "prompt_version": _string_facet(metadata.get("prompt_version")),
        "owner": _string_facet(metadata.get("owner")),
        "route": _string_facet(metadata.get("route")),
        "task": _string_facet(metadata.get("task")),
    }
    span_facets = {
        "models": _unique(models),
        "tools": _unique(tools),
        "span_statuses": _unique(span_statuses),
        "span_types": _unique(span_types),
        "duration_ms": round(span_duration_total, 3),
    }
    document_text = " ".join(part for part in parts if part).lower()[:100000]
    return document_text, metadata_facets, span_facets


def upsert_trace_search_document(
    db: Session,
    trace: Trace,
    spans: list[Span],
    *,
    policy_rules: dict[str, Any] | None = None,
) -> TraceSearchDocument:
    """Create or update a trace search document."""
    document_text, metadata_facets, span_facets = build_trace_search_document(
        trace,
        spans,
        policy_rules=policy_rules,
    )
    row = (
        db.query(TraceSearchDocument)
        .filter(
            TraceSearchDocument.project_id == trace.project_id,
            TraceSearchDocument.trace_id == trace.id,
        )
        .first()
    )
    now = datetime.now(timezone.utc)
    if row is None:
        row = TraceSearchDocument(
            project_id=trace.project_id,
            trace_id=trace.id,
            document_text=document_text,
            metadata_facets=metadata_facets,
            span_facets=span_facets,
            created_at=now,
            updated_at=now,
        )
        db.add(row)
        return row
    row.document_text = document_text
    row.metadata_facets = metadata_facets
    row.span_facets = span_facets
    row.updated_at = now
    return row


def match_search_terms(document_text: str, terms: list[str]) -> tuple[int, list[str]]:
    """Return search score and matched terms for a document."""
    if not terms:
        return 0, []
    matched = [term for term in terms if term in document_text]
    score = sum(document_text.count(term) for term in matched)
    return score, matched


def span_matches(span: Span, terms: list[str], *, policy_rules: dict[str, Any] | None = None) -> list[str]:
    """Return matched terms for a single span using redacted text."""
    span_text = " ".join(
        [
            span.name,
            span.span_type,
            span.status,
            _redacted_text(span.attributes or {}, policy_rules=policy_rules),
            _redacted_text(span.input, policy_rules=policy_rules),
            _redacted_text(span.output, policy_rules=policy_rules),
            _redacted_text(span.error, policy_rules=policy_rules),
        ]
    ).lower()
    return [term for term in terms if term in span_text]
