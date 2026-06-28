"""add redaction policies

Revision ID: b8c4e1f2a9d3
Revises: a29edfc8a3a2
Create Date: 2026-06-24 00:10:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b8c4e1f2a9d3"
down_revision: Union[str, Sequence[str], None] = "a29edfc8a3a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "project_redaction_policies",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("mode", sa.String(length=40), nullable=False),
        sa.Column("rules", sa.JSON(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id"),
    )
    op.create_index(
        op.f("ix_project_redaction_policies_project_id"),
        "project_redaction_policies",
        ["project_id"],
    )

    op.create_table(
        "sensitive_span_findings",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("trace_id", sa.String(length=64), nullable=False),
        sa.Column("span_id", sa.String(length=64), nullable=True),
        sa.Column("field_path", sa.String(length=512), nullable=False),
        sa.Column("rule_id", sa.String(length=80), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("action", sa.String(length=40), nullable=False),
        sa.Column("value_fingerprint", sa.String(length=24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["span_id"], ["spans.id"]),
        sa.ForeignKeyConstraint(["trace_id"], ["traces.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_sensitive_findings_project_created",
        "sensitive_span_findings",
        ["project_id", "created_at"],
    )
    op.create_index(
        "ix_sensitive_findings_project_trace",
        "sensitive_span_findings",
        ["project_id", "trace_id"],
    )
    op.create_index(
        "ix_sensitive_findings_project_severity_created",
        "sensitive_span_findings",
        ["project_id", "severity", "created_at"],
    )
    op.create_index(
        op.f("ix_sensitive_span_findings_action"),
        "sensitive_span_findings",
        ["action"],
    )
    op.create_index(
        op.f("ix_sensitive_span_findings_project_id"),
        "sensitive_span_findings",
        ["project_id"],
    )
    op.create_index(
        op.f("ix_sensitive_span_findings_rule_id"),
        "sensitive_span_findings",
        ["rule_id"],
    )
    op.create_index(
        op.f("ix_sensitive_span_findings_severity"),
        "sensitive_span_findings",
        ["severity"],
    )
    op.create_index(
        op.f("ix_sensitive_span_findings_span_id"),
        "sensitive_span_findings",
        ["span_id"],
    )
    op.create_index(
        op.f("ix_sensitive_span_findings_trace_id"),
        "sensitive_span_findings",
        ["trace_id"],
    )
    op.create_index(
        op.f("ix_sensitive_span_findings_value_fingerprint"),
        "sensitive_span_findings",
        ["value_fingerprint"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_sensitive_span_findings_value_fingerprint"), table_name="sensitive_span_findings")
    op.drop_index(op.f("ix_sensitive_span_findings_trace_id"), table_name="sensitive_span_findings")
    op.drop_index(op.f("ix_sensitive_span_findings_span_id"), table_name="sensitive_span_findings")
    op.drop_index(op.f("ix_sensitive_span_findings_severity"), table_name="sensitive_span_findings")
    op.drop_index(op.f("ix_sensitive_span_findings_rule_id"), table_name="sensitive_span_findings")
    op.drop_index(op.f("ix_sensitive_span_findings_project_id"), table_name="sensitive_span_findings")
    op.drop_index(op.f("ix_sensitive_span_findings_action"), table_name="sensitive_span_findings")
    op.drop_index("ix_sensitive_findings_project_severity_created", table_name="sensitive_span_findings")
    op.drop_index("ix_sensitive_findings_project_trace", table_name="sensitive_span_findings")
    op.drop_index("ix_sensitive_findings_project_created", table_name="sensitive_span_findings")
    op.drop_table("sensitive_span_findings")
    op.drop_index(op.f("ix_project_redaction_policies_project_id"), table_name="project_redaction_policies")
    op.drop_table("project_redaction_policies")
