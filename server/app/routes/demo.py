"""Demo helper endpoints for one-click story mode setup."""

from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

import redis
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.auth import verify_api_key
from app.config import settings
from app.database import check_db_connection, get_db
from app.models import Project, Span, Trace
from app.routes.ws import notify_span_ingested

router = APIRouter(prefix="/demo", tags=["Demo"])


class StoryModeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario: str = Field(default="agent_regression", pattern="^(agent_regression)$")


class DemoCheckStatus(str, Enum):
    OK = "ok"
    WARNING = "warning"
    ERROR = "error"


class DemoPreflightCheck(BaseModel):
    component: str
    status: DemoCheckStatus
    required: bool
    message: str


class DemoPreflightResponse(BaseModel):
    ready: bool
    can_seed: bool
    checks: list[DemoPreflightCheck]
    blockers: list[str]
    recommendations: list[str]


def _build_trace_payloads(now: datetime) -> list[dict[str, Any]]:
    """Build deterministic trace payloads for live demo storytelling."""
    base_id = now.strftime("%Y%m%d%H%M%S")
    seed_suffix = uuid4().hex[:8]
    trace_a_id = f"demo-{base_id}-baseline"
    trace_b_id = f"demo-{base_id}-regression"
    trace_c_id = f"demo-{base_id}-recovery"
    trace_a_id = f"{trace_a_id}-{seed_suffix}"
    trace_b_id = f"{trace_b_id}-{seed_suffix}"
    trace_c_id = f"{trace_c_id}-{seed_suffix}"

    start_a = now - timedelta(minutes=4)
    start_b = now - timedelta(minutes=3)
    start_c = now - timedelta(minutes=2)

    return [
        {
            "trace_id": trace_a_id,
            "name": "Story Mode: Baseline (efficient)",
            "start_time": start_a,
            "status": "success",
            "metadata": {"story_mode": True, "scenario": "agent_regression", "variant": "baseline"},
            "spans": [
                {
                    "id": f"{trace_a_id}-agent",
                    "name": "agent.plan",
                    "span_type": "agent",
                    "status": "success",
                    "start_time": start_a,
                    "duration_ms": 1600.0,
                    "tokens": 420,
                    "cost": 0.015,
                },
                {
                    "id": f"{trace_a_id}-retrieve",
                    "parent_id": f"{trace_a_id}-agent",
                    "name": "retrieval.docs",
                    "span_type": "retrieval",
                    "status": "success",
                    "start_time": start_a + timedelta(milliseconds=350),
                    "duration_ms": 500.0,
                },
                {
                    "id": f"{trace_a_id}-tool",
                    "parent_id": f"{trace_a_id}-agent",
                    "name": "tool.search",
                    "span_type": "tool",
                    "status": "success",
                    "start_time": start_a + timedelta(milliseconds=980),
                    "duration_ms": 450.0,
                },
                {
                    "id": f"{trace_a_id}-llm",
                    "parent_id": f"{trace_a_id}-agent",
                    "name": "llm.answer",
                    "span_type": "llm",
                    "status": "success",
                    "start_time": start_a + timedelta(milliseconds=1410),
                    "duration_ms": 840.0,
                    "tokens": 680,
                    "cost": 0.03,
                },
            ],
        },
        {
            "trace_id": trace_b_id,
            "name": "Story Mode: Candidate (regressed)",
            "start_time": start_b,
            "status": "error",
            "metadata": {"story_mode": True, "scenario": "agent_regression", "variant": "regressed"},
            "spans": [
                {
                    "id": f"{trace_b_id}-agent",
                    "name": "agent.plan",
                    "span_type": "agent",
                    "status": "error",
                    "start_time": start_b,
                    "duration_ms": 2600.0,
                    "tokens": 760,
                    "cost": 0.028,
                    "error": "Tool timeout caused retry loop",
                },
                {
                    "id": f"{trace_b_id}-retrieve",
                    "parent_id": f"{trace_b_id}-agent",
                    "name": "retrieval.docs",
                    "span_type": "retrieval",
                    "status": "success",
                    "start_time": start_b + timedelta(milliseconds=500),
                    "duration_ms": 700.0,
                },
                {
                    "id": f"{trace_b_id}-tool-1",
                    "parent_id": f"{trace_b_id}-agent",
                    "name": "tool.search",
                    "span_type": "tool",
                    "status": "success",
                    "start_time": start_b + timedelta(milliseconds=1100),
                    "duration_ms": 640.0,
                },
                {
                    "id": f"{trace_b_id}-tool-2",
                    "parent_id": f"{trace_b_id}-agent",
                    "name": "tool.search",
                    "span_type": "tool",
                    "status": "success",
                    "start_time": start_b + timedelta(milliseconds=1800),
                    "duration_ms": 620.0,
                },
                {
                    "id": f"{trace_b_id}-llm",
                    "parent_id": f"{trace_b_id}-agent",
                    "name": "llm.answer",
                    "span_type": "llm",
                    "status": "success",
                    "start_time": start_b + timedelta(milliseconds=2420),
                    "duration_ms": 1380.0,
                    "tokens": 1140,
                    "cost": 0.061,
                },
            ],
        },
        {
            "trace_id": trace_c_id,
            "name": "Story Mode: Recovery (optimized)",
            "start_time": start_c,
            "status": "success",
            "metadata": {"story_mode": True, "scenario": "agent_regression", "variant": "recovery"},
            "spans": [
                {
                    "id": f"{trace_c_id}-agent",
                    "name": "agent.plan",
                    "span_type": "agent",
                    "status": "success",
                    "start_time": start_c,
                    "duration_ms": 1200.0,
                    "tokens": 340,
                    "cost": 0.012,
                },
                {
                    "id": f"{trace_c_id}-retrieve",
                    "parent_id": f"{trace_c_id}-agent",
                    "name": "retrieval.docs",
                    "span_type": "retrieval",
                    "status": "success",
                    "start_time": start_c + timedelta(milliseconds=300),
                    "duration_ms": 360.0,
                },
                {
                    "id": f"{trace_c_id}-tool",
                    "parent_id": f"{trace_c_id}-agent",
                    "name": "tool.search",
                    "span_type": "tool",
                    "status": "success",
                    "start_time": start_c + timedelta(milliseconds=650),
                    "duration_ms": 260.0,
                },
                {
                    "id": f"{trace_c_id}-llm",
                    "parent_id": f"{trace_c_id}-agent",
                    "name": "llm.answer",
                    "span_type": "llm",
                    "status": "success",
                    "start_time": start_c + timedelta(milliseconds=920),
                    "duration_ms": 640.0,
                    "tokens": 520,
                    "cost": 0.024,
                },
            ],
        },
    ]


