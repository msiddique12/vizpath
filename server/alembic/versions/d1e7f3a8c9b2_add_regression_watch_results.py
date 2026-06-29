"""add regression watch results

Revision ID: d1e7f3a8c9b2
Revises: c0d5e2f6b4a1
Create Date: 2026-06-24 00:30:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d1e7f3a8c9b2"
down_revision: Union[str, Sequence[str], None] = "c0d5e2f6b4a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "regression_watch_results",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("trace_id", sa.String(length=64), nullable=False),
        sa.Column("baseline_trace_id", sa.String(length=64), nullable=True),
        sa.Column("group_key", sa.String(length=80), nullable=False),
        sa.Column("group_value", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("risk_score", sa.Integer(), nullable=False),
        sa.Column("risk_level", sa.String(length=20), nullable=False),
        sa.Column("signals", sa.JSON(), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("top_actions", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["baseline_trace_id"], ["traces.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["trace_id"], ["traces.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_regression_watch_project_created",
        "regression_watch_results",
        ["project_id", "created_at"],
    )
    op.create_index(
        "ix_regression_watch_project_risk_created",
        "regression_watch_results",
        ["project_id", "risk_level", "created_at"],
    )
    op.create_index(
        "ix_regression_watch_project_trace",
        "regression_watch_results",
        ["project_id", "trace_id"],
        unique=True,
    )
    op.create_index(op.f("ix_regression_watch_results_baseline_trace_id"), "regression_watch_results", ["baseline_trace_id"])
    op.create_index(op.f("ix_regression_watch_results_group_key"), "regression_watch_results", ["group_key"])
    op.create_index(op.f("ix_regression_watch_results_group_value"), "regression_watch_results", ["group_value"])
    op.create_index(op.f("ix_regression_watch_results_project_id"), "regression_watch_results", ["project_id"])
    op.create_index(op.f("ix_regression_watch_results_risk_level"), "regression_watch_results", ["risk_level"])
    op.create_index(op.f("ix_regression_watch_results_status"), "regression_watch_results", ["status"])
    op.create_index(op.f("ix_regression_watch_results_trace_id"), "regression_watch_results", ["trace_id"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_regression_watch_results_trace_id"), table_name="regression_watch_results")
    op.drop_index(op.f("ix_regression_watch_results_status"), table_name="regression_watch_results")
    op.drop_index(op.f("ix_regression_watch_results_risk_level"), table_name="regression_watch_results")
    op.drop_index(op.f("ix_regression_watch_results_project_id"), table_name="regression_watch_results")
    op.drop_index(op.f("ix_regression_watch_results_group_value"), table_name="regression_watch_results")
    op.drop_index(op.f("ix_regression_watch_results_group_key"), table_name="regression_watch_results")
    op.drop_index(op.f("ix_regression_watch_results_baseline_trace_id"), table_name="regression_watch_results")
    op.drop_index("ix_regression_watch_project_trace", table_name="regression_watch_results")
    op.drop_index("ix_regression_watch_project_risk_created", table_name="regression_watch_results")
    op.drop_index("ix_regression_watch_project_created", table_name="regression_watch_results")
    op.drop_table("regression_watch_results")
