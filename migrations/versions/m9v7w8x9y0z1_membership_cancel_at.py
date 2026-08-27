"""Add membership_cancel_at for period-end cancel UX.

Revision ID: m9v7w8x9y0z1
Revises: l8u6v7w8x9y0
"""
import sqlalchemy as sa
from alembic import op


revision = "m9v7w8x9y0z1"
down_revision = "l8u6v7w8x9y0"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("membership_cancel_at", sa.DateTime(), nullable=True))


def downgrade():
    with op.batch_alter_table("users") as batch:
        batch.drop_column("membership_cancel_at")
