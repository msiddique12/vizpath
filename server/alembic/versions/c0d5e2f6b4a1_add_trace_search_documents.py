"""add trace search documents

Revision ID: c0d5e2f6b4a1
Revises: b8c4e1f2a9d3
Create Date: 2026-06-24 00:20:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c0d5e2f6b4a1"
down_revision: Union[str, Sequence[str], None] = "b8c4e1f2a9d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "trace_search_documents",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("trace_id", sa.String(length=64), nullable=False),
        sa.Column("document_text", sa.Text(), nullable=False),
        sa.Column("metadata_facets", sa.JSON(), nullable=False),
        sa.Column("span_facets", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["trace_id"], ["traces.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_search_documents_project_trace",
        "trace_search_documents",
        ["project_id", "trace_id"],
        unique=True,
    )
    op.create_index(
        "ix_search_documents_project_updated",
        "trace_search_documents",
        ["project_id", "updated_at"],
    )
    op.create_index(
        op.f("ix_trace_search_documents_project_id"),
        "trace_search_documents",
        ["project_id"],
    )
    op.create_index(
        op.f("ix_trace_search_documents_trace_id"),
        "trace_search_documents",
        ["trace_id"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_trace_search_documents_trace_id"), table_name="trace_search_documents")
    op.drop_index(op.f("ix_trace_search_documents_project_id"), table_name="trace_search_documents")
    op.drop_index("ix_search_documents_project_updated", table_name="trace_search_documents")
    op.drop_index("ix_search_documents_project_trace", table_name="trace_search_documents")
    op.drop_table("trace_search_documents")
