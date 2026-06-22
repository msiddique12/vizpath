"""add eval suites

Revision ID: 7b33a4f6ed7b
Revises: 42f7f8f4b9d1
Create Date: 2026-06-22 00:05:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "7b33a4f6ed7b"
down_revision: Union[str, Sequence[str], None] = "42f7f8f4b9d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "eval_suites",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("assertion_profile", sa.String(length=40), nullable=False),
        sa.Column("source_trace_ids", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_eval_suites_project_created", "eval_suites", ["project_id", "created_at"])
    op.create_index(op.f("ix_eval_suites_project_id"), "eval_suites", ["project_id"])

    op.create_table(
        "eval_cases",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("suite_id", sa.UUID(), nullable=False),
        sa.Column("source_trace_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("input", sa.JSON(), nullable=True),
        sa.Column("expected_output", sa.JSON(), nullable=True),
        sa.Column("baseline_metrics", sa.JSON(), nullable=False),
        sa.Column("assertions", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["source_trace_id"], ["traces.id"]),
        sa.ForeignKeyConstraint(["suite_id"], ["eval_suites.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_eval_cases_suite_trace", "eval_cases", ["suite_id", "source_trace_id"])
    op.create_index(op.f("ix_eval_cases_source_trace_id"), "eval_cases", ["source_trace_id"])
    op.create_index(op.f("ix_eval_cases_suite_id"), "eval_cases", ["suite_id"])

    op.create_table(
        "eval_runs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("suite_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("candidate_trace_ids", sa.JSON(), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("pass_count", sa.Integer(), nullable=False),
        sa.Column("fail_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["suite_id"], ["eval_suites.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_eval_runs_project_created", "eval_runs", ["project_id", "created_at"])
    op.create_index("ix_eval_runs_suite_created", "eval_runs", ["suite_id", "created_at"])
    op.create_index(op.f("ix_eval_runs_project_id"), "eval_runs", ["project_id"])
    op.create_index(op.f("ix_eval_runs_suite_id"), "eval_runs", ["suite_id"])

    op.create_table(
        "eval_case_results",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("case_id", sa.UUID(), nullable=False),
        sa.Column("candidate_trace_id", sa.String(length=64), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("assertion_results", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["candidate_trace_id"], ["traces.id"]),
        sa.ForeignKeyConstraint(["case_id"], ["eval_cases.id"]),
        sa.ForeignKeyConstraint(["run_id"], ["eval_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_eval_results_run_case", "eval_case_results", ["run_id", "case_id"])
    op.create_index(op.f("ix_eval_case_results_candidate_trace_id"), "eval_case_results", ["candidate_trace_id"])
    op.create_index(op.f("ix_eval_case_results_case_id"), "eval_case_results", ["case_id"])
    op.create_index(op.f("ix_eval_case_results_run_id"), "eval_case_results", ["run_id"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_eval_case_results_run_id"), table_name="eval_case_results")
    op.drop_index(op.f("ix_eval_case_results_case_id"), table_name="eval_case_results")
    op.drop_index(op.f("ix_eval_case_results_candidate_trace_id"), table_name="eval_case_results")
    op.drop_index("ix_eval_results_run_case", table_name="eval_case_results")
    op.drop_table("eval_case_results")
    op.drop_index(op.f("ix_eval_runs_suite_id"), table_name="eval_runs")
    op.drop_index(op.f("ix_eval_runs_project_id"), table_name="eval_runs")
    op.drop_index("ix_eval_runs_suite_created", table_name="eval_runs")
    op.drop_index("ix_eval_runs_project_created", table_name="eval_runs")
    op.drop_table("eval_runs")
    op.drop_index(op.f("ix_eval_cases_suite_id"), table_name="eval_cases")
    op.drop_index(op.f("ix_eval_cases_source_trace_id"), table_name="eval_cases")
    op.drop_index("ix_eval_cases_suite_trace", table_name="eval_cases")
    op.drop_table("eval_cases")
    op.drop_index(op.f("ix_eval_suites_project_id"), table_name="eval_suites")
    op.drop_index("ix_eval_suites_project_created", table_name="eval_suites")
    op.drop_table("eval_suites")
