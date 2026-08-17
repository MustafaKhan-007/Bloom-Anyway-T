"""Add Full Bloom membership support and healing_access on videos.

Revision ID: y5h3c4d5e6f7
Revises: x4g2b3c4d5e6
Create Date: 2026-08-17
"""
from alembic import op
import sqlalchemy as sa


revision = "y5h3c4d5e6f7"
down_revision = "x4g2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("videos") as batch_op:
        batch_op.add_column(sa.Column(
            "healing_access", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    with op.batch_alter_table("videos") as batch_op:
        batch_op.drop_column("healing_access")
