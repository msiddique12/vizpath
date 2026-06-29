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
    alert_destinations = relationship(
        "ProjectAlertDestination",
        back_populates="project",
        cascade="all, delete-orphan",
    )
    alert_events = relationship(
        "ProjectAlertEvent",
        back_populates="project",
        cascade="all, delete-orphan",
    )
    redaction_policy = relationship(
        "ProjectRedactionPolicy",
        back_populates="project",
        uselist=False,
        cascade="all, delete-orphan",
    )
    sensitive_findings = relationship(
        "SensitiveSpanFinding",
        back_populates="project",
        cascade="all, delete-orphan",
    )
    trace_search_documents = relationship(
        "TraceSearchDocument",
        back_populates="project",
        cascade="all, delete-orphan",
    )
    regression_watch_results = relationship(
        "RegressionWatchResult",
        back_populates="project",
        cascade="all, delete-orphan",
    )
    triage_items = relationship(
        "TriageItem",
        back_populates="project",
        cascade="all, delete-orphan",
    )
    eval_suites = relationship(
        "EvalSuite",
        back_populates="project",
        cascade="all, delete-orphan",
    )
    dataset_builds = relationship(
        "DatasetBuild",
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


class ProjectRedactionPolicy(Base):
    """Per-project sensitive data redaction policy."""

    __tablename__ = "project_redaction_policies"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id"),
        nullable=False,
        unique=True,
        index=True,
    )
    mode = Column(String(40), default="audit_only", nullable=False)
    rules = Column(JSON, default=dict, nullable=False)
    enabled = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), onupdate=lambda: datetime.now(timezone.utc))

    project = relationship("Project", back_populates="redaction_policy")

    def __repr__(self) -> str:
        return f"<ProjectRedactionPolicy(project_id={self.project_id}, mode={self.mode})>"


class SensitiveSpanFinding(Base):
    """Sensitive-data finding detected while scanning span payloads."""

    __tablename__ = "sensitive_span_findings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id"),
        nullable=False,
        index=True,
    )
    trace_id = Column(String(64), ForeignKey("traces.id"), nullable=False, index=True)
    span_id = Column(String(64), ForeignKey("spans.id"), nullable=True, index=True)
    field_path = Column(String(512), nullable=False)
    rule_id = Column(String(80), nullable=False, index=True)
    severity = Column(String(20), nullable=False, index=True)
    action = Column(String(40), nullable=False)
    value_fingerprint = Column(String(24), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    project = relationship("Project", back_populates="sensitive_findings")
    trace = relationship("Trace")
    span = relationship("Span")

    __table_args__ = (
        Index("ix_sensitive_findings_project_created", "project_id", "created_at"),
        Index("ix_sensitive_findings_project_trace", "project_id", "trace_id"),
        Index("ix_sensitive_findings_project_severity_created", "project_id", "severity", "created_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<SensitiveSpanFinding(project_id={self.project_id}, trace_id={self.trace_id}, "
            f"rule_id={self.rule_id})>"
        )


class TraceSearchDocument(Base):
    """Redacted searchable document for one trace."""

    __tablename__ = "trace_search_documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id"),
        nullable=False,
        index=True,
    )
    trace_id = Column(String(64), ForeignKey("traces.id"), nullable=False, index=True)
    document_text = Column(Text, nullable=False)
    metadata_facets = Column(JSON, default=dict, nullable=False)
    span_facets = Column(JSON, default=dict, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), onupdate=lambda: datetime.now(timezone.utc))

    project = relationship("Project", back_populates="trace_search_documents")
    trace = relationship("Trace")

    __table_args__ = (
        Index("ix_search_documents_project_updated", "project_id", "updated_at"),
        Index("ix_search_documents_project_trace", "project_id", "trace_id", unique=True),
    )

    def __repr__(self) -> str:
        return f"<TraceSearchDocument(project_id={self.project_id}, trace_id={self.trace_id})>"


