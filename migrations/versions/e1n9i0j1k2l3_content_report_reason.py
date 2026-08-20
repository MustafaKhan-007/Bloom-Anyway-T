"""Content reports: reason field + user (peer session) targets.

Revision ID: e1n9i0j1k2l3
Revises: d0m8h9i0j1k2
Create Date: 2026-08-20
"""
from alembic import op
import sqlalchemy as sa


revision = "e1n9i0j1k2l3"
down_revision = "d0m8h9i0j1k2"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("content_reports") as batch:
        batch.add_column(sa.Column("reason", sa.String(length=80), nullable=True))


def downgrade():
    with op.batch_alter_table("content_reports") as batch:
        batch.drop_column("reason")
