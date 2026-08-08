"""Mood on journal entries (daily check-in scale).

Revision ID: r8a6b7c8d9e0
Revises: q7f5a6b7c8d9
"""
from alembic import op
import sqlalchemy as sa


revision = "r8a6b7c8d9e0"
down_revision = "q7f5a6b7c8d9"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("journal_entries") as batch:
        batch.add_column(sa.Column("mood", sa.String(length=20), nullable=True))


def downgrade():
    with op.batch_alter_table("journal_entries") as batch:
        batch.drop_column("mood")