def _persist_trace(db: Session, project_id: Any, trace_payload: dict[str, Any]) -> Trace:
    spans_payload = trace_payload["spans"]
    end_times = [
        span["start_time"] + timedelta(milliseconds=span["duration_ms"]) for span in spans_payload
    ]
    total_tokens = sum(span.get("tokens", 0) for span in spans_payload) or None
    total_cost = sum(span.get("cost", 0.0) for span in spans_payload) or None
    error_count = sum(1 for span in spans_payload if span["status"] == "error")

    trace = Trace(
        id=trace_payload["trace_id"],
        project_id=project_id,
        name=trace_payload["name"],
        status=trace_payload["status"],
        start_time=trace_payload["start_time"],
        end_time=max(end_times),
        duration_ms=(max(end_times) - trace_payload["start_time"]).total_seconds() * 1000,
        trace_metadata=trace_payload["metadata"],
        total_tokens=total_tokens,
        total_cost=total_cost,
        error_count=error_count,
        span_count=len(spans_payload),
    )
    db.add(trace)

    for span_payload in spans_payload:
        span = Span(
            id=span_payload["id"],
            trace_id=trace_payload["trace_id"],
            parent_id=span_payload.get("parent_id"),
            name=span_payload["name"],
            span_type=span_payload["span_type"],
            status=span_payload["status"],
            start_time=span_payload["start_time"],
            end_time=span_payload["start_time"] + timedelta(milliseconds=span_payload["duration_ms"]),
            duration_ms=span_payload["duration_ms"],
            attributes={"story_mode": True},
            events=[],
            input=None,
            output=None,
            error=span_payload.get("error"),
            tokens=span_payload.get("tokens"),
            cost=span_payload.get("cost"),
        )
        db.add(span)

    return trace


