"""add replay source event id to alert events

Revision ID: e6950a93fdb1
Revises: 6e88584b4849
Create Date: 2026-04-09 20:56:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "e6950a93fdb1"
down_revision: Union[str, Sequence[str], None] = "6e88584b4849"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("project_alert_events", schema=None) as batch_op:
        batch_op.add_column(sa.Column("replay_source_event_id", sa.UUID(), nullable=True))
        batch_op.create_index(
            "ix_project_alert_events_replay_source_event_id",
            ["replay_source_event_id"],
            unique=False,
        )
        batch_op.create_index(
            "ix_alert_events_project_source_created",
            ["project_id", "replay_source_event_id", "created_at"],
            unique=False,
        )
        batch_op.create_foreign_key(
            "fk_project_alert_events_replay_source_event_id",
            "project_alert_events",
            ["replay_source_event_id"],
            ["id"],
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("project_alert_events", schema=None) as batch_op:
        batch_op.drop_constraint(
            "fk_project_alert_events_replay_source_event_id",
            type_="foreignkey",
        )
        batch_op.drop_index("ix_alert_events_project_source_created")
        batch_op.drop_index("ix_project_alert_events_replay_source_event_id")
        batch_op.drop_column("replay_source_event_id")
