"""add triage items

Revision ID: 42f7f8f4b9d1
Revises: e6950a93fdb1
Create Date: 2026-06-22 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "42f7f8f4b9d1"
down_revision: Union[str, Sequence[str], None] = "e6950a93fdb1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "triage_items",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("trace_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("priority", sa.String(length=20), nullable=False),
        sa.Column("owner", sa.String(length=120), nullable=True),
        sa.Column("failure_mode", sa.String(length=120), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("linked_trace_ids", sa.JSON(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["trace_id"], ["traces.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_triage_project_status_created", "triage_items", ["project_id", "status", "created_at"])
    op.create_index("ix_triage_project_trace", "triage_items", ["project_id", "trace_id"], unique=True)
    op.create_index(op.f("ix_triage_items_failure_mode"), "triage_items", ["failure_mode"])
    op.create_index(op.f("ix_triage_items_owner"), "triage_items", ["owner"])
    op.create_index(op.f("ix_triage_items_priority"), "triage_items", ["priority"])
    op.create_index(op.f("ix_triage_items_project_id"), "triage_items", ["project_id"])
    op.create_index(op.f("ix_triage_items_status"), "triage_items", ["status"])
    op.create_index(op.f("ix_triage_items_trace_id"), "triage_items", ["trace_id"])



def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_triage_items_trace_id"), table_name="triage_items")
    op.drop_index(op.f("ix_triage_items_status"), table_name="triage_items")
    op.drop_index(op.f("ix_triage_items_project_id"), table_name="triage_items")
    op.drop_index(op.f("ix_triage_items_priority"), table_name="triage_items")
    op.drop_index(op.f("ix_triage_items_owner"), table_name="triage_items")
    op.drop_index(op.f("ix_triage_items_failure_mode"), table_name="triage_items")
    op.drop_index("ix_triage_project_trace", table_name="triage_items")
    op.drop_index("ix_triage_project_status_created", table_name="triage_items")
    op.drop_table("triage_items")