class RegressionWatchResult(Base):
    """Durable automatic regression comparison result for one trace."""

    __tablename__ = "regression_watch_results"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id"),
        nullable=False,
        index=True,
    )
    trace_id = Column(String(64), ForeignKey("traces.id"), nullable=False, index=True)
    baseline_trace_id = Column(String(64), ForeignKey("traces.id"), nullable=True, index=True)
    group_key = Column(String(80), nullable=False, index=True)
    group_value = Column(String(255), nullable=False, index=True)
    status = Column(String(40), nullable=False, index=True)
    risk_score = Column(Integer, default=0, nullable=False)
    risk_level = Column(String(20), nullable=False, index=True)
    signals = Column(JSON, default=list, nullable=False)
    metrics = Column(JSON, default=dict, nullable=False)
    top_actions = Column(JSON, default=list, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), onupdate=lambda: datetime.now(timezone.utc))

    project = relationship("Project", back_populates="regression_watch_results")
    trace = relationship("Trace", foreign_keys=[trace_id])
    baseline_trace = relationship("Trace", foreign_keys=[baseline_trace_id])

    __table_args__ = (
        Index("ix_regression_watch_project_created", "project_id", "created_at"),
        Index("ix_regression_watch_project_risk_created", "project_id", "risk_level", "created_at"),
        Index("ix_regression_watch_project_trace", "project_id", "trace_id", unique=True),
    )

    def __repr__(self) -> str:
        return (
            f"<RegressionWatchResult(project_id={self.project_id}, trace_id={self.trace_id}, "
            f"risk_level={self.risk_level})>"
        )


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


class TriageItem(Base):
    """Durable workflow item for failed or risky traces."""

    __tablename__ = "triage_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id"),
        nullable=False,
        index=True,
    )
    trace_id = Column(String(64), ForeignKey("traces.id"), nullable=False, index=True)
    status = Column(String(20), default="open", nullable=False, index=True)
    priority = Column(String(20), default="medium", nullable=False, index=True)
    owner = Column(String(120), nullable=True, index=True)
    failure_mode = Column(String(120), nullable=True, index=True)
    title = Column(String(255), nullable=False)
    notes = Column(Text, nullable=True)
    linked_trace_ids = Column(JSON, default=list, nullable=False)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    resolved_by = Column(String(120), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), onupdate=lambda: datetime.now(timezone.utc))

    project = relationship("Project", back_populates="triage_items")
    trace = relationship("Trace")

    __table_args__ = (
        Index("ix_triage_project_status_created", "project_id", "status", "created_at"),
        Index("ix_triage_project_trace", "project_id", "trace_id", unique=True),
    )

    def __repr__(self) -> str:
        return (
            f"<TriageItem(project_id={self.project_id}, trace_id={self.trace_id}, "
            f"status={self.status})>"
        )


class EvalSuite(Base):
    """Saved deterministic eval suite generated from traces."""

    __tablename__ = "eval_suites"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id"),
        nullable=False,
        index=True,
    )
    name = Column(String(120), nullable=False)
    assertion_profile = Column(String(40), nullable=False)
    source_trace_ids = Column(JSON, default=list, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), onupdate=lambda: datetime.now(timezone.utc))

    project = relationship("Project", back_populates="eval_suites")
    cases = relationship("EvalCase", back_populates="suite", cascade="all, delete-orphan")
    runs = relationship("EvalRun", back_populates="suite", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_eval_suites_project_created", "project_id", "created_at"),
    )


