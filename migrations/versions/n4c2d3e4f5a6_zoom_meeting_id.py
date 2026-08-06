"""Store Zoom meeting id for support-group sessions.

Revision ID: n4c2d3e4f5a6
Revises: m3b1c2d3e4f5
"""
from alembic import op
import sqlalchemy as sa


revision = "n4c2d3e4f5a6"
down_revision = "m3b1c2d3e4f5"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("support_group_meetings") as batch:
        batch.add_column(sa.Column("zoom_meeting_id", sa.String(length=64), nullable=True))


def downgrade():
    with op.batch_alter_table("support_group_meetings") as batch:
        batch.drop_column("zoom_meeting_id")
