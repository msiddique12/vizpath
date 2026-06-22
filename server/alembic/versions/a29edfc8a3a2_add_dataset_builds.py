"""add dataset builds

Revision ID: a29edfc8a3a2
Revises: 7b33a4f6ed7b
Create Date: 2026-06-22 00:10:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a29edfc8a3a2"
down_revision: Union[str, Sequence[str], None] = "7b33a4f6ed7b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "dataset_builds",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("format", sa.String(length=40), nullable=False),
        sa.Column("source_trace_ids", sa.JSON(), nullable=False),
        sa.Column("options", sa.JSON(), nullable=False),
        sa.Column("record_count", sa.Integer(), nullable=False),
        sa.Column("skipped_count", sa.Integer(), nullable=False),
        sa.Column("redaction_mode", sa.String(length=40), nullable=False),
        sa.Column("artifact", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_dataset_builds_project_created", "dataset_builds", ["project_id", "created_at"])
    op.create_index(op.f("ix_dataset_builds_format"), "dataset_builds", ["format"])
    op.create_index(op.f("ix_dataset_builds_project_id"), "dataset_builds", ["project_id"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_dataset_builds_project_id"), table_name="dataset_builds")
    op.drop_index(op.f("ix_dataset_builds_format"), table_name="dataset_builds")
    op.drop_index("ix_dataset_builds_project_created", table_name="dataset_builds")
    op.drop_table("dataset_builds")