class EvalCase(Base):
    """Saved eval case within a suite."""

    __tablename__ = "eval_cases"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    suite_id = Column(UUID(as_uuid=True), ForeignKey("eval_suites.id"), nullable=False, index=True)
    source_trace_id = Column(String(64), ForeignKey("traces.id"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    input = Column(JSON, nullable=True)
    expected_output = Column(JSON, nullable=True)
    baseline_metrics = Column(JSON, default=dict, nullable=False)
    assertions = Column(JSON, default=list, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    suite = relationship("EvalSuite", back_populates="cases")
    source_trace = relationship("Trace")
    results = relationship("EvalCaseResult", back_populates="case", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_eval_cases_suite_trace", "suite_id", "source_trace_id"),
    )


class EvalRun(Base):
    """Saved eval run against candidate traces."""

    __tablename__ = "eval_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    suite_id = Column(UUID(as_uuid=True), ForeignKey("eval_suites.id"), nullable=False, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False, index=True)
    name = Column(String(120), nullable=False)
    candidate_trace_ids = Column(JSON, default=list, nullable=False)
    passed = Column(Boolean, default=False, nullable=False)
    pass_count = Column(Integer, default=0, nullable=False)
    fail_count = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    suite = relationship("EvalSuite", back_populates="runs")
    results = relationship("EvalCaseResult", back_populates="run", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_eval_runs_project_created", "project_id", "created_at"),
        Index("ix_eval_runs_suite_created", "suite_id", "created_at"),
    )


class EvalCaseResult(Base):
    """Result for one eval case in one run."""

    __tablename__ = "eval_case_results"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id = Column(UUID(as_uuid=True), ForeignKey("eval_runs.id"), nullable=False, index=True)
    case_id = Column(UUID(as_uuid=True), ForeignKey("eval_cases.id"), nullable=False, index=True)
    candidate_trace_id = Column(String(64), ForeignKey("traces.id"), nullable=False, index=True)
    passed = Column(Boolean, default=False, nullable=False)
    metrics = Column(JSON, default=dict, nullable=False)
    assertion_results = Column(JSON, default=list, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    run = relationship("EvalRun", back_populates="results")
    case = relationship("EvalCase", back_populates="results")
    candidate_trace = relationship("Trace")

    __table_args__ = (
        Index("ix_eval_results_run_case", "run_id", "case_id"),
    )


class DatasetBuild(Base):
    """Saved redacted dataset artifact generated from traces."""

    __tablename__ = "dataset_builds"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id"),
        nullable=False,
        index=True,
    )
    name = Column(String(120), nullable=False)
    format = Column(String(40), nullable=False, index=True)
    source_trace_ids = Column(JSON, default=list, nullable=False)
    options = Column(JSON, default=dict, nullable=False)
    record_count = Column(Integer, default=0, nullable=False)
    skipped_count = Column(Integer, default=0, nullable=False)
    redaction_mode = Column(String(40), default="redacted", nullable=False)
    artifact = Column(JSON, default=dict, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    project = relationship("Project", back_populates="dataset_builds")

    __table_args__ = (
        Index("ix_dataset_builds_project_created", "project_id", "created_at"),
    )


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
    notification_cooldown_minutes = Column(Integer, default=60, nullable=False)
    last_triggered_at = Column(DateTime(timezone=True), nullable=True)
    last_notified_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), onupdate=lambda: datetime.now(timezone.utc))

    project = relationship("Project", back_populates="alert_rules")
    alert_events = relationship("ProjectAlertEvent", back_populates="rule")

    def __repr__(self) -> str:
        return (
            f"<ProjectAlertRule(project_id={self.project_id}, metric={self.metric}, "
            f"operator={self.operator}, threshold={self.threshold})>"
        )


class ProjectAlertDestination(Base):
    """Per-project destination for alert notifications."""

    __tablename__ = "project_alert_destinations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id"),
        nullable=False,
        index=True,
    )
    name = Column(String(120), nullable=False)
    kind = Column(String(20), nullable=False, default="webhook")
    target_url = Column(String(512), nullable=False)
    secret_token = Column(String(255), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), onupdate=lambda: datetime.now(timezone.utc))

    project = relationship("Project", back_populates="alert_destinations")
    alert_events = relationship("ProjectAlertEvent", back_populates="destination")

    __table_args__ = (
        Index("ix_alert_destinations_project_active", "project_id", "is_active"),
    )

    def __repr__(self) -> str:
        return (
            f"<ProjectAlertDestination(project_id={self.project_id}, name={self.name}, "
            f"kind={self.kind}, active={self.is_active})>"
        )


class ProjectAlertEvent(Base):
    """Per-project alert event history for rule breaches and deliveries."""

    __tablename__ = "project_alert_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id"),
        nullable=False,
        index=True,
    )
    rule_id = Column(
        UUID(as_uuid=True),
        ForeignKey("project_alert_rules.id"),
        nullable=True,
        index=True,
    )
    destination_id = Column(
        UUID(as_uuid=True),
        ForeignKey("project_alert_destinations.id"),
        nullable=True,
        index=True,
    )
    replay_source_event_id = Column(
        UUID(as_uuid=True),
        ForeignKey("project_alert_events.id"),
        nullable=True,
        index=True,
    )
    event_type = Column(String(40), nullable=False, index=True)
    rule_name = Column(String(120), nullable=True)
    metric = Column(String(40), nullable=True)
    operator = Column(String(10), nullable=True)
    threshold = Column(Float, nullable=True)
    current_value = Column(Float, nullable=True)
    message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    project = relationship("Project", back_populates="alert_events")
    rule = relationship("ProjectAlertRule", back_populates="alert_events")
    destination = relationship("ProjectAlertDestination", back_populates="alert_events")

    __table_args__ = (
        Index("ix_alert_events_project_created", "project_id", "created_at"),
        Index("ix_alert_events_project_type_created", "project_id", "event_type", "created_at"),
        Index("ix_alert_events_project_rule_created", "project_id", "rule_id", "created_at"),
        Index(
            "ix_alert_events_project_source_created",
            "project_id",
            "replay_source_event_id",
            "created_at",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<ProjectAlertEvent(project_id={self.project_id}, event_type={self.event_type}, "
            f"rule_id={self.rule_id}, destination_id={self.destination_id})>"
        )
