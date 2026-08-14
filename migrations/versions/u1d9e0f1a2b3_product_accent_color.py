"""Per-product card accent colour.

Revision ID: u1d9e0f1a2b3
Revises: t0c8d9e0f1a2
"""
from alembic import op
import sqlalchemy as sa


revision = "u1d9e0f1a2b3"
down_revision = "t0c8d9e0f1a2"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("products") as batch:
        batch.add_column(sa.Column("accent_color", sa.String(length=7), nullable=True))


def downgrade():
    with op.batch_alter_table("products") as batch:
        batch.drop_column("accent_color")
