"""Add timezone preference column on users.

Revision ID: i9d7e8f9a0b1
Revises: h8c6d7e8f9a0
"""
from alembic import op
import sqlalchemy as sa


revision = "i9d7e8f9a0b1"
down_revision = "h8c6d7e8f9a0"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("timezone", sa.String(length=64), nullable=True))


def downgrade():
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("timezone")
