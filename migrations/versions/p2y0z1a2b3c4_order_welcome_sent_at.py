"""Add welcome_sent_at on orders for membership welcome idempotency.

Revision ID: p2y0z1a2b3c4
Revises: o1x9y0z1a2b3
"""
import sqlalchemy as sa
from alembic import op


revision = "p2y0z1a2b3c4"
down_revision = "o1x9y0z1a2b3"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("orders") as batch:
        batch.add_column(sa.Column("welcome_sent_at", sa.DateTime(), nullable=True))


def downgrade():
    with op.batch_alter_table("orders") as batch:
        batch.drop_column("welcome_sent_at")
