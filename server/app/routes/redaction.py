"""Sensitive data redaction preview and findings endpoints."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.orm import Session

from app.auth import verify_api_key
from app.database import get_db
from app.models import Project, ProjectRedactionPolicy, SensitiveSpanFinding, Span, Trace
from app.redaction import (
    RedactionFinding,
    default_redaction_policy,
    findings_to_dicts,
    scan_and_redact,
)
from app.security import audit_log
from app.validation import ID_PATTERN

router = APIRouter(prefix="/redaction", tags=["Redaction"])


class RedactionPreviewRequest(BaseModel):
    """Preview what centralized redaction would store or export."""

    model_config = ConfigDict(extra="forbid")

    trace_id: str | None = Field(default=None, min_length=1, max_length=128, pattern=ID_PATTERN)
    span_id: str | None = Field(default=None, min_length=1, max_length=128, pattern=ID_PATTERN)
    payload: Any | None = None

    @model_validator(mode="after")
    def validate_target(self) -> "RedactionPreviewRequest":
        if self.trace_id is None and self.payload is None:
            raise ValueError("Either trace_id or payload is required.")
        if self.span_id is not None and self.trace_id is None:
            raise ValueError("span_id requires trace_id.")
        return self


def _policy_for_project(db: Session, project_id: Any) -> ProjectRedactionPolicy | None:
    return (
        db.query(ProjectRedactionPolicy)
        .filter(ProjectRedactionPolicy.project_id == project_id)
        .first()
    )


def _policy_settings(policy: ProjectRedactionPolicy | None) -> tuple[bool, str, dict[str, Any]]:
    if policy is None:
        defaults = default_redaction_policy()
        return bool(defaults["enabled"]), str(defaults["mode"]), dict(defaults["rules"])
    return bool(policy.enabled), policy.mode, policy.rules or {}


def _scan_field(value: Any, *, path: str, rules: dict[str, Any], findings: list[RedactionFinding]) -> Any:
    result = scan_and_redact(value, policy_rules=rules, field_path=path)
    findings.extend(result.findings)
    return result.value


def _serialize_finding(row: SensitiveSpanFinding) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "trace_id": row.trace_id,
        "span_id": row.span_id,
        "field_path": row.field_path,
        "rule_id": row.rule_id,
        "severity": row.severity,
        "action": row.action,
        "value_fingerprint": row.value_fingerprint,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@router.post("/preview")
async def preview_redaction(
    payload: RedactionPreviewRequest,
    request: Request,
    project: Project = Depends(verify_api_key),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Preview centralized redaction for a trace or explicit JSON payload."""
    policy = _policy_for_project(db, project.id)
    enabled, mode, rules = _policy_settings(policy)
    findings: list[RedactionFinding] = []

    if not enabled:
        return {
            "enabled": False,
            "mode": mode,
            "preview": payload.payload if payload.trace_id is None else None,
            "findings": [],
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    if payload.payload is not None and payload.trace_id is None:
        result = scan_and_redact(payload.payload, policy_rules=rules, field_path="payload")
        return {
            "enabled": True,
            "mode": mode,
            "preview": result.value,
            "findings": findings_to_dicts(result.findings),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    trace = (
        db.query(Trace)
        .filter(Trace.id == payload.trace_id, Trace.project_id == project.id)
        .first()
    )
    if trace is None:
        raise HTTPException(status_code=404, detail="Trace not found")

    spans_query = db.query(Span).filter(Span.trace_id == trace.id)
    if payload.span_id:
        spans_query = spans_query.filter(Span.id == payload.span_id)
    spans = spans_query.order_by(Span.start_time.asc(), Span.created_at.asc()).limit(200).all()
    if payload.span_id and not spans:
        raise HTTPException(status_code=404, detail="Span not found")

    preview = {
        "trace_id": trace.id,
        "trace_name": trace.name,
        "metadata": _scan_field(
            trace.trace_metadata or {},
            path=f"trace.{trace.id}.metadata",
            rules=rules,
            findings=findings,
        ),
        "spans": [],
    }
    for span in spans:
        preview["spans"].append(
            {
                "span_id": span.id,
                "name": span.name,
                "attributes": _scan_field(
                    span.attributes or {},
                    path=f"span.{span.id}.attributes",
                    rules=rules,
                    findings=findings,
                ),
                "events": _scan_field(
                    span.events or [],
                    path=f"span.{span.id}.events",
                    rules=rules,
                    findings=findings,
                ),
                "input": _scan_field(
                    span.input,
                    path=f"span.{span.id}.input",
                    rules=rules,
                    findings=findings,
                ),
                "output": _scan_field(
                    span.output,
                    path=f"span.{span.id}.output",
                    rules=rules,
                    findings=findings,
                ),
                "error": _scan_field(
                    span.error,
                    path=f"span.{span.id}.error",
                    rules=rules,
                    findings=findings,
                ),
            }
        )

    audit_log(
        "redaction_preview_generated",
        request_id=getattr(request.state, "request_id", None),
        project_id=str(project.id),
        trace_id=trace.id,
        span_id=payload.span_id,
        finding_count=len(findings),
    )
    return {
        "enabled": True,
        "mode": mode,
        "preview": preview,
        "findings": findings_to_dicts(findings),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/findings")
async def list_redaction_findings(
    project: Project = Depends(verify_api_key),
    db: Session = Depends(get_db),
    trace_id: str | None = Query(default=None, min_length=1, max_length=128, pattern=ID_PATTERN),
    span_id: str | None = Query(default=None, min_length=1, max_length=128, pattern=ID_PATTERN),
    severity: str | None = Query(default=None, pattern="^(low|medium|high|critical)$"),
    rule_id: str | None = Query(default=None, min_length=1, max_length=80),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    """List sensitive-data findings for the current project."""
    query = db.query(SensitiveSpanFinding).filter(SensitiveSpanFinding.project_id == project.id)
    if trace_id:
        query = query.filter(SensitiveSpanFinding.trace_id == trace_id)
    if span_id:
        query = query.filter(SensitiveSpanFinding.span_id == span_id)
    if severity:
        query = query.filter(SensitiveSpanFinding.severity == severity)
    if rule_id:
        query = query.filter(SensitiveSpanFinding.rule_id == rule_id)

    total = query.count()
    rows = (
        query.order_by(SensitiveSpanFinding.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return {
        "findings": [_serialize_finding(row) for row in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