@router.post("/story-mode")
async def seed_story_mode(
    req: StoryModeRequest,
    project: Project = Depends(verify_api_key),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Seed deterministic traces and return guided URLs for demo flow."""
    now = datetime.now(timezone.utc)
    trace_payloads = _build_trace_payloads(now)
    traces: list[Trace] = []

    for payload in trace_payloads:
        traces.append(_persist_trace(db, project.id, payload))

    db.commit()

    for trace in traces:
        await notify_span_ingested(str(trace.id), trace.span_count)

    baseline_id = trace_payloads[0]["trace_id"]
    candidate_id = trace_payloads[1]["trace_id"]
    recovery_id = trace_payloads[2]["trace_id"]

    return {
        "scenario": req.scenario,
        "seeded": len(traces),
        "trace_ids": [str(trace.id) for trace in traces],
        "recommended_flow": {
            "compare": f"/compare?traceA={baseline_id}&traceB={candidate_id}",
            "trace_baseline": f"/traces/{baseline_id}",
            "trace_candidate": f"/traces/{candidate_id}",
            "trace_recovery": f"/traces/{recovery_id}",
            "curation": "/curation",
        },
    }


def _build_demo_preflight() -> DemoPreflightResponse:
    checks: list[DemoPreflightCheck] = []
    blockers: list[str] = []
    recommendations: list[str] = []

    db_ready = bool(check_db_connection())
    checks.append(
        DemoPreflightCheck(
            component="database",
            status=DemoCheckStatus.OK if db_ready else DemoCheckStatus.ERROR,
            required=True,
            message="Database reachable" if db_ready else "Database not reachable",
        )
    )
    if not db_ready:
        blockers.append("Start PostgreSQL and ensure DATABASE_URL is valid.")

    redis_ready = False
    try:
        redis_client = redis.from_url(settings.redis_url)
        redis_ready = bool(redis_client.ping())
    except Exception:
        redis_ready = False
    checks.append(
        DemoPreflightCheck(
            component="redis",
            status=DemoCheckStatus.OK if redis_ready else DemoCheckStatus.WARNING,
            required=False,
            message="Redis reachable" if redis_ready else "Redis not reachable (optional for demo)",
        )
    )
    if not redis_ready:
        recommendations.append("Start Redis if you want live websocket streaming during the demo.")

    intelligence_ready = bool(settings.nvidia_api_key)
    checks.append(
        DemoPreflightCheck(
            component="intelligence",
            status=DemoCheckStatus.OK
            if intelligence_ready
            else DemoCheckStatus.WARNING,
            required=False,
            message=(
                "NVIDIA API key configured"
                if intelligence_ready
                else "NVIDIA_API_KEY not configured (AI features disabled)"
            ),
        )
    )
    if not intelligence_ready:
        recommendations.append("Set NVIDIA_API_KEY to unlock analysis and synthetic generation features.")

    ready = all(check.status != DemoCheckStatus.ERROR for check in checks if check.required)
    can_seed = db_ready

    return DemoPreflightResponse(
        ready=ready,
        can_seed=can_seed,
        checks=checks,
        blockers=blockers,
        recommendations=recommendations,
    )


@router.get("/preflight", response_model=DemoPreflightResponse)
async def preflight_demo() -> DemoPreflightResponse:
    """Check demo-critical service readiness."""
    return _build_demo_preflight()
