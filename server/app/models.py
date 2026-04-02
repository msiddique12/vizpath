"""SQLAlchemy ORM models for vizpath."""

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import relationship

from app.database import Base


class SpanType:
    LLM = "llm"
    TOOL = "tool"
    AGENT = "agent"
    RETRIEVAL = "retrieval"
    CHAIN = "chain"
    CUSTOM = "custom"


class SpanStatus:
    RUNNING = "running"
    SUCCESS = "success"
    ERROR = "error"


class Project(Base):
    """Project groups traces for a user."""

    __tablename__ = "projects"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    api_key_hash = Column(String(64), unique=True, index=True, nullable=False)
    previous_api_key_hash = Column(String(64), unique=True, index=True, nullable=True)
    api_key_grace_expires_at = Column(DateTime(timezone=True), nullable=True)
    api_key_revoked_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), onupdate=lambda: datetime.now(timezone.utc))

    traces = relationship("Trace", back_populates="project", cascade="all, delete-orphan")
    api_keys = relationship(
        "ProjectApiKey",
        back_populates="project",
        cascade="all, delete-orphan",
    )
    budget = relationship(
        "ProjectBudget",
        back_populates="project",
        uselist=False,
        cascade="all, delete-orphan",
    )
    alert_rules = relationship(
        "ProjectAlertRule",
        back_populates="project",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Project(id={self.id}, name='{self.name}')>"


class Trace(Base):
    """Top-level execution unit containing spans."""

    __tablename__ = "traces"

    id = Column(String(64), primary_key=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    status = Column(String(20), default=SpanStatus.RUNNING, index=True)
    start_time = Column(DateTime(timezone=True), nullable=False)
    end_time = Column(DateTime(timezone=True), nullable=True)
    duration_ms = Column(Float, nullable=True)
    trace_metadata = Column(JSON, default=dict)
    total_tokens = Column(Integer, nullable=True)
    total_cost = Column(Float, nullable=True)
    error_count = Column(Integer, default=0)
    span_count = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    project = relationship("Project", back_populates="traces")
    spans = relationship("Span", back_populates="trace", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_traces_project_created", "project_id", "created_at"),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "project_id": str(self.project_id),
            "name": self.name,
            "status": self.status,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration_ms": self.duration_ms,
            "metadata": self.trace_metadata,
            "total_tokens": self.total_tokens,
            "total_cost": self.total_cost,
            "error_count": self.error_count,
            "span_count": self.span_count,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self) -> str:
        return f"<Trace(id={self.id}, name='{self.name}')>"


class Span(Base):
    """Individual operation within a trace."""

    __tablename__ = "spans"

    id = Column(String(64), primary_key=True)
    trace_id = Column(String(64), ForeignKey("traces.id"), nullable=False, index=True)
    # Note: No ForeignKey constraint - spans may arrive out of order across batches
    parent_id = Column(String(64), nullable=True, index=True)
    name = Column(String(255), nullable=False)
    span_type = Column(String(50), default=SpanType.CUSTOM, index=True)
    status = Column(String(20), default=SpanStatus.RUNNING)
    start_time = Column(DateTime(timezone=True), nullable=False)
    end_time = Column(DateTime(timezone=True), nullable=True)
    duration_ms = Column(Float, nullable=True)
    attributes = Column(JSON, default=dict)
    events = Column(JSON, default=list)
    input = Column(JSON, nullable=True)
    output = Column(JSON, nullable=True)
    error = Column(Text, nullable=True)
    tokens = Column(Integer, nullable=True)
    cost = Column(Float, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    trace = relationship("Trace", back_populates="spans")
    # Note: parent/children relationships handled via parent_id column (no FK constraint)

    __table_args__ = (
        Index("ix_spans_trace_parent", "trace_id", "parent_id"),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "trace_id": str(self.trace_id),
            "parent_id": str(self.parent_id) if self.parent_id else None,
            "name": self.name,
            "span_type": self.span_type,
            "status": self.status,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration_ms": self.duration_ms,
            "attributes": self.attributes,
            "events": self.events,
            "input": self.input,
            "output": self.output,
            "error": self.error,
            "tokens": self.tokens,
            "cost": self.cost,
        }

    def __repr__(self) -> str:
        return f"<Span(id={self.id}, name='{self.name}')>"


class CuratedLabel(Base):
    """User-applied labels and annotations for traces."""

    __tablename__ = "curated_labels"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    trace_id = Column(String(64), ForeignKey("traces.id"), nullable=False, unique=True)
    label = Column(String(50), nullable=True, index=True)
    quality_score = Column(Float, nullable=True)
    notes = Column(Text, nullable=True)
    exported = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), onupdate=lambda: datetime.now(timezone.utc))

    def __repr__(self) -> str:
        return f"<CuratedLabel(trace_id={self.trace_id}, label='{self.label}')>"


class ProjectApiKey(Base):
    """Additional per-project API keys with scoped permissions."""

    __tablename__ = "project_api_keys"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id"),
        nullable=False,
        index=True,
    )
    name = Column(String(100), nullable=False)
    key_hash = Column(String(64), unique=True, index=True, nullable=False)
    key_fingerprint = Column(String(12), index=True, nullable=False)
    scopes = Column(JSON, default=list, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), onupdate=lambda: datetime.now(timezone.utc))

    project = relationship("Project", back_populates="api_keys")

    def __repr__(self) -> str:
        return (
            f"<ProjectApiKey(project_id={self.project_id}, "
            f"fingerprint={self.key_fingerprint}, scopes={self.scopes})>"
        )


class ProjectBudget(Base):
    """Per-project monthly budget settings."""

    __tablename__ = "project_budgets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id"),
        nullable=False,
        unique=True,
        index=True,
    )
    monthly_token_limit = Column(Integer, nullable=True)
    monthly_cost_limit = Column(Float, nullable=True)
    alert_threshold_percent = Column(Float, default=80.0, nullable=False)
    hard_stop_enabled = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), onupdate=lambda: datetime.now(timezone.utc))

    project = relationship("Project", back_populates="budget")

    def __repr__(self) -> str:
        return (
            f"<ProjectBudget(project_id={self.project_id}, "
            f"token_limit={self.monthly_token_limit}, cost_limit={self.monthly_cost_limit})>"
        )


class ProjectAlertRule(Base):
    """Per-project alert rule for quality, reliability, and cost SLOs."""

    __tablename__ = "project_alert_rules"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id"),
        nullable=False,
        index=True,
    )
    name = Column(String(120), nullable=False)
    metric = Column(String(40), nullable=False)
    operator = Column(String(10), nullable=False)
    threshold = Column(Float, nullable=False)
    window_days = Column(Integer, default=7, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    last_triggered_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), onupdate=lambda: datetime.now(timezone.utc))

    project = relationship("Project", back_populates="alert_rules")

    def __repr__(self) -> str:
        return (
            f"<ProjectAlertRule(project_id={self.project_id}, metric={self.metric}, "
            f"operator={self.operator}, threshold={self.threshold})>"
        )
