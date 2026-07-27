"""Add url column to notifications for non-forum deep links.

Revision ID: g7b5c6d7e8f9
Revises: f6a3b4c5d6e7
"""
from alembic import op
import sqlalchemy as sa


revision = "g7b5c6d7e8f9"
down_revision = "f6a3b4c5d6e7"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("notifications", schema=None) as batch_op:
        batch_op.add_column(sa.Column("url", sa.String(length=300), nullable=True))


def downgrade():
    with op.batch_alter_table("notifications", schema=None) as batch_op:
        batch_op.drop_column("url")
