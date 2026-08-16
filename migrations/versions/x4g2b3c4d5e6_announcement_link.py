"""Optional link URL on announcements.

Revision ID: x4g2b3c4d5e6
Revises: w3f1a2b3c4d5
"""
from alembic import op
import sqlalchemy as sa


revision = "x4g2b3c4d5e6"
down_revision = "w3f1a2b3c4d5"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("announcements") as batch:
        batch.add_column(sa.Column("link_url", sa.String(length=500), nullable=True))


def downgrade():
    with op.batch_alter_table("announcements") as batch:
        batch.drop_column("link_url")
